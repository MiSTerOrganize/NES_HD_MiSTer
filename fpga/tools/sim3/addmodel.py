"""8a additions model: compute every pixel's final sprite list WITHOUT Mesen's mutable walk, as
the hardware must - from an ordered list of contributions - and check it equals
hdref.process_additions exactly (record fields, list order, the 4-sprite cap, the pixel (0,0)
copy rule, the BG process_bg rule).

The model's assumptions are checked, not trusted: it refuses (exit 2) if an added sprite could
itself be a source (a chain), because the contribution order below would then be incomplete.

usage: python addmodel.py PACK.hdp RECDIR GAME_RAM FRAME [FRAME...]
       (FRAME = number; rec_FFFF.bin / watch_FFFF.bin in RECDIR)
exit 0 all equal, 1 a difference, 2 an assumption violated."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import hdref  # noqa: E402

FIELDS = hdref.Rec.__slots__
MUT = os.environ.get("ADDMODEL_MUT", "")   # order cap copy nobg nochain noign nofb
STATS = [] if os.environ.get("ADDMODEL_STATS") else None
STATS_RAW = []


def recsig(r):
    return tuple(getattr(r, k) for k in FIELDS if k != "inst")


def linef(p):
    """The line fields a pixel record carries (meaningful at x = 0; Pix.copy copies them)."""
    return (p.t, p.finex, p.gray, p.emph)


def scroll_y(t):
    return (((t & 0x3E0) >> 2) | ((t & 0x7000) >> 12)) + (240 if t & 0x800 else 0)


def model(ref):
    """Expected final screen (list of (tile_sig, [spr_sig...], t)) for ref's captured records."""
    sc = ref.screen                       # untouched capture (process_additions not run yet)
    adds = ref.additions
    n = 256 * 240
    # per pixel: captured sprite sigs, and a list of contributions (sort key, sig)
    contrib = [[] for _ in range(n)]
    added_keys = set()
    order = {id(a): i for i, a in enumerate(adds)}   # file order (identity, not equality)
    # the hardware's matcher: one table keyed by (palette or ANY, body) -> ascending indices,
    # looked up with the record's body and (CHR-ROM) its fallback body
    ANY = "any"
    table = {}
    for i, a in enumerate(adds):
        body = a["ofp"] if ref.game_ram else a["oidx"]
        table.setdefault((ANY if a["ignore"] else a["opal"], body), []).append(i)

    def matched(r):
        if ref.game_ram:
            if r.fp is None:
                return []
            bodies = [r.fp]
        else:
            if r.idx == hdref.NOTILE:
                return []
            bodies = [r.idx]
            if ref.has_fb and MUT != "nofb":
                f = ref.fallback(r.idx)
                if f is not None and f >= 0:
                    bodies.append(f)
        hit = set()
        for b in bodies:
            hit.update(table.get((r.pal, b), []))
            if MUT != "noign":
                hit.update(table.get((ANY, b), []))
        return [adds[i] for i in sorted(hit)]

    def emit(x, y, r, korder):
        lst = matched(r)
        if not MUT and [id(a) for a in lst] != [id(a) for a in ref.additions_for(r)]:
            raise AssertionError(f"table matcher != hdref for record pal {r.pal:#x} idx {r.idx}")
        for ai, a in enumerate(lst):
            tx = x + (-a["ox"] if r.hm else a["ox"])
            ty = y + (-a["oy"] if r.vm else a["oy"])
            if 0 <= tx < 256 and 0 <= ty < 240:
                c = r.copy()
                c.sci = 0
                c.idx, c.pal, c.fp = a["aidx"], a["apal"], a["afp"]
                added_keys.add((c.pal, c.idx, c.fp))
                # file order of the addition = its position in the full table
                contrib[(ty << 8) | tx].append(((y, x, korder, order[id(a)]), c))
        return len(lst) > 0

    first = sc[0]
    yscroll = scroll_y(first.t)
    tmpv = first.t
    process_bg = True
    for y in range(240):
        lf = sc[y << 8]
        if ((yscroll + y) & 7) == 0 or tmpv != lf.t:
            yscroll = scroll_y(lf.t)
            tmpv = lf.t
            process_bg = True
        scan_bg = process_bg and MUT != "nobg"
        process_bg = False
        for x in range(256):
            p = sc[(y << 8) | x]
            for k, s in enumerate(p.spr):
                emit(x, y, s, k)
            if scan_bg:
                if emit(x, y, p.tile, 99) and MUT != "nochain":
                    process_bg = True
    # chain check: an added record that would match an addition when scanned as a source
    for (pal, idx, fp) in added_keys:
        r = hdref.Rec.__new__(hdref.Rec)
        r.pal, r.idx, r.fp = pal, idx, fp
        if ref.additions_for(r) or matched(r):
            return None, "chain: an added sprite matches an addition (model order incomplete)"

    def final(pix_index, base):
        spr = [recsig(s) for s in base.spr]
        kf = (lambda kv: (kv[0][3], kv[0])) if MUT == "order" else (lambda kv: kv[0])
        for key, c in sorted(contrib[pix_index], key=kf):
            if len(spr) < 4 or MUT == "cap":
                spr.append(recsig(c))
        return spr

    out = [None] * n
    for i in range(1, n):
        out[i] = (recsig(sc[i].tile), final(i, sc[i]), linef(sc[i]))
    if STATS is not None:
        # accepted contributions only (the cap applied), grouped into RUNS the hardware would
        # store: consecutive target x, same source line, same source slot (k), same addition,
        # source offx stepping by one; cut at 8 pixels
        acc = {}
        raw = {}
        for i in range(n):
            room = 4 - len(sc[i].spr)
            cs = sorted(contrib[i], key=lambda kv: kv[0])
            for key, c in cs[:max(room, 0)]:
                acc.setdefault(i >> 8, []).append((i & 255, key, c))
            # what an order-blind generator must store: every contribution (it cannot know
            # which four come first until the line's runs are sorted)
            for key, c in cs:
                raw.setdefault(i >> 8, []).append((i & 255, key, c))

        def count_runs(groups):
            # a run: consecutive target x, same source line, slot and addition, source offx
            # stepping by one (so it never crosses an instance boundary)
            per_line = []
            for lst in groups.values():
                lst.sort(key=lambda e: (e[1][0], e[1][2], e[1][3], e[0]))
                runs = 0
                prev = None
                for tx, key, c in lst:
                    cont = (prev is not None and tx == prev[0] + 1 and key[0] == prev[1][0]
                            and key[2] == prev[1][2] and key[3] == prev[1][3]
                            and c.offx == prev[2].offx + 1)
                    if not cont:
                        runs += 1
                    prev = (tx, key, c)
                per_line.append(runs)
            return per_line

        runs_line = count_runs(acc)
        STATS_RAW.append(max(count_runs(raw), default=0))
        keys = {(c.pal, c.idx, c.fp) for lst in acc.values() for _, _, c in lst}
        tot = sum(len(v) for v in acc.values())
        STATS.append((tot, sum(runs_line), max(runs_line, default=0), len(keys),
                      max((len(v) for v in acc.values()), default=0)))
    # pixel (0,0): a copy of (0,239) taken at the START of line 239's scan, plus contributions
    # made INTO (0,0) during line 239's scan
    src = 239 << 8
    spr = [recsig(s) for s in sc[src].spr]
    for key, c in sorted(contrib[src], key=lambda kv: kv[0]):
        if key[0] < 239 and len(spr) < 4:
            spr.append(recsig(c))
    for key, c in sorted(contrib[0], key=lambda kv: kv[0]):
        if key[0] == 239 and len(spr) < 4:
            spr.append(recsig(c))
    if MUT != "copy":
        out[0] = (recsig(sc[src].tile), spr, linef(sc[src]))
    else:
        out[0] = (recsig(sc[0].tile), final(0, sc[0]), linef(sc[0]))
    return out, None


