"""A synthetic pack for hd3_romfix: six random ROMs, each with its own <patch> line, written
with test_hdp3_patch's generators so every run mode reaches the hardware:

    rom0  IPS with overlapping records, RLE records and records past the ROM's end (grows)
    rom1  IPS with the truncation extension (shrinks)
    rom2  UPS that grows the ROM        rom3  UPS that shrinks it
    rom4  BPS (every action, overlapping TargetCopy)
    rom5  IPS whose ROM size is not a multiple of 8 and whose records end mid-qword
plus decoy <patch> lines naming SHA1s of no ROM. Writes synth/pack (the pack folder),
synth/rom<k>.nes, synth/exp<k>.bin (rompatch.apply), and synth/nomatch.nes.

    python -I make_synth.py out_dir
"""
import hashlib
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import rompatch  # noqa: E402
import test_hdp3_patch as T  # noqa: E402

out = sys.argv[1]
pk = os.path.join(out, "pack")
os.makedirs(pk, exist_ok=True)
rng = random.Random(11)
lines = ["<ver>106"]


def rom(n):
    return b"NES\x1a" + bytes(rng.randrange(256) for _ in range(n - 4))


def ips_trunc(r, n_src):
    while True:
        p = T.ips(r, n_src)
        if p.endswith(b"EOF") and len(p) > 8:
            return p + rng.randint(n_src // 2, n_src - 1).to_bytes(3, "big")


made = []
for k in range(6):
    if k == 0:
        src = rom(30000); p = T.ips(rng, len(src))
    elif k == 1:
        src = rom(30000); p = ips_trunc(rng, len(src))
    elif k == 2:                                     # odd size: the staged file's last qword is partial
        while True:
            src = rom(20003); p = T.ups(rng, src)
            if rompatch.apply(src, p) and len(rompatch.apply(src, p)) > len(src):
                break
    elif k == 3:
        while True:
            src = rom(20000); p = T.ups(rng, src)
            if len(rompatch.apply(src, p)) < len(src):
                break
    elif k == 4:
        src = rom(20000); p = T.bps(rng, src)
    else:
        src = rom(24577); p = T.ips(rng, len(src))
    want = rompatch.apply(src, p)
    name = f"p{k}." + ("ips" if p[:5] == b"PATCH" else "ups" if p[:4] == b"UPS1" else "bps")
    open(os.path.join(pk, name), "wb").write(p)
    open(os.path.join(out, f"rom{k}.nes"), "wb").write(src)
    open(os.path.join(out, f"exp{k}.bin"), "wb").write(want)
    lines.append(f"<patch>{name},{hashlib.sha1(src).hexdigest().upper()}")
    made.append(f"rom{k}: {name} {len(src)} -> {len(want)}")
    if k == 2:                                       # decoys between real entries
        for _ in range(3):
            lines.append(f"<patch>{name},{hashlib.sha1(rom(100)).hexdigest().upper()}")

# rom6: UPS that grows the ROM and writes non-zero bytes into the grown part, so the XOR runs
# there read the source past its end (which must read as 0, not as whatever DDR3 holds)
def ups_of(src, dst):
    body = bytearray(b"UPS1") + T.vlq(len(src)) + T.vlq(len(dst))
    base = bytes(src[:len(dst)]) + bytes(max(0, len(dst) - len(src)))
    i = rel = 0
    while i < len(dst):
        if dst[i] == base[i]:
            i += 1
            continue
        body += T.vlq(i - rel)
        while i < len(dst) and dst[i] != base[i]:
            body.append(dst[i] ^ base[i])
            i += 1
        body.append(0)
        i += 1
        rel = i
    return T.tail(src, bytes(dst), body)


src = rom(16001)
dst = bytearray(src) + bytes(rng.randrange(1, 256) for _ in range(700))
dst[500:510] = bytes(10)
p = ups_of(src, dst)
want = rompatch.apply(src, p)
assert want == bytes(dst)
open(os.path.join(pk, "p6.ups"), "wb").write(p)
open(os.path.join(out, "rom6.nes"), "wb").write(src)
open(os.path.join(out, "exp6.bin"), "wb").write(want)
lines.append(f"<patch>p6.ups,{hashlib.sha1(src).hexdigest().upper()}")
made.append(f"rom6: p6.ups {len(src)} -> {len(want)} (writes past the source)")

open(os.path.join(out, "nomatch.nes"), "wb").write(rom(9000))
open(os.path.join(pk, "hires.txt"), "w").write("\n".join(lines) + "\n")
print("\n".join(made))
