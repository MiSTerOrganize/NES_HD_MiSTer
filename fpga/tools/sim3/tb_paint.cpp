// tb_paint.cpp - hd3_paint against hdarm4's display list and the pack's blocks.
//   tb_paint PACK.hdp LIST.dl OUT.ppm [seed]
// The pack is loaded at DDR3 qword 0 and the list's commands at qword 0x1000000; both reader
// clients get random acknowledge and return latencies on one shared return bus (one beat per
// clock), as hd3_ddr serves them. line_ok drops at random. The finished frame is written as a
// PPM cropped to the pack's overscan, the same crop hdarm4 --img uses, so the two compare
// directly (tools/armdec/img_cmp.py against hdref.py's PNG).
#include "Vhd3_paint.h"
#include "verilated.h"
#include <cstdio>
#include <cstdint>
#include <cstring>
#include <cstdlib>
#include <deque>
#include <vector>

double sc_time_stamp() { return 0; }

static std::vector<uint8_t> mem;
static uint64_t rdq(uint64_t qa) {
    uint64_t v = 0;
    if (qa * 8 + 8 <= mem.size()) memcpy(&v, &mem[qa * 8], 8);
    return v;
}

struct Beat { uint64_t due; int client; uint64_t data; };

int main(int argc, char **argv) {
    if (argc < 4) { fprintf(stderr, "usage: tb_paint PACK LIST OUT.ppm [seed]\n"); return 2; }
    unsigned seed = argc > 4 ? atoi(argv[4]) : 1;
    srand(seed);
    FILE *f = fopen(argv[1], "rb"); if (!f) { perror(argv[1]); return 2; }
    fseek(f, 0, SEEK_END); long ps = ftell(f); fseek(f, 0, SEEK_SET);
    const uint64_t LIST_Q = 0x1000000;
    mem.assign(LIST_Q * 8, 0);
    if (fread(mem.data(), 1, ps, f) != (size_t)ps) { fprintf(stderr, "short read\n"); return 2; }
    fclose(f);
    f = fopen(argv[2], "rb"); if (!f) { perror(argv[2]); return 2; }
    uint64_t hdr[2];
    if (fread(hdr, 8, 2, f) != 2) return 2;
    uint64_t n = hdr[1] >> 32;
    int top = hdr[1] & 255, bottom = (hdr[1] >> 8) & 255, left = (hdr[1] >> 16) & 255, right = (hdr[1] >> 24) & 255;
    mem.resize((LIST_Q + n + 64) * 8, 0);
    if (fread(&mem[LIST_Q * 8], 8, n, f) != n) { fprintf(stderr, "short list\n"); return 2; }
    fclose(f);
    if (hdr[0] & 7) { fprintf(stderr, "block section not qword aligned\n"); return 2; }
    // "pub": the list is published progressively, as the ARM may: list_end grows in multiples
    // of 8 qwords at random moments, and every qword not yet published holds garbage. A burst
    // read past list_end would paint that garbage, so the picture proves the gate.
    bool pub = argc > 5 && !strcmp(argv[5], "pub");
    uint64_t npad = (n + 7) & ~7ull, published = pub ? 0 : 0x1FFFFFF;
    std::vector<uint8_t> real(&mem[LIST_Q * 8], &mem[LIST_Q * 8] + npad * 8);
    if (pub) for (uint64_t i = 0; i < npad * 8; i++) mem[LIST_Q * 8 + i] = (uint8_t)rand();

    Vhd3_paint *t = new Vhd3_paint;
    t->list_base = LIST_Q;
    t->list_end = pub ? LIST_Q : 0x1FFFFFF;
    t->blocks_base = hdr[0] / 8;
    t->ov_top = top; t->ov_bottom = bottom;
    t->line_ok = 1;
    t->reset = 1;
    uint64_t cyc = 0;
    auto tick = [&]() { t->clk = 0; t->eval(); t->clk = 1; t->eval(); cyc++; };
    for (int i = 0; i < 4; i++) tick();
    t->reset = 0;
    for (int i = 0; i < 300; i++) tick();              // the tag clear

    static uint8_t img[480][512][3];
    memset(img, 0x55, sizeof img);
    std::deque<Beat> ret;
    int ack_wait[2] = {0, 0};
    long nbeats[2] = {0, 0}, npx = 0, lok_off = 0;
    t->start = 1; tick(); t->start = 0;
    bool fin = false;
    while (cyc < 50000000) {
        // inputs for this clock
        t->l_rd_ack = 0; t->b_rd_ack = 0; t->l_rd_valid = 0; t->b_rd_valid = 0;
        if (!ret.empty() && ret.front().due <= cyc) {
            Beat b = ret.front(); ret.pop_front();
            t->rd_data = b.data;
            if (b.client == 0) t->l_rd_valid = 1; else t->b_rd_valid = 1;
            nbeats[b.client]++;
        }
        // one acknowledge per clock, client order alternating
        for (int k = 0; k < 2; k++) {
            int c = (cyc + k) & 1;
            bool req = c == 0 ? t->l_rd_req : t->b_rd_req;
            if (!req) { ack_wait[c] = 0; continue; }
            if (ack_wait[c] == 0) ack_wait[c] = 1 + rand() % 6;
            if (--ack_wait[c] == 0) {
                uint64_t a = c == 0 ? t->l_rd_addr : t->b_rd_addr;
                if (c == 0) t->l_rd_ack = 1; else t->b_rd_ack = 1;
                uint64_t due = cyc + 12 + rand() % 30;
                if (!ret.empty() && due <= ret.back().due) due = ret.back().due + 1;
                for (int i = 0; i < 8; i++) ret.push_back({due + i, c, rdq(a + i)});
                break;
            }
        }
        if (pub && published < npad && rand() % 3000 == 0) {
            uint64_t step = 8 * (1 + rand() % 64), np = published + step > npad ? npad : published + step;
            memcpy(&mem[(LIST_Q + published) * 8], &real[published * 8], (np - published) * 8);
            published = np;
            t->list_end = LIST_Q + published;
        }
        if (rand() % 64 == 0) t->line_ok = !t->line_ok;
        if (!t->line_ok) lok_off++;
        tick();
        if (t->out_v) {
            int y = t->out_y, x = t->out_x;
            for (int s = 0; s < 4; s++) {
                uint32_t v = 0;
                for (int b = 0; b < 3; b++) v |= (uint32_t)((t->out_px[(s * 24 + b * 8) / 32] >> ((s * 24 + b * 8) % 32)) & 255) << (b * 8);
                // sub-pixel s: 0 r0c0, 1 r0c1, 2 r1c0, 3 r1c1; v = {R, G, B} with R high
                int r = s >> 1, c = s & 1;
                img[2 * y + r][2 * x + c][0] = (v >> 16) & 255;
                img[2 * y + r][2 * x + c][1] = (v >> 8) & 255;
                img[2 * y + r][2 * x + c][2] = v & 255;
            }
            npx++;
        }
        if (t->done) { fin = true; break; }
    }
    if (!fin) { fprintf(stderr, "TIMEOUT at %llu clocks, %ld pixels out\n", (unsigned long long)cyc, npx); return 1; }
    f = fopen(argv[3], "wb");
    int W = (256 - left - right) * 2, H = (240 - top - bottom) * 2;
    fprintf(f, "P6\n%d %d\n255\n", W, H);
    for (int yy = top * 2; yy < top * 2 + H; yy++) fwrite(&img[yy][left * 2][0], 1, (size_t)W * 3, f);
    fclose(f);
    printf("done in %llu clocks (%.1f per NES line), %ld pixels out, %ld list beats, %ld block beats, line_ok low %ld clocks\n",
           (unsigned long long)cyc, (double)cyc / (240 - top - bottom), npx, nbeats[0], nbeats[1], lok_off);
    delete t;
    return 0;
}
