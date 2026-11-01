"""Negative control for the 8a (additions) part of hd3_dict: each mutant must FAIL one of the
addition suites. The real RTL must pass all of them first. Anchors must occur exactly once.
(neg_dict_rtl.py covers the rest of hd3_dict.)

Suites: the addition-table fixtures in obj/dict (*_t.hdp made by make_heavy_add.py /
make_selffb.py, *_tab / *_addt by hdp3_addtab.py), each checked by check_dict.py against its
dict_golden.py golden. Timing modes: STD; SER1500 (DDR3 latency 1500: the resolver still
injects after the capture ends); LAG1500 (a frame timing-overflows); LAG4000 (frames are
abandoned - tb --allow-abandon, check_dict.py --lag).

usage: python neg_dict_add.py <testdata dir> [--rtl FILE] [--only NAME|NAME] [--jobs N]
"""
import concurrent.futures as cf
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
D = HERE
P = os.path.normpath(os.path.join(HERE, "..", ".."))
T = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else \
    os.path.normpath(os.path.join(P, "..", "NES_HDPack_testdata"))
WORK = os.path.join(HERE, "obj", "neg_dict_add")

MUTANTS = {
    "fallback lists never looked up":
        ("(ad_j == 3'd2 && !fbv)", "(ad_j == 3'd2)"),
    "any-palette lists never looked up":
        ("ad_j[0] ? 32'hFFFFFFFF : r_pal", "r_pal"),
    "fallback lists looked up with the record's own body":
        ("ad_j[1] ? {48'd0, fb[15:0]} : r_body", "r_body"),
    "a fallback equal to the body counted as a fallback":
        ("fb[16] && fb[15:0] != r_body[15:0]", "fb[16]"),
    "merge takes the LARGEST file index first":
        ("hidx[j] < hidx[msel]", "hidx[j] > hidx[msel]"),
    "lists concatenated instead of merged":
        ("(!many || hidx[j] < hidx[msel])", "(!many)"),
    "64-entry buffer refused one entry early":
        ("rd_data[31:0] > ABUF) ad_ovf <= 1;", "rd_data[31:0] >= ABUF) ad_ovf <= 1;"),
    "list longer than the buffer not refused":
        ("if ({25'd0, ad_n} + rd_data[31:0] > ABUF) ad_ovf <= 1;", "if (1'b0) ad_ovf <= 1;"),
    "full pool not refused":
        ("!inj_id[RAW] || ppool[res_bank][10]", "!inj_id[RAW]"),
    "pool refused one entry early":
        ("!inj_id[RAW] || ppool[res_bank][10]", "!inj_id[RAW] || ppool[res_bank] >= 11'd1023"),
    "pool not emptied at a bank's new frame":
        ("ppool[bb]    <= 0;", "ppool[bb]    <= ppool[bb];"),
    "addition overflow carried into the bank's next frame":
        ("fovf_a[bb]   <= 0;", "fovf_a[bb]   <= fovf_a[bb];"),
    "has-additions bit never set":
        ("{29'd0, add_cnt != 7'd0, 34'd0}", "{29'd0, 1'b0, 34'd0}"),
    "entry offsets swapped":
        ("{e_idx, e_oy, e_ox, inj_id[RAW-1:0]}", "{e_idx, e_ox, e_oy, inj_id[RAW-1:0]}"),
    "added key's palette dropped":
        ("inj_key  <= {ab1_q, ab2_q};", "inj_key  <= {32'd0, ab2_q};"),
    "list start not the pool position":
        ("add_start <= ppool[res_bank][9:0];", "add_start <= 10'd0;"),
    "injections sent for bank 0":
        ("inj_bank <= res_bank;", "inj_bank <= 1'b0;"),
    "index cleared while the resolver still injects":
        ("if (add_en) clr_pend <= 1;", "if (1'b0) clr_pend <= 1;"),
    "injection accepted for another bank":
        ("if (inj_bank == fr_bank) begin", "if (1'b1) begin"),
    # NOT a mutant: "injected record given additions of its own" ((add_en && !injm_q) -> add_en)
    # is output-equivalent - the converter refuses chains, so an added key's own lookups always
    # come back empty; the injm test only saves the resolver those lookups
    "list count latched from the wrong half":
        ("al_cnt <= rd_data[31:0];", "al_cnt <= rd_data[63:32];"),
    "list burst address not advanced":
        ("al_q <= al_q + 25'd8;", "al_q <= al_q;"),
    "abandoned frame not retired":
        ("if (!rdone[bb]) tog_r[bb] <= ~tog_r[bb];", "if (1'b0) tog_r[bb] <= ~tog_r[bb];"),
    "walk not restarted at a bank's new frame":
        ("if (rp_ep[res_bank] != ep_d[res_bank]) begin", "if (1'b0) begin"),
    "frame marked done never set":
        ("rdone[res_bank] <= 1;", "rdone[res_bank] <= rdone[res_bank];"),
}

