// Verilator testbench for rtl/hdpack/hd3_loader.sv.
//
// Streams .hdp files through the loader the way hps_io does (one byte per strobe, the next
// byte only while load_wait is low), with random gaps and a DDR3 write port that is busy at
// random. Checks:
//   - an intact file is accepted, every byte lands at PACK_Q*8 + offset, the header outputs
//     equal the file's fields, and the watched-address list (section 9) is copied out on the
//     lw_* port entry for entry;
//   - each corrupted variant is refused with the expected reason code.
//
//   tb_loader.exe [--intact-only] <file.hdp> [<file.hdp> ...]   (exit 0 = all checks pass)
// --intact-only skips the corrupted variants (each re-streams the whole file), for big packs.
#include "Vhd3_loader_tb_top.h"
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

struct Result { bool ok; int reject; std::vector<uint8_t> mem; uint64_t lo, hi; };

// the watched-address list the loader copied out while streaming (lw_* port)
static uint32_t lw_list[256];
static int lw_writes;
static void lw_sample(Vhd3_loader_tb_top *t) {
	if (!t->lw_we) return;
	lw_writes++;
	lw_list[t->lw_idx] = t->lw_addr;
}

static uint32_t rd32(const std::vector<uint8_t> &d, size_t o) { uint32_t v = 0; memcpy(&v, &d[o], 4); return v; }
static void wr32(std::vector<uint8_t> &d, size_t o, uint32_t v) { memcpy(&d[o], &v, 4); }
// an overscan field (i32) as hdref uses it: clamped to 0..255
static uint32_t ovc(uint32_t v) { int32_t s = (int32_t)v; return s < 0 ? 0 : s > 255 ? 255 : (uint32_t)s; }

static std::mt19937 rng(11);

static const uint64_t OVF_Q = 0x0800000;   // hd3_loader's default overflow qword

// a DDR3 write -> the file byte offset it holds. The main window holds file bytes below
// max_bytes, the overflow window the rest; a write in the wrong window is a hard failure.
static uint64_t file_off(Vhd3_loader_tb_top *t) {
	uint64_t a = (uint64_t)t->wr_addr, mb = t->max_bytes;
	if (t->wr_hi) {
		if (a < OVF_Q) { fprintf(stderr, "overflow write below OVF_Q\n"); exit(1); }
		return (a - OVF_Q) * 8 + mb;
	}
	if (a < PACK_Q) { fprintf(stderr, "write below the pack base\n"); exit(1); }
	uint64_t b = (a - PACK_Q) * 8;
	if (b >= mb) { fprintf(stderr, "main-window write at file byte %llu, beyond max_bytes\n",
	                       (unsigned long long)b); exit(1); }
	return b;
}
static long n_hi_writes;

// stream `bytes`; if `violate` >= 0, send that byte index while load_wait is high (broken handshake)
static Result run(Vhd3_loader_tb_top *t, const std::vector<uint8_t> &bytes, long violate, std::vector<uint8_t> &mem) {
	auto tick = [&]() { t->clk = 0; t->eval(); t->clk = 1; t->eval(); lw_sample(t); };
	std::uniform_int_distribution<int> pct(0, 99);
	lw_writes = 0;
	n_hi_writes = 0;
	memset(lw_list, 0xEE, sizeof lw_list);
	t->load_active = 1; t->load_wr = 0; t->wr_ack = 0;
	tick();
	uint64_t lo = ~0ull, hi = 0;
	size_t i = 0;
	int guard = 0;
	while (i < bytes.size() || t->wr_req) {
		t->load_wr = 0; t->wr_ack = 0;
		// the violating byte is sent only WHILE load_wait is high, every other byte only while it is low
		bool viol = violate >= 0 && (long)i == violate;
		bool can = viol ? (bool)t->load_wait : !t->load_wait;
		bool sent_viol = false;
		if (i < bytes.size() && can && (viol || pct(rng) < 70)) {
			t->load_wr = 1; t->load_data = bytes[i]; i++;
			sent_viol = viol;
		}
		// a byte on the same clock as the ack is harmless (the write is taken on that edge), so
		// the violating byte is sent on a clock where the pending write is NOT acknowledged
		if (t->wr_req && !sent_viol && pct(rng) < 60) {
			t->wr_ack = 1;
			uint64_t b = file_off(t), a = b / 8;          // a: file qword
			if (t->wr_hi) n_hi_writes++;
			if (b + 8 > mem.size()) mem.resize(b + 8, 0);
			uint64_t v = t->wr_data;
			memcpy(&mem[b], &v, 8);
			if (a < lo) lo = a;
			if (a > hi) hi = a;
		}
		tick();
		if (++guard > 400000000) { fprintf(stderr, "stall\n"); exit(1); }
	}
	t->load_wr = 0; t->wr_ack = 0;
	t->load_active = 0;
	tick();
	// drain the final flush
	for (int k = 0; k < 8; k++) {
		t->wr_ack = 0;
		if (t->wr_req) {
			t->wr_ack = 1;
			uint64_t b = file_off(t), a = b / 8;
			if (t->wr_hi) n_hi_writes++;
			if (a < lo) lo = a;
			if (a > hi) hi = a;
			if (b + 8 > mem.size()) mem.resize(b + 8, 0);
			uint64_t v = t->wr_data;
			memcpy(&mem[b], &v, 8);
		}
		tick();
	}
	return Result{(bool)t->pack_ok, (int)t->reject, {}, lo, hi};
}

