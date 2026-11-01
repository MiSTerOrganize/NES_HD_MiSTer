// Verilator testbench for rtl/hdpack/hd_watch.sv.
//
// A software model of the core's memory (SDRAM, sparse), its CPU/PPU mappings and the palette
// drives hd_watch with the access patterns the core produces: CPU reads and writes at CPU
// speed, PPU pattern and nametable fetches, mirroring and bank changes, four-screen pages,
// and savestate restores that write ALL of SDRAM. Snapshots are taken at random moments while
// writes keep arriving (the freeze FIFO must hold them), and every watched value is compared
// with the model's memory as it was at the snapshot clock, read through the mapping the last
// access before that clock used (the definition hd_watch implements).
//
//   tb_watch.exe [--seed S]       exit 0 = every value of every snapshot matched, no overflow
#include "Vhd_watch.h"
#include "verilated.h"
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <deque>
#include <random>
#include <unordered_map>
#include <vector>

double sc_time_stamp() { return 0; }

static Vhd_watch *t;
static std::mt19937 rng;
static uint32_t rnd(uint32_t n) { return rng() % n; }

// ---------------- model ----------------
static std::unordered_map<uint32_t, uint8_t> sd;   // SDRAM, 25-bit byte address, default 0
static uint8_t rd8(uint32_t a) { auto it = sd.find(a); return it == sd.end() ? 0 : it->second; }

static const uint32_t CPURAM = 0x380000, PRGRAM = 0x3C0000, CIRAM = 0x3A0000, FOUR = 0x3F0800;
static uint32_t prg_bank[16];      // current SDRAM 2 KB page for $8000 + p*0x800
static uint32_t chr_bank[8];       // current SDRAM 1 KB page (22-bit lin >> 10)
static int      mirror = 0;        // 0 vertical, 1 horizontal, 2 single A, 3 four-screen
static uint8_t  pal[32];

// "last used" mappings, exactly as hd_watch records them
static int32_t  m_prg[16], m_chr[8], m_q[4], m_ram = -1;

static uint32_t nt_page(int q) {   // SDRAM page (lin >> 10) of nametable quadrant q
	switch (mirror) {
	case 0:  return (CIRAM >> 10) + (q & 1);
	case 1:  return (CIRAM >> 10) + (q >> 1);
	case 2:  return CIRAM >> 10;
	default: return q < 2 ? (CIRAM >> 10) + q : (FOUR >> 10) + (q - 2);
	}
}

// pending strobes for this clock
struct Ev { int kind; uint32_t a, lin; uint8_t d; bool wr; };
static uint64_t clocks = 0;
static int fails = 0;

static void clear_inputs() {
	t->cpu_rd = 0; t->cpu_wr = 0; t->ppu_rd = 0; t->ppu_wr = 0; t->ss_wr = 0; t->snap = 0; t->lw_we = 0;
}

// SDRAM read responder for pass 2
static int sr_wait = -1;
static void sdram_port() {
	t->sr_ack = 0;
	if (t->sr_req) {
		if (sr_wait < 0) sr_wait = 3 + rnd(30);
		if (sr_wait-- == 0) { t->sr_ack = 1; t->sr_q = rd8(t->sr_addr); sr_wait = -1; }
	}
}

static void set_pal() {
	// pal_all is 192 bits = 6 x 32-bit words in Verilator
	uint32_t w[6] = {0};
	for (int n = 0; n < 32; n++)
		for (int b = 0; b < 6; b++)
			if (pal[n] >> b & 1) { int bit = n * 6 + b; w[bit / 32] |= 1u << (bit % 32); }
	for (int i = 0; i < 6; i++) t->pal_all[i] = w[i];
}

static bool was_cpu = false, was_ppu = false, was_ss = false;
static void tick() {
	sdram_port();
	t->clk = 0; t->eval(); t->clk = 1; t->eval(); clocks++;
	was_cpu = t->cpu_rd || t->cpu_wr;
	was_ppu = t->ppu_rd || t->ppu_wr;
	was_ss  = t->ss_wr;
	clear_inputs();
}

// Accesses are strobes, like the core's (which are many clocks apart: one CPU access per CPU
// cycle, 12 core clocks); hd_watch, like the SDRAM controller, counts rising edges, so a strobe
// right after another of the same kind first gets one low clock.
static void cpu_access(uint16_t a, bool wr, uint8_t d) {
	if (was_cpu) tick();
	uint32_t lin;
	if (a < 0x2000) lin = CPURAM + (a & 0x7FF);
	else if (a >= 0x6000 && a < 0x8000) lin = PRGRAM + (a & 0x1FFF);
	else if (a >= 0x8000) lin = (prg_bank[(a >> 11) & 15] << 11) | (a & 0x7FF);
	else lin = 0;
	t->cpu_a = a; t->cpu_lin = lin; t->cpu_d = d;
	if (wr) t->cpu_wr = 1; else t->cpu_rd = 1;
	if (a >= 0x8000) { m_prg[(a >> 11) & 15] = lin >> 11; }
	if (a >= 0x6000 && a < 0x8000) m_ram = lin >> 13;
	if (wr && (a < 0x2000 || (a >= 0x6000 && a < 0x8000))) sd[lin] = d;
}

