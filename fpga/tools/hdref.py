"""hdref.py - software reference renderer for the NES HD pack core (stage 3).

Renders one NES frame the way Mesen 2 does (MESEN_HD_RUNTIME_SPEC.md), from the same inputs
the hardware has: the format-3 pack (.hdp), the stage-2 frame record (rec_FFFF.bin) and the
watched-address snapshot (watch_FFFF.bin) that fullsim saves. Output is at 2x (512x480 before
overscan), the scale the hardware renders at; the .hdp blocks are already 16x16 per 8x8 tile.

It follows Mesen's order of work, including the parts that make results order-dependent:
  - backgrounds are chosen before additions are inserted (their conditions see the record
    without the added sprites);
  - additions are inserted before any pixel is drawn, with the pixel (0,0) copy bug (6.1);
  - frame-class conditions are evaluated at their first use and cached for the frame;
  - a fallback hit rewrites the record's TileIndex (3.16), which later conditions see;
  - the BG 8-pixel cache (3.17);
  - backdrop / backgrounds / sprites / BG tile layer order and lowestBgSprite (4.3);
  - grayscale and emphasis per scanline from x = 0 (5.2).

Known approximations (stated, not hidden):
  - a condition list is evaluated frame-class list first, then walk-class list; Mesen
    evaluates the pack's original order. Only differs if a frame-class condition's FIRST
    evaluation would move to a point after a fallback rewrite. The hardware does the same.
  - records Mesen leaves stale (NoTile BG fields, CHR-RAM tile data of a NoTile pixel) never
    match a tile condition or an addition here.
  - packs with scale other than 1 or 2 are drawn from the converter's area-resampled blocks.

usage:
  python hdref.py PACK.hdp RECDIR --frame F [--rom game.nes] [--out out.png]
  python hdref.py --sd-check RECDIR --frame F --rom game.nes     (no pack: the composited
        SD pixel must equal the PPU's output colour, col_FFFF.bin - checks record parsing)
"""
import argparse
import os
import struct
import sys
import zlib

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hdp3_read import Hdp3  # noqa: E402
from hdp3_convert import crc64  # noqa: E402

# Mesen 2.1.1 NesDefaultVideoFilter.cpp _ppuPaletteArgb[2C02], used when the pack has no
# palette.dat (the HD renderer uses the configured 2C02 palette, PACK:296).
MESEN_2C02 = [
    0x666666, 0x002A88, 0x1412A7, 0x3B00A4, 0x5C007E, 0x6E0040, 0x6C0600, 0x561D00,
    0x333500, 0x0B4800, 0x005200, 0x004F08, 0x00404D, 0x000000, 0x000000, 0x000000,
    0xADADAD, 0x155FD9, 0x4240FF, 0x7527FE, 0xA01ACC, 0xB71E7B, 0xB53120, 0x994E00,
    0x6B6D00, 0x388700, 0x0C9300, 0x008F32, 0x007C8D, 0x000000, 0x000000, 0x000000,
    0xFFFEFF, 0x64B0FF, 0x9290FF, 0xC676FF, 0xF36AFF, 0xFE6ECC, 0xFE8170, 0xEA9E22,
    0xBCBE00, 0x88D800, 0x5CE430, 0x45E082, 0x48CDDE, 0x4F4F4F, 0x000000, 0x000000,
    0xFFFEFF, 0xC0DFFF, 0xD3D2FF, 0xE8C8FF, 0xFBC2FF, 0xFEC4EA, 0xFECCC5, 0xF7D8A5,
    0xE4E594, 0xCFEF96, 0xBDF4AB, 0xB3F3CC, 0xB5EBF2, 0xB8B8B8, 0x000000, 0x000000,
]

ZERO_FP = crc64(bytes(16))
NOTILE = -1
OPS = {"eq": lambda a, b: a == b, "ne": lambda a, b: a != b, "gt": lambda a, b: a > b,
       "lt": lambda a, b: a < b, "le": lambda a, b: a <= b, "ge": lambda a, b: a >= b}


def i32(v):
    v &= 0xFFFFFFFF
    return v - (1 << 32) if v & 0x80000000 else v


def i64(v):
    v &= 0xFFFFFFFFFFFFFFFF
    return v - (1 << 64) if v & (1 << 63) else v


