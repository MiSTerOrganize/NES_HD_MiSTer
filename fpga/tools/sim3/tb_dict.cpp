// Verilator testbench for rtl/hdpack/hd3_dict.sv (stage-3 record dictionary).
//
// Replays recorded frame records (rec_FFFF.bin, the stage-2 capture buffer) as hd_capture's
// write stream, in hd_capture's own order - per line: BG slots 2.., the line header q0-q3,
// the next line's sprite fetches, the next line's BG slots 0-1 (the pre-render line supplies
// line 0's) - then the frame trailer. Stray pixel-region writes are mixed in, and random
// gaps leave tap_v low. DDR3 holds the .hdp at qword 0 (in-order 8-qword bursts, as in
// tb_lookup). After each frame's frame_done the bank is read back through the r_* ports and
// written as TSV; tools/sim3/check_dict.py compares it with dict_golden.py. A pack with an
// addition table (sections 16/17) turns the additions on: each record's merged addition list
// is read back through the a_* ports (last column, see dump_adds) and checked against the
// table by check_dict.py --pack.
//
//   tb_dict.exe <file.hdp> <out.tsv> --game-ram G --frame BANK:rec.bin [--frame ...]
//               [--gap P] [--busy P] [--lat N] [--seed S] [--overlap] [--line-clk N]
//               [--drop-header Y] [--allow-abandon]
//
// --allow-abandon (lag tests, check_dict.py --lag): under a DDR3 latency far beyond the real
// one the resolver can fall a whole frame behind; the RTL then abandons the old frame (its
// bank is restarted by the next stream for it) and flags the newer one overflowed. Without
// this option an out-of-order frame_done is an error.
//
// --overlap feeds each frame's stream right after the previous trailer, without waiting
// for its frame_done, so a frame's resolution runs while the next one is captured; banks
// are read back as their frame_done arrives.
#include "Vhd3_dict.h"
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
// g = pacing group: 0 = pre-render line, y+1 = line y's write burst. A group may not
// start before stream_t0 + g * line_clk, which models the real rate - one PPU line is
// 341 dots x 16 clk_sys = 5456 clocks - so the 4-slot line store is used as designed.
struct Tap { uint32_t a; uint64_t d; uint32_t g; };
static uint64_t stream_t0 = 0;
static uint32_t line_clk = 5456;
// --drop-header Y: line Y's header (q0-q3) is never written, in every frame. The RTL must
// treat that line as empty, not read the previous occupant of its line slot. Y >= 1:
// line 0's header is what starts a frame.
static int drop_hdr = -1;
static int allow_abandon = 0;

static uint64_t rq(const std::vector<uint8_t> &r, size_t off) { uint64_t v; memcpy(&v, &r[off], 8); return v; }

static Vhd3_dict *t;
static std::mt19937 rng;
static int busy = 0, lat = 12;
struct Burst { uint64_t qaddr; int wait; int beat; };
static std::deque<Burst> pend;
static uint64_t cyc = 0;
static std::deque<int> done_events;     // done_bank of every frame_done pulse, in order

// one clock: DDR3 model drives this cycle's inputs, then the edge
static void tick() {
	std::uniform_int_distribution<int> pct(0, 99);
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
			t->rd_data = q64m((b.qaddr + b.beat) * 8);
			if (++b.beat == 8) pend.pop_front();
		}
	}
	t->clk = 0; t->eval(); t->clk = 1; t->eval();
	cyc++;
	if (t->frame_done) done_events.push_back((int)t->done_bank);
}

// the write stream of one frame, in hd_capture's order
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
	auto stray = [&]() {
		std::uniform_int_distribution<uint32_t> px(0, 0x7FFF);
		if (rng() % 3 == 0) s.push_back({base + px(rng), (uint64_t)rng() << 32 | rng(), g});
	};
	sprites(0);                         // pre-render line
	spans(0, 0, 2);
	for (int y = 0; y < 240; y++) {
		g = (uint32_t)y + 1;
		spans(y, 2, 34);
		stray();
		if (y != drop_hdr) for (int q = 0; q < 4; q++) s.push_back({lq(y, q), rq(f.rec, line(y) + 8 * q), g});
		if (y < 239) { sprites(y + 1); spans(y + 1, 0, 2); }
		stray();
	}
	s.push_back({base + 0x1E000, rq(f.rec, 0xF0000), g});   // trailer: frame number
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

