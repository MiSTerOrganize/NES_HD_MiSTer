"""Checks for the stage-6 codec pieces.

    python tools/audio/test_ima.py

1. The C encoder (oggdecode pcm2adpcm) and the Python encoder (hdaudio.encode_stereo) produce
   the same bytes and the same state0 / statel, on synthetic signals that reach the clamps.
2. Decoding those bytes with hdaudio.ima_decode from state0 reconstructs the signal (SNR floor),
   and decoding from statel at the loop frame gives exactly the first pass's samples.
3. vol(x, v) = trunc(x * v / 255) equals the hardware form
   sign(p) * (((q * 257) + (q >> 8)) >> 16) with q = |p| + 1, for every |p| = |x| * v with
   |x| <= 32768, v <= 255 (exhaustive over all distinct products). Shifts and adds only; the
   first form tried, (|p| * 0x8081) >> 23, is off from |p| = 66299 and is kept as a control.
4. The lookahead encoder (depth 3, what the converter uses): its last-level shortcut equals
   trying all 16 nibbles; C == Python at depth 3 on slices; the loop restore still holds; and on
   the full signals it is never worse than greedy and meets the same floors.
Negative controls: a one-bit change to the step table, the divisor 256, and a last level that
tries only magnitude 0 must each fail.
Exit 0 = all pass.
"""
import math, os, random, struct, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import hdaudio as H

DEC = os.path.join(HERE, "oggdecode.exe")
# SNR floors: IMA ADPCM follows a full-scale square wave poorly (the step table has to climb
# from index 0 at every edge), so those synthetic signals get a lower floor than music does.
FLOOR = {"sine": 30.0, "noise": 12.0, "square_fullscale": 5.0, "silence_then_burst": 5.0}

fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else "  " + detail))
    if not ok:
        fails += 1


