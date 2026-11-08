// hd_reticle.sv - the Zapper crosshair drawn on the HD pack picture.
//
// video.sv draws the crosshair into the NES picture (palette $15, or $21 when aimed off-screen;
// zapper.sv decides when). The HD picture replaces the NES picture, so without this a Zapper
// game played with Zapper(Joy1/Joy2) or Zapper(Mouse) has nothing to aim with. This draws the
// same plus sign at the same screen position, coloured from the HD engine's own palette
// (rtl/hdpack/hd3_pal2c02.hex). Only the drawing is added: the gun senses light from the NES
// picture (zapper.sv reads the PPU colour index), exactly as on the console.
//
// The HD picture is one HD pixel per clk, 512 x 480 active, 2 x 2 HD pixels per NES pixel
// (hd3_scanout.sv), so the NES pixel is the active pixel / line count halved. HB/VB come with
// R/G/B in the same clock, so the counters index the pixel currently on R/G/B.
// Used by NES.sv and by tools/fullsim/sim_top.sv, so the simulation runs this exact code.

module hd_reticle
(
	input        clk,
	input        enable,     // a light gun is on and the Crosshairs option is On
	input  [7:0] aim_x,      // NES pixel the gun points at (zapper.sv)
	input  [7:0] aim_y,
	input        hb,
	input        vb,
	input  [7:0] r_in, g_in, b_in,
	output [7:0] r_out, g_out, b_out,

	// The pack marker, a 4 x 4 rectangle on top of the HD picture at an HD pixel position, set by
	// the game through four write-only registers. For a pack whose Mesen Lua script drew such a
	// thing (Dragon Quest III's minimap player dot, tools/corpus/make_dq3_hd_patch.py):
	//   $4108 x[7:0]   $4109 y[7:0]   $410A {2'b00, y[10:8], x[10:8]}  (signed: may be off-picture)
	//   $410B $D1 white, $D2 red, anything else off (a stray write cannot turn it on)
	input        rst,
	input [15:0] bus_a,
	input  [7:0] bus_d,
	input        bus_wr
);

reg signed [10:0] mk_x = 0, mk_y = 0;
reg [1:0] mk_on = 0;                       // 1 white, 2 red
always @(posedge clk) begin
	if (rst) mk_on <= 0;
	else if (bus_wr && bus_a[15:2] == 14'h1042) case (bus_a[1:0])
		2'd0: mk_x[7:0] <= bus_d;
		2'd1: mk_y[7:0] <= bus_d;
		2'd2: {mk_y[10:8], mk_x[10:8]} <= bus_d[5:0];
		2'd3: mk_on <= (bus_d == 8'hD1) ? 2'd1 : (bus_d == 8'hD2) ? 2'd2 : 2'd0;
	endcase
end

reg [9:0] px = 0, ln = 0;
reg       hb_d = 1;
always @(posedge clk) begin
	hb_d <= hb;
	if (hb) px <= 0;
	else    px <= px + 1'd1;
	if (vb)              ln <= 0;
	else if (hb & ~hb_d) ln <= ln + 1'd1;   // an active line just ended
end

// zapper.sv tests the PPU dot counter (cycle), and screen column = cycle - 2 (the NES picture is two
// dots behind the counter - the same offset fullsim's --xoff 2 is calibrated to, and the HD picture is
// lined up column for column with the NES picture). So the gun senses, and video.sv draws its plus,
// at screen column aim_x - 2; the row is not offset. Signed, so an aim at x 0..1 lands off the left
// edge exactly as the NES picture's plus does.
wire signed [10:0] nx = {2'b00, px[9:1]};
wire signed [10:0] ny = {2'b00, ln[9:1]};
wire signed [10:0] zx = {3'b000, aim_x} - 11'sd2;
wire signed [10:0] zy = {3'b000, aim_y};

// zapper.sv: hit_x = |aim_x - cycle| <= 1 on the aim row, hit_y = |aim_y - scanline| <= 1 on the aim column
wire on_mark = enable && !hb && !vb &&
	(((nx + 11'sd1 >= zx) && (zx + 11'sd1 >= nx) && ny == zy) ||
	 ((ny + 11'sd1 >= zy) && (zy + 11'sd1 >= ny) && nx == zx));
// zapper.sv is_offscreen
wire off = (aim_x >= 8'd254 || aim_x <= 8'd1) || (aim_y >= 8'd224 || aim_y <= 8'd8);
wire [23:0] rgb = off ? 24'h64b0ff : 24'hb71e7b;   // hd3_pal2c02.hex entries $21 and $15

// the marker: drawn over the crosshair, as neither game nor pack uses both.
// The position test is worked out one clock early, for the pixel the counters will hold next
// (px_n, ln_n follow the counter updates above exactly), and kept in registers, so the video
// path sees only registered bits ANDed with hb/vb - no subtractor between the HD picture and
// the output. Same pixels as testing px/ln combinationally.
wire [9:0]  px_n = hb ? 10'd0 : px + 1'd1;
wire [9:0]  ln_n = vb ? 10'd0 : (hb & ~hb_d) ? ln + 1'd1 : ln;
wire [10:0] dx_n = {1'b0, px_n} - mk_x;    // 0..3 in two's complement: the top nine bits are 0
wire [10:0] dy_n = {1'b0, ln_n} - mk_y;
reg  dot_xy = 0;
reg  [1:0] dot_on = 0;
always @(posedge clk) begin
	dot_xy <= dx_n[10:2] == 0 && dy_n[10:2] == 0;
	dot_on <= mk_on;
end
wire on_dot = (dot_on != 0) && dot_xy && !hb && !vb;
wire [7:0] dot_gb = dot_on[1] ? 8'h00 : 8'hFF;

assign r_out = on_dot ? 8'hFF : on_mark ? rgb[23:16] : r_in;
assign g_out = on_dot ? dot_gb : on_mark ? rgb[15:8]  : g_in;
assign b_out = on_dot ? dot_gb : on_mark ? rgb[7:0]   : b_in;

endmodule
