// Testbench top: hd_capture with a real hd_chrfp behind its fingerprint port.
module hd_capture_tb_top
(
	input          clk,
	input          reset,
	input          enable,
	input          chr_ram,

	input          chr_wr,
	input   [14:0] chr_addr,
	input    [7:0] chr_data,
	output         chr_idle,

	input          bg_we,
	input    [5:0] bg_slot,
	input   [21:0] bg_lin,
	input    [1:0] bg_pal,
	input          spr_we,
	input    [5:0] spr_idx,
	input   [54:0] spr_data,
	input          px_we,
	input    [7:0] px_x,
	input    [5:0] px_slot,
	input    [2:0] px_fx,
	input    [3:0] px_bgc,
	input          px_bg_on,
	input          px_spr_on,
	input          px_branch_b,
	input   [14:0] px_t,
	input    [2:0] px_finex,
	input          px_gray,
	input    [2:0] px_emph,
	input  [191:0] pal_all,
	input          line_done,
	input    [8:0] line_y,
	input          line_pre,

	output         wq_valid,
	output  [27:3] wq_addr,
	output  [63:0] wq_data,
	output   [7:0] wq_be,
	input          wq_ready,

	output         frame_done,
	output  [31:0] frame_num,
	output         overflow
);

wire [10:0] fp_tile;
wire [63:0] fp_q;

hd_chrfp #(.AW(15)) u_fp
(
	.clk(clk), .reset(reset),
	.wr(chr_wr), .wr_addr(chr_addr), .wr_data(chr_data),
	.fp_tile(fp_tile), .fp_q(fp_q), .idle(chr_idle)
);

hd_capture #(.FP_AW(15)) cap
(
	.clk(clk), .reset(reset), .enable(enable), .chr_ram(chr_ram),
	.bg_we(bg_we), .bg_slot(bg_slot), .bg_lin(bg_lin), .bg_pal(bg_pal),
	.spr_we(spr_we), .spr_idx(spr_idx), .spr_data(spr_data),
	.px_we(px_we), .px_x(px_x), .px_slot(px_slot), .px_fx(px_fx), .px_bgc(px_bgc),
	.px_bg_on(px_bg_on), .px_spr_on(px_spr_on), .px_branch_b(px_branch_b),
	.px_t(px_t), .px_finex(px_finex), .px_gray(px_gray), .px_emph(px_emph),
	.pal_all(pal_all),
	.line_done(line_done), .line_y(line_y), .line_pre(line_pre),
	.fp_tile(fp_tile), .fp_q(fp_q),
	.wq_valid(wq_valid), .wq_addr(wq_addr), .wq_data(wq_data), .wq_be(wq_be),
	.wq_ready(wq_ready),
	.frame_done(frame_done), .frame_num(frame_num), .overflow(overflow)
);

endmodule
