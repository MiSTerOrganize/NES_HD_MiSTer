"""Write a copy of a format-3 pack whose backgrounds reach the drawing paths no recorded frame
does, so the hd3_render test (check_render.py with backgrounds) sees them:

  - the recorded frames draw only Alpha backgrounds: record i gets blend Add when i % 5 == 1
    and Subtract when i % 5 == 2;
  - every recorded background starts at (0, 0) of its map at scroll 0: record i % 5 == 3 is
    moved 3 pixels right and 5 down inside its map (left += 3, top += 5, when that still fits),
    so the cell phase and the image row change within a group and the last lines fall off;
  - no ratio is ever negative or fractional against 8: ratio row r gets value
    (old * 5) // 4 - 20 - 3 * r, so small scrolls give a negative sx / sy (leading pixels and
    lines not drawn) and large ones run the record off its right / bottom edge.

With --edges, record i % 5 == 4 is also made 56 pixels narrower and 48 lines shorter (when at
least 16 of each are left past left / top), so its right and bottom edges fall inside the
screen. No recorded frame scrolls far enough to reach a full-size record's right or bottom edge
(the ratios above only reach a few lines of it), so without this the right-edge and bottom-edge
clips never decide a pixel. Narrowing changes the map's row stride, so the record shows other
cells of its own map; the reference reads the same pack, so that is still a legal picture.

The selection (bg_golden.py) does not depend on record contents, so only the render reference
(check_render.py, which reads the same modified pack) changes. A test fixture, never a pack to
ship.

usage: python make_bg_frame.py [--edges] <in.hdp> <out.hdp>
"""
import os
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import hdref  # noqa: E402

# the record is "<IIIIIHHB": map, w, h, left, top (5 x u32), hr, vr (u16), blend (u8)
BLEND = struct.calcsize("<IIIIIHH")


def main():
    args = [a for a in sys.argv[1:] if a != "--edges"]
    edges = len(args) != len(sys.argv) - 1
    if len(args) != 2:
        print(__doc__)
        return 2
    src, dst = args
    data = bytearray(open(src, "rb").read())
    h = hdref.Hdp3(bytes(data))
    nrec = (h.s(7) - h.s(6)) // 32
    nrat = (h.s(9) - h.s(8)) // 2048
    if nrec == 0 or nrat == 0:
        sys.exit("pack has no backgrounds or no ratio rows")
    add = sub = moved = shrunk = 0
    for i in range(nrec):
        o = h.s(6) + 32 * i
        mp, w, hh, left, top, hr, vr, blend = struct.unpack_from("<IIIIIHHB", data, o)
        if i % 5 == 1:
            data[o + BLEND] = 1
            add += 1
        elif i % 5 == 2:
            data[o + BLEND] = 2
            sub += 1
        elif i % 5 == 3 and left + 3 < w and top + 5 < hh:
            struct.pack_into("<II", data, o + 12, left + 3, top + 5)
            moved += 1
        elif edges and i % 5 == 4 and w - 56 >= left + 16 and hh - 48 >= top + 16:
            struct.pack_into("<II", data, o + 4, w - 56, hh - 48)
            shrunk += 1
    for r in range(nrat):
        for s in range(512):
            o = h.s(8) + r * 2048 + s * 4
            (v,) = struct.unpack_from("<i", data, o)
            struct.pack_into("<i", data, o, (v * 5) // 4 - 20 - 3 * r)
    if not (add and sub and moved) or (edges and not shrunk):
        sys.exit(f"nothing to change (add {add}, sub {sub}, moved {moved}, shrunk {shrunk})")
    # read the edits back through the reader the reference uses: a byte written at the wrong
    # offset still makes a pack whose renders agree on both sides, so the test would pass
    # without ever drawing an Add or Subtract background
    chk = hdref.Hdp3(bytes(data))
    got = [chk.bg_rec(i)["blend"] for i in range(min(nrec, 10))]
    want = [(1 if i % 5 == 1 else 2 if i % 5 == 2 else got[i]) for i in range(len(got))]
    if got != want or not any(g == 1 for g in got) or not any(g == 2 for g in got):
        sys.exit(f"blend edits not read back by hdref ({got})")
    if edges:
        sizes = [(chk.bg_rec(i)["w"], chk.bg_rec(i)["h"]) for i in range(4, nrec, 5)]
        orig = [struct.unpack_from("<II", open(src, "rb").read(), h.s(6) + 32 * i + 4)
                for i in range(4, nrec, 5)]
        if not any(s != o for s, o in zip(sizes, orig)):
            sys.exit("size edits not read back by hdref")
    open(dst, "wb").write(data)
    print(f"{dst}: {add} Add, {sub} Subtract, {moved} moved, {shrunk} shrunk records, "
          f"{nrat} ratio rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
