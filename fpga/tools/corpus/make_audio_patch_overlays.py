"""make_audio_patch_overlays.py [x-root] [--apply] - make the HD-audio packs that cannot start their
music complete (2026-10-29). Prints the recipe lines to add.

HD audio plays only when the game writes the HD audio registers ($4100-$4106), so an audio pack
needs a patched game. These packs name a patch they do not ship, ship it under another name, or
name a file with a comma in it (Mesen splits every tag on commas, so such a name can never load):

  supply  - the pack's <patch> line names a file it lacks; the same author's (or the same game's
            NEA) patch is copied in under exactly that name. The line stays as written: its hash
            already names the library ROM (iNES 1.0 form), which collection_check confirms.
            Ninja Gaiden / Journey to Silius / Life Force / Mega Man: PeV's "for Mesen 2.0" patch
            (the readme: rename it to match, or pre-patch the ROM).
  addline - the pack has music but no <patch> line at all (Jackal); PeV's NEA patch is added with
            a <patch> line for the library ROM.
  rehash  - the line's hash names no library ROM (Castlevania III: 0469b0c3...); the patch file
            (Kurrono's Castlevania III HD .ips, posted with the JUD6MENT set) fits Castlevania III
            (USA) - 400 bytes into empty space, 16 bytes of hooks - so the line names that ROM.
  rename  - a file name with a comma (1942 "Boss 1, Mid Boss A.ogg"; HDnes "Ice Climber (USA,
            Europe).bps") is copied without the comma and the line changed to match; a line naming
            a file under another name (1942 "Stage 6.ogg", shipped as "Stage 6-A.ogg") is pointed
            at the file that ships.

Each overlay = hires.txt (only the lines listed changed) + the files supplied, laid over the job's
own folder and its bases. Every change is checked (the line must be there exactly once, the file
supplied must have the recorded md5).
"""
import hashlib
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
import convert_corpus  # noqa: E402

X = next((a for a in sys.argv[1:] if not a.startswith("--")), "Z:/NES_HDPack_work/x")
RECIPES = os.path.join(HERE, "..", "..", "..", "NES_HDPack_testdata", "pack_recipes.tsv")
PAGE = os.path.join(HERE, "..", "..", "..", "NES_HDPack_testdata", "page_sources")
LIB = "Z:/MiSTer_Organize/RomRoot/MiSTer_Console/MiSTer_Console/games/NES/1 NES/"
APPLY = "--apply" in sys.argv
md5 = lambda p: hashlib.md5(open(p, "rb").read()).hexdigest()
sha1 = lambda p: hashlib.sha1(open(p, "rb").read()).hexdigest().upper()

NG = ("a103/Ninja Gaiden Mesen HD V1.ips", "6fe26802433684f129ff95fb20846cc3")
JTS = ("a095/Journey to Silius (for Mesen 2.0).ips", "18769b965dce14b6dfad9ae869af9f57")
LF = ("a097/Life Force (VC) (for Mesen 2.0).ips", "e1b32627f95ffee29af23e6b85209753")
MM = ("a101/Mega Man (US) (for Mesen 2.0).ips", "843ee3ab7d8d1ddb68859d7a945a87f9")
JACKAL = ("a093/Jackal_MesenNEA.ips", None)
CV3 = (os.path.join(PAGE, "A_Castlevania3_HD_Kurrono.ips"), "8d999a46d21d1026c0e2e72e360f50fa")
JACKAL_ROM = LIB + "1 USA/Jackal (USA).nes"
CV3_ROM = LIB + "1 USA/Castlevania III - Dracula's Curse (USA).nes"