# --------------------------------------------------------------------------------------------
# Frame record -> Mesen's per-pixel records
# --------------------------------------------------------------------------------------------
class Rec:
    """HdPpuTileInfo. fp = fingerprint of TileData (None = stale / unknown).
    inst = which capture entry made it (sprite table index, -1 for BG); not a Mesen field,
    used only by tools/hwmodel.py to group a sprite's pixels into one instance."""
    __slots__ = ("idx", "pal", "fp", "offx", "offy", "hm", "vm", "bgp", "sci", "scolor",
                 "bgci", "bgcolor", "ppubg", "poff", "inst")

    def copy(self):
        r = Rec.__new__(Rec)
        for k in Rec.__slots__:
            setattr(r, k, getattr(self, k))
        return r


class Pix:
    """HdPpuPixelInfo. Line fields (t, finex, gray, emph) are meaningful at x = 0."""
    __slots__ = ("tile", "spr", "t", "finex", "gray", "emph")

    def copy(self):
        p = Pix.__new__(Pix)
        p.tile = self.tile.copy()
        p.spr = [s.copy() for s in self.spr]
        p.t, p.finex, p.gray, p.emph = self.t, self.finex, self.gray, self.emph
        return p


def chr_index(lin):
    """Mesen TileIndex = absolute offset within the mapped region / 16 (spec 1.3)."""
    return (lin & 0xFFFFF) >> 4


def build_records(rec, game_ram, legacy):
    """Turn the stage-2 frame record into a 256x240 list of Pix, as Mesen would hold them."""
    screen = [None] * (256 * 240)
    for y in range(240):
        hoff = 0x40000 + y * 2048
        q0 = struct.unpack_from("<Q", rec, hoff)[0]
        t = q0 & 0x7FFF
        finex = (q0 >> 15) & 7
        gray = (q0 >> 18) & 1
        emph = (q0 >> 19) & 7
        nspan = min((q0 >> 32) & 0xFF, 34)
        nspr = min((q0 >> 48) & 0xFF, 64)
        pbits = int.from_bytes(rec[hoff + 8:hoff + 32], "little")
        pal = [(pbits >> (6 * n)) & 63 for n in range(32)]
        spans = []
        for s in range(nspan):
            qa, qb = struct.unpack_from("<QQ", rec, hoff + 64 + s * 16)
            spans.append((qa & 0x3FFFFF, (qa >> 32) & 3, qb))
        sprites = []
        for i in range(nspr):
            qa, qb = struct.unpack_from("<QQ", rec, hoff + 640 + i * 16)
            if not (qa >> 54) & 1:
                continue
            sprites.append(((qa >> 46) & 0xFF, (qa >> 38) & 0xFF, (qa >> 16) & 0x3FFFFF,
                            (qa >> 8) & 0xFF, qa & 0xFF, qb))
        sprites = [sp + (n,) for n, sp in enumerate(sprites)]
        for x in range(256):
            b0, b1, b2, b3 = rec[y * 1024 + x * 4: y * 1024 + x * 4 + 4]
            p = Pix.__new__(Pix)
            p.t, p.finex, p.gray, p.emph = t, finex, gray, emph
            tl = Rec.__new__(Rec)
            tl.offx = (b1 >> 2) & 7
            tl.hm = tl.vm = tl.bgp = False
            tl.sci = 0
            tl.scolor = 0
            tl.poff = 0
            tl.bgci = b1 & 3
            tl.bgcolor = b3
            tl.ppubg = b2
            tl.inst = -1
            slot = b0 & 63
            if slot == 63 or slot >= len(spans):
                tl.idx = NOTILE
                tl.pal = 0
                tl.fp = None
                tl.offy = 0
            else:
                lin, psel, fp = spans[slot]
                tl.idx = chr_index(lin)
                tl.offy = lin & 7
                pb = psel * 4
                tl.pal = pal[pb + 3] | (pal[pb + 2] << 8) | (pal[pb + 1] << 16)
                if not legacy:
                    tl.pal |= pal[0] << 24
                tl.fp = fp if game_ram else ZERO_FP
            p.tile = tl
            p.spr = []
            if b0 & 0x40:
                for attr, sx, lin, pix1, pix2, fp, inst in sprites:
                    c = x - sx
                    if c < 0 or c > 7:
                        continue
                    if len(p.spr) == 4:
                        break
                    s = Rec.__new__(Rec)
                    s.idx = chr_index(lin)
                    s.offy = lin & 7
                    s.offx = c
                    s.hm = bool(attr & 0x40)
                    s.vm = bool(attr & 0x80)
                    s.bgp = bool(attr & 0x20)
                    q = 0x10 + 4 * (attr & 3)
                    s.poff = q
                    s.pal = pal[q + 3] | (pal[q + 2] << 8) | (pal[q + 1] << 16)
                    if not legacy:
                        s.pal |= 0xFF000000
                    s.fp = fp if game_ram else ZERO_FP
                    # SpriteAddressGen hands SpriteSet bytes in display order: screen column c
                    # is bit c (both planes), whatever the flip (rtl/ppu.sv load_in)
                    s.sci = ((pix1 >> c) & 1) | (((pix2 >> c) & 1) << 1)
                    s.scolor = pal[q + s.sci] if s.sci else b2
                    s.bgci = tl.bgci
                    s.bgcolor = b3
                    s.ppubg = b2
                    s.inst = inst
                    p.spr.append(s)
            screen[y * 256 + x] = p
    return screen


