// Verilator testbench for rtl/hdpack/hd3_lookup.sv.
//
// Loads a format-3 .hdp into a model of the DDR3 window (the whole file at qword 0), builds a
// query list - every valid key in the key table, the default key of each tile, and mutated keys
// that must miss - runs each through the RTL and writes one TSV line per query. The answers are
// checked by tools/sim3/check_lookup.py against tools/hdp3_read.py, which is written separately.
//
//   tb_lookup.exe <file.hdp> <out.tsv> [--lat N] [--busy P] [--seed S] [--max N] [--key-only]
//
// DDR3 model: in-order 8-qword bursts; a request is accepted (rd_ack) on the clock it is seen,
// data starts N clocks later; with --busy P the acceptance and each data beat are delayed at
// random with probability P percent.
#include "Vhd3_tb_top.h"
#include "verilated.h"
#include <cstdio>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <vector>
#include <deque>
#include <random>
#include <string>

struct Query { uint32_t pal, kind, lo, hi; };

double sc_time_stamp() { return 0; }

static std::vector<uint8_t> mem;

static uint64_t q64(uint64_t byte_off) {
	uint64_t v = 0;
	if (byte_off + 8 <= mem.size()) memcpy(&v, &mem[byte_off], 8);
	return v;
}
static uint32_t u32(uint64_t off) { uint32_t v; memcpy(&v, &mem[off], 4); return v; }

