// Verilator testbench for rtl/hdpack/hd3_render.sv (stage-3 RENDER), through
// tools/sim3/hd3_render_tb.sv. Per frame, one after the other:
//   1. hd3_dict builds the frame's dictionary from the recorded write stream (as tb_resolve)
//   1b. hd3_add builds the frame's lanes (8a; only when the pack has additions)
//   2. hd3_resolve filters that bank
//   (hd3_fmap fills its maps during step 1, from the same write stream, pixel qwords included)
//   4. hd3_render draws the frame; every out_v pixel is collected into the 2x image
// DDR3 holds the .hdp at qword 0 and each frame's record (rec_FFFF.bin) at
// 0xC000000 + bank * 1 MB; both watch-value ports answer from the frame's watch_FFFF.bin.
//
// Output per frame: <prefix>_<frame>.rgb = "NRGB" u32 width u32 height, then width*height
// RGB bytes (the overscan window at 2x, exactly what hdref.HdRef.render returns), compared
// by check_render.py. A summary line per frame goes to stdout:
//   frame <i> bank <b> pixels <n> render <clocks> worst_line <clocks> unsup <u> overflow ...
//
//   tb_render.exe <file.hdp> <prefix> --game-ram G --frame BANK:rec.bin [--frame ...]
//                 [--busy P] [--lat N] [--seed S] [--line-clk N]
#include "Vhd3_render_tb.h"
#include "Vhd3_render_tb___024root.h"
#include "verilated.h"
#include <cstdio>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <vector>
#include <deque>
#include <random>
#include <string>
#include <algorithm>

double sc_time_stamp() { return 0; }

static std::vector<uint8_t> mem;
static const uint64_t REC_BASE = 0xC000000;
static std::vector<uint8_t> rec_mem(0x200000, 0);
static uint64_t q64m(uint64_t byte_off) {
	uint64_t v = 0;
	if (byte_off >= REC_BASE && byte_off + 8 <= REC_BASE + 0x200000)
		memcpy(&v, &rec_mem[byte_off - REC_BASE], 8);
	else if (byte_off + 8 <= mem.size()) memcpy(&v, &mem[byte_off], 8);
	return v;
}
static uint32_t u32m(uint64_t off) { uint32_t v; memcpy(&v, &mem[off], 4); return v; }
static int32_t i32m(uint64_t off) { int32_t v; memcpy(&v, &mem[off], 4); return v; }

struct Frame { int bank; std::string path, name; std::vector<uint8_t> rec, watch; };
struct Tap { uint32_t a; uint64_t d; uint32_t g; uint8_t be = 0xFF; };
static uint64_t stream_t0 = 0;
static uint32_t line_clk = 5456;
static uint64_t rq(const std::vector<uint8_t> &r, size_t off) { uint64_t v; memcpy(&v, &r[off], 8); return v; }

static Vhd3_render_tb *t;
static std::mt19937 rng;
static int busy = 0, lat = 12;
struct Burst { uint64_t qaddr; int wait; int beat; };
struct Port { std::deque<Burst> pend; };
static Port pd, ps, pl, pc, pe, pb, pa;
static uint64_t cyc = 0;
static std::deque<int> done_events;
static const std::vector<uint8_t> *cur_watch = nullptr;

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

static uint8_t watch_val(uint32_t i) {
	if (!cur_watch) return 0;
	const std::vector<uint8_t> &w = *cur_watch;
	uint32_t n; memcpy(&n, &w[4], 4);
	return i < n ? w[8 + 4 * n + i] : 0;
}

// out_v capture
static std::vector<uint8_t> img;
static int img_w = 0, img_h = 0, ov_t = 0, ov_l = 0;
static uint64_t npix = 0, bad_order = 0;
static int last_y = -1, last_x = -1;
static uint64_t line_t0 = 0, worst_line = 0;

