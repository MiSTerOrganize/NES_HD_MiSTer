// Verilator testbench for rtl/hdpack/hd3_add.sv (8a additions), through hd3_add_tb.sv:
// hd3_dict builds each frame's records and addition lists from the recorded frame's write
// stream (replayed exactly as tb_dict.cpp does), then hd3_add builds the frame's lanes reading
// the frame record from DDR3 and the dictionary's ports. After each frame the lanes of lines
// 0..240 are read back through the rl_* ports, each lane's added id through the dictionary's
// key store, and written as TSV; tools/sim3/check_add.py compares every pixel's added-sprite
// list with the model (addhw.py, itself checked against hdref.process_additions).
//
// Two DDR3 read ports: hd3_dict's reads the .hdp at qword 0, hd3_add's reads the frame-record
// buffers at 0xC000000 + bank * 1 MB (the recorded frame of that bank). Both: in-order
// 8-qword bursts after a latency, with random refusals.
//
//   tb_add.exe <file.hdp> <out.tsv> --game-ram G --frame BANK:rec.bin [--frame ...]
//              [--gap P] [--busy P] [--lat N] [--seed S] [--overlap] [--line-clk N]
//              [--pipelined] [--abort FRAME:CLOCKS ...]
//
// --abort K:N raises `abort` N clocks into frame K's pass (the stage-3 controller out of
// time): that frame must come back overflowed, and the next frame of the same bank exact. A
// done with one of ADD's bursts still outstanding is an error (its beat would land in the next
// frame's plan).
//
// --overlap: the next frame's stream starts right after the previous trailer, so ADD runs
// while the next frame is captured into the other bank; a frame's stream never starts while
// its bank's previous frame is still being added or read back (the real pipeline's rule).
#include "Vhd3_add_tb.h"
#include "verilated.h"
#include <cstdio>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <vector>
#include <deque>
#include <random>
#include <string>

double sc_time_stamp() { return 0; }

static std::vector<uint8_t> mem;
static uint64_t q64m(uint64_t byte_off) {
	uint64_t v = 0;
	if (byte_off + 8 <= mem.size()) memcpy(&v, &mem[byte_off], 8);
	return v;
}
static uint32_t u32m(uint64_t off) { uint32_t v; memcpy(&v, &mem[off], 4); return v; }

struct Frame { int bank; std::string path; std::vector<uint8_t> rec; };
struct Tap { uint32_t a; uint64_t d; uint32_t g; };
static uint64_t stream_t0 = 0;
static uint32_t line_clk = 5456;
static const std::vector<uint8_t> *recbank[2] = {nullptr, nullptr};

static uint64_t rq(const std::vector<uint8_t> &r, size_t off) { uint64_t v; memcpy(&v, &r[off], 8); return v; }

static Vhd3_add_tb *t;
static std::mt19937 rng;
static int busy = 0, lat = 12;
// --pipelined: a burst's latency runs from its acceptance, so outstanding bursts overlap (as
// the DDR3 behind hd3_ddr does); without it a burst starts its latency only at the front of
// the queue (tb_dict's model, the pessimistic bound)
static int pipelined = 0;
struct Burst { uint64_t qaddr; int wait; int beat; uint64_t ready; };
static std::deque<Burst> pend_d, pend_a;
static uint64_t cyc = 0;
static std::deque<int> done_events;
static int add_done = 0;
static int bad_addr = 0;
static int late_beat = 0;            // ADD's done with a burst of its own still outstanding

// the frame-record buffer qword at byte address a
static uint64_t rec64(uint64_t a) {
	if (a < 0xC000000 || a >= 0xC200000) { bad_addr++; return 0; }
	int b = (int)((a - 0xC000000) >> 20);
	size_t off = (size_t)((a - 0xC000000) & 0xFFFFF);
	if (!recbank[b]) { bad_addr++; return 0; }
	return rq(*recbank[b], off);
}

static void port(uint8_t req, uint32_t addr, uint8_t &ack, uint8_t &valid, uint64_t &data,
                 std::deque<Burst> &pend, bool rec) {
	std::uniform_int_distribution<int> pct(0, 99);
	ack = 0; valid = 0;
	if (req && !(busy && pct(rng) < busy)) {
		ack = 1;
		pend.push_back(Burst{(uint64_t)addr, lat, 0, cyc + (uint64_t)lat});
	}
	if (!pend.empty()) {
		Burst &b = pend.front();
		if (pipelined ? cyc < b.ready : b.wait > 0) { if (!pipelined) b.wait--; }
		else if (!(busy && pct(rng) < busy)) {
			valid = 1;
			data = rec ? rec64((b.qaddr + b.beat) * 8) : q64m((b.qaddr + b.beat) * 8);
			if (++b.beat == 8) pend.pop_front();
		}
	}
}

