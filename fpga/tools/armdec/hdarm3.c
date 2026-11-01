/* hdarm3.c - hdarm2.c without a per-pixel record array (OPEN_ITEMS item 11, round 3, 2026-10-22).
 *
 * Round 2 left an 8.3 ms floor on an EMPTY frame: writing and reading 61,440 32-byte pixel
 * records. Here a pixel's tile record is rebuilt on demand from the capture's 4-byte entry and
 * a per-line table of span records; only sprite pixels get a stored block, and the fallback
 * rewrite of a tile's index lives in an overlay (bitmap + int32 array) because the original
 * keeps it in the record. The additions pass's copy of each line's first pixel over (0,0) is
 * modelled by pointing (0,0) at that line (P0L) and copying its sprite block. Decisions must
 * stay byte-identical; parity.sh checks it.
 *
 * Round 2 header follows.
 *
 * hdarm2.c - hdarm.c restructured for speed, decisions unchanged (OPEN_ITEMS item 11, 2026-10-22).
 *
 * hdarm.c is the straight port and stays as the baseline. Changes here, each one exact:
 *   - compact records: Rec 24 bytes, sprites in a pool of 4-slot blocks allocated only for
 *     pixels that have a sprite (Pix 32 bytes instead of 168: 2 MB written per frame, not 10)
 *   - key-table lookups memoised per frame (find_key is a pure function of the pack)
 *   - whole get_matching result memoised per frame for keys whose rule list is STATIC: every
 *     condition in it is either frame-memoised (bit 11) or reads only SNAP/FRAME (types 0-2).
 *     Such a list gives the same answer at every pixel once its conditions have been seen,
 *     so the first call walks it for real (in the original order) and later calls replay it,
 *     including the fallback rewrite of the record's tile index.
 *     The static flag is a property of the pack; it is computed lazily and kept across
 *     iterations (a pack builder could store it), everything else is reset every iteration.
 *   - additions indexed by original-tile body, so a cache miss looks at matching additions only
 *   - the additions cache is reset by generation number instead of a 2 MB memset
 * Negative control MUT_MEMOALL memoises EVERY key: if parity still holds with it, these frames
 * do not exercise the static/non-static distinction and say nothing about it.
 *
 * Original header follows.
 *
 * hdarm.c - the stage-3 per-frame DECISION work in plain C, for the ARM-helper feasibility study
 * (OPEN_ITEMS item 11, 2026-10-21).
 *
 * Port of tools/hdref.py's decision path (build_records, select_backgrounds, process_additions,
 * get_matching with the BG 8-pixel cache and sprite draw order). Compositing is left out: it
 * stays in the FPGA in the ARM-helper design. Output must equal tools/armdec/hdref_decisions.py
 * byte for byte (same order, same format); that is the correctness check. Then it is timed on
 * the DE10-Nano's Cortex-A9.
 *
 * usage: hdarm PACK.hdp REC.bin WATCH.bin [--delta D] [--iters N] [--out FILE] [--quiet]
 *   --out   write the decision dump of the first iteration
 *   --iters repeat the whole decision pass N times (fresh state each time) and report timing
 */
#define _POSIX_C_SOURCE 200809L
/* 64-bit stat on 32-bit ARM: without it fstat fails with EOVERFLOW on filesystems whose inode
   numbers do not fit 32 bits (Docker bind mounts did; 2026-10-21) */
#define _FILE_OFFSET_BITS 64
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#ifndef _WIN32
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>
#endif

#define NOTILE (-1LL)

/* ---------------------------------------------------------------- byte access (little-endian) */
static const uint8_t *D;   /* the .hdp */
static uint32_t rd32(const uint8_t *p) { return p[0] | p[1] << 8 | p[2] << 16 | (uint32_t)p[3] << 24; }
static uint64_t rd64(const uint8_t *p) { return rd32(p) | (uint64_t)rd32(p + 4) << 32; }

/* ---------------------------------------------------------------- CRC-32 (MSB first, init 0) */
static uint32_t T32[256];
static void crc_init(void) {
    for (uint32_t i = 0; i < 256; i++) {
        uint32_t r = i << 24;
        for (int k = 0; k < 8; k++) r = (r & 0x80000000u) ? (r << 1) ^ 0x04C11DB7u : r << 1;
        T32[i] = r;
    }
}
static uint32_t crc32b(const uint8_t *d, int n) {
    uint32_t r = 0;
    for (int i = 0; i < n; i++) r = (r << 8) ^ T32[((r >> 24) ^ d[i]) & 0xFF];
    return r;
}

/* ---------------------------------------------------------------- pack header */
static uint32_t H_flags, H_options, nbuckets, max_probe, nconds, nwatched, nadd, nfallback;
static int32_t overscan[4];
static uint32_t SEC[18];
static int legacy, game_ram, cache_enabled;

/* ---------------------------------------------------------------- per-pixel records */
typedef struct {
    uint64_t fp;
    int32_t idx;
    uint32_t pal;
    uint8_t fpv, offx, offy, hm, vm, bgp, sci;
} Rec;
/* No per-pixel record array. A pixel's TILE record is built on demand from the capture's
   4-byte pixel entry (span slot, fine x) and a per-line table of span records; the only
   per-pixel state kept is (a) the sprite-block number, for pixels that have sprites, and
   (b) an overlay for the fallback rewrite of a tile's index, which the original makes
   persistent in its record. Pixel (0,0) is special: the additions pass copies each line's
   first pixel over it (hdref quirk), so it shows line P0L's first pixel. */
typedef struct { Rec r[4]; uint8_t n; } SBlk;

#ifdef CSTATS
long CST[16][2];
#endif
static const uint8_t *RECB;       /* the capture */
static Rec SPAN[240][35];         /* [y][slot]; slot 34 = no tile */
static uint8_t NSPAN[240], LFX[240];
static uint16_t LT[240];
static uint16_t *SBI;             /* per pixel: sprite block, 0 = none */
static SBlk *SB; static uint32_t SBn;
static uint8_t MUTB[61440 / 8]; static int32_t MUTI[61440];
static int P0L;
static int CUR_PIX = -1;          /* pixel whose tile record get_matching is working on */

