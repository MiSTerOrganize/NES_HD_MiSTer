"""Write a copy of a CHR-RAM game's format-3 pack whose tile conditions are all in INDEX form.

No corpus pack gives a tile condition as a tile index in a CHR-RAM game (8k), so nothing tested
that path. Mesen compares such a condition with the target's TileIndex = AbsoluteTileAddr/16,
which it sets for CHR-RAM tiles too (the CHR-RAM slot), and with no fallback (the map is built
for CHR-ROM games only) - MESEN_HD_RUNTIME_SPEC.md 3.5; hdref.tmatch does the same.

Every tileAtPosition / spriteAtPosition / tileNearby / spriteNearby condition in data form (16
bytes of CHR-RAM, q2 = fingerprint) becomes index form: data flag cleared, q2 = the TileIndex at
which that fingerprint was seen most often on the given recorded frames, among the targets with
the condition's own palette (the records hdref.build_records rebuilds; TileIndex = (CHR linear
& 0xFFFFF) >> 4, as hdref.chr_index). A fingerprint seen at several indices therefore matches at
only one of them, so the converted conditions are both true and false on the frames. A
fingerprint never seen keeps index 0 (it was false anyway). The palette and ignore flag are
kept. A test fixture only.

Two options make a harder variant, each closing a blind spot the plain one leaves:
  --shift N   adds N pixels to the X offset of every tileNearby / spriteNearby condition.
              Castlevania's offsets are whole tiles, so all the targets of one 8-pixel group
              share a tile and an index - one evaluation per group would then equal Mesen's
              per-pixel one. An offset that is not a multiple of 8 puts a tile boundary inside
              the group.
  --palmix    every second converted condition (without the ignore flag) gets an index that
              its fingerprint was seen at with a DIFFERENT palette than the condition's, so
              only the palette comparison keeps it false there.
  --keep-data leaves the conditions in data form (only --shift applies): the same harder
              offsets on the path that existed before 8k.
  --palflip   every converted condition (without the ignore flag) keeps its matching
              index but is given a palette never seen with that index, so it is false
              everywhere - and true wherever the palette check is skipped. Decisive for the
              palette comparison, where --palmix rarely is.

usage: python make_ixram_cond.py <in.hdp> <out.hdp> <recdir> [--shift N] [--palmix] [--palflip]
       [--keep-data] <frame> [...]
"""
import os
import struct
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import hdref  # noqa: E402
from hdp3_read import Hdp3  # noqa: E402

TILE_TYPES = (3, 4, 5, 6)
NEARBY = (5, 6)


def main():
    args = sys.argv[1:]
    shift, palmix, keep, palflip = 0, False, False, False
    rest = []
    while args:
        a = args.pop(0)
        if a == "--shift":
            shift = int(args.pop(0))
        elif a == "--palmix":
            palmix = True
        elif a == "--keep-data":
            keep = True
        elif a == "--palflip":
            palflip = True
        else:
            rest.append(a)
    if len(rest) < 4:
        print(__doc__)
        return 2
    src, dst, recdir, names = rest[0], rest[1], rest[2], rest[3:]
    data = bytearray(open(src, "rb").read())
    h = Hdp3(bytes(data))
    if not h.flags & 0x10:
        sys.exit(f"{src}: not a CHR-RAM game's pack")
    legacy = bool(h.flags & 1)
    seen = defaultdict(Counter)                 # fingerprint -> (TileIndex, palette) counts
    for n in names:
        rec = open(os.path.join(recdir, f"rec_{n}.bin"), "rb").read()
        for p in hdref.build_records(rec, True, legacy):
            for r in [p.tile] + p.spr:
                if r.fp is not None and r.idx != hdref.NOTILE:
                    seen[r.fp][(r.idx, r.pal)] += 1
    base = h.s(2)
    by_type, unseen, mixed, shifted, flipped, k = Counter(), 0, 0, 0, 0, 0
    for ci in range(h.nconds):
        o = base + 32 * ci
        q0 = struct.unpack_from("<Q", data, o)[0]
        if (q0 & 0xFF) not in TILE_TYPES or not (q0 >> 10) & 1:
            continue
        fp = struct.unpack_from("<Q", data, o + 16)[0]
        pal = struct.unpack_from("<Q", data, o + 24)[0] & 0xFFFFFFFF
        ign = (q0 >> 9) & 1
        same = Counter({i: c for (i, p), c in seen[fp].items() if ign or p == pal})
        other = Counter({i: c for (i, p), c in seen[fp].items() if p != pal and i not in same})
        idx = 0
        if palmix and not ign and other and k % 2:
            idx = other.most_common(1)[0][0]
            mixed += 1
        elif same:
            idx = same.most_common(1)[0][0]
            if palflip and not ign:
                used = {p for (i, p) in seen[fp] if i == idx}
                np_ = pal ^ 0x01010101
                while np_ in used:
                    np_ = (np_ + 0x01000000) & 0xFFFFFFFF
                q3 = struct.unpack_from("<Q", data, o + 24)[0]
                struct.pack_into("<Q", data, o + 24, (q3 & ~0xFFFFFFFF) | np_)
                flipped += 1
        elif not seen[fp]:
            unseen += 1
        k += 1
        if not keep:
            struct.pack_into("<Q", data, o, q0 & ~(1 << 10))
            struct.pack_into("<Q", data, o + 16, idx)
        if shift and (q0 & 0xFF) in NEARBY:
            q1 = struct.unpack_from("<Q", data, o + 8)[0]
            x = (q1 & 0xFFFFFFFF) + shift
            struct.pack_into("<Q", data, o + 8, (q1 & ~0xFFFFFFFF) | (x & 0xFFFFFFFF))
            shifted += 1
        by_type[q0 & 0xFF] += 1
    if not by_type:
        sys.exit("no data-form tile condition to convert")
    open(dst, "wb").write(data)
    print(f"{dst}: converted " + ", ".join(f"type {t}: {by_type[t]}" for t in sorted(by_type))
          + f"; {unseen} fingerprints never seen; {mixed} given another palette's index; "
          + f"{shifted} nearby offsets shifted by {shift}; {flipped} given a palette never "
          + "seen with their index")
    return 0


if __name__ == "__main__":
    sys.exit(main())
