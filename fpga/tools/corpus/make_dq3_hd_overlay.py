"""make_dq3_hd_overlay.py --deloc DIR [x-root] [--apply] : the Dragon Warrior III HD overlay
zz_var/dq3hd_a064 and the ROM it ships with (2026-10-30).

Pack a064 (dq3nes-mesen-hdpack-mod v0.5.1) drives its graphics conditions and its music from a
Mesen Lua script, which the core does not run. make_dq3_hd_patch.py turns that script into a
ROM patch; this script builds what ships:

  the ROM     Dragon Quest III Delocalized v1.14 (user's call 2026-10-30: ship the newest
              release; the T-En Collection DAT still lists v1.13 and will catch up). It is the
              v1.14 hack applied to Dragon Warrior III (USA), with the USA ROM's NES 2.0 header -
              the form the T-En DAT uses (its v1.13 [n] entry, b6346425..., is exactly that form of
              our v1.13 build) - under the name that DAT gives its releases. Written to
              NES_HDPack_testdata/roms/ (the collection reaches it as TESTDATA:roms/<name>).
              DIR holds "Dragon Quest III Delocalized v1.14.nes" and "... v1.13.nes", built by
              the hack's own IPS files on the library ROM.
  dq3hd.ips   the patch. It changes only PRG bank 30, byte-identical in USA, v1.13 and v1.14,
              so the file is the same for all three (checked here).
  hires.txt   a064's, two changes, each checked to apply exactly once:
              - the "script=HdPacks.lua" line is dropped (the patch replaces it);
              - <patch>dq3hd.ips,<sha1> lines after <scale> for the shipped ROM, v1.14 as the
                hack's own patch writes it (iNES 1.0 header), and the T-En DAT's v1.13 [n].
                Deliberately NOT the USA ROM: collection_check resolves a pack to the library
                ROM its patch names, which would ship the pack against the unhacked game.
Recipe:  dq3hd_a064 <TAB> zz_var/dq3hd_a064 <TAB> a064 <TAB> -
Manual:  dq3hd_a064 <TAB> TESTDATA:roms/<ROM name>      (pack_roms_manual.tsv)
Verified: test_dq3_hd_patch.py (pack Lua vs patch, randomized + negative controls) and the
Mesen A/B run (tools/mesen2, dq3_ab.lua) on the patched ROM.
"""
import hashlib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import make_dq3_hd_patch as P  # noqa: E402

argv = sys.argv[1:]
if "--deloc" not in argv:
    raise SystemExit(__doc__)
i = argv.index("--deloc")
DELOC = argv[i + 1]
del argv[i:i + 2]
APPLY = "--apply" in argv
args = [a for a in argv if not a.startswith("--")]
X = args[0] if args else "Z:/NES_HDPack_work/x"
LIB_ROM = ("Z:/MiSTer_Organize/RomRoot/MiSTer_Console/MiSTer_Console/games/NES/1 NES/1 USA/"
           "Dragon Warrior III (USA).nes")
USA_SHA = "19AB26DF82C3F92AF545C93008022CAB9C16F542"
SHIP_NAME = "Dragon Quest III (USA) [T-En by Translation Quest v1.14] [Delocalized] [n].nes"
SHIP_SHA = "02F259B882F4909F40C19B07FE0862F128EE7495"
KEYS = {  # whole-file sha1, as the core keys a <patch> line
    "shipped ROM (v1.14, USA NES 2.0 header)": SHIP_SHA,
    "v1.14 as the hack's IPS writes it (iNES 1.0 header)": "B49CE1DA69108CE499999F8A23346E1079D984B0",
    "v1.13 [n], T-En Collection DAT": "B6346425733EA0E6657972753B218F5BD40E5C5C",
}
ROMS = os.path.normpath(os.path.join(HERE, "..", "..", "..", "NES_HDPack_testdata", "roms"))
SRC = os.path.join(X, "a064")
DST = os.path.join(X, "zz_var", "dq3hd_a064")


def sha(d):
    return hashlib.sha1(d).hexdigest().upper()


def main():
    usa = open(LIB_ROM, "rb").read()
    if sha(usa) != USA_SHA:
        raise SystemExit("library ROM is not the expected Dragon Warrior III (USA)")
    v114 = open(os.path.join(DELOC, "Dragon Quest III Delocalized v1.14.nes"), "rb").read()
    v113 = open(os.path.join(DELOC, "Dragon Quest III Delocalized v1.13.nes"), "rb").read()
    ship = usa[:16] + v114[16:]
    if sha(ship) != SHIP_SHA or sha(v114) != KEYS["v1.14 as the hack's IPS writes it (iNES 1.0 header)"]:
        raise SystemExit("v1.14 build is not the expected one")
    if sha(usa[:16] + v113[16:]) != KEYS["v1.13 [n], T-En Collection DAT"]:
        raise SystemExit("v1.13 build does not equal the T-En DAT's v1.13 [n]")
    ips = P.ips(P.build(ship)[1])
    for name, d in (("Dragon Warrior III (USA)", usa), ("v1.13", v113), ("v1.14 iNES 1.0", v114)):
        if P.ips(P.build(d)[1]) != ips:
            raise SystemExit(f"{name}: the patch differs from the shipped ROM's")
    print(f"  {SHIP_NAME}: {SHIP_SHA}")
    print(f"  dq3hd.ips: {len(ips)} bytes, the same for USA, v1.13 and v1.14")
    text = open(os.path.join(SRC, "hires.txt"), encoding="utf-8", newline="").read()
    eol = "\r\n" if "\r\n" in text else "\n"            # a064's hires.txt is CRLF; keep it so
    lines = text.split(eol)
    drop = [i for i, s in enumerate(lines) if s.strip().startswith("script=")]
    scale = [i for i, s in enumerate(lines) if s.strip().startswith("<scale>")]
    if len(drop) != 1 or len(scale) != 1:
        raise SystemExit(f"hires.txt: expected one script= line and one <scale> line, got {drop} {scale}")
    if any("<patch>" in s for s in lines):
        raise SystemExit("hires.txt already has a <patch> line")
    add = [f"<patch>dq3hd.ips,{h}" for h in KEYS.values()]
    new = lines[:scale[0] + 1] + add + [s for i, s in enumerate(lines[scale[0] + 1:], scale[0] + 1)
                                        if i != drop[0]]
    print(f"  hires.txt: -1 line ({lines[drop[0]].strip()}), +{len(add)} <patch> lines")
    if not APPLY:
        print(f"  (dry run) would write {DST} and {os.path.join(ROMS, SHIP_NAME)}")
        return
    os.makedirs(DST, exist_ok=True)
    open(os.path.join(DST, "dq3hd.ips"), "wb").write(ips)
    with open(os.path.join(DST, "hires.txt"), "w", encoding="utf-8", newline="") as f:
        f.write(eol.join(new))
    open(os.path.join(ROMS, SHIP_NAME), "wb").write(ship)
    print(f"  wrote {DST} and roms/{SHIP_NAME}")


if __name__ == "__main__":
    main()
