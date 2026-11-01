"""Rebuild the WHOLE converted corpus with the current converter, recipes applied, each output
checked with hdp3_read.

Plain packs: every folder under the extract root holding hires.txt, named p<index>.hdp, the index
being the folder's position in the sorted walk. A folder named in pack_recipes.tsv is built from
its recipe instead (--base / --rom) under the recipe's out_name, and skipped in the plain pass.

Recordings, pack_roms_manual.tsv and corpus_plan key on the p<index> names, so a renumbering would
silently attach packs to the wrong game. --previous <results.tsv> compares every plain name with
the folder an earlier run gave it and REFUSES to start if any name now points elsewhere. A name
the previous run did not have is reported as new.

Resumable: a result line in <out>/convert_corpus.tsv means done.

usage: python -I convert_corpus.py <extract-root> <out-dir> <pack_recipes.tsv>
           [--previous old_results.tsv] [--samples N] [--dry-run] [--shard K/N] [--only names.txt]
--only names.txt builds only the jobs named there, one per line (an unknown name refuses).
--shard K/N runs every Nth job only, for N parallel processes on one out dir; each writes
convert_corpus.sK.tsv. Concatenate them into convert_corpus.tsv when all N have finished.
"""
import os
import subprocess
import sys
import time

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROMS = "Z:/MiSTer_Organize/RomRoot/MiSTer_Console/MiSTer_Console/games/NES/1 NES/1 USA"


def norm(p):
    return os.path.normcase(os.path.normpath(p))


def run(args):
    return subprocess.run([sys.executable, "-I"] + args, capture_output=True, encoding="utf-8",
                          errors="replace", timeout=6 * 3600)


def arg(name, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def load_jobs(root, recipes_file):
    jobs, recipe_dirs = [], set()           # (name, pack, bases, rom)
    with open(recipes_file, encoding="utf-8") as f:
        for line in f:
            if not line.strip() or line.startswith("#"):
                continue
            name, pack, base, rom = line.rstrip("\n").split("\t")
            pack = os.path.join(root, pack)
            bases = [] if base == "-" else [os.path.join(root, b) for b in base.split(";")]
            rom = None if rom == "-" else os.path.normpath(os.path.join(ROMS, rom))
            for p in [pack] + bases + ([rom] if rom else []):
                if not os.path.exists(p):
                    raise SystemExit(f"recipe {name}: {p} does not exist")
            recipe_dirs.add(norm(pack))
            jobs.append((name, pack, bases, rom))
    packs = sorted(dp for dp, dn, fn in os.walk(root) if any(x.lower() == "hires.txt" for x in fn))
    plain = [(f"p{i:03d}", d, [], None) for i, d in enumerate(packs) if norm(d) not in recipe_dirs]
    names = [j[0] for j in jobs + plain]
    if len(names) != len(set(names)):
        raise SystemExit("two jobs share an output name")
    return jobs, plain, len(packs)


def check_numbering(jobs, plain, previous):
    """Every p<index> name the previous run produced must still exist and name the same folder,
    whether it is now plain or a recipe kept under that name (p077: Galaga, given its ROM)."""
    old = {}
    with open(previous, encoding="utf-8") as f:
        for line in f:
            c = line.rstrip("\n").split("\t")
            if len(c) >= 5 and c[0].startswith("p") and c[0][1:].isdigit():
                old[c[0]] = norm(c[4])
    now = {n: norm(d) for n, d, _, _ in jobs + plain}
    moved = [(n, old[n], now[n]) for n in sorted(old) if n in now and now[n] != old[n]]
    gone = sorted(set(old) - set(now))
    new = [n for n, _, _, _ in plain if n not in old]
    for n, a, b in moved:
        print(f"MOVED   {n}: was {a}\n                now {b}")
    for n in gone:
        print(f"GONE    {n}: {old[n]}")
    for n in new:
        print(f"NEW     {n}: {now[n]}")
    print(f"numbering vs {previous}: {len(old)} old plain names, {len(moved)} moved, "
          f"{len(gone)} gone, {len(new)} new")
    return not moved and not gone


def main():
    root, outdir, recipes_file = sys.argv[1:4]
    samples = arg("--samples", "300")
    jobs, plain, npacks = load_jobs(root, recipes_file)
    print(f"{npacks} pack folders, {len(jobs)} recipes, {len(plain)} plain", flush=True)
    if arg("--previous") and not check_numbering(jobs, plain, arg("--previous")):
        raise SystemExit("REFUSED: a plain pack name would now point at a different folder")
    if "--dry-run" in sys.argv:
        for name, d, bases, rom in jobs + plain:
            print(f"{name}\t{d}\t{';'.join(bases) or '-'}\t{rom or '-'}")
        return
    os.makedirs(outdir, exist_ok=True)
    # --shard K/N: run only every Nth job (K = 0..N-1), so N processes can share one out dir.
    # Each shard appends to its own convert_corpus.sK.tsv; every run reads all of them as done.
    shard = arg("--shard")
    k, n = (int(x) for x in shard.split("/")) if shard else (0, 1)
    if not 0 <= k < n:
        raise SystemExit(f"--shard {shard}: need 0 <= K < N")
    tsv = os.path.join(outdir, f"convert_corpus.s{k}.tsv" if shard else "convert_corpus.tsv")
    done = set()
    for f_name in os.listdir(outdir):
        if f_name.startswith("convert_corpus") and f_name.endswith(".tsv"):
            with open(os.path.join(outdir, f_name), encoding="utf-8") as f:
                done |= {line.split("\t")[0] for line in f if line.strip()}
    todo = jobs + plain
    if arg("--only"):
        with open(arg("--only"), encoding="utf-8") as f:
            only = {line.strip() for line in f if line.strip() and not line.startswith("#")}
        unknown = only - {j[0] for j in todo}
        if unknown:
            raise SystemExit(f"--only names no job: {', '.join(sorted(unknown))}")
        todo = [j for j in todo if j[0] in only]
    for i, (name, d, bases, rom) in enumerate(todo):
        if name in done or i % n != k:
            continue
        out = os.path.join(outdir, f"{name}.hdp")
        extra = [a for b in bases for a in ("--base", b)] + (["--rom", rom] if rom else [])
        t0 = time.time()
        r = run([os.path.join(TOOLS, "hdp3_convert.py"), d, out] + extra)
        conv = (r.stdout + r.stderr).strip().replace("\n", " | ")
        if r.returncode != 0:
            status, size, detail = "REFUSED", 0, conv[-400:]
        else:
            size = os.path.getsize(out)
            r2 = run([os.path.join(TOOLS, "hdp3_read.py"), out, d, "--samples", samples] + extra)
            status = "OK" if r2.returncode == 0 else "CHECKFAIL"
            detail = conv[-300:] + " || " + (r2.stdout + r2.stderr).strip().replace("\n", " | ")[-500:]
        print(f"{status:9} {time.time() - t0:6.0f}s {name} {d}", flush=True)
        with open(tsv, "a", encoding="utf-8") as f:
            f.write(f"{name}\t{status}\t{time.time() - t0:.0f}\t{size}\t{d}\t{detail}\n")


if __name__ == "__main__":
    main()
