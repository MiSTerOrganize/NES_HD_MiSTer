"""Write a copy of a format-3 pack whose FRAME tileAtPosition / spriteAtPosition conditions are
retargeted to traps on the given recorded frames, so the hd3_resolve test can see bugs the
recorded conditions never expose (on the recorded frames no positional condition sits where a
palette mismatch, a tile-row boundary or a sprite's right edge decides its result):

  palette trap   the tile (or a covering sprite) actually at the position, but with a different
                 palette and the ignore flag clear: false, true if the palette is ignored
  row edge       tileAt: the BG tile at (x, y) exactly, on a line whose next line holds a
                 different record for the same span slot: true, false if line y+1 is read
  cover edge     spriteAt: a sprite's own tile and palette at sx + 8, one pixel right of it,
                 where sprites are shown: false, true if the cover window is 9 pixels
  fallback       tileAt: T = fallback(idx) of the tile actually there, T != idx: true, false if
                 the fallback map is not consulted (packs with a fallback map only)
  hidden         spriteAt: a sprite's tile and palette at a pixel it covers where sprites are
                 NOT shown at the dot: false, true if the sprites-shown bit is ignored
  sprite match   spriteAt: a covering sprite exactly, where its palette group read from the BG
                 half would differ: true, false if the palette comes from the BG groups

A trap only catches a bug if RESOLVE evaluates it on its frame AND its result reaches the
output, so traps are placed where both hold (fixture_pick.py): for each role, a frame with a
candidate position, then a frame condition that frame evaluates (frameRange, one-slot
memoryCheckConstant or a positional check, frame-class, not rewrite-sensitive) is turned into
that trap (tileAt or spriteAtPosition, data flag = game_ram, ignore flag clear) and kept only
if inverting it changes the golden. --per-role N traps per role (default 2). When every trap is
placed the whole set is checked again (a later trap can stop an earlier one being evaluated)
and the survivors are reported per role. The first version tuned condition ci for frame
FRAMES[ci % n] whether or not that frame ever filtered its rule list: on Metroid no positional
condition was evaluated at all (trap_sense.py), and the negative control caught only the
palette mutant of the 9 positional/fingerprint/legacy ones. A trap is also kept only if hdref.tmatch says the correct
result and the bug's result differ. resolve_golden.py reads the same modified pack. A test
fixture only.

usage: python make_pos_frame.py <in.hdp> <out.hdp> <recdir> <game_ram 0/1> [--per-role N]
                                <frame> [...]
"""
import os
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hdref  # noqa: E402
import fixture_pick  # noqa: E402

MEM_CONST, FRAME_RANGE, TILE_AT, SPRITE_AT = 1, 2, 3, 4
# frame conditions a trap may replace: the one-slot memory checks, frame ranges and the
# positional checks themselves (a two-slot memoryCheck is left alone - its edge fixture uses it)
POOL_TYPES = (MEM_CONST, FRAME_RANGE, TILE_AT, SPRITE_AT)


def line_spans(rec, y, game_ram, legacy):
    """Line y's span table and palette RAM, as hdref.build_records reads them."""
    hoff = 0x40000 + y * 2048
    q0 = struct.unpack_from("<Q", rec, hoff)[0]
    nspan = min((q0 >> 32) & 0xFF, 34)
    pbits = int.from_bytes(rec[hoff + 8:hoff + 32], "little")
    pal = [(pbits >> (6 * n)) & 63 for n in range(32)]
    out = []
    for s in range(nspan):
        qa, qb = struct.unpack_from("<QQ", rec, hoff + 64 + s * 16)
        lin, psel = qa & 0x3FFFFF, (qa >> 32) & 3
        r = hdref.Rec.__new__(hdref.Rec)
        r.idx = hdref.chr_index(lin)
        pb = psel * 4
        r.pal = pal[pb + 3] | (pal[pb + 2] << 8) | (pal[pb + 1] << 16)
        if not legacy:
            r.pal |= pal[0] << 24
        r.fp = qb if game_ram else hdref.ZERO_FP
        out.append(r)
    return out


def line_pal(rec, y):
    pbits = int.from_bytes(rec[0x40000 + y * 2048 + 8:0x40000 + y * 2048 + 32], "little")
    return [(pbits >> (6 * n)) & 63 for n in range(32)]


