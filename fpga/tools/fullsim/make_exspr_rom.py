"""Write a tiny NROM test cartridge that puts more than 8 sprites on a line, for checking the
HD tap's extra-sprite path (the core's 16-sprite option, fullsim --ex-sprites).

The program clears the nametable, loads a palette, turns on NMI, BG and sprites, then spins.
The NMI copies a fixed 256-byte OAM table from ROM ($C100, OAM DMA reads PRG ROM directly)
every frame, so the sprites are there from the first frame NMI runs.

OAM table (in OAM order, which is the PPU's evaluation and priority order):
  row A, line 40:  16 sprites, X = 8 + 14*i, tiles cycle, palettes cycle, h/v flips from
                   bits 2/3 of i, two of them behind the background. 8 main + 8 extra.
  row B, line 120: 12 sprites. 8 main + 4 extra (extra slots 4-7 empty).
  row C, line 180: 10 sprites with the SAME y, tile and attribute: the core's masked_sprites
                   case (a game hiding sprites behind the 8-sprite limit), so its extra
                   sprites must not be drawn and must be recorded as not valid.
  row D, line 80:  8 sprites at one (y, x) with different tiles + 2 elsewhere: masked by Mesen's
                   adaptive rule (fullsim --nolimit), not by the core's heuristic.
  row E, line 5:   7 at one position + 2 at another (one short of Mesen's mask); also in range of
                   the pre-render line's evaluation, so it checks line 0.
  the rest off screen (y = $F0).
Consecutive sprites in rows A and B differ in tile, so they do not trip the masking test.

--tall uses 8x16 sprites (PPUCTRL bit 5): bit 0 of the tile index selects the pattern table,
so some row-A sprites come from $1000.

usage: make_exspr_rom.py OUT.nes [--tall]
"""
import argparse
import random


def assemble(tall):
    code = bytearray()
    labels = {}
    fix = []                                    # (offset of the branch operand, label)

    def emit(*b):
        code.extend(b)

    def label(n):
        labels[n] = 0xC000 + len(code)

    def br(op, n):
        emit(op, 0)
        fix.append((len(code) - 1, n))

    def abs_(op, a):
        emit(op, a & 0xFF, a >> 8)

    label("reset")
    emit(0x78, 0xD8, 0xA2, 0xFF, 0x9A)          # SEI CLD LDX #$FF TXS
    emit(0xA9, 0x00)                            # LDA #0
    abs_(0x8D, 0x2000)
    abs_(0x8D, 0x2001)
    label("w1")
    abs_(0x2C, 0x2002)                          # BIT $2002
    br(0x10, "w1")                              # BPL w1
    label("w2")
    abs_(0x2C, 0x2002)
    br(0x10, "w2")
    # nametable 0 (and its attribute table): 1024 zero bytes
    emit(0xA9, 0x20); abs_(0x8D, 0x2006)
    emit(0xA9, 0x00); abs_(0x8D, 0x2006)
    emit(0xA2, 0x00, 0xA0, 0x04)                # LDX #0 LDY #4
    label("nt")
    abs_(0x8D, 0x2007)                          # STA $2007 (A = 0)
    emit(0xE8)                                  # INX
    br(0xD0, "nt")                              # BNE nt
    emit(0x88)                                  # DEY
    br(0xD0, "nt")
    # palette
    emit(0xA9, 0x3F); abs_(0x8D, 0x2006)
    emit(0xA9, 0x00); abs_(0x8D, 0x2006)
    emit(0xA2, 0x00)
    label("pal")
    abs_(0xBD, 0xC200)                          # LDA $C200,X
    abs_(0x8D, 0x2007)
    emit(0xE8, 0xE0, 0x20)                      # INX CPX #$20
    br(0xD0, "pal")
    emit(0xA9, 0x00); abs_(0x8D, 0x2006); abs_(0x8D, 0x2006)
    emit(0xA9, 0xA0 if tall else 0x80)          # NMI on (+ 8x16 sprites)
    abs_(0x8D, 0x2000)
    emit(0xA9, 0x1E)                            # BG + sprites, left 8 pixels included
    abs_(0x8D, 0x2001)
    label("spin")
    abs_(0x4C, labels["spin"])                  # JMP spin
    label("nmi")
    emit(0x48, 0xA9, 0x00)                      # PHA LDA #0
    abs_(0x8D, 0x2003)
    emit(0xA9, 0xC1)
    abs_(0x8D, 0x4014)                          # OAM DMA from $C100
    emit(0x68, 0x40)                            # PLA RTI
    for off, n in fix:
        d = labels[n] - (0xC000 + off + 1)
        assert -128 <= d < 0, (n, d)
        code[off] = d & 0xFF
    assert len(code) <= 0x100
    return code, labels


