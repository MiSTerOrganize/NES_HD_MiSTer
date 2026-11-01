// Testbench top for rtl/hdpack/hd3_resolve.sv: hd3_dict and hd3_resolve wired as stage 3
// wires them, so RESOLVE reads the dictionary hd3_dict really built. Each block keeps its own
// DDR3 read port here (tb_resolve.cpp serves both); the stage-3 arbiter is integration work.
// hd3_dict's read port belongs to RESOLVE while it is busy and to the testbench otherwise.
module hd3_resolve_tb #(parameter RAW = 11, parameter RSW = 10, parameter RS_MAX = 1024)
(
	input             clk,
	input             reset,
	input             game_ram,
	input             legacy,
	input      [27:3] keys_base,
	input      [27:3] rules_base,
	input      [27:3] conds_base,
	input      [27:3] clist_base,
	input      [31:0] bucket_mask,
	input      [15:0] max_probe,
	input      [27:3] fb_base,
	input      [31:0] fb_len,
	input      [27:3] bgl_base,
	input      [27:0] bgi_base,

	input             tap_v,
	input      [27:3] tap_a,
	input      [63:0] tap_d,
	output            frame_done,
	output            done_bank,
	output            dict_overflow,

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

	input             start,
	input             bank,
	output            busy,
	output            done,
	output            overflow,
	output            bg_lin,
	output            bg_warn,

	output            v_bank,
	output      [7:0] v_idx,
	input       [7:0] v_q,

	// testbench read of hd3_dict (only while RESOLVE is idle)
	input             t_bank,
	input   [RAW-1:0] t_rid,
	output     [63:0] t_res,
	output    [RAW:0] t_nrec,

	input             r_bank,
	input   [RAW-1:0] r_rid,
	output [2+1+11+RSW+25-1:0] r_rec,
	input   [RSW-1:0] r_ri,
	output     [72:0] r_rule,
	input             g_bank,
	input       [5:0] g_lvl,
	output     [20:0] g_q,
	input             s_bank,
	input      [10:0] s_a,
	output      [1:0] s_q
);

wire         rs_dbank;
wire [RAW-1:0] rs_drid;
wire  [95:0] key_unused;
wire   [1:0] fovf_unused;
wire   [7:0] ay_unused;
wire [RAW:0] span_unused, spr_unused;
wire  [31:0] frame_no;
wire  [16:0] am_unused;
wire [47+RAW:0] ape_unused;

hd3_dict #(.RAW(RAW)) dict (
	.clk(clk), .reset(reset),
	.game_ram(game_ram), .legacy(legacy),
	.keys_base(keys_base), .rules_base(rules_base),
	.bucket_mask(bucket_mask), .max_probe(max_probe),
	.fb_base(fb_base), .fb_len(fb_len),
	.add_en(1'b0), .akeys_base(25'd0), .abucket_mask(32'd0), .amax_probe(16'd0),
	.alists_base(25'd0),                  // no additions here: tb_add tests them
	.tap_v(tap_v), .tap_a(tap_a), .tap_d(tap_d),
	.rd_req(d_rd_req), .rd_addr(d_rd_addr), .rd_ack(d_rd_ack), .rd_data(d_rd_data),
	.rd_valid(d_rd_valid),
	.r_bank(busy ? rs_dbank : t_bank), .r_rid(busy ? rs_drid : t_rid),
	.r_key(key_unused), .r_res(t_res),
	.r_y(8'd0), .r_slot(6'd0), .r_span(span_unused), .r_fetch(4'd0), .r_spr(spr_unused),
	.r_nrec(t_nrec), .r_frame(frame_no),
	.a_bank(1'b0), .a_rid({RAW{1'b0}}), .a_m(am_unused), .a_pi(10'd0), .a_pe(ape_unused),
	.frame_done(frame_done), .done_bank(done_bank), .overflow(dict_overflow),
	.frame_ovf(fovf_unused)
);

hd3_resolve #(.RAW(RAW), .RSW(RSW), .RS_MAX(RS_MAX)) resolve (
	.clk(clk), .reset(reset),
	.game_ram(game_ram), .legacy(legacy),
	.rules_base(rules_base), .conds_base(conds_base), .clist_base(clist_base),
	.fb_base(fb_base), .fb_len(fb_len),
	.bgl_base(bgl_base), .bgi_base(bgi_base),
	.add_en(1'b0),                        // filtered as captured: tb_render tests additions
	.start(start), .bank(bank), .busy(busy), .done(done), .overflow(overflow),
	.bg_lin(bg_lin), .bg_warn(bg_warn),
	.d_bank(rs_dbank), .d_rid(rs_drid), .d_key(key_unused), .d_res(t_res), .d_nrec(t_nrec),
	.d_frame(frame_no),
	.a_y(ay_unused), .a_n(7'd0), .a_q('0),     // no additions here (render tb covers lanes)
	.v_bank(v_bank), .v_idx(v_idx), .v_q(v_q),
	.rd_req(s_rd_req), .rd_addr(s_rd_addr), .rd_ack(s_rd_ack), .rd_data(s_rd_data),
	.rd_valid(s_rd_valid),
	.r_bank(r_bank), .r_rid(r_rid), .r_rec(r_rec), .r_ri(r_ri), .r_rule(r_rule),
	.g_bank(g_bank), .g_lvl(g_lvl), .g_q(g_q), .s_bank(s_bank), .s_a(s_a), .s_q(s_q)
);

endmodule
