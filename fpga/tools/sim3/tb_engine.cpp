// Verilator testbench for hd3_engine.sv (the whole stage-3 HD engine) on its two clocks.
//
// clk (core) and clk_f (HD, 4 x clk) tick together from one loop: every clk edge is also a
// clk_f edge, as from the PLL. A DDR3 model (random busy, latency, bursts in issue order)
// serves hd3_ddr. The run:
//   1. the .hdp is streamed in through the OSD load port, one byte per core clock, and must
//      be accepted (pack_ok, reject 0);
//   2. NES frames are generated at the real line rate (1364 core clocks per line, 262 lines):
//      tap line_done/line_y at cycle 256 of every line, frame_num advanced at line 239's
//      line_done, watch_done one line later; frame i's record stream (the same qword stream
//      hd_capture writes; tb_render.cpp frame_stream) is offered on the record-writer port
//      from the pre-render line of frame i, group g from line g - 1, honouring cw_ready;
//   3. the engine's own scan-out is captured: the visible picture of NES frame i + 1 must be
//      HD frame i. Each captured frame is cropped to the overscan window and written as
//      <prefix>_<name>.rgb for check_render.py; pixels outside the window must be black.
// Checks in the testbench: the pack is accepted, every frame's stream drains before the next
// frame starts, the engine draws every frame (frames_drawn), drops none, sets no underflow or
// overrun, and the picture outside the window is black.
// Optional savestate traffic (--ss P): random reads and writes on the savestate channel to a
// scratch region throughout, every read checked against the model - the clk -> clk_f crossing.
//
//   tb_engine.exe <file.hdp> <prefix> --game-ram G --frame BANK:rec.bin [--frame ...]
//                 [--busy P] [--lat N] [--seed S] [--ss P] [--lines 262|312]
//                 [--watch-line L] [--expect-late 1] [--busy-burst N]
//                 [--rom F --rom-when after|before --rom-expect F --rom-result R --rom-loads N
//                  --pack2 F --dl-mid-access 1 --stale-cmd R:A
//                  --arm 1|0|junk|badlen|badlen0]   (ROM patching; see "ROM patching" below)
// --lines 312 is PAL timing (70 lines of vblank); --watch-line moves watch_done (the watched
// values of the bank answer noise from scanline 240 until then); --expect-late 1 is the slow
// DDR3 run, which must report underflow.
#include "Vhd3_engine.h"
#include "Vhd3_engine___024root.h"
#include "../armdec/romfix_arm.h"
#include "verilated.h"
#include <cstdio>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <vector>
#include <deque>
#include <random>
#include <string>
#include <unordered_map>
#include <algorithm>

double sc_time_stamp() { return 0; }

static const uint64_t REC_BASE = 0xC000000;
static const int LINE = 1364;               // core clocks per NES line
static int NLINES = 262;                    // --pal: 312 (70 lines of vblank instead of 20)

static std::mt19937 rng;
static int pct() { return std::uniform_int_distribution<int>(0, 99)(rng); }

// ---- DDR3 contents: 64K-qword pages ----
static std::unordered_map<uint64_t, std::vector<uint64_t>> pages;
static uint64_t &dq(uint64_t qa) {
	auto &p = pages[qa >> 16];
	if (p.empty()) {
		p.assign(65536, 0);
		// the ROM patcher's staging + target areas (bytes 0xC800000-0xCFFFFFF) start with
		// garbage, as real DDR3 does: anything it reads before writing shows up
		if ((qa >> 16) >= 0x190 && (qa >> 16) < 0x1A0)
			for (uint64_t k = 0; k < 65536; k++) {
				uint64_t x = ((qa >> 16) << 16 | k) * 0x9E3779B97F4A7C15ull;
				p[k] = x ^ (x >> 29);
			}
	}
	return p[qa & 0xFFFF];
}
static void dwr(uint64_t qa, uint64_t d, int be) {
	uint64_t &c = dq(qa);
	for (int b = 0; b < 8; b++)
		if (be >> b & 1) c = (c & ~(0xFFull << (8 * b))) | (d & (0xFFull << (8 * b)));
}

struct Frame { int bank; std::string path, name; std::vector<uint8_t> rec, watch; };
struct Q { uint32_t a; uint64_t d; uint32_t g; uint8_t be = 0xFF; };
static uint64_t rq(const std::vector<uint8_t> &r, size_t off) { uint64_t v; memcpy(&v, &r[off], 8); return v; }

// the record qword stream of one frame, exactly tb_render.cpp's (keep in step)
static std::vector<Q> frame_stream(const Frame &f) {
	const uint32_t base = (uint32_t)(REC_BASE / 8) + (uint32_t)f.bank * 0x20000;
	std::vector<Q> s;
	uint32_t g = 0;
	auto lq = [&](int y, int o) { return base + 0x8000u + (uint32_t)y * 256 + (uint32_t)o; };
	auto line = [&](int y) { return (size_t)0x40000 + (size_t)y * 2048; };
	auto nspan = [&](int y) { return (int)std::min<uint64_t>((rq(f.rec, line(y)) >> 32) & 0xFF, 34); };
	auto nfet = [&](int y) { return (int)((rq(f.rec, line(y)) >> 48) & 0xFF); };
	auto spans = [&](int y, int from, int to) {
		for (int k = from; k < to && k < nspan(y); k++) {
			s.push_back({lq(y, 8 + 2 * k), rq(f.rec, line(y) + 64 + 16 * k), g});
			s.push_back({lq(y, 9 + 2 * k), rq(f.rec, line(y) + 72 + 16 * k), g});
		}
	};
	auto sprites = [&](int y) {
		for (int i = 0; i < nfet(y) && i < 64; i++) {
			s.push_back({lq(y, 80 + 2 * i), rq(f.rec, line(y) + 640 + 16 * i), g});
			s.push_back({lq(y, 81 + 2 * i), rq(f.rec, line(y) + 648 + 16 * i), g});
		}
	};
	sprites(0);
	spans(0, 0, 2);
	for (int y = 0; y < 240; y++) {
		g = (uint32_t)y + 1;
		for (int q = 0; q < 128; q++)
			s.push_back({base + (uint32_t)y * 128 + (uint32_t)q, rq(f.rec, (size_t)y * 1024 + 8 * q), g});
		spans(y, 2, 34);
		for (int q = 0; q < 4; q++) s.push_back({lq(y, q), rq(f.rec, line(y) + 8 * q), g});
		if (y < 239) { sprites(y + 1); spans(y + 1, 0, 2); }
	}
	s.push_back({base + 0x1E000, rq(f.rec, 0xF0000), g});
	return s;
}

