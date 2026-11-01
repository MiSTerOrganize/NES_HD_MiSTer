"""Build a fixture (a copy of one recorded frame + a copy of the pack) in which a rewrite-sensitive
spriteNearby condition reads a sprite AT THE SAME PIXEL that Mesen looks up AFTER the sprite
being evaluated - so the target is still unrewritten when the condition is evaluated, and only
the sprites' order within the pixel (the render's sprite phase) decides that.

Mesen looks a pixel up BG first, then the BG-priority sprites, then the front sprites, each from
the last record to the first (spec 3.16); a fallback hit rewrites the looked-up record's
TileIndex. hd3_render reproduces that from order: a target sprite counts as rewritten when it
precedes the evaluation in progress, and at one pixel its phase is what orders two sprites. No
recorded frame has a sensitive spriteNearby reading a sprite at the same pixel, so a renderer
that ignores the phase passes every test without this.

On a line whose real fetches come first and whose last real fetch F is drawn in HD (key K) with a
dummy fetch after it:
  B  fetch F gets a tile T whose key under F's palette is rewritable (exact key missing,
     fallback key found) and whose lookup draws nothing (no rule passes), and pattern bytes 0, so
     B covers its 8 pixels but draws nothing - A stays visible behind it
  A  the dummy fetch after F becomes a copy of the original F: same X, tile, palette, flips; as
     the later record, Mesen looks A up BEFORE B at every shared pixel
K's first rule gets its frame list cleared and a walk list of one condition (the walk list used
by the fewest rules whose condition is used nowhere else), rewritten to

    spriteNearby X=0 Y=0, tile T, F's palette compared, rewrite-sensitive

which is true on B's unrewritten record (A's lookup comes first) and false on a rewritten one
(checked: T's fallback chain does not lead back to T). A candidate is kept only if the reference
draws A with that rule on the edited frame. The reference (hdref.render) grades the render.

usage: python make_phase_frame.py PACK.hdp RECDIR FRAME OUT.hdp OUTRECDIR
"""
import os
import shutil
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # python -I drops the script dir
import hdref  # noqa: E402
import make_rewrite_frame as mrf  # noqa: E402


def rewritable_tiles(r, pal):
    """Tiles whose key under pal is missing and whose fallback key exists, lowest first."""
    out = []
    probe = hdref.Rec.__new__(hdref.Rec)
    probe.pal, probe.fp = pal, hdref.ZERO_FP
    for t in range(len(r.fb)):
        f = r.fallback(t)
        if f < 0 or f == t:
            continue
        probe.idx = t
        if r.find(pal, probe) is not None:
            continue
        probe.idx = f
        if r.find(pal, probe) is None and r.find(0xFFFFFFFF, probe) is None:
            continue
        if f == t or r.fallback(f) == t:
            continue
        out.append(t)
    return out


def main():
    a = sys.argv[1:]
    if len(a) != 5:
        print(__doc__)
        return 2
    hdp, recdir, frame, outp, outdir = a[0], a[1], a[2], a[3], a[4]
    data = bytearray(open(hdp, "rb").read())
    h = hdref.Hdp3(bytes(data))
    if h.flags & 0x10:
        sys.exit("CHR-RAM game: no fallback map, no rewrite")
    rec = bytearray(open(os.path.join(recdir, f"rec_{frame}.bin"), "rb").read())
    watch = open(os.path.join(recdir, f"watch_{frame}.bin"), "rb").read()
    r0 = hdref.HdRef(h, bytes(rec), watch, False)
    top, right, bottom, left = [max(0, v) for v in h.overscan]
    wl = mrf.pick_walk_list(h)
    if wl is None:
        sys.exit("no one-condition walk list with a private condition")
    w, nw, ci = wl
    tried = 0
    for y in range(top, 240 - bottom):
        hoff = 0x40000 + y * 2048
        q0 = struct.unpack_from("<Q", rec, hoff)[0]
        nf = min((q0 >> 48) & 0xFF, 64)
        qs = [struct.unpack_from("<QQ", rec, hoff + 640 + k * 16) for k in range(nf)]
        val = [(q[0] >> 54) & 1 for q in qs]
        n = sum(val)
        if n == 0 or n >= nf or not all(val[:n]):
            continue
        qa, qb = qs[n - 1]
        sx = (qa >> 38) & 0xFF
        if sx < left or sx + 8 > 256 - right:
            continue
        if not all(rec[y * 1024 + x * 4] & 0x40 for x in range(sx, sx + 8)):
            continue
        s0 = next((s for s in r0.screen[(y << 8) | sx].spr if s.inst == n - 1), None)
        if s0 is None:
            continue
        off = r0.find(s0.pal, s0)
        if off is None or r0.get_matching(sx, y, s0)[0] in (None, 0xFFFFFFFF):
            continue
        lin = (qa >> 16) & 0x3FFFFF
        for t in rewritable_tiles(r0, s0.pal)[:40]:
            tried += 1
            # B: F with tile T (same row and plane bits) and empty pattern bytes
            blin = (lin & ~0xFFFF0) | ((t << 4) & 0xFFFF0)
            if hdref.chr_index(blin) != t:
                continue
            bqa = (qa & ~((0x3FFFFF << 16) | 0xFFFF)) | (blin << 16)
            erec = bytearray(rec)
            struct.pack_into("<QQ", erec, hoff + 640 + (n - 1) * 16, bqa, qb)
            struct.pack_into("<QQ", erec, hoff + 640 + n * 16, qa, qb)        # A
            edata = bytearray(data)
            rw = h.s(1) + off + 8
            struct.pack_into("<I", edata, rw + 4, 0)
            struct.pack_into("<I", edata, rw + 8, w)
            struct.pack_into("<QQQQ", edata, h.s(2) + 32 * ci,
                             6 | (1 << 24), 0, t, s0.pal & 0xFFFFFFFF)
            eh = hdref.Hdp3(bytes(edata))
            er = hdref.HdRef(eh, bytes(erec), watch, False)
            p = er.screen[(y << 8) | sx]
            a_rec = next((s for s in p.spr if s.inst == n), None)
            b_rec = next((s for s in p.spr if s.inst == n - 1), None)
            if a_rec is None or b_rec is None:
                continue
            # B must draw nothing; A must take rule 0 (the condition true on unrewritten B)
            if er.get_matching(sx, y, b_rec)[0] is not None:
                continue
            er2 = hdref.HdRef(eh, bytes(erec), watch, False)
            p2 = er2.screen[(y << 8) | sx]
            a2 = next(s for s in p2.spr if s.inst == n)
            pay = er2.get_matching(sx, y, a2)[0]
            if pay != eh.rules(off)[0]["payload"]:
                continue
            os.makedirs(outdir, exist_ok=True)
            open(os.path.join(outdir, f"rec_{frame}.bin"), "wb").write(erec)
            shutil.copy(os.path.join(recdir, f"watch_{frame}.bin"), outdir)
            open(outp, "wb").write(edata)
            print(f"frame {frame} line {y}: fetch {n - 1} -> B tile {t} (transparent, rewritable "
                  f"under {s0.pal:08x}), fetch {n} -> A = old fetch {n - 1} (tile {s0.idx}) at x "
                  f"{sx}; A's rule 0 walks list {w} (was used by {nw} rules), c{ci} := "
                  f"spriteNearby(0,0) tile {t}, sensitive")
            return 0
    sys.exit(f"frame {frame}: no candidate ({tried} tiles tried)")


if __name__ == "__main__":
    sys.exit(main())