static void tick() {
	uint8_t ack, valid; uint64_t data = 0;
	port(t->d_rd_req, t->d_rd_addr, ack, valid, data, pend_d, false);
	t->d_rd_ack = ack; t->d_rd_valid = valid; if (valid) t->d_rd_data = data;
	port(t->a_rd_req, t->a_rd_addr, ack, valid, data, pend_a, true);
	t->a_rd_ack = ack; t->a_rd_valid = valid; if (valid) t->a_rd_data = data;
	t->clk = 0; t->eval(); t->clk = 1; t->eval();
	cyc++;
	if (t->frame_done) done_events.push_back((int)t->done_bank);
	if (t->done) {
		add_done = 1;
		// a burst still to return would land in the next frame's plan
		if (!pend_a.empty() || t->a_rd_req) late_beat = 1;
	}
}

// the write stream of one frame, in hd_capture's order (as tb_dict.cpp)
static std::vector<Tap> frame_stream(const Frame &f) {
	const uint32_t base = 0xC000000 / 8 + (uint32_t)f.bank * 0x20000;
	std::vector<Tap> s;
	uint32_t g = 0;
	auto lq =[&](int y, int o) { return base + 0x8000u + (uint32_t)y * 256 + (uint32_t)o; };
	auto line = [&](int y) { return (size_t)0x40000 + (size_t)y * 2048; };
	auto nspan = [&](int y) { return (int)std::min<uint64_t>((rq(f.rec, line(y)) >> 32) & 0xFF, 34); };
	auto nfet = [&](int y) { return (int)((rq(f.rec, line(y)) >> 48) & 0xFF); };
	auto spans = [&](int y, int from, int to) {
		for (int k = from; k < to && k < nspan(y); k++) {
			s.push_back({lq(y, 8 + 2 * k), rq(f.rec, line(y) + 64 + 16 * k), g});
			s.push_back({lq(y, 9 + 2 * k), rq(f.rec, line(y) + 72 + 16 * k), g});
		}
	};
	auto sprites = [&](int y) {
		for (int i = 0; i < nfet(y) && i < 64; i++) {
			s.push_back({lq(y, 80 + 2 * i), rq(f.rec, line(y) + 640 + 16 * i), g});
			s.push_back({lq(y, 81 + 2 * i), rq(f.rec, line(y) + 648 + 16 * i), g});
		}
	};
	sprites(0);
	spans(0, 0, 2);
	for (int y = 0; y < 240; y++) {
		g = (uint32_t)y + 1;
		spans(y, 2, 34);
		for (int q = 0; q < 4; q++) s.push_back({lq(y, q), rq(f.rec, line(y) + 8 * q), g});
		if (y < 239) { sprites(y + 1); spans(y + 1, 0, 2); }
	}
	s.push_back({base + 0x1E000, rq(f.rec, 0xF0000), g});
	return s;
}

static void drive_stream(std::deque<Tap> &q, int gap) {
	std::uniform_int_distribution<int> pct(0, 99);
	t->tap_v = 0;
	if (!q.empty() && cyc >= stream_t0 + (uint64_t)q.front().g * line_clk &&
	    !(gap && pct(rng) < gap)) {
		t->tap_v = 1;
		t->tap_a = q.front().a;
		t->tap_d = q.front().d;
		q.pop_front();
	}
}

static const int RAW_BITS = 11;     // the testbench is built with the default RAW
static int nl_lanes() { return (int)(sizeof(t->rl_q) / 4); }   // one 32-bit word per lane

