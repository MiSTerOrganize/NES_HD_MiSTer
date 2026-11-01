"""Final view: every job that LACKS something (file/ROM/patch), and whether another job built
over the same folder lacks nothing (a complete build of the same pack). Tag warnings that
Mesen also only logs do not count as lacking."""
import collections, os, re, sys
sys.path.insert(0, r"C:\Users\miste\OneDrive\Desktop\MiSTerOrganize\MiSTerFrontier\NES_HDPack\tools\corpus")
import convert_corpus
TSV = r"C:\Users\miste\OneDrive\Desktop\MiSTerOrganize\MiSTerFrontier\NES_HDPack\tools\corpus\collection_check.tsv"
S = r"C:\Users\miste\AppData\Local\Temp\claude\C--Users-miste-OneDrive-Desktop-MiSTerOrganize\e4f1c244-eb30-4536-9f97-b20ee7d3b046\scratchpad"
MISS = re.compile(r"OGG file not found|Error while loading background|Patch file not found|"
                  r"Invalid bitmap index|^ROM|^patch|missing:|empty:|unreadable:|not a |does not load")
rows = {l.split("\t")[0]: l.rstrip("\n").split("\t") for l in open(TSV, encoding="utf-8")}
lack = {}
for n, r in rows.items():
    ps = [re.sub(r"^line \d+: ", "", p).strip() for p in r[5].split(" || ")] if r[5] else []
    m = [p for p in ps if MISS.search(p)]
    if m:
        lack[n] = collections.Counter(p.split(":")[0] for p in m)
jobs, plain, _ = convert_corpus.load_jobs("Z:/NES_HDPack_work/x", r"C:\Users\miste\OneDrive\Desktop\MiSTerOrganize\MiSTerFrontier\NES_HDPack_testdata\pack_recipes.tsv")
nm = lambda p: os.path.normcase(os.path.normpath(p))
by_dir = {nm(d): n for n, d, b, r in jobs + plain}
over = collections.defaultdict(list)
for n, d, bases, r in jobs + plain:
    for b in bases:
        if nm(b) in by_dir:
            over[by_dir[nm(b)]].append(n)
found = collections.defaultdict(lambda: [0, 0])
for l in open(S + r"\missing_files.tsv", encoding="utf-8"):
    c = l.rstrip("\n").split("\t")
    found[c[0]][0] += 1; found[c[0]][1] += int(c[3] != "0")
cov, open_ = [], []
for n in sorted(lack):
    good = [o for o in over.get(n, []) if o not in lack]
    (cov if good else open_).append((n, good))
print(f"{len(rows)} jobs; {len(rows) - len(lack)} lack nothing; {len(lack)} lack something:")
print(f"  {len(cov)} of those have a complete build of the same pack; {len(open_)} do not\n")
print("COVERED (base pack incomplete, complete variant exists):")
for n, g in cov:
    print(f"  {n:24s} -> {', '.join(g)}")
print("\nOPEN (nothing complete for this pack yet):")
for n, g in open_:
    f = found.get(n, [0, 0])
    print(f"  {n:24s} {rows[n][3].split('x' + chr(92))[-1][:58]:58s} {dict(lack[n])}  "
          f"[{f[1]}/{f[0]} missing files exist elsewhere]")
