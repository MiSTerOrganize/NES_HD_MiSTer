// fullsim.cpp - testbench for the whole-core NES + HD pack Verilator simulation (sim_top.sv).
//
//   fullsim --rom game.nes --frames N --out DIR [options]
//     --hdp pack.hdp      load a format-3 HD pack (tools/hdp3_convert.py output) through OSD
//                         slot 4 first; hd3_engine's ROM patcher applies its section 14 to the
//                         ROM that follows, as on the MiSTer
//     --hd 0|1            "HD Pack" OSD option (status[88]); default 1 when --hdp is given
//     --input script.txt  joypad 1 script, lines "<frame> <buttons>", buttons = 0, a hex mask or
//                         names joined by '+': RIGHT LEFT DOWN UP A B SELECT START. A line holds
//                         from the start of that frame until the next line.
//     --save LIST         frames to write: "all", "120,200", "every:10" (default: the last frame)
//     --palette FILE      .pal for the colour-index picture (default Palette/Kitrinx34.pal)
//     --ddr-lat N         DDR3 read latency in core clocks (default 12)
//     --ddr-busy P        percent of clocks DDRAM_BUSY is high (default 0)
//     --xoff N            screen x = PPU cycle - N for the colour-index picture (default 2)
//     --rec               stage-2 frame record: turn capture on ("HD Pack" option) and, for each
//                         saved frame F, also write col_FFFF.bin (262 x 341 PPU colour indices,
//                         one byte per PPU cycle) and rec_FFFF.bin (the 1 MB record buffer
//                         hd_capture wrote for that frame, read from the DDR3 model once the
//                         FIFO has drained) and chr_FFFF.bin (the 32 KB at SDRAM 0x200000 at
//                         the end of the visible lines). Checked by tools/fullsim/check_record.py.
//                         With a pack, also hdv_FFFF.rgb: the HD picture shown during F+1 (drawn
//                         from F's record), cropped to the pack's overscan window, in
//                         tools/sim3/check_render.py's format - compared there with hdref.
//     --ex-sprites        the core's "Extra sprites" option (status[25]): up to 16 sprites per line
//     --nolimit           an HD pack's disableSpriteLimit: extras forced on, masked by Mesen's
//                         adaptive rule (8+ in-range sprites at one position) instead of the core's.
//                         Without a pack only: a loaded pack's own option already drives it
//                         (hd3_engine's nolimit, ORed in sim_top as NES.sv does)
//     --watch LIST        stage-2 watched-address snapshot: load LIST (one u32 per line, hex, as in
//                         the .hdp's section 9; '#' starts a comment) into hd_watch, and for each
//                         saved frame F write watch_FFFF.bin: the list, the values hd_watch took
//                         at scanline 240 dot 0, and what the model held at that moment (CPU RAM,
//                         CIRAM, PRG-RAM page, palette). Checked by tools/fullsim/check_watch.py.
//     --audlog FILE       stage 6: every CPU write nes.v exports to hd3_audio (the bus export,
//                         not the device's decode, so it is the same with or without a pack)
//                         at $4100-$417F, one line "<frame> <addr hex> <value hex>" - the same
//                         format as NES_HDPack_testdata/tools/mesen2/audlog.lua writes
//     --zap FILE          a Zapper on NES port 2 (NES.sv "Peripheral = Zapper(Joy1)", trigger on
//                         the joystick, crosshairs on - drawn on the HD picture by hd_reticle.sv):
//                         lines "<frame> <x> <y> <fire>", aim at NES pixel x,y (y 0..239) and
//                         hold the trigger (fire 1) from that frame until the next line
//
// Outputs per saved frame F (frame 1 = first frame that starts after the reset is released):
//   nes_FFFF.png  256x240  PPU colour index (sim_top.color) through the palette file
//   vid_FFFF.png  256x240  rtl/video.sv RGB output (palette Kitrinx, incl. emphasis) - reference
//   hd_FFFF.png   512x480  hd3_engine scan-out RGB (only with an HD pack loaded and enabled)
// At the end, with a pack: hd3_engine's counters (frames drawn / dropped, ADDs aborted,
// underflow, overrun, dictionary overflow) and the DDR3 traffic.
#include "Vsim_top.h"
#include "Vsim_top___024root.h"
#include "verilated.h"
#include <zlib.h>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <deque>
#include <filesystem>
#include <map>
#include <set>
#include <string>
#include <vector>

static Vsim_top *top;
static uint64_t now = 0;
double sc_time_stamp() { return (double)now; }

// ---------------- DDR3 model (Avalon-like, in-order burst return) ----------------
static std::map<uint32_t, std::vector<uint64_t>> ddr_pages;   // 64K-qword pages
static uint64_t ddr_get(uint32_t qa) {
	auto it = ddr_pages.find(qa >> 16);
	return it == ddr_pages.end() ? 0 : it->second[qa & 0xFFFF];
}
static void ddr_put(uint32_t qa, uint64_t v, uint8_t be) {
	auto &pg = ddr_pages[qa >> 16];
	if (pg.empty()) pg.assign(65536, 0);
	uint64_t m = 0;
	for (int i = 0; i < 8; i++) if (be & (1 << i)) m |= 0xFFull << (8 * i);
	pg[qa & 0xFFFF] = (pg[qa & 0xFFFF] & ~m) | (v & m);
}
// ---------------- the ARM's part of the ROM patcher (every build) ----------------
// tools/armdec/romfix_arm.c, linked in: when hd3_romfix posts a status the ARM has not answered,
// decide on the staged ROM and the pack's section 14, write the target, then the command - as
// hdarm_daemon.c does on the device. Without it a section-14 pack would hold the core until
// hd3_romfix's timeout.
#include "../armdec/romfix_arm.h"
static rf_state rf_arm;
static std::vector<uint8_t> rf_s14, rf_tgt(RF_MAXB), rf_rom;
static unsigned rf_cmds = 0;
static uint32_t rfq(uint32_t off) { return (0x30000000u + off) >> 3; }
static void rf_poll() {
	if (rf_session_check(&rf_arm, ddr_get(rfq(RF_CMD_OFF))))    // as hdarm_daemon.c does, first
		fprintf(stderr, "romfix: the core started a new session\n");
	uint64_t s = ddr_get(rfq(RF_ST_OFF));
	if (!rf_pending(&rf_arm, s)) return;
	uint32_t L = RF_LEN(s) > RF_MAXB ? RF_MAXB : RF_LEN(s);
	rf_rom.assign(L + 8, 0);
	for (uint32_t i = 0; i < L; i += 8) { uint64_t v = ddr_get(rfq(RF_SRC_OFF) + i / 8); memcpy(&rf_rom[i], &v, 8); }
	uint32_t tl; uint64_t cmd;
	if (!rf_decide(&rf_arm, s, rf_rom.data(), rf_s14.empty() ? nullptr : rf_s14.data(),
	               (uint32_t)rf_s14.size(), rf_tgt.data(), &tl, &cmd)) return;
	for (uint32_t i = 0; i < tl; i += 8) {
		uint64_t v = 0; int be = 0;
		for (uint32_t k = 0; k < 8 && i + k < tl; k++) { v |= (uint64_t)rf_tgt[i + k] << (8 * k); be |= 1 << k; }
		ddr_put(rfq(RF_TGT_OFF) + i / 8, v, be);
	}
	ddr_put(rfq(RF_CMD_OFF), cmd, 0xFF);
	rf_cmds++;
	fprintf(stderr, "romfix: ARM answered (action %u, result %u, %u bytes)\n",
	        (unsigned)((cmd >> 30) & 3), (unsigned)((cmd >> 27) & 7), tl);
}

