"""hwmodel.py - check the stage-3 hardware lookup algorithm against hdref, and measure it.

hdref.py looks tiles up the way Mesen does: per pixel, in raster order, walking a key's rule
list until the first rule whose conditions pass (spec 3.16), with the BG 8-pixel cache (3.17).
The hardware cannot afford a rule walk per pixel (5456 engine cycles per line, 256 pixels,
up to 4 sprite records each). What it can do is walk a rule list ONCE per tile instance:

  instance = the pixels of one line that share one capture entry and one key: a BG fetch group
             (up to 8 pixels), the visible slice of one sprite, or the pixels an <addition>
             copied from one source instance (cut into runs of at most 8)

and evaluate every condition for all of the instance's pixels at once, as an 8-bit mask:

  unresolved = all pixels
  for rule in the key's rule list, in file order:
      mask = unresolved AND (frame conditions pass ? all : none)
      for each walk condition: mask &= its per-pixel result (hmirror, vmirror, bgpriority,
                                originPosition and positionCheckY are the same for every
                                pixel; positionCheckX, tileNearby, spriteNearby are not)
      the pixels in mask take this rule; unresolved &= ~mask
      stop when unresolved is empty
  a pixel's disableCache = OR of ForceDisableCache over the rules up to its match

Every pixel gets the same answer as the per-pixel walk, provided conditions are pure. They
are, except for one Mesen side effect: a fallback hit REWRITES the looked-up record's
TileIndex (spec 3.16), in raster order, and later tile/sprite conditions that read that pixel
see the rewritten index. The model reproduces it the way the hardware would, from ORDER rather
than from Mesen's mutable state: a target record counts as rewritten when its key is
rewritable (exact key missing, fallback key found) and it was looked up before the
evaluation in progress - raster order; at one pixel the BG lookup first, then the
BG-priority sprites, then the front sprites, each from the last record to the first; BG
pixels looked up per the 8-pixel cache rule; sprites when drawn. Frame conditions are
evaluated as in RESOLVE, before any lookup. A key whose list holds a condition that a rewrite
can change (`sensitive`) is walked one pixel at a time, so a target inside the same instance
sees the earlier pixels' lookups. So a mismatch reported here is a bug in this algorithm.

usage:
  python hwmodel.py PACK.hdp RECDIR --frame F --rom game.nes [--lines]

Prints: mismatches (pixel, Mesen-order result, instance result), then the cost census per
line (instances, rules examined, frame-condition references, walk-condition evaluations,
nearby reads) as maximum and mean, and per frame.
"""
import argparse
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hdref  # noqa: E402
from hdref import NOTILE  # noqa: E402

WALK_PIXEL = {"positionCheckX", "tileNearby", "spriteNearby", "originPositionCheckX"}
NEARBY = {"tileNearby", "spriteNearby"}


