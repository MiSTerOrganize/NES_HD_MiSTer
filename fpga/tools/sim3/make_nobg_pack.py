"""Copy an .hdp with its background layers disabled: section 5 (the 40-entry background level
table, {rule list offset, index offset} each) is zeroed, so no level has a rule list and nothing
is selected - in hdref (select_backgrounds skips roff 0) and in hd3_render alike.

Used by the line-0 fixture: Castlevania's backgrounds cover pixel (0,0), so with them a render
that draws pixel (0,0) from the wrong line looks the same as the right one. A test fixture only.

usage: python make_nobg_pack.py <src.hdp> <dst.hdp>
"""
import struct
import sys


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    d = bytearray(open(sys.argv[1], "rb").read())
    if d[:4] != b"NHDP":
        sys.exit("not an .hdp file")
    off, ln = struct.unpack_from("<II", d, 0x80 + 8 * 5)
    if ln != 320:
        sys.exit(f"section 5 is {ln} bytes, expected 320 (40 levels x 8)")
    used = sum(1 for i in range(40) if struct.unpack_from("<I", d, off + 8 * i)[0])
    d[off:off + ln] = bytes(ln)
    open(sys.argv[2], "wb").write(d)
    print(f"{sys.argv[2]}: {used} background levels disabled")
    return 0


if __name__ == "__main__":
    sys.exit(main())
