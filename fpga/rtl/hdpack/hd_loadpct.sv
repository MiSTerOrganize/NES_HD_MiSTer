// hd_loadpct.sv - "LOADING nn%" in the bottom-right corner while an HD pack is copied into DDR3.
//
// The same read-out as OpenBOR_7533's (native_video_writer.c, nv_draw_loading): its 5x7 glyphs,
// white text over a black copy one pixel down and right (no panel, so it stays legible on any
// picture), right-aligned so the digits do not shift sideways from 9% to 10%, 4 pixels in from
// the right and bottom edges. It is drawn on the picture going to video_mixer, in CLK_VIDEO.
//
// The picture's size is measured from the blanking (pixels per line, lines per frame of the
// previous frame), so the text sits in the corner whatever the overscan setting. The text is a
// 12-character field ("LOADING 100%" at most); each line of it is built into a shift register
// during horizontal blanking and shifted out across the field, so nothing is computed per pixel.
// show/pct come from the core clock and are taken once per frame, at vertical blanking, so a
// frame never shows a half-changed number.

module hd_loadpct (
	input        clk,
	input        ce,                 // pixel enable of the picture
	input        hb,
	input        vb,
	input        show_in,            // core clock: a pack copy is in progress
	input  [6:0] pct_in,             // core clock: its progress, 0..100
	input  [7:0] r_in, g_in, b_in,
	output [7:0] r_out, g_out, b_out
);

localparam [4:0] C_PCT = 5'd10, C_L = 5'd11, C_O = 5'd12, C_A = 5'd13, C_D = 5'd14,
                 C_I = 5'd15, C_N = 5'd16, C_G = 5'd17, C_SP = 5'd31;

