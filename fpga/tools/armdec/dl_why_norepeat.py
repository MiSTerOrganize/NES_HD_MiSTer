"""dl_why_norepeat.py - for one display list, why do lines fail the REPEAT test of
dl_compact_census.py? Counts, over consecutive line pairs that fail, whether the command count
differs and, for equal counts, which fields differ first. Also prints the longest line.

    python -I dl_why_norepeat.py LIST.dl
"""
import collections
import struct
import sys

d = open(sys.argv[1], "rb").read()
cmds = struct.unpack(f"<{len(d) // 8}Q", d)
lines, cur = [], []
for c in cmds:
    cur.append(c)
    if c & 3 == 3:
        lines.append(cur)
        cur = []
FIELDS = [("op", 0, 2), ("x0", 2, 8), ("len", 10, 8), ("blend", 18, 2), ("offy", 20, 3),
          ("vm", 23, 1), ("hm", 24, 1), ("offx", 25, 3), ("block", 28, 24)]
why = collections.Counter()
for a, b in zip(lines, lines[1:]):
    if len(a) != len(b):
        why[f"count {'+' if len(b) > len(a) else '-'}"] += 1
        continue
    for p, c in zip(a, b):
        if p == c:
            continue
        if p & 3 == 0 and c & 3 == 0:
            diff = [n for n, s, w in FIELDS if (p >> s) & ((1 << w) - 1) != (c >> s) & ((1 << w) - 1)]
            if diff == ["offy"]:
                op, oc, vm = (p >> 20) & 7, (c >> 20) & 7, (p >> 23) & 1
                if oc == (op - 1 if vm else op + 1):
                    continue
                why["offy wraps (tile-row boundary)"] += 1
                break
            why["+".join(diff)] += 1
            break
        why["non-BLIT differs"] += 1
        break
print(f"lines {len(lines)}, longest {max(len(l) for l in lines)} commands")
for k, v in why.most_common(12):
    print(f"{v:5}  {k}")
