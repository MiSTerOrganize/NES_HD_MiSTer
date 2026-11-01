"""img_cmp.py - compare a painter output (binary PPM) with a reference PNG, pixel for pixel.

usage: python img_cmp.py REF.png OUT.ppm
Prints the number of differing pixels and the first few; exit 1 if any differ.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from pngio import read_png  # noqa: E402


def read_ppm(path):
    d = open(path, "rb").read()
    parts = d.split(b"\n", 3)
    w, h = (int(v) for v in parts[1].split())
    return w, h, parts[3]


def main():
    rw, rh, rows = read_png(sys.argv[1])
    w, h, px = read_ppm(sys.argv[2])
    if (rw, rh) != (w, h):
        print(f"SIZE differs: ref {rw}x{rh}, out {w}x{h}")
        return 1
    bad = 0
    first = []
    for y in range(h):
        row = rows[y]
        for x in range(w):
            r, g, b = row[x][:3]
            o = (y * w + x) * 3
            if (px[o], px[o + 1], px[o + 2]) != (r, g, b):
                bad += 1
                if len(first) < 8:
                    first.append(f"({x},{y}) ref {r},{g},{b} out {px[o]},{px[o + 1]},{px[o + 2]}")
    print(f"{bad} pixels differ of {w * h}")
    for f in first:
        print("   ", f)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
