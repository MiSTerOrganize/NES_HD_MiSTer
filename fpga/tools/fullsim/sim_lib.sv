// sim_lib.sv - simulation-only replacements for the VHDL / vendor blocks of the NES core.
//
// The simulator reads no VHDL. The CPU (T65) is converted to Verilog by GHDL at build time
// (see build.sh); everything here is a hand-written SystemVerilog equivalent or stub.
// Every stub is listed with its justification in README.txt.

// ------------------------------------------------------------------------------------------
// eReg_SavestateV (rtl/bus_savestates.vhd) - FULL equivalent, not a stub.
// The register value (Dout) is used by the core in normal operation (it supplies the reset
// value of many registers), so this is a faithful port of the VHDL process.
// ------------------------------------------------------------------------------------------
module eReg_SavestateV #(parameter [9:0] Adr = 10'd0, parameter [63:0] def = 64'd0)
(
	input             clk,
	input      [63:0] BUS_Din,
	input       [9:0] BUS_Adr,
	input             BUS_wren,
	input             BUS_rst,
	output     [63:0] BUS_Dout,
	input      [63:0] Din,
	output     [63:0] Dout
);
	reg [63:0] Dout_buffer = def;
	always @(posedge clk) begin
		if (BUS_rst) Dout_buffer <= def;
		else if (BUS_Adr == Adr && BUS_wren) Dout_buffer <= BUS_Din;
	end
	assign Dout     = Dout_buffer;
	assign BUS_Dout = (BUS_Adr == Adr) ? Din : 64'd0;
endmodule

// ------------------------------------------------------------------------------------------
// savestates (rtl/savestates.vhd) - STUB of the idle state only.
// In the IDLE state the VHDL drives, every clock: reset_ss/reset_delay/BUS_rst <= reset_in
// (registered), everything else idle. save/load never assert in this simulation, so the
// state machine never leaves IDLE and this stub is cycle-exact for that use.
// ------------------------------------------------------------------------------------------
module savestates
(
	input             clk,
	input             reset_in,
	output reg        reset_ss = 0,
	output reg        reset_delay = 0,
	output            load_done,
	input             increaseSSHeaderCount,
	input             save,
	input             load,
	input      [31:0] savestate_address,
	output            savestate_busy,
	input             paused,
	output     [63:0] BUS_Din,
	output      [9:0] BUS_Adr,
	output            BUS_wren,
	output reg        BUS_rst = 0,
	input      [63:0] BUS_Dout,
	output            loading_savestate,
	output            saving_savestate,
	output            sleep_savestate,
	output     [24:0] Save_RAMAddr,
	output            Save_RAMRdEn,
	output            Save_RAMWrEn,
	output      [7:0] Save_RAMWriteData,
	input       [7:0] Save_RAMReadData,
	output      [2:0] Save_RAMType,
	output     [63:0] bus_out_Din,
	input      [63:0] bus_out_Dout,
	output     [25:0] bus_out_Adr,
	output            bus_out_rnw,
	output            bus_out_ena,
	output      [7:0] bus_out_be,
	input             bus_out_done
);
	always @(posedge clk) begin
		reset_ss    <= reset_in;
		reset_delay <= reset_in;
		BUS_rst     <= reset_in;
	end
	assign load_done = 0;
	assign savestate_busy = 0;
	assign BUS_Din = 64'd0;
	assign BUS_Adr = 10'd0;
	assign BUS_wren = 0;
	assign loading_savestate = 0;
	assign saving_savestate = 0;
	assign sleep_savestate = 0;
	assign Save_RAMAddr = 25'd0;
	assign Save_RAMRdEn = 0;
	assign Save_RAMWrEn = 0;
	assign Save_RAMWriteData = 8'd0;
	assign Save_RAMType = 3'd0;
	assign bus_out_Din = 64'd0;
	assign bus_out_Adr = 26'd0;
	assign bus_out_rnw = 0;
	assign bus_out_ena = 0;
	assign bus_out_be = 8'hFF;
endmodule

// ------------------------------------------------------------------------------------------
// statemanager (rtl/statemanager.vhd) - STUB. With save = load = rewind_on = 0 the VHDL never
// raises any output (rewind_active = 0 keeps sleep_rewind low).
// ------------------------------------------------------------------------------------------
module statemanager #(parameter Softmap_SaveState_ADDR = 0, parameter Softmap_Rewind_ADDR = 0)
(
	input         clk,
	input         reset,
	input         rewind_on,
	input         rewind_active,
	input  [31:0] savestate_number,
	input         save,
	input         load,
	output        sleep_rewind,
	input         vsync,
	output        request_savestate,
	output        request_loadstate,
	output [31:0] request_address,
	input         request_busy
);
	assign sleep_rewind = 0;
	assign request_savestate = 0;
	assign request_loadstate = 0;
	assign request_address = 32'd0;
