"""Negative control for the hd3_render unit test: each mutant of the RTL must FAIL the suite.

A check that has never been seen to fail proves nothing. Each mutation below is a plausible
real bug; the runner copies hd3_render.sv with that one change, builds the testbench into its
own folder, runs run_render.sh with it and requires a failure (a pixel mismatch, a testbench
error, a rare path not taken, or a hang). Every anchor must occur exactly once in the source,
so a stale anchor fails loudly instead of producing an unmutated "mutant" that passes. The real
RTL is built and run first and must PASS, or the control means nothing.

Mutants flagged "slot" are also built with NSLOT=4 (uncached tiles through the scratch slot),
"small" with RS_MAX=64 (unfiltered rule lists walked from DDR3) and "raw" with RAW=6 (64 record
ids, so Castlevania's frames overflow the dictionary - HDPACK_DESIGN.md "8o"); those paths are
only reached by those builds. "add" mutants (8a lanes) are built with NL=64 and run on the
addition fixtures alone, where the added sprites are drawn rather than overflowing.

A mutant that is NOT caught is a coverage gap in the fixtures, not a pass: either the suite
needs a frame that exercises it, or the mutation is not observable (say why in its name).

usage: python neg_render_rtl.py <testdata dir> <pack dir> [mutant name substring | extra=<kind> | notextra=<kind>]
"""
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
RTL_DIR = os.path.join(ROOT, "rtl", "hdpack")
RTL = os.path.join(RTL_DIR, "hd3_render.sv")
OTHERS = [os.path.join(HERE, "hd3_render_tb.sv")] + [
    os.path.join(RTL_DIR, f) for f in ("hd3_dict.sv", "hd3_lookup.sv", "hd3_add.sv",
                                       "hd3_resolve.sv", "hd3_fmap.sv", "hd3_rcache.sv",
                                       "hd3_ccache.sv")]