static void ppu_access(uint16_t a, bool wr, uint8_t d) {
	if (was_ppu) tick();
	a &= 0x3FFF;
	uint32_t lin;
	if (a < 0x2000) lin = (chr_bank[a >> 10] << 10) | (a & 0x3FF);
	else lin = (nt_page((a >> 10) & 3) << 10) | (a & 0x3FF);
	t->ppu_a = a; t->ppu_lin = lin; t->ppu_d = d;
	if (wr) t->ppu_wr = 1; else t->ppu_rd = 1;
	if (a < 0x2000) m_chr[a >> 10] = lin >> 10;
	else m_q[(a >> 10) & 3] = lin >> 10;
	if (wr && a >= 0x2000) sd[lin] = d;     // pattern ROM is never written
}

// expected value of a watched entry, from the model state at the snapshot clock
static uint8_t expect(uint32_t e) {
	if (e & 0x80000000u) {
		uint32_t p = e & 0x3FFF;
		if (p >= 0x3F00) {
			int i = p & 0x1F;
			if ((i & 0x13) == 0x10) i &= 0x0F;
			return pal[i] & 0x3F;
		}
		if (p < 0x2000) {
			int32_t b = m_chr[p >> 10];
			return b < 0 ? 0 : rd8(((uint32_t)b << 10) | (p & 0x3FF));
		}
		int32_t b = m_q[(p >> 10) & 3];
		return b < 0 ? 0 : rd8(((uint32_t)b << 10) | (p & 0x3FF));
	}
	uint32_t c = e & 0xFFFF;
	if (c < 0x2000) return rd8(CPURAM + (c & 0x7FF));
	if (c < 0x6000) return 0;
	if (c < 0x8000) return rd8(PRGRAM + (c & 0x1FFF));
	int32_t b = m_prg[(c >> 11) & 15];
	return b < 0 ? 0 : rd8(((uint32_t)b << 11) | (c & 0x7FF));
}

static void random_access() {
	switch (rnd(10)) {
	case 0: case 1: cpu_access(rnd(0x2000), true, rnd(256)); break;
	case 2:         cpu_access(0x6000 + rnd(0x2000), rnd(2), rnd(256)); break;
	case 3:         cpu_access(0x8000 + rnd(0x8000), false, 0); break;
	case 4:         cpu_access(rnd(0x2000), false, 0); break;
	case 5:         ppu_access(rnd(0x2000), false, 0); break;
	case 6:         ppu_access(0x2000 + rnd(0x1F00), true, rnd(256)); break;
	case 7:         ppu_access(0x2000 + rnd(0x1F00), false, 0); break;
	case 8:         if (!rnd(40)) prg_bank[rnd(16)] = rnd(64); break;   // bank switch
	default:        if (!rnd(60)) mirror = rnd(4);
	                else if (!rnd(40)) chr_bank[rnd(8)] = 0x800 + rnd(128);
	                else if (!rnd(30)) { pal[rnd(32)] = rnd(64); set_pal(); }
	}
}

// ---------------- test ----------------
static std::vector<uint32_t> list;

static void load_list(int n) {
	list.clear();
	for (int i = 0; i < n; i++) {
		uint32_t e;
		switch (rnd(9)) {
		case 0: case 1: e = rnd(0x2000); break;                         // CPU RAM incl. mirrors
		case 2:         e = 0x6000 + rnd(0x2000); break;                // PRG-RAM
		case 3:         e = 0x8000 + rnd(0x8000); break;                // PRG-ROM
		case 4:         e = 0x2000 + rnd(0x4000); break;                // registers: 0
		case 5:         e = 0x80000000u | rnd(0x2000); break;           // pattern
		case 6:         e = 0x80000000u | (0x2000 + rnd(0x1F00)); break; // nametable (incl $3000)
		default:        e = 0x80000000u | (0x3F00 + rnd(0x100)); break; // palette (incl mirrors)
		}
		list.push_back(e);
		t->lw_we = 1; t->lw_idx = i; t->lw_addr = e; tick();
	}
	t->list_n = n;
}