// a record's addition list (8a), read back through the a_* ports: "has-additions bit" then
// "/" and every pool entry as file index:ox:oy:added id:added palette:added body, comma
// separated ("-" for an empty list). The added key is read back through the key store, so the
// checker sees what the id really holds.
static const int RAW_BITS = 11;     // the testbench is built with hd3_dict's default RAW
static void dump_adds(FILE *out, int bank, int rid, int hasadd) {
	t->a_bank = bank; t->a_rid = rid;
	tick();
	uint32_t am = t->a_m;
	int cnt = (int)(am >> 10), start = (int)(am & 0x3FF);
	fprintf(out, "%d/", hasadd);
	if (!cnt) { fputc('-', out); return; }
	for (int e = 0; e < cnt; e++) {
		t->a_pi = (start + e) & 0x3FF;
		tick();
		uint64_t pe = t->a_pe;
		int aid = (int)(pe & ((1u << RAW_BITS) - 1));
		int ox = (int)((pe >> RAW_BITS) & 0xFFFF), oy = (int)((pe >> (RAW_BITS + 16)) & 0xFFFF);
		int idx = (int)((pe >> (RAW_BITS + 32)) & 0xFFFF);
		t->r_rid = aid;
		tick();
		uint32_t pal = t->r_key[2];
		uint64_t body = ((uint64_t)t->r_key[1] << 32) | t->r_key[0];
		fprintf(out, "%s%d:%d:%d:%d:%08x:%016llx", e ? "," : "", idx, (int16_t)ox, (int16_t)oy,
		        aid, pal, (unsigned long long)body);
	}
}

static void dump_bank(FILE *out, int fidx, const Frame &f) {
	// the read-back is the testbench's, not the PPU's: the line clock stops while it runs (see
	// the end), or the paused stream would afterwards arrive as a burst no PPU can produce -
	// several lines at one tap a clock, overrunning the 4-slot line store
	const uint64_t c0 = cyc;
	t->tap_v = 0;
	for (int y = 0; y < 240; y++) {
		if (y == drop_hdr) {
			// a header-less line must get no records: every one of its 34 span and 16
			// fetch slots must read back invalid. (They are never written in any frame of
			// the run, and the model's memories start at 0; a line mis-processed with the
			// previous occupant's header writes valid ids here.)
			int nvalid = 0;
			for (int k = 0; k < 50; k++) {
				bool spr = k >= 34;
				t->r_bank = f.bank; t->r_y = y;
				t->r_slot = spr ? 0 : k; t->r_fetch = spr ? k - 34 : 0;
				tick();
				if ((((spr ? t->r_spr : t->r_span)) >> 11) & 1) nvalid++;
			}
			fprintf(out, "#dropped %d line %d valid %d\n", fidx, y, nvalid);
			continue;
		}
		size_t lo = 0x40000 + (size_t)y * 2048;
		uint64_t q0 = rq(f.rec, lo);
		int ns = (int)std::min<uint64_t>((q0 >> 32) & 0xFF, 34);
		int nf = (int)std::min<uint64_t>((q0 >> 48) & 0xFF, 16);
		for (int k = 0; k < ns + nf; k++) {
			bool spr = k >= ns;
			int slot = spr ? k - ns : k;
			t->r_bank = f.bank; t->r_y = y; t->r_slot = spr ? 0 : slot; t->r_fetch = spr ? slot : 0;
			tick();
			uint32_t idw = spr ? t->r_spr : t->r_span;
			int valid = (idw >> 11) & 1, id = idw & 0x7FF;
			if (!valid) {
				fprintf(out, "%d\t%c\t%d\t%d\t0\t-\t-\t-\t-\t-\t-\t-\t-\n", fidx, spr ? 'S' : 'B', y, slot);
				continue;
			}
			t->r_rid = id;
			tick();
			uint32_t pal = t->r_key[2];
			uint64_t body = ((uint64_t)t->r_key[1] << 32) | t->r_key[0];
			uint64_t res = t->r_res;
			int done = (int)(res >> 63), via = (int)((res >> 61) & 3);
			uint64_t off = ((res >> 36) & 0x1FFFFFF) * 8;
			uint32_t fb2 = (uint32_t)((res >> 17) & 0x1FFFF), fb = (uint32_t)(res & 0x1FFFF);
			if (!done) via = 9;          // never resolved: the checker reports it
			fprintf(out, "%d\t%c\t%d\t%d\t1\t%d\t%08x\t%016llx\t%d\t%llu\t%05x\t%05x\t", fidx,
			        spr ? 'S' : 'B', y, slot, id, pal, (unsigned long long)body, via,
			        (unsigned long long)off, fb, fb2);
			dump_adds(out, f.bank, id, (int)((res >> 34) & 1));
			fputc('\n', out);
		}
	}
	t->r_bank = f.bank;
	tick();
	// overflow = the bank's frame_ovf (what hd3_render acts on: this frame is drawn without
	// lookups); sticky = the latched any-frame flag
	fprintf(out, "#frame %d bank %d nrec %u overflow %u sticky %u\n", fidx, f.bank,
	        (unsigned)t->r_nrec, (unsigned)((t->frame_ovf >> f.bank) & 1),
	        (unsigned)t->overflow);
	stream_t0 += cyc - c0;
}

