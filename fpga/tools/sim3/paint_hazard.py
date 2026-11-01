"""paint_hazard.py - display lists that make hd3_paint start a span on the pixel the previous
span wrote last.

The recorded frames never do that (a BG span ends at x 255 and sprites rarely start on the
last pixel of the span before them), so paint_parity.sh cannot see a painter that starts the
next span before the last one's writes have landed: on 2026-10-29 the guard was removed
completely and all 29 frames stayed pixel-exact.

  python paint_hazard.py IN.dl TIGHT.dl GAP.dl

After every BLIT A this inserts B: a 1-pixel BLIT of A's last pixel (same block, same source
column) in additive mode, so B reads the pixel A just wrote. TIGHT puts B straight after A.
GAP puts three FX commands between them, each carrying the line's current FX value so the
line's grayscale/emphasis is unchanged; they delay B well past A's last write. The painter is
right only if TIGHT and GAP give the same picture.
"""
import struct
import sys

OP_BLIT, OP_FILL, OP_FX, OP_EOL = 0, 1, 2, 3


def blit_on_last_pixel(c):
    x0 = (c >> 2) & 0xFF
    n = ((c >> 10) & 0xFF) + 1
    ox0 = (c >> 25) & 7
    last = (x0 + n - 1) & 0xFF
    b = c
    b &= ~(0xFF << 2)
    b |= last << 2
    b &= ~(0xFF << 10)                        # length field 0 = 1 pixel
    b &= ~(3 << 18)
    b |= 1 << 18                              # additive: reads the destination
    b &= ~(7 << 25)
    b |= ((ox0 + n - 1) & 7) << 25            # the source column of A's last pixel
    return b


def main():
    # the file: {block section offset, count<<32 | overscan}, then count command qwords
    raw = open(sys.argv[1], "rb").read()
    hdr0, hdr1 = struct.unpack_from("<2Q", raw, 0)
    n = hdr1 >> 32
    qs = list(struct.unpack_from("<%dQ" % n, raw, 16))
    tail = raw[16 + 8 * n:]
    tight, gap = [], []
    fx = OP_FX                                # the FX value in force on this line (0 = none)
    added = 0
    for c in qs:
        op = c & 3
        tight.append(c)
        gap.append(c)
        if op == OP_FX:
            fx = c
        elif op == OP_EOL:
            fx = OP_FX
        elif op == OP_BLIT:
            b = blit_on_last_pixel(c)
            tight.append(b)
            gap.extend([fx, fx, fx, b])
            added += 1
    if added == 0:
        print("no BLIT commands in", sys.argv[1])
        return 3                              # nothing to test in this frame
    for path, cmds in ((sys.argv[2], tight), (sys.argv[3], gap)):
        h = struct.pack("<2Q", hdr0, (len(cmds) << 32) | (hdr1 & 0xFFFFFFFF))
        open(path, "wb").write(h + struct.pack("<%dQ" % len(cmds), *cmds) + tail)
    print("%d commands, %d spans added" % (len(qs), added))
    return 0


if __name__ == "__main__":
    sys.exit(main())
