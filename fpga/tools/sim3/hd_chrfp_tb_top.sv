// Testbench top for hd_chrfp (32 KB of CHR RAM, 2048 tiles).
module hd_chrfp_tb_top
(
	input         clk,
	input         reset,
	input         wr,
	input  [14:0] wr_addr,
	input   [7:0] wr_data,
	input  [10:0] fp_tile,
	output [63:0] fp_q,
	output        idle
);

hd_chrfp #(.AW(15)) u (.*);

endmodule
