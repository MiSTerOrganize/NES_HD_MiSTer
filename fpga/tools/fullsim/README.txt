fullsim - whole-core Verilator simulation of the NES core + HD pack engine
==========================================================================

The hardware side of the pixel comparison against Mesen 2's HD renderer. It runs the real
RTL of rtl/nes.v (CPU, PPU, APU, every mapper), GameLoader (taken from NES.sv), video.sv,
hd_stage2 (frame capture + watched addresses) and hd3_engine (stage 3: pack loader, ROM
patcher, dictionary, additions, resolve, render, scan-out, on the 85.9 MHz clock) behind
hd3_ddr, with the MiSTer framework replaced by a C++ testbench. Until 2026-10-20 it ran the
MVP engine (hd_engine / hd_ddr) instead; see VERIFIED RESULTS for which runs used which.

Nothing in rtl/, NES.sv, NES.qsf or files.qip is modified. Everything new lives here.

FILES
  build.sh            one-command build (LF line endings)
  sim_top.sv          top level: NES.sv's glue logic + all core instances
  sim_lib.sv          equivalents / stubs for the VHDL and vendor blocks (list below)
  fullsim.cpp         testbench: ioctl loading, joypad script, DDR3 model, PNG capture
  compare_frames.py   compare a reference PNG (e.g. Mesen screenshot) with fullsim frames
  obj/                build output (generated; safe to delete)

