"""Edge-case additions fixture for hd3_add (8a): edit ONE recorded frame and write addition
records so the frame exercises the rules no recorded frame reaches. Each edit is checked to be
present in the result; the hardware mutants that must fail on it are listed in neg_add_rtl.py.

Frame edits (a copy of rec/watch goes to OUTDIR; the original is untouched):
  rank5   four copies of a sprite fetch WITHOUT additions are inserted before a fetch S that has
          them, at the same x: S is the fifth covering sprite there, so it is not a source
          (Mesen keeps four sprites per pixel)
  hidden  the sprites-shown bit is cleared on the 8 pixels of another fetch of S: not a source
  palbg   inside one BG tile, pixels 4..7 are moved to a new capture slot holding the same tile
          and row under ANOTHER palette: two sources, not one run (one ignore-palette addition
          plus one for the first palette only, so a merged run is visible)
  split   on a line that does not start a tile row, the scroll register (t) changes and an
          8-pixel run of a BG tile K is placed there; the line above has no BG source, so only
          the scroll change makes the line scanned for BG sources (Mesen's process_bg rule)
Records (every other addition record is neutralised):
  S      -> added, offset (0, +16 or -16)          (rank5, hidden)
  T      -> ignore-palette, (0, +24 or -24); T under the first palette -> (0, +32 or -32) (palbg)
  K      -> (0, +8 or -8)                          (split)
  V      a vertically mirrored sprite fetch (one is mirrored if none is) -> (0, +8): the target
         is 8 lines ABOVE                          (vertical mirror)
  C      a sprite fetch near the left edge -> (-(x + 3), 0): the lane is clipped by 3 pixels
                                                   (left clip: start and first column)

usage: python make_add_edge.py IN.hdp RECDIR GAME_RAM FRAME OUTDIR OUT.hdp
(IN.hdp must have additions and NO tables - the tables are rebuilt by hdp3_addtab.patch)"""
import os
import shutil
import struct
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import hdref  # noqa: E402
import hdp3_addtab as at  # noqa: E402

REC = "<IIQIIQiiI20x"
NEVER = 0x7FFFFFF0


def hoff(y):
    return 0x40000 + y * 2048


def line_hdr(r, y):
    q0 = struct.unpack_from("<Q", r, hoff(y))[0]
    return q0, (q0 >> 32) & 0xFF, (q0 >> 48) & 0xFF


def set_counts(r, y, nspan=None, nspr=None):
    q0 = struct.unpack_from("<Q", r, hoff(y))[0]
    if nspan is not None:
        q0 = (q0 & ~(0xFF << 32)) | (nspan << 32)
    if nspr is not None:
        q0 = (q0 & ~(0xFF << 48)) | (nspr << 48)
    struct.pack_into("<Q", r, hoff(y), q0)


def sprites(r, y):
    """[(slot, qa, qb)] of the line's valid sprite fetches, in fetch order."""
    _, _, nspr = line_hdr(r, y)
    out = []
    for i in range(min(nspr, 64)):
        qa, qb = struct.unpack_from("<QQ", r, hoff(y) + 640 + 16 * i)
        if (qa >> 54) & 1:
            out.append((i, qa, qb))
    return out


def spr_key(qa, qb, pal, gr):
    lin = (qa >> 16) & 0x3FFFFF
    q = 0x10 + 4 * (((qa >> 46) & 0xFF) & 3)
    p = pal[q + 3] | (pal[q + 2] << 8) | (pal[q + 1] << 16) | 0xFF000000
    return (p, (1, qb) if gr else (0, hdref.chr_index(lin)))


def free_slot(r, y):
    """A capture slot on line y for a new span: a new one if the line has room, else one no
    pixel references (e.g. the prefetched tile that never reaches the screen); None if none."""
    _, nspan, _ = line_hdr(r, y)
    if nspan < 34:
        return nspan, nspan + 1
    used = {r[y * 1024 + x * 4] & 63 for x in range(256)}
    s = next((s for s in range(nspan) if s not in used), None)
    return (s, nspan) if s is not None else None


def line_pal(r, y):
    pbits = int.from_bytes(r[hoff(y) + 8:hoff(y) + 32], "little")
    return [(pbits >> (6 * n)) & 63 for n in range(32)]


