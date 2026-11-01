"""Synthetic HD pack for the 8a lane tests, built on ONE recorded CHR-ROM frame so that every
lane rule decides the picture by construction (the converted corpus packs cannot: their added
sprites mostly land where they draw nothing, none comes from a flipped source, no added key has
an origin or position condition, and Castlevania's backgrounds cover pixel (0,0)).

Default frame: Metroid 880 - flipped sprites, fine X scroll on every line (so the BG tile at
x 0 starts mid-tile), and line 0's pixel 0 a different tile from line 239's. The pack has no
overscan and no backgrounds. Rules (each a mutant of hd3_render / hd3_resolve must change):
  flip    a flipped sprite source adds a sprite 16 px below it whose HD image is left/right
          asymmetric: drawn unflipped it differs
  sap     BG key B1 is drawn HD only if spriteAtPosition (absolute: one B1 pixel) sees the
          added key K2, which B1 itself adds at offset 0
  snb     BG key B2 likewise with spriteNearby 0,0 on its own added key K3
  origin  the BG tile at x 0 of a fine-scrolled line adds K4 at offset 0; K4 is drawn HD only
          when originPositionCheckX > 65535, i.e. its origin is negative - true only for the
          run that starts mid-tile, so a column taken without the source's is caught
  t00     BG key B4 is drawn HD only if tileAtPosition 0,0 sees line 239's pixel 0 tile (with
          additions Mesen leaves line 239's first-pixel record over pixel (0,0))
  p00     line 0's and line 239's pixel 0 tiles have different HD images
  z240    line 239's pixel 0 tile adds K5 at (0, -239): pixel (0,0) gets it only from the
          lanes of line 240
  notile  a source adds the NOTILE key, which has an HD rule: an added NOTILE sprite never
          matches (hdref), so the rule must not draw
  bgp     a behind-background sprite adds K6 at the offset putting most of it on opaque
          background: the added sprite keeps the source's priority, so it is hidden there
  sapx    BG key B5 is drawn HD only if spriteAtPosition sees K2 with a palette K2 does not
          have: never true (the added sprite's own palette must be compared)
  nzd     BG key B6 adds NOTILE 8 below and is drawn HD only if spriteNearby 0,8 sees tile
          DATA of all zeros: in a CHR-ROM game a data condition compares a zero fingerprint, so
          only the rule that an added NOTILE matches no tile condition keeps it false
Writes <out dir>/hires.txt and tiles.png (convert with hdp3_convert.py).

--no-z240 leaves the z240 addition out. Its added sprite covers pixel (0,0), which hides the BG
tile there, so p00 (line 239's pixel 0 drawn at (0,0)) needs this variant.

usage: python make_lane_pack.py <rec_FFFF.bin> <out dir> [--no-z240]
"""
import collections
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import hdref  # noqa: E402
from pngio import write_png  # noqa: E402

FREE = 0x7F0      # tile indices for the added keys: none is on screen (asserted)


