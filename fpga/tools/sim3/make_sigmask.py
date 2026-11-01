"""Masked-signature fixture for the hd3_resolve BG index (8i): every pack in the corpus writes
memoryCheckConstant masks of 0xFF, so nothing exercises the term mask. This copies a pack and,
for chosen index entries that MATCH on a recorded frame, gives one of the signature's terms a
mask that clears a bit SET in that frame's snapshot value (and clears the same bit in every
entry key of that signature, re-placing the table - as hdp3_convert would have built it from
a `mask` argument). With the mask the entry still matches; ignoring the mask it cannot.

The pack stays self-consistent: hdref / bg_golden read the same index, so goldens are made
from the fixture itself.

usage: python make_sigmask.py IN.hdp RECDIR GAME_RAM OUT.hdp FRAME [FRAME...] [--max N]"""
import os
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import hdref  # noqa: E402
from hdp3_convert import crc32  # noqa: E402


def main():
    a = sys.argv[1:]
    mx = 8
    if "--max" in a:
        i = a.index("--max")
        mx = int(a[i + 1])
        del a[i:i + 2]
    src, recdir, gr, out = a[0], a[1], int(a[2]), a[3]
    frames = [int(f) for f in a[4:]]
    d = bytearray(open(src, "rb").read())
    h = hdref.Hdp3(bytes(d))
    s13 = h.s(13)
    snaps = []
    for f in frames:
        rec = open(os.path.join(recdir, f"rec_{f:04d}.bin"), "rb").read()
        watch = open(os.path.join(recdir, f"watch_{f:04d}.bin"), "rb").read()
        snaps.append((f, hdref.HdRef(h, rec, watch, bool(gr)).snap))
    done = []
    for lvl in range(40):
        if len(done) >= mx:
            break
        _, ioff = h.bg_level(lvl)
        if not ioff:
            continue
        base = s13 + ioff
        (nsig,) = struct.unpack_from("<I", d, base)
        for k in range(nsig):
            if len(done) >= mx:
                break
            p = base + 4 + 48 * k
            n = d[p]
            terms = [(d[p + 2 + 2 * j], d[p + 3 + 2 * j]) for j in range(n)]
            if not n or any(mk != 0xFF for _, mk in terms):
                continue
            toff, nb, maxp = struct.unpack_from("<III", d, p + 34)
            ents = []
            for b in range(nb):
                e = s13 + toff + 32 * b
                lst, cnt, valid = struct.unpack_from("<III", d, e + 16)
                if valid:
                    ents.append([bytearray(d[e:e + 16]), lst, cnt])
            pick = None
            for f, snap in snaps:
                vals = bytes(snap[sl] for sl, _ in terms) + bytes(16 - n)
                if not any(bytes(e[0]) == vals for e in ents):
                    continue
                for j, (sl, _) in enumerate(terms):
                    if snap[sl]:
                        pick = (f, j, snap[sl] & -snap[sl])
                        break
                if pick:
                    break
            if not pick:
                continue
            f, j, bit = pick
            m = 0xFF & ~bit
            keys = [bytes(e[0][:j]) + bytes([e[0][j] & m]) + bytes(e[0][j + 1:]) for e in ents]
            if len(set(keys)) != len(keys):
                continue                        # masking would merge two entries: skip
            # rebuild the table in place: same size, linear probing from crc32(key)
            slots = [None] * nb
            mp = 0
            for key, (_, lst, cnt) in zip(keys, ents):
                hh = crc32(key) & (nb - 1)
                for probe in range(nb):
                    b = (hh + probe) & (nb - 1)
                    if slots[b] is None:
                        slots[b] = (key, lst, cnt)
                        mp = max(mp, probe)
                        break
            for b in range(nb):
                e = s13 + toff + 32 * b
                if slots[b] is None:
                    d[e:e + 32] = bytes(32)
                else:
                    key, lst, cnt = slots[b]
                    d[e:e + 32] = key + struct.pack("<IIII", lst, cnt, 1, 0)
            d[p + 3 + 2 * j] = m
            struct.pack_into("<I", d, p + 42, mp)
            done.append((lvl, k, j, m, f))
    if not done:
        sys.exit("no matching index entry with a non-zero term on these frames")
    open(out, "wb").write(bytes(d))
    print(f"{out}: {len(done)} masked terms: "
          + " ".join(f"L{lvl}/s{k}/t{j}/{m:#04x}@{f}" for lvl, k, j, m, f in done))


if __name__ == "__main__":
    main()
