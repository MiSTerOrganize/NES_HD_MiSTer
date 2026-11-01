// Verilator testbench for rtl/hdpack/hd3_loader.sv (the command-driven loader of hd3_pengine).
//
// A DDR3 model answers the loader's one-qword reads after a random delay: the pack image at
// PACK_Q, the ARM's command qword at CMD_Q. The test plays the ARM: it writes a command, waits
// for the answer (st_t toggles) and checks it. Checks:
//   - the command found at power-up is NOT carried out (DDR3 keeps an old one across a reload);
//   - BEGIN clears pack_ok and is answered with its sequence;
//   - COMMIT of an intact file is accepted, every header export equals the file's field, and
//     the watched-address list is copied out on lw_* entry for entry;
//   - a command whose sequence was already carried out is ignored;
//   - each corrupted variant is refused with the expected reason code;
//   - an unknown op is answered with reject 12; a reset in the middle of a COMMIT cancels it
//     and the next command still works.
//
//   tb_loader_cmd.exe <file.hdp> [<file.hdp> ...]       (exit 0 = all checks pass)
#include "Vhd3_loader_cmd_tb_top.h"
#include "verilated.h"
#include <cstdio>
#include <cstdint>
#include <cstring>
#include <vector>
#include <random>
#include <string>
#include <functional>

double sc_time_stamp() { return 0; }

static const uint64_t PACK_Q = 0x12345;
static const uint64_t CMD_Q  = 0x188000C;

static std::vector<uint8_t> img;   // the pack as the ARM copied it into DDR3
static uint64_t cmd = 0;           // the command qword
static std::mt19937 rng(7);

static bool     pend = false;      // a read is outstanding
static uint64_t pend_a = 0;
static int      pend_d = 0;
static long     reads = 0;

static uint32_t lw_list[256];
static int lw_writes;

static uint32_t rd32(const std::vector<uint8_t> &d, size_t o) { uint32_t v = 0; memcpy(&v, &d[o], 4); return v; }
static void wr32(std::vector<uint8_t> &d, size_t o, uint32_t v) { memcpy(&d[o], &v, 4); }
static uint32_t ovc(uint32_t v) { int32_t s = (int32_t)v; return s < 0 ? 0 : s > 255 ? 255 : (uint32_t)s; }

static uint64_t mem_read(uint64_t a) {
	if (a == CMD_Q) return cmd;
	if (a < PACK_Q) return 0xDEADBEEFDEADBEEFull;
	uint64_t b = (a - PACK_Q) * 8, v = 0;
	for (int k = 0; k < 8; k++) if (b + k < img.size()) v |= (uint64_t)img[b + k] << (8 * k);
	return v;
}

static void tick(Vhd3_loader_cmd_tb_top *t) {
	t->m_ready = 0;
	if (pend) {
		if (pend_d == 0) { t->m_ready = 1; t->m_dout = mem_read(pend_a); pend = false; reads++; }
		else pend_d--;
	}
	t->clk = 0; t->eval(); t->clk = 1; t->eval();
	if (t->lw_we) { lw_writes++; lw_list[t->lw_idx] = t->lw_addr; }
	if (t->m_req) {
		if (pend) { fprintf(stderr, "second read while one is outstanding\n"); exit(1); }
		pend = true; pend_a = t->m_addr; pend_d = rng() % 7;
	}
}

static uint8_t seq = 0;
static uint64_t make_cmd(int op, uint8_t s, uint32_t size) {
	return (0xC5ull << 56) | ((uint64_t)op << 48) | ((uint64_t)s << 40) | size;
}

// send a command and wait for its answer; false = no answer within the guard
static bool send(Vhd3_loader_cmd_tb_top *t, int op, uint32_t size) {
	seq++;
	cmd = make_cmd(op, seq, size);
	int st = t->st_t;
	for (long g = 0; g < 2000000; g++) {
		tick(t);
		if (t->st_t != st) return true;
	}
	return false;
}

// run long enough for several polls and report whether st_t moved
static bool quiet(Vhd3_loader_cmd_tb_top *t, int clocks) {
	int st = t->st_t;
	for (int i = 0; i < clocks; i++) { tick(t); if (t->st_t != st) return false; }
	return true;
}

