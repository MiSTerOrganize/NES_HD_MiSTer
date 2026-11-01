"""Negative control for the hd3_resolve unit test: each mutant of the RTL must FAIL the suite.

A check that has never been seen to fail proves nothing. Each mutation below is a plausible
real bug; the runner copies hd3_resolve.sv with that one change, builds the testbench into its
own folder, runs run_resolve.sh with it and requires a failure (a mismatch, a testbench error
or a hang). Every anchor must occur exactly once in the source, so a stale anchor fails loudly
instead of producing an unmutated "mutant" that passes. The real RTL is built and run first and
must PASS, or the control means nothing. Mutants marked "small" are also built with the rule
store capped (RS_MAX=64) and run on the overflow fixture.

A mutant that is NOT caught is a coverage gap in the fixtures, not a pass: either the suite
needs a frame that exercises it, or the mutation is not observable (say why in its name).

usage: python neg_resolve_rtl.py <testdata dir> <pack dir> [mutant name substring]
"""
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
RTL_DIR = os.path.join(ROOT, "rtl", "hdpack")
RTL = os.path.join(RTL_DIR, "hd3_resolve.sv")
OTHERS = [os.path.join(HERE, "hd3_resolve_tb.sv"), os.path.join(RTL_DIR, "hd3_dict.sv"),
          os.path.join(RTL_DIR, "hd3_lookup.sv")]

