"""Compare Mesen 2 screenshots with our frames.

  align:   python mesen_cmp.py align RECDIR F SHOT.png [SHOT.png ...] [--xoff 2]
           Which Mesen no-pack screenshot shows the same NES frame as fullsim frame F?
           Compares col_FFFF.bin (the PPU's colour index per dot) with each 256x240 shot,
           palette-independently: a match means every colour index maps to exactly one RGB
           and no two indices share one (lines with grayscale/emphasis are compared too, since
           a palette mapping still applies per (index, effect) pair - counted separately).
  compare: python mesen_cmp.py compare OURS.png MESEN.png [--diff out.png]
           Pixel-exact comparison of two same-size RGB images (hdref vs Mesen with a pack).
           Prints the differing pixel count, the largest channel difference and the bounding
           box of the differences.
"""
import argparse
import os
import struct
import sys
import zlib

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pngdec  # noqa: E402
from hdp3_convert import to_2x  # noqa: E402  (the converter's reduction, so both sides match)


def load_png(path):
    _, _, a = pngdec.decode_fast(open(path, "rb").read())
    return np.asarray(a)[:, :, :3].astype(np.int32)


def write_png(path, img):
    hgt, wid = img.shape[:2]
    raw = b"".join(b"\x00" + img[r].astype(np.uint8).tobytes() for r in range(hgt))

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))

    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", wid, hgt, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b"")
    open(path, "wb").write(png)


def align(a):
    col = open(os.path.join(a.recdir, f"col_{a.frame:04d}.bin"), "rb").read()
    idx = np.zeros((240, 256), dtype=np.int32)
    for y in range(240):
        row = col[y * 341 + a.xoff: y * 341 + a.xoff + 256]
        idx[y] = np.frombuffer(row, dtype=np.uint8) & 63
    best = None
    for p in a.shots:
        img = load_png(p)
        if img.shape[:2] != (240, 256):
            print(f"{os.path.basename(p)}: {img.shape[1]}x{img.shape[0]}, expected 256x240")
            continue
        rgb = (img[..., 0] << 16) | (img[..., 1] << 8) | img[..., 2]
        fwd = {}
        bad = 0
        for i in range(64):
            m = idx == i
            if not m.any():
                continue
            vals, counts = np.unique(rgb[m], return_counts=True)
            fwd[i] = vals[np.argmax(counts)]
            bad += int(m.sum() - counts.max())
        coll = len(fwd) - len(set(fwd.values()))
        print(f"{os.path.basename(p)}: {bad} pixels off the per-index colour, "
              f"{coll} index collisions")
        if best is None or bad < best[0]:
            best = (bad, p)
    if best:
        print(f"best: {os.path.basename(best[1])} ({best[0]} pixels off)")
    return 0 if best and best[0] == 0 else 1


def compare(a):
    x = load_png(a.ours)
    y = load_png(a.mesen)
    if (y.shape[0] * 2, y.shape[1] * 2) == x.shape[:2]:
        # A scale-1 pack: Mesen draws at 1x, the hardware (and hdref) at 2x by repeating each
        # pixel 2x2. Every layer is per-pixel, so 2x of Mesen's frame is the exact expectation.
        y = y.repeat(2, axis=0).repeat(2, axis=1)
        print(f"(Mesen frame is 1x: compared after 2x pixel repeat)")
    elif y.shape[0] * 2 % x.shape[0] == 0 and y.shape[0] * 2 // x.shape[0] >= 3 and \
            y.shape[1] * 2 == x.shape[1] * (y.shape[0] * 2 // x.shape[0]):
        # A scale-s pack (s >= 3): the converter area-reduces every image to 2x (to_2x), so
        # Mesen's frame is reduced the same way. A pixel's footprint never leaves its NES
        # pixel, so this is exact wherever the top layer is opaque across that NES pixel;
        # where it is partly transparent (sprite edges) or translucent, reducing after
        # compositing differs from compositing reduced layers: expect small differences there.
        s = y.shape[0] * 2 // x.shape[0]
        rgba = np.concatenate([y, np.full(y.shape[:2] + (1,), 255, np.int32)], axis=2)
        y = to_2x(rgba.astype(np.uint8), s)[:, :, :3].astype(np.int32)
        print(f"(Mesen frame is {s}x: compared after the converter's area reduction to 2x)")
    if x.shape != y.shape:
        print(f"size differs: ours {x.shape[1]}x{x.shape[0]}, Mesen {y.shape[1]}x{y.shape[0]}")
        return 1
    d = np.abs(x - y).max(axis=2)
    n = int((d > 0).sum())
    if n == 0:
        print(f"IDENTICAL ({x.shape[1]}x{x.shape[0]})")
        return 0
    ys, xs = np.nonzero(d)
    print(f"{n} of {d.size} pixels differ, max channel difference {int(d.max())}, "
          f"box x {xs.min()}..{xs.max()} y {ys.min()}..{ys.max()}; "
          f"{int((d > 2).sum())} differ by more than 2, {int((d > 16).sum())} by more than 16")
    hist = np.bincount(np.minimum(d[d > 0], 255).ravel())
    top = sorted(((c, v) for v, c in enumerate(hist) if c), reverse=True)[:6]
    print("   most common differences: " + ", ".join(f"{v} ({c} px)" for c, v in top))
    if a.diff:
        vis = np.zeros_like(x)
        vis[..., 0] = np.where(d > 0, 255, x[..., 0] // 3)
        vis[..., 1] = np.where(d > 0, 0, x[..., 1] // 3)
        vis[..., 2] = np.where(d > 0, 0, x[..., 2] // 3)
        write_png(a.diff, vis)
        print(f"   diff image -> {a.diff}")
    return 1


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("align")
    p.add_argument("recdir")
    p.add_argument("frame", type=int)
    p.add_argument("shots", nargs="+")
    p.add_argument("--xoff", type=int, default=2)
    p = sub.add_parser("compare")
    p.add_argument("ours")
    p.add_argument("mesen")
    p.add_argument("--diff")
    a = ap.parse_args()
    return align(a) if a.cmd == "align" else compare(a)


if __name__ == "__main__":
    sys.exit(main())
