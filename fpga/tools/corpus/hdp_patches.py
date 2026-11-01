"""hdp_patches.py - list the ROM-patch entries (section 14) a converted .hdp carries: the SHA1 of the
source ROM file each one applies to. A pack whose hires.txt has a <patch> line but whose .hdp has
no entry for it lost the patch at conversion.

    python -I hdp_patches.py PACK.hdp [...]
"""
import struct
import sys

S_PATCHES = 14
for path in sys.argv[1:]:
    d = open(path, "rb").read()
    off, size = struct.unpack_from("<II", d, 0x80 + 8 * S_PATCHES)
    name = path.replace("\\", "/").split("/")[-1]
    if not size:
        print(f"{name:40} no patch entries")
        continue
    n = struct.unpack_from("<I", d, off)[0]
    shas = [d[off + 64 + 64 * i: off + 64 + 64 * i + 20].hex() for i in range(n)]
    print(f"{name:40} {n} entr{'y' if n == 1 else 'ies'}: " + " ".join(shas))
