"""Negative control for the hd3_ddr arbiter unit test (tb_ddr3): every mutant must FAIL.

Each anchor must occur exactly once in rtl/hdpack/hd3_ddr.sv, so a stale anchor fails loudly
instead of producing an unmutated "mutant" that passes. Builds into obj/neg_ddr3/<mutant>.
usage: python tools/sim3/neg_ddr3.py          exit 0 = every mutant caught
"""
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
RTL = os.path.join(ROOT, "rtl", "hdpack", "hd3_ddr.sv")

MUTANTS = {
    "readers' pointer never advances (reader 0 always first)":
        ("rr      <= rnext[KW-1:0];", "rr      <= rr;"),
    "cw never gets its turn while a reader waits":
        ("wire        take_cw = cw_valid && (!rnext[KW] || cw_turn);",
         "wire        take_cw = cw_valid && !rnext[KW];"),
    "returning beat routed to the wrong reader":
        ("rd_valid[k] <= 1;", "rd_valid[(k + 1) % NR] <= 1;"),
    "savestate beats never routed to the savestate channel":
        ("if (rq[rq_rp[QW-1:0]][8]) begin", "if (1'b0) begin"),
    "frame-record byte enables ignored":
        ("cmd_be    <= cw_be;", "cmd_be    <= 8'hFF;"),
    "return-queue room ignored":
        ("pick(rr, rd_req & {NR{rq_room}});", "pick(rr, rd_req);"),
    "16-qword bursts":
        ("cmd_burst <= 8'd8;", "cmd_burst <= 8'd16;"),
    "pack-load write acknowledged but not issued":
        ("			cmd_wr    <= 1;\n			wr_ack    <= 1;", "			wr_ack    <= 1;"),
}


def main():
    src = open(RTL, encoding="utf-8").read()
    work = os.path.join(HERE, "obj", "neg_ddr3")
    os.makedirs(work, exist_ok=True)
    caught = 0
    for name, (old, new) in MUTANTS.items():
        n = src.count(old)
        if n != 1:
            print(f"ANCHOR ERROR [{name}]: found {n} times")
            return 2
        tag = "".join(c if c.isalnum() else "_" for c in name)[:60]
        mdir = os.path.join(work, tag)
        shutil.rmtree(mdir, ignore_errors=True)
        os.makedirs(mdir)
        mrtl = os.path.join(mdir, "hd3_ddr.sv")
        with open(mrtl, "w", encoding="utf-8", newline="\n") as f:
            f.write(src.replace(old, new))
        env = dict(os.environ, OBJ=mdir.replace("\\", "/"))
        b = subprocess.run(["sh", os.path.join(HERE, "build_one.sh"), "hd3_ddr",
                            os.path.join(HERE, "tb_ddr3.cpp").replace("\\", "/"), mrtl.replace("\\", "/")],
                           env=env, capture_output=True, text=True)
        if b.returncode:
            print(f"BUILD FAILED [{name}]\n{b.stdout[-800:]}{b.stderr[-800:]}")
            return 2
        r = subprocess.run([os.path.join(mdir, "tb_ddr3.exe"), "--cycles", "200000"],
                           capture_output=True, text=True, timeout=1800)
        failed = r.returncode != 0
        why = next((l for l in r.stdout.splitlines() if l.startswith("FAIL")), "")
        print(f"{'CAUGHT' if failed else 'MISSED'}  {name}   {why[:90]}")
        caught += failed
    print(f"{caught}/{len(MUTANTS)} mutants caught")
    return 0 if caught == len(MUTANTS) else 1


if __name__ == "__main__":
    sys.exit(main())
