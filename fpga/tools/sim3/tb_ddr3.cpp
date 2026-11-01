// Verilator testbench for rtl/hdpack/hd3_ddr.sv (the stage-3 DDR3 arbiter, NR = 3 read clients).
//
// A DDR3 model takes commands on clocks where DDRAM_BUSY is low (random busy), returns read
// bursts in issue order after a latency with random gaps, and applies writes with byte
// enables. Every client runs at once with random traffic:
//   ch1  savestate reads and writes (ddram.sv handshake: ch1_req pulse, wait ch1_ready)
//   wr   pack-load writes (req held until ack)
//   cw   frame-record writes with byte enables (valid until ready)
//   rd0-2 8-qword burst reads (req held until ack, several outstanding)
// Checks: every read beat reaches the right client, in order, with the data at its address;
// every write lands with exactly its byte enables; the savestate data is right; no client
// waits longer than the round-robin bound; and a phase with all three readers saturating
// still lets the capture writer through (the starvation case a fixed priority would fail).
//   tb_ddr3.exe [--seed S] [--busy P] [--lat N] [--cycles N]     exit 0 = all checks pass
#include "Vhd3_ddr.h"
#include "verilated.h"
#include <cstdio>
#include <cstdint>
#include <cstring>
#include <deque>
#include <map>
#include <random>
#include <string>
#include <vector>

double sc_time_stamp() { return 0; }

static std::mt19937 rng(1);
static int pct() { return std::uniform_int_distribution<int>(0, 99)(rng); }
static uint64_t r64() { return ((uint64_t)rng() << 32) | rng(); }

static std::map<uint64_t, uint64_t> mem;            // qword address -> data
static uint64_t init_val(uint64_t a) { return a * 0x9E3779B97F4A7C15ull ^ 0x5555AAAA5555AAAAull; }
static uint64_t mrd(uint64_t a) { auto it = mem.find(a); return it == mem.end() ? init_val(a) : it->second; }

static int fails = 0, checks = 0;
static void expect(bool c, const char *what, long long a = 0, long long b = 0) {
	checks++;
	if (!c) { if (fails < 20) printf("FAIL: %s (%lld %lld)\n", what, a, b); fails++; }
}

