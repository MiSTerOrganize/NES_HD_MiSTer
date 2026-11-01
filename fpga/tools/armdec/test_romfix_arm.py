"""Host test of romfix_arm.c (the ARM half of the ROM patcher), loaded through ctypes:

  1. the build: test_hdp3_patch.py's whole battery (corpus <patch> lines with their library ROM,
     300 synthetic IPS/BPS/UPS, the refusals) runs with hdp3_patch.build REPLACED by the C build,
     so every target must equal rompatch.apply byte for byte;
  2. SHA-1: rf_sha1 against hashlib for every length 0..300 and some large ones;
  3. the decision (rf_decide): the file's own SHA1 first, then its iNES 1.0 form (bytes 7-15 0)
     only for an iNES file with something there; the build from the form that matched; refusal
     codes; content-driven "replay the original"; a status answered once.

    python -I test_romfix_arm.py [corpus dir] [library dir]     (ROMFIX_C: a mutant copy)
"""
import ctypes
import hashlib
import os
import random
import struct
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
sys.path.insert(0, TOOLS)
SRC = os.environ.get("ROMFIX_C", os.path.join(HERE, "romfix_arm.c"))
OUT = os.environ.get("ROMFIX_DLL", os.path.join(TOOLS, "sim3", "obj", "romfix_arm.dll"))
os.makedirs(os.path.dirname(OUT), exist_ok=True)
env = dict(os.environ, PATH="C:/msys64/mingw64/bin;" + os.environ.get("PATH", ""))
r = subprocess.run(["C:/msys64/mingw64/bin/gcc.exe", "-O2", "-shared", "-I" + HERE, "-o", OUT, SRC], env=env,
                   capture_output=True, text=True)
if r.returncode:
    print(r.stderr)
    sys.exit(2)
os.add_dll_directory("C:/msys64/mingw64/bin")
C = ctypes.CDLL(OUT)
P = ctypes.c_char_p
C.rf_build.restype = ctypes.c_uint32
C.rf_build.argtypes = [P, ctypes.c_uint32, P, P, ctypes.c_uint32, ctypes.c_int, ctypes.c_void_p,
                       ctypes.POINTER(ctypes.c_int)]
C.rf_decide.restype = ctypes.c_int
C.rf_decide.argtypes = [ctypes.c_void_p, ctypes.c_uint64, P, P, ctypes.c_uint32, ctypes.c_void_p,
                        ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(ctypes.c_uint64)]
C.rf_sha1.argtypes = [P, ctypes.c_size_t, ctypes.c_void_p]
C.rf_pending.restype = ctypes.c_int
C.rf_pending.argtypes = [ctypes.c_void_p, ctypes.c_uint64]
C.rf_session_check.restype = ctypes.c_int
C.rf_session_check.argtypes = [ctypes.c_void_p, ctypes.c_uint64]
MAXB = 0x400000
TGT = ctypes.create_string_buffer(MAXB)

import hdp3_patch as H        # noqa: E402
import test_hdp3_patch as T   # noqa: E402


def c_build(e, src, p2=0):
    """hdp3_patch.build's contract, by the C build: target bytes or None."""
    sec = H.section([("00" * 20, e)])
    why = ctypes.c_int()
    n = C.rf_build(sec, len(sec), sec[64:128], bytes(src), len(src), p2, TGT, ctypes.byref(why))
    return TGT.raw[:n] if n else None


fails = 0


def check(name, ok, detail=""):
    global fails
    if not ok:
        fails += 1
        print(f"FAIL {name} {detail}")


def sha_tests():
    rng = random.Random(5)
    for n in list(range(301)) + [4095, 4096, 4097, 65536 + 17, 262160]:
        d = bytes(rng.randint(0, 255) for _ in range(n))
        o = ctypes.create_string_buffer(20)
        C.rf_sha1(d, n, o)
        check(f"sha1 len {n}", o.raw == hashlib.sha1(d).digest())
    print("sha1: checked")


class St(ctypes.Structure):     # rf_state
    _fields_ = [("have", ctypes.c_int), ("rseq", ctypes.c_uint8), ("aseq", ctypes.c_uint8),
                ("id", ctypes.c_uint8), ("hashed", ctypes.c_int), ("hrseq", ctypes.c_uint8),
                ("sha_raw", ctypes.c_uint8 * 20), ("sha_n", ctypes.c_uint8 * 20),
                ("n_cand", ctypes.c_int)]


