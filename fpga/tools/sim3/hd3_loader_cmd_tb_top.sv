// Testbench top for hd3_loader (the command-driven loader of hd3_pengine). MAXB / MAXT are its
// MAX_BYTES / MAX_TOTAL; POLL_W is small so the command is read every 16 clocks.
module hd3_loader_cmd_tb_top #(
	parameter [31:0] MAXB = 32'h0C000000,
	parameter [31:0] MAXT = 32'h18000000
)
(
	output     [31:0] max_bytes,
	output     [31:0] max_total,
	input             clk,
	input             reset,
	output            m_req,
	output     [27:3] m_addr,
	input      [63:0] m_dout,
	input             m_ready,
	output            pack_ok,
	output      [3:0] reject,
	output      [7:0] ack_seq,
	output            st_t,
	output      [7:0] scale,
	output      [7:0] flags,
	output     [31:0] options,
	output     [31:0] bucket_mask,
	output     [15:0] max_probe,
	output     [27:3] keys_base,
	output     [27:3] rules_base,
	output     [31:0] hdr_word0x2c,
	output     [31:0] hdr_word0x30,
	output     [31:0] hdr_word0x34,
	input             cart_no_chr_rom,
	output            game_ram,
	output            legacy,
	output     [27:3] fb_base,
	output     [31:0] fb_len,
	output            add_en,
	output     [27:3] akeys_base,
	output     [31:0] abucket_mask,
	output     [15:0] amax_probe,
	output     [27:3] alists_base,
	output      [7:0] ov_top,
	output      [7:0] ov_right,
	output      [7:0] ov_bottom,
	output      [7:0] ov_left,
	output            has_pal,
	output            cache_en,
	output            render_orig,
	output     [27:3] conds_base,
	output     [27:3] clist_base,
	output     [27:3] blocks_base,
	output     [27:3] bgl_base,
	output     [27:3] bgrec_base,
	output     [27:0] bgmap_base,
	output     [27:0] ratio_base,
	output     [27:3] pal_base,
	output     [27:0] bgi_base,
	output     [31:0] patch_len,
	output     [28:0] aud_off,
	output     [31:0] aud_len,
	output            lw_we,
	output      [7:0] lw_idx,
	output     [31:0] lw_addr
);

assign max_bytes = MAXB;
assign max_total = MAXT;
// a non-zero base, so offsets are really added; the command qword is the default's
hd3_loader #(.PACK_Q(25'h12345), .MAX_BYTES(MAXB), .MAX_TOTAL(MAXT), .POLL_W(4)) ld (.*);

endmodule