# name: (anchor, replacement, extra build: "" / "slot" / "small")
MUTANTS = {
    # 8i: the memo is no longer cleared but SEEDED at frame start from resolve's values of the
    # rewrite-sensitive conditions background selection evaluated
    "deferred-condition memo not reset at frame start":
        ("dm_a <= 11'(mc - 12'd1); dmw_d <= sd_q; dmw_e <= 1;",
         "dm_a <= 11'(mc - 12'd1); dmw_d <= sd_q; dmw_e <= 0;", ""),
    "memo not seeded (cleared instead)":
        ("dm_a <= 11'(mc - 12'd1); dmw_d <= sd_q; dmw_e <= 1;",
         "dm_a <= 11'(mc - 12'd1); dmw_d <= 2'b00; dmw_e <= 1;", ""),
    "memo hit skips the negation":
        ("begin e_res <= dm_q[0] ^ c_neg; c_memo_new", "begin e_res <= dm_q[0]; c_memo_new", ""),
    "BG cache not reset at the 8-pixel group boundary":
        ("uce = ((l_finex + xx[2:0]) == 3'd0) ? 1'b0 : use_c;", "uce = use_c;", ""),
    "BG cache ignores a rule's force-disable-cache":
        ("if (!wr_q[42] && cache_en) begin cached", "if (cache_en) begin cached", ""),
    "sensitive condition in a group not walked per pixel":
        ("if (c_sens && i_group) begin", "if (1'b0) begin", ""),
    "tileNearby (pipelined) ignores rewrites":
        ("r = !tp_dead[6] && tmatch(rw_able && in_win(tp_ty[6], tp_tx[6]) &&",
         "r = !tp_dead[6] && tmatch(1'b0 && in_win(tp_ty[6], tp_tx[6]) &&", ""),
    "a record does not see its own rewrite (offset-0 nearby)":
        ("seen = (ty == cy && tx == ccx && tp == cpp) || (lk && precedes",
         "seen = (lk && precedes", ""),
    # Not mutated: the "no record" guards (tp_dead[5] <= !d_span[RAW], si_dead[3] <= !d_spr[RAW]).
    # A pixel's sprite list holds valid fetches only and every BG span in range gets a record,
    # so a target without one exists only after the dictionary overflowed (more distinct records
    # than ids). Such a frame is drawn with no lookups at all (8o), so no condition reads the
    # missing record and both guards stay unreachable. Both mutants were seen to pass the whole
    # suite for that reason (2026-10-16).
    "spriteNearby (pipelined) ignores the sprite's phase":
        ("si_ph[1] <= 4'd1 + phase_of(fl[TLW-8 + sp_j], fl[4*TEW +: 3], sp_j);",
         "si_ph[1] <= 4'd1;", ""),
    "image slot reused for a different tile row":
        ("la_blk == r_pay[17:0] && la_row == i_offy", "la_blk == r_pay[17:0]", ""),
    "grayscale ignored":
        ("of_d <= {l_emph, l_gray, y, dp2_x, acc_n};", "of_d <= {l_emph, 1'b0, y, dp2_x, acc_n};", ""),
    "emphasis ignored":
        ("of_d <= {l_emph, l_gray, y, dp2_x, acc_n};", "of_d <= {3'd0, l_gray, y, dp2_x, acc_n};", ""),
    "compose plan drops front sprites":
        ("else m[9 - k] = 1'b1;", "else m[9 - k] = 1'b0;", ""),
    # Not mutated: the full-output-FIFO stall (!last || of_ahead < OF_D). Measured with the stall
    # removed (2026-10-16), the FIFO never holds more than ONE pixel on any fixture, at depth 8
    # or 2, with or without NSLOT=4 scratch stalls: the output stage pops a pixel every 2 clocks
    # on the clock the next one lands, and compose can issue at most two pixels back to back (the
    # front stage refills its one-plan buffer no faster than every 2 clocks). The stall can never
    # change the output, so a mutant without it passes by construction. It stays as a guard for
    # a faster front stage; run_render.sh's OF_LOG2=1 build still checks that stalling loses
    # nothing (the stall fires there).
    "prefetched condition taken for another list position":
        ("if (pf_ok[0] && pf_cp[0] == cp && !rc_pend) begin", "if (pf_ok[0] && !rc_pend) begin", ""),
    "rule read ahead taken for another rule":
        ("if (pf_rule_ok && pf_ri == w_ri) begin", "if (pf_rule_ok) begin", ""),
    # the 2026-10-16 bug: the main path's condition index in the register the prefetch also
    # writes (found by the cvsens fixture, invisible to every other one)
    "prefetch overwrites the evaluated condition's index":
        ([("m_ci   <= cp[2] ? lw_q[55:32] : lw_q[23:0];", "cc_ci  <= cp[2] ? lw_q[55:32] : lw_q[23:0];"),
          ("m_ci   <= cp[2] ? rc_q[55:32] : rc_q[23:0];", "cc_ci  <= cp[2] ? rc_q[55:32] : rc_q[23:0];"),
          ("cc_req <= 1; cc_pend <= 1; cc_ci <= m_ci;", "cc_req <= 1; cc_pend <= 1;")], None, ""),
    "list word reused for another qword":
        ("end else if (!rc_pend && lw_v && lw_a == cp[20:3]) begin",
         "end else if (!rc_pend && lw_v) begin", ""),
    "scratch slot loads tile row 0":
        ("if_d <= {7'd127, cst_r[17:0], cst_r[34:32]};", "if_d <= {7'd127, cst_r[17:0], 3'd0};",
         "slot"),
    "scratch slot reused without comparing the tile row":
        ("!(scr_v && scr_blk == r[17:0] && scr_row == r[34:32])", "!(scr_v && scr_blk == r[17:0])",
         "slot"),
    "unfiltered list reads the wrong rule word":
        ("rc_addr <= rules_base + w_offq + 25'd1 + {w_i2[23:0], 1'b0};",
         "rc_addr <= rules_base + w_offq + 25'd3 + {w_i2[23:0], 1'b0};", "small"),
    # 8o: a frame the dictionary overflowed is drawn with no lookups at all
    "overflowed frame still looked up":
        ("if (!i_rv || f_ovf || q_rec[48:47] == 2'd0", "if (!i_rv || q_rec[48:47] == 2'd0", "raw"),
    # the defect a Verilator miscompile produced (2026-10-17): a behind-background sprite drawn
    # in front of the background
    "sprite list loses the behind-background bit":
        ("bgp[n[1:0]] = ln[24];", "bgp[n[1:0]] = 1'b0;", ""),
    # ---- 8j backgrounds (the blend, clip and ratio mutants are caught by the make_bg_frame.py
    # fixtures: no recorded frame draws Add / Subtract or scrolls by a negative ratio) ----
    "background blend mode ignored (all Alpha)":
        ("dp_md <= cst_bg ? be_q[59:58] : 2'd0;", "dp_md <= 2'd0;", ""),
    "Add and Subtract swapped":
        ([("2'd1:    blend_m = {add_sat", "2'd2:    blend_m = {add_sat"),
          ("2'd2:    blend_m = {sub_sat", "2'd1:    blend_m = {sub_sat")], None, ""),
    "background pixel always from its group's first cell":
        ("wire [25:0] be_ref = be_sum[3] ? be_q[51:26] : be_q[25:0];",
         "wire [25:0] be_ref = be_q[25:0];", ""),
    "background column ignores the cell phase":
        ("else if (cst_bg) begin o = be_sum[2:0]; hm = 0; vm = 0; end",
         "else if (cst_bg) begin o = bx[2:0]; hm = 0; vm = 0; end", ""),
    "group mask ignores the cell phase":
        ("wire         [7:0] gp_am = 8'hFF >> bv_ph;", "wire         [7:0] gp_am = 8'hFF;", ""),
    "a level not drawn on a line keeps the previous line's pixels":
        ("if (bg_g == bgr_g) begin bdirty[bl] <= 0; bnext(); end",
         "if (1'b1) begin bdirty[bl] <= 0; bnext(); end", ""),
    "lines above the record drawn (negative y + sy)":
        ("bv_vis   <= !g_a[35] && g_b <= g_h;", "bv_vis   <= g_b <= g_h;", ""),
    "lines past the record's bottom drawn":
        ("bv_vis   <= !g_a[35] && g_b <= g_h;", "bv_vis   <= !g_a[35];", ""),
    "pixels left of the record drawn (-sx ignored)":
        ("wire signed [35:0] g_lo  = (g_mn > g_xl) ? g_mn : g_xl;",
         "wire signed [35:0] g_lo  = g_xl;", ""),
    "pixels past the record's right edge drawn":
        ("wire signed [35:0] g_hi  = (g_mx < g_xr) ? g_mx : g_xr;",
         "wire signed [35:0] g_hi  = g_xr;", ""),
    "scroll ratio reused after the scroll changed":
        ("if (bv_xv && bv_xs == bscr_x) bs <= B_L5;", "if (bv_xv) bs <= B_L5;", ""),
    "vertical ratio reused after the scroll changed":
        ("if (bv_yv && bv_ys == bscr_y) bs <= B_L6;", "if (bv_yv) bs <= B_L6;", ""),
    "map row offset reused for another row":
        ("if (bv_rv && bv_rcr == bv_py[31:3]) bs <= B_MF;", "if (bv_rv) bs <= B_MF;", ""),
    "next-row offset steps by one column too many":
        ("bv_rcr <= bv_py[31:3]; bv_rval <= bv_rval + cols28; bs <= B_MF;",
         "bv_rcr <= bv_py[31:3]; bv_rval <= bv_rval + cols28 + 28'd1; bs <= B_MF;", ""),
    "map word taken from the wrong half of its qword":
        ("wire        [31:0] lk_word = lk_w[0] ? mb_q[63:32] : mb_q[31:0];",
         "wire        [31:0] lk_word = lk_w[0] ? mb_q[31:0] : mb_q[63:32];", ""),
    "image slot of a cell kept from an earlier line":
        ("if (bs_q[36] && bs_q[35:28] == y && bs_q[27:10] == lk_blk && bs_q[9:7] == bv_row)",
         "if (bs_q[36] && bs_q[27:10] == lk_blk && bs_q[9:7] == bv_row)", ""),
    "uncached background cell drawn from slot 0":
        ("wire [41:0] be_r   = {1'b1, 1'b0, be_ref[25], be_ref[25] ? {4'd0, be_q[57:55]} : be_ref[24:18],",
         "wire [41:0] be_r   = {1'b1, 1'b0, 1'b0, be_ref[24:18],", "slot"),
    # 8a additions (run on the addition fixtures alone: "add")
    "pixel lists ignore the line's lanes":
        ("mergep(fl, pp_x1[0] ? p_q[13] : p_q[6], ln_cur, n_cur,",
         "mergep(fl, pp_x1[0] ? p_q[13] : p_q[6], ln_cur, 7'd0,", "add"),
    "lanes appended only where sprites are shown":
        ("\t\t\tif (k < nl && n < 3'd4 && lcov(l, xx)) begin\n\t\t\t\te[8 * n",
         "\t\t\tif (shown && k < nl && n < 3'd4 && lcov(l, xx)) begin\n\t\t\t\te[8 * n", "add"),
    "lane coverage one pixel short":
        ("lcov = xx >= l[7:0] && d <= {5'd0, l[10:8]};",
         "lcov = xx >= l[7:0] && d < {5'd0, l[10:8]};", "add"),
    "lane's background priority dropped in the pixel list":
        ("e[8 * n[1:0] +: 8] = {lk, k[5:0]};\n\t\t\t\tbgp[n[1:0]] = l[LW-2];",
         "e[8 * n[1:0] +: 8] = {lk, k[5:0]};\n\t\t\t\tbgp[n[1:0]] = 1'b0;", "add"),
    "pixel (0,0) not taken from line 239":
        ("pword = (vz && xx == 8'd0) ? w00", "pword = (1'b0 && xx == 8'd0) ? w00", "add"),
    "line 0 header not taken from line 239":
        ("\t\t\t\t\tif (vq == 7'd0) begin", "\t\t\t\t\tif (1'b0) begin", "add"),
    "pixel (0,0) without line 240's lanes":
        ("mergep(fl, p_q[6], ln_240, n_240,", "mergep(fl, p_q[6], ln_240, 7'd0,", "add"),
    "added sprites never walked":
        ("begin lf <= 0; lsel <= 0; st <= S_LF0; end", "begin lf <= 0; lsel <= 0; st <= S_FW; end",
         "add"),
    "added sprite column ignores its source column":
        ("ox[i_n[2:0]] <= it_c0 + sc[2:0];", "ox[i_n[2:0]] <= sc[2:0];", "add"),
    "added sprite drawn unflipped":
        ("n_hm[cj[1:0]]  <= l[LW-4];", "n_hm[cj[1:0]]  <= 1'b0;", "add"),
    "spriteAtPosition targets ignore lanes":
        ("tl = merget(fl, px[6], a_q, a_n, t_x);", "tl = merget(fl, px[6], a_q, 7'd0, t_x);", "add"),
    "spriteNearby targets ignore lanes":
        ("tl = merget(fl, px[6], a_q, a_n, sp_tx[2]);",
         "tl = merget(fl, px[6], a_q, 7'd0, sp_tx[2]);", "add"),
    "a target at (0,0) reads line 0":
        ("dline = (add_en && at == 16'd0) ? 8'd239 : at[15:8];", "dline = at[15:8];", "add"),
    "an added NOTILE / CHR-RAM sprite can match":
        ("if (ln && (game_ram || d_key[63:0] == {64{1'b1}}))", "if (1'b0)", "add"),
    # hd3_resolve's added-sprite branch: the resolve testbench has no additions, so the render
    # chain is the only place a spriteAtPosition/Nearby on an added sprite is checked
    "resolve: spriteAt palette of an added sprite ignored":
        ("wire        tm_pal  = c_ign || (t_lane ? lpal : rec_pal) == c3[31:0];",
         "wire        tm_pal  = c_ign || (t_lane ? c3[31:0] : rec_pal) == c3[31:0];", "add",
         "hd3_resolve.sv"),
}

