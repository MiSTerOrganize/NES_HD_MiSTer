"""Check rommatch.py (which <patch> applies to a ROM) and the pack model's two extensions beyond
Mesen (MD5 lines, pack_fixes.py file names):

  1. the forms: an NES 2.0 file gets an iNES 1.0 form (bytes 7-15 zero, nothing else changed);
     a file already in that form, or without an iNES header, gets none;
  2. order: the file before its iNES 1.0 form, SHA1 before MD5 - in find() and core_lookup();
  3. section_keys: SHA1 lines kept, MD5 lines resolved per form, a SHA1 line wins a clash;
  4. why the patch must be built from the form that matched: a BPS made against the iNES 1.0
     file refuses the NES 2.0 file (source CRC) and builds from its iNES 1.0 form;
  5. real packs: Mega Man Super a030 (pack_fixes) and Ninja Gaiden a037 (MD5 line) load with
     the extension, and Mesen's own patch set and error log are unchanged.

    python -I test_rommatch.py [extract root]
"""
import hashlib
import os
import sys
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import hdp3_patch as H          # noqa: E402
import hdpack_model as M        # noqa: E402
import rommatch as R            # noqa: E402
import rompatch                 # noqa: E402

X = sys.argv[1] if len(sys.argv) > 1 else "Z:/NES_HDPack_work/x"
fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  {detail}"))
    fails += not ok


def sha(b):
    return hashlib.sha1(b).hexdigest().upper()


def md5(b):
    return hashlib.md5(b).hexdigest().upper()


body = bytes((i * 37 + 11) & 0xFF for i in range(32768 + 8192))
nes2 = b"NES\x1a" + bytes([2, 1, 0x10, 0x08, 0, 0, 0x07, 0, 0, 0, 0, 0]) + body   # NES 2.0
ines = nes2[:7] + bytes(9) + nes2[16:]

# 1. forms
f = R.ines1(nes2)
check("ines1 zeroes exactly bytes 7-15", f == ines and f[:7] == nes2[:7] and f[16:] == nes2[16:])
check("ines1 of an iNES 1.0 file is None", R.ines1(ines) is None)
check("ines1 of a non-iNES file is None", R.ines1(b"\x00" * 64) is None)
check("forms order", [l for l, _ in R.forms(nes2)] == [R.FORM_RAW, R.FORM_INES1])
check("forms of iNES 1.0 file: just the file", [l for l, _ in R.forms(ines)] == [R.FORM_RAW])

# 2. order
both = {sha(nes2): "raw.ips", sha(ines): "ines1.ips"}
check("find: file before its iNES 1.0 form", R.find(nes2, both)[1] == "raw.ips")
check("find: iNES 1.0 form when only it is named", R.find(nes2, {sha(ines): "x"})[1:] == ("x", R.FORM_INES1))
check("find: source is the matched form", R.find(nes2, {sha(ines): "x"})[0] == ines)
check("find: SHA1 before MD5 in one form",
      R.find(nes2, {sha(nes2): "s"}, {md5(nes2): "m"})[1] == "s")
check("find: raw MD5 before iNES 1.0 SHA1",
      R.find(nes2, {sha(ines): "s"}, {md5(nes2): "m"})[1] == "m")
check("find: no match", R.find(nes2, {"0" * 40: "x"}, {"0" * 32: "y"}) is None)
check("core_lookup: file first", R.core_lookup(nes2, {sha(nes2), sha(ines)})[1] == sha(nes2))
check("core_lookup: then iNES 1.0", R.core_lookup(nes2, {sha(ines)})[:2] == (ines, sha(ines)))
check("core_lookup: no match", R.core_lookup(nes2, {"0" * 40}) is None)

# 3. section_keys / resolve_md5
idx = [dict(path="a", sha1=sha(nes2).lower(), md5=md5(nes2).lower(),
            ines1_sha1=sha(ines).lower(), ines1_md5=md5(ines).lower())]