int main(int argc, char **argv) {
	if (argc < 2) { fprintf(stderr, "usage: tb_loader <file.hdp> ...\n"); return 2; }
	Vhd3_loader_tb_top *t = new Vhd3_loader_tb_top;
	t->reset = 1; t->load_active = 0; t->load_wr = 0; t->wr_ack = 0;
	for (int k = 0; k < 4; k++) { t->clk = 0; t->eval(); t->clk = 1; t->eval(); }
	t->reset = 0;
	int fails = 0, checks = 0, n_known = 0, n_unknown = 0, n_add = 0, n_noadd = 0;
	bool intact_only = false;
	int first = 1;
	if (!strcmp(argv[1], "--intact-only")) { intact_only = true; first = 2; }
	auto expect = [&](bool c, const std::string &what) { checks++; if (!c) { fails++; printf("FAIL: %s\n", what.c_str()); } };

	for (int f = first; f < argc; f++) {
		FILE *fp = fopen(argv[f], "rb");
		if (!fp) { perror(argv[f]); return 2; }
		std::vector<uint8_t> d;
		{ fseek(fp, 0, SEEK_END); long n = ftell(fp); fseek(fp, 0, SEEK_SET); d.resize(n); if (fread(d.data(), 1, n, fp) != (size_t)n) return 2; fclose(fp); }
		std::string nm = argv[f];

		// intact file
		std::vector<uint8_t> mem;
		Result r = run(t, d, -1, mem);
		expect(r.ok && r.reject == 0, nm + ": intact file accepted (reject " + std::to_string(r.reject) + ")");
		expect(mem.size() >= d.size() && memcmp(mem.data(), d.data(), d.size()) == 0, nm + ": DDR3 image equals the file");
		expect(r.lo == 0 && r.hi == (d.size() + 7) / 8 - 1, nm + ": writes cover exactly the file");
		// a file reaching past max_bytes must have used the overflow window, one that does not
		// must not have
		expect((n_hi_writes > 0) == (d.size() > t->max_bytes), nm + ": overflow window used iff the file crosses max_bytes");
		expect(t->scale == d[6] && t->flags == d[7], nm + ": scale/flags");
		expect(t->options == rd32(d, 0x0C), nm + ": options");
		expect(t->bucket_mask == rd32(d, 0x24) - 1 && t->max_probe == (rd32(d, 0x28) & 0xFFFF), nm + ": bucket mask / max probe");
		expect((uint64_t)t->keys_base == PACK_Q + rd32(d, 0x80) / 8 && (uint64_t)t->rules_base == PACK_Q + rd32(d, 0x88) / 8, nm + ": section bases");
		expect(t->hdr_word0x2c == rd32(d, 0x2C) && t->hdr_word0x30 == rd32(d, 0x30) && t->hdr_word0x34 == rd32(d, 0x34), nm + ": counts");
		expect((uint64_t)t->fb_base == PACK_Q + rd32(d, 0x80 + 10 * 8) / 8 && t->fb_len == rd32(d, 0x44), nm + ": fallback map base / length");
		expect(t->legacy == (d[7] & 1), nm + ": legacy flag");
		{
			// what hd3_resolve / hd3_render take (stage 3)
			auto q = [&](int k) { return PACK_Q + rd32(d, 0x80 + 8 * k) / 8; };
			auto b = [&](int k) { return PACK_Q * 8 + rd32(d, 0x80 + 8 * k); };
			bool ok = (uint64_t)t->conds_base == q(2) && (uint64_t)t->clist_base == q(3) &&
			          (uint64_t)t->blocks_base == q(4) && (uint64_t)t->bgl_base == q(5) &&
			          (uint64_t)t->bgrec_base == q(6) && (uint64_t)t->bgmap_base == b(7) &&
			          (uint64_t)t->ratio_base == b(8) && (uint64_t)t->pal_base == q(12) &&
			          (uint64_t)t->bgi_base == b(13);
			expect(ok, nm + ": render section bases (2-8, 12, 13)");
			// section 14, ROM patches (hd3_romfix): table entry 14's length, header 0xF4 (the ARM
			// reads the section itself, from 0xF0)
			expect(t->patch_len == rd32(d, 0x80 + 14 * 8 + 4), nm + ": ROM patch section length");
			uint32_t o = rd32(d, 0x0C);
			expect(t->has_pal == ((d[7] >> 1) & 1) && t->cache_en == !((o >> 3) & 1) &&
			       t->render_orig == !((o >> 4) & 1), nm + ": has_pal / cache_en / render_orig");
			expect(t->ov_top == ovc(rd32(d, 0x10)) && t->ov_right == ovc(rd32(d, 0x14)) &&
			       t->ov_bottom == ovc(rd32(d, 0x18)) && t->ov_left == ovc(rd32(d, 0x1C)), nm + ": overscan");
		}
		{
			// the addition tables (sections 16/17, header 0x4C/0x50)
			bool has = rd32(d, 0x80 + 16 * 8 + 4) != 0;
			bool ok = t->add_en == has;
			if (has)
				ok &= (uint64_t)t->akeys_base == PACK_Q + rd32(d, 0x80 + 16 * 8) / 8 &&
				      (uint64_t)t->alists_base == PACK_Q + rd32(d, 0x80 + 17 * 8) / 8 &&
				      t->abucket_mask == rd32(d, 0x4C) - 1 && t->amax_probe == (rd32(d, 0x50) & 0xFFFF);
			expect(ok, nm + std::string(": addition tables (") + (has ? "present" : "none") + ")");
			(has ? n_add : n_noadd)++;
		}
		{
			// the pack's own type when flag bit 5 says it is known, else the loaded cart's
			bool known = d[7] & 0x20, pack_ram = d[7] & 0x10, ok = true;
			for (int cart = 0; cart < 2; cart++) {
				t->cart_no_chr_rom = cart;
				t->eval();
				ok &= t->game_ram == (known ? pack_ram : (bool)cart);
			}
			t->cart_no_chr_rom = 0;
			t->eval();
			expect(ok, nm + std::string(": game_ram (") + (known ? "from the pack" : "from the cart") + ")");
			(known ? n_known : n_unknown)++;
		}
		{
			uint32_t wn = rd32(d, 0x34), s9 = rd32(d, 0x80 + 9 * 8);
			bool same = lw_writes == (int)wn;
			for (uint32_t k = 0; k < wn && same; k++) same = lw_list[k] == rd32(d, s9 + 4 * k);
			expect(same, nm + ": watched list copied out (" + std::to_string(lw_writes) + " of " + std::to_string(wn) + " entries)");
		}

		// corrupted variants: (name, expected reject, mutation)
		struct Neg { const char *name; int code; std::function<void(std::vector<uint8_t>&)> mut; long violate; };
		std::vector<Neg> negs = {
			{"bad magic", 1, [](std::vector<uint8_t> &x) { x[0] = 'X'; }, -1},
			{"format 2", 2, [](std::vector<uint8_t> &x) { x[4] = 2; }, -1},
			{"scale 0", 3, [](std::vector<uint8_t> &x) { x[6] = 0; }, -1},
			{"scale 11", 3, [](std::vector<uint8_t> &x) { x[6] = 11; }, -1},
			{"unknown flag bit 6", 4, [](std::vector<uint8_t> &x) { x[7] |= 0x40; }, -1},
			{"truncated by 64 bytes", 5, [](std::vector<uint8_t> &x) { x.resize(x.size() - 64); }, -1},
			{"truncated by 3 bytes", 5, [](std::vector<uint8_t> &x) { x.resize(x.size() - 3); }, -1},
			{"one extra byte", 5, [](std::vector<uint8_t> &x) { x.push_back(0); }, -1},
			// a file bigger than MAX_TOTAL (the window build's is small; the default 384 MB one is
			// too slow to stream and is skipped below)
			{"size field too big for the region", 6, [t](std::vector<uint8_t> &x) {
				uint32_t big = t->max_total + 8; x.resize(big, 0); wr32(x, 0x20, big); }, -1},
			// a section other than 15 ending past the main window: the engine's readers could not
			// reach its tail (only meaningful when the file itself crosses max_bytes)
			{"non-audio section past the main window", 8, [t](std::vector<uint8_t> &x) {
				uint32_t o = rd32(x, 0x80);
				wr32(x, 0x84, (uint32_t)((x.size() - o) & ~7ull)); }, -1},
			// +1 is a power of two when the count is 1 (the smallest packs), so use 3 there
			{"bucket count not a power of two", 7, [](std::vector<uint8_t> &x) {
				uint32_t n = rd32(x, 0x24); wr32(x, 0x24, n == 1 ? 3 : n + 1); }, -1},
			{"bucket count 0", 7, [](std::vector<uint8_t> &x) { wr32(x, 0x24, 0); }, -1},
			{"section past the end", 8, [](std::vector<uint8_t> &x) { wr32(x, 0x84, (uint32_t)x.size()); }, -1},
			{"section not qword aligned", 8, [](std::vector<uint8_t> &x) { wr32(x, 0x80, rd32(x, 0x80) + 4); wr32(x, 0x84, 0); }, -1},
			// the LAST table entry too: the loader checks each entry as it streams past
			{"last section (17) past the end", 8, [](std::vector<uint8_t> &x) {
				wr32(x, 0x80 + 17 * 8, 0); wr32(x, 0x80 + 17 * 8 + 4, (uint32_t)x.size() + 8); }, -1},
			// a file that ends inside the section table, its size field agreeing and every
			// entry it does carry valid: only "the whole table must arrive" refuses it
			{"section table cut short", 8, [](std::vector<uint8_t> &x) {
				x.resize(200); wr32(x, 0x20, 200);
				for (int k = 0; k < 9; k++) { wr32(x, 0x80 + 8 * k, 0); wr32(x, 0x84 + 8 * k, 0); } }, -1},
			{"byte sent during load_wait", 9, [](std::vector<uint8_t> &) {}, 4096 + 7 + 1},
			{"257 watched addresses", 10, [](std::vector<uint8_t> &x) { wr32(x, 0x34, 257); }, -1},
			{"watched list longer than section 9", 10, [](std::vector<uint8_t> &x) {
				wr32(x, 0x34, rd32(x, 0x80 + 9 * 8 + 4) / 4 + 1); }, -1},
			// the addition table (reject 11); each works on a pack with or without one
			{"additions without a table (stale conversion)", 11, [](std::vector<uint8_t> &x) {
				wr32(x, 0x40, 5); wr32(x, 0x100, 0); wr32(x, 0x104, 0); wr32(x, 0x108, 0); wr32(x, 0x10C, 0);
				wr32(x, 0x4C, 0); wr32(x, 0x50, 0); }, -1},
			{"addition bucket count not a power of two", 11, [](std::vector<uint8_t> &x) { wr32(x, 0x4C, 3); }, -1},
			{"addition table size not 64 x buckets", 11, [](std::vector<uint8_t> &x) {
				if (rd32(x, 0x104)) { wr32(x, 0x4C, rd32(x, 0x4C) * 2); }
				else { wr32(x, 0x100, 0); wr32(x, 0x104, 64); wr32(x, 0x108, 0); wr32(x, 0x10C, 8); wr32(x, 0x4C, 2); } }, -1},
			{"addition table without lists", 11, [](std::vector<uint8_t> &x) {
				if (rd32(x, 0x104)) { wr32(x, 0x108, 0); wr32(x, 0x10C, 0); }
				else { wr32(x, 0x100, 0); wr32(x, 0x104, 64); wr32(x, 0x4C, 1); } }, -1},
			{"no additions but a probe count", 11, [](std::vector<uint8_t> &x) {
				wr32(x, 0x40, 0); wr32(x, 0x100, 0); wr32(x, 0x104, 0); wr32(x, 0x108, 0); wr32(x, 0x10C, 0);
				wr32(x, 0x4C, 0); wr32(x, 0x50, 1); }, -1},
		};
		if (intact_only) negs.clear();
		for (auto &n : negs) {
			if (!strcmp(n.name, "size field too big for the region") &&
			    (f != first || t->max_total > 0x4000000)) continue;   // one case; not 384 MB of streaming
			if (!strcmp(n.name, "non-audio section past the main window") && d.size() <= t->max_bytes)
				continue;
			// (a file past max_bytes with no other change must still pass: the intact case)
			std::vector<uint8_t> x = d;
			n.mut(x);
			// the broken-handshake byte must exist: a file shorter than the usual index gets one
			// at a qword boundary inside it (index 8k, sent on the clock after qword k-1's write)
			long viol = n.violate;
			if (viol >= (long)x.size()) viol = 8 * (long)(x.size() / 16);
			std::vector<uint8_t> m2;
			Result rn = run(t, x, viol, m2);
			expect(!rn.ok && rn.reject == n.code, nm + ": " + n.name + " refused with code " + std::to_string(n.code) +
			       " (got ok=" + std::to_string(rn.ok) + " code " + std::to_string(rn.reject) + ")");
		}
		// accepted variants: the overscan window clamped as hdref clamps it (negative -> 0, over
		// 255 -> 255, one field per position so a swapped field shows), and option/flag bits
		// flipped (they only change the exports)
		if (!intact_only) {
			std::vector<uint8_t> x = d;
			int32_t ovs[4] = {-5, 300, 7, 0x1000000};
			for (int k = 0; k < 4; k++) wr32(x, 0x10 + 4 * k, (uint32_t)ovs[k]);
			wr32(x, 0x0C, rd32(x, 0x0C) ^ 0x18);
			x[7] ^= 0x02;
			std::vector<uint8_t> m4;
			Result r4 = run(t, x, -1, m4);
			uint32_t o = rd32(x, 0x0C);
			expect(r4.ok && t->ov_top == 0 && t->ov_right == 255 && t->ov_bottom == 7 && t->ov_left == 255,
			       nm + ": overscan clamped (got " + std::to_string(t->ov_top) + " " + std::to_string(t->ov_right) +
			       " " + std::to_string(t->ov_bottom) + " " + std::to_string(t->ov_left) + ")");
			expect(r4.ok && t->has_pal == ((x[7] >> 1) & 1) && t->cache_en == !((o >> 3) & 1) &&
			       t->render_orig == !((o >> 4) & 1), nm + ": flag / option bits flipped");
		}
		// and an intact load afterwards is accepted again (no state carried over)
		std::vector<uint8_t> m3;
		Result r3 = run(t, d, -1, m3);
		expect(r3.ok, nm + ": accepted again after the refused loads");
		printf("%s: %zu bytes, %d checks so far, %d failures\n", nm.c_str(), d.size(), checks, fails);
	}
	delete t;
	printf("game_ram decided by the pack for %d file(s), by the cart for %d\n", n_known, n_unknown);
	printf("addition tables present in %d file(s), absent in %d\n", n_add, n_noadd);
	printf("%d checks, %d failures\n", checks, fails);
	return fails ? 1 : 0;
}
