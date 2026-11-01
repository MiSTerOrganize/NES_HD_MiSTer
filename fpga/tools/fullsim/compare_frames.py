"""Compare a reference picture (e.g. a Mesen 2 screenshot) against a range of fullsim frames.

usage: python compare_frames.py <reference.png> <fullsim_out_dir> [prefix] [first] [last] [--exact]
  prefix   nes (default), vid or hd - which fullsim picture to compare
  --exact  compare RGB values exactly (only meaningful when both used the same palette)
By default the comparison is palette-independent: each reference colour is mapped to the
fullsim colour it most often lands on, and a pixel counts as differing when it breaks that
mapping (or when two reference colours share one fullsim colour). This is what you want for a
Mesen screenshot, whose default palette is not Kitrinx34.
Prints, per frame, the number of differing pixels, and the best match.
"""
import os
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from pngio import read_png  # noqa: E402


def count_diff(rrows, rows, w, h, exact):
    if exact:
        return sum(1 for y in range(h) for x in range(w) if rows[y][x][:3] != rrows[y][x][:3])
    pairs = Counter((rrows[y][x][:3], rows[y][x][:3]) for y in range(h) for x in range(w))
    by_ref = defaultdict(list)
    for (rc, sc), n in pairs.items():
        by_ref[rc].append((n, sc))
    mapping = {rc: max(lst)[1] for rc, lst in by_ref.items()}
    # a fullsim colour claimed by two reference colours: only the larger claim is consistent
    owner = {}
    for rc, sc in mapping.items():
        n = pairs[(rc, sc)]
        if sc not in owner or n > owner[sc][0]:
            owner[sc] = (n, rc)
    good = sum(pairs[(rc, sc)] for rc, sc in mapping.items() if owner[sc][1] == rc)
    return w * h - good


def main():
    args = [a for a in sys.argv[1:] if a != "--exact"]
    exact = "--exact" in sys.argv
    if len(args) < 2:
        print(__doc__)
        return 2
    ref_path, out_dir = args[0], args[1]
    prefix = args[2] if len(args) > 2 else "nes"
    first = int(args[3]) if len(args) > 3 else 1
    last = int(args[4]) if len(args) > 4 else 9999
    rw, rh, rrows = read_png(ref_path)
    best = None
    for f in range(first, last + 1):
        p = os.path.join(out_dir, "%s_%04d.png" % (prefix, f))
        if not os.path.exists(p):
            continue
        w, h, rows = read_png(p)
        if (w, h) != (rw, rh):
            print("frame %d: size %dx%d != reference %dx%d" % (f, w, h, rw, rh))
            continue
        diff = count_diff(rrows, rows, w, h, exact)
        print("frame %4d: %6d differing pixels" % (f, diff))
        if best is None or diff < best[1]:
            best = (f, diff)
    if best is None:
        print("no frames found")
        return 1
    print("best match: frame %d with %d differing pixels of %d" % (best[0], best[1], rw * rh))
    return 0


if __name__ == "__main__":
    sys.exit(main())
