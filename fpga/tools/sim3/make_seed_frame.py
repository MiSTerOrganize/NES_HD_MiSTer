"""Write a copy of a format-3 pack in which a rewrite-sensitive FRAME condition is first used by
background selection and later by a lookup, after the tile it reads has been rewritten - the
case hd3_render's memo SEED exists for.

Mesen memoises a frame condition at its first use, and background selection runs before any
lookup (PACK:300-313), so a condition a background tests keeps the value it had on the
unrewritten screen for the rest of the frame. hd3_resolve evaluates such a condition during
selection and passes the value to hd3_render, whose frame-start memo sweep loads it (8i). A
renderer that clears the memo instead evaluates the condition again at its first lookup, after
the rewrite, and gets the other answer. No pack in the corpus has a sensitive background
condition, so without this fixture the seed never decides a pixel (the negative control's
"memo not seeded" mutant passed every other fixture).

The fixture, on a recorded frame with fallback hits:
  P   a pixel whose record has no exact key but whose fallback key exists, so Mesen rewrites
      its TileIndex to the fallback when it is looked up
  c   a frame condition reached through a one-condition list F; it becomes
          tileAtPosition (P.x, P.y), tile = P's ORIGINAL index, palette compared, sensitive
      which is true before P's lookup and false after it
  L   a background level whose first entry's frame list becomes F (the level is made
      unindexed), so selection evaluates c first - true - and the memo holds true
  Q   a pixel on a later line, with an exact key of its own, whose list's first rule gets frame
      list F and no walk list: with the seed the rule matches (true), without it the rule is
      evaluated after P's rewrite and fails
Every other rule that reaches c (any list holding it, as a frame or walk list) has that list
cleared first: one of them walked above P would evaluate c before the rewrite and memoise true
whether or not the seed works. L is assigned after that scrub, which would otherwise clear it.
The script renders the frame with the reference twice - as Mesen, and with c's memo dropped
after selection (the unseeded renderer) - and keeps the first Q for which the two pictures
differ, so the fixture provably decides a pixel.

usage: python make_seed_frame.py <in.hdp> <recdir> <frame> <out.hdp> [--tries N]
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import hdref  # noqa: E402
import make_rewrite_frame as mrw  # noqa: E402


def one_cond_frame_lists(h):
    """(list offset, condition) for every one-condition list some rule uses as its frame list."""
    out = {}
    offs = set(mrw.key_offsets(h))
    for lvl in range(40):
        roff, _ = h.bg_level(lvl)
        if roff:
            offs.add(roff)
    for off in offs:
        for rule in h.rules(off):
            f = rule["frame"]
            if f and f not in out:
                cl = h.clist(f)
                if len(cl) == 1 and h.cond(cl[0])["frame"]:
                    out[f] = cl[0]
    return out


def list_of(r, t):
    """The rule list a lookup of tile t walks: its key, the any-palette key, then the same two
    for its fallback tile (Mesen's order, spec 3.16)."""
    off = hdref.HdRef.find(r, t.pal, t)
    if off is None:
        off = hdref.HdRef.find(r, 0xFFFFFFFF, t)
    if off is not None:
        return off
    f = hdref.HdRef.fallback(r, t.idx)
    if f < 0 or f == t.idx:
        return None
    org = t.idx
    t.idx = f
    off = hdref.HdRef.find(r, t.pal, t)
    if off is None:
        off = hdref.HdRef.find(r, 0xFFFFFFFF, t)
    t.idx = org
    return off


def render(data, rec, watch, game_ram, drop=None):
    h = hdref.Hdp3(bytes(data))
    r = hdref.HdRef(h, rec, watch, game_ram)
    r.process_additions = lambda: None
    if drop is not None:
        sel = r.select_backgrounds

        def unseeded():
            layers = sel()
            r.memo.pop(drop, None)
            return layers
        r.select_backgrounds = unseeded
    out = r.render()
    return out, r


def main():
    a = sys.argv[1:]
    if len(a) < 4:
        print(__doc__)
        return 2
    hdp, recdir, frame, outp = a[0], a[1], int(a[2]), a[3]
    tries = int(a[a.index("--tries") + 1]) if "--tries" in a else 12
    data = bytearray(open(hdp, "rb").read())
    h = hdref.Hdp3(bytes(data))
    if h.flags & 0x10:
        sys.exit("CHR-RAM game: no fallback map, no rewrite")
    game_ram = False
    rec = open(os.path.join(recdir, f"rec_{frame:04d}.bin"), "rb").read()
    watch = open(os.path.join(recdir, f"watch_{frame:04d}.bin"), "rb").read()

    ps = mrw.candidates(h, rec, watch, 0)
    if not ps:
        sys.exit(f"no fallback hit on frame {frame}")
    lists = one_cond_frame_lists(h)
    if not lists:
        sys.exit("no one-condition frame list to borrow")
    levels = [lvl for lvl in range(40) if h.bg_level(lvl)[0]]
    if not levels:
        sys.exit("the pack has no backgrounds")
    F, ci = sorted(lists.items())[0]
    lvl = levels[0]

    screen = hdref.build_records(rec, game_ram, bool(h.flags & 1))
    r0 = hdref.HdRef(h, rec, watch, game_ram)
    top, right, bottom, left = [max(0, v) for v in h.overscan]
    # where each list is FIRST walked, in drawing order (row-major): a Q whose list is also
    # walked above P evaluates c there - before P's rewrite - so the memo holds true either
    # way and the seed decides nothing (the first version of this script tried such Qs only)
    first, kc = {}, {}
    for pos in range(256 * top, 256 * (240 - bottom)):
        t = screen[pos].tile
        if t.idx == hdref.NOTILE:
            continue
        k = (t.pal, t.idx)
        if k not in kc:
            kc[k] = list_of(r0, t)
        off = kc[k]
        if off is not None and off not in first:
            first[off] = pos
    all_offs = set(mrw.key_offsets(h)) | {h.bg_level(l)[0] for l in range(40) if h.bg_level(l)[0]}
    clists = {}
    print(f"{len(ps)} fallback hits; borrowing list {F} (c{ci}); background level {lvl}")
    for p in ps:
        px, py = p["x"], p["y"]
        ppos = py * 256 + px
        # Q: an exact key whose list is neither P's original nor fallback list, first walked
        # after P
        qs, seen = [], set()
        for y in range(py + 1, 240 - bottom):
            for x in range(left, 256 - right):
                t = screen[y * 256 + x].tile
                if t.idx == hdref.NOTILE:
                    continue
                if t.idx in (p["idx"], p["fb"]):
                    continue
                off = kc.get((t.pal, t.idx))
                if off is None or off == p["off"] or off in seen or first.get(off, -1) <= ppos:
                    continue
                seen.add(off)
                qs.append((x, y, off))
                if len(qs) >= tries:
                    break
            if len(qs) >= tries:
                break
        for qx, qy, qoff in qs:
            d = bytearray(data)
            q0 = struct.unpack_from("<Q", d, h.s(2) + 32 * ci)[0]
            memo = q0 >> 32
            # tileAtPosition (type 3), frame class (bit 11), index tile, palette compared,
            # rewrite-sensitive (bit 24); the condition keeps its memo slot
            nq0 = 3 | (1 << 11) | (1 << 24) | (memo << 32)
            struct.pack_into("<QQQQ", d, h.s(2) + 32 * ci, nq0,
                             (px & 0xFFFFFFFF) | ((py & 0xFFFFFFFF) << 32),
                             p["idx"] & 0xFFFFFFFFFFFFFFFF,
                             (p["pal"] & 0xFFFFFFFF) | (((py * 256 + px) & 0xFFFFFFFF) << 32))
            # c must be reached ONLY through L's entry 0 and Q's rule 0: the borrowed list F (or
            # any other list holding c) is also used by other tile rules, and one of those
            # walked above P evaluates c before the rewrite - true, so the memo holds true
            # seeded or not (why every pair of the first version found nothing). Drop those
            # references; the fixture stays self-consistent (the reference reads the same rules)
            for off in all_offs:
                for i, rule in enumerate(h.rules(off)):
                    for fld, lst in ((4, rule["frame"]), (8, rule["walk"])):
                        if lst and ci in clists.setdefault(lst, h.clist(lst)):
                            struct.pack_into("<I", d, h.s(1) + off + 8 + 16 * i + fld, 0)
            # level L: unindexed, its first entry tested by F (after the scrub, which cleared it)
            roff, _ = h.bg_level(lvl)
            struct.pack_into("<II", d, h.s(5) + lvl * 8, roff, 0)
            struct.pack_into("<I", d, h.s(1) + roff + 8 + 4, F)
            # Q's list, first rule: frame list F, no walk list
            struct.pack_into("<I", d, h.s(1) + qoff + 8 + 4, F)
            struct.pack_into("<I", d, h.s(1) + qoff + 8 + 8, 0)
            want, rw = render(d, rec, watch, game_ram)
            got, _ = render(d, rec, watch, game_ram, drop=ci)
            if rw.screen[py * 256 + px].tile.idx != p["fb"]:
                print(f"  P ({px},{py}) not rewritten in the reference (BG cache): next P")
                break
            ndiff = int((want != got).any(axis=2).sum())
            print(f"  P ({px},{py}) Q ({qx},{qy}): {ndiff} pixels differ")
            if ndiff:
                open(outp, "wb").write(d)
                print(f"{outp}: frame {frame} P ({px},{py}) tile {p['idx']} -> fallback "
                      f"{p['fb']} pal {p['pal']:08x}; c{ci} := tileAtPosition, sensitive, via "
                      f"list {F}; background level {lvl} entry 0 tests it; Q ({qx},{qy}) list "
                      f"{qoff} rule 0 tests it: {ndiff} output pixels differ unseeded")
                return 0
    sys.exit("no (P, Q) pair makes the seed decide a pixel")


if __name__ == "__main__":
    sys.exit(main())