# --------------------------------------------------------------------------------------------
# The renderer
# --------------------------------------------------------------------------------------------
class HdRef:
    def __init__(self, h, rec, watch, game_ram):
        self.h = h
        self.game_ram = game_ram
        self.legacy = bool(h.flags & 1)
        self.frame = struct.unpack_from("<Q", rec, 0xF0000)[0] & 0xFFFFFFFF
        self.screen = build_records(rec, game_ram, self.legacy)
        # watched snapshot, indexed by the pack's slot numbers
        if watch[:4] != b"NWAT":
            raise ValueError("watch file: bad magic")
        (n,) = struct.unpack_from("<I", watch, 4)
        wl = list(struct.unpack_from(f"<{n}I", watch, 8))
        vals = watch[8 + 4 * n: 8 + 5 * n]
        if h.nwatched == 0:
            self.snap = []              # the pack tests no memory; whatever was watched is unused
        elif wl != h.watched:
            raise ValueError(f"watch list ({n}) differs from the pack's ({len(h.watched)}); "
                             "rerun fullsim with --watch set to the pack's list")
        else:
            self.snap = list(vals)
        # fallback map (CHR-ROM games only, spec 6.2)
        self.fb = list(struct.unpack_from(f"<{h.nfallback}i", h.d, h.s(10))) if h.nfallback else []
        self.has_fb = any(v >= 0 for v in self.fb)
        # palette
        if h.flags & 2:
            self.palette = list(struct.unpack_from("<64I", h.d, h.s(12)))
        else:
            self.palette = MESEN_2C02
        self.prgb = [((c >> 16) & 255, (c >> 8) & 255, c & 255) for c in self.palette]
        self.cache_enabled = (h.options & 8) == 0
        self.render_original = (h.options & 16) == 0
        self.memo = {}
        self.cond_cache = {}
        self.rule_cache = {}
        self.block_cache = {}
        self.add_cache = {}
        self.additions = self._load_additions()
        self.stats = dict(bg_lookups=0, bg_hd=0, spr_lookups=0, spr_hd=0, fallback_hits=0,
                          additions=0, rules_walked=0, max_rules_walked=0, conds_evaluated=0,
                          walk_hist=[0] * 15)

    # ---- pack access ---------------------------------------------------------------------
    def cond(self, ci):
        c = self.cond_cache.get(ci)
        if c is None:
            c = self.h.cond(ci)
            self.cond_cache[ci] = c
        return c

    def rules(self, off):
        r = self.rule_cache.get(off)
        if r is None:
            r = self.h.rules(off)
            for rule in r:
                rule["fl"] = self.h.clist(rule["frame"])
                rule["wl"] = self.h.clist(rule["walk"])
            self.rule_cache[off] = r
        return r

    def block(self, i):
        b = self.block_cache.get(i)
        if b is None:
            b = self.h.block(i).astype(np.int32)
            self.block_cache[i] = b
        return b

    def fallback(self, idx):
        if 0 <= idx < len(self.fb):
            return self.fb[idx]
        return -1

    def find(self, pal, r):
        if self.game_ram:
            if r.fp is None:
                return None
            return self.h.find_key(pal & 0xFFFFFFFF, 1, r.fp & 0xFFFFFFFF, r.fp >> 32)
        if r.idx == NOTILE:
            return None
        return self.h.find_key(pal & 0xFFFFFFFF, 0, r.idx & 0xFFFFFFFF, 0)

    def _load_additions(self):
        out = []
        for i in range(self.h.nadd):
            v = struct.unpack_from("<IIQIIQiiI", self.h.d, self.h.s(11) + 64 * i)
            opal, okind, obody, apal, akind, abody, ox, oy, flags = v
            out.append(dict(
                opal=opal, oidx=i64(obody) if okind == 0 else NOTILE,
                ofp=obody if okind == 1 else ZERO_FP,
                apal=apal, aidx=i64(abody) if akind == 0 else NOTILE,
                afp=abody if akind == 1 else ZERO_FP,
                ox=ox, oy=oy, ignore=bool(flags & 1)))
        return out

    # ---- conditions (spec 3) -------------------------------------------------------------
    def tmatch(self, c, t):
        pal = c["q3"] & 0xFFFFFFFF
        if not c["data"]:
            tile = i64(c["q2"])
            if not (c["ignore"] or t.pal == pal):
                return False
            return t.idx != NOTILE and (t.idx == tile or self.fallback(t.idx) == tile)
        if t.fp is None or t.idx == NOTILE:
            return False
        if c["ignore"]:
            return t.fp == c["q2"]
        return t.pal == pal and t.fp == c["q2"]

    def at(self, idx):
        if idx < 0 or idx >= 61440:
            return None
        return self.screen[idx]

    def eval_cond(self, ci, x, y, rec):
        c = self.cond(ci)
        self.stats["conds_evaluated"] += 1
        if c["frame"]:
            v = self.memo.get(ci)
            if v is not None:
                return v
        t = c["type"]
        q1 = c["q1"]
        if t == "memoryCheck":
            a = self.snap[q1 & 0xFF] & c["mask"]
            b = self.snap[(q1 >> 8) & 0xFF] & c["mask"]
            r = OPS[c["op"]](a, b)
        elif t == "memoryCheckConstant":
            a = self.snap[q1 & 0xFF] & c["mask"]
            r = OPS[c["op"]](a, (q1 >> 8) & 0xFF)
        elif t == "frameRange":
            a, b = q1 & 0xFFFF, (q1 >> 16) & 0xFFFF
            r = a != 0 and (self.frame % a) >= b
        elif t in ("tileAtPosition", "spriteAtPosition"):
            p = self.at(c["q3"] >> 32)
            if p is None:
                r = False
            elif t == "tileAtPosition":
                r = self.tmatch(c, p.tile)
            else:
                r = any(self.tmatch(c, s) for s in p.spr)
        elif t in ("tileNearby", "spriteNearby"):
            X, Y = i32(q1), i32(q1 >> 32)
            if t == "tileNearby":
                p = self.at((y + Y) * 256 + x + X)
                r = p is not None and self.tmatch(c, p.tile)
            else:
                xs = -1 if (rec is not None and rec.hm) else 1
                ys = -1 if (rec is not None and rec.vm) else 1
                p = self.at((y + Y * ys) * 256 + x + X * xs)
                r = p is not None and any(self.tmatch(c, s) for s in p.spr)
        elif t in ("positionCheckX", "positionCheckY", "originPositionCheckX",
                   "originPositionCheckY"):
            if t == "positionCheckX":
                val = x
            elif t == "positionCheckY":
                val = y
            elif rec is None:
                val = 0
            elif t == "originPositionCheckX":
                val = x - (7 - rec.offx) if rec.hm else x - rec.offx
            else:
                val = y - (7 - rec.offy) if rec.vm else y - rec.offy
            r = OPS[c["op"]](val & 0xFFFFFFFF, q1 & 0xFFFFFFFF)
        elif t == "hmirror":
            r = rec is not None and rec.hm
        elif t == "vmirror":
            r = rec is not None and rec.vm
        elif t == "bgpriority":
            r = rec is not None and rec.bgp
        else:
            raise ValueError(f"condition type {t}")
        if c["negate"]:
            r = not r
        if c["frame"]:
            self.memo[ci] = r
        return r

    def passes(self, rule, x, y, rec):
        for ci in rule["fl"]:
            if not self.eval_cond(ci, x, y, rec):
                return False
        for ci in rule["wl"]:
            if not self.eval_cond(ci, x, y, rec):
                return False
        return True

    # ---- tile lookup (3.16, 3.17) --------------------------------------------------------
    def get_matching(self, x, y, r):
        """Returns (payload or None, disableCache)."""
        off = self.find(r.pal, r)
        if off is None:
            f = self.fallback(r.idx) if not self.game_ram else -1
            if f >= 0:
                org = r.idx
                r.idx = f
                off = self.find(r.pal, r)
                if off is None:
                    off = self.find(0xFFFFFFFF, r)
                if off is None:
                    r.idx = org
                else:
                    self.stats["fallback_hits"] += 1
            if off is None:
                off = self.find(0xFFFFFFFF, r)
        if off is None:
            return None, False
        dis = False
        n = 0
        st = self.stats
        try:
            for rule in self.rules(off):
                n += 1
                if rule["fdc"]:
                    dis = True
                if self.passes(rule, x, y, r):
                    return rule["payload"], dis
            return None, dis
        finally:
            # cost census for the stage-3 lookup design: rules walked per lookup
            st["rules_walked"] += n
            if n > st["max_rules_walked"]:
                st["max_rules_walked"] = n
            st["walk_hist"][min(n.bit_length(), 14)] += 1

    # ---- additions (6.1) -----------------------------------------------------------------
    def key_eq(self, r, pal, idx, fp):
        if self.game_ram:
            return r.fp is not None and r.pal == pal and r.fp == fp
        return r.idx == idx and r.pal == pal

    def body_eq(self, r, idx, fp):
        if self.game_ram:
            return r.fp is not None and r.fp == fp
        return r.idx == idx

    def additions_for(self, r):
        key = (r.pal, r.idx if not self.game_ram else r.fp)
        lst = self.add_cache.get(key)
        if lst is None:
            lst = []
            check_fb = (not self.game_ram) and self.has_fb
            for a in self.additions:
                if not a["ignore"] and self.key_eq(r, a["opal"], a["oidx"], a["ofp"]):
                    lst.append(a)
                elif a["ignore"] and self.body_eq(r, a["oidx"], a["ofp"]):
                    lst.append(a)
                elif check_fb and (a["ignore"] or r.pal == a["opal"]) \
                        and r.idx != NOTILE and self.fallback(r.idx) == a["oidx"]:
                    lst.append(a)
            self.add_cache[key] = lst
        return lst

    def draw_additions(self, x, y, r):
        lst = self.additions_for(r)
        for a in lst:
            tx = x + (-a["ox"] if r.hm else a["ox"])
            ty = y + (-a["oy"] if r.vm else a["oy"])
            if 0 <= tx < 256 and 0 <= ty < 240:
                p = self.screen[(ty << 8) | tx]
                if len(p.spr) < 4:
                    n = r.copy()
                    n.sci = 0
                    n.idx = a["aidx"]
                    n.pal = a["apal"]
                    n.fp = a["afp"]
                    p.spr.append(n)
                    self.stats["additions"] += 1
        return len(lst) > 0

    def process_additions(self):
        if not self.additions:
            return
        sc = self.screen

        def scroll_y(t):
            return (((t & 0x3E0) >> 2) | ((t & 0x7000) >> 12)) + (240 if t & 0x800 else 0)

        first = sc[0]
        yscroll = scroll_y(first.t)
        tmpv = first.t
        process_bg = True
        for y in range(240):
            # (BUG?) lineFirstPixel is a reference to ScreenTiles[0]; this copies line y's
            # first pixel record over pixel (0,0) (spec 6.1)
            sc[0] = sc[y << 8].copy() if y else sc[0]
            lf = sc[0]
            if ((yscroll + y) & 7) == 0 or tmpv != lf.t:
                yscroll = scroll_y(lf.t)
                tmpv = lf.t
                process_bg = True
            if process_bg:
                process_bg = False
                for x in range(256):
                    p = sc[(y << 8) | x]
                    i = 0
                    while i < len(p.spr):
                        self.draw_additions(x, y, p.spr[i])
                        i += 1
                    if self.draw_additions(x, y, p.tile):
                        process_bg = True
            else:
                for x in range(256):
                    p = sc[(y << 8) | x]
                    i = 0
                    while i < len(p.spr):
                        self.draw_additions(x, y, p.spr[i])
                        i += 1

    # ---- backgrounds (4.2, 4.4) ----------------------------------------------------------
    def select_backgrounds(self):
        h = self.h
        layers = [[], [], [], []]
        for lvl in range(40):
            roff, ioff = h.bg_level(lvl)
            if roff == 0:
                continue
            rl = self.rules(roff)
            order = h.bg_index_candidates(ioff, self.snap) if ioff else range(len(rl))
            for e in order:
                if all(self.eval_cond(ci, 0, 0, None) for ci in rl[e]["fl"]):
                    rec = h.bg_rec(rl[e]["payload"])
                    layers[lvl // 10].append(rec)
                    break
        return layers

    def bg_line(self, rec, y, scroll_x, scroll_y):
        sx = self.h.ratio(rec["hr"], scroll_x)
        sy = self.h.ratio(rec["vr"], scroll_y)
        if y >= -sy and y + rec["top"] + sy + 1 <= rec["h"]:
            return (sx, sy, -sx, rec["w"] - rec["left"] - sx - 1)
        return None

    def bg_pixel(self, rec, cfg, x, y):
        sx, sy, mn, mx = cfg
        if not (mn <= x <= mx):
            return None, 0
        px = rec["left"] + x + sx
        py = rec["top"] + y + sy
        cols = (rec["w"] + 7) >> 3
        (bi,) = struct.unpack_from("<I", self.h.d, self.h.s(7) + rec["map"] + 4 * ((py >> 3) * cols + (px >> 3)))
        if bi == 0xFFFFFFFF:
            return None, 0
        b = self.block(bi)
        return b[(py & 7) * 2:(py & 7) * 2 + 2, (px & 7) * 2:(px & 7) * 2 + 2], rec["blend"]

    # ---- drawing -------------------------------------------------------------------------
    @staticmethod
    def put_color(out, oy, ox, rgb):
        out[oy:oy + 2, ox:ox + 2] = rgb

    @staticmethod
    def blend_sub(out, oy, ox, sub, mode):
        """sub: 2x2x4 premultiplied RGBA. mode 0 Alpha, 1 Add, 2 Subtract (PACK:83-175)."""
        for r in range(2):
            for c in range(2):
                pr, pg, pb, a = (int(v) for v in sub[r, c])
                o = out[oy + r, ox + c]
                if mode == 0:
                    if a == 255:
                        o[0], o[1], o[2] = pr, pg, pb
                    elif a:
                        inv = (256 - a) & 0xFF
                        o[0] = (pr + ((inv * int(o[0])) >> 8 & 0xFF)) & 0xFF
                        o[1] = (pg + ((inv * int(o[1])) >> 8 & 0xFF)) & 0xFF
                        o[2] = (pb + ((inv * int(o[2])) >> 8 & 0xFF)) & 0xFF
                elif mode == 1:
                    o[0] = min(255, pr + int(o[0]))
                    o[1] = min(255, pg + int(o[1]))
                    o[2] = min(255, pb + int(o[2]))
                else:
                    o[0] = max(0, int(o[0]) - pr)
                    o[1] = max(0, int(o[1]) - pg)
                    o[2] = max(0, int(o[2]) - pb)

    def draw_tile(self, out, oy, ox, r, payload):
        if payload == 0xFFFFFFFF:
            return                      # fully transparent: draws nothing (and erases SD)
        b = self.block(payload)
        col = 7 - r.offx if r.hm else r.offx
        sub = b[r.offy * 2:r.offy * 2 + 2, col * 2:col * 2 + 2]
        if r.hm:
            sub = sub[:, ::-1]
        if r.vm:
            sub = sub[::-1, :]
        self.blend_sub(out, oy, ox, sub, 0)

    def render(self, overscan=None):
        h = self.h
        ov = list(h.overscan) if overscan is None else list(overscan)
        top, right, bottom, left = [max(0, v) for v in ov]
        layers = self.select_backgrounds()     # before additions (PACK:300-313)
        self.process_additions()
        out = np.zeros((480, 512, 3), dtype=np.int32)
        sc = self.screen
        for y in range(top, 240 - bottom):
            first = sc[y << 8]
            scroll_x = ((first.t & 0x1F) << 3) | first.finex | (256 if first.t & 0x400 else 0)
            scroll_y = (((first.t & 0x3E0) >> 2) | ((first.t & 0x7000) >> 12)) + \
                (240 if first.t & 0x800 else 0)
            cfgs = [[(rec, self.bg_line(rec, y, scroll_x, scroll_y)) for rec in lay]
                    for lay in layers]
            use_cached = False
            cached = None
            for x in range(left, 256 - right):
                p = sc[(y << 8) | x]
                oy, ox = y * 2, x * 2
                hd = None
                if p.tile.idx != NOTILE:
                    if ((scroll_x + x) & 7) == 0:
                        use_cached = False
                    if use_cached:
                        hd = cached
                    else:
                        hd, dis = self.get_matching(x, y, p.tile)
                        self.stats["bg_lookups"] += 1
                        if not dis and self.cache_enabled:
                            cached = hd
                            use_cached = True
                    if hd is not None:
                        self.stats["bg_hd"] += 1
                lowest = 999
                self.put_color(out, oy, ox, self.prgb[p.tile.ppubg])
                self.draw_layer(out, oy, ox, cfgs[0], x, y)
                for k in range(len(p.spr) - 1, -1, -1):
                    s = p.spr[k]
                    if s.bgp:
                        if s.sci:
                            lowest = k
                        self.draw_sprite(out, oy, ox, x, y, s)
                self.draw_layer(out, oy, ox, cfgs[1], x, y)
                if hd is not None:
                    self.draw_tile(out, oy, ox, p.tile, hd)
                elif self.render_original and p.tile.bgci:
                    self.put_color(out, oy, ox, self.prgb[p.tile.bgcolor])
                self.draw_layer(out, oy, ox, cfgs[2], x, y)
                for k in range(len(p.spr) - 1, -1, -1):
                    s = p.spr[k]
                    if not s.bgp and lowest > k:
                        self.draw_sprite(out, oy, ox, x, y, s)
                self.draw_layer(out, oy, ox, cfgs[3], x, y)
            self.line_effects(out, y, first, left, right)
        return out[top * 2:(240 - bottom) * 2, left * 2:(256 - right) * 2].astype(np.uint8)

    def draw_layer(self, out, oy, ox, cfgs, x, y):
        for rec, cfg in cfgs:
            if cfg is None:
                continue
            sub, mode = self.bg_pixel(rec, cfg, x, y)
            if sub is not None:
                self.blend_sub(out, oy, ox, sub, mode)

    def draw_sprite(self, out, oy, ox, x, y, s):
        hd, _ = self.get_matching(x, y, s)
        self.stats["spr_lookups"] += 1
        if hd is not None:
            self.stats["spr_hd"] += 1
            self.draw_tile(out, oy, ox, s, hd)
        elif s.sci:
            self.put_color(out, oy, ox, self.prgb[s.scolor])

    @staticmethod
    def line_effects(out, y, first, left, right):
        row = out[y * 2:y * 2 + 2, left * 2:(256 - right) * 2]
        if first.gray:
            avg = (row[..., 0] + row[..., 1] + row[..., 2]) // 3
            row[..., 0] = avg
            row[..., 1] = avg
            row[..., 2] = avg
        if first.emph:
            rf = gf = bf = 1.0
            if first.emph & 1:
                rf *= 1.1
                gf *= 0.9
                bf *= 0.9
            if first.emph & 2:
                gf *= 1.1
                rf *= 0.9
                bf *= 0.9
            if first.emph & 4:
                bf *= 1.1
                rf *= 0.9
                gf *= 0.9
            for ch, f in ((0, rf), (1, gf), (2, bf)):
                row[..., ch] = np.minimum(np.floor(row[..., ch] * f).astype(np.int32), 255)


# --------------------------------------------------------------------------------------------
# SD check: the composited SD pixel must equal the PPU's output colour
# --------------------------------------------------------------------------------------------
def sd_check(screen, col, xoff, legacy=False):
    bad = 0
    ok = 0
    from_sprite = 0
    first = []
    for y in range(240):
        if screen[y << 8].gray:
            continue
        for x in range(256):
            p = screen[(y << 8) | x]
            c = p.tile.ppubg
            spr = False
            lowest = 999
            for k in range(len(p.spr) - 1, -1, -1):
                s = p.spr[k]
                if s.bgp and s.sci:
                    lowest = k
                    c = s.scolor
                    spr = True
            if p.tile.bgci:
                c = p.tile.bgcolor
                spr = False
            for k in range(len(p.spr) - 1, -1, -1):
                s = p.spr[k]
                if not s.bgp and lowest > k and s.sci:
                    c = s.scolor
                    spr = True
            want = col[y * 341 + x + xoff] & 63
            if c == want:
                ok += 1
                from_sprite += spr
            else:
                bad += 1
                if len(first) < 10:
                    first.append(f"y{y} x{x}: composited {c:02x} PPU {want:02x} "
                                 f"sprites={[(s.sci, s.bgp) for s in p.spr]} bgci={p.tile.bgci}")
    return ok, bad, first, from_sprite


def write_png(path, img):
    hgt, wid = img.shape[:2]
    raw = b"".join(b"\x00" + img[r].astype(np.uint8).tobytes() for r in range(hgt))

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))

    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", wid, hgt, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b"")
    with open(path, "wb") as f:
        f.write(png)


