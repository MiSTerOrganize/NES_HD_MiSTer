// tb_loadpct.cpp - hd_loadpct on NES-shaped timing: one pixel every 4 clocks, 341 pixels per line
// (256 active), 262 lines (240 active). The picture is a grey ramp so the text and its shadow are
// visible on light and dark ground. Writes one PPM per case (active area only) and checks:
//   - with show = 0 the picture is untouched;
//   - with show = 1 the only changed pixels are white or black and all lie inside the 76 x 12
//     corner box (4 in from the right and bottom edges);
//   - the text is right-aligned: the right-most white column is the same for 7%, 42% and 100%.
// usage: tb_loadpct <out dir>
#include "Vhd_loadpct.h"
#include "verilated.h"
#include <cstdio>
#include <cstdlib>
#include <string>
#include <vector>

double sc_time_stamp() { return 0; }

static const int HT = 341, HA = 256, VT = 262, VA = 240;

struct Frame { std::vector<unsigned char> rgb; };

static Vhd_loadpct *m;
static void tick() { m->clk = 0; m->eval(); m->clk = 1; m->eval(); }

static unsigned char ground(int x, int y) { return (unsigned char)((x + y) & 0xFF); }

// runs one frame; returns the active area as sampled at ce (what video_mixer would take)
static Frame frame(int show, int pct) {
	Frame f; f.rgb.assign(HA * VA * 3, 0);
	m->show_in = show; m->pct_in = pct;
	for (int y = 0; y < VT; y++)
		for (int x = 0; x < HT; x++) {
			bool act = x < HA && y < VA;
			unsigned char g = act ? ground(x, y) : 0;
			m->hb = x >= HA; m->vb = y >= VA;
			m->r_in = g; m->g_in = g; m->b_in = g;
			for (int c = 0; c < 4; c++) {
				m->ce = (c == 0);
				m->eval();
				if (c == 0 && act) {
					unsigned char *p = &f.rgb[(y * HA + x) * 3];
					p[0] = m->r_out; p[1] = m->g_out; p[2] = m->b_out;
				}
				tick();
			}
		}
	return f;
}

static void save(const Frame &f, const std::string &path) {
	FILE *o = fopen(path.c_str(), "wb");
	fprintf(o, "P6\n%d %d\n255\n", HA, VA);
	fwrite(f.rgb.data(), 1, f.rgb.size(), o);
	fclose(o);
}

static int fails = 0;
static void check(bool ok, const char *what) { printf("%s %s\n", ok ? "PASS" : "FAIL", what); fails += !ok; }

// right-most white column, -1 if none; also verifies changed pixels are confined to the box
static int analyse(const Frame &f, bool &confined, bool &bw, int &changed) {
	int right = -1; confined = true; bw = true; changed = 0;
	for (int y = 0; y < VA; y++)
		for (int x = 0; x < HA; x++) {
			const unsigned char *p = &f.rgb[(y * HA + x) * 3];
			unsigned char g = ground(x, y);
			if (p[0] == g && p[1] == g && p[2] == g) continue;
			changed++;
			bool white = p[0] == 0xFF && p[1] == 0xFF && p[2] == 0xFF;
			bool black = !p[0] && !p[1] && !p[2];
			if (!white && !black) bw = false;
			if (x < HA - 76 || x > HA - 4 || y < VA - 12 || y > VA - 4) confined = false;
			if (white && x > right) right = x;
		}
	return right;
}

int main(int argc, char **argv) {
	Verilated::commandArgs(argc, argv);
	std::string out = argc > 1 ? argv[1] : ".";
	m = new Vhd_loadpct;
	m->ce = 0; m->hb = 1; m->vb = 1; m->show_in = 0; m->pct_in = 0;
	for (int i = 0; i < 16; i++) tick();

	// a frame to learn the size, then the cases (the text of frame n is set at the end of n-1)
	frame(0, 0);
	Frame off = frame(0, 0);
	bool conf, bw; int ch;
	analyse(off, conf, bw, ch);
	check(ch == 0, "show = 0 leaves the picture untouched");

	int rights[3]; int pcts[3] = {7, 42, 100};
	for (int i = 0; i < 3; i++) {
		frame(1, pcts[i]);
		Frame f = frame(1, pcts[i]);
		save(f, out + "/loadpct_" + std::to_string(pcts[i]) + ".ppm");
		rights[i] = analyse(f, conf, bw, ch);
		char msg[128];
		snprintf(msg, sizeof msg, "%d%%: %d pixels changed, all white/black", pcts[i], ch);
		check(ch > 0 && bw, msg);
		snprintf(msg, sizeof msg, "%d%%: drawn only inside the corner box", pcts[i]);
		check(conf, msg);
	}
	check(rights[0] == rights[1] && rights[1] == rights[2] && rights[0] == HA - 6,
	      "right-aligned: last white column fixed at width - 6 for 7%, 42%, 100%");

	// back to hidden: the frame after show drops must be clean again
	frame(0, 100);
	Frame back = frame(0, 100);
	analyse(back, conf, bw, ch);
	check(ch == 0, "show = 0 again: the text is gone");

	printf("%s\n", fails ? "FAILED" : "ALL PASS");
	delete m;
	return fails ? 1 : 0;
}
