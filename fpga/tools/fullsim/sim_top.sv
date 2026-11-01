// sim_top.sv - whole-core Verilator simulation of the NES core + HD pack engine.
//
// Instantiates GameLoader, NES, hd3_engine (stage 3, with its ROM patcher) and hd_stage2 the
// same way NES.sv (module emu) does, with the MiSTer framework replaced by:
//   - an hps_io-style ioctl port driven by the C++ testbench (fullsim.cpp)
//   - sdram_sim (tools/fullsim/sim_lib.sv) in place of rtl/sdram.sv
//   - the DDR3 behind hd3_engine's DDRAM_* port (hd3_ddr, on clk_f), modelled in C++
//   - fixed OSD status: everything at its default (all status bits 0) except "HD Pack" (status[88])
//     and the joystick 1 buttons, which are inputs.
// The glue logic below (file type decode, download reset, loader write pipeline, joypad shift
// registers, reset_nes) is copied from NES.sv; keep it in step if NES.sv changes.

module sim_top
(
	input             clk,             // 21.477 MHz core clock (NTSC)
	input             clk_f,           // 85.9 MHz HD engine / DDR3 clock (4 x clk, same PLL: NES.sv clk85)

	// hps_io ioctl (OSD file loading)
	input             ioctl_downloading,
	input       [7:0] filetype,        // ioctl_index: 8'h01 = NES rom (slot "FS,NESFDSNSF"), 8'h04 = HD pack
	input      [24:0] ioctl_addr,
	input             ioctl_wr,        // loader_clk
	input       [7:0] ioctl_dout,      // file_input
	output            ioctl_wait_out,

	input             hd_enable,       // status[88]
	input             ex_sprites,      // status[25] "Extra sprites" (16 per line)
	input             hd_nolimit,      // an HD pack's disableSpriteLimit (forced extras, Mesen's adaptive rule)
	input      [11:0] joy1,            // MiSTer joystick_0: {..., start, select, B, A, up, down, left, right}
	// Zapper on NES port 2 as NES.sv's "Peripheral = Zapper(Joy1)", "Zapper Trigger = Joystick",
	// "Crosshairs = On": zap_analog = joy_analog0 ({y, x}, signed), zap_fire = the Zapper/Vaus Btn
	input             zap_en,
	input      [15:0] zap_analog,
	input             zap_fire,

	// DDR3 (HD pack memory), modelled in C++
	input             DDRAM_BUSY,
	output      [7:0] DDRAM_BURSTCNT,
	output     [28:0] DDRAM_ADDR,
	input      [63:0] DDRAM_DOUT,
	input             DDRAM_DOUT_READY,
	output            DDRAM_RD,
	output     [63:0] DDRAM_DIN,
	output      [7:0] DDRAM_BE,
	output            DDRAM_WE,

	// NES picture (PPU output, before video.sv)
	output      [5:0] color,
	output      [8:0] cycle,
	output      [8:0] scanline,
	output      [2:0] emphasis,
	output      [1:0] nes_div,
	output            nes_hsync, nes_hblank, nes_vsync, nes_vblank,

	// video.sv output (what the MiSTer scaler sees for the NES picture), "full 240 lines" mode
	output            v_ce_pix,
	output      [7:0] v_R, v_G, v_B,
	output            v_HS, v_VS, v_HB, v_VB,

	// HD engine output
	output            hd_active,
	output      [7:0] hd_r, hd_g, hd_b,
	output            hd_hs, hd_vs, hd_hb, hd_vb,
	output      [3:0] hd_reject,       // hd3_engine status (see hd3_engine.sv)
	output            hd_underflow,
	output     [15:0] hd_frames_drawn,
	output     [15:0] hd_frames_dropped,
	output     [15:0] hd_adds_aborted,
	output            hd_overrun,
	output            hd_dict_overflow,

	output            loader_done_o,
	output            loader_fail_o,
	output            reset_nes_o,
	output     [15:0] sample,
	output            hd_aud_active,   // stage 6 (hd3_audio): the core's AUDIO_S
	output     [15:0] hd_aud_l,        // and AUDIO_L/R while it is set (NES.sv)
	output     [15:0] hd_aud_r,
	output     [15:0] hd_aud_underruns,
	output     [15:0] aud_bus_a,       // nes.v's bus export as hd3_audio sees it (--audlog)
	output      [7:0] aud_bus_d,
	output            aud_bus_wr,

	// stage 2 frame record (hd_capture)
	output            rec_frame_done,
	output     [31:0] rec_frame_num,
	output            rec_overflow,

	// stage 2 watched-address snapshot (hd_watch). The list comes from the pack (hd3_loader),
	// or, with w_ext, from fullsim's --watch (the stage-2 test without a pack). Its read ports
	// belong to hd3_engine; fullsim reads the values back from the model (hd_watch.vals).
	input             w_ext,
	input             w_lw_we,
	input       [7:0] w_lw_idx,
	input      [31:0] w_lw_addr,
	input       [8:0] w_list_n,
	output            w_snap,          // the tap's snap pulse (scanline 240 dot 0)
	output    [191:0] w_pal,           // the PPU's palette RAM (tap), 32 x 6 bits
	output            w_done,
	output            w_overflow,
	output            w_timeout
);

