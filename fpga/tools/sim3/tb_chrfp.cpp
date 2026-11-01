// Verilator testbench for rtl/hdpack/hd_chrfp.sv (32 KB CHR RAM, 2048 tiles).
//
// A software model holds the same 32 KB. Writes are driven in the patterns the core produces
// (a game uploading tiles through $2007 with CPU-speed gaps; a savestate restore writing every
// clock; writes aimed at a tile while it is being recomputed). After each phase the testbench
// waits for `idle` and compares EVERY tile's fingerprint with a CRC-64 computed here.
//
//   tb_chrfp.exe [--seed S]          exit 0 = all tiles match after every phase
#include "Vhd_chrfp_tb_top.h"
#include "Vhd_chrfp_tb_top___024root.h"
#include "verilated.h"
#include <cstdio>
#include <cstdint>
#include <cstring>
#include <cstdlib>
#include <random>
#include <vector>

double sc_time_stamp() { return 0; }

static uint64_t T64[256];
static void crc_init() {
	for (int b = 0; b < 256; b++) {
		uint64_t r = (uint64_t)b << 56;
		for (int i = 0; i < 8; i++) r = (r & (1ull << 63)) ? (r << 1) ^ 0x42F0E1EBA9EA3693ull : (r << 1);
		T64[b] = r;
	}
}
static uint64_t crc64(const uint8_t *d, int n) {
	uint64_t r = 0;
	for (int i = 0; i < n; i++) r = (r << 8) ^ T64[((r >> 56) ^ d[i]) & 0xFF];
	return r;
}

static Vhd_chrfp_tb_top *t;
static uint64_t clocks = 0;
static int fails = 0;
static int false_idle = 0;
static bool prev_idle = false;

// every clock: an idle that drops again without a write in between was false (work remained)
static void tick() {
	bool wrote = t->wr;
	t->clk = 0; t->eval(); t->clk = 1; t->eval(); clocks++;
	if (prev_idle && !t->idle && !wrote) {
		if (false_idle < 3) printf("  false idle: idle dropped at clock %llu with no write\n", (unsigned long long)clocks);
		false_idle++;
	}
	prev_idle = t->idle;
}

static std::vector<uint8_t> model(32768, 0);

static void put(uint32_t a, uint8_t v) {
	t->wr = 1; t->wr_addr = a; t->wr_data = v; tick(); t->wr = 0;
	model[a] = v;
}

static bool wait_idle(uint64_t limit) {
	uint64_t start = clocks;
	// idle must be seen on two consecutive clocks (it is registered state)
	int seen = 0;
	while (clocks - start < limit) { tick(); seen = t->idle ? seen + 1 : 0; if (seen >= 2) break; }
	if (seen < 2) return false;
	// and once idle, with no writes, it must STAY idle for longer than a full sweep (2048 tiles x
	// 18 clocks): an idle reported while dirty tiles remain would end when the scanner finds one.
	// Without this the check below is blind to an early idle, because reading all 2048 tiles
	// takes long enough for the scanner to finish behind it.
	for (int i = 0; i < 40000; i++) {
		tick();
		if (!t->idle) { printf("  idle dropped %d clocks after it was reported, with no writes\n", i); fails++; return true; }
	}
	return true;
}

static void check_all(const char *phase) {
	int bad = 0;
	for (int tile = 0; tile < 2048; tile++) {
		t->fp_tile = tile; tick();
		uint64_t want = crc64(&model[tile * 16], 16);
		if (t->fp_q != want) {
			if (bad < 5) printf("  %s: tile %d fp %016llx want %016llx\n", phase, tile,
			                    (unsigned long long)t->fp_q, (unsigned long long)want);
			bad++;
		}
	}
	printf("%s: %d of 2048 tiles wrong\n", phase, bad);
	if (bad) fails++;
}

