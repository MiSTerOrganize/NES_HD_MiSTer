"""Copy a .hdp with its overscan window changed (header 0x10..0x1C: top, right, bottom, left,
i32 each), for the engine test of the scan-out window: asymmetric on purpose, so a mutant
that swaps left/right or top/bottom draws a different picture.

    python make_ov_pack.py <in.hdp> <out.hdp> <top> <right> <bottom> <left>
"""
import struct
import sys

src, dst = sys.argv[1], sys.argv[2]
ov = [int(v) for v in sys.argv[3:7]]
with open(src, "rb") as f:
    b = bytearray(f.read())
if b[:4] != b"NHDP":
    sys.exit("not a .hdp")
struct.pack_into("<4i", b, 0x10, *ov)
with open(dst, "wb") as f:
    f.write(b)
print(f"{dst}: overscan top {ov[0]} right {ov[1]} bottom {ov[2]} left {ov[3]}")
