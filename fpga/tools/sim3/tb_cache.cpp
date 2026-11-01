// Verilator unit test for rtl/hdpack/hd3_rcache.sv and hd3_ccache.sv (via hd3_cache_tb.sv).
//
// Each cache is driven by its own random requester against its own DDR3 model. Memory contents
// are a hash of (generation, qword address); a flush bumps the generation, so a stale line read
// after a flush returns the wrong value and is caught. Every answer is checked, and the test
// also checks that a hit issues no DDR3 read and that every miss issues exactly one burst of the
// right line.
//
//   tb_cache.exe [--n N] [--seed S] [--gap G] [--lat L] [--busy P]
//
// --gap G: the requester may issue its next request G..3 clocks after seeing ack. G=1 is a
// registered requester (the renderer's shape: it sees ack on one edge and its req is captured
// on the next); G=0 also lets a request be captured on the very edge after ack (a requester
// that reacts combinationally). Default 0 - the caches must be safe for both.
// --busy P: probability (percent) of a gap before acceptance and before each data beat.
// --byp P: probability (percent) that an rcache request is an uncached (byp) read. Those go to
// a separate region (qword 0x40000+, same sets, different tags) whose contents change at every
// such request, like the renderer's frame records. Ordinary reads also visit that region (and may
// cache it). The rcache is checked against an exact model of its 4 direct-mapped lines: every
// answer must hit or miss exactly as the model says, a byp read always misses (one burst) and
// leaves the model unchanged, and a hit returns the value the line was filled with. Default 25.
#include "Vhd3_cache_tb.h"
#include "verilated.h"
#include <cstdio>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <random>

double sc_time_stamp() { return 0; }

static uint32_t gen = 1;
static uint64_t memv(uint64_t qa) {
	uint64_t x = qa * 0x9E3779B97F4A7C15ull ^ ((uint64_t)gen << 40) ^ 0x5bd1e995ull;
	x ^= x >> 31; x *= 0xD6E8FEB86659FD93ull; x ^= x >> 29;
	return x;
}

static const uint32_t VBASE = 0x40000;        // the volatile (byp) region, in qwords
static uint32_t vgen = 1;
static uint64_t memv2g(uint64_t qa, uint32_t vg) {
	uint64_t x = qa * 0xC2B2AE3D27D4EB4Full ^ ((uint64_t)vg << 33) ^ 0x27d4eb2full;
	x ^= x >> 29; x *= 0x9E3779B97F4A7C15ull; x ^= x >> 32;
	return x;
}
static uint64_t memat(uint64_t qa) { return qa >= VBASE ? memv2g(qa, vgen) : memv(qa); }

// exact model of the rcache (hd3_cache_tb's LB = 2: 4 direct-mapped lines of 8 qwords): which
// line each set holds, and the volatile generation it was filled at, so the expected hit/miss
// and the expected value of every answer are known
static const int RLB = 2;
struct MLine { bool v = false; uint32_t tag = 0, vg = 0; };
static MLine rmodel[1 << RLB];

static std::mt19937 rng;
static int rnd(int n) { return (int)(rng() % (unsigned)n); }

// DDR3 burst model for one port
struct Ddr {
	int st = 0;                 // 0 idle, 1 accepted (latency), 2 data
	int wait = 0, beat = 0;
	uint32_t addr = 0;
	int lat = 12, busy = 0;
	long bursts = 0;
	// outputs for the next edge
	int ack = 0, valid = 0; uint64_t data = 0;
	void step(int rd_req, uint32_t rd_addr) {
		ack = 0; valid = 0;
		if (st == 0) {
			if (rd_req && !(busy && rnd(100) < busy)) {
				ack = 1; addr = rd_addr; st = 1; wait = lat; bursts++;
			}
		} else if (st == 1) {
			if (--wait <= 0) { st = 2; beat = 0; }
		} else {
			if (!(busy && rnd(100) < busy)) {
				valid = 1; data = memat(addr + beat);
				if (++beat == 8) st = 0;
			}
		}
	}
};

