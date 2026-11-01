"""Negative control for the hd3_lookup unit test: each mutant of the RTL must FAIL the check.

A check that has never been seen to fail proves nothing. Each mutation below is a plausible
real bug; the runner copies hd3_lookup.sv with that one change, builds it into its own folder,
runs it on the given packs and requires check_lookup.py to report mismatches. The anchor of
every mutation must occur exactly once in the source, so a stale anchor fails loudly instead
of producing an unmutated "mutant" that passes.

usage: python neg_lookup.py <hdp_dir> <pack> [<pack> ...]
"""
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
RTL = os.path.join(ROOT, "rtl", "hdpack", "hd3_lookup.sv")

MUTANTS = {
    "kind not compared":
        ("rd_data[31:0] == q_hi && rd_data[62] == q_kind", "rd_data[31:0] == q_hi"),
    "probe limit one short":
        ("dec_n || probe == max_probe", "dec_n || probe + 16'd1 >= max_probe"),
    "empty entry does not stop the search":
        ("dec_n = 1; hit_n = 0;                       // empty entry: absent",
         "dec_n = dec_n;"),
    "byte order of the hash input reversed":
        ("key_bytes = {p[7:0],  p[15:8],  p[23:16],  p[31:24],",
         "key_bytes = {p[31:24], p[23:16], p[15:8], p[7:0],"),
    "pick ignores the walk list":
        ("qa_hold[63:32] == 32'd0 && rd_data[31:0] == 32'd0", "qa_hold[63:32] == 32'd0"),
    "rule count off by one":
        ("cnt_n = rd_data[31:0];", "cnt_n = rd_data[31:0] - 32'd1;"),
    # only the --key-only mode can show this one (the list is then read when it must not be)
    "key_only ignored":
        ("if (key_only) begin", "if (1'b0) begin"),
}

# every mutant runs in both modes; it is caught if either mode fails the check
MODES = [[], ["--key-only"]]


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    hdp_dir, packs = sys.argv[1], sys.argv[2:]
    with open(RTL, encoding="utf-8") as f:
        src = f.read()
    work = os.path.join(HERE, "obj", "neg")
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
        mrtl = os.path.join(mdir, "hd3_lookup.sv")
        with open(mrtl, "w", encoding="utf-8", newline="\n") as f:
            f.write(src.replace(old, new))
        env = dict(os.environ, LOOKUP_RTL=mrtl.replace("\\", "/"), OBJ=mdir.replace("\\", "/"),
                   ONLY_LOOKUP="1")
        b = subprocess.run(["sh", os.path.join(HERE, "build.sh")], env=env,
                           capture_output=True, text=True)
        if b.returncode:
            print(f"BUILD FAILED [{name}]\n{b.stdout[-800:]}{b.stderr[-800:]}")
            return 2
        failed = False
        for mode in MODES:
            for p in packs:
                out = os.path.join(mdir, p + "".join(mode) + ".tsv")
                r = subprocess.run([os.path.join(mdir, "tb_lookup.exe"), os.path.join(hdp_dir, p + ".hdp"),
                                    out, "--seed", "7"] + mode, capture_output=True, text=True)
                if r.returncode:            # a hang/timeout in the mutant also counts as caught
                    failed = True
                    break
                c = subprocess.run([sys.executable, "-I", os.path.join(HERE, "check_lookup.py"),
                                    os.path.join(hdp_dir, p + ".hdp"), out] + mode,
                                   capture_output=True, text=True)
                if c.returncode:
                    failed = True
                    break
            if failed:
                break
        print(f"{'CAUGHT' if failed else 'MISSED'}  {name}")
        caught += failed
    print(f"{caught}/{len(MUTANTS)} mutants caught")
    return 0 if caught == len(MUTANTS) else 1


if __name__ == "__main__":
    sys.exit(main())