def sprites_of(rec, y, game_ram=False, legacy=False):
    """The line's valid sprite fetches as (sx, Rec, bg_group_pal), as build_records makes them;
    bg_group_pal is the palette the same attribute bits would select from the BG half."""
    hoff = 0x40000 + y * 2048
    nspr = min((struct.unpack_from("<Q", rec, hoff)[0] >> 48) & 0xFF, 64)
    pal = line_pal(rec, y)
    out = []
    for i in range(nspr):
        qa, qb = struct.unpack_from("<QQ", rec, hoff + 640 + i * 16)
        if not (qa >> 54) & 1:
            continue
        attr, sx, lin = (qa >> 46) & 0xFF, (qa >> 38) & 0xFF, (qa >> 16) & 0x3FFFFF
        s = hdref.Rec.__new__(hdref.Rec)
        s.idx = hdref.chr_index(lin)
        q = 0x10 + 4 * (attr & 3)
        s.pal = pal[q + 3] | (pal[q + 2] << 8) | (pal[q + 1] << 16)
        b = 4 * (attr & 3)
        bgp = pal[b + 3] | (pal[b + 2] << 8) | (pal[b + 1] << 16)
        if not legacy:
            s.pal |= 0xFF000000
            bgp |= 0xFF000000
        s.fp = qb if game_ram else hdref.ZERO_FP
        out.append((sx, s, bgp))
    return out


def key(t, data):
    return t.fp if data else t.idx & 0xFFFFFFFFFFFFFFFF


class Frame:
    def __init__(self, h, recdir, name, game_ram):
        self.name = name
        self.rec = open(os.path.join(recdir, f"rec_{name}.bin"), "rb").read()
        self.watch = open(os.path.join(recdir, f"watch_{name}.bin"), "rb").read()
        self.ref = hdref.HdRef(h, self.rec, self.watch, game_ram)
        self.legacy = bool(h.flags & 1)
        self.game_ram = game_ram
        self.cands = {}

    def cond(self, data, tile, pal, pos, ignore=False):
        return {"data": data, "ignore": ignore, "q2": tile, "q3": (pos << 32) | (pal & 0xFFFFFFFF)}

    def candidates(self, kind, data):
        k = (kind, data)
        if k in self.cands:
            return self.cands[k]
        out = []
        scr = self.ref.screen
        for y in range(240):
            for x in range(256):
                p = scr[y * 256 + x]
                b0 = self.rec[y * 1024 + x * 4]
                if kind == "tile_pal" and p.tile.idx != hdref.NOTILE and (p.tile.fp is not None):
                    t = p.tile
                    c = self.cond(data, key(t, data), t.pal ^ 1, y * 256 + x)
                    ci = dict(c, ignore=True)
                    if not self.ref.tmatch(c, t) and self.ref.tmatch(ci, t):
                        out.append(c)
                elif kind == "tile_row" and y < 239 and p.tile.idx != hdref.NOTILE \
                        and p.tile.fp is not None and x % 8 == 3:
                    t = p.tile
                    c = self.cond(data, key(t, data), t.pal, y * 256 + x)
                    nxt = line_spans(self.rec, y + 1, self.game_ram, self.legacy)
                    slot = b0 & 63
                    bad = nxt[slot] if slot != 63 and slot < len(nxt) else None
                    if self.ref.tmatch(c, t) and (bad is None or not self.ref.tmatch(c, bad)):
                        out.append(c)
                elif kind == "spr_pal" and p.spr:
                    s = p.spr[0]
                    c = self.cond(data, key(s, data), s.pal ^ 1, y * 256 + x)
                    ci = dict(c, ignore=True)
                    if not any(self.ref.tmatch(c, r) for r in p.spr) and self.ref.tmatch(ci, s):
                        out.append(c)
                elif kind == "tile_fb" and p.tile.idx != hdref.NOTILE and x % 8 == 5:
                    t = p.tile
                    fb = self.ref.fallback(t.idx)
                    if fb >= 0 and fb != t.idx and not data:
                        c = self.cond(data, fb & 0xFFFFFFFFFFFFFFFF, t.pal, y * 256 + x)
                        if self.ref.tmatch(c, t):
                            out.append(c)
            if kind in ("spr_hidden", "spr_match"):
                spr = sprites_of(self.rec, y, self.game_ram, self.legacy)
                for x in range(0, 256, 3):
                    p = scr[y * 256 + x]
                    shown = self.rec[y * 1024 + x * 4] & 0x40
                    cov = [(s, bgp) for sx, s, bgp in spr if 0 <= x - sx <= 7][:4]
                    if not cov:
                        continue
                    s, bgp = cov[0]
                    if kind == "spr_hidden" and not shown and (s.fp is not None):
                        c = self.cond(data, key(s, data), s.pal, y * 256 + x)
                        if self.ref.tmatch(c, s):
                            out.append(c)
                    elif kind == "spr_match" and shown and p.spr and bgp != p.spr[0].pal:
                        r = p.spr[0]
                        c = self.cond(data, key(r, data), r.pal, y * 256 + x)
                        bug = []                          # the records the bug would build
                        for q, qbg in cov:
                            m = hdref.Rec.__new__(hdref.Rec)
                            m.idx, m.fp, m.pal = q.idx, q.fp, qbg
                            bug.append(m)
                        if self.ref.tmatch(c, r) and not any(self.ref.tmatch(c, m) for m in bug):
                            out.append(c)
            if kind == "spr_edge":
                row = [scr[y * 256 + x].spr for x in range(256)]
                for sx, _, _ in sprites_of(self.rec, y):
                    x = sx + 8
                    if x > 255 or not self.rec[y * 1024 + x * 4] & 0x40:
                        continue
                    src = [s for s in row[sx] if s.offx == 0]
                    if not src:
                        continue
                    s = src[0]
                    c = self.cond(data, key(s, data), s.pal, y * 256 + x)
                    if not any(self.ref.tmatch(c, r) for r in row[x]):
                        out.append(c)
        self.cands[k] = out
        return out


