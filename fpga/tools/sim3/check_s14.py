"""Show section 14 of a converted .hdp, check the ROM's entry builds like rompatch, and write a
copy with one data byte of that entry flipped (for hdp3_read's negative control).

    python -I check_s14.py file.hdp rom.nes out_damaged.hdp
"""
import hashlib
import struct
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import hdp3_patch as H  # noqa: E402
from hdp3_read import Hdp3, read_patches  # noqa: E402

hdp, rom_p, out = sys.argv[1:4]
d = open(hdp, "rb").read()
h = Hdp3(d)
off, n = h.sec[14]
print(f"section 14 at {off}, {n} bytes")
ents = read_patches(h)
rom = open(rom_p, "rb").read()
sha = hashlib.sha1(rom).hexdigest().upper()
for s, e in ents.items():
    print(f"  {s[:12]} base {e['base']} flags {e['flags']} tgt {e['tgt_size']} runs {len(e['runs'])} "
          f"data {len(e['data'])}{'  <- this ROM' if s == sha else ''}")
if sha in ents:
    t = H.build(ents[sha], rom)
    print(f"built {len(t) if t else 'REFUSED'} bytes, crc {hex(H.zlib.crc32(t)) if t else '-'}")
    # flip a data byte of this entry (inside section 14)
    k = list(ents).index(sha)
    e0 = off + 64 + 64 * k
    doff, dl = struct.unpack_from("<II", d, e0 + 48)
    b = bytearray(d)
    if dl:
        b[off + doff] ^= 1
    else:
        b[e0 + 28] ^= 1                 # no data: damage the target size instead
    open(out, "wb").write(bytes(b))
    print("damaged copy written")