endmodule

// ------------------------------------------------------------------------------------------
// eseopll (rtl/SOUND/OPLL, VRC7 FM audio) - STUB: silent. Audio only; VRC7 games still run.
// ------------------------------------------------------------------------------------------
module eseopll
(
	input         clk21m,
	input         reset,
	input         clkena,
	input         enawait,
	input         req,
	output        ack,
	input         wrt,
	input  [15:0] adr,
	input   [7:0] dbo,
	output [13:0] wav
);
	assign ack = req;
	assign wav = 14'd0;
endmodule

// ------------------------------------------------------------------------------------------
// spram / spram_sz / dpram (rtl/dpram.vhd, altsyncram) - behavioural equivalents.
// altsyncram with outdata_reg = UNREGISTERED: address registered, one clock read latency,
// read-during-write on the same port returns the NEW data. .mif init files are not loaded
// (the only init file in the simulated hierarchy is video.sv's custom palette, unused).
// ------------------------------------------------------------------------------------------
module spram_sz #(parameter addr_width = 8, parameter data_width = 8, parameter numwords = 2**8,
                  parameter mem_init_file = " ", parameter mem_name = "MEM")
(
	input                       clock,
	input      [addr_width-1:0] address,
	input      [data_width-1:0] data,
	input                       enable,
	input                       wren,
	output     [data_width-1:0] q,
	input                       cs
);
	reg [data_width-1:0] mem [numwords];
	reg [data_width-1:0] q0;
	always @(posedge clock) begin
		if (wren & cs) begin
			mem[address] <= data;
			q0 <= data;
		end else begin
			q0 <= mem[address];
		end
	end
	assign q = cs ? q0 : {data_width{1'b1}};
endmodule

module spram #(parameter addr_width = 8, parameter data_width = 8,
               parameter mem_init_file = " ", parameter mem_name = "MEM")
(
	input                       clock,
	input      [addr_width-1:0] address,
	input      [data_width-1:0] data = '0,
	input                       enable = 1'b1,
	input                       wren = 1'b0,
	output     [data_width-1:0] q,
	input                       cs = 1'b1
);
	spram_sz #(addr_width, data_width, 2**addr_width, mem_init_file, mem_name) sz
	(
		.clock(clock), .address(address), .data(data), .enable(enable), .wren(wren), .q(q), .cs(cs)
	);
endmodule

module dpram #(parameter init_file = " ", parameter widthad_a = 8, parameter width_a = 8,
               parameter outdata_reg_a = "UNREGISTERED", parameter outdata_reg_b = "UNREGISTERED")
(
	input       [widthad_a-1:0] address_a,
	input       [widthad_a-1:0] address_b = '0,
	input                       clock_a,
	input                       clock_b,
	input         [width_a-1:0] data_a = '0,
	input         [width_a-1:0] data_b = '0,
	input                       wren_a = 1'b0,
	input                       wren_b = 1'b0,
	input     [width_a/8-1:0]   byteena_a = '1,
	input     [width_a/8-1:0]   byteena_b = '1,
	output reg    [width_a-1:0] q_a,
	output reg    [width_a-1:0] q_b
);
	reg [width_a-1:0] mem [2**widthad_a];
	integer i;
	always @(posedge clock_a) begin
		if (wren_a) begin
			for (i = 0; i < width_a/8; i = i + 1)
				if (byteena_a[i]) mem[address_a][i*8 +: 8] <= data_a[i*8 +: 8];
			q_a <= data_a;
		end else q_a <= mem[address_a];
	end
	always @(posedge clock_b) begin
		if (wren_b) begin
			for (i = 0; i < width_a/8; i = i + 1)
				if (byteena_b[i]) mem[address_b][i*8 +: 8] <= data_b[i*8 +: 8];
			q_b <= data_b;
		end else q_b <= mem[address_b];
	end
endmodule

