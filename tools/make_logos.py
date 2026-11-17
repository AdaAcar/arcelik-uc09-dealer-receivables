"""Turn the downloaded Arçelik logo (white-background palette PNG) into two transparent logos:
assets/logo.png (black lettering, for light mode) and assets/logo-dark.png (white lettering, for dark mode).
The red mark keeps its exact colour. Pure standard library: edits the palette and adds per-colour alpha."""
import struct, sys, zlib
from pathlib import Path

src, out_dir = Path(sys.argv[1]), Path(sys.argv[2])
CROP = (68, 66, 800, 210)                       # x, y, width, height around the artwork
RED = (0xd9, 0x38, 0x35)

def chunks(b):
    i = 8
    while i < len(b):
        n = struct.unpack(">I", b[i:i + 4])[0]
        yield b[i + 4:i + 8], b[i + 8:i + 8 + n]
        i += 12 + n

raw = src.read_bytes()
idat, plte = b"", None
for t, d in chunks(raw):
    if t == b"IHDR": w, h, depth, ctype = struct.unpack(">IIBB", d[:10])
    elif t == b"PLTE": plte = [tuple(d[j:j + 3]) for j in range(0, len(d), 3)]
    elif t == b"IDAT": idat += d
assert depth == 8 and ctype == 3, "expected an 8-bit palette PNG"

# undo PNG row filters (1 byte per pixel)
data, rows, prev, p = zlib.decompress(idat), [], bytearray(w), 0
for _ in range(h):
    f, line = data[p], bytearray(data[p + 1:p + 1 + w]); p += 1 + w
    for x in range(w):
        a = line[x - 1] if x else 0; b = prev[x]; c = prev[x - 1] if x else 0
        if f == 1: line[x] = (line[x] + a) & 255
        elif f == 2: line[x] = (line[x] + b) & 255
        elif f == 3: line[x] = (line[x] + (a + b) // 2) & 255
        elif f == 4:
            pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
            line[x] = (line[x] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
    rows.append(line); prev = line

cx, cy, cw, chh = CROP
rows = [r[cx:cx + cw] for r in rows[cy:cy + chh]]

def palette(ink):
    cols, alpha = [], []
    for r, g, b in plte:
        if r - g > 20:                          # red mark and its anti-aliased edge against white
            cols.append(RED); alpha.append(max(0, min(255, round((255 - g) / (255 - RED[1]) * 255))))
        else:                                   # black lettering, greys and white background
            cols.append(ink); alpha.append(255 - round((r + g + b) / 3))
    return cols, alpha

def write(path, ink):
    cols, alpha = palette(ink)
    def chunk(t, d): return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    body = zlib.compress(b"".join(b"\x00" + bytes(r) for r in rows), 9)
    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", cw, chh, 8, 3, 0, 0, 0))
           + chunk(b"PLTE", b"".join(bytes(c) for c in cols)) + chunk(b"tRNS", bytes(alpha))
           + chunk(b"IDAT", body) + chunk(b"IEND", b""))
    path.write_bytes(png); print("wrote", path)

write(out_dir / "logo.png", (0, 0, 0))
write(out_dir / "logo-dark.png", (255, 255, 255))
