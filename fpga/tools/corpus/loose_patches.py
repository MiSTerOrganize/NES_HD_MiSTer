"""loose_patches.py - which converted packs ship a ROM patch (.ips/.bps) that their hires.txt does
NOT name in a <patch> line? Those patches are meant to be applied to the game by the user, so a
recording of the unpatched ROM is not what the pack's author plays. Lists, per pack, the loose
patch files and what the corpus plan ran for it.

    python -I loose_patches.py CONVERT_LOG PLAN_TSV
"""
import os
import re
import sys

log_p, plan_p = sys.argv[1:3]
plan = {}
for line in open(plan_p, encoding="utf-8").read().splitlines()[1:]:
    f = line.split("\t")
    for pk in f[6].split():                 # the packs column is space-separated
        plan[pk] = (f[0], f[2], f[5])       # group, rom, patch

for line in open(log_p, encoding="utf-8", errors="replace"):
    m = re.match(r"^OK\s+\d+s\s+(\S+)\s+(.*)$", line.rstrip("\r\n"))
    if not m:
        continue
    name, folder = m.group(1), m.group(2).replace("\\", "/")
    hires, loose = None, []
    for root, dirs, files in os.walk(folder):
        dirs.sort()
        for f in sorted(files):
            p = os.path.join(root, f).replace("\\", "/")
            if f.lower() == "hires.txt" and not hires:
                hires = p
            if f.lower().endswith((".ips", ".bps", ".ups", ".xdelta")):
                loose.append(os.path.relpath(p, folder).replace("\\", "/"))
    if not loose:
        continue
    named = set()
    if hires:
        for t in re.findall(r"<patch>\s*([^,\r\n]+)", open(hires, encoding="utf-8", errors="replace").read()):
            named.add(os.path.basename(t.strip()).lower())
    unnamed = [x for x in loose if os.path.basename(x).lower() not in named]
    if not unnamed:
        continue
    g, rom, patch = plan.get(name, ("-", "(not in plan)", ""))
    print(f"{name:10} {g:4} ran: {rom}  patch={patch or 'none'}")
    for x in unnamed:
        print(f"           loose: {x}")
