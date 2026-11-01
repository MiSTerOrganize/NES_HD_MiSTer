"""collection_check.py - is EVERY file each corpus pack needs actually there? Read-only.

For every job convert_corpus.py builds (recipes + plain packs), on the files the player gets
(the job folder laid over its --base folders, exactly as hdp3_convert.load_pack sees them):

  1. the pack loads at all (a missing <img> rejects the whole pack);
  2. every message the pack model logs, except lines pack_fixes.py already repairs: one that
     means a named file is not there (OGG/background/patch not found, an image index past the
     image list) is a problem; any other (condition not defined, version too low for a tag...)
     is the note Mesen logs for the same line and is counted in the last column;
  3. every graphics file (<img>, backgrounds), audio file (<bgm>/<sfx>) and patch file is
     present, non-empty and starts with the right signature (PNG / OggS / IPS-BPS-UPS); and,
     read straight from the hires.txt text, every file ANY line names is present - including
     lines the model rejects for another reason first (an MD5 <patch> hash, a long <bgm>);
  4. the game ROM: resolved from the recipe's ROM, pack_roms_manual.tsv, pack_roms_auto.tsv,
     the pack's own <supportedRom>/<patch> hashes against romindex.tsv, or the job it is laid
     over - and the ROM file must exist;
  5. when the pack has <patch> lines, one of them must match that ROM (raw or iNES 1.0 form,
     MD5 lines keyed through romindex.tsv - what the core does) and the patch must apply.

A job that fails is reported with every reason, and with the jobs (if any) that are laid over
its folder and pass - those are the complete builds of the same pack.

    python collection_check.py [x-root] [recipes.tsv]   -> collection_check.tsv + summary
Exit 0 only when no job has a problem.
"""
import collections
import hashlib
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
sys.path.insert(0, TOOLS)
sys.path.insert(0, HERE)
import convert_corpus  # noqa: E402
import hdp3_convert  # noqa: E402
import rommatch  # noqa: E402
import rompatch  # noqa: E402

ROOT = sys.argv[1] if len(sys.argv) > 1 else "Z:/NES_HDPack_work/x"
RECIPES = sys.argv[2] if len(sys.argv) > 2 else os.path.join(
    TOOLS, "..", "..", "NES_HDPack_testdata", "pack_recipes.tsv")
LIB = "Z:/MiSTer_Organize/RomRoot/MiSTer_Console/MiSTer_Console/games/NES"
PRIVATE = "Z:/MiSTer_Organize/RomRoot/MiSTer_Console_Private/MiSTer_Console_Private/games/NES_Private"
TESTDATA = os.path.normpath(os.path.join(TOOLS, "..", "..", "NES_HDPack_testdata"))
PRIORITY = ["1 NES/1 USA/", "1 NES/1 World/", "1 NES/2 Japan/", "1 NES/2 Europe/",
            "1 NES/2 Revisions/", "1 NES/"]
INDEX = rommatch.load_index(os.path.join(HERE, "romindex.tsv"))
SIG = {"png": (b"\x89PNG\r\n\x1a\n",), "ogg": (b"OggS",), "patch": (b"PATCH", b"BPS1", b"UPS1")}
# model messages that mean a file the pack names is not there (the line is dropped for that)
LACKS = re.compile(r"OGG file not found|Error while loading background|Patch file not found|"
                   r"Invalid bitmap index|Image file not found|not found: .*\.(png|ogg|ips|bps|ups)",
                   re.I)
# a line naming a file: <img>F  <background>F,..  <patch>F,..  <bgm>a,t,F,..  <sfx>a,t,F,..
REF = re.compile(r"^\s*(?:\[[^\]]*\])?\s*<(img|background|patch|bgm|sfx)>(.*)$", re.I)


def norm(p):
    return os.path.normcase(os.path.normpath(p))


def rank(p):
    return next((i for i, k in enumerate(PRIORITY) if p.startswith(k)), len(PRIORITY))


def lib_path(r):
    if r.startswith("PRIVATE:"):     # the library's private set (NES_Private: translations, hacks)
        return os.path.join(PRIVATE, r[8:])
    return os.path.join(TESTDATA, r[9:]) if r.startswith("TESTDATA:") else os.path.join(LIB, r)


def table_roms():
    auto, man = {}, {}
    for line in open(os.path.join(HERE, "pack_roms_auto.tsv"), encoding="utf-8").read().splitlines()[1:]:
        f = line.split("\t")
        if len(f) > 3 and f[2] in ("supportedRom", "patch", "match") and f[3]:
            auto[f[0]] = sorted(f[3].split(" | "), key=lambda p: (rank(p), p))[0]
    for line in open(os.path.join(HERE, "pack_roms_manual.tsv"), encoding="utf-8"):
        if line.startswith("#") or not line.strip():
            continue
        p, r = line.rstrip("\n").split("\t")[:2]
        man[p] = r
    return auto, man


