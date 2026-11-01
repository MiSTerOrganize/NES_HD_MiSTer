// hd3_cache_tb.sv - unit-test wrapper for hd3_rcache and hd3_ccache (tb_cache.cpp drives it).
// Both caches are built small (LB) so a random address stream forces set conflicts.
module hd3_cache_tb #(
	parameter LB = 2
)
(
	input             clk,
	input             reset,
	input             flush,

	// rcache
	input             r_req,
	input             r_byp,
	input      [27:3] r_addr,
	output            r_ack,
	output     [63:0] r_q,
	output            r_rd_req,
	output     [27:3] r_rd_addr,
	input             r_rd_ack,
	input      [63:0] r_rd_data,
	input             r_rd_valid,

	// ccache
	input      [27:3] c_base,
	input             c_req,
	input      [23:0] c_ci,
	output            c_ack,
	output    [255:0] c_q,
	output            c_rd_req,
	output     [27:3] c_rd_addr,
	input             c_rd_ack,
	input      [63:0] c_rd_data,
	input             c_rd_valid
);

hd3_rcache #(.LB(LB)) rc (
	.clk(clk), .reset(reset), .flush(flush),
	.req(r_req), .byp(r_byp), .addr(r_addr), .ack(r_ack), .q(r_q),
	.rd_req(r_rd_req), .rd_addr(r_rd_addr), .rd_ack(r_rd_ack), .rd_data(r_rd_data),
	.rd_valid(r_rd_valid)
);

hd3_ccache #(.LB(LB)) cc (
	.clk(clk), .reset(reset), .flush(flush), .base(c_base),
	.req(c_req), .ci(c_ci), .ack(c_ack), .q(c_q),
	.rd_req(c_rd_req), .rd_addr(c_rd_addr), .rd_ack(c_rd_ack), .rd_data(c_rd_data),
	.rd_valid(c_rd_valid)
);

endmodule
