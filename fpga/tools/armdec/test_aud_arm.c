/* test_aud_arm.c - unit checks on the ARM half of HD audio (aud_arm.c) for cases tb_audio's
 * scenario cannot reach (it loads one pack per run):
 *   1. a second pack load: a voice must not decode from a stream block it fetched out of the
 *      PREVIOUS pack (both packs put their section at the same file offset), on play and on a
 *      savestate restore;
 *   2. an SFX that ends must leave the voice list on the tick it ends: with seven SFX, a play on
 *      the next tick must append, not replace the oldest LIVE one;
 *   3. register edges: a loop write that arrives after a BGM's last frame must not revive it, a
 *      loop-off write must end a playing BGM, and the IMA index clamps at 88;
 *   4. restore checkpoints: the background builder makes a restore far into a stream start from
 *      the checkpoint below it (a few blocks, not the whole stream), with the same samples; a
 *      block that cannot be fetched keeps a checkpoint from being taken from its wrong state;
 *   5. a section whose entry table points past its end is refused;
 *   6. the log reader (aud_service on a fake DDR3): a late start (event 0 not a fresh pack reset)
 *      begins at the status tick and loads the pack's section itself; a fresh start begins at
 *      the pack reset; a long stall is caught up AUD_NSLOT ticks per pass; a torn status read
 *      is read again; a header that changes while its payload is read is left for the next
 *      pass; a header whose index is not the next one is not taken.
 * Build: gcc -O2 -std=gnu11 -I tools/armdec tools/armdec/test_aud_arm.c tools/armdec/aud_arm.c
 * (AUD_ARM_C overrides the second file for the negative control). Exit 0 = all pass.
 */
#include <stdio.h>
#include <string.h>
#include "aud_arm.h"

static uint8_t file[0x40000];           /* the pack file; the section sits at SEC */
#define SEC 0x1000u

/* fetches made, and a range [fail_lo, fail_hi) of file bytes that cannot be fetched */
static unsigned n_fetch = 0;
static uint32_t fail_lo = 0, fail_hi = 0;
static int fetch(void *ctx, uint32_t off, uint32_t len, uint8_t *dst) {
    (void)ctx;
    n_fetch++;
    if ((uint64_t)off + len > sizeof file) return 1;
    if (off < fail_hi && off + len > fail_lo) return 1;
    memcpy(dst, file + off, len);
    return 0;
}

/* a fake DDR3: the status (a list of values read in turn, the last one repeating), the event
   log, and a hook on the read of one qword */
static uint64_t st_seq[4]; static int st_n = 1, st_i = 0;
static uint64_t ev_log[2 * AUD_NEV];
static uint32_t hook_q = UINT32_MAX; static uint32_t hook_set_q; static uint64_t hook_v;
static uint64_t rd(void *ctx, uint32_t q) {
    (void)ctx;
    if (q == AUD_ST_Q) { uint64_t s = st_seq[st_i]; if (st_i + 1 < st_n) st_i++; return s; }
    if (q >= AUD_EV_Q && q < AUD_EV_Q + 2 * AUD_NEV) {
        uint64_t v = ev_log[q - AUD_EV_Q];
        if (q == hook_q) { ev_log[hook_set_q - AUD_EV_Q] = hook_v; hook_q = UINT32_MAX; }
        return v;
    }
    return 0;
}
static void wr(void *ctx, uint32_t q, uint64_t v) { (void)ctx; (void)q; (void)v; }
static const aud_io io = { rd, wr, fetch, NULL };

static void status(uint32_t T, uint16_t E) { st_seq[0] = 0xA7ull << 56 | (uint64_t)E << 32 | T; st_n = 1; st_i = 0; }
static void event(uint16_t i, int kind, uint32_t tick, uint64_t pay) {
    ev_log[2 * (i % AUD_NEV)] = 0xE1ull << 56 | (uint64_t)i << 40 | (uint64_t)kind << 36 | tick;
    ev_log[2 * (i % AUD_NEV) + 1] = pay;
}

static void put32(uint8_t *p, uint32_t v) { for (int i = 0; i < 4; i++) p[i] = (uint8_t)(v >> (8 * i)); }