int main(int argc, char **argv) {
	int busy = 20, lat = 12;
	long cycles = 400000;
	for (int i = 1; i + 1 < argc; i += 2) {
		std::string o = argv[i];
		if (o == "--seed") rng.seed(atoi(argv[i + 1]));
		else if (o == "--busy") busy = atoi(argv[i + 1]);
		else if (o == "--lat") lat = atoi(argv[i + 1]);
		else if (o == "--cycles") cycles = atol(argv[i + 1]);
	}
	Vhd3_ddr *t = new Vhd3_ddr;
	const int NR = 3;

	// DDR3 model state
	struct RB { uint64_t addr; int beats; int beat; long ready_at; };
	std::deque<RB> ddr_q;

	// client models
	// `others`: bursts granted to OTHER readers while this one waits; a round robin allows at
	// most NR - 1 (cw may pass more often while the return queue is full, which is fine)
	struct RdC { bool req = false; uint64_t addr = 0; std::deque<uint64_t> pend; int beat = 0;
	             long since = 0; long maxwait = 0; long bursts = 0; int others = 0, maxothers = 0; };
	RdC rc[NR];
	bool wr_req = false; uint64_t wr_addr = 0, wr_data = 0; long wr_n = 0;
	bool cw_valid = false; uint64_t cw_addr = 0, cw_data = 0; int cw_be = 0; long cw_n = 0;
	long cw_since = 0, cw_maxwait = 0; int cw_others = 0, cw_maxothers = 0;   // reader grants while cw waits (bound 1)
	bool ss_busy = false, ss_rnw = false; uint64_t ss_addr = 0, ss_data = 0; int ss_be = 0;
	long ss_n = 0;

	// expected memory after writes (model of what the arbiter must produce)
	std::map<uint64_t, uint64_t> expect_mem;
	auto apply = [&](std::map<uint64_t, uint64_t> &m, uint64_t a, uint64_t d, int be) {
		uint64_t cur = m.count(a) ? m[a] : init_val(a);
		for (int b = 0; b < 8; b++)
			if (be >> b & 1) cur = (cur & ~(0xFFull << (8 * b))) | (d & (0xFFull << (8 * b)));
		m[a] = cur;
	};

	// address ranges keep reads and writes apart, so a read's expected data is fixed
	auto rd_addr_gen = [&]() { return (uint64_t)(0x100000 + (rng() % 0x10000) * 8); };
	auto wr_addr_gen = [&]() { return (uint64_t)(0x400000 + (rng() % 0x8000)); };
	auto cw_addr_gen = [&]() { return (uint64_t)(0x800000 + (rng() % 0x8000)); };
	auto ss_addr_gen = [&]() { return (uint64_t)(0xC00000 + (rng() % 0x1000)); };

	t->DDRAM_CLK = 0; t->DDRAM_BUSY = 0; t->DDRAM_DOUT_READY = 0;
	t->ch1_req = 0; t->wr_req = 0; t->cw_valid = 0; t->rd_req = 0;
	t->eval();
	long saturate_from = cycles / 2, saturate_to = cycles / 2 + cycles / 8;
	long cw_in_sat = 0;
	for (long cyc = 0; cyc < cycles + 20000; cyc++) {
		bool tail = cyc >= cycles;                     // drain: no new requests
		bool sat = cyc >= saturate_from && cyc < saturate_to;

		// ---- drive inputs for this clock (registered model: decided before the edge) ----
		// DDR3 model outputs
		t->DDRAM_BUSY = (pct() < busy);
		t->DDRAM_DOUT_READY = 0;
		if (!ddr_q.empty() && ddr_q.front().ready_at <= cyc && pct() >= busy / 2) {
			RB &b = ddr_q.front();
			t->DDRAM_DOUT = mrd(b.addr + b.beat);
			t->DDRAM_DOUT_READY = 1;
			if (++b.beat == b.beats) ddr_q.pop_front();
		}
		// clients
		uint32_t rq = 0;
		for (int k = 0; k < NR; k++) {
			if (!rc[k].req && !tail && (sat ? true : pct() < 3) && rc[k].pend.size() < 4) {
				rc[k].req = true; rc[k].addr = rd_addr_gen(); rc[k].since = 0; rc[k].others = 0;
			}
			if (rc[k].req) rq |= 1u << k;
		}
		t->rd_req = rq;
		for (int k = 0; k < NR; k++) {
			uint32_t a = (uint32_t)rc[k].addr & 0x1FFFFFF;
			// rd_addr is NR*25 bits wide, packed
			for (int b = 0; b < 25; b++) {
				int bit = k * 25 + b;
				uint32_t &w = ((uint32_t *)t->rd_addr.data())[bit / 32];
				if (a >> b & 1) w |= 1u << (bit % 32); else w &= ~(1u << (bit % 32));
			}
		}
		if (!wr_req && !tail && pct() < 1) { wr_req = true; wr_addr = wr_addr_gen(); wr_data = r64(); }
		t->wr_req = wr_req; t->wr_addr = wr_addr; t->wr_data = wr_data;
		if (!cw_valid && !tail && (sat ? pct() < 20 : pct() < 8)) {
			cw_valid = true; cw_addr = cw_addr_gen(); cw_data = r64(); cw_be = rng() & 0xFF; cw_since = 0; cw_others = 0;
		}
		t->cw_valid = cw_valid; t->cw_addr = cw_addr; t->cw_data = cw_data; t->cw_be = cw_be;
		t->ch1_req = 0;
		if (!ss_busy && !tail && pct() < 1) {
			ss_busy = true; ss_rnw = pct() < 50; ss_addr = ss_addr_gen(); ss_data = r64(); ss_be = rng() & 0xFF;
			t->ch1_req = 1;
		}
		t->ch1_addr = (uint32_t)(ss_addr << 2);      // ch1_addr[27:1], qword at [27:3]
		t->ch1_rnw = ss_rnw; t->ch1_din = ss_data; t->ch1_be = ss_be;

		t->eval();
		// sample combinational outputs before the edge
		bool cw_taken = t->cw_ready;
		bool ddr_take = (t->DDRAM_RD || t->DDRAM_WE) && !t->DDRAM_BUSY;
		bool d_rd = t->DDRAM_RD, d_we = t->DDRAM_WE;
		uint64_t d_addr = t->DDRAM_ADDR & 0x1FFFFFFF;
		int d_burst = t->DDRAM_BURSTCNT; uint64_t d_din = t->DDRAM_DIN; int d_be = t->DDRAM_BE;

		// ---- clock edge ----
		t->DDRAM_CLK = 1; t->eval();

		if (ddr_take) {
			expect((d_addr >> 25) == 0x3, "address outside the 0x30000000 window", (long long)d_addr);
			uint64_t qa = d_addr & 0x1FFFFFF;
			if (d_rd) {
				expect(d_burst == 1 || d_burst == 8, "burst length", d_burst);
				ddr_q.push_back(RB{qa, d_burst, 0, cyc + lat});
			}
			if (d_we) {
				expect(d_burst == 1, "write burst length", d_burst);
				apply(mem, qa, d_din, d_be);
			}
		}
		if (cw_taken) {
			apply(expect_mem, cw_addr, cw_data, cw_be);
			cw_valid = false; cw_n++;
			if (cw_others > cw_maxothers) cw_maxothers = cw_others;
			if (sat) cw_in_sat++;
		}
		// registered outputs after the edge
		for (int k = 0; k < NR; k++) {
			if (t->rd_ack >> k & 1) {
				expect(rc[k].req, "ack without a request", k);
				rc[k].pend.push_back(rc[k].addr);
				rc[k].req = false; rc[k].bursts++;
				if (rc[k].others > rc[k].maxothers) rc[k].maxothers = rc[k].others;
				for (int j = 0; j < NR; j++) if (j != k && rc[j].req) rc[j].others++;
				if (cw_valid) cw_others++;
				if (rc[k].since > rc[k].maxwait) rc[k].maxwait = rc[k].since;
			}
			if (t->rd_valid >> k & 1) {
				expect(!rc[k].pend.empty(), "beat for a client with nothing outstanding", k);
				if (!rc[k].pend.empty()) {
					uint64_t a = rc[k].pend.front() + rc[k].beat;
					expect(t->rd_data == mrd(a), "read data", (long long)a, k);
					if (++rc[k].beat == 8) { rc[k].beat = 0; rc[k].pend.pop_front(); }
				}
			}
			if (rc[k].req) rc[k].since++;
		}
		expect(__builtin_popcount(t->rd_valid) <= 1, "two clients given one beat");
		if (t->wr_ack) {
			expect(wr_req, "wr_ack without a request");
			apply(expect_mem, wr_addr, wr_data, 0xFF); wr_req = false; wr_n++;
		}
		if (cw_valid) { cw_since++; if (cw_since > cw_maxwait) cw_maxwait = cw_since; }
		if (t->ch1_ready && ss_busy) {
			if (ss_rnw) expect(t->ch1_dout == mrd(ss_addr), "savestate read", (long long)ss_addr);
			else apply(expect_mem, ss_addr, ss_data, ss_be);
			ss_busy = false; ss_n++;
		}

		t->DDRAM_CLK = 0; t->eval();
	}
	// every write landed exactly
	for (auto &e : expect_mem) expect(mrd(e.first) == e.second, "write result", (long long)e.first);
	for (int k = 0; k < NR; k++) {
		expect(rc[k].pend.empty() && rc[k].beat == 0, "reads still outstanding at the end", k);
		printf("rd%d: %ld bursts, longest wait %ld clocks, at most %d other readers served first\n",
		       k, rc[k].bursts, rc[k].maxwait, rc[k].maxothers);
		expect(rc[k].maxothers <= NR - 1, "round robin bound broken", k, rc[k].maxothers);
	}
	printf("cw: %ld writes (%ld during the saturated phase), longest wait %ld clocks\n", cw_n, cw_in_sat, cw_maxwait);
	printf("wr: %ld writes, savestate: %ld\n", wr_n, ss_n);
	expect(!ss_busy, "a savestate access never completed");
	expect(!wr_req, "a pack-load write never completed");
	expect(!cw_valid, "a frame-record write never completed");
	expect(ss_n > 1000 && wr_n > 1000, "too few savestate / pack-load accesses", ss_n, wr_n);
	expect(cw_in_sat > 100, "capture writer starved while the readers saturate", cw_in_sat);
	for (int k = 0; k < NR; k++) expect(rc[k].bursts > 100, "a reader made no progress", k, rc[k].bursts);
	expect(cw_maxwait < 2000, "capture writer waited too long", cw_maxwait);
	printf("cw: at most %d reader bursts granted while it waited\n", cw_maxothers);
	expect(cw_maxothers <= 1, "capture writer passed over by more than one reader", cw_maxothers);
	printf("%d checks, %d failures\n", checks, fails);
	delete t;
	return fails ? 1 : 0;
}