// ---------------- the ARM's part of HD audio (every build) ----------------
// tools/armdec/aud_arm.c, linked in: read hd3_audio's status and event log out of the DDR3
// model, decode and mix the voices, write the PCM slots the FPGA mixes AUD_D ticks later - as
// hdarm_daemon.c's audio thread does on the device. Window qword q is DDR3 qword
// (0x30000000 >> 3) + q; pack file bytes >= 192 MB sit in the overflow window at 0x24000000.
#include "../armdec/aud_arm.h"
static aud_arm aud_a;
static uint64_t aud_rd(void *, uint32_t q) { return ddr_get((0x30000000u >> 3) + q); }
static void aud_wr(void *, uint32_t q, uint64_t v) { ddr_put((0x30000000u >> 3) + q, v, 0xFF); }
static int aud_fetch(void *, uint32_t off, uint32_t len, uint8_t *dst) {
	if ((uint64_t)off + len > 0x18000000u) return 1;
	for (uint32_t i = 0; i < len; i++) {
		uint32_t f = off + i;
		uint32_t qa = f < 0x0C000000u ? (0x30000000u + f) >> 3 : (0x24000000u + (f - 0x0C000000u)) >> 3;
		dst[i] = (uint8_t)(ddr_get(qa) >> (8 * (f & 7)));
	}
	return 0;
}
static aud_io aud_io_ = { aud_rd, aud_wr, aud_fetch, nullptr };
static bool aud_on = false;
static void aud_poll() {                           // a pass of hdarm_daemon.c's audio thread
	if (!aud_on) return;
	aud_service(&aud_a, &aud_io_);
	aud_build_checkpoints(&aud_a, AUD_CKB_STEP);
}

#ifdef FULLSIM_ARM
// ---------------- the ARM's part of the display-list route (PAINT=1 builds) ----------------
// What the ARM program does on the MiSTer, on the DDR3 model: take each finished frame record
// (and its watched-address values once the engine's marker names that frame), run hdarm4's
// decisions (tools/armdec/hdarm4.c, linked as a library), write the display list into buffer
// fid mod 4 padded to a multiple of 8 qwords, and publish it in the mailbox. --arm-delay-lines
// holds the publication back by that many NES lines of simulated time (the ARM's compute time).
// See rtl/hdpack/hd3_pengine.sv for the layout.
extern "C" {
int hdarm_init(const uint8_t *pack, size_t len);
uint32_t hdarm_nwatched(void);
int hdarm_frame(const uint8_t *rec, const uint8_t *vals, uint32_t nvals,
                const uint64_t **list, size_t *nq);
}
static const uint32_t ARM_REC_Q  = 0x3C000000u >> 3;   // record bank 0; bank 1 at + 0x20000
static const uint32_t ARM_LIST_Q = 0x3C200000u >> 3;   // list buffer k at + k * 0x10000
static const uint32_t ARM_MBOX_Q = 0x3C400000u >> 3;
static const uint64_t TICKS_PER_LINE = 341 * 4 * 4;    // clk_f ticks per NES line
static struct {
	bool on = false;
	std::vector<uint8_t> pack, rec;
	uint32_t nw = 0, last = 0, fid = 0;
	uint64_t delay = 0;
	struct Pending { uint64_t at; uint32_t fid, n; };
	std::deque<Pending> pend;
	unsigned frames = 0, published = 0;
	size_t max_q = 0;
} arm;
static void arm_poll() {
	for (uint32_t b = 0; b < 2; b++) {
		uint32_t base = ARM_REC_Q + b * 0x20000;
		uint32_t F = (uint32_t)ddr_get(base + 0x1E000);
		if (F <= arm.last || (F & 1) != b) continue;
		if (arm.nw) {
			uint64_t mk = ddr_get(base + 0x1E040);
			if ((uint32_t)mk != F) continue;              // the engine has not copied them yet
			if (((mk >> 32) & 0x1FF) != (arm.nw > 256 ? 256 : arm.nw)) {
				fprintf(stderr, "arm: watch marker of frame %u says %u values, the pack watches %u\n",
				        F, (unsigned)((mk >> 32) & 0x1FF), arm.nw);
				exit(1);
			}
		}
		arm.rec.resize(0x100000);
		for (uint32_t i = 0; i < 0x20000; i++) { uint64_t q = ddr_get(base + i); memcpy(&arm.rec[8 * i], &q, 8); }
		uint8_t vals[256] = {0};
		for (uint32_t i = 0; i < arm.nw && i < 256; i++)
			vals[i] = (uint8_t)(ddr_get(base + 0x1E020 + i / 8) >> (8 * (i & 7)));
		const uint64_t *dl; size_t n;
		if (hdarm_frame(arm.rec.data(), vals, arm.nw, &dl, &n)) {
			fprintf(stderr, "arm: hdarm_frame failed on frame %u\n", F); exit(1);
		}
		size_t np = (n + 7) & ~(size_t)7;
		if (np > 0x10000) { fprintf(stderr, "arm: list of %zu qwords overflows its buffer\n", n); exit(1); }
		arm.last = F; arm.fid++; arm.frames++;
		if (np > arm.max_q) arm.max_q = np;
		uint32_t lb = ARM_LIST_Q + (arm.fid & 3) * 0x10000;
		for (size_t i = 0; i < np; i++) ddr_put(lb + (uint32_t)i, i < n ? dl[i] : 0, 0xFF);
		arm.pend.push_back({now + arm.delay, arm.fid, (uint32_t)np});
	}
	while (!arm.pend.empty() && arm.pend.front().at <= now) {
		auto p = arm.pend.front(); arm.pend.pop_front();
		ddr_put(ARM_MBOX_Q, 0xA5ull << 56 | (uint64_t)p.n << 32 | p.fid, 0xFF);
		arm.published++;
	}
}
#endif

