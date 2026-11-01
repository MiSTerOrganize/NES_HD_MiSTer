"""feature_usage.py - how many pixels change when one HD-pack feature is left out.

OPEN_ITEMS item 11 (2026-10-22). Runs the exact decision program (hdarm3) once per recorded
frame with HD_FEATOFF=0 (the exact answer; parity.sh proves it equals hdref) and once per feature
switched off, then counts:
  pixels   window pixels whose decision line (BG tile + sprite choices) differs
  levels   background-level choices that differ
A renderer without a feature would produce exactly the "off" decisions, so a frame is still
correct without that feature only if both counts are 0.

usage: python feature_usage.py HDARM_EXE WORKDIR
"""
import os, subprocess, sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
T = os.path.normpath(os.path.join(HERE, '..', '..', '..', 'NES_HDPack_testdata'))
OUT = 'Z:/NES_HDPack_work/out'
PAIRS = [('a034', 'rec_mmm', 'Metroid'), ('p002', 'rec_cv', 'Castlevania'),
         ('p053', 'rec_smb3', 'Super Mario Bros. 3'), ('a057', 'rec_z2', 'Zelda II')]
FEATS = [(1, 'tile/sprite at position'), (2, 'tile/sprite nearby'), (4, 'position checks'),
         (8, 'mirror / bg-priority checks'), (16, 'additions'), (32, 'backgrounds'),
         (64, 'memory / frame conditions'),
         (1 | 2 | 4 | 8, 'ALL per-pixel conditions'),
         (1 | 2 | 4 | 8 | 16 | 32, 'everything but memory/frame conditions')]


def run(exe, pk, rec, watch, featoff, dst):
    env = dict(os.environ, HD_FEATOFF=str(featoff))
    r = subprocess.run([exe, f'{OUT}/{pk}.hdp', rec, watch, '--out', dst, '--iters', '1'],
                       env=env, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f'run failed {pk} {rec} featoff={featoff}: {r.stderr}')
    pix, lev = {}, set()
    with open(dst, encoding='ascii') as f:
        for line in f:
            if line.startswith('P '):
                a = line.split(' ', 3)
                pix[(a[1], a[2])] = a[3] if len(a) > 3 else ''
            elif line.startswith('L '):
                lev.add(line.strip())
    return pix, lev


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    exe, work = sys.argv[1], sys.argv[2]
    os.makedirs(work, exist_ok=True)
    # per game: frames, and per feature: (frames changed, total pixels changed, max pixels)
    res = defaultdict(lambda: defaultdict(lambda: [0, 0, 0, 0]))
    nframes = defaultdict(int)
    for pk, rd, game in PAIRS:
        for name in sorted(os.listdir(os.path.join(T, rd))):
            if not (name.startswith('rec_') and name.endswith('.bin')):
                continue
            f = name[4:-4]
            watch = os.path.join(T, rd, f'watch_{f}.bin')
            if not os.path.isfile(watch):
                continue
            rec = os.path.join(T, rd, name)
            nframes[game] += 1
            ep, el = run(exe, pk, rec, watch, 0, os.path.join(work, 'exact.txt'))
            for bit, _ in FEATS:
                op, ol = run(exe, pk, rec, watch, bit, os.path.join(work, 'off.txt'))
                keys = set(ep) | set(op)
                px = sum(1 for k in keys if ep.get(k) != op.get(k))
                lv = len(el ^ ol)
                s = res[game][bit]
                if px or lv:
                    s[0] += 1
                s[1] += px
                s[2] = max(s[2], px)
                s[3] += lv
    print('pixels = window pixels whose HD decision changes; a frame is only still exact if 0\n')
    for _, _, game in PAIRS:
        print(f'{game}  ({nframes[game]} frames)')
        for bit, label in FEATS:
            fr, tot, mx, lv = res[game][bit]
            print(f'  {label:42s} frames changed {fr:2d}/{nframes[game]:<2d}'
                  f'  pixels total {tot:7d}  max/frame {mx:6d}  bg-level choices {lv}')
        print()


if __name__ == '__main__':
    main()
