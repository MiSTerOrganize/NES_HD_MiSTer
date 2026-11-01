"""make_deadline_overlays.py [x-root] [--apply] - remove <background> lines that name an image
its author never released (user decision 2026-10-29: "Remove the dead lines").

Every release and mirror we hold was checked first (2026-10-29): LavaAirGlow0.png is in no
Metroid HD build (V1.5, V2.1.2, the 2024 archive.org build, the JUD6MENT copy), selectscreen.png
in no Zelda Remastered build (V1.3, LowCPU, ITA, JUD6MENT, GodModeKidd), imgPAUSE.png in no Road
Fighter pack (LiQuiDz 1.0 or the AllanUr4 one it is based on), Stage1.png in no Contra 80s release
(1.4.1, 1.4.2) nor the Contra Remastered demo, titlecb.png in no Castlevania Mesen HD copy (the
pack ships title0b..titlefb except that one blink frame; checked every download and page source
on 2026-10-29). Mesen skips a background whose image is missing,
so dropping the line changes nothing on screen; the pack then names only files it has.

Each overlay = the job's own hires.txt with exactly those lines removed (count checked), laid
over the job's folder and its bases. The image must be absent from the whole merged pack, or the
entry is refused. Prints the recipe lines to add.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
import convert_corpus  # noqa: E402
import hdp3_convert  # noqa: E402

X = next((a for a in sys.argv[1:] if not a.startswith("--")), "Z:/NES_HDPack_work/x")
RECIPES = os.path.join(HERE, "..", "..", "..", "NES_HDPack_testdata", "pack_recipes.tsv")
APPLY = "--apply" in sys.argv
FIX = [  # job, never-released image, lines expected
    ("a033_inner00", "LavaAirGlow0.png", 12),
    ("a034", "LavaAirGlow0.png", 12),
    ("a033_alt_DefaultRunSpeed_Fast_WithExtraWaveBeamRoom", "LavaAirGlow0.png", 12),
    ("a033_alt_VanillaMetroidRunSpeed_Slower", "LavaAirGlow0.png", 12),
    ("a033_alt_VanillaMetroidRunSpeed_SlowerAndMapWithoutExtraWaveBeamRoom", "LavaAirGlow0.png", 12),
    ("p058", "selectscreen.png", 1), ("p059", "selectscreen.png", 1),
    ("p061", "selectscreen.png", 1), ("p062", "selectscreen.png", 1),
    ("p063", "selectscreen.png", 1), ("p064", "selectscreen.png", 1),
    ("p080", "imgPAUSE.png", 1),
    ("contra80s_142", "Stage1.png", 2),
    ("p070", "Stage1.png", 2),
    ("p003", "titlecb.png", 2), ("mep_cv_sd_v12", "titlecb.png", 2),
]

jobs, plain, _ = convert_corpus.load_jobs(X, RECIPES)
by_name = {n: (d, b, r) for n, d, b, r in jobs + plain}
rel = lambda p: os.path.relpath(p, X).replace("\\", "/")
out_lines, bad = [], 0
for job, img, want in FIX:
    d, bases, rom = by_name[job]
    pk = hdp3_convert.load_pack(d, bases)
    if pk.has(img):
        print(f"REFUSED {job}: {img} IS in the pack"); bad += 1; continue
    raw = open(os.path.join(d, "hires.txt"), "rb").read()
    lines = raw.split(b"\n")
    key = b"<background>" + img.encode().lower() + b","
    keep = [ln for ln in lines if key not in ln.lower()]
    n = len(lines) - len(keep)
    if n != want:
        print(f"REFUSED {job}: expected {want} lines naming {img}, found {n}"); bad += 1; continue
    name = f"clean_{job}"
    out = os.path.join(X, "zz_var", name)
    print(f"{'WRITE' if APPLY else 'would write'} {rel(out)}: {job} minus {n} line(s) naming {img}")
    if APPLY:
        os.makedirs(out, exist_ok=True)
        open(os.path.join(out, "hires.txt"), "wb").write(b"\n".join(keep))
    r = os.path.relpath(rom, convert_corpus.ROMS).replace("\\", "/") if rom else "-"
    out_lines.append(f"{name}\tzz_var/{name}\t{';'.join(rel(p) for p in [d] + bases)}\t{r}")
print("\n".join(out_lines))
sys.exit(1 if bad else 0)
