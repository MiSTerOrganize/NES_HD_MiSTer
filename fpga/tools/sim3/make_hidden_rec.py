"""Copy recorded frames into a fixture folder, clearing the sprites-shown bit (pixel byte 0
bit 6) on the left half of every line of the frames named with --hide. No recording has a valid
sprite fetch covering a pixel where sprites are not shown (all frames of all recordings
scanned), so without this the hd3_resolve test cannot see spriteAtPosition ignore that bit.

The result is a legal frame record - what the PPU writes with sprite rendering disabled over
those dots - and hdref.build_records and the RTL both read the bit from it. watch_FFFF.bin
files are copied unchanged. A test fixture only.

usage: python make_hidden_rec.py <src recdir> <dst dir> <frame> [...] --hide <frame> [...]
"""
import os
import shutil
import sys


def main():
    a = sys.argv[1:]
    if len(a) < 3 or "--hide" not in a:
        print(__doc__)
        return 2
    src, dst = a[0], a[1]
    i = a.index("--hide")
    frames, hide = a[2:i], set(a[i + 1:])
    if not hide <= set(frames):
        sys.exit("--hide frames must be among the copied frames")
    os.makedirs(dst, exist_ok=True)
    for f in frames:
        shutil.copy(os.path.join(src, f"watch_{f}.bin"), dst)
        rec = bytearray(open(os.path.join(src, f"rec_{f}.bin"), "rb").read())
        n = 0
        if f in hide:
            for y in range(240):
                for x in range(128):
                    o = y * 1024 + x * 4
                    if rec[o] & 0x40:
                        rec[o] &= ~0x40
                        n += 1
        open(os.path.join(dst, f"rec_{f}.bin"), "wb").write(rec)
        print(f"rec_{f}.bin: " + (f"sprites-shown cleared on {n} pixels" if f in hide else "copied"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
