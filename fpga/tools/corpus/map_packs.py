"""map_packs.py - which ROM does each converted pack belong to?

Reads the conversion log (pack name -> source folder), each pack's hires.txt (<supportedRom>
and <patch> hashes) and romindex.tsv (romindex.py), and writes one row per pack:
    name, folder, how the ROM was matched, the matched ROM path(s), the pack's own title.
A <supportedRom> may be the SHA1 or MD5 of the whole file or of the data after the iNES header
(Mesen packs and HDNes-era packs differ); a <patch> names the whole-file SHA1 it applies to.
Packs with no usable hash are listed as UNMATCHED with their folder names, to be resolved by
hand in corpus_roms.tsv (never guessed here).

    python -I map_packs.py convert_log romindex.tsv out.tsv
"""
import os
import re
import sys

log_p, idx_p, out_p = sys.argv[1:4]
X = "Z:/NES_HDPack_work/x"

by_hash = {}
for line in open(idx_p, encoding="utf-8").read().splitlines()[1:]:
    f = line.split("\t")
    for h in f[1:7]:
        by_hash.setdefault(h.lower(), []).append(f[0])

packs = []
for line in open(log_p, encoding="utf-8", errors="replace"):
    m = re.match(r"^OK\s+\d+s\s+(\S+)\s+(.*)$", line.rstrip("\r\n"))
    if m:
        packs.append((m.group(1), m.group(2).replace("\\", "/")))


def hires_of(folder):
    for root, dirs, files in os.walk(folder):
        dirs.sort()
        for f in files:
            if f.lower() == "hires.txt":
                return os.path.join(root, f)
    return None


rows = []
for name, folder in packs:
    h = hires_of(folder)
    if not h:
        rows.append((name, folder, "NO_HIRES", "", "", ""))
        continue
    txt = open(h, encoding="utf-8", errors="replace").read()
    # a hash is the LAST comma field of its line (patch file names contain commas, e.g.
    # "Ice Climber (USA, Europe).bps") and is a whole MD5 or SHA1, never a prefix
    sup = [s.lower() for s in re.findall(r"<supportedRom>\s*([0-9A-Fa-f]{40}|[0-9A-Fa-f]{32})\s*$", txt, re.M)]
    pat = [s.lower() for s in re.findall(r"<patch>.*,\s*([0-9A-Fa-f]{40}|[0-9A-Fa-f]{32})\s*$", txt, re.M)]
    hit, how = [], ""
    for s in sup + pat:
        if s in by_hash:
            hit += by_hash[s]
            how = how or ("supportedRom" if s in sup else "patch")
    hit = sorted(set(hit))
    title = os.path.basename(os.path.dirname(h))
    rows.append((name, folder, how or ("NOHASH" if not (sup or pat) else "HASH_NOT_IN_LIBRARY"),
                 " | ".join(hit), ",".join(sup + pat), title))

with open(out_p, "w", encoding="utf-8", newline="\n") as fh:
    fh.write("pack\tfolder\tmatch\troms\thashes\ttitle\n")
    for r in rows:
        fh.write("\t".join(r) + "\n")
kinds = {}
for r in rows:
    kinds[r[2]] = kinds.get(r[2], 0) + 1
print(f"{len(rows)} packs: " + ", ".join(f"{k} {v}" for k, v in sorted(kinds.items())))
