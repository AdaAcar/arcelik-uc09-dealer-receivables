"""Dummy dataset for use case 09 · Dealer credit & receivables early warning.

Writes four source tables (dealers, invoices, payments, credit_limits) and one
derived month-end snapshot (dealer_month) to ./data, plus data.js for the
dashboard. All names and figures are invented. Seeded, so reruns are identical.
"""
import csv, json, math, random, datetime as dt
from collections import defaultdict
from pathlib import Path

random.seed(9)
OUT = Path(__file__).parent / "data"
OUT.mkdir(exist_ok=True)

GEN_START = dt.date(2024, 5, 1)            # warm-up so Nov-2024 balances are realistic
SNAP_MONTHS = [(2024 + (10 + i) // 12, (10 + i) % 12 + 1) for i in range(24)]  # Nov-24 .. Oct-26
DATA_END = dt.date(2026, 10, 31)

def month_end(y, m):
    return dt.date(y + m // 12, m % 12 + 1, 1) - dt.timedelta(days=1)

def add_months(y, m, k):
    t = y * 12 + (m - 1) + k
    return t // 12, t % 12 + 1

REGIONS = {
    "Marmara": (38, ["İstanbul"] * 4 + ["Bursa", "Kocaeli", "Tekirdağ", "Balıkesir", "Sakarya"]),
    "Ege": (22, ["İzmir"] * 2 + ["Manisa", "Aydın", "Denizli", "Muğla"]),
    "İç Anadolu": (22, ["Ankara"] * 2 + ["Konya", "Kayseri", "Eskişehir", "Sivas"]),
    "Akdeniz": (20, ["Antalya", "Adana", "Mersin", "Hatay", "Isparta"]),
    "Karadeniz": (16, ["Samsun", "Trabzon", "Ordu", "Zonguldak", "Rize"]),
    "Doğu Anadolu": (10, ["Erzurum", "Malatya", "Elazığ", "Van"]),
    "Güneydoğu Anadolu": (12, ["Gaziantep", "Diyarbakır", "Şanlıurfa", "Mardin"]),
}
# Share of non-reliable payers rises in the east (assumption, not a claim about real dealers)
REGION_RISK = {"Marmara": 0.9, "Ege": 0.9, "İç Anadolu": 1.0, "Akdeniz": 1.1,
               "Karadeniz": 1.0, "Doğu Anadolu": 1.4, "Güneydoğu Anadolu": 1.5}
SURNAMES = ["Yılmaz", "Kaya", "Demir", "Şahin", "Çelik", "Yıldız", "Yıldırım", "Öztürk", "Aydın",
            "Özdemir", "Arslan", "Doğan", "Kılıç", "Aslan", "Çetin", "Kara", "Koç", "Kurt", "Özkan",
            "Şimşek", "Polat", "Korkmaz", "Karaca", "Tekin", "Güneş", "Akın", "Bulut", "Turan",
            "Aksoy", "Ateş", "Keskin", "Ünal", "Güler", "Bozkurt", "Uçar", "Taş", "Avcı", "Sarı", "Işık"]
SUFFIX = ["Elektrik", "Dayanıklı Tüketim", "Ev Aletleri", "Ticaret", "Beyaz Eşya", "Elektronik"]
SEASON = [0.85, 0.85, 0.95, 1.0, 1.1, 1.2, 1.15, 1.0, 1.0, 1.05, 1.2, 1.1]  # Jan..Dec
INFL = 0.022                                  # nominal TRY growth per month (~30%/yr)
PRODUCT = [("Refrigerators", .27), ("Washing machines", .22), ("Dishwashers", .12),
           ("Built-in", .12), ("Air conditioners", .10), ("TV & electronics", .10), ("Small appliances", .07)]

def months_from_start(d):
    return (d.year - 2024) * 12 + d.month - 11   # 0 = Nov-2024

# ---------- dealers ----------
dealers, used = [], set()
did = 0
for region, (n, cities) in REGIONS.items():
    for _ in range(n):
        did += 1
        city = random.choice(cities)
        while True:
            name = f"{random.choice(SURNAMES)} {random.choice(SUFFIX)}"
            if (name, city) not in used:
                used.add((name, city)); break
        tier = random.choices("ABC", [.15, .45, .40])[0]
        r = random.random() / REGION_RISK[region]
        profile = ("reliable" if r < .55 else "slow" if r < .74 else "improving" if r < .80
                   else "deteriorating" if r < .92 else "distressed")
        dealers.append(dict(
            dealer_id=f"D{did:03d}", dealer_name=name, city=city, region=region,
            brand=random.choices(["Arçelik", "Beko"], [.55, .45])[0], tier=tier,
            payment_terms_days=random.choices([60, 90, 120], [.3, .5, .2])[0],
            base=dict(A=random.uniform(9, 16), B=random.uniform(3.5, 7), C=random.uniform(1, 2.5))[tier] * 1e6,
            profile=profile,
            onset=random.randint(13, 19) if profile == "deteriorating" else random.randint(4, 12),
            headroom=random.uniform(1.2, 1.3) if profile == "distressed" else random.uniform(1.55, 1.85),
        ))

def delay_mu(d, k):
    """Mean days paid after due date, for invoice month index k (0 = Nov-24)."""
    p = d["profile"]
    if p == "reliable": return -1
    if p == "slow": return 16
    if p == "distressed": return 70
    if p == "deteriorating": return 2 if k < d["onset"] else min(2 + 8 * (k - d["onset"] + 1), 115)
    if p == "improving": return 38 if k < d["onset"] else max(38 - 6 * (k - d["onset"] + 1), 2)

SD = dict(reliable=4, slow=12, distressed=35, deteriorating=10, improving=10)

# ---------- invoices & payments ----------
invoices, payments, limits = [], [], []
inv_no = pay_no = 0
inv_by_dealer = defaultdict(list)
monthly_sales = defaultdict(float)
paid_by_inv = defaultdict(list)          # invoice_id -> [(date, amount)]
blocked = defaultdict(float)             # (dealer_id, y, m) -> order value held back
cur_limit = {}
REVIEWS = {(2024, 5), (2025, 1), (2025, 7), (2026, 1), (2026, 7)}

def balance(did, day):
    """Unpaid amount of invoices dated before `day`, net of payments before `day`."""
    b = 0.0
    for i in inv_by_dealer[did]:
        if i["invoice_date"] >= day: continue
        b += i["amount_try"] - sum(a for pd, a in paid_by_inv[i["invoice_id"]] if pd < day)
    return b

y, m = GEN_START.year, GEN_START.month
while (y, m) <= (2026, 10):
    k = (y - 2024) * 12 + m - 11
    days = month_end(y, m).day
    first = dt.date(y, m, 1)
    for d in dealers:
        did = d["dealer_id"]
        # credit limit review every January and July (initial limit in May 2024)
        if (y, m) in REVIEWS:
            prev = cur_limit.get(did)
            if prev is None:
                avg = d["base"] * (1 + INFL) ** k * 1.15
            else:
                avg = sum(monthly_sales[(did, *add_months(y, m, -j))] for j in (1, 2, 3)) / 3 * 1.06
            lim = round(avg * d["payment_terms_days"] / 30 * d["headroom"] / 250_000) * 250_000
            reason = "Initial limit" if prev is None else ("H1 review" if m == 1 else "H2 review")
            if prev is not None and ((d["profile"] == "deteriorating" and k >= d["onset"]) or
                                     (d["profile"] == "distressed" and random.random() < .6)):
                lim, reason = prev, "Frozen: payment behaviour"
            limits.append(dict(dealer_id=did, effective_from=first, credit_limit_try=lim, review_reason=reason))
            cur_limit[did] = lim
        target = d["base"] * SEASON[m - 1] * (1 + INFL) ** k * random.uniform(.8, 1.2)
        if d["profile"] == "deteriorating" and k >= d["onset"]:
            target *= 1.15        # keeps ordering while paying slower
        # credit control: the ERP blocks most new orders once a dealer is over its limit
        ratio = balance(did, first) / cur_limit[did]
        wanted = target
        if ratio > 1.05: target *= .05
        elif ratio > .95: target *= .6
        blocked[(did, y, m)] = round(wanted - target, -2)   # orders held back by credit control
        n = dict(A=random.randint(8, 12), B=random.randint(5, 8), C=random.randint(2, 4))[d["tier"]]
        w = [random.uniform(.5, 1.5) for _ in range(n)]
        for wi in w:
            inv_no += 1
            idate = dt.date(y, m, random.randint(1, days))
            amt = round(target * wi / sum(w), -2)
            due = idate + dt.timedelta(days=d["payment_terms_days"])
            inv = dict(invoice_id=f"INV{inv_no:06d}", dealer_id=did, invoice_date=idate, due_date=due, amount_try=amt,
                       product_group=random.choices([p for p, _ in PRODUCT], [w for _, w in PRODUCT])[0])
            invoices.append(inv); inv_by_dealer[did].append(inv); monthly_sales[(did, y, m)] += amt
            # payment behaviour
            if d["profile"] == "distressed" and random.random() < .06:
                continue                                       # never paid
            lag = max(round(random.gauss(delay_mu(d, k), SD[d["profile"]])), -d["payment_terms_days"] + 5)
            p1 = due + dt.timedelta(days=lag)
            p_partial = .35 if d["profile"] in ("slow", "distressed", "deteriorating") else .12
            if random.random() < p_partial:
                part = round(amt * random.uniform(.5, .8), -2)
                parts = [(p1, part), (p1 + dt.timedelta(days=random.randint(15, 60)), amt - part)]
            else:
                parts = [(p1, amt)]
            for pdate, pamt in parts:
                if pdate > DATA_END: continue
                pay_no += 1
                paid_by_inv[inv["invoice_id"]].append((pdate, pamt))
                payments.append(dict(payment_id=f"PAY{pay_no:06d}", invoice_id=inv["invoice_id"],
                                     dealer_id=did, payment_date=pdate, amount_try=pamt,
                                     method=random.choices(["DBS", "Cheque", "Bank transfer"], [.45, .35, .20])[0]))
    y, m = add_months(y, m, 1)


def limit_at(did, day):
    return [l for l in limits if l["dealer_id"] == did and l["effective_from"] <= day][-1]["credit_limit_try"]

rng = random.Random(2026)   # separate stream: collateral and actions don't change invoices or payments

# ---------- collateral (bank guarantee letters, DBS bank limits, mortgages) ----------
COVER = dict(reliable=(.5, .9), slow=(.3, .6), improving=(.4, .7), deteriorating=(.3, .6), distressed=(.1, .35))
collateral = []
for d in dealers:
    did = d["dealer_id"]
    lim0 = limit_at(did, dt.date(2024, 5, 1))
    total = lim0 * rng.uniform(*COVER[d["profile"]])
    types = rng.sample(["Bank guarantee letter", "DBS bank limit", "Mortgage"], rng.choice([1, 2, 2, 3]))
    shares = [rng.uniform(.5, 1.5) for _ in types]
    for typ, sh in zip(types, shares):
        amt = round(total * sh / sum(shares) / 50_000) * 50_000
        if typ == "Mortgage":
            collateral.append(dict(dealer_id=did, collateral_type=typ, amount_try=amt,
                                   valid_from=dt.date(2024, 5, 1), valid_to=None))
        elif typ == "DBS bank limit":          # re-set at each limit review in line with the limit
            for r in [l for l in limits if l["dealer_id"] == did]:
                end = [l["effective_from"] for l in limits if l["dealer_id"] == did and l["effective_from"] > r["effective_from"]]
                collateral.append(dict(dealer_id=did, collateral_type=typ,
                                       amount_try=round(amt * r["credit_limit_try"] / lim0 / 50_000) * 50_000,
                                       valid_from=r["effective_from"], valid_to=(end[0] - dt.timedelta(days=1)) if end else None))
        else:                                  # 12-month letters, renewed +30% unless the dealer is in trouble
            start = dt.date(2024, rng.randint(1, 12), 1)
            while start <= DATA_END:
                end = dt.date(start.year + 1, start.month, 1) - dt.timedelta(days=1)
                collateral.append(dict(dealer_id=did, collateral_type=typ, amount_try=amt, valid_from=start, valid_to=end))
                k_end = months_from_start(end)
                stop = (d["profile"] == "deteriorating" and k_end >= d["onset"]) or (d["profile"] == "distressed" and rng.random() < .5)
                if stop: break
                start, amt = end + dt.timedelta(days=1), round(amt * 1.3 / 50_000) * 50_000

coll_by_dealer = defaultdict(list)
for c in collateral: coll_by_dealer[c["dealer_id"]].append(c)
def collateral_at(did, day):
    return sum(c["amount_try"] for c in coll_by_dealer[did] if c["valid_from"] <= day and (c["valid_to"] is None or c["valid_to"] >= day))

# ---------- month-end snapshots ----------
pay_by_inv = defaultdict(list)
for p in payments: pay_by_inv[p["invoice_id"]].append(p)
BUCKETS = ["not_due", "od_0_30", "od_31_60", "od_61_90", "od_90p"]

snap = []
for d in dealers:
    did = d["dealer_id"]
    prev = {}                                  # invoice_id -> bucket at previous month-end
    for (y, m) in SNAP_MONTHS:
        E = month_end(y, m)
        b = {k: 0.0 for k in BUCKETS}
        roll = [0.0, 0.0, 0.0]                 # still unpaid now, out of last month's 0-30 / 31-60 / 61-90
        cur = {}
        for i in inv_by_dealer[did]:
            if i["invoice_date"] > E: continue
            paid = sum(p["amount_try"] for p in pay_by_inv[i["invoice_id"]] if p["payment_date"] <= E)
            open_ = i["amount_try"] - paid
            if open_ < 1: continue
            dpd = (E - i["due_date"]).days
            key = ("not_due" if dpd <= 0 else "od_0_30" if dpd <= 30 else "od_31_60" if dpd <= 60
                   else "od_61_90" if dpd <= 90 else "od_90p")
            b[key] += open_
            cur[i["invoice_id"]] = key
            pk = prev.get(i["invoice_id"])
            if pk in ("od_0_30", "od_31_60", "od_61_90"):
                roll[BUCKETS.index(pk) - 1] += open_
        prev = cur
        s3 = sum(monthly_sales[(did, *add_months(y, m, -j))] for j in (0, 1, 2))
        d3 = (E - month_end(*add_months(y, m, -3))).days
        out = sum(b.values())
        overdue = out - b["not_due"]
        lim = limit_at(did, E)
        coll = collateral_at(did, E)
        snap.append(dict(month=f"{y}-{m:02d}", dealer_id=did, sales_month=round(monthly_sales[(did, y, m)]),
                         sales_3m=round(s3), days_3m=d3, outstanding=round(out),
                         **{k: round(v) for k, v in b.items()}, overdue=round(overdue),
                         credit_limit=lim, limit_use=round(out / lim, 4),
                         dso_days=round(out / s3 * d3, 1) if s3 else None,
                         collateral=coll, unsecured=round(max(0, out - coll)),
                         orders_blocked=round(blocked[(did, y, m)]),
                         roll_0_30=round(roll[0]), roll_31_60=round(roll[1]), roll_61_90=round(roll[2])))

# flags (same rules the dashboard applies)
FLOOR = 250_000
by_d = defaultdict(list)
for r in snap: by_d[r["dealer_id"]].append(r)
for rows in by_d.values():
    for t, r in enumerate(rows):
        od = [x["overdue"] for x in rows[max(0, t - 3):t + 1]]
        r["flag_overdue_rising_3m"] = int(len(od) == 4 and all(od[j + 1] >= od[j] * 1.05 and od[j + 1] > od[j] for j in range(3))
                                          and od[-1] >= FLOOR)
        r["flag_limit_use_90"] = int(r["limit_use"] > 0.90)
        r["flag_90p_share_10"] = int(r["outstanding"] > 0 and r["od_90p"] / r["outstanding"] > 0.10)

# ---------- action log (status at the latest month-end) ----------
FIRST = ["Elif", "Mehmet", "Zeynep", "Burak", "Selin", "Emre", "Deniz", "Can", "Ayşe", "Murat", "Ece", "Onur", "Gizem", "Kerem"]
LAST = ["Aydın", "Yalçın", "Erdem", "Karataş", "Tunç", "Oral", "Akgül", "Sezer", "Uysal", "Ergin"]
owners = {}
for region in REGIONS:
    owners[region] = [f"{rng.choice(FIRST)} {rng.choice(LAST)}" for _ in range(2 if REGIONS[region][0] > 20 else 1)]
actions = []
for d in dealers:
    r = by_d[d["dealer_id"]][-1]
    n_flags = r["flag_overdue_rising_3m"] + r["flag_limit_use_90"] + r["flag_90p_share_10"]
    if not n_flags: continue
    aged = r["od_90p"] / r["outstanding"] if r["outstanding"] else 0
    if aged > .25 and r["unsecured"] > 0: step, status = "Legal follow-up", "Escalated"
    elif r["limit_use"] > 1: step, status = "Orders blocked until payment", "Escalated"
    elif r["flag_90p_share_10"]: step, status = "Agree payment plan", "In progress"
    elif r["flag_overdue_rising_3m"]: step, status = "Call dealer this week", "Open"
    else: step, status = "Ask for extra guarantee", "Open"
    ptp = rng.random() < .55 and status != "Escalated"
    actions.append(dict(dealer_id=d["dealer_id"], owner=rng.choice(owners[d["region"]]), next_step=step, status=status,
                        last_contact=dt.date(2026, 10, rng.randint(1, 31)),
                        promise_to_pay_date=dt.date(2026, 11, rng.randint(3, 30)) if ptp else None,
                        promise_to_pay_try=round(r["overdue"] * rng.uniform(.3, .8), -4) if ptp else None))

# ---------- write ----------
def write(name, rows, cols):
    with open(OUT / name, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore"); w.writeheader(); w.writerows(rows)

dcols = ["dealer_id", "dealer_name", "city", "region", "brand", "tier", "payment_terms_days"]
write("dealers.csv", dealers, dcols)
write("invoices.csv", invoices, ["invoice_id", "dealer_id", "invoice_date", "due_date", "amount_try", "product_group"])
write("payments.csv", payments, ["payment_id", "invoice_id", "dealer_id", "payment_date", "amount_try", "method"])
write("credit_limits.csv", limits, ["dealer_id", "effective_from", "credit_limit_try", "review_reason"])
write("collateral.csv", collateral, ["dealer_id", "collateral_type", "amount_try", "valid_from", "valid_to"])
write("actions.csv", actions, ["dealer_id", "owner", "next_step", "status", "last_contact", "promise_to_pay_date", "promise_to_pay_try"])
write("dealer_month.csv", snap, list(snap[0].keys()))

# compact bundle for the dashboard
didx = {d["dealer_id"]: n for n, d in enumerate(dealers)}
epoch = dt.date(2024, 1, 1)
day = lambda x: (x - epoch).days if x else None
fields = ["sales_3m", "days_3m", "outstanding", "not_due", "od_0_30", "od_31_60", "od_61_90", "od_90p",
          "credit_limit", "collateral", "orders_blocked", "roll_0_30", "roll_31_60", "roll_61_90"]
series = {f: [[r[f] for r in by_d[d["dealer_id"]]] for d in dealers] for f in fields}
inv_compact = defaultdict(list)
for i in invoices:
    inv_compact[didx[i["dealer_id"]]].append([
        i["invoice_id"][3:], day(i["invoice_date"]), day(i["due_date"]), i["amount_try"],
        [[day(p["payment_date"]), p["amount_try"]] for p in pay_by_inv[i["invoice_id"]]]])
bundle = dict(
    months=[f"{y}-{m:02d}" for y, m in SNAP_MONTHS],
    monthEnds=[day(month_end(y, m)) for y, m in SNAP_MONTHS],
    dealers=[{k: d[k] for k in dcols} for d in dealers],
    series=series,
    invoices=[inv_compact[n] for n in range(len(dealers))],
    collateral=[[[c["collateral_type"], c["amount_try"], day(c["valid_from"]), day(c["valid_to"])] for c in coll_by_dealer[d["dealer_id"]]] for d in dealers],
    actions={didx[a["dealer_id"]]: dict(owner=a["owner"], step=a["next_step"], status=a["status"], contact=day(a["last_contact"]),
                                        ptp=day(a["promise_to_pay_date"]), ptpAmt=a["promise_to_pay_try"]) for a in actions},
    actionsAsOf=len(SNAP_MONTHS) - 1,
)
(Path(__file__).parent / "data.js").write_text("window.DATA=" + json.dumps(bundle, ensure_ascii=False, separators=(",", ":")) + ";", encoding="utf-8")

last = [r for r in snap if r["month"] == "2026-10"]
print(f"dealers {len(dealers)}  invoices {len(invoices)}  payments {len(payments)}  limits {len(limits)}  "
      f"collateral {len(collateral)}  actions {len(actions)}  snapshot rows {len(snap)}")
print("Oct-26 flags  rising3:", sum(r["flag_overdue_rising_3m"] for r in last),
      " limit>90%:", sum(r["flag_limit_use_90"] for r in last), " 90+>10%:", sum(r["flag_90p_share_10"] for r in last))
for mo in ["2025-06", "2025-12", "2026-06", "2026-10"]:
    rs = [r for r in snap if r["month"] == mo]
    o = sum(r["outstanding"] for r in rs); s = sum(r["sales_3m"] for r in rs)
    print(mo, f"AR {o/1e6:,.0f}M  overdue {sum(r['overdue'] for r in rs)/o:.1%}  DSO {o/s*rs[0]['days_3m']:.0f}  "
          f"secured {sum(min(r['collateral'], r['outstanding']) for r in rs)/o:.0%}  unsecured {sum(r['unsecured'] for r in rs)/1e6:,.0f}M  "
          f"blocked {sum(r['orders_blocked'] for r in rs)/1e6:,.1f}M")