def status(rseq, aseq, L, active=1, content=0, staged=1, last=0):
    return (0xA6 << 56 | rseq << 48 | aseq << 40 | last << 32 | active << 31 | 1 << 30 |
            content << 28 | staged << 27 | L)


def decide(st, s, rom, sec):
    tl = ctypes.c_uint32()
    cmd = ctypes.c_uint64()
    w = C.rf_decide(ctypes.byref(st), s, rom, sec if sec else None, len(sec) if sec else 0, TGT,
                    ctypes.byref(tl), ctypes.byref(cmd))
    c = cmd.value
    return w, (c >> 30) & 3, (c >> 27) & 7, c & 0xFFFFFF, TGT.raw[:tl.value], c


def decision_tests():
    rng = random.Random(9)
    base = bytes(rng.randint(0, 255) for _ in range(8000))
    nes2 = b"NES\x1a" + bytes([2, 1, 0, 0x08]) + bytes([0, 0, 0, 0, 0, 0, 0, 1]) + base
    ines1 = nes2[:7] + bytes(9) + nes2[16:]
    plain = b"XYZ!" + nes2[4:]                       # no magic: never a second pass
    p_raw, p_n = T.ips(rng, len(nes2)), T.bps(rng, ines1)
    want_raw = T.rompatch.apply(nes2, p_raw)
    want_n = T.rompatch.apply(ines1, p_n)
    sec_n = H.section([(hashlib.sha1(ines1).hexdigest(), H.compile_patch(p_n))])
    sec_both = H.section([(hashlib.sha1(ines1).hexdigest(), H.compile_patch(p_n)),
                          (hashlib.sha1(nes2).hexdigest(), H.compile_patch(p_raw))])
    st = St()
    w, a, res, n, tgt, c = decide(st, status(1, 1, len(nes2)), nes2, sec_n)
    check("iNES 1.0 form matched and built from that form", w == 1 and a == 1 and res == 1 and tgt == want_n)
    w2 = decide(st, status(1, 1, len(nes2)), nes2, sec_n)[0]
    check("a status is answered once", w2 == 0)
    st = St()
    w, a, res, n, tgt, c = decide(st, status(1, 1, len(nes2)), nes2, sec_both)
    check("the file's own entry wins over its iNES 1.0 entry", a == 1 and tgt == want_raw)
    st = St()
    _, a, res, *_ = decide(st, status(1, 1, len(plain)), plain, H.section(
        [(hashlib.sha1(b"NES\x1a" + plain[4:7] + bytes(9) + plain[16:]).hexdigest(), H.compile_patch(p_n))]))
    check("no magic: no second pass", a == 0 and res == 2)
    st = St()
    _, a, res, *_ = decide(st, status(1, 1, len(ines1)), ines1, sec_n)
    check("already the iNES 1.0 form: matched on the first pass", a == 1 and res == 1)
    st = St()
    _, a, res, *_ = decide(st, status(1, 1, len(nes2), active=0, content=1), nes2, sec_n)
    check("pack off while patched: replay the original", a == 2 and res == 2)
    st = St()
    _, a, res, *_ = decide(st, status(1, 1, len(nes2), content=0), b"\0" * len(nes2), sec_n)
    check("no match, original held: nothing to replay", a == 0 and res == 2)
    # refusals: CRC (a BPS against a damaged target) and a bad run mode
    comp = H.compile_patch(p_n)
    bad = dict(comp, crc=comp["crc"] ^ 1)
    st = St()
    _, a, res, *_ = decide(st, status(1, 1, len(nes2), content=1), nes2,
                           H.section([(hashlib.sha1(ines1).hexdigest(), bad)]))
    check("CRC refused: original replayed, result 4", a == 2 and res == 4)
    badm = dict(comp, runs=[(t, n2, a2, 7) for t, n2, a2, _ in comp["runs"][:1]] + list(comp["runs"][1:]))
    st = St()
    _, a, res, *_ = decide(st, status(1, 1, len(nes2)), nes2,
                           H.section([(hashlib.sha1(ines1).hexdigest(), badm)]))
    check("run mode 7 refused, result 3", a == 0 and res == 3)
    # id never equals the FPGA's last id
    st = St()
    *_, c = decide(st, status(1, 1, len(nes2), last=1), nes2, sec_n)
    check("command id skips the last id", (c >> 32) & 0xFF != 1)
    # a new ROM (rseq 2) on the same state is hashed again, not decided on the old ROM's SHA1
    st = St()
    other = bytes(rng.randint(0, 255) for _ in range(len(nes2)))
    decide(st, status(1, 1, len(other)), other, sec_n)
    _, a, res, _, tgt, _ = decide(st, status(2, 1, len(nes2)), nes2, sec_n)
    check("a new ROM is hashed again", a == 1 and tgt == want_n)
    # an entry past the section's end is never matched, even with the bytes there
    s1 = H.section([(hashlib.sha1(b"x").hexdigest(), H.compile_patch(p_n))])
    two = bytearray(s1 + H.section([(hashlib.sha1(ines1).hexdigest(), H.compile_patch(p_n))])[64:])
    two[0:4] = struct.pack("<I", 2)
    buf = ctypes.create_string_buffer(bytes(two), len(two))
    tl, cmd = ctypes.c_uint32(), ctypes.c_uint64()
    st = St()
    C.rf_decide(ctypes.byref(st), status(1, 1, len(ines1)), ines1, buf, 64 + 64, TGT,
                ctypes.byref(tl), ctypes.byref(cmd))
    check("no entry is read past the section",
          (cmd.value >> 30) & 3 == 0 and (cmd.value >> 27) & 7 == 2)
    # the command carries the target's length
    st = St()
    w, a, res, n, tgt, c = decide(st, status(1, 1, len(nes2)), nes2, sec_n)
    check("the command reports the target length", n == len(want_n) and len(tgt) == len(want_n))
    # an iNES file whose bytes 7-15 are already 0 is hashed once (no second form)
    st = St()
    decide(st, status(1, 1, len(ines1)), ines1, sec_n)
    check("bytes 7-15 already 0: no second form", st.n_cand == 0)
    print("decisions: checked")


