"""Check fullsim --watch output: every value hd_watch took at scanline 240 dot 0 against the
memory the simulation model held at that same clock (and the ROM file).

usage: check_watch.py DIR --rom game.nes
       check_watch.py --make-list game.nes OUT.txt     write a test list for that ROM

watch_FFFF.bin (tools/fullsim/fullsim.cpp --watch):
  "NWAT", u32 n, n x u32 list, n x u8 values, u32 flags (1 = overflow, 2 = SDRAM timeout),
  CPU RAM 2 KB (SDRAM 0x380000), CIRAM 2 KB (0x3A0000), PRG-RAM 8 KB (the page hd_watch
  tracked), palette 24 bytes (32 x 6 bits), u32 PRG-RAM base.

Expected values (MESEN_HD_RUNTIME_SPEC.md section 2.2):
  CPU $0000-$1FFF  CPU RAM, mirrored every 2 KB
  CPU $2000-$5FFF  0 (registers; hd_watch's documented limit)
  CPU $6000-$7FFF  PRG-RAM (not mapper 0: NROM has none, so the page is never learned)
  CPU $8000-$FFFF  PRG-ROM through the cart's mapping - checked for mapper 0 only
  PPU $0000-$1FFF  pattern memory - CHR-ROM games with mapper 0 only
  PPU $2000-$3EFF  nametables through the header's mirroring - mappers 0/2/3 only
  PPU $3F00-$3FFF  palette RAM, $10/$14/$18/$1C mirrored to $00/$04/$08/$0C
Entries a check cannot cover are counted as skipped, never as passed. A frame with a set flag
fails; a frame where nothing could be compared proves nothing and fails too.
"""
import glob
import os
import struct
import sys


def rom_info(path):
    d = open(path, "rb").read()
    if d[:4] != b"NES\x1a":
        sys.exit(f"{path}: not an iNES file")
    prg_n, chr_n, f6, f7 = d[4], d[5], d[6], d[7]
    off = 16 + (512 if f6 & 4 else 0)
    prg = d[off:off + prg_n * 16384]
    chr_rom = d[off + len(prg):off + len(prg) + chr_n * 8192]
    mapper = (f6 >> 4) | (f7 & 0xF0)
    mirror = "four" if f6 & 8 else ("vertical" if f6 & 1 else "horizontal")
    return dict(prg=prg, chr=chr_rom, mapper=mapper, mirror=mirror)


def expect(e, info, cpuram, ciram, prgram, pal):
    """(value, None) or (None, reason it cannot be checked)"""
    if e & 0x80000000:
        p = e & 0x3FFF
        if p >= 0x3F00:
            i = p & 0x1F
            if (i & 0x13) == 0x10:
                i &= 0x0F
            return pal[i] & 0x3F, None
        if p < 0x2000:
            if info["mapper"] != 0 or not info["chr"]:
                return None, "pattern: needs mapper 0 with CHR-ROM"
            return info["chr"][p], None
        if info["mapper"] not in (0, 2, 3) or info["mirror"] == "four":
            return None, "nametable: mirroring not known from the header"
        q = (p >> 10) & 3
        page = (q & 1) if info["mirror"] == "vertical" else (q >> 1)
        return ciram[page * 0x400 + (p & 0x3FF)], None
    c = e & 0xFFFF
    if c < 0x2000:
        return cpuram[c & 0x7FF], None
    if c < 0x6000:
        return 0, None
    if c < 0x8000:
        if info["mapper"] == 0:
            return None, "PRG-RAM: NROM has none (the page is never learned)"
        return prgram[c & 0x1FFF], None
    if info["mapper"] != 0:
        return None, "PRG-ROM: needs mapper 0"
    return info["prg"][(c - 0x8000) % len(info["prg"])], None


