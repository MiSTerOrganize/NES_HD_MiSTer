"""Negative control for hd3_add (8a additions): each mutant must FAIL one of the run_add.sh
suites (tb_add.exe + check_add.py, pixel by pixel against the lane model). The real RTL must
pass all of them first. Anchors must occur exactly once.

A mutant is built with NL=64 and run through the NL=64 suites (stopping at the first
failure); only a mutant that passes all of them is also built with NL=16 for the overflow
suites, so the target-line limit is covered without building every mutant twice.

usage: python neg_add_rtl.py [testdata dir] [--rtl FILE] [--only NAME|NAME] [--jobs N]
"""
import concurrent.futures as cf
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
P = os.path.normpath(os.path.join(HERE, "..", ".."))
T = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else \
    os.path.normpath(os.path.join(P, "..", "NES_HDPack_testdata"))
WORK = os.path.join(HERE, "obj", "neg_add")
RTL = os.path.join(P, "rtl", "hdpack")

MUTANTS = {
    "BG run continued across a tile":
        ("bopen && b_cl != 3'd7 && q_c", "bopen && q_c"),
    "BG run palette not compared":
        ("(spal[q_sl] == spal[b_sl] &&", "("),
    "lanes sorted largest key first":
        ("(!hb || ck < bk)", "(!hb || ck > bk)"),
    "sort key ignores the source rank":
        ("{l_ndx[16:0], src_k, e_idx,", "{l_ndx[16:0], 3'd0, e_idx,"),
    "horizontal mirror not applied to ox":
        ("dxs  = src_hm ? -ox_s : ox_s;", "dxs  = ox_s;"),
    "vertical mirror not applied to oy":
        ("dys  = src_vm ? -oy_s : oy_s;", "dys  = oy_s;"),
    "left clip does not move the start":
        ("l_x0  = (txs < 0) ? 8'd0 : txs[7:0];", "l_x0  = txs[7:0];"),
    "left clip does not advance the column":
        ("l_c0  = run_c0 + l_dc[2:0];", "l_c0  = run_c0;"),
    "lanes below line 239 kept":
        ("tys < 18'sd240 &&", "tys < 18'sd256 &&"),
    "process_bg ignores a scroll change":
        ("(ys3 + y[2:0]) == 3'd0 || tmpv != q0[14:0])", "(ys3 + y[2:0]) == 3'd0)"),
    "process_bg not carried by a BG hit":
        ("scan_bg <= pbg;", "scan_bg <= 0;"),
    "rank counts later fetches too":
        ("if (i < jj && v[i]) begin", "if (i != jj && v[i]) begin"),
    "4-sprite cap ignored":
        ("if (shown && rk_cur < 5'd4) begin", "if (shown) begin"),
    "sprites-shown bit ignored":
        ("if (shown && rk_cur < 5'd4) begin", "if (rk_cur < 5'd4) begin"),
    "pixel (0,0) takes lanes at any x":
        ("vlane[7:0] == 8'd0 && vlane[LW-1] == vph", "vlane[LW-1] == vph"),
    "pixel (0,0) lane groups swapped":
        ("vlane[7:0] == 8'd0 && vlane[LW-1] == vph", "vlane[7:0] == 8'd0 && vlane[LW-1] != vph"),
    "from-line-239 flag on the wrong line":
        ("{y == 9'd239, src_bgp,", "{y == 9'd238, src_bgp,"),
    "hm and vm swapped in the lane":
        ("src_bgp, src_vm, src_hm, src_row,", "src_bgp, src_hm, src_vm, src_row,"),
    "target-line limit not flagged":
        ("if (cr_q == NL[6:0]) ovf <= 1;", "if (1'b0) ovf <= 1;"),
    "source-line limit not flagged":
        ("if (nl == NB[6:0]) ovf <= 1;", "if (1'b0) ovf <= 1;"),
    "frame sweep never finds an addition":
        ("if (pr_v2 && a_m[16:10] != 7'd0) pr_hit <= 1;", "if (1'b0) pr_hit <= 1;"),
    "frame sweep checks half the records":
        ("if (pr_i < r_nrec) begin", "if (pr_i < (r_nrec >> 1)) begin"),
    "abort ends with bursts outstanding":
        ("S_ABT: if (!rd_req && outst == 4'd0 && !st_plan) st <= S_FIN;", "S_ABT: st <= S_FIN;"),
    "abort ignored":
        ("if (busy && abort && st != S_ABT", "if (1'b0 && abort && st != S_ABT"),
    "ovf not cleared at a new frame":
        ("\t\tbusy <= 1;\n\t\tovf  <= 0;", "\t\tbusy <= 1;"),
    "line 240 not cleared":
        ("if (cy == 9'd240) begin", "if (cy == 9'd239) begin"),
    "fetch area not read for sprite sources":
        ("st_b0    <= need_px ? 5'd0 : 5'd4;", "st_b0    <= 5'd4;"),
    "span area not read for BG sources":
        ("st_nb    <= any_bg ? 5'd29 : 5'd20;", "st_nb    <= 5'd20;"),
    "pixel pairs stored in the wrong order":
        ("pmw_a <= {bj_p[3:0], bb};", "pmw_a <= {bj_p[3:0], ~bb};"),
}