static void tile_rec(int i, Rec *t) {
    int y = i >> 8, x = i & 255;
    if (i == 0) y = P0L;
    const uint8_t *b = RECB + y * 1024 + x * 4;
    int slot = b[0] & 63;
    if (slot >= NSPAN[y]) slot = 34;
    *t = SPAN[y][slot];
    t->offx = (b[1] >> 2) & 7;
    if ((MUTB[i >> 3] >> (i & 7)) & 1) t->idx = MUTI[i];
}
static uint16_t line_t(int y) { return LT[y == 0 ? P0L : y]; }
static int nspr_of(int i) { return SBI[i] ? SB[SBI[i]].n : 0; }
static Rec *spr_of(int i, int k) { return &SB[SBI[i]].r[k]; }
static Rec *spr_push(int i) {
    if (!SBI[i]) { SBI[i] = (uint16_t)++SBn; SB[SBn].n = 0; }
    SBlk *b = &SB[SBI[i]];
    return &b->r[b->n++];
}
/* a change to the index of the tile record get_matching is working on, written through */
static void set_idx(Rec *r, int32_t v) {
    r->idx = v;
#ifdef MUT_NOWT   /* negative control: tile-index rewrite not written through to the overlay */
    return;
#endif
    if (CUR_PIX >= 0) { MUTB[CUR_PIX >> 3] |= (uint8_t)(1 << (CUR_PIX & 7)); MUTI[CUR_PIX] = v; }
}
static uint32_t FRAME;
/* Feature-usage study (OPEN_ITEMS item 11): env HD_FEATOFF switches pack features off so the
   decision dump can be diffed against the exact one. An unsupported condition FAILS (its rule
   cannot match), which is what a renderer without the feature would do.
     1 tileAtPosition/spriteAtPosition (3,4)   2 tileNearby/spriteNearby (5,6)
     4 position conditions (7-10)              8 hmirror/vmirror/bgpriority (11-13)
    16 additions                              32 backgrounds
    64 memory / frame-range conditions (0-2, frame-level, the ARM's job either way)
   0 (the default) leaves the program exact; parity.sh runs with it unset. */
static unsigned FEATOFF;
static unsigned feat_bit(int t) {
    return t <= 2 ? 64 : t <= 4 ? 1 : t <= 6 ? 2 : t <= 10 ? 4 : 8;
}
static uint8_t SNAP[256];
static int8_t *MEMO;      /* frame-condition memo, -1 = not evaluated */
static long st_rules, st_conds, st_fb, st_add;

static void build_records(const uint8_t *rec) {
    RECB = rec;
    memset(SBI, 0, 61440 * sizeof(uint16_t));
    memset(MUTB, 0, sizeof MUTB);
    P0L = 0;
    for (int y = 0; y < 240; y++) {
        const uint8_t *h = rec + 0x40000 + y * 2048;
        uint64_t q0 = rd64(h);
        int nspan = (int)((q0 >> 32) & 0xFF); if (nspan > 34) nspan = 34;
        int nspr = (int)((q0 >> 48) & 0xFF); if (nspr > 64) nspr = 64;
        uint8_t pal[32];
        for (int n = 0; n < 32; n++) {
            int bit = 6 * n, by = bit >> 3, sh = bit & 7;
            uint32_t v = h[8 + by] | (by + 1 < 24 ? h[9 + by] << 8 : 0);
            pal[n] = (v >> sh) & 63;
        }
        uint32_t sp_lin[34], sp_psel[34]; uint64_t sp_fp[34];
        for (int s = 0; s < nspan; s++) {
            uint64_t qa = rd64(h + 64 + s * 16), qb = rd64(h + 72 + s * 16);
            sp_lin[s] = qa & 0x3FFFFF; sp_psel[s] = (qa >> 32) & 3; sp_fp[s] = qb;
        }
        int ns = 0;
        uint8_t o_attr[64], o_sx[64], o_p1[64], o_p2[64]; uint32_t o_lin[64]; uint64_t o_fp[64];
        for (int i = 0; i < nspr; i++) {
            uint64_t qa = rd64(h + 640 + i * 16), qb = rd64(h + 648 + i * 16);
            if (!((qa >> 54) & 1)) continue;
            o_attr[ns] = (qa >> 46) & 0xFF; o_sx[ns] = (qa >> 38) & 0xFF;
            o_lin[ns] = (qa >> 16) & 0x3FFFFF; o_p1[ns] = (qa >> 8) & 0xFF; o_p2[ns] = qa & 0xFF;
            o_fp[ns] = qb; ns++;
        }
        LT[y] = q0 & 0x7FFF; LFX[y] = (q0 >> 15) & 7;
        NSPAN[y] = (uint8_t)nspan;
        /* slots 0..nspan-1 hold the line's spans; tile_rec maps every other slot value
           (63 = no span, or one past the line's spans) to slot 34, the no-tile record */
        for (int slot = 0; slot < nspan; slot++) {
            Rec *tl = &SPAN[y][slot];
            uint32_t lin = sp_lin[slot]; int pb = sp_psel[slot] * 4;
            tl->offx = 0; tl->hm = tl->vm = tl->bgp = 0; tl->sci = 0;
            tl->idx = (lin & 0xFFFFF) >> 4; tl->offy = lin & 7;
            tl->pal = pal[pb + 3] | pal[pb + 2] << 8 | pal[pb + 1] << 16;
            if (!legacy) tl->pal |= (uint32_t)pal[0] << 24;
            tl->fpv = 1; tl->fp = game_ram ? sp_fp[slot] : 0;
        }
        {
            Rec *tl = &SPAN[y][34];
            memset(tl, 0, sizeof *tl);
            tl->idx = NOTILE;
        }
        if (!ns) continue;
        for (int x = 0; x < 256; x++) {
            const uint8_t *b = rec + y * 1024 + x * 4;
            int pi = y * 256 + x;
            if (b[0] & 0x40) {
                for (int i = 0; i < ns; i++) {
                    int c = x - o_sx[i];
                    if (c < 0 || c > 7) continue;
                    if (nspr_of(pi) == 4) break;
                    Rec *s = spr_push(pi);
                    uint8_t a = o_attr[i];
                    s->idx = (o_lin[i] & 0xFFFFF) >> 4; s->offy = o_lin[i] & 7; s->offx = c;
                    s->hm = (a & 0x40) != 0; s->vm = (a & 0x80) != 0; s->bgp = (a & 0x20) != 0;
                    int q = 0x10 + 4 * (a & 3);
                    s->pal = pal[q + 3] | pal[q + 2] << 8 | pal[q + 1] << 16;
                    if (!legacy) s->pal |= 0xFF000000u;
                    s->fpv = 1; s->fp = game_ram ? o_fp[i] : 0;
                    s->sci = ((o_p1[i] >> c) & 1) | (((o_p2[i] >> c) & 1) << 1);
                }
            }
        }
    }
}

/* ---------------------------------------------------------------- pack lookups */
static int64_t fallback(int64_t idx) {
    if (idx >= 0 && idx < (int64_t)nfallback) return (int32_t)rd32(D + SEC[10] + 4 * idx);
    return -1;
}

