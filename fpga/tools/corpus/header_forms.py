"""header_forms.py - which header normalisation do pack hashes need? For every library ROM, hashes
three forms: the raw file, "z7" (header bytes 7-15 zeroed) and "k7" (byte 7's high nibble - the
iNES 1.0 mapper bits - kept, bytes 8-15 zeroed). Then reports, for every <patch> and
<supportedRom> hash in every hires.txt under the pack roots, which forms of which ROMs it equals.
The point: if no pack needs k7, the core can try z7 alone.

    python -I header_forms.py LIBRARY_DIR PACK_ROOT [PACK_ROOT ...]
"""
import hashlib
import os
import re
import sys

lib, roots = sys.argv[1], sys.argv[2:]
idx = {}
for root, _d, files in os.walk(lib):
    for f in files:
        if not f.lower().endswith(".nes"):
            continue
        p = os.path.join(root, f)
        d = open(p, "rb").read()
        forms = {"raw": d}
        if d[:4] == b"NES\x1a":
            forms["z7"] = d[:7] + bytes(9) + d[16:]
            forms["k7"] = d[:7] + bytes([d[7] & 0xF0]) + bytes(8) + d[16:]
        for k, x in forms.items():
            for h in (hashlib.sha1(x).hexdigest(), hashlib.md5(x).hexdigest()):
                idx.setdefault(h, set()).add((k, os.path.relpath(p, lib).replace("\\", "/")))

need = {"raw": 0, "z7": 0, "k7_only": 0, "none": 0}
for r in roots:
    for root, _d, files in os.walk(r):
        for f in files:
            if f.lower() != "hires.txt":
                continue
            p = os.path.join(root, f)
            t = open(p, encoding="utf-8", errors="replace").read()
            hs = re.findall(r"<supportedRom>\s*([0-9A-Fa-f]{40}|[0-9A-Fa-f]{32})\s*$", t, re.M)
            hs += re.findall(r"<patch>.*,\s*([0-9A-Fa-f]{40}|[0-9A-Fa-f]{32})\s*$", t, re.M)
            for h in sorted(set(x.lower() for x in hs)):
                hits = idx.get(h, set())
                kinds = {k for k, _ in hits}
                if "raw" in kinds:
                    need["raw"] += 1
                elif "z7" in kinds:
                    need["z7"] += 1
                elif "k7" in kinds:
                    need["k7_only"] += 1
                    print(f"K7 ONLY  {h}  {sorted(hits)}  {p}")
                else:
                    need["none"] += 1
                    print(f"NO MATCH {h}  {p}")
print(need)
