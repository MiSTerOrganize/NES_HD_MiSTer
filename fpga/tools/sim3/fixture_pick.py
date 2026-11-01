"""Shared by the hd3_resolve fixture generators (make_pos_frame.py, make_edge_frame.py): which
frame conditions a recorded frame actually EVALUATES in RESOLVE, and whether inverting one of
them changes RESOLVE's output (the golden). A fixture condition only catches a bug if both are
true: a trap planted in a rule list the frame never filters, or behind a condition that has
already failed, or after the list's stop point, is invisible to the test (that is how the first
fixtures left 9 of 29 negative-control mutants uncaught - trap_sense.py measures it).
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hdref  # noqa: E402
import hwmodel  # noqa: E402
from resolve_golden import golden_lists  # noqa: E402


def canon(lists):
    return {off: ([(r["payload"] & 0xFFFFFFFF, r["frame"] if later else 0, r["walk"],
                    bool(r["prefix"])) for r, later in keep], lastp)
            for off, (keep, lastp) in lists.items()}


class Rec:
    """One recorded frame: its record, watch file and name."""

    def __init__(self, recdir, name):
        self.name = name
        self.rec = open(os.path.join(recdir, f"rec_{name}.bin"), "rb").read()
        self.watch = open(os.path.join(recdir, f"watch_{name}.bin"), "rb").read()


def evaluated(data, fr, gr):
    """(set of frame conditions RESOLVE evaluates on frame fr, the golden) for pack bytes."""
    h = hdref.Hdp3(bytes(data))
    seen = set()

    class Seen(hwmodel.HwModel):
        def hw_eval(self, ci, x, y, r):
            seen.add(ci)
            return super().hw_eval(ci, x, y, r)

    return seen, canon(golden_lists(h, fr.rec, fr.watch, gr, Seen))


def visible(data, fr, gr, ci, base=None):
    """Does inverting condition ci's result change the golden on frame fr?"""
    h = hdref.Hdp3(bytes(data))
    if base is None:
        base = canon(golden_lists(h, fr.rec, fr.watch, gr))

    class Flip(hwmodel.HwModel):
        def hw_eval(self, c, x, y, r):
            v = super().hw_eval(c, x, y, r)
            return (not v) if c == ci else v

    return canon(golden_lists(h, fr.rec, fr.watch, gr, Flip)) != base


def all_reach(data, gr, placed):
    """Every (ci, frame) in placed is still evaluated on its frame and still changes the golden
    when inverted, on pack bytes data. A new trap or boundary must not knock out an earlier
    one: changing one condition's value changes which later conditions a rule list reaches."""
    by = {}
    for ci, fr in placed:
        by.setdefault(id(fr), (fr, []))[1].append(ci)
    for fr, cis in by.values():
        seen, gold = evaluated(data, fr, gr)
        for ci in cis:
            if ci not in seen or not visible(data, fr, gr, ci, gold):
                return False
    return True


def value(data, fr, gr, ci):
    """Condition ci's result on frame fr (as RESOLVE evaluates it, record-independent)."""
    h = hdref.Hdp3(bytes(data))
    m = hwmodel.HwModel(h, fr.rec, fr.watch, gr)
    m.select_backgrounds()
    m.process_additions()
    m.cap = [p.copy() for p in m.screen]
    m.dict_mode = True
    return bool(m.hw_eval(ci, 0, 0, None))
