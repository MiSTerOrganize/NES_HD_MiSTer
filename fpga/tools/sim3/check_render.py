"""Compare tb_render.exe's frames with hdref.HdRef.render on the same pack, record and watch.

    python check_render.py <file.hdp> <recdir> <prefix> <frame> [<frame> ...]
                           [--game-ram G] [--no-bg] [--no-add] [--show N] [--raw N]

<prefix>_<FFFF>.rgb are the testbench's images ("NRGB", u32 width, u32 height, RGB bytes).
--no-bg / --no-add render the reference without backgrounds / additions, for an RTL build
that does not draw them yet. --raw is the RTL's record id width (default 11): a frame with more
distinct record keys than 2**raw, or a line with more than 16 sprite fetches, is one hd3_dict
flags frame_ovf, and hd3_render draws it with no HD lookups (HDPACK_DESIGN.md, "8o"), so its
reference is rendered with every lookup answering "no rule". --nl is the RTL's lanes per line
(hd3_add NL, default 16): a frame whose additions need more lanes on a line than that (or more
than 64 from one source line) is one hd3_add flags ovf, drawn the same way - the overflow is
decided here by the lane model (addhw.py), never taken from the testbench. Exit status 1 on any
differing pixel.

Reference renders are cached in obj/refcache (CHECK_RENDER_CACHE overrides; "off" disables): the
key hashes the pack, record and watch bytes, every option that changes the reference, and the
source of the reference modules, so editing hdref/addhw/etc. invalidates it. A negative control
then renders each reference once instead of once per mutant.
"""
import collections
import hashlib
import os
import struct
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))     # -I leaves this folder out
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from hdp3_read import Hdp3  # noqa: E402
import hdref  # noqa: E402
from dict_keys import frame_overflows, frame_overflows_add  # noqa: E402
import addhw  # noqa: E402

NB = 64   # lanes one source line can emit (hd3_add NB)
HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.environ.get("CHECK_RENDER_CACHE", os.path.join(HERE, "obj", "refcache"))


def code_hash():
    """The reference's own source: a change to any of it must not reuse a cached render."""
    import hdp3_addtab  # noqa: F401  (dict_keys imports it lazily; hash it either way)
    hs = hashlib.sha1()
    for m in (hdref, addhw, sys.modules["hdp3_read"], sys.modules["dict_keys"], hdp3_addtab,
              sys.modules[__name__]):
        hs.update(open(m.__file__, "rb").read())
    return hs.hexdigest()


