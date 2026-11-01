// Verilator testbench for rtl/hdpack/hd_capture.sv (with a real hd_chrfp behind it).
//
// Drives a PPU-shaped tap stream: 262 lines per frame, a dot every 4 clocks, sprite fetches
// at dots 264..320 and BG prefetch at 328/336 of the line BEFORE the one they belong to, BG
// fetches at dots 8..256 and pixels at dots 1..256 of their own line, line_done at dot 256 of
// every line, pre-render = line 261. Lines vary between normal, rendering-off (branch A),
// forced-blank with v in $3F00 (branch B) and mixed, so the stale-field rules are exercised
// across frames. CHR RAM changes in vblank, so the fingerprints change between frames.
//
// A software model applies the same record layout (HDPACK_DESIGN.md "Frame record") to its
// own 2 MB image; the DDR3 sink applies the RTL's writes, with byte enables, to another.
// After each frame the two images must be identical, and `overflow` must stay 0.
// Then a starvation phase (the FIFO never drains) must SET `overflow`.
//
//   tb_capture.exe [--seed S] [--frames N] [--ready P]     exit 0 = all frames match
#include "Vhd_capture_tb_top.h"
#include "verilated.h"
#include <cstdio>
#include <cstdint>
#include <cstring>
#include <cstdlib>
#include <random>
#include <vector>

double sc_time_stamp() { return 0; }

static const uint32_t REC_BASE = 0xC000000;
static const uint32_t IMG = 0x200000;

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

static Vhd_capture_tb_top *t;
static std::mt19937 rng;
static double ready_p = 0.6;
static bool starve = false;
static int busy_left = 0;
static uint64_t clocks = 0;

static std::vector<uint8_t> dimg(IMG, 0), mimg(IMG, 0);
static std::vector<uint8_t> chr(32768, 0);
static uint8_t pal[32];

static void sink() {
	if (t->wq_valid && t->wq_ready) {
		uint32_t off = ((uint32_t)t->wq_addr << 3) - REC_BASE;
		if (off + 8 > IMG) { printf("write outside the record: byte %08x\n", ((uint32_t)t->wq_addr << 3)); exit(2); }
		for (int i = 0; i < 8; i++)
			if (t->wq_be & (1 << i)) dimg[off + i] = (uint8_t)(t->wq_data >> (8 * i));
	}
}

static void tick() {
	t->clk = 0; t->eval();
	sink();
	t->clk = 1; t->eval();
	clocks++;
	// next cycle's ready
	if (starve) t->wq_ready = 0;
	else if (busy_left > 0) { busy_left--; t->wq_ready = 0; }
	else {
		if (rng() % 2000 == 0) busy_left = 50 + rng() % 300;     // DDR3 refresh / other client
		t->wq_ready = (rng() % 1000) < (unsigned)(ready_p * 1000);
	}
}

static void set_pal() {
	for (int w = 0; w < 6; w++) t->pal_all[w] = 0;
	for (int n = 0; n < 32; n++)
		for (int b = 0; b < 6; b++)
			if (pal[n] >> b & 1) t->pal_all[(6 * n + b) / 32] |= 1u << ((6 * n + b) % 32);
}

static void clear_pulses() {
	t->bg_we = 0; t->spr_we = 0; t->px_we = 0; t->line_done = 0; t->line_pre = 0;
	t->chr_wr = 0;
}

// ---------------- model ----------------
struct M {
	uint32_t frame = 1;
	int build = -1;
	uint8_t h_pal[32];
	uint32_t h_t = 0, h_fx = 0, h_gray = 0, h_emph = 0, h_a = 0;
	int cnt_span = 0, cnt_spr = 0, cnt_sprv = 0;
	uint32_t even = 0; uint8_t even_be = 0; bool even_ok = false;
} m;

static uint32_t mbuf() { return (m.frame & 1) ? 0x100000 : 0; }
static void mput(uint32_t off, uint64_t d, uint8_t be) {
	for (int i = 0; i < 8; i++) if (be & (1 << i)) mimg[off + i] = (uint8_t)(d >> (8 * i));
}
static uint8_t rpal(int a) { a &= 31; if ((a & 3) == 0) a &= 15; return pal[a] & 63; }

