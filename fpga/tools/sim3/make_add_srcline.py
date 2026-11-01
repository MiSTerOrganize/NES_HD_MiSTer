"""Source-line overflow fixture for hd3_add (8a): one source line emits more than NB = 64 lanes
while no target line receives more than NL = 64 (and, with the lanes spread over many target
lines, not more than 16 either), so ONLY the per-source-line limit can flag the frame.

Two sprite keys that both appear on one line get 40 and 30 additions (merged lists stay under
the 64-entry cap), each with a different vertical offset, so the lanes land on 70 different
target lines. Every other addition record is neutralised. The frame must come back overflowed.

usage: python make_add_srcline.py IN.hdp RECDIR GAME_RAM FRAME OUT.hdp
(IN.hdp must have additions and NO tables)"""
import os
import struct
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import addhw  # noqa: E402
import hdref  # noqa: E402
import hdp3_addtab as at  # noqa: E402

REC = "<IIQIIQiiI20x"
NEVER = 0x7FFFFFF0
NB = 64


def main():
    src, recdir, gr, frame, out = sys.argv[1:6]
    gr, frame = int(gr), int(frame)
    d = bytearray(open(src, "rb").read())
    if struct.unpack_from("<I", d, 0x80 + 16 * 8 + 4)[0]:
        sys.exit("IN.hdp already has addition tables")
    h = hdref.Hdp3(bytes(d))
    rec = open(os.path.join(recdir, f"rec_{frame:04d}.bin"), "rb").read()
    watch = open(os.path.join(recdir, f"watch_{frame:04d}.bin"), "rb").read()
    ref = hdref.HdRef(h, rec, watch, bool(gr))

    def key(s):
        return (s.pal, (1, s.fp) if gr else (0, s.idx & 0xFFFFFFFFFFFFFFFF))

    # a line in 40..209 (room for 40 lanes above, 30 below) with two different sources: two
    # sprite keys, or a sprite key and a BG tile key (BG is scanned on a tile-row start line)
    pick = None
    for y in range(40, 210):
        ks = []
        for x in range(256):
            p = ref.screen[(y << 8) | x]
            for s in p.spr:
                if key(s) not in ks:
                    ks.append(key(s))
        if len(ks) >= 2:
            pick = (y, ks[0], ks[1])
            break
    if pick is None:
        n = sum(1 for i in range(256 * 240) if ref.screen[i].spr)
        sys.exit(f"no line in 40..209 with two sprite keys ({n} pixels carry sprites)")
    y, ka, kb = pick
    added = (0xFF222222, (1, 0xFFFFFFFFFFFFFE00) if gr else (0, NEVER - 64))
    recs = [(ka, -(j + 1)) for j in range(40)] + [(kb, j + 1) for j in range(30)]
    if h.nadd < len(recs):
        sys.exit(f"pack has only {h.nadd} addition records")
    sb = h.s(11)
    for i in range(h.nadd):
        if i < len(recs):
            (opal, (ok, ob)), oy = recs[i]
            apal, (ak, ab) = added
            ox, ign = 0, 0
        else:
            opal, ok, ob, apal, ak, ab, ox, oy, ign = 0, 0, NEVER, 0, 0, NEVER + 1, 0, 0, 0
            if gr:
                ok, ob, ak, ab = 1, 0xFFFFFFFFFFFFFFF0, 1, 0xFFFFFFFFFFFFFFF1
        struct.pack_into(REC, d, sb + 64 * i, opal, ok, ob, apal, ak, ab, ox, oy, ign)
    tmp = out + ".notab"
    open(tmp, "wb").write(bytes(d))
    at.patch(tmp, out)
    os.remove(tmp)
    ref2 = hdref.HdRef(hdref.Hdp3(open(out, "rb").read()), rec, watch, bool(gr))
    lanes, st = addhw.build(ref2)
    per_src = {}
    for ty in range(240):
        for ln in lanes[ty]:
            per_src[ln.sy] = per_src.get(ln.sy, 0) + 1
    most_src = max(per_src.values())
    most_tgt = max(len(lanes[ty]) for ty in range(241))
    print(f"{out}: line {y}, keys with 40 + 30 additions; most lanes from one source line "
          f"{most_src} (limit {NB}), most on a target line {most_tgt}")
    if most_src <= NB or most_tgt > 16:
        sys.exit("the fixture does not isolate the source-line limit")
    r = subprocess.run([sys.executable, "-I", os.path.join(HERE, "addhw.py"), out, recdir, str(gr),
                        str(frame)], capture_output=True, text=True)
    print("  lane model:", (r.stdout.strip().splitlines() or [r.stderr[-300:]])[-1])
    if r.returncode != 0:
        sys.exit("the lane model differs from hdref")


if __name__ == "__main__":
    main()
