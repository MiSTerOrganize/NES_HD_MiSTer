"""hash_probe.py - which hash of a ROM does a pack's <supportedRom> name? Prints several
candidate hashes of each ROM whose path contains the given text, and says which of the given
target hashes each candidate equals.

    python -I hash_probe.py LIBRARY_DIR "text in path" target_hash [target_hash ...]
"""
import hashlib
import os
import sys
import zlib

lib, text, targets = sys.argv[1], sys.argv[2].lower(), [t.lower() for t in sys.argv[3:]]
for root, _d, files in os.walk(lib):
    for f in files:
        p = os.path.join(root, f)
        if not f.lower().endswith(".nes") or text not in p.lower():
            continue
        d = open(p, "rb").read()
        hdr = d[:16] if d[:4] == b"NES\x1a" else b""
        body = d[len(hdr):]
        prg = hdr[4] * 16384 if hdr else len(body)
        trainer = 512 if hdr and hdr[6] & 4 else 0
        prgd = body[trainer:trainer + prg]
        chrd = body[trainer + prg:trainer + prg + (hdr[5] * 8192 if hdr else 0)]
        cand = {}
        variants = [("file", d), ("body", body), ("prg", prgd), ("chr", chrd), ("prg+chr", prgd + chrd),
                    ("chr+prg", chrd + prgd)]
        if hdr:   # iNES 1.0 headers as older dumps carry them (bytes 7/8-15 cleared)
            variants += [("h7z", hdr[:7] + bytes(9) + body), ("h8z", hdr[:8] + bytes(8) + body),
                         ("h7lo", hdr[:7] + bytes([hdr[7] & 0xF0]) + bytes(8) + body),
                         ("h7lo8z", hdr[:7] + bytes([hdr[7] & 0xF0]) + bytes(8) + body),
                         ("hb67", hdr[:4] + hdr[4:6] + bytes([hdr[6]]) + bytes(9) + body)]
        for nm, data in variants:
            cand[nm + ".sha1"] = hashlib.sha1(data).hexdigest()
            cand[nm + ".md5"] = hashlib.md5(data).hexdigest()
            cand[nm + ".crc"] = f"{zlib.crc32(data) & 0xffffffff:08x}"
        hits = [f"{k}={v}" for k, v in cand.items() if v in targets]
        print(os.path.relpath(p, lib), "HIT " + " ".join(hits) if hits else "")
