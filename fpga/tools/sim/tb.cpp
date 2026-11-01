// Verilator testbench for the HD pack engine.
//   tb <pack.hdp> <stim.txt> <out.bin> [busy_percent]
// 1. streams the .hdp through the load port (honouring load_wait)
// 2. replays a tap stimulus (stim.txt: "BASE <80 hex>" then "<clk> <80 hex>" event lines)
// 3. writes 5 bytes per clock (R G B HB VB) to out.bin
// DDR3 model: Avalon-like, random BUSY, fixed read latency, in-order burst return.
#include "Vhd_tb_top.h"
#include "verilated.h"
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <deque>
#include <string>
#include <unordered_map>
#include <vector>

static Vhd_tb_top *top;
static std::unordered_map<uint32_t, uint64_t> mem;     // qword address -> data
struct Beat { uint64_t at; uint64_t data; };
static std::deque<Beat> rq;
static uint64_t now = 0;
static int busy_pct = 25;
static uint64_t n_rd = 0, n_wr = 0;
double sc_time_stamp() { return (double)now; }

static void tick() {
	// DDR model, evaluated on the falling edge so it sees settled outputs
	top->clk = 0;
	top->eval();
	bool busy = (rand() % 100) < busy_pct;
	if (!busy && (top->DDRAM_RD || top->DDRAM_WE)) {
		uint32_t a = top->DDRAM_ADDR;
		if (top->DDRAM_WE) {
			uint64_t old = mem.count(a) ? mem[a] : 0, d = top->DDRAM_DIN, m = 0;
			for (int i = 0; i < 8; i++) if (top->DDRAM_BE & (1 << i)) m |= 0xFFull << (8 * i);
			mem[a] = (old & ~m) | (d & m);
			n_wr++;
		} else {
			uint64_t t = std::max<uint64_t>(now + 18, rq.empty() ? 0 : rq.back().at + 1);
			for (unsigned i = 0; i < top->DDRAM_BURSTCNT; i++) {
				uint32_t qa = a + i;
				rq.push_back({t + i, mem.count(qa) ? mem[qa] : 0});
			}
			n_rd++;
		}
	}
	top->DDRAM_BUSY = busy;
	if (!rq.empty() && rq.front().at <= now) {
		top->DDRAM_DOUT = rq.front().data;
		top->DDRAM_DOUT_READY = 1;
		rq.pop_front();
	} else {
		top->DDRAM_DOUT_READY = 0;
	}
	top->eval();
	top->clk = 1;
	top->eval();
	now++;
}

static void set_tap(const uint32_t *w) { for (int i = 0; i < 10; i++) top->tap[i] = w[i]; }

static void parse_hex(const char *s, uint32_t *w) {
	// 80 hex digits, most significant first
	for (int i = 0; i < 10; i++) {
		char buf[9];
		memcpy(buf, s + (9 - i) * 8, 8);
		buf[8] = 0;
		w[i] = (uint32_t)strtoul(buf, nullptr, 16);
	}
}

int main(int argc, char **argv) {
	if (argc < 4) { fprintf(stderr, "usage: tb pack.hdp stim.txt out.bin [busy%%]\n"); return 2; }
	if (argc > 4) busy_pct = atoi(argv[4]);
	srand(1);
	Verilated::commandArgs(argc, argv);
	top = new Vhd_tb_top;

	FILE *f = fopen(argv[1], "rb");
	if (!f) { perror(argv[1]); return 2; }
	std::vector<uint8_t> pack;
	int c;
	while ((c = fgetc(f)) != EOF) pack.push_back((uint8_t)c);
	fclose(f);

	for (int i = 0; i < 20; i++) tick();
	top->load_active = 1;
	for (int i = 0; i < 4; i++) tick();
	for (size_t i = 0; i < pack.size(); i++) {
		top->load_wr = 1;
		top->load_addr = (uint32_t)i;
		top->load_data = pack[i];
		tick();
		top->load_wr = 0;
		tick();
		int guard = 0;
		while (top->load_wait) { tick(); if (++guard > 10000) { fprintf(stderr, "load_wait stuck at %zu\n", i); return 1; } }
	}
	top->load_active = 0;
	for (int i = 0; i < 50; i++) tick();
	fprintf(stderr, "pack loaded: %zu bytes, %llu DDR writes, active=%d\n",
	        pack.size(), (unsigned long long)n_wr, top->active);
	if (!top->active) { fprintf(stderr, "FAIL: pack not accepted\n"); return 1; }

	FILE *s = fopen(argv[2], "r");
	if (!s) { perror(argv[2]); return 2; }
	FILE *o = fopen(argv[3], "wb");
	char line[256];
	uint32_t base[10] = {0}, ev[10];
	uint64_t next_clk = ~0ull, last = 0;
	bool have_ev = false;
	std::string evhex;
	auto read_ev = [&]() -> bool {
		while (fgets(line, sizeof line, s)) {
			if (!strncmp(line, "BASE ", 5)) { parse_hex(line + 5, base); continue; }
			if (!strncmp(line, "END ", 4)) { last = strtoull(line + 4, nullptr, 10); continue; }
			char *sp = strchr(line, ' ');
			if (!sp) continue;
			next_clk = strtoull(line, nullptr, 10);
			parse_hex(sp + 1, ev);
			return true;
		}
		return false;
	};
	have_ev = read_ev();
	uint64_t t0 = now;
	for (uint64_t k = 0; ; k++) {
		if (have_ev && k == next_clk) { set_tap(ev); have_ev = read_ev(); }
		else set_tap(base);
		tick();
		uint8_t rec[5] = { top->R, top->G, top->B, top->HB, top->VB };
		fwrite(rec, 1, 5, o);
		if (!have_ev && last && k >= last) break;
		if (k > 50000000) break;
	}
	fclose(o);
	fclose(s);
	fprintf(stderr, "ran %llu clocks, %llu DDR bursts\n", (unsigned long long)(now - t0), (unsigned long long)n_rd);
	top->final();
	delete top;
	return 0;
}
