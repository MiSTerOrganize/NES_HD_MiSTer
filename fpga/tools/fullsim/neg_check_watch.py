"""Negative control for check_watch.py: each corruption of a good watch_FFFF.bin must FAIL.

usage: neg_check_watch.py CHECKER DIR ROM FRAME
       (DIR holds a passing watch_FFFF.bin for FRAME; the good copy must PASS)
"""
import os
import shutil
import struct
import subprocess
import sys
import tempfile


def run(checker, d, rom):
    r = subprocess.run([sys.executable, "-I", checker, d, "--rom", rom], capture_output=True, text=True)
    return r.returncode, (r.stdout.strip().splitlines() or [""])[0]


def main():
    if len(sys.argv) != 5:
        print(__doc__)
        return 2
    checker, src_dir, rom, frame = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
    src = os.path.join(src_dir, f"watch_{frame:04d}.bin")
    good = open(src, "rb").read()
    n = struct.unpack_from("<I", good, 4)[0]
    lst = struct.unpack_from(f"<{n}I", good, 8)
    vbase = 8 + 4 * n
    fbase = vbase + n

    def first(pred):
        for i, e in enumerate(lst):
            if pred(e):
                return i
        raise SystemExit("no entry of the wanted kind in the list")

    def flip_val(i):
        b = bytearray(good)
        b[vbase + i] ^= 0x5A
        return bytes(b)

    def set_flags(v):
        b = bytearray(good)
        struct.pack_into("<I", b, fbase, v)
        return bytes(b)

    muts = [
        ("good file (must PASS)", good, 0),
        ("CPU RAM value wrong", flip_val(first(lambda e: not e & 0x80000000 and (e & 0xFFFF) < 0x2000)), 1),
        ("register value non-zero", flip_val(first(lambda e: not e & 0x80000000 and 0x2000 <= (e & 0xFFFF) < 0x6000)), 1),
        ("palette value wrong", flip_val(first(lambda e: e & 0x80000000 and (e & 0x3FFF) >= 0x3F00)), 1),
        ("palette mirror $3F10 wrong", flip_val(first(lambda e: e & 0x80000000 and (e & 0x3FFF) == 0x3F10)), 1),
        ("nametable value wrong", flip_val(first(lambda e: e & 0x80000000 and 0x2000 <= (e & 0x3FFF) < 0x3F00)), 1),
        ("nametable mirror $3000 wrong", flip_val(first(lambda e: e & 0x80000000 and (e & 0x3FFF) == 0x3000)), 1),
        ("PRG-ROM value wrong", flip_val(first(lambda e: not e & 0x80000000 and (e & 0xFFFF) >= 0x8000)), 1),
        ("pattern value wrong", flip_val(first(lambda e: e & 0x80000000 and (e & 0x3FFF) < 0x2000)), 1),
        ("overflow flag set", set_flags(1), 1),
        ("SDRAM timeout flag set", set_flags(2), 1),
    ]
    ok = 0
    tmp = tempfile.mkdtemp()
    try:
        for name, data, want_rc in muts:
            for f in os.listdir(tmp):
                os.remove(os.path.join(tmp, f))
            with open(os.path.join(tmp, f"watch_{frame:04d}.bin"), "wb") as f:
                f.write(data)
            rc, line = run(checker, tmp, rom)
            good_rc = (rc == 0) if want_rc == 0 else (rc != 0)
            ok += good_rc
            print(f"{name:32s} rc={rc} {'ok ' if good_rc else 'BAD'}  {line[:90]}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"{ok}/{len(muts)} behave as required")
    return 0 if ok == len(muts) else 1


if __name__ == "__main__":
    sys.exit(main())