struct Beat { uint64_t at; uint64_t data; };
static std::deque<Beat> rq;
static int ddr_lat = 12, ddr_busy = 0;
static uint32_t rng = 1;
static uint32_t rnd() { rng = rng * 1103515245u + 12345u; return (rng >> 16) & 0x7FFF; }
static uint64_t n_ddr_rd = 0, n_ddr_wr = 0;
static int hd_ov[4] = {0, 0, 0, 0};         // the pack's overscan window: top, right, bottom, left

// One HD-engine clock (clk_f, 85.9 MHz); `core` = this edge is also a rising edge of the core
// clock (every fourth, as from the PLL: same source, no phase shift). The DDR3 model runs on
// clk_f (DDRAM_CLK is clk85 in NES.sv): it reads the registered DDRAM_* outputs left by the
// previous rising edge, drives its inputs with the clocks low, then the edge is evaluated.
// `now` counts clk_f clocks; --ddr-lat is given in core clocks and scaled here.
static void ftick(bool core) {
	bool busy = ddr_busy && (int)(rnd() % 100) < ddr_busy;
	if (!top->DDRAM_BUSY && (top->DDRAM_RD || top->DDRAM_WE)) {
		uint32_t a = top->DDRAM_ADDR;
		if (top->DDRAM_WE) { ddr_put(a, top->DDRAM_DIN, top->DDRAM_BE); n_ddr_wr++; }
		else {
			uint64_t t = std::max<uint64_t>(now + 4 * (uint64_t)ddr_lat, rq.empty() ? 0 : rq.back().at + 1);
			for (unsigned i = 0; i < top->DDRAM_BURSTCNT; i++) rq.push_back({t + i, ddr_get(a + i)});
			n_ddr_rd++;
		}
	}
	top->DDRAM_BUSY = busy;
	if (!rq.empty() && rq.front().at <= now) {
		top->DDRAM_DOUT = rq.front().data;
		top->DDRAM_DOUT_READY = 1;
		rq.pop_front();
	} else top->DDRAM_DOUT_READY = 0;
	top->clk_f = 0;
	top->eval();
	top->clk_f = 1;
	if (core) top->clk = 1;
	top->eval();
	now++;
}

// One core clock = four clk_f clocks; the core clock falls half-way.
static void tick() {
	ftick(true);
	ftick(false);
	top->clk = 0;
	ftick(false);
	ftick(false);
}

// ---------------- PNG ----------------
static void png_chunk(FILE *f, const char *type, const std::vector<uint8_t> &d) {
	uint8_t len[4] = { (uint8_t)(d.size() >> 24), (uint8_t)(d.size() >> 16), (uint8_t)(d.size() >> 8), (uint8_t)d.size() };
	fwrite(len, 1, 4, f);
	fwrite(type, 1, 4, f);
	if (!d.empty()) fwrite(d.data(), 1, d.size(), f);
	uLong c = crc32(0, (const Bytef *)type, 4);
	if (!d.empty()) c = crc32(c, d.data(), (uInt)d.size());
	uint8_t cb[4] = { (uint8_t)(c >> 24), (uint8_t)(c >> 16), (uint8_t)(c >> 8), (uint8_t)c };
	fwrite(cb, 1, 4, f);
}
// Every output file opens through here. A run that cannot write its outputs is a failed run:
// skipping the file and carrying on (as this did until 2026-10-15) lost the records of a
// 50-minute run while the log still said "written".
static FILE *open_out(const char *path) {
	FILE *f = fopen(path, "wb");
	if (!f) { perror(path); fprintf(stderr, "fullsim: cannot write %s - stopping\n", path); exit(3); }
	return f;
}

static void write_png(const std::string &path, int w, int h, const std::vector<uint8_t> &rgb) {
	std::vector<uint8_t> raw;
	raw.reserve((size_t)h * (w * 3 + 1));
	for (int y = 0; y < h; y++) {
		raw.push_back(0);
		raw.insert(raw.end(), rgb.begin() + (size_t)y * w * 3, rgb.begin() + (size_t)(y + 1) * w * 3);
	}
	uLongf zl = compressBound(raw.size());
	std::vector<uint8_t> z(zl);
	compress2(z.data(), &zl, raw.data(), raw.size(), 6);
	z.resize(zl);
	FILE *f = open_out(path.c_str());
	static const uint8_t sig[8] = { 0x89, 'P', 'N', 'G', 13, 10, 26, 10 };
	fwrite(sig, 1, 8, f);
	std::vector<uint8_t> ihdr = { (uint8_t)(w >> 24), (uint8_t)(w >> 16), (uint8_t)(w >> 8), (uint8_t)w,
	                              (uint8_t)(h >> 24), (uint8_t)(h >> 16), (uint8_t)(h >> 8), (uint8_t)h,
	                              8, 2, 0, 0, 0 };
	png_chunk(f, "IHDR", ihdr);
	png_chunk(f, "IDAT", z);
	png_chunk(f, "IEND", {});
	fclose(f);
}

// ---------------- helpers ----------------
static std::vector<uint8_t> read_file(const char *p) {
	std::vector<uint8_t> v;
	FILE *f = fopen(p, "rb");
	if (!f) { perror(p); exit(2); }
	int c;
	while ((c = fgetc(f)) != EOF) v.push_back((uint8_t)c);
	fclose(f);
	return v;
}

