"""Negative control for the stage-3 integration RTL (hd3_engine, hd3_scanout, hd3_cross, the
new hd3_loader exports): each mutant is one deliberate defect; it is built, run on the engine
test set it should fail, and must be CAUGHT. A mutant that passes is a coverage gap unless it is
shown to be output-equivalent.

    python neg_engine.py [jobs] [only-name ...]

Sets (run_engine.sh modes): quick = SMB + the lane fixtures + the overscan fixture + the slow
DDR3 run; cvw = Castlevania with the watch snapshot late (40 MB pack, ~10 minutes); abort = the
lane fixture on a -GADD_BUDGET=20 build.
"""
import concurrent.futures as cf
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RTL = os.path.normpath(os.path.join(HERE, "..", "..", "rtl", "hdpack"))
WORK = os.path.join(HERE, "obj", "neg_engine")

# (name, file, old, new, set)
M = [
    # ---- clock crossings ----
    ("xq_ready_always", "hd3_cross.sv", "assign i_ready = ~(put_t ^ got_t);", "assign i_ready = 1'b1;", "quick"),
    ("xq_take_without_ready", "hd3_cross.sv", "if (o_valid & o_ready) got_t", "if (o_valid) got_t", "quick"),
    ("ss_req_level", "hd3_cross.sv", "f_req <= rq_t ^ rq_d;", "f_req <= rq_t;", "quick"),
    ("ss_rnw_inverted", "hd3_cross.sv", "f_rnw <= rnw;", "f_rnw <= ~rnw;", "quick"),
    ("ss_be_ignored", "hd3_cross.sv", "f_be <= be;", "f_be <= 8'hFF;", "quick"),
    ("ss_ready_level", "hd3_cross.sv", "ready <= rd_t ^ rd_d;", "ready <= rd_t;", "quick"),
    ("load_ack_unchecked", "hd3_engine.sv", "always @(posedge clk) ld_wr_ack <= ld_take;",
     "always @(posedge clk) ld_wr_ack <= ld_wr_req & ~ld_wr_ack;", "quick"),
    ("tap_without_ready", "hd3_engine.sv", "wire        tap_v  = cwf_v & cwf_r;", "wire        tap_v  = cwf_v;", "quick"),
    # ---- controller ----
    ("watch_not_waited", "hd3_engine.sv", "C_WAITW: if (!wneed || watch_ok[cur_b] ||", "C_WAITW: if (1'b1 ||", "cvw"),
    ("watch_wrong_bank", "hd3_engine.sv", "wd_b <= ~frame_num[0];", "wd_b <= frame_num[0];", "cvw"),
    ("add_never_aborted", "hd3_engine.sv", "if (acnt >= 24'(ADD_BUDGET) && !r_ad_abort) begin", "if (1'b0) begin", "abort"),
    ("add_ovf_ignored", "hd3_engine.sv", ".frame_ovf(dict_fovf[rn_bank] || add_ovf[rn_bank])", ".frame_ovf(dict_fovf[rn_bank])", "quick"),
    ("target_always_next", "hd3_engine.sv", "tgt <= (disp_y >= 9'd240) ? dcount : dcount + 2'd1;", "tgt <= dcount + 2'd1;", "quick"),
    ("target_always_current", "hd3_engine.sv", "tgt <= (disp_y >= 9'd240) ? dcount : dcount + 2'd1;", "tgt <= dcount;", "quick"),
    ("draw_during_previous_frame", "hd3_engine.sv", ": (fdiff != 2'd1);", ": 1'b1;", "quick"),
    ("ring_one_line_too_far", "hd3_engine.sv", "disp_y + 9'd7)", "disp_y + 9'd8)", "quick"),
    ("vblank_nine_lines", "hd3_engine.sv", "(rn_line < 8'd8))", "(rn_line < 8'd9))", "quick"),
    ("progress_one_ahead", "hd3_engine.sv", "else if (out_v) p_cur_y <= {1'b0, out_y};",
     "else if (out_v) p_cur_y <= {1'b0, out_y} + 9'd1;", "quick"),
    ("finished_frame_forgotten", "hd3_engine.sv", "			p_fin_v <= 1;", "			p_fin_v <= 0;", "quick"),
    ("pending_wrong_bank", "hd3_engine.sv", "pend_v <= 1; pend_b <= done_bank;", "pend_v <= 1; pend_b <= ~done_bank;", "quick"),
    ("overrun_other_bank", "hd3_engine.sv", "tap_a[20] == cur_b && cst", "tap_a[20] != cur_b && cst", "quick"),
    # ---- the shared dictionary / lane read port (8m: ADD, then RESOLVE, then RENDER) ----
    ("dict_bank_add_ignored", "hd3_engine.sv", ".r_bank(ad_busy ? ad_bank : rs_busy ? rs_dbank : rn_dbank),",
     ".r_bank(rs_busy ? rs_dbank : rn_dbank),", "quick"),
    ("dict_bank_resolve_ignored", "hd3_engine.sv", ".r_bank(ad_busy ? ad_bank : rs_busy ? rs_dbank : rn_dbank),",
     ".r_bank(ad_busy ? ad_bank : rn_dbank),", "quick"),
    ("dict_rid_add_ignored", "hd3_engine.sv", ".r_rid(ad_busy ? ad_rid : rs_busy ? rs_drid : rn_drid),",
     ".r_rid(rs_busy ? rs_drid : rn_drid),", "quick"),
    ("dict_rid_resolve_ignored", "hd3_engine.sv", ".r_rid(ad_busy ? ad_rid : rs_busy ? rs_drid : rn_drid),",
     ".r_rid(ad_busy ? ad_rid : rn_drid),", "quick"),
    ("dict_rid_render_ignored", "hd3_engine.sv", ".r_rid(ad_busy ? ad_rid : rs_busy ? rs_drid : rn_drid),",
     ".r_rid(ad_busy ? ad_rid : rs_drid),", "quick"),
    ("dict_line_add_ignored", "hd3_engine.sv", ".r_y(ad_busy ? ad_y : rn_y), .r_slot(ad_busy ? ad_slot : rn_slot)",
     ".r_y(rn_y), .r_slot(ad_busy ? ad_slot : rn_slot)", "quick"),
    ("dict_slot_add_ignored", "hd3_engine.sv", ".r_y(ad_busy ? ad_y : rn_y), .r_slot(ad_busy ? ad_slot : rn_slot)",
     ".r_y(ad_busy ? ad_y : rn_y), .r_slot(rn_slot)", "quick"),
    ("dict_fetch_add_ignored", "hd3_engine.sv", ".r_fetch(ad_busy ? ad_fetch : rn_fetch)", ".r_fetch(rn_fetch)", "quick"),
    ("lanes_resolve_ignored", "hd3_engine.sv", ".rl_y(rs_busy ? rs_ay : rn_ay)", ".rl_y(rn_ay)", "quick"),
    ("watch2_resolve_bank", "hd3_engine.sv", "assign w2_bank = rn_dbank;", "assign w2_bank = rs_dbank;", "cvw"),
    # ---- scan-out ----
    ("subpixel_swapped", "hd3_scanout.sv", "q[{s1_sub, 3'b000} * 3 +: 24]", "q[{s1_sub[0], s1_sub[1], 3'b000} * 3 +: 24]", "quick"),
    ("no_line_lag", "hd3_scanout.sv", "		disp_y <= job_y;", "		disp_y <= line_y;", "quick"),
    ("frame_id_late", "hd3_scanout.sv", "if (disp_y < 9'd240 && job_y >= 9'd240) dcount",
     "if (disp_y < 9'd241 && job_y >= 9'd241) dcount", "quick"),
    ("window_left_ignored", "hd3_scanout.sv", "({1'b0, o_x} >= {1'b0, ov_left}) &&", "", "quick"),
    ("window_top_ignored", "hd3_scanout.sv", "(disp_y >= {1'b0, ov_top}) && ", "", "quick"),
    ("hsync_late", "hd3_scanout.sv", "(o_px >= 10'd544)", "(o_px >= 10'd545)", "quick"),
    ("vsync_early", "hd3_scanout.sv", "(disp_y >= 9'd245)", "(disp_y >= 9'd244)", "quick"),
    ("hcnt_free_running", "hd3_scanout.sv", "hcnt <= line_done ? 11'd0 : (hcnt", "hcnt <= 1'b0 ? 11'd0 : (hcnt", "quick"),
    ("line_shown_part_way", "hd3_scanout.sv", "wire        o_ok  = (hcnt == 11'd0) ? o_ok0 : l_ok;",
     "wire        o_ok  = o_ok0;", "quick"),
    ("underflow_from_start", "hd3_scanout.sv", "if (p_run && p_cur_t == dcount) armed <= 1;", "armed <= 1;", "quick"),
    ("underflow_never", "hd3_scanout.sv", "&& armed) underflow <= 1;", "&& 1'b0) underflow <= 1;", "quick"),
    # ---- loader exports ----
    ("conds_base_wrong", "hd3_loader_stream.sv", "assign conds_base   = PACK_Q + h_s2off[27:3];",
     "assign conds_base   = PACK_Q + h_s3off[27:3];", "quick"),
    ("overscan_word_wrong", "hd3_loader_stream.sv", "7'd5:  h_ov[1] <= b_word;", "7'd7:  h_ov[1] <= b_word;", "quick"),
]


