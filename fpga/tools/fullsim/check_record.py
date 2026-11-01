"""Check the stage-2 frame record against the real core (fullsim --rec output).

For each saved frame F, rec_FFFF.bin is the record hd_capture wrote and col_FFFF.bin the
PPU's actual output (one colour index per PPU cycle). Checks, per visible pixel:

  1. colour: where no fetched sprite covers the pixel and the line is not grayscale, the
     PPU's output colour must equal the record's BgColor (b3). This pins the tap's pixel
     alignment, the BG colour index, the attribute palette and the palette lookup.
  2. identity (CHR-ROM data from --rom; CHR-RAM games use chr_FFFF.bin, the SDRAM dump fullsim
     takes at the end of the visible lines): the BG span the pixel points at names a CHR address;
     decoding that tile row at the pixel's OffsetX must give the record's BgColorIndex. This
     pins the span slot / OffsetX mapping, i.e. exactly what an HD tile lookup keys on.
  3. palette select: the span's attribute palette must be the one b3 was looked up with.
  4. header: x = 0 flag and counts are sane, the header's y matches.
  5. sequence: along a rendered line slot*8 + OffsetX - x is constant, except that a
     mid-line scroll write (status-bar split) shifts it once for good; a short run that ends
     again right away is a pixel naming the wrong tile column (catches an OffsetX error
     inside a solid-colour tile row, which check 2 cannot see).
  6. fingerprints: every BG span and sprite fetch carries CRC-64 of its 16 tile bytes
     (CHR-RAM games, computed here from the independent dump) or 0 (CHR-ROM games).
  7. sprite identity: every valid sprite entry (main and, with the 16-sprite option, extra)
     names the LOW-plane row of a tile (address bit 3 clear) whose two plane bytes are the
     recorded pattern bytes, bit-reversed unless the sprite is flipped horizontally (the PPU's
     own vram_f). This pins the CHR address an HD sprite lookup keys on, which the colour
     check cannot see (it skips sprite-covered pixels).
  8. 16-sprite copy: with the core's extra sprites on (more than 8 fetches on a line), entry 8
     (extra 0) is the core's copy of main sprite 7 and must not be VALID when identical to
     entry 7 (hd_tap.sv explains; an HD render would otherwise draw that sprite twice). The SD
     colour checks cannot see this: the copy never decides an SD pixel.

usage: python check_record.py DIR --rom game.nes [--xoff 2]
exit 0 = every checked pixel agrees
"""
import argparse
import glob
import os
import struct
import sys


_T64 = []
for _i in range(256):
    _r = _i << 56
    for _ in range(8):
        _r = ((_r << 1) ^ 0x42F0E1EBA9EA3693) if _r & (1 << 63) else (_r << 1)
        _r &= 0xFFFFFFFFFFFFFFFF
    _T64.append(_r)


def crc64(data):
    """CRC-64, poly 0x42F0E1EBA9EA3693, init 0, MSB first, no final XOR (hd_chrfp.sv)."""
    r = 0
    for b in data:
        r = ((r << 8) & 0xFFFFFFFFFFFFFFFF) ^ _T64[((r >> 56) ^ b) & 0xFF]
    return r


def check_fingerprints(rec, chr_dump, chr_ram, stats, first):
    """6. every BG span and sprite fetch: qB = CRC-64 of its 16 tile bytes (CHR-RAM games,
    from the independent SDRAM dump), 0 for CHR-ROM games."""
    for y in range(240):
        hoff = 0x40000 + y * 2048
        q0 = struct.unpack_from("<Q", rec, hoff)[0]
        nspan = (q0 >> 32) & 0xFF
        nspr = (q0 >> 48) & 0xFF
        ents = [(hoff + 64 + s * 16, "span %d" % s, 0) for s in range(min(nspan, 34))]
        ents += [(hoff + 640 + i * 16, "sprite %d" % i, 16) for i in range(min(nspr, 64))]
        for off, what, shift in ents:
            qa, qb = struct.unpack_from("<QQ", rec, off)
            lin = (qa >> shift) & 0x3FFFFF
            if not chr_ram:
                want = 0
            else:
                rel = lin - 0x200000
                if rel < 0 or rel >= len(chr_dump):
                    stats["fp_skip"] += 1
                    continue
                t = rel & ~15
                want = crc64(chr_dump[t:t + 16])
            if qb == want:
                stats["fp_ok"] += 1
            else:
                stats["fp_bad"] += 1
                if len(first) < 8:
                    first.append(f"y{y} {what}: lin {lin:06x} fingerprint {qb:016x}, expected {want:016x}")


def _rev8(b):
    return int(f"{b:08b}"[::-1], 2)