def main():
    args = [a for a in sys.argv[1:] if a != "--no-z240"]
    if len(args) != 2:
        print(__doc__)
        return 2
    z240 = "--no-z240" not in sys.argv
    rec = open(args[0], "rb").read()
    out = args[1]
    sc = hdref.build_records(rec, False, False)
    NT = hdref.NOTILE

    bg = collections.Counter()
    first = {}
    used = set()
    for i, p in enumerate(sc):
        k = (p.tile.idx, p.tile.pal)
        if p.tile.idx != NT:
            bg[k] += 1
            first.setdefault(k, i)
            used.add(p.tile.idx)
        for s in p.spr:
            used.add(s.idx)
    for j in range(8):
        if FREE + j in used:
            sys.exit(f"tile {FREE + j:X} is on screen; pick another FREE")

    p0, p239 = sc[0].tile, sc[239 << 8].tile
    k0, k239 = (p0.idx, p0.pal), (p239.idx, p239.pal)
    if k0 == k239 or NT in (p0.idx, p239.idx):
        sys.exit("line 0 and line 239 pixel 0 must be different tiles")
    # the BG tile at x 0 on a line with fine X (its run starts mid-tile)
    y3 = next((y for y in range(1, 239) if sc[y << 8].finex and sc[y << 8].tile.idx != NT
               and (sc[y << 8].tile.idx, sc[y << 8].tile.pal) not in (k0, k239)), None)
    if y3 is None:
        sys.exit("no fine-scrolled line with a tile at x 0")
    k3 = (sc[y3 << 8].tile.idx, sc[y3 << 8].tile.pal)
    # flipped sprite source
    flip = next(((s.idx, s.pal) for p in sc for s in p.spr if s.hm and s.idx != NT), None)
    if flip is None:
        sys.exit("no flipped sprite on this frame")
    # a behind-background sprite that is not also drawn in front somewhere
    front = {(s.idx, s.pal) for p in sc for s in p.spr if not s.bgp}
    behind = next(((s.idx, s.pal) for p in sc for s in p.spr
                   if s.bgp and s.idx != NT and (s.idx, s.pal) not in front
                   and (s.idx, s.pal) != flip), None)
    if behind is None:
        sys.exit("no behind-background sprite on this frame")
    # where K6 lands: the offset putting the most added pixels on opaque background with no
    # sprite of their own (where the background is transparent the priority decides nothing)
    # (an addition's offset is mirrored by its source's flips: hdref.draw_additions)
    src = [(i, s.hm, s.vm) for i, p in enumerate(sc) for s in p.spr if (s.idx, s.pal) == behind]
    best = (0, 0, 0)
    for dy in range(-40, 41, 2):
        for dx in range(-40, 41, 2):
            n = 0
            for i, hm, vm in src:
                tx, ty = (i & 255) + (-dx if hm else dx), (i >> 8) + (-dy if vm else dy)
                if 0 <= tx < 256 and 0 <= ty < 240:
                    t = sc[(ty << 8) | tx]
                    n += t.tile.idx != NT and t.tile.bgci != 0 and not t.spr
            if n > best[0]:
                best = (n, dx, dy)
    if best[0] < 16:
        sys.exit("no offset puts the behind-background sprite's addition on opaque background")
    bdx, bdy = best[1], best[2]
    # B1, B2, B4, B5, B6: BG keys of few instances (few runs a line), not any key above
    taken = {k0, k239, k3}
    small = [k for k, n in sorted(bg.items(), key=lambda kv: (kv[1], kv[0]))
             if 64 <= n <= 256 and k not in taken]
    if len(small) < 5:
        sys.exit("not enough small BG keys")
    b1, b2, b4, b5, b6 = small[0], small[1], small[2], small[3], small[4]
    x1, y1 = first[b1] & 255, first[b1] >> 8

    def h(k):
        return f"{k[0] & 0xFFFFFFFF:X},{k[1]:08X}"

    # images 0..11: flip, sap, snb, origin, t00, p00 line 0, p00 line 239, z240, notile, bgp,
    # sapx, nzd
    imgs = []
    cols = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0), (255, 0, 255), (0, 255, 255),
            (255, 128, 0), (128, 0, 255), (255, 255, 255), (0, 128, 64), (64, 0, 128),
            (128, 64, 0)]
    for n, c in enumerate(cols):
        a = c
        b = tuple(255 - v // 2 for v in c)          # right half a different colour: asymmetric
        imgs.append([[(a if x < 8 else b) + (255,) for x in range(16)] for _ in range(16)])
    w = 16 * len(imgs)
    rows = [[imgs[x // 16][y][x % 16] for x in range(w)] for y in range(16)]
    os.makedirs(out, exist_ok=True)
    write_png(os.path.join(out, "tiles.png"), w, 16, rows)

    pal1 = flip[1]
    K = {n: (FREE + j, pal1) for j, n in enumerate(["k1", "k2", "k3", "k4", "k5"])}
    K["k2"] = (FREE + 1, b1[1])
    K["k3"] = (FREE + 2, b2[1])
    K["k4"] = (FREE + 3, k3[1])
    K["k5"] = (FREE + 4, k239[1])
    K["k6"] = (FREE + 5, behind[1])
    notile = (-1, b4[1])
    notile6 = (-1, b6[1])
    wrong = b1[1] ^ 0x01000000               # a palette K2 does not have

    def tile(img, k, conds=""):
        # bitmap 0 (the one PNG), image img at x 16 * img
        return f"{conds}<tile>0,{h(k)},{16 * img},0,1,N"

    L = ["<ver>108", "<scale>2", "<img>tiles.png",
         f"<condition>sap,spriteAtPosition,{x1},{y1},{h(K['k2'])}",
         f"<condition>snb,spriteNearby,0,0,{h(K['k3'])}",
         "<condition>org,originPositionCheckX,>,65535",
         f"<condition>t00,tileAtPosition,0,0,{h(k239)}",
         f"<condition>sapx,spriteAtPosition,{x1},{y1},{FREE + 1:X},{wrong:08X}",
         f"<condition>nzd,spriteNearby,0,8,{'0' * 32},{b6[1]:08X}",
         tile(0, K["k1"]),
         tile(1, b1, "[sap]"),
         tile(2, b2, "[snb]"),
         tile(3, K["k4"], "[org]"),
         tile(4, b4, "[t00]"),
         tile(5, k0),
         tile(6, k239),
         tile(7, K["k5"]),
         tile(8, notile),
         tile(9, K["k6"]),
         tile(10, b5, "[sapx]"),
         tile(11, b6, "[nzd]"),
         tile(8, notile6),
         f"<addition>{h(flip)},0,16,{h(K['k1'])}",
         f"<addition>{h(behind)},{bdx},{bdy},{h(K['k6'])}",
         f"<addition>{h(b6)},0,8,{h(notile6)}",
         f"<addition>{h(b1)},0,0,{h(K['k2'])}",
         f"<addition>{h(b2)},0,0,{h(K['k3'])}",
         f"<addition>{h(k3)},0,0,{h(K['k4'])}",
         f"<addition>{h(b4)},0,8,{h(notile)}"]
    if z240:
        L.insert(-1, f"<addition>{h(k239)},0,-239,{h(K['k5'])}")
    with open(os.path.join(out, "hires.txt"), "w", newline="\n") as f:
        f.write("\n".join(L) + "\n")
    print(f"{out}: flip {h(flip)}  B1 {h(b1)} at ({x1},{y1})  B2 {h(b2)}  origin line {y3} "
          f"fine x {sc[y3 << 8].finex} key {h(k3)}  B4 {h(b4)}  line0 {h(k0)}  line239 {h(k239)}"
          f"  behind {h(behind)} at ({bdx},{bdy}), {best[0]} px on opaque BG  B5 {h(b5)}  B6 {h(b6)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
