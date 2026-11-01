"""Build a synthetic Mesen-format HD pack from a CHR-ROM game's own tiles.

Every CHR tile becomes a 16x16 tile: EPX (scale2x) smoothed, colour 0 transparent,
colours 1-3 recoloured to fixed bright values. Registered as default tiles (wildcard
palette), so every tile the game draws is replaced. Purpose: an end-to-end test pack
whose every pixel is predictable, in Mesen's own hires.txt format.

usage: python make_test_pack.py <rom.nes> <out_dir>
"""
import hashlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pngio import write_png  # noqa: E402

COLOURS = {1: (255, 64, 64, 255), 2: (64, 224, 64, 255), 3: (64, 128, 255, 255)}
TILES_PER_ROW = 32


def chr_rom(rom):
    if rom[:4] != b"NES\x1a":
        raise SystemExit("not an iNES file")
    prg = rom[4] * 16384
    chr_size = rom[5] * 8192
    if chr_size == 0:
        raise SystemExit("CHR-RAM game: not supported by the test version")
    start = 16 + (512 if rom[6] & 4 else 0) + prg
    return rom[start:start + chr_size]


def tile_pixels(chr_data, t):
    lo = chr_data[t * 16:t * 16 + 8]
    hi = chr_data[t * 16 + 8:t * 16 + 16]
    return [[((lo[y] >> (7 - x)) & 1) | (((hi[y] >> (7 - x)) & 1) << 1)
             for x in range(8)] for y in range(8)]


def epx(px):
    out = [[0] * 16 for _ in range(16)]
    for y in range(8):
        for x in range(8):
            p = px[y][x]
            a = px[y - 1][x] if y > 0 else p
            b = px[y][x + 1] if x < 7 else p
            c = px[y][x - 1] if x > 0 else p
            d = px[y + 1][x] if y < 7 else p
            e1 = a if (c == a and c != d and a != b) else p
            e2 = b if (a == b and a != c and b != d) else p
            e3 = c if (d == c and d != b and c != a) else p
            e4 = d if (b == d and b != a and d != c) else p
            out[2 * y][2 * x], out[2 * y][2 * x + 1] = e1, e2
            out[2 * y + 1][2 * x], out[2 * y + 1][2 * x + 1] = e3, e4
    return out


def main():
    rom_path, out_dir = sys.argv[1], sys.argv[2]
    with open(rom_path, "rb") as f:
        rom = f.read()
    chr_data = chr_rom(rom)
    ntiles = len(chr_data) // 16
    rows_t = (ntiles + TILES_PER_ROW - 1) // TILES_PER_ROW
    w, h = TILES_PER_ROW * 16, rows_t * 16
    img = [[(0, 0, 0, 0)] * w for _ in range(h)]
    lines = ["<ver>106", "<scale>2", "<img>tiles.png"]
    for t in range(ntiles):
        big = epx(tile_pixels(chr_data, t))
        ox, oy = (t % TILES_PER_ROW) * 16, (t // TILES_PER_ROW) * 16
        for y in range(16):
            row = img[oy + y]
            for x in range(16):
                row[ox + x] = COLOURS.get(big[y][x], (0, 0, 0, 0))
        lines.append(f"<tile>0,{t:X},FFFFFFFF,{ox},{oy},1,Y")
    os.makedirs(out_dir, exist_ok=True)
    write_png(os.path.join(out_dir, "tiles.png"), w, h, img)
    with open(os.path.join(out_dir, "hires.txt"), "w", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    print(f"{ntiles} tiles, sheet {w}x{h}, rom sha1 {hashlib.sha1(rom[16:]).hexdigest()}")


if __name__ == "__main__":
    main()