# job -> (overlay name, [("supply", file name, src), ("line", old, new), ("copy", new name, src)])
FIX = {
    "p104": ("pfix_p104", [("supply", "Ninja Gaiden.ips", NG)]),
    "fill_p105": ("pfix_fill_p105", [("supply", "Ninja Gaiden.ips", NG)]),
    "fill_p118": ("pfix_fill_p118", [("supply", "Ninja Gaiden.ips", NG)]),
    "p096": ("pfix_p096", [("supply", "Journey to Silius.ips", JTS)]),
    "fill_p097": ("pfix_fill_p097", [("supply", "Journey to Silius.ips", JTS)]),
    "p098": ("pfix_p098", [("supply", "Life Force (USA) (Rev 1) (Virtual Console).ips", LF)]),
    "fill_p103_woodfrog": ("pfix_fill_p103_woodfrog", [("supply", "Mega Man.ips", MM)]),
    "fill_p103_vomitron": ("pfix_fill_p103_vomitron", [("supply", "Mega Man.ips", MM)]),
    "fill_p103_woodfrog_ym2612": ("pfix_fill_p103_woodfrog_ym2612", [("supply", "Mega Man.ips", MM)]),
    "p094": ("pfix_p094", [("supply", "Jackal_MesenNEA.ips", JACKAL),
                           ("addline", "Jackal_MesenNEA.ips", JACKAL_ROM)]),
    "fill_p095": ("pfix_fill_p095", [("supply", "Jackal_MesenNEA.ips", JACKAL),
                                     ("addline", "Jackal_MesenNEA.ips", JACKAL_ROM)]),
    "p089": ("pfix_p089", [("supply", "Castlevania III.ips", CV3),
                           ("line", "<patch>Castlevania III.ips,0469b0c338f475d7222408e3f270879f",
                            "<patch>Castlevania III.ips,{rom}", CV3_ROM)]),
}
T1942 = [("line", "<bgm>0,6,Stage 6.ogg", "<bgm>0,6,Stage 6-A.ogg", None),
         ("line", "<bgm>0,7,Boss 1, Mid Boss A.ogg", "<bgm>0,7,Boss 1 - Mid Boss A.ogg", None),
         ("copy", "Boss 1 - Mid Boss A.ogg", ("a082/Boss 1, Mid Boss A.ogg", None))]
FIX["v1942b_hdmusic"] = ("pfix_v1942b_hdmusic", T1942)
FIX["v1942b_nomusic_evgeny"] = ("pfix_v1942b_nomusic_evgeny", T1942)
ICE = [("line", "<patch>Ice Climber (USA, Europe).bps,", "<patch>Ice Climber (USA Europe).bps,", None),
       ("copy", "Ice Climber (USA Europe).bps", ("a105/_inner08/Ice Climber (USA, Europe).bps", None))]
FIX["nea_iceclimber_2a03"] = ("pfix_nea_iceclimber_2a03", ICE)
FIX["nea_iceclimber_sfc"] = ("pfix_nea_iceclimber_sfc", ICE)
# Gryzor (Contra Japan + English translation): PeV's NEA patch, shipped as a091 "Gryzor (for
# Mesen 2.0).ips". a089/a090 name it "gryzor.ips"; the Gryzor (US) fills name it without an
# extension ("Gryzor Mesen HD V1"), which is given one so the file is plainly an IPS.
# The line's hash (MD5 caa299d1) is the translated ROM with a true iNES 1.0 header (byte 7 =
# 0x10, VRC2's mapper bits kept); the core tries the file and the file with bytes 7-15 zeroed, so
# it can never reach that form (measured 2026-10-29: the only such hash among the corpus's 71).
# The library holds that game as "Contra (Japan) [T-En by Stardust Crusaders v1.01] [n].nes" -
# same body, NES 2.0 header - and the IPS writes only past the header, so the line names that
# file's own SHA1 instead.
GRY = ("a091/Gryzor (for Mesen 2.0).ips", "4610d1c7f7adfddc7f7091af62fcc0e5")
GRY_ROM = ("Z:/MiSTer_Organize/RomRoot/MiSTer_Console_Private/MiSTer_Console_Private/games/NES_Private/"
           "2 NES_Private Supplement/1 Translations/NES [T-En Collection]/"
           "Contra (Japan) [T-En by Stardust Crusaders v1.01] [n].nes")