def entry(sha, base, flags, ssz, tsz, trunc, crc, roff, rn, doff, dlen):
    e = sha + bytes([base, flags, 0, 0]) + struct.pack("<10I", ssz, tsz, trunc, crc, roff, rn, doff, dlen,
                                                        0, 0)
    return e[:64]


def bounds_tests():
    """hand-built sections, so each bound is the only thing that refuses"""
    src = bytes(range(256)) * 4
    sha = hashlib.sha1(src).digest()
    st_ = status(1, 1, len(src))

    def run(sec, plen):
        st = St()
        buf = ctypes.create_string_buffer(bytes(sec), len(sec))
        tl, cmd = ctypes.c_uint32(), ctypes.c_uint64()
        C.rf_decide(ctypes.byref(st), st_, src, buf, plen, TGT, ctypes.byref(tl), ctypes.byref(cmd))
        return (cmd.value >> 27) & 7
    hdr = struct.pack("<I", 1) + bytes(60)
    # a run table that ends one byte past the section: refused, even with the bytes in memory
    fill = struct.pack("<IIIB3x", 0, 4, 0x55, 4)
    sec = hdr + entry(sha, 1, 0, 0, len(src), 0, 0, 128, 1, 0, 0) + fill
    check("run table inside the section: built", run(sec, len(sec)) == 1)
    check("run table past the section: refused", run(sec, len(sec) - 1) == 3)
    # the literal data one byte past the section: refused
    lit = struct.pack("<IIIB3x", 0, 4, 0, 0)
    sec = hdr + entry(sha, 1, 0, 0, len(src), 0, 0, 128, 1, 144, 4) + lit + b"\1\2\3\4"
    check("data inside the section: built", run(sec, len(sec)) == 1)
    check("data past the section: refused", run(sec, len(sec) - 1) == 3)
    # a run longer than the target stops at the target's end
    sec = hdr + entry(sha, 1, 0, 0, 10, 0, 0, 128, 1, 0, 0) + struct.pack("<IIIB3x", 0, 100, 0x77, 4)
    ctypes.memset(TGT, 0xEE, 200)
    r = run(sec, len(sec))
    check("a run stops at the target's end", r == 1 and TGT.raw[:10] == b"\x77" * 10 and
          TGT.raw[10:100] == b"\xEE" * 90)
    # an entry past the section's end is never read (its SHA1 matches, its bytes are there)
    other = entry(hashlib.sha1(b"x").digest(), 1, 0, 0, len(src), 0, 0, 192, 1, 0, 0)
    real = entry(sha, 1, 0, 0, len(src), 0, 0, 192, 1, 0, 0)
    sec = struct.pack("<I", 2) + bytes(60) + other + real + fill
    check("second entry inside the section: matched", run(sec, len(sec)) == 1)
    check("second entry past the section: not read", run(sec, 128) == 2)
    # records whose bytes add up past 16 x 4 MB: refused, not built (a malformed table could
    # otherwise keep the ARM busy for hours); a table just under the budget builds
    big = 0x400000
    rec = struct.pack("<IIIB3x", 0, big, 0x5A, 4)
    sec = hdr + entry(sha, 1, 0, 0, big, 0, 0, 128, 16, 0, 0) + rec * 16
    check("records within the byte budget: built", run(sec, len(sec)) == 1)
    sec = hdr + entry(sha, 1, 0, 0, big, 0, 0, 128, 17, 0, 0) + rec * 17
    check("records past the byte budget: refused", run(sec, len(sec)) == 3)
    print("bounds: checked")