static bool load(const std::string &p, std::vector<uint8_t> &v) {
	FILE *f = fopen(p.c_str(), "rb");
	if (!f) { perror(p.c_str()); return false; }
	fseek(f, 0, SEEK_END); long sz = ftell(f); fseek(f, 0, SEEK_SET);
	v.resize((size_t)sz);
	bool ok = fread(v.data(), 1, (size_t)sz, f) == (size_t)sz;
	fclose(f);
	return ok;
}

static Vhd3_engine *t;
static int busy = 0, lat = 12, busy_burst = 1;
// --dl-mid-access: the second pack's download starts while the ROM patcher has a DDR3 read in
// flight, and that read's answer is held back (hold_read) through the whole download and 2000
// core clocks past it - so it arrives only after the patcher, its pack changed, has asked for
// its next access: the case hd3_romfix's `drop` exists for. The loader only writes, so holding
// the read queue holds nothing else.
static bool dl_mid = false, hold_read = false;
static uint64_t fcyc = 0;                    // clk_f cycles
struct RB { uint64_t qa; int beats, beat; uint64_t at; };
static std::deque<RB> ddr_q;
static const std::vector<uint8_t> *watch_of[2] = {nullptr, nullptr};
static int fails = 0;
static void expect(bool c, const char *what, long long a = 0, long long b = 0) {
	if (!c) { if (fails < 30) printf("FAIL: %s (%lld %lld)\n", what, a, b); fails++; }
}

static bool watch_noise[2] = {false, false};   // the bank is being rewritten: answer noise
static uint8_t watch_val(int bank, uint32_t i) {
	if (watch_noise[bank & 1]) return (uint8_t)rng();
	const std::vector<uint8_t> *w = watch_of[bank & 1];
	if (!w) return 0;
	uint32_t n; memcpy(&n, &(*w)[4], 4);
	return i < n ? (*w)[8 + 4 * n + i] : 0;
}

// savestate traffic model (core clock)
static int ss_pct = 0;
static bool ss_busy = false, ss_rnw = false;
static uint64_t ss_qa = 0, ss_d = 0; static int ss_be = 0;
static std::unordered_map<uint64_t, uint64_t> ss_mem;   // expected contents of the scratch region
static long ss_n = 0, ss_wait = 0;
static const uint64_t SS_BASE = 0xD000000;               // byte offset of the scratch region: past the
                                                         // pack (< 0xC000000) and the records

// one clk_f clock; core = this clk_f edge is also a clk rising edge
static void ftick(bool core) {
	// DDR3 model, before the edge. --busy-burst N: a busy period, once it starts, lasts N clk_f
	// clocks (a refresh, another master), so the engine's crossings fill and must hold back
	static int burst_left = 0;
	if (burst_left > 0) { t->DDRAM_BUSY = 1; burst_left--; }
	else {
		t->DDRAM_BUSY = busy && pct() < busy;
		if (t->DDRAM_BUSY && busy_burst > 1) burst_left = busy_burst - 1;
	}
	t->DDRAM_DOUT_READY = 0;
	if (!hold_read && !ddr_q.empty() && ddr_q.front().at <= fcyc && !(busy && pct() < busy / 2)) {
		RB &b = ddr_q.front();
		t->DDRAM_DOUT = dq(b.qa + b.beat);
		t->DDRAM_DOUT_READY = 1;
		if (++b.beat == b.beats) ddr_q.pop_front();
	}
	t->eval();
	// pacing invariant (hd3_engine line_ok): RENDER writes ring line y into slot y mod 8, and that
	// slot must already have been shown. While the scan-out still shows the frame before the one
	// being drawn, no ring write at all; while it shows the frame being drawn at line d, only lines
	// up to d + 7; in the blanking before it, only lines 0-7. Checked on every write, so a
	// violation is caught even when the overwritten line happens to look the same.
	if (t->rootp->hd3_engine__DOT__out_v) {
		int d = t->rootp->hd3_engine__DOT__scan__DOT__disp_y, y = t->rootp->hd3_engine__DOT__out_y;
		int fd = (t->rootp->hd3_engine__DOT__tgt - t->rootp->hd3_engine__DOT__scan__DOT__dcount) & 3;
		if (fd == 1) expect(false, "ring written while the frame before is still shown", y, d);
		else if (fd == 0) {
			expect(d < 240 ? y <= d + 7 : y < 8, "ring written ahead of the scan-out", y, d);
			// and a line the scan-out decided to show must have been complete: never written again
			// while it is on screen (a late frame's line is shown whole or blanked whole)
			if (d < 240 && y == d && t->rootp->hd3_engine__DOT__scan__DOT__l_ok
			    && t->rootp->hd3_engine__DOT__scan__DOT__hcnt != 0)
				expect(false, "ring line written while it is being shown", y, d);
		}
	}
	bool take = (t->DDRAM_RD || t->DDRAM_WE) && !t->DDRAM_BUSY;
	bool rd = t->DDRAM_RD;
	uint64_t a = t->DDRAM_ADDR & 0x1FFFFFFF;
	int burst = t->DDRAM_BURSTCNT; uint64_t din = t->DDRAM_DIN; int be = t->DDRAM_BE;
	uint8_t v1 = watch_val(t->w1_bank, t->w1_idx), v2 = watch_val(t->w2_bank, t->w2_idx);

	t->clk_f = 1;
	if (core) t->clk = 1;
	t->eval();
	fcyc++;
	if (take) {
		expect((a >> 25) == 3, "DDR3 address outside the window", (long long)a);
		uint64_t qa = a & 0x1FFFFFF;
		if (rd) ddr_q.push_back(RB{qa, burst, 0, fcyc + (uint64_t)lat});
		else { expect(burst == 1, "write burst", burst); dwr(qa, din, be); }
	}
	t->w1_q = v1; t->w2_q = v2;
	t->clk_f = 0;
	t->eval();
}

