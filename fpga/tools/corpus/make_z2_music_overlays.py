"""Build the Zelda II "Revamp+Music" variant overlays (ZII-mesen packs a057, a058, a059).

The pack README: "To use replacement music rename Revamp+Music.ips to Revamp.ips and place OGG
files in the Music folder." The OGGs are not in the pack (its .gitignore excludes *.ogg); they are
Niskala's "Zelda 2 Remake Music" (two zips, Part 1 + Part 2, 2022-11-27), which the user obtained
from the project Discord. So each overlay holds:
    Revamp.ips          = the base pack's Revamp+Music.ips, byte for byte
    Music/<name>.ogg    = the 13 files the pack's <bgm> lines name, copied from the remake set
hires.txt is NOT overlaid - the base's own <patch>Revamp.ips line and <bgm> lines are used as is.

Nothing in the extract tree is modified; overlays go to <x>/zz_var/<name>/. The music patch is
applied to the library ROM here first, so a patch that does not fit is refused.

usage: python -I make_z2_music_overlays.py <music dir> [x-root]
  <music dir> = folder holding the extracted "Zelda 2 Remake Music (Part 1)" and "(Part 2)" folders
"""
import hashlib
import os
import shutil
import sys

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import rompatch  # noqa: E402

ROM = ("Z:/MiSTer_Organize/RomRoot/MiSTer_Console/MiSTer_Console/games/NES/1 NES/1 USA/"
       "Zelda II - The Adventure of Link (USA).nes")

# overlay name, base pack dir (under x)
BASES = [
    ("vz2music_a057", "a057/ZII-mesen-de2a1105d1f0be3a2bebf5a0dfe03c069eadcb81"),
    ("vz2music_a058", "a058/ZII-mesen-67599a8bd3578632d83762f0ac1ef27da54c5eed"),
    ("vz2music_a059", "a059/ZII-mesen-Pre-release"),
]

# pack name -> remake track. Direct matches by title, except three judged by game scene:
#   ending  (song 78)  -> Zelda Awakens   (the ending is Zelda waking)
#   credits (song 84)  -> End Credits
#   courage (song 114) -> Triforce        (the Triforce of Courage)
# The remake's Dungeon Clear, Flute and Item have no slot in the pack and are not used.
TRACKS = {
    "battle": "Zelda 2 - Battle Theme [v3].ogg",
    "boss": "Zelda 2 - Palace Boss [v2].ogg",
    "courage": "Zelda 2 - Triforce [v1].ogg",
    "credits": "Zelda 2 - End Credits [v1].ogg",
    "ending": "Zelda 2 - Zelda Awakens [v1].ogg",
    "greatpalace": "Zelda 2 - Great Palace [v2].ogg",
    "house": "Zelda 2 - House [v1].ogg",
    "intro": "Zelda 2 - Title Screen [v1].ogg",
    "lvlup": "Zelda 2 - Level Up [v1].ogg",
    "overworld": "Zelda 2 - Overworld Theme [v2].ogg",
    "palace": "Zelda 2 - Palace Theme [v3].ogg",
    "shadow": "Zelda 2 - Shadow Link Boss [v2].ogg",
    "town": "Zelda 2 - Town Theme [v2].ogg",
}


def find_tracks(music_dir):
    found = {}
    for root, _dirs, files in os.walk(music_dir):
        if "__MACOSX" in root:
            continue
        for f in files:
            found.setdefault(f, os.path.join(root, f))
    out = {}
    for name, src in TRACKS.items():
        if src not in found:
            raise SystemExit(f"REFUSED: remake track missing: {src}")
        with open(found[src], "rb") as fh:
            if fh.read(4) != b"OggS":
                raise SystemExit(f"REFUSED: not an Ogg file: {found[src]}")
        out[name] = found[src]
    return out


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    music_dir = sys.argv[1]
    x = sys.argv[2] if len(sys.argv) > 2 else "Z:/NES_HDPack_work/x"
    tracks = find_tracks(music_dir)
    rom = open(ROM, "rb").read()
    rom_sha = hashlib.sha1(rom).hexdigest().upper()
    bad = 0
    for name, base in BASES:
        bdir = os.path.join(x, base)
        hires = open(os.path.join(bdir, "hires.txt"), "rb").read().decode("latin-1")
        if f"<patch>Revamp.ips,{rom_sha}".lower() not in hires.lower():
            print(f"REFUSED {name}: base hires.txt does not name Revamp.ips for ROM {rom_sha[:12]}")
            bad += 1
            continue
        wanted = {ln.split(",")[-1].strip() for ln in hires.splitlines() if ln.startswith("<bgm>")}
        missing = sorted(w for w in wanted if os.path.splitext(os.path.basename(w))[0] not in tracks)
        if missing:
            print(f"REFUSED {name}: no track for {missing}")
            bad += 1
            continue
        mpatch = open(os.path.join(bdir, "Revamp+Music.ips"), "rb").read()
        try:
            out = rompatch.apply(rom, mpatch)
        except Exception as e:  # noqa: BLE001 - any refusal is reported, not hidden
            print(f"REFUSED {name}: Revamp+Music.ips does not apply: {e}")
            bad += 1
            continue
        odir = os.path.join(x, "zz_var", name)
        os.makedirs(os.path.join(odir, "Music"), exist_ok=True)
        with open(os.path.join(odir, "Revamp.ips"), "wb") as f:
            f.write(mpatch)
        for t, src in tracks.items():
            shutil.copyfile(src, os.path.join(odir, "Music", t + ".ogg"))
        print(f"OK {name}: base {base}; {len(wanted)} bgm lines, 13 OGGs; patched ROM "
              f"{hashlib.sha1(out).hexdigest()[:12]} ({len(rom)} -> {len(out)} bytes); {odir}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
