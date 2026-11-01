"""Negative controls for HD audio: rtl/hdpack/hd3_audio.sv (the FPGA half) and
tools/armdec/aud_arm.c (the ARM half). Every mutation must be caught by tb_audio.

    python tools/audio/neg_audio.py [--from N] [--to N] [--list]

Each mutation replaces one anchor (which must match exactly once - a mutation that matches
nothing is a broken control, not a pass) in a copy of one of the two files, builds the
testbench with the overflow window inside the entry table (WIN 8448) and an ARM event queue of
2 (so the queue-full path runs), and runs the comparison: scripted default registers (hi window
required), scripted alternate registers, random writes, a PAL run, a busy-DDR run, and a run
with the ARM half stopped (every PCM slot missing: the underrun count and the NES-only output
are checked). A mutation is CAUGHT when any run fails. Exit 0 only if every mutation in range
is caught.

Since 2026-10-28 (OPEN_ITEMS item 11) the decoding and the volumes run on the ARM, so their
controls (IMA tables, volume rounding, loop state, mix order) are mutations of aud_arm.c; the
register, tracker, savestate, event-log and mix controls are mutations of hd3_audio.sv.
"""
import argparse, os, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
FILES = {
    "rtl": os.path.join(ROOT, "rtl", "hdpack", "hd3_audio.sv"),
    "arm": os.path.join(ROOT, "tools", "armdec", "aud_arm.c"),
}
WIN = "8448"
GCC_ENV = dict(os.environ, PATH="C:/msys64/mingw64/bin;" + os.environ.get("PATH", ""))
# the pack-reset rule: the states of a tick being mixed, which a reset lets finish
RST_KEEP = ("if (st != S_TRK && st != S_TRKV && st != S_TRKC && st != S_NES && st != S_MIX)\n"
            "\t\t\tst <= S_IDLE;")

