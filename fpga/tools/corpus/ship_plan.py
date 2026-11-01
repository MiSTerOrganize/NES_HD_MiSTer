"""ship_plan.py [x-root] - decide what the NES_HD collection ships, and account for every job.

Input: the jobs (convert_corpus.load_jobs over pack_recipes.tsv) and collection_check.tsv.
Output: Z:/NES_HDPack_work/ship_plan.tsv, one row per SHIPPED pack:
    job  rom_ref  rom_file  hdp_name  label
and ship_accounting.tsv, one row per job: shipped / superseded-by <job> / dropped <reason>.

Rules (user decisions 2026-10-29: "one ROM, variant-suffixed packs"; every pack complete):
  * A job ships when collection_check calls it OK, or it is in FORCE (shipped knowingly).
  * A job the check flags is SUPERSEDED when a shipped job's layers contain all of its layers
    (an overlay built on it: pfix_/clean_/fill_ ...) - the overlay is the same pack, made
    complete. A complete job is never superseded: an overlay over it is a variant, both ship.
  * DROP lists the jobs left out for a reason (duplicates, templates, user decisions).
  * Every job not shipped must be superseded, a duplicate, or in DROP, else exit 1.
  * Two shipped jobs whose merged files are byte-identical ship once.
  * Names come from LABELS (hand-written): the ROM keeps its exact library file name, its one
    main pack is "<rom stem>.hdp", every other pack "<rom stem> [<label>].hdp". A shipped job
    without a label, a ROM without exactly one main pack, or a name clash refuses the plan.
"""
import collections
import hashlib
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import convert_corpus  # noqa: E402

X = next((a for a in sys.argv[1:] if not a.startswith("--")), "Z:/NES_HDPack_work/x")
RECIPES = os.path.join(HERE, "..", "..", "..", "NES_HDPack_testdata", "pack_recipes.tsv")
CHECK = os.path.join(HERE, "collection_check.tsv")
OUT = "Z:/NES_HDPack_work/ship_plan.tsv"
ACC = "Z:/NES_HDPack_work/ship_accounting.tsv"

