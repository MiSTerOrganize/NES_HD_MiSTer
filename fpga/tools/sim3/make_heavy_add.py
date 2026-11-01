"""Heavy additions fixture for the 8a dictionary: rewrite a pack's <addition> records so the
recorded frames exercise the merge (up to four lists per record, interleaved in file order),
the 64-entry merged-list cap and the 1,024-entry pool.

Modes:
  mixed  lists of 1..64 entries over many on-screen keys, every list kind used, all interleaved
         in file order; one merged list exactly 64 long; pool under 1,024 (no overflow)
  cap    as mixed, but one record's merged list is 65 long  -> the frame must overflow
  pool   many on-screen keys with long lists, pool over 1,024 -> the frame must overflow

Added keys are synthetic (bodies no tile or fingerprint can have), so no added key matches an
addition (no chains). Records not used are neutralised.

usage: python make_heavy_add.py IN.hdp RECDIR GAME_RAM FRAME MODE OUT.hdp [GOLDEN.tsv]
(GOLDEN = dict_golden.py's file for FRAME: the pool and list lengths are then measured over the
keys the dictionary actually captures, and pool1024 / pool1025 are trimmed to exactly that)"""
import os
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import hdref  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hdp3_addtab as at  # noqa: E402

REC = "<IIQIIQiiI20x"
NEVER = 0x7FFFFFF0


