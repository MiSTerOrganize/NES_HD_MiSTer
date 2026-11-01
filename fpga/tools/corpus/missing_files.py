"""Every FILE a pack references but does not have: OGG audio, background images, IPS patches
(a patch already redirected by pack_fixes is not counted). For each missing file, search the
whole extract tree, the downloads folder and every zip in both by basename. Read-only.
Writes missing_files.tsv (job, kind, file, hits, where)."""
import collections, os, re, sys, zipfile

TOOLS = "C:/Users/miste/OneDrive/Desktop/MiSTerOrganize/MiSTerFrontier/NES_HDPack/tools"
ROOT = "Z:/NES_HDPack_work/x"
SEARCH = [ROOT, "Z:/NES_HDPack_work/dl"]
RECIPES = "C:/Users/miste/OneDrive/Desktop/MiSTerOrganize/MiSTerFrontier/NES_HDPack_testdata/pack_recipes.tsv"
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TOOLS); sys.path.insert(0, TOOLS + "/corpus")
import hdp3_convert, convert_corpus  # noqa: E402

loose, inzip = collections.defaultdict(list), collections.defaultdict(list)
for top in SEARCH:
    for dp, _dn, fn in os.walk(top):
        for f in fn:
            full = os.path.join(dp, f)
            loose[f.lower()].append(full)
            if f.lower().endswith(".zip"):
                try:
                    with zipfile.ZipFile(full) as z:
                        for n in z.namelist():
                            b = n.replace("\\", "/").split("/")[-1].lower()
                            if b:
                                inzip[b].append(full + "::" + n)
                except Exception:
                    pass

jobs, plain, _ = convert_corpus.load_jobs(ROOT, RECIPES)
rows = []
tot = collections.Counter()
for name, d, bases, rom in jobs + plain:
    pk = hdp3_convert.load_pack(d, bases)
    seen = set()
    fixed_lines = {ln for ln, w in pk.compat if "pack_fixes" in w}
    for _l, m in pk.errors:
        if _l in fixed_lines:
            continue                         # pack_fixes.py keeps this line for the core
        if m.startswith("OGG file not found: "):
            kind, f = "audio", m.split(": ", 1)[1].strip()
        elif m.startswith("Error while loading background: "):
            kind, f = "background", m.split(": ", 1)[1].strip()
        elif m.startswith("Patch file not found: "):
            sha = m.split(": ", 1)[1].strip().upper()
            if sha in getattr(pk, "patches", {}):
                continue                     # pack_fixes already supplies a patch
            kind, f = "patch", sha
        else:
            continue
        if (kind, f) in seen:
            continue
        seen.add((kind, f))
        b = f.replace("\\", "/").split("/")[-1].lower()
        hits = [("loose", p) for p in loose.get(b, [])] + [("zip", p) for p in inzip.get(b, [])]
        tot[kind] += 1
        rows.append((name, kind, f, str(len(hits)), " | ".join(f"{k}:{p}" for k, p in hits[:3])))

with open(os.path.join(HERE, "missing_files.tsv"), "w", encoding="utf-8") as fo:
    for r in rows:
        fo.write("\t".join(r) + "\n")
by = collections.defaultdict(lambda: [0, 0])
for r in rows:
    by[(r[0], r[1])][0] += 1
    by[(r[0], r[1])][1] += int(r[3] != "0")
print("missing files by kind:", dict(tot))
for (n, k), (c, f) in sorted(by.items()):
    print(f"{n:22s} {k:10s} missing {c:4d}  found-somewhere {f:4d}")