# Mutants proven to leave every output pixel unchanged (not run; the reason is the proof):
EQUIVALENT = {
    "group entry read for another level (prefetch tag without the level)":
        "be_tag only ever differs from the issuing step's {level, group} in its level bits right "
        "after a pixel's last step, and every pixel's FIRST step is the backdrop (plan_steps "
        "starts m = 10'd1, steps50 puts m[0] at bit 0), a colour step that never tests be_hit. "
        "Every issuing step writes the NEXT step's {step_lvl(cst2), bx[7:3]} into be_tag, and a "
        "step that does not issue rewrites its own {cst_l, bx[7:3]}, so by the time any "
        "background step tests be_hit the level bits already match. Dropping them changes no "
        "hit. Measured too: the full suite passes with the mutant (2026-10-20 run), including "
        "frames where 49,088-55,900 pixels per frame have two or more levels in range.",
}


def selected(only, name):
    """No filter, a name substring (several joined with "|" select any of them), "extra=<kind>"
    for every mutant of one build kind, or "notextra=<kind>" for every mutant except that kind's."""
    if not only:
        return True
    if only.startswith("extra="):
        return MUTANTS[name][2] == only[6:]
    if only.startswith("notextra="):
        return MUTANTS[name][2] != only[9:]
    return any(part and part in name for part in only.split("|"))


