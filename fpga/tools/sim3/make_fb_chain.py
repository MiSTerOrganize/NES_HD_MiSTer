"""Write a copy of a format-3 pack whose fallback map has second-hop chains, so the
hd3_dict test reaches the fallback(fallback(idx)) read that no recorded frame reaches.

For every tile i whose fallback f has no fallback of its own, set fallback(f) = i. Entries
that already existed are never changed (checked); tiles that had none gain one, so a record
on such a tile may now also resolve by fallback. That is fine for a test: dict_golden.py
reads the same modified map. The copy is a test fixture, never a pack to ship.

usage: python make_fb_chain.py <in.hdp> <out.hdp>
"""
import os
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import hdref  # noqa: E402


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    data = bytearray(open(sys.argv[1], "rb").read())
    h = hdref.Hdp3(bytes(data))
    n = h.nfallback
    if not n:
        sys.exit("pack has no fallback map")
    base = h.s(10)
    fb = list(struct.unpack_from(f"<{n}i", data, base))
    added = 0
    for i, f in enumerate(fb):
        if 0 <= f < n and fb[f] < 0:
            fb[f] = i
            added += 1
    if not added:
        sys.exit("no chain could be added")
    struct.pack_into(f"<{n}i", data, base, *fb)
    # the first hop must be untouched for every tile that had one
    old = struct.unpack_from(f"<{n}i", h.d, base)
    changed = [i for i in range(n) if old[i] != fb[i]]
    if any(old[i] >= 0 for i in changed):
        sys.exit("a first-hop entry changed - refusing")
    with open(sys.argv[2], "wb") as f:
        f.write(data)
    print(f"{sys.argv[2]}: {added} second-hop chains added ({n} map entries)")


if __name__ == "__main__":
    sys.exit(main())
