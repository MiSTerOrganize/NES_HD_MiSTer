/* rec_subset_test.c - proves the daemon's partial record copy (hdarm_rec.h fetch_record) holds
 * everything hdarm4 reads: for each frame, the display list from the FULL record must equal the
 * one from a buffer holding only fetch_record's bytes, with every other byte set to garbage.
 *
 *   build: gcc -O2 -DHDARM_LIB -c hdarm4.c && gcc -O2 rec_subset_test.c hdarm4.o -lm
 *   run:   rec_subset_test PACK.hdp REC.bin WATCH.bin [REC.bin WATCH.bin ...]
 * Exit 0 only if every frame matches. A control: setting env SUBSET_BREAK=1 drops the sprite
 * entries from the copy, which must make some frame with sprites differ.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "hdarm_rec.h"

int hdarm_init(const uint8_t *pack, size_t len);
uint32_t hdarm_nwatched(void);
int hdarm_frame(const uint8_t *rec, const uint8_t *vals, uint32_t nvals,
                const uint64_t **list, size_t *nq);

static uint8_t *load(const char *p, size_t *n) {
    FILE *f = fopen(p, "rb"); if (!f) { perror(p); exit(2); }
    fseek(f, 0, SEEK_END); long l = ftell(f); fseek(f, 0, SEEK_SET);
    uint8_t *b = malloc(l > 0 ? l : 1);
    if (fread(b, 1, l, f) != (size_t)l) { fprintf(stderr, "%s: short read\n", p); exit(2); }
    fclose(f); *n = l; return b;
}
static uint32_t le32(const uint8_t *p) { return p[0] | p[1] << 8 | p[2] << 16 | (uint32_t)p[3] << 24; }

static uint64_t *run(const uint8_t *rec, const uint8_t *vals, uint32_t nw, size_t *nq) {
    const uint64_t *dl;
    if (hdarm_frame(rec, vals, nw, &dl, nq)) { fprintf(stderr, "hdarm_frame failed\n"); exit(2); }
    uint64_t *c = malloc(*nq * 8 + 8); memcpy(c, dl, *nq * 8); return c;
}

int main(int argc, char **argv) {
    if (argc < 4 || (argc - 2) % 2) { fprintf(stderr, "usage: rec_subset_test PACK REC WATCH [REC WATCH ...]\n"); return 2; }
    int brk = getenv("SUBSET_BREAK") != NULL;
    size_t pl; uint8_t *pack = load(argv[1], &pl);
    if (hdarm_init(pack, pl)) { fprintf(stderr, "pack refused\n"); return 2; }
    uint32_t nw = hdarm_nwatched();
    uint8_t *part = malloc(REC_LEN);
    int bad = 0, n = 0;
    for (int a = 2; a < argc; a += 2) {
        size_t rl, wl; uint8_t *rec = load(argv[a], &rl), *wat = load(argv[a + 1], &wl);
        if (rl < REC_LEN) { uint8_t *r2 = calloc(1, REC_LEN); memcpy(r2, rec, rl); free(rec); rec = r2; }
        uint8_t vals[256] = {0};
        if (nw) {
            if (memcmp(wat, "NWAT", 4) || le32(wat + 4) != nw) { fprintf(stderr, "%s: watch list mismatch\n", argv[a + 1]); return 2; }
            memcpy(vals, wat + 8 + 4 * nw, nw > 256 ? 256 : nw);
        }
        memset(part, 0xA5, REC_LEN);                 /* garbage wherever fetch_record does not copy */
        fetch_record(part, rec);
        if (brk) for (int y = 0; y < 240; y++) memset(part + 0x40000 + y * 2048 + 640, 0xA5, 64 * 16);
        size_t n1, n2, n3;
        uint64_t *full = run(rec, vals, nw, &n1);
        uint64_t *sub = run(part, vals, nw, &n2);
        uint64_t *full2 = run(rec, vals, nw, &n3);
        int ok = n1 == n2 && n1 == n3 && !memcmp(full, sub, n1 * 8) && !memcmp(full, full2, n1 * 8);
        printf("%s: %zu qwords %s\n", argv[a], n1, ok ? "same" : "DIFFER");
        bad += !ok; n++;
        free(full); free(sub); free(full2); free(rec); free(wat);
    }
    printf("%d of %d frames identical\n", n - bad, n);
    return bad ? 1 : 0;
}
