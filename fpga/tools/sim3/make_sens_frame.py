"""Write a copy of a format-3 pack with some FRAME conditions flagged rewrite-sensitive (q0 bit
24), so the hd3_resolve test reaches the deferral path: a flagged frame condition is not
evaluated in RESOLVE but kept with its rule for render, and the rule then does not end the
list. No pack in the corpus flags a frame condition (all 23 flagged conditions are walk-class,
measured 2026-10-15), so without this fixture that path is never exercised.

A frame condition is flagged when its index ci satisfies ci % MOD == REM. resolve_golden.py
reads the same modified flags. The copy is a test fixture, never a pack to ship.

usage: python make_sens_frame.py <in.hdp> <out.hdp> [MOD REM]     (default 3 1)
"""
import os
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import hdref  # noqa: E402


def main():
    if len(sys.argv) not in (3, 5):
        print(__doc__)
        return 2
    mod, rem = (int(sys.argv[3]), int(sys.argv[4])) if len(sys.argv) == 5 else (3, 1)
    data = bytearray(open(sys.argv[1], "rb").read())
    h = hdref.Hdp3(bytes(data))
    base = h.s(2)
    flagged = frame = 0
    for ci in range(h.nconds):
        q0 = struct.unpack_from("<Q", data, base + 32 * ci)[0]
        if not (q0 >> 11) & 1:          # frame-class only
            continue
        frame += 1
        if ci % mod == rem and not (q0 >> 24) & 1:
            struct.pack_into("<Q", data, base + 32 * ci, q0 | (1 << 24))
            flagged += 1
    if not flagged:
        sys.exit("no frame condition flagged - choose another MOD/REM")
    open(sys.argv[2], "wb").write(data)
    print(f"{sys.argv[2]}: {flagged} of {frame} frame conditions flagged rewrite-sensitive")
    return 0


if __name__ == "__main__":
    sys.exit(main())
