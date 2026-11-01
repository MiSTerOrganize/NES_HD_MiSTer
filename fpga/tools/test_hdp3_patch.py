"""Check hdp3_patch (the section-14 compiler and its hardware model) against rompatch.apply,
byte for byte:

  1. every <patch> line in the corpus whose source ROM is in the library: the real patch, the
     real ROM, written to section 14 and parsed back the way the hardware reads it;
  2. synthetic IPS (overlapping records, RLE, records past the source's end, truncation),
     BPS (every action, overlapping TargetCopy) and UPS (growing and shrinking) on random ROMs;
  3. the refusals: wrong source (size or CRC), a damaged patch, a damaged section -> unpatched.

    python -I test_hdp3_patch.py [corpus dir] [library dir]
"""
import glob
import hashlib
import os
import random
import struct
import sys
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import hdp3_patch as H          # noqa: E402
import rompatch                 # noqa: E402

X = sys.argv[1] if len(sys.argv) > 1 and __name__ == "__main__" else "Z:/NES_HDPack_work/x"
ROMS = (sys.argv[2] if len(sys.argv) > 2 and __name__ == "__main__"
        else "Z:/MiSTer_Organize/RomRoot/MiSTer_Console/MiSTer_Console/games/NES")
fails = 0


def check(name, ok, detail=""):
    global fails
    if not ok:
        fails += 1
        print(f"FAIL {name} {detail}")


def through_section(sha, comp):
    """Write one entry to section 14 and read it back as the hardware would."""
    sec = H.section([(sha, comp)])
    check("section 64-aligned", len(sec) % 64 == 0, str(len(sec)))
    e = H.parse(sec)
    check("parse count", len(e) == 1)
    return e[0]


def same(name, rom, patch, sha="00" * 20):
    try:
        want = rompatch.apply(rom, patch)
    except rompatch.PatchError:
        want = None
    try:
        e = through_section(sha, H.compile_patch(patch))
        got = H.build(e, rom)
    except rompatch.PatchError:
        got = None
    if want != got:
        where = ""
        if want is not None and got is not None:
            n = min(len(want), len(got))
            d = next((i for i in range(n) if want[i] != got[i]), n)
            where = f"len {len(want)} vs {len(got)}, first diff at {d}"
        check(name, False, f"want {'refused' if want is None else 'ok'}, got "
              f"{'refused' if got is None else 'ok'} {where}")
        return False
    return want is not None


# ---------------------------------------------------------------- 1. corpus
def corpus():
    """Every <patch> line (SHA1 or MD5) whose ROM is in the library in either form the core
    tries (rommatch: the file, then its iNES 1.0 form), applied to THAT form."""
    import rommatch
    import pack_fixes
    lib = {}                                   # hash upper -> (file path, form label)
    for p in glob.glob(ROMS + "/**/*.nes", recursive=True):
        if os.path.getsize(p) > 0x400000:      # past the 4 MB the core stages: never patched
            continue
        with open(p, "rb") as f:
            d = f.read()
        for label, c in rommatch.forms(d):     # only the hashes are kept: the bytes of every
            for hx in (hashlib.sha1(c).hexdigest().upper(),   # form of every ROM do not fit
                       hashlib.md5(c).hexdigest().upper()):
                lib.setdefault(hx, (p, label))

    def form_of(p, label):
        with open(p, "rb") as f:
            return dict(rommatch.forms(f.read()))[label]
    tested = applied = by_form = 0
    for h in sorted(glob.glob(X + "/**/hires.txt", recursive=True)):
        d = os.path.dirname(h)
        with open(h, encoding="utf-8", errors="replace") as f:
            lines = [l.strip() for l in f if l.strip().lower().startswith("<patch>")]
        for l in lines:
            parts = [t.strip() for t in l[len("<patch>"):].rsplit(",", 1)]
            if len(parts) < 2:
                continue
            sha = parts[1].upper()
            pp = os.path.join(d, parts[0])
            if not os.path.exists(pp):
                for fx in pack_fixes.PATCH_FILE_FIXES:
                    if fx["named"].lower() == parts[0].lower() and fx["hash"] == sha:
                        pp = os.path.join(d, fx["actual"])
            if sha not in lib or not os.path.exists(pp):
                continue
            with open(pp, "rb") as f:
                patch = f.read()
            path, label = lib[sha]
            rom = form_of(path, label)
            tested += 1
            by_form += label != rommatch.FORM_RAW
            if same(f"corpus {os.path.relpath(d, X)}/{parts[0]}{label}", rom, patch,
                    hashlib.sha1(rom).hexdigest()):
                applied += 1
    print(f"corpus: {tested} patch lines with their ROM ({by_form} through the iNES 1.0 form "
          f"or an MD5), {applied} applied, all identical to rompatch"
          if not fails else f"corpus: {tested} tested")
    check("corpus found lines", tested >= 20, str(tested))
    check("corpus reaches iNES 1.0 / MD5 lines", by_form >= 10, str(by_form))


# ---------------------------------------------------------------- 2. synthetic
def vlq(n):
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n == 0:
            out.append(b | 0x80)
            return bytes(out)
        out.append(b)
        n -= 1


def tail(src, dst, body):
    body += struct.pack("<II", zlib.crc32(src), zlib.crc32(dst))
    return body + struct.pack("<I", zlib.crc32(body))


def ips(rng, n_src):
    p = bytearray(b"PATCH")
    for _ in range(rng.randint(1, 30)):
        off = rng.randint(0, n_src + 4000)
        if off == 0x454F46:
            off += 1
        if rng.random() < 0.3:
            size = rng.randint(1, 600)
            p += off.to_bytes(3, "big") + b"\0\0" + size.to_bytes(2, "big") + bytes([rng.randint(0, 255)])
        else:
            size = rng.randint(1, 300)
            p += off.to_bytes(3, "big") + size.to_bytes(2, "big") + bytes(rng.randint(0, 255) for _ in range(size))
    p += b"EOF"
    if rng.random() < 0.3:
        p += rng.randint(0, n_src + 5000).to_bytes(3, "big")
    return bytes(p)