int main(int argc, char **argv) {
	long n = 200000; unsigned seed = 1; int gapmin = 0, lat = 12, busy = 0, bypp = 25;
	for (int i = 1; i + 1 < argc; i += 2) {
		if (!strcmp(argv[i], "--n")) n = atol(argv[i + 1]);
		else if (!strcmp(argv[i], "--seed")) seed = (unsigned)atoi(argv[i + 1]);
		else if (!strcmp(argv[i], "--gap")) gapmin = atoi(argv[i + 1]);
		else if (!strcmp(argv[i], "--lat")) lat = atoi(argv[i + 1]);
		else if (!strcmp(argv[i], "--busy")) busy = atoi(argv[i + 1]);
		else if (!strcmp(argv[i], "--byp")) bypp = atoi(argv[i + 1]);
		else { fprintf(stderr, "unknown option %s\n", argv[i]); return 2; }
	}
	rng.seed(seed);
	Vhd3_cache_tb *t = new Vhd3_cache_tb;
	Ddr rd, cd; rd.lat = cd.lat = lat; rd.busy = cd.busy = busy;
	const uint32_t cbase = 0x12340;   // section 2 base (qwords)
	t->c_base = cbase;

	// small address spaces so lines are re-used and evicted often (LB=2: 4 lines)
	auto r_pick = [&]() -> uint32_t { return (uint32_t)rnd(16 * 8); };     // 16 lines of qwords
	auto c_pick = [&]() -> uint32_t { return (uint32_t)rnd(24); };         // 24 records

	auto tick = [&]() {
		t->clk = 0; t->eval();
		t->clk = 1; t->eval();
	};
	t->reset = 1; tick(); tick(); t->reset = 0;

	long r_done = 0, c_done = 0, errors = 0, flushes = 0;
	long r_hit = 0, c_hit = 0, r_byp_done = 0;
	int r_byp = 0;
	int r_pend = 0, c_pend = 0, r_gap = 0, c_gap = 0;
	uint32_t r_want = 0, c_want = 0;
	long r_bursts_at_req = 0, c_bursts_at_req = 0, r_cyc = 0, c_cyc = 0;
	// the line each cache believes it holds is not modelled; instead hit/miss is inferred from
	// whether a burst happened, and checked against the expected line address when it did
	uint32_t r_burst_addr = 0, c_burst_addr = 0;
	int r_burst_seen = 0, c_burst_seen = 0;

	for (long cyc = 0; r_done + c_done < n && cyc < n * 200; cyc++) {
		// inputs for this edge
		t->r_req = 0; t->r_byp = 0; t->c_req = 0; t->flush = 0;
		if (!r_pend && !c_pend && rnd(5000) == 0) {
			t->flush = 1; gen++; flushes++;
			for (auto &l : rmodel) l.v = false;
		}
		else {
			if (!r_pend && r_gap <= 0) {
				r_byp = rnd(100) < bypp;
				if (r_byp) { r_want = VBASE + r_pick(); vgen++; }   // the region changed
				else r_want = (rnd(5) == 0 ? VBASE : 0) + r_pick();  // ordinary reads may cache it
				t->r_req = 1; t->r_byp = r_byp; t->r_addr = r_want; r_pend = 1;
				r_bursts_at_req = rd.bursts; r_burst_seen = 0; r_cyc = cyc;
			}
			if (!c_pend && c_gap <= 0) {
				c_want = c_pick(); t->c_req = 1; t->c_ci = c_want; c_pend = 1;
				c_bursts_at_req = cd.bursts; c_burst_seen = 0; c_cyc = cyc;
			}
		}
		t->r_rd_ack = rd.ack; t->r_rd_valid = rd.valid; t->r_rd_data = rd.data;
		t->c_rd_ack = cd.ack; t->c_rd_valid = cd.valid; t->c_rd_data = cd.data;
		tick();
		r_gap--; c_gap--;
		// DDR models see the post-edge requests
		long rb = rd.bursts, cb = cd.bursts;
		rd.step(t->r_rd_req, t->r_rd_addr);
		cd.step(t->c_rd_req, t->c_rd_addr);
		if (rd.bursts != rb) { r_burst_addr = rd.addr; r_burst_seen++; }
		if (cd.bursts != cb) { c_burst_addr = cd.addr; c_burst_seen++; }

		if (t->r_ack) {
			if (!r_pend) { fprintf(stderr, "rcache: ack with no request (cycle %ld)\n", cyc); errors++; }
			MLine &ml = rmodel[(r_want >> 3) & ((1u << RLB) - 1)];
			uint32_t mtag = r_want >> (3 + RLB);
			bool want_hit = !r_byp && ml.v && ml.tag == mtag;
			if (want_hit != (r_burst_seen == 0)) {
				if (errors < 20) fprintf(stderr, "rcache: %s read of %u %s, the model says %s (cycle %ld)\n",
					r_byp ? "byp" : "ordinary", r_want, r_burst_seen ? "missed" : "hit",
					want_hit ? "hit" : "miss", cyc);
				errors++;
			}
			uint64_t exp = want_hit && r_want >= VBASE ? memv2g(r_want, ml.vg) : memat(r_want);
			if (!r_byp && !want_hit) { ml.v = true; ml.tag = mtag; ml.vg = vgen; }
			if (t->r_q != exp) {
				if (errors < 20) fprintf(stderr, "rcache: addr %u got %016llx want %016llx (cycle %ld, gen %u)\n",
					r_want, (unsigned long long)t->r_q, (unsigned long long)exp, cyc, gen);
				errors++;
			}
			if (r_burst_seen > 1 || (r_burst_seen && r_burst_addr != (r_want & ~7u))) {
				fprintf(stderr, "rcache: wrong refill for addr %u (%d bursts, line %u)\n", r_want, r_burst_seen, r_burst_addr);
				errors++;
			}
			if (r_byp) {
				r_byp_done++;
				if (r_burst_seen != 1) {
					fprintf(stderr, "rcache: byp read of %u answered with %d bursts (must be 1)\n", r_want, r_burst_seen);
					errors++;
				}
			} else if (!r_burst_seen) r_hit++;
			if (!r_burst_seen && cyc - r_cyc > 3) {
				fprintf(stderr, "rcache: hit took %ld clocks\n", cyc - r_cyc); errors++;
			}
			r_pend = 0; r_done++; r_gap = gapmin + rnd(4 - gapmin);
		}
		if (t->c_ack) {
			if (!c_pend) { fprintf(stderr, "ccache: ack with no request (cycle %ld)\n", cyc); errors++; }
			int bad = 0;
			for (int w = 0; w < 4; w++) {
				uint64_t got = (uint64_t)t->c_q[2 * w] | ((uint64_t)t->c_q[2 * w + 1] << 32);
				if (got != memv(cbase + 4 * c_want + w)) bad = 1;
			}
			if (bad) {
				if (errors < 20) fprintf(stderr, "ccache: record %u wrong (cycle %ld, gen %u)\n", c_want, cyc, gen);
				errors++;
			}
			if (c_burst_seen > 1 || (c_burst_seen && c_burst_addr != cbase + 4 * (c_want & ~1u))) {
				fprintf(stderr, "ccache: wrong refill for record %u (%d bursts, addr %u)\n", c_want, c_burst_seen, c_burst_addr);
				errors++;
			}
			if (!c_burst_seen) c_hit++;
			if (!c_burst_seen && cyc - c_cyc > 3) {
				fprintf(stderr, "ccache: hit took %ld clocks\n", cyc - c_cyc); errors++;
			}
			c_pend = 0; c_done++; c_gap = gapmin + rnd(4 - gapmin);
		}
	}
	(void)r_bursts_at_req; (void)c_bursts_at_req;
	if (r_done + c_done < n) { fprintf(stderr, "HANG: %ld of %ld requests answered\n", r_done + c_done, n); errors++; }
	if (bypp > 0 && r_byp_done == 0) { fprintf(stderr, "no byp read was made\n"); errors++; }
	printf("rcache %ld answers (%ld hits, %ld byp)  ccache %ld answers (%ld hits)  %ld flushes  %s (%ld errors)\n",
		r_done, r_hit, r_byp_done, c_done, c_hit, flushes, errors ? "FAIL" : "PASS", errors);
	delete t;
	return errors ? 1 : 0;
}
