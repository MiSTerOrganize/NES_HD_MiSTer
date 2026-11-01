// Verilator testbench for rtl/hdpack/hd3_audio.sv. Driven by tools/audio/tb_audio_run.py.
//
//   tb_audio MEM.bin SCRIPT.txt OUT.txt [seed]
//
// MEM.bin is the pack file image (byte f of the file at offset f). The DDR3 model answers
// hd3_audio's 8-qword reads from it, mapping the address back to a file offset the way the
// loader stores the file (hi = 0: qword - PACK_Q; hi = 1: qword - OVF_Q + WIN_BYTES/8; the
// parameters are passed to Verilator as -G and repeated here through -D), with a random
// latency and random gaps between beats.
//
// SCRIPT lines:
//   C off len alt        configuration: section 15 offset/length, alternate registers
//   F sample             a 48 kHz frame: set the NES sample, wait for the frame, log it
//   W addr val           a CPU write (one core clock strobe, then a CPU cycle of 12 clocks)
//   R addr               a CPU read: log hit_rd and rdata (after 3 CPU cycles, as the CPU can)
//   Q addr val           a write timed to land 9-14 clk_f before the next 48 kHz tick
//   Z lo hi / S off      the header+entry table range and each stream start (file offsets)
//   B lo hi              busy DDR: reads outside Z and outside a stream's first block wait
//                        [lo, hi) clocks
//   H n                  the DDR answers nothing for the next n clk_f cycles
//   V [n]                a savestate save after n CPU cycles (8): log the two words ("V a b")
//   L a b                a savestate load of the two state words (hex)
//   X addr val           a save with a CPU write between reading word A and word B
//   A n                  the ARM half (tools/armdec/aud_arm.c, linked in) runs every n clk_f
//                        cycles; 0 = the ARM stops (default 700)
//   K d                  a pack reset d clk_f after a tick is taken: section length 0 for one
//                        clk_f (pok_f low for one clock, then a rising edge), then wait for the
//                        tables to reload. Logs "K st frames stamp_ok": the FSM state at the
//                        reset edge, the frames the device produced between that edge and the
//                        reload, and whether the logged reset event's tick is the frame count
//                        then. A tick being mixed must finish (frames 1, stamped after it).
//   N n                  run n more frames without logging them
// OUT lines: "F l r" per frame, "R hit val" per read, "V a b" per save, "K ..." per pack
// reset, "U n" underruns at the end.
//
// Since 2026-10-28 the device's decoding runs on the ARM: hd3_audio logs its events and status
// to DDR3 through its write port (aw_*) and reads a PCM slot per tick. The DDR model keeps every
// qword written at or above the mailbox (window qword 0x1880000) in a store and answers reads
// there from it; the ARM half reads and writes the same store through aud_io.
#include <cstdio>
#include <cstdlib>
#include <cstdint>
#include <cstring>
#include <vector>
#include <deque>
#include <string>
#include <unordered_map>
#include "Vhd3_audio.h"
#include "Vhd3_audio___024root.h"
#include "verilated.h"
#include "aud_arm.h"

#ifndef PACK_Q
#define PACK_Q 0
#endif
#ifndef OVF_Q
#define OVF_Q 0x0800000
#endif
#ifndef WIN_BYTES
#define WIN_BYTES 0x0C000000
#endif
#ifndef AUD_D
#define AUD_D 1024
#endif

double sc_time_stamp() { return 0; }

static Vhd3_audio* t;
static std::vector<uint8_t> mem;
static uint64_t hc = 0;                       // clk_f half cycles
static uint32_t rng = 1;
static uint32_t rnd() { rng ^= rng << 13; rng ^= rng >> 17; rng ^= rng << 5; return rng; }

// bad = the address points into the window that does not hold that file range (the loader put
// file bytes below WIN_BYTES only in the main window and the rest only in the overflow window),
// so the model returns junk there, as the real DDR3 would. lo = a main-window burst: a beat of it
// at or past WIN_BYTES is junk too (a burst that starts below the boundary and runs past it).
struct Burst { uint64_t f; int wait; int beat; bool bad; bool st; uint32_t q; bool lo; };
static std::deque<Burst> q;
static bool acked_hold = false;
static FILE* out;
static long nframes = 0;                      // frame_done strobes seen

