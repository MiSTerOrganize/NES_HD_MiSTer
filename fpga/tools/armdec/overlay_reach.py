"""overlay_reach.py - can the tile-rewrite overlay change ANY decision in a pack?

Mesen rewrites a background tile's index X to fallback[X] when X has no HD match, and the new
index persists in that pixel's record. A tileNearby test (tile V, not data-keyed) reads a
record as: match iff idx == V or fallback[idx] == V. So the persisted rewrite can only change
the answer for an X where
        (X == V or fb[X] == V)  !=  (fb[X] == V or fb[fb[X]] == V)
If no such X exists for any rewrite-sensitive tileNearby condition, the overlay cannot change
a single decision in that pack, whatever frame is drawn. (spriteNearby reads sprite records,
which hdarm3 rewrites in place, not through the overlay.)

usage: python overlay_reach.py HDP [HDP ...]
"""
import struct, sys


def check(path):
    d = open(path, 'rb').read()
    sec = [struct.unpack_from('<II', d, 0x80 + 8 * i) for i in range(18)]
    nconds = struct.unpack_from('<I', d, 0x2C)[0]
    nfb = struct.unpack_from('<I', d, 0x44)[0]
    fb = [struct.unpack_from('<i', d, sec[10][0] + 4 * i)[0] for i in range(nfb)]
    f = lambda x: fb[x] if 0 <= x < nfb else -1
    sens = {}
    for i in range(nconds):
        q0, q1, q2, q3 = struct.unpack_from('<QQQQ', d, sec[2][0] + 32 * i)
        if (q0 & 0xFF) != 5 or not (q0 >> 24) & 1 or (q0 >> 10) & 1:
            continue
        ox = struct.unpack('<i', struct.pack('<I', q1 & 0xFFFFFFFF))[0]
        oy = struct.unpack('<i', struct.pack('<I', q1 >> 32))[0]
        sens[i] = (q2, ox, oy)
    owners = {i: set() for i in sens}       # background tiles whose rule lists evaluate the cond

    def clist(off):
        out, p = [], sec[3][0] + off
        if off == 0:
            return out
        while True:
            w = struct.unpack_from('<I', d, p)[0]; p += 4
            out.append(w & 0xFFFFFF)
            if w >> 31:
                return out
    for b in range(sec[0][1] // 64):
        for j in range(4):
            q0, q1 = struct.unpack_from('<QQ', d, sec[0][0] + b * 64 + j * 16)
            if not q1 >> 63 or (q1 >> 62) & 1:
                continue
            L = sec[1][0] + ((q1 >> 32) & 0x3FFFFFFF) * 8
            for r in range(struct.unpack_from('<I', d, L)[0]):
                w = struct.unpack_from('<IIII', d, L + 8 + 16 * r)
                for c in clist(w[1]) + clist(w[2]):
                    if c in owners:
                        owners[c].add(q0 >> 32)
    reach = 0
    for i, (V, ox, oy) in sens.items():
        hits = []
        for X in range(nfb):
            K = fb[X]
            if K < 0 or (X == V or K == V) == (K == V or f(K) == V):
                continue
            if (ox, oy) == (0, 0):
                # the reader IS the rewritten pixel: its list (that of K) must evaluate the cond
                if K not in owners[i]:
                    continue
            elif not (oy < 0 or (oy == 0 and ox < 0)):
                # the target is drawn after the reader, so it is not rewritten yet when read
                continue
            hits.append((X, K))
        reach += len(hits)
        print(f'  cond {i}: tile {V} offset ({ox},{oy}), {len(owners[i])} owner tiles, '
              f'reachable rewrites {hits[:5]}')
        if hits:
            print(f'    owner tiles: {sorted(owners[i])}')
    return len(sens), reach


tot = 0
for p in sys.argv[1:]:
    c, r = check(p)
    tot += r
    print(f'{p}: {c} rewrite-sensitive tileNearby conditions, {r} (cond, tile) pairs the overlay can change')
print('VERDICT:', 'the overlay CAN change decisions' if tot else 'the overlay cannot change any decision in these packs')
