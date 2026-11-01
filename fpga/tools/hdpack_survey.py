"""Survey Mesen HD packs: which hires.txt features each pack uses, and what the core supports.

usage: python hdpack_survey.py <pack_dir_or_hires.txt> [...] [--tsv out.tsv]

Feature names follow Mesen2's HdPackLoader (Core/NES/HdPacks/HdPackLoader.cpp), which is the
reference: tags <tile> <background> <condition> <img> <addition> <fallback> <bgm> <sfx> <ver>
<scale> <overscan> <patch> <options>; condition types hmirror vmirror bgpriority tileAtPosition
tileNearby spriteAtPosition spriteNearby memoryCheck(Constant) ppuMemoryCheck(Constant)
frameRange positionCheckX/Y originPositionCheckX/Y.
"""
import os
import re
import sys
from collections import Counter

COND_RE = re.compile(r"^\[([^\]]*)\]")
BUILTIN = {"hmirror", "vmirror", "bgpriority"}


def find_hires(path):
    if os.path.isfile(path):
        return [path]
    out = []
    for root, _, files in os.walk(path):
        for f in files:
            if f.lower() == "hires.txt":
                out.append(os.path.join(root, f))
    return out


def survey(hires):
    f = Counter()
    info = {"ver": 0, "scale": 0, "chr": set(), "cond_types": Counter(), "options": set()}
    conds = {}
    for raw in open(hires, encoding="utf-8", errors="replace"):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        cond = None
        m = COND_RE.match(line)
        if m:
            cond = m.group(1)
            line = line[m.end():]
        tag = line.split(">", 1)[0] + ">" if line.startswith("<") else None
        body = line.split(">", 1)[1] if tag else ""
        tok = [t.strip() for t in body.split(",")]
        if tag == "<ver>":
            info["ver"] = int(body)
        elif tag == "<scale>":
            info["scale"] = int(body)
        elif tag == "<condition>":
            conds[tok[0]] = tok[1]
            info["cond_types"][tok[1]] += 1
        elif tag == "<options>":
            info["options"].update(t for t in tok if t)
        elif tag == "<tile>":
            ram = len(tok) > 1 and len(tok[1]) >= 32
            info["chr"].add("RAM" if ram else "ROM")
            kind = "default" if len(tok) > 2 and tok[2].upper() == "FFFFFFFF" else (
                "sprite" if len(tok) > 2 and tok[2][:2].upper() == "FF" else "bg")
            f["tile"] += 1
            f["tile " + kind] += 1
            if cond:
                f["tile conditional"] += 1
                for c in cond.split("&"):
                    c = c.lstrip("!")
                    f["tile cond:" + (c if c in BUILTIN else conds.get(c, "?undefined"))] += 1
            if len(tok) > 5:
                try:
                    if float(tok[5]) != 1.0:
                        f["tile brightness!=1"] += 1
                except ValueError:
                    pass
        elif tag == "<background>":
            f["background"] += 1
            if cond:
                f["background conditional"] += 1
            if len(tok) > 2 and any(t not in ("", "0", "0.0") for t in tok[2:4]):
                f["background scroll-ratio"] += 1
        elif tag:
            f[tag] += 1
    return info, f


def main():
    args = sys.argv[1:]
    tsv = None
    if "--tsv" in args:
        i = args.index("--tsv")
        tsv = args[i + 1]
        del args[i:i + 2]
    rows = []
    for a in args:
        for h in find_hires(a):
            info, f = survey(h)
            rows.append((h, info, f))
            print("=" * 78)
            print(h)
            print("  ver %d  scale %d  CHR %s  options %s" % (
                info["ver"], info["scale"], "+".join(sorted(info["chr"])) or "-",
                ",".join(sorted(info["options"])) or "-"))
            print("  condition defs:", ", ".join("%s %d" % kv for kv in info["cond_types"].most_common()) or "-")
            for k, v in sorted(f.items()):
                print("  %-32s %d" % (k, v))
    if tsv:
        keys = sorted({k for _, _, f in rows for k in f})
        ctypes = sorted({k for _, i, _ in rows for k in i["cond_types"]})
        with open(tsv, "w", encoding="utf-8") as o:
            o.write("\t".join(["pack", "ver", "scale", "chr", "options"] + keys
                              + ["def:" + c for c in ctypes]) + "\n")
            for h, i, f in rows:
                o.write("\t".join([h, str(i["ver"]), str(i["scale"]), "+".join(sorted(i["chr"])),
                                   ",".join(sorted(i["options"]))] + [str(f.get(k, 0)) for k in keys]
                                  + [str(i["cond_types"].get(c, 0)) for c in ctypes]) + "\n")


if __name__ == "__main__":
    main()
