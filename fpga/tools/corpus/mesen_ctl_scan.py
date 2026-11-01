"""Which corpus groups' ROMs get NO controller in Mesen with an empty settings.json?
Mesen configures input from its game DB (by CRC32 of PRG+CHR) or an NES 2.0 header's byte 15;
with neither, it keeps the configured ports, which default to none.
usage: python -I noctl_scan.py <corpus WORK> <MesenNesDB.txt>"""
import os
import sys
import zlib

sys.stdout.reconfigure(encoding="utf-8")
work, db = sys.argv[1], sys.argv[2]
crcs = {}
for line in open(db, encoding="utf-8", errors="replace"):
    if line[:1].isalnum() and "," in line:
        f = line.rstrip("\n").split(",")
        crcs[f[0].upper()] = f[13] if len(f) > 13 else ""
plan = [l.split("\t") for l in open(os.path.join(work, "plan.tsv"), encoding="utf-8").read().splitlines()[1:]]
for r in plan:
    g = r[0]
    p = os.path.join(work, g, "rom.nes")
    if not os.path.exists(p):
        print(f"{g}: no rom.nes")
        continue
    d = open(p, "rb").read()
    nes2 = d[:4] == b"NES\x1a" and (d[7] & 0x0C) == 0x08
    crc = f"{zlib.crc32(d[16:]) & 0xFFFFFFFF:08X}"
    indb = crc in crcs
    how = ("DB ctrl=" + crcs[crc]) if indb else ("NES2.0 exp=%d" % d[15] if nes2 else "NONE")
    flag = "" if indb or (nes2 and d[15]) else "   <-- no controller in Mesen"
    print(f"{g} {r[1][:44]:44} {how}{flag}")
