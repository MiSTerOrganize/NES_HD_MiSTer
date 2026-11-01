"""Fixture for the BG 8-pixel lookup cache's ForceDisableCache flag (the rule "prefix" bit).

Mesen caches a BG lookup across the rest of its aligned 8-pixel group unless the match's
disableCache is set, and disableCache ORs ForceDisableCache over EVERY rule walked up to the
match - rules a frame condition filters out included. RESOLVE drops those rules, so each kept
rule carries the OR as its prefix bit (HDPACK_DESIGN.md, hd3_resolve). The cache never changes a
lookup's RESULT (an aligned group is one tile); it changes WHICH pixels are looked up, and that
is visible only through fallback rewrites: a lookup that falls back rewrites the record's tile
index, and a rewrite-sensitive tile condition read later sees the rewritten index.

No recorded frame makes a fallback rewrite (Metroid's frames: 0), so the negative control's
"prefix ignores filtered-out rules" mutant was caught on no frame. This builds the case:
  1. G: a BG group (>= 2 pixels) of record R = (pal, idx) whose FALLBACK list matches R's pixels
     through a rule with prefix 1 and ForceDisableCache 0 (so only the prefix disables the
     cache). R's exact key is removed (its palette word changed to an unused value, which keeps
     every probe chain intact), so R's lookups now fall back and rewrite.
  2. P: the first pixel of a later BG group on the same line whose matching rule r has walk
     conditions and a different next result. r's first walk condition (a walk-class condition,
     in no frame list anywhere) becomes tileNearby(skipped - P, 0, idx, pal), flagged
     rewrite-sensitive, ForceDisableCache set on r and the prefix bits of r and the rules after
     it ORed, as the converter would write them.
  Correct: every pixel of G is looked up and rewritten, the trap reads idx' != idx -> false ->
  the next result. Mutant (prefix = the rule's own flag): G caches after its first pixel, the
  last pixel is never rewritten, the trap reads idx -> true -> r's payload.
A candidate is kept only if hwmodel --dict matches the reference with 0 differences and the
mutant differs (both measured, not argued).

usage: python -I make_prefix_frame.py <in.hdp> <out.hdp> <recdir> <frame> [--max N]
"""
import os
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import hdref  # noqa: E402
import hwmodel  # noqa: E402
from hdp3_read import Hdp3, TYPES, crc32  # noqa: E402
from hdref import NOTILE  # noqa: E402

TILE_NEARBY = TYPES.index("tileNearby")
WALK_TYPES = {TYPES.index(t) for t in ("tileNearby", "spriteNearby", "positionCheckX",
                                       "positionCheckY", "originPositionCheckX",
                                       "originPositionCheckY", "hmirror", "vmirror",
                                       "bgpriority")}


def key_entry(h, pal, lo, hi):
    """Byte offset of the key-table entry (pal, CHR-ROM tile lo/hi), or None."""
    b0 = crc32(struct.pack("<III", pal, lo, hi)) & (h.nbuckets - 1)
    for probe in range(h.max_probe + 1):
        b = h.s(0) + ((b0 + probe) & (h.nbuckets - 1)) * 64
        for j in range(4):
            e = b + j * 16
            q0, q1 = struct.unpack_from("<QQ", h.d, e)
            if not q1 >> 63:
                return None
            if ((q0 & 0xFFFFFFFF) == pal and q0 >> 32 == lo and (q1 & 0xFFFFFFFF) == hi
                    and not (q1 >> 62) & 1):
                return e
    return None


def free_slot(h, pal, lo, buf=None):
    """Byte offset of the first empty slot on key (pal, lo, 0)'s probe sequence within the
    header's max_probe, or None. A key stored there is found by find_key, and no existing
    key moves: an empty slot already ends every probe sequence that reaches it. buf: the
    bytes being modified, so a second insertion cannot reuse the first one's slot."""
    d = h.d if buf is None else buf
    b0 = crc32(struct.pack("<III", pal, lo, 0)) & (h.nbuckets - 1)
    for probe in range(h.max_probe + 1):
        b = h.s(0) + ((b0 + probe) & (h.nbuckets - 1)) * 64
        for j in range(4):
            e = b + j * 16
            if not struct.unpack_from("<Q", d, e + 8)[0] >> 63:
                return e
    return None