static int64_t find_key(uint32_t pal, int kind, uint32_t lo, uint32_t hi) {
    uint8_t k[12];
    for (int i = 0; i < 4; i++) { k[i] = pal >> 8 * i; k[4 + i] = lo >> 8 * i; k[8 + i] = hi >> 8 * i; }
    uint32_t h = crc32b(k, 12) & (nbuckets - 1);
    for (uint32_t probe = 0; probe <= max_probe; probe++) {
        const uint8_t *b = D + SEC[0] + (uint64_t)((h + probe) & (nbuckets - 1)) * 64;
        for (int j = 0; j < 4; j++) {
            uint64_t q0 = rd64(b + j * 16), q1 = rd64(b + j * 16 + 8);
            if (!(q1 >> 63)) return -1;
            if ((uint32_t)q0 == pal && (uint32_t)(q0 >> 32) == lo && (uint32_t)q1 == hi
                && (int)((q1 >> 62) & 1) == kind)
                return (int64_t)((q1 >> 32) & 0x3FFFFFFF) * 8;
        }
    }
    return -1;
}

/* ---------------------------------------------------------------- per-frame memos */
static uint32_t G;        /* generation: bumped every iteration, so nothing carries between them */
static long st_fm_hit, st_gm_hit, st_gm_static, st_gm_dynamic;

/* 32-bit only: the A9 is a 32-bit core, and a 64x64 multiply costs several instructions */
static uint32_t mix(uint32_t pal, uint32_t lo, uint32_t hi, uint32_t k) {
    uint32_t h = lo * 0x9E3779B1u ^ hi * 0x85EBCA77u ^ pal * 0xC2B2AE3Du ^ k * 0x27D4EB2Fu;
    h ^= h >> 15; h *= 0x2C1B3C6Du; h ^= h >> 12;
    return h;
}

/* find_key memo: a pure function of the pack */
#define FM_N 16384
typedef struct { uint32_t pal, lo, hi, gen; int64_t off; uint8_t kind; } FM;
static FM *FMT; static uint32_t FMcount;
static int64_t find_key_m(uint32_t pal, int kind, uint32_t lo, uint32_t hi) {
    uint32_t h = mix(pal, lo, hi, kind);
    for (int i = 0; i < 32; i++) {
        FM *e = &FMT[(h + i) & (FM_N - 1)];
        if (e->gen != G) {
            int64_t off = find_key(pal, kind, lo, hi);
            if (FMcount < FM_N * 3 / 4) { e->gen = G; e->pal = pal; e->lo = lo; e->hi = hi; e->kind = kind; e->off = off; FMcount++; }
            return off;
        }
        if (e->pal == pal && e->lo == lo && e->hi == hi && e->kind == kind) { st_fm_hit++; return e->off; }
    }
    return find_key(pal, kind, lo, hi);
}

static int64_t find(uint32_t pal, const Rec *r) {
    if (game_ram) {
        if (!r->fpv) return -1;
        return find_key_m(pal, 1, (uint32_t)r->fp, (uint32_t)(r->fp >> 32));
    }
    if (r->idx == NOTILE) return -1;
    return find_key_m(pal, 0, (uint32_t)r->idx, 0);
}

/* is a rule list static? Pack property: kept across iterations */
#define CL_N 65536
typedef struct { uint32_t off; uint8_t used, flag; } CL;
static CL *CLT; static uint32_t CLcount;
static int clist_static(uint32_t off) {
    if (off == 0) return 1;
    const uint8_t *p = D + SEC[3] + off;
    for (;;) {
        uint32_t w = rd32(p); p += 4;
        uint64_t q0 = rd64(D + SEC[2] + 32 * (uint64_t)(w & 0xFFFFFF));
        if (!(((q0 >> 11) & 1) || (q0 & 0xFF) <= 2)) return 0;
        if (w >> 31) return 1;
    }
}
static int list_static(int64_t off) {
#ifdef MUT_MEMOALL   /* negative control: treat every list as static */
    (void)off; return 1;
#endif
    uint32_t h = (uint32_t)((uint64_t)off * 0x9E3779B97F4A7C15ull >> 40);
    for (int i = 0; i < 64; i++) {
        CL *e = &CLT[(h + i) & (CL_N - 1)];
        if (e->used && e->off == (uint32_t)off) return e->flag;
        if (!e->used) {
            const uint8_t *L = D + SEC[1] + off;
            uint32_t n = rd32(L); int s = 1;
            for (uint32_t k = 0; k < n && s; k++) {
                const uint8_t *w = L + 8 + 16 * k;
                s = clist_static(rd32(w + 4)) && clist_static(rd32(w + 8));
            }
            if (CLcount < CL_N * 3 / 4) { e->used = 1; e->off = (uint32_t)off; e->flag = s; CLcount++; }
            return s;
        }
    }
    return 0;
}

/* per-frame REDUCED rule lists. A condition of type 0-2 (memory, frame counter) has the same
   value at every pixel, so it can be evaluated once per frame, in any order. A rule that has
   such a condition evaluating false can never pass this frame and is dropped -- unless the rule
   also holds a frame-memoised condition of another type (bit 11, type > 2): that one takes its
   value from the FIRST pixel that evaluates it, so skipping the rule could move that first
   evaluation and change the memo. Dropped rules still OR their disableCache bit into the
   result, exactly as walking them would (dis_before for rules ahead of a kept one, tail for
   rules after the last). A kept rule with nothing pixel-dependent always passes, and ends the
   list. */
static int eval_cond(uint32_t ci, int x, int y, const Rec *rec);
typedef struct { uint32_t rule; uint8_t disb, always; } RE;
typedef struct { uint32_t off, gen, start, n; uint8_t tail; } RL;
#define RL_N 16384
static RL *RLT; static RE *REA; static uint32_t REn, REcap; static long st_rl_kept, st_rl_dropped;

static int cond_pure(uint64_t q0) { return (q0 & 0xFF) <= 2; }
/* 0 = clist fails on a pure condition, 1 = no pure failure; *dyn / *fdyn report what it holds */
static int clist_scan(uint32_t off, int *dyn, int *fdyn) {
    if (off == 0) return 1;
    const uint8_t *p = D + SEC[3] + off;
    int ok = 1;
    for (;;) {
        uint32_t w = rd32(p); p += 4;
        uint32_t ci = w & 0xFFFFFF;
        uint64_t q0 = rd64(D + SEC[2] + 32 * (uint64_t)ci);
        if (cond_pure(q0)) { if (ok && !eval_cond(ci, 0, 0, NULL)) ok = 0; }
        else { *dyn = 1; if ((q0 >> 11) & 1) *fdyn = 1; }
        if (w >> 31) return ok;
    }
}

