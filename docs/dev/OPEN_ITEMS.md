# NES HD pack - open items (working list)

User directive 2026-10-17: "Do all open items". Ordered by dependency; each item is closed only
when its RTL, its test against the reference (hdref / Mesen) and its negative control are done
and HDPACK_DESIGN.md says so. Quartus runs once, at the very end, SEED 1 -> 20, then stop.

Status key: OPEN / IN PROGRESS / CLOSED (date, where documented).

## A. Stage 4 inside the renderer (hd3_resolve + hd3_render)
1. 8i/8j backgrounds: selection in hd3_resolve (40 levels, first passing entry per level, the
   value index for large levels), drawing in hd3_render (layers between sprites/BG, scroll
   ratios, offsets, blend Alpha/Add/Subtract, brightness baked), per-line row cache.
   Test: check_render without --no-bg. CLOSED 2026-10-25: simulation complete 2026-10-20 (below)
   and the NES.sv integration it waited on is done (item 10). Kept for history.
   8i built (scratch): selection by per-level candidate bitmap, pack-format CRC, seed stored
   before negation, read port on render's bank (g_bank). All resolve fixtures 0 mismatches.
   8j built (scratch): frame load + line prep + 50-step compose; one-clock background steps.
   All 16 base frames, the a034/p002/a057_bg fixtures (Add / Subtract / moved / negative
   ratios) and the NSLOT=4 build pixel-exact; worst backlog 3.5 lines (SMB 300).
   2026-10-17 (checked): promoted to rtl/tools; run_render.sh carries mmmbg/cvbg/z2bg, the
   sens and z2seed fixtures and the NSLOT=4 / RS_MAX=64 / RAW=6 builds; the full suite (with
   additions) passed as neg_render's "all" baseline. Left: neg_render_rtl.py over EVERY mutant
   (the 18 background mutants and "memo not seeded" have never been run against the final
   RTL; queued after the lane run), neg_resolve_rtl.py (running), test_render_all.sh.
   The loader must export the new bases (item 10).
   2026-10-20: neg_render_rtl.py over the promoted RTL: baseline passes, 54/54 run mutants caught,
   1 equivalent (prefetch tag level bits; proof in the script's EQUIVALENT table). Three misses
   closed with new fixtures: make_bg_frame.py --edges (z2bge, cvbge) and make_vscroll_rec.py
   (mmmbgv, z2bgv) - HDPACK_DESIGN.md "8i/8j" correction note.
   2026-10-20: neg_resolve_rtl.py over the promoted RTL: baseline passes all fixtures, 50/50
   mutants caught (incl. the 21 background-selection mutants and the memo-seed ones).
   2026-10-20: test_render_all.sh over the promoted RTL: rc 0 - cache unit 3/3, fmap all pass,
   every render group PASS on the normal, NSLOT=4, RS_MAX=64, OF_LOG2=1, RAW=6, NL=64 and
   NL=64 RS_MAX=1 builds, 8k index fixtures 4/4 on both; worst backlog 3.5 lines (smb300).
   Simulation side of item 1 complete; remaining work is the NES.sv integration (item 10).
2. 8a additions: candidate sprites per pixel, nearby reads see them, the line-0 / pixel (0,0)
   copy rule, frame-memo order vs additions in hd3_resolve. Test: check_render without
   --no-add. CLOSED 2026-10-25: suites, negative controls and the stage-3 abort are all done
   (below and item 10, which wired the ADD abort into hd3_engine). Kept for history.
   Done 2026-10-17: pack sections 16/17 (converter + hdp3_addtab, independent check in
   hdp3_read, neg_read_addtab 6/6, corpus patched, originals in out/pre8a/); hd3_loader
   exports + refusal 11; hd3_add (frame sweep, per-line burst plan, abort/ovf) with 16 suites
   at 0 differences and neg_add_rtl 29/29 (one mutant documented output-equivalent).
   Done 2026-10-17: neg_loader 21/21; hd3_resolve + hd3_render read the lanes (pixel-list
   merge, pixel (0,0) from line 239 + line 240's lanes, line 0 header from line 239, added
   sprite runs, spriteAtPosition / spriteNearby targets, NOTILE / CHR-RAM added sprites never
   match); hd3_render_tb runs dict -> add -> resolve -> render; check_render includes additions
   by default and decides lane overflow itself from the addhw model (--nl). Base sets pixel-
   exact. New render fixtures make_add_draw.sh (z2d / cvd: added keys with opaque HD payloads)
   are pixel-exact on NL=16 and NL=64 builds and decisive (no-addition reference differs by
   312..37,216 px a frame); z2mix / cvmix decisive by overflow; z2t/cvt/z2s/cvs/z2e pass as
   correctness checks. Resolve tb rebuilt (ports tied, 0 warnings), all fixtures 0 mismatches.
   neg_render extra=add found a gap: "lanes appended only where sprites are shown" MISSED (no
   recording hides sprites where an added sprite lands). Fixture made (make_add_draw.sh now
   also writes obj/dict/rec_z2dhid + rec_cvdhid, sprites hidden on the left half): the real
   NL=64 build passes both sets, the mutant fails 3 of 4 frames (6,180-17,184 px). OWED: add
   "z2dh obj/dict/a057_addd.hdp 0 obj/dict/rec_z2dhid 1|0:0700 1:0300" and
   "cvdh obj/dict/p002_addd.hdp 1 obj/dict/rec_cvdhid 1|0:0250 1:0700" to run_render.sh adds()
   AFTER the running neg_render runs finish (they re-read run_render.sh per mutant), then
   re-run that mutant: python neg_render_rtl.py T P "sprites are shown".
   2026-10-20 (checked): z2dh and cvdh ARE in run_render.sh adds() (lines 100-101), and the
   2026-10-20 neg_render_rtl run over the promoted RTL caught every mutant it ran (item 1), so
   the "owed" note above is done.
   Left: tb_loader over the 137-pack corpus (alive; output is block-buffered, not stuck);
   neg_render_rtl extra=add (14 lane mutants, NL=64 build) running; full test_render_all.sh
   incl. NL_EXE; HDPACK_DESIGN.md "8a - as built"; the stage-3 controller's abort (B).
3. 8h 16th sprite / disableSpriteLimit: more than 8 sprites per line (extra-sprites tap).
   DONE in simulation (HDPACK_DESIGN.md "8h - a pack's disableSpriteLimit"). The tap was done
   2026-10-16. 2026-10-17: ppu.sv hd_nolimit (extras forced, Mesen's adaptive rule in OAMEval
   over dots 0-63), nes.v / fullsim (--nolimit) wired, test_exspr.py rows D + E + two forced
   runs: ALL PASS (both sprite sizes). Negative control neg_exspr.py 9/9 caught (6 new 8h
   mutants). A pre-render block was removed as dead logic (the control proved it
   unobservable). Documented: above 15 sprites a line the core stops (Mesen 64). Left only:
   NES.sv driving hd_nolimit (item 10).
4. 8k CHR-RAM index conditions (a tile condition given as an index in a CHR-RAM game).
   IN PROGRESS - Mesen compares TileIndex = AbsoluteTileAddr/16 (set for CHR-RAM too), no
   fallback (spec 3.5); hd3_resolve already does this. Fixture obj/dict/p002_ix.hdp
   (make_ixram_cond.py: 1,341 conditions converted; flipping every index changes 591-3,368
   reference pixels per frame, so it is decisive). RTL: per-pixel restart for nearby types,
   frame-record fetch through hd3_rcache with a new uncached `byp` mode, CHR-RAM index branch
   in tmatch. Second fixture obj/dict/p002_ixh.hdp (`--shift 3 --palmix`: nearby offsets
   moved off the 8-pixel grid, palettes mixed) found a real bug: a sprite run is NOT an
   i_group, so a nearby index condition there was evaluated once (e_uni) at the first pixel
   and applied to the whole run. Fixed (scratch copy): nearby index conditions are never
   uniform and go down the single-pixel path pixel by pixel; the forced build that sends
   EVERY nearby condition down that path also matches hdref (p002_ds.hdp, `--keep-data`).
   All four index fixtures pass (ix, ixh, ixs shift-only, ixp palmix-only).
   CLOSED 2026-10-17 (HDPACK_DESIGN.md "8k"): promoted to rtl/tools; full suite passes;
   neg_ix 11/11, neg_cache 14/14, neg_render_rtl 21/21. Cost recorded there (worst line
   32,760 clocks on p002_ix; no corpus pack has an index condition in a CHR-RAM game).
   2026-10-20: neg_ix re-run on the promoted renderer (line_ok / line_y ports): baseline PASS,
   11/11 caught. "index read through the cache" is caught by run_ix.sh's structural
   REQUIRE_IXR check (all 5 frames made 0 uncached index reads), not by a pixel difference -
   as designed; neg_ix.py now prints that FAIL line as the reason (it showed an empty reason).
5. 8o what the renderer outputs when hd3_dict overflows (more than 2,048 records).
   CLOSED 2026-10-17 (HDPACK_DESIGN.md "8o"): a frame whose dictionary overflowed is drawn
   with no HD lookups. RAW=6 build in run_render.sh (Castlevania overflows every frame, the
   other games stay under). Full suite + neg_dict_rtl 16/16 + resolve passes; neg_render
   mutants "overflowed frame still looked up" and "sprite list loses the behind-background
   bit" (the Verilator find4 miscompile found on the way) both caught.
6. fmap unit test. CLOSED 2026-10-17 (HDPACK_DESIGN.md "hd3_fmap unit test"): run_fmap.sh
   passes, neg_fmap.py 14/14, now part of test_render_all.sh; the hd3_fmap comment corrected
   (at most 7 bursts in flight, not "fewer than 6").
   2026-10-20: re-run on the final RTL: baseline all pass, 20/20 caught (the mutant set grew to
   20 with 8a; HDPACK_DESIGN.md already lists 20).
7. Render speed levers (tileNearby drain, condition cache misses, line load overlap, BG image
   instances) - only if the integrated budget needs them; measure after 1-3. CLOSED 2026-10-21:
   NOT NEEDED, measured. run_engine.sh full on the RTL as of 2026-10-21 (obj/run_engine_full_1021.log,
   33 shown frames over the corpus-content sets smb, light, the Castlevania/Zelda II/Metroid packs and
   the stress fixtures): dropped 0, underflow 0, overrun 0 on every frame. aborted_add is non-zero
   ONLY on the synthetic lane stress fixtures (lane, lanenz, laneov: 17 lanes > NL 16; cvd: 35-52;
   cvmix: 2,073-2,176), where "addition overflow, drawn without lookups" is the required result and
   the reference agrees to 0 pixels. No real content aborts ADD or underflows scan-out, so no render
   lever is owed. The one measured lever (8k index-condition target cache, p002_ix 183-line backlog)
   still has no corpus pack that needs it. Re-open if the hardware compile (item 15) runs the engine
   below 85.9 MHz, or a new pack underflows.
   Measured lever (2026-10-17): 8k index conditions cost one uncached burst per target read -
   p002_ix frame 250 mean 9,474 / worst 32,760 clocks per line (183-line backlog). An exact
   1,024-entry target-index cache {kind, line, slot/fetch}, cleared in S_MCLR, would fix it; no
   corpus pack needs it (HDPACK_DESIGN.md "8k").

## B. Integration
8. 8f engine on the 85.9 MHz clock; savestate channel crossed into it. CLOSED 2026-10-25 in
   simulation (promoted 2026-10-20, every check owed by the front-end fixes re-run 2026-10-21);
   the 85.9 MHz timing itself is item 15's Quartus run. Was IN PROGRESS
   (HDPACK_DESIGN.md "Stage-3 engine (8f)"). 2026-10-19: run_engine.sh full ALL PASS (0 px
   differing, 946,503 savestate accesses, 0 failures); neg_engine.py 34/34 caught after the
   light / pace cases, the tb_engine pacing monitors and the ring garbage fill closed 5 misses.
   2026-10-20: PROMOTED to rtl/hdpack + tools/sim3 (hd3_engine/cross/scanout/romfix/sha1, newer
   hd3_loader/hd_stage2/hd_watch; NES.sv; files.qip and the fullsim list now name the hd3_*
   files and drop hd_engine/hd_ddr; old repo copies backed up in the scratchpad). From the repo:
   lint 0/0, run_engine.sh quick ALL PASS, romfix_cases.py 38/38 (earlier notes said 40/40; the result file
   has 19 cases / 38 runs), test_sha1.py 416/0 wrong,
   neg_loader 30/30 + 4 not observable (exit 3). Gap found: neg_loader accepted a pack set with
   no addition tables and "missed" the two section-16/17 mutants for the fixture's sake - it
   now refuses such a set (FIXTURE ERROR), as it already did for lists and patches.
   From the repo: neg_engine 34/34; neg_romfix 31/32 + 1 output-equivalent (after the
   back-pressure case, item 12); neg_sha1 9/9; neg_patch 13/13 (re-run after a first run was
   stopped by the low-memory reaper at 10/10).
   2026-10-21: neg_engine.py re-run over the RTL as it stands after the 2026-10-20 render /
   resolve promotion (no rtl/ file is newer than the tb_engine build its baseline ran on;
   run_engine.sh full ALL PASS that day): 34/34 caught, rc 0. romfix_cases.py on the same RTL:
   20 cases / 40 runs, ALL PASS, rc 0. Since the 2026-10-20 13:35 front-end fixes (hd3_add,
   hd3_ccache, hd3_rcache, hd3_render, hd3_resolve) these have re-run: run_engine full,
   test_render_all, neg_render 54/54, neg_resolve 50/50, neg_engine 34/34, romfix_cases 40/40.
   neg_add_rtl.py: baseline 15/15, 29/29 caught + 1 documented output-equivalent, rc 0 (its
   suite list is run_add.sh's 16 minus cvsser, the slow serial-DDR3 case). GAP FOUND:
   test_render_all.sh does not run run_add.sh, and obj/add*/tb_add.exe dated from 2026-10-17,
   so the 16-suite hd3_add unit test had never run on the 10-20 edit. Both builds (NL=64,
   NL=16) rebuilt from rtl/ and run_add.sh run: 16/16 suites 0 differences (z2srcl, cvmix,
   cvs16 check 0 pixels by design - every frame is "overflow as required", and check_add.py
   fails on an ovf mismatch). neg_cache.py (rebuilds from rtl/): baseline all pass, 14/14
   caught, rc 0. neg_ix.py (rebuilds from rtl/): baseline PASS, 11/11 caught, rc 0. Every
   simulation check owed by the 10-20 front-end fixes is now done (item 15's note).
   Regression list written (HDPACK_DESIGN.md "Regression list"): run_add.sh, run_engine,
   romfix_cases, test_sha1, test_hdp3_patch and the new tools/msim_check.sh (ModelSim
   front-end + $readmemh ROM check, PASS; negative-checked: missing .hex and the undone
   part-select fix both FAIL). test_sha1 416/0, test_hdp3_patch ALL PASS.
9. 8m dict + watch read-port sharing between RESOLVE and RENDER. CLOSED 2026-10-25 (superseded
   by the 2026-10-17 decision in HDPACK_DESIGN.md "Frame budget and the dictionary read port
   (8m)"): fmap left the vblank chain and snoops capture writes into two banks, so the dictionary
   read port has one owner at a time (ADD, then RESOLVE, RENDER otherwise) and no second port is
   needed. The integrated engine (item 10) runs that ownership; run_engine full ALL PASS.
10. NES.sv integration: hd_stage2 + hd3_* + hd3_ddr replace the MVP engine; output to the
    video path; full-system sim (fullsim) against hdref on recorded games. CLOSED 2026-10-25:
    integrated and checked end to end on Metroid and Castlevania (below); a further game is
    optional. Was OPEN
    Wiring owed by 8i/8j: the loader exports the section bases hd3_resolve/hd3_render read
    (conds s2, clist, bgl s5, bgi s13, bgrec s6, maps s7, ratios s8); resolve's g_/s_ read
    ports to render's gs_/sd_ (render's bank); render's new DDR3 read port B into hd3_ddr.
    Wiring owed by 8h: nes.v's hd_nolimit (tied 1'b0 in NES.sv today) = hd3_loader
    options[0] (header 0x0C bit 0, disableSpriteLimit; 37 of the 137 corpus packs set it)
    AND the HD picture enabled (OSD on + pack loaded). Gate it on BOTH: Mesen applies the
    option only while the pack is in use, and it changes the SD picture too.
    Wiring owed by 8a: the stage-3 controller's abort when hd3_add flags ovf.
    2026-10-20: the wiring above is in the promoted hd3_engine / NES.sv (section bases from the
    loader, render's DDR3 port B, hd_nolimit = disableSpriteLimit AND the HD picture on, the
    ADD abort - tb_engine's lane fixture shows aborted_add 1). NES.sv in the repo is now the
    integrated one. Left: the first whole-core fullsim build with hd3_engine and a run against
    hdref/Mesen; Quartus finding hd3_render's $readmemh .hex files from the project folder.
    2026-10-21: fullsim builds the integrated core (hd_stage2 + hd3_engine + hd3_ddr). Found and
    fixed: under Verilator hd3_render took bare .hex names, so from the project folder (where
    fullsim runs, as Quartus does) all four ROMs loaded as zeros; new define HD3_HEX_PROJECT
    (fullsim build.sh sets it) and fullsim refuses to start if the files are missing (tested:
    rc 2 from tools/). Metroid + a034 (mmm.ips), 400 frames: 0 dropped, 0 aborted, 0 underflow,
    0 overrun, 0 dictionary overflow; hdv frames 0/100/200/300 == hdref, 0 px; hd frames
    100/300/400 == Mesen 102/302/402 exactly, hd 200 == Mesen 201 exactly (one-frame offset on a
    title-animation step). Quartus .hex resolution is checked by tools/msim_check.sh (ModelSim,
    same project-folder paths) and gets its final confirmation from the item-15 compile.
    Still open here: fullsim against further games (only Metroid run so far).
    2026-10-21: Castlevania + p002 (CHR-RAM, cv_play.txt), 1000 frames: drawn 1000, dropped 0,
    aborted 0, underflow 0, overrun 0, dictionary overflow 0; NES vs video.sv 0 px on every
    sampled frame; all 20 hdv frames (0, 50, ... 950) == hdref, 0 px (check_render.py,
    7.7k-39k background lookups per frame). Against Mesen (scratchpad cv_fullsim_mesen.py,
    each frame paired by its own SD shot as HDPACK_DESIGN.md "Castlevania p002" requires):
    frames 700 and 1000 equal Mesen outside the known partial-alpha mask (1025 / 1018 px inside
    it); frames 250 and 450 differ by ~18.6k px, ALL of it the recorded one-frame FrameNumber
    phase - the core equals hdref at its own numbering (0 px) and hdref at Mesen's numbering
    (--frame-delta -1) equals Mesen outside the mask (0 px). Two games now pass end to end.
    Left: a further game is optional, not owed.
11. 8l M10K budget and 8g ALM budget: per-entity estimates, the 2-entry output FIFO
    candidate, composite_decoder (user decision - ask, do not decide). OPEN
    2026-10-21 M10K half MEASURED (HDPACK_DESIGN.md "M10K budget (8l)"): everything but the MVP
    used 160 of 553 blocks in the 2026-10-15 fit, leaving 393; the stage-3 engine's memories,
    elaborated by Verilator with parameters resolved, need about 457-496. OVER BY ~64-103
    BLOCKS. The two snooping fmap banks alone are 112. Levers listed there (one fmap bank -56,
    dictionary key/record width, scan-out ring, 2-entry output FIFO, composite_decoder); none
    applied. ALM half needs a Quartus run, which the rule defers to the final state - but the
    budget decides what the final state is. Both are put to the user.
    User 2026-10-21: synthesis-only Quartus run approved now (full fit + SEED 1-20 still waits for
    the final state); composite_decoder decided after synthesis; savings looked for elsewhere
    before touching the two fmap banks.
    FOUND BY THAT RUN: Quartus 17 crashed in elaboration ("Internal Error: Sub-system: VRFX ...
    veriname_elab.cpp line 836: read to RAM wasn't mapped to a specific read port"). Bisected
    standalone (hd3_add as top, 11 s per run): the module-array read fx[i] inside function rank()
    in hd3_add. Removing just that read made synthesis succeed. Fixed by passing fx into rank()
    as a packed 128-bit vector (logic unchanged); hd3_add alone then synthesizes, run_add.sh
    16/16 suites 0 differences. The whole design then elaborates past hd3_add with no further
    crash. No simulator (Verilator, ModelSim front-end) flags this construct - only Quartus did,
    which is the argument for running synthesis before the final state.
    SYNTHESIS RESULT (2026-10-21 14:02, output_files/NES.map.rpt, successful, 0 errors):
    THE DESIGN DOES NOT FIT THE CYCLONE V, BY ABOUT 2X IN LOGIC AND ~1.2X IN BLOCK RAM.
      whole design  126,652 combinational ALUTs, 147,815 registers, 5,455,382 block-memory bits
                    (96 % of the bits), 112 / 112 DSP. Calibrated on the 2026-10-15 fit (57,848
                    ALUTs + 55,900 registers -> 42,539 ALMs, ~0.74 ALM per ALUT): ~90,000+ ALMs
                    against 41,910.
      hd3_engine    67,787 ALUTs, 87,752 registers, 4.25 Mbit, 18 DSP. hd3_render alone 39,434
                    ALUTs / 49,553 registers (its own logic: wide lane/plan vectors, not memories);
                    hd3_add 7,495 / 12,991; hd3_dict 5,809 / 11,800; hd3_resolve 5,122 / 5,517;
                    hd3_audio 4,764 / 2,904; hd3_romfix 3,761 / 2,569.
      everything else (NES 28,682, hd_stage2 7,588, composite_decoder 1,337, framework) about
                    58,900 ALUTs, ~43,000 ALMs: the device is already full WITHOUT the engine.
      M10K, priced by shape from the RAM summary: ~678 of 553. kmem is built TWICE (two read
                    ports: kmem_rtl_0 and _rtl_1, 40 each); hd_stage2 has grown to 65 (chrfp
                    shadow 32768 x 8 = 32).
      The 14 arrays Quartus did not infer as RAM are all small (8-34 entries); the logic size is
      real logic, not memories falling into registers.
    This is beyond the listed levers: composite_decoder (~1,000 ALMs) and the trims in "M10K
    budget (8l)" are a few percent. The direction is a user decision (scope of the stage-3
    engine, the 2026-10-13 "pure FPGA, no ARM helper" decision, an HD build with fewer NES
    mappers, or a different device). Put to the user 2026-10-21.
    USER DIRECTION 2026-10-21: measure the ARM-helper route first (A9 benchmark) and list the
    mappers the corpus uses.
    MAPPERS THE CORPUS USES (2026-10-21, base ROM header from the No-Intro library + every IPS
    and BPS patch shipped in the pack applied to that header; scratchpad pack_games.tsv,
    game_mappers.py, bps_mappers.py):
      0 NROM 38 packs · 1 MMC1 29 (+ Ice Climber after its NEA .bps) · 2 UxROM 25 (+ the 3
      Gryzor packs = Contra (E), known UNROM, title not in the library) · 4 MMC3 6 (the two
      1942 music .ips switch NROM -> MMC3) · 5 MMC5 2 · 25 VRC4 1 (Bio Miracle) · 87 1 (TwinBee)
      · 99 VS (Ice Climber VS patches; their .bps sources are not in the library, so the
      target mapper is unverified) · not resolved: a105/_inner06 (HDNes-Graphics-Pac, game
      unknown), Battle City (J) x3 (title not in the library; NROM).
      Synthesis cost of the mapper block (cart_top): 12,408 ALUTs / 11,515 registers. Keeping
      0/1/2/4/5/25/87/99 (MMC1 49, MMC3 528, MMC5 343 + its audio 567, VRC24 224, 99 9, plus
      cart_top's own 1,374) is ~3,100 ALUTs, so the rest frees ~9,300 ALUTs / ~9,800 registers
      (~6,900 ALMs). Largest single items in the rest: NSF player 1,913, FDS audio 1,754 + FDS
      497, VRC7 audio 1,284.
      NOT A CUT LIST (user, 2026-10-21): "What if in the future more games get hd pack support
      and they have different mappers ... Careful what we remove." This is a measurement of
      TODAY's packs only. No mapper is removed on the strength of it; space comes from the ARM
      helper first. A trimmed-mapper build is a last resort, and then only as a separate HD
      build beside the full NES core, never a replacement for it.
    A9 FEASIBILITY BENCHMARK (2026-10-21, tools/armdec/):
      hdarm.c is the per-frame DECISION work in plain C (records, background choice, additions,
      every tile lookup with the BG 8-pixel cache and sprite draw order; compositing stays in
      the FPGA). hdref_decisions.py dumps the same decisions from hdref. parity.sh: 29 of 29
      recorded frames (a034 x9, p002 x6, p053 x5, a057 x9) byte-identical, and three mutants
      (ignore negate / no additions / nearby off by one) each caught (21 / 12 / 9 frames).
      A first pair of mutants (no fallback, no BG cache) changed NO decision on these frames
      and was replaced - a control that cannot fail proves nothing.
      The arm32 static build (bookworm gcc 12, -mcpu=cortex-a9, Docker) is identical on 4 of 4
      frames under QEMU. Two bugs on the way: mingw64 first on PATH swaps in a python with no
      numpy (references came out empty, hidden by a 2>/dev/null); 32-bit fstat without
      _FILE_OFFSET_BITS=64 fails with EOVERFLOW and the size read as 0.
      Dev-PC (x86) medians, a RANKING not an A9 figure: most frames 0.8-1.4 ms; heaviest
      p002 (Castlevania) frame 60 = 3.3 ms (150k rule walks, 148k condition evaluations).
      ON-DEVICE RESULT (2026-10-22 00:17 UTC, MiSTer at MENU, core 0, 20 iterations, -O2):
      PARITY 29 of 29 identical on the A9 itself. TIMING: EVERY frame is over the 16.6 ms budget.
        median per frame   28.9 ms (p053 f200, zero rules) .. 109.0 ms (p002 f60)
        a034 Metroid 38.6-63.1 · p053 SMB3 28.9-48.1 · a057 Zelda II 52.4-66.9 · p002 CV 59.0-109.0
        phases: records 17-18 ms on EVERY frame (building 61,440 pixel records from the 1 MB
        frame record); lookups 11-74 ms (scales with rules walked); additions 14-23 ms where a
        pack uses them; levels <0.3 ms.
        A9 is ~35-40x slower than the dev PC on this code (cache-missy hash walks over 7-74 MB).
      VERDICT: the straight per-pixel port does not fit, by 1.7x (best) to 6.5x (Castlevania).
      Not yet known whether a restructured version would: the FPGA capture could hand over the
      records (removes ~17 ms), and decisions per TILE rather than per pixel, or only for tiles
      that changed since last frame, cut the lookup work, but none of that is measured.
      Bundle left on the device at /media/fat/hdbench (bench.log = the raw result).
    ROUND 2, hdarm2.c (2026-10-22, user: "Proceed"). Same decisions, restructured: 32-byte
      pixel records with sprites in a block pool (2 MB/frame instead of 10), per-frame memos of
      table lookups and of whole results for lists that cannot vary by pixel, additions indexed
      by tile, and per-frame reduced rule lists (rules a type 0-2 condition already fails are
      dropped once per frame, their disableCache bit kept; rules holding a frame-memoised
      condition of another type are never dropped, since that would move its first evaluation).
      Parity: 29 of 29 on the PC AND on the A9; NEGATE/NOADD/NEARBY still caught; new control
      MUT_MEMOALL (memoise every list) differs on 12 frames, so the static test is load-bearing.
      A9 medians (bench2.log):
        SMB3 8.3-25.2 ms · Metroid 15.9-19.3 · Zelda II 19.8-26.1 · Castlevania 27.9-56.3
        phases: records 4-7.6 · lookups 4.2-42.7 · additions ~5 where used · levels <0.3
      2-3.5x better than round 1, still over 16.6 ms on 23 of 29 frames. Two floors are visible:
      an EMPTY frame (p053 f200, zero rules) costs 8.3 ms, i.e. just touching 61,440 pixel
      records twice is memory-bound on the A9; and Castlevania's ~74,000 per-pixel "tile nearby"
      checks are real per-pixel work no memo removes (42.7 ms of lookups on f60).
      Next lever if pursued: do not materialise per-pixel records at all -- read the 4-byte
      capture plus the per-line span/sprite tables directly (about 0.25 MB per pass instead of
      2 MB). That attacks the floor; it does not remove Castlevania's nearby checks.
    ROUND 3, hdarm3.c (2026-10-22, user: "Proceed"). No per-pixel record array: a pixel's tile
      record is rebuilt from the 4-byte capture entry + a per-line span table; only sprite
      pixels keep a block; the fallback tile-index rewrite lives in an overlay (bitmap + array,
      written through from get_matching); the additions pass's copy of each line's first pixel
      over (0,0) is modelled as an alias line P0L plus a copied sprite block.
      Parity 29 of 29 on PC and A9. Controls: NEGATE/NOADD/NEARBY caught; MEMOALL differs on 12;
      MUT_NOP0 ((0,0) alias off) differs on 2 -- exercised; MUT_NOWT (overlay write-through off)
      differs on 0 -- the overlay is NOT exercised by these 29 frames (correct by construction,
      unproven by test; OPEN: needs a frame or a hand-built case where a later condition reads
      a pixel whose tile index was rewritten).
      CLOSED 2026-10-22 - PROVEN by a hand-built case. tools/armdec/overlay_reach.py works out,
      from the pack alone, where the overlay can change a decision: a rewrite-sensitive
      tileNearby test (tile V) changes only for an X where (X==V or fb[X]==V) differs from
      (fb[X]==V or fb[fb[X]]==V), the reader must be a tile whose rule list holds the test,
      and the read pixel must be drawn before it. Over the 5 flagged packs ONE test qualifies:
      a033 (all four variants) "background tile 8 rows up is 5873", read from tiles 3750/4006,
      which reach that list only as SPRITES on palette ff153429. a034's only flagged test
      (offset 0,0, tile 2801) can never change: every tile falling back to one of its 14
      owners gives the same answer before and after - which is why no recorded frame showed it.
      tools/armdec/overlay_case.py builds that frame over a recorded one (background tile 5873
      on palette 0f271107, which misses and falls back to 1265; one tile-4006 sprite per line).
        a033_inner00, frame 600, tile 4006:          exact == reference; MUT_NOWT differs on 160 lines
        a033_alt_VanillaSlower, frame 1020, tile 3750: exact == reference; MUT_NOWT differs on 160 lines
      So the overlay is reached, and right. (A random fuzz, overlay_fuzz.py, never reaches it:
      the case needs a sprite on a specific palette under a specific background tile.)
      A9 medians (bench3.log):
        SMB3 5.6-23.9 ms · Metroid 12.6-16.9 · Zelda II 14.1-20.9 · Castlevania 22.1-53.1
        records now 0.4-3.9 ms; lookups 5.2-45.8 ms.
      Follow-up 3b (32-bit hash + last-hit check before the memo table): parity 29 of 29, timing
      UNCHANGED within noise (bench3b.log). The hypothesis that the memo probe was the per-pixel
      cost was wrong; what makes Metroid's lookups ~11 ms with almost no rules walked is not
      identified and would need a profiler on the A9.
      IDENTIFIED 2026-10-22 by ablation (scratchpad ovfuzz/abl.c, PC, a034 frame 600, 3 runs each;
      gprof gives no samples under mingw, so parts were switched off instead):
        full                                   lookups 0.47 ms
        get_matching skipped (hd = -1)         lookups 0.46 ms   - the lookup itself is ~free
        per-pixel record build skipped         lookups 0.04 ms
      ~90% of the pass is tile_rec(): building a full Rec for all 61,440 pixels every frame,
      although the 8-pixel cache reuses one answer per tile (match_hits 7,651 = one per tile).
      PC/A9 ratio ~30x (SMB3 frame) puts that at ~10-12 ms on the A9 - the unexplained cost.
      A fix would build the record only when the pixel's span slot changes (or the cache
      breaks), i.e. ~1 in 8 pixels. NOT applied: it only matters if the ARM does per-pixel
      work, which item 11 has ruled out (Castlevania stays over budget either way).
      CONCLUSION OF THE THREE ROUNDS: on the A9, frame-level work (levels, condition memo,
      reduced rule lists) is cheap (< 1 ms); per-PIXEL work is what costs, ~5 ms as a floor and
      up to ~46 ms for Castlevania's tile-nearby checks. ARM-only fails for Castlevania-class
      packs by ~3x and leaves Metroid / Zelda II at or over budget with no headroom for Linux,
      Main_MiSTer and handing decisions to the FPGA.
    HYBRID-SPLIT SIZING (2026-10-22, from the 2026-10-21 synthesis + the 2026-10-15 fit, no new
      Quartus run):
      free space today: the 10-15 fit was 42,539 ALMs (FAILED, 102 %) and included the old MVP
        hd_engine at 7,569 ALMs. Without it the core is ~34,970 ALMs, so ~6,900 ALMs are free.
        (NES 19,008 of which the mapper block 9,303; ascal 2,158; hd_stage2 3,037;
        composite_decoder 1,190.)
      stage-3 engine: 67,787 ALUTs x ~0.74 = ~50,000 ALMs. 7x the free space.
      what the ARM could take: hd3_resolve 5,122 + hd3_add 7,495 + hd3_dict's resolver (est.
        ~3,000 of its 4,751 own) + render's frame-memo / slow DDR3 list walk (not separable in
        the report; generous guess ~7,000 of its 35,500 own) = ~22,600 ALUTs = ~16,700 ALMs.
        Remainder ~33,000 ALMs: still ~5x the free space. Every mapper but today's corpus
        (~6,900 ALMs, NOT a cut list) would still leave it ~2.4x over.
      CONCLUSION: moving decisions to the ARM does not decide fit. The per-pixel renderer alone
        (hd3_render, ~29,000 ALMs est.) is ~4x the free space, and the ARM measurably cannot do
        per-pixel work in time. The report attributes render's size to wide lane/plan vectors
        (parallel hardware, not memories), so the open question is whether a SERIALISED renderer
        (fewer lanes, more clocks per pixel) fits the per-line time budget. That is the next
        thing to measure; otherwise the honest options are a smaller feature set in the FPGA or
        different hardware. Direction is the user's.
      Non-render engine is ALSO over: add 7,495 + dict 5,809 + resolve 5,122 + audio 4,764 +
        romfix 3,761 + small ~600 = ~27,500 ALUTs = ~20,000 ALMs. With the ARM taking resolve,
        add, the dictionary resolver, HD audio and the ROM SHA-1 (all per-frame or streaming
        work it is good at), ~2,500 ALMs remain, leaving ~4,400 for the renderer: a ~6x shrink
        from ~29,000. That is the bar any DE10-Nano design has to clear.
    FEATURE-USAGE STUDY (2026-10-22, user "Proceed"; tools/armdec/feature_usage.py, hdarm3.c
      HD_FEATOFF switch - default 0, parity 29/29 unchanged). Each feature switched off in turn
      (an unsupported condition fails), decisions diffed against the exact dump, 29 frames:
                                    Metroid     Castlevania   SMB3          Zelda II
        tile/sprite AT position     bg only     0             bg only       bg only (68 choices)
        tile/sprite NEARBY          320 px      4,096 px      32,544 px     2,304 px
        position checks (x/y)       0           0             0             0
        mirror / bg-priority        4,544 px    3,072 px      0             7,872 px
        additions                   0           1,666 px      0             5,440 px
        backgrounds                 every frame every frame   4 of 5        every frame
        memory / frame conditions   10,096 px   188,054 px    0             8,320 px
      (pixel totals over all frames of that game; SMB3 nearby peaks at 19,776 px in one frame)
      Every feature but position checks changes real frames, and the static census
      (scratchpad feature_survey.txt) has tileNearby in 31 packs, spriteNearby 37,
      tileAtPosition 68, spriteAtPosition 52, hmirror 26, additions 13, backgrounds ~63.
      A reduced feature set therefore breaks most packs; it is not the way to fit.
      WHAT IS ACTUALLY PER-PIXEL (the useful result): only nearby (5,6) and position (7-10)
      depend on the pixel being drawn. AT-position (3,4) reads a fixed screen position, so it is
      per-frame; mirror/bg-priority (11-13) depend on the record, so they are per-record; memory
      and frame conditions are per-frame; additions and background choice are per-frame. All of
      those can be resolved before the frame is drawn (ARM), leaving the FPGA renderer with: per
      pixel, a pre-filtered rule list whose only remaining conditions are nearby/position checks
      against the frame map. CAVEAT: rewrite-sensitive conditions (q0 bit 24) depend on lookup
      ORDER via the fallback rewrite, so an at-position check on a rewritten tile cannot always
      be settled up front - how many such conditions the corpus has must be counted before
      relying on this.
      COUNTED (tools/armdec/rewrite_census.py, all 137 packs): NO at-position, memory, frame,
      mirror or position condition is rewrite-sensitive. Only 13 tileNearby + 10 spriteNearby
      conditions in 5 packs are - and nearby stays in the FPGA anyway. So the up-front
      resolution holds for the whole corpus. Nearby is also the bulk of the corpus: 18,792
      tileNearby + 42,272 spriteNearby conditions vs 2,009 + 1,487 at-position.
      NEXT: size a renderer that does only that (nearby/position + fetch + composite), against
      the ~4,400 ALM bar.
    REDUCED-RENDERER SIZING (2026-10-22, user "Proceed"; standalone synthesis of hd3_render
      only, scratchpad qrender/ and ysz/min/, no change to the real RTL):
        Quartus, renderer alone, as shipped       28,712 ALUTs  19,073 regs  656,336 RAM bits
        Quartus, renderer alone, REDUCED           28,562 ALUTs  18,788 regs  631,760 RAM bits
          (reduced = no DDR3 slow path, no deferred frame memo, only nearby + position
          condition types: the renderer the ARM-split design would keep)
        yosys (synth_intel_alm), as shipped        ~18,700 LUTs + 5,626 arith, 8,480 FF,
                                                   612 MLAB cells, 102 M10K
      THE REDUCTION SAVES 150 ALUTs (0.5 %). The rule-checking machinery is a small sequential
      state machine; the renderer's size is its drawing logic (per-pixel sprite lists, the
      16-lane addition merge, background preparation, the 2x2 compose and blend), which any
      renderer of these packs needs. ~28,600 ALUTs is ~21,000 ALMs against the ~4,400 bar, and
      against the ~6,900 ALMs free today. CONCLUSION: no division of work between the ARM and
      the FPGA makes full HD-pack rendering fit the DE10-Nano. (Every MiSTer board, including
      the clones, uses this same Cyclone V 5CSEBA6.)
      WHOLE ENGINE SYNTHESISED ALONE (2026-10-22, Quartus 17.0 balanced, scratchpad qengine/):
        hd3_engine 49,325 ALUTs, 36,144 regs, 4,307,252 RAM bits, 18 DSP
          render 28,835 · audio 4,759 · resolve 4,462 · romfix 4,062 (sha1 1,247) · add 3,212
          dict 2,591 · loader 614 · ddr 320 · scanout 158 · fmap 93 · top 206
        Inside the full design the same engine measured 67,787 ALUTs, so ~18,500 ALUTs (27%)
        of that figure was the full build's cost, not the engine's (Resource Aware Inference
        For Block RAM is ON there, and the chip's M10K is over-subscribed, so memories were
        rebuilt from logic). CORRECTED FIT, at the 1.36 ALUTs/ALM ratio used throughout:
          whole engine ~36,300 ALMs against ~6,900 free             - 5.3x over
          ARM-split (ARM takes resolve/add/dict/audio/romfix = 19,086 ALUTs): FPGA keeps the
          renderer 28,835 + ~1,400 = ~22,200 ALMs                    - 3.2x over
          the renderer alone must shrink ~3.6x (21,200 -> ~5,900 ALMs)
        This narrows the gap from the "~6x" stated earlier to ~3.6x, but it still does not fit.
        Whether serialising the renderer can reach 3.6x is the per-section breakdown's job
        (the yosys netlist run, still owed).
      RENDERER BREAKDOWN BY SECTION (2026-10-22, tools/armdec/word_sections.py on a word-level
        yosys netlist, `synth -run :fine`; scratchpad ysz/render_word.ys). A gate-level netlist
        was tried first and kept a source line on only 4% of its cells - useless. At word level
        each mux/adder/shifter is one cell with its line; cost is a LUT-equivalent model
        (absolute ~3x Quartus, so only the SHARES are used). Cells with no line (lowered array
        accesses, 49%) were attributed by walking forward to the first named signal or lined
        cell (scratchpad ysz/noline_trace.py; 1% stayed unresolved).
          addition-list merge  merget 29% + mergep 12%            41%   (16-lane, per pixel)
          sprite search        find4                              14%   (x4, per pixel)
          line coverage        lcov                              1.5%
          coverage/rule caches ccache + rcache                     8%
          everything else (compose, blend, backgrounds, rule walk, state machines) ~36%,
          no single section above 3%
        The parallel per-pixel lane logic - what serialising removes - is ~56%. Removing ALL of
        it and the caches leaves 36-44%: a 2.3-2.8x shrink at the very best (before adding the
        serial units back, and before the clock budget: a 16-lane merge done one lane a clock
        takes 16 of the ~21 HD clocks per NES pixel on its own). The renderer needs ~3.6x.
        CONCLUSION: serialising the renderer does not close the gap; with the ARM split it
        still lands ~1.3-1.6x over the free logic, before the block-RAM shortfall. A faithful
        renderer does not fit the DE10-Nano by this route either.
      ANOMALY, recorded not chased: inside the full design Quartus reported the renderer at
      39,434 ALUTs / 49,553 regs, against 28,712 / 19,073 alone with the same file and
      parameters; arrays such as lpix, bgr, bgc, bsc, bglist, spoff are RAM alone and absent
      from the full-design report. Worth ~10,700 ALUTs if it is a fixable inference problem,
      but it does not change the conclusion.
    THE ROUTE THAT CAN FIT: ARM DISPLAY LIST + FPGA SPAN PAINTER (2026-10-22, user: "fit on
      mister while keeping faithful to mesen", working autonomously). The ARM makes EVERY
      decision and the FPGA only paints. Per NES line the ARM emits a list of 64-bit commands
      in Mesen's composite order (backdrop, bg layer 0, behind-BG sprites lowest priority first,
      layer 1, the BG tile or its fallback colour, layer 2, front sprites, layer 3, then the
      line's grayscale/emphasis). A BLIT paints one span of one HD block row (2 HD rows x 2*len
      pixels) with the block's alpha/add/subtract blend; a FILL paints an opaque colour; FX
      applies grayscale/emphasis; EOL ends the line. Later commands paint over earlier ones, so
      the FPGA needs no sprite lists, no merge, no search, no rule walk - which is the 64% of
      the renderer the breakdown above attributes to per-pixel decision logic.
      Spans: each paint item carries an identity (BG tile run, capture sprite, or addition =
      (parent entry, addition index)); per line the items are ordered by a topological sort of
      every pixel's draw order, then merged into spans of neighbouring pixels with the same
      block, row, flip and consecutive column. A cycle (no single order serves every pixel)
      falls back to per-pixel commands; it has not happened on any test frame.
      Code: tools/armdec/hdarm4.c (hdarm3's decisions + the display-list generator + a C model
      of the painter that reads ONLY the list), tools/armdec/dl_parity.sh + img_cmp.py.
      RESULT: all 29 recorded frames (Metroid 9, Castlevania 6, SMB3 5, Zelda II 9) are
        PIXEL-EXACT against hdref.py's render (0 pixels differ on every frame), from the
        display list alone. 0 lines needed the per-pixel fallback.
      LOAD (worst frames): up to 161 commands and 1,280 blit pixels in one NES line (Zelda II
        f1880); 9.6k-28k commands per frame. At 1 HD pixel per clock a 1,280-pixel line is
        2 x 2,560 = 5,120 HD pixels against 5,456 clocks per line - tight at 1 px/clock, so the
        painter blends 2 HD pixels per clock (one block row holds both rows of a pixel pair).
      ARM COST on the PC (median of 20): Metroid 0.78 ms, Castlevania 2.27 ms, SMB3 1.19 ms,
        Zelda II 0.79 ms per frame, the display list itself 0.32-0.47 ms of that. The A9 is
        ~25x slower on this code (hdarm3 measured 53 ms for Castlevania there); A9 timing of
        hdarm4 is the next measurement.
      DDR3 TRAFFIC: one BLIT reads one tile row of a block (128 B, two 8-qword bursts). Without
        a cache that is up to 214 MB/s (Zelda II f1880); a 256-row direct-mapped cache brings it
        to 39-67 MB/s, worst 63 misses in one NES line.
      PAINTER RTL: rtl/hdpack/hd3_paint.sv (2026-10-22). Command FIFO (128) fed by reader
        client L, front end with the 256-row block-row cache (tags in M10K, refill by reader
        client B; a miss is held while a queued/painting command uses that row), paint queue
        (8), painter at one NES pixel = 4 HD pixels per clock into one of two line buffers,
        hd3_render's grayscale/emphasis output stage, hd3_render's line_ok pacing.
        VERIFIED: tools/sim3/tb_paint.cpp + tools/sim3/paint_parity.sh run the RTL in Verilator
        from hdarm4's display list and the real pack, random DDR3 latency, random line_ok:
        ALL 29 FRAMES PIXEL-EXACT vs hdref.py. Worst 1,777 clocks per NES line (Zelda II
        f1880, with line_ok low about half the time) against 5,456.
        SIZE (Quartus 17.0 analysis & synthesis, the painter alone, scratchpad qpaint/):
          ~1,469 ALMs (estimate), 2,092 ALUTs, 1,607 registers, 16 DSP blocks,
          375,928 RAM bits (about 41 M10K: 26 for the cache, 6 line buffer, 6 emphasis ROMs)
        Against the renderer's ~21,000 ALMs. With the ~1,000 ALMs of engine that stays on the
        FPGA (loader, DDR3 arbiter, scan-out, top) the HD part is ~2,500 ALMs against ~6,900
        free: THE FPGA SIDE FITS.
      STILL OPEN for this route: (1) A9 time of hdarm4 (the MiSTer was unreachable at 23:40;
        hdarm3 measured 5.6-53 ms there, the budget is one frame, 16.6 ms; the 2026-10-22 day
        work below brought the ARM instruction count under the estimated budget on all 29
        frames - the device measurement is what remains); (2) the ARM<->FPGA frame
        handoff (records out, display list in) and the ARM program; (3) audio and ROM patches
        (resolve/add/dict/audio/romfix left the FPGA in this split; audio becomes a PCM ring,
        romfix stays or moves); (4) integration into NES.sv, fullsim against Mesen, then the
        full compile.
      PROGRESS 2026-10-22 (night, working autonomously):
        ARM COST NOW (PC, median of 10, all 29 frames): 0.33-2.17 ms per frame; worst Castlevania
          f0060 2.17 ms (lookups 1.12 ms of it), SMB3 f0040 1.95 ms, every other game <= 1.37 ms.
          At the ~23x A9/PC ratio hdarm3 showed, Castlevania would be ~45-50 ms on the A9 against
          a ~14-16 ms budget: STILL THE CRITICAL RISK OF THIS ROUTE, unmeasured because the
          MiSTer stayed unreachable (WinSCP timeouts at 23:40 and 01:05; Windows ping counts the
          PC's own "Destination host unreachable" replies as received, so its Received count
          means nothing - only a WinSCP session proves the unit is up).
        TRIED AND REVERTED: a content-keyed memo of neighbour-dependent lookups (key = the
          neighbour tiles' content instead of their positions). It was SLOWER (SMB3 lookups
          1.05 ms against the previous-pixel memo's lower figure: 1,812 rejected reuses against
          5,090 hits, and the hashing cost more than it saved). The previous-pixel memo stays.
          Do not retry it without a cheaper key.
        NEGATIVE CONTROL THAT COULD NOT FIRE: MUT_TCSTALE (the neighbour-read cache TC_I not
          cleared when a tile is rewritten) changed no output on any recorded frame or on the
          overlay test case, so that invalidation is kept as defence, not proven load-bearing.
        PAINTER LIST_END GATE (hd3_paint): the list reader stops at the published end (port
          list_end), so the ARM may publish a list progressively. Verified: paint_parity.sh in
          normal mode AND "pub" mode (tb_paint fills unpublished qwords with random garbage and
          publishes 8-64 qwords at random times) - 29/29 pixel-exact both ways, worst line
          ~1,787 clocks. NEGATIVE CONTROL: the same RTL without the gate differs on 177k, 204k
          and 167k pixels of three frames in pub mode, 0 in normal mode. The gate is load-bearing.
        ENGINE: rtl/hdpack/hd3_pengine.sv (same ports as hd3_engine, drops into NES.sv). Keeps the
          loader, capture/watch crossings, romfix, savestates, audio and scan-out; replaces the
          dictionary/additions/resolve/frame maps/renderer with hd3_paint. Adds a watch copier
          (hd_watch's values for the finished snapshot -> DDR3 + a marker), a mailbox poller and
          a pack-state word. The whole ARM<->FPGA protocol (addresses, ordering, the four list
          buffers, the mailbox, the pack word) is written at the top of that file. Lint clean.
        FULL-CORE SIMULATION OF THE ROUTE: tools/fullsim/build.sh PAINT=1 OBJ=<dir> builds the
          core with hd3_pengine and links hdarm4.c (as a library, -DHDARM_LIB) as the ARM:
          fullsim.cpp (FULLSIM_ARM) takes each finished record from the DDR3 model, runs the
          decisions, writes the list and publishes it; --arm-delay-lines N holds publication back
          to model the ARM's compute time. First run (Castlevania to f0061) in progress.
        ARM PROGRAM: tools/armdec/hdarm_daemon.c (+ hdarm4.c as a library). Maps DDR3 through
          /dev/mem O_SYNC, copies the pack's decision sections once per pack generation and the
          record once per frame, publishes with a single NEON 64-bit mailbox store after a
          barrier, prints copy/decide/publish timing. Cross-builds clean (scratchpad
          armdec/xbuild_d.sh, 446 KB static). NOT YET RUN on the device.
      PROGRESS 2026-10-22 (day, autonomous): THE DECISION CODE NOW MEASURES UNDER THE A9 BUDGET.
        HOW IT IS MEASURED WITHOUT THE MISTER: tools/armdec/cg_arm.sh builds hdarm4 for ARMv7
          inside an emulated debian:bookworm (docker --platform linux/arm/v7) and counts ARM
          instructions with valgrind cachegrind at --iters 1 and 3; warm per frame = (3 - 1) / 2.
          Converted with ~1.03 ns per ARM instruction (the earlier A9 bench gave 1.29 ns per x86
          instruction; ARM runs ~1.25 instructions per x86 one), the ~14 ms decision budget is
          ~13.6M instructions. This is an ESTIMATE; tools/armdec/bench_a9.sh on the device decides.
        RESULT, all 29 frames (with the fast run loop below): worst 11.38M (Castlevania f0060),
          then 10.46M (Castlevania f0250); Castlevania others <= 10.05M; Zelda II <= 8.68M;
          SMB3 <= 7.36M; Metroid <= 6.73M. About 11.7 ms at the estimate, ~16% under budget.
          ONE FRAME GOT SLOWER: SMB3 f0200 2.95M -> 3.38M (+0.43M), the lightest frame in the
          set. EXPLAINED: that frame has no background tile on any pixel (all 61,440 take the
          no-tile path, 0 cached), so the fast loop never runs there; the +0.43M (~7 ARM
          instructions per pixel) is the new code's effect on the per-pixel loop's register
          allocation, the compiler sensitivity described below. It does not affect the worst case.
        WHAT GOT IT THERE (Castlevania f0060 from 18.14M at the start of the day):
          - game-RAM packs: a tile's identity is now its CONTENT (palette, index, fingerprint,
            interned per frame by cid_build) and the vertical memo runs for them too; a 32-bit
            identity path for them (their overlay is always empty - get_matching_walk has no
            fallback for game-RAM packs; MEMO_VERIFY asserts it).
          - each memo entry stores the decision's class and value (hc/hv), so a reuse needs no
            64-bit work and no recomputation.
          - a fast path for the common memo shape (one tile dependency that moves with the pixel,
            no position conditions): one identity read instead of deps_hold.
          - build flags: -O3 -fno-pie (tools/armdec/xbuild.sh, xbuild_d.sh, now in the repo).
            Debian's gcc builds position-independent code by default, so every global read in
            the per-pixel loop cost a pc-relative load plus an add; -fno-pie alone took f0060
            from 12.99M to 12.29M, with -O3 11.67M.
          - rule dispatch for "is tile K nearby" runs (SMB3 f0040 12.39M -> 9.53M): its rule
            lists test ONE tile key at up to 50 positions in turn ("tile 329 at +8, else +16 ...");
            per frame each span record gets a lazily filled match flag for the key, so each test
            is a table read instead of eval_cond + tile_at_matches. Dependencies and
            disableCache bits are collected exactly as the sequential walk does.
          - a fast run loop over the rest of a tile (Metroid f0960 8.64M -> 6.72M, SMB3 f0040
            9.53M -> 7.36M, Castlevania f0250 10.95M -> 10.46M): once a tile's decision is
            cached, its remaining pixels only extend the BG run, so a tight loop consumes them
            while each one has no sprite, the same backdrop index and (class 1) the next fine x
            or (class 2) the same colour / transparency. Off while the decision dump is on.
        TEST COVERAGE ADDED WITH IT: the decision dump forces every pixel through the full loop,
          so a check that only compares dumps never runs a fast path. exact_check.sh now also
          compares the display list from a run WITHOUT the dump (29/29); memo_stress.sh compares
          each frame's list with and without the dump; qemu_parity.sh and bench_a9.sh check the
          A9 build's list against expected_dl.md5 (29/29 under QEMU). NEGATIVE CONTROL: five
          mutants of the fast loop (no colour test, no transparency test, no sprite test x2, no
          tile-boundary test) all pass the old checks and fail the new one (4-26 of 29 frames).
        COMPILER SENSITIVITY, worth knowing before the next change: the per-pixel loop is
          register-starved, and unrelated edits move its code generation. Measured three times:
          a literal argument made GCC clone dep_note and cost the loop 0.3M; per-pixel statistics
          counters cost ~0.1M (now compiled out of the daemon/timing builds, PIXSTAT); packing the
          BG-run state into one key and a two-pass line loop were both SLOWER and were reverted.
          Measure every change on the four reference frames (CV 0060/0250, a034 0960, p053 0040).
        VERIFIED: exact_check.sh 29/29 decisions and display lists vs hdarm3; MEMO_VERIFY 0
          failures on the four reference frames; the A9 build (-O3 -fno-pie, static) gives the
          expected display list on all 29 frames under QEMU (tools/armdec/qemu_parity.sh, 29/29).
        NES_PAINT SYNTHESIS (quartus_map NES -c NES_PAINT, synthesis-only): started 2026-10-22
          08:33 and stopped by Claude Code within seconds because the PC was low on memory; not
          restarted (needs the user's go-ahead). Three orphaned quartus_map helpers from it could
          not be stopped from the shell and hold ~190 MB each until reboot.
        STILL OWED: the real A9 timing (bench_a9.sh; WinSCP to 192.168.1.51 timed out again at
          ~05:00 and ~12:50, the unit may simply be off); memo_stress.sh result on this build.
      PROGRESS 2026-10-22 (afternoon): BOTH MEASUREMENTS TAKEN. NEITHER FITS YET.
        A9 TIMING, MEASURED ON THE DEVICE (bench_a9.sh, hdarm4_a9 md5 a99ce5de..., core 0, 20
          iterations per frame; log NES_HDPack_work_saved/2026-10-22/bench8.log, md5 8cfef4e8...):
          PARITY 29/29 and DISPLAY LIST 29/29 on the A9 itself. Median per frame:
            Castlevania (p002) 17.1-23.4 ms, worst f0060 23.4 ms
            Zelda II (a057)    11.3-16.4 ms
            SMB3 (p053)         7.3-14.0 ms
            Metroid (a034)      9.4-13.2 ms
          13 of 29 frames are over the ~14 ms budget (all 6 Castlevania, 7 of 9 Zelda II); the
          worst needs a 1.67x cut. THE ESTIMATE WAS WRONG BY 2x: measured time / cachegrind count
          is 1.8-2.15 ns per ARM instruction on every frame (f0060 23.4 ms / 11.38M = 2.06),
          not the assumed 1.03, i.e. about 0.6 instructions per clock at 800 MHz - the loop is
          memory-bound, not instruction-bound. Instruction counts still rank frames correctly,
          but the conversion to ms is ~2.0 ns, not 1.03; the budget in instructions is ~6.8M,
          not 13.6M. Do not reuse 1.03.
          Fixed per-frame cost worth looking at first: the "records" column is 2.3-4.8 ms on
          every frame (4.8 on Castlevania), before any decision work. Not yet known how much of
          it the device daemon would also pay (bench reads records from the recording, the
          daemon from DDR3). The lookups / displaylist columns print empty in this build.
          Max column spikes to 28-43 ms on some frames (core 0 takes the device IRQs); the
          device daemon needs a worst case, not a median - measure core 1 too.
        NES_PAINT SYNTHESIS (quartus_map NES -c NES_PAINT, 8 min, exit 0, run started after
          the reboot; the earlier hang did not recur):
            Estimate of logic utilization 42,887 ALMs against 41,910 (102%)
            61,761 ALUTs, 50,211 registers, 1,807,432 block bits, 112 DSP (100%)
          Against the full stage-3 engine (NES revision, 2026-10-21): 110,382 ALMs, 147,815
          registers, 5,455,382 bits. The route cut the design to 39%, but ~1,000 ALMs over.
          WHY THE EARLIER "FITS" ESTIMATE WAS LOW: it assumed audio and romfix left the FPGA in
          this split; hd3_pengine still contains both. Largest blocks (ALUTs incl. children):
            NES core 28,550 (PPU 9,801 of it, OAMEval 7,632; mappers 12,347)
            hd3_pengine 11,818: hd3_audio 4,777, hd3_romfix 3,766 (sha1 1,251), hd3_paint 2,006
            hd_stage2 1,912, ascal 2,894, composite_decoder 1,339 (27 DSP)
          At the overall 0.69 ALM/ALUT ratio, moving audio and romfix off the FPGA (sub-item 3
          of this item) is ~5,900 ALMs, which would put the design near 37,000 (~88%). A
          synthesis estimate is not the fitter's number; the fit is what decides.
          DSP at exactly 112/112 in both revisions: check the map report for multipliers
          implemented in logic before trusting the ALM figure.
        A9 SPEED WORK, 2026-10-22 evening (all variants exact_check 29/29 on the PC; device A/B
          = ab_a9.sh, builds in rotation, 5 reference frames x 3 rounds x 20 iters, core 0):
          WHERE THE TIME IS (SUBT build, Castlevania f0060, ms): memo clear 0.004,
            build_records 2.6, pid_build (+cid) 2.5, select_levels ~0.1, additions 2.5,
            lookups 15.9. pid_build is ~250k instructions and still took ~2 ms: it streams
            one byte of every 4-byte pixel over the 240 KB record, and the A9 waits ~250 ns
            (measured, pointer chase; core 1 ~450 ns) per 32-byte line - the hardware does
            not prefetch these streams.
          stream_bench.c (scratchpad, the pid_build pattern after a 4 MB flush, core 0):
            no prefetch 1.74 ms; a whole row of PLDs at the row start 1.72 ms (NOTHING - the
            A9's line-fill buffers fill and the burst stalls); one PLD per 32-byte line INSIDE
            the loop, 64 B - 2 KB ahead, 0.75 ms. Core 1: 3.6 ms -> 0.66 ms.
          TRIED AND REVERTED: (1) PF_AHEAD - a burst of PLDs for the next line's rows at each
            line start in every pass: +0.75 to +1.5 ms on every frame. (2) fusing pid_build
            and cid_build into build_records line by line: the cache simulation said -7.8k L2
            read misses per frame, the device said 0 to +0.7 ms. The simulation's miss count
            does not predict A9 time here; measure on the device.
          KEPT: PFI inline prefetch (one per 8 pixels, PFD = 256 bytes ahead) in pid_build and
            the lookups pixel loop, and pid_build's inner loop in 8-pixel blocks. Device:
            CV0060 23.41 -> 21.82 ms, CV0250 20.88 -> 19.63, Z2 0760 16.63 -> 15.37,
            Metroid 0960 12.59 -> 11.08, SMB3 0040 14.25 -> 12.54 (the original column is the
            first A/B's h4pf0; the block loop alone, PFD=0, gave 22.55 / 20.16 / 15.33 / 11.85 /
            13.13). ~7%, against the 1.67x Castlevania needs.
          DEVICE PROFILE (gprof -pg, line level, CV0060 x1000 on core 0, 24.5 s sampled;
            NES_HDPack_work_saved/2026-10-22/speed_work/gprof_lines.txt, pg_lines.py): FLAT.
            The top line is 5.8% (caching the decision after a walk), then 3.8% (copying a
            memo reuse); everything else <= 2.9%. By area: the per-pixel loop's bookkeeping
            ~55%, sprites (spr_push / spr_of / spr_walk / spr_pixel) ~8%, additions
            (process_additions / draw_additions / ax_range) ~7%, display-list emission
            (gen_line / emit_layer / dl_put) ~6%, records ~9%. find_key + find_key_m (the pack
            hash lookups) only ~2%, eval_cond ~0.6% - the random pack reads are NOT the cost.
            15.4 ms / 61,440 pixels = ~250 ns = ~200 A9 cycles per pixel, spread thin.
          CONCLUSION: constant-factor work on this structure will not give the 1.67x
            Castlevania needs (the whole day's instruction-count tuning was 18.14M -> 11.38M,
            1.6x, and this evening's prefetch 7% more; the A9 runs it at 0.6 instructions
            per clock). Remaining
            levers, each a design decision: (a) decide per TILE instead of per pixel wherever
            the pack's rules make every pixel of a tile equal (the fast run loop does this
            only after a pixel's decision is cached); (b) have the FPGA capture write the
            records already in the ARM's working form (compact pixel plane, sprite blocks),
            removing most of the ~3.7 ms records phase; (c) a deeper ARM-side budget, e.g.
            publishing a frame's list one frame late (latency 1 frame) so the decision work
            has the whole 16.6 ms rather than ~14 ms. (Cross-core work splitting is ruled out
            by the project's standing rule.)
          OWED for the kept PFI change: memo_stress.sh and the A9 qemu_parity / bench_a9 run
            (exact_check 29/29 passed on the PC; the change only adds prefetches and blocks
            pid_build's loop by 8).
        PER-TILE DECISIONS (user's pick of (a), 2026-10-22 evening). Path counts per frame
          (-DPATHSTAT build): Castlevania f0060 sent 44,160 of 61,440 pixels through the loop
          body, 33,127 of them line-memo reuses carrying disableCache - the decision was
          per-pixel only because the pack said so, while what it depended on (one tile at an
          offset, R_one) was the same across the tile. Metroid/Zelda II/SMB3 had no such pixels.
          KEPT (exact_check 29/29 + A9 bench_a9 PARITY 29/29, DISPLAY LIST 29/29):
          1. Per-tile dependency cache (NO_TILEDEP turns it off): after a per-pixel decision
             whose noted dependencies are all relative tile dependencies (no position
             conditions, no sprite or fixed ones), the rest of the tile's pixels reuse it while
             each dependency's target PID stays the same - exactly the line memo's own reuse
             test, made once per tile. MEMO_VERIFY walks every pixel it answers. CV f0060 body
             pixels 44,160 -> 14,040. A9: CV0060 22.26 -> 18.37 ms, CV0250 19.75 -> 18.03.
          2. Layer emission (NO_LAYERFAST): emit_layer reserves the display list once, reads
             the map row in order and builds the fixed command fields once. Byte-identical
             lists. Zelda II -0.38 ms, Metroid -0.30.
          3. Whole-tile fast run (NO_TILESCAN; NO_NEONSCAN for the scalar run_scan on the A9):
             the fast run's per-pixel continue test (no sprite, same PID, same backdrop index,
             and the class rule) made for the rest of the tile at once with NEON. PID, SBI and
             the line-0 row copy are padded so the 8-wide reads stay in bounds. -0.17 to -0.72
             ms on all five frames.
          A9 now (core 0, median, ms): CV0060 17.4-17.9 (was 23.41 this morning), CV0250 17.6
          (20.88), Zelda II 14.5 (16.63), Metroid 10.6 (12.59), SMB3 11.8 (14.25).
          TRIED AND NOT KEPT: closing/reopening colour runs inside the fast run (CV -0.2/-0.8,
          the other games +0.35/+0.5); prefetching build_records' next line header (-0.1 ms);
          a last-key memo in additions_for (-0.1 ms). The last two are below the A9's
          build-to-build layout noise: identical lookups code moved up to 1.1 ms between builds
          that differ elsewhere, so a single A/B cannot resolve a change under ~0.5 ms.
          WHERE CASTLEVANIA STANDS: one BG decision per tile already (7,682 tile-start
          decisions = 32 x 240), so per-tile has taken what it can from the BG decisions.
          Left: records 3.7 ms, additions 2.5 ms, lookups ~11 ms (tile starts, sprites, the
          display list). Still ~3.5 ms over the ~14 ms budget. The remaining levers are (b)
          records in the ARM's form from the capture and (c) one frame of latency (budget to
          16.6 ms). (An earlier estimate here said (b)+(c) together fit with margin; that
          predates measuring the uncached copies below and is WITHDRAWN.)
        UNCACHED COPY COSTS (measured on the device 2026-10-22, core 0, pf/dmem_bench.c). The
          DDR3 window (0x20000000+) is outside System RAM, so /dev/mem maps it strongly-ordered
          and bandwidth depends only on bytes per load/store instruction:
            read  memcpy ~55 MB/s, NEON 64-byte ~82, LDM 32-byte ~131, VLDM 128-byte 340-365
            write memcpy 103 MB/s, VSTM 109
          fetch_record (the per-frame record copy) was 6.2 ms (8 sprites/line) to 8.9 ms (64)
          with the old NEON loop. KEPT: hdarm_rec.h fetch() now copies 128-byte VLDM/VSTM
          blocks and fetches only up128(64 + nspan*16) from +0 and up128(nspr*16) from +640 of
          each line; correctness checked against a written random pattern (0 differences of
          262,144 bytes - the first check read all-zero memory and proved nothing).
          Display-list write-back: CV0060 104,640 B, worst a057_1880 226,512 B, mean 116,671 B,
          i.e. ~1.0-2.1 ms at ~105 MB/s.
          Revised per-frame totals: CV0060 ~17.4 + 1.3 (fetch) + 1.0 (list) ~ 19.7 ms; Z2 0760
          ~14.5 + 1.3 + 1.1 ~ 16.9 ms. Neither fits 16.6 ms with (c) alone.
          No user-space DMA: the kernel (6.18.38-MiSTer) has pdma@ffe01000 but no driver user
          space can reach.
        (b) REDEFINED: cut the bytes crossing the uncached boundary in BOTH directions -
          (1) a compact record from the capture (the ARM reads only what the decisions use, no
          2 KB-per-line padding), (2) a compact display list that hd3_paint expands. Measure
          candidate formats in software on the A9 first (pack the existing records/lists into
          the candidate form, time fetch + write-back), and only then touch RTL. The FPGA is at
          102% ALMs today (~88% expected once audio and romfix leave it), so any RTL format
          change has to be small.
          MEASURED 2026-10-22 on the 29 test frames (tools/armdec/dl_compact_census.py over
          hdarm4 --dl dumps; dl_why_norepeat.py for the reasons):
            list as published          3,734,656 B total, worst a057_1880 226,560 B
            6-byte commands            2,800,104 B (no command uses bits above 51; checked)
            REPEAT line                  824,656 B (4.5x) - a line equal to the previous one
                                                   with every BLIT one tile row on (offy +1,
                                                   -1 under vm, no wrap) becomes ONE command
            REPEAT + 6-byte              618,492 B (6.0x); a057_1880 -> 25,716 B
          Most lines repeat (Metroid ~200/240, Zelda II ~178/208, SMB3 ~205/240, CV f0700+
          ~201/240). Castlevania f0060/0250/0450 only ~76/240: there the command COUNT changes
          from line to line (per-pixel decisions cut the runs differently) - REPEAT still takes
          f0060 from 104,640 to 73,160 B (54,870 with 6-byte commands).
          Painter cost of REPEAT: hd3_paint keeps the previous line's commands; the longest line
          in the set is 260 commands, ~3 M10K at 52 bits. Count it against 8l's M10K budget.
          Record side: fetch_record reads 240 KB of pixels (4 bytes each, all four read by
          hdarm4: b0 span slot + sprite flag, b1 BG colour index + fine column, b2 final colour
          index, b3 BG palette entry) + line headers/spans/sprites. Information is ~24 bits a
          pixel and b3 may be derivable from the span's palette and b1; 2-3 bytes a pixel would
          save ~0.2-0.35 ms. Smaller than the list lever; needs the derivability proven first.
          WHAT THIS DOES TO THE BUDGET (with (c), 16.6 ms): Zelda II 0760 ~14.5 decide + 1.3
          fetch + ~0.15 list = ~16.0 ms, fits. Castlevania f0060 ~17.4 decide alone is already
          over 16.6 - (b) and (c) cannot close it; the decisions themselves must still lose
          ~2.5-3 ms on Castlevania. Next step for (b) if pursued: the REPEAT command in hd3_paint
          + hdarm4's list writer, checked by dl_parity.sh (pixel-exact on all 29) and the
          painter's own fullsim run.
        (c) DESIGN (ARM-only, no RTL): when record F is ready, publish list F-1 (already
          complete) and then compute F. The painter shows F-1 during display of F+1, one frame
          later than now. Two record banks still suffice provided record F is copied out
          (fetch_record) before the capture can reuse its bank.
          DONE in hdarm_daemon.c (2026-10-22): --lag 1 (default) holds the decided list in local
          memory and publishes it as soon as the next record is ready, then fetches and decides
          that record; --lag 0 is the old publish-at-once path; --once forces lag 0. A held list
          is dropped when the pack goes away or its generation moves. Cross-builds clean
          (xbuild_d.sh, -Wall, no warnings). Stats now count the held list's write-back in
          "publish".
          OWED: (1) fullsim PAINT=1 with --arm-delay-lines 262 (one frame) against 0 - the
          painted picture of frame N+1 must equal the delay-0 picture of frame N (run once the
          corpus recording batch has freed the CPU); (2) on the device: the timing line with
          lag 1, and no torn/skipped growth.
        CORPUS (user, 2026-10-22: "isn't the goal ... the complete collection of mesen hd pack
          games"): timing and correctness are moving from 4 games to the whole converted corpus.
          tools/corpus/: romindex.py + map_packs.py (a pack's <supportedRom> is the hash of the
          whole file with an iNES 1.0 header, bytes 7-15 zero; the library is NES 2.0, so the
          index carries ines1 sha1/md5 columns), pack_roms_manual.tsv (37 packs with no usable
          hash, resolved by folder name; 5 have no ROM in the library: p000/p084/p131 Battle
          City (J), p055 SMB T+Rus, p132 BombSweeper), corpus_plan.py (128 packs -> 57
          recordings, grouped by the ROM the core runs after any <patch> and by
          disableSpriteLimit; each group watches the union of its packs' addresses),
          watch_subset.py (cuts one pack's watch file out of the union snapshot; identity case
          byte-identical to an existing watch file), per-game input scripts tuned against Mesen
          screenshots (make_scripts.py, mesen_tune.py, tune_montage.py), corpus_record.py
          (fullsim batch, resumable). Rebuilt fullsim checked first: CV f0060 rec/col/chr/watch
          identical to the 2026-10-15 recording except the extra-sprite fetches added by 8h
          (rec_main8_same.py: 0 differences outside them). Batch started 2026-10-22 13:12, 6
          workers. RATE MEASURED at 19:56: 0.08 frames/s per job with 6 in parallel (half the
          0.16 single-job figure), total 55,357 frames -> ~32 h wall, not 12-14 h; g09 alone
          (3401 frames) ~12 h. 4 groups done by 19:56 (g06 g13 g16 g17). record_batch.log
          printed nothing because ex.map reports in submit order and g01 is first; fixed for
          future runs (as_completed), the running batch keeps the old behaviour - per-group
          progress is the `done` files and rec/fullsim.log. Still to do per pack: decisions vs hdref, hdref vs Mesen (pixel-exact; Mesen
          frame = fullsim frame + 2), A9 timing incl. fetch and write-back.
          COVERAGE AUDIT 2026-10-22 (user: "find what is missing so we have full coverage"):
            - "137 packs" (Summary.txt) counts out/*.hdp, which includes 4 dev test packs
              (smb_testpack, test_a000, test_cv, test_cv2). Real converted packs = 133.
            - The collection's 4 GitHub folders were NEVER converted (0 lines in any convert
              log). gh_HDNes-Graphics-Pac and gh_hdnes-projects/Super Mario Bros have hires.txt
              byte-identical to converted packs (a105/_inner06, a112) - duplicates. The other 3
              are MISSING: gh_Faxanadu_Revisioned (hdpacks/faxanadu-revisioned),
              gh_Kiwi_mesen_hd_textures "1943 (U)" and "BattleCity (Japan)". Full set = 136.
            - The 5 loose .ips in the collection: 3 are byte-identical to patches shipped inside
              packs (akuogg.ips, mmm.ips, ZeldaHD.ips); b_cv.ips (CV30th, kya) and Kurrono's CV3
              .ips ship alone. Applied to the library ROM, none gives a hash any pack names
              (tools/corpus/ips_probe.py) - so no pack is keyed to them.
            - STALE CORPUS: every out/*.hdp is dated <= 2026-10-17; section 14 (ROM patches,
              hdp3_patch.py 2026-10-18) and 15 (audio) are EMPTY in all of them, including
              a034/a057 whose hires.txt <patch> lines are real (tools/corpus/hdp_patches.py,
              hdp_sections.py). The whole set must be reconverted with the current converter.
            - PATCHES NOT RUN: corpus_plan applies a <patch> only when the RAW file SHA1 matches
              (as Mesen and the converter do). Mega Man Super (p025, a099/a100/p103, mms_var_*),
              Ice Climber (p115/p116) and Ninja Gaiden (a037, an MD5) name the iNES-1.0-header
              hash, so with the library's NES 2.0 ROMs their patch is never applied and groups
              g11/g16/g17/g27 recorded the UNPATCHED game. The Mega Man Super readme says the
              pack needs its patch (white squares on the title otherwise) and tells users with
              a different hash to edit hires.txt. DECISION OWED (user): match <patch> and
              <supportedRom> against the iNES-1.0-normalised hash as well, so No-Intro ROMs get
              the author's intended game - a deliberate step beyond Mesen's literal behaviour.
              Also check in Mesen which file a030 applies: its hires.txt names "Mega Man.ips"
              but the folder ships "Megaman - Super.ips".
            - Optional variants (re-checked 2026-10-23):
              * Mega Man Super's 4 Customization patches: ALREADY BUILT, recipes mms_var_1..16
                in pack_recipes.tsv (4 per release a028-a031). This line was stale.
              * 1942 music pack (bogaa, a082 = p085): ADDED as recipes v1942b_hdmusic and
                v1942b_nomusic_evgeny. a082 holds no tiles, only 16 <bgm> lines + OGGs, and its
                hires.txt names no patch: the player applies Patches/1942HDMUSIC.ips (or
                NoMusicWtihEvgenyImprovments.ips) by hand. Each recipe is an overlay
                (tools/corpus/make_variant_overlays.py -> x/zz_var/<name>/hires.txt) = the base
                hires.txt + a <patch> line keyed to the library ROM (1fc8410c...), so the core
                patches at load. Both convert and check clean (scratchpad test). The patches
                grow the cart 40,976 -> 131,088 bytes. Two <bgm> files are missing in the pack
                itself, as in Mesen: "Stage 6.ogg" (shipped as "Stage 6-A.ogg") and
                "Boss 1, Mid Boss A.ogg" (the comma splits the line; Mesen reads "Boss 1").
                NOTE: the default p085 has no patch, so it changes nothing in the game.
              * NOT BUILDABLE, music not in the collection:
                1942 LiQuiDz (a105/_inner00 = p107): same 1942HDMUSIC.ips and the same <bgm>
                  lines as a082, byte for byte, but no OGGs; v1942b_hdmusic is the complete
                  build of the same thing.
                Bio Miracle Bokutte Upa v2 (a105/_inner01 = p108): audio-only (16 <bgm>, no
                  tiles); its soundtrack is a separate download. DOWNLOADED 2026-10-23 (user
                  approved): BioMiracle-sndtrk.zip, 25,391,251 bytes, Google Drive id
                  1JFZ291rZ1K7baub36G7XrShxiRmuqE7E (the HDnes readme's link). It is a complete
                  pack (hires.txt with its own <patch> line + 14 OGGs + NEA-BioMicacle.ips,
                  byte-identical to the v2 .ips), now corpus folder x/zz_dl_biomiracle_sndtrk.
                  Its hires.txt names "NEA-BioMiracle.ips" (typo); fixed by a pack_fixes.py
                  PATCH_FILE_FIXES entry (MD5-checked). Converts and checks clean
                  (57.9 MB .hdp). Plain pack, mapped by its own <patch> hash.
                Zelda II Revamp+Music (a057-a059): README says rename Revamp+Music.ips to
                  Revamp.ips "and place OGG files in the Music folder"; Music/ is empty (the
                  music is by Niskala, not shipped) and the music patch is marked unfinished.
                  FOUND 2026-10-23 (same day): the user got Niskala's "Zelda 2 Remake Music"
                  from the project Discord, two zips at Desktop/Zelda_2_Remake_Music
                  (Part_1 2,285,791 B, Part_2 6,926,596 B; 16 OGG tracks dated 2022-11-27, all
                  valid OggS). tools/corpus/make_z2_music_overlays.py builds overlays
                  x/zz_var/vz2music_a057/a058/a059 = Revamp+Music.ips as Revamp.ips + the 13 named
                  OGGs (refuses if a track is missing or the patch does not apply; it applies to
                  the library ROM, 262160 B). Recipes added. Three names were judged by scene, not
                  title: ending=Zelda Awakens, credits=End Credits, courage=Triforce (a057
                  comments credits+courage out). Unused remake tracks: Dungeon Clear, Flute, Item.
                  vz2music_a059 converts: 90.1 MB vs 63.7 MB plain; the 9 "Error while loading
                  background" lines are the base pack's own missing PNGs (present in the plain
                  build too, hidden there by hdp3_convert's 10-problem print cap).
                  Earlier the same day it had been SEARCHED, NOT PUBLICLY AVAILABLE: repo github.com/ModernRetroDesign/
                  ZII-mesen (branches main + 2x, tag Pre-release v0.6.8) never held an OGG - its
                  .gitignore excludes *.ogg (since commit 390d8573, the "Music patch" commit
                  27583b4b added only Revamp+Music.ips + the bgm lines). Composer is most likely
                  Christopher Niskala (YouTube UCYwa9KLm4d2aIJfZckXBD-A, game-music arranger; has a
                  2015 Zelda 2 "Silent Film" medley, no track set); nothing on Bandcamp, archive.org
                  or his public channel matches the 13 files. Only remaining source: the project
                  Discord "ZELDA2 Revamped for Mesen" (invite discord.gg/feFCZMUQQm, live) - needs
                  the user's own Discord account. romhacking.net thread topic=33860 is behind a
                  bot check (not bypassed) with no Wayback copy.
                Overlays made for the first two are parked in Z:/NES_HDPack_work/var_held.
              * Audio is stage 6, still OPEN: none of these music variants is audible on the core
                until it lands.
            Tools: tools/corpus/{ips_probe,loose_patches,patch_check,hdp_patches,hdp_sections}.py
            MISSING-ROM RECHECK (same day) - 4 of the 5 "missing" were in the library:
            - Battle City (J) packs p000 p084 p131: the library file is
              "1 NES/2 Japan/BattleCity (Japan) (En).nes" (no space, so a name search missed it);
              Kiwi's new BattleCity pack names exactly this file's SHA1 (e1061c92...).
            - BombSweeper p132 (hash-less HDNes pack): three library copies, all with the same
              CHR (4448c673...), and "1 NES/4 Betas & Protos/.../Bomb Sweeper (World) (Proto)
              (Aftermarket) (Unl).nes" has the same PRG as the Homebrew copy - use it.
            - FOUND 2026-10-23: Super Mario Bros. (JU) [T+Rus Guyver 24.11.2016] for p055.
              Downloaded from nesroms.ru post 12815, download slot 1 (the tabs do NOT match
              the slot numbers: slot 2 is the Japanese FDS original, slot 3 an English All
              Night Nippon translation). Its SHA1 is 4567780a... in both the raw and iNES 1.0
              forms, the hash p055's hires.txt names. Saved as
              NES_HDPack_testdata/roms/smb_rus_guyver.nes; p055's row in
              tools/corpus/pack_roms_manual.tsv points to it. All packs now have a ROM.
            - Mega Man Super a030 (the YM2612 audio release) names "Mega Man.ips" but ships
              "Megaman - Super.ips", byte-identical (cc404135...) to the patch the sibling
              releases a028/a029/a031 name. Author typo; needs a converter recipe naming the
              file that is there.
            DECISION (user 2026-10-22): "yes to full compatibility for all 136" - the core
              matches <patch> and <supportedRom> against the iNES-1.0-normalised hash as well as
              the raw file, so No-Intro (NES 2.0 header) ROMs get the patched game the author
              built the pack for. OWED: converter + core matching, corpus_plan the same rule,
              manual table updated for the 4 resolved packs, convert the 3 new packs, reconvert
              all 136, re-record changed groups (g11 g16 g17 g27 + new + the 4 resolved).
          Yie Ar Kung-Fu (g52) FIXED 2026-10-23 - the cause was Mesen, not the game: its ROM has
            an iNES 1.0 header and no Mesen DB entry, so Mesen attached NO controller and every
            $4016/$4017 read was open bus ($40) for every button. NES_HDPack_testdata/tools/
            mesen2/settings.json now sets Nes Port1/Port2 to NesController (a DB entry or an
            NES 2.0 header still overrides it). Scanned all 57 corpus ROMs: g52 is the ONLY one
            Mesen had no controller for. scripts/g52.txt (make_scripts.py) now presses Start at
            100 and fights; mesen_tune shows STAGE 01 and a real fight. OWED: re-record g52 (its
            current recording is the attract demo), and rescan the new plan's ROMs (3 new packs,
            p055, the variants) with tools/corpus/mesen_ctl_scan.py WORK MesenNesDB.txt (it
            flags the rows Mesen gives no controller; with the new settings.json those now get
            standard pads, so a flagged row is a ROM to re-tune, not a failure).
          RE-PLAN 2026-10-25 (from the full reconvert, Z:/NES_HDPack_work/out3: 142 packs, 138 OK +
            4 CHECKFAIL p036 p043 p100 p110 = the chiptune audio-SNR flag only, .hdp produced):
            scratchpad tsv_to_log.py -> map_packs.py (142: supportedRom 54, patch 48, NOHASH 25,
            HASH_NOT_IN_LIBRARY 12, NO_HIRES 3) -> corpus_plan.py into a NEW work folder
            Z:/NES_HDPack_work/corpus_replan (corpus/ with its recordings untouched): 139 packs in
            76 recordings, 0 packs without a ROM. New packs: p000 p055 p084 p131 p132 p133
            v1942b_hdmusic v1942b_nomusic_evgeny z1943 zbcity zfax.
            Diff (scratchpad plan_diff.py: reusable = same rom.nes sha1 + same nolimit + old group
            recorded + new watch list a subset of the old): REUSE 42, RECORD 34 -
              watches more addresses: g00 g01 g11 g19 g20 g36 g44 g47 g61
              new ROM or option: g08 g12 g13 g14 g21-g25 g32 g35 g39 g45 g48 g51 g52 g54 g56 g60
                g62 g68 g69 g70 g72 g75
            plus Yie Ar Kung-Fu (new g67 <- old g52), which plan_diff counts as reusable but must be
            re-recorded (its recording is the attract demo; see the g52 note below).
            mesen_ctl_scan over corpus_replan: 22 groups have no Mesen DB entry (the patched ROMs
            change the CRC): g08 g12 g13 g14 g21-g25 g32 g35 g39 g45 g48 g51 g52 g60 g62 g67 g69
            g70 g75. settings.json now gives them standard pads, so each needs a tuned script
            (mesen_tune), not a fix - EXCEPT g45 (Duck Hunt patched, p110 p111): the Zapper came
            from the DB entry, so Mesen now gives that ROM a pad and the game cannot be played in
            the reference. OWED: set Port 2 = Zapper for g45's Mesen runs. RECORDING 35 groups is a
            multi-day fullsim batch; it runs after the Music Player RBF rebuild (one heavy job at a
            time) and after the 34 scripts are tuned.
          Zelda (Europe) g51 region CONFIRMED 2026-10-25: both run it PAL. fullsim takes the system
          type from the header (sim_top effective_sys_type; g51's rom.nes is NES 2.0, byte 12 = 1 =
          PAL). Mesen (Auto region) reports region=Pal for the same file through
          NES_HDPack_testdata/tools/mesen2/regioninfo.lua (emu.getState().region at frame 60); the
          USA ROM reports Ntsc in the same probe, so the probe tells the two apart.
          ZAPPER (user report 2026-10-23: Duck Hunt reached the dog, no cursor, no button fired).
            The collection's only light-gun game is Duck Hunt (g35; Mesen DB controller type 8,
            every other corpus ROM is a standard pad). On the core it needs OSD Peripheral =
            Zapper(Joy1/Joy2) or Zapper(Mouse); in Joy mode the ANALOG STICK aims (joy_analog,
            not the d-pad), the trigger is the "Zapper/Vaus Btn" (joystick bit 10) and fires
            only with "Zapper Trigger = Joystick" (default Mouse).
            DEFECT FOUND AND FIXED IN RTL (2026-10-23, not yet built or run): with an HD pack on,
            the picture is hd_r/g/b, and the crosshair was drawn only into video.sv's NES
            picture - so the HD picture had no crosshair. New rtl/hd_reticle.sv draws the same
            plus sign (zapper.sv's hit_x/hit_y, colours $15/$21 from hd3_pal2c02.hex) at the
            aim point on the HD picture; zapper.sv exports aim_x/aim_y; NES.sv and
            tools/fullsim/sim_top.sv both instantiate it (files.qip + build.sh list it). Hit
            detection is unchanged and HD-independent: zapper.sv senses the PPU colour index.
            fullsim: sim_top gained the Zapper (zap_en/zap_analog/zap_fire, port 2 D3/D4 as
            NES.sv) and fullsim.cpp --zap FILE ("<frame> <x> <y> <fire>"). Lint: fullsim lint
            clean; hd_reticle -Wall clean; NES.sv's instance is NOT linted (fullsim does not
            compile NES.sv - only Quartus checks it, at the final state).
            OWED, after the recording batch (one heavy job at a time):
            1. build fullsim into a separate OBJ (the batch runs obj/fullsim.exe).
            2. regression: with no --zap, one recorded group reproduces byte for byte.
            3. Duck Hunt g35 with --zap: (a) the crosshair is in the HD frames at the aim
               point, on- and off-screen colours; (b) the same zap script with --hd 0 and
               --hd 1 gives identical NES pictures (hits do not depend on the HD picture);
               (c) a hit lands - read a duck's position from a no-fire run (the sim is
               deterministic), aim there and fire, the duck falls and the score moves.
            4. Mesen reference for the same script, if Mesen 2's Lua can drive its Zapper.
            5. Hardware: the user's Duck Hunt on the MiSTer with the settings above.
            RESULTS 2026-10-27 (runs in Z:/NES_HDPack_work/zap_check, obj_zap; scratchpad
            zap_review.py, zap_step2.py, zap_sheet.py, zap_crop.py):
            1. DONE (tools/fullsim/obj_zap, 10-24).
            2. PASS: obj_zap with no --zap, g35 --rec, frame 300: rec/col/chr bins and nes/vid
               PNGs byte-identical to corpus/g35/rec (made by the pre-Zapper obj/fullsim.exe).
            3a. PASS: the plus sign is in hd_ frames at the aim point (128,100 -> HD 256,200), same
               colour as video.sv's in vid_; off-screen-top (200,5) draws the light-blue plus;
               off the left edge (0,100) nothing drawn. NEGATIVE CONTROL: HD on, no Zapper
               (r7_noz_hd1) vs HD on with Zapper (r3_3pos_hd1), frames 30-150: the only
               difference is bbox (250,198)-(256,204) = the plus sign; without the Zapper no plus.
            3b. PASS: r3_3pos --hd 0 vs --hd 1, 30 nes_ frames, 0 differ.
            3c. PASS: aim at the duck (125,33), fire at 780: duck shot, score 000000 -> 000500,
               HIT counter marks the duck, shells 3 -> 2; no-fire control keeps score 0. (The
               scratchpad zap_step3c_verdict.py prints FAIL because it also demanded the HIT box
               stay unchanged in the no-fire run, where the current-duck marker flashes anyway -
               its criterion was wrong, the frames are right; checked by eye, zs1.png.)
            4. Mesen 2.1.1 (zapper.lua, same aim/fire, Zapper on port 2): the hit registers in both
               (score 500, same HIT counter); fullsim 790 == Mesen 788 exactly (aligned offset 0).
               During the fall 800-870 the duck sprite box differs (fullsim shows the "500" text
               where Mesen does not; best Mesen match drifts -6..+6 frames); from 880 the frames
               match again. Within the game's post-hit sequence, not in the HD path (3b), and not
               in the reticle. Stock zapper.sv behaviour vs Mesen's light-sense timing - not
               changed by this fork. Recorded, not chased.
            5. OWED, hardware only (Claude may not deploy). The Zapper FIX (HD reticle) is
               verified in simulation; the item stays open only for the hardware check.
        AFFINITY (user, 2026-10-22): the MiSTer Frontier cores pin audio to one A9 and video to
          the other. Decisions are measured on core 0 (memory latency ~250 ns there, ~450 ns on
          core 1). When audio moves off the FPGA onto the ARM (this item, part 3), pin it to
          core 1 and keep the decision work on core 0.
    2026-10-27 ALM lever 1 (hd3_audio block scan serialised, HDPACK_DESIGN "As built"):
      synthesis-only NES_PAINT (quartus_map, rc 0, 0 errors): hd3_audio 4,777 -> 4,161 ALUTs
      (-616); hd3_pengine 11,818 -> 11,443; whole design 61,761 -> 61,380 ALUTs, map estimate
      42,887 -> 42,837 ALMs. hd3_romfix moved 3,766 -> 3,998 in the same run (synthesis noise,
      RTL unchanged). Tests: tb_audio_all 26/26, neg_audio 61/61, msim PASS. NOT CLOSED: the
      fitter was at 102% of ALMs on the last fit, and this lever is far smaller than the gap;
      the A9 decision time for Castlevania is still over budget (~17.4 ms decide + fetch/list).
      OWNER DECISION NEEDED before item 15 can run: which larger lever to take - move audio
      and/or romfix to the ARM (estimated ~88% ALMs together), the composite_decoder option,
      or another; and how the Castlevania decision time is brought under the frame.
    2026-10-28 OWNER DECISION APPLIED: audio decoding and the ROM-patch decision moved to the ARM
      (HDPACK_DESIGN "Stage 5 ... Since 2026-10-28" and "Stage 6 ... Since 2026-10-28"; items 12
      and 13 for the tests). Synthesis-only NES_PAINT (quartus_map rc 0, 0 errors):
        map estimate 42,837 -> 38,487 ALMs (102.2% -> 91.8% of 41,910); registers 50,550 ->
        47,189; hd3_audio 4,161 -> 1,365 ALUTs, hd3_romfix 3,998 -> 511 (hd3_sha1 gone).
      FOUND BY THE FIRST RUN: the 2,048 x 16 NES-delay store was built from ~32,000 registers
      (estimate 58,781 ALMs, 140%), "uninferred due to asynchronous read logic": an initial value
      on the store and its output register blocks M10K inference. Stored signed now (zero =
      silence), no initial values; tb_audio_all identical, the store is an M10K in the second run.
      A synthesis estimate is not a fit: whether it fits is item 15's first compile.
      Castlevania's ARM decision time (< 16.6 ms) needs A9 measurements on the device (deploy is
      not allowed to Claude) - an OWNER item.
      MEASURED ON THE DEVICE 2026-10-28 (owner's go-ahead; tools/armdec/bench_a9.sh, current
      hdarm4_a9 md5 11ef9170 cross-built by xbuild.sh, the 2026-10-22 a9_bundle, MENU core loaded,
      core 0, 20 iterations): PARITY 29 of 29. Median ms - Castlevania p002 f0060 17.52, f0250
      17.56, f0450 17.27, f0700 15.07, f1000 16.59, f1300 15.86 (10-22: 23.4 / 20.8 / 20.4 / 17.1 /
      17.8 / 18.2); Zelda II a057 9.2-14.6 (worst f0760 14.58); Metroid a034 7.1-10.9; SMB3 p053
      5.7-12.3. Max column 24-35 ms on most frames (core 0 takes the device IRQs).
      VERDICT: every pack fits the 16.6 ms frame EXCEPT Castlevania - 3 of 6 frames are 0.7-1.0 ms
      over on decide alone, before the record fetch (~1.3 ms) and the list. Still OPEN; the
      remaining levers are (b) records written by the capture in the ARM's form (records = 3.5-3.8
      ms here) and (c) one frame of latency. Owner decision which.
    NAMING DECISION (user, 2026-10-29, confirms the 2026-10-22 one): the name is "NES_HD"
      everywhere - CONF_STR setname NES_HD, games/NES_HD/, _Other/NES_HD_<date>.rbf, ARM daemon
      games/NES_HD/NES_HD, logs/NES_HD/. (NES_HDPack was briefly chosen the same day and
      dropped.) The pack collection lives in games/NES_HD/HD_Packs/ (user, 2026-10-29; the
      handler creates it every launch). The GitHub repo is MiSTerOrganize/NES_HD_MiSTer
      (renamed from NES_MiSTer 2026-10-29; the old URL redirects). The core is a MiSTer Frontier core: Master_Daemon spawns games/NES_HD/_handler.sh
      (in this repo) on CORENAME NES_HD, and the handler execs the daemon. Own setname =
      no CORENAME collision with the stock NES core; saves/configs separate from stock NES.
      MiSTer Main has no core-type check for "NES" (checked user_io.cpp), so the rename turns
      nothing off. Still owed to SHIP it: external_files.csv rows in MiSTer_Frontier + the
      Install/Uninstall checks (discovery-driven; confirm Uninstall's purge never touches
      games/NES).

## C. Later stages
12. Stage 5: ROM patches (IPS/BPS/UPS) applied in SDRAM at pack load, before the mapper is
    configured. BUILT + TESTED in the integration scratch (HDPACK_DESIGN.md "Stage 5 - ROM
    patches as built"): converter section 14 (tools/hdp3_patch.py, 21/21 corpus lines + 300
    synthetic identical to rompatch, 13/13 mutants); hd3_sha1 (416 digests, 9/9 mutants);
    hd3_romfix in the engine (38/38 runs - recorded at the time as "40/40" - and 31/32 mutants,
    the last shown output-equivalent).
    2026-10-20 re-run from the repo: neg_romfix 30/32 - `no_stall` had been caught only by the
    random DDR3-busy sequence lining up, and the repo testbench's extra random draws moved it.
    New case uc_ok_backpressure (--busy-burst 200) forces the FIFO to fill: good build passes
    both orders, no_stall fails with result 5. Cases now 20 / 40 runs, 40/40 pass; neg_romfix
    no_stall re-run: CAUGHT (uc_ok_backpressure after) -> 31/32 + the one output-equivalent.
    2026-10-19: loader patch outputs now checked by tb_loader; neg_loader 34/34 (HDPACK_DESIGN.md
    "Stage 5" tests).
    2026-10-20: moved into rtl/hdpack with the stage-3 engine; tests in tools/sim3 (fixtures in
    tools/sim3/fixtures/romfix), neg_patch.py in tools/. Owed: reconvert a034 with its mmm.ips
    (out/a034.hdp predates section 14) and fullsim Metroid + mmm.ips vs Mesen.
    2026-10-21: a034 reconverted with section 14 into Z:/NES_HDPack_work/out_a034_ips/a034.hdp
    (75,642,368 bytes; out/a034.hdp left as it was): `hdp3_convert.py x/a034 ... --rom
    "Metroid (USA).nes"` applied mmm.ips, dropped 1,987 index-keyed additions as Mesen does
    (the patched cart has CHR-ROM AND CHR-RAM), rc 0. hdp3_read --rom: 0 problems - section
    14 decoded independently and the patched ROM built as the hardware builds it equals
    rompatch.apply. Left: the fullsim run.
    2026-10-21: fullsim run done (item 10 note): with the patched a034 pack the core boots the
    IPS-patched Metroid and draws the same HD frames Mesen does with the same pack and ROM. The
    ROM patch path is verified end to end. Item 12 has no open work left.
    2026-10-22 REOPENED (user: full compatibility for all 136): patches keyed by the iNES 1.0
    form of a No-Intro ROM (113 corpus hashes) and MD5 lines (a037, p099) now apply - in the
    converter, the checker, the planner AND the core (second SHA-1 pass in hd3_romfix,
    HDPACK_DESIGN.md "Beyond Mesen"); pack_fixes.py maps a030's and a037's misnamed patch files.
    Done: test_rommatch ALL PASS; test_hdp3_patch 104 corpus lines (71 via the new rule) ALL
    PASS; romfix_cases 27 cases / 54 runs ALL PASS on the final RTL; neg_romfix 10/10 (8 new
    mutants + 2 re-anchored); test_sha1 416/0. Owed: the reconversion of all 136 + 3 new packs
    (zfax, z1943, zbcity in pack_recipes.tsv; all three convert, hdp3_read 0 problems), the re-plan and the
    re-recording of the groups whose program changed (31 patched groups of 73, against 11 of 57
    before), and the post's wording once that is done.
    2026-10-27 STATUS: the RTL, converter, checker and planner work of the reopen is done and
    tested (above); out5 reconversion done (142/142 OK in convert_corpus.tsv, 2026-10-27 04:29)
    and the re-plan done (corpus_replan, 10-25). What is left is NOT ROM-patch work: the
    re-recording of the patched groups is corpus coverage (item 10) and the post's wording is the
    owner's. Item 12 is CLOSED as an engineering item on that basis; the re-recordings stay owed
    under item 10.
    2026-10-28 MOVED TO THE ARM (item 11 owner decision; HDPACK_DESIGN "Stage 5 ... Since
      2026-10-28"): hd3_romfix stages the download in DDR3 and holds the core; romfix_arm.c
      (hdarm_daemon service thread, core 1) hashes, decides and builds; the FPGA replays the ROM
      it is told to. Tests (results filled in below as each completes): test_romfix_arm.py
      (rf_build vs rompatch on the corpus lines and the synthetic set); romfix_cases on tb_engine
      with romfix_arm linked in, incl. the new arm_silent case; neg_romfix_arm (ARM half);
      neg_romfix (FPGA half). fullsim
      1942 + v1942b_hdmusic (paint route): "romfix: ARM answered (action 1, result 1, 131088
      bytes)", the IPS-patched MMC3 game boots, 0 NES-vs-video differences.
    2026-10-28 (later) handshake hardening, all re-run on fresh builds:
      - FOUND: a core reload restarts both sides at {rseq 1, aseq 2}, so the ARM's late answer to
        the OLD session's status matched the NEW session's question (uc_ok_stale failed with
        result 2). Fix: at power-up hd3_romfix reads the old status and starts rseq 0x40 past it
        (S_INIT0), then clears both qwords; the ARM's rf_session_check forgets its record when
        the core's command qword has been cleared (new session). Length refusal (result 3) for a
        replay length of 0 or past the 4 MB target area.
      - tb fixes: arm_silent could never settle (arm_quiet() waited for a silent ARM to answer)
        and the 2^25-clock timeout takes over half an hour to simulate - tb_engine is now built
        with HD3_SIM_TMO = 2^20 (the RBF keeps 2^25); arm_silent with the ROM loaded BEFORE the
        pack correctly ends at result 2 (the core is never held), not 6. uc_ok_stale2 corrected
        to {65, 2}, the question a FIXED 0x40 jump would repeat (66 was never asked by anyone).
        New case swap_midaccess (a pack download starting while the patcher's poll read is in
        flight, its answer held back past the download).
      - romfix_cases: ALL PASS, 68 runs (34 cases x 2 load orders) + swap_midaccess 2/2.
        test_romfix_arm quick + full ALL PASS; neg_romfix_arm 36/36 caught.
      - neg_romfix new mutants: rseq_not_moved_at_powerup, old_status_not_read, bad_length_accepted,
        zero_length_accepted all CAUGHT. Two earlier "CAUGHT (arm_silent)" verdicts were fake
        (the case timed out) - re-run with the short timeout they were MISSED, and both are now
        recorded in neg_romfix.py as not observable, with the measurement: the `take` guard is
        an equivalent mutant (the state machine is held while drop != 0); removing `drop`
        shifts answers by one access and the shift heals at the next idle answer before any read
        whose data matters (swap_midaccess drives 2 accesses outstanding in S_MEM; all pass).
      - neg_loader (p080, uc, lane, p132, + p093 for a pack that leaves the game's type to the
        cart): 30/30 caught, 3 not observable (no pack has a fallback map or render_orig bits).
        Before p093 was added, "game_ram ignores the cart" read MISSED: no given pack exercised
        it; neg_loader now reports both game_ram mutants NOT OBSERVABLE when that is so.
      - fullsim both routes REBUILT (an earlier attempt ran out of memory and silently re-ran the
        old binaries; those results were discarded), 1942 + v1942b_hdmusic 150 frames, paint
        route: ARM answered (action 1, result 1, 131088 bytes), 0 NES-vs-video differences,
        124,512 ticks, 6 events, 0 bad, 0 fetch failures, 0 underruns. Engine route: the same figures.
      - hdarm_daemon cross-built (docker, debian:bookworm) after the core-0 pin; ModelSim
        front-end check PASS (23 files) after the hd3_romfix changes.
13. Stage 6: audio, $4100-$4106 (and the alternate range), BGM/SFX from decoded tracks in
    DDR3, mixed with the APU. IN PROGRESS
    2026-10-21: hd3_audio built and wired (hd3_engine reader 7; nes.v bus export + gating;
    NES.sv AUDIO_S/L/R; loader + hd3_ddr overflow window for file bytes >= 192 MB). Tests
    (HDPACK_DESIGN.md "Stage 6 - Tests"): tb_audio vs hdaudio.py 26/26 runs identical;
    neg_audio 35/35; loader window 45 checks 0 failures, neg_loader_window 8/8; neg_loader
    33/33; engine lint 0/0; ModelSim 22 files PASS; run_engine quick ALL PASS.
    Left: (a) run_engine full + fullsim rebuild with the new nes.v bus (no-regression run);
    (b) Mesen's $4100-$4106 writes for a recorded input against fullsim's, with a pack whose
    ROM writes the device; (c) NES level (NES_SHIFT) measured against Mesen; (d) ADPCM output
    vs Mesen's decode + Hermite chain (signal-to-noise).
    (c) DONE 2026-10-21: NES level measured against Mesen's NesSoundMixer formula (HDPACK_DESIGN.md
    "Stage 6 - NES level"): core/Mesen 1.43-1.76 by channel through the halving mapper path,
    which every mapper of the 85 audio packs uses (expansion mixers halve the 2A03 too). NES_SHIFT
    replaced by a 5/8 gain (x/2 + x/8): -1.0..+0.8 dB per channel. Model + tb updated, 26 runs
    identical, neg_audio 58/58 (2 new mutants), lint 0/0, ModelSim PASS.
    (d) DONE 2026-10-21: ADPCM against Mesen's decode + Hermite chain (HDPACK_DESIGN.md
    "Stage 6 - ADPCM against Mesen"): new `oggdecode snr`, cross-checked against the model decoder
    to 0.01 dB; all 85 audio packs, 681 distinct files / 33,959 s: mean 34.2 dB, median 33.2 dB,
    58 files under 20 dB (chiptune square waves, worst 7.4 dB). Converter output unchanged (byte-identical),
    test_ima.py ALL PASS.
    (f) APPLIED 2026-10-26 (user's call, option 1): depth-3 lookahead encoder in oggdecode.cpp
    and hdaudio.py (HDPACK_DESIGN.md "Stage 6 - ADPCM against Mesen"); decoder, format and
    hardware unchanged. Last-level shortcut checked against all 16 nibbles over 20,000 states
    (it needs the other sign's magnitude 0 for a clamped predictor - the first version missed
    it and the check caught it); C == Python at depth 3; loop restore holds; test_ima.py ALL
    PASS. Worst greedy files now: Metal 7.4 -> 14.3, BirdOutOfHole 10.2 -> 18.1, PowerBeamShot
    11.5 -> 18.9, Mappy sfx-wave 11.9 -> 22.0, sfx-get 12.0 -> 23.1, bgm-flydisc 11.5 -> 20.9.
    The four packs that carry those files (p036 p043 p100 p110) reconverted into
    Z:/NES_HDPack_work/out4: 142/142 OK, 0 "off Mesen". STILL TO DO: the full depth-3 corpus
    rebuild into Z:/NES_HDPack_work/out5 (running, ~5.5 h; first pack a033 1524 s vs 202 s) -
    then confirm 142 OK, re-run snr_corpus.py for the corpus-wide figures, and use out5 for the
    re-recordings.
    2026-10-27: out5 finished 04:29, convert_corpus.tsv 142/142 OK. snr_corpus re-run at depth 3
      (scratchpad snr3/, `oggdecode snr FILE 48000 3`; Metal.ogg reproduces 14.27 dB): 88 audio
      packs, 694 distinct files / 35,165 s, 0 undecodable; duration-weighted mean 35.88 dB
      (greedy 34.2), median 34.64 (33.2), min 14.27 (7.4); worst loud 100 ms window 12.37 dB
      (0_bgm-main.ogg; greedy 7.4), 1st percentile 16.61 (9.1); files < 20 dB: 5 (greedy 58),
      < 30 dB: 124 (216). HDPACK_DESIGN "ADPCM against Mesen" corpus figures to be read as these.
      (f) DONE.
    (b) 2026-10-27, MEASURED (not fully closed - frame skew): 1942 + v1942b_hdmusic (out5; the
      core applies 1942HDMUSIC.ips at pack load), generic.txt input. Mesen 2.1.1 with the a082
      files + the overlay hires.txt in HdPacks/aud1942 (scratchpad aud13b_mesen.py, audlog.lua,
      1200 frames) logs 6 writes; fullsim (obj_zap, --audlog, 601 frames,
      Z:/NES_HDPack_work/aud13b) logs 6. Address, value and order identical:
      4100=01 4105=01 4102=FF 4105=01 | 4105=09 | 4105=01. Frames (fullsim numbering, Mesen-2):
      fullsim 1,1,1,1,3,557 vs Mesen 0,0,0,0,2,553 - the first five one frame apart, the last
      four. Comparator aud13b_compare.py --selftest catches a changed value, a moved frame and a
      dropped write. NOT explained yet: the +1 on the first writes (frame-numbering convention,
      fullsim F = Mesen F+2 was measured on SMB) and the 4-frame skew at the last write
      (input-driven; Mesen randomises power-on RAM, fullsim zeroes it). Owed: an input-free
      write (attract demo) to separate the two, or Mesen with zeroed RAM.
      CLOSED 2026-10-28 - not a core defect; the skew is the harness's input alignment.
        RAM: Mesen with RamPowerOnState AllZeros (fullsim's state) still logs the 6th write at raw
        frame 555 (random RAM 555, AllOnes 556 - so the setting is live); zeroed RAM does not
        remove the skew.
        Input: with NO input the 6th write never happens (5 writes), so it is input-driven. 1942
        acts on input every 3 frames, so the 6th write follows MESEN_INPUT_OFFSET as a 3-frame
        staircase: offset -2 -> 561, -1..1 -> 558, 2..4 -> 555, 5..7 -> 552, 8..10 -> 549,
        11..12 -> 546 (scratchpad aud13b_offsets.py). At offset -1..1 Mesen logs raw frames
        2,2,2,2,4,558 against fullsim's 1,1,1,1,3,557: every write exactly +1, the same constant
        numbering offset as the first writes, with address, value and order identical. The
        harness's MESEN_INPUT_OFFSET=2 (the F+2 measured on SMB) is 1 frame too large for this
        comparison; with the matching offset fullsim and Mesen agree on all 6 writes.
    (a) PARTLY: fullsim obj_zap (built 10-24 with the nes.v bus export) reproduces the corpus
      g35 (Duck Hunt) --rec recording of the pre-export obj/fullsim.exe byte for byte at frame
      300 (rec/col/chr/nes/vid identical) - the nes.v bus/gating does not change the NES.
      run_engine full not re-run (it tests hd3_engine; see item 11 on which engine is final).
    2026-10-27 hd3_audio block scan serialised for item 11 (HDPACK_DESIGN "As built"): tb_audio_all
      26/26 identical, neg_audio 61/61 caught (35 re-anchored + 3 new scan mutants), msim PASS.
    2026-10-28 DECODING MOVED TO THE ARM (item 11 owner decision; HDPACK_DESIGN "Stage 6 ...
      Since 2026-10-28"): hd3_audio keeps registers, key search, voice tracker, tick and mix;
      events go to a DDR3 log; aud_arm.c (hdarm_daemon thread, core 1) decodes and writes PCM
      slots the mix reads AUD_D = 1024 ticks (21.3 ms) later, the NES path delayed by the same.
      Streams are read from the pack in DDR3 256 bytes at a time (no copy into ARM memory).
      Tests: tb_audio_all (both windows, slow ARM, no ARM, event queue of 2, AUD_D 1024) ALL
      IDENTICAL; test_aud_arm.c ALL PASS; test_ima ALL PASS; msim 23 files PASS; lint 0/0;
      fullsim 1942 + v1942b_hdmusic (paint route): 124,512 ticks rendered, 6 events, 0 bad, 0
      fetch failures, 0 underruns, register writes identical to the 10-27 run.
      Found on the way: the log FIFO wrote one slot late (slow-ARM run); the ARM render loop
      stopped short when one tick's events filled its queue (event-queue-of-2 build); four
      mutants nothing caught (power-on volume save, SFX stolen = newest, save word A not held,
      window boundary), now covered by new scenario steps. neg_audio: see the line below.
      OWNER-LEVEL CHANGES: all audio 21.3 ms later while the device is active (~1.3 frames behind
      the picture); no HD music or SFX if the ARM program is not running (NES audio still plays);
      a program started late plays only voices started after it.
    2026-10-28 (later) hardening, re-run on fresh builds:
      - FOUND (RTL): with the event log FIFO full and DDR3 writes stalled, the state machine
        waited in S_LOGP and the 48 kHz tick stalled with it. Fix: an event is taken only when
        the FIFO has room for its two entries (wf_room); otherwise it stays queued (4 deep) and a
        full queue drops it and counts it (ev_lost, an hd3_engine output). New tb run --flood
        (write port stalled 150k clocks, 8 writes a frame): lost > 0, every taken event logged,
        ARM 0 bad events.
      - PCM slot read: the tag is latched on beat 0 and checked on beat 7 against the slot's
        current tick, so a late read is discarded whole, never half-mixed (tb --pcm-late).
      - tb_audio: table bursts past the window now carry junk beats (as the hardware's do);
        --off runs at 0x2028/0x2038 (lo-window bursts); the ARM builds its checkpoints every tick.
      - tb_audio_all ALL IDENTICAL; neg_audio 115/115 caught (new: PCM mixable before the last
        beat, unaligned table burst, CPU-write queue wraps, event taken with the log full, and
        ARM mutants for the builder end, bad-entry gate, entry range, header re-read, status
        loop, fresh-start check, late load, catch-up cap, forward-jump restart); test_aud_arm
        ALL PASS; test_ima ALL PASS; lint 0/0; msim 23 files PASS.
      - hdarm_daemon: the main thread is now pinned to core 0 before its threads start (the
        affinity comment had claimed it was).
      - Not covered by a negative control: a pack reset arriving mid-tick still finishes that
        tick (output-identical at the frame-count level the tb compares).
        CLOSED 2026-10-28: tb_audio `K d` (+ tb_audio_run.py --reset-mid) drops the section
        length for one clk_f, d = 0..15 clk_f after the edge that takes a tick, and reads the
        FSM state at the reset edge (st/pok_f/old_pok/tick_pend are verilator public_flat_rd;
        comments only, no logic change). Per reset it checks: a reset in S_TRK, S_NES or S_MIX
        lets that tick finish (exactly 1 frame between the reset and the reload), a reset in
        S_IDLE produces none, and the logged reset event is stamped with the tick count after
        it; the run fails unless all three tick states were hit. Seeds 1 and 3 (random, 3000):
        16 resets, states 0/4/5/6, 0 wrong, the ARM half saw all 17 resets, U 0, 0 mismatches.
        neg_audio mutants 18 (reset aborts the tick) and 19 (only the tracker may finish) are
        CAUGHT by the new run alone - the nine existing runs passed both. tb_audio_all.sh ALL
        IDENTICAL with the two new runs.
      - LATE START FIXED 2026-10-28 (was "a program started late plays only voices started after
        it"). RTL: a kind-4 state event every 2^SYNC_LOG2 = 256 ticks (5.3 ms) - payload = save
        word A of now (snap_now), header flags bit 0 = BGM paused (lg_flags, the old 4'd0 field).
        ARM: an aud_arm started after the session's pack reset scans the log back from the newest
        event for the latest kind-4 within AUD_NSLOT/2 ticks, starts at its tick and index, and
        applies it as a restore (BGM at its frame, pause flag); a side that started with the
        session ignores them. Only SFX already playing at the start are lost (by design). Tests:
        tb_audio_run --arm-late playing / paused (ARM held off, started at frame 2300/2400 with a
        looping BGM; paused also resumes at 2900): 0 mismatches from F+D+64 on. neg_audio 4 new
        mutants (no state events, pause flag dropped, ARM ignores them, flags not read) all
        CAUGHT; 119 total. tb_audio_all ALL IDENTICAL (40 runs), test_aud_arm ALL PASS, msim 23 PASS.
      - AUDIO LAG HALVED 2026-10-29: AUD_D 1024 -> 512 ticks (21.3 ms -> 10.7 ms), AUD_CK 65536 ->
        16384. (The 10-28 "the 21.3 ms stays" decision was taken without the measurement it said
        was needed; the owner asked again and it was measured.) A9, SCHED_FIFO on core 1, scratch
        aud_bench.c: decode 132-135 ns a frame; a restore from a checkpoint was 9.0 ms at the old
        spacing, 2.31 ms max at 16384; a checkpoint-builder pass 1.6 ms max; 96 ticks of BGM
        0.04 ms; the 2 ms sleep wakes at most 0.15 ms late (29,506 sleeps, 60 s). Worst gap
        between renders: 2 + 0.11 + 1.6 + 2.31 = ~6.1 ms = ~292 ticks, inside 512 with 1.75x.
        A 52 ms stall seen once per ~0.7 s while the bench ran the builder NONSTOP was RT
        throttling (sched_rt_runtime_us 950000 / period 1000000); with the daemon's 2 ms sleep
        between passes: 5 runs, 0 passes over 2 ms. The extra checkpoints cost 4x as many
        8-byte states (one per 0.34 s of audio). tb_audio_all: shipped build at 512, plus --arm
        490000 (an ARM pass every ~274 ticks, the measured gap) random and --busy, plus a control
        at --arm 1074000 (~600 ticks a pass) that must mismatch.
      - FIXED 2026-10-29 (owner: fix it): a savestate loaded before the checkpoint builder had
        reached that BGM decoded from frame 0 in one pass (562 ms for a frame 4.19 M = 87 s into
        a stream on the A9): the HD voices dropped out that long. Neither option first proposed
        removes the dropout (building that stream first still has to decode from frame 0, and
        spreading the decode keeps the thread free but the music still waits), because IMA ADPCM
        has to be decoded in order to reach a frame. So the converter now stores the states:
        section 15 header word 0x0C = a checkpoint table (HDPACK_DESIGN "Section 15 layout"),
        written by oggdecode as it encodes, read by aud_arm.c load_checkpoints at pack load;
        the FPGA does not read the word. A table that does not fit is ignored and the old builder
        runs, as for packs converted earlier (they need converting again to gain the fix).
        Tests: test_aud_arm 42 PASS (new 4b: a restore 2*16384+300 frames in, before any builder
        pass, plays the same sample from a few block reads; tables with another spacing, a wrong
        count, a wrong first state, an index of 89, or an offset past the section are each not
        used and the restore is still right); test_ima ALL PASS (encoder checkpoints == an
        independent decode, incl. a length the spacing divides and one shorter than it);
        tb_audio_all ALL IDENTICAL (table taken in 41 runs; two new --no-ck runs, the
        pre-2026-10-29 format, take the builder path); hdp3_read.check_audio re-derives every
        state over the whole stream (oggdecode ckscan) and neg_audio_section has 4 new mutants.
      - CHECKED 2026-10-29: savestates ignore word B BY DESIGN. Mesen's HdAudioDevice::Serialize
        (tools/audio/mesen/HdAudioDevice.cpp:40) keeps album, BGM track, track offset, SFX volume,
        BGM volume and playback options; word A carries every one (album, volumes, loop, BGM on +
        entry + frame) and nothing else in Mesen is saved (no SFX, no pause). Word B held the
        BGM's ADPCM state; the ARM now rebuilds that exactly by decoding from the checkpoint below
        the frame (aud_restore), so it would be redundant. ss_out_b is tied to 0 and ss_in_b is
        unread in hd3_audio.sv.
      - DEGRADE WITHOUT THE ARM PROGRAM: HD audio - tb --arm 0 (every slot missing and counted,
        NES path alone comes out). ROM patching - romfix arm_silent: result 6 after the timeout,
        the ROM runs unpatched. Both already tested; nothing new needed.
    (e) DONE 2026-10-21: savestates (HDPACK_DESIGN.md "Stage 6 - Savestates"). User's call:
    resume EXACTLY (saved frame + ADPCM state), not Mesen's offset-as-sample-number quirk; SFX
    and pause untouched as in Mesen; a save with no BGM stops the BGM on load (Mesen leaves it).
    Two savestate registers (indices 29/30) in NES.sv, nes.v `SaveStateExt_save`, hd3_audio
    snapshot handshake + restore. tb_audio vs the model: 26 runs identical, 994 saves and 1,044
    loads compared; neg_audio 56/56 caught (21 savestate mutants). Not covered by simulation:
    the NES.sv / nes.v wiring through savestates.vhd (hardware only; vlog clean on every new
    line) - check on hardware after item 15.

## D. Close-out
14. Iterative audit of the integrated engine (capped at round 5) and the final full-project
    sweep. OPEN
    2026-10-27: not run - it belongs at the final state, and the design is not final (item 11
    does not fit).
15. Quartus at the final state: SEED 1, 2, ... 20, read every clock's slack after each; stop
    at the first all-positive seed, or report at 20. OPEN
    2026-10-27: BLOCKED by item 11 - NES_PAINT does not fit (102% ALMs at the last fit), so no
    seed can pass. No full compile was run. Pass bar since 2026-10-26: EVERY slack >= +0.200 ns.
    2026-10-29 FIRST FULL COMPILE (SEED 1, NES_PAINT): it FITS now (ALMs 89%, DSP 98%, M10K 47%
    - both of the first two in the alert band), and timing MISSED by far more than placement:
    setup -9.230 ns on clk85 and -4.691 ns on clk (hold worst +0.129 on pll_hdmi; the HDMI
    scaler's own paths at -0.196 are the usual seed-sized framework margin). Both large misses
    are two real RTL defects in hd3_audio, the first time its clock crossings were ever timed:
      - clk -> clk85: nes_sample went straight from the APU mixer (combinational) into nd_wd,
        19.8 ns of logic in the 11.6 ns a related-clock crossing gets (20,000+ paths).
      - clk85 -> clk: hit_rd / hit_wr were decoded from en_f / alt_f / pok_f / tab_ok (clk_f
        registers) and go combinationally into the CPU bus mux and the T65 (~20,000 paths).
    FIXED in hd3_audio.sv: nes_sample registered on clk (nes_c) before clk_f reads it; the bus
    decode now starts from core-clock registers (en_c / pok_c / alt_c / tab_c). Both query
    reports hit their 20,000-path cap, so other classes may sit behind these two - the next
    compile shows them. tb_audio_all ALL IDENTICAL and msim_check PASS on the fixed RTL.
    SEED count restarts at 1 for the fixed design.
    2026-10-29 second compile (SEED 1, both crossings fixed): clk -9.230 -> setup +1.269, clk85
    -> -0.152, paths under +0.200 ns 40,047 -> 239. What is left: the HDMI framework (sys/
    shadowmask -> osd, ascal) at -0.285 (framework, seed only); hd3_audio's S_TRK voice-list
    compaction (m_done[ord[i]] through a 7-step prefix in one clock) at -0.152; hd3_paint's
    crow1 line buffer at +0.041. FIXED the hd3_audio one: S_TRK now registers each SFX
    position's keep bit (m_keep) and a new state S_TRKC (11) compacts from it - one more clk_f
    clock per tick, of ~1,790. The pack-reset rule (a tick being mixed finishes) includes
    S_TRKC; tb_audio_run's --reset-mid now wants a reset in each of S_TRK, S_TRKC, S_NES and
    S_MIX (all four hit). neg_audio: three anchors moved with today's RTL (nes_c, the bus
    decode) and four had been broken since lg_flags / a second next_t line went in - all
    re-anchored; new mutants for nes_c, tab_c in the bus decode, m_keep, the S_TRKC reset rule
    and the six checks of the section's checkpoint table. tb_audio_all ALL IDENTICAL,
    msim_check PASS. Third compile, SEED 1 again.
    2026-10-29 third compile: clk85 setup -4.323, two NEW long paths, both mine, both now split:
    (1) hd3_audio S_TRK: selecting the voice at m_i (ord[m_i-1], then 8-way muxes of 29-bit
    v_pos/v_frames/v_lpos) and the end/loop compares in one clock. New state S_TRKV (12): S_TRK
    registers the voice's fields (t_v/t_play/t_pos/t_fr/t_lp/t_loop), S_TRKV does the update -
    one more clk_f clock per voice per tick. Pack-reset rule includes S_TRKV; --reset-mid hits
    all five tick states [4,5,6,11,12]; tb_audio_all ALL IDENTICAL. neg_audio mutants
    re-anchored (pause, loop restart, end-a-frame-late, voice-list compaction) + new ones for
    t_play's BGM pause and the S_TRKV reset rule. tb_audio's K command now also counts clocks
    the device takes the bus while its tables reload (tab_ok low > 8 clocks; L line, must be 0)
    - closes the gap where the "bus decode ignores tab_ok" mutant went MISSED.
    (2) hd3_paint: crow0/crow1 + line-buffer M10K read (unregistered output) -> 8x8 multiply ->
    blend select -> lbw_d in one clock (-4.08; +0.041 the compile before, by luck). New stage
    s2 registers both RAM reads; issue-to-write 2 -> 3 clocks, so the next-span start and EOL
    wait for s2_v too. paint_parity 29/29 normal + pub, worst line 1,881 clocks of 5,456.
    COVERAGE GAP FOUND: paint_parity cannot see this hazard at all - with the start guard
    removed COMPLETELY all 29 frames stayed pixel-exact (no recorded span starts within two
    pixels of the previous span's last write). New test tools/sim3/paint_hazard.{py,sh}: after
    every BLIT adds a 1-pixel additive BLIT on its last pixel, painted with and without an FX
    gap (FX value of the line, so nothing else changes); the two pictures must match. Real
    RTL 28/28 (1 frame has no BLIT); the start guard one clock early (no !s2_v) -> 0/28. The
    EOL's !s2_v is redundant by construction (the start guard already holds the EOL back) and
    is kept as defence like its !s1_v. Fourth compile, SEED 1.
    2026-10-29 fourth compile: clk85 setup -2.277, hdmi +0.026. Worst path now c0_r/c1_r ->
    lbw_d: the blend itself (12 8x8 multiplies in logic - DSP 98% full - plus add, compare and
    mode select) in one clock. Split again: s3 registers each channel's bprep {a==FF, a==0,
    ((256-a)*o)>>8, o, p}, the next clock does bfin (the mode select). Issue-to-write 4
    clocks; start + EOL wait for s3_v. paint_parity 29/29 normal + pub, worst line 1,971 of
    5,456; paint_hazard 28/28, and 0/28 with !s3_v dropped from the start guard. neg_audio:
    132/133 caught; the miss (spacing check removed) was a test gap - test_aud_arm's bad-spacing
    table also had the wrong count, so the count check refused it first. ck_table now always
    writes the AUD_CK count; the spacing mutant fails it. (The fourth compile's path dump
    first hung: quartus_sta crashed in sta_find_duplicates_of_deleted_net_name and sat on the
    trace for ~7 h; re-run under a 15-min timeout it finished.) Fifth compile, SEED 1.
    2026-10-29 fifth compile: clk85 -0.449 (was -2.277), hdmi -0.023, hold min +0.191 (hdmi
    ascal) / +0.215 (clk85); ALM 90%, DSP 98%. The clk85 paths are hd3_audio's nesd M10K output
    -> S_NES DC block/clamp/level -> acc_l/acc_r. nd_q is read at the tick and used >= 4
    clocks later, so a second register nd_q2 (2 clocks) costs nothing; tb_audio_all ALL
    IDENTICAL, msim PASS. The hdmi paths are framework (sys/ ascal), seed only. Sixth compile,
    SEED 1.
    2026-10-20 pre-Quartus front-end check (ModelSim ASE 10.5 from the Quartus 17 install, every
    rtl/hdpack file in files.qip): found constructs Verilator accepts and standard SV (so likely
    Quartus 17) rejects, all fixed - hd3_render indexed a part-select (`fl[a -: 4][j]` ->
    `fl[a-3 + j]`); hd3_add / hd3_resolve / hd3_ccache / hd3_rcache used names before declaring
    them (declarations moved up). Now 21/21 files compile with 0 errors, 0 warnings. And
    hd3_render's $readmemh used bare names that Quartus resolves against the PROJECT folder
    (video.sv uses "rtl/tao.mif"), which would have synthesised the 2C02 palette and emphasis
    ROMs as zeros; now `ifdef VERILATOR` bare / else "rtl/hdpack/...". ModelSim run from the
    project folder loads all four ROMs matching the files; the control run from tools/ warns
    "Failed to open readmem file" and reads x. At the final compile still check the map report
    for $readmemh / 10850 warnings - ModelSim is not Quartus. The RTL edits above still need
    the simulation regression (run_engine quick, test_render_all, neg_* where touched).
    2026-10-21: done - all of it passes on the edited RTL (item 8's 10-21 note). The check is
    now repeatable: sh tools/msim_check.sh.
