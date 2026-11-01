"""overlay_case.py - a hand-built frame that reaches hdarm3's tile-rewrite overlay.

overlay_reach.py finds exactly one condition in the corpus the overlay can change: in the four
a033 Metroid packs, a tileNearby test "background tile 8 rows up is 5873" (offset (0,-8),
palette ignored), read from the rule lists of tiles 3750 / 4006, which those tiles only reach
as SPRITES on palette ff153429. Background tile 5873 has keys only for 0f201000 / 0f281604 /
0f28191a, so on palette 0f271107 it misses, falls back to 1265 (which has a 0f271107 key), and
the record keeps index 1265 - so when the sprite 8 rows below tests "tile is 5873", Mesen
answers NO. Without the overlay (MUT_NOWT) hdarm3 still sees 5873 and answers YES.

This writes that frame on top of a recorded one (palette RAM set on a band of lines, every
background span made tile 5873 on palette 3, one tile-4006 sprite per line), then compares:
    reference  hdref_decisions.py      (the Python port of Mesen)
    exact      hdarm3                  must EQUAL the reference
    NOWT       hdarm3 -DMUT_NOWT       must DIFFER from it
usage: python overlay_case.py PACK.hdp RECDIR FRAME EXACT.exe NOWT.exe WORKDIR [--tile 4006]
"""
import argparse, os, shutil, struct, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
Y0, Y1, SX = 40, 200, 100


def set_pal(rec, h, n, v):
    """6-bit palette entry n of a line header (packed LSB-first from byte 8)."""
    bit = 6 * n
    for k in range(6):
        b, s = 8 + (bit + k) // 8, (bit + k) % 8
        rec[h + b] = (rec[h + b] & ~(1 << s)) | (((v >> k) & 1) << s)


def build(src, tile):
    rec = bytearray(src)
    for y in range(Y0, Y1):
        h = 0x40000 + y * 2048
        q0 = struct.unpack_from('<Q', rec, h)[0]
        nspan = min((q0 >> 32) & 0xFF, 34)
        # universal background 0x0f; background palette 3 = 27 11 07 -> pal 0f271107
        set_pal(rec, h, 0, 0x0F)
        for n, v in ((13, 0x27), (14, 0x11), (15, 0x07)):
            set_pal(rec, h, n, v)
        # sprite palette 0 = 15 34 29 -> pal ff153429
        for n, v in ((0x11, 0x15), (0x12, 0x34), (0x13, 0x29)):
            set_pal(rec, h, n, v)
        for s in range(nspan):
            o = h + 64 + s * 16
            qa = struct.unpack_from('<Q', rec, o)[0]
            qa = (qa & ~(0xFFFF << 4)) | (5873 << 4)          # tile 5873, keep fine y
            qa = (qa & ~(3 << 32)) | (3 << 32)                # palette 3
            struct.pack_into('<Q', rec, o, qa)
        # exactly one sprite on the line: tile `tile`, palette 0, front, solid colour 3
        q0 = (q0 & ~(0xFF << 48)) | (1 << 48)
        struct.pack_into('<Q', rec, h, q0)
        lin = (tile << 4) | (y & 7)
        qa = (1 << 54) | (0 << 46) | (SX << 38) | (lin << 16) | (0xFF << 8) | 0xFF
        struct.pack_into('<QQ', rec, h + 640, qa, 0)
        for x in range(256):
            p = y * 1024 + x * 4
            if SX <= x < SX + 8:
                rec[p] |= 0x40
            else:
                rec[p] &= ~0x40 & 0xFF
    return rec


def main():
    ap = argparse.ArgumentParser()
    for n in ('hdp', 'recdir', 'frame', 'exact', 'nowt', 'work'):
        ap.add_argument(n)
    ap.add_argument('--tile', type=int, default=4006)
    a = ap.parse_args()
    f = '%04d' % int(a.frame)
    rd = os.path.join(a.work, 'case')
    os.makedirs(rd, exist_ok=True)
    rec = build(open(os.path.join(a.recdir, f'rec_{f}.bin'), 'rb').read(), a.tile)
    open(os.path.join(rd, f'rec_{f}.bin'), 'wb').write(rec)
    shutil.copyfile(os.path.join(a.recdir, f'watch_{f}.bin'), os.path.join(rd, f'watch_{f}.bin'))
    ref = subprocess.run([sys.executable, os.path.join(HERE, 'hdref_decisions.py'), a.hdp, rd,
                          '--frame', str(int(f))], capture_output=True, text=True)
    if not ref.stdout.strip():
        sys.exit('reference failed:\n' + ref.stderr)
    want = ref.stdout.replace('\r', '')
    print('reference:', ref.stderr.strip())
    res = {}
    for name, exe in (('exact', a.exact), ('nowt', a.nowt)):
        of = os.path.join(a.work, f'case_{name}.txt')
        subprocess.run([exe, a.hdp, os.path.join(rd, f'rec_{f}.bin'),
                        os.path.join(rd, f'watch_{f}.bin'), '--out', of], capture_output=True)
        got = open(of, newline='').read().replace('\r', '')
        nd = sum(1 for p, q in zip(got.split('\n'), want.split('\n')) if p != q)
        res[name] = got == want
        print(f'{name:6s} {"EQUALS the reference" if got == want else f"differs on {nd} lines"}')
    ok = res['exact'] and not res['nowt']
    print('VERDICT:', 'PASS - overlay reached and correct' if ok else
          ('FAIL - exact differs from the reference' if not res['exact'] else
           'INCONCLUSIVE - this frame does not reach the overlay'))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