/* a section: n entries of (key, frames), every stream filled with byte b; returns its length */
static uint32_t section(int n, const uint32_t *key, const uint32_t *frames, uint8_t b) {
    uint8_t *s = file + SEC;
    memset(s, 0, sizeof file - SEC);
    memcpy(s, "HDAU", 4);
    put32(s + 4, (uint32_t)n);
    uint32_t at = 16 + 32 * (uint32_t)n;
    for (int i = 0; i < n; i++) {
        uint8_t *e = s + 16 + 32 * i;
        put32(e, key[i]); put32(e + 4, at); put32(e + 8, frames[i]); put32(e + 12, 0);
        memset(s + at, b, frames[i]);       /* state 0 (s0, sl) left 0 */
        at += frames[i];
    }
    return at;
}

/* one BGM entry (key 0) of `frames` bytes of pseudo-random nibbles; returns the section length */
static uint32_t section_rand(uint32_t frames, uint32_t seed) {
    uint8_t *s = file + SEC;
    memset(s, 0, sizeof file - SEC);
    memcpy(s, "HDAU", 4);
    put32(s + 4, 1);
    put32(s + 16, 0); put32(s + 20, 48); put32(s + 24, frames); put32(s + 28, 0);
    for (uint32_t i = 0; i < frames; i++) {
        seed = seed * 1103515245u + 12345u;
        s[48 + i] = (uint8_t)(seed >> 16);
    }
    return 48 + frames;
}

/* an independent IMA decoder (the one in hdaudio.py), for the checkpoint table */
static const int T_STEP[89] = {
    7, 8, 9, 10, 11, 12, 13, 14, 16, 17, 19, 21, 23, 25, 28, 31, 34, 37, 41, 45, 50, 55, 60,
    66, 73, 80, 88, 97, 107, 118, 130, 143, 157, 173, 190, 209, 230, 253, 279, 307, 337, 371,
    408, 449, 494, 544, 598, 658, 724, 796, 876, 963, 1060, 1166, 1282, 1411, 1552, 1707, 1878,
    2066, 2272, 2499, 2749, 3024, 3327, 3660, 4026, 4428, 4871, 5358, 5894, 6484, 7132, 7845,
    8630, 9493, 10442, 11487, 12635, 13899, 15289, 16818, 18500, 20350, 22385, 24623, 27086,
    29794, 32767};
static void t_ima(int *p, int *x, int n) {
    static const int ID[8] = {-1, -1, -1, -1, 2, 4, 6, 8};
    int s = T_STEP[*x], d = s >> 3;
    if (n & 4) d += s;
    if (n & 2) d += s >> 1;
    if (n & 1) d += s >> 2;
    int v = n & 8 ? *p - d : *p + d;
    *p = v < -32768 ? -32768 : v > 32767 ? 32767 : v;
    int i = *x + ID[n & 7];
    *x = i < 0 ? 0 : i > 88 ? 88 : i;
}
static void put64(uint8_t *p, uint64_t v) { put32(p, (uint32_t)v); put32(p + 4, (uint32_t)(v >> 32)); }

/* append a checkpoint table to the one-entry section of section_rand (frames F, state 0 = 0),
   at the given spacing, optionally broken; returns the new section length */
static uint32_t ck_table(uint32_t len, uint32_t F, uint32_t spacing, int bad_count, int bad_first,
                         int bad_index) {
    uint8_t *s = file + SEC;
    /* the count is always the one the loader expects for AUD_CK, so a table at another
       spacing is refused by the spacing check alone, not by the count check */
    uint32_t off = (len + 7) & ~7u, n = F / AUD_CK + 1;
    put32(s + 12, off);
    put32(s + off, spacing); put32(s + off + 4, n + (bad_count ? 1 : 0));
    int pl = 0, il = 0, pr = 0, ir = 0;
    put64(s + off + 8, bad_first ? 1 : 0);
    for (uint32_t i = 0, k = 1; i < F && k < n; i++) {
        t_ima(&pl, &il, s[48 + i] & 15);
        t_ima(&pr, &ir, s[48 + i] >> 4);
        if ((i + 1) % spacing == 0) {
            uint64_t x = bad_index && k == 2 ? 89 : (uint64_t)ir;
            put64(s + off + 8 + 8 * k, (uint64_t)(pl & 0xFFFF) | (uint64_t)il << 16 |
                  (uint64_t)(pr & 0xFFFF) << 32 | x << 48);
            k++;
        }
    }
    return off + 8 + 8 * (n + (bad_count ? 1 : 0));
}

