"""Check tb_add.exe's lanes (hd3_add, 8a) against the model.

For every frame of the run, addhw.build gives the model's lanes (addhw.py is itself checked
against hdref.process_additions on every pixel). The check is what a reader sees: for every
pixel (x, y) - and pixel (0,0) through virtual line 240 - the lanes of its line covering x, in
slot order, each as {added palette, added body, column at x, row, hm, vm, bgp}, must equal the
model's. (Lanes whose sort keys tie cover disjoint pixels, so this fixes their order wherever
it shows; how a run is cut into lanes is not checked, only what is read.)

Overflow: a frame whose model needs more than NL lanes on a line (or the 64 a source line can
emit), or whose pass the testbench aborted (out of time), must come back with ovf set and is
not compared further; any other frame must not set ovf. A frame whose dictionary overflowed
(its records are incomplete: RENDER draws it with no lookups) is reported and skipped.

usage: python check_add.py OUT.tsv PACK.hdp RECDIR FRAME [FRAME...]   (frames in run order)
exit 0 equal, 1 a difference"""
import collections
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import addhw  # noqa: E402
import hdref  # noqa: E402

NB = 64


def read(path):
    lanes = collections.defaultdict(lambda: collections.defaultdict(list))
    meta = {}
    nl = game_ram = None
    for ln in open(path, encoding="utf-8"):
        if ln.startswith("#nl"):
            p = ln.split()
            nl, game_ram = int(p[1]), int(p[3])
            continue
        if ln.startswith("#frame"):
            p = ln.split()
            meta[int(p[1])] = {p[i]: int(p[i + 1]) for i in range(2, len(p) - 1, 2)}
            continue
        if ln.startswith("frame"):
            continue
        f = ln.rstrip("\n").split("\t")
        k, y = int(f[0]), int(f[1])
        x0, n, col, row, hm, vm, bgp = (int(v) for v in f[3:10])
        lanes[k][y].append((x0, n, col, row, hm, vm, bgp, int(f[11], 16), int(f[12], 16)))
    return lanes, meta, nl, game_ram


def covering(lanes, x):
    out = []
    for x0, n, col, row, hm, vm, bgp, pal, body in lanes:
        if x0 <= x < x0 + n:
            out.append((pal, body, (col + x - x0) & 7, row, hm, vm, bgp))
    return out


def main():
    a = sys.argv[1:]
    tsv, pack, recdir = a[0], a[1], a[2]
    frames = [int(v) for v in a[3:]]
    got, meta, nl, game_ram = read(tsv)
    h = hdref.Hdp3(open(pack, "rb").read())
    bad = checked = 0
    for k, fr in enumerate(frames):
        if k not in meta:
            print(f"frame {k} ({fr}): no read-back")
            bad += 1
            continue
        m = meta[k]
        if m.get("dict_ovf"):
            print(f"frame {k} ({fr}): dictionary overflowed - not compared")
            continue
        if m.get("aborted"):
            # out of time (tb --abort): the frame must be flagged, its lanes are not used
            if not m["ovf"]:
                print(f"frame {k} ({fr}): aborted but ovf not set")
                bad += 1
            else:
                print(f"frame {k} ({fr}): aborted, overflow as required")
            continue
        rec = open(os.path.join(recdir, f"rec_{fr:04d}.bin"), "rb").read()
        watch = open(os.path.join(recdir, f"watch_{fr:04d}.bin"), "rb").read()
        ref = hdref.HdRef(h, rec, watch, bool(game_ram))
        want, _ = addhw.build(ref)
        per_src = collections.Counter(ln.sy for ty in range(241) for ln in want[ty] if ty < 240)
        need_ovf = max(len(want[ty]) for ty in range(241)) > nl or \
            (max(per_src.values()) if per_src else 0) > NB
        if need_ovf != bool(m["ovf"]):
            print(f"frame {k} ({fr}): ovf {m['ovf']}, the model {'needs' if need_ovf else 'does not need'}"
                  f" it (most lanes on a line {max(len(want[ty]) for ty in range(241))}, NL {nl})")
            bad += 1
            continue
        if need_ovf:
            print(f"frame {k} ({fr}): overflow as required")
            continue
        nbad = 0
        for y in range(241):
            mine = got[k][y]
            model = []
            for ln in want[y]:
                pal, idx, fp = ln.key
                body = (fp if game_ram else idx) & 0xFFFFFFFFFFFFFFFF
                model.append((ln.tx0, ln.n, ln.offx0, ln.offy, int(ln.hm), int(ln.vm),
                              int(ln.bgp), pal & 0xFFFFFFFF, body))
            for x in (range(1) if y == 240 else range(256)):
                g, w = covering(mine, x), covering(model, x)
                if g != w:
                    if nbad < 5:
                        print(f"frame {k} ({fr}): pixel ({x},{y}) rtl {g}\n    model {w}")
                    nbad += 1
                checked += 1
        if len(got[k][240]) != len(want[240]):
            print(f"frame {k} ({fr}): line 240 holds {len(got[k][240])} lanes, model {len(want[240])}")
            nbad += 1
        print(f"frame {k} ({fr}): {m['lanes']} lanes (model {sum(len(want[y]) for y in range(241))}), "
              f"{nbad} pixel differences, ADD {m['add_cycles']} clocks")
        bad += nbad
    print(f"{tsv}: {checked} pixels checked, {bad} differences")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