def bps(rng, src):
    """A random but valid BPS patch: build the target command by command, then sign it."""
    n_dst = rng.randint(1, 6000)
    dst = bytearray()
    cmds = bytearray()
    src_rel = dst_rel = 0
    while len(dst) < n_dst:
        o = len(dst)
        length = min(rng.randint(1, 200), n_dst - o)
        acts = [1]
        if o + length <= len(src):
            acts.append(0)
        if len(src) >= length:
            acts.append(2)
        if o > 0:
            acts.append(3)
        a = rng.choice(acts)
        cmds += vlq(((length - 1) << 2) | a)
        if a == 0:
            dst += src[o:o + length]
        elif a == 1:
            lit = bytes(rng.randint(0, 255) for _ in range(length))
            cmds += lit
            dst += lit
        elif a == 2:
            to = rng.randint(0, len(src) - length)
            d = to - src_rel
            cmds += vlq((abs(d) << 1) | (d < 0))
            dst += src[to:to + length]
            src_rel = to + length
        else:
            to = rng.randint(max(0, o - 300), o - 1)     # may overlap the bytes being written
            d = to - dst_rel
            cmds += vlq((abs(d) << 1) | (d < 0))
            for k in range(length):
                dst.append(dst[to + k])
            dst_rel = to + length
    body = bytearray(b"BPS1") + vlq(len(src)) + vlq(n_dst) + vlq(3) + b"abc" + cmds
    return tail(src, bytes(dst), body)


def ups(rng, src):
    n_dst = max(1, len(src) + rng.randint(-1000, 1000))
    dst = bytearray(src[:n_dst]) + bytearray(max(0, n_dst - len(src)))
    for _ in range(rng.randint(0, 40)):
        i = rng.randrange(n_dst)
        for k in range(rng.randint(1, 50)):
            if i + k < n_dst:
                dst[i + k] = rng.randint(0, 255)
    body = bytearray(b"UPS1") + vlq(len(src)) + vlq(n_dst)
    base = bytes(src[:n_dst]) + bytes(max(0, n_dst - len(src)))
    i = 0
    rel = 0
    while i < n_dst:
        if dst[i] == base[i]:
            i += 1
            continue
        body += vlq(i - rel)
        while i < n_dst and dst[i] != base[i]:
            body.append(dst[i] ^ base[i])
            i += 1
        body.append(0)
        i += 1
        rel = i
    return tail(src, bytes(dst), body)


def synthetic():
    rng = random.Random(1)
    n = 0
    for t in range(300):
        src = bytes(rng.randint(0, 255) for _ in range(rng.randint(1, 5000)))
        kind = t % 3
        p = ips(rng, len(src)) if kind == 0 else bps(rng, src) if kind == 1 else ups(rng, src)
        ok = same(f"synthetic {['IPS', 'BPS', 'UPS'][kind]} #{t}", src, p)
        n += ok
        check(f"synthetic {t} applied", ok or kind == 0)
    print(f"synthetic: 300 patches, {n} applied")


# ---------------------------------------------------------------- 3. refusals
def refusals():
    rng = random.Random(2)
    src = bytes(rng.randint(0, 255) for _ in range(3000))
    for name, gen in (("BPS", bps), ("UPS", ups)):
        p = gen(rng, src)
        e = through_section("00" * 20, H.compile_patch(p))
        check(f"{name} right source builds", H.build(e, src) is not None)
        check(f"{name} short source refused", H.build(e, src[:-1]) is None)
        bad = bytearray(src)
        bad[100] ^= 1
        # a same-size wrong ROM: the target CRC refuses it unless the byte is never used
        got = H.build(e, bytes(bad))
        if got is not None:
            check(f"{name} wrong source: identical result only if byte 100 unused",
                  got == rompatch.apply(src, p))
        dam = bytearray(p)
        dam[len(dam) // 2] ^= 0x40
        try:
            H.compile_patch(bytes(dam))
            check(f"{name} damaged patch refused", False)
        except rompatch.PatchError:
            pass
    # a damaged run (the section corrupted in DDR3) fails the BPS target CRC
    p = bps(rng, src)
    c = H.compile_patch(p)
    c["runs"] = [(t, n, a ^ 1, m) if i == 0 else (t, n, a, m) for i, (t, n, a, m) in enumerate(c["runs"])]
    e = through_section("00" * 20, c)
    check("damaged run refused by the CRC", H.build(e, src) is None or H.build(e, src) == rompatch.apply(src, p))
    # several entries in one section, each found and built
    ents = []
    roms = []
    for k in range(5):
        s = bytes(rng.randint(0, 255) for _ in range(1000 + k))
        q = [ips(rng, len(s)), bps(rng, s), ups(rng, s)][k % 3]
        ents.append((hashlib.sha1(s).hexdigest(), H.compile_patch(q)))
        roms.append((s, q))
    es = H.parse(H.section(ents))
    for k, e in enumerate(es):
        s, q = roms[k]
        check(f"multi-entry {k} sha", e["sha1"] == hashlib.sha1(s).hexdigest().upper())
        try:
            want = rompatch.apply(s, q)
        except rompatch.PatchError:
            want = None
        check(f"multi-entry {k} build", H.build(e, s) == want)
    print("refusals: checked")


if __name__ == "__main__":
    corpus()
    synthetic()
    refusals()
    print("ALL PASS" if not fails else f"{fails} FAILURES")
    sys.exit(1 if fails else 0)