z2 = [f"--frame {b}:{T}/rec_z2/rec_{f}.bin" for b, f in ((0, "0300"), (1, "0420"), (0, "0700"), (1, "1000"))]
z2g = [f"obj/dict/g_z2_{f}.tsv" for f in ("0300", "0420", "0700", "1000")]
# goldens of the self-fallback pack (fallback[b] = b changes the fb column)
z2sfg = [f"obj/dict/gsf_z2_{f}.tsv" for f in ("0300", "0420", "0700", "1000")]
cv = [f"--frame {b}:{T}/rec_cv/rec_{f}.bin" for b, f in ((0, "0250"), (1, "0450"), (0, "0700"), (1, "1000"), (0, "1300"))]
cvg = [f"obj/dict/g_cv_{f}.tsv" for f in ("0250", "0450", "0700", "1000", "1300")]
STD = dict(lat=60, busy=40, overlap=True, lag=False)
SER1500 = dict(lat=1500, busy=90, overlap=False, lag=False)   # resolver injects after capture end
LAG1500 = dict(lat=1500, busy=90, overlap=True, lag=True)     # a frame timing-overflows
LAG4000 = dict(lat=4000, busy=95, overlap=True, lag=True)     # frames are abandoned
SUITES = [  # (name, pack, game_ram, frames, goldens, seed[, mode]); most discriminating first
    ("hz2mixed", "obj/dict/h_z2_mixed_t.hdp", 0, z2, z2g, 17),
    ("hz2selffb", "obj/dict/h_z2_selffb_t.hdp", 0, z2, z2sfg, 17),
    ("hz2dupser", "obj/dict/h_z2_dup_t.hdp", 0, z2, z2g, 23, SER1500),
    ("hz2duplag", "obj/dict/h_z2_dup_t.hdp", 0, z2, z2g, 23, LAG1500),
    ("hz2dupab", "obj/dict/h_z2_dup_t.hdp", 0, z2, z2g, 23, LAG4000),
    ("hcvdupser", "obj/dict/h_cv_dup_t.hdp", 1, cv, cvg, 29, SER1500),
    ("hz2cap", "obj/dict/h_z2_cap_t.hdp", 0, z2, z2g, 17),
    ("hz2pool1025", "obj/dict/h_z2_pool1025_t.hdp", 0, z2, z2g, 17),
    ("hz2pool1024", "obj/dict/h_z2_pool1024_t.hdp", 0, z2, z2g, 17),
    ("hcvmixed", "obj/dict/h_cv_mixed_t.hdp", 1, cv, cvg, 19),
    ("z2tab", "obj/dict/a057_tab.hdp", 0, z2, z2g, 5),
    ("cvtab", "obj/dict/p002_tab.hdp", 1, cv, cvg, 11),
    ("hz2pool", "obj/dict/h_z2_pool_t.hdp", 0, z2, z2g, 17),
    ("hcvcap", "obj/dict/h_cv_cap_t.hdp", 1, cv, cvg, 19),
    ("z2addt", "obj/dict/a057_addt.hdp", 0, z2, z2g, 7),
    ("cvaddt", "obj/dict/p002_addt.hdp", 1, cv, cvg, 13),
    ("z2", "Z:/NES_HDPack_work/out/a057.hdp", 0, z2, z2g, 5),
    ("cv", "Z:/NES_HDPack_work/out/p002.hdp", 1, cv, cvg, 11),
]


