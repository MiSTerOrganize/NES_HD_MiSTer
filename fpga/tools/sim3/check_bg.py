"""Compare tb_resolve.exe's background selection read-back (8i) with bg_golden.py.

Per frame, all 40 levels must hold the entry the golden picked (or nothing), the memo seed
must hold exactly the golden's rewrite-sensitive conditions with the same values, and the
sticky flags must be clear: bg_lin (an indexed level scanned linearly) never happens on a
pack whose candidate lists fit the bitmap, and bg_warn (sticky) only from the first frame
whose golden has a seedwarn line onward.

usage: python check_bg.py tb.tsv golden_frame0.tsv [golden_frame1.tsv ...]
"""
import sys


def load_golden(path):
    lv, seed, warn = {}, {}, False
    with open(path) as f:
        for ln in f:
            p = ln.split()
            if not p:
                continue
            if p[0] == "lvl":
                lv[int(p[1])] = int(p[2])
            elif p[0] == "seed":
                seed[int(p[1])] = int(p[2])
            elif p[0] == "seedwarn":
                warn = True
    return lv, seed, warn


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    tb, goldens = sys.argv[1], [load_golden(g) for g in sys.argv[2:]]
    lv, seed, flags = {}, {}, {}
    with open(tb) as f:
        for ln in f:
            p = ln.split()
            if not p:
                continue
            if p[0] == "bg":
                lv[(int(p[1]), int(p[2]))] = int(p[3])
            elif p[0] == "seed":
                seed.setdefault(int(p[1]), {})[int(p[2])] = int(p[3])
            elif p[0] == "bgflags":
                flags[int(p[1])] = (int(p[2]), int(p[3]))
    bad, sel, seeded, anywarn = [], 0, 0, False
    for fr, (glv, gseed, gwarn) in enumerate(goldens):
        anywarn |= gwarn                   # bg_warn is sticky: it stays set once raised
        if fr not in flags:
            bad.append(f"frame {fr}: no background read-back")
            continue
        for lvl in range(40):
            got, want = lv.get((fr, lvl)), glv.get(lvl, -1)
            if got != want:
                bad.append(f"frame {fr} level {lvl}: selected {got}, golden {want}")
            sel += want >= 0
        s = seed.get(fr, {})
        if s != gseed:
            extra = {k: v for k, v in s.items() if gseed.get(k) != v}
            miss = {k: v for k, v in gseed.items() if s.get(k) != v}
            bad.append(f"frame {fr}: seed differs (rtl only {extra}, golden only {miss})")
        seeded += len(gseed)
        lin, warn = flags[fr]
        if lin:
            bad.append(f"frame {fr}: an indexed level was scanned linearly (bg_lin)")
        if warn != int(anywarn):
            bad.append(f"frame {fr}: bg_warn {warn}, golden expects {int(anywarn)}")
    for b in bad[:20]:
        print("  " + b)
    print(f"{sel} selections and {seeded} seeds over {len(goldens)} frames, "
          f"{len(bad)} mismatches")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
