"""Negative control for the hd_capture unit test: each mutant of the RTL must FAIL tb_capture.

Each anchor must occur exactly once in the source, so a stale anchor fails loudly instead of
producing an unmutated "mutant" that passes.

usage: python neg_capture.py
"""
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
RTL = os.path.join(ROOT, "rtl", "hdpack", "hd_capture.sv")

MUTANTS = {
    "branch B writes the whole pixel":
        ("pxbe = 4'b0001;", "pxbe = 4'b1111;"),
    "header written whole when x = 0 was branch B":
        ("hdr_be0 <= h_a ? 8'hFF : 8'hF8;", "hdr_be0 <= 8'hFF;"),
    "pre-render fetches not routed to line 0":
        ("if (line_pre)                               build_line <= 9'd0;",
         "if (1'b0)                                   build_line <= 9'd0;"),
    "fingerprint taken a clock early":
        ("if (ent_st == 2'd1) ent_st <= 2'd2;", "if (ent_st == 2'd1) begin ent_qb <= chr_ram ? fp_q : 64'd0; ent_st <= 2'd3; end"),
    "span count misses the fetch on the line_done clock":
        ("hdr_d0  <= {line_y[7:0], spr_n, sprv_n, span_n,",
         "hdr_d0  <= {line_y[7:0], spr_n, sprv_n, cnt_span,"),
    "BG colour read from the wrong palette":
        ("pidx = {px_bgc[3:2], cidx};", "pidx = {2'b00, cidx};"),
    "FIFO full test done in 32 bits":
        ("wire          ffull  = fcount[FD];", "wire          ffull  = (fwp - frp) == (1 << FD);"),
    "frame buffer not alternated":
        ("wire [27:0] buf_base = REC_BASE + (frame_num[0] ? 28'h100000 : 28'h0);",
         "wire [27:0] buf_base = REC_BASE;"),
}


def main():
    with open(RTL, encoding="utf-8") as f:
        src = f.read()
    work = os.path.join(HERE, "obj", "neg_capture")
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
        mrtl = os.path.join(mdir, "hd_capture.sv")
        with open(mrtl, "w", encoding="utf-8", newline="\n") as f:
            f.write(src.replace(old, new))
        env = dict(os.environ, CAPTURE_RTL=mrtl.replace("\\", "/"), OBJ=mdir.replace("\\", "/"))
        b = subprocess.run(["sh", os.path.join(HERE, "build.sh")], env=env, capture_output=True, text=True)
        if b.returncode:
            print(f"BUILD FAILED [{name}]\n{b.stdout[-800:]}{b.stderr[-800:]}")
            return 2
        r = subprocess.run([os.path.join(mdir, "tb_capture.exe")], capture_output=True, text=True)
        failed = r.returncode != 0
        print(f"{'CAUGHT' if failed else 'MISSED'}  {name}")
        caught += failed
    print(f"{caught}/{len(MUTANTS)} mutants caught")
    return 0 if caught == len(MUTANTS) else 1


if __name__ == "__main__":
    sys.exit(main())
