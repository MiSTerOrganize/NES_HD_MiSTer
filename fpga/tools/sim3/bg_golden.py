"""Golden reference for hd3_resolve's background selection (8i): for one recorded frame, the
entry hdref.select_backgrounds picks at each of the 40 levels, and the value of every
rewrite-sensitive frame condition it evaluated (render's memo is seeded with those).

It runs hdref's OWN select_backgrounds on the HwModel resolve_golden.py uses, so there is no
second copy of the selection rule to drift: the pack reader's bg_level / bg_rec are wrapped
to note which level is being scanned and which entry it chose.

    #bg <game_ram> <legacy>
    lvl <0-39> <payload | -1>          one line per level (-1 = nothing selected)
    seed <memo index> <0|1>            one line per rewrite-sensitive condition evaluated:
                                       its result BEFORE negation (render's memo format)
    seedwarn <condition index>         a sensitive condition whose memo index is >= 2048

usage: python bg_golden.py <file.hdp> <recdir> <frame> <out.tsv> --game-ram 0/1
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import hdref  # noqa: E402
import hwmodel  # noqa: E402


def golden_bg(h, rec, watch, game_ram):
    """({level: payload or None}, {memo index: value}, [sensitive conditions past the memo])"""
    m = hwmodel.HwModel(h, rec, watch, game_ram)
    picked = {lvl: None for lvl in range(40)}
    cur = [None]
    level0, rec0 = h.bg_level, h.bg_rec

    def bg_level(lvl):
        cur[0] = lvl
        return level0(lvl)

    def bg_rec(i):
        picked[cur[0]] = i
        return rec0(i)

    h.bg_level, h.bg_rec = bg_level, bg_rec
    try:
        m.select_backgrounds()
    finally:
        h.bg_level, h.bg_rec = level0, rec0

    # the seed holds what render's memo holds: the result BEFORE negation (hdref's memo holds
    # it after), since render negates on read
    seed, warn = {}, []
    for ci, v in m.memo.items():
        c = m.cond(ci)
        if not c["sens"]:
            continue
        if c["memo"] >= 2048:
            warn.append(ci)
        else:
            seed[c["memo"]] = bool(v) ^ c["negate"]
    return picked, seed, warn


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("hdp")
    ap.add_argument("recdir")
    ap.add_argument("frame", type=int)
    ap.add_argument("out")
    ap.add_argument("--game-ram", type=int, choices=(0, 1), required=True)
    a = ap.parse_args()
    h = hdref.Hdp3(open(a.hdp, "rb").read())
    rec = open(os.path.join(a.recdir, f"rec_{a.frame:04d}.bin"), "rb").read()
    watch = open(os.path.join(a.recdir, f"watch_{a.frame:04d}.bin"), "rb").read()
    picked, seed, warn = golden_bg(h, rec, watch, bool(a.game_ram))
    with open(a.out, "w") as f:
        f.write(f"#bg {a.game_ram} {int(bool(h.flags & 1))}\n")
        for lvl in range(40):
            p = picked[lvl]
            f.write(f"lvl {lvl} {-1 if p is None else p}\n")
        for k in sorted(seed):
            f.write(f"seed {k} {int(seed[k])}\n")
        for ci in warn:
            f.write(f"seedwarn {ci}\n")
    n = sum(p is not None for p in picked.values())
    print(f"{a.out}: {n} levels selected, {len(seed)} seeded, {len(warn)} past the memo")


if __name__ == "__main__":
    sys.exit(main())