def main():
    src, recdir, gr, frame, mode, out = sys.argv[1:7]
    golden = sys.argv[7] if len(sys.argv) > 7 else None
    gr, frame = int(gr), int(frame)
    d = bytearray(open(src, "rb").read())
    h = hdref.Hdp3(bytes(d))
    rec = open(os.path.join(recdir, f"rec_{frame:04d}.bin"), "rb").read()
    watch = open(os.path.join(recdir, f"watch_{frame:04d}.bin"), "rb").read()
    ref = hdref.HdRef(h, rec, watch, bool(gr))
    kind = 1 if gr else 0

    def body(r):
        return (r.fp if gr else r.idx) & 0xFFFFFFFFFFFFFFFF

    def keyed(r):
        return r.fp is not None if gr else r.idx != hdref.NOTILE

    # distinct on-screen records (palette, body), BG and sprites, in screen order
    seen = []
    have = set()
    fbs = {}
    for p in ref.screen:
        for r in [p.tile] + list(p.spr):
            if keyed(r):
                k = (r.pal, body(r))
                if k not in have:
                    have.add(k)
                    seen.append(k)
                    if not gr and ref.has_fb:
                        f = ref.fallback(r.idx)
                        if f is not None and f >= 0 and f != r.idx:
                            fbs[k] = f
    if len(seen) < 12:
        sys.exit(f"only {len(seen)} distinct keys on this frame")
    print(f"{len(seen)} distinct on-screen keys, {len(fbs)} with a fallback")

    # each target key gets entries spread over its (up to four) table keys
    def table_keys(k):
        pal, b = k
        out = [(pal, b, 0), (0, b, 1)]                      # (opal, obody, ignore)
        if k in fbs:
            out += [(pal, fbs[k], 0), (0, fbs[k], 1)]
        return out

    # synthetic added keys: palette 0..63, body outside every real tile/fingerprint
    def added(n):
        return (n % 64, 0x7EEE000000000000 + n if gr else 0x7EEE0000 + n)

    # merged-list lengths per target key (an ANY-palette or fallback addition is SHARED by
    # every record with that body / fallback, so targets are chosen with distinct bodies and
    # distinct fallbacks to keep each target's list its own)
    targets = []
    bodies = set()
    fallbacks = set()
    for k in seen:
        f = fbs.get(k)
        if k[1] in bodies or (f is not None and (f in fallbacks or f in bodies)) or k[1] in fallbacks:
            continue
        bodies.add(k[1])
        if f is not None:
            fallbacks.add(f)
        targets.append(k)
    # the other on-screen records must match none of the targets' table keys; a record sharing
    # a target's body or fallback would get the ANY / fallback lists too - which is fine (the
    # checker derives every list from the table) but makes the lengths unpredictable, so the
    # pool / cap arithmetic below counts it from the table afterwards
    if mode == "mixed":
        lens = [64, 37, 22, 13, 9, 5, 3, 2, 1, 17, 29, 6]
    elif mode == "cap":
        lens = [65, 20, 11, 7, 3, 1]
    elif mode == "pool":
        lens = [60] * 22
    elif mode == "pool1024":
        lens = [64] * 16           # exactly the pool, each list exactly the buffer
    elif mode == "pool1025":
        lens = [64] * 15 + [63, 2]
    elif mode == "dup":
        # the targets are records first captured LATE in the frame (so their additions are
        # resolved after the capture ends, when the index could already have been cleared), and
        # the added keys are records captured EARLY, each used by several additions: every
        # injection must find the id the key already has
        if not golden:
            sys.exit("dup needs the golden file")
        ys = {}
        for line in open(golden):
            p = line.rstrip("\n").split("\t")
            if len(p) >= 10 and p[3] == "1":
                k = (int(p[4], 16), int(p[5], 16))
                y = int(p[1])
                lo, hi = ys.get(k, (y, y))
                ys[k] = (min(lo, y), max(hi, y))
        late_y = int(sys.argv[8]) if len(sys.argv) > 8 else 176
        late = [k for k in targets if k in ys and ys[k][0] >= late_y]
        banned = set()
        for t in late:
            banned.add(t[1])
            if t in fbs:
                banned.add(fbs[t])

        nf0 = struct.unpack_from("<I", d, 0x44)[0]
        fb0 = list(struct.unpack_from(f"<{nf0}i", d, struct.unpack_from("<I", d, 0x80 + 80)[0])) \
            if nf0 else []

        def fbk(b):
            return fb0[b] if (not gr and 0 <= b < len(fb0)) else -1
        early = [k for k in ys if ys[k][1] < 112 and k[1] not in banned and fbk(k[1]) not in banned
                 and k not in late]
        if len(late) < (2 if late_y > 200 else 6) or len(early) < 3:
            sys.exit(f"dup: {len(late)} late targets, {len(early)} early keys")
        targets = late
        # long lists: under a slow DDR3 (the lag suite) resolving them outlasts the capture
        nt = min(10, len(late))
        lens = [min(60, h.nadd // nt)] * nt

        def added(nn):                                  # noqa: F811
            return early[nn % len(early)]
        print(f"dup: {len(lens)} late targets (first line >= 176), {len(early)} early added keys")
    else:
        sys.exit("mode is mixed, cap or pool")
    if len(targets) < len(lens):
        sys.exit(f"only {len(targets)} usable target keys, need {len(lens)}")

    n = h.nadd
    base = h.s(11)
    nfb = struct.unpack_from("<I", d, 0x44)[0]
    fbl = list(struct.unpack_from(f"<{nfb}i", d, struct.unpack_from("<I", d, 0x80 + 80)[0])) \
        if nfb else []
    # the keys the dictionary captures on this frame (what the pool is counted over)
    gkeys = set()
    if golden:
        for line in open(golden):
            p = line.rstrip("\n").split("\t")
            if len(p) >= 10 and p[3] == "1":
                gkeys.add((int(p[4], 16), int(p[5], 16)))

    def write(lens):
        # per-target entry lists, interleaved round-robin in file order
        per = []
        an = 0
        for t, cnt in zip(targets, lens):
            tks = table_keys(t)
            ents = []
            for j in range(cnt):
                ok = tks[j % len(tks)]
                ak = added(an)
                an += 1
                ents.append((ok[0], ok[1], ak[0], ak[1], (j % 7) - 3, (j % 5) - 2, ok[2]))
            per.append(ents)
        recs = []
        while any(per):
            for ents in per:
                if ents:
                    recs.append(ents.pop(0))
        if len(recs) > n:
            sys.exit(f"pack has only {n} addition records, need {len(recs)}")
        for i in range(n):
            if i < len(recs):
                opal, ob, apal, ab, ox, oy, ign = recs[i]
                struct.pack_into(REC, d, base + 64 * i, opal, kind, ob, apal, kind, ab, ox, oy, ign)
            elif gr:
                struct.pack_into(REC, d, base + 64 * i, 0, 1, 0xFFFFFFFFFFFFFFF0, 0, 1,
                                 0xFFFFFFFFFFFFFFF1, 0, 0, 0)
            else:
                struct.pack_into(REC, d, base + 64 * i, 0, 0, NEVER, 0, 0, NEVER + 1, 0, 0, 0)
        return len(recs), an

    def measure():
        t, nb, mp, li = at.build(bytes(d[base:base + 64 * n]), n)
        ls = [len(at.matched(t, nb, mp, li, p, kind, b, fbl)) for p, b in gkeys]
        return sum(ls), max(ls) if ls else 0

    goal = {"pool1024": 1024, "pool1025": 1025}.get(mode)
    lens = list(lens)
    nrec, an = write(lens)
    tot, mx = measure() if gkeys else (None, None)
    while goal is not None and tot != goal:
        # trim the last target (sharing makes one entry worth more than one pool slot, so
        # step one entry at a time and re-measure)
        big = [i for i, v in enumerate(lens) if v > 1]
        if tot < goal or not big:
            sys.exit(f"cannot reach a pool of exactly {goal} (at {tot})")
        lens[big[-1]] -= 1
        nrec, an = write(lens)
        tot, mx = measure()
    open(out, "wb").write(bytes(d))
    print(f"{out}: {nrec} additions over {len(lens)} target keys "
          f"({sum(1 for t in targets[:len(lens)] if t in fbs)} with a fallback list), "
          f"{an} added keys; on this frame: pool {tot}, longest merged list {mx}")


if __name__ == "__main__":
    main()
