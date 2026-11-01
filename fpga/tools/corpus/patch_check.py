"""patch_check.py - for a pack that ships a ROM patch its hires.txt does not name: does the pack's
<supportedRom> name the UNPATCHED ROM or the PATCHED one? Applies the patch (IPS or BPS) to the ROM
the corpus ran and compares both against the pack's own hashes (whole file and iNES-1.0-header
forms, SHA1 and MD5).

    python -I patch_check.py LIBRARY_DIR PACK_FOLDER ROM_RELPATH PATCH_RELPATH [...]
"""
import hashlib
import os
import re
import sys
import zlib


def ips(rom, p):
    assert p[:5] == b"PATCH"
    out, i = bytearray(rom), 5
    while p[i:i + 3] != b"EOF":
        off = int.from_bytes(p[i:i + 3], "big"); n = int.from_bytes(p[i + 3:i + 5], "big"); i += 5
        if n == 0:
            n = int.from_bytes(p[i:i + 2], "big"); data = p[i + 2:i + 3] * n; i += 3
        else:
            data = p[i:i + n]; i += n
        if off + n > len(out):
            out.extend(bytes(off + n - len(out)))
        out[off:off + n] = data
    return bytes(out)


def bps(rom, p):
    assert p[:4] == b"BPS1"
    i = 4

    def num():
        nonlocal i
        d, s = 0, 1
        while True:
            x = p[i]; i += 1
            d += (x & 0x7F) * s
            if x & 0x80:
                return d
            s <<= 7; d += s
    src_sz, dst_sz, meta = num(), num(), num()
    i += meta
    out = bytearray(dst_sz)
    o = sr = tr = 0
    end = len(p) - 12
    while i < end:
        d = num(); cmd, ln = d & 3, (d >> 2) + 1
        if cmd == 0:
            out[o:o + ln] = rom[o:o + ln]; o += ln
        elif cmd == 1:
            out[o:o + ln] = p[i:i + ln]; i += ln; o += ln
        else:
            d = num(); off = (-1 if d & 1 else 1) * (d >> 1)
            if cmd == 2:
                sr += off; out[o:o + ln] = rom[sr:sr + ln]; sr += ln; o += ln
            else:
                tr += off
                for _ in range(ln):
                    out[o] = out[tr]; o += 1; tr += 1
    want_src = int.from_bytes(p[-12:-8], "little")
    if zlib.crc32(rom) & 0xffffffff != want_src:
        print(f"   (bps source crc {want_src:08x} != this ROM {zlib.crc32(rom) & 0xffffffff:08x})")
    return bytes(out)


def forms(d):
    v = {"file": d}
    if d[:4] == b"NES\x1a":
        v["ines1"] = d[:7] + bytes(9) + d[16:]
    r = {}
    for k, x in v.items():
        r[hashlib.sha1(x).hexdigest()] = k + ".sha1"
        r[hashlib.md5(x).hexdigest()] = k + ".md5"
    return r


lib, folder, romrel, patches = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4:]
if not os.path.isdir(folder):             # a pack name: look its folder up in the convert log
    for line in open("Z:/NES_HDPack_work/convert_all3.log", encoding="utf-8", errors="replace"):
        m = re.match(r"^OK\s+\d+s\s+(\S+)\s+(.*)$", line.rstrip("\r\n"))
        if m and m.group(1) == folder:
            folder = m.group(2).replace("\\", "/")
            break
    else:
        sys.exit(f"no pack folder for {folder}")
hires = None
for root, dirs, files in os.walk(folder):
    dirs.sort()
    for f in files:
        if f.lower() == "hires.txt" and not hires:
            hires = os.path.join(root, f)
txt = open(hires, encoding="utf-8", errors="replace").read()
sup = [s.lower() for s in re.findall(r"<supportedRom>\s*([0-9A-Fa-f]{40}|[0-9A-Fa-f]{32})\s*$", txt, re.M)]
pat = [s.lower() for s in re.findall(r"<patch>.*,\s*([0-9A-Fa-f]{40}|[0-9A-Fa-f]{32})\s*$", txt, re.M)]
print(f"{folder}\n   supportedRom: {sup or 'none'}   <patch> hashes: {pat or 'none'}")
rom = open(os.path.join(lib, romrel), "rb").read()
f0 = forms(rom)
print("   UNPATCHED:", [f0[h] for h in sup + pat if h in f0] or "no match")
for pr in patches:
    data = open(os.path.join(folder, pr), "rb").read()
    out = ips(rom, data) if data[:5] == b"PATCH" else bps(rom, data)
    f1 = forms(out)
    print(f"   + {pr}:", [f1[h] for h in sup + pat if h in f1] or "no match")