# name: (anchor, replacement, needs the small build)
MUTANTS = {
    "memo stores the value before negation":
        ("mm_wd <= {1'b1, res ^ c_neg};", "mm_wd <= {1'b1, res};", False),
    "rewrite-sensitive condition evaluated instead of deferred":
        ("if (fq_q[24] && !bgm) begin               // rewrite-sensitive",
         "if (1'b0) begin               // rewrite-sensitive", False),
    "stop ignores deferred conditions":
        ("(wptr == 32'd0 && !later) ? S_LEND : S_NEXT;", "(wptr == 32'd0) ? S_LEND : S_NEXT;", False),
    "never stops at an unconditional rule":
        ("(wptr == 32'd0 && !later) ? S_LEND : S_NEXT;", "(1'b0) ? S_LEND : S_NEXT;", False),
    "kept rule loses its deferred frame list":
        ("later ? fptr[19:0] : 20'd0", "20'd0", False),
    "last prefix read from the first rule":
        ("fq_addr <= lbase + {fq_q[23:0], 1'b0};       // qB of rule n-1",
         "fq_addr <= lbase + 25'd2;       // qB of rule n-1", False),
    "prefix flag dropped":
        ("pfx   <= fq_q[57];", "pfx   <= 1'b0;", False),
    "memoryCheckConstant ignores the mask":
        (": cmp8(ma & c_mask, c1[15:8], c_op);", ": cmp8(ma, c1[15:8], c_op);", False),
    "memoryCheck compares A with itself":
        ("cmp8(ma & c_mask, v_q & c_mask, c_op)", "cmp8(ma & c_mask, ma & c_mask, c_op)", False),
    "operator > tested as <":
        ("4'd2: cmp8 = a >  b;", "4'd2: cmp8 = a <  b;", False),
    "operator <= tested as <":
        ("4'd4: cmp8 = a <= b;", "4'd4: cmp8 = a <  b;", False),
    "frameRange >= tested as >":
        ("res <= rem[15:0] >= c1[31:16];", "res <= rem[15:0] > c1[31:16];", False),
    "frameRange uses the wrong frame number":
        ("frame <= d_frame;", "frame <= d_frame + 32'd1;", False),
    "tileAt/spriteAt palette ignored":
        ("wire        tm_pal  = c_ign || (t_lane ? lpal : rec_pal) == c3[31:0];",
         "wire        tm_pal  = 1'b1;", False),
    # (the added-sprite palette branch, t_lane ? lpal, cannot be reached here: the resolve
    # testbench has no additions - neg_render_rtl.py carries that mutant on the render chain)
    "tileAt reads the next line's header":
        ("{9'd0, py, 8'd0};          // line py's header",
         "{9'd0, py + 8'd1, 8'd0};          // line py's header", False),
    "spriteAt cover window 9 pixels":
        ("px - fq_q[45:38] <= 8'd7", "px - fq_q[45:38] <= 8'd8", False),
    "spriteAt ignores the sprites-shown bit":
        ("if (!b0[6] || h0[55:48] == 8'd0)", "if (h0[55:48] == 8'd0)", False),
    "spriteAt palette taken from the BG groups":
        ("t_spr ? {1'b1, qa[47:46]}", "t_spr ? {1'b0, qa[47:46]}", False),
    "tileAt fallback never tried":
        ("end else if ({16'd0, t_idx} < fb_len) begin", "end else if (1'b0) begin", False),
    "fallback map word halves swapped":
        ("(t_idx[0] ? fq_q[63:32] : fq_q[31:0])} == c2;", "(t_idx[0] ? fq_q[31:0] : fq_q[63:32])} == c2;", False),
    "CHR-RAM tile fingerprint ignored":
        ("t_fp  <= game_ram ? fq_q : 64'd0;              // CHR-ROM",
         "t_fp  <= 64'd0;              // CHR-ROM", False),
    "legacy flag ignored":
        ("wire  [7:0] top     = legacy ? 8'h00 :", "wire  [7:0] top     = 1'b0 ? 8'h00 :", False),
    "list cache hit drops the deferred flag":
        ("later <= fl_q[0];", "later <= 1'b0;", False),
    "list cache tag not compared":
        ("if (fl_q[30] && fl_q[29:2] == fptr[27:0] && fptr[31:28] == 4'd0) begin",
         "if (fl_q[30]) begin", False),
    "list table shares lists without comparing offsets":
        ("if (lt_q[LTW-1] && lt_q[LTW-2 -: 25] == offq) begin", "if (lt_q[LTW-1]) begin", False),
    # ---- background selection (8i), checked by check_bg.py against bg_golden.py ----
    "bg: value index hashed with zlib's polynomial":
        ("? 32'h04C11DB7 : 32'd0);", "? 32'hEDB88320 : 32'd0);", False),
    "bg: value index CRC seeded with all ones":
        ("crc <= 32'd0;", "crc <= 32'hFFFFFFFF;", False),
    "bg: bucket drops the low bit":
        ("(crc + pp) & (sg_nb - 32'd1);", "(crc + pp) & (sg_nb - 32'd2);", False),
    "bg: probing stops one short of max_probe":
        ("if (pp == sg_maxp) begin", "if (pp + 32'd1 >= sg_maxp) begin", False),
    # NOT a mutant: "invalid table entry read as a match" (S_GCL's valid test forced false) is
    # output-equivalent. An empty slot is all zeros: its key differs from any value set with a
    # nonzero byte, and when the values are all zero it matches with count 0 - no candidates,
    # the same as the invalid path. The converter never deletes, so no probe runs past an empty
    # slot to a live entry. Probing just continues to maxp and gives up: same result.
    "bg: entry values not compared":
        ("vdiff  <= {fq_q, pq0} != vals;", "vdiff  <= 1'b0;", False),
    "bg: snapshot value not masked":
        ("vals[8 * tj +: 8] <= v_q & sg[8 * (3 + 2 * tj) +: 8];", "vals[8 * tj +: 8] <= v_q;", False),
    "bg: one term fewer than the signature has":
        ("if ({4'd0, tj} >= sg_n) begin", "if ({4'd0, tj} + 5'd1 >= sg_n) begin", False),
    "bg: signature count read from the low half always":
        ("nsig <= g_cnt_a[2] ? fq_q[63:32] : fq_q[31:0];", "nsig <= fq_q[31:0];", False),
    "bg: candidate list read one word late":
        ("la + {li[25:0], 2'b00};", "la + {li[25:0], 2'b00} + 28'd4;", False),
    "bg: highest candidate taken first":
        ("for (i = 31; i >= 0; i = i - 1) if (v[i]) lowbit = i[4:0];",
         "for (i = 0; i <= 31; i = i + 1) if (v[i]) lowbit = i[4:0];", False),
    "bg: bitmap word kept from another level":
        ("((bm_q[37:32] == lvl + 6'd1) ? bm_q[31:0] : 32'd0) |", "(bm_q[31:0]) |", False),
    "bg: bitmap not cleared between frames":
        ("bm_we <= 1; bm_wa <= clr[9:0];  bm_wd <= 0;", "bm_we <= 0; bm_wa <= clr[9:0];  bm_wd <= 0;", False),
    "bg: level table halves swapped (index read as the rule list)":
        ("ioff <= fq_q[63:32];", "ioff <= fq_q[31:0];", False),
    "bg: unindexed level starts at entry 1":
        ("// unindexed: every entry in order\n\t\t\t\tgri <= 0;",
         "// unindexed: every entry in order\n\t\t\t\tgri <= 1;", False),
    "bg: gives up after the first failing entry":
        ("st <= S_GF;                               // the entry failed",
         "st <= S_GEND;                               // the entry failed", False),
    "bg: selection written to bank 0 only":
        ("bs_we <= 1; bs_wa <= {bk, lvl}; bs_wd <= {1'b1, payload[19:0]};",
         "bs_we <= 1; bs_wa <= {1'b0, lvl}; bs_wd <= {1'b1, payload[19:0]};", False),
    "bg: rewrite-sensitive condition deferred during selection":
        ("if (fq_q[24] && !bgm) begin               // rewrite-sensitive",
         "if (fq_q[24]) begin               // rewrite-sensitive", False),
    "bg: memo seed not written":
        ("sd_we <= 1; sd_wa <= {bk, c_memo}; sd_wd <= {1'b1, res};",
         "sd_we <= 0; sd_wa <= {bk, c_memo}; sd_wd <= {1'b1, res};", False),
    "bg: memo seed stores the negated value (render negates on read)":
        ("sd_wd <= {1'b1, res};", "sd_wd <= {1'b1, res ^ c_neg};", False),
    "bg: memo seed not cleared between frames":
        ("sd_we <= 1; sd_wa <= {bk, clr[10:0]}; sd_wd <= 0;",
         "sd_we <= 0; sd_wa <= {bk, clr[10:0]}; sd_wd <= 0;", False),
    "bg: selection read port follows resolve's bank, not the frame's":
        ("g_q <= bgsel[{g_bank, g_lvl}];", "g_q <= bgsel[{r_bank, g_lvl}];", False),
    "next rule read one rule too far":
        ("fq_addr <= lbase + 25'd3 + {ri[23:0], 1'b0};", "fq_addr <= lbase + 25'd5 + {ri[23:0], 1'b0};", False),
    "next condition word skips one":
        ("cp <= cp + 28'd4;", "cp <= cp + 28'd8;", False),
    "full rule store not reported":
        ("lkind    <= 2'd2;", "lkind    <= 2'd1;", True),
    "list table not cleared between frames":
        ("lt_we <= 1; lt_wa <= clr[10:0]; lt_wd <= 0;", "lt_we <= 0; lt_wa <= clr[10:0]; lt_wd <= 0;", False),
}