static const RL *reduce(int64_t off) {
    uint32_t h = (uint32_t)((uint64_t)off * 0x9E3779B97F4A7C15ull >> 40);
    RL *slot = NULL;
    for (int i = 0; i < 64; i++) {
        RL *e = &RLT[(h + i) & (RL_N - 1)];
        if (e->gen != G) { slot = e; break; }
        if (e->off == (uint32_t)off) return e;
    }
    if (!slot) return NULL;
    slot->gen = G; slot->off = (uint32_t)off; slot->start = REn; slot->n = 0; slot->tail = 0;
    const uint8_t *L = D + SEC[1] + off;
    uint32_t n = rd32(L);
    uint8_t pend = 0;
    for (uint32_t k = 0; k < n; k++) {
        const uint8_t *w = L + 8 + 16 * k;
        uint8_t db = (rd32(w + 12) >> 24) & 1;
        int dyn = 0, fdyn = 0;
        int ok = clist_scan(rd32(w + 4), &dyn, &fdyn);
        ok = clist_scan(rd32(w + 8), &dyn, &fdyn) && ok;
        if (!ok && !fdyn) { pend |= db; st_rl_dropped++; continue; }
        if (REn == REcap) { REcap = REcap * 2 + 4096; REA = realloc(REA, REcap * sizeof(RE)); }
        REA[REn].rule = k; REA[REn].disb = pend; REA[REn].always = ok && !dyn;
        REn++; slot->n++; pend = 0; st_rl_kept++;
        if (ok && !dyn) break;      /* passes at every pixel: later rules are never reached */
    }
    slot->tail = pend;
    return slot;
}

/* get_matching memo: only entries whose list is static (or that found no list) */
#define GM_N 16384
typedef struct { uint32_t pal, lo, hi, gen; int64_t res; int32_t newidx; uint8_t kind, fpv, dis, mut; } GM;
static GM *GMT; static uint32_t GMcount;

/* ---------------------------------------------------------------- conditions */
static int op_eval(int op, uint64_t a, uint64_t b) {
    switch (op) {
    case 0: return a == b; case 1: return a != b; case 2: return a > b;
    case 3: return a < b; case 4: return a <= b; default: return a >= b;
    }
}

static int tmatch(uint64_t q0, uint64_t q2, uint64_t q3, const Rec *t) {
    uint32_t pal = (uint32_t)q3;
    int ignore = (q0 >> 9) & 1, data = (q0 >> 10) & 1;
    if (!data) {
        int64_t tile = (int64_t)q2;
        if (!(ignore || t->pal == pal)) return 0;
        return t->idx != NOTILE && (t->idx == tile || fallback(t->idx) == tile);
    }
    if (!t->fpv || t->idx == NOTILE) return 0;
    if (ignore) return t->fp == q2;
    return t->pal == pal && t->fp == q2;
}

static int in_screen(int64_t i) { return i >= 0 && i < 61440; }
static int tile_at_matches(uint64_t q0, uint64_t q2, uint64_t q3, int64_t i) {
    if (!in_screen(i)) return 0;
    Rec t; tile_rec((int)i, &t);
    return tmatch(q0, q2, q3, &t);
}
static int sprite_at_matches(uint64_t q0, uint64_t q2, uint64_t q3, int64_t i) {
    if (!in_screen(i)) return 0;
    int n = nspr_of((int)i);
    for (int k = 0; k < n; k++) if (tmatch(q0, q2, q3, spr_of((int)i, k))) return 1;
    return 0;
}

static int eval_cond(uint32_t ci, int x, int y, const Rec *rec) {
    const uint8_t *c = D + SEC[2] + 32 * (uint64_t)ci;
    uint64_t q0 = rd64(c), q1 = rd64(c + 8), q2 = rd64(c + 16), q3 = rd64(c + 24);
    int frame = (q0 >> 11) & 1;
    st_conds++;
#ifdef CSTATS   /* per-type evaluation counts: [type][frame-memoised hit?] */
    { extern long CST[16][2]; CST[q0 & 15][frame && MEMO[ci] >= 0]++; }
#endif
    if (frame && MEMO[ci] >= 0) return MEMO[ci];
    int t = q0 & 0xFF, op = (q0 >> 12) & 0xF, r = 0;
    uint32_t mask = (q0 >> 16) & 0xFF;
    switch (t) {
    case 0: r = op_eval(op, SNAP[q1 & 0xFF] & mask, SNAP[(q1 >> 8) & 0xFF] & mask); break;
    case 1: r = op_eval(op, SNAP[q1 & 0xFF] & mask, (q1 >> 8) & 0xFF); break;
    case 2: { uint32_t a = q1 & 0xFFFF, b = (q1 >> 16) & 0xFFFF; r = a != 0 && (FRAME % a) >= b; break; }
    case 3: r = tile_at_matches(q0, q2, q3, (int64_t)(q3 >> 32)); break;
    case 4: r = sprite_at_matches(q0, q2, q3, (int64_t)(q3 >> 32)); break;
    case 5: case 6: {
        int64_t X = (int32_t)(uint32_t)q1, Y = (int32_t)(uint32_t)(q1 >> 32);
#ifdef MUT_NEARBY   /* negative control: nearby offset off by one pixel */
        X += 1;
#endif
        if (t == 5) {
            r = tile_at_matches(q0, q2, q3, (y + Y) * 256 + x + X);
        } else {
            int64_t xs = (rec && rec->hm) ? -1 : 1, ys = (rec && rec->vm) ? -1 : 1;
            r = sprite_at_matches(q0, q2, q3, (y + Y * ys) * 256 + x + X * xs);
        }
        break;
    }
    case 7: case 8: case 9: case 10: {
        int64_t val;
        if (t == 7) val = x;
        else if (t == 8) val = y;
        else if (!rec) val = 0;
        else if (t == 9) val = rec->hm ? x - (7 - rec->offx) : x - rec->offx;
        else val = rec->vm ? y - (7 - rec->offy) : y - rec->offy;
        r = op_eval(op, (uint32_t)val, (uint32_t)q1);
        break;
    }
    case 11: r = rec && rec->hm; break;
    case 12: r = rec && rec->vm; break;
    case 13: r = rec && rec->bgp; break;
    default: fprintf(stderr, "condition type %d\n", t); exit(2);
    }
#ifndef MUT_NEGATE   /* negative control: ignore the negate bit */
    if ((q0 >> 8) & 1) r = !r;
#endif
    if (FEATOFF & feat_bit(t)) r = 0;
    if (frame) MEMO[ci] = (int8_t)r;
    return r;
}