class HwModel(hdref.HdRef):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.cap = None
        self.hwmemo = {}
        self.planned = -1
        self.hwres = {}
        self.mism = []
        self.checked = 0
        self.line_cost = []
        self.keys_frame = set()
        # fallback-rewrite tracking (see the module docstring)
        self.where = {}           # id(capture record) -> (x, y, "B" or sprite slot k)
        self.lk_bg = set()        # BG pixels looked up so far, by the BG 8-pixel cache rule
        self.cur = None           # (y, x, phase) of the lookup being evaluated; None = RESOLVE
        self.hw_mode = False
        self.sens_cache = {}
        self.ksens_cache = {}
        self.rw_cache = {}
        self.rewrites_seen = 0
        # stage-3 record dictionary (HDPACK_DESIGN.md "Stage-3 memory plan"): when on, every
        # key the frame uses gets its list filtered ONCE, before any lookup, and the walk
        # reads only that filtered list
        self.dict_mode = False
        self.filtered = {}        # rule-list offset -> [(rule, deferred frame conditions)]
        self.records = {}         # (pal, idx, fp) -> record id
        self.dict_stats = {}

    # ---- evaluation on the capture, with its own frame memo ------------------------------
    def hw_eval(self, ci, x, y, rec):
        s, m, st = self.screen, self.memo, self.stats["conds_evaluated"]
        self.screen, self.memo, self.hw_mode = self.cap, self.hwmemo, True
        try:
            return hdref.HdRef.eval_cond(self, ci, x, y, rec)
        finally:
            self.screen, self.memo, self.hw_mode = s, m, False
            self.stats["conds_evaluated"] = st

    # ---- Mesen's fallback rewrite, reproduced from lookup ORDER, not from Mesen's state --
    def rewritable(self, pal, idx):
        """GetMatchingTile rewrites a record (pal, idx): exact key missing, fallback found."""
        k = (pal, idx)
        v = self.rw_cache.get(k)
        if v is None:
            v = False
            if not self.game_ram and idx != NOTILE and self.fallback(idx) >= 0:
                r = hdref.Rec.__new__(hdref.Rec)
                r.idx, r.pal, r.fp = idx, pal, None
                if self.find(pal, r) is None:
                    r.idx = self.fallback(idx)
                    v = self.find(pal, r) is not None or self.find(0xFFFFFFFF, r) is not None
            self.rw_cache[k] = v
        return v

    @staticmethod
    def phase(p, k):
        """Mesen's order at one pixel: BG lookup (0), BG-priority sprites from the last record
        to the first, then front sprites the same way."""
        n = len(p.spr)
        return 1 + (n - 1 - k) if p.spr[k].bgp else 1 + n + (n - 1 - k)

    def looked_up(self, w):
        if self.cur is None:
            return False
        x, y, k = w
        # the record being looked up itself: Mesen rewrites it BEFORE walking its rules, so an
        # offset-0 nearby condition reading it sees the rewritten index (a pixel that is not
        # really looked up - a BG cache copy, a sprite hidden by a BG-priority one - has its
        # result discarded, so treating it as looked up changes nothing)
        if k == "B":
            if (y, x, 0) == self.cur:
                return True
            return (x, y) in self.lk_bg and (y, x, 0) < self.cur
        p = self.cap[(y << 8) | x]
        if (y, x, self.phase(p, k)) == self.cur:
            return True
        lowest = min((j for j, s in enumerate(p.spr) if s.bgp and s.sci), default=999)
        drawn = p.spr[k].bgp or lowest > k
        return drawn and (y, x, self.phase(p, k)) < self.cur

    def tmatch(self, c, t):
        if self.hw_mode and t is not None:
            w = self.where.get(id(t))
            if w is not None and self.rewritable(t.pal, t.idx) and self.looked_up(w):
                self.rewrites_seen += 1
                t2 = t.copy()
                t2.idx = self.fallback(t.idx)
                return super().tmatch(c, t2)
        return super().tmatch(c, t)

    def sensitive(self, ci):
        """Can a rewrite change this condition's result? (HDPACK_DESIGN.md, 'one walk per
        tile instance'). Only such conditions need the target's lookup order. This is the
        condition record's bit 24, as the hardware reads it: the converter sets it and
        hdp3_read re-derives it, so a model built on its own estimate could pass while the
        file the hardware gets is wrong."""
        v = self.sens_cache.get(ci)
        if v is None:
            v = bool(self.cond(ci)["sens"])
            self.sens_cache[ci] = v
        return v

    def key_sensitive(self, off):
        v = self.ksens_cache.get(off)
        if v is None:
            v = any(self.sensitive(ci) for rule in self.rules(off)
                    for ci in list(rule["fl"]) + list(rule["wl"]))
            self.ksens_cache[off] = v
        return v

    def resolve_key(self, r):
        """Key resolution of GetMatchingTile without mutating r. Returns rule-list offset."""
        off = self.find(r.pal, r)
        if off is None:
            f = self.fallback(r.idx) if not self.game_ram else -1
            if f >= 0:
                t = r.copy()
                t.idx = f
                off = self.find(r.pal, t)
                if off is None:
                    off = self.find(0xFFFFFFFF, t)
            if off is None:
                off = self.find(0xFFFFFFFF, r)
        return off

    def filter_list(self, off, r):
        """One rule list filtered by the frame conditions, as RESOLVE does it: keep the rules
        whose non-sensitive frame conditions pass, in order, each with its rewrite-sensitive
        frame conditions (tested later, at render); stop after the first kept rule with
        nothing left to test. Returns (kept [(rule, deferred conditions)], rules read,
        frame conditions evaluated). Also the golden for rtl/hdpack/hd3_resolve.sv
        (tools/sim3/resolve_golden.py)."""
        keep, reads, refs = [], 0, 0
        self.cur = None
        for rule in self.rules(off):
            reads += 1
            later, ok = [], True
            for ci in rule["fl"]:
                if self.cond(ci)["sens"]:
                    later.append(ci)
                    continue
                refs += 1
                if not self.hw_eval(ci, 0, 0, r):
                    ok = False
                    break
            if not ok:
                continue
            keep.append((rule, later))
            if not rule["wl"] and not later:
                break
        return keep, reads, refs

    def build_dict(self):
        """RESOLVE as the stage-3 plan describes it, on the whole frame's capture: give every
        distinct record (palette, tile, fingerprint) an id, resolve its key once (exact,
        fallback, default key), and filter each key's list by the frame conditions, keeping
        rules up to and including the first one with nothing left to test at render time.
        A frame condition flagged rewrite-sensitive is NOT evaluated here: Mesen memoises it at
        first use, so its answer can depend on lookups made earlier in the frame. It is kept
        with the rule and tested by the walk."""
        reads = refs = deferred = 0
        for p in self.cap:
            for r in [p.tile] + list(p.spr):
                # a record has a key exactly when find() can look it up: the fingerprint in a
                # CHR-RAM game, the tile index otherwise. An addition naming its target by
                # fingerprint has idx NOTILE and a valid fp (Castlevania, a CHR-RAM game), so
                # testing idx alone dropped it here while the walk still looked it up.
                if (r.fp is None) if self.game_ram else (r.idx == NOTILE):
                    continue
                k = (r.pal, r.idx, r.fp)
                if k in self.records:
                    continue
                self.records[k] = len(self.records)
                off = self.resolve_key(r)
                if off is None or off in self.filtered:
                    continue
                keep, n_reads, n_refs = self.filter_list(off, r)
                reads += n_reads
                refs += n_refs
                deferred += sum(len(later) for _, later in keep)
                self.filtered[off] = keep
        self.dict_stats = {"records": len(self.records), "keys": len(self.filtered),
                           "kept": sum(len(v) for v in self.filtered.values()),
                           "longest": max((len(v) for v in self.filtered.values()), default=0),
                           "rule_reads": reads, "frame_refs": refs, "deferred": deferred}

    def walk(self, y, px, recs, cost, pts, after=None):
        """px: pixel x list, recs: capture records (same key), pts: Mesen-order point of each
        pixel's lookup. Returns [(payload, dis)]. A key whose list holds a rewrite-sensitive
        condition is walked one pixel at a time, calling after(k, result) between pixels so
        the caller can record that pixel's lookup before the next one reads it."""
        n = len(px)
        off = self.resolve_key(recs[0])
        if off is not None and n > 1 and self.key_sensitive(off):
            cost["seq_inst"] += 1
            out = []
            for k in range(n):
                v = self.walk(y, [px[k]], [recs[k]], cost, [pts[k]])[0]
                out.append(v)
                if after:
                    after(k, v)
            return out
        res = [(None, False)] * n
        if off is None:
            if after:
                for k in range(n):
                    after(k, res[k])
            return res
        self.keys_frame.add(off)
        if self.dict_mode:
            entries = self.filtered[off]
        else:
            entries = [(rule, rule["fl"]) for rule in self.rules(off)]
        full = (1 << n) - 1
        unresolved = full
        pre = False
        for rule, fl in entries:
            cost["rules"] += 1
            # ForceDisableCache ORs over EVERY rule up to the match, filtered out or not; the
            # filtered list carries each kept rule's prefix flag, which is that OR
            pre = bool(rule["prefix"]) if self.dict_mode else (pre or bool(rule["fdc"]))
            mask = unresolved
            self.cur = None if not self.dict_mode else pts[0]
            for ci in fl:
                cost["frefs"] += 1
                if not self.hw_eval(ci, px[0], y, recs[0]):
                    mask = 0
                    break
            if mask:
                cost["srules"] += 1          # a rule a RESOLVE-filtered list still holds
                for ci in rule["wl"]:
                    c = self.cond(ci)
                    t = c["type"]
                    cost["wevals"] += 1
                    if t in NEARBY:
                        cost["nearby"] += 1
                        X, Y = hdref.i32(c["q1"]), hdref.i32(c["q1"] >> 32)
                        if X % 8 == 0 and Y % 8 == 0:
                            cost["nearby_grid"] += 1
                    m2 = 0
                    if t in WALK_PIXEL or (t == "originPositionCheckY"):
                        for k in range(n):
                            self.cur = pts[k]
                            if (mask >> k) & 1 and self.hw_eval(ci, px[k], y, recs[k]):
                                m2 |= 1 << k
                    else:
                        self.cur = pts[0]
                        if self.hw_eval(ci, px[0], y, recs[0]):
                            m2 = full
                    mask &= m2
                    if not mask:
                        break
            if mask:
                for k in range(n):
                    if (mask >> k) & 1:
                        res[k] = (rule["payload"], pre)
                unresolved &= ~mask
                if not unresolved:
                    break
        if self.dict_mode and unresolved:
            # no kept rule matched: Mesen walked the WHOLE list, so the flag is its last
            # rule's prefix, filtered-out rules included
            full_list = self.rules(off)
            pre = bool(full_list[-1]["prefix"]) if full_list else False
        for k in range(n):
            if (unresolved >> k) & 1:
                res[k] = (None, pre)
        if after:
            for k in range(n):
                after(k, res[k])
        return res

    # ---- one line: group into instances, walk each once ----------------------------------
    def plan_line(self, y):
        if self.cap is None:
            # the capture after additions (they are inserted into the record before drawing)
            self.cap = [p.copy() for p in self.screen]
            for i, p in enumerate(self.cap):
                xx, yy = i & 255, i >> 8
                self.where[id(p.tile)] = (xx, yy, "B")
                for k, s in enumerate(p.spr):
                    self.where[id(s)] = (xx, yy, k)
            if self.dict_mode:
                self.build_dict()
        cost = defaultdict(int)
        cap = self.cap
        first = cap[y << 8]
        scroll_x = ((first.t & 0x1F) << 3) | first.finex | (256 if first.t & 0x400 else 0)
        # BG: fetch groups, taken left to right
        groups = defaultdict(list)
        for x in range(256):
            r = cap[(y << 8) | x].tile
            if r.idx == NOTILE:
                continue
            groups[((scroll_x + x) >> 3, r.idx, r.pal, r.offy, r.fp)].append(x)
        # which BG pixels Mesen LOOKS UP (render(): the 8-pixel cache), kept in x order
        cache = {"use": False}

        def mark(x, v):
            if ((scroll_x + x) & 7) == 0:
                cache["use"] = False
            if not cache["use"]:
                self.lk_bg.add((x, y))
                if not v[1] and self.cache_enabled:
                    cache["use"] = True

        for gk, xs in groups.items():
            cost["bg_inst"] += 1
            recs = [cap[(y << 8) | x].tile for x in xs]
            pts = [(y, x, 0) for x in xs]
            res = self.walk(y, xs, recs, cost, pts, lambda k, v, xs=xs: mark(xs[k], v))
            for x, v in zip(xs, res):
                self.hwres[(x, y, "B")] = v
        # sprite records: per capture entry and key, cut into runs of <= 8 pixels
        sg = defaultdict(list)
        for x in range(256):
            for k, s in enumerate(cap[(y << 8) | x].spr):
                sg[(s.inst, s.pal, s.idx, s.fp, s.hm, s.vm, s.bgp)].append((x, k, s))
        for items in sg.values():
            runs, cur = [], []
            for it in items:
                if cur and (it[0] != cur[-1][0] + 1 or len(cur) == 8):
                    runs.append(cur)
                    cur = []
                cur.append(it)
            if cur:
                runs.append(cur)
            for run in runs:
                cost["spr_inst"] += 1
                xs = [it[0] for it in run]
                pts = [(y, x, self.phase(cap[(y << 8) | x], k)) for x, k, s in run]
                for (x, k, s), v in zip(run, self.walk(y, xs, [it[2] for it in run], cost, pts)):
                    self.hwres[(x, y, k)] = v
        self.line_cost.append((y, dict(cost)))
        self.planned = y

    # ---- hook: Mesen-order lookup (reference) vs the instance result ---------------------
    def get_matching(self, x, y, r):
        if self.planned != y:
            self.plan_line(y)
        p = self.screen[(y << 8) | x]
        if r is p.tile:
            key = (x, y, "B")
        else:
            key = next(((x, y, k) for k, s in enumerate(p.spr) if s is r), None)
        ref = super().get_matching(x, y, r)
        hw = self.hwres.get(key)
        self.checked += 1
        if hw is None or hw[0] != ref[0] or (key[2] == "B" and hw[1] != ref[1]):
            self.mism.append((key, ref, hw))
        return ref


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("hdp")
    ap.add_argument("recdir")
    ap.add_argument("--frame", type=int, required=True)
    ap.add_argument("--rom")
    ap.add_argument("--lines", action="store_true", help="print every line's cost")
    ap.add_argument("--dict", action="store_true",
                    help="walk per-frame filtered lists (the stage-3 record dictionary)")
    a = ap.parse_args()
    h = hdref.Hdp3(open(a.hdp, "rb").read())
    if h.flags & 0x20:
        game_ram = bool(h.flags & 0x10)
    elif a.rom:
        game_ram = hdref.rom_is_chr_ram(a.rom)
    else:
        sys.exit("pack does not say whether the game is CHR-RAM; give --rom")
    rec = open(os.path.join(a.recdir, f"rec_{a.frame:04d}.bin"), "rb").read()
    watch = open(os.path.join(a.recdir, f"watch_{a.frame:04d}.bin"), "rb").read()
    m = HwModel(h, rec, watch, game_ram)
    m.dict_mode = a.dict
    m.render()
    if a.dict:
        d = m.dict_stats
        print(f"   DICT       {d.get('records', 0)} records, {d.get('keys', 0)} keys; RESOLVE "
              f"read {d.get('rule_reads', 0)} rule records and {d.get('frame_refs', 0)} frame "
              f"condition references; kept {d.get('kept', 0)} (longest {d.get('longest', 0)}), "
              f"{d.get('deferred', 0)} rewrite-sensitive frame conditions deferred")
    print(f"frame {a.frame}: {m.checked} lookups checked, {len(m.mism)} differ, "
          f"fallback rewrites in the reference {m.stats['fallback_hits']}, rewritten targets "
          f"read by the model {m.rewrites_seen}, rewrite-sensitive conditions used "
          f"{sum(1 for v in m.sens_cache.values() if v)}")
    for key, ref, hw in m.mism[:12]:
        print(f"   pixel {key}: Mesen order {ref}, instance {hw}")
    names = ("bg_inst", "spr_inst", "seq_inst", "rules", "srules", "frefs", "wevals", "nearby",
             "nearby_grid")
    tot = {k: 0 for k in names}
    mx = {k: (0, -1) for k in names}
    for y, c in m.line_cost:
        for k in names:
            v = c.get(k, 0)
            tot[k] += v
            if v > mx[k][0]:
                mx[k] = (v, y)
        if a.lines:
            print(f"   line {y:3d}: " + " ".join(f"{k}={c.get(k, 0)}" for k in names))
    nl = max(1, len(m.line_cost))
    print("   per line   " + "  ".join(f"{k} max {mx[k][0]} (y{mx[k][1]}) mean {tot[k] / nl:.1f}"
                                      for k in names))
    print(f"   per frame  rules {tot['rules']}, walk evals {tot['wevals']}, nearby reads "
          f"{tot['nearby']}, distinct keys {len(m.keys_frame)}, distinct frame conditions "
          f"evaluated {len(m.hwmemo)}")
    # RESOLVE alternative (design "Rule selection at run time"): each key used this frame has
    # its list filtered by the frame class ONCE, keeping passing rules up to and including the
    # first one with no walk conditions; instances then walk only that short list.
    r_rules = r_frefs = longest = 0
    short = {}
    m.cur = None
    for off in m.keys_frame:
        keep = []
        for rule in m.rules(off):
            r_rules += 1
            ok = True
            for ci in rule["fl"]:
                r_frefs += 1
                if not m.hw_eval(ci, 0, 0, None):
                    ok = False
                    break
            if ok:
                keep.append(rule)
                if not rule["wl"]:
                    break
        short[off] = len(keep)
        longest = max(longest, len(keep))
    print(f"   RESOLVE    {len(m.keys_frame)} keys: {r_rules} rule records read, {r_frefs} frame "
          f"condition references; longest filtered list {longest}, "
          f"mean {sum(short.values()) / max(1, len(short)):.1f}, kept in total "
          f"{sum(short.values())}")
    # sizes for per-frame on-chip dictionaries: distinct (palette, tile) records and distinct
    # tile indices on screen (BG spans and sprite records, additions included)
    recs, tiles = set(), set()
    for p in (m.cap if m.cap is not None else m.screen):   # no lookup this frame: no copy made
        for r in [p.tile] + list(p.spr):
            if r.idx != NOTILE:
                recs.add((r.pal, r.idx))
                tiles.add(r.idx)
    wconds = {ci for off in m.keys_frame for rule in m.rules(off) for ci in rule["wl"]}
    print(f"   DICTS      distinct (palette, tile) records {len(recs)}, distinct tiles "
          f"{len(tiles)}, walk conditions reachable from the frame's keys {len(wconds)}")
    return 1 if m.mism else 0


if __name__ == "__main__":
    sys.exit(main())
