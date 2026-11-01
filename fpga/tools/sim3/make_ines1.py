"""Fixtures for hd3_romfix's second pass (the iNES 1.0 form, rommatch.py): ROMs with an NES 2.0
style header (bytes 7-15 not zero) whose <patch> line names the SHA1 of the same file with
bytes 7-15 zero - what pack authors' iNES 1.0 dumps hash to.

    rom0  IPS keyed by the iNES 1.0 form          -> patched, built from that form
    rom1  BPS keyed by the iNES 1.0 form (its source CRC is that form's, so building from the
          raw file would fail) with SourceRead runs over the header
    rom2  UPS keyed by the iNES 1.0 form, XOR runs over header bytes 0-20 (they must read the
          zeroed form)
    rom3  two lines: one for the file itself, one for its iNES 1.0 form -> the file's wins
    rom4  BPS keyed by the iNES 1.0 form whose target CRC is wrong -> refused, ROM unpatched
          (in its own pack, bad.hdp - every other entry is good)
    rom5  no "NES\\x1a" magic, keyed by the zeroed form -> no second pass, no match
Writes ines1/pack/, ines1/bad_pack/, ines1/rom<k>.nes and ines1/exp<k>.bin (what the core must
end up with: rompatch.apply of the form that matched, or the ROM).

    python -I make_ines1.py out_dir
"""
import hashlib
import os
import random
import sys
import zlib

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import rommatch  # noqa: E402
import rompatch  # noqa: E402
import test_hdp3_patch as T  # noqa: E402

out = sys.argv[1]
pk, bpk = os.path.join(out, "pack"), os.path.join(out, "bad_pack")
os.makedirs(pk, exist_ok=True)
os.makedirs(bpk, exist_ok=True)
rng = random.Random(23)
lines, bad_lines, made = ["<ver>106"], ["<ver>106"], []


def rom(n, magic=True):
    head = b"NES\x1a" if magic else b"NEZ\x1a"
    r = bytearray(head + bytes(rng.randrange(256) for _ in range(n - 4)))
    r[7] |= 0x08                                  # NES 2.0 marker, and bytes 7-15 not all 0
    r[9] |= 0x01
    return bytes(r)


def sha(b):
    return hashlib.sha1(b).hexdigest().upper()


def zeroed(r):
    return r[:7] + bytes(9) + r[16:]


def bps_header_reads(src):
    """A BPS that copies the whole source (SourceRead) and writes 6 literal bytes at 200."""
    v = T.vlq
    cmds = v(((200 - 1) << 2) | 0) + v(((6 - 1) << 2) | 1) + b"ZEROED" + \
        v(((len(src) - 206 - 1) << 2) | 0)
    tgt = bytearray(src)
    tgt[200:206] = b"ZEROED"
    return T.tail(src, bytes(tgt), bytearray(b"BPS1") + v(len(src)) + v(len(tgt)) + v(0) + cmds)


def ups_header_xor(src):
    """A UPS whose XOR runs cover bytes 0-20 and a few later ones."""
    dst = bytearray(src)
    for i in list(range(0, 21)) + [999, 1000, 4000]:
        dst[i] ^= 0x5A
    body = bytearray(b"UPS1") + T.vlq(len(src)) + T.vlq(len(dst))
    i = rel = 0
    while i < len(dst):
        if dst[i] == src[i]:
            i += 1
            continue
        body += T.vlq(i - rel)
        while i < len(dst) and dst[i] != src[i]:
            body.append(dst[i] ^ src[i])
            i += 1
        body.append(0)
        i += 1
        rel = i
    return T.tail(src, bytes(dst), body)


def write(k, r, exp, note):
    open(os.path.join(out, f"rom{k}.nes"), "wb").write(r)
    open(os.path.join(out, f"exp{k}.bin"), "wb").write(exp)
    made.append(f"rom{k}: {note}  {len(r)} -> {len(exp)}")


# rom0: IPS
r = rom(30000); z = zeroed(r)
p = T.ips(rng, len(z))
open(os.path.join(pk, "p0.ips"), "wb").write(p)
lines.append(f"<patch>p0.ips,{sha(z)}")
write(0, r, rompatch.apply(z, p), "IPS on the iNES 1.0 form")

# rom1: BPS over the header
r = rom(20000); z = zeroed(r)
p = bps_header_reads(z)
try:
    rompatch.apply(r, p)
    raise SystemExit("rom1: the BPS should refuse the raw file")
except rompatch.PatchError:
    pass
open(os.path.join(pk, "p1.bps"), "wb").write(p)
lines.append(f"<patch>p1.bps,{sha(z)}")
write(1, r, rompatch.apply(z, p), "BPS on the iNES 1.0 form (refuses the raw file)")

# rom2: UPS XOR over the header
r = rom(16003); z = zeroed(r)
p = ups_header_xor(z)
open(os.path.join(pk, "p2.ups"), "wb").write(p)
lines.append(f"<patch>p2.ups,{sha(z)}")
want = rompatch.apply(z, p)
assert want[7:16] == bytes(b ^ 0x5A for b in bytes(9)), "XOR must read the zeroed bytes"
write(2, r, want, "UPS XOR over the zeroed header")

# rom3: the file's own line wins
r = rom(24000); z = zeroed(r)
p_raw, p_z = T.ips(rng, len(r)), T.ips(rng, len(z))
open(os.path.join(pk, "p3raw.ips"), "wb").write(p_raw)
open(os.path.join(pk, "p3z.ips"), "wb").write(p_z)
lines.append(f"<patch>p3z.ips,{sha(z)}")          # listed first: order must not matter
lines.append(f"<patch>p3raw.ips,{sha(r)}")
write(3, r, rompatch.apply(r, p_raw), "file line beats iNES 1.0 line")

# rom4: wrong target CRC (own pack)
r = rom(20000); z = zeroed(r)
good = bps_header_reads(z)
body = bytearray(good[:-12]) + good[-12:-8] + (zlib.crc32(b"wrong") & 0xFFFFFFFF).to_bytes(4, "little")
p = bytes(body) + zlib.crc32(bytes(body)).to_bytes(4, "little")
open(os.path.join(bpk, "p4.bps"), "wb").write(p)
bad_lines.append(f"<patch>p4.bps,{sha(z)}")
write(4, r, r, "iNES 1.0 match, target CRC wrong -> unpatched")

# rom5: no magic
r = rom(12000, magic=False); z = zeroed(r)
assert rommatch.ines1(r) is None
p = T.ips(rng, len(z))
open(os.path.join(pk, "p5.ips"), "wb").write(p)
lines.append(f"<patch>p5.ips,{sha(z)}")
write(5, r, r, "no NES magic -> no second pass")

open(os.path.join(pk, "hires.txt"), "w").write("\n".join(lines) + "\n")
open(os.path.join(bpk, "hires.txt"), "w").write("\n".join(bad_lines) + "\n")
print("\n".join(made))
