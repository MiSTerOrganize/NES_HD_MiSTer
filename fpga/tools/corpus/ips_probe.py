"""ips_probe.py - what are the loose .ips files in the HD pack collection for? Each is applied to
every library ROM whose path contains its keyword; the result's hashes (whole file, and with an
iNES 1.0 header the way <supportedRom> is computed) are looked up against every <supportedRom>
and <patch> hash in every hires.txt under the given pack roots. Also prints the IPS's own
records so a tiny code patch can be read directly.

    python -I ips_probe.py LIBRARY_DIR PACKS_DIR [PACKS_DIR ...]
"""
import hashlib
import os
import re
import sys

lib, roots = sys.argv[1], sys.argv[2:]
COLL = "C:/Users/miste/OneDrive/Desktop/MiSTerOrganize/MiSTerFrontier/##NES HD Core/Mesen HD Packs"
IPS = [("03_Castlevania_kya_HD_2023_Castlevania_Mesen_HD.ips", "/castlevania (usa)"),
       ("04_CV30th_kya_2018-04-05_b_cv.ips", "/castlevania (usa)"),
       ("12_Metroid_HD_V2.0_zeldix.ips", "/metroid (usa)"),
       ("22_Zelda_HD_zeldix.ips", "/legend of zelda, the (usa)"),
       ("A_Castlevania3_HD_Kurrono.ips", "/castlevania iii - dracula's curse (usa)")]

want = {}
for r in roots:
    for root, _d, files in os.walk(r):
        for f in files:
            if f.lower() != "hires.txt":
                continue
            p = os.path.join(root, f)
            t = open(p, encoding="utf-8", errors="replace").read()
            for h in re.findall(r"<supportedRom>\s*([0-9A-Fa-f]{40}|[0-9A-Fa-f]{32})\s*$", t, re.M):
                want.setdefault(h.lower(), set()).add(p)
            for h in re.findall(r"<patch>.*,\s*([0-9A-Fa-f]{40}|[0-9A-Fa-f]{32})\s*$", t, re.M):
                want.setdefault(h.lower(), set()).add(p)
print(f"{len(want)} distinct pack hashes")


def ips_apply(rom, ips):
    assert ips[:5] == b"PATCH", "not an IPS"
    out, i, recs = bytearray(rom), 5, []
    while ips[i:i + 3] != b"EOF":
        off = int.from_bytes(ips[i:i + 3], "big"); n = int.from_bytes(ips[i + 3:i + 5], "big"); i += 5
        if n == 0:
            n = int.from_bytes(ips[i:i + 2], "big"); data = ips[i + 2:i + 3] * n; i += 3
        else:
            data = ips[i:i + n]; i += n
        if off + n > len(out):
            out.extend(bytes(off + n - len(out)))
        out[off:off + n] = data
        recs.append((off, n))
    return bytes(out), recs


def hashes(d):
    v = {"file": d}
    if d[:4] == b"NES\x1a":
        v["ines1"] = d[:7] + bytes(9) + d[16:]
    r = {}
    for k, data in v.items():
        r[k + ".sha1"] = hashlib.sha1(data).hexdigest()
        r[k + ".md5"] = hashlib.md5(data).hexdigest()
    return r


roms = []
for root, _d, files in os.walk(lib):
    for f in files:
        if f.lower().endswith(".nes"):
            roms.append(os.path.join(root, f).replace("\\", "/"))

for name, key in IPS:
    ips = open(os.path.join(COLL, name), "rb").read()
    print(f"\n== {name} ({len(ips)} bytes)")
    for p in roms:
        if key not in p.lower():
            continue
        rom = open(p, "rb").read()
        out, recs = ips_apply(rom, ips)
        if p == [q for q in roms if key in q.lower()][0]:
            print("   records:", ", ".join(f"{o:#x}+{n}" for o, n in recs[:12]),
                  "..." if len(recs) > 12 else "", f"({len(recs)} records)")
        for k, h in hashes(out).items():
            for pk in want.get(h, ()):
                print(f"   {os.path.relpath(p, lib)} + ips -> {k} matches {pk}")
        for k, h in hashes(rom).items():
            for pk in want.get(h, ()):
                print(f"   (unpatched {os.path.relpath(p, lib)} {k} matches {pk})")
