/* ck_probe.c - load a converted pack's section 15 into the ARM half (aud_arm.c) and check its
 * restore-checkpoint table is taken, then restore every BGM/SFX entry at several points with and
 * without the table: the same sample must come out, and with the table the restore reads only a
 * few blocks. A pack converted before 2026-10-29 reports "no table".
 *   gcc -O2 -std=gnu11 -I tools/armdec tools/armdec/ck_probe.c tools/armdec/aud_arm.c -o ck_probe
 *   ck_probe <pack.hdp>          exit 0 = table taken and every restore matched
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "aud_arm.h"

static uint8_t *file; static size_t file_len; static unsigned n_fetch;
static int fetch(void *ctx, uint32_t off, uint32_t len, uint8_t *dst) {
    (void)ctx; n_fetch++;
    if ((uint64_t)off + len > file_len) return 1;
    memcpy(dst, file + off, len);
    return 0;
}
static uint64_t rd(void *ctx, uint32_t q) { (void)ctx; (void)q; return 0; }
static void wr(void *ctx, uint32_t q, uint64_t v) { (void)ctx; (void)q; (void)v; }
static const aud_io io = { rd, wr, fetch, NULL };
static uint32_t le32(const uint8_t *p) { return p[0] | p[1] << 8 | p[2] << 16 | (uint32_t)p[3] << 24; }

int main(int argc, char **argv) {
    if (argc != 2) { fprintf(stderr, "usage: ck_probe <pack.hdp>\n"); return 2; }
    FILE *f = fopen(argv[1], "rb");
    if (!f) { perror(argv[1]); return 2; }
    fseek(f, 0, SEEK_END); file_len = ftell(f); fseek(f, 0, SEEK_SET);
    file = malloc(file_len);
    if (!file || fread(file, 1, file_len, f) != file_len) { fprintf(stderr, "read failed\n"); return 2; }
    fclose(f);
    uint32_t off = le32(file + 0x80 + 8 * 15), len = le32(file + 0x80 + 8 * 15 + 4);
    if (!len) { printf("no section 15\n"); return 1; }

    static aud_arm a, b;
    aud_init(&a);
    if (aud_load_section(&a, &io, off, len)) { printf("section refused\n"); return 1; }
    printf("section at 0x%x, %u bytes, %d entries, checkpoint table %s\n", off, len, a.n_ent,
           a.ck_loaded ? "TAKEN" : "NOT taken");
    if (!a.ck_loaded) return 1;

    /* the reference: the same section with its table offset cleared (decodes from frame 0) */
    uint32_t keep = le32(file + off + 12);
    memset(file + off + 12, 0, 4);
    aud_init(&b);
    if (aud_load_section(&b, &io, off, len) || b.ck_loaded) { printf("reference load failed\n"); return 1; }
    file[off + 12] = keep; file[off + 13] = keep >> 8; file[off + 14] = keep >> 16; file[off + 15] = keep >> 24;

    int bad = 0, n = 0; unsigned max_fetch = 0, ref_fetch = 0;
    for (int e = 0; e < a.n_ent; e++) {
        uint32_t fr = a.ent[e].frames;
        if (!fr) continue;
        uint32_t pts[] = { 0, fr / 3, fr / 2, fr - 1, AUD_CK * (fr / AUD_CK / 2) + 777 };
        for (unsigned i = 0; i < sizeof pts / sizeof pts[0]; i++) {
            uint32_t p = pts[i] < fr ? pts[i] : fr - 1;
            uint64_t w = (uint64_t)128 << 48 | (uint64_t)128 << 40 | 1ull << 38 |
                         (uint64_t)e << 29 | p;
            uint32_t oa[AUD_NV], ob[AUD_NV];
            n_fetch = 0; aud_restore(&a, w); aud_tick(&a, oa);
            unsigned fa = n_fetch;
            n_fetch = 0; aud_restore(&b, w); aud_tick(&b, ob);
            if (fa > max_fetch) max_fetch = fa;
            if (n_fetch > ref_fetch) ref_fetch = n_fetch;
            n++;
            if (memcmp(oa, ob, sizeof oa)) {
                bad++;
                printf("MISMATCH entry %d frame %u: voice 0 %08x vs %08x\n", e, p, oa[0], ob[0]);
            }
        }
    }
    printf("%d restores, %d mismatches; block reads per restore: with table max %u, without %u\n",
           n, bad, max_fetch, ref_fetch);
    return bad ? 1 : 0;
}