// ------------------------------------------------------------------------------------------
// sdram_sim - behavioural replacement for rtl/sdram.sv (same channel semantics).
// The real controller runs at 4x the core clock and starts an access on the RISING EDGE of a
// channel's rd or wr (it does not re-trigger while the line stays high). ch0 has priority over
// ch1 over ch2. dout is registered and holds until the next access on that channel; a write
// also loads dout with the written byte. Real latency is 7 clk85 edges (~1.75 core clocks):
// a request raised at core edge T0 is visible to the core at edge T2. Here the access is done
// at T1 (when the edge is detected) and dout registered there, so the core also sees it at T2.
// Byte address = channel address (bank,row,col,byte), 32 MB.
// ------------------------------------------------------------------------------------------
module sdram_sim
(
	input             clk,
	input      [24:0] ch0_addr,
	input             ch0_rd,
	input             ch0_wr,
	input       [7:0] ch0_din,
	output reg  [7:0] ch0_dout,
	input      [24:0] ch1_addr,
	input             ch1_rd,
	input             ch1_wr,
	input       [7:0] ch1_din,
	output reg  [7:0] ch1_dout,
	input      [24:0] ch2_addr,
	input             ch2_rd,
	input             ch2_wr,
	input       [7:0] ch2_din,
	output reg  [7:0] ch2_dout,
	output reg        ch2_busy = 0     // ch2 only, like rtl/sdram.sv: high from the access until
	                                   // dout is valid (2 core clocks here, ~1.5 real); dout
	                                   // holds a decoy until then, so an early reader fails
);
	reg  [1:0] busy2 = 0;
	reg [24:0] ch2_a = 0;
	reg [7:0] mem [33554432] /*verilator public_flat_rd*/;   // fullsim.cpp --rec dumps CHR from it
	reg [2:0] old_rd = 0, old_wr = 0;
	wire [2:0] rd = {ch2_rd, ch1_rd, ch0_rd};
	wire [2:0] wr = {ch2_wr, ch1_wr, ch0_wr};
	wire [2:0] go = (rd & ~old_rd) | (wr & ~old_wr);

	always @(posedge clk) begin
		old_rd <= rd;
		old_wr <= wr;
		if (go[0]) begin
			if (wr[0]) begin mem[ch0_addr] <= ch0_din; ch0_dout <= ch0_din; end
			else ch0_dout <= mem[ch0_addr];
		end
		if (go[1]) begin
			if (wr[1]) begin mem[ch1_addr] <= ch1_din; ch1_dout <= ch1_din; end
			else ch1_dout <= mem[ch1_addr];
		end
		if (busy2 != 0) begin
			busy2 <= busy2 - 1'd1;
			if (busy2 == 2'd1) begin
				ch2_busy <= 0;
				ch2_dout <= mem[ch2_a];
			end
		end
		if (go[2]) begin
			if (wr[2]) begin mem[ch2_addr] <= ch2_din; ch2_dout <= ch2_din; end
			else begin
				ch2_a    <= ch2_addr;
				ch2_dout <= ~mem[ch2_addr];     // decoy until busy falls
				ch2_busy <= 1;
				busy2    <= 2'd2;
			end
		end
	end
endmodule

// ------------------------------------------------------------------------------------------
// T65 wrapper: GHDL emits the converted CPU as T65_ghdl with VHDL's port spelling; rtl/nes.v
// relies on Quartus' case-insensitive VHDL port binding (.mode, .res_n, .clk ...), which
// Verilog cannot do, so this wrapper restates the ports in nes.v's spelling.
// ------------------------------------------------------------------------------------------
module T65
(
	input   [1:0] mode,
	input         BCD_en,
	input         res_n,
	input         pwr_n,
	input         clk,
	input         enable,
	input         rdy,
	input         IRQ_n,
	input         NMI_n,
	output        R_W_n,
	output [15:0] A,
	input   [7:0] DI,
	output  [7:0] DO,
	output        Instrnew,
	input  [63:0] SaveStateBus_Din,
	input   [9:0] SaveStateBus_Adr,
	input         SaveStateBus_wren,
	input         SaveStateBus_rst,
	input         SaveStateBus_load,
	output [63:0] SaveStateBus_Dout
);
	wire [23:0] a24;
	assign A = a24[15:0];
	T65_ghdl cpu
	(
		.Mode(mode), .BCD_en(BCD_en), .Res_n(res_n), .Pwr_n(pwr_n), .Enable(enable), .Clk(clk),
		.Rdy(rdy), .Abort_n(1'b1), .IRQ_n(IRQ_n), .NMI_n(NMI_n), .SO_n(1'b1), .DI(DI),
		.SaveStateBus_Din(SaveStateBus_Din), .SaveStateBus_Adr(SaveStateBus_Adr),
		.SaveStateBus_wren(SaveStateBus_wren), .SaveStateBus_rst(SaveStateBus_rst),
		.SaveStateBus_load(SaveStateBus_load),
		.R_W_n(R_W_n), .Sync(), .EF(), .MF(), .XF(), .ML_n(), .VP_n(), .VDA(), .VPA(),
		.A(a24), .DO(DO), .Regs(), .NMI_ack(), .Instrnew(Instrnew),
		.SaveStateBus_Dout(SaveStateBus_Dout)
	);
endmodule
