"""dl_compact_census.py - how small could the display list get? Lever (b) of OPEN_ITEMS item 11:
the list crosses the uncached DDR3 boundary at ~105 MB/s, so its size is ARM time.

Per list (hdarm4 --dl dump, u64 commands, hd3_paint format) it reports:
  now      bytes as published (padded to 8 qwords)
  pack48   every command in 6 bytes (no command uses bits above 51)
  rep      a line whose commands equal the previous line's with each BLIT's tile row one step on
           (offy + 1, or - 1 when vm is set; no wrap) becomes one REPEAT command
  rep48    rep with 6-byte commands
Also checks the "no bits above 51" claim it relies on.

    python -I dl_compact_census.py LIST.dl [...]
"""
import struct
import sys


def lines_of(cmds):
    out, cur = [], []
    for c in cmds:
        cur.append(c)
        if c & 3 == 3:
            out.append(cur)
            cur = []
    return out, cur


def stepped(prev, cur):
    if len(prev) != len(cur):
        return False
    for p, c in zip(prev, cur):
        if p & 3 != 0:                     # FILL, FX, EOL: must be identical
            if p != c:
                return False
            continue
        if c & 3 != 0:
            return False
        offy_p, offy_c = (p >> 20) & 7, (c >> 20) & 7
        vm = (p >> 23) & 1
        want = offy_p - 1 if vm else offy_p + 1
        if not 0 <= want <= 7 or offy_c != want:
            return False
        mask = ~(7 << 20) & (2 ** 64 - 1)
        if p & mask != c & mask:
            return False
    return True


tot = {"now": 0, "pack48": 0, "rep": 0, "rep48": 0}
print(f"{'list':28} {'cmds':>6} {'now':>8} {'pack48':>8} {'rep':>8} {'rep48':>8} {'replines':>8}")
for path in sys.argv[1:]:
    d = open(path, "rb").read()
    cmds = list(struct.unpack(f"<{len(d) // 8}Q", d))
    high = sum(1 for c in cmds if c >> 52)
    if high:
        print(f"{path}: {high} commands use bits above 51 - pack48 figures invalid")
    lines, tail = lines_of(cmds)
    now = ((len(cmds) + 7) // 8) * 64
    nrep, ncmd_rep = 0, 0
    for i, ln in enumerate(lines):
        if i and stepped(lines[i - 1], ln):
            nrep += 1
            ncmd_rep += 1
        else:
            ncmd_rep += len(ln)
    ncmd_rep += len(tail)
    r = {"now": now, "pack48": len(cmds) * 6, "rep": ncmd_rep * 8, "rep48": ncmd_rep * 6}
    for k in tot:
        tot[k] += r[k]
    name = path.replace("\\", "/").split("/")[-1]
    print(f"{name:28} {len(cmds):6} {r['now']:8} {r['pack48']:8} {r['rep']:8} {r['rep48']:8} "
          f"{nrep:4}/{len(lines)}")
print(f"{'TOTAL':28} {'':6} " + " ".join(f"{tot[k]:8}" for k in ("now", "pack48", "rep", "rep48")))
