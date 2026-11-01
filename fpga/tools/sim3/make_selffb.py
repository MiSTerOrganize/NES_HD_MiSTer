"""Self-fallback fixture for the 8a dictionary: copy a CHR-ROM pack and set fallback[b] = b
(an explicit <fallback b, b> line - legal in a pack, never produced by the automatic table)
for every captured key with additions whose body is inside the fallback table.

A self-fallback must contribute NO fallback lists (Mesen's addition lookup is an elif chain:
the key / body lists already matched the same records), so hd3_dict must skip the (P,F)
and (ANY,F) lookups when F == body. Looking them up again doubles every entry.

usage: python make_selffb.py IN.hdp GOLDEN.tsv OUT.hdp [MAX]
(GOLDEN = dict_golden.py's file for a frame of the pack's game; MAX keys to rewrite, default 16)"""
import os
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import hdp3_addtab as at  # noqa: E402


def main():
    src, golden, out = sys.argv[1:4]
    mx = int(sys.argv[4]) if len(sys.argv) > 4 else 16
    d = bytearray(open(src, "rb").read())
    nfb = struct.unpack_from("<I", d, 0x44)[0]
    fbo = struct.unpack_from("<I", d, 0x80 + 80)[0]
    if not nfb:
        sys.exit("pack has no fallback table (CHR-RAM game?)")
    fbl = list(struct.unpack_from(f"<{nfb}i", d, fbo))
    nadd = struct.unpack_from("<I", d, 0x40)[0]
    abase = struct.unpack_from("<I", d, 0x80 + 88)[0]
    t, nb, mp, li = at.build(bytes(d[abase:abase + 64 * nadd]), nadd)
    keys = []
    for line in open(golden):
        p = line.rstrip("\n").split("\t")
        if len(p) >= 10 and p[3] == "1":
            k = (int(p[4], 16), int(p[5], 16))
            if k not in keys:
                keys.append(k)
    done = []
    for pal, body in keys:
        if len(done) >= mx:
            break
        if not 0 <= body < nfb or body in [b for _, b in done]:
            continue
        if not at.matched(t, nb, mp, li, pal, 0, body, fbl):
            continue
        fbl[body] = body
        done.append((pal, body))
    if not done:
        sys.exit("no captured key with additions has its body inside the fallback table")
    struct.pack_into(f"<{nfb}i", d, fbo, *fbl)
    open(out, "wb").write(bytes(d))
    print(f"{out}: {len(done)} self-fallbacks: " + " ".join(f"{p:08x}/{b:x}" for p, b in done))


if __name__ == "__main__":
    main()
