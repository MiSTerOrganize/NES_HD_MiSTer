"""Negative control for the cache unit test (tb_cache.cpp): each mutant of hd3_rcache.sv or
hd3_ccache.sv must FAIL it.

A test never seen to fail proves nothing. Each mutant is one plausible bug; every anchor must
occur exactly once in its file, so a stale anchor fails loudly instead of building an
unmutated "mutant". The unmutated caches are built and run first and must PASS.

usage: python neg_cache.py [mutant name substring]
"""
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RTL_DIR = os.path.normpath(os.path.join(HERE, "..", "..", "rtl", "hdpack"))
FILES = {"r": "hd3_rcache.sv", "c": "hd3_ccache.sv"}

# name: (file key, anchor, replacement)
MUTANTS = {
    "rcache: flush does not invalidate":
        ("r", "\tif (flush) vld <= 0;", "\tif (1'b0) vld <= 0;"),
    "rcache: hit ignores the tag":
        ("r", "if (!byp_r && vld[set_r] && tag_q == tag_r) begin", "if (!byp_r && vld[set_r]) begin"),
    "rcache: answers with the wrong beat of the line":
        ("r", "if (beat == addr_r[5:3]) q <= rd_data;", "if (beat == 3'd0) q <= rd_data;"),
    "rcache: answers in the last fill beat (no settle clock)":
        ("r", "\t\t\tif (!byp_r) vld[set_r] <= 1;\n\t\t\tst     <= S_HIT;",
              "\t\t\tif (!byp_r) vld[set_r] <= 1;\n\t\t\tack <= 1;\n\t\t\tst     <= S_IDLE;"),
    # the uncached (byp) read the renderer uses for frame records (8k); tb_cache.cpp checks it
    # against an exact model of the lines, which is what makes the tag/hit mutants observable
    "rcache: byp read hits the cache":
        ("r", "if (!byp_r && vld[set_r] && tag_q == tag_r)", "if (vld[set_r] && tag_q == tag_r)"),
    "rcache: byp read writes the line's data":
        ("r", "dat_we <= !byp_r;", "dat_we <= 1;"),
    "rcache: byp read writes the tag":
        ("r", "tag_we <= !byp_r;", "tag_we <= 1;"),
    "rcache: byp read marks the line valid":
        ("r", "if (!byp_r) vld[set_r] <= 1;", "vld[set_r] <= 1;"),
    "rcache: byp flag not latched with the request":
        ("r", "\t\tbyp_r  <= byp;\n", ""),
    # (no "valid bit kept while refilling" mutant: the caches answer one request at a time, so a
    # line is never read mid-fill and its valid bit was never cleared there - removed as dead
    # logic 2026-10-16 when this control showed it unobservable)
    "ccache: flush does not invalidate":
        ("c", "\tif (flush) vld <= 0;", "\tif (1'b0) vld <= 0;"),
    "ccache: hit ignores the tag":
        ("c", "if (vld[set_r] && tag_q == tag_r) begin", "if (vld[set_r]) begin"),
    "ccache: returns the other record of the line":
        ("c", "if (beat[2] == ci_r[0]) q[64 * beat[1:0] +: 64] <= rd_data;",
              "if (beat[2] != ci_r[0]) q[64 * beat[1:0] +: 64] <= rd_data;"),
    "ccache: answers in the last fill beat (no settle clock)":
        ("c", "\t\t\tvld[set_r] <= 1;\n\t\t\tst  <= S_HIT;",
              "\t\t\tvld[set_r] <= 1;\n\t\t\tack <= 1;\n\t\t\tst  <= S_IDLE;"),
    "ccache: reads the wrong record pair from DDR3":
        ("c", "rd_addr <= base + {ci_r[22:1], 3'd0};", "rd_addr <= base + {ci_r[23:1], 2'd0};"),
}

RUNS = [["--gap", "0", "--seed", "1"], ["--gap", "0", "--seed", "2", "--busy", "30"],
        ["--gap", "1", "--seed", "3", "--busy", "20", "--lat", "5"]]


def build(files, odir):
    env = dict(os.environ, OBJ=odir.replace("\\", "/"))
    b = subprocess.run(["sh", os.path.join(HERE, "build_one.sh"), "hd3_cache_tb",
                        os.path.join(HERE, "tb_cache.cpp"), os.path.join(HERE, "hd3_cache_tb.sv"),
                        files["r"], files["c"]], env=env, capture_output=True, text=True)
    return b.returncode == 0, b.stdout[-600:] + b.stderr[-600:]


def suite(odir):
    exe = os.path.join(odir, "tb_cache.exe")
    for args in RUNS:
        try:
            r = subprocess.run([exe, "--n", "60000"] + args, capture_output=True, text=True,
                               timeout=300)
        except subprocess.TimeoutExpired:
            return False, "hung"
        if r.returncode != 0:
            return False, (r.stdout + r.stderr).strip().splitlines()[0][:150]
    return True, "all pass"


def main():
    only = sys.argv[1] if len(sys.argv) > 1 else None
    work = os.path.join(HERE, "obj", "neg_cache")
    os.makedirs(work, exist_ok=True)
    src = {k: open(os.path.join(RTL_DIR, f), encoding="utf-8").read() for k, f in FILES.items()}
    live = {k: os.path.join(RTL_DIR, f) for k, f in FILES.items()}

    base = os.path.join(work, "_baseline")
    shutil.rmtree(base, ignore_errors=True)
    os.makedirs(base)
    ok, log = build(live, base)
    if not ok:
        print("BUILD FAILED [baseline]\n" + log)
        return 2
    passed, why = suite(base)
    print("baseline: " + why, flush=True)
    if not passed:
        print("FAIL: the unmutated caches do not pass - fix that before trusting the control")
        return 2

    caught, missed = 0, []
    for name, (k, old, new) in MUTANTS.items():
        if only and only not in name:
            continue
        n = src[k].count(old)
        if n != 1:
            print(f"ANCHOR ERROR [{name}]: found {n} times")
            return 2
        tag = "".join(ch if ch.isalnum() else "_" for ch in name)[:60]
        mdir = os.path.join(work, tag)
        shutil.rmtree(mdir, ignore_errors=True)
        os.makedirs(mdir)
        files = dict(live)
        files[k] = os.path.join(mdir, FILES[k])
        with open(files[k], "w", encoding="utf-8", newline="\n") as f:
            f.write(src[k].replace(old, new))
        ok, log = build(files, mdir)
        if not ok:
            print(f"BUILD FAILED [{name}]\n{log}")
            return 2
        passed, why = suite(mdir)
        if passed:
            missed.append(name)
            print(f"MISSED  {name}", flush=True)
        else:
            caught += 1
            print(f"CAUGHT  {name}  ({why})", flush=True)
    total = len([m for m in MUTANTS if not only or only in m])
    print(f"{caught}/{total} mutants caught")
    for m in missed:
        print(f"  not caught: {m}")
    return 0 if not missed else 1


if __name__ == "__main__":
    sys.exit(main())