def hash_roms(hires):
    """Library ROMs (relative paths) any <supportedRom>/<patch> hash of this hires.txt names."""
    digests = set()
    for line in hires.splitlines():
        m = re.match(r"\s*<(supportedRom|patch)>(.*)$", line, re.I)
        if m:
            for h in re.findall(r"\b([0-9A-Fa-f]{40}|[0-9A-Fa-f]{32})\b", m.group(2)):
                digests.add(h.lower())
    hits = set()
    for row in INDEX:
        if digests & {row.get(k, "").lower() for k in
                      ("sha1", "md5", "body_sha1", "body_md5", "ines1_sha1", "ines1_md5")}:
            hits.add(row["path"])
    return sorted(hits, key=lambda p: (rank(p), p))


def patch_rom(pk, patch_files):
    """Library ROM a <patch> line of this pack applies to (whole-file SHA1, its iNES 1.0 form,
    or an MD5 line keyed through romindex.tsv), or None."""
    want = {k.lower() for k in pk.patches} | {k.lower() for k in pk.patches_md5}
    for row in sorted(INDEX, key=lambda r: (rank(r["path"]), r["path"])):
        if want & {row.get("sha1", "").lower(), row.get("ines1_sha1", "").lower(),
                   row.get("md5", "").lower(), row.get("ines1_md5", "").lower()}:
            return row["path"]
    return None


def file_check(pk, name, kind):
    if not pk.has(name):
        return f"{kind} missing: {name}"
    try:
        data = pk.read(name)
    except OSError as e:
        return f"{kind} unreadable: {name} ({e})"
    if not data:
        return f"{kind} empty: {name}"
    sig = "ogg" if kind == "audio" else "patch" if kind == "patch" else "png"
    if not data.startswith(SIG[sig]):
        return f"{kind} not a {sig.upper()} file: {name} (starts {data[:8].hex()})"
    return None


