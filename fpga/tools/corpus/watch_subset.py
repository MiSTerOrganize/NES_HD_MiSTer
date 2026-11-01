"""watch_subset.py - one pack's watch snapshot out of a recording made with a union list.

A corpus recording serves every pack of the same game, so fullsim runs with --watch on the
UNION of those packs' watched addresses (hd_watch takes up to 256). hdarm4 and hdref want the
snapshot in the pack's own slot order (watch_FFFF.bin: "NWAT", n, n x u32 list, n x u8 values,
u32 flags, then the CPU RAM / CIRAM / PRG-RAM / palette dumps). This writes that file for one
pack: same layout, the pack's list, each value taken from the union entry with the same u32
address. An address missing from the union is an error (the recording was made for another
pack set), never a guess.

    python -I watch_subset.py PACK.hdp union_watch.bin out_watch.bin
    python -I watch_subset.py --list PACK.hdp [PACK.hdp ...]   (print the union list, hex)
"""
import os
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from hdp3_read import Hdp3  # noqa: E402


def pack_list(path):
    return Hdp3(open(path, "rb").read()).watched


if sys.argv[1] == "--list":
    seen, out = set(), []
    for p in sys.argv[2:]:
        for a in pack_list(p):
            if a not in seen:
                seen.add(a)
                out.append(a)
    if len(out) > 256:
        sys.exit(f"union of {len(out)} addresses is over hd_watch's 256")
    for a in out:
        print(f"{a:08x}")
    sys.exit(0)

pack_p, union_p, out_p = sys.argv[1:4]
want = pack_list(pack_p)
u = open(union_p, "rb").read()
if u[:4] != b"NWAT":
    sys.exit(f"{union_p}: bad magic")
n = struct.unpack_from("<I", u, 4)[0]
ulist = list(struct.unpack_from(f"<{n}I", u, 8))
uvals = u[8 + 4 * n: 8 + 5 * n]
tail = u[8 + 5 * n:]                       # flags + dumps, unchanged
pos = {a: i for i, a in enumerate(ulist)}
missing = [a for a in want if a not in pos]
if missing:
    sys.exit(f"{os.path.basename(pack_p)}: {len(missing)} watched addresses not in the recording, "
             f"first {missing[0]:08x}")
vals = bytes(uvals[pos[a]] for a in want)
with open(out_p, "wb") as fh:
    fh.write(b"NWAT" + struct.pack("<I", len(want)) + struct.pack(f"<{len(want)}I", *want) + vals + tail)