static void tick() {
	serve(pd, t->d_rd_req, t->d_rd_addr, t->d_rd_ack, t->d_rd_data, t->d_rd_valid);
	serve(ps, t->s_rd_req, t->s_rd_addr, t->s_rd_ack, t->s_rd_data, t->s_rd_valid);
	serve(pl, t->l_rd_req, t->l_rd_addr, t->l_rd_ack, t->l_rd_data, t->l_rd_valid);
	serve(pc, t->c_rd_req, t->c_rd_addr, t->c_rd_ack, t->c_rd_data, t->c_rd_valid);
	serve(pe, t->e_rd_req, t->e_rd_addr, t->e_rd_ack, t->e_rd_data, t->e_rd_valid);
	serve(pb, t->b_rd_req, t->b_rd_addr, t->b_rd_ack, t->b_rd_data, t->b_rd_valid);
	serve(pa, t->a_rd_req, t->a_rd_addr, t->a_rd_ack, t->a_rd_data, t->a_rd_valid);
	// both watch-value ports: one clock latency
	uint8_t rv = watch_val(t->rs_v_idx), nv = watch_val(t->v_idx);
	t->clk = 0; t->eval(); t->clk = 1; t->eval();
	t->rs_v_q = rv; t->v_q = nv;
	cyc++;
	if (t->frame_done) done_events.push_back((int)t->done_bank);
	if (t->out_v) {
		int y = t->out_y, x = t->out_x;
		if (!(y > last_y || (y == last_y && x > last_x))) bad_order++;
		if (y != last_y) {
			if (last_y >= 0 && cyc - line_t0 > worst_line) worst_line = cyc - line_t0;
			line_t0 = cyc;
		}
		last_y = y; last_x = x;
		int oy = (y - ov_t) * 2, ox = (x - ov_l) * 2;
		const uint32_t *w = t->out_px.data();
		uint32_t sub[4];
		uint64_t lo = (uint64_t)w[0] | ((uint64_t)w[1] << 32);
		uint64_t hi = (uint64_t)w[2];
		sub[0] = (uint32_t)(lo & 0xFFFFFF);
		sub[1] = (uint32_t)((lo >> 24) & 0xFFFFFF);
		sub[2] = (uint32_t)(((lo >> 48) | (hi << 16)) & 0xFFFFFF);
		sub[3] = (uint32_t)((hi >> 8) & 0xFFFFFF);
		if (oy >= 0 && ox >= 0 && oy + 1 < img_h && ox + 1 < img_w) {
			for (int k = 0; k < 4; k++) {
				int py = oy + (k >> 1), px = ox + (k & 1);
				uint8_t *p = &img[((size_t)py * img_w + px) * 3];
				p[0] = (uint8_t)(sub[k] >> 16); p[1] = (uint8_t)(sub[k] >> 8); p[2] = (uint8_t)sub[k];
			}
		} else bad_order++;
		npix++;
	}
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
		// the line's pixel qwords (hd3_fmap takes them; hd3_dict ignores the pixel area)
		for (int q = 0; q < 128; q++)
			s.push_back({base + (uint32_t)y * 128 + (uint32_t)q, rq(f.rec, (size_t)y * 1024 + 8 * q), g});
		spans(y, 2, 34);
		for (int q = 0; q < 4; q++) s.push_back({lq(y, q), rq(f.rec, line(y) + 8 * q), g});
		if (y < 239) { sprites(y + 1); spans(y + 1, 0, 2); }
	}
	s.push_back({base + 0x1E000, rq(f.rec, 0xF0000), g});
	return s;
}

static bool load(const std::string &p, std::vector<uint8_t> &v) {
	FILE *f = fopen(p.c_str(), "rb");
	if (!f) { perror(p.c_str()); return false; }
	fseek(f, 0, SEEK_END); long sz = ftell(f); fseek(f, 0, SEEK_SET);
	v.resize((size_t)sz);
	bool ok = fread(v.data(), 1, (size_t)sz, f) == (size_t)sz;
	fclose(f);
	if (!ok) fprintf(stderr, "%s: short read\n", p.c_str());
	return ok;
}

template <class F>
static bool run_until(F cond, uint64_t limit, const char *what) {
	uint64_t t0 = cyc;
	while (!cond()) {
		tick();
		if (cyc - t0 > limit) { fprintf(stderr, "timeout waiting for %s (cycle %llu)\n", what, (unsigned long long)cyc); return false; }
	}
	return true;
}

