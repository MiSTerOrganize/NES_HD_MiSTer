"""Small .hdp fixture for the loader unit test and its negative control (neg_loader.py).

The loader exports fb_base / fb_len (section 10, header 0x44), legacy (flags bit 0) and
game_ram (flags bit 4 when bit 5 says the pack knows, else the cart). Only 60-75 MB corpus packs
carry a fallback map, and the negative control streams every pack once per mutant and per
corrupted variant, so this writes a small one instead: a copy of a small pack with
  - a fallback map appended as section 10 (N i32 entries) and its count at header 0x44,
  - header word 0x40 (the addition count) set to a different value (so reading the wrong word
    shows), and therefore a small addition table as sections 16/17 (4 buckets = 256 bytes,
    a 32-byte list area, header 0x4C = 4 and 0x50 = 3, distinct values so a wrong word shows;
    the loader checks the table's shape, not its contents),
  - flags bits chosen by --flags (default 0x29: legacy, game type known, CHR-ROM).
Header file size and the section table stay valid, so the loader accepts it.

usage: python make_loader_fixture.py SRC.hdp OUT.hdp [--flags HEX] [--entries N]
"""
import argparse
import struct


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("out")
    ap.add_argument("--flags", default="29")
    ap.add_argument("--entries", type=int, default=37)
    a = ap.parse_args()
    d = bytearray(open(a.src, "rb").read())
    if d[:4] != b"NHDP":
        raise SystemExit("not a format-3 pack")
    while len(d) % 8:
        d.append(0)
    off = len(d)
    for k in range(a.entries):
        d += struct.pack("<i", (k * 7 + 3) if k % 3 else -1)
    while len(d) % 8:
        d.append(0)
    struct.pack_into("<II", d, 0x80 + 10 * 8, off, 4 * a.entries)
    struct.pack_into("<I", d, 0x44, a.entries)
    struct.pack_into("<I", d, 0x40, a.entries + 1000)
    for sec, size in ((16, 256), (17, 32)):
        while len(d) % 64:
            d.append(0)
        struct.pack_into("<II", d, 0x80 + sec * 8, len(d), size)
        d += bytes(size)
    struct.pack_into("<II", d, 0x4C, 4, 3)
    d[7] = int(a.flags, 16)
    struct.pack_into("<I", d, 0x20, len(d))
    open(a.out, "wb").write(d)
    print(f"{a.out}: {len(d)} bytes, flags {d[7]:02x}, section 10 at {off} ({a.entries} entries), "
          "addition table 4 buckets")


if __name__ == "__main__":
    main()
