"""Malformed section-14 packs for hd3_romfix's refusal paths, made from synth/synth.hdp:

    synth/bad_mode.hdp   rom0's entry (IPS): its first run's mode set to 7          -> refused (3)
    synth/bad_tgt.hdp    rom4's entry (BPS): a TargetCopy run reading at/after its
                         own write position                                          -> refused (3)
    synth/bad_runs.hdp   rom2's entry (UPS): run count reaching past the section     -> refused (3)
    synth/bad_data.hdp   rom0's entry (IPS): a LIT run's data range past the entry's
                         data length                                                 -> refused (3)

Section 14 = header u32 at 0xF0 (offset) / 0xF4 (length); entries 64 bytes from +64:
sha1[20] base flags pad[2] | ssz tsz | trunc crc | roff rn | doff dlen; runs 16 bytes:
tgt len arg mode. Every edit is checked to have landed where it was meant to.

    python -I make_bad.py synth
"""
import hashlib
import os
import struct
import sys

d = sys.argv[1]
src = open(os.path.join(d, "synth.hdp"), "rb").read()
s14, n14 = struct.unpack_from("<II", src, 0xF0)
assert n14 >= 64, "no section 14"


def entry_of(rom_k):
    sha = hashlib.sha1(open(os.path.join(d, f"rom{rom_k}.nes"), "rb").read()).digest()
    count = struct.unpack_from("<I", src, s14)[0]
    for k in range(count):
        e = s14 + 64 + 64 * k
        if src[e:e + 20] == sha:
            return e
    raise SystemExit(f"rom{rom_k}: no entry")


def fields(e):
    roff, rn = struct.unpack_from("<II", src, e + 40)
    doff, dlen = struct.unpack_from("<II", src, e + 48)
    return roff, rn, doff, dlen


def runs(e):
    roff, rn, _, _ = fields(e)
    return [(s14 + roff + 16 * i,) + struct.unpack_from("<IIIB", src, s14 + roff + 16 * i)
            for i in range(rn)]


def write(name, edits):
    b = bytearray(src)
    for off, fmt, val in edits:
        struct.pack_into(fmt, b, off, val)
    open(os.path.join(d, name), "wb").write(b)
    print(f"{name}: {len(edits)} edit(s)")


e0 = entry_of(0)
r0 = runs(e0)
write("bad_mode.hdp", [(r0[0][0] + 12, "<B", 7)])

e4 = entry_of(4)
tgt = [r for r in runs(e4) if r[4] == 2]
assert tgt, "rom4's BPS has no TargetCopy run"
pos, t, n, a, m = tgt[0]
write("bad_tgt.hdp", [(pos + 8, "<I", t)])            # source position = its own target position

e2 = entry_of(2)
roff, rn, _, _ = fields(e2)
write("bad_runs.hdp", [(e2 + 44, "<I", (n14 - roff) // 16 + 1)])

write("bad_ssz.hdp", [(e2 + 24, "<I", struct.unpack_from("<I", src, e2 + 24)[0] + 1)])

# rom0's runs copied to just past the section's end (the file is extended and its size word
# at 0x20 updated): the runs themselves are valid, so only the run-list bounds check refuses
assert s14 + n14 == len(src) == struct.unpack_from("<I", src, 0x20)[0], "section 14 is not last"
roff0, rn0, _, _ = fields(e0)
runs0 = src[s14 + roff0: s14 + roff0 + 16 * rn0]
b = bytearray(src) + bytes((-len(src)) % 64)
new_roff = len(b) - s14
b += runs0
struct.pack_into("<I", b, 0x20, len(b))
struct.pack_into("<I", b, e0 + 40, new_roff)
open(os.path.join(d, "bad_runs_out.hdp"), "wb").write(b)
print("bad_runs_out.hdp: runs moved past the section")

lit = [r for r in r0 if r[4] == 0]
assert lit, "rom0's IPS has no LIT run"
_, _, _, dlen = fields(e0)
pos, t, n, a, m = lit[0]
write("bad_data.hdp", [(pos + 8, "<I", dlen)])         # data starts at the end of the data
