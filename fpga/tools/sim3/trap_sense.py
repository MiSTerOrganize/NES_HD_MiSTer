"""Does a fixture's condition actually reach the hd3_resolve output?

A condition can be set up so a bug flips its VALUE (make_pos_frame.py, make_edge_frame.py)
and still be invisible to the test: if it sits in a rule whose other conditions already fail,
or in a rule after the list's stop point, or is never evaluated at all, RESOLVE's output is
the same either way and the negative control misses the bug. This tool checks it directly:
for every frame condition of the chosen types that the golden evaluates, it recomputes the
golden with that one condition's result inverted and reports whether any list changed.

usage: python trap_sense.py <file.hdp> <recdir> <game_ram 0/1> <types> <frame> [frame ...]
  types: comma-separated condition type names (e.g. tileAtPosition,spriteAtPosition) or "all"
  frame: recording name, e.g. 0250
Exit 0 always; the report is the result. A type with 0 visible conditions is a fixture gap.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hdref  # noqa: E402
import hwmodel  # noqa: E402
from resolve_golden import golden_lists  # noqa: E402


def canon(lists):
    return {off: ([(r["payload"] & 0xFFFFFFFF, r["frame"] if later else 0, r["walk"],
                    bool(r["prefix"])) for r, later in keep], lastp)
            for off, (keep, lastp) in lists.items()}


def main():
    if len(sys.argv) < 6:
        print(__doc__)
        return 2
    hdp, recdir, gr, types, names = sys.argv[1], sys.argv[2], bool(int(sys.argv[3])), \
        sys.argv[4], sys.argv[5:]
    h = hdref.Hdp3(open(hdp, "rb").read())
    want = None if types == "all" else set(types.split(","))
    totals = {}
    for name in names:
        rec = open(os.path.join(recdir, f"rec_{name}.bin"), "rb").read()
        watch = open(os.path.join(recdir, f"watch_{name}.bin"), "rb").read()
        seen = set()

        class Rec(hwmodel.HwModel):
            def hw_eval(self, ci, x, y, r):
                seen.add(ci)
                return super().hw_eval(ci, x, y, r)

        base = canon(golden_lists(h, rec, watch, gr, Rec))
        probe = hwmodel.HwModel(h, rec, watch, gr)
        cands = sorted(ci for ci in seen
                       if want is None or probe.cond(ci)["type"] in want)
        for ci in cands:
            t = probe.cond(ci)["type"]

            class Flip(hwmodel.HwModel):
                def hw_eval(self, c, x, y, r, _ci=ci):
                    v = super().hw_eval(c, x, y, r)
                    return (not v) if c == _ci else v

            vis = canon(golden_lists(h, rec, watch, gr, Flip)) != base
            e = totals.setdefault(t, [0, 0])
            e[0] += 1
            e[1] += int(vis)
            print(f"frame {name} cond {ci} {t}: {'VISIBLE' if vis else 'invisible'}", flush=True)
    print("summary:")
    for t, (n, v) in sorted(totals.items()):
        print(f"  {t}: {v} of {n} evaluated conditions reach the output"
              + ("   <-- FIXTURE GAP" if v == 0 else ""))
    if not totals:
        print("  no condition of those types is evaluated on these frames   <-- FIXTURE GAP")
    return 0


if __name__ == "__main__":
    sys.exit(main())
