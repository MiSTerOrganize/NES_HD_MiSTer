// Simulation wrapper: hd_engine + hd_ddr, DDR3 modelled in C++ (tools/sim/tb.cpp).
module hd_tb_top
(
	input          clk,
	input  [319:0] tap,

	input          load_active,
	input          load_wr,
	input   [24:0] load_addr,
	input    [7:0] load_data,
	output         load_wait,

	input          DDRAM_BUSY,
	output   [7:0] DDRAM_BURSTCNT,
	output  [28:0] DDRAM_ADDR,
	input   [63:0] DDRAM_DOUT,
	input          DDRAM_DOUT_READY,
	output         DDRAM_RD,
	output  [63:0] DDRAM_DIN,
	output   [7:0] DDRAM_BE,
	output         DDRAM_WE,

	output         active,
	output   [7:0] R, G, B,
	output         HS, VS, HB, VB
);

wire        rd_req, rd_ack, rd_valid, wr_req, wr_ack;
wire [27:3] rd_addr, wr_addr;
wire [63:0] rd_data, wr_data;

hd_engine eng
(
	.clk(clk), .reset(1'b0), .enable(1'b1), .tap(tap),
	.load_active(load_active), .load_wr(load_wr), .load_addr(load_addr),
	.load_data(load_data), .load_wait(load_wait),
	.rd_req(rd_req), .rd_addr(rd_addr), .rd_ack(rd_ack), .rd_data(rd_data), .rd_valid(rd_valid),
	.wr_req(wr_req), .wr_addr(wr_addr), .wr_data(wr_data), .wr_ack(wr_ack),
	.active(active), .R(R), .G(G), .B(B), .HS(HS), .VS(VS), .HB(HB), .VB(VB)
);

wire [63:0] ss_dout;
wire        ss_ready;

hd_ddr ddr
(
	.DDRAM_CLK(clk), .DDRAM_BUSY(DDRAM_BUSY), .DDRAM_BURSTCNT(DDRAM_BURSTCNT),
	.DDRAM_ADDR(DDRAM_ADDR), .DDRAM_DOUT(DDRAM_DOUT), .DDRAM_DOUT_READY(DDRAM_DOUT_READY),
	.DDRAM_RD(DDRAM_RD), .DDRAM_DIN(DDRAM_DIN), .DDRAM_BE(DDRAM_BE), .DDRAM_WE(DDRAM_WE),
	.ch1_addr(27'd0), .ch1_dout(ss_dout), .ch1_din(64'd0), .ch1_req(1'b0), .ch1_rnw(1'b1),
	.ch1_be(8'hFF), .ch1_ready(ss_ready),
	.rd_req(rd_req), .rd_addr(rd_addr), .rd_ack(rd_ack), .rd_data(rd_data), .rd_valid(rd_valid),
	.wr_req(wr_req), .wr_addr(wr_addr), .wr_data(wr_data), .wr_ack(wr_ack)
);

endmodule