/* walk a condition list (offset into section 3); 1 if all pass */
static int clist_pass(uint32_t off, int x, int y, const Rec *rec) {
    if (off == 0) return 1;
    const uint8_t *p = D + SEC[3] + off;
    for (;;) {
        uint32_t w = rd32(p); p += 4;
        if (!eval_cond(w & 0xFFFFFF, x, y, rec)) return 0;
        if (w >> 31) return 1;
    }
}

static int64_t get_matching_walk(int x, int y, Rec *r, int *dis, int *is_static);

/* returns payload, or -1 for no HD tile; *dis = disableCache */
static int64_t get_matching(int x, int y, Rec *r, int *dis) {
    uint32_t lo, hi; uint8_t kind = (uint8_t)game_ram;
    if (game_ram) { lo = (uint32_t)r->fp; hi = (uint32_t)(r->fp >> 32); }
    else { lo = (uint32_t)r->idx; hi = 0; }
    /* neighbouring pixels of one tile ask the same question: check the last memo hit first */
    static GM *last;
    if (last && last->gen == G && last->pal == r->pal && last->lo == lo && last->hi == hi
        && last->kind == kind && last->fpv == r->fpv) {
        st_gm_hit++;
        if (last->mut) set_idx(r, last->newidx);
        *dis = last->dis;
        return last->res;
    }
    uint32_t h = mix(r->pal, lo, hi, kind | (uint32_t)r->fpv << 1);
    GM *slot = NULL;
    for (int i = 0; i < 32; i++) {
        GM *e = &GMT[(h + i) & (GM_N - 1)];
        if (e->gen != G) { slot = e; break; }
        if (e->pal == r->pal && e->lo == lo && e->hi == hi && e->kind == kind && e->fpv == r->fpv) {
            st_gm_hit++;
            last = e;
            if (e->mut) set_idx(r, e->newidx);
            *dis = e->dis;
            return e->res;
        }
    }
    int32_t org = r->idx; int st;
    int64_t res = get_matching_walk(x, y, r, dis, &st);
    if (st) st_gm_static++; else st_gm_dynamic++;
    if (st && slot && GMcount < GM_N * 3 / 4) {
        slot->gen = G; slot->pal = r->pal; slot->lo = lo; slot->hi = hi; slot->kind = kind; slot->fpv = r->fpv;
        slot->res = res; slot->dis = (uint8_t)*dis; slot->mut = r->idx != org; slot->newidx = r->idx;
        GMcount++;
        last = slot;
    }
    return res;
}

/* the original get_matching body; *is_static = 1 if the answer is the same at every pixel */
static int64_t get_matching_walk(int x, int y, Rec *r, int *dis, int *is_static) {
    *is_static = 1;
    int64_t off = find(r->pal, r);
    if (off < 0) {
        int64_t f = game_ram ? -1 : fallback(r->idx);
        if (f >= 0) {
            int64_t org = r->idx;
            set_idx(r, (int32_t)f);
            off = find(r->pal, r);
            if (off < 0) off = find(0xFFFFFFFFu, r);
            if (off < 0) set_idx(r, (int32_t)org); else st_fb++;
        }
        if (off < 0) off = find(0xFFFFFFFFu, r);
    }
    *dis = 0;
    if (off < 0) return -1;
    *is_static = list_static(off);
    const uint8_t *L = D + SEC[1] + off;
#ifndef NO_REDUCE
    const RL *rl = reduce(off);
    if (rl) {
        if (rl->n == 0 || REA[rl->start].always) *is_static = 1;
        for (uint32_t i = 0; i < rl->n; i++) {
            const RE *e = &REA[rl->start + i];
            const uint8_t *w = L + 8 + 16 * e->rule;
            st_rules++;
            if (e->disb) *dis = 1;
            if ((rd32(w + 12) >> 24) & 1) *dis = 1;
            if (e->always || (clist_pass(rd32(w + 4), x, y, r) && clist_pass(rd32(w + 8), x, y, r)))
                return rd32(w);
        }
        if (rl->tail) *dis = 1;
        return -1;
    }
#endif
    uint32_t n = rd32(L);
    for (uint32_t i = 0; i < n; i++) {
        const uint8_t *w = L + 8 + 16 * i;
        st_rules++;
        if ((rd32(w + 12) >> 24) & 1) *dis = 1;
        if (clist_pass(rd32(w + 4), x, y, r) && clist_pass(rd32(w + 8), x, y, r))
            return rd32(w);
    }
    return -1;
}

/* ---------------------------------------------------------------- backgrounds */
static int cmp_u32(const void *a, const void *b) {
    uint32_t x = *(const uint32_t *)a, y = *(const uint32_t *)b; return x < y ? -1 : x > y;
}
static int bg_candidates(uint32_t ioff, uint32_t *out, int max) {
    const uint8_t *base = D + SEC[13] + ioff;
    uint32_t nsig = rd32(base); int n = 0;
    for (uint32_t k = 0; k < nsig; k++) {
        const uint8_t *p = base + 4 + 48 * k;
        int nterms = p[0];
        uint8_t vals[16] = {0};
        for (int j = 0; j < nterms; j++) vals[j] = SNAP[p[2 + 2 * j]] & p[3 + 2 * j];
        uint32_t toff = rd32(p + 34), nb = rd32(p + 38), maxp = rd32(p + 42);
        uint32_t h = crc32b(vals, 16) & (nb - 1);
        for (uint32_t probe = 0; probe <= maxp; probe++) {
            const uint8_t *e = D + SEC[13] + toff + 32 * (uint64_t)((h + probe) & (nb - 1));
            uint32_t lst = rd32(e + 16), cnt = rd32(e + 20), valid = rd32(e + 24);
            if (!valid) break;
            if (!memcmp(e, vals, 16)) {
                for (uint32_t i = 0; i < cnt && n < max; i++) out[n++] = rd32(D + SEC[13] + lst + 4 * i);
                break;
            }
        }
    }
    qsort(out, n, 4, cmp_u32);
    int u = 0;
    for (int i = 0; i < n; i++) if (!u || out[u - 1] != out[i]) out[u++] = out[i];
    return u;
}

/* ---------------------------------------------------------------- output */
static char *OB; static size_t OBn, OBcap; static int OUT_ON;
static void outf(const char *fmt, ...) __attribute__((format(printf, 1, 2)));
#include <stdarg.h>
static void outf(const char *fmt, ...) {
    if (!OUT_ON) return;
    if (OBcap - OBn < 512) { OBcap = OBcap * 2 + 65536; OB = realloc(OB, OBcap); }
    va_list ap; va_start(ap, fmt);
    OBn += vsnprintf(OB + OBn, OBcap - OBn, fmt, ap);
    va_end(ap);
}