check("resolve_md5 raw", R.resolve_md5(md5(nes2), idx) == [sha(nes2)])
check("resolve_md5 iNES 1.0", R.resolve_md5(md5(ines), idx) == [sha(ines)])
check("resolve_md5 unknown", R.resolve_md5("0" * 32, idx) == [])
k = R.section_keys({sha(ines): "line.ips"}, {md5(ines): "md5.ips"}, idx)
check("section_keys: SHA1 line wins a clash", k == {sha(ines): "line.ips"}, str(k))
k = R.section_keys({}, {md5(ines): "md5.ips"}, idx)
check("section_keys: MD5 keyed by the form's SHA1", k == {sha(ines): "md5.ips"}, str(k))
check("section_keys: no index drops MD5", R.section_keys({}, {md5(ines): "m"}, None) == {})
# a library ROM with no NES 2.0 header (ines1 columns = the file) must not double up
idx1 = [dict(path="b", sha1=sha(ines).lower(), md5=md5(ines).lower(),
             ines1_sha1=sha(ines).lower(), ines1_md5=md5(ines).lower())]
check("resolve_md5 no duplicate for an iNES 1.0 file", R.resolve_md5(md5(ines), idx1) == [sha(ines)])


# 4. a BPS against the iNES 1.0 file
def vlq(n):
    out = bytearray()
    while True:
        x = n & 0x7F
        n >>= 7
        if n == 0:
            out.append(0x80 | x)
            return bytes(out)
        out.append(x)
        n -= 1


tgt = bytearray(ines)
tgt[100:104] = b"HDPK"
cmds = vlq(((100 - 1) << 2) | 0) + vlq(((4 - 1) << 2) | 1) + b"HDPK" + \
       vlq(((len(ines) - 104 - 1) << 2) | 0)
p = b"BPS1" + vlq(len(ines)) + vlq(len(tgt)) + vlq(0) + cmds
p += zlib.crc32(ines).to_bytes(4, "little") + zlib.crc32(bytes(tgt)).to_bytes(4, "little")
p += zlib.crc32(p).to_bytes(4, "little")
try:
    rompatch.apply(nes2, p)
    raw_refused = False
except rompatch.PatchError:
    raw_refused = True
check("BPS made on iNES 1.0 refuses the NES 2.0 file", raw_refused)
e = H.parse(H.section([(sha(ines).lower(), H.compile_patch(p))]))[0]
src, s, _ = R.core_lookup(nes2, {e["sha1"]})
check("hardware model builds it from the iNES 1.0 form", H.build(e, src) == bytes(tgt))
check("hardware model refuses the raw NES 2.0 file", H.build(e, nes2) is None)

# 5. real packs
a030 = os.path.join(X, "a030", "HdPacks", "Mega Man Super")
if os.path.isdir(a030):
    pk = M.load(a030)
    key = "2F88381557339A14C20428455F6991C1EB902C99"
    check("a030: fixed patch name used", pk.patches.get(key, "").endswith("Megaman - Super.ips"),
          str(pk.patches))
    check("a030: Mesen's 'not found' still logged",
          any("Patch file not found" in m for _l, m in pk.errors))
    check("a030: the fix is reported", any("pack_fixes" in w for _l, w in pk.compat))
else:
    print("SKIP a030 (no extract)")
a037 = os.path.join(X, "a037")
if os.path.isdir(a037):
    from hdp3_convert import load_pack                       # a037 is built over a036
    pk = load_pack(a037, [os.path.join(X, "a036", "Ninja Gaiden (USA)")])
    check("a037: MD5 line kept for the core", len(pk.patches_md5) == 1, str(pk.patches_md5))
    check("a037: MD5 line not in Mesen's set", not pk.patches, str(pk.patches))
    check("a037: Mesen's 'Invalid SHA1' still logged",
          any("Invalid SHA1" in m for _l, m in pk.errors))
else:
    print("SKIP a037 (no extract)")

print("ALL PASS" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)