def rom_is_chr_ram(path):
    with open(path, "rb") as f:
        d = f.read(16)
    if d[:4] != b"NES\x1a":
        sys.exit("not an iNES file")
    return d[5] == 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("hdp", nargs="?")
    ap.add_argument("recdir")
    ap.add_argument("--frame", type=int, required=True)
    ap.add_argument("--rom")
    ap.add_argument("--out")
    ap.add_argument("--sd-check", action="store_true")
    ap.add_argument("--xoff", type=int, default=2)
    # Added to the recorded FrameNumber before rendering. Comparing against Mesen only: the
    # same game state can reach the core one frame later than Mesen after power-on (Castlevania
    # p002: Mesen numbers it one lower), which moves every frameRange result by one frame.
    ap.add_argument("--frame-delta", type=int, default=0)
    a = ap.parse_args()
    rp = os.path.join(a.recdir, f"rec_{a.frame:04d}.bin")
    rec = open(rp, "rb").read()
    if a.sd_check:
        if not a.rom:
            sys.exit("--sd-check needs --rom")
        game_ram = rom_is_chr_ram(a.rom)
        screen = build_records(rec, game_ram, False)
        col = open(os.path.join(a.recdir, f"col_{a.frame:04d}.bin"), "rb").read()
        ok, bad, first, from_sprite = sd_check(screen, col, a.xoff)
        print(f"frame {a.frame}: SD composite {ok} ok / {bad} bad "
              f"({from_sprite} of the matches decided by a sprite pixel)")
        for line in first:
            print("   ", line)
        return 1 if bad or not ok else 0
    if not a.hdp:
        sys.exit("pack required")
    h = Hdp3(open(a.hdp, "rb").read())
    if h.flags & 0x20:
        game_ram = bool(h.flags & 0x10)
    elif a.rom:
        game_ram = rom_is_chr_ram(a.rom)
    else:
        sys.exit("pack does not say whether the game is CHR-RAM; give --rom")
    watch = open(os.path.join(a.recdir, f"watch_{a.frame:04d}.bin"), "rb").read()
    r = HdRef(h, rec, watch, game_ram)
    r.frame += a.frame_delta
    img = r.render()
    out = a.out or os.path.join(a.recdir, f"hdref_{a.frame:04d}.png")
    write_png(out, img)
    print(f"frame {a.frame} (FrameNumber {r.frame}): {img.shape[1]}x{img.shape[0]} -> {out}")
    print("   ", ", ".join(f"{k} {v}" for k, v in r.stats.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