def sh(cmd, log, env=None):
    with open(log, "w") as f:
        return subprocess.run(["sh", "-c", cmd], stdout=f, stderr=subprocess.STDOUT, env=env).returncode


def one(m):
    name, fn, old, new, st = m
    d = os.path.join(WORK, name)
    shutil.rmtree(d, ignore_errors=True)
    shutil.copytree(RTL, os.path.join(d, "rtl"), ignore=shutil.ignore_patterns("obj"))
    p = os.path.join(d, "rtl", fn)
    with open(p, encoding="utf-8") as f:
        s = f.read()
    n = s.count(old)
    if n != 1:
        return name, f"ANCHOR x{n}"
    with open(p, "w", encoding="utf-8", newline="") as f:
        f.write(s.replace(old, new))
    env = dict(os.environ, RTLDIR=os.path.join(d, "rtl").replace("\\", "/"))
    obj = os.path.join(d, "obj").replace("\\", "/")
    flags = "-GNL=64 -GADD_BUDGET=20" if st == "abort" else ""
    if sh(f'sh "{HERE}/build_engine.sh" "{obj}" {flags}', os.path.join(d, "build.log"), env) != 0:
        return name, "BUILD FAILED"
    exe = obj + "/tb_engine.exe"
    out = os.path.join(d, "out").replace("\\", "/")
    if st == "abort":
        cmd = f'ABORT_EXE="{exe}" OUT="{out}" sh "{HERE}/run_engine.sh" abort'
    else:
        cmd = f'EXE="{exe}" OUT="{out}" sh "{HERE}/run_engine.sh" {st}'
    rc = sh(cmd, os.path.join(d, "run.log"), env)
    return name, "CAUGHT" if rc != 0 else "MISSED"


def main():
    jobs = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    only = set(sys.argv[2:])
    ms = [m for m in M if not only or m[0] in only]
    os.makedirs(WORK, exist_ok=True)
    res = {}
    with cf.ThreadPoolExecutor(jobs) as ex:
        for name, r in ex.map(one, ms):
            res[name] = r
            print(f"{name}: {r}", flush=True)
    caught = sum(1 for r in res.values() if r == "CAUGHT")
    print(f"{caught} of {len(ms)} caught")
    sys.exit(0 if caught == len(ms) else 1)


main()