def session_tests():
    """a core reload: hd3_romfix clears the command qword at power-up, and this side, having
    answered {1, 1} before, must answer the new session's {1, 1} again"""
    src = bytes(range(256)) * 4
    st = St()
    decide(st, status(1, 1, len(src)), src, b"")
    check("answered: the same status is not pending again", C.rf_pending(ctypes.byref(st), status(1, 1, len(src))) == 0)
    check("a non-zero command: no new session", C.rf_session_check(ctypes.byref(st), 0xC7 << 56) == 0)
    check("a cleared command: a new session", C.rf_session_check(ctypes.byref(st), 0) == 1)
    check("after a new session {1, 1} is pending", C.rf_pending(ctypes.byref(st), status(1, 1, len(src))) == 1)
    st = St()
    check("nothing answered yet: a cleared command changes nothing", C.rf_session_check(ctypes.byref(st), 0) == 0)
    print("session: checked")


def fixture_tests():
    """every hd3_romfix co-sim case (tools/sim3/romfix_cases.py), one pack, through rf_decide:
    the result code, and the target bytes where the case patches"""
    sys.path.insert(0, os.path.join(TOOLS, "sim3"))
    import romfix_cases as RC
    n = 0
    for name, pack, rom, exp, res, loads, extra in RC.CASES:
        if "--pack2" in extra or "--arm" in extra:
            continue                          # second pack / the ARM's absence: not a decision
        pk, rb, eb = (open(p, "rb").read() for p in (pack, rom, exp))
        o14, n14 = struct.unpack_from("<II", pk, 0xF0)
        sec = pk[o14:o14 + n14] if n14 else b""
        st = St()
        w, a, r, ln, tgt, _ = decide(st, status(1, 1, len(rb)), rb, sec)
        ok = w == 1 and r == res and (tgt == eb if res == 1 else (a == 0 and eb == rb))
        check(f"fixture {name}", ok, f"result {r} want {res}, action {a}")
        n += 1
    print(f"fixtures: {n} cases checked")


if __name__ == "__main__":
    sha_tests()
    decision_tests()
    bounds_tests()
    session_tests()
    fixture_tests()
    if "--quick" in sys.argv:                 # (the mutant runner: the battery below is ~2 min)
        print("ALL PASS" if not fails else f"{fails} FAILURES")
        sys.exit(1 if fails else 0)
    H.build = c_build                 # test_hdp3_patch's battery, through the C build
    T.H.build = c_build
    T.corpus()
    T.synthetic()
    T.refusals()
    fails += T.fails
    print("ALL PASS" if not fails else f"{fails} FAILURES")
    sys.exit(1 if fails else 0)