// busy-DDR mode: reads other than the header/entry table (Z) and a stream's first block (S) take
// [busy_lo, busy_hi) clocks, as under contention from the render readers
static uint64_t busy_lo = 0, busy_hi = 0, z_lo = 0, z_hi = 0;
static uint64_t pcm_lo = 0, pcm_hi = 0;        // 'P': PCM slot read latency
static std::vector<uint64_t> starts;

// a copy of hd3_audio's 48 kHz accumulator, so a write can be timed to land just before a tick
static uint64_t tacc_m = 0, tmod_m = 85909091;
static uint64_t stall_until = 0;              // clk_f cycle until which the DDR is stalled
static uint64_t aw_stall_until = 0;           // 'G': clk_f cycle until which only writes stall
static int ticks_ahead() {
	uint64_t a = tacc_m;
	for (int c = 1; c < 10000; c++) {
		uint64_t n = a + 48000;
		if (n >= tmod_m) return c;
		a = n;
	}
	return 10000;
}
static long nhi = 0, nlo = 0;                 // bursts read through each window

static uint64_t qword_at(uint64_t f) {
	uint64_t v = 0;
	for (int i = 0; i < 8; i++) v |= (uint64_t)(f + i < mem.size() ? mem[f + i] : 0) << (8 * i);
	return v;
}

// the DDR3 store above the mailbox: written by hd3_audio's write port and by the ARM half
static const uint64_t STORE_Q = 0x1880000;
static std::unordered_map<uint32_t, uint64_t> store;
static long nwrites = 0, nstray = 0;
static long n_hitwr = 0, n_logged = 0;         // 'W' writes the device took / write events logged
static long n_rst_ev = 0;                      // pack-reset events logged
static long n_hit_loading = 0;                 // 'K': clocks the device took the bus mid-reload
static uint32_t last_rst_tick = 0;             // the tick field of the last one
static uint64_t st_rd(void*, uint32_t q) { auto it = store.find(q); return it == store.end() ? 0 : it->second; }
static void st_wr(void*, uint32_t q, uint64_t v) { store[q] = v; }
static int st_fetch(void*, uint32_t off, uint32_t len, uint8_t* dst) {
	if ((uint64_t)off + len > mem.size()) return 1;
	memcpy(dst, mem.data() + off, len);
	return 0;
}
static aud_arm arm;
static aud_io arm_io = { st_rd, st_wr, st_fetch, nullptr };
static long arm_every = 700;                  // clk_f cycles between ARM passes; 0 = ARM stopped
static long arm_count = 0;

