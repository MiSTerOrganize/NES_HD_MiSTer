"""Copy recorded frames into a fixture folder and, on one line of each, add a second sprite fetch
(in place of the line's first dummy fetch) that is the line's last real fetch moved 8 pixels
right and shifted to a DIFFERENT tile row, with the same tile, palette and flips. The render's
image-slot cache then sees two consecutive instances of one HD block on one line at different
rows; a slot reused on the block alone (row ignored) draws the second sprite with the first one's
row. No recorded frame has two such instances back to back on a line, so without this the row
check is never decisive.

Every line records 8 fetches, unused OAM slots as invalid dummies; the new fetch replaces the
first dummy. A candidate (line, new row) is kept only if, on the EDITED record, the reference
draws both sprites with the same image block (not the transparent payload, which takes no slot)
and that block's rows for the two tile rows differ - packs often pick a different block per
row, and an equal block row would draw the same pixels either way. The new fetch copies the
original's pattern bytes, so it covers the same pixels of its 8; sprites must be shown there.

The result is a legal frame record (the PPU fetches a sprite per OAM entry on the line); hdref
and the RTL both build their sprite lists from it. watch_*.bin files are copied unchanged.

--dx 0 puts the copy exactly over the original instead (same x, different row): both are drawn
as consecutive compose steps of every pixel they cover, nothing in between, so on a line whose
slots ran out (an NSLOT=4 build) they share the SCRATCH slot back to back - the only scene in which
the scratch slot's row check decides a pixel. --skip K takes the K+1-th qualifying line.

usage: python make_slotrow_rec.py PACK.hdp <src recdir> <dst dir> --game-ram G
                                  [--dx 0|8] [--skip K] FRAME [...]
"""
import os
import shutil
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import hdref  # noqa: E402


def line_fetches(rec, y):
    hoff = 0x40000 + y * 2048
    q0 = struct.unpack_from("<Q", rec, hoff)[0]
    nf = min((q0 >> 48) & 0xFF, 64)
    return hoff, [struct.unpack_from("<QQ", rec, hoff + 640 + k * 16) for k in range(nf)]


def payload(h, rec, watch, game_ram, y, inst, x0):
    """The reference's result for sprite record `inst` at the first pixel of x0..x0+7 it covers."""
    r = hdref.HdRef(h, bytes(rec), watch, game_ram)
    for x in range(x0, x0 + 8):
        s = next((s for s in r.screen[(y << 8) | x].spr if s.inst == inst), None)
        if s is not None:
            return r.get_matching(x, y, s)[0]
    return None


def edit(rec, hoff, n, qa, qb, row, dx):
    sx = (qa >> 38) & 0xFF
    nlin = (((qa >> 16) & 0x3FFFFF) & ~7) | row
    nqa = (qa & ~((0x3FFFFF << 16) | (0xFF << 38))) | (nlin << 16) | ((sx + dx) << 38)
    out = bytearray(rec)
    struct.pack_into("<QQ", out, hoff + 640 + n * 16, nqa, qb)
    return out


def pick(h, rec, watch, game_ram, dx=8, skip=0):
    top, right, bottom, left = [max(0, v) for v in h.overscan]
    why = {}

    def no(k):
        why[k] = why.get(k, 0) + 1

    for y in range(top, 240 - bottom):
        hoff, qs = line_fetches(rec, y)
        val = [(q[0] >> 54) & 1 for q in qs]
        n = sum(val)
        if n == 0 or n >= len(qs) or not all(val[:n]):
            no("no real sprite followed by a dummy fetch")
            continue
        qa, qb = qs[n - 1]
        sx = (qa >> 38) & 0xFF
        if sx + dx + 8 > 256 - right:
            no("off screen")
            continue
        if not all(rec[y * 1024 + x * 4] & 0x40 for x in range(sx + dx, sx + dx + 8)):
            no("sprites hidden")
            continue
        p0 = payload(h, rec, watch, game_ram, y, n - 1, sx)
        if p0 is None or p0 == 0xFFFFFFFF:
            no("no HD image")
            continue
        blk = h.block(p0 & 0x3FFFF)
        row0 = (qa >> 16) & 7
        for row in range(8):
            if row == row0 or (blk[2 * row:2 * row + 2] == blk[2 * row0:2 * row0 + 2]).all():
                continue
            out = edit(rec, hoff, n, qa, qb, row, dx)
            if payload(h, out, watch, game_ram, y, n, sx + dx) == p0:
                if skip:
                    skip -= 1
                    no("skipped (--skip)")
                    break
                return out, (y, n, sx, row0, row, p0)
        no("no row with the same block and different pixels")
    print("lines rejected:", why)
    return None, None


def main():
    a = sys.argv[1:]
    if len(a) < 6 or "--game-ram" not in a:
        print(__doc__)
        return 2
    opts = {"--dx": 8, "--skip": 0}
    for k in list(opts):
        if k in a:
            j = a.index(k)
            opts[k] = int(a[j + 1])
            a = a[:j] + a[j + 2:]
    if opts["--dx"] not in (0, 8):
        sys.exit("--dx must be 0 or 8")
    i = a.index("--game-ram")
    game_ram = bool(int(a[i + 1]))
    rest = a[:i] + a[i + 2:]
    hdp, src, dst, frames = rest[0], rest[1], rest[2], rest[3:]
    h = hdref.Hdp3(open(hdp, "rb").read())
    os.makedirs(dst, exist_ok=True)
    for f in frames:
        shutil.copy(os.path.join(src, f"watch_{f}.bin"), dst)
        rec = open(os.path.join(src, f"rec_{f}.bin"), "rb").read()
        watch = open(os.path.join(src, f"watch_{f}.bin"), "rb").read()
        out, info = pick(h, rec, watch, game_ram, opts["--dx"], opts["--skip"])
        if out is None:
            sys.exit(f"rec_{f}.bin: no qualifying line")
        open(os.path.join(dst, f"rec_{f}.bin"), "wb").write(out)
        y, n, sx, row0, row, p0 = info
        print(f"rec_{f}.bin: line {y}: fetch {n - 1} (x {sx}, row {row0}) copied as fetch {n} "
              f"at x {sx + opts['--dx']}, row {row}; both draw block {p0 & 0x3FFFF}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
