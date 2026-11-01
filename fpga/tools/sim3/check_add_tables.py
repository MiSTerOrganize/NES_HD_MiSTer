"""Check the 8a addition tables against the reference matcher.

For each pack: add sections 16/17 (hdp3_addtab.patch) to a temporary copy, then
  1. every addition is found through its own original key (and only lists that hold it);
  2. for every distinct record on the given frames (BG tiles and sprites), the hardware's
     up-to-four lookups give exactly hdref.additions_for, in file order, with the same offsets
     and added keys.
usage: python check_add_tables.py PACK.hdp RECDIR GAME_RAM FRAME [FRAME...]
exit 0 equal, 1 a difference, 2 refused (a chain)."""
import os
import struct
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import hdp3_addtab as at  # noqa: E402
import hdref  # noqa: E402


def main():
    pack, recdir, gr = sys.argv[1], sys.argv[2], int(sys.argv[3])
    tmp = os.path.join(tempfile.gettempdir(), "check_add_tables.hdp")
    try:
        at.patch(pack, tmp)
    except at.Refused as e:
        print(f"{os.path.basename(pack)}: refused: {e}")
        return 2
    d = open(tmp, "rb").read()
    nb, mp = struct.unpack_from("<II", d, 0x4C)
    t_off, t_len = struct.unpack_from("<II", d, 0x80 + 8 * at.S_ADDKEYS)
    l_off, l_len = struct.unpack_from("<II", d, 0x80 + 8 * at.S_ADDLISTS)
    table, lists = d[t_off:t_off + t_len], d[l_off:l_off + l_len]
    h = hdref.Hdp3(open(pack, "rb").read())
    bad = 0
    # 1: every addition reachable through its own key
    recs = at.records(d[h.s(11):h.s(11) + 64 * h.nadd], h.nadd)
    for i, r in enumerate(recs):
        pal, kind, lo, hi = at.table_key(r)
        got = [e[0] for e in at.lookup(table, nb, mp, lists, pal, kind, lo | (hi << 32))]
        if i not in got:
            print(f"  addition {i} not in the list of its own key")
            bad += 1
    nrec = 0
    for f in sys.argv[4:]:
        f = int(f)
        rec = open(os.path.join(recdir, f"rec_{f:04d}.bin"), "rb").read()
        watch = open(os.path.join(recdir, f"watch_{f:04d}.bin"), "rb").read()
        ref = hdref.HdRef(h, rec, watch, bool(gr))
        order = {id(a): i for i, a in enumerate(ref.additions)}   # identity, not equality
        seen = set()
        for p in ref.screen:
            for r in [p.tile] + p.spr:
                k = (r.pal, r.idx, r.fp)
                if k in seen:
                    continue
                seen.add(k)
                if gr:
                    if r.fp is None:
                        continue
                    kind, body = 1, r.fp
                else:
                    if r.idx == hdref.NOTILE:
                        continue
                    kind, body = 0, r.idx
                w = [(order[id(a)], a["ox"], a["oy"], a["apal"],
                      a["afp"] if gr else a["aidx"]) for a in ref.additions_for(r)]
                got = at.matched(table, nb, mp, lists, r.pal, kind, body, ref.fb)
                g = [(e[0], e[1], e[2], e[4], e[5] if gr else hdref.i64(e[5])) for e in got]
                if w != g:
                    if bad < 5:
                        print(f"  frame {f} record pal {r.pal:#x} idx {r.idx}: want {w[:4]} got {g[:4]}")
                    bad += 1
        nrec += len(seen)
    print(f"{os.path.basename(pack)}: {h.nadd} additions, table {nb} buckets (max probe {mp}), "
          f"{nrec} records checked, {bad} differences")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
