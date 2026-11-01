"""hd3_fmap unit test: build the tap stream tb_fmap.exe drives, and check its map dumps.

    python gen_fmap_stream.py gen <stream.bin> <rec_a.bin> <rec_b.bin> <seed>
    python gen_fmap_stream.py check <stream.bin> <rec_a.bin> <rec_b.bin> <seed> <dump_prefix>

hd3_fmap fills its maps by snooping the capture writer's record stream (hd_capture.sv), so the
test drives that stream and nothing else. The expected maps come from an independent model: the
two 1 MiB record buffers as bytes, every write applied with its byte enables, and the maps read
out of those bytes the way the record layout defines them (HDPACK_DESIGN.md "Frame record"):
  pixel map    y*128 + x/2 -> {pixel x|1 byte 0 [6:0], pixel x&~1 byte 0 [6:0]}
  line table   y -> {min(fetches, 16), min(spans, 34)} from header q0 (spans [39:32], fetches [55:48])
  sprite table y, fetch i < 16 -> {valid 54, attr bit 5 (51), X [45:38], [15:8], [7:0]} of qword A
A word the writer never stores is stale in the buffer and must be stale in the map too, so the
stream deliberately leaves sprite slots unwritten and the model keeps whatever they held.

Phases (a map dump after each, of BOTH banks):
  1  bank 0 from rec_a and bank 1 from rec_b, every qword of the pixel area and every line block
     written whole (defines every entry; checks the banks are kept apart)
  2  bank 0 from random bytes, the writer's shapes: pixel halves with byte enables 0000 (no even
     pixel), 0001 (branch B), 1111 and random; q0 with 0xF8 (x = 0 was branch B) or 0xFF; a random
     number of sprite fetches per line, the rest left stale; spans, palette qwords, the trailer;
     header counts at and past both caps; repeated writes to one address
  3  bank 1 the same with another seed
  4  bank 0 again (stale-versus-fresh against phase 2's contents)
Interleaved everywhere: idle clocks carrying random address/data/enables with tap_v = 0, and
writes the map must ignore - below the record buffers, past them (2 MiB up, an alias of bank 0's
pixels if in_rec were not checked), between the pixel area and the line blocks, line blocks of
y 240..255, and past the line blocks (the trailer, an alias of line 96 if t_l[16] were not checked).

Stream records (24 bytes): u32 op, u32 a, u64 d, u32 be, u32 pad
  op 0 write (a = qword address, d, be)   op 1 idle (a = clocks, d/be = noise)   op 2 dump (a = n)
"""
import random
import struct
import sys

REC_BASE = 0xC000000
QB = REC_BASE >> 3
BUF_Q = 0x20000                      # qwords per 1 MiB buffer
HDR_Q = 0x40000 >> 3                 # line blocks start


def rec_q(rec, q):
    return struct.unpack_from("<Q", rec, q * 8)[0]


