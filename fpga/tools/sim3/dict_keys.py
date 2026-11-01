"""Does hd3_dict overflow on a recorded frame? (HDPACK_DESIGN.md, "8o")

hd3_dict gives every distinct record key of a frame an id, up to 2**RAW of them. A frame with
more distinct keys, or with a line holding more than 16 sprite fetches, is flagged frame_ovf and
hd3_render draws it with no HD lookups. This module computes, from rec_FFFF.bin alone, the same
two facts the RTL acts on, so check_render.py can build the matching reference:

    key  = (palette, body): body = the 64-bit fingerprint (qB) in a CHR-RAM game, else the
           tile index ((CHR linear address >> 4) & 0xFFFF, hd3_dict's lin[19:4])
    items per line, in hd3_dict's order: BG span slots < min(span count, 34), then sprite
           fetches < min(fetch count, 16) that are valid (bit 54 of qA)

Written from the record layout (HDPACK_DESIGN.md "hd3_dict"), not from the RTL source.
"""
import struct


def frame_keys(rec, game_ram, legacy):
    """Return (distinct keys in allocation order, a line had more than 16 fetches)."""
    seen = {}
    nfet_over = False
    for y in range(240):
        hoff = 0x40000 + y * 2048
        q0 = struct.unpack_from("<Q", rec, hoff)[0]
        nspan = min((q0 >> 32) & 0xFF, 34)
        nfet_raw = (q0 >> 48) & 0xFF
        nfet_over |= nfet_raw > 16
        nfet = min(nfet_raw, 16)
        pbits = int.from_bytes(rec[hoff + 8:hoff + 32], "little")
        c = [(pbits >> (6 * n)) & 63 for n in range(32)]
        for s in range(nspan):
            qa, qb = struct.unpack_from("<QQ", rec, hoff + 64 + s * 16)
            pb = ((qa >> 32) & 3) * 4
            pal = c[pb + 3] | (c[pb + 2] << 8) | (c[pb + 1] << 16) | (0 if legacy else c[0] << 24)
            body = qb if game_ram else ((qa & 0x3FFFFF) >> 4) & 0xFFFF
            seen.setdefault((pal, body), len(seen))
        for i in range(nfet):
            qa, qb = struct.unpack_from("<QQ", rec, hoff + 640 + i * 16)
            if not (qa >> 54) & 1:
                continue
            q = 0x10 + 4 * ((qa >> 46) & 3)
            pal = c[q + 3] | (c[q + 2] << 8) | (c[q + 1] << 16) | (0 if legacy else 0xFF000000)
            body = qb if game_ram else (((qa >> 16) & 0x3FFFFF) >> 4) & 0xFFFF
            seen.setdefault((pal, body), len(seen))
    return list(seen), nfet_over


def frame_overflows(rec, game_ram, legacy, raw=11):
    keys, nfet_over = frame_keys(rec, game_ram, legacy)
    return len(keys) > (1 << raw) or nfet_over, len(keys)


ABUF = 64       # hd3_dict: merged addition entries one record can buffer
POOL = 1024     # hd3_dict: addition pool entries per bank


def frame_overflows_add(h, rec, game_ram, legacy, raw=11):
    """frame_overflows for a pack with additions (8a): hd3_dict also gives every added key an
    id (deduplicated against the frame's keys on the full {palette, body}), so the ids are the
    record keys plus the distinct added keys. It also overflows a frame when one record's merged
    additions exceed ABUF, or the bank's pool exceeds POOL entries. h = hdp3_read.Hdp3.
    Returns (overflowed, ids, why)."""
    import hdp3_addtab as A
    keys, nfet_over = frame_keys(rec, game_ram, legacy)
    if nfet_over:
        return True, len(keys), "more than 16 sprite fetches on a line"
    if len(keys) > (1 << raw):
        return True, len(keys), f"{len(keys)} record keys"
    if not h.add_nb:
        return False, len(keys), ""
    d = h.d
    table = d[h.sec[A.S_ADDKEYS][0]:h.sec[A.S_ADDKEYS][0] + h.sec[A.S_ADDKEYS][1]]
    lists = d[h.sec[A.S_ADDLISTS][0]:h.sec[A.S_ADDLISTS][0] + h.sec[A.S_ADDLISTS][1]]
    fb = list(struct.unpack_from(f"<{h.nfallback}i", d, h.sec[A.S_FALLBACK][0])) \
        if h.nfallback and not game_ram else []
    kind = 1 if game_ram else 0
    ids = set(keys)
    pool = 0
    for pal, body in keys:
        m = A.matched(table, h.add_nb, h.add_mp, lists, pal, kind, body, fb)
        if not m:
            continue
        if len(m) > ABUF:
            return True, len(ids), f"a record matches {len(m)} additions > {ABUF}"
        pool += len(m)
        if pool > POOL:
            return True, len(ids), f"addition pool {pool} > {POOL} entries"
        for e in m:
            ids.add((e[4], e[5] & 0xFFFFFFFFFFFFFFFF))
            if len(ids) > (1 << raw):
                return True, len(ids), f"{len(keys)} record keys + added keys > {1 << raw} ids"
    return False, len(ids), ""
