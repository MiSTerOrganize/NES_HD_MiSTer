"""overlay_fuzz.py - exercise hdarm3's tile-rewrite overlay, which no recorded frame reaches.

Mesen rewrites a background tile's index to its fallback when the tile's own index has no
match, and the rewritten index persists in that pixel's record, so a later tileNearby test
that reads the pixel sees the new index. hdarm3 keeps that rewrite in an overlay (set_idx ->
MUTB/MUTI). Parity across the recorded frames shows MUT_NOWT (overlay not written) changes
NOTHING, i.e. the overlay is never exercised there (OPEN_ITEMS item 11, round 3).

This builds frames that do exercise it. For every rewrite-sensitive tileNearby condition in
the pack (q0 bit 24), it takes a recorded frame and sets a random share of the background spans
to that condition's tile V, where V has a fallback. Then:
    reference  hdref_decisions.py on the mutated frame (the Python port of Mesen)
    exact      hdarm3 built plainly            must equal the reference on EVERY trial
    NOWT       hdarm3 built -DMUT_NOWT         must differ on AT LEAST ONE trial
The first proves the overlay is right, the second that the trials reach it at all.

usage: python overlay_fuzz.py PACK.hdp RECDIR EXACT.exe NOWT.exe WORKDIR [--trials N] [--seed S]
"""
import argparse, os, random, shutil, struct, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))


def sections(d):
    return [struct.unpack_from('<II', d, 0x80 + 8 * i) for i in range(18)]


def main():
    ap = argparse.ArgumentParser()
    for n in ('hdp', 'recdir', 'exact', 'nowt', 'work'):
        ap.add_argument(n)
    ap.add_argument('--trials', type=int, default=40)
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--share', type=float, default=0.3)
    ap.add_argument('--tiles', help='comma list of tiles to write (default: the sensitive tiles)')
    ap.add_argument('--palette', action='store_true',
                    help='also randomise the span palette, so the tile own match can fail')
    a = ap.parse_args()
    rnd = random.Random(a.seed)
    d = open(a.hdp, 'rb').read()
    sec = sections(d)
    nconds = struct.unpack_from('<I', d, 0x2C)[0]
    nfb = struct.unpack_from('<I', d, 0x44)[0]
    fb = [struct.unpack_from('<i', d, sec[10][0] + 4 * i)[0] for i in range(nfb)]

    sens = []
    for i in range(nconds):
        q0, q1, q2, q3 = struct.unpack_from('<QQQQ', d, sec[2][0] + 32 * i)
        if (q0 & 0xFF) == 5 and (q0 >> 24) & 1 and not (q0 >> 10) & 1:
            sens.append((i, q2))
    tiles = sorted({v for _, v in sens})
    print(f'{len(sens)} rewrite-sensitive tileNearby conditions, tiles {tiles}')
    if a.tiles:
        # explicit pool: the tested tile plus the tiles whose lists read it (overlay_reach.py)
        tiles = [int(t) for t in a.tiles.split(',')]
    else:
        tiles = [v for v in tiles if v < nfb and fb[v] >= 0]
    if not tiles:
        sys.exit('no sensitive tile has a fallback: the overlay cannot be reached in this pack')
    print(f'tile pool: {[(v, fb[v] if v < nfb else -1) for v in tiles]}')

    frames = sorted(fn[4:8] for fn in os.listdir(a.recdir)
                    if fn.startswith('rec_') and fn.endswith('.bin'))
    rd = os.path.join(a.work, 'rec')
    os.makedirs(rd, exist_ok=True)
    exact_bad = nowt_diff = 0
    for t in range(a.trials):
        f = rnd.choice(frames)
        v = rnd.choice(tiles)
        rec = bytearray(open(os.path.join(a.recdir, f'rec_{f}.bin'), 'rb').read())
        changed = 0
        for y in range(240):
            h = 0x40000 + y * 2048
            nspan = min((struct.unpack_from('<Q', rec, h)[0] >> 32) & 0xFF, 34)
            for s in range(nspan):
                if rnd.random() >= a.share:
                    continue
                o = h + 64 + s * 16
                qa = struct.unpack_from('<Q', rec, o)[0]
                w = rnd.choice(tiles) if a.tiles else v
                qa = (qa & ~(0xFFFF << 4)) | ((w & 0xFFFF) << 4)
                if a.palette:   # also move the span to a random background palette (bits 32-33)
                    qa = (qa & ~(3 << 32)) | (rnd.randrange(4) << 32)
                struct.pack_into('<Q', rec, o, qa)
                changed += 1
        open(os.path.join(rd, f'rec_{f}.bin'), 'wb').write(rec)
        shutil.copyfile(os.path.join(a.recdir, f'watch_{f}.bin'), os.path.join(rd, f'watch_{f}.bin'))
        ref = subprocess.run([sys.executable, os.path.join(HERE, 'hdref_decisions.py'), a.hdp, rd,
                              '--frame', str(int(f))], capture_output=True, text=True)
        if not ref.stdout.strip():
            sys.exit(f'reference failed on trial {t}:\n{ref.stderr}')
        want = ref.stdout.replace('\r', '')
        fbhits = ref.stderr.strip().split()[5] if ref.stderr.strip() else '?'
        outs = {}
        for name, exe in (('exact', a.exact), ('nowt', a.nowt)):
            of = os.path.join(a.work, name + '.txt')
            subprocess.run([exe, a.hdp, os.path.join(rd, f'rec_{f}.bin'),
                            os.path.join(rd, f'watch_{f}.bin'), '--out', of],
                           capture_output=True)
            outs[name] = open(of, newline='').read().replace('\r', '')
        e_ok = outs['exact'] == want
        n_diff = outs['nowt'] != want
        exact_bad += not e_ok
        nowt_diff += n_diff
        print(f'trial {t:3d} frame {f} tile {v:5d} spans {changed:4d} fallback_hits {fbhits:>6s}'
              f'  exact {"OK" if e_ok else "MISMATCH"}  nowt {"DIFFERS" if n_diff else "same"}')
        os.remove(os.path.join(rd, f'rec_{f}.bin'))
    print(f'\nexact matches the reference on {a.trials - exact_bad} of {a.trials} trials')
    print(f'MUT_NOWT differs from the reference on {nowt_diff} of {a.trials} trials')
    ok = exact_bad == 0 and nowt_diff > 0
    print('VERDICT:', 'PASS - overlay exercised and correct' if ok else
          ('FAIL - exact mismatched' if exact_bad else 'INCONCLUSIVE - overlay never reached'))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