def sources(mfile=None, mpath=None):
    """The build's RTL list with file `mfile` (a basename) replaced by the mutated copy `mpath`."""
    files = OTHERS + [RTL]
    if mfile:
        if not any(os.path.basename(p) == mfile for p in files):
            sys.exit(f"mutant targets {mfile}, which the build does not use")
        files = [mpath if os.path.basename(p) == mfile else p for p in files]
    return files


def build(files, mdir, vflags=None):
    env = dict(os.environ, OBJ=mdir.replace("\\", "/"))
    if vflags:
        env["VFLAGS"] = vflags
    b = subprocess.run(["sh", os.path.join(HERE, "build_one.sh"), "hd3_render_tb",
                        os.path.join(HERE, "tb_render.cpp")] + files,
                       env=env, capture_output=True, text=True)
    return b.returncode == 0, b.stdout[-800:] + b.stderr[-800:]


def suite(mdir, td, packs, extra):
    """Return (passed, summary)."""
    env = dict(os.environ, EXE=os.path.join(mdir, "tb_render.exe").replace("\\", "/"),
               OUT=mdir.replace("\\", "/"))
    if extra == "add":
        # 8a mutants: only the addition fixtures can decide them; run those alone, on the NL=64
        # build where the heavy fixtures draw their lanes instead of overflowing
        env["ADD_ONLY"] = "1"
        env["REF"] = "--nl 64"
    if extra == "all":
        env["NL_EXE"] = os.path.join(mdir, "nl64", "tb_render.exe").replace("\\", "/")
    if extra == "add" or extra == "all":
        # the lane fixtures again with every rule list unfiltered (RS_MAX=1), so render's own
        # condition walk decides the spriteAtPosition / spriteNearby / (0,0) targets
        env["RS1_EXE"] = os.path.join(mdir, "rs1", "tb_render.exe").replace("\\", "/")
    if extra == "slot" or extra == "all":
        env["SLOT_EXE"] = os.path.join(mdir, "slot", "tb_render.exe").replace("\\", "/")
    if extra == "small" or extra == "all":
        env["SMALL_EXE"] = os.path.join(mdir, "small", "tb_render.exe").replace("\\", "/")
    if extra == "raw" or extra == "all":
        env["RAW_EXE"] = os.path.join(mdir, "raw", "tb_render.exe").replace("\\", "/")
    try:
        r = subprocess.run(["sh", os.path.join(HERE, "run_render.sh"), td, packs], env=env,
                           capture_output=True, text=True,
                           timeout=7200 if extra == "all" else 2400)
    except subprocess.TimeoutExpired:
        return False, "suite hung"
    bad = [ln.strip() for ln in r.stdout.splitlines()
           if "FAIL" in ln or "failed" in ln or "NEVER TAKEN" in ln]
    return r.returncode == 0, "; ".join(bad) if bad else "all pass"


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    td, packs = sys.argv[1], sys.argv[2]
    only = sys.argv[3] if len(sys.argv) > 3 else None
    work = os.path.join(HERE, "obj", "neg_render")
    os.makedirs(work, exist_ok=True)

    base = os.path.join(work, "_baseline")
    shutil.rmtree(base, ignore_errors=True)
    os.makedirs(base)
    ok, log = build(sources(), base)
    ok2, log2 = build(sources(), os.path.join(base, "slot"), "-GNSLOT=4")
    ok3, log3 = build(sources(), os.path.join(base, "small"), "-GRS_MAX=64")
    ok4, log4 = build(sources(), os.path.join(base, "raw"), "-GRAW=6")
    ok5, log5 = build(sources(), os.path.join(base, "nl64"), "-GNL=64")
    ok6, log6 = build(sources(), os.path.join(base, "rs1"), "-GNL=64 -GRS_MAX=1")
    if not (ok and ok2 and ok3 and ok4 and ok5 and ok6):
        print(f"BUILD FAILED [baseline]\n{log}{log2}{log3}{log4}{log5}{log6}")
        return 2
    passed, why = suite(base, td, packs, "all")
    print(f"baseline: {why}", flush=True)
    if not passed:
        print("FAIL: the unmutated RTL does not pass - fix that before trusting the control")
        return 2

    caught, missed = 0, []
    for idx, (name, spec) in enumerate(MUTANTS.items()):
        if not selected(only, name):
            continue
        old, new, extra = spec[:3]
        mfile = spec[3] if len(spec) > 3 else "hd3_render.sv"    # the RTL file it mutates
        with open(os.path.join(RTL_DIR, mfile), encoding="utf-8") as f:
            src = f.read()
        # one edit, or (old is a list) several edits that together make the mutant
        edits = old if isinstance(old, list) else [(old, new)]
        msrc = src
        for a, b in edits:
            n = msrc.count(a)
            if n != 1:
                print(f"ANCHOR ERROR [{name}]: found {n} times: {a[:60]!r}")
                return 2
            msrc = msrc.replace(a, b)
        # short: Verilator's generated names under hd3_render_tb/ already run ~75 characters,
        # and a long folder name pushes them past Windows' 260-character path limit (the
        # build then fails with "Can't write file")
        tag = "%02d_" % idx + "".join(ch if ch.isalnum() else "_" for ch in name)[:24]
        mdir = os.path.join(work, tag)
        shutil.rmtree(mdir, ignore_errors=True)
        os.makedirs(mdir)
        mrtl = os.path.join(mdir, mfile)
        with open(mrtl, "w", encoding="utf-8", newline="\n") as f:
            f.write(msrc)
        files = sources(mfile, mrtl)
        ok, log = build(files, mdir, "-GNL=64" if extra == "add" else None)
        if ok and extra == "add":
            ok, log = build(files, os.path.join(mdir, "rs1"), "-GNL=64 -GRS_MAX=1")
        if ok and extra == "slot":
            ok, log = build(files, os.path.join(mdir, "slot"), "-GNSLOT=4")
        if ok and extra == "small":
            ok, log = build(files, os.path.join(mdir, "small"), "-GRS_MAX=64")
        if ok and extra == "raw":
            ok, log = build(files, os.path.join(mdir, "raw"), "-GRAW=6")
        if not ok:
            print(f"BUILD FAILED [{name}]\n{log}")
            return 2
        passed, why = suite(mdir, td, packs, extra)
        if passed:
            missed.append(name)
            print(f"MISSED  {name}", flush=True)
        else:
            caught += 1
            print(f"CAUGHT  {name}  ({why[:160]})", flush=True)
    total = len([m for m in MUTANTS if selected(only, m)])
    print(f"{caught}/{total} mutants caught")
    for m in missed:
        print(f"  not caught: {m}")
    for name, why in EQUIVALENT.items():
        print(f"EQUIVALENT (not run)  {name}: {why}")
    return 0 if not missed else 1


if __name__ == "__main__":
    sys.exit(main())
