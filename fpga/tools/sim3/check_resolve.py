"""Compare tb_resolve.exe's read-back of hd3_resolve with resolve_golden.py.

For every record of every frame:
  via 0 (no list)   -> kind 0
  via != 0          -> kind 1 or 2, the record table's list offset == hd3_dict's
  kind 1            -> its rules (payload, fptr, wptr, prefix), in order, and last_prefix
                       equal the golden list at that offset
  kind 2            -> accepted only with --allow-unfiltered / --expect-unfiltered (the rule
                       store filled; render walks that list from DDR3)
Every golden list must be reached by some record, and the rule store must not overflow unless
allowed. --expect-unfiltered (a build with a lowered RS_MAX) also REQUIRES it to overflow.

usage: python check_resolve.py tb.tsv golden_frame0.tsv [golden_frame1.tsv ...] [flags]
       (one golden per --frame, in order)
"""
import sys


def load_golden(path):
    lists, cur = {}, None
    head = None
    with open(path) as f:
        for ln in f:
            p = ln.split()
            if not p:
                continue
            if head is None and ln.startswith("#") and not ln.startswith("#list"):
                head = ln[1:].split()
                continue
            if p[0] == "#list":
                cur = int(p[1])
                lists[cur] = {"lastp": int(p[3]), "rules": []}
            elif p[0] == "rule":
                lists[cur]["rules"].append(tuple(int(x) for x in p[1:5]))
    return head, lists


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    expect_unf = "--expect-unfiltered" in sys.argv     # a build with a lowered RS_MAX
    allow_unf = expect_unf or "--allow-unfiltered" in sys.argv
    if len(args) < 2:
        print(__doc__)
        return 2
    tb, goldens = args[0], [load_golden(g) for g in args[1:]]
    recs, rules, frames = {}, {}, {}
    with open(tb) as f:
        for ln in f:
            p = ln.split()
            if p[0] == "rec":
                fr, rid = int(p[1]), int(p[2])
                recs[(fr, rid)] = dict(via=int(p[3]), offq=int(p[4]), kind=int(p[5]),
                                       lastp=int(p[6]), count=int(p[7]), start=int(p[8]),
                                       roffq=int(p[9]))
                rules[(fr, rid)] = []
            elif p[0] == "rule":
                rules[(int(p[1]), int(p[2]))].append(tuple(int(x) for x in p[3:7]))
            elif p[0] == "#frame":
                frames[int(p[1])] = dict(nrec=int(p[5]), cycles=int(p[7]),
                                         dov=int(p[9]), rov=int(p[10]))
    bad, checked, unfiltered = [], 0, 0
    for fr, (head, lists) in enumerate(goldens):
        if fr not in frames:
            bad.append(f"frame {fr}: no read-back")
            continue
        if frames[fr]["dov"]:
            bad.append(f"frame {fr}: hd3_dict overflow")
        if frames[fr]["rov"] and not allow_unf:
            bad.append(f"frame {fr}: rule store overflow")
        seen = set()
        for rid in range(frames[fr]["nrec"]):
            r = recs.get((fr, rid))
            if r is None:
                bad.append(f"frame {fr} rid {rid}: missing")
                continue
            checked += 1
            if r["via"] == 0:
                if r["kind"] != 0:
                    bad.append(f"frame {fr} rid {rid}: no list but kind {r['kind']}")
                continue
            off = r["offq"] * 8
            seen.add(off)
            if r["kind"] not in (1, 2) or r["roffq"] != r["offq"]:
                bad.append(f"frame {fr} rid {rid}: kind {r['kind']} offq {r['roffq']} "
                           f"(dict says {r['offq']})")
                continue
            g = lists.get(off)
            if g is None:
                bad.append(f"frame {fr} rid {rid}: list {off} not in the golden")
                continue
            if r["kind"] == 2:
                unfiltered += 1
                continue
            got = rules[(fr, rid)]
            if r["lastp"] != g["lastp"]:
                bad.append(f"frame {fr} rid {rid} list {off}: last_prefix {r['lastp']} "
                           f"!= {g['lastp']}")
            if got != g["rules"]:
                n = next((i for i, (a, b) in enumerate(zip(got, g["rules"])) if a != b),
                         min(len(got), len(g["rules"])))
                bad.append(f"frame {fr} rid {rid} list {off}: {len(got)} rules, golden "
                           f"{len(g['rules'])}; first difference at {n}: "
                           f"{got[n] if n < len(got) else '-'} vs "
                           f"{g['rules'][n] if n < len(g['rules']) else '-'}")
        for off in lists:
            if off not in seen:
                bad.append(f"frame {fr}: golden list {off} reached by no record")
    if expect_unf and not (unfiltered and any(v["rov"] for v in frames.values())):
        bad.append("expected the rule store to fill (overflow + unfiltered records): it did not")
    for b in bad[:25]:
        print("MISMATCH", b)
    cyc = max((v["cycles"] for v in frames.values()), default=0)
    print(f"{tb}: {checked} records, {sum(len(l) for _, l in goldens)} lists checked, "
          f"{unfiltered} unfiltered, longest RESOLVE {cyc} clocks, {len(bad)} mismatches")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
