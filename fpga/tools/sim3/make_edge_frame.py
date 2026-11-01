"""Write a copy of a format-3 pack whose FRAME conditions sit exactly on their comparison
boundary on the given recorded frames, so the hd3_resolve test can tell >= from > and <= from <.
On the recorded frames no frameRange has frame % A == B and no ordered memoryCheckConstant has
value == constant where it changes a result, so those mutants are invisible without this.

A boundary condition only catches a bug if RESOLVE evaluates it on that frame AND its result
reaches the output (fixture_pick.py), so each target is placed only where both hold:
  range   a frameRange with A != 0 that the frame evaluates:  B := F % A
  gt/lt/le/ge   a one-slot memoryCheckConstant the frame evaluates: op := target,
                constant := watch[slot] & mask on that frame (the boundary)
and kept only if inverting it changes the golden. --per-target N of each (default 2). The
first version tuned condition ci for frame FRAMES[ci % n] whether or not that frame evaluated
it, and the negative control missed "<= tested as <". F is the frame number hdref reads (rec
trailer qword 0xF0000). resolve_golden.py reads the same modified pack. A test fixture only.

usage: python make_edge_frame.py <in.hdp> <out.hdp> <recdir> <game_ram 0/1> [--per-target N]
                                 <frame> [<frame> ...]   (frames as rec file numbers, e.g. 0250)
"""
import os
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hdref  # noqa: E402
import fixture_pick  # noqa: E402

MEM_CONST, FRAME_RANGE = 1, 2
OPS = {"gt": 2, "lt": 3, "le": 4, "ge": 5}


class Frame(fixture_pick.Rec):
    def __init__(self, recdir, name):
        super().__init__(recdir, name)
        self.frame = struct.unpack_from("<Q", self.rec, 0xF0000)[0] & 0xFFFFFFFF
        w = self.watch
        if w[:4] != b"NWAT":
            sys.exit(f"watch_{name}.bin: bad magic")
        (n,) = struct.unpack_from("<I", w, 4)
        self.wl = list(struct.unpack_from(f"<{n}I", w, 8))
        self.vals = w[8 + 4 * n: 8 + 5 * n]


def main():
    args = sys.argv[1:]
    if len(args) < 5:
        print(__doc__)
        return 2
    src, dst, recdir, gr, names = args[0], args[1], args[2], bool(int(args[3])), args[4:]
    per = 2
    if names[:1] == ["--per-target"]:
        per, names = int(names[1]), names[2:]
    data = bytearray(open(src, "rb").read())
    h = hdref.Hdp3(bytes(data))
    frames = [Frame(recdir, n) for n in names]
    for f in frames:
        if h.nwatched and f.wl != h.watched:
            sys.exit(f"watch_{f.name}.bin lists different addresses from the pack")
    base = h.s(2)
    targets = [("range", None)] + [(k, v) for k, v in OPS.items()]
    used, placed = set(), []
    for tname, op in targets:
        got = 0
        for f in frames:
            if got >= per:
                break
            seen, _ = fixture_pick.evaluated(data, f, gr)
            for ci in sorted(seen - used):
                if got >= per:
                    break
                o = base + 32 * ci
                q0, q1 = struct.unpack_from("<QQ", data, o)
                if not (q0 >> 11) & 1 or (q0 >> 24) & 1:
                    continue
                t = q0 & 0xFF
                trial = bytearray(data)
                if op is None:
                    a = q1 & 0xFFFF
                    if t != FRAME_RANGE or not a:
                        continue
                    struct.pack_into("<Q", trial, o + 8,
                                     (q1 & ~(0xFFFF << 16)) | ((f.frame % a) << 16))
                else:
                    if t != MEM_CONST:
                        continue
                    v = f.vals[q1 & 0xFF] & ((q0 >> 16) & 0xFF)
                    struct.pack_into("<Q", trial, o, (q0 & ~(0xF << 12)) | (op << 12))
                    struct.pack_into("<Q", trial, o + 8, (q1 & ~0xFF00) | (v << 8))
                if fixture_pick.visible(trial, f, gr, ci) and fixture_pick.all_reach(
                        trial, gr, [(c2, f2) for _, c2, f2 in placed]):
                    data = trial
                    used.add(ci)
                    placed.append((tname, ci, f))
                    got += 1
        print(f"  {tname}: {got}" + ("" if got else "   (no candidate reached RESOLVE)"),
              flush=True)
    alive = {}
    for tname, ci, f in placed:
        seen, gold = fixture_pick.evaluated(data, f, gr)
        ok = ci in seen and fixture_pick.visible(data, f, gr, ci, gold)
        alive[tname] = alive.get(tname, 0) + int(ok)
        if not ok:
            print(f"  WARNING {tname} cond {ci} on {f.name} no longer reaches the output")
    if not placed:
        sys.exit("nothing reached RESOLVE on these frames")
    open(dst, "wb").write(data)
    print(f"{dst}: " + ", ".join(f"{t} {alive.get(t, 0)}" for t, _ in targets))
    return 0


if __name__ == "__main__":
    sys.exit(main())
