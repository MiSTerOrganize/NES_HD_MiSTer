"""rec_diff.py - where do two frame records differ? Summarises differing bytes by region
(pixels / line header / spans / sprites / trailer) and prints the first few line headers that
differ, decoded (span count, valid sprites, sprite fetches).

    python -I rec_diff.py a.bin b.bin
"""
import struct
import sys

a, b = open(sys.argv[1], "rb").read(), open(sys.argv[2], "rb").read()
n = min(len(a), len(b))
reg = {}
lines = []
for i in range(n):
    if a[i] == b[i]:
        continue
    if i < 0x40000:
        k = "pixels"
    elif i < 0x40000 + 240 * 2048:
        o = (i - 0x40000) % 2048
        k = "header" if o < 64 else "spans" if o < 640 else "sprites" if o < 1664 else "pad"
        y = (i - 0x40000) // 2048
        if not lines or lines[-1] != y:
            lines.append(y)
    else:
        k = "trailer/other"
    reg[k] = reg.get(k, 0) + 1
print(f"len {len(a)} {len(b)}; differing bytes by region: {reg}; lines {len(lines)}")
for y in lines[:6]:
    for nm, d in (("A", a), ("B", b)):
        q0 = struct.unpack_from("<Q", d, 0x40000 + y * 2048)[0]
        print(f"  line {y} {nm}: spans {(q0 >> 32) & 0xFF} valid-sprites {(q0 >> 40) & 0xFF} "
              f"fetches {(q0 >> 48) & 0xFF} q0={q0:016x}")
