"""Compare a slow-DDR3 engine picture with the same frame drawn in time.

    python slow_check.py <good.rgb> <slow.rgb>

When RENDER falls behind the scan-out, hd3_scanout shows a line it has not finished as black
(and sets underflow); a line it has finished must be exactly the in-time picture. So every
row of the slow picture is either identical to the good one or entirely black. Both kinds must
occur, or the run did not exercise the late path (all identical) or drew nothing (all black).
Rows are compared in pairs (one NES line = two HD rows), since a line is shown or blanked whole.
Exit 1 on any other row.
"""
import struct
import sys


def load(p):
    with open(p, "rb") as f:
        b = f.read()
    magic, w, h = struct.unpack_from("<III", b, 0)
    if magic != 0x4247524E:
        sys.exit(f"{p}: not an NRGB file")
    return w, h, b[12:]


def main():
    gw, gh, g = load(sys.argv[1])
    sw, sh, s = load(sys.argv[2])
    if (gw, gh) != (sw, sh):
        sys.exit("sizes differ")
    stride = gw * 3
    same = black = bad = 0
    for y in range(0, gh, 2):
        rs = s[y * stride:(y + 2) * stride]
        rg = g[y * stride:(y + 2) * stride]
        if rs == rg:
            same += 1
        elif not any(rs):
            black += 1
        else:
            bad += 1
            if bad <= 5:
                print(f"line {y // 2}: neither the in-time picture nor black")
    print(f"lines: {same} as drawn in time, {black} black (late), {bad} wrong")
    if bad or not black or not same:
        print("FAIL")
        sys.exit(1)
    print("PASS")


main()