int main(int argc, char **argv) {
	if (argc < 3) { fprintf(stderr, "see the header of tb_dict.cpp for usage\n"); return 2; }
	int game_ram = -1, gap = 0, overlap = 0; unsigned seed = 1;
	std::vector<Frame> frames;
	for (int i = 3; i < argc; i++) {
		std::string o = argv[i];
		if (o == "--overlap") { overlap = 1; continue; }
		if (o == "--allow-abandon") { allow_abandon = 1; continue; }
		if (i + 1 >= argc) { fprintf(stderr, "option %s needs a value\n", o.c_str()); return 2; }
		std::string v = argv[++i];
		if (o == "--game-ram") game_ram = atoi(v.c_str());
		else if (o == "--gap") gap = atoi(v.c_str());
		else if (o == "--busy") busy = atoi(v.c_str());
		else if (o == "--lat") lat = atoi(v.c_str());
		else if (o == "--seed") seed = (unsigned)atoi(v.c_str());
		else if (o == "--line-clk") line_clk = (uint32_t)atoi(v.c_str());
		else if (o == "--drop-header") drop_hdr = atoi(v.c_str());
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
	if (drop_hdr == 0 || drop_hdr > 239) {
		fprintf(stderr, "--drop-header takes 1..239 (line 0 starts the frame)\n");
		return 2;
	}
	rng.seed(seed);

	FILE *f = fopen(argv[1], "rb");
	if (!f) { perror(argv[1]); return 2; }
	fseek(f, 0, SEEK_END); long sz = ftell(f); fseek(f, 0, SEEK_SET);
	mem.resize((size_t)sz + 4096, 0);
	if (fread(mem.data(), 1, (size_t)sz, f) != (size_t)sz) { fprintf(stderr, "short read\n"); return 2; }
	fclose(f);
	if (memcmp(mem.data(), "NHDP", 4) || mem[4] != 3) { fprintf(stderr, "not a format-3 .hdp\n"); return 2; }

	t = new Vhd3_dict;
	t->game_ram    = game_ram;
	t->legacy      = mem[7] & 1;
	t->keys_base   = u32m(0x80) / 8;
	t->rules_base  = u32m(0x88) / 8;
	t->bucket_mask = u32m(0x24) - 1;
	t->max_probe   = u32m(0x28);
	t->fb_base     = u32m(0x80 + 8 * 10) / 8;
	t->fb_len      = u32m(0x44);
	// additions (8a): section 16 = addition-key table, 17 = its lists; 0x4C/0x50 = bucket
	// count and max probe
	t->add_en       = u32m(0x80 + 8 * 16 + 4) != 0;
	t->akeys_base   = u32m(0x80 + 8 * 16) / 8;
	t->abucket_mask = u32m(0x4C) - 1;
	t->amax_probe   = u32m(0x50);
	t->alists_base  = u32m(0x80 + 8 * 17) / 8;
	t->tap_v = 0; t->rd_ack = 0; t->rd_valid = 0;
	t->reset = 1;
	for (int i = 0; i < 4; i++) tick();
	t->reset = 0;
	for (int i = 0; i < 8; i++) tick();

	FILE *out = fopen(argv[2], "w");
	if (!out) { perror(argv[2]); return 2; }
	fprintf(out, "frame\tkind\ty\tslot\tvalid\tid\tpal\tbody\tvia\toff\tfb\tfb2\tadds\n");

	// frame k's stream; with --overlap the next one starts right after the trailer
	std::deque<int> waiting;            // frames whose frame_done has not arrived yet
	size_t next = 0;
	std::deque<Tap> q;
	uint64_t deadline = 0;
	while (next < frames.size() || !waiting.empty() || !q.empty()) {
		if (q.empty() && next < frames.size() && (overlap || waiting.empty())) {
			auto s = frame_stream(frames[next]);
			q.assign(s.begin(), s.end());
			stream_t0 = cyc;
			waiting.push_back((int)next);
			next++;
			// lag tests run the DDR3 model far slower than the real one; give the resolver time,
			// but bounded: the real RTL needs ~5.8M cycles for all four frames at latency 4000,
			// and a resolver that walks past nrec (stale records until its pointer wraps) takes
			// ~190M - same output, since the frames it delays are flagged overflowed anyway, so
			// the budget is what catches it
			deadline = cyc + 241ull * line_clk + (allow_abandon ? 20000000ull : 6000000ull);
		}
		drive_stream(q, gap);
		tick();
		while (!done_events.empty()) {
			int bank = done_events.front();
			done_events.pop_front();
			if (waiting.empty()) { fprintf(stderr, "frame_done with no frame waiting\n"); return 1; }
			int k = waiting.front();
			// --allow-abandon: a frame whose bank was restarted (the stream after the next one
			// began) before the resolver finished it is abandoned - it never gets a frame_done,
			// and its bank now holds the newer frame, so it cannot be read back. Which frame a
			// done belongs to is told by the bank's frame number (its trailer); the waiting
			// frames before it are the abandoned ones (the checker then requires that the next
			// frame of the same bank reports overflow).
			if (allow_abandon) {
				t->r_bank = bank;
				t->eval();
				const uint32_t fn = t->r_frame;
				auto num = [&](int j) { return (uint32_t)rq(frames[j].rec, 0xF0000); };
				while ((bank != frames[k].bank || num(k) != fn) && waiting.size() > 1) {
					fprintf(out, "#abandoned %d bank %d\n", k, frames[k].bank);
					waiting.pop_front();
					k = waiting.front();
				}
			}
			if (bank != frames[k].bank) {
				fprintf(stderr, "frame_done for bank %d, expected %d (frame %d)\n", bank, frames[k].bank, k);
				return 1;
			}
			waiting.pop_front();
			// read the bank back now; a stream still in progress just pauses (tap_v low is
			// legal input), and the next frame writes the OTHER bank
			dump_bank(out, k, frames[k]);
		}
		if (cyc > deadline && deadline) { fprintf(stderr, "timeout waiting for frame_done (cycle %llu)\n", (unsigned long long)cyc); return 1; }
	}
	fclose(out);
	printf("%zu frames, %llu cycles (gap %d%%, lat %d, busy %d%%, %s)\n", frames.size(),
	       (unsigned long long)cyc, gap, lat, busy, overlap ? "overlap" : "serial");
	delete t;
	return 0;
}