// MiSTer joystick_0 bit order (sim_top.joy1): right left down up A B select start
static unsigned parse_buttons(const char *s) {
	char *end;
	unsigned long v = strtoul(s, &end, 0);
	if (*end == 0 || *end == '\n' || *end == '\r') return (unsigned)v;
	unsigned m = 0;
	std::string t(s);
	size_t p = 0;
	while (p < t.size()) {
		size_t q = t.find_first_of("+|,\r\n", p);
		std::string n = t.substr(p, q == std::string::npos ? std::string::npos : q - p);
		for (auto &c : n) c = toupper(c);
		if (n == "RIGHT") m |= 1; else if (n == "LEFT") m |= 2; else if (n == "DOWN") m |= 4;
		else if (n == "UP") m |= 8; else if (n == "A") m |= 16; else if (n == "B") m |= 32;
		else if (n == "SELECT") m |= 64; else if (n == "START") m |= 128;
		else if (!n.empty()) { fprintf(stderr, "unknown button '%s'\n", n.c_str()); exit(2); }
		if (q == std::string::npos) break;
		p = q + 1;
	}
	return m;
}

#ifdef FULLSIM_ARM
// The display-list route's pack load, as hdarm_daemon.c's pack loader does it on the device:
// BEGIN, copy the file into DDR3 (bytes below 192 MB at 0x30000000, the rest at 0x24000000),
// COMMIT, and wait for hd3_loader's answer in the pack-state qword (0x3C400008: [47:40] the
// command's sequence, [39:36] reject, [48] valid). See rtl/hdpack/hd3_loader.sv.
static uint8_t pk_seq = 0;
static void pk_command(int op, uint32_t size, const char *what) {
	const uint32_t CMD_Q = 0x3C400060u >> 3, ST_Q = 0x3C400008u >> 3;
	for (int attempt = 0; attempt < 4; attempt++) {
		pk_seq++;
		ddr_put(CMD_Q, (0xC5ull << 56) | ((uint64_t)op << 48) | ((uint64_t)pk_seq << 40) | size, 0xFF);
		for (long g = 0; g < 600000; g++) {           // > 2^17-clock poll + the header reads
			tick();
			uint64_t s = ddr_get(ST_Q);
			if ((s >> 56) == 0x5A && ((s >> 40) & 0xFF) == pk_seq) return;
		}
		fprintf(stderr, "%s: no answer to sequence %u, resending\n", what, pk_seq);
	}
	fprintf(stderr, "%s: no answer from hd3_loader\n", what);
	exit(1);
}
static void pack_copy_load(const std::vector<uint8_t> &data) {
	const uint64_t MAXB = 0x0C000000;
	pk_command(1, 0, "BEGIN");
	for (size_t i = 0; i < data.size(); i += 8) {
		uint64_t v = 0; uint8_t be = 0;
		for (size_t k = 0; k < 8 && i + k < data.size(); k++) { v |= (uint64_t)data[i + k] << (8 * k); be |= 1 << k; }
		uint64_t b = i < MAXB ? 0x30000000u + i : 0x24000000u + (i - MAXB);
		ddr_put((uint32_t)(b >> 3), v, be);
	}
	pk_command(2, (uint32_t)data.size(), "COMMIT");
	uint64_t s = ddr_get(0x3C400008u >> 3);
	fprintf(stderr, "hd pack: copied into DDR3, loader %s (reject %u)\n",
	        (s >> 48) & 1 ? "accepted it" : "REFUSED it", (unsigned)((s >> 36) & 0xF));
}
#endif

// stream a file through the ioctl port like hps_io: one byte per write strobe, honour ioctl_wait
static void ioctl_load(const std::vector<uint8_t> &data, uint8_t index, const char *what) {
	top->filetype = index;
	top->ioctl_downloading = 1;
	for (int i = 0; i < 64; i++) tick();
	for (size_t i = 0; i < data.size(); i++) {
		top->ioctl_addr = (uint32_t)i;
		top->ioctl_dout = data[i];
		top->ioctl_wr = 1;
		tick();
		top->ioctl_wr = 0;
		tick();
		tick();
		int guard = 0;
		while (top->ioctl_wait_out) {
			tick();
			if (++guard > 100000) { fprintf(stderr, "%s: ioctl_wait stuck at byte %zu\n", what, i); exit(1); }
		}
	}
	tick();
	top->ioctl_downloading = 0;
	for (int i = 0; i < 64; i++) tick();
}