def check_sprite_identity(rec, chr_src, chr_ram, stats, first):
    """7. every valid sprite entry {valid, attr, x, lin, pix1, pix2}: lin is a low-plane row
    (bit 3 clear) and chr[lin], chr[lin + 8] give pix1, pix2 (reversed unless attr bit 6)."""
    for y in range(240):
        hoff = 0x40000 + y * 2048
        nspr = (struct.unpack_from("<Q", rec, hoff)[0] >> 48) & 0xFF
        if nspr > 8:
            q7 = struct.unpack_from("<Q", rec, hoff + 640 + 7 * 16)[0]
            q8 = struct.unpack_from("<Q", rec, hoff + 640 + 8 * 16)[0]
            if (q7 >> 54) & 1 and (q8 >> 54) & 1 and (q7 & ((1 << 54) - 1)) == (q8 & ((1 << 54) - 1)):
                stats["dup_bad"] += 1
                if len(first) < 8:
                    first.append(f"y{y}: entry 8 is a valid copy of entry 7 ({q8:014x})")
        for i in range(min(nspr, 64)):
            qa = struct.unpack_from("<Q", rec, hoff + 640 + i * 16)[0]
            if not (qa >> 54) & 1:
                continue
            attr = (qa >> 46) & 0xFF
            lin = (qa >> 16) & 0x3FFFFF
            pix1, pix2 = (qa >> 8) & 0xFF, qa & 0xFF
            if (lin >> 20) != 2:
                stats["sid_skip"] += 1
                continue
            off = (lin - 0x200000) if chr_ram else (lin & 0xFFFFF)
            if lin & 8 or off + 8 >= len(chr_src):
                bad = True
                exp = None
            else:
                raw0, raw1 = chr_src[off], chr_src[off + 8]
                exp = (raw0, raw1) if attr & 0x40 else (_rev8(raw0), _rev8(raw1))
                bad = exp != (pix1, pix2)
            if bad:
                stats["sid_bad"] += 1
                if len(first) < 8:
                    first.append(f"y{y} sprite {i}: lin {lin:06x} attr {attr:02x} pattern "
                                 f"{pix1:02x} {pix2:02x}, CHR gives {exp}")
            else:
                stats["sid_ok"] += 1


def load_chr(rom_path):
    with open(rom_path, "rb") as f:
        d = f.read()
    if d[:4] != b"NES\x1a":
        sys.exit("not an iNES file")
    prg = d[4] * 16384
    chr_size = d[5] * 8192
    start = 16 + (512 if d[6] & 4 else 0) + prg
    return d[start:start + chr_size]