// one clk_f cycle (two half cycles); the core clock rises with every fourth clk_f
static void cyc() {
	// a write the port takes at this edge (the values held before it)
	if (t->aw_valid && t->aw_ready) {
		uint32_t a = (uint32_t)t->aw_addr;
		store[a] = t->aw_data;
		nwrites++;
		if (a >= AUD_EV_Q && a < AUD_EV_Q + 2 * AUD_NEV && !((a - AUD_EV_Q) & 1) &&
		    ((t->aw_data >> 36) & 0xF) == 1)
			n_logged++;
		if (a >= AUD_EV_Q && a < AUD_EV_Q + 2 * AUD_NEV && !((a - AUD_EV_Q) & 1) &&
		    ((t->aw_data >> 36) & 0xF) == 3) {
			n_rst_ev++;
			last_rst_tick = (uint32_t)t->aw_data;
		}
		// the FPGA may write only its status and the event log
		if (a != AUD_ST_Q && !(a >= AUD_EV_Q && a < AUD_EV_Q + 2 * AUD_NEV)) {
			if (nstray++ < 5)
				fprintf(stderr, "stray write: qword %07x = %016llx\n", a,
				        (unsigned long long)t->aw_data);
		}
	}
	// the ARM half, between edges (it sees what the FPGA has written so far)
	if (arm_every && ++arm_count >= arm_every) {
		arm_count = 0;
		uint32_t n = aud_service(&arm, &arm_io);
		aud_build_checkpoints(&arm, AUD_CKB_STEP);      // as hdarm_daemon.c does each pass
		if (getenv("TB_AUDIO_DEBUG"))
			fprintf(stderr, "svc frame %ld: rendered %u, next_t %u, status %016llx\n", nframes, n,
			        arm.next_t, (unsigned long long)st_rd(nullptr, AUD_ST_Q));
	}
	// rising edge of clk_f (and of clk every 4th cycle)
	t->clk_f = 1;
	if ((hc / 2) % 4 == 0) t->clk = 1;
	t->eval();
	hc++;
	{ uint64_t n = tacc_m + 48000; tacc_m = n >= tmod_m ? n - tmod_m : n; }
	if (t->frame_done) nframes++;
	// drive the DDR3 side for the next edge
	t->rd_ack = 0;
	t->rd_valid = 0;
	bool stalled = hc / 2 < stall_until;          // 'H': the DDR answers nothing for a while
	t->aw_ready = !stalled && hc / 2 >= aw_stall_until && (rnd() % 3 != 0);   // busy a third of the time
	if (stalled) {
	} else if (t->rd_req && !acked_hold && !t->rd_hi && t->rd_addr >= STORE_Q) {
		// a read of the store (the PCM slots)
		int wait = (int)(8 + rnd() % 40);
		if (busy_hi > busy_lo) wait = (int)(busy_lo + rnd() % (busy_hi - busy_lo));
		if (pcm_hi > pcm_lo) wait = (int)(pcm_lo + rnd() % (pcm_hi - pcm_lo));
		q.push_back({0, wait, 0, false, true, (uint32_t)t->rd_addr, false});
		t->rd_ack = 1;
		acked_hold = true;
	} else if (t->rd_req && !acked_hold) {
		uint64_t a = t->rd_addr;
		bool bad;
		uint64_t f;
		if (t->rd_hi) {
			bad = a < OVF_Q;
			f = bad ? 0 : (a - OVF_Q) * 8 + (uint64_t)WIN_BYTES;
			nhi++;
		} else {
			bad = a < PACK_Q || (a - PACK_Q) * 8 >= (uint64_t)WIN_BYTES;
			f = bad ? 0 : (a - PACK_Q) * 8;
			nlo++;
		}
		int wait = (int)(8 + rnd() % 40);
		if (busy_hi > busy_lo && !bad && !(f >= z_lo && f < z_hi)) {
			bool first = false;
			for (uint64_t s : starts) if ((s >> 6) == (f >> 6)) first = true;
			if (!first) wait = (int)(busy_lo + rnd() % (busy_hi - busy_lo));
		}
		q.push_back({f, wait, 0, bad, false, 0, !t->rd_hi});
		t->rd_ack = 1;
		acked_hold = true;                       // req drops the clock after the ack
	} else if (!t->rd_req) {
		acked_hold = false;
	}
	if (!q.empty() && !stalled) {
		Burst& b = q.front();
		if (b.wait > 0) b.wait--;
		else if (rnd() % 4 != 0) {               // a beat, with random gaps
			t->rd_valid = 1;
			t->rd_data = b.st  ? st_rd(nullptr, b.q + b.beat)
			           : (b.bad || (b.lo && b.f + 8 * b.beat >= (uint64_t)WIN_BYTES))
			             ? 0xA5C3F00D5A3C0FF0ull ^ ((uint64_t)rnd() << 17) : qword_at(b.f + 8 * b.beat);
			if (++b.beat == 8) q.pop_front();
			// 'P': a PCM slot's beats are spread out too, so a tick can fall between its first
			// beat and its last (the slot then half old, half new)
			else if (b.st && pcm_hi > pcm_lo) b.wait = (int)(rnd() % 100);
		}
	}
	// falling edge
	t->clk_f = 0;
	if ((hc / 2) % 4 == 2) t->clk = 0;
	t->eval();
	hc++;
}

// advance to just after the next rising core-clock edge
static void core_edge() {
	do cyc(); while ((hc / 2) % 4 != 1);
}

