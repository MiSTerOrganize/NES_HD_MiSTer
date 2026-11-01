"""ship_stage.py OUT [OUT ...] [--apply] - stage the NES_HD collection from ship_plan.tsv.

Builds Z:/NES_HDPack_work/ship/NES_HD/ with
    HD_Packs/<hdp_name>     each shipped pack's newest OK build (ship_todo.built)
    1 NES_HD/<rom_file>     each ROM once, copied byte for byte from the library
    manifest.md5            md5 of every staged file, relative paths (md5sum -c format)
Refuses (exit 1, nothing written) if any shipped pack has no current build, any ROM is
missing, or two ROMs share a file name. Dry run by default.
"""
import hashlib
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import convert_corpus  # noqa: E402
import ship_plan  # noqa: E402
import ship_todo  # noqa: E402

STAGE = "Z:/NES_HDPack_work/ship/NES_HD"
APPLY = "--apply" in sys.argv


def md5(p):
    h = hashlib.md5()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    outdirs = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not outdirs:
        raise SystemExit(__doc__)
    # ship_todo.X, not ship_plan.X: ship_plan reads its root from argv, and here argv is OUT dirs
    jobs, plain, _ = convert_corpus.load_jobs(ship_todo.X, ship_plan.RECIPES)
    layers = {n: [d] + list(b) for n, d, b, _r in jobs + plain}
    rows = [l.split("\t") for l in open(ship_plan.OUT, encoding="utf-8").read().splitlines()[1:] if l]
    have = ship_todo.built(outdirs, layers)
    problems, packs, roms = [], [], {}
    for job, rom_ref, rom_file, hdp_name, _label in rows:
        if job not in have:
            problems.append(f"{job}: no OK build in {outdirs}")
        elif max(ship_todo.newest(L) for L in layers[job]) > have[job][1]:
            problems.append(f"{job}: build older than its files")
        else:
            packs.append((have[job][0], hdp_name))
        src = ship_plan.rom_path(rom_ref)
        if not os.path.isfile(src):
            problems.append(f"{rom_ref}: ROM missing")
        elif rom_file in roms and os.path.normcase(roms[rom_file]) != os.path.normcase(src):
            problems.append(f"{rom_file}: two different ROMs share this name")
        roms[rom_file] = src
    if problems:
        print("\n".join("REFUSED " + p for p in problems))
        sys.exit(1)
    print(f"{len(packs)} packs, {len(roms)} ROMs -> {STAGE}" + ("" if APPLY else "  (dry run)"))
    if not APPLY:
        return
    if os.path.isdir(STAGE):
        shutil.rmtree(STAGE)
    os.makedirs(os.path.join(STAGE, "HD_Packs"))
    os.makedirs(os.path.join(STAGE, "1 NES_HD"))
    lines = []
    for src, name in sorted(packs, key=lambda p: p[1].lower()):
        dst = os.path.join(STAGE, "HD_Packs", name)
        shutil.copyfile(src, dst)
        if md5(dst) != md5(src):
            raise SystemExit(f"copy mismatch: {dst}")
        lines.append(f"{md5(dst)}  HD_Packs/{name}")
    for name, src in sorted(roms.items(), key=lambda r: r[0].lower()):
        dst = os.path.join(STAGE, "1 NES_HD", name)
        shutil.copyfile(src, dst)
        if md5(dst) != md5(src):
            raise SystemExit(f"copy mismatch: {dst}")
        lines.append(f"{md5(dst)}  1 NES_HD/{name}")
    with open(os.path.join(STAGE, "manifest.md5"), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    print(f"staged, {len(lines)} files verified, manifest.md5 written")


if __name__ == "__main__":
    main()
