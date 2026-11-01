"""Copy recorded frames into a fixture folder with the PPU's grayscale and colour-emphasis bits set
on bands of lines (line header q0: bit 18 grayscale, bits 19-21 emphasis R/G/B). Games set these
rarely and none of the recorded frames do, so without this the render's line effects
(hdref.line_effects: grayscale average, emphasis scale) are never decisive.

Bands, by line number y: y % 32 in 4..7 grayscale; 12..15 emphasis 1 (R); 20..23 emphasis 6
(G+B); 28..31 grayscale + emphasis 7. Everything else is unchanged. The result is a legal frame
record (PPUMASK is written per line); hdref and the RTL both read the bits from it.
watch_*.bin files are copied unchanged.

usage: python make_effects_rec.py <src recdir> <dst dir> FRAME [...]
"""
import os
import shutil
import struct
import sys

BANDS = {range(4, 8): (1, 0), range(12, 16): (0, 1), range(20, 24): (0, 6), range(28, 32): (1, 7)}


def main():
    a = sys.argv[1:]
    if len(a) < 3:
        print(__doc__)
        return 2
    src, dst, frames = a[0], a[1], a[2:]
    os.makedirs(dst, exist_ok=True)
    for f in frames:
        shutil.copy(os.path.join(src, f"watch_{f}.bin"), dst)
        rec = bytearray(open(os.path.join(src, f"rec_{f}.bin"), "rb").read())
        n = 0
        for y in range(240):
            for band, (gray, emph) in BANDS.items():
                if y % 32 in band:
                    hoff = 0x40000 + y * 2048
                    q0 = struct.unpack_from("<Q", rec, hoff)[0]
                    if (q0 >> 18) & 0xF:
                        sys.exit(f"rec_{f}.bin line {y} already has effect bits set")
                    q0 |= (gray << 18) | (emph << 19)
                    struct.pack_into("<Q", rec, hoff, q0)
                    n += 1
        open(os.path.join(dst, f"rec_{f}.bin"), "wb").write(rec)
        print(f"rec_{f}.bin: effect bits set on {n} lines")
    return 0


if __name__ == "__main__":
    sys.exit(main())
