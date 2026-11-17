"""Bundle dashboard.html + data.js into one self-contained file you can open offline."""
from pathlib import Path
here = Path(__file__).parent
html = (here / "dashboard.html").read_text(encoding="utf-8")
data = (here / "data.js").read_text(encoding="utf-8")
html = html.replace('<script src="data.js"></script>', "<script>" + data + "</script>")
# embed the light- and dark-mode logos from assets/ (built by tools/make_logos.py)
import base64
for name in ("logo.png", "logo-dark.png"):
    f = here / "assets" / name
    if f.exists():
        html = html.replace(f'src="assets/{name}"', f'src="data:image/png;base64,{base64.b64encode(f.read_bytes()).decode()}"')
        print("logo embedded:", name)
head = '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n<style>body{margin:0}[hidden]{display:none!important}</style>\n'
i = html.index("</style>") + len("</style>")
(here / "Dealer_Receivables_Watch.html").write_text(head + html[:i] + "\n</head>\n<body>\n" + html[i:] + "\n</body>\n</html>\n", encoding="utf-8")
print("ok")