// The download the CORE sees (c_*): the ioctl port's own, or the ROM patcher's replay of the
// patched ROM (hd3_romfix, stage 5) - as in NES.sv. The ioctl_* ports feed the patcher and the
// pack loader.
wire        c_dl, c_wr;
wire  [7:0] c_ft, c_dout;
wire [24:0] c_addr;
wire        rom_stall, rom_hold;
wire  [1:0] rom_content;
wire  [2:0] rom_result;
wire        is_nes_dl = (~|filetype[5:0] && filetype[7:6] == 2'b01) ||
                        (filetype[1:0] == 2'b01 && filetype[7:6] == 2'b00 && ~&filetype);

// ---------------- file type decode (NES.sv) ----------------
reg type_bios, type_fds, type_gg, type_nsf, type_nes, type_palette, is_bios, downloading;
reg loader_reset;
reg ioctl_download;
wire loader_busy, loader_done, loader_fail, rom_loaded;

always @(posedge clk) begin
	reg old_downld;

	old_downld <= downloading;
	loader_reset <= !download_reset || (~old_downld && downloading);

	ioctl_download <= c_dl;
	{type_bios, type_fds, type_gg, type_nsf, type_nes, type_palette, is_bios, downloading} <= 0;
	if (~|c_ft[5:0])
		case(c_ft[7:6])
			2'b00: begin type_bios <= 1; is_bios <= 1; downloading <= c_dl; end
			2'b01: begin type_nes <= 1; downloading <= c_dl; end
			2'b10: begin type_fds <= 1; downloading <= c_dl; end
		endcase
	else if(&c_ft)
		type_gg <= 1;
	else if (c_ft[1:0] == 2'b01)
		case (c_ft[7:6])
			2'b00: begin type_nes <= 1; downloading <= c_dl; end
			2'b01: begin type_fds <= 1; downloading <= c_dl; end
			2'b10: begin type_nsf <= 1; downloading <= c_dl; end
		endcase
	else if (c_ft[1:0] == 2'b10) begin
		type_bios <= 1;
		downloading <= c_dl;
	end else if (c_ft[1:0] == 2'b11)
		type_palette <= 1;
end

// reset after download
reg [7:0] download_reset_cnt = 0;
wire download_reset = download_reset_cnt != 0;
always @(posedge clk) begin
	if(downloading) download_reset_cnt <= 8'hFF;
	else if(!loader_busy && download_reset_cnt) download_reset_cnt <= download_reset_cnt - 1'd1;
end

// hold machine in reset until first download starts
reg init_reset_n = 0;
always @(posedge clk) if(downloading) init_reset_n <= 1;

// ---------------- system type (status[72:70] = 0 = Auto) ----------------
reg  [63:0] mapper_flags;
wire        e_nolimit;              // hd3_engine: the pack's disableSpriteLimit while its picture is on
wire [63:0] loader_flags;
wire [1:0] effective_sys_type = (mapper_flags[44:43] == 2'd1) ? 2'd3 :
                                (mapper_flags[37:36] == 2'd1) ? 2'd1 :
                                (mapper_flags[37:36] == 2'd3) ? 2'd2 : 2'd0;
reg [1:0] old_sys_type;
always @(posedge clk) old_sys_type <= effective_sys_type;

wire hold_reset;
wire reset_nes =
	~init_reset_n  ||
	download_reset ||
	loader_fail    ||
	hold_reset     ||
	rom_hold       ||
	(old_sys_type != effective_sys_type);

assign reset_nes_o = reset_nes;
assign loader_done_o = loader_done;
assign loader_fail_o = loader_fail;

// ---------------- GameLoader (extracted verbatim from NES.sv at build time) ----------------
wire [7:0]  loader_input = c_dout;         // no FDS bios / NSF player in this simulation
wire        loader_clk = c_wr;
wire [24:0] loader_addr;
wire [7:0]  loader_write_data;
wire        loader_write;
wire [9:0]  prg_mask, chr_mask;

GameLoader loader
(
	.clk              ( clk               ),
	.clearval         ( 1'b0              ),   // RAM Clear = No
	.cleardata        ( 8'h00             ),
	.reset            ( loader_reset      ),
	.downloading      ( downloading       ),
	.filetype         ( {4'b0000, type_nsf, type_fds, type_nes, type_bios} ),
	.is_bios          ( is_bios           ),
	.indata           ( loader_input      ),
	.indata_clk       ( loader_clk        ),
	.mem_addr         ( loader_addr       ),
	.mem_data         ( loader_write_data ),
	.mem_write        ( loader_write      ),
	.mapper_flags     ( loader_flags      ),
	.prg_mask         ( prg_mask          ),
	.chr_mask         ( chr_mask          ),
	.busy             ( loader_busy       ),
	.done             ( loader_done       ),
	.error            ( loader_fail       ),
	.rom_loaded       ( rom_loaded        )
);

always @(posedge clk) if (loader_done) mapper_flags <= loader_flags;

// loader_write -> clock when data available (NES.sv)
reg loader_write_mem;
reg [7:0] loader_write_data_mem;
reg [24:0] loader_addr_mem;
reg loader_write_triggered;
reg ioctl_wait;

always @(posedge clk) begin
	if(loader_write) begin
		loader_write_triggered <= 1'b1;
		loader_addr_mem <= loader_addr;
		loader_write_data_mem <= loader_write_data;
		ioctl_wait <= 1;
	end

	if(nes_ce == 3) begin
		loader_write_mem <= loader_write_triggered;
		if(loader_write_triggered) begin
			loader_write_triggered <= 1'b0;
		end else if(ioctl_wait) begin
			ioctl_wait <= 0;
		end
	end
end

// ---------------- joypads (NES.sv, no peripherals, no multitap) ----------------
wire [7:0] nes_joy_A = { joy1[0], joy1[1], joy1[2], joy1[3], joy1[7], joy1[6], joy1[5], joy1[4] };
wire [7:0] nes_joy_B = 8'd0;
wire [2:0] joypad_out;
wire [1:0] joypad_clock;
reg  [23:0] joypad_bits, joypad_bits2;
reg   [1:0] last_joypad_clock;

always @(posedge clk) begin
	if (reset_nes) begin
		joypad_bits <= 0;
		joypad_bits2 <= 0;
		last_joypad_clock <= 0;
	end else begin
		if (joypad_out[0]) begin
			joypad_bits  <= {16'hFFFF, nes_joy_A};
			joypad_bits2 <= {16'hFFFF, nes_joy_B};
		end
		if (!joypad_clock[0] && last_joypad_clock[0])
			joypad_bits <= {1'b0, joypad_bits[23:1]};
		if (!joypad_clock[1] && last_joypad_clock[1])
			joypad_bits2 <= {1'b0, joypad_bits2[23:1]};
		last_joypad_clock <= joypad_clock;
	end
end

wire [4:0] joypad1_data = {4'b0, joypad_bits[0]};
// NES.sv: "else if (lightgun_en) joypad2_data[4:3] = {trigger, light};"
wire [4:0] joypad2_data = {zap_en ? {zap_trigger, zap_light} : 2'b00, 2'b0, joypad_bits2[0]};

// ---------------- Zapper (NES.sv's instance, joystick mode) ----------------
wire [1:0] zap_reticle;
wire       zap_light, zap_trigger;
wire [7:0] zap_aim_x, zap_aim_y;
zapper zap (
	.clk(clk),
	.reset(reset_nes | ~zap_en),
	.mode(1'b1),
	.trigger_mode(1'b1),
	.ps2_mouse(25'd0),
	.analog(zap_analog),
	.analog_trigger(zap_fire),
	.cycle(cycle),
	.scanline(scanline),
	.color(color),
	.reticle(zap_reticle),
	.light(zap_light),
	.trigger(zap_trigger),
	.aim_x(zap_aim_x),
	.aim_y(zap_aim_y)
);

// ---------------- NES ----------------
wire [1:0] nes_ce;
assign nes_div = nes_ce;
wire [24:0] cpu_addr;
wire [21:0] ppu_addr;
wire        cpu_read, cpu_write, ppu_read, ppu_write;
wire  [7:0] cpu_dout, cpu_din, ppu_dout, ppu_din;
wire [415:0] hd_tap_bus;
wire        hd_chr_wr;
wire [15:0] hd_cpu_a;
wire [13:0] hd_ppu_a;
wire [15:0] hd_bus_a;
wire  [7:0] hd_bus_dout;
wire        hd_bus_wr, hd_aud_hit_wr, hd_aud_hit_rd;
wire  [7:0] hd_aud_rdata;
assign aud_bus_a  = hd_bus_a;
assign aud_bus_d  = hd_bus_dout;
assign aud_bus_wr = hd_bus_wr;
wire        hd_sd_own, hd_sd_rd, ch2_busy;
wire [24:0] hd_sd_addr;
wire  [7:0] ch2_dout;
wire signed [23:0] composite_a, composite_b;
wire [17:0] bram_addr;
wire  [7:0] bram_dout;
wire        bram_write, bram_en;

NES nes (
	.clk             (clk),
	.reset_nes       (reset_nes),
	.ppu_rst_behavior(1'b0),
	.cold_reset      (downloading & (type_fds | type_nes)),
	.pausecore       (1'b0),
	.corepaused      (),
	.debug_dots      (1'b0),
	.sys_type        (effective_sys_type),
	.vs_dip_switches (8'd0),
	.nes_div         (nes_ce),
	.mapper_flags    (downloading ? 64'd0 : mapper_flags),
	.gg              (1'b0),
	.gg_code         (129'd0),
	.gg_reset        (1'b0),
	.gg_avail        (),
	.sample          (sample),
	.audio_channels  (5'b11111),
	.int_audio       (1'b1),
	.ext_audio       (1'b1),
	.apu_ce          (),
	.ex_sprites      (ex_sprites),
	.hd_nolimit      (hd_nolimit | e_nolimit),   // --nolimit, or the loaded pack's option (NES.sv)
	.color           (color),
	.hsync           (nes_hsync),
	.hblank          (nes_hblank),
	.vsync           (nes_vsync),
	.vblank          (nes_vblank),
	.composite_a     (composite_a),
	.composite_b     (composite_b),
	.emphasis        (emphasis),
	.cycle           (cycle),
	.scanline        (scanline),
	.mask            (2'b00),
	.dejitter_timing (1'b0),
	.joypad_out      (joypad_out),
	.joypad_clock    (joypad_clock),
	.joypad1_data    (joypad1_data),
	.joypad2_data    (joypad2_data),
	.diskside        (),
	.fds_busy        (1'b0),
	.fds_eject       (1'b0),
	.fds_auto_eject  (1'b1),             // ~status[16]
	.max_diskside    (2'd3),
	.fds_fast        (1'b1),             // ~status[17]
	.cpumem_addr     (cpu_addr ),
	.cpumem_read     (cpu_read ),
	.cpumem_write    (cpu_write),
	.cpumem_dout     (cpu_dout ),
	.cpumem_din      (cpu_din  ),
	.ppumem_addr     (ppu_addr ),
	.hd_tap_bus      (hd_tap_bus),
	.hd_chr_wr       (hd_chr_wr),
	.hd_cpu_a        (hd_cpu_a),
	.hd_ppu_a        (hd_ppu_a),
	.hd_bus_a        (hd_bus_a),
	.hd_bus_dout     (hd_bus_dout),
	.hd_bus_wr       (hd_bus_wr),
	.hd_aud_hit_wr   (hd_aud_hit_wr),
	.hd_aud_hit_rd   (hd_aud_hit_rd),
	.hd_aud_rdata    (hd_aud_rdata),
	.ppumem_read     (ppu_read ),
	.ppumem_write    (ppu_write),
	.ppumem_dout     (ppu_dout ),
	.ppumem_din      (ppu_din  ),
	.refresh         (),
	.prg_mask        (prg_mask ),
	.chr_mask        (chr_mask ),
	.bram_addr       (bram_addr),
	.bram_din        (8'hFF),
	.bram_dout       (bram_dout),
	.bram_write      (bram_write),
	.bram_override   (bram_en),
	.save_written    (),
	.mapper_has_flashsaves (),
	.mapper_has_savestate  (),
	.increaseSSHeaderCount (1'b1),
	.save_state      (1'b0),
	.load_state      (1'b0),
	.savestate_number(2'd0),
	.sleep_savestate (),
	.state_loaded    (),
	.Savestate_SDRAMAddr     (),
	.Savestate_SDRAMRdEn     (),
	.Savestate_SDRAMWrEn     (),
	.Savestate_SDRAMWriteData(),
	.Savestate_SDRAMReadData (8'd0),
	.SaveStateExt_Din        (),
	.SaveStateExt_Adr        (),
	.SaveStateExt_wren       (),
	.SaveStateExt_rst        (),
	.SaveStateExt_Dout       (64'd0),
	.SaveStateExt_load       (),
	.SaveStateExt_save       (),
	.SAVE_out_Din            (),
	.SAVE_out_Dout           (64'd0),
	.SAVE_out_Adr            (),
	.SAVE_out_rnw            (),
	.SAVE_out_ena            (),
	.SAVE_out_be             (),
	.SAVE_out_done           (1'b0)
);

// ---------------- memory (replaces rtl/sdram.sv) ----------------
sdram_sim sdram
(
	.clk        ( clk ),
	.ch0_addr   (  (downloading | loader_busy) ? loader_addr_mem       : {3'b0, ppu_addr}  ),
	.ch0_wr     (                                loader_write_mem      | ppu_write ),
	.ch0_din    (  (downloading | loader_busy) ? loader_write_data_mem : ppu_dout  ),
	.ch0_rd     ( ~(downloading | loader_busy)                         & ppu_read  ),
	.ch0_dout   ( ppu_din   ),
	.ch1_addr   ( cpu_addr  ),
	.ch1_wr     ( cpu_write ),
	.ch1_din    ( cpu_dout  ),
	.ch1_rd     ( cpu_read  ),
	.ch1_dout   ( cpu_din   ),
	// ch2: no battery saves or savestates in the simulation, so the HD port always owns it
	.ch2_addr   ( hd_sd_addr ),
	.ch2_wr     ( 1'b0 ),
	.ch2_din    ( 8'd0 ),
	.ch2_rd     ( hd_sd_rd ),
	.ch2_dout   ( ch2_dout ),
	.ch2_busy   ( ch2_busy )
);

// ---------------- video.sv (only for hold_reset and the reference RGB stream) ----------------
video video
(
	.clk(clk),
	.reset(reset_nes),
	.cnt(nes_ce),
	.color(color),
	.count_h(cycle),
	.count_v(scanline),
	.hide_overscan(2'b01),              // "full": 240 lines, 256 dots (capture only; no effect on the core)
	.palette(4'd0),                     // Kitrinx
	.emphasis(emphasis),
	.reticle(zap_en ? zap_reticle : 2'b00),   // NES.sv: Crosshairs On
	.sys_type(effective_sys_type),
	.vs_ppu_type(mapper_flags[48:45]),
	.pal_video(1'b0),
	.nes_hblank(nes_hblank),
	.nes_hsync(nes_hsync),
	.nes_vsync(nes_vsync),
	.nes_vblank(nes_vblank),
	.load_color(1'b0),
	.load_color_data(24'd0),
	.load_color_index(6'd0),
	.hold_reset(hold_reset),
	.ce_pix(v_ce_pix),
	.HSync(v_HS),
	.VSync(v_VS),
	.HBlank(v_HB),
	.VBlank(v_VB),
	.R(v_R),
	.G(v_G),
	.B(v_B)
);

// ---------------- HD pack (NES.sv) ----------------
wire        hd_load_wait;
wire  [7:0] hd_r_raw, hd_g_raw, hd_b_raw;   // engine picture before the Zapper crosshair
wire        cw_valid, cw_ready;
wire [27:3] cw_addr;
wire [63:0] cw_data;
wire  [7:0] cw_be;
wire        e_lw_we;
wire  [7:0] e_lw_idx;
wire [31:0] e_lw_addr;
wire  [8:0] e_list_n;
wire        hd_w1_bank, hd_w2_bank;
wire  [7:0] hd_w1_idx, hd_w1_q, hd_w2_idx, hd_w2_q;

// HD_PAINT (build.sh with PAINT=1): the display-list route, hd3_pengine, same ports; the ARM's
// part is played by fullsim.cpp (FULLSIM_ARM) on the DDR3 model.
`ifdef HD_PAINT
hd3_pengine hd3_engine
`else
hd3_engine hd3_engine
`endif
(
	.clk         (clk),
	.clk_f       (clk_f),
	.reset       (1'b0),
	.enable      (hd_enable),

	.load_active (ioctl_downloading && filetype[5:0] == 6'd4),
	.load_wr     (ioctl_downloading && filetype[5:0] == 6'd4 && ioctl_wr),
	.load_data   (ioctl_dout),

	.rom_dl      (ioctl_downloading),
	.rom_is_nes  (is_nes_dl),
	.rom_wr      (ioctl_wr),
	.rom_din     (ioctl_dout),
	.rom_addr    (ioctl_addr),
	.rom_ft      (filetype),
	.rom_stall   (rom_stall),
	.rom_o_dl    (c_dl),
	.rom_o_wr    (c_wr),
	.rom_o_din   (c_dout),
	.rom_o_addr  (c_addr),
	.rom_o_ft    (c_ft),
	.rom_core_wait (ioctl_wait),
	.rom_hold    (rom_hold),
	.rom_content (rom_content),
	.rom_result  (rom_result),
	.load_wait   (hd_load_wait),
	.cart_no_chr_rom (mapper_flags[15]),

	.cw_valid    (cw_valid),
	.cw_addr     (cw_addr),
	.cw_data     (cw_data),
	.cw_be       (cw_be),
	.cw_ready    (cw_ready),
	.frame_num   (rec_frame_num),
	.watch_done  (w_done),

	.lw_we       (e_lw_we),
	.lw_idx      (e_lw_idx),
	.lw_addr     (e_lw_addr),
	.list_n      (e_list_n),
	.w1_bank     (hd_w1_bank),
	.w1_idx      (hd_w1_idx),
	.w1_q        (hd_w1_q),
	.w2_bank     (hd_w2_bank),
	.w2_idx      (hd_w2_idx),
	.w2_q        (hd_w2_q),

	.line_done   (hd_tap_bus[114]),
	.line_y      (hd_tap_bus[123:115]),

	.pal         (effective_sys_type == 2'd1),   // as NES.sv
	.cpu_a       (hd_bus_a),
	.cpu_dout    (hd_bus_dout),
	.cpu_wr_strobe (hd_bus_wr),
	.aud_hit_wr  (hd_aud_hit_wr),
	.aud_hit_rd  (hd_aud_hit_rd),
	.aud_rdata   (hd_aud_rdata),
	.nes_sample  (sample),
	.aud_active  (hd_aud_active),
	.aud_l       (hd_aud_l),
	.aud_r       (hd_aud_r),

	// no savestates in this simulation
	.aud_ss_save (1'b0),
	.aud_ss_load (1'b0),
	.aud_ss_in_a (64'd0),
	.aud_ss_in_b (64'd0),
	.aud_ss_out_a(),
	.aud_ss_out_b(),
	.ss_addr     (27'd0),
	.ss_din      (64'd0),
	.ss_dout     (),
	.ss_req      (1'b0),
	.ss_rnw      (1'b1),
	.ss_be       (8'hFF),
	.ss_ack      (),

	.DDRAM_BUSY  (DDRAM_BUSY),
	.DDRAM_BURSTCNT (DDRAM_BURSTCNT),
	.DDRAM_ADDR  (DDRAM_ADDR),
	.DDRAM_DOUT  (DDRAM_DOUT),
	.DDRAM_DOUT_READY (DDRAM_DOUT_READY),
	.DDRAM_RD    (DDRAM_RD),
	.DDRAM_DIN   (DDRAM_DIN),
	.DDRAM_BE    (DDRAM_BE),
	.DDRAM_WE    (DDRAM_WE),

	.active      (hd_active),
	.nolimit     (e_nolimit),
	.R(hd_r_raw), .G(hd_g_raw), .B(hd_b_raw),
	.HS(hd_hs), .VS(hd_vs), .HB(hd_hb), .VB(hd_vb),

	.reject (hd_reject), .underflow (hd_underflow), .frames_drawn (hd_frames_drawn),
	.frames_dropped (hd_frames_dropped), .adds_aborted (hd_adds_aborted),
	.overrun (hd_overrun), .dict_overflow (hd_dict_overflow), .aud_underruns (hd_aud_underruns), .aud_ev_lost ()
);

// the Zapper crosshair on the HD picture, the same module NES.sv uses
hd_reticle hd_reticle
(
	.clk(clk),
	.enable(zap_en),
	.aim_x(zap_aim_x), .aim_y(zap_aim_y),
	.hb(hd_hb), .vb(hd_vb),
	.r_in(hd_r_raw), .g_in(hd_g_raw), .b_in(hd_b_raw),
	.r_out(hd_r), .g_out(hd_g), .b_out(hd_b)
);

hd_stage2 hd_stage2
(
	.clk        (clk),
	.reset      (reset_nes),
	.enable     (hd_enable),
	.tap        (hd_tap_bus),
	.chr_ram    (mapper_flags[15]),
	.ppu_wr     (hd_chr_wr),
	.ppu_addr   (ppu_addr),
	.ppu_data   (ppu_dout),
	.ss_wr      (1'b0),
	.ss_addr    (25'd0),
	.ss_data    (8'd0),
	.cw_valid   (cw_valid),
	.cw_addr    (cw_addr),
	.cw_data    (cw_data),
	.cw_be      (cw_be),
	.cw_ready   (cw_ready),
	.frame_done (rec_frame_done),
	.frame_num  (rec_frame_num),
	.overflow   (rec_overflow),

	// the list from the pack (hd3_loader), or from fullsim's --watch for the stage-2 test
	.lw_we      (w_ext ? w_lw_we   : e_lw_we),
	.lw_idx     (w_ext ? w_lw_idx  : e_lw_idx),
	.lw_addr    (w_ext ? w_lw_addr : e_lw_addr),
	.list_n     (w_ext ? w_list_n  : e_list_n),

	.cpu_rd     (cpu_read),
	.cpu_wr     (cpu_write),
	.cpu_a      (hd_cpu_a),
	.cpu_lin    (cpu_addr),
	.cpu_d      (cpu_dout),
	.vram_rd    (ppu_read),
	.vram_wr    (ppu_write),
	.vram_a     (hd_ppu_a),
	.vram_lin   (ppu_addr),
	.vram_d     (ppu_dout),

	.sd_allow   (1'b1),
	.sd_own     (hd_sd_own),
	.sd_rd      (hd_sd_rd),
	.sd_addr    (hd_sd_addr),
	.sd_busy    (ch2_busy),
	.sd_dout    (ch2_dout),

	.v_clk      (clk_f),
	.v_bank     (hd_w1_bank),
	.v_idx      (hd_w1_idx),
	.v_q        (hd_w1_q),
	.v2_bank    (hd_w2_bank),
	.v2_idx     (hd_w2_idx),
	.v2_q       (hd_w2_q),
	.watch_done (w_done),
	.watch_overflow (w_overflow),
	.sd_timeout (w_timeout)
);

assign w_snap = hd_tap_bus[344];
assign w_pal  = hd_tap_bus[315:124];

assign ioctl_wait_out = ioctl_wait | hd_load_wait | rom_stall;

endmodule