# Mutants proven to leave every reader's list unchanged (not run; the reason is the proof):
EQUIVALENT = {
    "sort key ignores the addition index":
        "lanes with equal (-dx, rank) from DIFFERENT sources of one source line cover disjoint "
        "target pixels (distinct source pixels, same dx, so the order between them never shows); "
        "lanes from ONE source are emitted in its merged-list order, which hd3_dict builds in "
        "file order (= addition index order), and the selection sort keeps emission order on "
        "ties (strict '<'). So the index term only re-confirms an order that is already there.",
}

z2 = "0:0300 1:0420 0:0700 1:1000"
cv = "0:0250 1:0450 0:0700 1:1000 0:1300"
STD = "--gap 25 --busy 40 --lat 60"
OVL = STD + " --overlap"
# (name, pack, game_ram, recdir, frames, tb args); most discriminating first
SUITES = [
    ("cvs", "obj/dict/p002_addt.hdp", 1, "rec_cv", cv, STD + " --seed 13"),
    ("z2e", "obj/dict/a057_edge.hdp", 0, "rec_z2edge", "0:0700 1:0700", STD + " --seed 53"),
    ("z2srcl", "obj/dict/a057_srcl.hdp", 0, "rec_z2", "0:0700 1:0700", STD + " --seed 61"),
    ("z2rep", "obj/dict/a057_addt.hdp", 0, "rec_z2",
     "0:0300 0:0420 0:0700 0:0700 0:0420 0:1000 0:1000 0:0420", STD + " --seed 59"),
    ("z2s", "obj/dict/a057_addt.hdp", 0, "rec_z2", z2, STD + " --seed 7"),
    ("cvsab", "obj/dict/p002_addt.hdp", 1, "rec_cv", cv,
     STD + " --abort 0:3000 --abort 2:200000 --abort 4:1 --seed 43"),
    ("z2tab", "obj/dict/a057_tab.hdp", 0, "rec_z2", z2, OVL + " --pipelined --abort 2:20000 --seed 47"),
    ("z2t", "obj/dict/a057_tab.hdp", 0, "rec_z2", z2, STD + " --seed 5"),
    ("cvt", "obj/dict/p002_tab.hdp", 1, "rec_cv", cv, STD + " --seed 11"),
    ("cvsov", "obj/dict/p002_addt.hdp", 1, "rec_cv", cv, OVL + " --seed 17"),
    ("z2mix", "obj/dict/h_z2_mixed_t.hdp", 0, "rec_z2", z2, STD + " --seed 23"),
    ("cvmix", "obj/dict/h_cv_mixed_t.hdp", 1, "rec_cv", cv, STD + " --seed 29"),
]
SMALL = [
    ("z2s16", "obj/dict/a057_addt.hdp", 0, "rec_z2", z2, STD + " --seed 31"),
    ("cvs16", "obj/dict/p002_addt.hdp", 1, "rec_cv", cv, OVL + " --seed 37"),
    ("z2t16", "obj/dict/a057_tab.hdp", 0, "rec_z2", z2, OVL + " --seed 41"),
]


def build(rtl, mdir, nl):
    os.makedirs(mdir, exist_ok=True)
    obj = os.path.join(mdir, f"obj{nl}")
    files = ["hd3_add_tb.sv", os.path.join(RTL, "hd3_dict.sv"), os.path.join(RTL, "hd3_lookup.sv"), rtl]
    r = subprocess.run(["sh", "build_one.sh", "hd3_add_tb", "tb_add.cpp"] + files, cwd=HERE,
                       env=dict(os.environ, OBJ=obj, VFLAGS=f"-GNL={nl}"),
                       capture_output=True, text=True)
    exe = os.path.join(obj, "tb_add.exe")
    if r.returncode != 0 or not os.path.exists(exe):
        return None, (r.stdout + r.stderr)[-400:]
    return exe, ""


