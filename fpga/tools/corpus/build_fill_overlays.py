"""Fill overlays: for each job, the files its hires.txt references but its folders lack (audio +
backgrounds), taken from an explicitly chosen sibling download of the SAME game. Match by the
pack-relative path (case-insensitive) under each source root, else by a basename that is unique
in that root. When several roots hold the file and their bytes differ, it is reported, not
guessed (the first root wins only if every candidate is byte-identical).
Overlay = Z:/NES_HDPack_work/x/zz_var/fill_<job>, audio/backgrounds only, no hires.txt.
Dry run by default; --apply writes. Prints recipe lines."""
import collections, hashlib, os, shutil, sys

TOOLS = "C:/Users/miste/OneDrive/Desktop/MiSTerOrganize/MiSTerFrontier/NES_HDPack/tools"
ROOT = "Z:/NES_HDPack_work/x"
RECIPES = "C:/Users/miste/OneDrive/Desktop/MiSTerOrganize/MiSTerFrontier/NES_HDPack_testdata/pack_recipes.tsv"
sys.path.insert(0, TOOLS); sys.path.insert(0, TOOLS + "/corpus")
import hdp3_convert, convert_corpus  # noqa: E402
APPLY = "--apply" in sys.argv

MMS = ["a028"]
PLAN = {
    "a037": ["a102/HDPacks/Ninja Gaiden"],
    "p105": ["a102/HDPacks/Ninja Gaiden"],
    "p118": ["a102/HDPacks/Ninja Gaiden"],
    "p020": MMS, "p030": MMS,
    **{f"mms_var_{i}": MMS for i in range(5, 17)},
    "p072": ["a064"],
    "p088": ["a084", "a083", "a066/HdPacks/Castlevania 2 Mesen HD"],
    "p093": ["a089/HDPacks/Gryzor", "a090/HDPacks/Gryzor"],
    "p095": ["a092/HDPacks/Jackal (US)"],
    "p097": ["a094/HDPacks/Journey to Silius"],
    "p103": ["a100", "a099/HDPacks/Mega Man Super", "a030/HdPacks/Mega Man Super"],
    "p111": ["a105/_inner03"],
    # Shatterhand: the 42 stage-select maps sit in the pack's own stageselect_maps/ subfolder,
    # hires.txt names them at the pack root.
    "p054": ["a045/shatter_man/stageselect_maps"],
    # Zelda II pre-release: 8 forest images the later releases of the same pack ship.
    "a059": ["a057/ZII-mesen-de2a1105d1f0be3a2bebf5a0dfe03c069eadcb81", "a058/ZII-mesen-67599a8bd3578632d83762f0ac1ef27da54c5eed"],
    "vz2music_a059": ["a057/ZII-mesen-de2a1105d1f0be3a2bebf5a0dfe03c069eadcb81", "a058/ZII-mesen-67599a8bd3578632d83762f0ac1ef27da54c5eed"],
}
# Audio-only patches written to play ANY of several music sets: one overlay per set, each set
# must cover every file on its own.
VARIANTS = {
    "p088": {"yone_vrc6": "a066/HdPacks/Castlevania 2 Mesen HD", "yone_vrc6_batty": "a083",
             "jud6ment": "a084"},
    "p093": {"met": "a089/HDPacks/Gryzor", "vomitron_met": "a090/HDPacks/Gryzor"},
    "p103": {"woodfrog": "a100", "vomitron": "a099/HDPacks/Mega Man Super",
             "woodfrog_ym2612": "a030/HdPacks/Mega Man Super"},
}
for j, vs in VARIANTS.items():
    PLAN.pop(j)
    for tag, r in vs.items():
        PLAN[f"{j}_{tag}"] = [r]
JOBOF = {f"{j}_{t}": j for j, vs in VARIANTS.items() for t in vs}
ONLY = [a for a in sys.argv[1:] if not a.startswith("--")]

def md5(p):
    h = hashlib.md5()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()

index_cache = {}
def index(root):
    if root not in index_cache:
        byrel, bybase = {}, collections.defaultdict(list)
        base = os.path.join(ROOT, root)
        for dp, _d, fn in os.walk(base):
            for f in fn:
                full = os.path.join(dp, f)
                rel = os.path.relpath(full, base).replace("\\", "/").lower()
                byrel[rel] = full
                bybase[f.lower()].append(full)
        index_cache[root] = (byrel, bybase)
    return index_cache[root]

def find(root, rel):
    byrel, bybase = index(root)
    r = rel.replace("\\", "/").lower()
    for k, v in byrel.items():
        if k == r or k.endswith("/" + r):
            return v
    c = bybase.get(r.split("/")[-1], [])
    return c[0] if len(c) == 1 else None

jobs, plain, _ = convert_corpus.load_jobs(ROOT, RECIPES)
alljobs = {n: (d, b) for n, d, b, _r in jobs + plain}
recipes = []
for job, roots in PLAN.items():
    if ONLY and job not in ONLY:
        continue
    d, bases = alljobs[JOBOF.get(job, job)]
    pk = hdp3_convert.load_pack(d, bases)
    want = []
    for _l, m in pk.errors:
        for pre in ("OGG file not found: ", "Error while loading background: "):
            if m.startswith(pre):
                want.append(m[len(pre):].strip())
    want = list(dict.fromkeys(want))
    plan, bad = [], []
    for rel in want:
        cands = [(r, p) for r in roots for p in [find(r, rel)] if p]
        if not cands:
            bad.append(f"{rel} (nowhere)"); continue
        sums = {md5(p) for _r, p in cands}
        if len(sums) > 1:
            bad.append(f"{rel} (sources differ: " + ", ".join(r for r, _p in cands) + ")")
            continue
        plan.append((rel, cands[0][1], cands[0][0]))
    out = os.path.join(ROOT, "zz_var", "fill_" + job)
    if APPLY and plan:
        if os.path.exists(out) and any(os.scandir(out)):
            sys.exit(f"{out} exists and is not empty - refusing")
        for rel, src, _r in plan:
            dst = os.path.join(out, *rel.replace("\\", "/").split("/"))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copyfile(src, dst + ".part")
            os.replace(dst + ".part", dst)
    used = collections.Counter(r for _x, _y, r in plan)
    print(f"{job:12s} want {len(want):4d}  fill {len(plan):4d}  from {dict(used)}  problems {len(bad)}")
    for b in bad[:6]:
        print("      ", b)
    if plan:
        base_s = ";".join(os.path.relpath(x, ROOT).replace("\\", "/") for x in [d] + bases)
        recipes.append(f"fill_{job}\tzz_var/fill_{job}\t{base_s}\t-")
print("\n" + "\n".join(recipes))
print("\nAPPLIED" if APPLY else "\ndry run - nothing written")
