// Testbench top for rtl/hdpack/hd3_render.sv: hd3_dict, hd3_add, hd3_resolve, hd3_fmap and
// hd3_render wired as stage 3 wires them, so RENDER draws from the dictionary hd3_dict built,
// the lanes hd3_add built (8a) and the rule lists hd3_resolve filtered. Each block has its own
// DDR3 read port here (tb_render.cpp serves all seven); the stage-3 arbiter is integration
// work. hd3_fmap snoops the record write stream (tap_*, with byte enables) as hd3_dict does;
// RENDER reads the maps of its own frame's bank.
// hd3_dict's read port belongs to ADD while it is busy, then to RESOLVE while it is busy, and
// to RENDER otherwise; hd3_add's lane reader to RESOLVE while it is busy and RENDER otherwise
// (the testbench runs them one after the other; integration must share the ports while
// ADD/RESOLVE prepare frame N+1 and RENDER draws frame N).
// A frame whose lanes are incomplete (hd3_add ovf) is drawn like a dictionary-overflowed one:
// without lookups.
module hd3_render_tb #(parameter RAW = 11, parameter RSW = 10, parameter RS_MAX = 1024,
                       parameter integer NSLOT = 127, parameter integer OF_LOG2 = 3,
                       parameter integer PROFILE = 0,
                       parameter integer PLINE = -1,
                       parameter integer NL = 16, parameter integer NB = 64)
(
	input             clk,
	input             reset,
	input             game_ram,
	input             legacy,
	input             cache_en,
	input             render_orig,
	input             has_pal,
	input       [7:0] ov_top,
	input       [7:0] ov_bottom,
	input       [7:0] ov_left,
	input       [7:0] ov_right,
	input      [27:3] keys_base,
	input      [27:3] rules_base,
	input      [27:3] conds_base,
	input      [27:3] clist_base,
	input      [27:3] blocks_base,
	input      [27:3] pal_base,
	input      [31:0] bucket_mask,
	input      [15:0] max_probe,
	input      [27:3] fb_base,
	input      [31:0] fb_len,
	input      [27:3] bgl_base,
	input      [27:0] bgi_base,
	input      [27:3] bgrec_base,
	input      [27:0] bgmap_base,
	input      [27:0] ratio_base,
	input             add_en,
	input      [27:3] akeys_base,
	input      [31:0] abucket_mask,
	input      [15:0] amax_probe,
	input      [27:3] alists_base,

	input             tap_v,
	input      [27:3] tap_a,
	input      [63:0] tap_d,
	input       [7:0] tap_be,
	output            frame_done,
	output            done_bank,
	output            dict_overflow,
	output      [1:0] dict_fovf,

	output            d_rd_req,
	output     [27:3] d_rd_addr,
	input             d_rd_ack,
	input      [63:0] d_rd_data,
	input             d_rd_valid,
	output            s_rd_req,
	output     [27:3] s_rd_addr,
	input             s_rd_ack,
	input      [63:0] s_rd_data,
	input             s_rd_valid,
	output            l_rd_req,
	output     [27:3] l_rd_addr,
	input             l_rd_ack,
	input      [63:0] l_rd_data,
	input             l_rd_valid,
	output            c_rd_req,
	output     [27:3] c_rd_addr,
	input             c_rd_ack,
	input      [63:0] c_rd_data,
	input             c_rd_valid,
	output            e_rd_req,
	output     [27:3] e_rd_addr,
	input             e_rd_ack,
	input      [63:0] e_rd_data,
	input             e_rd_valid,
	output            b_rd_req,
	output     [27:3] b_rd_addr,
	input             b_rd_ack,
	input      [63:0] b_rd_data,
	input             b_rd_valid,
	output            a_rd_req,
	output     [27:3] a_rd_addr,
	input             a_rd_ack,
	input      [63:0] a_rd_data,
	input             a_rd_valid,

	input             ad_start,
	input             ad_bank,
	input             ad_abort,
	output            ad_busy,
	output            ad_done,
	output            ad_ovf,

	input             rs_start,
	input             rs_bank,
	output            rs_busy,
	output            rs_done,
	output            rs_overflow,
	output      [7:0] rs_v_idx,
	input       [7:0] rs_v_q,

	input             start,
	input             bank,
	output            busy,
	output            done,
	output            unsup,
	output      [7:0] v_idx,
	input       [7:0] v_q,

	output            out_v,
	output      [7:0] out_y,
	output      [7:0] out_x,
	output     [95:0] out_px
);

