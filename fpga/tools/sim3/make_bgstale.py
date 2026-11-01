"""Stale-candidate fixture for the hd3_resolve background index (8i). Resolve marks a level's
index candidates in a bitmap tagged with the level, and clears it at the start of every frame.
A bitmap NOT cleared keeps frame A's candidates into frame B: an entry whose signature matched
in A but not in B would still be tried in B. The converter moves the signature's eq terms out
of the entry's own condition list, so such an entry is ACCEPTED if the rest of its conditions
hold - a wrong selection. No recorded pair of consecutive frames shows that, so the negative
control's "bitmap not cleared" mutant passed every run.

For consecutive frames (A, B) of a run, this looks for an indexed level L and entry E that is
a candidate in A but not in B, lies before B's real selection (or B selects nothing although
it has candidates), and has no other candidate of a level processed between L-in-A and L-in-B
writing its bitmap word. E's own condition list is then emptied (always true), so the stale
candidate is accepted in B by a renderer that keeps the bitmap. The pack stays
self-consistent (goldens are made from it).

usage: python make_bgstale.py IN.hdp RECDIR GAME_RAM OUT.hdp FRAME FRAME [FRAME...]"""
import os
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import hdref  # noqa: E402
from hdp3_convert import crc32  # noqa: E402


def refs(h, d, recdir, gr, f):
    rec = open(os.path.join(recdir, f"rec_{f:04d}.bin"), "rb").read()
    watch = open(os.path.join(recdir, f"watch_{f:04d}.bin"), "rb").read()
    return hdref.HdRef(hdref.Hdp3(bytes(d)), rec, watch, bool(gr))


def words(h, r, lvls):
    """Bitmap words (entry >> 5) every indexed level writes in a frame, by level."""
    out = {}
    for lvl in lvls:
        _, ioff = h.bg_level(lvl)
        out[lvl] = {e >> 5 for e in h.bg_index_candidates(ioff, r.snap)}
    return out


