"""Convert a Mesen HD pack folder (hires.txt + PNGs) into the .hdp file the test core loads.

Test-version scope: CHR-ROM tiles, scale 2, unconditional <tile> entries. Everything else is
counted and reported, never silently dropped.

.hdp layout (little-endian), all offsets fixed:
  0x00000  header   64 bytes   magic "NHDP", u16 version (2), u8 scale, u8 0, u32 table_size,
                               u32 tiles, u32 max_probe, u32 rom_crc32 (0 = unknown)
  0x00040  palette  64 x 4     R, G, B, 0   (SD colours for tiles the pack does not replace)
  0x00140  table    8192 x 8   hash table entries, layout below (0 = empty slot)
  0x10400  atlas    tiles x 1024   16x16 px, row-major, R,G,B,A bytes (A is 0 or 255)

Hash entry (u64):  [17:0] tile index   [19:18] kind (0 = BG, 1 = sprite, 2 = default)
                   [43:20] pal24       [59:44] atlas index   [63] valid
pal24 = c0<<18 | c1<<12 | c2<<6 | c3 (6 bits each); c0 = backdrop for BG, 0 for sprite/default.
Hash  = CRC-13, poly 0x1CF5, init 0, MSB first, over the 44-bit key {kind, pal24, tile};
        linear probing. rtl/hdpack must compute exactly this. (Format 1 used an XOR fold.)

usage: python hdp_convert.py <pack_dir> <out.hdp> [--palette file.pal]
"""
import argparse
import os
import re
import struct
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pngio import read_png  # noqa: E402

TABLE_SIZE = 8192
MAX_PROBE_LIMIT = 16
SCALE = 2
TILE_PX = 8 * SCALE
PAL_OFF, TABLE_OFF, ATLAS_OFF = 0x40, 0x140, 0x10400
HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PAL = os.path.join(HERE, "..", "Palette", "Kitrinx34.pal")


HASH_POLY = 0x1CF5
FLAG_LEGACY_KEY = 0x01
MESEN_VERSION = 109      # BaseHdNesPack::CurrentVersion: Mesen refuses newer packs


_STOI = re.compile(r"\s*([+-]?\d+)")
_STOF = re.compile(r"\s*([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)")


def stoi(text):
    """C++ std::stoi, which Mesen uses for every decimal field: leading digits only, so
    "565F" reads as 565. No digits at all throws, and Mesen then rejects the whole pack."""
    m = _STOI.match(text)
    if not m:
        raise SystemExit(f"field {text!r} is not a number; Mesen refuses this pack too")
    return int(m.group(1))


def brightness_value(text, version):
    """Mesen's integer brightness for a <tile> line (HdPackLoader::ProcessTileTag).

    text is the field, or None when the line has none. Version 0 has no field (255);
    101-104 store it through a uint8_t, so values over 1.0 wrap; 105+ keep the int.
    The float is single precision, as Mesen parses it with stof.
    """
    if version == 0 or text is None:
        return 255
    m = _STOF.match(text)                # std::stof: leading number only
    if not m:
        raise SystemExit(f"brightness {text!r} is not a number; Mesen refuses this pack too")
    b = int(struct.unpack("<f", struct.pack("<f", float(m.group(1))))[0] * 255)
    return b & 0xFF if version < 105 else b


def adjust_brightness(c, b):
    """Mesen's HdNesPack::AdjustBrightness for one channel."""
    return c if b == 255 else min(255, (b * (c + 1)) >> 8)