def insert_key(h, out, pal, lo, off):
    e = free_slot(h, pal & 0xFFFFFFFF, lo & 0xFFFFFFFF, out)
    struct.pack_into("<QQ", out, e, (pal & 0xFFFFFFFF) | ((lo & 0xFFFFFFFF) << 32),
                     ((off // 8) << 32) | (1 << 63))


def all_lists(h):
    """Every rule-list offset in section 1: key lists and background lists."""
    seen = set()
    for b in range(h.nbuckets):
        base = h.s(0) + b * 64
        for j in range(4):
            q0, q1 = struct.unpack_from("<QQ", h.d, base + j * 16)
            if q1 >> 63:
                seen.add(((q1 >> 32) & 0x3FFFFFFF) * 8)
    for lvl in range(40):
        off, n = h.bg_level(lvl)
        if n:
            seen.add(off)
    return seen


def cond_users(h):
    """cond index -> set of ('frame'|'walk') roles it appears in, over every rule."""
    roles = {}
    for off in all_lists(h):
        for r in h.rules(off):
            for role, cl in (("frame", r["frame"]), ("walk", r["walk"])):
                for ci in h.clist(cl):
                    roles.setdefault(ci, set()).add(role)
    return roles


def rule_addr(h, off, i):
    return h.s(1) + off + 8 + 16 * i


def model_diff(data, fr, mutate):
    h = Hdp3(bytes(data))
    m = hwmodel.HwModel(h, fr[0], fr[1], False)
    m.dict_mode = True
    if mutate:
        orig = m.build_dict

        def bd():
            orig()
            for off, v in m.filtered.items():
                m.filtered[off] = [(dict(rule, prefix=rule["fdc"]), fl) for rule, fl in v]
        m.build_dict = bd
    m.render()
    return len(m.mism)


def matched(r, off, x, y, rec):
    """(index of the first rule of list off passing at (x, y) for rec, prefix, fdc) or None."""
    for i, rule in enumerate(r.rules(off)):
        if r.passes(rule, x, y, rec):
            return i, bool(rule["prefix"]), bool(rule["fdc"])
    return None


REJECT = {}


def rej(why):
    REJECT[why] = REJECT.get(why, 0) + 1


def candidates(data, fr):
    h = Hdp3(bytes(data))
    r = hdref.HdRef(h, fr[0], fr[1], False)
    r.select_backgrounds()
    r.process_additions()
    scr = r.screen
    # every distinct key list with 2+ rules - candidates to host the trap through a new key
    keyl = set()
    for b in range(h.nbuckets):
        base = h.s(0) + b * 64
        for j in range(4):
            q0, q1 = struct.unpack_from("<QQ", h.d, base + j * 16)
            if q1 >> 63:
                keyl.add(((q1 >> 32) & 0x3FFFFFFF) * 8)
    multi = sorted(off for off in keyl if len(h.rules(off)) >= 2)[:600]
    tried = set()
    print(f"  rule lists with 2+ rules: {len(multi)}", flush=True)
    # only lines/columns render() actually looks up (the pack's overscan)
    top, right, bottom, left = [max(0, v) for v in h.overscan]
    print(f"  overscan top {top} right {right} bottom {bottom} left {left}", flush=True)
    for y in range(top, 240 - bottom):
        first = scr[y << 8]
        sx = ((first.t & 0x1F) << 3) | first.finex | (256 if first.t & 0x400 else 0)
        groups = {}
        for x in range(left, 256 - right):
            t = scr[(y << 8) | x].tile
            if t.idx == NOTILE:
                continue
            groups.setdefault(((sx + x) >> 3, t.idx, t.pal), []).append(x)
        order = sorted(groups.items(), key=lambda kv: kv[1][0])
        for gi, ((_, idx, pal), xs) in enumerate(order):
            if len(xs) < 2:
                rej("group < 2 pixels")
                continue
            if not (0 <= idx < len(r.fb)):
                rej("tile outside the fallback map")
                continue
            if (idx, pal) in tried:
                rej("tile/palette already tried")
                continue
            tried.add((idx, pal))
            # the group's own key must miss (exact AND default) so the lookup reaches the
            # fallback; a tile with an exact key gets it removed by plant()
            natural = key_entry(h, pal, idx & 0xFFFFFFFF, 0) is None
            if r.find(0xFFFFFFFF, scr[(y << 8) | xs[0]].tile) is not None:
                rej("default key catches it before the fallback")
                continue
            # retarget fallback(idx) to a keyed tile f whose list matches both ends of the group
            # at the SAME rule k > 0, own ForceDisableCache 0, with an earlier rule j that
            # matches at neither end. plant() sets j's ForceDisableCache and recomputes the
            # prefix bits, so k's prefix becomes 1 from a rule the walk does not stop at.
            pick = None
            # f: a tile on no key for this palette (a new key (pal, f) is inserted pointing at
            # an existing multi-rule list), whose own fallback does not lead back to idx
            f = next((t for t in range(idx + 1, idx + 4096)
                      if key_entry(h, pal, t & 0xFFFFFFFF, 0) is None
                      and r.fallback(t) != idx and free_slot(h, pal, t) is not None), None)
            cands = [(f, off) for off in multi] if f is not None else []
            if not cands:
                rej("  sub: no free key slot for a new fallback tile")
            stage = 0
            for f, fo in cands:
                rl = r.rules(fo)
                ends = []
                for x in (xs[0], xs[-1]):
                    rr = scr[(y << 8) | x].tile.copy()
                    rr.idx = f
                    ends.append((x, rr, matched(r, fo, x, y, rr)))
                ks = {e[2][0] if e[2] else None for e in ends}
                if len(ks) != 1 or None in ks:
                    continue
                stage = max(stage, 1)
                k = ks.pop()
                if k == 0 or rl[k]["fdc"]:
                    continue
                stage = max(stage, 2)
                j = next((i for i in range(k)
                          if not any(r.passes(rl[i], x, y, rr) for x, rr, _ in ends)), None)
                if j is None:
                    continue
                pick = (f, fo, j)
                break
            if pick is None:
                rej(["  sub: no list matches both ends at one rule",
                     "  sub: matches only at rule 0 (or matched rule has its own FDC)",
                     "  sub: no earlier rule misses at both ends"][stage]
                    if cands else "no keyed tile whose list can host the trap")
                continue
            f, fo, jrule = pick
            skipped = xs[-1]
            sites = 0
            why2 = "trap: no later aligned group on the line"
            for (_, idx2, pal2), xs2 in order[gi + 1:]:
                xp = xs2[0]
                if xp <= skipped or ((sx + xp) & 7) != 0 or idx2 == idx:
                    continue
                recp = scr[(y << 8) | xp].tile
                ins2 = None
                po = r.find(pal2, recp)
                if po is None:
                    po = r.find(0xFFFFFFFF, recp)
                if po is None and r.fallback(idx2) < 0 and 0 <= idx2:
                    # no key: insert (pal2, idx2) -> a list that matches at xp
                    po = next((o for o in multi if o != fo
                               and matched(r, o, xp, y, recp) is not None), None)
                    if po is not None:
                        if free_slot(h, pal2 & 0xFFFFFFFF, idx2 & 0xFFFFFFFF) is None:
                            po = None
                        else:
                            ins2 = (pal2, idx2)
                if po is None or po == fo:
                    why2 = "trap: later group has no key and none could be added"
                    continue
                mt = matched(r, po, xp, y, recp)
                if mt is None:
                    why2 = "trap: later group's list matches nothing"
                    continue
                k = mt[0]
                # if the planted condition fails the lookup falls through to rule k+1 or to
                # "no replacement" - either way a different result, measured below
                sites += 1
                yield {"y": y, "xs": xs, "idx": idx, "pal": pal, "f": f, "skipped": skipped,
                       "xp": xp, "po": po, "k": k, "natural": natural, "fo": fo, "j": jrule, "ins2": ins2}
            if not sites:
                rej(why2)


def set_fdc(h, out, off, j):
    """Set ForceDisableCache on rule j of list off and recompute the list's prefix bits."""
    pre = 0
    for i in range(len(h.rules(off))):
        ra = rule_addr(h, off, i)
        w3 = struct.unpack_from("<I", out, ra + 12)[0]
        fdc = ((w3 >> 24) & 1) | (1 if i == j else 0)
        pre |= fdc
        struct.pack_into("<I", out, ra + 12, (w3 & 0xFCFFFFFF) | (fdc << 24) | (pre << 25))


def plant(data, c, spare):
    h = Hdp3(bytes(data))
    out = bytearray(data)
    struct.pack_into("<i", out, h.s(10) + 4 * c["idx"], c["f"])
    insert_key(h, out, c["pal"], c["f"], c["fo"])
    if c["ins2"]:
        if free_slot(h, c["ins2"][0] & 0xFFFFFFFF, c["ins2"][1] & 0xFFFFFFFF, out) is None:
            return None
        insert_key(h, out, c["ins2"][0], c["ins2"][1], c["po"])
    set_fdc(h, out, c["fo"], c["j"])
    if not c["natural"]:
        e = key_entry(h, c["pal"], c["idx"] & 0xFFFFFFFF, 0)
        q0 = struct.unpack_from("<Q", out, e)[0]
        struct.pack_into("<Q", out, e, (q0 & ~0xFFFFFFFF) | 0x7E000000 | (c["pal"] & 0xFFFFFF))
    rules = h.rules(c["po"])
    # rule k's walk list becomes a borrowed single-condition list whose condition is used
    # only as a walk condition; that condition becomes the trap
    spare_off, ci = spare
    struct.pack_into("<I", out, rule_addr(h, c["po"], c["k"]) + 8, spare_off)
    a = h.s(2) + 32 * ci
    q0 = struct.unpack_from("<Q", out, a)[0]
    X = (c["skipped"] - c["xp"]) & 0xFFFFFFFF
    nq0 = TILE_NEARBY | (0xFF << 16) | (1 << 24) | (q0 & 0xFFFFFFFF00000000)
    struct.pack_into("<QQQQ", out, a, nq0, X, c["idx"] & 0xFFFFFFFFFFFFFFFF, c["pal"] & 0xFFFFFFFF)
    # ForceDisableCache on r (tileNearby off the 8-pixel grid) and the prefix OR after it
    pre = 0
    for i, rule in enumerate(rules):
        ra = rule_addr(h, c["po"], i)
        w3 = struct.unpack_from("<I", out, ra + 12)[0]
        fdc = (w3 >> 24) & 1
        if i == c["k"]:
            fdc = 1
        pre |= fdc
        w3 = (w3 & 0xF8FFFFFF) | (fdc << 24) | (pre << 25)
        struct.pack_into("<I", out, ra + 12, w3)
    return out


def main():
    if len(sys.argv) < 5:
        print(__doc__)
        return 2
    src, dst, recdir, name = sys.argv[1:5]
    mx = int(sys.argv[sys.argv.index("--max") + 1]) if "--max" in sys.argv else 40
    data = bytearray(open(src, "rb").read())
    fr = (open(os.path.join(recdir, f"rec_{name}.bin"), "rb").read(),
          open(os.path.join(recdir, f"watch_{name}.bin"), "rb").read())
    if model_diff(data, fr, None):
        sys.exit("the input pack already differs from the reference on this frame")
    hh = Hdp3(bytes(data))
    roles = cond_users(hh)
    spares = []
    for off in all_lists(hh):
        for rl in hh.rules(off):
            if rl["walk"]:
                cl = hh.clist(rl["walk"])
                if len(cl) == 1 and roles.get(cl[0], set()) == {"walk"}:
                    spares.append((rl["walk"], cl[0]))
    if not spares:
        sys.exit("no single-condition walk list to borrow for the trap")
    print(f"  borrowable walk lists: {len(set(spares))}", flush=True)
    tried = 0
    for c in candidates(data, fr):
        out = plant(data, c, spares[0])
        if out is None:
            continue
        tried += 1
        good = model_diff(out, fr, None)
        bad = model_diff(out, fr, True) if good == 0 else 0
        print(f"  line {c['y']} group x {c['xs'][0]}..{c['xs'][-1]} tile {c['idx']}->{c['f']}"
              f" read from x {c['xp']}: unmutated {good}, mutant {bad}", flush=True)
        if good == 0 and bad > 0:
            open(dst, "wb").write(out)
            Hdp3(bytes(out))
            how = ("tile already had no key" if c["natural"]
                   else "its exact key removed")
            add = (f", key added for tile {c['ins2'][1]}" if c["ins2"] else "")
            print(f"{dst}: trap at line {c['y']}: tile {c['idx']} pal {c['pal']:08x} ({how}) "
                  f"falls back to tile {c['f']} -> list {c['fo']} rule {c['j']} given "
                  f"ForceDisableCache{add}; condition read at x {c['xp']}; "
                  f"unmutated 0, mutant {bad} differences")
            return 0
        if tried >= mx:
            break
    print(f"no visible trap after {tried} candidates; rejections: "
          + ", ".join(f"{k} {v}" for k, v in sorted(REJECT.items(), key=lambda kv: -kv[1])))
    return 1


if __name__ == "__main__":
    sys.exit(main())
