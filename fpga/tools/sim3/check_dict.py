"""Check tb_dict.exe's read-back against dict_golden.py, one golden file per streamed frame
(in the order the frames were given to the testbench).

Per frame: every BG span and sprite fetch must carry the golden key and resolution (via,
rule-list offset, fallback, second-hop fallback); ids must be consistent - the same key
always the same id, different keys different ids; the bank's record count must equal the
number of distinct keys; overflow must stay 0 unless the golden says a line fetched more than
16 sprites. Exit 0 only when every check holds and something was checked.

--drop-header Y matches tb_dict's option of the same name: line Y was streamed without its
header, so it must hold no records - its items are left out of the comparison and its keys
out of the expected record count.

--pack PACK (8a additions): when the pack has an addition table (sections 16/17), every
record's addition list must be the union, in file order, of the lists its up-to-four keys hold
- (palette, body), (any, body) and, CHR-ROM with a fallback F != body, (palette, F) and
(any, F) - read here straight from the table (written separately from the RTL); its
has-additions bit must say whether the list is empty; each entry's id must hold the added key
and agree with the ids of the frame's other keys; and the record count must be the number of
distinct captured AND added keys. A frame whose lists overflow the 1,024-entry pool must
report overflow (8o) and is not compared further.

--lag (lag tests, tb_dict --allow-abandon under a DDR3 latency far beyond the real one): the
resolver may fall behind. A frame it could not finish must say so - overflow 1 with no
predicted cause is accepted as a timing overflow (the frame is drawn without lookups, so its
additions and record count are not compared; its captured keys still are), and an abandoned
frame (no frame_done: its bank was restarted) is accepted only if the next frame streamed
into the same bank reports overflow. Nothing may be wrong in a frame that claims to be whole.

usage: python check_dict.py <tb_out.tsv> <golden0.tsv> [<golden1.tsv> ...] [--drop-header Y]
                            [--pack PACK] [--lag]
"""
import os
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from hdp3_convert import crc32  # noqa: E402  (the format's hash)

ANY = 0xFFFFFFFF
POOL = 1024
ABUF = 64


class AddTable:
    """The addition-key table (section 16) and its lists (section 17) of a format-3 pack."""

    def __init__(self, path):
        d = open(path, "rb").read()
        self.d = d
        self.nb, self.mp = struct.unpack_from("<II", d, 0x4C)
        self.keys, nkeys = struct.unpack_from("<II", d, 0x80 + 8 * 16)
        self.lists, _ = struct.unpack_from("<II", d, 0x80 + 8 * 17)
        self.on = nkeys != 0
        nfb = struct.unpack_from("<I", d, 0x44)[0]
        fbs = struct.unpack_from("<I", d, 0x80 + 8 * 10)[0]
        self.fb = list(struct.unpack_from(f"<{nfb}i", d, fbs)) if nfb else []

    def lookup(self, pal, kind, body):
        lo, hi = body & 0xFFFFFFFF, body >> 32
        h = crc32(struct.pack("<III", pal, lo, hi)) & (self.nb - 1)
        for probe in range(self.mp + 1):
            b = self.keys + ((h + probe) & (self.nb - 1)) * 64
            for j in range(4):
                q0, q1 = struct.unpack_from("<QQ", self.d, b + j * 16)
                if not q1 >> 63:
                    return []
                if ((q0 & 0xFFFFFFFF) == pal and q0 >> 32 == lo and (q1 & 0xFFFFFFFF) == hi
                        and (q1 >> 62) & 1 == kind):
                    off = self.lists + ((q1 >> 32) & 0x3FFFFFFF) * 8
                    (cnt,) = struct.unpack_from("<I", self.d, off)
                    out = []
                    for e in range(cnt):
                        e0, apal, abody = struct.unpack_from("<QQQ", self.d, off + 8 + 24 * e)
                        out.append((e0 & 0xFFFF, s16((e0 >> 16) & 0xFFFF),
                                    s16((e0 >> 32) & 0xFFFF), apal & 0xFFFFFFFF, abody))
                    return out
        return []

    def matched(self, pal, kind, body):
        bodies = [body]
        if kind == 0 and 0 <= body < len(self.fb) and self.fb[body] >= 0 and self.fb[body] != body:
            bodies.append(self.fb[body])
        hit = {}
        for b in bodies:
            for p in (pal, ANY):
                for e in self.lookup(p, kind, b):
                    hit[e[0]] = e
        return [hit[i] for i in sorted(hit)]


def s16(v):
    return v - 0x10000 if v & 0x8000 else v


def load_golden(path):
    rows = {}
    with open(path) as f:
        head = f.readline().lstrip("#").split()
        for line in f:
            p = line.rstrip("\n").split("\t")
            if len(p) < 10:
                continue
            rows[(p[0], int(p[1]), int(p[2]))] = p[3:]
    return rows, int(head[2]), int(head[0])


