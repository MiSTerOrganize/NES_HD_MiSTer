"""rec_main8_same.py - is a --nolimit record the old 8-fetch record plus extra entries only?
Compares pixels, span area and the first 8 sprite fetch entries of every line; reports the
header qwords with the fetch-count byte masked out.

    python -I rec_main8_same.py new.bin old.bin
"""
import struct
import sys

a, b = open(sys.argv[1], "rb").read(), open(sys.argv[2], "rb").read()
bad = []
if a[:0x40000] != b[:0x40000]:
    bad.append("pixels")
for y in range(240):
    o = 0x40000 + y * 2048
    qa, qb = struct.unpack_from("<Q", a, o)[0], struct.unpack_from("<Q", b, o)[0]
    m = ~(0xFF << 48) & (2 ** 64 - 1)
    if qa & m != qb & m or a[o + 8:o + 64] != b[o + 8:o + 64]:
        bad.append(f"header {y}")
    if a[o + 64:o + 640] != b[o + 64:o + 640]:
        bad.append(f"spans {y}")
    if a[o + 640:o + 640 + 128] != b[o + 640:o + 640 + 128]:
        bad.append(f"main8 {y}")
tail = a[0x40000 + 240 * 2048:] == b[0x40000 + 240 * 2048:]
print(f"differences outside extra-sprite fetches: {len(bad)} {bad[:5]}; trailer same: {tail}")