static void cpu_cycles(int n) { for (int i = 0; i < 12 * n; i++) core_edge(); }

int main(int argc, char** argv) {
	if (argc < 4) { fprintf(stderr, "usage: tb_audio MEM SCRIPT OUT [seed [pal]]\n"); return 2; }
	FILE* f = fopen(argv[1], "rb");
	if (!f) return 2;
	fseek(f, 0, SEEK_END); mem.resize(ftell(f)); fseek(f, 0, SEEK_SET);
	if (fread(mem.data(), 1, mem.size(), f) != mem.size()) return 2;
	fclose(f);
	FILE* sc = fopen(argv[2], "r");
	out = fopen(argv[3], "w");
	if (!sc || !out) return 2;
	if (argc > 4) rng = (uint32_t)strtoul(argv[4], nullptr, 10) | 1;
	int pal = argc > 5 ? atoi(argv[5]) : 0;       // PAL: clk_f is 106406848 Hz
	tmod_m = pal ? 106406848ull : 85909091ull;

	aud_init(&arm);
	t = new Vhd3_audio;
	t->clk = 0; t->clk_f = 0; t->pal = pal; t->enable = 1; t->pack_ok = 0;
	t->eval();
	for (int i = 0; i < 64; i++) cyc();

	char line[256];
	long frames = 0;
	long frames_base = 0;                     // nframes at the alignment frame
	uint64_t hc_base = 0;                     // hc at the alignment frame
	while (fgets(line, sizeof line, sc)) {
		char k = line[0];
		if (k == 'Z') {
			unsigned long long lo, hi;
			sscanf(line + 1, "%llu %llu", &lo, &hi);
			z_lo = lo; z_hi = hi;
		} else if (k == 'S') {
			unsigned long long s;
			sscanf(line + 1, "%llu", &s);
			starts.push_back(s);
		} else if (k == 'A') {
			long n;
			sscanf(line + 1, "%ld", &n);
			arm_every = n;
		} else if (k == 'B') {
			unsigned long long lo, hi;
			sscanf(line + 1, "%llu %llu", &lo, &hi);
			busy_lo = lo; busy_hi = hi;
		} else if (k == 'P') {
			// PCM slot reads take [lo, hi) clocks: around one tick (~1,790 clk_f), so a read can
			// still be in flight when the next tick is mixed
			unsigned long long lo, hi;
			sscanf(line + 1, "%llu %llu", &lo, &hi);
			pcm_lo = lo; pcm_hi = hi;
		} else if (k == 'Q') {
			// a write timed so the device is still handling it when the next tick arrives
			unsigned a, v;
			sscanf(line + 1, "%x %x", &a, &v);
			core_edge();
			for (int g = 0; g < 2000; g++) {
				int ta = ticks_ahead();
				if (ta >= 9 && ta <= 14) break;
				core_edge();
			}
			t->addr = a; t->wdata = v;
			t->wr_strobe = 1;
			t->eval();
			if (t->hit_wr) n_hitwr++;
			core_edge();
			t->wr_strobe = 0;
		} else if (k == 'C') {
			unsigned long off, len, alt;
			sscanf(line + 1, "%lu %lu %lu", &off, &len, &alt);
			t->aud_off = off; t->aud_len = len; t->alt_regs = alt;
			core_edge();
			t->pack_ok = 1;
			long guard = 0;
			while (!t->active && guard++ < 2000000) cyc();
			if (!t->active) { fprintf(stderr, "never became active\n"); return 1; }
			// align: the first frame after the table is in (made with NES sample 0; the
			// model replays it as a priming frame)
			long n0 = nframes;
			while (nframes == n0) cyc();
			frames_base = nframes;
			hc_base = hc;
		} else if (k == 'F') {
			unsigned s;
			sscanf(line + 1, "%u", &s);
			if (nframes != frames_base + frames) {
				fprintf(stderr, "a frame passed inside a write/read block (script too dense)\n");
				return 1;
			}
			t->nes_sample = (uint16_t)s;
			long guard = 0;
			while (nframes == frames_base + frames && guard++ < 100000) cyc();
			if (nframes == frames_base + frames) { fprintf(stderr, "no frame\n"); return 1; }
			cyc();                                // out_l/out_r valid after the strobe
			fprintf(out, "F %d %d\n", (int16_t)t->out_l, (int16_t)t->out_r);
			frames++;
		} else if (k == 'W') {
			unsigned a, v;
			sscanf(line + 1, "%x %x", &a, &v);
			core_edge();
			t->addr = a; t->wdata = v;
			t->wr_strobe = 1;
			t->eval();
			if (t->hit_wr) n_hitwr++;
			core_edge();
			t->wr_strobe = 0;
			cpu_cycles(1);
		} else if (k == 'H') {
			unsigned long n;
			sscanf(line + 1, "%lu", &n);
			stall_until = hc / 2 + n;
		} else if (k == 'G') {
			unsigned long n;
			sscanf(line + 1, "%lu", &n);
			aw_stall_until = hc / 2 + n;
		} else if (k == 'V') {
			// a savestate save: the device has settled after the writes before it (8 CPU
			// cycles, or the given number); ss_save held while the registers are read, as
			// nes.v's saving_savestate is
			int w = 8;
			sscanf(line + 1, "%d", &w);
			cpu_cycles(w);
			t->ss_save = 1;
			cpu_cycles(1);
			fprintf(out, "V %016llx %016llx\n", (unsigned long long)t->ss_out_a,
			        (unsigned long long)t->ss_out_b);
			t->ss_save = 0;
			core_edge();
		} else if (k == 'X') {
			// a save with a register write between reading word A and word B: the device must
			// hold what it gave for A (the CPU is stopped during a real save, but the audio
			// runs on and the two registers are read at different times)
			unsigned addr, v;
			sscanf(line + 1, "%x %x", &addr, &v);
			cpu_cycles(8);
			t->ss_save = 1;
			cpu_cycles(1);
			unsigned long long a = t->ss_out_a;
			core_edge();
			t->addr = addr; t->wdata = v;
			t->wr_strobe = 1;
			t->eval();
			if (t->hit_wr) n_hitwr++;
			core_edge();
			t->wr_strobe = 0;
			cpu_cycles(8);
			// word A read again after the write (as the bus would if it read A late): with ss_save
			// held it must still be the value at the start of the save; print the late reading,
			// and fail outright if it moved
			if (t->ss_out_a != a) {
				fprintf(stderr, "save word A changed while ss_save was held\n");
				return 1;
			}
			fprintf(out, "V %016llx %016llx\n", (unsigned long long)t->ss_out_a,
			        (unsigned long long)t->ss_out_b);
			t->ss_save = 0;
			core_edge();
		} else if (k == 'L') {
			// a savestate load: the registers take the loaded values part-way through the load
			// (the bus writes them while ss_load is high), so a restore must wait for its end
			unsigned long long a, b;
			sscanf(line + 1, "%llx %llx", &a, &b);
			core_edge();
			t->ss_load = 1;
			cpu_cycles(1);
			t->ss_in_a = a; t->ss_in_b = b;
			cpu_cycles(1);
			t->ss_load = 0;
			cpu_cycles(2);
		} else if (k == 'K') {
			// a pack reset d clk_f after the edge that takes a tick (S_IDLE with tick_pend and
			// the tables in): the length goes to 0 on edge d, pok_f is low after it and high
			// after d+1, so edge d+2 is the reset - with d 0, the tracker's second clock
			int d = 0;
			sscanf(line + 1, "%d", &d);
			auto* r = t->rootp;
			long g = 0;
			while (!(r->hd3_audio__DOT__st == 0 && r->hd3_audio__DOT__tick_pend && t->active) &&
			       g++ < 4000000)
				cyc();
			if (!r->hd3_audio__DOT__tick_pend) { fprintf(stderr, "K: no tick pending\n"); return 1; }
			for (int i = 0; i < d; i++) cyc();
			uint32_t len = t->aud_len;
			t->aud_len = 0;
			cyc();                                // pok_f goes low on this edge
			t->aud_len = len;
			// the edge that sees pok_f high with old_pok low is the reset: note the state the
			// FSM is in at it (read before the edge, as the always block sees it)
			int st_edge = -1;
			long n_edge = 0;
			for (int i = 0; i < 8 && st_edge < 0; i++) {
				if (r->hd3_audio__DOT__pok_f && !r->hd3_audio__DOT__old_pok) {
					st_edge = r->hd3_audio__DOT__st;
					n_edge = nframes;
				}
				cyc();
			}
			if (st_edge < 0) { fprintf(stderr, "K: no reset edge\n"); return 1; }
			long ev0 = n_rst_ev;
			g = 0;
			while (t->active && g++ < 100) cyc();
			// while the tables reload the device must not take the bus: park the address on its
			// registers ($4100, the alternate $4018 read) and count the cycles it hits, once
			// tab_ok has been low longer than the core-clock copy the bus decode reads lags it
			g = 0;
			uint16_t keep_addr = t->addr;
			int low = 0;
			while (!t->active && g++ < 4000000) {
				t->addr = (g & 1) ? 0x4100 : 0x4018;
				t->eval();
				low = r->hd3_audio__DOT__tab_ok ? 0 : low + 1;
				if (low > 8 && (t->hit_rd || t->hit_wr)) n_hit_loading++;
				cyc();
			}
			t->addr = keep_addr;
			if (!t->active) { fprintf(stderr, "K: tables never reloaded\n"); return 1; }
			long frames_window = nframes - n_edge;
			g = 0;
			while (n_rst_ev == ev0 && g++ < 4000000) cyc();
			if (n_rst_ev == ev0) { fprintf(stderr, "K: no reset event logged\n"); return 1; }
			// the reset is stamped with the tick count when it is logged: every tick the device
			// mixed up to then (frame_done and tcount advance together)
			int stamp_ok = (long)last_rst_tick == n_edge + frames_window;
			fprintf(out, "K %d %ld %d\n", st_edge, frames_window, stamp_ok);
		} else if (k == 'N') {
			// run n more frames unlogged (after pack resets: the ARM half applies an event when
			// it renders that event's tick, and learns the tick from a status written every 16)
			long n = 0;
			sscanf(line + 1, "%ld", &n);
			long n0 = nframes, g = 0;
			while (nframes < n0 + n && g++ < 400000000L) cyc();
			if (nframes < n0 + n) { fprintf(stderr, "N: frames stopped\n"); return 1; }
		} else if (k == 'R') {
			unsigned a;
			sscanf(line + 1, "%x", &a);
			cpu_cycles(3);
			t->addr = a;
			core_edge();
			// rdata is a don't-care without hit_rd (nes.v only takes it on a hit)
			fprintf(out, "R %d %d\n", (int)t->hit_rd, t->hit_rd ? (int)t->rdata : 0);
		}
	}
	// 48 kHz rate: frames produced since alignment against clk_f clocks elapsed
	uint64_t clocks = (hc - hc_base) / 2;
	long expect = (long)(clocks * 48000ull / (pal ? 106406848ull : 85909091ull));
	if (getenv("TB_AUDIO_DEBUG"))
		fprintf(stderr, "arm: n_ent %d sec_len %u bgm.on %d n_sfx %d next_t %u\n", arm.n_ent,
		        arm.sec_len, arm.bgm.on, arm.n_sfx, arm.next_t);
	fprintf(out, "L %ld\n", n_hit_loading);
	fprintf(out, "E %d %ld %ld\n", (int)t->ev_lost, n_hitwr, n_logged);
	fprintf(out, "D %d\n", (int)AUD_D);
	fprintf(out, "A %u %u %u %u %u %ld %ld %d\n", arm.ticks, arm.events, arm.resets, arm.bad_events,
	        arm.fetch_fail, nwrites, nstray, arm.ck_loaded);
	fprintf(out, "T %ld %ld\n", expect, nframes - frames_base);
	fprintf(out, "H %ld %ld\n", nlo, nhi);
	fprintf(out, "U %d\n", (int)t->underruns);
	fclose(out);
	aud_free(&arm);
	delete t;
	return 0;
}
