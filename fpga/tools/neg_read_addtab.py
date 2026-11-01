"""Negative control for hdp3_read.check_add_tables: the clean pack must report 0, each
damaged copy must report at least one problem.
usage: python neg_read_add.py PACK.hdp"""
import struct
import sys

sys.path.insert(0, r"C:\Users\miste\OneDrive\Desktop\MiSTerOrganize\MiSTerFrontier\NES_HDPack\tools")
import hdp3_read  # noqa: E402

d0 = open(sys.argv[1], "rb").read()


def run(d):
    return hdp3_read.check_add_tables(hdp3_read.Hdp3(bytes(d)))


def sec(d, i):
    return struct.unpack_from("<II", d, 0x80 + 8 * i)


fails = 0
base = run(d0)
print(f"clean: {len(base)} problems")
fails += bool(base)

cases = {}
d = bytearray(d0)                        # an entry's ox changed
o17 = sec(d, 17)[0]
d[o17 + 8 + 2] ^= 1
cases["list entry offset changed"] = d
d = bytearray(d0)                        # an entry's added body changed
d[o17 + 8 + 16] ^= 1
cases["list entry added body changed"] = d
d = bytearray(d0)                        # the first valid table entry dropped
o16, l16 = sec(d, 16)
for k in range(0, l16, 16):
    q1 = struct.unpack_from("<Q", d, o16 + k + 8)[0]
    if q1 >> 63:
        struct.pack_into("<Q", d, o16 + k + 8, q1 & ~(1 << 63))
        break
cases["table entry dropped"] = d
d = bytearray(d0)                        # a list count shortened
cnt = struct.unpack_from("<I", d, o17)[0]
struct.pack_into("<I", d, o17, cnt - 1 if cnt > 1 else 0)
cases["list count shortened"] = d
d = bytearray(d0)                        # bucket count not a power of two
struct.pack_into("<I", d, 0x4C, struct.unpack_from("<I", d, 0x4C)[0] - 1)
cases["bucket count wrong"] = d
d = bytearray(d0)                        # an addition's ignore-palette flag flipped
o11 = sec(d, 11)[0]
d[o11 + 40] ^= 1
cases["ignore-palette flag flipped"] = d

for name, dd in cases.items():
    p = run(dd)
    ok = bool(p)
    print(f"{'CAUGHT ' if ok else 'MISSED '} {name}: {len(p)} problems{(' - ' + p[0]) if p else ''}")
    fails += not ok
print("PASS" if not fails else f"FAIL ({fails})")
sys.exit(1 if fails else 0)