GRY_MD5 = "caa299d1a8ecb6dbf8b74ec5145747bf"
for _j in ("p091", "p092"):
    FIX[_j] = ("pfix_" + _j, [("supply", "gryzor.ips", GRY),
                              ("line", f"<patch>gryzor.ips,{GRY_MD5}", "<patch>gryzor.ips,{rom}", GRY_ROM)])
for _j in ("fill_p093_met", "fill_p093_vomitron_met"):
    FIX[_j] = ("pfix_" + _j, [("line", f"<patch>Gryzor Mesen HD V1,{GRY_MD5}",
                               "<patch>Gryzor Mesen HD V1.ips,{rom}", GRY_ROM),
                              ("supply", "Gryzor Mesen HD V1.ips", GRY)])
# not audio, same mechanism: SMB p053 names "water_bg.png" but ships it as "water bg.png"
FIX["p053"] = ("pfix_p053", [("line", "<background>water_bg.png,", "<background>water bg.png,", None)])
FIX["nea_iceclimbervs_a"] = ("pfix_nea_iceclimbervs_a",
                             [ICE[0], ("copy", "Ice Climber (USA Europe).bps",
                                       ("a105/_inner09/Ice Climber (USA, Europe).bps", None))])

jobs, plain, _ = convert_corpus.load_jobs(X, RECIPES)
by = {n: (d, b, r) for n, d, b, r in jobs + plain}
rel = lambda p: os.path.relpath(p, X).replace("\\", "/")
src = lambda s: s if os.path.isabs(s) else os.path.join(X, s)
recipes, bad = [], 0
for job, (name, steps) in FIX.items():
    d, bases, rom = by[job]
    layers = [d] + bases
    hp = next((os.path.join(L, "hires.txt") for L in layers if os.path.isfile(os.path.join(L, "hires.txt"))), None)
    text = open(hp, "rb").read().decode("latin-1")
    nl = "\r\n" if "\r\n" in text else "\n"
    files, why = {}, []
    for st in steps:
        kind = st[0]
        if kind in ("supply", "copy"):
            fname, (path, want) = st[1], st[2]
            path = src(path)
            if not os.path.isfile(path) or (want and md5(path) != want):
                print(f"REFUSED {job}: {path} missing or not md5 {want}"); bad += 1; break
            files[fname] = path
            why.append(f"{kind} {fname} <- {rel(path) if path.startswith(X) else os.path.basename(path)}")
        elif kind == "addline":
            if "<patch>" in text:
                print(f"REFUSED {job}: already has a <patch> line"); bad += 1; break
            line = f"<patch>{st[1]},{sha1(st[2])}"
            lines = text.split(nl)
            at = next(i for i, ln in enumerate(lines) if ln.startswith("<options>") or ln.startswith("<ver>"))
            lines.insert(at + 1, line)
            text = nl.join(lines)
            why.append(f"add {line}")
        elif kind == "line":
            old, new, romp = st[1], st[2], st[3]
            if romp:
                new = new.format(rom=sha1(romp))
            if text.count(old) != 1:
                print(f"REFUSED {job}: '{old}' found {text.count(old)} times"); bad += 1; break
            text = text.replace(old, new)
            why.append(f"line '{old}' -> '{new}'")
    else:
        out = os.path.join(X, "zz_var", name)
        print(f"{'WRITE' if APPLY else 'would write'} {rel(out)} over {job}: " + "; ".join(why))
        if APPLY:
            os.makedirs(out, exist_ok=True)
            open(os.path.join(out, "hires.txt"), "wb").write(text.encode("latin-1"))
            for fname, path in files.items():
                shutil.copyfile(path, os.path.join(out, fname))
        r = os.path.relpath(rom, convert_corpus.ROMS).replace("\\", "/") if rom else "-"
        recipes.append(f"{name}\tzz_var/{name}\t{';'.join(rel(p) for p in layers)}\t{r}")
print("\n".join(recipes))
sys.exit(1 if bad else 0)