static int select_levels(void) {
    static uint32_t cand[65536];
    int hits = 0;
    if (FEATOFF & 32) return 0;
    for (int lvl = 0; lvl < 40; lvl++) {
        uint32_t roff = rd32(D + SEC[5] + lvl * 8), ioff = rd32(D + SEC[5] + lvl * 8 + 4);
        if (roff == 0) continue;
        const uint8_t *L = D + SEC[1] + roff;
        uint32_t n = rd32(L);
        int nc = ioff ? bg_candidates(ioff, cand, 65536) : (int)n;
        for (int i = 0; i < nc; i++) {
            uint32_t e = ioff ? cand[i] : (uint32_t)i;
            const uint8_t *w = L + 8 + 16 * e;
            if (clist_pass(rd32(w + 4), 0, 0, NULL)) {
                outf("L %d %x\n", lvl, rd32(w));
                hits++;
                break;
            }
        }
    }
    return hits;
}

/* ---------------------------------------------------------------- additions */
typedef struct { uint32_t opal, apal, ignore; int64_t oidx, aidx; uint64_t ofp, afp; int32_t ox, oy; } Add;
static Add *ADDS;
static int has_fb;
/* additions_for cache: open addressing on (pal, key, keytype) */
typedef struct { uint32_t pal, gen; uint8_t isnone; uint64_t key; int start, n; } AC;
static AC *ACT; static int ACTn; static int *ACL; static int ACLn, ACLcap;

static void add_cache_reset(void) {
    if (!ACT) { ACTn = 1 << 16; ACT = calloc(ACTn, sizeof(AC)); }
    ACLn = 0;   /* entries are live only when gen == G */
}

/* additions sorted by original body (tile index, or fingerprint for CHR-RAM games), then by
   index: every addition additions_for can take has body == the record's body or, through a
   fallback, == fallback(record's tile) */
typedef struct { uint64_t body; uint32_t a; } AX;
static AX *AXT;
static int cmp_ax(const void *p, const void *q) {
    const AX *a = p, *b = q;
    if (a->body != b->body) return a->body < b->body ? -1 : 1;
    return a->a < b->a ? -1 : a->a > b->a;
}
static void ax_range(uint64_t body, uint32_t *lo, uint32_t *hi) {
    uint32_t l = 0, h = nadd;
    while (l < h) { uint32_t m = (l + h) / 2; if (AXT[m].body < body) l = m + 1; else h = m; }
    *lo = l; h = nadd;
    while (l < h) { uint32_t m = (l + h) / 2; if (AXT[m].body <= body) l = m + 1; else h = m; }
    *hi = l;
}

static int key_eq(const Rec *r, uint32_t pal, int64_t idx, uint64_t fp) {
    if (game_ram) return r->fpv && r->pal == pal && r->fp == fp;
    return r->idx == idx && r->pal == pal;
}
static int body_eq(const Rec *r, int64_t idx, uint64_t fp) {
    if (game_ram) return r->fpv && r->fp == fp;
    return r->idx == idx;
}

static const int *additions_for(const Rec *r, int *cnt) {
    uint64_t key = game_ram ? r->fp : (uint64_t)(int64_t)r->idx;
    uint8_t isnone = game_ram && !r->fpv;
    uint32_t h = (uint32_t)(key * 0x9E3779B97F4A7C15ull >> 40) ^ r->pal * 2654435761u;
    for (int i = 0;; i++) {
        AC *e = &ACT[(h + i) & (ACTn - 1)];
        if (e->gen != G) {
            e->gen = G; e->pal = r->pal; e->key = key; e->isnone = isnone; e->start = ACLn; e->n = 0;
            int check_fb = !game_ram && has_fb;
            /* candidates: body == key, plus body == fallback(key); merged in index order */
            uint32_t l1, h1, l2 = 0, h2 = 0;
            ax_range(key, &l1, &h1);
            if (check_fb && r->idx != NOTILE) {
                int64_t f = fallback(r->idx);
                if ((uint64_t)f != key) ax_range((uint64_t)f, &l2, &h2);
            }
            while (l1 < h1 || l2 < h2) {
                uint32_t a;
                if (l2 >= h2 || (l1 < h1 && AXT[l1].a < AXT[l2].a)) a = AXT[l1++].a; else a = AXT[l2++].a;
                const Add *A = &ADDS[a];
                int take = 0;
                if (!A->ignore && key_eq(r, A->opal, A->oidx, A->ofp)) take = 1;
                else if (A->ignore && body_eq(r, A->oidx, A->ofp)) take = 1;
                else if (check_fb && (A->ignore || r->pal == A->opal) && r->idx != NOTILE
                         && fallback(r->idx) == A->oidx) take = 1;
                if (take) {
                    if (ACLn == ACLcap) { ACLcap = ACLcap * 2 + 1024; ACL = realloc(ACL, ACLcap * sizeof(int)); }
                    ACL[ACLn++] = a; e->n++;
                }
            }
            *cnt = e->n; return ACL + e->start;
        }
        if (e->pal == r->pal && e->key == key && e->isnone == isnone) { *cnt = e->n; return ACL + e->start; }
        if (i >= ACTn) { fprintf(stderr, "additions cache full\n"); exit(2); }
    }
}

static int draw_additions(int x, int y, const Rec *r) {
    int n; const int *lst = additions_for(r, &n);
    for (int i = 0; i < n; i++) {
        const Add *A = &ADDS[lst[i]];
        int tx = x + (r->hm ? -A->ox : A->ox), ty = y + (r->vm ? -A->oy : A->oy);
        if (tx >= 0 && tx < 256 && ty >= 0 && ty < 240) {
            int pi = (ty << 8) | tx;
            if (nspr_of(pi) < 4) {
                Rec nr = *r;
                nr.sci = 0; nr.idx = (int32_t)A->aidx; nr.pal = A->apal; nr.fp = A->afp; nr.fpv = 1;
                *spr_push(pi) = nr;
                st_add++;
            }
        }
    }
    return n > 0;
}

static int scroll_y(uint16_t t) { return (((t & 0x3E0) >> 2) | ((t & 0x7000) >> 12)) + ((t & 0x800) ? 240 : 0); }