static void dump_lanes(FILE *out, int fidx, int bank, uint64_t add_cycles, int aborted) {
	const uint64_t c0 = cyc;
	t->tap_v = 0;
	t->t_bank = bank;
	int total = 0;
	for (int y = 0; y <= 240; y++) {
		t->rl_y = y;
		tick();
		int n = t->rl_n;
		uint32_t w[64];
		for (int k = 0; k < n && k < 64; k++) w[k] = t->rl_q[k];
		for (int k = 0; k < n && k < 64; k++) {
			uint32_t v = w[k];
			int x0 = v & 0xFF, len = (int)((v >> 8) & 7) + 1;
			int aid = (int)((v >> 11) & ((1u << RAW_BITS) - 1));
			int col = (int)((v >> (RAW_BITS + 11)) & 7), row = (int)((v >> (RAW_BITS + 14)) & 7);
			int hm = (v >> (RAW_BITS + 17)) & 1, vm = (v >> (RAW_BITS + 18)) & 1;
			int bgp = (v >> (RAW_BITS + 19)) & 1, s239 = (v >> (RAW_BITS + 20)) & 1;
			t->t_rid = aid;
			tick();
			uint32_t pal = t->t_key[2];
			uint64_t body = ((uint64_t)t->t_key[1] << 32) | t->t_key[0];
			fprintf(out, "%d\t%d\t%d\t%d\t%d\t%d\t%d\t%d\t%d\t%d\t%d\t%08x\t%016llx\n", fidx, y, k,
			        x0, len, col, row, hm, vm, bgp, s239, pal, (unsigned long long)body);
			total++;
		}
	}
	fprintf(out, "#frame %d bank %d lanes %d ovf %u dict_ovf %u aborted %d add_cycles %llu\n",
	        fidx, bank, total, (unsigned)t->ovf, (unsigned)((t->dict_fovf >> bank) & 1), aborted,
	        (unsigned long long)add_cycles);
	stream_t0 += cyc - c0;
}