wire           rs_dbank, rn_dbank;
wire [RAW-1:0] rs_drid, rn_drid;
wire    [95:0] r_key;
wire    [63:0] r_res;
wire     [7:0] rn_y;
wire     [5:0] rn_slot;
wire     [3:0] rn_fetch;
wire   [RAW:0] r_span, r_spr, r_nrec;
wire    [31:0] r_frame;
wire           rs_vbank;
wire     [7:0] ad_y;
wire     [5:0] ad_slot;
wire     [3:0] ad_fetch;
wire [RAW-1:0] ad_rid, ad_arid;
wire     [9:0] ad_pi;
wire    [16:0] a_m;
wire [47+RAW:0] a_pe;
wire     [7:0] rs_ay, rn_ay;
wire     [6:0] rl_n;
wire [NL*(RAW+21)-1:0] rl_q;

hd3_dict #(.RAW(RAW)) dict (
	.clk(clk), .reset(reset),
	.game_ram(game_ram), .legacy(legacy),
	.keys_base(keys_base), .rules_base(rules_base),
	.bucket_mask(bucket_mask), .max_probe(max_probe),
	.fb_base(fb_base), .fb_len(fb_len),
	.add_en(add_en), .akeys_base(akeys_base), .abucket_mask(abucket_mask),
	.amax_probe(amax_probe), .alists_base(alists_base),
	.tap_v(tap_v), .tap_a(tap_a), .tap_d(tap_d),
	.rd_req(d_rd_req), .rd_addr(d_rd_addr), .rd_ack(d_rd_ack), .rd_data(d_rd_data),
	.rd_valid(d_rd_valid),
	.r_bank(ad_busy ? ad_bank : rs_busy ? rs_dbank : rn_dbank),
	.r_rid(ad_busy ? ad_rid : rs_busy ? rs_drid : rn_drid),
	.r_key(r_key), .r_res(r_res),
	.r_y(ad_busy ? ad_y : rn_y), .r_slot(ad_busy ? ad_slot : rn_slot), .r_span(r_span),
	.r_fetch(ad_busy ? ad_fetch : rn_fetch), .r_spr(r_spr),
	.r_nrec(r_nrec), .r_frame(r_frame),
	.a_bank(ad_bank), .a_rid(ad_arid), .a_m(a_m), .a_pi(ad_pi), .a_pe(a_pe),
	.frame_done(frame_done), .done_bank(done_bank), .overflow(dict_overflow),
	.frame_ovf(dict_fovf)
);

hd3_add #(.RAW(RAW), .NL(NL), .NB(NB)) add (
	.clk(clk), .reset(reset),
	.start(ad_start), .bank(ad_bank), .add_en(add_en), .abort(ad_abort), .busy(ad_busy),
	.done(ad_done), .ovf(ad_ovf),
	.r_y(ad_y), .r_slot(ad_slot), .r_span(r_span), .r_fetch(ad_fetch), .r_spr(r_spr),
	.r_rid(ad_rid), .r_key(r_key), .r_nrec(r_nrec),
	.a_rid(ad_arid), .a_m(a_m), .a_pi(ad_pi), .a_pe(a_pe),
	.rd_req(a_rd_req), .rd_addr(a_rd_addr), .rd_ack(a_rd_ack), .rd_data(a_rd_data),
	.rd_valid(a_rd_valid),
	.rl_y(rs_busy ? rs_ay : rn_ay), .rl_n(rl_n), .rl_q(rl_q)
);

// the lanes are incomplete for this bank: draw it without lookups
reg [1:0] add_ovf = 0;
always @(posedge clk) if (ad_done) add_ovf[ad_bank] <= ad_ovf;

wire [RAW-1:0] q_rid;
wire [2+1+11+RSW+25-1:0] q_rec;
wire [RSW-1:0] q_ri;
wire    [72:0] q_rule;
wire           gs_bank, sd_bank;          // backgrounds: resolve's selection and memo seed,
wire     [5:0] gs_lvl;                    //   read by render for its own frame's bank
wire    [20:0] gs_q;
wire    [10:0] sd_a;
wire     [1:0] sd_q;
wire           rs_bglin, rs_bgwarn;

