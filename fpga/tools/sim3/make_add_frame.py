"""Synthetic additions fixture for 8a: rewrite a pack's <addition> records in place so ONE frame
exercises every rule the recorded frames never reach, then prove it does.

Rules forced (each must change the result when the model gets it wrong - checked below):
  bg      a BG tile source (process_bg: the next line is scanned too)
  order   two sources at different x feeding the same pixels, in reverse file order
  cap     four additions targeting their own source pixels, so the 4-sprite cap refuses some
  ignore  an ignore-palette addition on a sprite body under another palette
  fb      a fallback-matched addition (CHR-ROM packs with a fallback map only)
  zero    a source on line 239 aimed at pixel (0,0)
Every other addition record is neutralised (its original key can never occur).

usage: python make_add_frame.py IN.hdp RECDIR GAME_RAM FRAME OUT.hdp [--draw]
--draw prefers added keys that have an HD payload (render fixtures: the added sprites draw)."""
import collections
import os
import struct
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import hdref  # noqa: E402

REC = "<IIQIIQiiI20x"
NEVER = 0x7FFFFFF0          # an index no CHR has


def body_of(r, game_ram):
    return (1, r.fp) if game_ram else (0, r.idx & 0xFFFFFFFFFFFFFFFF)


def main():
    draw = "--draw" in sys.argv
    argv = [a for a in sys.argv if a != "--draw"]
    src, recdir, gr, frame, out = argv[1], argv[2], int(argv[3]), int(argv[4]), argv[5]
    d = bytearray(open(src, "rb").read())
    h = hdref.Hdp3(bytes(d))
    rec = open(os.path.join(recdir, f"rec_{frame:04d}.bin"), "rb").read()
    watch = open(os.path.join(recdir, f"watch_{frame:04d}.bin"), "rb").read()
    ref = hdref.HdRef(h, rec, watch, bool(gr))
    sc = ref.screen

    def keyed(r):
        return r.fp is not None if gr else r.idx != hdref.NOTILE

    bgcnt = collections.Counter()
    bgrec = {}
    spcnt = collections.Counter()
    sprec = {}
    for i, p in enumerate(sc):
        if keyed(p.tile):
            k = (p.tile.pal, body_of(p.tile, gr))
            bgcnt[k] += 1
            bgrec.setdefault(k, (i, p.tile))
        for s in p.spr:
            if keyed(s):
                k = (s.pal, body_of(s, gr))
                spcnt[k] += 1
                sprec.setdefault(k, (i, s))
    # a BG key covering few pixels, with two instances 16 px apart on one line: the pixel
    # between them then receives from both sources, so the ORDER rule decides its list
    pair = set()
    for i, p in enumerate(sc):
        if (i & 255) + 16 < 256 and keyed(p.tile):
            q = sc[i + 16].tile
            if keyed(q) and (q.pal, body_of(q, gr)) == (p.tile.pal, body_of(p.tile, gr)):
                pair.add((p.tile.pal, body_of(p.tile, gr)))
    pool = sorted((v, k) for k, v in bgcnt.items() if k in pair)
    if not pool:
        sys.exit("no BG key with two instances 16 px apart on this frame")
    bg_small = pool[0][1]
    sp_keys = [k for k, _ in spcnt.most_common()]
    sp_a = sp_keys[0]
    # a sprite body that also appears (or not) under another palette: ignore-palette match
    sp_ign = sp_keys[1] if len(sp_keys) > 1 else sp_keys[0]
    # added keys: on-screen keys used as nothing's original. With --draw, keys whose own
    # on-screen record finds an HD payload come first, so the added sprites are DRAWN and the
    # picture depends on the lanes (the render test needs that; the lane test does not)
    originals = {bg_small, sp_a, sp_ign}
    cand = [k for k in list(bgcnt) + sp_keys if k not in originals]
    if draw:
        def drawn(k):
            i, r = bgrec.get(k) or sprec[k]
            pay, _ = ref.get_matching(i & 255, i >> 8, r)
            # 0xFFFFFFFF is a fully transparent payload: it draws nothing
            return pay is not None and pay != 0xFFFFFFFF
        cand.sort(key=lambda k: not drawn(k))      # stable: drawn keys first, order kept
        print(f"  --draw: {sum(1 for k in cand[:8] if drawn(k))} of the 8 added keys draw")
    added = []
    for k in cand:
        if k[1] in [o[1] for o in originals]:
            continue
        added.append(k)
        if len(added) == 8:
            break
    if len(added) < 8:
        sys.exit("not enough distinct added keys on this frame")
    # a source on line 239 for the (0,0) rule
    l239 = [(x, sc[(239 << 8) | x]) for x in range(256)]
    z = next(((x, p.tile) for x, p in l239 if keyed(p.tile)), None)
    recs = []                 # (opal, (okind, obody), apal, (akind, abody), ox, oy, ignore)
    recs.append((bg_small[0], bg_small[1], added[0][0], added[0][1], -8, 0, 0))   # order: first in
    recs.append((bg_small[0], bg_small[1], added[1][0], added[1][1], 8, 0, 0))    # file order, later x
    for j in range(4):                                                           # cap
        recs.append((sp_a[0], sp_a[1], added[2 + (j & 1)][0], added[2 + (j & 1)][1], 0, 0, 0))
    recs.append((0, sp_ign[1], added[4][0], added[4][1], 0, 8, 1))               # ignore palette
    fb_note = "no fallback map"
    if not gr and ref.has_fb:
        # an on-screen BG tile whose fallback exists: key the addition on the FALLBACK index
        for k, (i, t) in bgrec.items():
            f = ref.fallback(t.idx)
            if f is not None and f >= 0 and f != t.idx:
                recs.append((t.pal, (0, f & 0xFFFFFFFFFFFFFFFF), added[5][0], added[5][1], 0, -8, 0))
                recs.append((0, (0, f & 0xFFFFFFFFFFFFFFFF), added[6][0], added[6][1], 8, 8, 1))
                fb_note = f"tile {t.idx} -> fallback {f}"
                break
    if z:
        x0, t0 = z
        recs.append((t0.pal, body_of(t0, gr), added[7][0], added[7][1], -x0, -239, 0))
    n = h.nadd
    if len(recs) > n:
        sys.exit(f"pack has only {n} addition records")
    base = h.s(11)
    for i in range(n):
        if i < len(recs):
            opal, (ok, ob), apal, (ak, ab), ox, oy, ign = recs[i]
        else:
            # never matched, and its added key is not its own original (that would be a chain)
            opal, ok, ob, apal, ak, ab, ox, oy, ign = 0, 0, NEVER, 0, 0, NEVER + 1, 0, 0, 0
            if gr:
                ok, ob, ak, ab = 1, 0xFFFFFFFFFFFFFFF0, 1, 0xFFFFFFFFFFFFFFF1
        struct.pack_into(REC, d, base + 64 * i, opal, ok, ob, apal, ak, ab, ox, oy, ign)
    open(out, "wb").write(bytes(d))
    print(f"{out}: {len(recs)} additions written ({fb_note}; zero-source {'yes' if z else 'NO'})")
    # prove it: the model equals hdref, and every mutant differs on this frame
    model = os.path.join(HERE, "addmodel.py")
    args = [sys.executable, "-I", model, out, recdir, str(gr), str(frame)]
    r = subprocess.run(args, capture_output=True, text=True)
    print("  model:", r.stdout.strip().splitlines()[-1] if r.stdout else r.stderr[-300:])
    if r.returncode != 0:
        sys.exit("model differs from hdref on the fixture")
    has_fb_rec = fb_note != "no fallback map"
    muts = ["order", "cap", "copy", "nobg", "nochain", "noign"] + (["nofb"] if has_fb_rec else [])
    for m in muts:
        r = subprocess.run(args, capture_output=True, text=True,
                           env=dict(os.environ, ADDMODEL_MUT=m))
        caught = r.returncode == 1
        print(f"  mutant {m}: {'caught' if caught else 'NOT CAUGHT'}")
        if not caught:
            sys.exit(f"the fixture does not exercise rule '{m}'")


if __name__ == "__main__":
    main()