FORCE = {  # job -> why it ships although the check flags it
    # (p071, the Lua-driven Dragon Warrior III HD pack, shipped here until 2026-10-30; it is now
    # superseded by dq3hd_a064, the same pack with the Lua turned into a ROM patch)
}
DROP = {  # job -> reason
    "p065": "Zelda II Revamped 2022: dropped on the user's call 2026-10-29",
    "p069": "Contra 80s 1.4.1: replaced by 1.4.2 (clean_contra80s_142), user's call 2026-10-29",
    "p072": "Dragon Warrior III HD git snapshot (a065): the same mod as the released pack p071",
    "fill_p072": "Dragon Warrior III HD git snapshot (a065) filled from p071: same mod as p071",
    "p093": "Gryzor (US) NEA kit: hires.txt + patch, no music; shipped as pfix_fill_p093_*",
    "p099": "Life Force NEA kit (a097): hires.txt + patch only, no music; p098 is the pack",
    "p107": "1942 NEA (a105/_inner00): same music files as a082, which ships as pfix_v1942b_*",
    "nea_1942": "1942 NEA filled: same 10 music files as a082 (md5-identical), ships as pfix_v1942b_*",
    "p108": "Bio Miracle Bokutte Upa sound pack: replaced by p133 (patch-complete release)",
    "mms_var_3": "Mega Man Super 'Music Remixed, No Pause (Default)': identical to p015",
    "mms_var_1": "Mega Man Super option (stale customization hires.txt): rebuilt as mmsfix_1",
    "mms_var_2": "Mega Man Super option (stale customization hires.txt): rebuilt as mmsfix_2",
    "mms_var_4": "Mega Man Super option (stale customization hires.txt): rebuilt as mmsfix_4",
    # 2026-10-30 duplicate sweep: each of these built byte-identical to the pack kept beside it
    "z1943": "1943 Kiwi (GitHub copy): identical to p074 (a067), only a supportedRom line differs",
    "fill_p086": "Castlevania II VRC6 'batty' (a083): same source files as fill_p073 (a066)",
    "pfix_fill_p093_met": "Contra (J) NEA MET kit (a091): same files as pfix_p091 (a089)",
    "pfix_fill_p093_vomitron_met": "Contra (J) NEA Vomitron kit (a091): same files as pfix_p092 (a090)",
    "p112": "Duck Hunt HD v1.1, HDnes repo copy (a105/_inner05): same files as p011 (a020)",
    "p012": "Ice Climber HD (a021): same files as p114 (a105/_inner07)",
    # a030's Customization 'Patch - Music' folders are stale copies from Mega Man Super 2.1.5:
    # they point at the 2.1.5 music, not a030's YM2612 tracks, so these four built identical to
    # fill_mms_var_5..8. The YM2612 music ships as p025.
    "fill_mms_var_9": "a030 'Music NES, No Pause' option: identical to fill_mms_var_5, no YM2612 music",
    "fill_mms_var_10": "a030 'Music NES, Pause' option: identical to fill_mms_var_6, no YM2612 music",
    "fill_mms_var_11": "a030 'Music Remixed, No Pause' option: identical to fill_mms_var_7, no YM2612 music",
    "fill_mms_var_12": "a030 'Music Remixed, Pause' option: identical to fill_mms_var_8, no YM2612 music",
    # ...and the unfilled originals those fill builds covered (each names files its own source lacks)
    "mms_var_9": "a030 stale music option (names 2.1.5 MUS_*.ogg a030 lacks); see fill_mms_var_9",
    "mms_var_10": "a030 stale music option (names 2.1.5 MUS_*.ogg a030 lacks); see fill_mms_var_10",
    "mms_var_11": "a030 stale music option (names 2.1.5 MUS_*.ogg a030 lacks); see fill_mms_var_11",
    "mms_var_12": "a030 stale music option (names 2.1.5 MUS_*.ogg a030 lacks); see fill_mms_var_12",
    "p086": "Castlevania II VRC6 'batty' kit (a083, patch files missing); see fill_p086",
    "fill_p093_met": "Contra (J) NEA MET kit before the patch-name fix; see pfix_fill_p093_met",
    "fill_p093_vomitron_met": "Contra (J) NEA Vomitron kit before the patch-name fix; see pfix_fill_p093_vomitron_met",
}
# Every shipped pack's name, written by hand: None = the ROM's main pack (named exactly like the
# ROM), else the bracketed variant label. A shipped job missing here, or two packs of one ROM
# with the same label, refuses the plan.
LABELS = {
    "p076": None,
    "pfix_v1942b_hdmusic": None, "pfix_v1942b_nomusic_evgeny": "No Music, Evgeny Fixes",
    "p074": None,
    "p004": None, "p006": "Aclectico 30th", "clean_p003": "Yone2008 VRC6 Audio",
    "fill_p090": "Yone2008 VRC6 Audio, batty", "clean_mep_cv_sd_v12": "SD Pack v1.2",
    "mep_cv_vk_v11": "Vampire Killer v1.1",
    "p084": None, "p000": "HD", "p131": "Yuri Egorov 2023", "zbcity": "Kiwi",
    "p133": None, "p132": None, "p001": None,
    "p002": None, "fix_p005": "Templates johnnyoak85", "p127": "Sour 2018",
    "fill_p088_jud6ment": None, "fill_p088_yone_vrc6": "Yone2008 VRC6 Audio",
    "fill_p073": "Yone2008 VRC6 Audio, v2",
    "pfix_p089": None, "p106": "bogaa Test 2017",
    "p075": None,
    "pfix_p091": None, "pfix_p092": "Vomitron MET Hybrid",
    "clean_contra80s_142": None, "clean_p070": "Remastered Aclectico Demo",
    "p008": None, "p007": "Bowser's Castle",
    "p010": None, "nea_drmario": None, "dq3hd_a064": None,
    "mep_duckhunt_nea": None, "fill_p111": "NEA Audio", "p110": "Audio",
    "zfax": None, "p077": None, "p078": None, "p081": None,
    "p114": None, "pfix_nea_iceclimber_sfc": "NEA, SFC Music",
    "pfix_nea_iceclimber_2a03": "NEA, 2A03 Music", "pfix_nea_iceclimbervs_a": "NEA VS v1.0",
    "nea_iceclimbervs_b": "NEA VS v1.1",
    "pfix_p094": None, "pfix_fill_p095": "NEA",
    "pfix_fill_p097": None,
    "p013": None, "p123": "MkWong98",
    "clean_p062": None, "clean_p059": "Remastered v1.3", "clean_p058": "Remastered v1.3 Low CPU",
    "p060": "GodModeKidd 2026", "clean_p061": "GodModeKidd 2026 Zip Build",
    "pfix_p098": None, "p014": None,
    "p100": None, "p082": "30th Anniversary",
    "p015": None, "mmsfix_1": "Super 2.1.1, NES Music", "mmsfix_2": "Super 2.1.1, NES Music, Pause",
    "mmsfix_4": "Super 2.1.1, Pause",
    "fill_mms_var_5": "Super 2.1.5", "fill_mms_var_6": "Super 2.1.5, NES Music, Pause",
    "fill_mms_var_7": "Super 2.1.5, Remixed Music", "fill_mms_var_8": "Super 2.1.5, Remixed Music, Pause",
    "p025": "Super Woodfrog YM2612",
    "fill_p030": "Super GitHub", "fill_mms_var_13": "Super GitHub, NES Music",
    "fill_mms_var_14": "Super GitHub, NES Music, Pause", "fill_mms_var_15": "Super GitHub, Remixed Music",
    "fill_mms_var_16": "Super GitHub, Remixed Music, Pause",
    "a099": "Super Vomitron", "a100": "Super Woodfrog, batty",
    "pfix_fill_p103_woodfrog": "Super NEA, Woodfrog Music", "pfix_fill_p103_vomitron": "Super NEA, Vomitron Music",
    "clean_a033_inner00": None, "p043": "8BitTroid", "p044": "Fusiontroid", "p045": "Legacytroid",
    "p046": "Megatroid", "clean_a033_alt_DefaultRunSpeed_Fast_WithExtraWaveBeamRoom": "Fast, Extra Wave Beam Room",
    "clean_a033_alt_VanillaMetroidRunSpeed_Slower": "Vanilla Speed",
    "clean_a033_alt_VanillaMetroidRunSpeed_SlowerAndMapWithoutExtraWaveBeamRoom": "Vanilla Speed, Vanilla Map",
    "clean_a034": "JUD6MENT Orchestral", "p035": "v1.5", "p036": "v1.5 8BitTroid", "p037": "v1.5 Fusiontroid",
    "p038": "v1.5 Megatroid",
    "p083": None, "fill_a037": None, "p048": "HDNes Beta", "pfix_fill_p105": "NEA",
    "p050": None, "p124": None, "p129": "HDNes 2014",
    "a039": None, "p052": "Arcade", "p113": "HDNes",
    "p079": None, "p130": None, "clean_p080": None, "fill_p054": None,
    "mep_smb_arcade": None, "pfix_p053": "Paper Mario", "p056": "roney33 Alpha", "p125": "LyonHrt",
    "p126": "MkWong98", "fill_p119": "NEA Music",
    "p128": None, "nea_smb2_doki": "NEA, Doki Doki Music", "nea_smb2_remix": "NEA, Remix Music",
    "tbsound_a048": None, "nea_urban_jazz": None, "nea_urban_gangster": "Gangster",
    "nea_yiearkungfu": None,
    "vz2music_a058": None, "vz2music_a057": "Main", "fill_vz2music_a059": "Pre-release",
    "p055": None, "p011": "HD v1.1",
}
PRIVATE = "Z:/MiSTer_Organize/RomRoot/MiSTer_Console_Private/MiSTer_Console_Private/games/NES_Private"
LIB = "Z:/MiSTer_Organize/RomRoot/MiSTer_Console/MiSTer_Console/games/NES"
TESTDATA = os.path.normpath(os.path.join(HERE, "..", "..", "..", "NES_HDPack_testdata"))