static void process_additions(void) {
#ifdef MUT_NOADD   /* negative control: no additions */
    return;
#endif
    if (!nadd || (FEATOFF & 16)) return;
    int yscroll = scroll_y(line_t(0)); uint16_t tmpv = line_t(0); int process_bg = 1;
    for (int y = 0; y < 240; y++) {
        if (y) {
            /* the original copies the whole pixel over pixel (0,0), sprites included: point
               (0,0) at line y, and give it its own copy of that pixel's sprite block, so a later
               addition to (0,0) cannot change line y's first pixel through an alias. No tile
               rewrite can exist yet (those happen in lookups), so the overlay needs no copy. */
#ifndef MUT_NOP0   /* negative control: (0,0) keeps showing line 0 */
            P0L = y;
#endif
            int src = y << 8;
            SBI[0] = 0;
            if (SBI[src]) { SBI[0] = (uint16_t)++SBn; SB[SBn] = SB[SBI[src]]; }
        }
        uint16_t lt = line_t(0);
        if (((yscroll + y) & 7) == 0 || tmpv != lt) { yscroll = scroll_y(lt); tmpv = lt; process_bg = 1; }
        int dobg = process_bg;
        if (process_bg) process_bg = 0;
        for (int x = 0; x < 256; x++) {
            int pi = (y << 8) | x;
            for (int i = 0; i < nspr_of(pi); i++) { Rec r = *spr_of(pi, i); draw_additions(x, y, &r); }
            if (dobg) {
                Rec t; tile_rec(pi, &t);
                if (draw_additions(x, y, &t)) process_bg = 1;
            }
        }
    }
}

/* ---------------------------------------------------------------- the decision pass */
static void outv(int64_t v) { if (v < 0) outf(" -"); else outf(" %llx", (unsigned long long)v); }

static void lookups(void) {
    int top = overscan[0] > 0 ? overscan[0] : 0, right = overscan[1] > 0 ? overscan[1] : 0;
    int bottom = overscan[2] > 0 ? overscan[2] : 0, left = overscan[3] > 0 ? overscan[3] : 0;
    for (int y = top; y < 240 - bottom; y++) {
        int fl = y == 0 ? P0L : y;        /* (0,0) may show another line's first pixel */
        uint16_t ft = LT[fl];
        int scroll_x = ((ft & 0x1F) << 3) | LFX[fl] | ((ft & 0x400) ? 256 : 0);
        int use_cached = 0; int64_t cached = -1;
        for (int x = left; x < 256 - right; x++) {
            int pi = (y << 8) | x;
            int any = 0, dis;
            Rec t; tile_rec(pi, &t);
            if (t.idx != NOTILE) {
                int64_t hd;
                if (((scroll_x + x) & 7) == 0) use_cached = 0;
                if (use_cached) hd = cached;
                else {
                    CUR_PIX = pi;
                    hd = get_matching(x, y, &t, &dis);
                    CUR_PIX = -1;
                    if (!dis && cache_enabled) { cached = hd; use_cached = 1; }
                }
                outf("P %d %d B", y, x); any = 1; outv(hd);
            }
            int lowest = 999;
            int ns = nspr_of(pi);
            for (int k = ns - 1; k >= 0; k--) {
                Rec *s = spr_of(pi, k);
                if (s->bgp) {
                    if (s->sci) lowest = k;
                    int64_t v = get_matching(x, y, s, &dis);
                    if (!any) { outf("P %d %d", y, x); any = 1; }
                    outf(" S%d", k); outv(v);
                }
            }
            for (int k = ns - 1; k >= 0; k--) {
                Rec *s = spr_of(pi, k);
                if (!s->bgp && lowest > k) {
                    int64_t v = get_matching(x, y, s, &dis);
                    if (!any) { outf("P %d %d", y, x); any = 1; }
                    outf(" S%d", k); outv(v);
                }
            }
            if (any) outf("\n");
        }
    }
}

/* ---------------------------------------------------------------- files */
static uint8_t *load(const char *path, size_t *len) {
#ifdef _WIN32
    FILE *f = fopen(path, "rb"); if (!f) { perror(path); exit(1); }
    fseek(f, 0, SEEK_END); *len = ftell(f); fseek(f, 0, SEEK_SET);
    uint8_t *b = malloc(*len); if (fread(b, 1, *len, f) != *len) { perror(path); exit(1); }
    fclose(f); return b;
#else
    /* plain read: simplest, and loading is outside the timed region. (An earlier mmap version
       "failed" only because fstat had failed and left the size 0; see _FILE_OFFSET_BITS.) */
    int fd = open(path, O_RDONLY); if (fd < 0) { perror(path); exit(1); }
    struct stat st;
    if (fstat(fd, &st) != 0) { perror(path); exit(1); }
    *len = (size_t)st.st_size;
    uint8_t *b = malloc(*len ? *len : 1);
    if (!b) { perror("malloc"); exit(1); }
    size_t got = 0;
    while (got < *len) {
        ssize_t k = read(fd, b + got, *len - got);
        if (k <= 0) { perror(path); exit(1); }
        got += (size_t)k;
    }
    close(fd); return b;
#endif
}

static double now(void) {
    struct timespec ts; clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec + ts.tv_nsec * 1e-9;
}
static int cmp_d(const void *a, const void *b) {
    double x = *(const double *)a, y = *(const double *)b; return x < y ? -1 : x > y;
}

