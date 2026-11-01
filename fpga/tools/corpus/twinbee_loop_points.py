"""twinbee_loop_points.py <pack dir> : sample-exact loop points for TwinBee's n27 (where n24's
body starts inside it) and n32 (where its music starts after the silent lead that n31 covers).
Result for pack a048 (2026-10-29): n27 loops at sample 294741 (6.68347 s, correlation 0.995 with
n24 across the whole file); n32 loops at 153873 (3.48918 s; n31 is 153914 samples long).
Decodes at the files' native 44100 Hz (no resample), coarse envelope cross-correlation, then
refines the n27 lag sample by sample on the raw waveform."""
import os, struct, subprocess, sys, tempfile
import numpy as np
EXE = "C:/Users/miste/OneDrive/Desktop/MiSTerOrganize/MiSTerFrontier/NES_HDPack/tools/audio/oggdecode.exe"
d = sys.argv[1]; R = 44100
def granule(n):
    b = open(os.path.join(d, f"n{n}.ogg"), "rb").read(); j = b.rfind(b"OggS")
    return struct.unpack("<q", b[j + 6:j + 14])[0]
def load(n):
    out = os.path.join(tempfile.mkdtemp(), "x.raw")
    subprocess.run([EXE, "render", os.path.join(d, f"n{n}.ogg"), out, str(R), "0"], capture_output=True, check=True)
    return np.fromfile(out, dtype="<i2").reshape(-1, 2).astype(np.float64)
a27, a24, a32 = load(27), load(24), load(32)
m27, m24 = a27.mean(1), a24.mean(1)
f = 8
ea = m27[: len(m27) // f * f].reshape(-1, f).mean(1); eb = m24[: len(m24) // f * f].reshape(-1, f).mean(1)
n = 1
while n < len(ea) + len(eb): n <<= 1
c = np.fft.irfft(np.fft.rfft(ea, n) * np.conj(np.fft.rfft(eb, n)), n)
coarse = int(np.argmax(c[: len(ea)])) * f
best = None
W = R * 20
for lag in range(coarse - 400, coarse + 401):
    x, y = m27[lag:lag + W], m24[:W]
    cc = float(np.dot(x, y) / (np.linalg.norm(x) * np.linalg.norm(y)))
    if best is None or cc > best[1]: best = (lag, cc)
lag, cc = best
diff = np.abs(a27[lag:lag + W] - a24[:W])
print(f"n27 decoded {len(a27)} samples (granule {granule(27)}); n24 body starts at sample {lag} "
      f"= {lag / R:.5f}s, corr {cc:.5f}, mean|diff| {diff.mean():.1f}, max|diff| {diff.max():.0f}")
for t in (0, 20, 40, 60):
    s = int(t * R); m = min(len(m27) - lag, len(m24)) - R
    if s < m:
        x, y = m27[lag + s:lag + s + R], m24[s:s + R]
        print(f"   t={t:2d}s corr {np.dot(x, y) / (np.linalg.norm(x) * np.linalg.norm(y) + 1e-9):.5f}")
amp = np.abs(a32).max(1)
first = int(np.argmax(amp > 64))
print(f"n32 decoded {len(a32)} samples (granule {granule(32)}); lead silence ends at sample {first} "
      f"= {first / R:.5f}s; n31 length {granule(31)} samples = {granule(31) / R:.5f}s")
print(f"n32 peak in first {first} samples: {amp[:first].max() if first else 0:.0f}")
