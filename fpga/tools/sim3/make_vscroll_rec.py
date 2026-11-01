"""Copy recorded frames into a fixture folder with the vertical scroll changed on bands of lines.

Every recorded frame keeps one vertical scroll for the whole picture (the games split the screen
horizontally only), so the background engine's cached vertical ratio (hd3_render bv_ys / bv_yval,
re-read when the line's scroll differs from the one it was read for) is never stale and the
"vertical ratio reused after the scroll changed" mutant cannot fail. Here lines with
y % 32 in 16..31 get their scroll Y moved by +DELTA (wrapping inside 0..479, the two nametable
halves), so the vertical scroll changes every 16 lines and each background level must re-read its
vertical ratio.

Only the line header's PPU t (q0 bits 0-14: coarse Y 5-9, nametable Y 11, fine Y 12-14) changes;
coarse X, nametable X and fine X are kept. The tiles of a line are recorded per pixel, so the SD
picture does not move - only what hdref and the RTL both derive from t (background scroll, the
addition scan's tile-row test) does. watch_*.bin files are copied unchanged.

usage: python make_vscroll_rec.py <src recdir> <dst dir> FRAME [...]
"""
import os
import shutil
import struct
import sys

DELTA = 24


def scroll_y(t):
    return (((t & 0x3E0) >> 2) | ((t & 0x7000) >> 12)) + (240 if t & 0x800 else 0)


def with_scroll_y(t, sy):
    half, v = (1, sy - 240) if sy >= 240 else (0, sy)
    t &= ~(0x3E0 | 0x800 | 0x7000) & 0x7FFF
    return t | ((v >> 3) << 5) | (half << 11) | ((v & 7) << 12)


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
            if y % 32 < 16:
                continue
            hoff = 0x40000 + y * 2048
            q0 = struct.unpack_from("<Q", rec, hoff)[0]
            t = q0 & 0x7FFF
            want = (scroll_y(t) + DELTA) % 480
            nt = with_scroll_y(t, want)
            if scroll_y(nt) != want or (nt & 0x41F) != (t & 0x41F):
                sys.exit(f"rec_{f}.bin line {y}: t {t:04x} -> {nt:04x} does not encode scroll {want}")
            struct.pack_into("<Q", rec, hoff, (q0 & ~0x7FFF) | nt)
            n += 1
        open(os.path.join(dst, f"rec_{f}.bin"), "wb").write(rec)
        print(f"rec_{f}.bin: vertical scroll moved on {n} lines")
    return 0


if __name__ == "__main__":
    sys.exit(main())
