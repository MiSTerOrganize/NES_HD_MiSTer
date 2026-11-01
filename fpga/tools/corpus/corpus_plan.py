"""corpus_plan.py - group the corpus packs into recordings.

One fullsim recording serves every pack that runs the SAME program the same way: the ROM the
core ends up with (the library ROM, patched by the pack's <patch> the core picks for it - the
file's SHA1, then its iNES 1.0 form's, MD5 lines keyed through romindex.tsv; rommatch.py, as
rom_expect.py does) and the sprite-limit option (disableSpriteLimit, options
bit 0, which the core applies while the pack is active and which changes the record). Each
group gets the union of its packs' watched addresses (watch_subset.py makes each pack's own
watch file from it afterwards).

Writes WORK/plan.tsv (group, game key, rom file, nolimit, packs) and per group WORK/gNN/:
rom.nes (what the core runs) and watch.txt (the union list).

    python -I corpus_plan.py pack_roms_auto.tsv pack_roms_manual.tsv WORK [OUT]
(OUT: the folder of converted .hdp files; default Z:/NES_HDPack_work/out)
"""
import hashlib
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import pack_fixes  # noqa: E402
import rommatch  # noqa: E402
import rompatch  # noqa: E402
from hdp3_read import Hdp3  # noqa: E402

INDEX = rommatch.load_index(os.path.join(HERE, "romindex.tsv"))

LIB = "Z:/MiSTer_Organize/RomRoot/MiSTer_Console/MiSTer_Console/games/NES"
PRIVATE = "Z:/MiSTer_Organize/RomRoot/MiSTer_Console_Private/MiSTer_Console_Private/games/NES_Private"
TESTDATA = os.path.normpath(os.path.join(HERE, "..", "..", "..", "NES_HDPack_testdata"))
OUT = "Z:/NES_HDPack_work/out"
PRIORITY = ["1 NES/1 USA/", "1 NES/1 World/", "1 NES/2 Japan/", "1 NES/2 Europe/",
            "1 NES/2 Revisions/", "1 NES/"]

def patch_lines(folder):
    """({SHA1 upper: path}, {MD5 upper: path}) from the pack's hires.txt <patch> lines (the hash
    is the last comma field; file names can contain commas), with pack_fixes.py's file-name
    corrections applied, as the pack model does. Read directly rather than loading the whole
    pack, which is not needed here."""
    for root, dirs, files in os.walk(folder):
        dirs.sort()
        for f in files:
            if f.lower() == "hires.txt":
                sha1s, md5s = {}, {}
                for line in open(os.path.join(root, f), encoding="utf-8", errors="replace"):
                    m = re.match(r"\s*<patch>(.*),\s*([0-9A-Fa-f]{40}|[0-9A-Fa-f]{32})\s*$", line)
                    if not m:
                        continue
                    name, digest = m.group(1).strip(), m.group(2).upper()
                    path = os.path.join(root, name)
                    if not os.path.isfile(path):
                        for fx in pack_fixes.PATCH_FILE_FIXES:
                            alt = os.path.join(root, fx["actual"])
                            if (fx["named"].lower() == name.lower() and fx["hash"] == digest
                                    and os.path.isfile(alt) and hashlib.md5(
                                        open(alt, "rb").read()).hexdigest() == fx["actual_md5"]):
                                path = alt
                    if os.path.isfile(path):
                        (sha1s if len(digest) == 40 else md5s)[digest] = path
                return sha1s, md5s
    return {}, {}


auto_p, man_p, work = sys.argv[1:4]
if len(sys.argv) > 4:                    # the converted packs (default: the 2026-10-17 build)
    OUT = sys.argv[4]
os.makedirs(work, exist_ok=True)

folder, rom = {}, {}
for line in open(auto_p, encoding="utf-8").read().splitlines()[1:]:
    f = line.split("\t")
    folder[f[0]] = f[1]
    if f[2] in ("supportedRom", "patch"):
        cands = f[3].split(" | ")
        rank = lambda p: next((i for i, k in enumerate(PRIORITY) if p.startswith(k)), len(PRIORITY))
        rom[f[0]] = sorted(cands, key=lambda p: (rank(p), p))[0]
for line in open(man_p, encoding="utf-8"):
    if line.startswith("#") or not line.strip():
        continue
    p, r, _why = line.rstrip("\n").split("\t")
    rom[p] = r

groups, skipped = {}, []
for p in sorted(rom, key=lambda s: (re.sub(r"\d+", "", s), int(re.sub(r"\D", "", s) or 0))):
    r = rom[p]
    if r.startswith("MISSING"):
        skipped.append((p, r))
        continue
    path = (os.path.join(PRIVATE, r[8:]) if r.startswith("PRIVATE:") else
            os.path.join(TESTDATA, r[9:]) if r.startswith("TESTDATA:") else os.path.join(LIB, r))
    data = open(path, "rb").read()
    sha1s, md5s = patch_lines(folder[p])
    keys = rommatch.section_keys(sha1s, md5s, INDEX)        # what the converter writes
    hit = rommatch.core_lookup(data, set(keys))             # what the core then picks
    run, patched = data, ""
    if hit:
        src, sha, label = hit
        try:
            run = rompatch.apply(src, open(keys[sha], "rb").read())
            patched = os.path.basename(keys[sha]) + label
        except rompatch.PatchError as e:
            patched = f"refused: {e}"
    h = Hdp3(open(f"{OUT}/{p}.hdp", "rb").read())
    key = (hashlib.sha1(run).hexdigest(), h.options & 1)
    g = groups.setdefault(key, {"rom": r, "run": run, "nolimit": h.options & 1, "packs": [], "watch": [],
                                "patch": set()})
    g["packs"].append(p)
    g["patch"].add(patched or "-")
    for a in h.watched:
        if a not in g["watch"]:
            g["watch"].append(a)

rows = []
for n, (key, g) in enumerate(sorted(groups.items(), key=lambda kv: kv[1]["rom"])):
    gd = os.path.join(work, f"g{n:02d}")
    os.makedirs(gd, exist_ok=True)
    open(os.path.join(gd, "rom.nes"), "wb").write(g["run"])
    if len(g["watch"]) > 256:
        sys.exit(f"g{n:02d}: union of {len(g['watch'])} watched addresses is over 256 - split the group")
    with open(os.path.join(gd, "watch.txt"), "w", newline="\n") as fh:
        fh.write(f"# union of {', '.join(g['packs'])}\n")
        for a in g["watch"]:
            fh.write(f"{a:08x}\n")
    game = os.path.splitext(os.path.basename(g["rom"]))[0]
    rows.append(f"g{n:02d}\t{game}\t{g['rom']}\t{g['nolimit']}\t{len(g['watch'])}\t"
                f"{','.join(sorted(g['patch']))}\t{' '.join(g['packs'])}")
with open(os.path.join(work, "plan.tsv"), "w", encoding="utf-8", newline="\n") as fh:
    fh.write("group\tgame\trom\tnolimit\twatched\tpatch\tpacks\n" + "\n".join(rows) + "\n")
print(f"{sum(len(g['packs']) for g in groups.values())} packs in {len(groups)} recordings; "
      f"{len(skipped)} packs without a ROM: {' '.join(p for p, _ in skipped)}")