hd3_resolve #(.RAW(RAW), .RSW(RSW), .RS_MAX(RS_MAX), .NL(NL)) resolve (
	.clk(clk), .reset(reset),
	.game_ram(game_ram), .legacy(legacy), .add_en(add_en), .d_key(r_key),
	.a_y(rs_ay), .a_n(rl_n), .a_q(rl_q),
	.rules_base(rules_base), .conds_base(conds_base), .clist_base(clist_base),
	.fb_base(fb_base), .fb_len(fb_len),
	.bgl_base(bgl_base), .bgi_base(bgi_base),
	.start(rs_start), .bank(rs_bank), .busy(rs_busy), .done(rs_done), .overflow(rs_overflow),
	.bg_lin(rs_bglin), .bg_warn(rs_bgwarn),
	.d_bank(rs_dbank), .d_rid(rs_drid), .d_res(r_res), .d_nrec(r_nrec), .d_frame(r_frame),
	.v_bank(rs_vbank), .v_idx(rs_v_idx), .v_q(rs_v_q),
	.rd_req(s_rd_req), .rd_addr(s_rd_addr), .rd_ack(s_rd_ack), .rd_data(s_rd_data),
	.rd_valid(s_rd_valid),
	.r_bank(rn_dbank), .r_rid(q_rid), .r_rec(q_rec), .r_ri(q_ri), .r_rule(q_rule),
	.g_bank(gs_bank), .g_lvl(gs_lvl), .g_q(gs_q), .s_bank(sd_bank), .s_a(sd_a), .s_q(sd_q)
);

wire  [14:0] p_a;
wire  [13:0] p_q;
wire   [7:0] l_y, s_y;
wire  [10:0] l_q;
wire [415:0] s_q;

hd3_fmap fmap (
	.clk(clk),
	.tap_v(tap_v), .tap_a(tap_a), .tap_d(tap_d), .tap_be(tap_be),
	.r_bank(rn_dbank),
	.p_a(p_a), .p_q(p_q), .l_y(l_y), .l_q(l_q), .s_y(s_y), .s_q(s_q)
);

hd3_render #(.RAW(RAW), .RSW(RSW), .NSLOT(NSLOT), .OF_LOG2(OF_LOG2), .PROFILE(PROFILE),
            .PLINE(PLINE), .NL(NL)) render (
	.clk(clk), .reset(reset),
	.game_ram(game_ram), .cache_en(cache_en), .render_orig(render_orig), .has_pal(has_pal),
	.ov_top(ov_top), .ov_bottom(ov_bottom), .ov_left(ov_left), .ov_right(ov_right),
	.rules_base(rules_base), .conds_base(conds_base), .clist_base(clist_base),
	.blocks_base(blocks_base), .pal_base(pal_base),
	.bgrec_base(bgrec_base), .bgmap_base(bgmap_base), .ratio_base(ratio_base),
	.add_en(add_en), .flush(reset),
	.start(start), .bank(bank), .frame_ovf(dict_fovf[bank] || add_ovf[bank]), .busy(busy),
	.done(done),
	.unsup(unsup),
	.d_bank(rn_dbank), .d_rid(rn_drid), .d_key(r_key), .d_res(r_res),
	.d_y(rn_y), .d_slot(rn_slot), .d_span(r_span), .d_fetch(rn_fetch), .d_spr(r_spr),
	.d_frame(r_frame),
	.q_rid(q_rid), .q_rec(q_rec), .q_ri(q_ri), .q_rule(q_rule),
	.gs_bank(gs_bank), .gs_lvl(gs_lvl), .gs_q(gs_q), .sd_bank(sd_bank), .sd_a(sd_a), .sd_q(sd_q),
	.p_a(p_a), .p_q(p_q), .l_y(l_y), .l_q(l_q), .s_y(s_y), .s_q(s_q),
	.v_idx(v_idx), .v_q(v_q),
	.a_y(rn_ay), .a_n(rl_n), .a_q(rl_q),
	.l_rd_req(l_rd_req), .l_rd_addr(l_rd_addr), .l_rd_ack(l_rd_ack), .l_rd_data(l_rd_data),
	.l_rd_valid(l_rd_valid),
	.c_rd_req(c_rd_req), .c_rd_addr(c_rd_addr), .c_rd_ack(c_rd_ack), .c_rd_data(c_rd_data),
	.c_rd_valid(c_rd_valid),
	.e_rd_req(e_rd_req), .e_rd_addr(e_rd_addr), .e_rd_ack(e_rd_ack), .e_rd_data(e_rd_data),
	.e_rd_valid(e_rd_valid),
	.b_rd_req(b_rd_req), .b_rd_addr(b_rd_addr), .b_rd_ack(b_rd_ack), .b_rd_data(b_rd_data),
	.b_rd_valid(b_rd_valid),
	.out_v(out_v), .out_y(out_y), .out_x(out_x), .out_px(out_px),
	// display pacing belongs to the engine (tb_engine checks it); unpaced here
	.line_ok(1'b1), .line_y()
);

endmodule
