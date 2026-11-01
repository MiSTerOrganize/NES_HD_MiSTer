"""Extra-sprite (16 per line) test of the stage-2 HD tap, through the whole core (fullsim).

Writes the two test cartridges (make_exspr_rom.py: 8x8 and 8x16 sprites), runs fullsim --rec
on each with the core's "Extra sprites" option on, and on the 8x8 one with it off, then checks
every saved frame with check_record.py (incl. 7 sprite identity and 8 the 16-sprite copy rule)
and hdref.py --sd-check (the SD composite rebuilt from the record must equal the PPU output).
Also checks the per-line counts the test cartridge implies:
  line 40  (16 sprites):         16 fetches, 8 main + 7 extra valid (extra 0 = the core's copy
                                 of main 7, recorded not valid; the 16th sprite is never loaded)
  line 120 (12 sprites):         8 main + 4 extra valid
  line 180 (10 identical):       8 main + 0 extra (the core's masked_sprites case)
  option off:                    8 fetches on every line

usage: python tools/fullsim/test_exspr.py [--exe FULLSIM] [--work DIR]
   (default exe tools/fullsim/obj/fullsim.exe; build it with tools/fullsim/build.sh)
negative control: tools/fullsim/neg_exspr.py
exit 0 = everything passes
"""
import argparse
import os
import struct
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))

EXPECT_ON = {5: (16, 8, 1), 40: (16, 8, 7), 80: (16, 8, 2), 120: (16, 8, 4), 180: (16, 8, 0)}
EXPECT_OFF = {5: (8, 8, 0), 40: (8, 8, 0), 80: (8, 8, 0), 120: (8, 8, 0), 180: (8, 8, 0)}
# --nolimit (an HD pack's disableSpriteLimit): extras forced on whatever the OSD option says,
# masked by Mesen's adaptive rule - line 80 (8 at one position) masked, line 180 (same tile at
# different x) and line 5 (7 at one position) not; line 0 (the pre-render line's evaluation)
# gets no valid extras (Mesen loads none there). The OSD option's line 0 is the core's own.
EXPECT_NOLIMIT = {5: (16, 8, 1), 40: (16, 8, 7), 80: (16, 8, 0), 120: (16, 8, 4), 180: (16, 8, 2)}
NOLIMIT_LINE0_EXTRAS = 0


def counts(rec, y):
    hoff = 0x40000 + y * 2048
    n = (struct.unpack_from("<Q", rec, hoff)[0] >> 48) & 0xFF
    val = [(struct.unpack_from("<Q", rec, hoff + 640 + i * 16)[0] >> 54) & 1 for i in range(min(n, 64))]
    return n, sum(val[:8]), sum(val[8:])


def run_case(exe, work, rom, ex, frames, expect, nolimit=False):
    out = os.path.join(work, f"{os.path.basename(rom)[:-4]}_{'nolimit' if nolimit else 'on' if ex else 'off'}")
    os.makedirs(out, exist_ok=True)
    cmd = [exe, "--rom", rom, "--frames", str(max(frames)), "--save", ",".join(map(str, frames)),
           "--rec", "--palette", os.path.join(ROOT, "Palette", "Kitrinx34.pal"), "--out", out]
    if ex:
        cmd.append("--ex-sprites")
    if nolimit:
        cmd.append("--nolimit")
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        print(f"  fullsim failed rc={r.returncode}: {(r.stdout + r.stderr)[-300:]}")
        return False
    ok = True
    r = subprocess.run([sys.executable, "-I", os.path.join(HERE, "check_record.py"), out, "--rom", rom],
                       capture_output=True, text=True)
    print("  " + r.stdout.strip().splitlines()[-1])
    ok &= r.returncode == 0
    for f in frames:
        r = subprocess.run([sys.executable, "-I", os.path.join(ROOT, "tools", "hdref.py"), out,
                            "--frame", str(f), "--sd-check", "--rom", rom], capture_output=True, text=True)
        line = r.stdout.strip().splitlines()[0] if r.stdout.strip() else r.stderr[-200:]
        if r.returncode:
            print("  " + line)
        ok &= r.returncode == 0
        rec = open(os.path.join(out, f"rec_{f:04d}.bin"), "rb").read()
        for y, want in expect.items():
            got = counts(rec, y)
            if got != want:
                print(f"  frame {f} line {y}: fetches/main/extra {got}, expected {want}")
                ok = False
        if nolimit and counts(rec, 0)[2] != NOLIMIT_LINE0_EXTRAS:
            print(f"  frame {f} line 0: {counts(rec, 0)[2]} valid extras, expected none")
            ok = False
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--exe", default=os.path.join(HERE, "obj", "fullsim.exe"))
    ap.add_argument("--work", default=os.path.join(HERE, "out", "exspr"))
    ap.add_argument("--frames", default="4,5,6")
    a = ap.parse_args()
    frames = [int(x) for x in a.frames.split(",")]
    os.makedirs(a.work, exist_ok=True)
    roms = {}
    for name, tall in (("exspr", False), ("exspr_tall", True)):
        roms[name] = os.path.join(a.work, name + ".nes")
        subprocess.run([sys.executable, "-I", os.path.join(HERE, "make_exspr_rom.py"), roms[name]]
                       + (["--tall"] if tall else []), check=True, capture_output=True)
    ok = True
    for name, ex, exp, nl in (("exspr", True, EXPECT_ON, False), ("exspr_tall", True, EXPECT_ON, False),
                              ("exspr", False, EXPECT_OFF, False),
                              ("exspr", False, EXPECT_NOLIMIT, True), ("exspr_tall", False, EXPECT_NOLIMIT, True)):
        print(f"{name} extra sprites {'forced (--nolimit)' if nl else 'on' if ex else 'off'}:")
        r = run_case(a.exe, a.work, roms[name], ex, frames, exp, nl)
        print("  PASS" if r else "  FAIL")
        ok &= r
    print("ALL PASS" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
