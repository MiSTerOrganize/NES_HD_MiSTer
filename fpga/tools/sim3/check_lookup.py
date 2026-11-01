"""Check tb_lookup.exe's answers against tools/hdp3_read.py (written separately from the RTL).

For every query line: the key's presence and rule-list offset (Hdp3.find_key), the list's
rule count, the first rule whose frame and walk condition lists are both empty (Hdp3.rules) -
payload and position - and the number of buckets read. The bucket count matters: a search
that does not stop at an empty entry still finds the right answers on a well-formed table,
but reads buckets it should not, which costs DDR3 time the line budget does not have. Exit 0
only when every line agrees and the run both found keys and missed keys (a run that never
exercised one side checks nothing).

usage: python check_lookup.py <file.hdp> <tb_out.tsv> [--key-only]

--key-only checks a run made with tb_lookup --key-only: the lookup stops once the key is
decided, so count and the pick must come back 0 (the list is never read).
"""
import os
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from hdp3_read import Hdp3  # noqa: E402
from hdp3_convert import crc32  # noqa: E402  (the hash is part of the format)


def buckets_read(h, pal, kind, lo, hi):
    """Buckets a correct search reads: it stops at the bucket holding the key or an empty
    entry, or after max_probe + 1 buckets."""
    b0 = crc32(struct.pack("<III", pal, lo, hi)) & (h.nbuckets - 1)
    for probe in range(h.max_probe + 1):
        b = h.s(0) + ((b0 + probe) & (h.nbuckets - 1)) * 64
        for j in range(4):
            q0, q1 = struct.unpack_from("<QQ", h.d, b + j * 16)
            if not q1 >> 63:
                return probe + 1
            if ((q0 & 0xFFFFFFFF) == pal and q0 >> 32 == lo and (q1 & 0xFFFFFFFF) == hi
                    and (q1 >> 62) & 1 == kind):
                return probe + 1
    return h.max_probe + 1


def main():
    key_only = "--key-only" in sys.argv[3:]
    if len(sys.argv) != 3 + key_only:
        print(__doc__)
        return 2
    with open(sys.argv[1], "rb") as f:
        h = Hdp3(f.read())
    bad = 0
    n = hits = misses = picks = 0
    with open(sys.argv[2]) as f:
        cols = f.readline().rstrip("\n").split("\t")
        for line in f:
            r = dict(zip(cols, line.rstrip("\n").split("\t")))
            pal, kind, lo, hi = (int(r["pal"], 16), int(r["kind"]), int(r["lo"], 16), int(r["hi"], 16))
            off = h.find_key(pal, kind, lo, hi)
            nb = min(buckets_read(h, pal, kind, lo, hi), 15)     # the RTL counter saturates at 15
            exp = {"found": 0, "list_off": 0, "count": 0, "pick_valid": 0, "probes": nb}
            if off is not None and key_only:
                exp = {"found": 1, "list_off": off, "count": 0, "pick_valid": 0, "probes": nb}
            elif off is not None:
                rules = h.rules(off)
                exp = {"found": 1, "list_off": off, "count": len(rules), "pick_valid": 0,
                       "probes": nb}
                for i, ru in enumerate(rules):
                    if ru["frame"] == 0 and ru["walk"] == 0:
                        exp.update(pick_valid=1, payload=ru["payload"], index=i)
                        break
            got = {"found": int(r["found"]), "list_off": int(r["list_off"]), "count": int(r["count"]),
                   "pick_valid": int(r["pick_valid"]), "probes": int(r["probes"])}
            if got["pick_valid"]:
                got.update(payload=int(r["payload"], 16), index=int(r["index"]))
            n += 1
            hits += exp["found"]
            misses += 1 - exp["found"]
            picks += exp["pick_valid"]
            if got != exp:
                bad += 1
                if bad <= 10:
                    print(f"MISMATCH key pal={pal:08x} kind={kind} lo={lo:08x} hi={hi:08x}: "
                          f"rtl {got} expected {exp}")
    print(f"{sys.argv[2]}: {n} queries ({hits} present, {misses} absent, {picks} with an "
          f"unconditional rule): {bad} mismatches")
    if n == 0 or hits == 0 or misses == 0:
        print("FAIL: the run did not exercise both present and absent keys")
        return 1
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