static int snapshot(bool bank, int busy) {
	// the snapshot clock: writes this clock count, mappings are the ones before it
	int32_t s_prg[16], s_chr[8], s_q[4];
	memcpy(s_prg, m_prg, sizeof s_prg); memcpy(s_chr, m_chr, sizeof s_chr); memcpy(s_q, m_q, sizeof s_q);
	if (busy) random_access();
	memcpy(m_prg, s_prg, sizeof s_prg); memcpy(m_chr, s_chr, sizeof s_chr); memcpy(m_q, s_q, sizeof s_q);
	std::vector<uint8_t> want;
	for (uint32_t e : list) want.push_back(expect(e));
	t->snap = 1; t->bank = bank;
	tick();
	// keep the machine busy while it works: the freeze FIFO must hold these
	uint64_t start = clocks;
	while (!t->done) {
		if (clocks - start > 200000) { printf("  snapshot never finished\n"); return 1; }
		if (busy && rnd(12) == 0) random_access();
		tick();
	}
	int bad = 0;
	for (size_t i = 0; i < list.size(); i++) {
		t->v_bank = bank; t->v_idx = i; tick(); tick();
		if (t->v_q != want[i]) {
			if (bad < 6) printf("  entry %zu (%08x): got %02x want %02x\n", i, list[i], t->v_q, want[i]);
			bad++;
		}
	}
	return bad;
}

int main(int argc, char **argv) {
	unsigned seed = 1;
	for (int i = 1; i < argc; i++) if (!strcmp(argv[i], "--seed") && i + 1 < argc) seed = atoi(argv[++i]);
	rng.seed(seed);
	Verilated::commandArgs(argc, argv);
	t = new Vhd_watch;
	clear_inputs();
	t->enable = 1; t->reset = 1; t->list_n = 0; t->sr_ack = 0;
	for (int i = 0; i < 16; i++) { prg_bank[i] = rnd(64); m_prg[i] = -1; }
	for (int i = 0; i < 8; i++)  { chr_bank[i] = 0x800 + rnd(128); m_chr[i] = -1; }
	for (int i = 0; i < 4; i++)  m_q[i] = -1;
	for (int i = 0; i < 32; i++) pal[i] = rnd(64);
	set_pal();
	// ROM content: PRG pages 0..63 (2 KB each) and CHR pages 0x800..0x87F (1 KB each)
	for (uint32_t p = 0; p < 64; p++) for (int k = 0; k < 2048; k += 7) sd[(p << 11) | k] = rnd(256);
	for (uint32_t p = 0x800; p < 0x880; p++) for (int k = 0; k < 1024; k += 5) sd[(p << 10) | k] = rnd(256);
	for (int i = 0; i < 8; i++) tick();
	t->reset = 0;

	int total = 0, snaps = 0;
	// phase 1: 256 entries, quiet snapshots
	load_list(256);
	for (int i = 0; i < 3000; i++) random_access(), tick(), tick();
	total += snapshot(false, 0); snaps++;
	// phase 2: busy snapshots (writes during the freeze), both banks
	for (int r = 0; r < 12; r++) {
		for (int i = 0; i < 2000 + (int)rnd(4000); i++) { random_access(); tick(); if (rnd(2)) tick(); }
		total += snapshot(r & 1, 1); snaps++;
	}
	// phase 3: four-screen and mirroring changes, short list
	load_list(40);
	for (int r = 0; r < 8; r++) {
		mirror = r % 4;
		for (int i = 0; i < 3000; i++) { random_access(); tick(); }
		total += snapshot(r & 1, 1); snaps++;
	}
	// phase 4: a savestate restore writes all of SDRAM's relevant regions (and garbage
	// elsewhere, which must not disturb anything), then snapshot
	load_list(200);
	for (int i = 0; i < 2000; i++) { random_access(); tick(); }
	for (int k = 0; k < 6000; k++) {
		uint32_t a;
		switch (rnd(5)) {
		case 0:  a = CPURAM + rnd(0x800); break;
		case 1:  a = PRGRAM + rnd(0x2000); break;
		case 2:  a = CIRAM + rnd(0x800); break;
		case 3:  a = 0x100000 + rnd(0x100000); break;   // elsewhere: not a nametable page
		default: a = FOUR + rnd(0x800); break;          // four-screen page: kept only if known
		}
		uint8_t d = rnd(256);
		t->ss_wr = 1; t->ss_addr = a; t->ss_d = d; tick(); tick();
		// A restore writes SDRAM. The four-screen pages were written by the PPU in phase 3,
		// so hd_watch knows them and must follow these writes too; the 0x1xxxxx writes must
		// not claim a nametable slot (that would evict a four-screen page and set overflow).
		sd[a] = d;
	}
	for (int r = 0; r < 4; r++) {
		for (int i = 0; i < 1000; i++) { random_access(); tick(); }
		total += snapshot(r & 1, 1); snaps++;
	}

	printf("seed %u: %d snapshots, %d value mismatches, overflow %d, %llu clocks\n", seed, snaps, total,
	       (int)t->overflow, (unsigned long long)clocks);
	bool ok = total == 0 && !t->overflow;
	printf("%s\n", ok ? "PASS" : "FAIL");
	delete t;
	return ok ? 0 : 1;
}
