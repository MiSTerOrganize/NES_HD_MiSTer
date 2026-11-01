"""Build audio overlay folders (no hires.txt, audio only) for the HDnes NEA packs from the
downloaded audio zips. Each overlay is used as a recipe 'pack' with the original pack folder as
its base, the same way zz_var/vz2music_* works. Only the files the base pack's hires.txt asks
for and cannot find are extracted; each is matched by its pack-relative path against the zip
member path's tail. Ambiguous or unmatched files are reported, never guessed.
Dry run by default; --apply writes. Prints the recipe lines to add."""
import os, sys, zipfile

TOOLS = "C:/Users/miste/OneDrive/Desktop/MiSTerOrganize/MiSTerFrontier/NES_HDPack/tools"
ROOT = "Z:/NES_HDPack_work/x"
DL = "Z:/NES_HDPack_work/dl"
sys.path.insert(0, TOOLS)
import hdp3_convert  # noqa: E402
APPLY = "--apply" in sys.argv

V = [  # variant, base pack (relative to ROOT), zip
    ("nea_1942",              "a105/_inner00", "1942-AUDIO-PACK.zip"),
    ("nea_drmario",           "a105/_inner02", "Audio1-DrMario.zip"),
    ("nea_iceclimber_2a03",   "a105/_inner08", "iceclimber-ogg_2x2A03.zip"),
    ("nea_iceclimber_sfc",    "a105/_inner08", "iceclimber-ogg_superfamicom.zip"),
    ("nea_iceclimbervs_a",    "a105/_inner09", "AUDIO1-IceClimberVS.zip"),
    ("nea_iceclimbervs_b",    "a105/_inner10", "AUDIO1-IceClimberVS.zip"),
    ("nea_smb2_doki",         "a105/_inner13", "AUDIO-smb2-doki.zip"),
    ("nea_smb2_remix",        "a105/_inner13", "AUDIO-smb2-remix_ShoesBeDrawin.zip"),
    ("nea_urban_jazz",        "a105/_inner14", "Audio-UrbanChampionJazz.zip"),
    ("nea_urban_gangster",    "a105/_inner14", "Audio-UrbanChampionGangster.zip"),
    ("nea_yiearkungfu",       "a105/_inner15/Yie Ar Kung-Fu (Japan)", "NEA_Audio1-Yie.Ar.Kung-Fu.zip"),
]

def zpath(name):
    return os.path.join(DL, name[:-4], name)

recipes, short = [], []
for var, base, zname in V:
    bdir = os.path.join(ROOT, base)
    pk = hdp3_convert.load_pack(bdir, [])
    miss = list(dict.fromkeys(m.split("OGG file not found: ", 1)[1].strip()
                              for _l, m in pk.errors if "OGG file not found" in m))
    with zipfile.ZipFile(zpath(zname)) as z:
        members = [n for n in z.namelist() if not n.endswith("/")]
        low = [n.replace("\\", "/").lower() for n in members]
        plan, bad = [], []
        for rel in miss:
            r = rel.replace("\\", "/").lower()
            cand = [m for m, l in zip(members, low) if l == r or l.endswith("/" + r)]
            if len(cand) == 1:
                plan.append((rel, cand[0]))
            else:
                bad.append((rel, len(cand)))
        out = os.path.join(ROOT, "zz_var", var)
        if APPLY:
            if os.path.exists(out) and any(os.scandir(out)):
                sys.exit(f"{out} exists and is not empty - refusing")
            for rel, m in plan:
                dst = os.path.join(out, *rel.replace("\\", "/").split("/"))
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                data = z.read(m)          # CRC-checked by zipfile
                with open(dst + ".part", "wb") as f:
                    f.write(data)
                os.replace(dst + ".part", dst)
        print(f"{var:22s} base {base:40s} missing {len(miss):3d}  extract {len(plan):3d}  unmatched {len(bad)}"
              + ("" if not bad else "  " + ", ".join(f"{r}({c})" for r, c in bad)))
        if bad:
            short.append(var)
    recipes.append(f"{var}\tzz_var/{var}\t{base}\t-")

print("\nrecipe lines:")
print("\n".join(recipes))
print("\n" + ("APPLIED" if APPLY else "dry run - nothing written"))
