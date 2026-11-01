"""Negative control for test_exspr.py: build fullsim with one deliberate defect in the extra-sprite
tap at a time and require test_exspr.py to FAIL on each.

  m1_no_extra        hd_stage2 drops extra entries (the record has 8 sprites per line)
                     -> SD composite and colour checks fail on the extra sprites' pixels
  m2_no_plane_clear  the extra entry keeps the HIGH-plane CHR address
                     -> check_record 7 (sprite identity); invisible to the SD composite
  m3_no_copy_rule    extra entry 0 stays valid when it is the core's copy of main sprite 7
                     -> check_record 8; invisible to the SD composite
  m4-m8, m10 (8h)    hd_nolimit not forcing extras; the core's heuristic kept; Mesen's run
                     keyed on y alone; masking at 7 or at 9 instead of 8; a run not restarted
                     at a new position -> the per-line counts

Each mutant: snapshot the source file's bytes, apply one replacement (exactly one match),
build, test, restore the bytes (never from git). The real tree is rebuilt at the end.
usage: python tools/fullsim/neg_exspr.py
exit 0 = every mutant caught
"""
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
TAP = os.path.join(ROOT, "rtl", "hdpack", "hd_tap.sv")
ST2 = os.path.join(ROOT, "rtl", "hdpack", "hd_stage2.sv")
PPU = os.path.join(ROOT, "rtl", "ppu.sv")

MUTANTS = [
    ("m1_no_extra", ST2, ".spr_we      (tap[31] | tap[352]),", ".spr_we      (tap[31]),"),
    ("m2_no_plane_clear", TAP, "x_lin <= chr_lin & ~22'd8;", "x_lin <= chr_lin;"),
    ("m3_no_copy_rule", TAP, "\t\t\t\tx0_hold[54] <= 1'b0;", "\t\t\t\tx0_hold[54] <= x0_hold[54];"),
    # 8h: an HD pack's disableSpriteLimit (hd_nolimit, fullsim --nolimit)
    ("m4_nolimit_not_forcing", PPU, "wire ex_on = extra_sprites | hd_nolimit;", "wire ex_on = extra_sprites;"),
    ("m5_core_rule_kept", PPU, "assign masked_sprites = mesen_limit ? mx_block : &repeat_count;",
     "assign masked_sprites = &repeat_count;"),
    ("m6_run_by_y_only", PPU, "if (mx_have && {mx_y, mx_x} == mx_last) begin",
     "if (mx_have && mx_y == mx_last[15:8]) begin"),
    ("m7_masks_at_7", PPU, "if (mx_run == 4'd7) mx_block <= 1;", "if (mx_run == 4'd6) mx_block <= 1;"),
    ("m8_masks_at_9", PPU, "if (mx_run == 4'd7) mx_block <= 1;", "if (mx_run == 4'd8) mx_block <= 1;"),
    # (no pre-render mutant: an explicit pre-render block was dead logic - extras are only copied
    # while `evaluating`, which excludes the pre-render line - and was removed after this control
    # proved it unobservable: line 0 records no valid extras with or without it)
    ("m10_run_not_restarted", PPU, "\t\t\t\t\t\tmx_run <= 4'd1;", "\t\t\t\t\t\tmx_run <= mx_run;"),
]


def build():
    r = subprocess.run(["sh", os.path.join(HERE, "build.sh")], cwd=ROOT, capture_output=True, text=True)
    if r.returncode:
        sys.exit("build failed:\n" + (r.stdout + r.stderr)[-2000:])


def main():
    work = os.path.join(HERE, "out", "neg_exspr")
    os.makedirs(work, exist_ok=True)
    missed = 0
    for name, path, old, new in MUTANTS:
        orig = open(path, "rb").read()
        txt = orig.decode("utf-8")
        if txt.count(old) != 1:
            sys.exit(f"{name}: anchor found {txt.count(old)} times")
        try:
            open(path, "wb").write(txt.replace(old, new).encode("utf-8"))
            build()
            exe = os.path.join(work, f"fullsim_{name}.exe")
            shutil.copy(os.path.join(HERE, "obj", "fullsim.exe"), exe)
        finally:
            open(path, "wb").write(orig)
        if open(path, "rb").read() != orig:
            sys.exit(f"{name}: source not restored")
        r = subprocess.run([sys.executable, "-I", os.path.join(HERE, "test_exspr.py"), "--exe", exe,
                            "--work", os.path.join(work, name), "--frames", "5"], capture_output=True, text=True)
        caught = r.returncode != 0
        missed += not caught
        print(f"{'CAUGHT' if caught else 'MISSED'} {name}")
    build()
    print(f"{len(MUTANTS) - missed}/{len(MUTANTS)} caught")
    return 1 if missed else 0


if __name__ == "__main__":
    sys.exit(main())
