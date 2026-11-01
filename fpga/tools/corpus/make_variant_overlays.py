"""Build the variant overlays for packs whose alternative build is a patch the player applies.

Some packs ship an .ips that a Mesen player applies to their own ROM by hand to get an
alternative build (HD music, no music). The pack's hires.txt names no patch. Each variant here
becomes an overlay folder holding ONE file, hires.txt = the base hires.txt with a <patch> line
appended, keyed to the library ROM's SHA1, so the core patches the ROM at load the way the
player would have by hand. It is laid over its unchanged base with --base (variant files win,
exactly as copying them over the pack would). The base hires.txt must have no <patch> line.

Nothing in the extract tree is modified; overlays are written under <x>/zz_var/<name>/.
Each patch is applied to the ROM here with rompatch.py, so a patch that does not fit is refused
before any recipe points at it.

usage: python -I make_variant_overlays.py [x-root]   (default Z:/NES_HDPack_work/x)
"""
import hashlib
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import rompatch  # noqa: E402

NES = "Z:/MiSTer_Organize/RomRoot/MiSTer_Console/MiSTer_Console/games/NES/1 NES"

# name, base dir (under x), patch file (relative to base), ROM (under NES), what it is
VARIANTS = [
    ("v1942b_hdmusic", "a082", "Patches/1942HDMUSIC.ips",
     "1 USA/1942 (Japan, USA) (En).nes", "1942 music pack (bogaa): HD music patch"),
    ("v1942b_nomusic_evgeny", "a082", "Patches/NoMusicWtihEvgenyImprovments.ips",
     "1 USA/1942 (Japan, USA) (En).nes", "1942 music pack (bogaa): no-music patch with Evgeny's improvements"),
]
# NOT built (2026-10-23), their music is not in the collection:
#   1942 LiQuiDz (a105/_inner00): its 1942HDMUSIC.ips and <bgm> lines are byte-identical to
#     a082's, but it ships no OGG files; v1942b_hdmusic above is the complete build.
#   Bio Miracle Bokutte Upa v2 (a105/_inner01): its soundtrack was a separate download; it is
#     now in the corpus as its own complete pack, x/zz_dl_biomiracle_sndtrk (same .ips, with
#     the OGGs and its own <patch> line), so no overlay is needed.
#   Zelda II Revamp+Music (a057-a059): built separately by make_z2_music_overlays.py, since it
#     overlays a patch file and 13 OGGs rather than adding a <patch> line.
# Overlays made for the first two before this was found are in Z:/NES_HDPack_work/var_held.


def main():
    x = sys.argv[1] if len(sys.argv) > 1 else "Z:/NES_HDPack_work/x"
    bad = 0
    for name, base, patch, rom, what in VARIANTS:
        bdir = os.path.join(x, base)
        hires = os.path.join(bdir, "hires.txt")
        romp = os.path.join(NES, rom)
        raw = open(hires, "rb").read()
        romb = open(romp, "rb").read()
        sha = hashlib.sha1(romb).hexdigest().upper()
        if b"<patch>" in raw.lower():
            print(f"REFUSED {name}: base hires.txt already has a <patch> line")
            bad += 1
            continue
        try:
            out = rompatch.apply(romb, open(os.path.join(bdir, patch), "rb").read())
        except Exception as e:          # noqa: BLE001 - any refusal is reported, not hidden
            print(f"REFUSED {name}: {patch} does not apply to {rom}: {e}")
            bad += 1
            continue
        nl = b"\r\n" if b"\r\n" in raw else b"\n"
        body = raw if raw.endswith(nl) else raw + nl
        body += f"<patch>{patch},{sha}".encode("ascii") + nl
        odir = os.path.join(x, "zz_var", name)
        os.makedirs(odir, exist_ok=True)
        with open(os.path.join(odir, "hires.txt"), "wb") as f:
            f.write(body)
        print(f"OK {name}: {what}; ROM {sha[:12]} -> patched {hashlib.sha1(out).hexdigest()[:12]}"
              f" ({len(romb)} -> {len(out)} bytes); overlay {odir}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
