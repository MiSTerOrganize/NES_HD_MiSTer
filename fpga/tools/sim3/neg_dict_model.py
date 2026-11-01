"""Negative control for hwmodel --dict: each mutant of the RESOLVE filter must make the model
differ from the reference on the given frame; the unmutated model must not.
usage: python -I neg_dict.py PACK.hdp RECDIR FRAME ROM"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import hdref  # noqa: E402
import hwmodel  # noqa: E402


def run(pack, recdir, frame, rom, mutate):
    h = hdref.Hdp3(open(pack, "rb").read())
    game_ram = hdref.rom_is_chr_ram(rom)
    rec = open(os.path.join(recdir, f"rec_{frame:04d}.bin"), "rb").read()
    watch = open(os.path.join(recdir, f"watch_{frame:04d}.bin"), "rb").read()
    m = hwmodel.HwModel(h, rec, watch, game_ram)
    m.dict_mode = True
    if mutate:
        mutate(m)
    m.render()
    return len(m.mism)


def keep_failing(m):
    """RESOLVE keeps every rule: frame conditions never evaluated."""
    orig = m.build_dict

    def bd():
        orig()
        for off in m.filtered:
            m.filtered[off] = [(rule, []) for rule in m.rules(off)]
    m.build_dict = bd


def stop_early(m):
    """RESOLVE stops at the first KEPT rule, walk conditions or not."""
    orig = m.build_dict

    def bd():
        orig()
        for off in m.filtered:
            m.filtered[off] = m.filtered[off][:1]
    m.build_dict = bd


def no_prefix(m):
    """The cache flag of a match ignores filtered-out rules before it."""
    orig = m.build_dict

    def bd():
        orig()
        for off, v in m.filtered.items():
            m.filtered[off] = [(dict(rule, prefix=rule["fdc"]), fl) for rule, fl in v]
    m.build_dict = bd


def main():
    pack, recdir, frame, rom = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4]
    base = run(pack, recdir, frame, rom, None)
    print(f"unmutated: {base} differ")
    ok = base == 0
    for f in (keep_failing, stop_early, no_prefix):
        n = run(pack, recdir, frame, rom, f)
        print(f"{'CAUGHT' if n else 'MISSED'}  {f.__doc__.strip()}  ({n} differ)")
        ok &= n > 0
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