def main():
    src, recdir, gr, frame, outdir, out = sys.argv[1:7]
    gr, frame = int(gr), int(frame)
    d = bytearray(open(src, "rb").read())
    h = hdref.Hdp3(bytes(d))
    if struct.unpack_from("<I", d, 0x80 + 16 * 8 + 4)[0]:
        sys.exit("IN.hdp already has addition tables; give the pack without them")
    rec = bytearray(open(os.path.join(recdir, f"rec_{frame:04d}.bin"), "rb").read())
    watch_p = os.path.join(recdir, f"watch_{frame:04d}.bin")
    watch = open(watch_p, "rb").read()
    if d[7] & 1:
        sys.exit("legacy pack: the sprite palette key differs; use a pack version >= 100")

    # ---- choose the sprite fetches ----
    by_key = {}                      # key -> [(y, slot, qa, qb)]
    for y in range(240):
        pal = line_pal(rec, y)
        for slot, qa, qb in sprites(rec, y):
            sx = (qa >> 38) & 0xFF
            if sx > 240:
                continue
            by_key.setdefault(spr_key(qa, qb, pal, gr), []).append((y, slot, qa, qb))
    keys = sorted(by_key, key=lambda k: len(by_key[k]))
    S = next((k for k in keys if len(by_key[k]) >= 2 and
              any(16 <= (e[2] >> 38) & 0xFF <= 230 for e in by_key[k])), None)
    if S is None:
        sys.exit("no sprite key with two fetches on this frame")
    F = next((k for k in keys if k != S and k[1] != S[1]), None)
    others = []
    for k in keys:
        if k[1] not in (S[1], F[1]) and k[1] not in [o[1] for o in others]:
            others.append(k)
    if len(others) < 2:
        sys.exit("not enough distinct sprite keys")
    V, C = others[0], others[1]

    # rank5: line of an S fetch with room for 4 more fetches
    used_lines = set()
    ya = None
    for y, slot, qa, qb in by_key[S]:
        if 16 <= (qa >> 38) & 0xFF <= 230 and line_hdr(rec, y)[2] + 4 <= 64 and 20 <= y <= 219:
            ya, sa, qa_s = y, slot, qa
            break
    if ya is None:
        sys.exit("no line for the rank-5 edit")
    fy, fslot, fqa, fqb = by_key[F][0]
    sx = (qa_s >> 38) & 0xFF
    # the copies must carry F's palette on line ya: same attr palette bits as on F's line works
    # only if the line palettes agree - so copy F's tile with S's attribute (same palette slot)
    # and only the tile bits of F (its key then = (S's palette, F's tile))
    attr_s = (qa_s >> 46) & 0xFF
    cq = (fqa & ~((0xFF << 46) | (0xFF << 38))) | (attr_s << 46) | (sx << 38) | (1 << 54)
    if spr_key(cq, fqb, line_pal(rec, ya), gr)[1] == S[1]:
        sys.exit("F has S's tile")
    n = line_hdr(rec, ya)[2]
    base = hoff(ya) + 640
    ents = [struct.unpack_from("<QQ", rec, base + 16 * i) for i in range(n)]
    ents = ents[:sa] + [(cq, fqb)] * 4 + ents[sa:]
    for i, (a, b) in enumerate(ents):
        struct.pack_into("<QQ", rec, base + 16 * i, a, b)
    set_counts(rec, ya, nspr=n + 4)
    used_lines.add(ya)

    # hidden: another S fetch, on another line
    yb = None
    for y, slot, qa, qb in by_key[S]:
        if y not in used_lines and 20 <= y <= 219 and (qa >> 38) & 0xFF <= 248:
            yb, sxb = y, (qa >> 38) & 0xFF
            break
    if yb is None:
        sys.exit("no second S fetch for the hidden edit")
    for x in range(sxb, min(sxb + 8, 256)):
        rec[yb * 1024 + x * 4] &= 0xBF
    used_lines.add(yb)

    # vertical mirror: a V fetch with vm, or set vm on one
    vy, vslot, vqa, vqb = next(((y, s, a, b) for y, s, a, b in by_key[V] if (a >> 46) & 0x80),
                               by_key[V][0])
    if not (vqa >> 46) & 0x80:
        vqa |= 0x80 << 46
        struct.pack_into("<Q", rec, hoff(vy) + 640 + 16 * vslot, vqa)
    if vy < 12:
        sys.exit("the V fetch is too high for a target 8 lines above")

    # left clip: a C fetch with x < 40
    cy, cslot, cqa, cqb = min(by_key[C], key=lambda e: (e[2] >> 38) & 0xFF)
    cx = (cqa >> 38) & 0xFF
    if cx > 200:
        sys.exit("no C fetch to clip")

    # ---- BG edits ----
    ref0 = hdref.HdRef(h, bytes(rec), open(watch_p, "rb").read(), bool(gr))
    sc = ref0.screen
    keyed = (lambda t: t.fp is not None) if gr else (lambda t: t.idx != hdref.NOTILE)

    def bgkey(t):
        return (t.pal, (1, t.fp) if gr else (0, t.idx & 0xFFFFFFFFFFFFFFFF))

    cnt = {}
    for p in sc:
        if keyed(p.tile):
            cnt[bgkey(p.tile)] = cnt.get(bgkey(p.tile), 0) + 1
    # palbg: a tile run x0..x0+7 (offx 0..7, one slot) on a line with a free span slot
    yc = x0 = None
    for y in range(24, 200):
        if y in used_lines:
            continue
        if free_slot(rec, y) is None:
            continue
        for x in range(8, 240):
            ps = [sc[(y << 8) | (x + i)] for i in range(8)]
            sl = {rec[y * 1024 + (x + i) * 4] & 63 for i in range(8)}
            if (len(sl) == 1 and keyed(ps[0].tile) and all(p.tile.offx == i for i, p in enumerate(ps))
                    and cnt[bgkey(ps[0].tile)] <= 64):
                yc, x0, slot_c = y, x, sl.pop()
                break
        if yc is not None:
            break
    if yc is None:
        free = sum(1 for y in range(24, 200) if free_slot(rec, y) is not None)
        sys.exit(f"no BG tile run for the palbg edit ({free} lines in 24..199 with a free span slot)")
    tq = sc[(yc << 8) | x0].tile
    T = bgkey(tq)
    ns, ncount = free_slot(rec, yc)
    qa, qb = struct.unpack_from("<QQ", rec, hoff(yc) + 64 + 16 * slot_c)
    pal_c = line_pal(rec, yc)
    psel = (qa >> 32) & 3
    alt = next((s for s in range(4) if s != psel and
                pal_c[4 * s + 1:4 * s + 4] != pal_c[4 * psel + 1:4 * psel + 4]), None)
    if alt is None:
        sys.exit("all BG palettes equal on the palbg line")
    struct.pack_into("<QQ", rec, hoff(yc) + 64 + 16 * ns, (qa & ~(3 << 32)) | (alt << 32), qb)
    set_counts(rec, yc, nspan=ncount)
    for x in range(x0 + 4, x0 + 8):
        b = rec[yc * 1024 + x * 4]
        rec[yc * 1024 + x * 4] = (b & 0xC0) | ns
    used_lines.add(yc)

    # split: line yd not starting a tile row; tile K placed on 8 pixels; line yd-1 must not
    # hold K (the only BG keys with additions are T and K)
    def scroll_y(t):
        return (((t & 0x3E0) >> 2) | ((t & 0x7000) >> 12)) + (240 if t & 0x800 else 0)
    Kt = None
    for k, c in sorted(cnt.items(), key=lambda kv: kv[1]):
        if k[1] != T[1] and c <= 64:
            Kt = k
            break
    if Kt is None:
        sys.exit("no K tile")
    kloc = next(i for i, p in enumerate(sc) if keyed(p.tile) and bgkey(p.tile) == Kt)
    ky = kloc >> 8
    kslot = rec[ky * 1024 + (kloc & 255) * 4] & 63
    kqa, kqb = struct.unpack_from("<QQ", rec, hoff(ky) + 64 + 16 * kslot)
    kpsel = (kqa >> 32) & 3

    # ---- records (written before the split line is chosen: that choice needs the lines
    # where some BG pixel matches an addition, fallback matches included) ----
    def toward(y, d):
        return d if 0 <= y + d < 240 else -d

    added = [(0xFF000000 | 0x111111, (1, 0xFFFFFFFFFFFFFF00 + j) if gr else (0, NEVER - 16 + j))
             for j in range(8)]
    recs = [
        (S[0], S[1], added[0], 0, toward(ya, 16), 0),
        (0, T[1], added[1], 0, toward(yc, 24), 1),
        (T[0], T[1], added[2], 0, toward(yc, 32), 0),
        (Kt[0], Kt[1], added[3], 0, 8, 0),          # the split line is chosen in 40..200
        (V[0], V[1], added[4], 0, 8, 0),
        (C[0], C[1], added[5], -(cx + 3), 0, 0),
    ]
    if h.nadd < len(recs):
        sys.exit(f"pack has only {h.nadd} addition records")
    sb = h.s(11)
    for i in range(h.nadd):
        if i < len(recs):
            opal, (ok, ob), (apal, (ak, ab)), ox, oy, ign = recs[i]
        else:
            opal, ok, ob, apal, ak, ab, ox, oy, ign = 0, 0, NEVER, 0, 0, NEVER + 1, 0, 0, 0
            if gr:
                ok, ob, ak, ab = 1, 0xFFFFFFFFFFFFFFF0, 1, 0xFFFFFFFFFFFFFFF1
        struct.pack_into(REC, d, sb + 64 * i, opal, ok, ob, apal, ak, ab, ox, oy, ign)
    ref1 = hdref.HdRef(hdref.Hdp3(bytes(d)), bytes(rec), watch, bool(gr))
    sc = ref1.screen

    yd = None
    ys = scroll_y(sc[0].t)
    tmpv = sc[0].t
    rows = {}
    for y in range(240):
        t = sc[y << 8].t
        if ((ys + y) & 7) == 0 or tmpv != t:
            ys, tmpv = scroll_y(t), t
        rows[y] = (ys + y) & 7
    k_lines = {i >> 8 for i, p in enumerate(sc) if keyed(p.tile) and ref1.additions_for(p.tile)}
    for y in range(40, 200):
        if (y in used_lines or rows[y] == 0 or (y - 1) in k_lines or y in k_lines
                or free_slot(rec, y) is None or line_pal(rec, y)[4 * kpsel + 1:4 * kpsel + 4]
                != line_pal(rec, ky)[4 * kpsel + 1:4 * kpsel + 4]):
            continue
        yd = y
        break
    if yd is None:
        sys.exit("no line for the split edit")
    q0 = line_hdr(rec, yd)[0]
    ns, ncount = free_slot(rec, yd)
    struct.pack_into("<QQ", rec, hoff(yd) + 64 + 16 * ns, kqa, kqb)
    set_counts(rec, yd, nspan=ncount)
    q0 = line_hdr(rec, yd)[0]
    xs = 100
    for i in range(8):
        o = yd * 1024 + (xs + i) * 4
        rec[o] = (rec[o] & 0xC0) | ns
        rec[o + 1] = (rec[o + 1] & ~(7 << 2)) | (i << 2)
    struct.pack_into("<Q", rec, hoff(yd), q0 ^ 1)          # t changes (coarse x bit 0)
    used_lines.add(yd)

    os.makedirs(outdir, exist_ok=True)
    open(os.path.join(outdir, f"rec_{frame:04d}.bin"), "wb").write(bytes(rec))
    shutil.copyfile(watch_p, os.path.join(outdir, f"watch_{frame:04d}.bin"))
    tmp = out + ".notab"
    open(tmp, "wb").write(bytes(d))
    at.patch(tmp, out)
    os.remove(tmp)
    print(f"{out}: rank5 line {ya} x {sx} (4 copies before the S fetch), hidden line {yb} x {sxb}, "
          f"palbg line {yc} x {x0}+4 (palette {psel}->{alt}), split line {yd} x {xs} "
          f"(row {rows[yd]}), vmirror line {vy}, clip line {cy} x {cx}")

    # the edits are visible to the reference: S is not in the 5th-sprite pixels' lists, the
    # hidden pixels have no sprites, and the model equals hdref on the edited frame
    ref = hdref.HdRef(hdref.Hdp3(open(out, "rb").read()), open(os.path.join(outdir, f"rec_{frame:04d}.bin"), "rb").read(),
                      open(watch_p, "rb").read(), bool(gr))
    # rank5: the four covering sprites are the copies (no additions); S is not among them
    p = ref.screen[(ya << 8) | (sx + 3)]
    if len(p.spr) != 4 or any(ref.additions_for(s) for s in p.spr):
        sys.exit("rank5 edit not as intended (a covering copy has additions, or not 4 sprites)")
    if ref.screen[(yb << 8) | sxb].spr:
        sys.exit("hidden edit: sprites still listed")
    pa, pb = ref.screen[(yc << 8) | x0].tile, ref.screen[(yc << 8) | (x0 + 4)].tile
    if pa.pal == pb.pal or len(ref.additions_for(pa)) != 2 or len(ref.additions_for(pb)) != 1:
        sys.exit("palbg edit: the two halves do not match different addition lists")
    if bgkey(ref.screen[(yd << 8) | xs].tile) != Kt or not ref.additions_for(ref.screen[(yd << 8) | xs].tile):
        sys.exit("split edit: K not placed")
    r = subprocess.run([sys.executable, "-I", os.path.join(HERE, "addmodel.py"), out, outdir, str(gr),
                        str(frame)], capture_output=True, text=True)
    print("  model:", (r.stdout.strip().splitlines() or [r.stderr[-300:]])[-1])
    if r.returncode != 0:
        sys.exit("model differs from hdref on the edge fixture")
    r = subprocess.run([sys.executable, "-I", os.path.join(HERE, "addhw.py"), out, outdir, str(gr),
                        str(frame)], capture_output=True, text=True)
    print("  lane model:", (r.stdout.strip().splitlines() or [r.stderr[-300:]])[-1])
    if r.returncode != 0:
        sys.exit("the lane model differs from hdref on the edge fixture")


if __name__ == "__main__":
    main()
