"""Negative control for tb_loader_cmd (rtl/hdpack/hd3_loader.sv, the command-driven loader).

Each mutant changes one line of a COPY of the RTL (the anchor must occur exactly once, so a stale
anchor fails loudly) and must make the testbench fail.

usage: python neg_loader_cmd.py PACK.hdp [PACK.hdp ...]      (exit 0 = every mutant caught)
"""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
RTL = os.path.join(ROOT, "rtl", "hdpack", "hd3_loader.sv")

MUTANTS = {
    "power-up command carried out": ("if (!based) begin", "if (1'b0) begin"),
    "repeated command carried out again":
        ("m_dout[47:40] != last_seq) begin", "1'b1) begin"),
    "sequence not answered": ("ack_seq <= cmd_seq;", "ack_seq <= 8'd0;"),
    "size check dropped": ("(cmd_size != w_size)                         ? 4'd5 :", "1'b0 ? 4'd5 :"),
    "section check dropped": ("if (hq >= 6'd16 && sec_err) sec_bad <= 1;", ""),
    "section table length not checked": ("(sec_bad || w_size < 32'h110)", "(sec_bad)"),
    "audio section not exempt": ("(hq != 6'd31 && sec_top > {1'b0, MAX_BYTES})", "(sec_top > {1'b0, MAX_BYTES})"),
    "watch list halves swapped": ("lw_addr <= m_dout[31:0];", "lw_addr <= m_dout[63:32];"),
    "watch list count ignored": ("wn <= wn_new;", "wn <= 9'd256;"),
    "oversized watch list accepted": ("(!wlist_ok)                                  ? 4'd10 :", "1'b0 ? 4'd10 :"),
    "unknown op accepted": ("? 4'd0 : 4'd12;", "? 4'd0 : 4'd0;"),
    "reset does not cancel": ("pack_ok <= 0;\n\t\tst      <= S_IDLE;", "st      <= S_IDLE;"),
    "reset leaves the loader mid-COMMIT": ("\t\tst      <= S_IDLE;\n\tend\nend", "\tend\nend"),
    "header qword 4 read from qword 5": ("6'd4:  begin w_size", "6'd5:  begin w_size"),
    "COMMIT does not clear pack_ok first": ("\t\t\tpack_ok  <= 0;\n", "\n"),
}


def main():
    packs = [p.replace("\\", "/") for p in sys.argv[1:]]
    if not packs:
        print(__doc__)
        return 2
    src = open(RTL, encoding="utf-8").read()
    work = tempfile.mkdtemp(prefix="neg_ldcmd_")
    missed = []
    for i, (name, (old, new)) in enumerate(MUTANTS.items(), 1):
        n = src.count(old)
        if n != 1:
            print(f"ANCHOR ERROR [{name}]: found {n} times")
            return 2
        d = os.path.join(work, f"m{i}")
        os.makedirs(d)
        m = os.path.join(d, "hd3_loader.sv")
        with open(m, "w", encoding="utf-8", newline="\n") as f:
            f.write(src.replace(old, new))
        env = dict(os.environ, OBJ=d.replace("\\", "/"))
        b = subprocess.run(["sh", os.path.join(HERE, "build_one.sh"), "hd3_loader_cmd_tb_top",
                            os.path.join(HERE, "tb_loader_cmd.cpp").replace("\\", "/"),
                            os.path.join(HERE, "hd3_loader_cmd_tb_top.sv").replace("\\", "/"),
                            m.replace("\\", "/")], env=env, capture_output=True, text=True)
        if b.returncode:
            print(f"BUILD FAILED [{name}]\n{b.stdout[-600:]}{b.stderr[-600:]}")
            missed.append(name)
            continue
        try:
            r = subprocess.run([os.path.join(d, "tb_loader_cmd.exe")] + packs,
                               capture_output=True, text=True, timeout=600)
            failed = r.returncode != 0
        except subprocess.TimeoutExpired:
            failed = True
        print(f"{'CAUGHT' if failed else 'MISSED'}  {name}", flush=True)
        if not failed:
            missed.append(name)
    shutil.rmtree(work, ignore_errors=True)
    print(f"{len(MUTANTS) - len(missed)}/{len(MUTANTS)} mutants caught")
    return 1 if missed else 0


if __name__ == "__main__":
    sys.exit(main())
