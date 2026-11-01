// Verilator testbench for rtl/hdpack/hd3_resolve.sv (stage-3 RESOLVE), through
// tools/sim3/hd3_resolve_tb.sv: hd3_dict builds each frame's dictionary from the recorded
// write stream exactly as in tb_dict.cpp, and on its frame_done RESOLVE filters that bank.
// DDR3 holds the .hdp at qword 0 and each frame's record (rec_FFFF.bin) at
// 0xC000000 + bank * 1 MB, the stage-2 capture buffer; hd_watch's value port answers from
// the frame's watch_FFFF.bin (same folder). Both blocks have their own DDR3 port here.
//
// After RESOLVE's done every record of the bank is read back as TSV for check_resolve.py:
//   rec  <frame> <rid> <via> <offq> <kind> <lastp> <count> <start>
//   rule <frame> <rid> <payload> <fptr> <wptr> <prefix>        (count lines, kind 1 only)
//   #frame <frame> bank <b> nrec <n> cycles <resolve clocks> overflow <dict> <resolve>
//
//   tb_resolve.exe <file.hdp> <out.tsv> --game-ram G --frame BANK:rec.bin [--frame ...]
//                  [--gap P] [--busy P] [--lat N] [--seed S] [--overlap] [--line-clk N]
//
// --overlap starts the next frame's stream right after the previous trailer, so RESOLVE
// runs while the next frame is captured into the other bank.
#include "Vhd3_resolve_tb.h"
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

static std::vector<uint8_t> mem;               // .hdp, then the two record buffers
static const uint64_t REC_BASE = 0xC000000;
static std::vector<uint8_t> rec_mem(0x200000, 0);   // the two record buffers (banks 0, 1)
static uint64_t q64m(uint64_t byte_off) {
	uint64_t v = 0;
	if (byte_off >= REC_BASE && byte_off + 8 <= REC_BASE + 0x200000)
		memcpy(&v, &rec_mem[byte_off - REC_BASE], 8);
	else if (byte_off + 8 <= mem.size()) memcpy(&v, &mem[byte_off], 8);
	return v;
}
static uint32_t u32m(uint64_t off) { uint32_t v; memcpy(&v, &mem[off], 4); return v; }

struct Frame { int bank; std::string path; std::vector<uint8_t> rec, watch; };
struct Tap { uint32_t a; uint64_t d; uint32_t g; };
static uint64_t stream_t0 = 0;
static uint32_t line_clk = 5456;
static uint64_t rq(const std::vector<uint8_t> &r, size_t off) { uint64_t v; memcpy(&v, &r[off], 8); return v; }

static Vhd3_resolve_tb *t;
static std::mt19937 rng;
static int busy = 0, lat = 12;
struct Burst { uint64_t qaddr; int wait; int beat; };
struct Port { std::deque<Burst> pend; };
static Port pd, ps;
static uint64_t cyc = 0;
static std::deque<int> done_events;
static int resolve_done = 0;
static const std::vector<uint8_t> *cur_watch = nullptr;   // the bank RESOLVE is filtering
static uint8_t v_next = 0;

template <class REQ, class ADDR, class ACK, class DATA, class VALID>
static void serve(Port &p, REQ req, ADDR addr, ACK &ack, DATA &data, VALID &valid) {
	std::uniform_int_distribution<int> pct(0, 99);
	ack = 0; valid = 0;
	if (req && !(busy && pct(rng) < busy)) {
		ack = 1;
		p.pend.push_back(Burst{(uint64_t)addr, lat, 0});
	}
	if (!p.pend.empty()) {
		Burst &b = p.pend.front();
		if (b.wait > 0) b.wait--;
		else if (!(busy && pct(rng) < busy)) {
			valid = 1;
			data = q64m((b.qaddr + b.beat) * 8);
			if (++b.beat == 8) p.pend.pop_front();
		}
	}
}

static void tick() {
	serve(pd, t->d_rd_req, t->d_rd_addr, t->d_rd_ack, t->d_rd_data, t->d_rd_valid);
	serve(ps, t->s_rd_req, t->s_rd_addr, t->s_rd_ack, t->s_rd_data, t->s_rd_valid);
	// hd_watch value port, one clock latency: the edge registers the value at the index
	// presented during this clock
	v_next = 0;
	if (cur_watch) {
		const std::vector<uint8_t> &w = *cur_watch;
		uint32_t n; memcpy(&n, &w[4], 4);
		uint32_t i = t->v_idx;
		if (i < n) v_next = w[8 + 4 * n + i];
	}
	t->clk = 0; t->eval(); t->clk = 1; t->eval();
	t->v_q = v_next;
	cyc++;
	if (t->frame_done) done_events.push_back((int)t->done_bank);
	if (t->done) resolve_done = 1;
}