int main(int argc, char **argv) {
	if (argc < 3) { fprintf(stderr, "see the header of tb_add.cpp for usage\n"); return 2; }
	int game_ram = -1, gap = 0, overlap = 0; unsigned seed = 1;
	std::vector<Frame> frames;
	std::vector<std::pair<int, uint64_t>> aborts;    // --abort K:N
	for (int i = 3; i < argc; i++) {
		std::string o = argv[i];
		if (o == "--overlap") { overlap = 1; continue; }
		if (o == "--pipelined") { pipelined = 1; continue; }
		if (i + 1 >= argc) { fprintf(stderr, "option %s needs a value\n", o.c_str()); return 2; }
		std::string v = argv[++i];
		if (o == "--game-ram") game_ram = atoi(v.c_str());
		else if (o == "--gap") gap = atoi(v.c_str());
		else if (o == "--busy") busy = atoi(v.c_str());
		else if (o == "--lat") lat = atoi(v.c_str());
		else if (o == "--seed") seed = (unsigned)atoi(v.c_str());
		else if (o == "--line-clk") line_clk = (uint32_t)atoi(v.c_str());
		else if (o == "--abort") {
			size_t c = v.find(':');
			if (c == std::string::npos) { fprintf(stderr, "--abort FRAME:CLOCKS\n"); return 2; }
			aborts.push_back({atoi(v.substr(0, c).c_str()), (uint64_t)atoll(v.substr(c + 1).c_str())});
		}
		else if (o == "--frame") {
			size_t c = v.find(':');
			if (c == std::string::npos) { fprintf(stderr, "--frame BANK:file\n"); return 2; }
			Frame f; f.bank = atoi(v.substr(0, c).c_str()) & 1; f.path = v.substr(c + 1);
			FILE *rf = fopen(f.path.c_str(), "rb");
			if (!rf) { perror(f.path.c_str()); return 2; }
			f.rec.resize(0x100000);
			if (fread(f.rec.data(), 1, 0x100000, rf) != 0x100000) { fprintf(stderr, "%s: short\n", f.path.c_str()); return 2; }
			fclose(rf);
			frames.push_back(f);
		} else { fprintf(stderr, "unknown option %s\n", o.c_str()); return 2; }
	}
	if (game_ram < 0 || frames.empty()) { fprintf(stderr, "need --game-ram and --frame\n"); return 2; }
	rng.seed(seed);

	FILE *f = fopen(argv[1], "rb");
	if (!f) { perror(argv[1]); return 2; }
	fseek(f, 0, SEEK_END); long sz = ftell(f); fseek(f, 0, SEEK_SET);
	mem.resize((size_t)sz + 4096, 0);
	if (fread(mem.data(), 1, (size_t)sz, f) != (size_t)sz) { fprintf(stderr, "short read\n"); return 2; }
	fclose(f);
	if (memcmp(mem.data(), "NHDP", 4) || mem[4] != 3) { fprintf(stderr, "not a format-3 .hdp\n"); return 2; }

	t = new Vhd3_add_tb;
	t->game_ram     = game_ram;
	t->legacy       = mem[7] & 1;
	t->keys_base    = u32m(0x80) / 8;
	t->rules_base   = u32m(0x88) / 8;
	t->bucket_mask  = u32m(0x24) - 1;
	t->max_probe    = u32m(0x28);
	t->fb_base      = u32m(0x80 + 8 * 10) / 8;
	t->fb_len       = u32m(0x44);
	t->add_en       = u32m(0x80 + 8 * 16 + 4) != 0;
	t->akeys_base   = u32m(0x80 + 8 * 16) / 8;
	t->abucket_mask = u32m(0x4C) - 1;
	t->amax_probe   = u32m(0x50);
	t->alists_base  = u32m(0x80 + 8 * 17) / 8;
	t->tap_v = 0; t->start = 0; t->bank = 0;
	t->reset = 1;
	for (int i = 0; i < 4; i++) tick();
	t->reset = 0;
	for (int i = 0; i < 8; i++) tick();
	if (!t->add_en) { fprintf(stderr, "the pack has no addition table (sections 16/17)\n"); return 2; }

	FILE *out = fopen(argv[2], "w");
	if (!out) { perror(argv[2]); return 2; }
	fprintf(out, "#nl %d game_ram %d\n", nl_lanes(), game_ram);
	fprintf(out, "frame\ty\tslot\tx0\tlen\tcol\trow\thm\tvm\tbgp\tfrom239\tpal\tbody\n");

	std::deque<int> waiting;            // frames streamed, frame_done not yet seen
	std::deque<int> adding;             // frames whose ADD runs or waits to run
	int busy_bank[2] = {0, 0};          // a frame of this bank is not yet read back
	size_t next = 0;
	std::deque<Tap> q;
	uint64_t deadline = 0, add_t0 = 0;
	int running = -1, aborted = 0;
	while (next < frames.size() || !waiting.empty() || !adding.empty() || !q.empty() || running >= 0) {
		if (q.empty() && next < frames.size() && !busy_bank[frames[next].bank] &&
		    (overlap || (waiting.empty() && adding.empty() && running < 0))) {
			auto s = frame_stream(frames[next]);
			q.assign(s.begin(), s.end());
			recbank[frames[next].bank] = &frames[next].rec;
			busy_bank[frames[next].bank] = 1;
			stream_t0 = cyc;
			waiting.push_back((int)next);
			next++;
			deadline = cyc + 241ull * line_clk + 8000000ull;
		}
		drive_stream(q, gap);
		t->start = 0;
		if (running < 0 && !adding.empty()) {
			running = adding.front();
			adding.pop_front();
			t->bank = frames[running].bank;
			t->start = 1;
			add_done = 0;
			add_t0 = cyc;
			// ADD's own budget. This DDR3 model starts a burst's latency only when it reaches
			// the front of the queue, so latency does not overlap: up to 30 bursts a line, 240
			// lines, each paying --lat in full (--lat 1500 is ~11M clocks a frame)
			const uint64_t abud = 2000000ull + 240ull * 30 * ((uint64_t)lat + 40);
			if (deadline < cyc + abud) deadline = cyc + abud;
			aborted = 0;
		}
		// --abort K:N: the controller runs out of time N clocks into frame K's pass
		t->t_abort = 0;
		if (running >= 0 && !add_done)
			for (auto &a : aborts)
				if (a.first == running && cyc - add_t0 >= a.second) { t->t_abort = 1; aborted = 1; }
		tick();
		while (!done_events.empty()) {
			int bank = done_events.front();
			done_events.pop_front();
			if (waiting.empty()) { fprintf(stderr, "frame_done with no frame waiting\n"); return 1; }
			int k = waiting.front();
			if (bank != frames[k].bank) {
				fprintf(stderr, "frame_done for bank %d, expected %d (frame %d)\n", bank, frames[k].bank, k);
				return 1;
			}
			waiting.pop_front();
			adding.push_back(k);
		}
		if (running >= 0 && add_done) {
			const uint64_t ac = cyc - add_t0;
			dump_lanes(out, running, frames[running].bank, ac, aborted);
			busy_bank[frames[running].bank] = 0;
			running = -1;
			add_done = 0;
		}
		if (bad_addr) { fprintf(stderr, "a read outside the frame-record buffers\n"); return 1; }
		if (late_beat) { fprintf(stderr, "done with a burst still outstanding\n"); return 1; }
		if (cyc > deadline && deadline) { fprintf(stderr, "timeout (cycle %llu)\n", (unsigned long long)cyc); return 1; }
	}
	fclose(out);
	printf("%zu frames, %llu cycles (gap %d%%, lat %d, busy %d%%, %s, NL %d)\n", frames.size(),
	       (unsigned long long)cyc, gap, lat, busy, overlap ? "overlap" : "serial", nl_lanes());
	delete t;
	return 0;
}
