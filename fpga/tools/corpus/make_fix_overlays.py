"""make_fix_overlays.py [x-root] [--apply] - overlays that make two incomplete packs whole
without touching the extract tree (2026-10-29). Prints the recipe lines to add.

mmsfix_1/2/4 - Mega Man Super (a028). Its four "Patch - Music ..." customization folders each
  ship a hires.txt that is an OLDER copy of the pack's own (it still names Backdrops and menu
  frames the 2.x release renamed, and calls the patch "Mega Man 1 - Super.ips" while the folder
  ships "Megaman - Super.ips"). The music option is the .ips alone: the four hires.txt differ
  from the pack's current one in nothing but those stale names. So each overlay = the pack's
  current hires.txt + that option's .ips. Option 3 ("Music Remixed, No Pause (Default)") ships
  the same .ips as the pack itself (md5 b43089a5...), so it is the main pack and gets no overlay.

fix_p005 - Castlevania templates (a013/castlevania-mesen-main). 14 Vampire Bat tiles in the
  "# 07.png" section name image 34; the pack lists 8 images (0-7) and every other tile in that
  section names 7. Mesen drops the 14 lines ("Invalid bitmap index"). Fixed to 7.
"""
import hashlib
import os
import re
import shutil
import sys

x = next((a for a in sys.argv[1:] if not a.startswith("--")), "Z:/NES_HDPack_work/x")
APPLY = "--apply" in sys.argv
md5 = lambda p: hashlib.md5(open(p, "rb").read()).hexdigest()
bad = 0

MMS = os.path.join(x, "a028")
base_hires = open(os.path.join(MMS, "hires.txt"), "rb").read()
assert b"<patch>Megaman - Super.ips,2F88381557339A14C20428455F6991C1EB902C99" in base_hires
MAIN_IPS = md5(os.path.join(MMS, "Megaman - Super.ips"))
OPTS = {1: "Patch - Music NES, No Pause", 2: "Patch - Music NES, Pause Intact",
        3: "Patch - Music Remixed, No Pause (Default)", 4: "Patch - Music Remixed, Pause Intact"}
recipes = []
for n, opt in OPTS.items():
    ips = os.path.join(MMS, "Customization", opt, "Megaman - Super.ips")
    h = md5(ips)
    if h == MAIN_IPS:
        print(f"mms option {n} ({opt}): same .ips as the main pack ({h[:8]}) - no overlay")
        continue
    out = os.path.join(x, "zz_var", f"mmsfix_{n}")
    print(f"{'WRITE' if APPLY else 'would write'} {out}: current hires.txt + {opt} .ips ({h[:8]})")
    if APPLY:
        os.makedirs(out, exist_ok=True)
        open(os.path.join(out, "hires.txt"), "wb").write(base_hires)
        shutil.copyfile(ips, os.path.join(out, "Megaman - Super.ips"))
    recipes.append(f"mmsfix_{n}\tzz_var/mmsfix_{n}\ta028\t-")

CV = os.path.join(x, "a013", "castlevania-mesen-main")
raw = open(os.path.join(CV, "hires.txt"), "rb").read()
lines = raw.split(b"\n")
section, changed = None, 0
for i, ln in enumerate(lines):
    m = re.match(rb"# (\d+)\.png", ln)
    if m:
        section = int(m.group(1))
    if ln.startswith(b"<tile>34,"):
        if section != 7:
            print(f"REFUSED fix_p005: line {i + 1} names image 34 outside the 07.png section")
            bad += 1
        lines[i] = b"<tile>7," + ln[len(b"<tile>34,"):]
        changed += 1
if changed != 14:
    print(f"REFUSED fix_p005: expected 14 image-34 tiles, found {changed}")
    bad += 1
elif not bad:
    out = os.path.join(x, "zz_var", "fix_p005")
    print(f"{'WRITE' if APPLY else 'would write'} {out}: hires.txt with {changed} tiles 34 -> 7")
    if APPLY:
        os.makedirs(out, exist_ok=True)
        open(os.path.join(out, "hires.txt"), "wb").write(b"\n".join(lines))
    recipes.append("fix_p005\tzz_var/fix_p005\ta013/castlevania-mesen-main\t-")
# Urban Champion "Gangster" music set (overlay nea_urban_gangster, existing recipe): its own
# hires.txt (Audio-UrbanChampionGangster.zip) names snd_02-04-intro.ogg (intro variation) and the
# zip does not ship it. User decision 2026-10-29: play the set's main intro there. The overlay
# gets the zip's hires.txt (it differs from the base's only in comments) with that one line changed.
import zipfile  # noqa: E402
ZIP = "Z:/NES_HDPack_work/dl/Audio-UrbanChampionGangster/Audio-UrbanChampionGangster.zip"
with zipfile.ZipFile(ZIP) as z:
    names = set(z.namelist())
    hires = z.read("hires.txt")
old, new = b"<bgm>2,004,snd_02-04-intro.ogg", b"<bgm>2,004,snd_02-02-intro.ogg"
if hires.count(old) != 1 or "snd_02-04-intro.ogg" in names or "snd_02-02-intro.ogg" not in names:
    print("REFUSED urban gangster: the zip or its hires.txt is not the one this fix was written for")
    bad += 1
else:
    out = os.path.join(x, "zz_var", "nea_urban_gangster")
    print(f"{'WRITE' if APPLY else 'would write'} {out}/hires.txt: 2,004 -> snd_02-02-intro.ogg")
    if APPLY:
        open(os.path.join(out, "hires.txt"), "wb").write(hires.replace(old, new))
print("\n".join(recipes))
sys.exit(1 if bad else 0)