def main():
    jobs, plain, _ = convert_corpus.load_jobs(ROOT, RECIPES)
    alljobs = jobs + plain
    auto, man = table_roms()
    by_dir = {norm(d): name for name, d, _b, _r in alljobs}
    rows, ok = [], {}
    rom_of = {}
    notes = collections.defaultdict(list)
    # jobs with no --base first, so a job laid over another can inherit that job's ROM
    for name, d, bases, rom in sorted(alljobs, key=lambda j: len(j[2])):
        probs = []
        try:
            pk = hdp3_convert.load_pack(d, bases)
        except Exception as e:  # noqa: BLE001 - every rejection is a finding
            rows.append((name, d, "-", [f"pack does not load: {e}"]))
            ok[name] = False
            continue
        fixed = {ln for ln, w in pk.compat if "pack_fixes" in w}
        for ln, msg in pk.errors:
            if ln in fixed:
                continue
            # a file the pack names and does not have is a problem; every other message is the
            # log note Mesen prints for the same line (author tag quirks), kept as a note
            (probs if LACKS.search(msg) else notes[name]).append(f"line {ln}: {msg}")
        for img in pk.images:
            p = file_check(pk, img, "graphics")
            if p:
                probs.append(p)
        for bg in pk.background_files:
            p = file_check(pk, bg, "background")
            if p:
                probs.append(p)
        for tid, (f, _loop) in pk.bgm.items():
            p = file_check(pk, f, "audio")
            if p:
                probs.append(p)
        for tid, f in pk.sfx.items():
            p = file_check(pk, f, "audio")
            if p:
                probs.append(p)
        # every file a line NAMES, read straight from the text: the model drops a line on its
        # first error (an MD5 <patch> hash, a too-long <bgm>), which would hide a missing file
        named = set()
        if pk.has("hires.txt"):
            for ln, line in enumerate(pk.read("hires.txt").decode("latin-1").splitlines(), 1):
                m = REF.match(line)
                if not m:
                    continue
                fields = [x.strip() for x in m.group(2).split(",")]
                f = fields[2] if m.group(1).lower() in ("bgm", "sfx") and len(fields) > 2 else fields[0]
                if (m.group(1).lower() == "patch" and len(fields) > 1
                        and fields[1].upper() in {**pk.patches, **pk.patches_md5}):
                    continue        # pack_fixes.py resolved a misnamed patch for this line
                if f and f not in named:
                    named.add(f)
                    if not pk.has(f):
                        probs.append(f"line {ln}: <{m.group(1)}> names a file the pack lacks: {f}")
        patch_files = {**pk.patches, **pk.patches_md5}
        for f in set(patch_files.values()):
            p = file_check(pk, f, "patch")
            if p:
                probs.append(p)
        # ROM
        r, how = None, ""
        if rom:
            r, how = os.path.relpath(rom, LIB).replace("\\", "/"), "recipe"
        elif name in man:
            r, how = man[name], "manual"
        elif name in auto:
            r, how = auto[name], "auto"
        else:
            hr = hash_roms(pk.read("hires.txt").decode("latin-1")) if pk.has("hires.txt") else []
            if hr:
                r, how = hr[0], "hash"
            else:
                for b in bases:
                    if norm(b) in by_dir and by_dir[norm(b)] in rom_of:
                        r, how = rom_of[by_dir[norm(b)]], f"base {by_dir[norm(b)]}"
                        break
        if patch_files and r is not None and not r.startswith("MISSING"):
            # the pack's patch names one exact ROM: if a DIFFERENT library ROM is that one,
            # that is the pack's ROM (the table entry may only name the game)
            pr = patch_rom(pk, patch_files)
            if pr and pr != r:
                r, how = pr, f"patch target (table said {r})"
        elif patch_files and r is None:
            pr = patch_rom(pk, patch_files)
            if pr:
                r, how = pr, "patch target"
        if r is None:
            probs.append("ROM: none resolved (no recipe/manual/auto entry, no hash in the library)")
        elif r.startswith("MISSING"):
            probs.append(f"ROM: {r}")
        elif not os.path.isfile(lib_path(r)):
            probs.append(f"ROM file not found: {r} ({how})")
        else:
            rom_of[name] = r
            if (pk.bgm or pk.sfx) and not patch_files:
                # HD audio starts only when the game writes the HD audio registers, which an
                # unpatched cartridge never does: without a patch these lines can never play
                probs.append(f"audio: {len(pk.bgm)} <bgm> / {len(pk.sfx)} <sfx> lines but no "
                             f"<patch> for {r} - the original game never starts this audio")
            if patch_files:
                data = open(lib_path(r), "rb").read()
                # file NAMES (read through the merged view - a patch may live in a base folder)
                sha1s = {k: v for k, v in pk.patches.items() if pk.has(v)}
                md5s = {k: v for k, v in pk.patches_md5.items() if pk.has(v)}
                keys = rommatch.section_keys(sha1s, md5s, INDEX)
                hit = rommatch.core_lookup(data, set(keys))
                if not hit:
                    probs.append(f"patch: no <patch> line matches the ROM {r} - the patch never "
                                 f"applies (pack names {', '.join(sorted(patch_files))})")
                else:
                    src, sha, label = hit
                    try:
                        rompatch.apply(src, pk.read(keys[sha]))
                    except rompatch.PatchError as e:
                        probs.append(f"patch {os.path.basename(keys[sha])} does not apply to {r}: {e}")
        rows.append((name, d, f"{r or '-'} ({how})" if r else "-", probs))
        ok[name] = not probs
    # which passing jobs are laid over a failing job's folder
    over = collections.defaultdict(list)
    for name, d, bases, _r in alljobs:
        for b in bases:
            if norm(b) in by_dir:
                over[by_dir[norm(b)]].append(name)
    out = os.path.join(HERE, "collection_check.tsv")
    bad = 0
    with open(out, "w", encoding="utf-8", newline="\n") as fo:
        for name, d, r, probs in rows:
            good = [o for o in over.get(name, []) if ok.get(o)]
            fo.write(f"{name}\t{'OK' if not probs else 'PROBLEM'}\t{r}\t{d}\t"
                     f"{','.join(good) or '-'}\t{' || '.join(probs)}\t{len(notes[name])}\n")
            if probs:
                bad += 1
                print(f"PROBLEM {name}  ({d})  ROM {r}")
                if good:
                    print(f"    complete build(s) laid over it: {', '.join(good)}")
                kinds = collections.Counter(p.split(":")[0] if not p.startswith("line") else
                                            p.split(": ", 1)[1].split(":")[0] for p in probs)
                for k, c in kinds.most_common():
                    ex = next(p for p in probs if k in p)
                    print(f"    {c:4d} x {k}   e.g. {ex[:150]}")
    noted = sum(1 for name, _d, _r, probs in rows if not probs and notes[name])
    print(f"\n{len(rows)} jobs: {len(rows) - bad} complete ({noted} of them with Mesen log notes "
          f"only - author tag quirks, every line loads as in Mesen), {bad} with problems -> {out}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
