"""hdp_sections.py - print a .hdp's format version bytes and its 18 section (offset, size) pairs.

    python -I hdp_sections.py PACK.hdp
"""
import struct
import sys

d = open(sys.argv[1], "rb").read()
print("magic", d[:4], "bytes 4..16", d[4:16].hex(), "file", len(d))
for i in range(18):
    o, s = struct.unpack_from("<II", d, 0x80 + 8 * i)
    print(f"  section {i:2}: off {o:#010x} size {s}")
