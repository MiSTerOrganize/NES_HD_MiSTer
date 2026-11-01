"""Make a 'light' recording: a copy of an SMB frame with everything after the first line's
nametable data kept but every line's sprite fetch count and span count set to 0, and every
tile qword equal to line 0's - so the frame's dictionary holds a handful of keys and
ADD + RESOLVE finish quickly. Written as obj/engine_fix/light/rec_<name>.bin + watch_<name>.bin
(run_engine.sh's fixture folder).

    python -I make_light.py <rec_dir> <src FFFF> <name FFFF>
"""
import os
import shutil
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    src_dir, src, name = sys.argv[1], sys.argv[2], sys.argv[3]
    with open(os.path.join(src_dir, f"rec_{src}.bin"), "rb") as f:
        r = bytearray(f.read())
    for y in range(240):
        r[y * 1024:(y + 1) * 1024] = r[0:1024]            # every line's tiles = line 0's
        hdr = 0x40000 + y * 2048
        q = struct.unpack_from("<Q", r, hdr)[0]
        q &= ~((0xFF << 32) | (0xFF << 48))                  # no spans, no sprite fetches
        struct.pack_into("<Q", r, hdr, q)
    out = os.path.join(HERE, "obj", "engine_fix", "light")
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, f"rec_{name}.bin"), "wb") as f:
        f.write(r)
    shutil.copy(os.path.join(src_dir, f"watch_{src}.bin"), os.path.join(out, f"watch_{name}.bin"))
    print(f"obj/engine_fix/light/rec_{name}.bin from rec_{src}.bin")


if __name__ == "__main__":
    main()