M = [
    # ---- FPGA: the mix (NES path delayed by AUD_D, then the voices of the PCM slot)
    ("rtl", "DC blocker shift 10 -> 9", "(dc_y >>> 10)", "(dc_y >>> 9)"),
    ("rtl", "DC blocker removed", "y = 20'(nes_x) - dc_x + dc_y - (dc_y >>> 10);", "y = 20'(nes_x);"),
    ("rtl", "NES sample not made signed", "nd_wd <= {~nes_c[15], nes_c[14:0]};",
     "nd_wd <= nes_c;"),
    ("rtl", "NES sample read on clk_f straight from the APU (not through nes_c)",
     "always @(posedge clk) nes_c <= nes_sample;", "always @(posedge clk) nes_c <= 16'h8000;"),
    ("rtl", "NES path not delayed", "nd_ra <= 11'(tcount - AUD_D);", "nd_ra <= 11'(tcount - 1);"),
    ("rtl", "mix wraps instead of clamping",
     "acc_l <= clamp16({{4{acc_l[15]}}, acc_l} + {{4{sl[15]}}, sl});",
     "acc_l <= 16'({{4{acc_l[15]}}, acc_l} + {{4{sl[15]}}, sl});"),
    ("rtl", "voice R taken from the L half", "sr = m_pcm ? pc_s[m_i[2:0]][31:16]",
     "sr = m_pcm ? pc_s[m_i[2:0]][15:0]"),
    ("rtl", "PCM beat halves swapped", "pc_s[{r_beat[1:0] - 2'd1, 1'b0}] <= rd_data[31:0];",
     "pc_s[{r_beat[1:0] - 2'd1, 1'b0}] <= rd_data[63:32];"),
    ("rtl", "PCM slot of the wrong tick", "pc_t <= tcount + 32'd1 - AUD_D;", "pc_t <= tcount - AUD_D;"),
    ("rtl", "slot tag not checked", "pc_ok   <= pc_tag == {8'hD5, 24'd0, pc_t};", "pc_ok   <= 1'b1;"),
    ("rtl", "PCM slot mixable before its last beat", "if (r_beat == 3'd0) pc_tag <= rd_data;",
     "if (r_beat == 3'd0) begin pc_tag <= rd_data; pc_done <= 1; pc_ok <= rd_data == {8'hD5, 24'd0, pc_t}; end"),
    ("rtl", "table burst not aligned to 64 bytes", "f2q({off_f[28:6], 6'd0} + {14'd0, ld_burst, 6'd0})",
     "f2q(off_f + {14'd0, ld_burst, 6'd0})"),
    ("rtl", "CPU-write queue wraps when full", "if (ev_wp + 2'd1 == ev_rp) begin", "if (1'b0) begin"),
    ("rtl", "an event is taken with the log FIFO full", "wire       wf_room = wf_n <= 9'd253;",
     "wire       wf_room = 1'b1;"),
    ("rtl", "underrun not counted", "underruns <= underruns + 16'd1;", "underruns <= underruns;"),
    ("rtl", "underrun counted in the first D ticks", "if (since_rst >= 11'(AUD_D) && ", "if ("),
    ("rtl", "NES level: x/8 term dropped", "nes_level = (c >>> 1) + (c >>> 3);", "nes_level = (c >>> 1);"),
    ("rtl", "NES level: logical shifts", "nes_level = (c >>> 1) + (c >>> 3);", "nes_level = (c >> 1) + (c >> 3);"),
    ("rtl", "a pack reset aborts the tick being mixed", RST_KEEP, "st <= S_IDLE;"),
    ("rtl", "a pack reset lets the tick's tracker finish but not its mix", RST_KEEP,
     "if (st != S_TRK && st != S_TRKV && st != S_TRKC)\n\t\t\tst <= S_IDLE;"),
    ("rtl", "an ended SFX stays in the voice list",
     "m_keep[i] <= i < n_sfx && !m_done[ord[i]];", "m_keep[i] <= i < n_sfx;"),
    ("rtl", "a pack reset aborts the tick in its compaction clock", RST_KEEP,
     "if (st != S_TRK && st != S_TRKV && st != S_NES && st != S_MIX)\n\t\t\tst <= S_IDLE;"),
    ("rtl", "a pack reset aborts the tick in a voice's update clock", RST_KEEP,
     "if (st != S_TRK && st != S_TRKC && st != S_NES && st != S_MIX)\n\t\t\tst <= S_IDLE;"),
    ("rtl", "no state events logged", "if (&tcount[SYNC_LOG2-1:0]) sync_due <= 1;", ""),
    ("rtl", "state event drops the pause flag", "lg_flags <= {3'd0, r_pause};", "lg_flags <= 4'd0;"),
    ("rtl", "tick lost while busy", "if (tnext >= tmod) tick_pend <= 1;",
     "if (tnext >= tmod && st == S_IDLE) tick_pend <= 1;"),
    ("rtl", "PAL modulus", "pal ? 27'd106406848", "pal ? 27'd85909091"),
    # ---- FPGA: registers, status, entry tables
    ("rtl", "alternate register decode", "{(addr > 16'h4100) ? addr[2:0] : addr[6:4], wdata}",
     "{addr[2:0], wdata}"),
    ("rtl", "revision byte", "(addr[2:0] == 3'd1) ? 8'd1", "(addr[2:0] == 3'd1) ? 8'd2"),
    ("rtl", "$4105/$4106 reads not taken", "assign hit_rd = active_c & (alt_c ? alt_r : def_a);",
     "assign hit_rd = active_c & (alt_c ? alt_r : def_a & addr[2:0] < 3'd5);"),
    ("rtl", "bus decode ignores the tables-loaded flag", "wire active_c = en_c & pok_c & tab_c;",
     "wire active_c = en_c & pok_c;"),
    ("rtl", "BGM status ignores pause", "st_bgm <= v_on[0] & ~r_pause;", "st_bgm <= v_on[0];"),
    ("rtl", "stop-SFX bit", "if (ev_head[2]) begin", "if (ev_head[3]) begin"),
    ("rtl", "SFX error bit always 0", "st_err <= kt_q[17];", "st_err <= 1'b0;"),
    ("rtl", "BGM error bit always 1", "st_err <= !kt_q[17];", "st_err <= 1'b1;"),
    ("rtl", "undefined id sets error", "st_err <= 0;                          // undefined id",
     "st_err <= 1;                          // undefined id"),
    ("rtl", "binary search lower bound", "s_lo <= {1'b0, s_mid} + 10'd1;", "s_lo <= {1'b0, s_mid};"),
    ("rtl", "album ignored", "{ev_head[10:8] == 3'd6, r_album, ev_head[7:0]}",
     "{ev_head[10:8] == 3'd6, 8'd0, ev_head[7:0]}"),
    ("rtl", "undecodable flag lost", "kt_wd[17] <= rd_data[31:0] == 32'd0;", "kt_wd[17] <= 1'b0;"),
    ("rtl", "entry count limit", "rd_data[63:32] > 32'd512", "rd_data[63:32] > 32'd16"),
    ("rtl", "frame count from the wrong word", "en_wd <= {rd_data[60:32], rd_data[28:0]};",
     "en_wd <= {rd_data[60:32], rd_data[28:0] + 29'd1};"),
    ("rtl", "loop frame from the wrong word", "en_wd <= {rd_data[60:32], rd_data[28:0]};",
     "en_wd <= {29'd0, rd_data[28:0]};"),
    ("rtl", "overflow window off by a qword", "OVF_Q + f[27:3] - WIN_BYTES[27:3]",
     "OVF_Q + f[27:3] - WIN_BYTES[27:3] + 25'd1"),
    ("rtl", "window boundary < -> <=", "(f < WIN_BYTES)", "(f <= WIN_BYTES)"),
    ("rtl", "power-on BGM volume", "r_bvol <= 8'd128; r_svol <= 8'd128; r_album <= 0;",
     "r_bvol <= 8'd255; r_svol <= 8'd128; r_album <= 0;"),
    # ---- FPGA: the voice tracker (status bits and savestate positions)
    ("rtl", "tracker loop restarts at frame 0", "? t_lp : t_pos;", "? 29'd0 : t_pos;"),
    ("rtl", "tracker: pause stops SFX too", "(mv == 3'd0 && r_pause)", "r_pause"),
    ("rtl", "tracker: a paused BGM still advances",
     "t_play <= v_on[mv] && !(mv == 3'd0 && r_pause);", "t_play <= v_on[mv];"),
    ("rtl", "tracker: steal newest SFX", "v = ord[0];", "v = ord[SFX_V - 1];"),
    ("rtl", "tracker: non-looping end a frame late",
     "if (p + 29'd1 >= t_fr && !t_loop) m_done[t_v] <= 1;", ""),
    ("rtl", "tracker: the voice list keeps every position",
     "if (m_keep[i]) begin ord[k] <= ord[i]; k = k + 3'd1; end",
     "begin ord[k] <= ord[i]; k = k + 3'd1; end"),
    # ---- FPGA: savestates
    ("rtl", "restore ignores the saved frame", "v_pos[0] <= ss_in_a[28:0];", "v_pos[0] <= 29'd0;"),
    ("rtl", "restore keeps a BGM the save had not", "\t\tend else\n\t\t\tv_on[0] <= 0;\n", "\t\tend\n"),
    ("rtl", "restore: BGM volume", "r_bvol  <= ss_in_a[55:48];", "r_bvol  <= r_bvol;"),
    ("rtl", "restore: album", "r_album <= ss_in_a[63:56];", "r_album <= r_album;"),
    ("rtl", "restore: loop option", "r_loop  <= ss_in_a[39];", "r_loop  <= r_loop;"),
    ("rtl", "restore: the BGM's loop flag", "v_loop[0] <= ss_in_a[39];", "v_loop[0] <= 1'b0;"),
    ("rtl", "restore never requested", "if (rs_s[2] != rs_s[1]) rs_req <= 1;", "if (1'b0) rs_req <= 1;"),
    ("rtl", "restore taken at the load's start", "if (ld_old & ~ss_load) rs_tog", "if (~ld_old & ss_load) rs_tog"),
    ("rtl", "restore entry bound < -> <=", "{1'b0, rs_idx} < n_ent", "{1'b0, rs_idx} <= n_ent"),
    ("rtl", "a load before the pack applies to it", "rs_req <= 0;                          // a load before",
     "rs_req <= rs_req;                     // a load before"),
    ("rtl", "save: frame off by one", "v_on[0] ? v_pos[0] : 29'd0}", "v_on[0] ? v_pos[0] + 29'd1 : 29'd0}"),
    ("rtl", "save: BGM fields kept with no BGM", "v_on[0] ? v_ent[0] : 9'd0", "v_ent[0]"),
    ("rtl", "save: not held while it is read", "if (!ss_save) ss_out_a <= snap;", "ss_out_a <= snap;"),
    # ---- FPGA: the event log and status for the ARM
    ("rtl", "write event: register field lost", "lg_pay <= {53'd0, ev_head};",
     "lg_pay <= {53'd0, 3'd0, ev_head[7:0]};"),
    ("rtl", "restore event: payload lost", "lg_pay <= ss_in_a;", "lg_pay <= 64'd0;"),
    ("rtl", "restore event: unknown kind", "lg_kind <= 4'd2;", "lg_kind <= 4'd9;"),
    ("rtl", "pack reset not logged", "rst_pend <= 1; since_rst <= 0;", "rst_pend <= 0; since_rst <= 0;"),
    ("rtl", "pack reset: wrong offset", "lg_pay <= {len_f, 3'd0, off_f};", "lg_pay <= {len_f, 3'd0, off_f + 29'd8};"),
    ("rtl", "event stamped a tick late", "lg_kind, lg_flags, tcount};", "lg_kind, lg_flags, tcount + 32'd1};"),
    ("rtl", "event header: wrong index", "8'hE1, ev_idx, lg_kind", "8'hE1, ev_idx + 16'd1, lg_kind"),
    ("rtl", "status counts an event too many", "8'hA7, 8'd0, ev_idx, tcount}", "8'hA7, 8'd0, ev_idx + 16'd1, tcount}"),
    ("rtl", "status a tick ahead", "8'hA7, 8'd0, ev_idx, tcount}", "8'hA7, 8'd0, ev_idx, tcount + 32'd1}"),
    ("rtl", "status never written", "if (tcount[3:0] == 4'hF) st_due <= 1;", "if (1'b0) st_due <= 1;"),
    ("rtl", "log FIFO writes the next slot", "if (wf_we) wf[wf_wa] <= wf_wd;", "if (wf_we) wf[wf_wp[7:0]] <= wf_wd;"),
    ("rtl", "log FIFO reads an entry not yet written", "!aw_valid && wf_cp != wf_rp",
     "!aw_valid && wf_wp != wf_rp"),
    ("rtl", "write port ignores ready", "if (aw_valid && aw_ready) aw_valid <= 0;", "if (aw_valid) aw_valid <= 0;"),
    # ---- ARM: decode and volumes (hdaudio.Device)
    ("arm", "vol divisor 255 -> 256", "q = (p < 0 ? -p : p) / 255;", "q = (p < 0 ? -p : p) / 256;"),
    ("arm", "vol sign of negatives", "return p < 0 ? -q : q;", "return q;"),
    ("arm", "IMA step table entry", "494, 544, 598", "494, 545, 598"),
    ("arm", "IMA index step for nibble 7", "{-1, -1, -1, -1, 2, 4, 6, 8}", "{-1, -1, -1, -1, 2, 4, 6, 7}"),
    ("arm", "IMA index clamp 88 -> 87", "i > 88 ? 88 : i", "i > 87 ? 87 : i"),
    ("arm", "IMA right channel from the low nibble", "ima(&v->pr, &v->ir, b >> 4);", "ima(&v->pr, &v->ir, b & 15);"),
    ("arm", "loop restores state0 not statel", "unpack(e->sl, v);", "unpack(e->s0, v);"),
    ("arm", "loop restarts at frame 0", "v->pos = e->loop;", "v->pos = 0;"),
    ("arm", "pause ignored", "if (a->bgm.on && !a->paused) {", "if (a->bgm.on) {"),
    ("arm", "steal newest SFX", "memmove(&a->sfx[0], &a->sfx[1], sizeof a->sfx[0] * (AUD_SFX - 1));", ";"),
    ("arm", "SFX mixed in the BGM's place", "out[1 + i] =", "out[i] ="),
    ("arm", "SFX at the BGM volume", "(vol(r, a->svol) & 0xFFFF) << 16 | (vol(l, a->svol) & 0xFFFF)",
     "(vol(r, a->bvol) & 0xFFFF) << 16 | (vol(l, a->bvol) & 0xFFFF)"),
    ("arm", "BGM left and right swapped", "(vol(r, a->bvol) & 0xFFFF) << 16 | (vol(l, a->bvol) & 0xFFFF)",
     "(vol(l, a->bvol) & 0xFFFF) << 16 | (vol(r, a->bvol) & 0xFFFF)"),
    ("arm", "BGM end a frame late",
     "if (a->bgm.pos >= a->ent[a->bgm.e].frames && !a->bgm.loop) a->bgm.on = 0;", ""),
    ("arm", "SFX kept past its last frame", "if (v->pos < a->ent[v->e].frames) {", "if (1) {"),
    ("arm", "SFX compaction keeps the wrong voice", "if (keep != i) a->sfx[keep] = *v;", ";"),
    # ---- ARM: the stream blocks read from the pack
    ("arm", "block not refetched past its end", "off - v->blk_at >= AUD_BLK", "off - v->blk_at > AUD_BLK"),
    ("arm", "block read from the file start, not the section", "a->sec_off + at, n, v->blk",
     "at, n, v->blk"),
    ("arm", "a new voice keeps the previous stream's block", "    v->on = 1; v->e = e; v->loop = loop; v->pos = 0;\n    v->blk_at = UINT32_MAX;\n",
     "    v->on = 1; v->e = e; v->loop = loop; v->pos = 0;\n"),
    ("arm", "a restore keeps the previous stream's block",
     "        v->blk_at = UINT32_MAX;\n        v->bad = 0;\n        unpack(e->ck[k], v);",
     "        v->bad = 0;\n        unpack(e->ck[k], v);"),
    # ---- ARM: restore checkpoints and section checks
    ("arm", "builder makes no checkpoint", "uint32_t end = (e->nck - 1) * AUD_CK;", "uint32_t end = 0;"),
    ("arm", "checkpoint taken from a stream that missed a block",
     "if (v->pos % AUD_CK == 0 && !v->bad) {", "if (v->pos % AUD_CK == 0) {"),
    ("arm", "a missed block does not mark the stream", "            a->fetch_fail++;\n            v->bad = 1;\n",
     "            a->fetch_fail++;\n"),
    ("arm", "entry past the section accepted", "if (e->start > len || e->frames > len - e->start) {",
     "if (0) {"),
    ("arm", "entry table read from the wrong place", "io->fetch(io->ctx, off + 16, 32 * n, tab)",
     "io->fetch(io->ctx, off + 32, 32 * n, tab)"),
    ("arm", "album ignored", "find(a, (uint32_t)(a->album * 256 + v))", "find(a, (uint32_t)v)"),
    ("arm", "undecodable BGM starts", "if (e >= 0 && a->ent[e].frames > 0) voice_start(a, &a->bgm",
     "if (e >= 0) voice_start(a, &a->bgm"),
    ("arm", "key search misses entry 0", "if (a->ent[m].key == key) return m;",
     "if (a->ent[m].key == key && m > 0) return m;"),
    ("arm", "loop option not applied to the BGM", "if (a->bgm.on) a->bgm.loop = v & 1;", ""),
    ("arm", "stop-BGM bit", "if (v & 2) a->bgm.on = 0;", "if (v & 8) a->bgm.on = 0;"),
    # ---- ARM: restore and the log
    ("arm", "restore: ADPCM state not derived", "while (v->pos < p) decode_one(a, v);", ""),
    ("arm", "restore: frame lost", "    v->pos = pos;\n", "    v->pos = 0;\n"),
    ("arm", "restore: loop flag", "v->loop = a->options & 1; v->pos = k * AUD_CK;",
     "v->loop = 0; v->pos = k * AUD_CK;"),
    ("arm", "restore keeps a BGM the save had not", "    } else {\n        a->bgm.on = 0;\n    }\n}",
     "    }\n}"),
    ("arm", "restore: BGM volume", "a->bvol = (w >> 48) & 0xFF;", "a->bvol = a->bvol;"),
    ("arm", "write event register field", "aud_write(a, (int)(ev->payload >> 8) & 7,",
     "aud_write(a, (int)(ev->payload >> 8) & 3,"),
    ("arm", "event applied a tick late", "(int32_t)(a->q[qi].tick - a->next_t) <= 0",
     "(int32_t)(a->q[qi].tick - a->next_t) < 0"),
    ("arm", "slot tag of the next tick", "0xD5ull << 56 | a->next_t);", "0xD5ull << 56 | (a->next_t + 1));"),
    ("arm", "renders past unread events", "if (a->ev_next != E) limit = a->nq ? a->q[a->nq - 1].tick : a->next_t;", ""),
    ("arm", "a full queue of one tick never drains",
     "        if ((int32_t)(limit - a->next_t) <= 0) break;\n",
     "        if ((int32_t)(limit - a->next_t) <= 0 || (int32_t)(a->q[qi < a->nq ? qi : 0].tick - a->next_t) < 0) break;\n"),
    # the section's restore-checkpoint table (2026-10-29)
    ("arm", "pack checkpoint table never taken", "    load_checkpoints(a, io, le32(h + 12));\n", ""),
    ("arm", "table spacing not checked", "if (spacing != AUD_CK || count != want ||",
     "if (count != want ||"),
    ("arm", "table count not checked", "if (spacing != AUD_CK || count != want ||",
     "if (spacing != AUD_CK ||"),
    ("arm", "table first state not checked",
     "        if (le64(t + 8 * at) != a->ent[i].s0) { free(t); return; }\n", ""),
    ("arm", "table index not checked",
     "if (((s >> 16) & 0xFFFF) > 88 || ((s >> 48) & 0xFFFF) > 88) { free(t); return; }",
     "(void)s;"),
    ("arm", "taken table still left to the builder",
     "    a->ckb_e = a->n_ent;                 /* nothing left for the builder */\n", ""),
    ("arm", "first tick skipped at start", "a->next_t = (uint32_t)h;\n                a->ev_next = 0;",
     "a->next_t = T;\n                a->ev_next = 0;"),
    ("arm", "event header index not checked", "|| (uint16_t)(h >> 40) != a->ev_next) break;", ") break;"),
    ("arm", "header not read again after its payload", "        if (io->rd(io->ctx, q) != h) break;\n", ""),
    ("arm", "status read once (torn read taken)", "for (int i = 0; i < 4; i++) {", "for (int i = 0; i < 0; i++) {"),
    ("arm", "late start taken for a fresh one (E wrapped)",
     "if (((h >> 36) & 0xF) == 3 && (uint32_t)(T - (uint32_t)h) < AUD_NSLOT / 2) {", "if (1) {"),
    ("arm", "late start does not load the section", "            late_load(a, io);\n", ""),
    ("arm", "a late start ignores the state events", "a->want_sync = 1;\n", ""),
    ("arm", "event flags not read", "ev->flags = (h >> 32) & 0xF;", "ev->flags = 0;"),
    ("arm", "stall caught up in one pass",
     "    if ((int32_t)(limit - a->next_t) > (int32_t)AUD_NSLOT) limit = a->next_t + AUD_NSLOT;\n", ""),
    ("arm", "a forward jump of the tick count is not a new session",
     "((uint32_t)(T - a->last_T) > 0x40000000u ||", "((int32_t)(T - a->last_T) < 0 ||"),
]

