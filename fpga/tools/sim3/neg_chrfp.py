"""Negative control for the hd_chrfp unit test: each mutant of the RTL must FAIL tb_chrfp.

Each anchor must occur exactly once in the source, so a stale anchor fails loudly instead of
producing an unmutated "mutant" that passes.

usage: python neg_chrfp.py
"""
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
RTL = os.path.join(ROOT, "rtl", "hdpack", "hd_chrfp.sv")

MUTANTS = {
    "the scanner's clear beats a core write for the port":
        ("if (wr)                  begin dw_en = 1'b1; dw_a = w_tile; dw_d = 1'b1; end\n"
         "\telse if (rs == R_CLEAR)  begin dw_en = 1'b1; dw_a = r_tile; dw_d = 1'b0; end",
         "if (rs == R_CLEAR)       begin dw_en = 1'b1; dw_a = r_tile; dw_d = 1'b0; end\n"
         "\telse if (wr)             begin dw_en = 1'b1; dw_a = w_tile; dw_d = 1'b1; end"),
    "writes during a recompute are lost":
        ("if (wr)                  begin dw_en", "if (wr && rs != R_READ) begin dw_en"),
    "CRC bits taken LSB first":
        ("((x[63] ^ b[i])", "((x[63] ^ b[7-i])"),
    "one byte short":
        ("if (r_byte == 5'd16) rs <= R_DONE;", "if (r_byte == 5'd15) rs <= R_DONE;"),
    "a write does not restart the clean count":
        ("if (wr) clean <= 0;", "if (1'b0) clean <= 0;"),
    "idle after a pass that may include a stale read (NT, not NT+1)":
        ("localparam [TB+1:0] CLEAN_ALL = NT + 1;", "localparam [TB+1:0] CLEAN_ALL = NT;"),
}


def main():
    with open(RTL, encoding="utf-8") as f:
        src = f.read()
    work = os.path.join(HERE, "obj", "neg_chrfp")
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
        mrtl = os.path.join(mdir, "hd_chrfp.sv")
        with open(mrtl, "w", encoding="utf-8", newline="\n") as f:
            f.write(src.replace(old, new))
        env = dict(os.environ, CHRFP_RTL=mrtl.replace("\\", "/"), OBJ=mdir.replace("\\", "/"))
        b = subprocess.run(["sh", os.path.join(HERE, "build.sh")], env=env, capture_output=True, text=True)
        if b.returncode:
            print(f"BUILD FAILED [{name}]\n{b.stdout[-800:]}{b.stderr[-800:]}")
            return 2
        r = subprocess.run([os.path.join(mdir, "tb_chrfp.exe")], capture_output=True, text=True)
        failed = r.returncode != 0
        print(f"{'CAUGHT' if failed else 'MISSED'}  {name}")
        caught += failed
    print(f"{caught}/{len(MUTANTS)} mutants caught")
    return 0 if caught == len(MUTANTS) else 1


if __name__ == "__main__":
    sys.exit(main())
