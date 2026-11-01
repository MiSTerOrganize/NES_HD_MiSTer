"""compare_audlog.py - item 13(b): the CPU writes to the HD audio registers, Mesen vs fullsim.

Both logs are "<frame> <addr hex> <value hex>" per write ('#' comments; Mesen's "R" read lines
are ignored). Mesen's audlog.lua numbers frames by frames completed, fullsim by its own frame
counter, and the two runs reach the same game state a frame or two apart (power-on phase and
the input offset - HDPACK_DESIGN.md "FrameNumber phase"). So the check is:
  1. the SEQUENCE of (addr, value) writes must be identical, write for write;
  2. the frame offset between matching writes must be one constant (reported, not assumed).
A shorter run on either side is reported as such, not as a mismatch.
usage: python compare_audlog.py MESEN_LOG FULLSIM_LOG
"""
import sys


def load(p):
    out = []
    for line in open(p, encoding='utf-8', errors='replace'):
        s = line.split('#', 1)[0].split()
        if len(s) == 3 and s[1] != 'R':
            out.append((int(s[0]), int(s[1], 16), int(s[2], 16)))
    return out


def main():
    m, f = load(sys.argv[1]), load(sys.argv[2])
    print(f'Mesen {len(m)} writes, fullsim {len(f)} writes')
    n = min(len(m), len(f))
    bad = [(i, m[i], f[i]) for i in range(n) if m[i][1:] != f[i][1:]]
    offs = sorted({f[i][0] - m[i][0] for i in range(n)})
    for i, a, b in bad[:10]:
        print(f'  write {i}: Mesen frame {a[0]} {a[1]:04x}={a[2]:02x}  fullsim frame {b[0]} {b[1]:04x}={b[2]:02x}')
    print(f'frame offset fullsim - Mesen over matching writes: {offs}')
    if len(m) != len(f):
        longer, k = ('Mesen', m) if len(m) > len(f) else ('fullsim', f)
        print(f'  {longer} has {abs(len(m) - len(f))} more writes; first extra: {k[n]}')
    ok = not bad and len(m) == len(f) and len(offs) <= 1
    print('VERDICT:', 'IDENTICAL write sequence, constant frame offset' if ok else
          ('VALUES DIFFER' if bad else ('COUNT DIFFERS' if len(m) != len(f) else 'OFFSET VARIES')))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