def signals():
    rnd = random.Random(7)
    n = 20000
    sig = {}
    sig["sine"] = [(int(20000 * math.sin(i / 9.0)), int(12000 * math.sin(i / 23.0))) for i in range(n)]
    sig["noise"] = [(rnd.randint(-32768, 32767), rnd.randint(-32768, 32767)) for _ in range(n)]
    sig["square_fullscale"] = [((32767 if (i // 37) & 1 else -32768),
                                (-32768 if (i // 51) & 1 else 32767)) for i in range(n)]
    sig["silence_then_burst"] = [(0, 0)] * 5000 + [(30000, -30000)] * 50 + [(0, 0)] * 5000
    return sig


def c_encode(pcm, loop, depth):
    with tempfile.TemporaryDirectory() as d:
        a, b = os.path.join(d, "in.raw"), os.path.join(d, "out.ima")
        with open(a, "wb") as f:
            f.write(b"".join(struct.pack("<hh", l, r) for l, r in pcm))
        out = subprocess.run([DEC, "pcm2adpcm", a, b, str(loop), str(depth)],
                             capture_output=True, text=True)
        if out.returncode:
            return None, out.stderr
        kv = dict(x.split("=") for x in out.stdout.split())
        ck = open(b + ".ck", "rb").read()
        c_encode.ck = list(struct.unpack("<%dQ" % (len(ck) // 8), ck))
        return (open(b, "rb").read(), int(kv["state0"], 16), int(kv["statel"], 16)), ""


def decode(data, state, start=0, count=None):
    pl, il, pr, ir = H.unpack_state(state)
    out = []
    end = len(data) if count is None else start + count
    for i in range(start, end):
        b = data[i]
        pl, il = H.ima_decode(pl, il, b & 15)
        pr, ir = H.ima_decode(pr, ir, b >> 4)
        out.append((pl, pr))
    return out


def snr(a, b):
    sig = sum(x * x + y * y for x, y in a) or 1
    err = sum((x - p) ** 2 + (y - q) ** 2 for (x, y), (p, q) in zip(a, b)) or 1
    return 10 * math.log10(sig / err)


# 1 + 2, the greedy encoder (depth 0) on the full signals
greedy_snr = {}
for name, pcm in signals().items():
    loop = len(pcm) // 3
    py = H.encode_stereo(pcm, loop)
    c, err = c_encode(pcm, loop, 0)
    check("encoder C == Python (depth 0): %s" % name, c is not None and c == py,
          err or "bytes/states differ")
    full = decode(py[0], py[1])
    s = snr(pcm, full)
    greedy_snr[name] = s
    floor = FLOOR[name]
    check("decode SNR %s = %.1f dB (floor %.0f)" % (name, s, floor), s >= floor)
    seam = decode(py[0], py[2], loop)
    check("loop restore replays the first pass exactly: %s" % name, seam == full[loop:])
    check("encoder checkpoints == decoder's (hdaudio.checkpoints): %s" % name,
          c_encode.ck == H.checkpoints(py[0], len(pcm), py[1]))

# 3, restore checkpoints over several spacings, incl. a length the spacing divides (the last
# checkpoint is then the state after every frame) and a stream shorter than one spacing
rnd = random.Random(3)
for n in (H.CK_SPACING * 3 + 777, H.CK_SPACING * 2, 100):
    pcm = [(rnd.randint(-30000, 30000), rnd.randint(-30000, 30000)) for _ in range(n)]
    c, err = c_encode(pcm, 0, 0)
    py = H.checkpoints(c[0], n, c[1]) if c else None
    check("checkpoints, %d frames: C == Python, %d of them" % (n, n // H.CK_SPACING + 1),
          c is not None and c_encode.ck == py and len(py) == n // H.CK_SPACING + 1, err)
    if c:
        full = decode(c[0], c[1])
        k = len(py) - 1
        at = k * H.CK_SPACING
        tail = decode(c[0], py[k], at) if at < n else []
        check("decoding from the last checkpoint gives the stream's own samples (%d)" % n,
              tail == full[at:])

# 4, the lookahead encoder the converter uses (depth 3, OPEN_ITEMS 13f)
# 4a: its last-level shortcut (two magnitudes either side of the target) equals trying all 16
rnd = random.Random(11)
def brute_last(pred, idx, sample):
    return min((sample - H.ima_decode(pred, idx, n)[0]) ** 2 for n in range(16))
mism = []
for _ in range(20000):
    pred = rnd.choice((rnd.randint(-32768, 32767), 32767, -32768, rnd.randint(-40, 40)))
    idx = rnd.randint(0, 88)
    sample = rnd.choice((rnd.randint(-32768, 32767), pred, pred + 1, 32767, -32768))
    sample = max(-32768, min(32767, sample))
    if H._best_last(pred, idx, sample) != brute_last(pred, idx, sample):
        mism.append((pred, idx, sample))
check("last-level shortcut == all 16 nibbles (20000 random states incl. the clamps)", not mism,
      "first %s" % mism[:3])
saved_bl = H._best_last
H._best_last = lambda p, i, s: min((s - H.ima_decode(p, i, m)[0]) ** 2 for m in range(1))
check("negative control: a last level that tries only magnitude 0 is caught",
      any(H._best_last(p, i, s) != brute_last(p, i, s) for p, i, s in
          ((0, 40, 20000), (100, 10, -3000), (-500, 60, 9000))))
H._best_last = saved_bl

# 4b: C == Python at depth 3 (Python is slow, so slices), and the loop restore still holds
for name, pcm in signals().items():
    part = pcm[4900:5300] if name == "silence_then_burst" else pcm[:400]
    loop = len(part) // 3
    py = H.encode_stereo(part, loop, 3)
    c, err = c_encode(part, loop, 3)
    check("encoder C == Python (depth 3): %s" % name, c is not None and c == py,
          err or "bytes/states differ")
    full = decode(py[0], py[1])
    check("loop restore replays the first pass exactly (depth 3): %s" % name,
          decode(py[0], py[2], loop) == full[loop:])

# 4c: on the full signals, depth 3 is never worse than greedy and still meets the floor
for name, pcm in signals().items():
    c, err = c_encode(pcm, len(pcm) // 3, 3)
    if c is None:
        check("depth 3 encode: %s" % name, False, err)
        continue
    s = snr(pcm, decode(c[0], c[1]))
    check("depth 3 SNR %s = %.1f dB (greedy %.1f, floor %.0f)"
          % (name, s, greedy_snr[name], FLOOR[name]),
          s >= FLOOR[name] and s >= greedy_snr[name] - 0.05)

# 3
def div255(a):
    """the hardware's /255 of a non-negative product (hd3_audio)"""
    q = a + 1
    return ((q << 8) + q + (q >> 8)) >> 16


def hw_vol(p, f=div255):
    q = f(abs(p))
    return -q if p < 0 else q

prods = set()
for v in range(256):
    for x in range(32769):
        prods.add(x * v)
bad = [p for p in prods if div255(p) != p // 255]
check("hardware /255 == truncating /255 over %d products" % len(prods), not bad,
      "first bad %s" % bad[:3])
for x, v in ((-32768, 255), (-1, 1), (-254, 1), (-255, 1), (32767, 128), (-32768, 128)):
    check("vol(%d,%d) == hw form" % (x, v), H.vol(x, v) == hw_vol(x * v))
check("negative control: (p * 0x8081) >> 23 is NOT exact",
      any(((p * 0x8081) >> 23) != p // 255 for p in prods))

# negative controls
saved = H.STEP
H.STEP = tuple(s ^ (1 if i == 40 else 0) for i, s in enumerate(saved))
pcm = signals()["sine"]
bad_py = H.encode_stereo(pcm, 0)
H.STEP = saved
c, _ = c_encode(pcm, 0, 0)
check("negative control: altered step table is detected", c is not None and c != bad_py)
check("negative control: /256 differs from /255",
      any((p >> 8) != p // 255 for p in (255, 510, 8355840)))

print("ALL PASS" if not fails else "%d FAILED" % fails)
sys.exit(1 if fails else 0)