static void m_pixel(int x, int slot, int fx, int bgc, int bg_on, int spr_on, int bb,
                    uint32_t tt, int finex, int gray, int emph) {
	if (m.build < 0) return;
	int cidx = bg_on ? (bgc & 3) : 0;
	uint32_t d; uint8_t be;
	if (bb) { d = 0x3F; be = 1; }
	else {
		int b2 = rpal(0);
		int b3 = cidx ? rpal(((bgc >> 2) & 3) * 4 + cidx) : b2;
		d = (uint32_t)(bg_on ? slot : 63) | (spr_on << 6) | ((cidx | (fx << 2)) << 8) | (b2 << 16) | (b3 << 24);
		be = 0xF;
	}
	if (x == 0) {
		m.h_a = !bb;
		if (!bb) { m.h_t = tt; m.h_fx = finex; m.h_gray = gray; m.h_emph = emph; }
	}
	if (!bb && (bg_on || spr_on)) memcpy(m.h_pal, pal, 32);
	if (!(x & 1)) { m.even = d; m.even_be = be; m.even_ok = true; }
	else {
		uint64_t q = ((uint64_t)d << 32) | (m.even_ok ? m.even : 0);
		uint8_t qbe = (be << 4) | (m.even_ok ? m.even_be : 0);
		mput(mbuf() + m.build * 1024 + (x >> 1) * 8, q, qbe);
		m.even_ok = false;
	}
}
static void m_entry(uint32_t off, uint64_t qa, uint32_t lin, bool chr_ram) {
	uint32_t tile = (lin >> 4) & 0x7FF;
	uint64_t fp = chr_ram ? crc64(&chr[tile * 16], 16) : 0;
	mput(off, qa, 0xFF);
	mput(off + 8, fp, 0xFF);
}
static void m_span(int slot, uint32_t lin, int p, bool chr_ram) {
	if (m.build < 0) return;
	uint64_t qa = (1ull << 63) | ((uint64_t)p << 32) | lin;
	m_entry(mbuf() + 0x40000 + m.build * 2048 + 64 + slot * 16, qa, lin, chr_ram);
	if (slot + 1 > m.cnt_span) m.cnt_span = slot + 1;
}
static void m_sprite(int idx, uint64_t data, bool chr_ram) {
	if (m.build < 0) return;
	m_entry(mbuf() + 0x40000 + m.build * 2048 + 640 + idx * 16, data, (uint32_t)(data >> 16) & 0x3FFFFF, chr_ram);
	m.cnt_spr++;
	if (data >> 54 & 1) m.cnt_sprv++;
}
static void m_line_done(int y, bool pre) {
	if (y < 240) {
		uint64_t q0 = (uint64_t)m.h_t | ((uint64_t)m.h_fx << 15) | ((uint64_t)m.h_gray << 18) |
		              ((uint64_t)m.h_emph << 19) | ((uint64_t)m.h_a << 24) |
		              ((uint64_t)m.cnt_span << 32) | ((uint64_t)m.cnt_sprv << 40) |
		              ((uint64_t)m.cnt_spr << 48) | ((uint64_t)(y & 255) << 56);
		uint32_t off = mbuf() + 0x40000 + y * 2048;
		mput(off, q0, m.h_a ? 0xFF : 0xF8);
		uint64_t pq[3] = {0, 0, 0};
		for (int n = 0; n < 32; n++)
			for (int b = 0; b < 6; b++)
				if (m.h_pal[n] >> b & 1) pq[(6 * n + b) / 64] |= 1ull << ((6 * n + b) % 64);
		for (int i = 0; i < 3; i++) mput(off + 8 + i * 8, pq[i], 0xFF);
	}
	m.cnt_span = m.cnt_spr = m.cnt_sprv = 0;
	m.even_ok = false;
	if (y == 239) { mput(mbuf() + 0xF0000, m.frame, 0xFF); m.frame++; }
	if (pre) m.build = 0;
	else if (y < 239) m.build = y + 1;
	else m.build = -1;
}

// ---------------- stimulus ----------------
struct LineSpec { int mode; };

static int fails = 0;