int main(int argc, char **argv) {
	if (argc < 3) { fprintf(stderr, "usage: tb_lookup <file.hdp> <out.tsv> [--lat N] [--busy P] [--seed S] [--max N]\n"); return 2; }
	int lat = 12, busy = 0; unsigned seed = 1; size_t maxq = 0; int key_only = 0;
	for (int i = 3; i < argc; i += 2) {
		if (!strcmp(argv[i], "--key-only")) { key_only = 1; i--; continue; }
		if (i + 1 >= argc) { fprintf(stderr, "option %s needs a value\n", argv[i]); return 2; }
		if (!strcmp(argv[i], "--lat")) lat = atoi(argv[i + 1]);
		else if (!strcmp(argv[i], "--busy")) busy = atoi(argv[i + 1]);
		else if (!strcmp(argv[i], "--seed")) seed = (unsigned)atoi(argv[i + 1]);
		else if (!strcmp(argv[i], "--max")) maxq = (size_t)atoll(argv[i + 1]);
		else { fprintf(stderr, "unknown option %s\n", argv[i]); return 2; }
	}
	FILE *f = fopen(argv[1], "rb");
	if (!f) { perror(argv[1]); return 2; }
	fseek(f, 0, SEEK_END); long sz = ftell(f); fseek(f, 0, SEEK_SET);
	mem.resize((size_t)sz + 4096, 0);
	if (fread(mem.data(), 1, (size_t)sz, f) != (size_t)sz) { fprintf(stderr, "short read\n"); return 2; }
	fclose(f);
	if (memcmp(mem.data(), "NHDP", 4) || mem[4] != 3) { fprintf(stderr, "not a format-3 .hdp\n"); return 2; }

	uint32_t nbuckets = u32(0x24), max_probe = u32(0x28);
	uint32_t sec_keys = u32(0x80), sec_rules = u32(0x88);
	if (sec_keys % 8 || sec_rules % 8) { fprintf(stderr, "section not qword aligned\n"); return 2; }

	// query list
	std::vector<Query> qs;
	std::mt19937 rng(seed);
	for (uint32_t b = 0; b < nbuckets; b++)
		for (int j = 0; j < 4; j++) {
			uint64_t e = sec_keys + (uint64_t)b * 64 + j * 16;
			uint64_t a = q64(e), c = q64(e + 8);
			if (!(c >> 63)) continue;
			Query q{(uint32_t)a, (uint32_t)((c >> 62) & 1), (uint32_t)(a >> 32), (uint32_t)c};
			qs.push_back(q);
			Query d = q; d.pal = 0xFFFFFFFF; qs.push_back(d);          // default key of the tile
			if (rng() % 4 == 0) { Query m = q; m.pal ^= 1u << (rng() % 32); qs.push_back(m); }
			if (rng() % 8 == 0) { Query m = q; m.kind ^= 1; qs.push_back(m); }
			if (rng() % 8 == 0) { Query m = q; m.lo ^= 1u << (rng() % 32); qs.push_back(m); }
			if (q.kind && rng() % 4 == 0) { Query m = q; m.hi ^= 1u << (rng() % 32); qs.push_back(m); }
		}
	for (int i = 0; i < 64; i++) qs.push_back(Query{(uint32_t)rng(), rng() & 1u, (uint32_t)rng(), (uint32_t)rng()});
	if (maxq && qs.size() > maxq) {
		std::shuffle(qs.begin(), qs.end(), rng);
		qs.resize(maxq);
	}

	FILE *out = fopen(argv[2], "w");
	if (!out) { perror(argv[2]); return 2; }
	fprintf(out, "pal\tkind\tlo\thi\tfound\tlist_off\tcount\tpick_valid\tpayload\tindex\tprobes\tcycles\n");

	Vhd3_tb_top *t = new Vhd3_tb_top;
	t->keys_base   = sec_keys / 8;
	t->rules_base  = sec_rules / 8;
	t->bucket_mask = nbuckets - 1;
	t->max_probe   = max_probe;
	t->key_only = key_only;
	t->reset = 1; t->req = 0; t->rd_ack = 0; t->rd_valid = 0;
	for (int i = 0; i < 4; i++) { t->clk = 0; t->eval(); t->clk = 1; t->eval(); }
	t->reset = 0;

	struct Burst { uint64_t qaddr; int wait; int beat; };
	std::deque<Burst> pend;
	std::uniform_int_distribution<int> pct(0, 99);
	uint64_t total_cycles = 0, max_cycles = 0;
	size_t nq = 0;

	for (const Query &q : qs) {
		t->q_pal = q.pal; t->q_kind = q.kind; t->q_lo = q.lo; t->q_hi = q.hi;
		t->req = 1;
		uint64_t cyc = 0;
		bool fin = false;
		while (!fin) {
			// drive this cycle's inputs from the model state
			t->rd_ack = 0; t->rd_valid = 0;
			if (t->rd_req && !(busy && pct(rng) < busy)) {
				t->rd_ack = 1;
				pend.push_back(Burst{(uint64_t)t->rd_addr, lat, 0});
			}
			if (!pend.empty()) {
				Burst &b = pend.front();
				if (b.wait > 0) b.wait--;
				else if (!(busy && pct(rng) < busy)) {
					t->rd_valid = 1;
					t->rd_data = q64((b.qaddr + b.beat) * 8);
					if (++b.beat == 8) pend.pop_front();
				}
			}
			t->clk = 0; t->eval(); t->clk = 1; t->eval();
			t->req = 0;
			cyc++;
			if (t->done) fin = true;
			if (cyc > 2000000) { fprintf(stderr, "timeout on query %zu\n", nq); return 1; }
		}
		if (!pend.empty()) { fprintf(stderr, "burst still pending at done (query %zu)\n", nq); return 1; }
		total_cycles += cyc;
		if (cyc > max_cycles) max_cycles = cyc;
		fprintf(out, "%08x\t%u\t%08x\t%08x\t%u\t%u\t%u\t%u\t%08x\t%u\t%u\t%llu\n",
		        q.pal, q.kind, q.lo, q.hi, t->found, t->list_off, t->list_count, t->pick_valid,
		        t->pick_payload, t->pick_index, t->probes, (unsigned long long)cyc);
		nq++;
	}
	fclose(out);
	printf("%zu queries, mean %.1f cycles, max %llu (lat %d, busy %d%%)\n", nq,
	       nq ? (double)total_cycles / nq : 0.0, (unsigned long long)max_cycles, lat, busy);
	delete t;
	return 0;
}
