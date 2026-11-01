"""Negative control for hdp3_read.check_audio: each mutation of a converted pack's section 15
must be reported, and the unmodified pack must pass.

    python tools/audio/neg_audio_section.py <pack.hdp> <pack_dir> [base_dir ...]

A variant/overlay pack (e.g. v1942b_hdmusic over a082) needs its base dirs, as hdp3_convert --base.
"""
import os, struct, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import hdp3_read as R
from hdp3_convert import load_pack

hdp, pack_dir = sys.argv[1], sys.argv[2]
data = bytearray(open(hdp, "rb").read())
p = load_pack(pack_dir, sys.argv[3:])
off, ln = struct.unpack_from("<II", data, 0x80 + 8 * 15)
n, data_off = struct.unpack_from("<II", data, off + 4)
ent0 = off + 16                      # first entry: key, start, frames, loop, state0, statel


def run(buf):
    return R.check_audio(R.Hdp3(bytes(buf)), p, limit=200000)


def mutate(name, fn):
    buf = bytearray(data)
    fn(buf)
    errs = run(buf)
    ok = bool(errs)
    print(("CAUGHT " if ok else "MISSED ") + name + ("  " + errs[0] if errs else ""))
    return ok


base = run(data)
print(("PASS   " if not base else "FAIL   ") + "unmodified pack" + ("  " + base[0] if base else ""))
start = struct.unpack_from("<I", data, ent0 + 4)[0]
results = [not base]
results.append(mutate("stream bytes flipped (first 4096)", lambda b: [
    b.__setitem__(off + start + i, b[off + start + i] ^ 0x88) for i in range(4096)]))
results.append(mutate("statel wrong", lambda b: struct.pack_into(
    "<Q", b, ent0 + 24, struct.unpack_from("<Q", b, ent0 + 24)[0] ^ 0x1)))
results.append(mutate("frames wrong", lambda b: struct.pack_into(
    "<I", b, ent0 + 8, struct.unpack_from("<I", b, ent0 + 8)[0] - 1)))
results.append(mutate("keys out of order", lambda b: (
    lambda k0, k1: (struct.pack_into("<I", b, ent0, k1), struct.pack_into("<I", b, ent0 + 32, k0)))(
    *struct.unpack_from("<I", b, ent0), *struct.unpack_from("<I", b, ent0 + 32))))
# the restore-checkpoint table (since 2026-10-29): {u32 spacing, u32 count, u64 states} at ck_off
(ck_off,) = struct.unpack_from("<I", data, off + 12)
ents = [struct.unpack_from("<IIIIQQ", data, ent0 + 32 * i) for i in range(n)]
idx, best, deep = 0, -1, None
for i, (key, st, fr, lp, s0, sl) in enumerate(ents):    # the deepest checkpoint of the longest
    nck = fr // 16384 + 1
    if fr > best:
        best, deep = fr, idx + nck - 1
    idx += nck
print("checkpoint table at %#x, %d states; flipping state %d (frame %d of a %d-frame entry)" % (
    ck_off, idx, deep, (best // 16384) * 16384, best))
results.append(mutate("checkpoint table offset cleared", lambda b: struct.pack_into(
    "<I", b, off + 12, 0)))
results.append(mutate("checkpoint count one short", lambda b: struct.pack_into(
    "<I", b, off + ck_off + 4, idx - 1)))
results.append(mutate("checkpoint spacing halved", lambda b: struct.pack_into(
    "<I", b, off + ck_off, 8192)))
results.append(mutate("deepest checkpoint's left predictor off by one", lambda b: struct.pack_into(
    "<Q", b, off + ck_off + 8 + 8 * deep,
    struct.unpack_from("<Q", b, off + ck_off + 8 + 8 * deep)[0] ^ 0x1)))
print("ALL OK" if all(results) else "%d FAILED" % results.count(False))
sys.exit(0 if all(results) else 1)