int main(int argc, char **argv) {
	if (argc < 2) { fprintf(stderr, "usage: tb_loader_cmd <file.hdp> ...\n"); return 2; }
	Vhd3_loader_cmd_tb_top *t = new Vhd3_loader_cmd_tb_top;
	int fails = 0, checks = 0;
	auto expect = [&](bool c, const std::string &what) { checks++; if (!c) { fails++; printf("FAIL: %s\n", what.c_str()); } };

	// power-up with an old COMMIT already in DDR3 (and a pack image that would pass): the loader
	// must only record its sequence
	{
		FILE *fp = fopen(argv[1], "rb");
		if (!fp) { perror(argv[1]); return 2; }
		fseek(fp, 0, SEEK_END); long n = ftell(fp); fseek(fp, 0, SEEK_SET);
		img.resize(n); if (fread(img.data(), 1, n, fp) != (size_t)n) return 2; fclose(fp);
	}
	seq = 0x40;
	cmd = make_cmd(2, seq, (uint32_t)img.size());
	t->reset = 1; t->m_ready = 0; t->cart_no_chr_rom = 0;
	for (int k = 0; k < 4; k++) tick(t);
	t->reset = 0;
	expect(quiet(t, 200) && !t->pack_ok, "stale command at power-up not carried out");

	for (int f = 1; f < argc; f++) {
		FILE *fp = fopen(argv[f], "rb");
		if (!fp) { perror(argv[f]); return 2; }
		std::vector<uint8_t> d;
		{ fseek(fp, 0, SEEK_END); long n = ftell(fp); fseek(fp, 0, SEEK_SET); d.resize(n); if (fread(d.data(), 1, n, fp) != (size_t)n) return 2; fclose(fp); }
		std::string nm = argv[f];

		// BEGIN
		expect(send(t, 1, 0), nm + ": BEGIN answered");
		expect(!t->pack_ok && t->reject == 0 && t->ack_seq == seq, nm + ": BEGIN clears pack_ok, ack_seq");

		// intact COMMIT
		img = d;
		lw_writes = 0; memset(lw_list, 0xEE, sizeof lw_list);
		expect(send(t, 2, (uint32_t)d.size()), nm + ": COMMIT answered");
		expect(t->pack_ok && t->reject == 0 && t->ack_seq == seq,
		       nm + ": intact file accepted (reject " + std::to_string(t->reject) + ")");
		expect(t->scale == d[6] && t->flags == d[7], nm + ": scale/flags");
		expect(t->options == rd32(d, 0x0C), nm + ": options");
		expect(t->bucket_mask == rd32(d, 0x24) - 1 && t->max_probe == (rd32(d, 0x28) & 0xFFFF), nm + ": bucket mask / max probe");
		expect((uint64_t)t->keys_base == PACK_Q + rd32(d, 0x80) / 8 && (uint64_t)t->rules_base == PACK_Q + rd32(d, 0x88) / 8, nm + ": section bases");
		expect(t->hdr_word0x2c == rd32(d, 0x2C) && t->hdr_word0x30 == rd32(d, 0x30) && t->hdr_word0x34 == rd32(d, 0x34), nm + ": counts");
		expect((uint64_t)t->fb_base == PACK_Q + rd32(d, 0x80 + 10 * 8) / 8 && t->fb_len == rd32(d, 0x44), nm + ": fallback map");
		expect(t->legacy == (d[7] & 1), nm + ": legacy flag");
		{
			auto q = [&](int k) { return PACK_Q + rd32(d, 0x80 + 8 * k) / 8; };
			auto b = [&](int k) { return PACK_Q * 8 + rd32(d, 0x80 + 8 * k); };
			bool ok = (uint64_t)t->conds_base == q(2) && (uint64_t)t->clist_base == q(3) &&
			          (uint64_t)t->blocks_base == q(4) && (uint64_t)t->bgl_base == q(5) &&
			          (uint64_t)t->bgrec_base == q(6) && (uint64_t)t->bgmap_base == b(7) &&
			          (uint64_t)t->ratio_base == b(8) && (uint64_t)t->pal_base == q(12) &&
			          (uint64_t)t->bgi_base == b(13);
			expect(ok, nm + ": render section bases (2-8, 12, 13)");
			expect(t->patch_len == rd32(d, 0x80 + 14 * 8 + 4), nm + ": ROM patch length");
			expect(t->aud_off == rd32(d, 0x80 + 15 * 8) && t->aud_len == rd32(d, 0x80 + 15 * 8 + 4), nm + ": audio section");
			uint32_t o = rd32(d, 0x0C);
			expect(t->has_pal == ((d[7] >> 1) & 1) && t->cache_en == !((o >> 3) & 1) &&
			       t->render_orig == !((o >> 4) & 1), nm + ": has_pal / cache_en / render_orig");
			expect(t->ov_top == ovc(rd32(d, 0x10)) && t->ov_right == ovc(rd32(d, 0x14)) &&
			       t->ov_bottom == ovc(rd32(d, 0x18)) && t->ov_left == ovc(rd32(d, 0x1C)), nm + ": overscan");
			bool has = rd32(d, 0x80 + 16 * 8 + 4) != 0;
			bool aok = t->add_en == has;
			if (has)
				aok &= (uint64_t)t->akeys_base == PACK_Q + rd32(d, 0x80 + 16 * 8) / 8 &&
				       (uint64_t)t->alists_base == PACK_Q + rd32(d, 0x80 + 17 * 8) / 8 &&
				       t->abucket_mask == rd32(d, 0x4C) - 1 && t->amax_probe == (rd32(d, 0x50) & 0xFFFF);
			expect(aok, nm + ": addition tables");
			bool known = d[7] & 0x20, pack_ram = d[7] & 0x10, gok = true;
			for (int cart = 0; cart < 2; cart++) {
				t->cart_no_chr_rom = cart; t->eval();
				gok &= t->game_ram == (known ? pack_ram : (bool)cart);
			}
			t->cart_no_chr_rom = 0; t->eval();
			expect(gok, nm + ": game_ram");
			uint32_t wn = rd32(d, 0x34), s9 = rd32(d, 0x80 + 9 * 8);
			bool same = lw_writes == (int)wn;
			for (uint32_t k = 0; k < wn && same; k++) same = lw_list[k] == rd32(d, s9 + 4 * k);
			expect(same, nm + ": watched list copied out (" + std::to_string(lw_writes) + " of " + std::to_string(wn) + ")");
		}

		// the same command again is not carried out
		expect(quiet(t, 400) && t->pack_ok, nm + ": repeated command ignored");
		// a reset drops a valid pack
		t->reset = 1; tick(t); t->reset = 0;
		expect(!t->pack_ok, nm + ": reset clears pack_ok");

		// corrupted variants (mutation of the DDR3 image and/or the command size)
		struct Neg { const char *name; int code; std::function<void(std::vector<uint8_t>&, uint32_t&)> mut; };
		uint32_t MAXB = t->max_bytes, MAXT = t->max_total;
		std::vector<Neg> negs = {
			{"bad magic", 1, [](auto &x, auto &) { x[0] = 'X'; }},
			{"format 2", 2, [](auto &x, auto &) { x[4] = 2; }},
			{"scale 0", 3, [](auto &x, auto &) { x[6] = 0; }},
			{"scale 11", 3, [](auto &x, auto &) { x[6] = 11; }},
			{"unknown flag bit 6", 4, [](auto &x, auto &) { x[7] |= 0x40; }},
			{"copied size short by 64", 5, [](auto &, auto &s) { s -= 64; }},
			{"copied size one byte long", 5, [](auto &, auto &s) { s += 1; }},
			{"size field too big for the region", 6, [MAXT](auto &x, auto &s) { s = MAXT + 8; wr32(x, 0x20, s); }},
			{"bucket count not a power of two", 7, [](auto &x, auto &) {
				uint32_t n = rd32(x, 0x24); wr32(x, 0x24, n == 1 ? 3 : n + 1); }},
			{"bucket count 0", 7, [](auto &x, auto &) { wr32(x, 0x24, 0); }},
			{"section past the end", 8, [](auto &x, auto &) { wr32(x, 0x84, rd32(x, 0x20)); }},
			{"section not qword aligned", 8, [](auto &x, auto &) { wr32(x, 0x80, rd32(x, 0x80) + 4); wr32(x, 0x84, 0); }},
			{"last section (17) past the end", 8, [](auto &x, auto &) {
				wr32(x, 0x80 + 17 * 8, 0); wr32(x, 0x80 + 17 * 8 + 4, rd32(x, 0x20) + 8); }},
			{"file shorter than the header", 8, [](auto &x, auto &s) {
				s = 200; wr32(x, 0x20, 200);
				for (int k = 0; k < 18; k++) { wr32(x, 0x80 + 8 * k, 0); wr32(x, 0x84 + 8 * k, 0); } }},
			{"non-audio section past the main window", 8, [MAXB](auto &x, auto &s) {
				s = MAXB + 0x1000; wr32(x, 0x20, s);
				uint32_t o = rd32(x, 0x80); wr32(x, 0x84, (s - o) & ~7u); }},
			{"257 watched addresses", 10, [](auto &x, auto &) { wr32(x, 0x34, 257); }},
			{"watched list longer than section 9", 10, [](auto &x, auto &) {
				wr32(x, 0x34, rd32(x, 0x80 + 9 * 8 + 4) / 4 + 1); }},
			{"additions without a table", 11, [](auto &x, auto &) {
				wr32(x, 0x40, 5); wr32(x, 0x100, 0); wr32(x, 0x104, 0); wr32(x, 0x108, 0); wr32(x, 0x10C, 0);
				wr32(x, 0x4C, 0); wr32(x, 0x50, 0); }},
			{"addition bucket count not a power of two", 11, [](auto &x, auto &) { wr32(x, 0x4C, 3); }},
			{"no additions but a probe count", 11, [](auto &x, auto &) {
				wr32(x, 0x40, 0); wr32(x, 0x100, 0); wr32(x, 0x104, 0); wr32(x, 0x108, 0); wr32(x, 0x10C, 0);
				wr32(x, 0x4C, 0); wr32(x, 0x50, 1); }},
		};
		for (auto &n : negs) {
			if (MAXB + 0x1000 > MAXT && !strcmp(n.name, "non-audio section past the main window")) continue;
			img = d;
			uint32_t s = (uint32_t)d.size();
			n.mut(img, s);
			bool ans = send(t, 2, s);
			expect(ans && !t->pack_ok && t->reject == n.code && t->ack_seq == seq,
			       nm + ": " + n.name + " refused with " + std::to_string(n.code) +
			       " (got ok=" + std::to_string(t->pack_ok) + " code " + std::to_string(t->reject) + ")");
		}
		// accepted variant: the audio section reaching past the main window
		{
			img = d;
			uint32_t s = MAXB + 0x1000;
			wr32(img, 0x20, s);
			wr32(img, 0x80 + 15 * 8, 0); wr32(img, 0x80 + 15 * 8 + 4, s);
			bool ans = send(t, 2, s);
			expect(ans && t->pack_ok, nm + ": audio section past the window accepted (reject " + std::to_string(t->reject) + ")");
		}
		// overscan clamp + option/flag bits
		{
			img = d;
			int32_t ovs[4] = {-5, 300, 7, 0x1000000};
			for (int k = 0; k < 4; k++) wr32(img, 0x10 + 4 * k, (uint32_t)ovs[k]);
			wr32(img, 0x0C, rd32(img, 0x0C) ^ 0x18);
			img[7] ^= 0x02;
			bool ans = send(t, 2, (uint32_t)d.size());
			uint32_t o = rd32(img, 0x0C);
			expect(ans && t->pack_ok && t->ov_top == 0 && t->ov_right == 255 && t->ov_bottom == 7 && t->ov_left == 255,
			       nm + ": overscan clamped");
			expect(t->has_pal == ((img[7] >> 1) & 1) && t->cache_en == !((o >> 3) & 1) &&
			       t->render_orig == !((o >> 4) & 1), nm + ": flag / option bits flipped");
		}
		// unknown op
		{
			img = d;
			bool ans = send(t, 7, 0);
			expect(ans && !t->pack_ok && t->reject == 12 && t->ack_seq == seq, nm + ": unknown op refused with 12");
		}
		// reset in the middle of a COMMIT
		{
			img = d;
			seq++;
			cmd = make_cmd(2, seq, (uint32_t)d.size());
			long r0 = reads;
			int st = t->st_t;
			for (long g = 0; g < 200000 && reads < r0 + 8; g++) tick(t);
			t->reset = 1; tick(t); t->reset = 0;
			expect(!t->pack_ok && t->st_t == st, nm + ": reset cancels the COMMIT");
			expect(quiet(t, 400), nm + ": cancelled COMMIT not resumed");
			bool ans = send(t, 2, (uint32_t)d.size());
			expect(ans && t->pack_ok, nm + ": next COMMIT after a reset accepted");
		}
		printf("%s: %zu bytes, %d checks so far, %d failures\n", nm.c_str(), d.size(), checks, fails);
	}
	delete t;
	printf("%d checks, %d failures\n", checks, fails);
	return fails ? 1 : 0;
}