def parse_adds(s):
    """'H/entries' -> (has-additions bit, [(idx, ox, oy, id, pal, body)])."""
    hb, _, rest = s.partition("/")
    out = []
    if rest and rest != "-":
        for e in rest.split(","):
            idx, ox, oy, aid, apal, abody = e.split(":")
            out.append((int(idx), int(ox), int(oy), aid, apal, abody))
    return int(hb), out


def main():
    args = sys.argv[1:]
    drop = None
    if "--drop-header" in args:
        i = args.index("--drop-header")
        drop = int(args[i + 1])
        del args[i:i + 2]
    lag = "--lag" in args
    if lag:
        args.remove("--lag")
    table = None
    if "--pack" in args:
        i = args.index("--pack")
        table = AddTable(args[i + 1])
        del args[i:i + 2]
        if not table.on:
            table = None
    if len(args) < 2:
        print(__doc__)
        return 2
    goldens = []
    for g in args[1:]:
        rows, over, game_ram = load_golden(g)
        if drop is not None:
            rows = {k: v for k, v in rows.items() if k[1] != drop}
        goldens.append((rows, over, game_ram))
    got = {}
    meta = {}
    dropped = {}
    abandoned = {}                      # frame -> bank
    with open(args[0]) as f:
        f.readline()
        for line in f:
            if line.startswith("#abandoned"):
                w = line.split()
                abandoned[int(w[1])] = int(w[3])
                continue
            if line.startswith("#dropped"):
                w = line.split()
                dropped[int(w[1])] = (int(w[3]), int(w[5]))
                continue
            if line.startswith("#frame"):
                w = line.split()
                meta[int(w[1])] = dict(bank=int(w[3]), nrec=int(w[5]), overflow=int(w[7]),
                                       sticky=int(w[9]) if len(w) > 9 else None)
                continue
            p = line.rstrip("\n").split("\t")
            got.setdefault(int(p[0]), {})[(p[1], int(p[2]), int(p[3]))] = p[4:]
    bad = 0
    checked = 0
    any_over = False
    sticky_seen = False

    def report(msg):
        nonlocal bad
        bad += 1
        if bad <= 12:
            print("MISMATCH " + msg)

    n_timing = 0
    for k, (gold, nfet_over, game_ram) in enumerate(goldens):
        if k in abandoned:
            if not lag:
                report(f"frame {k}: abandoned (no frame_done) outside a lag test")
                continue
            # the next frame streamed into the same bank must have been told
            nxt = next((j for j in range(k + 1, len(goldens))
                        if meta.get(j, {}).get("bank") == abandoned[k]), None)
            if nxt is None or not meta.get(nxt, {}).get("overflow"):
                report(f"frame {k}: abandoned, but the next frame of its bank ({nxt}) "
                       "does not report overflow")
            print(f"frame {k}: abandoned (bank restarted before it was resolved)")
            any_over = True
            continue
        tb = got.get(k)
        if tb is None:
            report(f"frame {k}: no read-back")
            continue
        m = meta.get(k)
        timing_over = False
        ids = {}
        keys_of = {}
        # additions: each distinct captured key's merged list, and whether the frame overflows
        # the pool or one record's 64-entry buffer (then the frame is drawn without lookups)
        want_adds = {}
        add_over = False
        if table is not None:
            for item, g in gold.items():
                if g[0] == "1" and (g[1], g[2]) not in want_adds:
                    want_adds[(g[1], g[2])] = table.matched(int(g[1], 16), game_ram,
                                                            int(g[2], 16))
            add_over = (sum(len(v) for v in want_adds.values()) > POOL or
                        any(len(v) > ABUF for v in want_adds.values()))
        # --lag: an overflow with no predicted cause is the resolver falling behind; the frame
        # is drawn without lookups, so only its captured keys are compared
        if lag and m is not None and m["overflow"] and not (nfet_over or add_over):
            timing_over = True
            n_timing += 1
        skip = add_over or timing_over
        for item, g in gold.items():
            t = tb.get(item)
            checked += 1
            if t is None:
                report(f"frame {k} {item}: missing in the read-back")
                continue
            if g[0] == "0":
                if t[0] != "0":
                    report(f"frame {k} {item}: invalid sprite fetch got a record {t}")
                continue
            if t[0] != "1":
                report(f"frame {k} {item}: no record (golden {g})")
                continue
            tid, tpal, tbody, tvia, toff, tfb, tfb2 = t[1:8]
            gpal, gbody, gvia, goff, gfb, gfb2 = g[1:7]
            if timing_over:
                # the resolver may not have reached this record: only the capture is checked
                if (tpal, tbody) != (gpal, gbody):
                    report(f"frame {k} {item}: rtl key {tpal}/{tbody}, golden {gpal}/{gbody}")
            elif (tpal, tbody, tvia, toff, tfb, tfb2) != (gpal, gbody, gvia, goff, gfb, gfb2):
                report(f"frame {k} {item}: rtl pal {tpal} body {tbody} via {tvia} off {toff} "
                       f"fb {tfb} fb2 {tfb2}; golden pal {gpal} body {gbody} via {gvia} "
                       f"off {goff} fb {gfb} fb2 {gfb2}")
            key = (gpal, gbody)
            if key in ids and ids[key] != tid:
                report(f"frame {k} {item}: key {key} has ids {ids[key]} and {tid}")
            ids.setdefault(key, tid)
            if tid in keys_of and keys_of[tid] != key:
                report(f"frame {k} {item}: id {tid} holds keys {keys_of[tid]} and {key}")
            keys_of.setdefault(tid, key)
            if table is not None and not skip:
                hb, entries = parse_adds(t[8])
                want = want_adds[key]
                if hb != (1 if want else 0):
                    report(f"frame {k} {item}: has-additions bit {hb}, list of {len(want)}")
                gotl = [(i, ox, oy, int(p, 16), int(b, 16)) for i, ox, oy, _, p, b in entries]
                wantl = [(i, ox, oy, p, b & 0xFFFFFFFFFFFFFFFF) for i, ox, oy, p, b in want]
                if gotl != wantl:
                    report(f"frame {k} {item}: additions {gotl[:3]}... ({len(gotl)}), "
                           f"expected {wantl[:3]}... ({len(wantl)})")
                for _, _, _, aid, apal, abody in entries:
                    akey = (apal, abody)
                    if akey in ids and ids[akey] != aid:
                        report(f"frame {k} {item}: added key {akey} has ids {ids[akey]} and {aid}")
                    ids.setdefault(akey, aid)
                    if aid in keys_of and keys_of[aid] != akey:
                        report(f"frame {k} {item}: id {aid} holds keys {keys_of[aid]} and {akey}")
                    keys_of.setdefault(aid, akey)
        extra = set(tb) - set(gold)
        if extra:
            report(f"frame {k}: {len(extra)} items not in the golden, e.g. {sorted(extra)[:3]}")
        if drop is not None:
            d = dropped.get(k)
            if d is None or d[0] != drop:
                report(f"frame {k}: no read-back of the header-less line {drop}")
            elif d[1]:
                report(f"frame {k}: header-less line {drop} holds {d[1]} valid ids, expected 0")
        m = meta.get(k)
        if m is None:
            report(f"frame {k}: no summary line")
        else:
            # every distinct added key must hold a record too (8a), so with additions on the
            # count is checked against the keys the checker itself derived from the table
            nkeys = len(ids)
            if table is not None and not skip:
                added = {(f"{p:08x}", f"{b & 0xFFFFFFFFFFFFFFFF:016x}")
                         for v in want_adds.values() for _, _, _, p, b in v}
                nkeys = len(set(want_adds) | added)
            if not skip and m["nrec"] != nkeys:
                report(f"frame {k}: nrec {m['nrec']}, distinct keys {nkeys}")
            if m["overflow"] != (nfet_over or add_over or timing_over):
                report(f"frame {k}: overflow {m['overflow']}, expected {int(nfet_over or add_over)}")
            # the sticky flag latches: once any frame up to this one overflowed it must be set
            # (it may be set early - with --overlap the next frame is captured before this
            # read-back - so only "set when due" is checked here, "never set when no frame
            # overflowed" after the loop)
            any_over = any_over or nfet_over or add_over or timing_over
            if m["sticky"] is not None and any_over and not m["sticky"]:
                report(f"frame {k}: sticky overflow 0 after an overflowed frame")
            sticky_seen = sticky_seen or bool(m["sticky"])
        npool = sum(len(v) for v in want_adds.values())
        print(f"frame {k}: {len(gold)} items, {len(ids)} distinct keys, nrec "
              f"{m['nrec'] if m else '?'}" +
              (f", {npool} pool entries over {sum(1 for v in want_adds.values() if v)} records"
               + (" (OVERFLOW)" if add_over else "") if table is not None else "")
              + (" (TIMING OVERFLOW: resolver fell behind, drawn without lookups)"
                 if timing_over else ""))
    if sticky_seen and not any_over:
        report("sticky overflow set though no frame overflowed")
    if lag:
        print(f"lag: {n_timing} frame(s) timing-overflowed, {len(abandoned)} abandoned")
    print(f"{args[0]}: {checked} items checked, {bad} mismatches")
    if checked == 0:
        print("FAIL: nothing checked")
        return 1
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
