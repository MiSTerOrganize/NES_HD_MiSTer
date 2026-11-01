"""HD engine simulation: build a tap stimulus, run the Verilator model, check every pixel.

usage: python hd_sim.py <rom.nes> <pack_dir> <pack.hdp> <tb.exe> <work_dir> [busy%] [scene]

scene = "synthetic" (default) or "pack".
  synthetic: BG tiles from pattern table 1, a fixed palette, five sprites covering
             front/behind priority, h/v flip, overlap, an off-edge sprite and a dummy slot.
  pack:      palettes and tiles chosen from keys the pack really contains, keys that sit
             past their home slot (probe > 0) first, so the lookup's probing, the default
             fallback and the SD fallback are all exercised on real data. Runs 64 lines.

Expected pixels come from the pack's PNGs via the converter's own parse rules (exact key,
then the tile's default key, then the NES pixel), not from the .hdp, so the converter's atlas
extraction is checked as well as the core.
"""
import os
import subprocess
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
from pngio import read_png  # noqa: E402
import hdp_convert as H  # noqa: E402

CLK_PER_DOT = 4
DOTS = 341
LINE_CLK = CLK_PER_DOT * DOTS

SYN_PAL = [0x22, 0x29, 0x1A, 0x0F, 0x22, 0x36, 0x17, 0x0F, 0x22, 0x30, 0x21, 0x0F, 0x22, 0x27, 0x17,
           0x0F, 0x22, 0x16, 0x27, 0x18, 0x22, 0x1A, 0x30, 0x27, 0x22, 0x16, 0x30, 0x27, 0x22, 0x0F,
           0x36, 0x17]

# sprite slot: (valid, tile, x, y_top, attr)   attr: [7] vflip [6] hflip [5] behind [1:0] pal
SYN_SPRITES = [
    (1, 0x10, 20, 2, 0x41),    # front, hflip, pal 1
    (1, 0x20, 24, 2, 0xA2),    # behind BG, vflip, pal 2  (overlaps sprite 0 at x 24..27)
    (1, 0x31, 100, 3, 0x03),   # front, pal 3
    (0, 0x00, 0, 0, 0x00),     # dummy
    (1, 0x45, 250, 2, 0x20),   # behind, runs off the right edge
    (0, 0, 0, 0, 0), (0, 0, 0, 0, 0), (0, 0, 0, 0, 0),
]


def chr_rom(rom):
    prg = rom[4] * 16384
    start = 16 + (512 if rom[6] & 4 else 0) + prg
    return rom[start:start + rom[5] * 8192]


def field(word, lsb, width, value):
    return word | ((value & ((1 << width) - 1)) << lsb)


def split24(p):
    return [(p >> s) & 0x3F for s in (18, 12, 6, 0)]