def rom_path(r):
    if r.startswith("PRIVATE:"):
        return os.path.join(PRIVATE, r[8:])
    return os.path.join(TESTDATA, r[9:]) if r.startswith("TESTDATA:") else os.path.join(LIB, r)


def norm(p):
    return os.path.normcase(os.path.normpath(p))


def merged(layers):
    """{lower relpath: (layer path, size)} - first layer wins, as the pack loader does."""
    out = {}
    for L in layers:
        for dp, _dn, fn in os.walk(L):
            for f in fn:
                rel = os.path.relpath(os.path.join(dp, f), L).replace("\\", "/").lower()
                if rel not in out:
                    p = os.path.join(dp, f)
                    out[rel] = (p, os.path.getsize(p))
    return out


def signature(files):
    h = hashlib.sha1()
    for rel in sorted(files):
        p, size = files[rel]
        h.update(f"{rel}\t{size}\n".encode())
        if rel == "hires.txt":
            h.update(open(p, "rb").read())
    return h.hexdigest()


_md5 = {}


def file_md5(p):
    if p not in _md5:
        h = hashlib.md5()
        with open(p, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        _md5[p] = h.hexdigest()
    return _md5[p]


def same_bytes(fa, fb):
    """Two merged packs hold the same files with the same bytes."""
    if fa.keys() != fb.keys():
        return False
    return all(fa[r][0] == fb[r][0] or file_md5(fa[r][0]) == file_md5(fb[r][0]) for r in fa)


def main():
    jobs, plain, _ = convert_corpus.load_jobs(X, RECIPES)
    layers = {n: [norm(d)] + [norm(b) for b in bases] for n, d, bases, _r in jobs + plain}
    status, romref = {}, {}
    for line in open(CHECK, encoding="utf-8"):
        c = line.rstrip("\n").split("\t")
        status[c[0]] = c[1]
        m = re.match(r"(.*?\.nes) \((.*)\)$", c[2])    # the "how" can itself hold parens
        romref[c[0]] = m.group(1) if m else c[2]
    for n in DROP:
        if n not in layers:
            raise SystemExit(f"DROP names unknown job {n}")
    # A complete pack is never superseded by an overlay built on it: such an overlay is a
    # VARIANT (another music option, run speed, patch choice), and both ship. Only a pack
    # the check flags is replaced by the complete overlay over it (in the accounting below).
    ship = [n for n in layers if (status.get(n) == "OK" or n in FORCE) and n not in DROP]
    # identical merged packs ship once
    seen, dup = collections.defaultdict(list), {}
    files = {}
    for n in sorted(ship):
        files[n] = merged(layers[n])
        s = signature(files[n])
        for k in seen[s]:                   # same names/sizes/hires: confirm byte for byte
            if same_bytes(files[n], files[k]):
                dup[n] = k
                break
        else:
            seen[s].append(n)
    ship = [n for n in ship if n not in dup]
    # accounting for EVERY job
    acc, bad = [], 0
    for n in sorted(layers):
        if n in ship:
            acc.append((n, "shipped", FORCE.get(n, "")))
        elif n in dup:
            acc.append((n, "duplicate", dup[n]))
        elif n in DROP:
            acc.append((n, "dropped", DROP[n]))
        else:
            # a failing job is accounted for when a shipped job holds all its layers
            # (a cover that was itself collapsed as a duplicate counts through the copy kept)
            cov = sorted({dup.get(b, b) for b in list(ship) + list(dup)
                          if set(layers[n]) <= set(layers[b])})
            if cov:
                acc.append((n, "superseded", ",".join(cov)))
            else:
                acc.append((n, "UNACCOUNTED", status.get(n, "?")))
                bad += 1
    # names
    by_rom = collections.defaultdict(list)
    for n in ship:
        by_rom[romref[n]].append(n)
    rows, problems = [], []
    for n in ship:
        if n not in LABELS:
            problems.append(f"{n}: shipped but has no LABELS entry")
    for n in LABELS:
        if n not in ship:
            problems.append(f"{n}: LABELS entry for a job that does not ship")
    for r, ns in sorted(by_rom.items()):
        rom_file = os.path.basename(rom_path(r))
        if not os.path.isfile(rom_path(r)):
            problems.append(f"{r}: ROM file not found")
        stem = os.path.splitext(rom_file)[0]
        mains = [n for n in ns if LABELS.get(n, "") is None]
        if len(mains) != 1:
            problems.append(f"{rom_file}: {len(mains)} main packs {mains} (need exactly 1)")
        used = {}
        for n in sorted(ns, key=lambda n: (LABELS.get(n) is not None, LABELS.get(n) or "")):
            lab = LABELS.get(n, "?")
            name = f"{stem}.hdp" if lab is None else f"{stem} [{lab}].hdp"
            if name.lower() in used:
                problems.append(f"{name}: both {used[name.lower()]} and {n}")
            used[name.lower()] = n
            rows.append((n, r, rom_file, name, lab or ""))
    if problems:
        print("\n".join("REFUSED " + p for p in problems))
        sys.exit(1)
    with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("job\trom_ref\trom_file\thdp_name\tlabel\n")
        for row in rows:
            fh.write("\t".join(row) + "\n")
    with open(ACC, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("job\tfate\tdetail\n")
        for row in acc:
            fh.write("\t".join(row) + "\n")
    roms = {r[1] for r in rows}
    print(f"{len(layers)} jobs: {len(rows)} ship over {len(roms)} ROMs; "
          f"{sum(1 for a in acc if a[1] == 'superseded')} superseded, "
          f"{sum(1 for a in acc if a[1] == 'duplicate')} duplicate, {len(DROP)} dropped, "
          f"{bad} UNACCOUNTED -> {OUT}")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
