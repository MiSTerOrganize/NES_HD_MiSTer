"""rom_parts.py - print each NES file's mapper, PRG/CHR sizes and the MD5 of its PRG and CHR, so
candidate ROMs for a hash-less pack can be told apart (or shown to be the same game).

    python -I rom_parts.py FILE.nes [...]
"""
import hashlib
import sys

for p in sys.argv[1:]:
    d = open(p, "rb").read()
    h = d[:16]
    prg, chrn = h[4] * 16384, h[5] * 8192
    off = 16 + (512 if h[6] & 4 else 0)
    mapper = (h[6] >> 4) | (h[7] & 0xF0)
    pd, cd = d[off:off + prg], d[off + prg:off + prg + chrn]
    print(f"mapper {mapper:3} prg {prg:6} chr {chrn:6} prg.md5 {hashlib.md5(pd).hexdigest()[:12]} "
          f"chr.md5 {hashlib.md5(cd).hexdigest()[:12]}  {p.split('/')[-1]}")