def main():
    a = sys.argv[1:]
    src, recdir, gr, outp = a[0], a[1], int(a[2]), a[3]
    frames = [int(f) for f in a[4:]]
    d = bytearray(open(src, "rb").read())
    h = hdref.Hdp3(bytes(d))
    idx = [lvl for lvl in range(40) if h.bg_level(lvl)[0] and h.bg_level(lvl)[1]]
    if not idx:
        sys.exit("no indexed background level")
    for fa, fb in zip(frames, frames[1:]):
        ra, rb = refs(h, d, recdir, gr, fa), refs(h, d, recdir, gr, fb)
        wa, wb = words(h, ra, idx), words(h, rb, idx)
        for lvl in idx:
            roff, ioff = h.bg_level(lvl)
            rl = rb.rules(roff)
            ca = list(h.bg_index_candidates(ioff, ra.snap))
            cb = list(h.bg_index_candidates(ioff, rb.snap))
            if not cb:
                continue
            selb = next((e for e in cb if all(rb.eval_cond(ci, 0, 0, None)
                                               for ci in rl[e]["fl"])), None)
            for e in sorted(set(ca) - set(cb)):
                if selb is not None and e > selb:
                    break
                w = e >> 5
                # resolve scans only the words B's own candidates touch ([wmin, wmax])
                if not min(c >> 5 for c in cb) <= w <= max(c >> 5 for c in cb):
                    continue
                # levels after L in A and before L in B must not write word w
                if any(w in wa[o] for o in idx if o > lvl) or \
                   any(w in wb[o] for o in idx if o < lvl):
                    continue
                # empty E's own condition list (rule +4 = frame list offset)
                struct.pack_into("<I", d, h.s(1) + roff + 8 + 16 * e + 4, 0)
                # E must not change A's selection order relative to the test: recompute B
                rb2 = refs(h, d, recdir, gr, fb)
                rl2 = rb2.rules(roff)
                selb2 = next((x for x in cb if all(rb2.eval_cond(ci, 0, 0, None)
                                                   for ci in rl2[x]["fl"])), None)
                if selb2 != selb:
                    struct.pack_into("<I", d, h.s(1) + roff + 8 + 16 * e + 4,
                                     rl[e]["frame"] if "frame" in rl[e] else 0)
                    continue
                open(outp, "wb").write(bytes(d))
                print(f"{outp}: level {lvl} entry {e}: candidate on frame {fa}, not on "
                      f"{fb}; frame {fb} selects {selb}; entry conditions emptied")
                return 0
    # no natural case: re-key one table bucket of a signature to frame A's values (the
    # candidates it lists become A-only), as make_sigmask.py re-places a table
    s13 = h.s(13)
    for fa, fb in zip(frames, frames[1:]):
        ra, rb = refs(h, d, recdir, gr, fa), refs(h, d, recdir, gr, fb)
        wa, wb = words(h, ra, idx), words(h, rb, idx)
        for lvl in idx:
            roff, ioff = h.bg_level(lvl)
            rl = rb.rules(roff)
            cb = list(h.bg_index_candidates(ioff, rb.snap))
            if not cb:
                continue
            lo, hi = min(c >> 5 for c in cb), max(c >> 5 for c in cb)
            selb = next((e for e in cb if all(rb.eval_cond(ci, 0, 0, None)
                                               for ci in rl[e]["fl"])), None)
            base = s13 + ioff
            (nsig,) = struct.unpack_from("<I", d, base)
            for k in range(nsig):
                p = base + 4 + 48 * k
                n = d[p]
                terms = [(d[p + 2 + 2 * j], d[p + 3 + 2 * j]) for j in range(n)]
                toff, nb, maxp = struct.unpack_from("<III", d, p + 34)
                va = bytes(ra.snap[sl] & mk for sl, mk in terms) + bytes(16 - n)
                vb = bytes(rb.snap[sl] & mk for sl, mk in terms) + bytes(16 - n)
                if va == vb:
                    continue
                ents = []
                for b in range(nb):
                    e = s13 + toff + 32 * b
                    lst, cnt, valid = struct.unpack_from("<III", d, e + 16)
                    if valid:
                        ents.append([bytes(d[e:e + 16]), lst, cnt])
                if any(key == va for key, _, _ in ents):
                    continue                        # the natural search covered it
                for xi, (key, lst, cnt) in enumerate(ents):
                    if key == vb:
                        continue
                    lx = struct.unpack_from(f"<{cnt}I", d, s13 + lst)
                    pick = None
                    for e in sorted(lx):
                        if e in cb or (selb is not None and e > selb):
                            continue
                        w = e >> 5
                        if not lo <= w <= hi:
                            continue
                        if any(w in wa[o] for o in idx if o > lvl) or \
                           any(w in wb[o] for o in idx if o < lvl):
                            continue
                        pick = e
                        break
                    if pick is None:
                        continue
                    ents[xi][0] = va
                    slots = [None] * nb
                    mp = 0
                    for kk, ll, cc in ents:
                        hh = crc32(kk) & (nb - 1)
                        for probe in range(nb):
                            bb = (hh + probe) & (nb - 1)
                            if slots[bb] is None:
                                slots[bb] = (kk, ll, cc)
                                mp = max(mp, probe)
                                break
                    for bb in range(nb):
                        e = s13 + toff + 32 * bb
                        if slots[bb] is None:
                            d[e:e + 32] = bytes(32)
                        else:
                            kk, ll, cc = slots[bb]
                            d[e:e + 32] = kk + struct.pack("<IIII", ll, cc, 1, 0)
                    struct.pack_into("<I", d, p + 42, mp)
                    struct.pack_into("<I", d, h.s(1) + roff + 8 + 16 * pick + 4, 0)
                    # re-derive with the fixture and confirm the case holds
                    h2 = hdref.Hdp3(bytes(d))
                    ra2, rb2 = refs(h2, d, recdir, gr, fa), refs(h2, d, recdir, gr, fb)
                    ca2 = h2.bg_index_candidates(ioff, ra2.snap)
                    cb2 = h2.bg_index_candidates(ioff, rb2.snap)
                    if pick not in ca2 or pick in cb2 or list(cb2) != cb:
                        sys.exit(f"synthesis did not hold (level {lvl} sig {k} entry {pick})")
                    open(outp, "wb").write(bytes(d))
                    print(f"{outp}: level {lvl} signature {k}: bucket re-keyed to frame {fa}'s "
                          f"values; entry {pick} (word {pick >> 5}, frame {fb} scans words "
                          f"{lo}-{hi}) is a candidate on {fa} only; frame {fb} selects {selb}; "
                          f"entry conditions emptied")
                    return 0
    sys.exit("no stale-candidate case on these frames")


if __name__ == "__main__":
    sys.exit(main())