int main(int argc, char **argv) {
	const char *rom = nullptr, *hdp = nullptr, *outdir = ".", *script = nullptr;
	const char *palf = nullptr, *watchf = nullptr, *audlogf = nullptr, *zapf = nullptr;
	std::string save = "";
	int frames = 0, hd = -1, xoff = 2, hd_off_at = -1;
	bool rec = false, ex_spr = false, nolimit = false;
	aud_init(&aud_a);
	aud_on = true;
	for (int i = 1; i < argc; i++) {
		std::string a = argv[i];
		auto nxt = [&]() -> const char * { if (i + 1 >= argc) { fprintf(stderr, "missing value for %s\n", a.c_str()); exit(2); } return argv[++i]; };
		if (a == "--rom") rom = nxt();
		else if (a == "--hdp") hdp = nxt();
		else if (a == "--frames") frames = atoi(nxt());
		else if (a == "--out") outdir = nxt();
		else if (a == "--input") script = nxt();
		else if (a == "--save") save = nxt();
		else if (a == "--hd") hd = atoi(nxt());
		else if (a == "--hd-off-at") hd_off_at = atoi(nxt());
		else if (a == "--palette") palf = nxt();
		else if (a == "--ddr-lat") ddr_lat = atoi(nxt());
		else if (a == "--ddr-busy") ddr_busy = atoi(nxt());
		else if (a == "--xoff") xoff = atoi(nxt());
		else if (a == "--rec") rec = true;
		else if (a == "--ex-sprites") ex_spr = true;
		else if (a == "--nolimit") nolimit = true;
		else if (a == "--watch") watchf = nxt();
		else if (a == "--audlog") audlogf = nxt();
		else if (a == "--zap") zapf = nxt();
#ifdef FULLSIM_ARM
		else if (a == "--arm-delay-lines") arm.delay = (uint64_t)atoi(nxt()) * TICKS_PER_LINE;
#endif
		else { fprintf(stderr, "unknown argument %s\n", a.c_str()); return 2; }
	}
	if (!rom || frames <= 0) {
		fprintf(stderr, "usage: fullsim --rom game.nes --frames N --out DIR [--hdp pack.hdp] [--hd 0|1]\n"
		                "       [--input script.txt] [--save all|F1,F2|every:N] [--palette f.pal]\n"
		                "       [--ddr-lat N] [--ddr-busy P] [--xoff N] [--rec] [--watch list.txt]\n"
		                "       [--audlog file.txt] [--zap zapper.txt]\n");
		return 2;
	}
	if (hd < 0) hd = (hdp || rec || watchf) ? 1 : 0;
	// hd3_render's $readmemh takes project-folder paths in this build (HD3_HEX_PROJECT, as
	// Quartus): a missing file only warns and leaves the 2C02 palette / emphasis ROM all zeros,
	// which would make every HD picture wrong without failing anything - refuse instead.
	for (const char *hx : {"rtl/hdpack/hd3_pal2c02.hex", "rtl/hdpack/hd3_emph_r.hex",
	                       "rtl/hdpack/hd3_emph_g.hex", "rtl/hdpack/hd3_emph_b.hex"}) {
		FILE *f = fopen(hx, "rb");
		if (!f) {
			fprintf(stderr, "fullsim: %s not found - run from the project folder (NES_HDPack)\n", hx);
			return 2;
		}
		fclose(f);
	}
	{
		std::error_code ec;
		std::filesystem::create_directories(outdir, ec);
		if (ec) { fprintf(stderr, "fullsim: cannot create %s: %s\n", outdir, ec.message().c_str()); return 3; }
	}

	// watched-address list
	std::vector<uint32_t> wlist;
	if (watchf) {
		FILE *f = fopen(watchf, "r");
		if (!f) { perror(watchf); return 2; }
		char line[256];
		while (fgets(line, sizeof line, f)) {
			char *h = strchr(line, '#');
			if (h) *h = 0;
			char *e;
			unsigned long v = strtoul(line, &e, 16);
			if (e == line) continue;          // blank / comment line
			wlist.push_back((uint32_t)v);
		}
		fclose(f);
		if (wlist.empty() || wlist.size() > 256) { fprintf(stderr, "%s: need 1..256 entries, got %zu\n", watchf, wlist.size()); return 2; }
	}

	// palette
	std::vector<uint8_t> pal(192, 0);
	{
		std::string p = palf ? palf : "";
		if (p.empty()) {
			// default: Palette/Kitrinx34.pal next to the repo root (exe lives in tools/fullsim/obj)
			std::string exe = argv[0];
			size_t s = exe.find_last_of("/\\");
			std::string dir = s == std::string::npos ? "." : exe.substr(0, s);
			p = dir + "/../../../Palette/Kitrinx34.pal";
		}
		FILE *f = fopen(p.c_str(), "rb");
		if (!f) { fprintf(stderr, "cannot open palette %s\n", p.c_str()); return 2; }
		if (fread(pal.data(), 1, 192, f) != 192) { fprintf(stderr, "palette %s too short\n", p.c_str()); return 2; }
		fclose(f);
	}

	// frames to save
	std::set<int> want;
	int every = 0;
	bool all = false;
	if (save.empty()) want.insert(frames);
	else if (save == "all") all = true;
	else if (!save.compare(0, 6, "every:")) every = atoi(save.c_str() + 6);
	else {
		size_t p = 0;
		while (p < save.size()) { want.insert(atoi(save.c_str() + p)); size_t q = save.find(',', p); if (q == std::string::npos) break; p = q + 1; }
	}
	auto wanted = [&](int f) { return all || want.count(f) || (every > 0 && f % every == 0); };

	// input script
	std::map<int, unsigned> inputs;
	if (script) {
		FILE *f = fopen(script, "r");
		if (!f) { perror(script); return 2; }
		char line[256];
		while (fgets(line, sizeof line, f)) {
			char *p = line;
			while (*p == ' ' || *p == '\t') p++;
			if (*p == '#' || *p == '\n' || *p == '\r' || !*p) continue;
			char *e;
			long fr = strtol(p, &e, 10);
			while (*e == ' ' || *e == '\t') e++;
			inputs[(int)fr] = parse_buttons(e);
		}
		fclose(f);
	}

	// Zapper script: the gun on NES port 2, as NES.sv with "Peripheral = Zapper(Joy1)",
	// "Zapper Trigger = Joystick", "Crosshairs = On". Lines "<frame> <x> <y> <fire>": aim at NES
	// pixel (x, y) and hold the Zapper/Vaus Btn (fire 1) from that frame until the next line.
	// The aim goes in as the analog stick value zapper.sv turns back into that pixel:
	// x = stick + 128, y = ((stick + 128) * 240) >> 8.
	struct Zap { unsigned analog; bool fire; };
	std::map<int, Zap> zaps;
	if (zapf) {
		FILE *f = fopen(zapf, "r");
		if (!f) { perror(zapf); return 2; }
		char line[256];
		while (fgets(line, sizeof line, f)) {
			char *p = line;
			while (*p == ' ' || *p == '\t') p++;
			if (*p == '#' || *p == '\n' || *p == '\r' || !*p) continue;
			int fr, x, y, fire;
			if (sscanf(p, "%d %d %d %d", &fr, &x, &y, &fire) != 4 || x < 0 || x > 255 || y < 0 || y > 239) {
				fprintf(stderr, "fullsim: bad --zap line: %s", line);
				return 2;
			}
			unsigned ya = 0;                  // smallest stick value that maps to y
			while (ya < 255 && ((ya * 240) >> 8) < (unsigned)y) ya++;
			if (((ya * 240) >> 8) != (unsigned)y) { fprintf(stderr, "fullsim: --zap y %d is not reachable\n", y); return 2; }
			unsigned ax = (unsigned)(x - 128) & 0xFF, ay = (ya - 128) & 0xFF;
			zaps[fr] = Zap{(ay << 8) | ax, fire != 0};
		}
		fclose(f);
		if (zaps.empty()) { fprintf(stderr, "fullsim: --zap %s has no lines\n", zapf); return 2; }
	}

	Verilated::commandArgs(argc, argv);
	top = new Vsim_top;
	top->hd_enable = 0;
	top->ex_sprites = ex_spr;
	top->hd_nolimit = nolimit;
	top->joy1 = 0;
	top->zap_en = !zaps.empty();
	top->zap_analog = 0;
	top->zap_fire = 0;
	top->w_lw_we = 0;
	top->w_list_n = 0;
	top->w_ext = !wlist.empty();                // --watch: the list comes from here, not the pack
	for (int i = 0; i < 200; i++) tick();
	for (size_t i = 0; i < wlist.size(); i++) {
		top->w_lw_we = 1;
		top->w_lw_idx = (uint8_t)i;
		top->w_lw_addr = wlist[i];
		tick();
	}
	top->w_lw_we = 0;
	top->w_list_n = (uint16_t)wlist.size();

	auto t_start = std::chrono::steady_clock::now();
	if (hdp) {
		auto pack = read_file(hdp);
#ifdef FULLSIM_ARM
		if (hd) {
			arm.pack = pack;
			if (hdarm_init(arm.pack.data(), arm.pack.size())) { fprintf(stderr, "arm: pack refused\n"); return 1; }
			arm.nw = hdarm_nwatched();
			arm.on = true;
			fprintf(stderr, "arm: display-list route, %u watched addresses, publication delay %llu lines\n",
			        arm.nw, (unsigned long long)(arm.delay / TICKS_PER_LINE));
		}
#endif
#ifdef FULLSIM_ARM
		pack_copy_load(pack);
#else
		ioctl_load(pack, 0x04, "hd pack");
#endif
		for (int i = 0; i < 100; i++) tick();
		if (pack.size() >= 0xF8) {                     // section 14 (header 0xF0 offset, 0xF4 size)
			uint32_t o14, n14; memcpy(&o14, &pack[0xF0], 4); memcpy(&n14, &pack[0xF4], 4);
			if (n14 && (uint64_t)o14 + n14 <= pack.size()) rf_s14.assign(pack.begin() + o14, pack.begin() + o14 + n14);
		}
		fprintf(stderr, "hd pack: %zu bytes streamed, %llu qwords written to DDR3\n", pack.size(),
		        (unsigned long long)n_ddr_wr);
		// what check_render.py needs to compare a frame with hdref: the overscan window (the
		// .rgb files are cropped to it, as hdref.render returns), and the pack's watched-address
		// list for the watch_FFFF.bin dumps (hd3_loader feeds the same list to hd_watch)
		if (pack.size() >= 0x100) {
			for (int k = 0; k < 4; k++) {
				int32_t v; memcpy(&v, &pack[0x10 + 4 * k], 4);
				hd_ov[k] = std::min(255, std::max(0, (int)v));
			}
			if (wlist.empty()) {
				uint32_t n, s9; memcpy(&n, &pack[0x34], 4); memcpy(&s9, &pack[0x80 + 9 * 8], 4);
				for (uint32_t i = 0; i < n && i < 256 && s9 + 4 * i + 4 <= pack.size(); i++) {
					uint32_t a; memcpy(&a, &pack[s9 + 4 * i], 4); wlist.push_back(a);
				}
			}
		}
	}
	top->hd_enable = hd;
	if (hdp && hd) {
		tick();
		if (!top->hd_active) { fprintf(stderr, "FAIL: HD pack not accepted (hd_active=0)\n"); return 1; }
		fprintf(stderr, "hd pack accepted (hd_active=1)\n");
	}

	auto romdata = read_file(rom);
	ioctl_load(romdata, 0x01, "rom");
	{
		int guard = 0;
		while (!top->loader_done_o) { tick(); if (++guard > 10000000) { fprintf(stderr, "loader never done\n"); return 1; } }
	}
	if (top->loader_fail_o) { fprintf(stderr, "FAIL: loader reported an error (bad header?)\n"); return 1; }
	fprintf(stderr, "rom: %zu bytes loaded\n", romdata.size());
	{
		int guard = 0;
		while (top->reset_nes_o) {
			tick();
			if ((now & 255) == 0) { rf_poll(); aud_poll(); }
			if (++guard > 10000000) { fprintf(stderr, "reset never released\n"); return 1; }
		}
	}
	uint64_t clk_reset_released = now;
	auto t_run = std::chrono::steady_clock::now();

	// capture state
	std::vector<uint8_t> nesidx(262 * 341, 0x0F);
	std::vector<uint8_t> vid(256 * 240 * 3, 0), hdbuf(512 * 480 * 3, 0);
	int frame = 0;                 // frame being drawn (0 = partial frame at reset release)
	unsigned last_cycle = top->cycle, last_sl = top->scanline;
	int since_change = 99;
	unsigned cur_cycle = 0, cur_sl = 0;
	int vrow = -1, vcol = 0;
	bool vhb_last = true, vvb_last = true;
	int hrow = -1, hcol = 0, hd_rows = 0;
	bool hhb_last = true, hvb_last = true;
	unsigned joy = 0;
	int saved = 0;
	int rec_pending_frame = -1;
	uint32_t rec_pending_cap = 0;
	uint64_t rec_pending_at = 0;
	std::vector<uint8_t> rec_chr(0x8000, 0);
	// watched-address snapshot: the model's memory at the snap pulse, written with hd_watch's
	// values once it reports done
	int w_pending_frame = -1;
	unsigned w_bank_sel = 0;
	std::vector<uint8_t> w_dump;
	std::string od = outdir;
	char name[512];
	FILE *audlog = audlogf ? open_out(audlogf) : nullptr;
	unsigned aud_n = 0;
	bool aud_wr_last = false;

	while (frame <= frames) {
		// joypad for this frame
		auto it = inputs.upper_bound(frame);
		if (it != inputs.begin()) joy = std::prev(it)->second;
		top->joy1 = joy;
		if (hd_off_at >= 0 && frame >= hd_off_at && top->hd_enable) {
			// the OSD "HD Pack" option switched Off mid-game (only the option: the pack stays)
			top->hd_enable = 0;
			fprintf(stderr, "frame %d: HD Pack option switched Off\n", frame);
		}
		if (!zaps.empty()) {
			auto zt = zaps.upper_bound(frame);
			if (zt != zaps.begin()) { top->zap_analog = std::prev(zt)->second.analog; top->zap_fire = std::prev(zt)->second.fire; }
		}

		tick();
		if ((now & 255) == 0) { rf_poll(); aud_poll(); }
#ifdef FULLSIM_ARM
		if (arm.on && (now & 255) == 0) arm_poll();
#endif

		// ---- stage 6: the CPU writes the device would see (one per strobe pulse) ----
		if (audlog) {
			bool wr = top->aud_bus_wr;
			if (wr && !aud_wr_last && top->aud_bus_a >= 0x4100 && top->aud_bus_a <= 0x417F) {
				fprintf(audlog, "%d %04x %02x\n", frame, (unsigned)top->aud_bus_a, (unsigned)top->aud_bus_d);
				aud_n++;
			}
			aud_wr_last = wr;
		}

		// ---- stage-2 frame record: dump a completed buffer once its writes have drained ----
		if (rec) {
			if (top->rec_frame_done) {
				rec_pending_frame = frame;                    // the fullsim frame being drawn
				rec_pending_cap   = top->rec_frame_num - 1;   // the capture frame just completed
				rec_pending_at    = now + 48000;              // 12000 core clocks, about 9 lines: FIFO long drained
				// CHR region (0x200000, 32 KB) as it is NOW, at the end of the visible lines:
				// CHR RAM is not written while rendering, so this is what the capture saw.
				// An independent copy for checking fingerprints (not the RTL's own shadow).
				for (int i = 0; i < 0x8000; i++) rec_chr[i] = top->rootp->sim_top__DOT__sdram__DOT__mem[0x200000 + i];
			}
			if (rec_pending_frame >= 0 && now >= rec_pending_at) {
				if (wanted(rec_pending_frame)) {
					uint32_t base = (0x3C000000u + ((rec_pending_cap & 1) ? 0x100000u : 0)) >> 3;
					std::vector<uint64_t> buf(0x100000 / 8);
					for (size_t i = 0; i < buf.size(); i++) buf[i] = ddr_get(base + (uint32_t)i);
					snprintf(name, sizeof name, "%s/rec_%04d.bin", od.c_str(), rec_pending_frame);
					FILE *rf = open_out(name);
					fwrite(buf.data(), 8, buf.size(), rf); fclose(rf);
					snprintf(name, sizeof name, "%s/chr_%04d.bin", od.c_str(), rec_pending_frame);
					FILE *xf = open_out(name);
					fwrite(rec_chr.data(), 1, rec_chr.size(), xf); fclose(xf);
					fprintf(stderr, "frame %d: record of capture frame %u written%s\n", rec_pending_frame,
					        rec_pending_cap, top->rec_overflow ? " (OVERFLOW SET)" : "");
				}
				rec_pending_frame = -1;
			}
		}

		// ---- stage-2 watched-address snapshot ----
		if (!wlist.empty()) {
			static bool snap_seen = false;
			auto *R = top->rootp;
			if (snap_seen) {
				// hd_watch froze its copies on this edge (it sees the registered snap one clock
				// after the tap raised it); a write on this edge counts for both.
				snap_seen = false;
				if (wanted(frame) && w_pending_frame < 0) {
					w_pending_frame = frame;
					w_bank_sel = (~top->rec_frame_num) & 1;   // hd_stage2 bank = ~frame_num[0]
					w_dump.clear();
					for (int i = 0; i < 0x800; i++) w_dump.push_back(R->sim_top__DOT__sdram__DOT__mem[0x380000 + i]);
					for (int i = 0; i < 0x800; i++) w_dump.push_back(R->sim_top__DOT__sdram__DOT__mem[0x3A0000 + i]);
					uint32_t rb = (uint32_t)R->sim_top__DOT__hd_stage2__DOT__u_watch__DOT__ram_base << 13;
					for (int i = 0; i < 0x2000; i++) w_dump.push_back(R->sim_top__DOT__sdram__DOT__mem[(rb + i) & 0x1FFFFFF]);
					for (int i = 0; i < 6; i++)
						for (int b = 0; b < 4; b++) w_dump.push_back((top->w_pal[i] >> (8 * b)) & 0xFF);
					for (int b = 0; b < 4; b++) w_dump.push_back((rb >> (8 * b)) & 0xFF);
				}
			}
			if (top->w_snap) snap_seen = true;
			if (top->w_done && w_pending_frame >= 0) {
				snprintf(name, sizeof name, "%s/watch_%04d.bin", od.c_str(), w_pending_frame);
				FILE *wf = open_out(name);
				{
					// "NWAT", n, then n x u32 list, n x u8 values, flags, then the dumps:
					// CPU RAM 2 KB, CIRAM 2 KB, PRG-RAM page 8 KB, palette 24 bytes, PRG-RAM base u32
					uint32_t n = (uint32_t)wlist.size(), flags = (top->w_overflow ? 1u : 0u) | (top->w_timeout ? 2u : 0u);
					fwrite("NWAT", 1, 4, wf);
					fwrite(&n, 4, 1, wf);
					fwrite(wlist.data(), 4, n, wf);
					for (uint32_t i = 0; i < n; i++) {
						uint8_t v = R->sim_top__DOT__hd_stage2__DOT__u_watch__DOT__vals[(w_bank_sel << 8) | i];
						fwrite(&v, 1, 1, wf);
					}
					fwrite(&flags, 4, 1, wf);
					fwrite(w_dump.data(), 1, w_dump.size(), wf);
					fclose(wf);
				}
				fprintf(stderr, "frame %d: watched-address snapshot written (%u entries%s%s)\n", w_pending_frame,
				        (unsigned)wlist.size(), top->w_overflow ? ", OVERFLOW SET" : "", top->w_timeout ? ", SDRAM TIMEOUT" : "");
				w_pending_frame = -1;
			}
		}

		// ---- PPU colour index: sample 2 clocks after each PPU tick (mid pixel) ----
		unsigned c = top->cycle, sl = top->scanline;
		if (c != last_cycle || sl != last_sl) {
			if (sl == 0 && last_sl != 0) {
				// a new frame starts: frame `frame` is complete
				if (frame >= 1 && wanted(frame)) {
					std::vector<uint8_t> rgb(256 * 240 * 3);
					for (int y = 0; y < 240; y++)
						for (int x = 0; x < 256; x++) {
							int cx = x + xoff;
							uint8_t ci = (cx < 341) ? (nesidx[y * 341 + cx] & 0x3F) : 0x0F;
							memcpy(&rgb[(y * 256 + x) * 3], &pal[ci * 3], 3);
						}
					snprintf(name, sizeof name, "%s/nes_%04d.png", od.c_str(), frame);
					write_png(name, 256, 240, rgb);
					snprintf(name, sizeof name, "%s/vid_%04d.png", od.c_str(), frame);
					write_png(name, 256, 240, vid);
					int diff = 0;
					for (size_t i = 0; i < rgb.size(); i += 3) if (memcmp(&rgb[i], &vid[i], 3)) diff++;
					fprintf(stderr, "frame %d: nes vs video.sv pixels differing: %d\n", frame, diff);
					if (rec) {
						snprintf(name, sizeof name, "%s/col_%04d.bin", od.c_str(), frame);
						FILE *cf = open_out(name);
						fwrite(nesidx.data(), 1, nesidx.size(), cf); fclose(cf);
					}
					saved++;
				}
				frame++;
			}
			cur_cycle = c; cur_sl = sl;
			since_change = 0;
			last_cycle = c; last_sl = sl;
		} else if (++since_change == 2) {
			if (cur_sl < 262 && cur_cycle < 341) nesidx[cur_sl * 341 + cur_cycle] = top->color;
		}

		// ---- video.sv RGB (the MiSTer's own NES picture) ----
		if (top->v_ce_pix) {
			bool hb = top->v_HB, vb = top->v_VB;
			if (!vb && vvb_last) vrow = 0;
			if (hb && !vhb_last && !vb && vcol > 0) { vrow++; }
			if (!hb) {
				if (vhb_last) vcol = 0;
				if (!vb && vrow >= 0 && vrow < 240 && vcol < 256) {
					uint8_t *p = &vid[(vrow * 256 + vcol) * 3];
					p[0] = top->v_R; p[1] = top->v_G; p[2] = top->v_B;
				}
				vcol++;
			}
			vhb_last = hb; vvb_last = vb;
		}

		// ---- HD engine output: one pixel per core clock ----
		if (hdp && hd) {
			bool hb = top->hd_hb, vb = top->hd_vb;
			if (!vb && hvb_last) { hrow = 0; hd_rows = 0; }
			if (vb && !hvb_last && hrow >= 0) {
				// HD frame finished during NES frame `frame`
				if (wanted(frame)) {
					snprintf(name, sizeof name, "%s/hd_%04d.png", od.c_str(), frame);
					write_png(name, 512, 480, hdbuf);
					fprintf(stderr, "frame %d: hd frame written (%d rows)\n", frame, hd_rows);
				}
				// the same picture as hdv_<capture frame>.rgb for check_render.py: the HD frame
				// shown during NES frame F was captured during F - 1 (rec_/watch_ F-1), cropped
				// to the pack's overscan window
				if (rec && wanted(frame - 1)) {
					int wy0 = 2 * hd_ov[0], wx0 = 2 * hd_ov[3];
					int wh = std::max(0, (240 - hd_ov[2] - hd_ov[0]) * 2), ww = std::max(0, (256 - hd_ov[1] - hd_ov[3]) * 2);
					std::vector<uint8_t> o((size_t)ww * wh * 3);
					for (int y = 0; y < wh; y++)
						memcpy(&o[(size_t)y * ww * 3], &hdbuf[((size_t)(y + wy0) * 512 + wx0) * 3], (size_t)ww * 3);
					snprintf(name, sizeof name, "%s/hdv_%04d.rgb", od.c_str(), frame - 1);
					FILE *vf = open_out(name);
					uint32_t hd[3] = {0x4247524Eu, (uint32_t)ww, (uint32_t)wh};
					fwrite(hd, 4, 3, vf); fwrite(o.data(), 1, o.size(), vf); fclose(vf);
				}
				hrow = -1;
			}
			if (hb && !hhb_last && !vb && hcol > 0) { hrow++; hd_rows = hrow; }
			if (!hb) {
				if (hhb_last) hcol = 0;
				if (!vb && hrow >= 0 && hrow < 480 && hcol < 512) {
					uint8_t *p = &hdbuf[(hrow * 512 + hcol) * 3];
					p[0] = top->hd_r; p[1] = top->hd_g; p[2] = top->hd_b;
				}
				hcol++;
			}
			hhb_last = hb; hvb_last = vb;
		}
	}

	auto t_end = std::chrono::steady_clock::now();
	double run_s = std::chrono::duration<double>(t_end - t_run).count();
	double tot_s = std::chrono::duration<double>(t_end - t_start).count();
	uint64_t clks = (now - clk_reset_released) / 4;     // `now` counts clk_f
	fprintf(stderr, "ran %d frames, %llu core clocks in %.1f s: %.2f frames/s (%.2f MHz, %.1f%% of real time); total %.1f s\n",
	        frames, (unsigned long long)clks, run_s, frames / run_s, clks / run_s / 1e6,
	        100.0 * (clks / run_s) / 21477272.0, tot_s);
	if (hdp) fprintf(stderr, "DDR3: %llu bursts read, %llu qwords written\n", (unsigned long long)n_ddr_rd, (unsigned long long)n_ddr_wr);
	if (hdp)
		fprintf(stderr, "audio ARM half: %u ticks rendered, %u events, %u pack resets, %u bad events, "
		        "%u fetch failures; hd3_audio underruns %u\n", aud_a.ticks, aud_a.events, aud_a.resets,
		        aud_a.bad_events, aud_a.fetch_fail, (unsigned)top->hd_aud_underruns);
	if (hdp && hd)
		fprintf(stderr, "hd3_engine: frames drawn %u dropped %u, ADDs aborted %u, underflow %u, overrun %u, "
		        "dictionary overflow %u\n", (unsigned)top->hd_frames_drawn, (unsigned)top->hd_frames_dropped,
		        (unsigned)top->hd_adds_aborted, (unsigned)top->hd_underflow, (unsigned)top->hd_overrun,
		        (unsigned)top->hd_dict_overflow);
#ifdef FULLSIM_ARM
	if (arm.on)
		fprintf(stderr, "arm: %u frame records taken, %u lists published, largest %zu qwords\n",
		        arm.frames, arm.published, arm.max_q);
#endif
	fprintf(stderr, "saved %d frame(s) to %s\n", saved, outdir);
	if (audlog) {
		fprintf(audlog, "# %u writes in %d frames\n", aud_n, frames);
		fclose(audlog);
		fprintf(stderr, "audio register writes: %u logged to %s\n", aud_n, audlogf);
	}
	top->final();
	delete top;
	return 0;
}