int main(int argc, char **argv) {
    if (argc < 4) { fprintf(stderr, "usage: hdarm PACK.hdp REC.bin WATCH.bin [--delta D] [--iters N] [--out F]\n"); return 2; }
    { const char *e = getenv("HD_FEATOFF"); FEATOFF = e ? (unsigned)strtoul(e, NULL, 0) : 0; }
    int delta = 0, iters = 1; const char *outp = NULL;
    for (int i = 4; i < argc; i++) {
        if (!strcmp(argv[i], "--delta") && i + 1 < argc) delta = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--iters") && i + 1 < argc) iters = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--out") && i + 1 < argc) outp = argv[++i];
        else { fprintf(stderr, "bad arg %s\n", argv[i]); return 2; }
    }
    crc_init();
    size_t dl, rl, wl;
    D = load(argv[1], &dl);
    const uint8_t *rec = load(argv[2], &rl);
    const uint8_t *wat = load(argv[3], &wl);
    if (memcmp(D, "NHDP", 4) || (D[4] | D[5] << 8) != 3) {
        fprintf(stderr, "not a format-3 .hdp (%zu bytes, starts %02x %02x %02x %02x %02x %02x)\n",
                dl, D[0], D[1], D[2], D[3], D[4], D[5]);
        return 1;
    }
    if (rl < 0xF0008) { fprintf(stderr, "short frame record\n"); return 1; }
    H_flags = D[7]; H_options = rd32(D + 12);
    for (int i = 0; i < 4; i++) overscan[i] = (int32_t)rd32(D + 0x10 + 4 * i);
    nbuckets = rd32(D + 0x24); max_probe = rd32(D + 0x28); nconds = rd32(D + 0x2C);
    nwatched = rd32(D + 0x34); nadd = rd32(D + 0x40); nfallback = rd32(D + 0x44);
    for (int i = 0; i < 18; i++) SEC[i] = rd32(D + 0x80 + 8 * i);
    legacy = H_flags & 1;
    if (!(H_flags & 0x20)) { fprintf(stderr, "pack does not say whether the game is CHR-RAM\n"); return 1; }
    game_ram = (H_flags & 0x10) != 0;
    cache_enabled = (H_options & 8) == 0;
    /* watch snapshot, indexed by the pack's slot numbers */
    if (memcmp(wat, "NWAT", 4)) { fprintf(stderr, "watch file: bad magic\n"); return 1; }
    uint32_t wn = rd32(wat + 4);
    if (nwatched) {
        if (wn != nwatched) { fprintf(stderr, "watch list differs\n"); return 1; }
        for (uint32_t i = 0; i < wn; i++)
            if (rd32(wat + 8 + 4 * i) != rd32(D + SEC[9] + 4 * i)) { fprintf(stderr, "watch list differs\n"); return 1; }
        memcpy(SNAP, wat + 8 + 4 * wn, wn > 256 ? 256 : wn);
    }
    has_fb = 0;
    for (uint32_t i = 0; i < nfallback; i++) if ((int32_t)rd32(D + SEC[10] + 4 * i) >= 0) { has_fb = 1; break; }
    ADDS = calloc(nadd ? nadd : 1, sizeof(Add));
    for (uint32_t i = 0; i < nadd; i++) {
        const uint8_t *a = D + SEC[11] + 64 * (uint64_t)i;
        uint32_t okind = rd32(a + 4), akind = rd32(a + 20);
        uint64_t obody = rd64(a + 8), abody = rd64(a + 24);
        ADDS[i].opal = rd32(a); ADDS[i].oidx = okind == 0 ? (int64_t)obody : NOTILE; ADDS[i].ofp = okind == 1 ? obody : 0;
        ADDS[i].apal = rd32(a + 16); ADDS[i].aidx = akind == 0 ? (int64_t)abody : NOTILE; ADDS[i].afp = akind == 1 ? abody : 0;
        ADDS[i].ox = (int32_t)rd32(a + 32); ADDS[i].oy = (int32_t)rd32(a + 36); ADDS[i].ignore = rd32(a + 40) & 1;
        if (akind == 0 && (ADDS[i].aidx < INT32_MIN || ADDS[i].aidx > INT32_MAX)) {
            fprintf(stderr, "addition %u: tile index does not fit 32 bits\n", i); return 1;
        }
    }
    AXT = calloc(nadd ? nadd : 1, sizeof(AX));
    for (uint32_t i = 0; i < nadd; i++) {
        AXT[i].body = game_ram ? ADDS[i].ofp : (uint64_t)ADDS[i].oidx; AXT[i].a = i;
    }
    qsort(AXT, nadd, sizeof(AX), cmp_ax);
    SBI = malloc(61440 * sizeof(uint16_t));
    SB = malloc(sizeof(SBlk) * (61440 + 256 + 2));   /* every pixel, plus one copy per line */
    FMT = calloc(FM_N, sizeof(FM)); GMT = calloc(GM_N, sizeof(GM)); CLT = calloc(CL_N, sizeof(CL));
    RLT = calloc(RL_N, sizeof(RL));
    MEMO = malloc(nconds ? nconds : 1);

    double *tb = calloc(iters, sizeof(double)), *tl = calloc(iters, sizeof(double)),
           *ta = calloc(iters, sizeof(double)), *tk = calloc(iters, sizeof(double)),
           *tt = calloc(iters, sizeof(double));
    long r_rules = 0, r_conds = 0, r_fb = 0, r_add = 0;
    for (int it = 0; it < iters; it++) {
        OUT_ON = (it == 0 && outp != NULL); OBn = 0;
        st_rules = st_conds = st_fb = st_add = 0;
        st_fm_hit = st_gm_hit = st_gm_static = st_gm_dynamic = 0;
        double t0 = now();
        G++; FMcount = GMcount = 0; SBn = 0; REn = 0; st_rl_kept = st_rl_dropped = 0;
        FRAME = (uint32_t)(rd64(rec + 0xF0000) & 0xFFFFFFFF) + delta;
        memset(MEMO, 0xFF, nconds ? nconds : 1);
        add_cache_reset();
        build_records(rec);
        double t1 = now();
        outf("F %u\n", FRAME);
        select_levels();
        double t2 = now();
        process_additions();
        double t3 = now();
        lookups();
        double t4 = now();
        tb[it] = t1 - t0; tl[it] = t2 - t1; ta[it] = t3 - t2; tk[it] = t4 - t3; tt[it] = t4 - t0;
        if (it == 0) { r_rules = st_rules; r_conds = st_conds; r_fb = st_fb; r_add = st_add; }
        if (it == iters - 1)
            fprintf(stderr, "memo find_hits %ld match_hits %ld walked_static %ld walked_dynamic %ld sprite_blocks %u"
                    " reduced_kept %ld reduced_dropped %ld\n",
                    st_fm_hit, st_gm_hit, st_gm_static, st_gm_dynamic, SBn, st_rl_kept, st_rl_dropped);
        if (OUT_ON) {
            FILE *f = fopen(outp, "wb"); if (!f) { perror(outp); return 1; }
            fwrite(OB, 1, OBn, f); fclose(f);
        }
    }
    fprintf(stderr, "rules_walked %ld conds_evaluated %ld fallback_hits %ld additions %ld\n",
            r_rules, r_conds, r_fb, r_add);
#ifdef CSTATS
    { extern long CST[16][2];
      for (int t = 0; t < 16; t++) if (CST[t][0] || CST[t][1])
          fprintf(stderr, "cond type %2d evaluated %ld memo-hit %ld\n", t, CST[t][0], CST[t][1]); }
#endif
    if (iters > 1) {
        double *v[5] = {tb, tl, ta, tk, tt}; const char *nm[5] = {"records", "levels", "additions", "lookups", "TOTAL"};
        for (int k = 0; k < 5; k++) {
            qsort(v[k], iters, sizeof(double), cmp_d);
            fprintf(stderr, "%-10s min %7.3f ms  median %7.3f ms  max %7.3f ms\n", nm[k],
                    v[k][0] * 1e3, v[k][iters / 2] * 1e3, v[k][iters - 1] * 1e3);
        }
    }
    return 0;
}