BUILD
  sh tools/fullsim/build.sh            -> tools/fullsim/obj/fullsim.exe (~1 min)
  sh tools/fullsim/build.sh --lint     Verilator lint only
  THREADS=n sh tools/fullsim/build.sh  multithreaded model (measured SLOWER: 0.13 vs 0.68
                                       frames/s at 4 threads - leave it at 1)
  Needs MSYS2 mingw64: ghdl, verilator 5.x, g++, zlib. MSYS2 `make` is not used (its TMP
  override breaks gcc on this box); the script drives verilator_bin.exe and g++ directly.

  Build steps:
   1. GHDL converts the T65 CPU (rtl/t65/*.vhd + rtl/bus_savestates.vhd for its package and
      eReg_SavestateV) to Verilog: ghdl -a --std=08 -fsynopsys -fexplicit, then
      ghdl synth --out=verilog T65. The script checks the result is not a hollow port-only
      shell (>= 5000 lines, >= 4 modules; it is ~11200 lines, 6 modules). The top module is
      renamed T65_ghdl and the file is wrapped in `begin_keywords "1364-2005" because GHDL
      emits signal names that are SystemVerilog keywords (break). A wrapper module T65 in
      sim_lib.sv restates the ports in rtl/nes.v's spelling: nes.v binds .mode/.res_n/.clk
      ... and relies on Quartus' case-insensitive VHDL port matching, which Verilog lacks.
   2. GameLoader is extracted from NES.sv with awk into obj/gameloader.sv on every build,
      so it always tracks NES.sv.
   3. FDS.sv, Sunsoft.sv and video.sv contain constant tables written as
      `wire [w] name[n] = '{...};` (a net array with an initialiser) which Quartus accepts
      and Verilator does not. Build-time copies in obj/patched/ turn exactly those 12
      declarations into `localparam logic`; the script fails if the count is not 12.
   4. sys/iir_filter.v is added (FDS.sv uses it). Waived Verilator checks, all of which
      Quartus tolerates: PROCASSWIRE (procedural assignment to `wire`), ASSIGNIN (ppu.sv
      declares sys_type inout, nes.v feeds it an input), plus the usual lint/style noise.

RUN
  tools/fullsim/obj/fullsim.exe --rom game.nes --frames N --out DIR [options]
    --hdp pack.hdp      load a format-3 HD pack (made by tools/hdp3_convert.py) through OSD
                        slot 4 BEFORE the ROM, so frame numbers match a run without a pack;
                        hd3_engine patches that ROM with the pack's section 14 as it loads
    --hd 0|1            the "HD Pack" OSD option (status[88]); default 1 with --hdp
    --input script.txt  joypad 1, lines "<frame> <buttons>"; buttons = 0, a hex mask, or names
                        joined by '+': RIGHT LEFT DOWN UP A B SELECT START. A line holds from
                        the start of that frame until the next line. '#' starts a comment.
    --save LIST         "all", "120,200" or "every:10" (default: the last frame only)
    --palette FILE      palette for nes_*.png (default Palette/Kitrinx34.pal)
    --ddr-lat N         DDR3 read latency in core clocks (default 12)
    --ddr-busy P        percent of clocks DDRAM_BUSY is high (default 0)
    --xoff N            screen x = PPU cycle - N for nes_*.png (default 2, see below)
    --rec               stage-2 frame record (see fullsim.cpp's header): col_/rec_/chr_FFFF.bin
                        per saved frame, checked by check_record.py, and with a pack
                        hdv_FFFF.rgb - the HD picture drawn from frame F's record - for
                        tools/sim3/check_render.py against hdref
    --watch LIST        stage-2 watched-address snapshot, checked by check_watch.py
    --ex-sprites        the core's "Extra sprites" OSD option
    --nolimit           disableSpriteLimit without a pack (a pack's own option drives it anyway)

  Output per saved frame F:
    nes_FFFF.png  256x240  the PPU colour index (sim_top.color, 6 bits) through the palette
                           file. Emphasis bits are NOT applied.
    vid_FFFF.png  256x240  rtl/video.sv's RGB output (built-in Kitrinx palette, emphasis
                           applied, hide_overscan "full 240 lines"). Independent cross-check:
                           the run prints "nes vs video.sv pixels differing" per frame; it
                           should be 0 unless the game uses colour emphasis.
    hd_FFFF.png   512x480  hd3_engine scan-out R/G/B, assembled from its HB/VB (one pixel per
                           core clock, two output lines per NES line). Only with a pack loaded
                           and enabled. Written when the HD frame ends, which is during NES
                           frame F; it is drawn from frame F-1's record.
  At the end of a run with a pack: hd3_engine's counters (frames drawn / dropped, ADDs
  aborted, underflow, overrun, dictionary overflow) and the DDR3 bursts / qwords.

  Frame numbering: frame 1 is the first frame that starts (PPU scanline -> 0) after the NES
  reset is released. MEASURED against Mesen 2.1.1 headless (smb.nes, no pack): fullsim frame F
  = Mesen frame F+2 (fullsim 32 == Mesen 34, the frame the SMB title is drawn half-way, 0
  differing pixels palette-independently; fullsim 33 == Mesen 35). Mesen's screenshot uses its
  own default palette, not Kitrinx34, so compare with compare_frames.py (palette-independent by
  default) or switch Mesen to Kitrinx34.

  Pixel alignment (--xoff 2): video.sv shows, in column k, the colour the PPU outputs when
  its cycle counter is k+2 (one register stage for the pixel, three for the blank window).
  The nes_*.png picture uses the same mapping; the per-frame "nes vs video.sv" count proves it.

  compare:
    python tools/fullsim/compare_frames.py mesen.png OUTDIR [nes|vid|hd] [first] [last] [--exact]

WHAT IS MODELLED HOW
  Two clocks: the core on the 21.477 MHz core clock (NTSC), hd3_engine, hd3_ddr and the DDR3
  model on clk_f = 4 x that (85.9 MHz, NES.sv's clk85, which is also its DDRAM_CLK); the core
  clock rises on every fourth clk_f edge, as the shared PLL gives. The SDRAM controller's own
  4x clock and CLK_VIDEO are not simulated (see sdram_sim below).

  sdram_sim (sim_lib.sv) replaces rtl/sdram.sv: a 32 MB byte array with the same channel
  semantics - an access starts on the RISING EDGE of a channel's rd or wr (holding the line
  high does not re-trigger), a write also loads dout with the written byte, dout holds until
  the next access. The real controller (4x clock) delivers data 7 clk85 edges (~1.75 core
  clocks) after a request raised at core edge T0, i.e. the core sees it at edge T2; the model
  reads at T1 and registers dout there, so the core also sees it at T2. Not modelled: the
  real controller's same-word read cache (it returns the same bytes), refresh, and the
  ch0-before-ch1 serialisation when both raise a request on the same clock (the core is
  designed so CPU and PPU requests do not collide). ch2 (backup RAM / savestates) is unused.

  DDR3 (fullsim.cpp): Avalon-style, 64-bit, sparse memory on clk_f, in-order burst return
  after --ddr-lat core clocks (scaled to clk_f), optional random BUSY.

  ioctl (fullsim.cpp): hps_io-style - ioctl_download high, then one byte per ioctl_wr strobe
  with ioctl_addr = byte index, waiting while ioctl_wait (loader ioctl_wait | hd_load_wait).
  The ROM goes in as ioctl_index 8'h01 (slot "FS,NESFDSNSF", .nes), the pack as 8'h04.

  OSD status: every OSD option at its default (all status bits 0, as a fresh MiSTer.cfg):
  System Type Auto (NTSC for plain iNES), no extra sprites, mask edges off, no cheats, no
  peripherals, no multitap; FDS auto-eject and fast-load on (FDS only). See sim_top.sv for the
  exact values fed to each NES port. Only "HD Pack" and the
  joystick are inputs. Joypad 1 uses the real 4016 shift register from NES.sv; joypad 2 is idle.

  video.sv is instantiated (with hide_overscan = "full") because its hold_reset output is
  part of NES.sv's reset_nes; it also provides the vid_*.png reference picture.

STUBS AND EQUIVALENTS (sim_lib.sv)
  eReg_SavestateV  FULL port of rtl/bus_savestates.vhd (not a stub): its Dout supplies the
                   reset value of many core registers in normal operation.
  savestates       stub of the IDLE state only: reset_ss, reset_delay and BUS_rst follow
                   reset_in one clock later, exactly as the VHDL does in IDLE; save/load never
                   assert here so the VHDL never leaves IDLE. Cycle-exact for this use.
  statemanager     stub, all outputs 0: with save = load = rewind_on = 0 the VHDL never
                   raises any of them.
  eseopll          (VRC7 FM synth, rtl/SOUND/OPLL) stub: silent output, ack = req. Audio
                   only; VRC7 games still run. Video is unaffected.
  spram, spram_sz,
  dpram            behavioural altsyncram equivalents: registered address, one clock read
                   latency, read-during-write on the same port returns the new data,
                   byte enables honoured. .mif init files are NOT loaded (the only one in the
                   simulated hierarchy is video.sv's custom palette RAM, which is not used).
  T65              thin port-name wrapper around the GHDL-converted CPU. SO_n and Abort_n
                   are tied high (Abort_n is unused in T65.vhd; SO_n only acts on a falling
                   edge, which a constant never produces - in Quartus they are unconnected).
  Not instantiated: NES.sv's FDS BIOS RAM and NSF player ROM (no FDS/NSF in this sim),
  zapper, keyboard, Miracle piano, composite decoder, cheats loader, backup RAM paths.

SPEED (measured, this box, smb.nes, no pack)
  ~0.68 NES frames/s simulated (~0.27 MHz core clock, ~1.2% of real time): 200 frames take
  ~5 minutes. Every mapper in cart.sv is evaluated every clock, as on the FPGA.

VERIFIED RESULTS - hd3_engine (2026-10-21)
  Metroid (USA).nes + the a034 pack converted by hdp3_convert with its mmm.ips (section 14,
  75,642,368 bytes), 400 frames, --save every:100 --rec:
  - pack accepted, 9,455,296 qwords in DDR3; no $readmem warnings (HD3_HEX_PROJECT build).
  - hd3_engine counters: 400 frames drawn, 0 dropped, 0 ADDs aborted, 0 underflow, 0 overrun,
    0 dictionary overflow. nes vs video.sv: 0 differing pixels on every saved frame.
  - tools/sim3/check_render.py on hdv_0000..0300 against hdref: 0 of 245,760 pixels differ
    on all four (7,680 BG + 2,512 sprite lookups per frame from 100 on).
  - Against Mesen 2.1.1 with the same pack and ROM, compared by exact RGB (both draw the
    pack's own art, so the palette question does not arise): hd 100/300/400 == Mesen
    102/302/402 with 0 differing pixels. hd 200 differs from Mesen 202 (2,447 px: 1,658 by
    1-4 levels, 789 by 9-13) and equals Mesen 201 exactly: the title
    animation steps on a frame where the two runs are one frame apart, not a rendering
    difference. Mesen randomises power-on RAM; fullsim zeroes it.
  5.2 s of simulation per frame with the pack (0.19 frames/s; 2,071 s for 400 frames, plus
  ~51 min streaming the 75 MB pack into DDR3 before frame 0).

VERIFIED RESULTS (2026-10-15, MVP engine hd_engine / hd_ddr and a format-2 pack - history)
  smb.nes, no pack, 210 frames: frame 200 is the SMB title screen. nes_*.png == vid_*.png on
  every frame (0 differing pixels). Against Mesen 2.1.1 (palette-independent compare):
  fullsim 32/33/119 == Mesen 34/35/121 with 0 differing pixels, i.e. fullsim F = Mesen F+2;
  the reference ../NES_HDPack_testdata/tools/mesen2/t1.png (Mesen frame 120) == fullsim 118.
  smb_testpack converted with tools/hdp_convert.py, --hd 1, 40 frames: pack accepted, 65536
  atlas qwords in DDR3, 74645 bursts read; hd_0040.png (512x480) == Mesen frame 42 with the
  same pack, 0 differing pixels palette-independently. An --exact compare differs (133663 px)
  only because Mesen used its own default palette, not Kitrinx34.

KNOWN LIMITATIONS
  - NTSC only (no PAL/Dendy PLL reconfiguration).
  - Power-on RAM is all zero (Mesen randomises by default; SMB reports reads of uninitialised
    RAM in Mesen but the pictures still match).
  - Emphasis is not applied to nes_*.png (vid_*.png has it).
  - Audio is produced (sim_top.sample) but not written anywhere.