int main(int argc, char **argv) {
	if (argc < 3) { fprintf(stderr, "see the header of tb_render.cpp for usage\n"); return 2; }
	int game_ram = -1; unsigned seed = 1;
	std::vector<Frame> frames;
	for (int i = 3; i < argc; i++) {
		std::string o = argv[i];
		if (i + 1 >= argc) { fprintf(stderr, "option %s needs a value\n", o.c_str()); return 2; }
		std::string v = argv[++i];
		if (o == "--game-ram") game_ram = atoi(v.c_str());
		else if (o == "--busy") busy = atoi(v.c_str());
		else if (o == "--lat") lat = atoi(v.c_str());
		else if (o == "--seed") seed = (unsigned)atoi(v.c_str());
		else if (o == "--line-clk") line_clk = (uint32_t)atoi(v.c_str());
		else if (o == "--frame") {
			size_t c = v.find(':');
			if (c == std::string::npos) { fprintf(stderr, "--frame BANK:file\n"); return 2; }
			Frame f; f.bank = atoi(v.substr(0, c).c_str()) & 1; f.path = v.substr(c + 1);
			if (!load(f.path, f.rec) || f.rec.size() < 0x100000) { fprintf(stderr, "%s: bad record\n", f.path.c_str()); return 2; }
			f.rec.resize(0x100000);
			std::string wp = f.path;
			size_t k = wp.rfind("rec_");
			if (k == std::string::npos) { fprintf(stderr, "%s: not a rec_FFFF.bin\n", f.path.c_str()); return 2; }
			f.name = wp.substr(k + 4, wp.size() - k - 8);
			wp.replace(k, 4, "watch_");
			if (!load(wp, f.watch) || f.watch.size() < 8 || memcmp(f.watch.data(), "NWAT", 4)) { fprintf(stderr, "%s: bad watch file\n", wp.c_str()); return 2; }
			frames.push_back(f);
		} else { fprintf(stderr, "unknown option %s\n", o.c_str()); return 2; }
	}
	if (game_ram < 0 || frames.empty()) { fprintf(stderr, "need --game-ram and --frame\n"); return 2; }
	rng.seed(seed);

	if (!load(argv[1], mem)) return 2;
	mem.resize(mem.size() + 4096, 0);
	if (memcmp(mem.data(), "NHDP", 4) || mem[4] != 3) { fprintf(stderr, "not a format-3 .hdp\n"); return 2; }
	if ((uint64_t)mem.size() >= REC_BASE) { fprintf(stderr, "pack overlaps the record buffers\n"); return 2; }

	uint8_t flags = mem[7];
	uint32_t options = u32m(12);
	int ov[4];                                   // top, right, bottom, left (hdref.render)
	for (int k = 0; k < 4; k++) ov[k] = std::min(255, std::max(0, (int)i32m(0x10 + 4 * k)));
	ov_t = ov[0]; ov_l = ov[3];
	img_h = std::max(0, (240 - ov[2] - ov[0]) * 2);
	img_w = std::max(0, (256 - ov[1] - ov[3]) * 2);

	t = new Vhd3_render_tb;
	t->game_ram    = game_ram;
	t->legacy      = flags & 1;
	t->has_pal     = (flags >> 1) & 1;
	t->cache_en    = (options & 8) == 0;
	t->render_orig = (options & 16) == 0;
	t->ov_top = ov[0]; t->ov_right = ov[1]; t->ov_bottom = ov[2]; t->ov_left = ov[3];
	t->keys_base   = u32m(0x80) / 8;
	t->rules_base  = u32m(0x88) / 8;
	t->conds_base  = u32m(0x90) / 8;
	t->clist_base  = u32m(0x98) / 8;
	t->blocks_base = u32m(0x80 + 8 * 4) / 8;
	t->pal_base    = u32m(0x80 + 8 * 12) / 8;
	t->bucket_mask = u32m(0x24) - 1;
	t->max_probe   = u32m(0x28);
	t->fb_base     = u32m(0x80 + 8 * 10) / 8;
	t->fb_len      = u32m(0x44);
	t->bgl_base    = u32m(0x80 + 8 * 5) / 8;       // section 5: background level table
	t->bgi_base    = u32m(0x80 + 8 * 13);          // section 13: value index (byte address)
	t->bgrec_base  = u32m(0x80 + 8 * 6) / 8;       // section 6: background records
	t->bgmap_base  = u32m(0x80 + 8 * 7);           // section 7: background maps (byte address)
	t->ratio_base  = u32m(0x80 + 8 * 8);           // section 8: scroll ratios (byte address)
	t->add_en       = u32m(0x80 + 8 * 16 + 4) != 0; // sections 16/17: the addition table
	t->akeys_base   = u32m(0x80 + 8 * 16) / 8;
	t->abucket_mask = u32m(0x4C) - 1;
	t->amax_probe   = u32m(0x50);
	t->alists_base  = u32m(0x80 + 8 * 17) / 8;
	t->tap_v = 0; t->tap_be = 0xFF; t->rs_start = 0; t->start = 0;
	t->ad_start = 0; t->ad_abort = 0; t->ad_bank = 0;
	t->reset = 1;
	for (int i = 0; i < 4; i++) tick();
	t->reset = 0;
	for (int i = 0; i < 8; i++) tick();

	int fail = 0;
	for (size_t fi = 0; fi < frames.size(); fi++) {
		const Frame &fr = frames[fi];
		// 1. capture -> dictionary
		memcpy(&rec_mem[(size_t)fr.bank * 0x100000], fr.rec.data(), 0x100000);
		auto s = frame_stream(fr);
		std::deque<Tap> q(s.begin(), s.end());
		stream_t0 = cyc;
		done_events.clear();
		uint64_t limit = 241ull * line_clk + 40000000;
		while (!q.empty() || done_events.empty()) {
			t->tap_v = 0;
			if (!q.empty() && cyc >= stream_t0 + (uint64_t)q.front().g * line_clk) {
				t->tap_v = 1; t->tap_a = q.front().a; t->tap_d = q.front().d; t->tap_be = q.front().be;
				q.pop_front();
			}
			tick();
			if (cyc - stream_t0 > limit) { fprintf(stderr, "timeout (dictionary)\n"); return 1; }
		}
		t->tap_v = 0;
		if (done_events.front() != fr.bank) { fprintf(stderr, "frame_done for the wrong bank\n"); return 1; }
		// 1b. ADD: the frame's lanes (a pack without additions gets none - done at once)
		uint64_t a0 = cyc;
		unsigned aovf = 0;
		t->ad_bank = fr.bank; t->ad_start = 1; tick(); t->ad_start = 0;
		if (!run_until([] { return (bool)t->ad_done; }, 400000000ull, "ADD")) return 1;
		aovf = t->ad_ovf;
		uint64_t add_clk = cyc - a0;
		// 2. RESOLVE
		cur_watch = &fr.watch;
		t->rs_bank = fr.bank; t->rs_start = 1; tick(); t->rs_start = 0;
		if (!run_until([] { return (bool)t->rs_done; }, 400000000ull, "RESOLVE")) return 1;
		// 4. RENDER
		img.assign((size_t)img_w * img_h * 3, 0);
		npix = 0; bad_order = 0; last_y = -1; last_x = -1; worst_line = 0;
		uint64_t r0 = cyc;
		line_t0 = cyc;
		t->bank = fr.bank; t->start = 1; tick(); t->start = 0;
		if (!run_until([] { return (bool)t->done; }, 4000000000ull, "RENDER")) return 1;
		if (last_y >= 0 && cyc - line_t0 > worst_line) worst_line = cyc - line_t0;
		uint64_t want = (uint64_t)(img_w / 2) * (img_h / 2);
		std::string op = std::string(argv[2]) + "_" + fr.name + ".rgb";
		FILE *o = fopen(op.c_str(), "wb");
		if (!o) { perror(op.c_str()); return 2; }
		uint32_t hd[3] = {0x4247524Eu, (uint32_t)img_w, (uint32_t)img_h};   // "NRGB"
		fwrite(hd, 4, 3, o);
		fwrite(img.data(), 1, img.size(), o);
		fclose(o);
		printf("frame %s bank %d pixels %llu/%llu render %llu worst_line %llu unsup %u "
		       "overflow %u %u order_errors %llu add %llu add_ovf %u\n", fr.name.c_str(), fr.bank,
		       (unsigned long long)npix, (unsigned long long)want, (unsigned long long)(cyc - r0),
		       (unsigned long long)worst_line, (unsigned)t->unsup, (unsigned)t->dict_overflow,
		       (unsigned)t->rs_overflow, (unsigned long long)bad_order,
		       (unsigned long long)add_clk, aovf);
		// path counters (cumulative over the run; rtl/hdpack/hd3_render.sv, VERILATOR only)
		auto *R = t->rootp;
		printf("  paths: walks %u kind2 %u restart %u sens %u rewrite %u memo_hit %u memo_new %u "
		       "scratch %u ofstall %u fovf %u ixr %u\n",
		       (unsigned)R->hd3_render_tb__DOT__render__DOT__sim_walks,
		       (unsigned)R->hd3_render_tb__DOT__render__DOT__sim_kind2,
		       (unsigned)R->hd3_render_tb__DOT__render__DOT__sim_restart,
		       (unsigned)R->hd3_render_tb__DOT__render__DOT__sim_sens,
		       (unsigned)R->hd3_render_tb__DOT__render__DOT__sim_rw,
		       (unsigned)R->hd3_render_tb__DOT__render__DOT__sim_memo_hit,
		       (unsigned)R->hd3_render_tb__DOT__render__DOT__sim_memo_new,
		       (unsigned)R->hd3_render_tb__DOT__render__DOT__sim_scratch,
		       (unsigned)R->hd3_render_tb__DOT__render__DOT__sim_ofstall,
		       (unsigned)R->hd3_render_tb__DOT__render__DOT__sim_fovf,
		       (unsigned)R->hd3_render_tb__DOT__render__DOT__sim_ixr);
		printf("  bg: steps %u add %u sub %u uncached %u worst_prep %u\n",
		       (unsigned)R->hd3_render_tb__DOT__render__DOT__sim_bgstep,
		       (unsigned)R->hd3_render_tb__DOT__render__DOT__sim_bgadd,
		       (unsigned)R->hd3_render_tb__DOT__render__DOT__sim_bgsub,
		       (unsigned)R->hd3_render_tb__DOT__render__DOT__sim_bgunc,
		       (unsigned)R->hd3_render_tb__DOT__render__DOT__sim_bgprep);
		if (npix != want || bad_order) fail = 1;
		cur_watch = nullptr;
	}
	delete t;
	return fail;
}
