"""Negative control for the hd_watch unit test: each mutant of the RTL must FAIL tb_watch.

Each anchor must occur exactly once in the source, so a stale anchor fails loudly instead of
producing an unmutated "mutant" that passes. A mutant is caught if tb_watch fails on any of
the seeds (some defects only show when a write lands on a watched address mid-snapshot).

usage: python neg_watch.py
"""
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
RTL = os.path.join(ROOT, "rtl", "hdpack", "hd_watch.sv")
SEEDS = ["1", "2", "3"]

MUTANTS = {
    "no freeze at the snapshot":
        ("frozen  <= 1;", "frozen  <= 0;"),
    "CPU writes bypass the FIFO while frozen":
        ("wire        c_buf  = frozen || c_cnt != 0;", "wire        c_buf  = c_cnt != 0;"),
    "FIFO drained (and dropped) while frozen":
        ("if (!frozen && c_cnt != 0) cr_p <= cr_p + 1'd1;", "if (c_cnt != 0) cr_p <= cr_p + 1'd1;"),
    "palette $10/$14/$18/$1C not mirrored":
        ("5'h13) == 5'h10)", "5'h13) == 5'h1F)"),
    "nametable mapping read live, not latched at dot 0":
        ("nt_find(s_qmap[e[11:10]])", "nt_find(qmap[e[11:10]])"),
    "savestate writes may claim nametable slots":
        ("else if (!pw_e[31]) begin", "else begin"),
    "value bank ignored":
        ("s_bank  <= bank;", "s_bank  <= 1'b0;"),
    "PRG-RAM page never learned (savestate PRG-RAM writes lost)":
        ("if (c_acc && cpu_a[15:13] == 3'b011) begin", "if (1'b0) begin"),
    "registers read as RAM":
        ("3'b001, 3'b010: kind = 3'd3;", "3'b001, 3'b010: kind = 3'd0;"),
}


def main():
    with open(RTL, encoding="utf-8") as f:
        src = f.read()
    work = os.path.join(HERE, "obj", "neg_watch")
    os.makedirs(work, exist_ok=True)
    caught = 0
    for name, (old, new) in MUTANTS.items():
        n = src.count(old)
        if n != 1:
            print(f"ANCHOR ERROR [{name}]: found {n} times")
            return 2
        tag = "".join(c if c.isalnum() else "_" for c in name)
        mdir = os.path.join(work, tag)
        shutil.rmtree(mdir, ignore_errors=True)
        os.makedirs(mdir)
        mrtl = os.path.join(mdir, "hd_watch.sv")
        with open(mrtl, "w", encoding="utf-8", newline="\n") as f:
            f.write(src.replace(old, new))
        env = dict(os.environ, OBJ=mdir.replace("\\", "/"))
        b = subprocess.run(["sh", os.path.join(HERE, "build_one.sh"), "hd_watch",
                            os.path.join(HERE, "tb_watch.cpp").replace("\\", "/"), mrtl.replace("\\", "/")],
                           env=env, capture_output=True, text=True)
        if b.returncode:
            print(f"BUILD FAILED [{name}]\n{b.stdout[-800:]}{b.stderr[-800:]}")
            return 2
        failed = False
        for s in SEEDS:
            r = subprocess.run([os.path.join(mdir, "tb_watch.exe"), "--seed", s], capture_output=True, text=True)
            if r.returncode != 0:
                failed = True
                break
        print(f"{'CAUGHT' if failed else 'MISSED'}  {name}")
        caught += failed
    print(f"{caught}/{len(MUTANTS)} mutants caught")
    return 0 if caught == len(MUTANTS) else 1


if __name__ == "__main__":
    sys.exit(main())