RUNS = [
    ["--seed", "1", "--need-hi"],
    ["--seed", "1", "--alt"],
    ["--seed", "2", "--random", "--frames", "3000"],
    ["--seed", "5", "--random", "--pal", "--frames", "2000"],
    ["--seed", "6", "--busy"],
    ["--seed", "9", "--random", "--frames", "600", "--arm", "0"],
    ["--seed", "3", "--off", "0x2028"],
    ["--seed", "3", "--pcm-late", "--frames", "3000"],
    ["--seed", "3", "--flood", "--frames", "600"],
    ["--seed", "1", "--frames", "300", "--reset-mid"],
    ["--seed", "1", "--frames", "3500", "--arm-late", "playing"],
    ["--seed", "1", "--frames", "3500", "--arm-late", "paused"],
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="lo", type=int, default=1)
    ap.add_argument("--to", dest="hi", type=int, default=len(M))
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    if a.list:
        for i, m in enumerate(M, 1):
            print("%2d %-3s %s" % (i, m[0], m[1]))
        return 0
    src = {k: open(p, encoding="utf-8").read() for k, p in FILES.items()}
    work = tempfile.mkdtemp(prefix="neg_audio_")
    missed, broken = [], []
    for i in range(a.lo, a.hi + 1):
        which, name, old, new = M[i - 1]
        n = src[which].count(old)
        if n != 1:
            print("%2d %-3s %-44s ANCHOR MATCHES %d (broken control)" % (i, which, name, n))
            broken.append(i)
            continue
        f = os.path.join(work, "m%d.%s" % (i, "sv" if which == "rtl" else "c"))
        with open(f, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(src[which].replace(old, new))
        env = dict(os.environ, OBJ=work.replace("\\", "/"), EXE="m%d" % i, AUD_QN="2")
        env["AUDIO_RTL" if which == "rtl" else "AUD_ARM"] = f.replace("\\", "/")
        b = subprocess.run(["sh", os.path.join(ROOT, "tools", "sim3", "build_audio.sh"), WIN],
                           env=env, capture_output=True, text=True)
        exe = os.path.join(work, "m%d.exe" % i)
        if b.returncode or not os.path.isfile(exe):
            # a mutation that no longer compiles is caught by the build itself, but it proves
            # nothing about the tests - report it as broken so it gets rewritten
            print("%2d %-3s %-44s BUILD FAILED" % (i, which, name))
            print(b.stdout[-800:] + b.stderr[-800:])
            broken.append(i)
            continue
        caught = None
        if which == "arm":
            # the unit checks (tools/armdec/test_aud_arm.c: a second pack load, an SFX ending
            # under a full voice list) on the mutated file first
            ux = os.path.join(work, "u%d.exe" % i)
            u = subprocess.run(["C:/msys64/mingw64/bin/gcc.exe", "-O2", "-std=gnu11", "-I", os.path.join(ROOT, "tools", "armdec"),
                                os.path.join(ROOT, "tools", "armdec", "test_aud_arm.c"), f, "-o", ux],
                               capture_output=True, text=True, env=GCC_ENV)
            if u.returncode:
                caught = "unit test build failed"
            else:
                p = subprocess.run([ux], capture_output=True, text=True, env=GCC_ENV)
                if p.returncode:
                    fl = [l for l in p.stdout.splitlines() if l.startswith("FAIL")]
                    caught = "test_aud_arm: " + (fl[0] if fl else "rc %d" % p.returncode)[:80]
        for r in ([] if caught else RUNS):
            try:
                p = subprocess.run([sys.executable, "-I", os.path.join(HERE, "tb_audio_run.py"),
                                    "--exe", exe] + r, capture_output=True, text=True, timeout=600)
                rc, last = p.returncode, (p.stdout.strip().splitlines() or ["?"])[-1][:90]
            except subprocess.TimeoutExpired:
                rc, last = 1, "TIMEOUT (a hang counts as caught)"
            if rc:
                caught = " ".join(r) + ": " + last
                break
        print("%2d %-3s %-44s %s" % (i, which, name, "CAUGHT  " + caught if caught else "MISSED"))
        if not caught:
            missed.append(i)
        sys.stdout.flush()
    shutil.rmtree(work, ignore_errors=True)
    print("missed: %s  broken: %s" % (missed or "none", broken or "none"))
    return 1 if missed or broken else 0


sys.exit(main())