def oam_table(tall):
    oam = [0xF0] * 256                          # y = $F0: off screen
    k = 0

    def put(y, tile, attr, x):
        nonlocal k
        oam[k:k + 4] = [y, tile, attr, x]
        k += 4

    for i in range(16):
        tile = 1 + (i % 4)
        if tall:
            tile = (2 * (1 + (i % 4))) | (1 if i % 3 == 0 else 0)
        attr = (i % 4) | (0x40 if i & 4 else 0) | (0x80 if i & 8 else 0) | (0x20 if i in (5, 13) else 0)
        put(39, tile, attr, 8 + 14 * i)
    for i in range(12):
        tile = 1 + (i % 3)
        if tall:
            tile = 2 * (1 + (i % 3))
        put(119, tile, (i + 1) % 4, 20 + 18 * i)
    for i in range(10):
        put(179, 4 if tall else 2, 1, 30 + 20 * i)
    # row D, line 80: 8 sprites stacked at ONE position with different tiles, then 2 elsewhere.
    # The core's heuristic (consecutive same y/tile/attr) does not see a mask, so extras load;
    # Mesen's adaptive rule (8 in-range sprites at one (y, x)) does, so with --nolimit they don't.
    # Row C is the opposite case: same y/tile/attr at different x - masked by the core, not by
    # Mesen.
    for i in range(10):
        tile = 1 + (i % 4)
        if tall:
            tile = 2 * (1 + (i % 4))
        put(79, tile, i % 4, 100 if i < 8 else 150 + 20 * (i - 8))
    # row E, y = 2 (lines 3-10): 7 stacked at one position, then 2 stacked at another - runs of
    # 7 and 2, one short of Mesen's mask, so extras load (a run that is not restarted at the new
    # position would reach 8). y = 2 is also in range of the core's pre-render line (it
    # evaluates with scanline 261, low byte 5), where Mesen loads nothing: line 0 must have no
    # extras.
    for i in range(9):
        tile = 1 + (i % 4)
        if tall:
            tile = 2 * (1 + (i % 4))
        put(2, tile, i % 4, 60 if i < 7 else 130)
    return bytes(oam)


def chr_data():
    rng = random.Random(1234)
    c = bytearray(8192)
    bg = [0x81, 0x42, 0x24, 0x18, 0x18, 0x24, 0x42, 0x81]
    c[0:8] = bytes(bg)                          # BG tile 0: an X, colour 1
    for base in (0x0000, 0x1000):
        for t in range(1, 16):
            for r in range(8):
                # asymmetric rows, mostly opaque, all three colours, so flips and the plane
                # order both show
                c[base + t * 16 + r] = rng.randrange(256) | (0x80 >> r)
                c[base + t * 16 + 8 + r] = rng.randrange(256) & ~(1 << r) & 0xFF
    return bytes(c)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--tall", action="store_true")
    a = ap.parse_args()
    code, labels = assemble(a.tall)
    prg = bytearray(16384)
    prg[0:len(code)] = code
    prg[0x100:0x200] = oam_table(a.tall)
    pal = [0x0F, 0x16, 0x27, 0x18] * 4 + [0x0F, 0x11, 0x21, 0x31, 0x0F, 0x14, 0x24, 0x34,
                                         0x0F, 0x1A, 0x2A, 0x3A, 0x0F, 0x17, 0x27, 0x37]
    prg[0x200:0x220] = bytes(pal)
    prg[0x3FFA:0x4000] = bytes([labels["nmi"] & 0xFF, labels["nmi"] >> 8,
                                labels["reset"] & 0xFF, labels["reset"] >> 8,
                                labels["reset"] & 0xFF, labels["reset"] >> 8])
    hdr = b"NES\x1a" + bytes([1, 1, 0, 0]) + bytes(8)
    with open(a.out, "wb") as f:
        f.write(hdr + bytes(prg) + chr_data())
    print(f"{a.out}: {len(code)} code bytes, reset ${labels['reset']:04X}, nmi ${labels['nmi']:04X}"
          f"{', 8x16 sprites' if a.tall else ''}")


if __name__ == "__main__":
    main()
