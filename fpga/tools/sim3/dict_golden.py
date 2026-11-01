"""Golden reference for the hd3_dict unit test: what the record dictionary must hold for one
recorded frame (rec_FFFF.bin) and one format-3 pack.

For every BG span slot < span count and every sprite fetch < fetch count (at most 16) of every
line, the key Mesen looks up and its resolution, computed with hdref's own pieces (Hdp3,
chr_index, find, fallback) - written separately from the RTL:

    kind y slot valid pal body via off fb fb2

kind B = BG span, S = sprite fetch. valid 0 = an invalid sprite fetch (no record). pal and
body in hex; body = the fingerprint in a CHR-RAM game, else the tile index. via 0 none,
1 exact key, 2 fallback tile (under the record's palette or the default one), 3 default
palette; off = rule-list byte offset (0 when via is 0). fb / fb2 = fallback(idx) and
fallback(fallback(idx)) as {valid}{tile} hex, CHR-ROM only (fallback() of hdref).

The first line is "#game_ram legacy nfet_overflow" so the runner can configure the testbench.

usage: python dict_golden.py <file.hdp> <rec_FFFF.bin> <out.tsv> (--rom ROM | --game-ram 0/1)
"""
import argparse
import os
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import hdref  # noqa: E402

DEFAULT = 0xFFFFFFFF


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("hdp")
    ap.add_argument("rec")
    ap.add_argument("out")
    ap.add_argument("--rom")
    ap.add_argument("--game-ram", type=int, choices=(0, 1))
    a = ap.parse_args()
    h = hdref.Hdp3(open(a.hdp, "rb").read())
    if a.game_ram is not None:
        game_ram = bool(a.game_ram)
    elif h.flags & 0x20:
        game_ram = bool(h.flags & 0x10)
    elif a.rom:
        game_ram = hdref.rom_is_chr_ram(a.rom)
    else:
        sys.exit("say whether the game is CHR-RAM: --rom or --game-ram")
    legacy = bool(h.flags & 1)
    fb = list(struct.unpack_from(f"<{h.nfallback}i", h.d, h.s(10))) if h.nfallback else []
    rec = open(a.rec, "rb").read()

    def fallback(i):
        return fb[i] if 0 <= i < len(fb) else -1

    def find(pal, body):
        if game_ram:
            return h.find_key(pal & 0xFFFFFFFF, 1, body & 0xFFFFFFFF, body >> 32)
        return h.find_key(pal & 0xFFFFFFFF, 0, body & 0xFFFFFFFF, 0)

    def resolve(pal, body):
        off = find(pal, body)
        if off is not None:
            return 1, off
        if not game_ram:
            f = fallback(body)
            if f >= 0:
                off = find(pal, f)
                if off is None:
                    off = find(DEFAULT, f)
                if off is not None:
                    return 2, off
        off = find(DEFAULT, body)
        if off is not None:
            return 3, off
        return 0, 0

    def fbw(v):
        return (1 << 16) | (v & 0xFFFF) if v >= 0 else 0

    lines = []
    over = 0
    for y in range(240):
        hoff = 0x40000 + y * 2048
        q0 = struct.unpack_from("<Q", rec, hoff)[0]
        nspan = min((q0 >> 32) & 0xFF, 34)
        nfet_raw = (q0 >> 48) & 0xFF
        nfet = min(nfet_raw, 16)
        over |= nfet_raw > 16
        pbits = int.from_bytes(rec[hoff + 8:hoff + 32], "little")
        c = [(pbits >> (6 * n)) & 63 for n in range(32)]
        items = []
        for s in range(nspan):
            qa, qb = struct.unpack_from("<QQ", rec, hoff + 64 + s * 16)
            pb = ((qa >> 32) & 3) * 4
            pal = c[pb + 3] | (c[pb + 2] << 8) | (c[pb + 1] << 16) | (0 if legacy else c[0] << 24)
            items.append(("B", s, True, pal, qa & 0x3FFFFF, qb))
        for i in range(nfet):
            qa, qb = struct.unpack_from("<QQ", rec, hoff + 640 + i * 16)
            if not (qa >> 54) & 1:
                items.append(("S", i, False, 0, 0, 0))
                continue
            q = 0x10 + 4 * ((qa >> 46) & 3)
            pal = c[q + 3] | (c[q + 2] << 8) | (c[q + 1] << 16) | (0 if legacy else 0xFF000000)
            items.append(("S", i, True, pal, (qa >> 16) & 0x3FFFFF, qb))
        for kind, slot, valid, pal, lin, qb in items:
            if not valid:
                lines.append(f"{kind}\t{y}\t{slot}\t0\t-\t-\t-\t-\t-\t-")
                continue
            idx = hdref.chr_index(lin)
            body = qb if game_ram else idx
            via, off = resolve(pal, body)
            f = -1 if game_ram else fallback(idx)
            f2 = fallback(f) if f >= 0 else -1
            lines.append(f"{kind}\t{y}\t{slot}\t1\t{pal:08x}\t{body:016x}\t{via}\t{off}\t"
                         f"{fbw(f):05x}\t{fbw(f2):05x}")
    with open(a.out, "w") as f:
        f.write(f"#{int(game_ram)}\t{int(legacy)}\t{int(over)}\n")
        f.write("\n".join(lines) + "\n")
    n_keys = len({tuple(ln.split("\t")[4:6]) for ln in lines if ln.split("\t")[3] == "1"})
    print(f"{a.rec}: {len(lines)} items, {n_keys} distinct keys, game_ram {int(game_ram)}, "
          f"legacy {int(legacy)}")


if __name__ == "__main__":
    sys.exit(main())