// 5x7 rows, bit 4 = left column (OpenBOR's nv_font5x7 / nv_font_az / nv_font_punct)
function [4:0] glyph(input [4:0] c, input [2:0] row);
	reg [34:0] g;
	begin
		case (c)
			5'd0:  g = {5'h0E,5'h11,5'h11,5'h11,5'h11,5'h11,5'h0E};
			5'd1:  g = {5'h04,5'h0C,5'h04,5'h04,5'h04,5'h04,5'h0E};
			5'd2:  g = {5'h0E,5'h11,5'h01,5'h02,5'h04,5'h08,5'h1F};
			5'd3:  g = {5'h1F,5'h02,5'h04,5'h02,5'h01,5'h11,5'h0E};
			5'd4:  g = {5'h02,5'h06,5'h0A,5'h12,5'h1F,5'h02,5'h02};
			5'd5:  g = {5'h1F,5'h10,5'h1E,5'h01,5'h01,5'h11,5'h0E};
			5'd6:  g = {5'h06,5'h08,5'h10,5'h1E,5'h11,5'h11,5'h0E};
			5'd7:  g = {5'h1F,5'h01,5'h02,5'h04,5'h08,5'h08,5'h08};
			5'd8:  g = {5'h0E,5'h11,5'h11,5'h0E,5'h11,5'h11,5'h0E};
			5'd9:  g = {5'h0E,5'h11,5'h11,5'h0F,5'h01,5'h02,5'h0C};
			C_PCT: g = {5'h19,5'h1A,5'h02,5'h04,5'h08,5'h0B,5'h13};
			C_L:   g = {5'h10,5'h10,5'h10,5'h10,5'h10,5'h10,5'h1F};
			C_O:   g = {5'h0E,5'h11,5'h11,5'h11,5'h11,5'h11,5'h0E};
			C_A:   g = {5'h0E,5'h11,5'h11,5'h1F,5'h11,5'h11,5'h11};
			C_D:   g = {5'h1E,5'h11,5'h11,5'h11,5'h11,5'h11,5'h1E};
			C_I:   g = {5'h0E,5'h04,5'h04,5'h04,5'h04,5'h04,5'h0E};
			C_N:   g = {5'h11,5'h19,5'h15,5'h13,5'h11,5'h11,5'h11};
			C_G:   g = {5'h0E,5'h11,5'h10,5'h17,5'h11,5'h11,5'h0F};
			default: g = 35'd0;
		endcase
		glyph = (row > 3'd6) ? 5'd0 : g[34 - row*5 -: 5];
	end
endfunction

// show/pct into this clock (they change at most every few milliseconds)
reg       show_s1 = 0, show_s2 = 0;
reg [6:0] pct_s1 = 0, pct_s2 = 0;
always @(posedge clk) begin
	show_s1 <= show_in; show_s2 <= show_s1;
	pct_s1  <= pct_in;  pct_s2  <= pct_s1;
end

// the picture's size and the position in it
reg [11:0] x = 0, w = 0;
reg [10:0] y = 0, h = 0;
reg        hb_d = 0, vb_d = 0;

// the text of this frame: 12 character codes, right-aligned
reg        show_f = 0;
reg  [4:0] code [12];
integer    k;

// "LOADING " then the digits then "%"
function [4:0] text_char(input [3:0] i, input [6:0] p);
	reg [1:0] nd;
	reg [3:0] t;
	begin
		nd = (p >= 7'd100) ? 2'd3 : (p >= 7'd10) ? 2'd2 : 2'd1;
		case (i)
			4'd0: text_char = C_L;  4'd1: text_char = C_O;  4'd2: text_char = C_A;
			4'd3: text_char = C_D;  4'd4: text_char = C_I;  4'd5: text_char = C_N;
			4'd6: text_char = C_G;  4'd7: text_char = C_SP;
			default: begin
				t = i - 4'd8;                                    // digit position
				if (t == {2'd0, nd}) text_char = C_PCT;
				else if (nd == 2'd3) text_char = (t == 4'd0) ? 5'd1 : 5'd0;
				else if (nd == 2'd2) text_char = (t == 4'd0) ? {1'b0, p / 7'd10} : {1'b0, p % 7'd10};
				else                 text_char = {1'b0, p[3:0]};
			end
		endcase
	end
endfunction

wire [6:0] pct_c = (pct_s2 > 7'd100) ? 7'd100 : pct_s2;
wire [3:0] len   = (pct_c >= 7'd100) ? 4'd12 : (pct_c >= 7'd10) ? 4'd11 : 4'd10;

// field position: 72 pixels of text (12 x 6) ending 4 in from the right; 7 rows + the shadow
// row ending 4 up from the bottom
wire [11:0] xs = w - 12'd76;
wire [10:0] ys = h - 11'd12;
wire signed [11:0] ty = $signed({1'b0, y}) - $signed({1'b0, ys});

function [71:0] row_bits(input [2:0] row);
	integer j;
	begin
		row_bits = 72'd0;
		for (j = 0; j < 12; j = j + 1)
			row_bits[71 - j*6 -: 6] = {glyph(code[j], row), 1'b0};
	end
endfunction

reg [71:0] sw = 0;               // white: this line of the text
reg [72:0] ss = 0;               // black: the line above, one pixel to the right

always @(posedge clk) begin
	if (ce) begin
		hb_d <= hb;
		vb_d <= vb;

		if (hb) x <= 12'd0;
		else    x <= x + 12'd1;

		if (hb && !hb_d && !vb && x != 12'd0) begin            // a picture line ended
			w <= x;
			y <= y + 11'd1;
		end
		if (vb && !vb_d) begin                                  // the frame ended
			h <= y;
			y <= 11'd0;
			show_f <= show_s2 && w >= 12'd80 && y >= 11'd16;
			for (k = 0; k < 12; k = k + 1)
				code[k] <= (k < 12 - len) ? C_SP : text_char(k - (12 - len), pct_c);
		end

		if (hb) begin                                           // build the next line
			sw <= (ty >= 0 && ty <= 6) ? row_bits(ty[2:0]) : 72'd0;
			ss <= (ty >= 1 && ty <= 7) ? {1'b0, row_bits(ty[2:0] - 3'd1)} : 73'd0;
		end
		else if (x >= xs) begin
			sw <= {sw[70:0], 1'b0};
			ss <= {ss[71:0], 1'b0};
		end
	end
end

wire in_field = show_f && !hb && !vb && x >= xs;
wire white    = in_field && sw[71];
wire black    = in_field && ss[72];

assign r_out = white ? 8'hFF : black ? 8'h00 : r_in;
assign g_out = white ? 8'hFF : black ? 8'h00 : g_in;
assign b_out = white ? 8'hFF : black ? 8'h00 : b_in;

endmodule