def check(rec, col, chr_rom, xoff, frame):
    stats = dict(px=0, col_ok=0, col_bad=0, col_skip=0, id_ok=0, id_bad=0, id_skip=0, pal_bad=0, hdr_bad=0,
                 seq_bad=0, fp_ok=0, fp_bad=0, fp_skip=0, rendered=0, sid_ok=0, sid_bad=0, sid_skip=0, dup_bad=0)
    first = []
    for y in range(240):
        hoff = 0x40000 + y * 2048
        q0 = struct.unpack_from("<Q", rec, hoff)[0]
        gray = (q0 >> 18) & 1
        xa = (q0 >> 24) & 1
        nspan = (q0 >> 32) & 0xFF
        nsprv = (q0 >> 40) & 0xFF
        nspr = (q0 >> 48) & 0xFF
        hy = (q0 >> 56) & 0xFF
        if hy != y or nspan > 34 or nsprv > nspr or nspr > 64:
            stats["hdr_bad"] += 1
            if len(first) < 8:
                first.append(f"y{y}: header y={hy} spans={nspan} sprites={nsprv}/{nspr}")
        pal = []
        pbits = int.from_bytes(rec[hoff + 8:hoff + 32], "little")
        for n in range(32):
            pal.append((pbits >> (6 * n)) & 63)
        cover = [False] * 256
        for i in range(nspr):
            qa = struct.unpack_from("<Q", rec, hoff + 640 + i * 16)[0]
            if not (qa >> 54) & 1:
                continue
            sx = (qa >> 38) & 0xFF
            for x in range(sx, min(256, sx + 8)):
                cover[x] = True
        # 5. sequence: d(x) = slot*8 + OffsetX - x is constant along a rendered stretch, except
        #    that a mid-line scroll write (a status-bar split) shifts it once and it STAYS
        #    shifted. A wrong pixel shows up as a run that ends again right away: interior runs
        #    of fewer than 8 pixels, or a 1-pixel run at either end, are errors.
        runs = []                  # [x0, length, d] within contiguous rendered stretches
        for x in range(256):
            b0, b1 = rec[y * 1024 + x * 4], rec[y * 1024 + x * 4 + 1]
            if b0 & 63 == 63:
                runs.append(None)
                continue
            d = (b0 & 63) * 8 + ((b1 >> 2) & 7) - x
            if runs and runs[-1] is not None and runs[-1][2] == d:
                runs[-1][1] += 1
            else:
                runs.append([x, 1, d])
        stretch = []
        for r in runs + [None]:
            if r is not None:
                stretch.append(r)
                continue
            for k, (x0, ln, d) in enumerate(stretch):
                edge = k == 0 or k == len(stretch) - 1
                if len(stretch) > 1 and ((not edge and ln < 8) or ln == 1):
                    stats["seq_bad"] += 1
                    if len(first) < 8:
                        first.append(f"y{y} x{x0}: {ln}-pixel run of tile position offset {d} "
                                     f"(a pixel naming the wrong tile column)")
            stretch = []
        for x in range(256):
            b0, b1, b2, b3 = rec[y * 1024 + x * 4: y * 1024 + x * 4 + 4]
            stats["px"] += 1
            slot = b0 & 63
            cidx = b1 & 3
            ox = (b1 >> 2) & 7
            if slot != 63:
                stats["rendered"] += 1
            cx = x + xoff
            out = col[y * 341 + cx] & 63 if cx < 341 else None
            # 1. colour
            if cover[x] or gray or out is None:
                stats["col_skip"] += 1
            elif out == b3:
                stats["col_ok"] += 1
            else:
                stats["col_bad"] += 1
                if len(first) < 8:
                    first.append(f"y{y} x{x}: PPU {out:02x} record b3 {b3:02x} b2 {b2:02x} slot {slot} cidx {cidx}")
            # 2./3. identity and palette select
            if slot == 63 or chr_rom is None:
                stats["id_skip"] += 1
                continue
            qa = struct.unpack_from("<Q", rec, hoff + 64 + slot * 16)[0]
            lin = qa & 0x3FFFFF
            psel = (qa >> 32) & 3
            if cidx and b3 != pal[psel * 4 + cidx]:
                stats["pal_bad"] += 1
                if len(first) < 8:
                    first.append(f"y{y} x{x}: b3 {b3:02x} but span palette {psel} gives {pal[psel*4+cidx]:02x}")
            if (lin >> 20) != 2:
                stats["id_skip"] += 1
                continue
            off = lin & 0xFFFF7
            if off + 8 >= len(chr_rom):
                stats["id_skip"] += 1
                continue
            bit = 7 - ox
            exp = ((chr_rom[off] >> bit) & 1) | (((chr_rom[off + 8] >> bit) & 1) << 1)
            if exp == cidx:
                stats["id_ok"] += 1
            else:
                stats["id_bad"] += 1
                if len(first) < 8:
                    first.append(f"y{y} x{x}: span {slot} lin {lin:06x} ox {ox} decodes {exp}, record {cidx}")
    return stats, first


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    ap.add_argument("--rom")
    ap.add_argument("--xoff", type=int, default=2)
    a = ap.parse_args()
    if not a.rom:
        sys.exit("--rom is required (CHR-ROM data or the CHR-RAM flag comes from it)")
    chr_rom = load_chr(a.rom)
    chr_ram = not chr_rom
    if chr_ram:
        print("CHR-RAM game: identity and fingerprints checked against chr_FFFF.bin")
    bad = 0
    recs = sorted(glob.glob(os.path.join(a.dir, "rec_*.bin")))
    if not recs:
        sys.exit("no rec_*.bin in " + a.dir)
    for rp in recs:
        f = int(os.path.basename(rp)[4:8])
        cp = os.path.join(a.dir, f"col_{f:04d}.bin")
        if not os.path.exists(cp):
            print(f"frame {f}: no col file")
            bad += 1
            continue
        rec = open(rp, "rb").read()
        col = open(cp, "rb").read()
        if chr_ram:
            xp = os.path.join(a.dir, f"chr_{f:04d}.bin")
            if not os.path.exists(xp):
                print(f"frame {f}: no chr dump (CHR-RAM game needs fullsim --rec chr_FFFF.bin)")
                bad += 1
                continue
            chr_src = open(xp, "rb").read()
        else:
            chr_src = chr_rom
        st, first = check(rec, col, chr_src, a.xoff, f)
        check_fingerprints(rec, chr_src, chr_ram, st, first)
        check_sprite_identity(rec, chr_src, chr_ram, st, first)
        ok = (st["col_bad"] == 0 and st["id_bad"] == 0 and st["pal_bad"] == 0 and st["hdr_bad"] == 0
              and st["seq_bad"] == 0 and st["fp_bad"] == 0 and st["sid_bad"] == 0 and st["dup_bad"] == 0)
        print(f"frame {f}: colour {st['col_ok']} ok / {st['col_bad']} bad ({st['col_skip']} skipped), "
              f"identity {st['id_ok']} ok / {st['id_bad']} bad, palette-select bad {st['pal_bad']}, "
              f"header bad {st['hdr_bad']}, sequence bad {st['seq_bad']}, "
              f"fingerprint {st['fp_ok']} ok / {st['fp_bad']} bad, "
              f"sprite identity {st['sid_ok']} ok / {st['sid_bad']} bad, 16-sprite copy bad {st['dup_bad']}  "
              f"{'OK' if ok else 'FAIL'}")
        for line in first:
            print("   ", line)
        # a frame where nothing could be compared proves nothing (a rendering-off frame has no
        # tiles to identify, but its colours are still checked)
        if not ok or st["col_ok"] == 0 or st["fp_ok"] == 0 or (st["rendered"] and st["id_ok"] == 0):
            bad += 1
    print(f"{len(recs) - bad}/{len(recs)} frames pass")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