def main():
    pack, recdir, gr = sys.argv[1], sys.argv[2], int(sys.argv[3])
    h = hdref.Hdp3(open(pack, "rb").read())
    worst = 0
    for f in sys.argv[4:]:
        f = int(f)
        rec = open(os.path.join(recdir, f"rec_{f:04d}.bin"), "rb").read()
        watch = open(os.path.join(recdir, f"watch_{f:04d}.bin"), "rb").read()
        ref = hdref.HdRef(h, rec, watch, bool(gr))
        try:
            exp, err = model(ref)
        except AssertionError as e:
            exp, err = None, str(e)
        if err:
            print(f"frame {f}: {err}")
            return 2
        ref.process_additions()
        bad = 0
        for i, p in enumerate(ref.screen):
            got = (recsig(p.tile), [recsig(s) for s in p.spr], linef(p))
            if got != exp[i]:
                if bad < 5:
                    print(f"frame {f}: pixel ({i & 255},{i >> 8}) differs\n  ref {got}\n  mdl {exp[i]}")
                bad += 1
        print(f"frame {f}: {bad} pixels differ, {ref.stats['additions']} additions inserted")
        if STATS is not None:
            tot, runs, mx, nk, mxl = STATS.pop()
            print(f"  stats: {tot} accepted sprite-pixels, {runs} runs, max {mx} runs on a line "
                  f"(max {mxl} pixels on a line), {nk} distinct added keys; "
                  f"cap-blind generator: max {STATS_RAW.pop()} runs on a line")
        worst = max(worst, bad)
    return 1 if worst else 0


if __name__ == "__main__":
    sys.exit(main())