static std::vector<Tap> frame_stream(const Frame &f) {
	const uint32_t base = (uint32_t)(REC_BASE / 8) + (uint32_t)f.bank * 0x20000;
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

static void dump_bank(FILE *out, int fidx, const Frame &f, uint64_t cycles) {
	t->tap_v = 0;
	t->t_bank = f.bank; t->r_bank = f.bank;
	tick();
	unsigned nrec = t->t_nrec;
	for (unsigned rid = 0; rid < nrec && rid < 2048; rid++) {
		t->t_rid = rid; t->r_rid = rid;
		tick();
		uint64_t res = t->t_res;
		int via = (int)((res >> 61) & 3);
		uint64_t offq = (res >> 36) & 0x1FFFFFF;
		uint64_t rr = t->r_rec;                       // {kind 2, lastp, count 11, start 10, offq 25}
		uint32_t roffq = (uint32_t)(rr & 0x1FFFFFF);
		uint32_t start = (uint32_t)((rr >> 25) & 0x3FF);
		uint32_t count = (uint32_t)((rr >> 35) & 0x7FF);
		int lastp = (int)((rr >> 46) & 1), kind = (int)((rr >> 47) & 3);
		fprintf(out, "rec\t%d\t%u\t%d\t%llu\t%d\t%d\t%u\t%u\t%u\n", fidx, rid, via,
		        (unsigned long long)offq, kind, lastp, count, start, roffq);
		if (kind != 1) continue;
		for (uint32_t i = 0; i < count; i++) {
			t->r_ri = (start + i) & 0x3FF;
			tick();
			const uint32_t *w = t->r_rule.data();          // 73 bits
			uint32_t payload = w[0], fptr = w[1] & 0xFFFFF;
			uint32_t wptr = ((w[1] >> 20) | (w[2] << 12)) & 0xFFFFF;
			int prefix = (int)((w[2] >> 8) & 1);
			fprintf(out, "rule\t%d\t%u\t%u\t%u\t%u\t%d\n", fidx, rid, payload, fptr, wptr, prefix);
		}
	}
	// background selection (8i): {valid, record index} per level, then the memo seed. Read
	// through g_bank with r_bank on the OTHER bank, as when resolve is already working on the
	// next frame: a selection port that followed r_bank would answer for the wrong frame.
	t->r_bank = !f.bank;
	t->g_bank = f.bank;
	for (unsigned lvl = 0; lvl < 40; lvl++) {
		t->g_lvl = lvl;
		tick();
		uint32_t g = t->g_q;
		fprintf(out, "bg\t%d\t%u\t%d\n", fidx, lvl, (g >> 20) & 1 ? (int)(g & 0xFFFFF) : -1);
	}
	t->s_bank = f.bank;
	for (unsigned a = 0; a < 2048; a++) {
		t->s_a = a;
		tick();
		if (t->s_q & 2) fprintf(out, "seed\t%d\t%u\t%u\n", fidx, a, (unsigned)(t->s_q & 1));
	}
	fprintf(out, "bgflags\t%d\t%u\t%u\n", fidx, (unsigned)t->bg_lin, (unsigned)t->bg_warn);
	fprintf(out, "#frame %d bank %d nrec %u cycles %llu overflow %u %u\n", fidx, f.bank, nrec,
	        (unsigned long long)cycles, (unsigned)t->dict_overflow, (unsigned)t->overflow);
}

int main(int argc, char **argv) {
	if (argc < 3) { fprintf(stderr, "see the header of tb_resolve.cpp for usage\n"); return 2; }
	int game_ram = -1, gap = 0, overlap = 0; unsigned seed = 1;
	std::vector<Frame> frames;
	for (int i = 3; i < argc; i++) {
		std::string o = argv[i];
		if (o == "--overlap") { overlap = 1; continue; }
		if (i + 1 >= argc) { fprintf(stderr, "option %s needs a value\n", o.c_str()); return 2; }
		std::string v = argv[++i];
		if (o == "--game-ram") game_ram = atoi(v.c_str());
		else if (o == "--gap") gap = atoi(v.c_str());
		else if (o == "--busy") busy = atoi(v.c_str());
		else if (o == "--lat") lat = atoi(v.c_str());
		else if (o == "--seed") seed = (unsigned)atoi(v.c_str());
		else if (o == "--line-clk") line_clk = (uint32_t)atoi(v.c_str());
		else if (o == "--frame") {
			size_t c = v.find(':');
			if (c == std::string::npos) { fprintf(stderr, "--frame BANK:file\n"); return 2; }
			Frame f; f.bank = atoi(v.substr(0, c).c_str()) & 1; f.path = v.substr(c + 1);
			FILE *rf = fopen(f.path.c_str(), "rb");
			if (!rf) { perror(f.path.c_str()); return 2; }
			f.rec.resize(0x100000);
			if (fread(f.rec.data(), 1, 0x100000, rf) != 0x100000) { fprintf(stderr, "%s: short\n", f.path.c_str()); return 2; }
			fclose(rf);
			std::string wp = f.path;
			size_t k = wp.rfind("rec_");
			if (k == std::string::npos) { fprintf(stderr, "%s: not a rec_FFFF.bin\n", f.path.c_str()); return 2; }
			wp.replace(k, 4, "watch_");
			FILE *wf = fopen(wp.c_str(), "rb");
			if (!wf) { perror(wp.c_str()); return 2; }
			fseek(wf, 0, SEEK_END); long wsz = ftell(wf); fseek(wf, 0, SEEK_SET);
			f.watch.resize((size_t)wsz);
			if (fread(f.watch.data(), 1, (size_t)wsz, wf) != (size_t)wsz) { fprintf(stderr, "%s: short\n", wp.c_str()); return 2; }
			fclose(wf);
			if (wsz < 8 || memcmp(f.watch.data(), "NWAT", 4)) { fprintf(stderr, "%s: bad watch file\n", wp.c_str()); return 2; }
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
	if ((uint64_t)sz >= REC_BASE) { fprintf(stderr, "pack overlaps the record buffers\n"); return 2; }

	t = new Vhd3_resolve_tb;
	t->game_ram    = game_ram;
	t->legacy      = mem[7] & 1;
	t->keys_base   = u32m(0x80) / 8;
	t->rules_base  = u32m(0x88) / 8;
	t->conds_base  = u32m(0x90) / 8;
	t->clist_base  = u32m(0x98) / 8;
	t->bucket_mask = u32m(0x24) - 1;
	t->max_probe   = u32m(0x28);
	t->fb_base     = u32m(0x80 + 8 * 10) / 8;
	t->fb_len      = u32m(0x44);
	t->bgl_base    = u32m(0x80 + 8 * 5) / 8;       // section 5: background level table
	t->bgi_base    = u32m(0x80 + 8 * 13);          // section 13: value index (byte address)
	t->tap_v = 0; t->start = 0;
	t->reset = 1;
	for (int i = 0; i < 4; i++) tick();
	t->reset = 0;
	for (int i = 0; i < 8; i++) tick();

	FILE *out = fopen(argv[2], "w");
	if (!out) { perror(argv[2]); return 2; }

	std::deque<int> waiting;        // frames captured, not yet dumped
	std::deque<int> to_resolve;     // frames whose frame_done arrived, waiting for RESOLVE
	int resolving = -1;
	uint64_t res_t0 = 0, max_cyc = 0;
	size_t next = 0;
	std::deque<Tap> q;
	uint64_t deadline = 0;
	while (next < frames.size() || !waiting.empty() || !q.empty()) {
		if (q.empty() && next < frames.size() && waiting.size() < (overlap ? 2u : 1u)) {
			const Frame &fr = frames[next];
			// the stage-2 capture would have written this bank's record buffer by now
			memcpy(&rec_mem[(size_t)fr.bank * 0x100000], fr.rec.data(), 0x100000);
			auto s = frame_stream(fr);
			q.assign(s.begin(), s.end());
			stream_t0 = cyc;
			waiting.push_back((int)next);
			next++;
			deadline = cyc + 241ull * line_clk + 40000000;
		}
		if (resolving < 0 && !to_resolve.empty()) {
			resolving = to_resolve.front();
			to_resolve.pop_front();
			cur_watch = &frames[resolving].watch;
			t->bank = frames[resolving].bank;
			t->start = 1;
			res_t0 = cyc;
			resolve_done = 0;
		}
		drive_stream(q, gap);
		tick();
		t->start = 0;
		while (!done_events.empty()) {
			int bank = done_events.front();
			done_events.pop_front();
			int k = -1;
			for (int w : waiting) {
				bool queued = false;
				for (int x : to_resolve) queued |= x == w;
				if (w != resolving && !queued) { k = w; break; }
			}
			if (k < 0) { fprintf(stderr, "frame_done with no frame waiting\n"); return 1; }
			if (bank != frames[k].bank) {
				fprintf(stderr, "frame_done for bank %d, expected %d (frame %d)\n", bank, frames[k].bank, k);
				return 1;
			}
			to_resolve.push_back(k);
		}
		if (resolve_done && resolving >= 0) {
			uint64_t c = cyc - res_t0;
			if (c > max_cyc) max_cyc = c;
			dump_bank(out, resolving, frames[resolving], c);
			if (waiting.empty() || waiting.front() != resolving) { fprintf(stderr, "frames out of order\n"); return 1; }
			waiting.pop_front();
			cur_watch = nullptr;
			resolving = -1;
			resolve_done = 0;
		}
		if (cyc > deadline && deadline) { fprintf(stderr, "timeout (cycle %llu)\n", (unsigned long long)cyc); return 1; }
	}
	fclose(out);
	printf("%zu frames, %llu cycles, longest RESOLVE %llu clocks (gap %d%%, lat %d, busy %d%%, %s)\n",
	       frames.size(), (unsigned long long)cyc, (unsigned long long)max_cyc, gap, lat, busy,
	       overlap ? "overlap" : "serial");
	delete t;
	return 0;
}
