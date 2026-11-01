"""memo_fuzz.py - exercise hdarm4's dependency memo where recorded frames do not.

hdarm4 reuses the previous pixel's background decision when the pixel has the same tile record
and every tile its tileNearby / tileAtPosition conditions read is unchanged. On the recorded
frames the nearby tiles almost never change inside one tile (one rejection in Castlevania), so
the frames cannot show the dependency check is needed. Here each line's tile layout is
rewritten into random runs of 1..R pixels, so the tiles a nearby condition reads change at
arbitrary x. Then on every trial:
    h3     hdarm3 (decision parity with hdref_decisions.py proven)      = reference
    exact  hdarm4 built plainly                    must equal h3 on EVERY trial
    loose  hdarm4 -DMUT_DEPLOOSE (deps ignored)    must differ on AT LEAST ONE trial

usage: python memo_fuzz.py PACK.hdp REC.bin WATCH.bin H3.exe EXACT.exe LOOSE.exe WORKDIR
       [--trials N] [--seed S] [--run R]
"""
import argparse, os, random, struct, subprocess, sys


def main():
    ap = argparse.ArgumentParser()
    for n in ('hdp', 'rec', 'watch', 'h3', 'exact', 'loose', 'work'):
        ap.add_argument(n)
    ap.add_argument('--trials', type=int, default=20)
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--run', type=int, default=10)
    a = ap.parse_args()
    rnd = random.Random(a.seed)
    os.makedirs(a.work, exist_ok=True)
    base = open(a.rec, 'rb').read()
    ok = differ = 0
    for t in range(a.trials):
        d = bytearray(base)
        for y in range(240):
            q0, = struct.unpack_from('<Q', d, 0x40000 + y * 2048)
            nspan = min((q0 >> 32) & 0xFF, 34)
            if nspan == 0:
                continue
            x = 0
            while x < 256:
                n = rnd.randint(1, a.run)
                slot = 63 if rnd.random() < 0.05 else rnd.randrange(nspan)
                for xx in range(x, min(256, x + n)):
                    p = y * 1024 + xx * 4
                    d[p] = (d[p] & 0xC0) | slot
                x += n
        rp = os.path.join(a.work, 'rec.bin')
        open(rp, 'wb').write(d)
        outs = {}
        for k in ('h3', 'exact', 'loose'):
            o = os.path.join(a.work, k + '.txt')
            r = subprocess.run([getattr(a, k), a.hdp, rp, a.watch, '--out', o],
                               stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            if r.returncode:
                print('%s FAILED trial %d: %s' % (k, t, r.stderr.decode(errors='replace')[-300:]))
                return 2
            outs[k] = open(o, 'rb').read()
        if outs['exact'] == outs['h3']:
            ok += 1
        else:
            print('MISMATCH trial', t)
        if outs['loose'] != outs['h3']:
            differ += 1
    print('exact == hdarm3 on %d of %d trials; loose mutant differs on %d' % (ok, a.trials, differ))
    return 0 if ok == a.trials and differ > 0 else 1


if __name__ == '__main__':
    sys.exit(main())