// ROM patching (hd3_romfix): --rom FILE is downloaded as an NES ROM, before or after the pack
// (--rom-when before|after, default after). Every download the CORE sees (pass-through or the
// patcher's replay) is captured; the last must equal --rom-expect, there must be --rom-loads of
// them (1 = left unpatched, 2 = replayed) and rom_result must end as --rom-result. The core's
// loader is modelled by a 2-5 clock wait after every byte it takes.
static std::string rom_path, rom_expect_path, pack2_path;   // --pack2: loaded after the ROM settles
static bool rom_before = false;
static int rom_want_result = -1, rom_want_loads = -1;
static std::vector<std::vector<uint8_t>> rom_sessions;
static bool rom_prev_odl = false, rom_free_gap = false, rom_watch_gap = false;
static int rom_cwait = 0;

// The ARM half of the ROM patcher (tools/armdec/romfix_arm.c, linked in): it polls the status
// qword every 200-2000 core clocks; a status it has not answered is decided on what DDR3 holds
// THEN (the staged ROM, the pack's section 14), and the target plus the command are written
// 500-4500 core clocks later, target first - as hdarm_daemon.c does on the device.
static rf_state arm_rf;
static std::vector<uint8_t> arm_tgt(RF_MAXB);
static uint32_t arm_tlen = 0;
static uint64_t arm_cmd = 0, arm_due = 0, arm_poll_at = 0;
static bool arm_sched = false;
static long arm_cmds = 0;
// --arm 1 (default) answers; 0 never answers (the FPGA's timeout, result 6); junk writes a decoy
// command first and leaves it 40000 clocks - longer than either FPGA poll period - before the real
// one. The four decoys are the four ways a command is not for the FPGA's current question (wrong
// magic, rseq, aseq, or the id it last carried out); each would replay the original ROM with
// result 7, which no case expects
static int arm_mode = 1;
static int stale_r = -1, stale_a = -1;             // --stale-cmd
static int arm_phase = 0;                          // decoys written for the pending command
static void arm_step(uint64_t now) {
	if (arm_sched) {
		if (now < arm_due) return;
		if (arm_mode == 2 && arm_phase < 4) {          // all four decoys, then the command
			uint64_t s = dq(RF_ST_OFF / 8);
			uint64_t d = 0xC7ull << 56 | (uint64_t)RF_RSEQ(s) << 48 | (uint64_t)RF_ASEQ(s) << 40 |
			             (uint64_t)(uint8_t)(RF_LASTID(s) + 0x55) << 32 | 2ull << 30 | 7ull << 27;
			switch (arm_phase) {
			case 0: d ^= 1ull << 56; break;                                        // magic
			case 1: d = (d & ~(0xFFull << 48)) | (uint64_t)(uint8_t)(RF_RSEQ(s) - 1) << 48; break;
			case 2: d = (d & ~(0xFFull << 40)) | (uint64_t)(uint8_t)(RF_ASEQ(s) - 1) << 40; break;
			default: d = (d & ~(0xFFull << 32)) | (uint64_t)RF_LASTID(s) << 32; break;   // repeat
			}
			dwr(RF_CMD_OFF / 8, d, 0xFF);
			arm_phase++; arm_due = now + 40000;
			return;
		}
		arm_phase = 0;
		for (uint32_t i = 0; i < arm_tlen; i += 8) {
			uint64_t v = 0; int be = 0;
			for (uint32_t k = 0; k < 8 && i + k < arm_tlen; k++) { v |= (uint64_t)arm_tgt[i + k] << (8 * k); be |= 1 << k; }
			dwr((RF_TGT_OFF + i) / 8, v, be);
		}
		uint64_t c = arm_cmd;
		// --arm badlen / badlen0: a "replay the target" command whose length is past the 4 MB
		// target area, or 0 - not one romfix_arm.c writes; the FPGA must refuse it (result 3)
		if ((arm_mode == 3 || arm_mode == 4) && (c >> 30 & 3) == 1)
			c = (c & ~0xFFFFFFull) | (arm_mode == 3 ? (uint64_t)RF_MAXB + 8 : 0);
		dwr(RF_CMD_OFF / 8, c, 0xFF);
		arm_sched = false; arm_cmds++;
		return;
	}
	if (arm_mode == 0) return;
	if (now < arm_poll_at) return;
	arm_poll_at = now + 200 + rng() % 1800;
	rf_session_check(&arm_rf, dq(RF_CMD_OFF / 8));    // as hdarm_daemon.c does, first
	uint64_t s = dq(RF_ST_OFF / 8);
	if (!rf_pending(&arm_rf, s)) return;
	uint32_t L = RF_LEN(s) > RF_MAXB ? RF_MAXB : RF_LEN(s);
	std::vector<uint8_t> rom(L + 8);
	for (uint32_t i = 0; i < L; i += 8) { uint64_t v = dq((RF_SRC_OFF + i) / 8); memcpy(&rom[i], &v, 8); }
	// section 14 of the pack in DDR3 (file byte f at window byte f): header 0xF0 offset, 0xF4 size
	auto rd8 = [&](uint64_t f) { return (uint8_t)(dq(f / 8) >> (8 * (f & 7))); };
	auto rd32 = [&](uint64_t f) { return (uint32_t)rd8(f) | rd8(f + 1) << 8 | rd8(f + 2) << 16 | (uint32_t)rd8(f + 3) << 24; };
	uint32_t o14 = rd32(0xF0), n14 = rd32(0xF4);
	std::vector<uint8_t> s14(n14);
	for (uint32_t i = 0; i < n14; i++) s14[i] = rd8((uint64_t)o14 + i);
	if (rf_decide(&arm_rf, s, rom.data(), n14 ? s14.data() : nullptr, n14, arm_tgt.data(), &arm_tlen, &arm_cmd)) {
		arm_sched = true;
		arm_due = now + 500 + rng() % 4000;
	}
}
// nothing left for the ARM to answer or write
// (--arm 0: a silent ARM leaves its question pending for ever, so it is never "quiet" by that
// test; it has nothing to write, which is what the settle check needs)
static bool arm_quiet() {
	return !arm_sched && (arm_mode == 0 || !rf_pending(&arm_rf, dq(RF_ST_OFF / 8)));
}

