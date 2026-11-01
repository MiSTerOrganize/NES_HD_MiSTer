"""Write a copy of a format-3 pack in which one BG group's lookup reads a pixel of the SAME group
that the group's own fallback lookup has just rewritten - the case hd3_render's per-pixel
restart and its rewrite-aware tileNearby exist for.

Mesen looks a tile up pixel by pixel; when the exact key is missing and the fallback key exists
it rewrites the record's TileIndex to the fallback (spec 3.16), so a tile condition reading that
pixel AFTER its lookup sees the fallback index. hd3_render reproduces this from lookup order for
conditions flagged rewrite-sensitive (q0 bit 24); inside a BG group it restarts the walk one
pixel at a time. No pack in the corpus has a sensitive condition that can see a rewrite inside
one group, so without this fixture that path never decides a pixel and a renderer that skips it
passes every test (the negative control showed exactly that).

The fixture, on a recorded frame with fallback hits:
  P   a BG pixel that is not the first pixel of its tile (P-1 holds the same tile), whose record
      has no exact key but whose fallback key exists; the target is its list's first rule, whose
      frame list is cleared (on the recorded frames every such rule's frame condition is false,
      so RESOLVE would drop it before any walk condition was evaluated)
  L   a walk list of ONE condition, used by as few rules as possible and whose condition is
      used nowhere else
The target rule's walk pointer is set to L and its disable-cache flag is set (else Mesen looks
up only the first pixel of each 8-pixel group and the others reuse it), and L's condition becomes

    tileNearby X=-1 Y=0, tile = P's ORIGINAL index, P's palette compared, rewrite-sensitive

which is true on P-1's original record and false once P-1's own lookup has rewritten it - so the
group's later pixels lose the rule exactly when the rewrite is modelled. The reference
(hdref.render) rewrites records in Mesen's order and grades the result; whether the scene
reaches the output is checked by running the RTL with the restart disabled (the negative
control's mutant).

--dx 0 makes the condition tileNearby X=0 Y=0, which reads the pixel being looked up ITSELF:
Mesen rewrites the record before walking its rules, so the condition sees its own rewritten
index and is false; a renderer that treats the record as not yet looked up gets true. (Real
packs carry sensitive offset-0 nearby conditions - Metroid a033/a034.)

usage: python make_rewrite_frame.py <in.hdp> <recdir> <frame> <out.hdp> [--pick N] [--list]
                                    [--dx -1|0]
"""
import os
import struct
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import hdref  # noqa: E402


def key_offsets(h):
    offs = set()
    for b in range(h.nbuckets):
        base = h.s(0) + b * 64
        for j in range(4):
            q0, q1 = struct.unpack_from("<QQ", h.d, base + j * 16)
            if q1 >> 63:
                offs.add(((q1 >> 32) & 0x3FFFFFFF) * 8)
    return offs


def pick_walk_list(h):
    """The one-condition walk list used by the fewest rules whose condition no other list uses."""
    use, cond_use = Counter(), Counter()
    for off in key_offsets(h):
        for rule in h.rules(off):
            for lst in (rule["frame"], rule["walk"]):
                if lst:
                    cond_use.update(set(h.clist(lst)))
            if rule["walk"]:
                use[rule["walk"]] += 1
    best = None
    for w, n in use.items():
        cl = h.clist(w)
        if len(cl) == 1 and cond_use[cl[0]] == 1 and not h.cond(cl[0])["frame"]:
            if best is None or n < best[1]:
                best = (w, n, cl[0])
    return best


def candidates(h, rec, watch, dx=-1):
    r = hdref.HdRef(h, rec, watch, False)
    screen = hdref.build_records(rec, False, bool(h.flags & 1))     # unrewritten copy
    seen, out = set(), []
    top, right, bottom, left = [max(0, v) for v in h.overscan]
    for y in range(top, 240 - bottom):          # lines and columns Mesen looks up
        for x in range(max(1, left + 1), 256 - right):
            t = screen[y * 256 + x].tile
            if t.idx == hdref.NOTILE or (dx < 0 and t.offx == 0):
                continue
            if hdref.HdRef.find(r, t.pal, t) is not None:
                continue
            f = hdref.HdRef.fallback(r, t.idx)
            if f < 0:
                continue
            org = t.idx
            t.idx = f
            off = hdref.HdRef.find(r, t.pal, t)
            if off is None:
                off = hdref.HdRef.find(r, 0xFFFFFFFF, t)
            t.idx = org
            if off is None or (off, org, t.pal) in seen:
                continue
            seen.add((off, org, t.pal))
            out.append(dict(y=y, x=x, idx=org, fb=f, pal=t.pal, off=off, rule=0))
    return out


def main():
    a = sys.argv[1:]
    if len(a) < 4:
        print(__doc__)
        return 2
    hdp, recdir, frame, outp = a[0], a[1], int(a[2]), a[3]
    pick = int(a[a.index("--pick") + 1]) if "--pick" in a else 0
    dx = int(a[a.index("--dx") + 1]) if "--dx" in a else -1
    if dx not in (-1, 0):
        sys.exit("--dx must be -1 or 0")
    data = bytearray(open(hdp, "rb").read())
    h = hdref.Hdp3(bytes(data))
    if h.flags & 0x10:
        sys.exit("CHR-RAM game: no fallback map, no rewrite")
    rec = open(os.path.join(recdir, f"rec_{frame:04d}.bin"), "rb").read()
    watch = open(os.path.join(recdir, f"watch_{frame:04d}.bin"), "rb").read()
    cs = candidates(h, rec, watch, dx)
    if "--list" in a:
        for i, c in enumerate(cs):
            print(i, c)
        return 0
    if pick >= len(cs):
        sys.exit(f"{len(cs)} candidates on frame {frame}")
    wl = pick_walk_list(h)
    if wl is None:
        sys.exit("no one-condition walk list with a private condition")
    w, n, ci = wl
    c = cs[pick]
    # the target rule gets walk list L, and disables the 8-pixel
    # BG cache (word 3 bit 24) - with the cache on, only a group's first pixel is looked up and
    # the rest reuse its result, so no pixel would read a rewrite made inside its own group
    rw = h.s(1) + c["off"] + 8 + 16 * c["rule"]
    struct.pack_into("<I", data, rw + 4, 0)
    struct.pack_into("<I", data, rw + 8, w)
    # bit 24 = ForceDisableCache, bit 25 = its running OR over this and the earlier rules (the
    # hardware reads the prefix bit - hdp3_convert writes both); this rule is the list's first
    (w3,) = struct.unpack_from("<I", data, rw + 12)
    struct.pack_into("<I", data, rw + 12, w3 | (1 << 24) | (1 << 25))
    if c["rule"] != 0:
        sys.exit("a later rule's prefix bit would need recomputing")
    # L's condition: tileNearby (type 5), walk-class, index tile, palette compared, sensitive
    struct.pack_into("<QQQQ", data, h.s(2) + 32 * ci,
                     5 | (1 << 24), dx & 0xFFFFFFFF, c["idx"] & 0xFFFFFFFFFFFFFFFF,
                     c["pal"] & 0xFFFFFFFF)
    open(outp, "wb").write(data)
    print(f"{outp}: frame {frame} pixel ({c['x']},{c['y']}) tile {c['idx']} -> fallback {c['fb']} "
          f"pal {c['pal']:08x}; its rule {c['rule']} walks list {w} (was used by {n} rules), "
          f"c{ci} := tileNearby({dx},0) tile {c['idx']}, sensitive")
    return 0


if __name__ == "__main__":
    sys.exit(main())
