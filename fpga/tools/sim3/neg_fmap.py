"""Negative control for the hd3_fmap unit test: each mutant of the RTL must FAIL run_fmap.sh.

A check that has never been seen to fail proves nothing. Each mutation below is a plausible real
bug; the runner copies hd3_fmap.sv with that one change, builds tb_fmap.exe into its own folder,
runs run_fmap.sh with it and requires a failure (a map mismatch, a testbench error or a hang).
Every anchor must occur exactly once in the source, so a stale anchor fails loudly instead of
producing an unmutated "mutant" that passes. The real RTL is built and run first and must PASS.

usage: python neg_fmap.py <testdata dir> [mutant name substring]
"""
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RTL = os.environ.get("FMAP_RTL") or \
    os.path.normpath(os.path.join(HERE, "..", "..", "rtl", "hdpack", "hd3_fmap.sv"))
BUILD_ONE = os.environ.get("BUILD_ONE") or os.path.join(HERE, "build_one.sh")

MUTANTS = {
    "tap_v ignored for the even pixel":
        ("if (tap_v && t_pix && tap_be[0])", "if (t_pix && tap_be[0])"),
    "even pixel ignores its byte enable":
        ("if (tap_v && t_pix && tap_be[0])", "if (tap_v && t_pix)"),
    "odd pixel takes the even pixel's byte enable":
        ("if (tap_v && t_pix && tap_be[4])", "if (tap_v && t_pix && tap_be[0])"),
    "pixel halves swapped":
        ("pm_e[pw_a] <= tap_d[6:0];", "pm_e[pw_a] <= tap_d[38:32];"),
    "pixel loses the sprites-shown bit":
        ("pm_o[pw_a] <= tap_d[38:32];", "pm_o[pw_a] <= {1'b0, tap_d[37:32]};"),
    "pixel map ignores the bank":
        ("wire [15:0] pw_a = {t_bank, t_q[14:0]};", "wire [15:0] pw_a = {1'b0, t_q[14:0]};"),
    "pixel map sized for 61,440 entries":
        ("reg [6:0] pm_e [65536];", "reg [6:0] pm_e [61440];"),
    "pixel area stops at line 224":
        ("t_q < 17'h07800;", "t_q < 17'h07000;"),
    "record range not checked":
        ("wire        in_rec = rel[27:21] == 7'd0;", "wire        in_rec = 1'b1;"),
    "line blocks past the area not rejected":
        ("t_l[15:8] < 8'd240 && !t_l[16];", "t_l[15:8] < 8'd240;"),
    "span count not capped at 34":
        ("(tap_d[39:32] > 8'd34) ? 6'd34 : tap_d[37:32]", "tap_d[37:32]"),
    "fetch count not capped at 16":
        ("(tap_d[55:48] > 8'd16) ? 5'd16 : tap_d[52:48]", "tap_d[52:48]"),
    "line header taken from the wrong qword":
        ("if (tap_v && t_line && t_o == 8'd0)", "if (tap_v && t_line && t_o == 8'd1)"),
    "line table ignores the bank":
        ("lmem[{t_bank, t_y}] <=", "lmem[{1'b0, t_y}] <="),
    "sprite table stores qword B":
        ("t_o < 8'd112 && !t_f[0];", "t_o < 8'd112 && t_f[0];"),
    "sprite area read from the wrong offset":
        ("wire  [7:0] t_f    = t_o - 8'd80;", "wire  [7:0] t_f    = t_o - 8'd88;"),
    "sprite lane taken from the wrong fetch bits":
        ("t_f[4:1] == gi", "t_f[3:0] == gi"),
    "sprite behind-background bit from the wrong attribute bit":
        ("{tap_d[54], tap_d[51],", "{tap_d[54], tap_d[50],"),
    "sprite table ignores the bank":
        ("m[{t_bank, t_y}] <= sw_d;", "m[{1'b0, t_y}] <= sw_d;"),
    "read bank ignored":
        ("pq_e <= pm_e[{r_bank, p_a}];", "pq_e <= pm_e[{1'b0, p_a}];"),
}


def build(rtl, mdir):
    env = dict(os.environ, OBJ=mdir.replace("\\", "/"))
    b = subprocess.run(["sh", BUILD_ONE, "hd3_fmap", os.path.join(HERE, "tb_fmap.cpp"), rtl],
                       env=env, capture_output=True, text=True)
    return b.returncode == 0, b.stdout[-800:] + b.stderr[-800:]


def suite(mdir, td):
    env = dict(os.environ, EXE=os.path.join(mdir, "tb_fmap.exe").replace("\\", "/"),
               OUT=mdir.replace("\\", "/"))
    for s in ("stream_1.bin", "stream_2.bin"):      # the stream depends only on the seeds
        src = os.path.join(HERE, "obj", "fmap", s)
        if os.path.exists(src) and not os.path.exists(os.path.join(mdir, s)):
            shutil.copy(src, mdir)
    try:
        r = subprocess.run(["sh", os.path.join(HERE, "run_fmap.sh"), td], env=env,
                           capture_output=True, text=True, timeout=900)
    except subprocess.TimeoutExpired:
        return False, "suite hung"
    bad = [ln.strip() for ln in r.stdout.splitlines() if "FAIL" in ln or "failed" in ln or "differ" in ln]
    return r.returncode == 0, "; ".join(bad) if bad else "all pass"


def main():
    if len(sys.argv) not in (2, 3):
        print(__doc__)
        return 2
    td = sys.argv[1]
    only = sys.argv[2] if len(sys.argv) == 3 else None
    src = open(RTL, encoding="utf-8").read()
    work = os.path.join(HERE, "obj", "neg_fmap")
    os.makedirs(work, exist_ok=True)
    base = os.path.join(work, "_baseline")
    shutil.rmtree(base, ignore_errors=True)
    os.makedirs(base)
    ok, log = build(RTL, base)
    if not ok:
        print(f"BUILD FAILED [baseline]\n{log}")
        return 2
    passed, why = suite(base, td)
    print(f"baseline: {why}", flush=True)
    if not passed:
        print("FAIL: the unmutated RTL does not pass - fix that before trusting the control")
        return 2
    caught, missed, run = 0, [], 0
    for idx, (name, (a, b)) in enumerate(MUTANTS.items()):
        if only and only not in name:
            continue
        n = src.count(a)
        if n != 1:
            print(f"ANCHOR ERROR [{name}]: found {n} times: {a[:60]!r}")
            return 2
        run += 1
        # short, unique: a long folder name pushes Verilator's generated paths past Windows'
        # 260-character limit (the build then fails with "Can't write file")
        tag = "%02d_" % idx + "".join(ch if ch.isalnum() else "_" for ch in name)[:24]
        mdir = os.path.join(work, tag)
        shutil.rmtree(mdir, ignore_errors=True)
        os.makedirs(mdir)
        mrtl = os.path.join(mdir, "hd3_fmap.sv")
        with open(mrtl, "w", encoding="utf-8", newline="\n") as f:
            f.write(src.replace(a, b))
        ok, log = build(mrtl, mdir)
        if not ok:
            print(f"BUILD FAILED [{name}]\n{log}")
            return 2
        passed, why = suite(mdir, td)
        if passed:
            missed.append(name)
            print(f"MISSED  {name}", flush=True)
        else:
            caught += 1
            print(f"CAUGHT  {name}  ({why[:160]})", flush=True)
    print(f"{caught}/{run} mutants caught")
    for m in missed:
        print(f"  not caught: {m}")
    return 0 if not missed else 1


if __name__ == "__main__":
    sys.exit(main())