def pack_scene(entries, probe_of, ntiles, legacy):
    """Palettes, BG tile lists per palette, and sprites, all taken from the pack's own keys.

    legacy: pre-100 pack, every key is kind 0 with colour 0 cleared, sprites included. The
    backdrop is then set non-zero so a core that forgot to clear colour 0 misses every key.
    """
    skind = 0 if legacy else 1
    def rank(kind):
        """pal24 -> (deepest probe, key count) over keys of this kind; deepest first."""
        r = {}
        for (t, k, p), pr in probe_of.items():
            if k == kind and t < ntiles:
                d, n = r.get(p, (0, 0))
                r[p] = (max(d, pr), n + 1)
        return r

    bg, sp = rank(0), rank(skind)
    c0 = Counter()
    for p, (d, n) in bg.items():
        c0[p >> 18] += d * 1000 + n          # the backdrop holding the deepest keys wins
    backdrop = c0.most_common(1)[0][0] if c0 else 0x0F
    bgpals = sorted((p for p in bg if p >> 18 == backdrop), key=lambda p: bg[p], reverse=True)[:4]
    sppals = sorted(sp, key=lambda p: sp[p], reverse=True)[:4]
    if legacy:
        sppals = sppals[1:] + sppals[:1]     # sprites use different keys from the background
        backdrop = 0x0F
    while len(bgpals) < 4:
        bgpals.append((backdrop << 18) | 0x30F0F)     # a palette the pack has no key for
    while len(sppals) < 4:
        sppals.append(0x30F0F)
    pal = []
    for p in bgpals:
        pal += [backdrop] + split24(p)[1:]
    for p in sppals:
        pal += [backdrop] + split24(p)[1:]

    def order(kind, p):
        ts = [t for (t, k, q) in entries if k == kind and q == p and t < ntiles]
        return sorted(ts, key=lambda t: (-probe_of[(t, kind, p)], t))

    defaults = sorted(t for (t, k, q) in entries if k == 2 and t < ntiles)
    bglists = []
    for i, p in enumerate(bgpals):
        exact = order(0, p)
        deep = [t for t in exact if probe_of[(t, 0, p)] > 0]
        rest = [t for t in exact if probe_of[(t, 0, p)] == 0]
        # tiles that only have a default key, and tiles with no key at all, near the front
        dflt = [t for t in defaults if (t, 0, p) not in entries][:4]
        nokey = [t for t in range(ntiles)
                 if (t, 0, p) not in entries and (t, 2, 0) not in entries][:4]
        bglists.append(deep + dflt + nokey + rest or [0])
    sprites = []
    xs = [20, 24, 100, 160, 250]
    attrs = [0x41, 0xA2, 0x03, 0x00, 0x20]
    for j in range(5):
        a = attrs[j]
        ts = order(skind, sppals[a & 3]) or defaults or [0]
        sprites.append((1, ts[j % len(ts)], xs[j], 2 + (j % 3) * 8, a))
    sprites.insert(3, (0, 0, 0, 0, 0))
    sprites = (sprites + [(0, 0, 0, 0, 0)] * 8)[:8]
    return pal, bglists, sprites


