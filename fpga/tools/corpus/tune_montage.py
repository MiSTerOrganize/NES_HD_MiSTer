"""tune_montage.py - stack the per-group tune.png sheets (frames 120/300/600/900/1200/1500),
N groups per output image, each row labelled with its group and game, at half size.

    python -I tune_montage.py WORK OUTDIR [N] [g01,g09,...]
"""
import os
import sys

from PIL import Image, ImageDraw

work, out = sys.argv[1], sys.argv[2]
n = int(sys.argv[3]) if len(sys.argv) > 3 else 10
os.makedirs(out, exist_ok=True)
rows = [l.split("\t") for l in open(os.path.join(work, "plan.tsv"), encoding="utf-8").read().splitlines()[1:]]
if len(sys.argv) > 4:
    keep = set(sys.argv[4].split(","))
    rows = [r for r in rows if r[0] in keep]
for k in range(0, len(rows), n):
    part = rows[k:k + n]
    sheets = [Image.open(os.path.join(work, r[0], "tune.png")).convert("RGB") for r in part]
    sheets = [s.resize((s.width // 2, s.height // 2)) for s in sheets]
    lab = 14
    w = max(s.width for s in sheets)
    img = Image.new("RGB", (w, sum(s.height + lab for s in sheets)), (40, 40, 40))
    d = ImageDraw.Draw(img)
    y = 0
    for r, s in zip(part, sheets):
        d.text((2, y + 1), f"{r[0]}  {r[1]}  nolimit={r[3]}", fill=(255, 255, 0))
        img.paste(s, (0, y + lab))
        y += s.height + lab
    img.save(os.path.join(out, f"montage_{k // n:02d}.png"))
print("done")
