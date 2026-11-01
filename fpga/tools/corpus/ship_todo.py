"""ship_todo.py OUT [OUT ...] - which shipped packs (ship_plan.tsv) still need converting.

A shipped job needs (re)building when no OUT dir holds an OK <job>.hdp, or when that .hdp is
older than the newest file in any of the job's layers (an overlay changed after the build).
Prints a summary and writes Z:/NES_HDPack_work/ship_todo.txt (one job per line, for
convert_corpus.py --only). The newest OK build across the OUT dirs, in order, is the one kept.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import convert_corpus  # noqa: E402

X = "Z:/NES_HDPack_work/x"
RECIPES = os.path.join(HERE, "..", "..", "..", "NES_HDPack_testdata", "pack_recipes.tsv")
PLAN = "Z:/NES_HDPack_work/ship_plan.tsv"
TODO = "Z:/NES_HDPack_work/ship_todo.txt"


def newest(path):
    t = 0.0
    for dp, _dn, fn in os.walk(path):
        for f in fn:
            t = max(t, os.path.getmtime(os.path.join(dp, f)))
    return t


def built(outdirs, layers):
    """{job: (hdp path, mtime)} for every OK row, the latest build winning. A row whose pack
    folder is not the job's folder today is ignored: plain jobs are numbered by folder order,
    so a name in an older out dir can mean a different pack."""
    norm = lambda p: os.path.normcase(os.path.normpath(p))
    out = {}
    for d in outdirs:
        for f in os.listdir(d):
            if not (f.startswith("convert_corpus") and f.endswith(".tsv")):
                continue
            for line in open(os.path.join(d, f), encoding="utf-8"):
                c = line.split("\t")
                if len(c) < 5 or c[1] != "OK" or c[0] not in layers:
                    continue
                if norm(c[4]) != norm(layers[c[0]][0]):
                    continue
                p = os.path.join(d, c[0] + ".hdp")
                if os.path.isfile(p) and (c[0] not in out or os.path.getmtime(p) > out[c[0]][1]):
                    out[c[0]] = (p, os.path.getmtime(p))
    return out


def main():
    outdirs = sys.argv[1:]
    if not outdirs:
        raise SystemExit(__doc__)
    jobs, plain, _ = convert_corpus.load_jobs(X, RECIPES)
    layers = {n: [d] + list(b) for n, d, b, _r in jobs + plain}
    ship = [l.split("\t")[0] for l in open(PLAN, encoding="utf-8").read().splitlines()[1:] if l]
    have = built(outdirs, layers)
    todo, stale, missing = [], 0, 0
    for n in ship:
        if n not in have:
            todo.append(n)
            missing += 1
        elif max(newest(L) for L in layers[n]) > have[n][1]:
            todo.append(n)
            stale += 1
    with open(TODO, "w", encoding="utf-8", newline="\n") as f:
        f.write("".join(n + "\n" for n in todo))
    print(f"{len(ship)} shipped: {len(ship) - len(todo)} built and current, {missing} not built, "
          f"{stale} built before their files changed -> {TODO}")


if __name__ == "__main__":
    main()
