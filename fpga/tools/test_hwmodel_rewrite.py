"""test_hwmodel_rewrite.py - the fallback-rewrite path of tools/hwmodel.py, on a frame built
to exercise it (no recorded frame does).

Mesen rewrites a looked-up record's TileIndex to its fallback when the exact key is missing
(spec 3.16); a tile condition read AFTER that sees the rewritten index. hwmodel reproduces it
from lookup order. This test takes a real frame of a pack that has rewrite-sensitive
conditions, clears it, and places on one line:

    T  a sprite whose key is rewritable and which a sensitive condition names
    Q  a sprite whose rule list uses that condition, offset so that it reads T

once with T BEFORE Q in Mesen's order (Mesen sees T rewritten) and once AFTER (Mesen sees the
original). Pass = hwmodel agrees with the Mesen-order reference on every lookup in both, AND
the negative control (tracking switched off) disagrees somewhere - otherwise the scene did
not exercise the path and the pass would mean nothing.

usage: python test_hwmodel_rewrite.py PACK.hdp RECDIR FRAME     (e.g. Metroid HD a034)
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hdref  # noqa: E402
import hwmodel  # noqa: E402

PASS = FAIL = 0


def check(ok, what):
    global PASS, FAIL
    if ok:
        PASS += 1
        print("PASS", what)
    else:
        FAIL += 1
        print("FAIL", what)


def all_keys(h):
    for b in range(h.nbuckets):
        base = h.s(0) + b * 64
        for j in range(4):
            q0, q1 = struct.unpack_from("<QQ", h.d, base + j * 16)
            if q1 >> 63:
                yield (q0 & 0xFFFFFFFF, q0 >> 32, (q1 >> 62) & 1, ((q1 >> 32) & 0x3FFFFFFF) * 8)


def sprite(idx, pal, x, sx, inst, hm=False):
    s = hdref.Rec.__new__(hdref.Rec)
    s.idx, s.pal, s.fp = idx, pal, hdref.ZERO_FP
    s.offx = x - sx
    s.offy = 0
    s.hm, s.vm, s.bgp = hm, False, False
    s.sci, s.scolor, s.bgci, s.bgcolor, s.ppubg, s.poff, s.inst = 1, 1, 0, 0, 0, 0x10, inst
    return s


def scene(h, rec, watch, game_ram, target, query, Y, tx, qx, qhm, track):
    m = hwmodel.HwModel(h, rec, watch, game_ram)
    if not track:
        m.tmatch = lambda c, t: hdref.HdRef.tmatch(m, c, t)
    for p in m.screen:
        p.tile.idx = hdref.NOTILE
        p.spr = []
    for (idx, pal, x0, inst, hm) in ((target[0], target[1], tx, 0, False),
                                     (query[0], query[1], qx, 1, qhm)):
        for x in range(x0, x0 + 8):
            if 0 <= x < 256:
                m.screen[(Y << 8) | x].spr.append(sprite(idx, pal, x, x0, inst, hm))
    m.render()
    return m


def main():
    hdp, recdir, frame = sys.argv[1], sys.argv[2], int(sys.argv[3])
    h = hdref.Hdp3(open(hdp, "rb").read())
    rec = open(os.path.join(recdir, f"rec_{frame:04d}.bin"), "rb").read()
    watch = open(os.path.join(recdir, f"watch_{frame:04d}.bin"), "rb").read()
    game_ram = bool(h.flags & 0x10)
    probe = hwmodel.HwModel(h, rec, watch, game_ram)
    # a sensitive condition with Y == 0 (target on the query's own line), used by a sprite key
    found = None
    for pal, lo, kind, off in all_keys(h):
        if kind != 0:
            continue
        for rule in probe.rules(off):
            for ci in rule["wl"]:
                c = probe.cond(ci)
                if not probe.sensitive(ci) or c["type"] != "spriteNearby" or c["ignore"]:
                    continue
                X, Yo = hdref.i32(c["q1"]), hdref.i32(c["q1"] >> 32)
                if Yo == 0 and probe.rewritable(c["q3"] & 0xFFFFFFFF, hdref.i64(c["q2"])):
                    found = (pal, lo, ci, X, hdref.i64(c["q2"]), c["q3"] & 0xFFFFFFFF)
                    break
            if found:
                break
        if found:
            break
    check(found is not None, "pack has a rewrite-sensitive spriteNearby on the same line")
    if not found:
        return 1
    qpal, qidx, ci, X, T, tpal = found
    print(f"   query key ({qpal:08x},{qidx}), condition {ci}: spriteNearby X={X} tile {T} "
          f"palette {tpal:08x}; T rewrites to {probe.fallback(T)}")
    # Q at qx reads x + X, or x - X when Q is horizontally mirrored (spec 3.9). The target is
    # looked up before Q exactly when it lies to Q's left on this line.
    Y, qx = 100, 120
    untracked_differs = 0
    for qhm in (False, True):
        d = -X if qhm else X
        tx = qx + d
        order = "T looked up first (left of Q)" if d < 0 else "Q looked up first (T to its right)"
        ms = scene(h, rec, watch, game_ram, (T, tpal), (qidx, qpal), Y, tx, qx, qhm, True)
        mo = scene(h, rec, watch, game_ram, (T, tpal), (qidx, qpal), Y, tx, qx, qhm, False)
        print(f"   Q mirrored={qhm}, {order}: T at x {tx}, Q at x {qx}: tracked "
              f"{len(ms.mism)} differ ({ms.checked} lookups, {ms.rewrites_seen} rewritten "
              f"reads), untracked {len(mo.mism)} differ, reference fallback hits "
              f"{ms.stats['fallback_hits']}")
        check(not ms.mism, f"Q mirrored={qhm}: with rewrite tracking, 0 differences")
        untracked_differs += len(mo.mism)
    check(untracked_differs > 0,
          "negative control: without tracking the model differs (the scene reaches the path)")
    return 1 if FAIL else 0


if __name__ == "__main__":
    r = main()
    print(f"{PASS} passed, {FAIL} failed")
    sys.exit(r)