def run(exe, mdir, suites, stop_on_fail):
    out = []
    for name, pack, gr, rec, frames, extra in suites:
        tsv = os.path.join(mdir, f"{name}.tsv")
        args = [exe, pack, tsv, "--game-ram", str(gr)]
        nums = []
        for bf in frames.split():
            b, f = bf.split(":")
            args += ["--frame", f"{b}:{T}/{rec}/rec_{f}.bin"]
            nums.append(str(int(f)))
        try:
            r = subprocess.run(args + extra.split(), cwd=HERE, capture_output=True, text=True,
                               timeout=3600)
        except subprocess.TimeoutExpired:
            out.append((name, "testbench hang"))
            if stop_on_fail:
                return out
            continue
        if r.returncode != 0:
            out.append((name, "testbench error: " + (r.stdout + r.stderr).strip()[-120:]))
        else:
            c = subprocess.run([sys.executable, "-I", "check_add.py", tsv, pack, f"{T}/{rec}"] + nums,
                               cwd=HERE, capture_output=True, text=True)
            last = c.stdout.strip().splitlines()[-1] if c.stdout.strip() else c.stderr[-120:]
            out.append((name, "pass" if c.returncode == 0 else last))
        if stop_on_fail and out[-1][1] != "pass":
            return out
    return out


def mutant(name, src):
    old, new = MUTANTS[name]
    if src.count(old) != 1:
        return name, f"ANCHOR FOUND {src.count(old)} TIMES"
    mdir = os.path.join(WORK, f"m{list(MUTANTS).index(name):02d}")
    os.makedirs(mdir, exist_ok=True)
    mrtl = os.path.join(mdir, "hd3_add.sv")
    open(mrtl, "w", encoding="utf-8", newline="").write(src.replace(old, new))
    for nl, suites in ((64, SUITES), (16, SMALL)):
        exe, err = build(mrtl, mdir, nl)
        if exe is None:
            # a build failure is a harness problem, never a catch
            return name, "BUILD FAILED: " + (err.strip().splitlines()[-1] if err.strip() else "?")
        bad = [r for r in run(exe, mdir, suites, True) if r[1] != "pass"]
        if bad:
            return name, f"CAUGHT by {bad[0][0]}: {bad[0][1]}"
    return name, "MISSED (passes all suites)"


def main():
    rtl = sys.argv[sys.argv.index("--rtl") + 1] if "--rtl" in sys.argv else os.path.join(RTL, "hd3_add.sv")
    only = sys.argv[sys.argv.index("--only") + 1].split("|") if "--only" in sys.argv else None
    jobs = int(sys.argv[sys.argv.index("--jobs") + 1]) if "--jobs" in sys.argv else 3
    src = open(rtl, encoding="utf-8", newline="").read()
    os.makedirs(WORK, exist_ok=True)
    if not only:
        base = os.path.join(WORK, "_baseline")
        res = []
        for nl, suites in ((64, SUITES), (16, SMALL)):
            exe, err = build(rtl, base, nl)
            if exe is None:
                print("baseline does not build", err)
                return 2
            res += run(exe, base, suites, False)
        fails = [r for r in res if r[1] != "pass"]
        print(f"baseline: {len(res) - len(fails)}/{len(res)} suites pass", flush=True)
        if fails:
            for r in fails:
                print("  FAIL", r)
            return 1
    names = only if only else list(MUTANTS)
    missed = 0
    with cf.ThreadPoolExecutor(jobs) as ex:
        for name, verdict in ex.map(lambda n: mutant(n, src), names):
            print(("CAUGHT  " if verdict.startswith("CAUGHT") else "MISSED  ") + name + "  " + verdict,
                  flush=True)
            missed += not verdict.startswith("CAUGHT")
    print(f"{len(names) - missed}/{len(names)} mutants caught")
    for name, why in EQUIVALENT.items():
        print(f"EQUIVALENT (not run)  {name}: {why}")
    return 1 if missed else 0


if __name__ == "__main__":
    sys.exit(main())
