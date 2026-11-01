// Testbench top for rtl/hdpack/hd3_add.sv: hd3_dict and hd3_add wired as stage 3 wires them,
// so ADD reads the record ids and addition lists hd3_dict really built. Each block keeps its
// own DDR3 read port here (tb_add.cpp serves both); the stage-3 arbiter is integration work.
// hd3_dict's r_* ports belong to ADD while it is busy and to the testbench otherwise.
module hd3_add_tb #(parameter RAW = 11, parameter NL = 16, parameter NB = 64)
(
	input             clk,
	input             reset,
	input             game_ram,
	input             legacy,
	input      [27:3] keys_base,
	input      [27:3] rules_base,
	input      [31:0] bucket_mask,
	input      [15:0] max_probe,
	input      [27:3] fb_base,
	input      [31:0] fb_len,
	input             add_en,
	input      [27:3] akeys_base,
	input      [31:0] abucket_mask,
	input      [15:0] amax_probe,
	input      [27:3] alists_base,

	input             tap_v,
	input      [27:3] tap_a,
	input      [63:0] tap_d,
	output            frame_done,
	output            done_bank,
	output            dict_overflow,
	output      [1:0] dict_fovf,

	output            d_rd_req,
	output     [27:3] d_rd_addr,
	input             d_rd_ack,
	input      [63:0] d_rd_data,
	input             d_rd_valid,

	output            a_rd_req,
	output     [27:3] a_rd_addr,
	input             a_rd_ack,
	input      [63:0] a_rd_data,
	input             a_rd_valid,

	input             start,
	input             t_abort,
	input             bank,
	output            busy,
	output            done,
	output            ovf,

	// testbench reads: a record's key (only while ADD is idle) and a line's lanes
	input             t_bank,
	input   [RAW-1:0] t_rid,
	output     [95:0] t_key,
	input       [7:0] rl_y,
	output      [6:0] rl_n,
	output [NL*(RAW+21)-1:0] rl_q
);

wire     [7:0] ad_y;
wire     [5:0] ad_slot;
wire     [3:0] ad_fetch;
wire   [RAW:0] r_span, r_spr, r_nrec;
wire [RAW-1:0] ad_rid, ad_arid;
wire     [9:0] ad_pi;
wire    [16:0] a_m;
wire [47+RAW:0] a_pe;
wire    [63:0] res_unused;
wire    [31:0] frame_unused;

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
	.r_bank(busy ? bank : t_bank), .r_rid(busy ? ad_rid : t_rid),
	.r_key(t_key), .r_res(res_unused),
	.r_y(ad_y), .r_slot(ad_slot), .r_span(r_span), .r_fetch(ad_fetch), .r_spr(r_spr),
	.r_nrec(r_nrec), .r_frame(frame_unused),
	.a_bank(bank), .a_rid(ad_arid), .a_m(a_m), .a_pi(ad_pi), .a_pe(a_pe),
	.frame_done(frame_done), .done_bank(done_bank), .overflow(dict_overflow),
	.frame_ovf(dict_fovf)
);

hd3_add #(.RAW(RAW), .NL(NL), .NB(NB)) add (
	.clk(clk), .reset(reset),
	.start(start), .bank(bank), .add_en(add_en), .abort(t_abort), .busy(busy), .done(done), .ovf(ovf),
	.r_y(ad_y), .r_slot(ad_slot), .r_span(r_span), .r_fetch(ad_fetch), .r_spr(r_spr),
	.r_rid(ad_rid), .r_key(t_key), .r_nrec(r_nrec),
	.a_rid(ad_arid), .a_m(a_m), .a_pi(ad_pi), .a_pe(a_pe),
	.rd_req(a_rd_req), .rd_addr(a_rd_addr), .rd_ack(a_rd_ack), .rd_data(a_rd_data),
	.rd_valid(a_rd_valid),
	.rl_y(rl_y), .rl_n(rl_n), .rl_q(rl_q)
);

endmodule
