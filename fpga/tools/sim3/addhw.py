"""8a additions - model of the HARDWARE storage scheme, checked against hdref.process_additions.

hd3_add (vblank, per frame), as modelled here:
  for each source line y = 0..239 (Mesen's process_bg rule decides whether BG spans are scanned):
    sources = the line's sprite fetches whose record has additions (members: the pixels where
              the fetch is one of the first four valid covering fetches and sprites are shown,
              rank k = its position) and, on a process_bg line, the BG spans whose record has
              additions (members: the pixels whose BG slot is the span; k = 4, after sprites)
    each source's members are cut into RUNS of consecutive pixels whose offx steps by one
    for each run and each matching addition (file order) the target run (tx = x +/- ox, ty =
    y +/- oy) is clipped to the screen and becomes a LANE {tx0, len, key, offx0, offy, hm, vm,
    bgp, source line}
    the line's lanes are sorted by (-dx, k, addition index) and appended, in that order, to their
    target line's lane list
  pixel (0,0): a virtual line 240 = the lanes of line 239 from source lines < 239 covering x 0,
    then the lanes of line 0 from source line 239 covering x 0
A reader's list for pixel (x, y): the captured sprites (n_c), then the lanes of line y (240 for
(0,0)) covering x, in order, at most 4 - n_c of them. (0,0)'s captured sprites and tile are
(0,239)'s; line 0's line fields are line 239's.

Checked: every pixel's tile, sprite list (idx, pal, fp, offx, offy, hm, vm, bgp, sci) and line
fields equal hdref after process_additions.

usage: python addhw.py PACK.hdp RECDIR GAME_RAM FRAME [FRAME...]   exit 0 equal / 1 differ"""
import collections
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import hdref  # noqa: E402

DRAWN = ("idx", "pal", "fp", "offx", "offy", "hm", "vm", "bgp", "sci")
Lane = collections.namedtuple("Lane", "tx0 n key offx0 offy hm vm bgp sy sk")


def sig(r):
    return tuple(getattr(r, k) for k in DRAWN)


def scroll_y(t):
    return (((t & 0x3E0) >> 2) | ((t & 0x7000) >> 12)) + (240 if t & 0x800 else 0)


def build(ref):
    sc = ref.screen
    adds = ref.additions
    order = {id(a): i for i, a in enumerate(adds)}
    lanes = [[] for _ in range(241)]
    stats = collections.Counter()
    yscroll = scroll_y(sc[0].t)
    tmpv = sc[0].t
    process_bg = True
    for y in range(240):
        t = sc[y << 8].t
        if ((yscroll + y) & 7) == 0 or tmpv != t:
            yscroll = scroll_y(t)
            tmpv = t
            process_bg = True
        scan_bg = process_bg
        process_bg = False
        # sources: (k, member pixels in x order with their source records)
        srcs = collections.defaultdict(list)       # (k, instance) -> [(x, rec)]
        for x in range(256):
            p = sc[(y << 8) | x]
            for k, s in enumerate(p.spr):
                if ref.additions_for(s):
                    srcs[(k, s.inst)].append((x, s))
            if scan_bg and p.tile.idx != hdref.NOTILE and ref.additions_for(p.tile):
                process_bg = True
                srcs[(4, ("bg", p.tile.idx, p.tile.pal, p.tile.offy))].append((x, p.tile))
        line_lanes = []
        for (k, inst), mem in srcs.items():
            # runs: consecutive x, offx stepping by one
            runs = []
            for x, r in mem:
                if runs and x == runs[-1][-1][0] + 1 and r.offx == runs[-1][-1][1].offx + 1:
                    runs[-1].append((x, r))
                else:
                    runs.append([(x, r)])
            for run in runs:
                r0 = run[0][1]
                for a in ref.additions_for(r0):
                    dx = -a["ox"] if r0.hm else a["ox"]
                    dy = -a["oy"] if r0.vm else a["oy"]
                    ty = y + dy
                    if not 0 <= ty < 240:
                        continue
                    pix = [(x + dx, r) for x, r in run if 0 <= x + dx < 256]
                    if not pix:
                        continue
                    line_lanes.append(((-dx, k, order[id(a)]), ty,
                                       Lane(pix[0][0], len(pix), (a["apal"], a["aidx"], a["afp"]),
                                            pix[0][1].offx, r0.offy, r0.hm, r0.vm, r0.bgp, y,
                                            (-dx, k, order[id(a)]))))
        line_lanes.sort(key=lambda e: e[0])
        for _, ty, ln in line_lanes:
            lanes[ty].append(ln)
            stats["lanes"] += 1
    # virtual line 240 for pixel (0,0)
    for ln in lanes[239]:
        if ln.sy < 239 and ln.tx0 == 0:
            lanes[240].append(ln)
    for ln in lanes[0]:
        if ln.sy == 239 and ln.tx0 == 0:
            lanes[240].append(ln)
    stats["max_lanes_line"] = max(len(l) for l in lanes[:240])
    stats["lines_with_lanes"] = sum(1 for l in lanes[:240] if l)
    return lanes, stats


def read_list(ref, lanes, x, y):
    """(tile, sprite list, line fields) a reader reconstructs for pixel (x, y)."""
    sc = ref.screen
    if (x, y) == (0, 0):
        base, ly = sc[239 << 8], 240
    else:
        base, ly = sc[(y << 8) | x], y
    spr = [sig(s) for s in base.spr]
    for ln in lanes[ly]:
        if len(spr) >= 4:
            break
        if ln.tx0 <= x < ln.tx0 + ln.n:
            pal, idx, fp = ln.key
            spr.append((idx, pal, fp, ln.offx0 + (x - ln.tx0), ln.offy, ln.hm, ln.vm, ln.bgp, 0))
    first = sc[239 << 8] if y == 0 else sc[y << 8]
    return sig(base.tile), spr, (first.t, first.finex, first.gray, first.emph)


def main():
    pack, recdir, gr = sys.argv[1], sys.argv[2], int(sys.argv[3])
    h = hdref.Hdp3(open(pack, "rb").read())
    worst = 0
    for f in sys.argv[4:]:
        f = int(f)
        rec = open(os.path.join(recdir, f"rec_{f:04d}.bin"), "rb").read()
        watch = open(os.path.join(recdir, f"watch_{f:04d}.bin"), "rb").read()
        ref = hdref.HdRef(h, rec, watch, bool(gr))
        lanes, st = build(ref)
        mine = [read_list(ref, lanes, i & 255, i >> 8) for i in range(256 * 240)]
        ref.process_additions()
        bad = 0
        for i, p in enumerate(ref.screen):
            x, y = i & 255, i >> 8
            first = ref.screen[y << 8]
            got = (sig(p.tile), [sig(s) for s in p.spr],
                   (first.t, first.finex, first.gray, first.emph))
            if got != mine[i]:
                if bad < 5:
                    print(f"frame {f}: pixel ({x},{y}) differs\n  ref {got}\n  hw  {mine[i]}")
                bad += 1
        print(f"frame {f}: {bad} pixels differ; {st['lanes']} lanes, max {st['max_lanes_line']} on "
              f"a line, {st['lines_with_lanes']} lines with lanes, (0,0) lanes {len(lanes[240])}, "
              f"{ref.stats['additions']} inserted")
        worst = max(worst, bad)
    return 1 if worst else 0


if __name__ == "__main__":
    sys.exit(main())