def build(rtl, mdir):
    os.makedirs(mdir, exist_ok=True)
    shutil.copy(rtl, os.path.join(mdir, "hd3_dict.sv"))
    r = subprocess.run(["sh", "tools/sim3/build_one.sh", "hd3_dict", "tools/sim3/tb_dict.cpp",
                        os.path.join(mdir, "hd3_dict.sv"), "rtl/hdpack/hd3_lookup.sv"],
                       cwd=P, env=dict(os.environ, OBJ=os.path.join(mdir, "obj")),
                       capture_output=True, text=True)
    exe = os.path.join(mdir, "obj", "tb_dict.exe")
    if r.returncode != 0 or not os.path.exists(exe):
        return None, (r.stdout + r.stderr)[-400:]
    return exe, ""


def run(exe, mdir, s, stop_on_fail):
    """'pass' or why it failed, per suite (stops at the first failure if asked)."""
    out = []
    for suite in s:
        name, pack, gr, frames, gold, seed = suite[:6]
        mode = suite[6] if len(suite) > 6 else STD
        tsv = os.path.join(mdir, f"{name}.tsv")
        args = [exe, pack, tsv, "--game-ram", str(gr)]
        for f in frames:
            args += f.split()
        args += (["--overlap"] if mode["overlap"] else []) + \
                (["--allow-abandon"] if mode["lag"] else []) + \
                ["--gap", "25", "--busy", str(mode["busy"]), "--lat", str(mode["lat"]),
                 "--seed", str(seed)]
        try:
            r = subprocess.run(args, cwd=D, capture_output=True, text=True, timeout=1800)
        except subprocess.TimeoutExpired:
            out.append((name, "testbench hang"))
            if stop_on_fail:
                return out
            continue
        if r.returncode != 0:
            out.append((name, "testbench error: " + (r.stdout + r.stderr).strip()[-120:]))
        else:
            c = subprocess.run([sys.executable, "-I", "check_dict.py", tsv] + gold + ["--pack", pack]
                               + (["--lag"] if mode["lag"] else []),
                               cwd=D, capture_output=True, text=True)
            last = c.stdout.strip().splitlines()[-1] if c.stdout.strip() else c.stderr[-120:]
            out.append((name, "pass" if c.returncode == 0 else last))
        if stop_on_fail and out[-1][1] != "pass":
            return out
    return out


def mutant(name, src):
    old, new = MUTANTS[name]
    if src.count(old) != 1:
        return name, f"ANCHOR FOUND {src.count(old)} TIMES"
    # short folder names: Verilator's generated file names are long, and a long mutant name in
    # the path broke three builds on Windows' 260-character path limit
    mdir = os.path.join(WORK, f"m{list(MUTANTS).index(name):02d}")
    os.makedirs(mdir, exist_ok=True)
    mrtl = os.path.join(mdir, "mut.sv")
    open(mrtl, "w", encoding="utf-8", newline="").write(src.replace(old, new))
    exe, err = build(mrtl, mdir)
    if exe is None:
        # a build failure is a harness problem, never a catch
        return name, "BUILD FAILED: " + (err.strip().splitlines()[-1] if err.strip() else "?")
    res = run(exe, mdir, SUITES, True)
    bad = [r for r in res if r[1] != "pass"]
    return name, (f"CAUGHT by {bad[0][0]}: {bad[0][1]}" if bad else "MISSED (passes all suites)")


def main():
    rtl = sys.argv[sys.argv.index("--rtl") + 1] if "--rtl" in sys.argv else \
        os.path.join(P, "rtl", "hdpack", "hd3_dict.sv")
    only = sys.argv[sys.argv.index("--only") + 1].split("|") if "--only" in sys.argv else None
    jobs = int(sys.argv[sys.argv.index("--jobs") + 1]) if "--jobs" in sys.argv else 4
    src = open(rtl, encoding="utf-8", newline="").read()
    os.makedirs(WORK, exist_ok=True)
    if not only:
        exe, err = build(rtl, os.path.join(WORK, "_baseline"))
        if exe is None:
            print("baseline does not build", err)
            return 2
        res = run(exe, os.path.join(WORK, "_baseline"), SUITES, False)
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
    return 1 if missed else 0


if __name__ == "__main__":
    sys.exit(main())