def main():
    if len(sys.argv) < 6:
        print(__doc__)
        return 2
    src, dst, recdir, gr, names = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4]), sys.argv[5:]
    per_role = 2
    while names and names[0].startswith("--"):
        if names[0] == "--per-role":
            per_role, names = int(names[1]), names[2:]
        else:
            sys.exit(f"unknown option {names[0]}")
    data = bytearray(open(src, "rb").read())
    h = hdref.Hdp3(bytes(data))
    gr = bool(gr)
    frames = [Frame(h, recdir, n, gr) for n in names]
    base = h.s(2)
    tile_roles = ["tile_pal", "tile_row"] + (["tile_fb"] if h.nfallback and not gr else [])
    roles = [(k, TILE_AT) for k in tile_roles] + \
        [(k, SPRITE_AT) for k in ("spr_pal", "spr_edge", "spr_hidden", "spr_match")]
    used, placed = set(), []          # placed: (role, ci, frame)
    for kind, newt in roles:
        got, k = 0, 0
        for f in frames:
            if got >= per_role:
                break
            cands = f.candidates(kind, gr)
            if not cands:
                continue
            seen, _ = fixture_pick.evaluated(data, f, gr)
            for ci in sorted(seen - used):
                if got >= per_role:
                    break
                o = base + 32 * ci
                q0 = struct.unpack_from("<Q", data, o)[0]
                if not (q0 >> 11) & 1 or (q0 >> 24) & 1 or (q0 & 0xFF) not in POOL_TYPES:
                    continue
                c = cands[(k * 7919) % len(cands)]
                k += 1
                trial = bytearray(data)
                nq0 = (q0 & ~0xFF & ~(1 << 9) & ~(1 << 10)) | newt | (int(gr) << 10)
                struct.pack_into("<Q", trial, o, nq0)
                struct.pack_into("<QQ", trial, o + 16, c["q2"] & 0xFFFFFFFFFFFFFFFF, c["q3"])
                if fixture_pick.visible(trial, f, gr, ci) and fixture_pick.all_reach(
                        trial, gr, [(c2, f2) for _, c2, f2 in placed]):
                    data = trial
                    used.add(ci)
                    placed.append((kind, ci, f))
                    got += 1
        ncand = sum(len(f.candidates(kind, gr)) for f in frames)
        print(f"  {kind}: {got} trap(s)" + ("" if got else
              f"   (no trap reached RESOLVE; {ncand} candidate positions on these frames)"),
              flush=True)
    # a later trap can change which conditions an earlier one's frame evaluates: check them all
    # again on the finished pack, and say which survived
    alive = {}
    for kind, ci, f in placed:
        seen, gold = fixture_pick.evaluated(data, f, gr)
        ok = ci in seen and fixture_pick.visible(data, f, gr, ci, gold)
        alive[kind] = alive.get(kind, 0) + int(ok)
        if not ok:
            print(f"  WARNING {kind} cond {ci} on {f.name} no longer reaches the output")
    if not placed:
        sys.exit("no trap reached RESOLVE on these frames")
    open(dst, "wb").write(data)
    print(f"{dst}: game_ram {int(gr)} legacy {int(bool(h.flags & 1))} fallback map {h.nfallback}; "
          + ", ".join(f"{k} {alive.get(k, 0)}" for k, _ in roles))
    return 0


if __name__ == "__main__":
    sys.exit(main())
