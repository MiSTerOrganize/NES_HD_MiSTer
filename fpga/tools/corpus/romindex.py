"""romindex.py - hash every .nes in the No-Intro NES library so packs can be matched to ROMs.

Writes one row per ROM: path, whole-file sha1, whole-file md5, body (no 16-byte iNES header)
sha1, body md5, PRG size, CHR size. A pack's <supportedRom> may be any of these (Mesen packs
use SHA1 of the ROM data, HDNes-era packs MD5), and a <patch> matches the whole-file SHA1.

    python -I romindex.py LIBRARY_DIR out.tsv
"""
import hashlib
import os
import sys

lib, out = sys.argv[1], sys.argv[2]
rows = []
for root, _dirs, files in os.walk(lib, onerror=lambda e: (_ for _ in ()).throw(e)):
    for f in files:
        if not f.lower().endswith(".nes"):
            continue
        p = os.path.join(root, f)
        d = open(p, "rb").read()
        body = d[16:] if d[:4] == b"NES\x1a" else d
        prg = d[4] * 16384 if d[:4] == b"NES\x1a" else 0
        chr_ = d[5] * 8192 if d[:4] == b"NES\x1a" else 0
        # what pack authors' tools hashed: the whole file with an iNES 1.0 header, i.e. this
        # file's first 7 header bytes and bytes 7-15 zero (measured: Castlevania (USA), Ninja
        # Gaiden (USA) and Super Mario Bros. (World) packs hash exactly this, SHA1 and MD5)
        ines1 = (d[:7] + bytes(9) + body) if d[:4] == b"NES\x1a" else d
        rows.append("\t".join([
            os.path.relpath(p, lib).replace("\\", "/"),
            hashlib.sha1(d).hexdigest(), hashlib.md5(d).hexdigest(),
            hashlib.sha1(body).hexdigest(), hashlib.md5(body).hexdigest(),
            hashlib.sha1(ines1).hexdigest(), hashlib.md5(ines1).hexdigest(),
            str(prg), str(chr_)]))
rows.sort()
with open(out, "w", encoding="utf-8", newline="\n") as fh:
    fh.write("path\tsha1\tmd5\tbody_sha1\tbody_md5\tines1_sha1\tines1_md5\tprg\tchr\n")
    fh.write("\n".join(rows) + "\n")
print(f"{len(rows)} ROMs indexed -> {out}")