class Gen:
    def __init__(self, seed):
        self.r = random.Random(seed)
        self.ops = []
        self.bufs = [bytearray(0x100000), bytearray(0x100000)]
        self.ndump = 0

    def write(self, bank, q, d, be, apply=True):
        self.ops.append((0, QB + bank * BUF_Q + q, d, be))
        if apply:
            b = self.bufs[bank]
            for i in range(8):
                if be >> i & 1:
                    b[q * 8 + i] = d >> (8 * i) & 0xFF

    def raw(self, qaddr, d, be):        # a write the map must ignore (outside the buffers)
        self.ops.append((0, qaddr & 0x1FFFFFF, d, be))

    def idle(self, n):
        r = self.r
        self.ops.append((1, n, r.getrandbits(64), r.getrandbits(8)))

    def maybe_idle(self, p=0.05):
        if self.r.random() < p:
            self.idle(self.r.randint(1, 6))

    def dump(self):
        self.ops.append((2, self.ndump, 0, 0))
        exp = self.expected()
        self.ndump += 1
        return exp

    def expected(self):
        out = {}
        for bank in (0, 1):
            rec = self.bufs[bank]
            for y in range(240):
                for xp in range(128):
                    e = rec[y * 1024 + 2 * xp * 4] & 0x7F
                    o = rec[y * 1024 + (2 * xp + 1) * 4] & 0x7F
                    out[("P", bank, y * 128 + xp)] = (o << 7) | e
                h = 0x40000 + y * 2048
                q0 = struct.unpack_from("<Q", rec, h)[0]
                spans, fet = (q0 >> 32) & 0xFF, (q0 >> 48) & 0xFF
                out[("L", bank, y)] = (min(fet, 16) << 6) | min(spans, 34)
                for i in range(16):
                    qa = struct.unpack_from("<Q", rec, h + 640 + 16 * i)[0]
                    out[("S", bank, y, i)] = ((qa >> 54 & 1) << 25) | ((qa >> 51 & 1) << 24) | \
                        ((qa >> 38 & 0xFF) << 16) | ((qa >> 8 & 0xFF) << 8) | (qa & 0xFF)
        return out

    # -- phases --
    def full(self, bank, rec):
        for y in range(240):
            for q in range(128):
                self.write(bank, y * 128 + q, rec_q(rec, y * 128 + q), 0xFF)
            for k in range(256):
                q = HDR_Q + y * 256 + k
                self.write(bank, q, rec_q(rec, q), 0xFF)
            self.maybe_idle(0.2)

    def junk(self, bank):
        r = self.r
        for _ in range(r.randint(1, 3)):
            kind = r.randrange(5)
            d, be = r.getrandbits(64), r.getrandbits(8) | 1
            if kind == 0:                                   # below the buffers
                self.raw(QB - r.randint(1, 0x80000), d, be)
            elif kind == 1:                                 # 2 MiB+ up: would alias pixels
                self.raw(QB + 0x40000 * r.randint(1, 3) + r.randrange(240 * 128), d, be)
            elif kind == 2:                                 # gap between pixels and line blocks
                self.write(bank, r.randrange(0x7800, 0x8000), d, be)
            elif kind == 3:                                 # line blocks of y 240..255
                self.write(bank, HDR_Q + r.randint(240, 255) * 256 + r.randrange(256), d, be)
            else:                                           # past the line blocks
                self.write(bank, r.randrange(0x18000, BUF_Q), d, be)

    def partial(self, bank):
        r = self.r
        boundary = {3: (16, 34), 4: (17, 35), 5: (0, 0), 6: (255, 255), 7: (15, 33)}
        for y in range(240):
            for q in range(128):
                be = 0
                for half in (0, 4):
                    c = r.random()
                    nib = 0x0 if c < 0.15 else 0x1 if c < 0.3 else 0xF if c < 0.85 else r.getrandbits(4)
                    be |= nib << half
                d = r.getrandbits(64)
                self.write(bank, y * 128 + q, d, be)
                if r.random() < 0.01:                       # rewritten: last write wins
                    self.write(bank, y * 128 + q, r.getrandbits(64), r.getrandbits(8))
                self.maybe_idle(0.01)
            hq = HDR_Q + y * 256
            q0 = r.getrandbits(64)
            if y in boundary:
                fet, sp = boundary[y]
                q0 = (q0 & ~(0xFF << 48) & ~(0xFF << 32)) | (fet << 48) | (sp << 32)
            self.write(bank, hq, q0, 0xF8 if r.random() < 0.3 else 0xFF)
            for k in (1, 2, 3):
                self.write(bank, hq + k, r.getrandbits(64), 0xFF)
            for s in range(r.randint(0, 34)):
                self.write(bank, hq + 8 + 2 * s, r.getrandbits(64), 0xFF)
                self.write(bank, hq + 9 + 2 * s, r.getrandbits(64), 0xFF)
            nf = r.choice([0, 0, 3, 8, 15, 16, 20, 40, 64])
            for i in range(nf):
                self.write(bank, hq + 80 + 2 * i, r.getrandbits(64), 0xFF)
                self.write(bank, hq + 81 + 2 * i, r.getrandbits(64), 0xFF)
            self.junk(bank)
            self.maybe_idle(0.1)
        self.write(bank, 0xF0000 >> 3, r.getrandbits(64), 0xFF)    # trailer


def build(seed, rec_a, rec_b):
    g = Gen(seed)
    exps = []
    g.full(0, rec_a)
    g.full(1, rec_b)
    exps.append(g.dump())
    g.partial(0)
    exps.append(g.dump())
    g.partial(1)
    exps.append(g.dump())
    g.partial(0)
    exps.append(g.dump())
    return g, exps


def load(path):
    rec = open(path, "rb").read()
    if len(rec) < 0x100000:
        sys.exit(f"{path}: not a 1 MiB record")
    return rec


def read_dump(path):
    got = {}
    for line in open(path):
        f = line.split()
        if not f or f[0] == "#":
            continue
        if f[0] == "S":
            got[("S", int(f[1]), int(f[2]), int(f[3]))] = int(f[4], 16)
        else:
            got[(f[0], int(f[1]), int(f[2]))] = int(f[3], 16)
    return got


def main():
    if len(sys.argv) < 6 or sys.argv[1] not in ("gen", "check"):
        print(__doc__)
        return 2
    mode, stream, ra, rb, seed = sys.argv[1:6]
    g, exps = build(int(seed), load(ra), load(rb))
    if mode == "gen":
        with open(stream, "wb") as f:
            for op, a, d, be in g.ops:
                f.write(struct.pack("<IIQII", op, a, d, be, 0))
        print(f"{stream}: {len(g.ops)} records, {g.ndump} dumps")
        return 0
    prefix = sys.argv[6]
    bad = 0
    for n, exp in enumerate(exps):
        try:
            got = read_dump(f"{prefix}_{n}.txt")
        except OSError as e:
            print(f"dump {n}: {e}")
            return 1
        if set(got) != set(exp):
            print(f"dump {n}: {len(got)} entries dumped, {len(exp)} expected")
            bad += 1
            continue
        diff = [k for k in exp if exp[k] != got[k]]
        for k in diff[:5]:
            print(f"dump {n} {k}: got {got[k]:x} want {exp[k]:x}")
        if diff:
            kinds = {}
            for k in diff:
                kinds[(k[0], k[1])] = kinds.get((k[0], k[1]), 0) + 1
            print(f"dump {n}: {len(diff)} of {len(exp)} entries differ {kinds}")
        bad += len(diff)
    print("PASS" if not bad else "FAIL")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
