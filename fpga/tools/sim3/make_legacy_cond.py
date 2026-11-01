"""Write a variant of a legacy (version < 100) pack's hires.txt whose tile rules carry frame
conditions, for the hd3_resolve legacy-flag test.

No legacy pack in the corpus has a condition (all 7 have 0), so RESOLVE's legacy path - the
record palette's top byte is 0 in a legacy pack instead of the backdrop colour - is never
exercised by real data, and the negative control's "legacy flag ignored" mutant cannot be
caught. Mesen accepts <condition> in any pack version, so a user's legacy pack can have them.

This adds N positional frame conditions (alternately tileAtPosition and spriteAtPosition - the
only condition types Mesen accepts below version 101; frameRange and memoryCheck need 101+) and
prefixes every tile rule with one of them, round-robin. Their targets are placeholders
(position i,0, tile 0, palette 0 - distinct, or the converter merges them):
make_pos_frame.py retargets the ones RESOLVE evaluates. The
variant folder holds only hires.txt; convert it with
the original as --base so the images resolve:
    python ../hdp3_convert.py <variant dir> <out.hdp> --base <original dir>
then make_pos_frame.py turns the ones RESOLVE evaluates into tileAt / spriteAtPosition traps
(with the legacy palette, top byte 0). A test fixture only.

usage: python make_legacy_cond.py <original pack dir> <variant dir> [N]
"""
import os
import sys


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    src, dst = sys.argv[1], sys.argv[2]
    n = int(sys.argv[3]) if len(sys.argv) > 3 else 24
    raw = open(os.path.join(src, "hires.txt"), "rb").read().decode("utf-8", "surrogateescape")
    lines = raw.split("\n")
    out, tiles, conds_written = [], 0, False
    for line in lines:
        body = line.rstrip("\r")
        if body.startswith("<ver>"):
            v = int(body[5:])
            if v >= 100:
                sys.exit(f"pack version {v}: not a legacy pack")
        if not conds_written and body.startswith("<img>"):
            # distinct x per condition: the converter merges conditions with identical arguments
            out += [f"<condition>leg{i},{('tileAtPosition', 'spriteAtPosition')[i % 2]},{i},0,0,0"
                    for i in range(n)]
            conds_written = True
        if body.startswith("<tile>"):
            body = f"[leg{tiles % n}]" + body
            tiles += 1
        out.append(body)
    if not tiles or not conds_written:
        sys.exit("no tile rules / no <img> line found")
    os.makedirs(dst, exist_ok=True)
    with open(os.path.join(dst, "hires.txt"), "wb") as f:
        f.write("\n".join(out).encode("utf-8", "surrogateescape"))
    print(f"{dst}/hires.txt: {n} conditions on {tiles} tile rules")
    return 0


if __name__ == "__main__":
    sys.exit(main())
