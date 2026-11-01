"""Copy recorded frames into a fixture folder and make line 0's own first-pixel data differ from
line 239's, so a render that takes pixel (0,0) or line 0's line fields from the wrong line is
caught (HDPACK_DESIGN.md "8a": with additions, Mesen draws line 0 with line 239's line fields
and pixel (0,0) is line 239's pixel 0 record).

The recorded frames cannot show it: in Castlevania (overscan 0) line 0's pixel 0 and header are
identical to line 239's, and in Zelda II (where they differ) the pack's overscan hides line 0.
For a pack WITH additions line 0's own pixel 0 word and header line fields are never read by
Mesen, so editing them changes nothing in the reference; a render that reads them changes.

  --gray F    set the grayscale bit (header q0 bit 18) of line 0 on frame F
  --pixel F   on frame F, line 0's pixel 0 becomes BG off (slot 63) in colour 0x16 (red), with
              sprites not shown

usage: python make_line0_rec.py <src recdir> <dst dir> <frame> [...] [--gray F] [--pixel F]
"""
import os
import shutil
import struct
import sys


def main():
    a = sys.argv[1:]
    gray, pixel = set(), set()
    frames = []
    i = 0
    while i < len(a):
        if a[i] in ("--gray", "--pixel"):
            (gray if a[i] == "--gray" else pixel).add(a[i + 1])
            i += 2
        else:
            frames.append(a[i])
            i += 1
    if len(frames) < 3 or not (gray | pixel) <= set(frames[2:]):
        print(__doc__)
        return 2
    src, dst, frames = frames[0], frames[1], frames[2:]
    os.makedirs(dst, exist_ok=True)
    for f in frames:
        shutil.copy(os.path.join(src, f"watch_{f}.bin"), dst)
        rec = bytearray(open(os.path.join(src, f"rec_{f}.bin"), "rb").read())
        what = []
        if f in gray:
            o = 0x40000
            q0 = struct.unpack_from("<Q", rec, o)[0]
            q239 = struct.unpack_from("<Q", rec, o + 239 * 2048)[0]
            if (q239 >> 18) & 1:
                sys.exit(f"rec_{f}: line 239 is grayscale already; the edit would not differ")
            struct.pack_into("<Q", rec, o, q0 | (1 << 18))
            what.append("line 0 grayscale")
        if f in pixel:
            if rec[0:4] != rec[239 * 1024:239 * 1024 + 4]:
                print(f"rec_{f}: note: line 0 and line 239 pixel 0 already differ")
            rec[0] = 63            # sprites not shown, BG off
            rec[2] = 0x16
            rec[3] = 0x16
            what.append("line 0 pixel 0 red, BG off")
        open(os.path.join(dst, f"rec_{f}.bin"), "wb").write(rec)
        print(f"rec_{f}.bin: " + (", ".join(what) if what else "copied"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