def build(rtl, mdir, small=False):
    env = dict(os.environ, OBJ=mdir.replace("\\", "/"))
    if small:
        env["VFLAGS"] = "-GRS_MAX=64"
    b = subprocess.run(["sh", os.path.join(HERE, "build_one.sh"), "hd3_resolve_tb",
                        os.path.join(HERE, "tb_resolve.cpp"), OTHERS[0], OTHERS[1], OTHERS[2], rtl],
                       env=env, capture_output=True, text=True)
    return b.returncode == 0, b.stdout[-800:] + b.stderr[-800:]


def suite(mdir, td, packs, small_dir=None):
    """Return (passed, summary)."""
    env = dict(os.environ, EXE=os.path.join(mdir, "tb_resolve.exe").replace("\\", "/"),
               OUT=mdir.replace("\\", "/"))
    if small_dir:
        env["SMALL_EXE"] = os.path.join(small_dir, "tb_resolve.exe").replace("\\", "/")
    # the goldens live in obj/dict; the suite reads them from OUT, so copy them in
    gold = os.path.join(HERE, "obj", "dict")
    for f in os.listdir(gold):
        if f.startswith("rg_") or f.startswith("bgg_"):     # bgg_: background goldens (8i)
            shutil.copy(os.path.join(gold, f), mdir)
    try:
        r = subprocess.run(["sh", os.path.join(HERE, "run_resolve.sh"), td, packs], env=env,
                           capture_output=True, text=True, timeout=3600)
    except subprocess.TimeoutExpired:
        return False, "suite hung"
    lines = [ln for ln in r.stdout.splitlines() if ln.strip()]
    bad = [ln.split(": ", 1)[-1] for ln in lines if " 0 mismatches" not in ln]
    return r.returncode == 0, "; ".join(bad) if bad else "all pass"


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    td, packs = sys.argv[1], sys.argv[2]
    only = sys.argv[3] if len(sys.argv) > 3 else None
    with open(RTL, encoding="utf-8") as f:
        src = f.read()
    work = os.path.join(HERE, "obj", "neg_resolve")
    os.makedirs(work, exist_ok=True)

    base = os.path.join(work, "_baseline")
    shutil.rmtree(base, ignore_errors=True)
    os.makedirs(base)
    ok, log = build(RTL, base)
    ok2, log2 = build(RTL, os.path.join(base, "small"), small=True)
    if not (ok and ok2):
        print(f"BUILD FAILED [baseline]\n{log}{log2}")
        return 2
    passed, why = suite(base, td, packs, os.path.join(base, "small"))
    print(f"baseline: {why}", flush=True)
    if not passed:
        print("FAIL: the unmutated RTL does not pass - fix that before trusting the control")
        return 2

    caught, missed = 0, []
    for idx, (name, (old, new, small)) in enumerate(MUTANTS.items()):
        if only and only not in name:
            continue
        n = src.count(old)
        if n != 1:
            print(f"ANCHOR ERROR [{name}]: found {n} times")
            return 2
        # short, unique: a long folder name pushes Verilator's generated paths past Windows'
        # 260-character limit
        tag = "%02d_" % idx + "".join(ch if ch.isalnum() else "_" for ch in name)[:24]
        mdir = os.path.join(work, tag)
        shutil.rmtree(mdir, ignore_errors=True)
        os.makedirs(mdir)
        mrtl = os.path.join(mdir, "hd3_resolve.sv")
        with open(mrtl, "w", encoding="utf-8", newline="\n") as f:
            f.write(src.replace(old, new))
        ok, log = build(mrtl, mdir)
        sdir = None
        if ok and small:
            sdir = os.path.join(mdir, "small")
            ok, log = build(mrtl, sdir, small=True)
        if not ok:
            print(f"BUILD FAILED [{name}]\n{log}")
            return 2
        passed, why = suite(mdir, td, packs, sdir)
        if passed:
            missed.append(name)
            print(f"MISSED  {name}", flush=True)
        else:
            caught += 1
            print(f"CAUGHT  {name}  ({why[:160]})", flush=True)
    total = len([m for m in MUTANTS if not only or only in m])
    print(f"{caught}/{total} mutants caught")
    for m in missed:
        print(f"  not caught: {m}")
    return 0 if not missed else 1


if __name__ == "__main__":
    sys.exit(main())
