"""Survey every <patch> line in the corpus packs (Z:/NES_HDPack_work/x/*/hires.txt): format,
size, how many per pack, and whether a ROM in the library matches one of its SHA1s.

    python survey.py
"""
import glob
import hashlib
import os
import sys

X = "Z:/NES_HDPack_work/x"
ROMS = "Z:/MiSTer_Organize/RomRoot/MiSTer_Console/MiSTer_Console/games/NES"


def main():
    rom_by_sha = {}
    for p in glob.glob(ROMS + "/**/*.nes", recursive=True):
        with open(p, "rb") as f:
            d = f.read()
        rom_by_sha[hashlib.sha1(d).hexdigest().upper()] = (p, len(d))
    print(f"{len(rom_by_sha)} library ROMs hashed")
    packs = 0
    fmt = {}
    sizes = []
    matched = 0
    rows = []
    for h in sorted(glob.glob(X + "/*/hires.txt") + glob.glob(X + "/*/*/hires.txt")):
        d = os.path.dirname(h)
        with open(h, encoding="utf-8", errors="replace") as f:
            lines = [l.strip() for l in f if l.strip().lower().startswith("<patch>")]
        if not lines:
            continue
        packs += 1
        for l in lines:
            body = l[len("<patch>"):]
            parts = [t.strip() for t in body.split(",")]
            if len(parts) < 2:
                rows.append((d, l, "bad line"))
                continue
            name, sha = parts[0], parts[1].upper()
            pp = os.path.join(d, name)
            if not os.path.exists(pp):
                rows.append((d, name, "file missing"))
                continue
            with open(pp, "rb") as f:
                b = f.read()
            kind = b[:4].decode("latin1")
            k = "IPS" if b[:5] == b"PATCH" else "BPS" if b[:4] == b"BPS1" else "UPS" if b[:4] == b"UPS1" else "?" + kind
            fmt[k] = fmt.get(k, 0) + 1
            sizes.append(len(b))
            m = rom_by_sha.get(sha)
            if m:
                matched += 1
            rows.append((os.path.basename(d), name, f"{k} {len(b)} B rom={'yes ' + os.path.basename(m[0]) + ' ' + str(m[1]) if m else 'no'}"))
    for r in rows:
        print(" | ".join(r).replace(" | ", "  "))
    print(f"packs with <patch>: {packs}; patch lines by format: {fmt}; largest {max(sizes) if sizes else 0} B; "
          f"lines whose source ROM is in the library: {matched}")


main()
