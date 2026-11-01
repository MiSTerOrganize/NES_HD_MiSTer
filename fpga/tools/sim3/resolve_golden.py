"""Golden reference for the hd3_resolve unit test: every rule list one recorded frame uses,
filtered by the frame conditions exactly as RESOLVE does it (hwmodel.HwModel.filter_list,
the code the stage-3 model is checked with).

The frame is prepared the way Mesen does before any tile is looked up: backgrounds selected,
additions inserted (hdref.render's order); the capture the conditions read is that state, as
in hwmodel. A list is listed once, under its rule-list offset (the `off` of dict_golden.py):

    #list <off> last_prefix <0|1> kept <n>
    rule <payload> <fptr> <wptr> <prefix>          one line per kept rule, in order

payload = w0, wptr = w2 (walk list pointer, 0 = none), prefix = w3 bit 25 (prefix_fdc);
fptr = w1 when the rule kept rewrite-sensitive frame conditions for render to test, else 0.
last_prefix = the prefix of the LIST's last rule (filtered-out rules included): render's flag
when no kept rule matches.

Records come from the frame record exactly as hd3_dict forms them (BG spans and valid sprite
fetches 0-15; additions are not records hd3_dict sees). The first line is
"#game_ram legacy additions" - a pack with additions is evaluated with them inserted, which
the RTL does not do yet (stage 4), so a mismatch on such a pack is expected until then.

usage: python resolve_golden.py <file.hdp> <recdir> <frame> <out.tsv> (--rom ROM | --game-ram 0/1)
"""
import argparse
import os
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import hdref  # noqa: E402
import hwmodel  # noqa: E402


def golden_lists(h, rec, watch, game_ram, model=hwmodel.HwModel):
    """{list offset: (kept [(rule, deferred conditions)], last_prefix)} for one frame - the
    whole golden. `model` lets a caller pass a HwModel subclass (trap_sense.py flips one
    condition's result with it)."""
    m = model(h, rec, watch, game_ram)
    # Mesen's order before the first tile lookup (hdref.render): backgrounds, then additions
    m.select_backgrounds()
    m.process_additions()
    m.cap = [p.copy() for p in m.screen]
    m.dict_mode = True

    # the records hd3_dict forms, straight from the frame record (as dict_golden.py)
    legacy = bool(h.flags & 1)
    recs = []
    for y in range(240):
        hoff = 0x40000 + y * 2048
        q0 = struct.unpack_from("<Q", rec, hoff)[0]
        nspan = min((q0 >> 32) & 0xFF, 34)
        nfet = min((q0 >> 48) & 0xFF, 16)
        pbits = int.from_bytes(rec[hoff + 8:hoff + 32], "little")
        c = [(pbits >> (6 * n)) & 63 for n in range(32)]
        for s in range(nspan):
            qa, qb = struct.unpack_from("<QQ", rec, hoff + 64 + s * 16)
            pb = ((qa >> 32) & 3) * 4
            pal = c[pb + 3] | (c[pb + 2] << 8) | (c[pb + 1] << 16) | (0 if legacy else c[0] << 24)
            recs.append((pal, (qa & 0x3FFFFF), qb))
        for i in range(nfet):
            qa, qb = struct.unpack_from("<QQ", rec, hoff + 640 + i * 16)
            if (qa >> 54) & 1:
                q = 0x10 + 4 * ((qa >> 46) & 3)
                pal = c[q + 3] | (c[q + 2] << 8) | (c[q + 1] << 16) | (0 if legacy else 0xFF000000)
                recs.append((pal, (qa >> 16) & 0x3FFFFF, qb))

    lists = {}
    for pal, lin, qb in set(recs):
        r = hdref.Rec.__new__(hdref.Rec)
        for k in hdref.Rec.__slots__:      # resolve_key copies the record on a fallback
            setattr(r, k, 0)
        r.pal, r.idx = pal, hdref.chr_index(lin)
        r.fp = qb if game_ram else hdref.ZERO_FP
        r.hm = r.vm = r.bgp = False
        r.inst = -1
        off = m.resolve_key(r)
        if off is None or off in lists:
            continue
        keep, _, _ = m.filter_list(off, r)
        full = m.rules(off)
        lists[off] = (keep, bool(full[-1]["prefix"]) if full else False)
    return lists


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("hdp")
    ap.add_argument("recdir")
    ap.add_argument("frame", type=int)
    ap.add_argument("out")
    ap.add_argument("--rom")
    ap.add_argument("--game-ram", type=int, choices=(0, 1))
    a = ap.parse_args()
    h = hdref.Hdp3(open(a.hdp, "rb").read())
    if a.game_ram is not None:
        game_ram = bool(a.game_ram)
    elif h.flags & 0x20:
        game_ram = bool(h.flags & 0x10)
    elif a.rom:
        game_ram = hdref.rom_is_chr_ram(a.rom)
    else:
        sys.exit("say whether the game is CHR-RAM: --rom or --game-ram")
    rec = open(os.path.join(a.recdir, f"rec_{a.frame:04d}.bin"), "rb").read()
    watch = open(os.path.join(a.recdir, f"watch_{a.frame:04d}.bin"), "rb").read()
    legacy = bool(h.flags & 1)
    lists = golden_lists(h, rec, watch, game_ram)

    with open(a.out, "w") as f:
        f.write(f"#{int(game_ram)}\t{int(legacy)}\t{h.nadd}\n")
        for off in sorted(lists):
            keep, lastp = lists[off]
            f.write(f"#list {off} last_prefix {int(lastp)} kept {len(keep)}\n")
            for rule, later in keep:
                fptr = rule["frame"] if later else 0
                f.write(f"rule {rule['payload'] & 0xFFFFFFFF} {fptr} {rule['walk']} "
                        f"{int(bool(rule['prefix']))}\n")
    print(f"{a.out}: {len(lists)} lists, {sum(len(k) for k, _ in lists.values())} kept rules, "
          f"additions {h.nadd}")


if __name__ == "__main__":
    sys.exit(main())