def main():
    rom_path, pack_dir, hdp, tb, work = sys.argv[1:6]
    busy = sys.argv[6] if len(sys.argv) > 6 else "25"
    scene = sys.argv[7] if len(sys.argv) > 7 else "synthetic"
    rom = open(rom_path, "rb").read()
    chrd = chr_rom(rom)
    ntiles = len(chrd) // 16

    _, scale, images, entries, _, _, _ = H.parse_pack(pack_dir)
    legacy = bool(open(hdp, "rb").read(8)[7] & 1)     # header flag bit 0, as the core reads it
    _, _, probe_of = H.build_table(entries, {a: i for i, a in enumerate(set(entries.values()))})

    if scene == "pack":
        PAL, bglists, SPRITES = pack_scene(entries, probe_of, ntiles, legacy)
        LINES = list(range(0, 64))

        def bg_tile(slot, y):
            lst = bglists[slot % 4]
            return lst[(slot // 4 + (y // 8) * 9) % len(lst)]
    else:
        PAL, SPRITES, LINES = SYN_PAL, SYN_SPRITES, list(range(0, 13))

        def bg_tile(slot, y):
            return 256 + ((slot * 7 + (y // 8) * 13) % 256)

    def pix(t, row, col):
        lo, hi = chrd[t * 16 + row], chrd[t * 16 + 8 + row]
        return ((lo >> (7 - col)) & 1) | (((hi >> (7 - col)) & 1) << 1)

    pal_bits = 0
    for i, v in enumerate(PAL):
        pal_bits |= v << (124 + 6 * i)

    events = {}

    def ev(clk, lsb, width, value):
        events[clk] = field(events.get(clk, pal_bits), lsb, width, value)

    def spr_rows(y):
        out = []
        for valid, t, x, yt, attr in SPRITES:
            r = y - yt
            ok = valid and 0 <= r < 8
            fr = (7 - r) if attr & 0x80 else r
            fr = fr if ok else 0
            lin = 0x200000 + t * 16 + fr
            lo = hi = 0
            for k in range(8):
                col = 7 - k if attr & 0x40 else k
                c = pix(t, fr, col) if ok else 0
                lo |= (c & 1) << k
                hi |= (c >> 1) << k
            out.append((ok, attr, x, lin, lo, hi))
        return out

    # line index in the stimulus: 0 = pre-render line (511), 1.. = LINES
    seq = [511] + LINES + [LINES[-1] + 1]
    for li, y in enumerate(seq):
        base = li * LINE_CLK
        nxt = seq[li + 1] if li + 1 < len(seq) else None
        # cycles 257-320 of this line: sprites for the next line
        if nxt is not None and nxt < 240:
            for k, (ok, attr, x, lin, lo, hi) in enumerate(spr_rows(nxt)):
                c = base + (257 + 8 * k) * CLK_PER_DOT
                ev(c, 31, 1, 1)
                ev(c, 32, 3, k)
                ev(c, 35, 55, (int(ok) << 54) | (attr << 46) | (x << 38) | (lin << 16) | (lo << 8) | hi)
        # cycles 328, 336: BG slots 0, 1 of the next line
        if nxt is not None and nxt < 240:
            for s, cyc in ((0, 328), (1, 336)):
                c = base + cyc * CLK_PER_DOT
                t = bg_tile(s, nxt)
                ev(c, 0, 1, 1); ev(c, 1, 6, s); ev(c, 7, 22, 0x200000 + t * 16 + nxt % 8); ev(c, 29, 2, s % 4)
        if y < 240:
            for s in range(2, 34):
                c = base + (8 * (s - 1)) * CLK_PER_DOT
                t = bg_tile(s, y)
                ev(c, 0, 1, 1); ev(c, 1, 6, s); ev(c, 7, 22, 0x200000 + t * 16 + y % 8); ev(c, 29, 2, s % 4)
            for x in range(256):
                c = base + (x + 1) * CLK_PER_DOT
                s = x // 8
                ci = pix(bg_tile(s, y), y % 8, x % 8)
                ev(c, 90, 1, 1); ev(c, 91, 8, x); ev(c, 99, 6, s); ev(c, 105, 3, x % 8)
                ev(c, 108, 4, ((s % 4) << 2) | ci); ev(c, 112, 1, 1); ev(c, 113, 1, 1)
        c = base + 256 * CLK_PER_DOT
        ev(c, 114, 1, 1); ev(c, 115, 9, y)

    stim = os.path.join(work, "stim.txt")
    with open(stim, "w") as f:
        f.write("BASE %080x\n" % pal_bits)
        for c in sorted(events):
            f.write("%d %080x\n" % (c, events[c]))
        # stop after the last output line pair, before the free-running output counter
        # would start repeating it (hardware always gets the next line_done)
        f.write("END %d\n" % ((len(seq) - 1) * LINE_CLK + 256 * CLK_PER_DOT + 1300))

    out = os.path.join(work, "out.bin")
    r = subprocess.run([tb, hdp, stim, out, busy], capture_output=True, text=True)
    sys.stderr.write(r.stderr)
    if r.returncode:
        raise SystemExit("tb failed")

    # ---- expected picture ----
    loaded = {}
    sdpal = open(hdp, "rb").read()[0x40:0x40 + 256]
    used = Counter()

    def lookup(t, kind, p):
        k = (t, kind, p)
        if k in entries:
            used["exact probe %d" % probe_of[k]] += 1
            return entries[k]
        if (t, 2, 0) in entries:
            used["default probe %d" % probe_of[(t, 2, 0)]] += 1
            return entries[(t, 2, 0)]
        used["SD fallback"] += 1
        return None

    def tex(akey, hx, hy):
        img, x, y, bright = akey
        if img not in loaded:
            loaded[img] = read_png(os.path.join(pack_dir, images[img]))
        # Written independently of hdp_convert.tile_rgba so a resampling bug there shows up.
        # The 2x output pixel (hx, hy) covers source [hx*s/2, (hx+1)*s/2) per axis; each source
        # pixel weighs its overlap (measured in half pixels).
        rows = loaded[img][2]

        def cover(o):
            a, b = o * scale, (o + 1) * scale
            out = []
            for i in range(a // 2, (b + 1) // 2):
                w = min(b, 2 * i + 2) - max(a, 2 * i)
                if w > 0:
                    out.append((i, w))
            return out

        box = [(rows[y + j][x + i], wj * wi) for j, wj in cover(hy) for i, wi in cover(hx)]
        solid = [(p, w) for p, w in box if p[3] >= 128]
        use = solid or box

        def lit(c):          # Mesen HdNesPack::AdjustBrightness; bright is its 0-255 integer
            return c if bright == 255 else min(255, (bright * (c + 1)) >> 8)
        tw = sum(w for _, w in use)
        rgb = tuple(sum(lit(p[c]) * w for p, w in use) // tw for c in range(3))
        return rgb, 2 * sum(w for _, w in solid) >= sum(w for _, w in box)

    def sd(n):
        v = PAL[n]
        return tuple(sdpal[v * 4:v * 4 + 3])

    def bg_key_pal(pi):
        c0 = 0 if legacy else PAL[0]
        return (c0 << 18) | (PAL[pi * 4 + 1] << 12) | (PAL[pi * 4 + 2] << 6) | PAL[pi * 4 + 3]

    def spr_key_pal(pi):
        b = 16 + pi * 4
        return (PAL[b + 1] << 12) | (PAL[b + 2] << 6) | PAL[b + 3]

    def expect(y, t, hx):
        x, sx = hx // 2, hx % 2
        s = x // 8
        bt = bg_tile(s, y)
        ak = lookup(bt, 0, bg_key_pal(s % 4))
        if ak is None:                                   # SD fallback: the NES pixel
            bci = pix(bt, y % 8, x % 8)
            bg_rgb, bg_draw = sd((s % 4) * 4 + bci), bci != 0
        else:
            bg_rgb, bg_draw = tex(ak, 2 * (x % 8) + sx, 2 * (y % 8) + t)
        cand = []
        for k, (ok, attr, X, lin, lo, hi) in enumerate(spr_rows(y)):
            rel = x - X
            if not ok or not 0 <= rel < 8:
                continue
            ci = ((lo >> rel) & 1) | (((hi >> rel) & 1) << 1)
            st = (lin - 0x200000) >> 4
            fr = lin & 7
            col = (2 * rel + sx) ^ (15 if attr & 0x40 else 0)
            row = 2 * fr + (t ^ (1 if attr & 0x80 else 0))
            ak = lookup(st, 0 if legacy else 1, spr_key_pal(attr & 3))
            if ak is None:
                rgb, a = sd(16 + (attr & 3) * 4 + ci), ci != 0
            else:
                rgb, a = tex(ak, col, row)
            cand.append((k, attr & 0x20, ci != 0, a, rgb))
        masked = False
        for k, behind, opq, a, rgb in cand:
            if behind and opq:
                masked = True
            if not behind and a and not masked:
                return rgb
        if bg_draw:
            return bg_rgb
        for k, behind, opq, a, rgb in cand:
            if behind and a:
                return rgb
        return sd(0)

    data = open(out, "rb").read()
    recs = [data[i:i + 5] for i in range(0, len(data), 5)]
    runs, cur = [], []
    for rec in recs:
        if rec[3] == 0 and rec[4] == 0:
            cur.append(tuple(rec[:3]))
        elif cur:
            runs.append(cur)
            cur = []
    if cur:
        runs.append(cur)
    print("scene %s: output lines %d (expected %d)" % (scene, len(runs), 2 * len(LINES)))
    bad = 0
    for i, run in enumerate(runs[:2 * len(LINES)]):
        y, t = LINES[i // 2], i % 2
        if len(run) != 512:
            print("line y=%d t=%d: length %d" % (y, t, len(run)))
            bad += 1
            continue
        for hx in range(512):
            e = expect(y, t, hx)
            if run[hx] != e:
                if bad < 20:
                    print("y=%d t=%d hx=%d got %s want %s" % (y, t, hx, run[hx], e))
                bad += 1
    if len(runs) != 2 * len(LINES):
        print("wrong number of output lines")
        bad += 1
    print("lookups checked:", ", ".join("%s %d" % kv for kv in sorted(used.items())))
    print("RESULT:", "PASS" if bad == 0 else "FAIL (%d mismatches)" % bad)
    sys.exit(0 if bad == 0 else 1)


if __name__ == "__main__":
    main()