int main(int argc, char **argv) {
	unsigned seed = 3;
	for (int i = 1; i + 1 < argc; i += 2) if (!strcmp(argv[i], "--seed")) seed = atoi(argv[i + 1]);
	crc_init();
	std::mt19937 rng(seed);
	t = new Vhd_chrfp_tb_top;
	t->wr = 0; t->reset = 1; tick(); tick(); t->reset = 0;

	// phase 0: fill all of CHR RAM, one byte per clock (a savestate restore)
	for (uint32_t a = 0; a < 32768; a++) put(a, rng() & 0xFF);
	uint64_t c0 = clocks;
	if (!wait_idle(200000)) { printf("phase 0: never idle\n"); return 1; }
	printf("phase 0: full 32 KB restore, idle %llu clocks after the last write\n", (unsigned long long)(clocks - c0));
	check_all("phase 0 (bulk restore)");

	// phase 1: game-style uploads - runs of 16..256 bytes to a random tile-aligned address,
	// one byte every 48..120 clocks (CPU STA $2007 pacing), with long gaps between runs
	for (int run = 0; run < 400; run++) {
		uint32_t a = (rng() % 2048) * 16;
		int len = 16 + rng() % 241;
		for (int i = 0; i < len; i++) {
			put((a + i) & 0x7FFF, rng() & 0xFF);
			int gap = 47 + rng() % 73;
			for (int g = 0; g < gap; g++) tick();
		}
		if (rng() % 10 == 0) for (int g = 0; g < 2000; g++) tick();
	}
	if (!wait_idle(200000)) { printf("phase 1: never idle\n"); return 1; }
	check_all("phase 1 (paced uploads)");

	// phase 2: hammer single tiles - writes to the same tile every 1..20 clocks, so many land
	// while that tile's recompute is in progress
	for (int rep = 0; rep < 3000; rep++) {
		uint32_t tile = rng() % 2048;
		int n = 1 + rng() % 40;
		for (int i = 0; i < n; i++) {
			put(tile * 16 + (rng() & 15), rng() & 0xFF);
			int gap = rng() % 20;
			for (int g = 0; g < gap; g++) tick();
		}
	}
	if (!wait_idle(500000)) { printf("phase 2: never idle\n"); return 1; }
	check_all("phase 2 (writes during recompute)");

	// phase 3: back-to-back writes across word boundaries (tiles 31/32, 63/64 ...), every clock
	for (int rep = 0; rep < 2000; rep++) {
		uint32_t w = rng() % 64;
		for (int i = 0; i < 64; i++) put(((w * 32 * 16) + 31 * 16 + i) & 0x7FFF, rng() & 0xFF);
	}
	if (!wait_idle(500000)) { printf("phase 3: never idle\n"); return 1; }
	check_all("phase 3 (word boundaries, every clock)");

	// phase 4: a write to a CLEAN tile on the exact clock the scanner reads that tile's dirty
	// bit (rs == SCAN, ph == 0, scan_p == tile). The block-RAM read returns the old bit, so this
	// pass misses the write; idle must still wait for the next pass to see it.
	auto *R = t->rootp;
	int aimed = 0;
	for (int rep = 0; rep < 60; rep++) {
		uint32_t tile = rng() % 2048;
		bool hit = false;
		for (int c = 0; c < 20000 && !hit; c++) {
			if (R->hd_chrfp_tb_top__DOT__u__DOT__rs == 1 && R->hd_chrfp_tb_top__DOT__u__DOT__ph == 0 &&
			    R->hd_chrfp_tb_top__DOT__u__DOT__scan_p == tile) {
				put(tile * 16 + (rng() & 15), rng() & 0xFF);
				hit = true;
			} else tick();
		}
		if (!hit) { printf("phase 4: scanner never reached tile %u\n", tile); fails++; break; }
		aimed++;
		if (!wait_idle(200000)) { printf("phase 4: never idle\n"); return 1; }
	}
	check_all("phase 4 (write on the scanner's read clock)");
	printf("phase 4: %d writes aimed at the scanner's read clock\n", aimed);

	if (false_idle) fails++;
	printf("%llu clocks, %d false idles, %d failures\n", (unsigned long long)clocks, false_idle, fails);
	delete t;
	return fails ? 1 : 0;
}
