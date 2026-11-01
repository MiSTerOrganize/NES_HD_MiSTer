"""rewrite_census.py - which condition types are flagged rewrite-sensitive, per pack.

A rewrite-sensitive condition (q0 bit 24, set by the converter) can change answer within a
frame because Mesen's fallback rewrite alters a tile's index as lookups proceed, so it cannot
always be settled before the frame is drawn. OPEN_ITEMS item 11, 2026-10-22.

usage: python rewrite_census.py [HDP_DIR]
"""
import glob, os, struct, sys
from collections import Counter

NAMES = {0: 'memoryCheck', 1: 'memoryCheckConstant', 2: 'frameRange', 3: 'tileAtPosition',
         4: 'spriteAtPosition', 5: 'tileNearby', 6: 'spriteNearby', 7: 'positionX',
         8: 'positionY', 9: 'originX', 10: 'originY', 11: 'hmirror', 12: 'vmirror',
         13: 'bgpriority'}


def main():
    d = sys.argv[1] if len(sys.argv) > 1 else 'Z:/NES_HDPack_work/out'
    packs = sorted(glob.glob(os.path.join(d, '*.hdp')))
    if not packs:
        sys.exit(f'no .hdp files in {d}')
    tot, sens, packs_with = Counter(), Counter(), Counter()
    per_pack = []
    for p in packs:
        with open(p, 'rb') as f:
            hdr = f.read(0x80 + 8 * 18)
            nconds = struct.unpack_from('<I', hdr, 0x2C)[0]
            sec2 = struct.unpack_from('<I', hdr, 0x80 + 8 * 2)[0]
            f.seek(sec2)
            raw = f.read(32 * nconds)
        if len(raw) != 32 * nconds:
            sys.exit(f'{p}: condition section short')
        seen = set()
        for i in range(nconds):
            q0 = struct.unpack_from('<Q', raw, 32 * i)[0]
            t = q0 & 0xFF
            tot[t] += 1
            if (q0 >> 24) & 1:
                sens[t] += 1
                seen.add(t)
        for t in seen:
            packs_with[t] += 1
        if seen:
            per_pack.append((os.path.basename(p), sorted(NAMES.get(t, t) for t in seen)))
    print(f'{len(packs)} packs\n')
    for name, kinds in per_pack:
        print(f'  rewrite-sensitive in {name}: {", ".join(kinds)}')
    print()
    print(f'{"type":22s} {"conditions":>11s} {"rewrite-sensitive":>18s} {"packs with any":>15s}')
    for t in sorted(tot):
        print(f'{NAMES.get(t, t):22s} {tot[t]:11d} {sens[t]:18d} {packs_with[t]:15d}')


if __name__ == '__main__':
    main()
