// Verilator unit test for rtl/hdpack/hd3_fmap.sv on its own.
//
// hd3_fmap fills its maps by snooping the capture writer's record stream. This testbench drives
// that stream from a file built by gen_fmap_stream.py (24-byte records: u32 op, u32 a, u64 d,
// u32 be, u32 pad):
//   op 0  one write on the tap: tap_v = 1, tap_a = a (qword address), tap_d = d, tap_be = be
//   op 1  a clocks with tap_v = 0 while address, data and enables carry noise (d, be)
//   op 2  map dump n = a: every entry of BOTH banks read back through the read ports (one clock
//         latency each) into <prefix>_<n>.txt, which gen_fmap_stream.py check compares against
//         its byte model of the record buffers
// While writes stream, the read ports are driven with random addresses and banks, so a read on
// the same clock as a write is exercised too.
//
//   tb_fmap.exe <prefix> <stream.bin>
#include "Vhd3_fmap.h"
#include "verilated.h"
#include <cstdio>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <random>
#include <string>

double sc_time_stamp() { return 0; }

struct Rec { uint32_t op, a; uint64_t d; uint32_t be, pad; };

int main(int argc, char **argv) {
	if (argc != 3) { fprintf(stderr, "usage: tb_fmap.exe <prefix> <stream.bin>\n"); return 2; }
	std::string prefix = argv[1];
	FILE *f = fopen(argv[2], "rb");
	if (!f) { fprintf(stderr, "%s: cannot open\n", argv[2]); return 2; }
	std::mt19937 rng(1);

	Vhd3_fmap *t = new Vhd3_fmap;
	auto tick = [&]() { t->clk = 0; t->eval(); t->clk = 1; t->eval(); };
	t->tap_v = 0;
	tick();

	Rec r;
	long writes = 0, dumps = 0;
	while (fread(&r, sizeof r, 1, f) == 1) {
		if (r.op == 0 || r.op == 1) {
			uint32_t n = r.op == 0 ? 1 : r.a;
			for (uint32_t k = 0; k < n; k++) {
				t->tap_v  = r.op == 0;
				t->tap_a  = r.op == 0 ? r.a : (rng() & 0x1FFFFFF);
				t->tap_d  = r.d;
				t->tap_be = r.be;
				t->r_bank = rng() & 1;
				t->p_a = rng() & 0x7FFF;
				t->l_y = rng() & 0xFF;
				t->s_y = rng() & 0xFF;
				tick();
			}
			if (r.op == 0) writes++;
		} else if (r.op == 2) {
			t->tap_v = 0;
			std::string path = prefix + "_" + std::to_string(r.a) + ".txt";
			FILE *o = fopen(path.c_str(), "w");
			if (!o) { fprintf(stderr, "%s: cannot write\n", path.c_str()); return 2; }
			for (int bank = 0; bank < 2; bank++) {
				t->r_bank = bank;
				for (int a = 0; a < 240 * 128; a++) { t->p_a = a; tick(); fprintf(o, "P %d %d %04x\n", bank, a, t->p_q); }
				for (int y = 0; y < 240; y++) {
					t->l_y = y; t->s_y = y; tick();
					fprintf(o, "L %d %d %03x\n", bank, y, t->l_q);
					for (int i = 0; i < 16; i++) {
						uint32_t v = 0;     // lane i = s_q[26i +: 26] of a 416-bit VlWide
						for (int b = 0; b < 26; b++) {
							int bit = 26 * i + b;
							v |= ((t->s_q[bit >> 5] >> (bit & 31)) & 1u) << b;
						}
						fprintf(o, "S %d %d %d %07x\n", bank, y, i, v);
					}
				}
			}
			fclose(o);
			dumps++;
		} else {
			fprintf(stderr, "bad op %u\n", r.op);
			return 2;
		}
	}
	fclose(f);
	printf("%ld writes, %ld dumps\n", writes, dumps);
	delete t;
	return 0;
}