static void run_frame(bool chr_ram, int frame_index) {
	// per-line modes for this frame
	int mode[262];
	for (int y = 0; y < 262; y++) {
		int r = rng() % 100;
		mode[y] = r < 70 ? 0 : r < 80 ? 1 : r < 90 ? 2 : 3;
	}
	mode[0] = 0;   // a rendered dot early, so the palette latch is defined
	t->chr_ram = chr_ram;
	for (int y = 0; y < 262; y++) {
		for (int dot = 0; dot <= 340; dot++) {
			clear_pulses();
			bool vis = y < 240;
			bool fetch_line = vis || y == 261;
			// palette writes only where the line has no rendered dot
			if (vis && (mode[y] == 1 || mode[y] == 2) && rng() % 40 == 0) { pal[rng() % 32] = rng() & 63; set_pal(); }
			if (vis && dot >= 1 && dot <= 256) {
				int x = dot - 1;
				int bb = mode[y] == 2 ? 1 : mode[y] == 3 ? (rng() % 5 == 0) : 0;
				int bg_on = mode[y] == 0 || mode[y] == 3 ? (rng() % 8 != 0) : 0;
				int spr_on = mode[y] == 0 || mode[y] == 3 ? (rng() % 3 == 0) : 0;
				t->px_we = 1; t->px_x = x; t->px_slot = rng() % 34; t->px_fx = rng() & 7;
				t->px_bgc = rng() & 15; t->px_bg_on = bg_on; t->px_spr_on = spr_on; t->px_branch_b = bb;
				t->px_t = rng() & 0x7FFF; t->px_finex = rng() & 7; t->px_gray = rng() & 1; t->px_emph = rng() & 7;
				m_pixel(x, t->px_slot, t->px_fx, t->px_bgc, bg_on, spr_on, bb, t->px_t, t->px_finex, t->px_gray, t->px_emph);
			}
			// BG fetches belonging to THIS line (slots 2..33) and prefetch for the next (0,1)
			if (fetch_line && ((vis && dot >= 8 && dot <= 256 && dot % 8 == 0) || dot == 328 || dot == 336)) {
				int slot = dot == 328 ? 0 : dot == 336 ? 1 : dot / 8 + 1;
				uint32_t lin = (rng() & 0x7FF0) | (rng() & 7);
				t->bg_we = 1; t->bg_slot = slot; t->bg_lin = lin; t->bg_pal = rng() & 3;
				m_span(slot, lin, t->bg_pal, chr_ram);
			}
			// sprite fetches for the next line
			if (fetch_line && dot >= 264 && dot <= 320 && dot % 8 == 0) {
				int idx = (dot - 264) / 8;
				uint64_t lin = (rng() & 0x7FF0) | (rng() & 0xF);
				uint64_t data = ((uint64_t)(rng() % 4 != 0) << 54) | ((uint64_t)(rng() & 255) << 46) |
				                ((uint64_t)(rng() & 255) << 38) | (lin << 16) | (rng() & 0xFFFF);
				t->spr_we = 1; t->spr_idx = idx; t->spr_data = data;
				m_sprite(idx, data, chr_ram);
			}
			if (dot == 256) {
				t->line_done = 1; t->line_y = y; t->line_pre = (y == 261);
				m_line_done(y, y == 261);
			}
			tick();
			clear_pulses();
			for (int k = 0; k < 3; k++) tick();
		}
		// vblank: change CHR RAM, let the fingerprints settle, and check the finished frame
		if (y == 245 && chr_ram) {
			int n = rng() % 2000;
			for (int i = 0; i < n; i++) {
				uint32_t a = rng() & 0x7FFF; uint8_t v = rng();
				t->chr_wr = 1; t->chr_addr = a; t->chr_data = v; chr[a] = v; tick();
			}
			clear_pulses();
			int w = 0;
			while (!t->chr_idle && w < 200000) { tick(); w++; }
			tick(); tick();
			if (!t->chr_idle) { printf("chrfp never idle\n"); fails++; }
		}
		if (y == 250 && !starve) {
			int bad = 0, first = -1;
			for (uint32_t i = 0; i < IMG; i++)
				if (dimg[i] != mimg[i]) { if (first < 0) first = i; bad++; }
			if (bad) {
				printf("frame %d: %d bytes differ, first at +%06x (rtl %02x model %02x)\n",
				       frame_index, bad, first, dimg[first], mimg[first]);
				fails++;
			}
		}
	}
}

int main(int argc, char **argv) {
	unsigned seed = 1; int frames = 8;
	for (int i = 1; i + 1 < argc; i += 2) {
		if (!strcmp(argv[i], "--seed")) seed = atoi(argv[i + 1]);
		else if (!strcmp(argv[i], "--frames")) frames = atoi(argv[i + 1]);
		else if (!strcmp(argv[i], "--ready")) ready_p = atof(argv[i + 1]);
	}
	crc_init();
	rng.seed(seed);
	t = new Vhd_capture_tb_top;
	for (int i = 0; i < 32; i++) pal[i] = rng() & 63;
	set_pal();
	clear_pulses();
	t->enable = 1; t->wq_ready = 1;
	t->reset = 1; tick(); tick(); t->reset = 0;
	// a CHR-RAM game: fill CHR, wait for the fingerprints
	for (int a = 0; a < 32768; a++) { chr[a] = rng(); t->chr_wr = 1; t->chr_addr = a; t->chr_data = chr[a]; tick(); }
	clear_pulses();
	while (!t->chr_idle) tick();
	tick(); tick();

	// frame numbering starts at 1: lines before the first pre-render go nowhere
	for (int f = 0; f < frames; f++) {
		run_frame(f < frames / 2, f);   // CHR-RAM for the first half, CHR-ROM (fp = 0) after
		if (t->overflow) { printf("overflow set in frame %d at ready %.2f\n", f, ready_p); fails++; break; }
	}
	uint32_t trl = 0;
	memcpy(&trl, &dimg[((m.frame - 1) & 1 ? 0x100000 : 0) + 0xF0000], 4);
	printf("frames %d, last trailer %u (model frame %u), %llu clocks\n", frames, trl, m.frame - 1,
	       (unsigned long long)clocks);
	if (trl != m.frame - 1) { printf("trailer mismatch\n"); fails++; }

	// negative control: a FIFO that never drains must be reported
	starve = true;
	run_frame(false, frames);
	printf("starvation: overflow = %d (must be 1)\n", t->overflow);
	if (!t->overflow) fails++;

	printf("%d failures\n", fails);
	delete t;
	return fails ? 1 : 0;
}