static void rom_monitor(bool cw_edge) {  // after a core clock edge; cw_edge = core_wait at it
	bool odl = t->rom_o_dl && t->rom_o_ft == 0x41;   // a ROM-type download (not the pack's)
	if (odl && !rom_prev_odl) rom_sessions.emplace_back();
	// a replay write issued on an edge where the core's loader was busy would be lost
	if (t->rom_o_wr && cw_edge && t->rootp->hd3_engine__DOT__romfix__DOT__rp)
		expect(false, "replay write while the core was busy", (long long)t->rom_o_addr);
	if (odl && t->rom_o_wr) {
		auto &s = rom_sessions.back();
		expect(t->rom_o_addr == s.size(), "core-side address", (long long)t->rom_o_addr, (long long)s.size());
		s.push_back(t->rom_o_din);
		rom_cwait = 2 + (int)(rng() % 19);        // 2-20: sometimes longer than the replay's gap
	}
	// between the end of the OSD download and the replay the core must stay in reset
	if (rom_watch_gap && !odl && !t->rom_hold) rom_free_gap = true;
	rom_prev_odl = odl;
}

int main(int argc, char **argv) {
	if (argc < 3) { fprintf(stderr, "see the header of tb_engine.cpp for usage\n"); return 2; }
	int game_ram = -1; unsigned seed = 1;
	int watch_line = 241;      // scanline whose clock 0 carries watch_done (hd_watch is done)
	int expect_late = 0;       // 1: a deliberately slow DDR3 - underflow MUST be reported
	std::vector<Frame> frames;
	for (int i = 3; i < argc; i++) {
		std::string o = argv[i];
		if (i + 1 >= argc) { fprintf(stderr, "option %s needs a value\n", o.c_str()); return 2; }
		std::string v = argv[++i];
		if (o == "--game-ram") game_ram = atoi(v.c_str());
		else if (o == "--busy") busy = atoi(v.c_str());
		else if (o == "--lat") lat = atoi(v.c_str());
		else if (o == "--seed") seed = (unsigned)atoi(v.c_str());
		else if (o == "--ss") ss_pct = atoi(v.c_str());
		else if (o == "--watch-line") watch_line = atoi(v.c_str());
		else if (o == "--lines") NLINES = atoi(v.c_str());
		else if (o == "--busy-burst") busy_burst = atoi(v.c_str());
		else if (o == "--expect-late") expect_late = atoi(v.c_str());
		else if (o == "--rom") rom_path = v;
		else if (o == "--rom-when") rom_before = (v == "before");
		else if (o == "--rom-expect") rom_expect_path = v;
		else if (o == "--rom-result") rom_want_result = atoi(v.c_str());
		else if (o == "--rom-loads") rom_want_loads = atoi(v.c_str());
		else if (o == "--pack2") pack2_path = v;
		else if (o == "--dl-mid-access") dl_mid = atoi(v.c_str()) != 0;
		else if (o == "--arm") arm_mode = v == "junk" ? 2 : v == "badlen" ? 3 : v == "badlen0" ? 4 : atoi(v.c_str());
		else if (o == "--stale-cmd") {
			// R:A - DDR3 already holds, at power-up, the last session's command "replay the
			// target" for question {rseq R, aseq A}, id 1, over a target of 0x5A bytes (a core
			// reload keeps DDR3). The FPGA must clear it before its first question, or it
			// replays the junk. Its length is the --rom file's (set after the options are read)
			size_t c = v.find(':');
			if (c == std::string::npos) { fprintf(stderr, "--stale-cmd RSEQ:ASEQ\n"); return 2; }
			stale_r = atoi(v.substr(0, c).c_str()); stale_a = atoi(v.substr(c + 1).c_str());
		}
		else if (o == "--frame") {
			size_t c = v.find(':');
			if (c == std::string::npos) { fprintf(stderr, "--frame BANK:file\n"); return 2; }
			Frame f; f.bank = atoi(v.substr(0, c).c_str()) & 1; f.path = v.substr(c + 1);
			if (!load(f.path, f.rec) || f.rec.size() < 0x100000) { fprintf(stderr, "%s: bad record\n", f.path.c_str()); return 2; }
			f.rec.resize(0x100000);
			std::string wp = f.path;
			size_t k = wp.rfind("rec_");
			if (k == std::string::npos) { fprintf(stderr, "%s: not a rec_FFFF.bin\n", f.path.c_str()); return 2; }
			f.name = wp.substr(k + 4, wp.size() - k - 8);
			wp.replace(k, 4, "watch_");
			if (!load(wp, f.watch) || f.watch.size() < 8 || memcmp(f.watch.data(), "NWAT", 4)) { fprintf(stderr, "%s: bad watch file\n", wp.c_str()); return 2; }
			frames.push_back(f);
		} else { fprintf(stderr, "unknown option %s\n", o.c_str()); return 2; }
	}
	if (game_ram < 0 || (frames.empty() && rom_path.empty())) { fprintf(stderr, "need --game-ram and --frame (or --rom)\n"); return 2; }
	for (size_t i = 0; i < frames.size(); i++)
		if (frames[i].bank != (int)(i & 1)) { fprintf(stderr, "frame %zu: the engine writes bank %zu, the run says %d\n", i, i & 1, frames[i].bank); return 2; }
	rng.seed(seed);

	if (stale_r >= 0) {
		std::vector<uint8_t> r;
		if (rom_path.empty() || !load(rom_path, r) || r.empty() || r.size() > RF_MAXB) {
			fprintf(stderr, "--stale-cmd needs a --rom of 1..%u bytes\n", (unsigned)RF_MAXB);
			return 2;
		}
		for (uint32_t i = 0; i < r.size(); i += 8) dwr((RF_TGT_OFF + i) / 8, 0x5A5A5A5A5A5A5A5Aull, 0xFF);
		dwr(RF_ST_OFF / 8, 0xA6ull << 56 | (uint64_t)(uint8_t)stale_r << 48 | (uint64_t)(uint8_t)stale_a << 40 |
		    1ull << 27 | r.size(), 0xFF);
		dwr(RF_CMD_OFF / 8, 0xC7ull << 56 | (uint64_t)(uint8_t)stale_r << 48 | (uint64_t)(uint8_t)stale_a << 40 |
		    1ull << 32 | 1ull << 30 | 1ull << 27 | r.size(), 0xFF);
	}

	std::vector<uint8_t> pack;
	if (!load(argv[1], pack)) return 2;
	uint32_t opt; memcpy(&opt, &pack[12], 4);
	int ov[4];                                 // top, right, bottom, left
	for (int k = 0; k < 4; k++) { int32_t v; memcpy(&v, &pack[0x10 + 4 * k], 4); ov[k] = std::min(255, std::max(0, (int)v)); }
	int img_h = std::max(0, (240 - ov[2] - ov[0]) * 2), img_w = std::max(0, (256 - ov[1] - ov[3]) * 2);

	t = new Vhd3_engine;
	t->clk = 0; t->clk_f = 0; t->reset = 1; t->enable = 1;
	t->load_active = 0; t->load_wr = 0; t->cart_no_chr_rom = (game_ram == 1) ? 1 : 0;
	t->cw_valid = 0; t->frame_num = 0; t->watch_done = 0;   // capture writes bank frame_num[0]
	t->line_done = 0; t->line_y = 0;
	t->ss_req = 0; t->DDRAM_BUSY = 0; t->DDRAM_DOUT_READY = 0;
	t->rom_dl = 0; t->rom_is_nes = 0; t->rom_wr = 0; t->rom_ft = 0; t->rom_addr = 0; t->rom_core_wait = 0;
	// the scan-out ring starts with garbage: on hardware it holds whatever an earlier pack drew
	// (a pack with another overscan window, or another game), so every pixel shown must have been
	// drawn for this frame or masked - never left over
	for (int i = 0; i < 2048; i++)
		for (int w = 0; w < 3; w++) t->rootp->hd3_engine__DOT__scan__DOT__ring[i][w] = (uint32_t)rng();
	t->eval();

	// core-clock driver state
	uint64_t ccyc = 0;
	auto ctick = [&]() {                       // one core clock = four clk_f clocks
		t->rom_core_wait = rom_cwait > 0;
		if (rom_cwait > 0) rom_cwait--;
		// savestate traffic (every clock, so it also meets the ROM patcher on the shared
		// crossing); between accesses the request fields carry noise, so the crossing must take
		// them at the request, not later
		t->ss_req = 0;
		if (ss_pct) {
			t->ss_rnw = rng() & 1; t->ss_addr = rng() & 0x7FFFFFF;
			t->ss_din = ((uint64_t)rng() << 32) | rng(); t->ss_be = rng() & 0xFF;
		}
		if (ss_pct && !ss_busy && pct() < ss_pct) {
			ss_busy = true; ss_wait = 0; ss_rnw = pct() < 50; ss_qa = SS_BASE / 8 + (rng() % 512);
			ss_d = ((uint64_t)rng() << 32) | rng(); ss_be = rng() & 0xFF;
			t->ss_req = 1; t->ss_rnw = ss_rnw; t->ss_addr = (uint32_t)(ss_qa << 2);
			t->ss_din = ss_d; t->ss_be = ss_be;
		}
		bool cw_edge = t->rom_core_wait;
		ftick(true);
		rom_monitor(cw_edge);
		ftick(false);
		t->clk = 0;
		ftick(false);
		ftick(false);
		ccyc++;
		arm_step(ccyc);
		// ddram.sv's savestate engine waits for every access, so one must finish in bounded
		// time (the channel has priority over everything else)
		// (not counted while --dl-mid-access holds every read answer back on purpose)
		if (ss_busy && !hold_read && ++ss_wait > 2000) { expect(false, "savestate access not answered in 2000 clocks", (long long)ss_qa); ss_busy = false; }
		if (ss_busy && t->ss_ack) {
			ss_wait = 0;
			uint64_t cur = ss_mem.count(ss_qa) ? ss_mem[ss_qa] : 0;
			if (ss_rnw) expect(t->ss_dout == cur, "savestate read", (long long)ss_qa);
			else {
				for (int b = 0; b < 8; b++)
					if (ss_be >> b & 1) cur = (cur & ~(0xFFull << (8 * b))) | (ss_d & (0xFFull << (8 * b)));
				ss_mem[ss_qa] = cur;
			}
			ss_busy = false; ss_n++;
		}
	};
	for (int i = 0; i < 8; i++) ctick();
	t->reset = 0;
	for (int i = 0; i < 8; i++) ctick();

	// the OSD download of the ROM (hps_io: a byte per write, held off by ioctl_wait)
	std::vector<uint8_t> rom;
	if (!rom_path.empty() && !load(rom_path, rom)) return 2;
	auto rom_download = [&]() {
		t->rom_ft = 0x41; t->rom_is_nes = 1;
		for (int i = 0; i < 4; i++) ctick();
		t->rom_dl = 1;
		for (int i = 0; i < 4; i++) ctick();
		for (size_t k = 0; k < rom.size(); ) {
			t->rom_wr = 0;
			t->eval();
			if (!t->rom_stall && !t->rom_core_wait && (rng() % 3) == 0) {
				t->rom_wr = 1; t->rom_din = rom[k]; t->rom_addr = (uint32_t)k; k++;
			}
			ctick();
		}
		t->rom_wr = 0; t->rom_addr = (uint32_t)rom.size();
		for (int i = 0; i < 4; i++) ctick();
		t->rom_dl = 0;
		rom_watch_gap = true;
	};
	// until the patcher is idle again: the FPGA side idle with nothing to tell the ARM, the ARM
	// with nothing to answer or write, and its last command carried out or overtaken - for 20000
	// clocks running (longer than the FPGA's idle poll period)
	auto rom_settle = [&]() {
		long calm = 0;
		for (long i = 0; i < 400000000L; i++) {
			ctick();
			if (t->rom_o_dl && rom_watch_gap) rom_watch_gap = false;   // the replay has begun
			uint64_t s = dq(RF_ST_OFF / 8), c = dq(RF_CMD_OFF / 8);
			bool done = (c >> 56) != 0xC7 || ((c >> 32) & 0xFF) == RF_LASTID(s) ||
			            ((c >> 48) & 0xFF) != RF_RSEQ(s) || ((c >> 40) & 0xFF) != RF_ASEQ(s);
			// the FPGA's own idle poll (S_IDLE -> S_MEM -> S_CHK -> S_IDLE, every POLL_I clocks)
			// counts as idle: with the command done or stale (`done`) it cannot act on it
			unsigned rst = t->rootp->hd3_engine__DOT__romfix__DOT__st;
			unsigned rret = t->rootp->hd3_engine__DOT__romfix__DOT__ret;
			bool fidle = !t->rootp->hd3_engine__DOT__romfix__DOT__from_dl &&
			             (rst == 0 || rst == 5 || (rst == 10 && rret == 5));   // S_IDLE/S_CHK/S_MEM

			bool idle = fidle && !t->rom_o_dl &&
			            !t->rootp->hd3_engine__DOT__romfix__DOT__act_dirty && arm_quiet() && done;
			calm = idle ? calm + 1 : 0;
			if (calm > 20000) return;
			if (getenv("TB_RFDBG") && i % 1000000 == 0)
				fprintf(stderr, "[rf] i=%ld st=%u odl=%d dirty=%d sched=%d pend=%d done=%d s=%016llx c=%016llx cmds=%ld\n",
				        i, (unsigned)t->rootp->hd3_engine__DOT__romfix__DOT__st, (int)t->rom_o_dl,
				        (int)t->rootp->hd3_engine__DOT__romfix__DOT__act_dirty, (int)arm_sched,
				        (int)rf_pending(&arm_rf, s), (int)done, (unsigned long long)s, (unsigned long long)c, arm_cmds);
		}
		expect(false, "the ROM patcher never went idle");
	};
	auto rom_check = [&]() {
		std::vector<uint8_t> want;
		if (!load(rom_expect_path, want)) exit(2);
		printf("ROM: %zu core-side load(s), result %u, content %u\n", rom_sessions.size(),
		       (unsigned)t->rom_result, (unsigned)t->rom_content);
		expect(rom_want_loads < 0 || (int)rom_sessions.size() == rom_want_loads, "ROM loads the core saw",
		       (long long)rom_sessions.size(), rom_want_loads);
		expect(rom_want_result < 0 || (int)t->rom_result == rom_want_result, "rom_result", t->rom_result, rom_want_result);
		expect(!rom_sessions.empty() && rom_sessions.back() == want, "the core's ROM differs from --rom-expect",
		       rom_sessions.empty() ? -1 : (long long)rom_sessions.back().size(), (long long)want.size());
		if (!rom_sessions.empty()) expect(rom_sessions.front() == rom, "the first load is not the OSD file");
		expect(!(rom_want_loads == 2 && !rom_before && rom_free_gap), "the core ran between the download and the replay");
	};
	if (!rom.empty() && rom_before) {
		rom_download();
		rom_settle();
		rom_watch_gap = false;
	}

	// 1. pack load. It is an OSD download too, so the ROM patcher sees hps_io's downloading
	// rise and fall with the pack's file type (index 4) - as in NES.sv
	auto load_pack = [&](const std::vector<uint8_t> &pk) -> bool {
		t->rom_ft = 4; t->rom_is_nes = 0; t->rom_dl = 1;
		t->load_active = 1; ctick();
		size_t pos = 0;
		while (pos < pk.size()) {
			t->load_wr = 0; t->rom_wr = 0;
			t->eval();
			if (!t->load_wait) { t->load_wr = 1; t->rom_wr = 1; t->rom_din = pk[pos]; t->rom_addr = (uint32_t)pos; t->load_data = pk[pos++]; }
			ctick();
		}
		t->load_wr = 0; t->rom_wr = 0; ctick();
		t->load_active = 0; t->rom_dl = 0;
		for (int i = 0; i < 64; i++) ctick();
		if (hold_read) {                       // --dl-mid-access: the patcher now asks again
			for (int i = 0; i < 2000; i++) ctick();
			printf("dl-mid-access: answer released with %u access(es) outstanding, patcher state %u\n",
			       (unsigned)t->rootp->hd3_engine__DOT__romfix__DOT__nout,
			       (unsigned)t->rootp->hd3_engine__DOT__romfix__DOT__st);
			hold_read = false;
		}
		if (t->reject != 0 || !t->active) { printf("FAIL: pack refused (reject %u)\n", (unsigned)t->reject); return false; }
		// the loader's last writes can still be queued behind a long --busy-burst stall: give
		// them 200000 clocks to land (a lost write never does)
		size_t bad_q = 0;
		for (long w = 0; w < 200000; w++) {
			bad_q = SIZE_MAX;
			for (size_t i = 0; i < pk.size(); i += 8) {
				uint64_t want = 0; memcpy(&want, &pk[i], std::min<size_t>(8, pk.size() - i));
				if (dq(i / 8) != want) { bad_q = i / 8; break; }
			}
			if (bad_q == SIZE_MAX) return true;
			ctick();
		}
		printf("FAIL: pack qword %zu not in DDR3\n", bad_q);
		return false;
	};
	if (!load_pack(pack)) return 1;
	printf("pack loaded: %zu bytes, %llu core clocks, list_n %u\n", pack.size(), (unsigned long long)ccyc, (unsigned)t->list_n);
	if ((int)t->rootp->hd3_engine__DOT__game_ram != game_ram) {
		printf("FAIL: the loader decided game_ram %d, the run says %d\n", (int)t->rootp->hd3_engine__DOT__game_ram, game_ram);
		return 1;
	}
	if (!rom.empty()) {
		if (!rom_before) rom_download();
		rom_settle();
		rom_watch_gap = false;
		if (!pack2_path.empty()) {             // a second pack replaces the first
			std::vector<uint8_t> p2;
			if (!load(pack2_path, p2)) return 1;
			if (dl_mid) {
				// wait for an access of the patcher's (its idle poll, every POLL_I clocks) to be
				// in flight (S_MEM = 10, nout != 0), hold DDR3 so it stays unanswered, start the
				// download now
				long w = 0;
				while (!(t->rootp->hd3_engine__DOT__romfix__DOT__st == 10 &&
				         t->rootp->hd3_engine__DOT__romfix__DOT__nout != 0) && w < 2000000) { ctick(); w++; }
				if (w >= 2000000) { printf("FAIL: --dl-mid-access: no patcher access in flight\n"); return 1; }
				hold_read = true;                      // released in load_pack, after the download
				printf("dl-mid-access: download starts with %u access(es) in flight\n",
				       (unsigned)t->rootp->hd3_engine__DOT__romfix__DOT__nout);
			}
			if (!load_pack(p2)) return 1;
			rom_settle();
		}
		rom_check();
		if (frames.empty()) {
			printf("%d failures\n", fails);
			delete t;
			return fails ? 1 : 0;
		}
	}

	// 2. frames at the line rate; 3. scan-out capture
	std::vector<uint8_t> img;                  // 512 x 480 of the frame being shown
	int row = -1, col = 0; bool prev_hb = true, prev_vb = true, prev_hs = false, prev_vs = false;
	int shown = -1;                            // which frame the current visible period shows
	int nesf = 0;                              // NES frame number (0 = frame 0 streams)
	std::deque<Q> q;
	uint64_t black_bad = 0;
	int ssg = 0;
	auto flush_pic = [&](int fi) {
		if (fi < 0 || fi >= (int)frames.size()) return;
		std::vector<uint8_t> o((size_t)img_w * img_h * 3);
		for (int y = 0; y < 480; y++)
			for (int x = 0; x < 512; x++) {
				const uint8_t *p = &img[((size_t)y * 512 + x) * 3];
				int wy = y - 2 * ov[0], wx = x - 2 * ov[3];
				if (wy >= 0 && wx >= 0 && wy < img_h && wx < img_w) memcpy(&o[((size_t)wy * img_w + wx) * 3], p, 3);
				else if (p[0] | p[1] | p[2]) black_bad++;
			}
		std::string op = std::string(argv[2]) + "_" + frames[fi].name + ".rgb";
		FILE *f = fopen(op.c_str(), "wb");
		if (!f) { perror(op.c_str()); exit(2); }
		uint32_t hd[3] = {0x4247524Eu, (uint32_t)img_w, (uint32_t)img_h};
		fwrite(hd, 4, 3, f); fwrite(o.data(), 1, o.size(), f); fclose(f);
		printf("frame %s shown: drawn %u dropped %u aborted_add %u underflow %u overrun %u\n",
		       frames[fi].name.c_str(), (unsigned)t->frames_drawn, (unsigned)t->frames_dropped,
		       (unsigned)t->adds_aborted, (unsigned)t->underflow, (unsigned)t->overrun);
	};

	int total = (int)frames.size() + 1;        // the last frame is shown in NES frame size()
	bool uf_seen = false;
	for (nesf = 0; nesf < total; nesf++) {
		for (int ln = 0; ln < NLINES; ln++) {
			int scan = (ln == 0) ? NLINES - 1 : ln - 1;   // NES frame nesf starts with its pre-render line
			// frame nesf's record stream: group g from line g - 1 (pre-render line = group 0)
			int fi = nesf;
			if (ln == 0) {
				if (!q.empty()) { printf("FAIL: frame %d's stream had %zu qwords left\n", nesf - 1, q.size()); fails++; q.clear(); }
				if (fi < (int)frames.size()) {
					auto s = frame_stream(frames[fi]);
					q.assign(s.begin(), s.end());
				}
			}
			for (int c = 0; c < LINE; c++) {
				// record writer
				t->cw_valid = 0;
				if (!q.empty() && (int)q.front().g <= ln) {
					t->cw_valid = 1; t->cw_addr = q.front().a; t->cw_data = q.front().d; t->cw_be = q.front().be;
				}
				// tap timing
				t->line_done = (c == 256);
				t->line_y = scan;
				t->watch_done = 0;
				if (c == 256 && scan == 239) t->frame_num = (uint32_t)nesf + 1;   // capture of frame nesf + 1 begins
				// the snapshot of frame nesf goes into bank nesf[0] from scanline 240 dot 0 (the
				// values of frame nesf - 2 are gone from then) and is complete at watch_done
				if (c == 0 && scan == 240 && nesf < (int)frames.size()) watch_noise[nesf & 1] = true;
				if (c == 0 && scan == watch_line && nesf < (int)frames.size()) {
					t->watch_done = 1;
					watch_noise[nesf & 1] = false;
					watch_of[nesf & 1] = &frames[nesf].watch;
				}
				t->eval();
				bool cw_take = t->cw_valid && t->cw_ready;
				int cst0 = t->rootp->hd3_engine__DOT__cst;
				ctick();
				if (cw_take) q.pop_front();
				if (cst0 == 3 && t->rootp->hd3_engine__DOT__cst == 4)   // RESOLVE done, RENDER starts
					printf("render start: NES frame %d scanline %d clock %d, disp_y %d, tag %d, scan-out id %d\n",
					       nesf, scan, c, (int)t->rootp->hd3_engine__DOT__scan__DOT__disp_y,
					       (int)t->rootp->hd3_engine__DOT__tgt, (int)t->rootp->hd3_engine__DOT__scan__DOT__dcount);
				if (t->underflow && !uf_seen) {
					uf_seen = true;
					printf("underflow first at NES frame %d line %d (scanline %d) clock %d\n", nesf, ln, scan, c);
				}
				// scan-out capture (registered outputs, sampled after the edge)
				bool hb = t->HB, vb = t->VB, hs = t->HS, vs = t->VS;
				// sync geometry, pinned to the line_done edge at clock 256 of every line: the
				// outputs follow disp_y / hcnt by two registers, so a half-line's first pixel
				// is at clock 258 (+682 for the second), blanking from pixel 512, sync 544..607,
				// VB from the line_done of scanline 241 (disp_y 240) to that of scanline 1, VS
				// for disp_y 245-246
				if (ccyc > 20000 && nesf > 0) {
					if (hb != prev_hb) expect((c - (hb ? 88 : 258) + 1364) % 682 == 0, hb ? "HB rise position" : "HB fall position", ln, c);
					if (hs != prev_hs) expect((c - (hs ? 120 : 184) + 1364) % 682 == 0, hs ? "HS rise position" : "HS fall position", ln, c);
					if (vb != prev_vb) expect(c == 258 && ln == (vb ? 242 : 2), vb ? "VB rise position" : "VB fall position", ln, c);
					if (vs != prev_vs) expect(c == 258 && ln == (vs ? 247 : 249), vs ? "VS rise position" : "VS fall position", ln, c);
					if (hb && !prev_hb && !vb) expect(col == 512, "pixels in a half-line", col);
					if (hs || vs) expect(t->R == 0 && t->G == 0 && t->B == 0, "colour during sync");
					if (hb || vb) expect(t->R == 0 && t->G == 0 && t->B == 0, "colour during blanking");
				}
				prev_hs = hs; prev_vs = vs;
				if (prev_vb && !vb) {                  // a visible period begins
					img.assign((size_t)512 * 480 * 3, 0);
					row = 0; col = 0;
					shown = nesf - 1;
				}
				if (!vb && !hb && row >= 0 && row < 480 && col < 512) {
					uint8_t *p = &img[((size_t)row * 512 + col) * 3];
					p[0] = t->R; p[1] = t->G; p[2] = t->B;
					col++;
				}
				if (!vb && !prev_hb && hb) { row++; col = 0; }
				if (!prev_vb && vb) { if (row != 480) { printf("FAIL: visible period of %d rows\n", row); fails++; } flush_pic(shown); row = -1; }
				prev_hb = hb; prev_vb = vb;
			}
		}
	}
	(void)ssg;
	expect(black_bad == 0, "picture outside the overscan window not black", (long long)black_bad);
	if (expect_late) {
		expect(t->underflow == 1, "a slow DDR3 run reported no underflow");
	} else {
		expect(t->underflow == 0, "underflow (a line shown before it was drawn)");
		expect(t->overrun == 0, "overrun (a frame took longer than a frame)");
	}
	expect(t->frames_dropped == 0, "frames dropped", t->frames_dropped);
	if (!expect_late) expect(t->frames_drawn == frames.size(), "frames drawn", t->frames_drawn, (long long)frames.size());
	else expect(t->frames_drawn >= 1, "a slow DDR3 run drew no frame at all");
	expect(!ss_pct || ss_n > 0, "no savestate traffic happened");
	printf("savestate accesses %ld; %d failures\n", ss_n, fails);
	delete t;
	return fails ? 1 : 0;
}
