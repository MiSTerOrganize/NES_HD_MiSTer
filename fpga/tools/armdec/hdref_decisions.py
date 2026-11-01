"""hdref_decisions.py - dump every decision hdref makes for one frame, in hdref's own order.

The ARM-helper feasibility study (OPEN_ITEMS item 11) ports the per-frame DECISION work to C
(hdarm.c): build the per-pixel records, choose backgrounds, insert additions, and look up every
tile Mesen would look up. Compositing stays in the FPGA, so nothing is drawn here.

This walks exactly the order hdref.render() uses (lookups are order-dependent: a fallback hit
rewrites the record that later conditions read), but records results instead of drawing.
The C port must produce byte-identical output.

Output (text):
  F <FrameNumber>
  L <level 0..39> <payload>             background chosen for a level (one line per hit)
  P <y> <x> B <payload|-> S<k> <payload|-> ...   every pixel where a lookup happened
  (payload printed in hex; "-" = no HD tile; ffffffff = transparent)

usage: python hdref_decisions.py PACK.hdp RECDIR --frame F [--frame-delta D] [--rom R] > out.txt
"""
import argparse
import os
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import hdref  # noqa: E402
from hdref import NOTILE  # noqa: E402
from hdp3_read import Hdp3  # noqa: E402


def fmt(v):
    return "-" if v is None else "%x" % v


class Dec(hdref.HdRef):
    def levels(self):
        """select_backgrounds, but returning (level, payload) pairs."""
        h = self.h
        out = []
        for lvl in range(40):
            roff, ioff = h.bg_level(lvl)
            if roff == 0:
                continue
            rl = self.rules(roff)
            order = h.bg_index_candidates(ioff, self.snap) if ioff else range(len(rl))
            for e in order:
                if all(self.eval_cond(ci, 0, 0, None) for ci in rl[e]["fl"]):
                    out.append((lvl, rl[e]["payload"]))
                    break
        return out

    def decide(self, overscan=None):
        h = self.h
        ov = list(h.overscan) if overscan is None else list(overscan)
        top, right, bottom, left = [max(0, v) for v in ov]
        lines = ["F %d" % self.frame]
        for lvl, pay in self.levels():
            lines.append("L %d %x" % (lvl, pay))
        self.process_additions()
        sc = self.screen
        for y in range(top, 240 - bottom):
            first = sc[y << 8]
            scroll_x = ((first.t & 0x1F) << 3) | first.finex | (256 if first.t & 0x400 else 0)
            use_cached = False
            cached = None
            for x in range(left, 256 - right):
                p = sc[(y << 8) | x]
                parts = []
                hd = None
                if p.tile.idx != NOTILE:
                    if ((scroll_x + x) & 7) == 0:
                        use_cached = False
                    if use_cached:
                        hd = cached
                    else:
                        hd, dis = self.get_matching(x, y, p.tile)
                        if not dis and self.cache_enabled:
                            cached = hd
                            use_cached = True
                    parts.append("B " + fmt(hd))
                lowest = 999
                for k in range(len(p.spr) - 1, -1, -1):
                    s = p.spr[k]
                    if s.bgp:
                        if s.sci:
                            lowest = k
                        v, _ = self.get_matching(x, y, s)
                        parts.append("S%d %s" % (k, fmt(v)))
                for k in range(len(p.spr) - 1, -1, -1):
                    s = p.spr[k]
                    if not s.bgp and lowest > k:
                        v, _ = self.get_matching(x, y, s)
                        parts.append("S%d %s" % (k, fmt(v)))
                if parts:
                    lines.append("P %d %d %s" % (y, x, " ".join(parts)))
        return lines


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("hdp")
    ap.add_argument("recdir")
    ap.add_argument("--frame", type=int, required=True)
    ap.add_argument("--frame-delta", type=int, default=0)
    ap.add_argument("--rom")
    a = ap.parse_args()
    h = Hdp3(open(a.hdp, "rb").read())
    if h.flags & 0x20:
        game_ram = bool(h.flags & 0x10)
    elif a.rom:
        game_ram = hdref.rom_is_chr_ram(a.rom)
    else:
        sys.exit("pack does not say whether the game is CHR-RAM; give --rom")
    rec = open(os.path.join(a.recdir, "rec_%04d.bin" % a.frame), "rb").read()
    watch = open(os.path.join(a.recdir, "watch_%04d.bin" % a.frame), "rb").read()
    d = Dec(h, rec, watch, game_ram)
    d.frame += a.frame_delta
    sys.stdout.write("\n".join(d.decide()) + "\n")
    st = d.stats
    sys.stderr.write("rules_walked %d conds_evaluated %d fallback_hits %d additions %d\n"
                     % (st["rules_walked"], st["conds_evaluated"], st["fallback_hits"],
                        st["additions"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
