"""Negative controls for the loader's overflow window and size limit (run_loader_window.sh).

    python tools/sim3/neg_loader_window.py        (exit 0 = every mutant caught)

Each mutant replaces the n-th occurrence of an anchor in a copy of hd3_loader.sv (the anchor
must occur exactly `count` times, so a stale anchor fails loudly) and must make the window test
fail.
"""
import os, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
RTL = os.path.join(ROOT, "rtl", "hdpack", "hd3_loader_stream.sv")

# (name, anchor, replacement, expected occurrences, which occurrence to replace)
M = [
    ("window boundary >= -> >", "fq >= MAX_BYTES[28:3]", "fq > MAX_BYTES[28:3]", 1, 0),
    ("overflow offset off by a qword", "OVF_Q + 25'(fq - MAX_BYTES[28:3])",
     "OVF_Q + 25'(fq - MAX_BYTES[28:3]) + 25'd1", 1, 0),
    ("audio section not exempt", "(cnt[8:3] != 6'd31 && sec_top > {1'b0, MAX_BYTES})",
     "(sec_top > {1'b0, MAX_BYTES})", 1, 0),
    ("window check dropped", "(cnt[8:3] != 6'd31 && sec_top > {1'b0, MAX_BYTES})", "1'b0", 1, 0),
    ("section 14 exempt instead of 15", "cnt[8:3] != 6'd31", "cnt[8:3] != 6'd30", 1, 0),
    ("size limit not refused", "(w_size > MAX_TOTAL)                         ? 4'd6 :",
     "1'b0 ? 4'd6 :", 1, 0),
    ("final flush always in the main window", "wr_hi   <= f_hi;", "wr_hi   <= 1'b0;", 2, 1),
    ("regular writes always in the main window", "wr_hi   <= f_hi;", "wr_hi   <= 1'b0;", 2, 0),
]


def main():
    src = open(RTL, encoding="utf-8").read()
    work = tempfile.mkdtemp(prefix="neg_lwin_")
    missed = []
    for i, (name, old, new, cnt, which) in enumerate(M, 1):
        n = src.count(old)
        if n != cnt:
            print("%d %-42s ANCHOR MATCHES %d, expected %d" % (i, name, n, cnt))
            missed.append(i)
            continue
        parts = src.split(old)
        mutated = old.join(parts[:which + 1]) + new + old.join(parts[which + 1:])
        f = os.path.join(work, "hd3_loader_m%d.sv" % i)
        open(f, "w", encoding="utf-8").write(mutated)
        env = dict(os.environ, LOADER_RTL=f.replace("\\", "/"),
                   OBJ=os.path.join(work, "o%d" % i).replace("\\", "/"))
        p = subprocess.run(["sh", os.path.join(HERE, "run_loader_window.sh")], env=env,
                           capture_output=True, text=True)
        out = (p.stdout + p.stderr).strip().splitlines()
        fails = [l for l in out if l.startswith("FAIL") or "write" in l and "window" in l
                 or "below" in l]
        if p.returncode:
            print("%d %-42s CAUGHT  %s" % (i, name, (fails or out or ["?"])[0][:100]))
        else:
            print("%d %-42s MISSED" % (i, name))
            missed.append(i)
        sys.stdout.flush()
    shutil.rmtree(work, ignore_errors=True)
    print("missed: %s" % (missed or "none"))
    return 1 if missed else 0


sys.exit(main())
