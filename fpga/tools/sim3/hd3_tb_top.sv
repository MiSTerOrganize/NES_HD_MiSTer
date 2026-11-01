// Testbench top for hd3_lookup: the C++ side drives the request and models DDR3.
module hd3_tb_top
(
	input             clk,
	input             reset,
	input      [27:3] keys_base,
	input      [27:3] rules_base,
	input      [31:0] bucket_mask,
	input      [15:0] max_probe,

	input             req,
	input             key_only,
	input      [31:0] q_pal,
	input             q_kind,
	input      [31:0] q_lo,
	input      [31:0] q_hi,

	output            done,
	output            found,
	output     [31:0] list_off,
	output     [31:0] list_count,
	output            pick_valid,
	output     [31:0] pick_payload,
	output     [31:0] pick_index,
	output      [3:0] probes,

	output            rd_req,
	output     [27:3] rd_addr,
	input             rd_ack,
	input      [63:0] rd_data,
	input             rd_valid
);

hd3_lookup lk (.*);

endmodule