/* the pack header late_load reads: "NHDP", section 15 at 0xF8 / 0xFC */
static void pack_header(uint32_t off, uint32_t len) {
    memset(file, 0, SEC);
    memcpy(file, "NHDP", 4);
    put32(file + 0xF8, off); put32(file + 0xFC, len);
}

static int fails = 0;
static void check(int ok, const char *what) {
    printf("%s %s\n", ok ? "PASS" : "FAIL", what);
    if (!ok) fails++;
}

int main(void) {
    static aud_arm a;
    uint32_t out[AUD_NV];

    /* 1. two packs, the BGM stream at the same offset, different bytes */
    {
        uint32_t key[1] = {0}, fr[1] = {600};
        uint32_t len = section(1, key, fr, 0x77);      /* +7 nibbles: the predictor climbs */
        aud_init(&a);
        check(aud_load_section(&a, &io, SEC, len) == 0, "pack 1 loads");
        aud_write(&a, 5, 0);                           /* BGM 0 */
        for (int i = 0; i < 10; i++) aud_tick(&a, out);
        int16_t up = (int16_t)(out[0] & 0xFFFF);
        len = section(1, key, fr, 0xFF);               /* -7 nibbles: it falls */
        check(aud_load_section(&a, &io, SEC, len) == 0, "pack 2 loads");
        aud_write(&a, 5, 0);
        for (int i = 0; i < 10; i++) aud_tick(&a, out);
        int16_t down = (int16_t)(out[0] & 0xFFFF);
        check(up > 0 && down < 0, "a play after a pack load decodes the new pack's stream");

        /* the restore path: pack 1 again, play, load pack 2, restore BGM 0 at frame 10 */
        len = section(1, key, fr, 0x77);
        aud_load_section(&a, &io, SEC, len);
        aud_write(&a, 5, 0);
        for (int i = 0; i < 20; i++) aud_tick(&a, out);
        len = section(1, key, fr, 0xFF);
        aud_load_section(&a, &io, SEC, len);
        /* word A: volumes 128/128, BGM on, entry 0, frame 10 */
        uint64_t w = (uint64_t)128 << 48 | (uint64_t)128 << 40 | 1ull << 38 | 10;
        aud_restore(&a, w);
        aud_tick(&a, out);
        check((int16_t)(out[0] & 0xFFFF) < 0, "a restore after a pack load decodes the new pack's stream");
        aud_free(&a);
    }

    /* 2. seven SFX, the second one ends, then a play */
    {
        uint32_t key[3] = {0x10000, 0x10001, 0x10002}, fr[3] = {1000, 3, 1000};
        uint32_t len = section(3, key, fr, 0x77);
        aud_init(&a);
        aud_load_section(&a, &io, SEC, len);
        aud_write(&a, 6, 0);                           /* B: long, the oldest */
        aud_write(&a, 6, 1);                           /* A: three frames */
        for (int i = 0; i < 5; i++) aud_write(&a, 6, 2);  /* five more: seven */
        for (int i = 0; i < 3; i++) aud_tick(&a, out); /* A plays its last frame */
        aud_write(&a, 6, 2);                           /* six live: appended */
        aud_tick(&a, out);
        int live = 0;
        for (int k = 1; k < AUD_NV; k++) live += out[k] != 0;
        check(live == 7, "a play after an SFX ended keeps all six live SFX and adds the new one");
        aud_free(&a);
    }

    /* 3. register edges */
    {
        uint32_t key[1] = {0}, fr[1] = {10};
        uint32_t len = section(1, key, fr, 0x77);
        aud_init(&a);
        aud_load_section(&a, &io, SEC, len);
        aud_write(&a, 5, 0);                           /* BGM, loop off */
        for (int i = 0; i < 10; i++) aud_tick(&a, out); /* its last frame */
        aud_write(&a, 0, 1);                           /* loop on, after the end */
        aud_tick(&a, out);
        check(out[0] == 0, "a loop write after a BGM's last frame does not revive it");

        aud_write(&a, 0, 1);
        aud_write(&a, 5, 0);                           /* BGM, looping */
        for (int i = 0; i < 5; i++) aud_tick(&a, out);
        aud_write(&a, 0, 0);                           /* loop off while it plays */
        for (int i = 0; i < 10; i++) aud_tick(&a, out);
        check(out[0] == 0, "a loop-off write ends a playing BGM at its end");

        /* index to 88 and the predictor to +32767 (twelve +7 nibbles), then nibble 8: -(step>>3)
           with step 32767 (index 88) is 28672, scaled by 128/255 */
        uint8_t *s = file + SEC + 48;
        fr[0] = 13;
        len = section(1, key, fr, 0x77);
        s[12] = 0x88;
        aud_load_section(&a, &io, SEC, len);
        aud_write(&a, 0, 0);
        aud_write(&a, 5, 0);
        for (int i = 0; i < 13; i++) aud_tick(&a, out);
        check((int16_t)(out[0] & 0xFFFF) == 28672 * 128 / 255, "the IMA index clamps at 88");
        aud_free(&a);
    }

    /* 4. restore checkpoints */
    {
        const uint32_t F = 3 * AUD_CK + 500, X = 2 * AUD_CK + 300;
        uint32_t len = section_rand(F, 7);
        static aud_arm ref, b;
        aud_init(&ref);
        aud_load_section(&ref, &io, SEC, len);
        aud_write(&ref, 5, 0);
        for (uint32_t i = 0; i <= X; i++) aud_tick(&ref, out);
        uint32_t want = out[0];
        aud_free(&ref);

        aud_init(&b);
        aud_load_section(&b, &io, SEC, len);
        while (aud_build_checkpoints(&b, AUD_CKB_STEP)) {}
        int all = 1;
        for (uint32_t k = 0; k < b.ent[0].nck; k++) all &= b.ent[0].ckv[k];
        check(all, "the builder leaves a checkpoint every AUD_CK frames");
        n_fetch = 0;
        aud_restore(&b, (uint64_t)128 << 48 | (uint64_t)128 << 40 | 1ull << 38 | X);
        aud_tick(&b, out);
        check(out[0] == want, "a restore from a built checkpoint plays the same sample");
        check(n_fetch < 8, "a restore far into a stream reads a few blocks, not the stream");
        aud_free(&b);

        /* a block that cannot be fetched under checkpoint 1: no checkpoint from that state */
        aud_init(&b);
        aud_load_section(&b, &io, SEC, len);
        fail_lo = SEC + 48 + AUD_CK - 600; fail_hi = fail_lo + 1;
        aud_write(&b, 5, 0);
        for (uint32_t i = 0; i < AUD_CK + 20; i++) aud_tick(&b, out);
        fail_lo = fail_hi = 0;
        check(!b.ent[0].ckv[1], "no checkpoint is taken from a stream that missed a block");
        aud_restore(&b, (uint64_t)128 << 48 | (uint64_t)128 << 40 | 1ull << 38 | (AUD_CK + 5));
        aud_tick(&b, out);
        uint32_t got = out[0];
        aud_init(&ref);
        aud_load_section(&ref, &io, SEC, len);
        aud_write(&ref, 5, 0);
        for (uint32_t i = 0; i <= AUD_CK + 5; i++) aud_tick(&ref, out);
        check(got == out[0], "a restore past the missed block plays the stream's own samples");
        aud_free(&ref);
        aud_free(&b);
    }

    /* 4b. the section's own checkpoint table (hdaudio.build_section, since 2026-10-29): a
       restore far into a stream right after the pack loads, before any builder pass */
    {
        const uint32_t F = 3 * AUD_CK + 500, X = 2 * AUD_CK + 300;
        uint32_t base = section_rand(F, 9);
        static aud_arm ref, b;
        aud_init(&ref);
        aud_load_section(&ref, &io, SEC, base);
        aud_write(&ref, 5, 0);
        for (uint32_t i = 0; i <= X; i++) aud_tick(&ref, out);
        uint32_t want = out[0];
        aud_free(&ref);

        enum { OK, SPACING, COUNT, FIRST, INDEX, PAST };
        const char *what[] = {"", "another spacing", "a count that is not the entries' sum",
                              "a first state that is not state 0", "an index past 88",
                              "a table offset past the section"};
        for (int bad = OK; bad <= PAST; bad++) {
            uint32_t len = ck_table(base, F, bad == SPACING ? AUD_CK / 2 : AUD_CK,
                                    bad == COUNT, bad == FIRST, bad == INDEX);
            if (bad == PAST) put32(file + SEC + 12, len + 8);
            aud_init(&b);
            check(aud_load_section(&b, &io, SEC, len) == 0, "a section with a checkpoint table loads");
            n_fetch = 0;
            aud_restore(&b, (uint64_t)128 << 48 | (uint64_t)128 << 40 | 1ull << 38 | X);
            aud_tick(&b, out);
            if (bad == OK) {
                check(b.ck_loaded && b.ckb_e == b.n_ent, "the table is taken and the builder has nothing left");
                check(out[0] == want, "a restore before any builder pass plays the same sample");
                check(n_fetch < 8, "... reading a few blocks, not the stream");
            } else {
                char msg[160];
                snprintf(msg, sizeof msg, "a table with %s is not used", what[bad]);
                check(!b.ck_loaded && b.ckb_e == 0, msg);
                check(out[0] == want, "... and the restore still plays the right sample");
            }
            aud_free(&b);
        }
        put32(file + SEC + 12, 0);
    }

    /* 5. an entry past the section's end */
    {
        uint32_t key[1] = {0}, fr[1] = {100};
        uint32_t len = section(1, key, fr, 0x77);
        aud_init(&a);
        check(aud_load_section(&a, &io, SEC, len - 1) != 0 && a.n_ent == 0,
              "a section whose stream runs past its end is refused");
        aud_free(&a);
    }

    /* 6. the log reader */
    {
        uint32_t key[1] = {0}, fr[1] = {1000};
        uint32_t len = section(1, key, fr, 0x77);
        pack_header(SEC, len);
        memset(ev_log, 0, sizeof ev_log);

        /* late start: E small, but event 0 is a write from long ago (E wrapped) */
        aud_init(&a);
        event(0, 1, 5, 0x400); event(1, 1, 6, 0x400); event(2, 1, 7, 0x400);
        status(100000, 3);
        aud_service(&a, &io);
        check(a.started && a.next_t == 100000 && a.n_ent == 1,
              "a late start begins at the status tick and loads the pack's section");
        aud_free(&a);

        /* fresh start: event 0 is the pack reset, stamped just before the status */
        aud_init(&a);
        memset(ev_log, 0, sizeof ev_log);
        event(0, 3, 99990, (uint64_t)len << 32 | SEC);
        status(100000, 1);
        uint32_t n = aud_service(&a, &io);
        check(n == 10 && a.next_t == 100000 && a.resets == 1, "a fresh start begins at the pack reset");

        /* a stall: 20,000 ticks with nothing new, caught up AUD_NSLOT per pass */
        status(120000, 1);
        n = aud_service(&a, &io);
        check(n == AUD_NSLOT && a.restarts == 0, "a long stall is caught up a slot ring per pass");
        while (a.next_t != 120000 && aud_service(&a, &io)) {}
        check(a.next_t == 120000, "and reaches the status tick");

        /* a torn status read (a T of a wild jump), then the real one twice */
        st_seq[0] = 0xA7ull << 56 | 1ull << 32 | 0xF0000000u;
        st_seq[1] = 0xA7ull << 56 | 1ull << 32 | 120010u;
        st_seq[2] = st_seq[1]; st_n = 3; st_i = 0;
        aud_service(&a, &io);
        check(a.restarts == 0 && a.next_t == 120010, "a torn status is read again, not taken");

        /* a header that changes while its payload is read */
        event(1, 1, 120011, 0x401);
        hook_q = AUD_EV_Q + 2 * 1 + 1; hook_set_q = AUD_EV_Q + 2 * 1;
        hook_v = 0xE1ull << 56 | 2049ull << 40 | 1ull << 36 | 120020;
        status(120012, 2);
        unsigned ev0 = a.events;
        aud_service(&a, &io);
        check(a.ev_next == 1 && a.events == ev0, "a header that changes under its payload is left for the next pass");

        /* a stale header (the slot's previous use) is not the next event */
        event(1, 1, 120011, 0x401);
        ev_log[2] = 0xE1ull << 56 | (uint64_t)(uint16_t)(1 - AUD_NEV) << 40 | 1ull << 36 | 120011;
        status(120013, 2);
        aud_service(&a, &io);
        check(a.ev_next == 1 && a.events == ev0, "a header with the wrong index is not taken");

        /* the tick count jumps forward by more than any stall (2^30 ticks is six hours): a core
           reload whose count happens to be ahead, not a stall to render through */
        status(120013u + 0x40000000u + 1000u, 2);
        aud_service(&a, &io);
        check(a.restarts == 1, "a forward jump past 2^30 ticks is a new session");
        aud_free(&a);
    }
    printf("%s\n", fails ? "FAILED" : "ALL PASS");
    return fails != 0;
}