def box_weights(o, scale):
    """Source pixels under 2x output pixel o, with integer weights.

    In half-source-pixel units the output pixel spans [o*scale, (o+1)*scale) and source pixel
    i spans [2i, 2i+2); the weight is the overlap. scale 1 -> one pixel (exact doubling),
    scale 2 -> one pixel, scale 4 -> two equal pixels, odd scales -> partial edge pixels.
    """
    lo, hi = o * scale, (o + 1) * scale
    return [(i, min(hi, 2 * i + 2) - max(lo, 2 * i)) for i in range(lo // 2, (hi + 1) // 2)]


def tile_rgba(rows, x, y, scale, bright):
    """The 16x16 (2x) tile at pack-pixel (x, y) of a decoded PNG: list of rows of (r, g, b, opaque).

    bright is Mesen's integer brightness (255 = unchanged), applied to each source pixel first,
    so the result is Mesen's own picture area-resampled to 2x. An output pixel is opaque when
    at least half its area is (alpha >= 128); its colour is the area-weighted mean of the
    opaque pixels under it, so edges do not darken towards transparent black.
    """
    out = []
    for oy in range(TILE_PX):
        wy = box_weights(oy, scale)
        row = []
        for ox in range(TILE_PX):
            px = [(rows[y + j][x + i], a * b) for j, a in wy for i, b in box_weights(ox, scale)]
            total = sum(w for _, w in px)
            solid = [(p, w) for p, w in px if p[3] >= 128]
            opaque = 2 * sum(w for _, w in solid) >= total
            src = solid if solid else px
            sw = sum(w for _, w in src)
            r, g, b = (sum(adjust_brightness(p[c], bright) * w for p, w in src) // sw
                       for c in range(3))
            row.append((r, g, b, opaque))
        out.append(row)
    return out


def hash_key(tile, kind, pal24):
    """CRC-13 (poly 0x1CF5, init 0, MSB first) of the 44-bit key {kind, pal24, tile}.

    A pure XOR network in hardware. The format-1 XOR fold clustered badly on real packs,
    which use few palettes: Duck Hunt HD needed 69 probes, Pac-Man 129; CRC-13 needs 1-3.
    """
    v = (kind << 42) | (pal24 << 18) | (tile & 0x3FFFF)
    r = 0
    for i in range(43, -1, -1):
        fb = ((r >> 12) & 1) ^ ((v >> i) & 1)
        r = (r << 1) & 0x1FFF
        if fb:
            r ^= HASH_POLY
    return r & (TABLE_SIZE - 1)


def from_hex(text):
    """Mesen HexUtilities::FromHex: every character shifts in a nibble, non-hex ones as 0,
    into a 32-bit int."""
    v = 0
    for ch in text:
        v = (v << 4) & 0xFFFFFFFF
        if ch in "0123456789abcdefABCDEF":
            v |= int(ch, 16)
    return v


def parse_palette(hexstr):
    """Mesen PaletteColors hex -> (kind, pal24) or None if out of range."""
    v = from_hex(hexstr)
    if v == 0xFFFFFFFF:
        return 2, 0
    b = [(v >> s) & 0xFF for s in (24, 16, 8, 0)]
    if b[0] == 0xFF:
        kind, b[0] = 1, 0
    else:
        kind = 0
    if any(x > 0x3F for x in b):
        return None
    return kind, (b[0] << 18) | (b[1] << 12) | (b[2] << 6) | b[3]


def parse_pack(pack_dir):
    """Read hires.txt under the test-version rules.

    Returns (version, scale, images, entries, atlas_keys, atlas, stats):
      scale       the pack's <scale> (Mesen's default is 1); the atlas is always built at 2x
      entries     (tile, kind, pal24) -> atlas key, first definition kept
      atlas_keys  atlas key -> atlas index;  atlas  list of (img, x, y, brightness)
    """
    stats = Counter()
    version = 0
    scale = 1
    images = []
    entries = {}          # (tile, kind, pal24) -> atlas key
    atlas_keys = {}       # (img, x, y, brightness) -> atlas index
    atlas = []
    # Mesen HdPackLoader::LoadHdNesPack: lines split on '\n' with trailing CR/LF removed and
    # nothing else trimmed (a line with leading spaces is ignored), a leading "[...]" holds the
    # conditions, and fields split on ',' with no trimming.
    with open(os.path.join(pack_dir, "hires.txt"), "rb") as f:
        lines = f.read().decode("utf-8", "surrogateescape").split("\n")
    for raw in lines:
        line = raw.rstrip("\r\n")
        if not line:
            continue
        conditional = False
        if line.startswith("["):
            end = line.find("]", 1)
            if end < 0:
                stats["ignored: unterminated condition"] += 1
                continue
            conditional = True
            line = line[end + 1:]
        if line.startswith("<ver>"):
            version = stoi(line[5:])
            if version > MESEN_VERSION:
                raise SystemExit(f"pack version {version} is newer than Mesen {MESEN_VERSION}")
        elif line.startswith("<scale>"):
            scale = stoi(line[7:])
            if not 1 <= scale <= 10:
                raise SystemExit(f"scale {scale}: Mesen supports 1 to 10")
        elif line.startswith("<img>"):
            images.append(line[5:])
        elif line.startswith("<tile>"):
            stats["tile lines"] += 1
            tok = line[6:].split(",")
            if version < 100:
                # tile,img,c1,c2,c3,x,y[,brightness],default[,16 CHR-RAM bytes]
                # The key has no colour 0 and no sprite marker (HdNesPpu.h).
                if len(tok) >= 24:
                    stats["skipped: CHR-RAM tile"] += 1
                    continue
                tile, img = stoi(tok[0]), stoi(tok[1])
                cols = [stoi(tok[i]) for i in (2, 3, 4)]
                x, y = stoi(tok[5]), stoi(tok[6])
                i = 7
                bright = brightness_value(tok[i] if version > 0 else None, version)
                i += 1 if version > 0 else 0
                default = tok[i] == "Y"          # ParseBooleanValue: exactly "Y"
                if any(not 0 <= c <= 0x3F for c in cols):
                    stats["skipped: palette out of range"] += 1
                    continue
                parsed = (0, (cols[0] << 12) | (cols[1] << 6) | cols[2])
            else:
                img, tiledata, pal = stoi(tok[0]), tok[1], tok[2]
                x, y = stoi(tok[3]), stoi(tok[4])
                bright = brightness_value(tok[5], version)
                default = tok[6] == "Y"
                if len(tiledata) >= 32:
                    stats["skipped: CHR-RAM tile"] += 1
                    continue
                tile = from_hex(tiledata) if version > 102 else stoi(tiledata)
                parsed = parse_palette(pal)
                if parsed is None:
                    stats["skipped: palette out of range"] += 1
                    continue
            if conditional:
                stats["skipped: conditional"] += 1
                continue
            if tile >= 1 << 18:
                stats["skipped: tile index too large"] += 1
                continue
            akey = (img, x, y, bright)
            keys = [(tile,) + parsed]
            if default and keys[0] != (tile, 2, 0):
                keys.append((tile, 2, 0))
            for k in keys:
                if k in entries:
                    stats["duplicate key (first kept)"] += 1
                    continue
                entries[k] = akey
                if akey not in atlas_keys:
                    atlas_keys[akey] = len(atlas)
                    atlas.append(akey)
        elif line.startswith("<"):
            stats["ignored: " + line.split(">")[0] + ">"] += 1

    if len(atlas) >= 1 << 16:
        raise SystemExit("too many distinct tiles for the test version")
    if len(entries) > TABLE_SIZE * 3 // 4:
        raise SystemExit(f"{len(entries)} keys: hash table too full")
    return version, scale, images, entries, atlas_keys, atlas, stats


def build_table(entries, atlas_keys):
    """Linear-probe every key into the table. Returns (table, max_probe, probe_of_key)."""
    table = [0] * TABLE_SIZE
    max_probe = 0
    probe_of = {}
    for (tile, kind, pal24), akey in entries.items():
        h = hash_key(tile, kind, pal24)
        for probe in range(TABLE_SIZE):
            slot = (h + probe) & (TABLE_SIZE - 1)
            if table[slot] == 0:
                table[slot] = (1 << 63) | (atlas_keys[akey] << 44) | (pal24 << 20) | (kind << 18) | tile
                max_probe = max(max_probe, probe)
                probe_of[(tile, kind, pal24)] = probe
                break
    if max_probe >= MAX_PROBE_LIMIT:
        raise SystemExit(f"max probe {max_probe} exceeds the hardware limit {MAX_PROBE_LIMIT}")
    return table, max_probe, probe_of


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pack_dir")
    ap.add_argument("out")
    ap.add_argument("--palette")
    args = ap.parse_args()

    version, scale, images, entries, atlas_keys, atlas, stats = parse_pack(args.pack_dir)
    table, max_probe, _ = build_table(entries, atlas_keys)

    pal_path = args.palette or (os.path.join(args.pack_dir, "palette.dat")
                                if os.path.exists(os.path.join(args.pack_dir, "palette.dat"))
                                else DEFAULT_PAL)
    with open(pal_path, "rb") as f:
        pal = f.read()[:192]
    if len(pal) != 192:
        raise SystemExit(f"{pal_path}: expected a 192-byte palette")

    loaded = {}
    out = bytearray(ATLAS_OFF + len(atlas) * TILE_PX * TILE_PX * 4)
    # flags (byte 7): bit 0 = legacy key (pack version < 100): the core must look tiles up
    # with colour 0 cleared and sprites keyed like background tiles.
    flags = FLAG_LEGACY_KEY if version < 100 else 0
    out[0:24] = b"NHDP" + struct.pack("<HBBIIII", 2, SCALE, flags, TABLE_SIZE, len(atlas),
                                      max_probe, 0)
    for i in range(64):
        out[PAL_OFF + i * 4:PAL_OFF + i * 4 + 4] = pal[i * 3:i * 3 + 3] + b"\x00"
    for i, e in enumerate(table):
        out[TABLE_OFF + i * 8:TABLE_OFF + i * 8 + 8] = struct.pack("<Q", e)
    for ai, (img, x, y, bright) in enumerate(atlas):
        if img not in loaded:
            loaded[img] = read_png(os.path.join(args.pack_dir, images[img]))
        w, h, rows = loaded[img]
        src_px = 8 * scale
        if x + src_px > w or y + src_px > h:
            raise SystemExit(f"tile at {x},{y} falls outside {images[img]}")
        base = ATLAS_OFF + ai * TILE_PX * TILE_PX * 4
        for ty, row in enumerate(tile_rgba(rows, x, y, scale, bright)):
            for tx, (r, g, b, opaque) in enumerate(row):
                o = base + (ty * TILE_PX + tx) * 4
                out[o:o + 4] = bytes((r, g, b, 255 if opaque else 0))
    with open(args.out, "wb") as f:
        f.write(out)

    print(f"pack version {version} scale {scale}: {len(entries)} keys, {len(atlas)} atlas tiles, "
          f"max probe {max_probe}, {len(out)} bytes, palette {os.path.basename(pal_path)}")
    for k, v in sorted(stats.items()):
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