def reference(h, hdp_bytes, rec, watch, game_ram, raw, nl, no_bg, no_add, fr, code):
    """(image, stats, messages) for one frame, from the cache when the inputs are identical."""
    key = None
    if CACHE != "off":
        hs = hashlib.sha1(code.encode())
        for b in (hdp_bytes, rec, watch):
            hs.update(hashlib.sha1(b).digest())
        hs.update(repr((game_ram, raw, nl, no_bg, no_add, NB)).encode())
        key = os.path.join(CACHE, hs.hexdigest() + ".npz")
        if os.path.exists(key):
            z = np.load(key, allow_pickle=False)
            msgs = [m for m in str(z["msgs"]).split("\n") if m]
            stats = dict(zip(("bg_lookups", "spr_lookups", "fallback_hits"),
                             (int(v) for v in z["stats"])))
            return z["img"], stats, msgs
    msgs = []
    r = hdref.HdRef(h, rec, watch, game_ram)
    if no_add:
        ovf, nkeys = frame_overflows(rec, game_ram, bool(h.flags & 1), raw)
        why = f"{nkeys} record keys > {1 << raw} ids (or > 16 fetches on a line)"
    else:
        # added keys take dictionary ids too, and the addition buffer / pool can overflow
        ovf, nkeys, why = frame_overflows_add(h, rec, game_ram, bool(h.flags & 1), raw)
    if not ovf and not no_add and r.additions:
        lanes, _ = addhw.build(hdref.HdRef(h, rec, watch, game_ram))
        per_src = collections.Counter(ln.sy for ty in range(240) for ln in lanes[ty])
        most = max(len(lanes[ty]) for ty in range(241))
        if most > nl or (max(per_src.values()) if per_src else 0) > NB:
            r.get_matching = lambda x, y, rr: (None, False)
            msgs.append(f"frame {fr}: {most} lanes on a line > NL {nl} (or > {NB} from one "
                        f"source line): addition overflow, reference drawn without lookups")
    if ovf:
        # no lookup at all: the original picture (backgrounds, which do not depend on the
        # dictionary, are still selected and drawn)
        r.get_matching = lambda x, y, rr: (None, False)
        msgs.append(f"frame {fr}: {why}: dictionary overflow, reference drawn without lookups")
    if no_bg:
        r.select_backgrounds = lambda: [[], [], [], []]
    if no_add:
        r.process_additions = lambda: None
    want = r.render()
    st = {k: int(r.stats[k]) for k in ("bg_lookups", "spr_lookups", "fallback_hits")}
    if key:
        os.makedirs(CACHE, exist_ok=True)
        tmp = key + f".{os.getpid()}.part.npz"
        np.savez(tmp, img=want, stats=np.array(list(st.values())), msgs=np.array("\n".join(msgs)))
        os.replace(tmp, key)
    return want, st, msgs


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    opts = sys.argv[1:]
    game_ram = None
    show = 5
    raw = 11
    nl = 16
    for i, a in enumerate(opts):
        if a == "--game-ram":
            game_ram = bool(int(opts[i + 1]))
            args.remove(opts[i + 1])
        if a == "--show":
            show = int(opts[i + 1])
            args.remove(opts[i + 1])
        if a == "--raw":
            raw = int(opts[i + 1])
            args.remove(opts[i + 1])
        if a == "--nl":
            nl = int(opts[i + 1])
            args.remove(opts[i + 1])
    no_bg = "--no-bg" in opts
    no_add = "--no-add" in opts
    hdp, recdir, prefix = args[0], args[1], args[2]
    frames = [int(f) for f in args[3:]]
    hdp_bytes = open(hdp, "rb").read()
    h = Hdp3(hdp_bytes)
    if game_ram is None:
        if not h.flags & 0x20:
            sys.exit("pack does not say whether the game is CHR-RAM; give --game-ram")
        game_ram = bool(h.flags & 0x10)
    code = code_hash()
    bad_frames = 0
    for fr in frames:
        rec = open(os.path.join(recdir, f"rec_{fr:04d}.bin"), "rb").read()
        watch = open(os.path.join(recdir, f"watch_{fr:04d}.bin"), "rb").read()
        want, st, msgs = reference(h, hdp_bytes, rec, watch, game_ram, raw, nl, no_bg, no_add,
                                   fr, code)
        for m in msgs:
            print(m)
        d = open(f"{prefix}_{fr:04d}.rgb", "rb").read()
        magic, w, hgt = struct.unpack_from("<III", d, 0)
        if magic != 0x4247524E:
            sys.exit(f"{prefix}_{fr:04d}.rgb: bad magic")
        got = np.frombuffer(d, dtype=np.uint8, offset=12).reshape(hgt, w, 3)
        if got.shape != want.shape:
            print(f"frame {fr}: size {got.shape} vs reference {want.shape}")
            bad_frames += 1
            continue
        diff = np.any(got != want, axis=2)
        n = int(diff.sum())
        print(f"frame {fr}: {n} of {diff.size} pixels differ (bg_lookups {st['bg_lookups']}, "
              f"spr_lookups {st['spr_lookups']}, fallback_hits {st['fallback_hits']})")
        if n:
            bad_frames += 1
            ys, xs = np.nonzero(diff)
            for k in range(min(show, n)):
                y, x = int(ys[k]), int(xs[k])
                print(f"    out ({x},{y}) = nes ({x // 2},{y // 2}) rel: got {tuple(got[y, x])} "
                      f"want {tuple(want[y, x])}")
    print("PASS" if not bad_frames else f"FAIL ({bad_frames} frames differ)")
    return 1 if bad_frames else 0


if __name__ == "__main__":
    sys.exit(main())