def check_file(path, info):
    d = open(path, "rb").read()
    if d[:4] != b"NWAT":
        return False, f"{os.path.basename(path)}: bad magic"
    n = struct.unpack_from("<I", d, 4)[0]
    o = 8
    lst = list(struct.unpack_from(f"<{n}I", d, o)); o += 4 * n
    vals = d[o:o + n]; o += n
    flags = struct.unpack_from("<I", d, o)[0]; o += 4
    cpuram = d[o:o + 0x800]; o += 0x800
    ciram = d[o:o + 0x800]; o += 0x800
    prgram = d[o:o + 0x2000]; o += 0x2000
    pbits = int.from_bytes(d[o:o + 24], "little"); o += 24
    pal = [(pbits >> (6 * k)) & 63 for k in range(32)]
    ok = bad = skip = 0
    first = []
    kinds = {}
    for i, e in enumerate(lst):
        want, why = expect(e, info, cpuram, ciram, prgram, pal)
        if why:
            skip += 1
            kinds[why] = kinds.get(why, 0) + 1
            continue
        if vals[i] == want:
            ok += 1
        else:
            bad += 1
            if len(first) < 8:
                first.append(f"  entry {i} ({e:08x}): hd_watch {vals[i]:02x}, model {want:02x}")
    good = bad == 0 and flags == 0 and ok > 0
    msg = (f"{os.path.basename(path)}: {ok} ok / {bad} bad / {skip} skipped"
           f"{', OVERFLOW' if flags & 1 else ''}{', SDRAM TIMEOUT' if flags & 2 else ''}"
           f"  {'OK' if good else 'FAIL'}")
    for k, v in kinds.items():
        msg += f"\n    skipped {v}: {k}"
    if first:
        msg += "\n" + "\n".join(first)
    return good, msg


def make_list(rom, out):
    """A deterministic list touching every address class and every mirror."""
    info = rom_info(rom)
    L = []
    L += [0x0000, 0x0001, 0x00FF, 0x0100, 0x01FF, 0x0300, 0x0400, 0x06FF, 0x07FF]
    L += [0x0800, 0x0F00, 0x1000 | 0x0756, 0x1800 | 0x0700, 0x1FFF]           # mirrors
    L += list(range(0x0700, 0x0780, 4))                                      # game state area
    L += [0x2000, 0x2002, 0x4016, 0x5FFF]                                    # registers -> 0
    if info["mapper"] != 0:                                                  # PRG-RAM
        L += [0x6000, 0x6001, 0x60FF, 0x6800, 0x6C00, 0x7000, 0x7400, 0x77FF, 0x7FFE, 0x7FFF]
    if info["mapper"] in (0,):
        L += [0x8000, 0x8001, 0x9FFF, 0xA000, 0xBFFF, 0xC000, 0xE000, 0xFFFA, 0xFFFC, 0xFFFF]
    pp = [0x3F00 + i for i in range(32)] + [0x3F20, 0x3F30, 0x3FFF, 0x3F80]
    L += [0x80000000 | p for p in pp]
    nt = [0x2000, 0x2001, 0x2041, 0x21E3, 0x23C0, 0x23FF, 0x2400, 0x2442, 0x27FF,
          0x2800, 0x2843, 0x2BFF, 0x2C00, 0x2C44, 0x2FFF, 0x3000, 0x3045, 0x3EFF]
    L += [0x80000000 | p for p in nt]
    if info["chr"]:
        L += [0x80000000 | p for p in (0x0000, 0x0010, 0x0FFF, 0x1000, 0x1234, 0x1FFF)]
    L = L[:256]
    with open(out, "w") as f:
        f.write(f"# watched-address test list for {os.path.basename(rom)} ({len(L)} entries)\n")
        for e in L:
            f.write(f"{e:08x}\n")
    print(f"{out}: {len(L)} entries")


def main():
    a = sys.argv[1:]
    if len(a) == 3 and a[0] == "--make-list":
        make_list(a[1], a[2])
        return 0
    if len(a) != 3 or a[1] != "--rom":
        print(__doc__)
        return 2
    info = rom_info(a[2])
    files = sorted(glob.glob(os.path.join(a[0], "watch_*.bin")))
    if not files:
        print("no watch_*.bin files")
        return 1
    passed = 0
    for p in files:
        good, msg = check_file(p, info)
        print(msg)
        passed += good
    print(f"{passed}/{len(files)} frames pass")
    return 0 if passed == len(files) else 1


if __name__ == "__main__":
    sys.exit(main())
