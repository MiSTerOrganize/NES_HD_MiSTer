"""Negative control for test_hdp3_patch.py: each mutant is one defect in hdp3_patch.py; the
test must fail on every one.

    python -I neg_patch.py
"""
import os
import shutil
import subprocess
import sys

TOOLS = os.path.dirname(os.path.abspath(__file__)).replace("\\", "/")
WORK = os.path.join(TOOLS, "sim3", "obj", "neg_patch")

M = [
    ("ips_first_record_wins", 'owner[off + k] = ("lit", base + k)',
     'owner.setdefault(off + k, ("lit", base + k))'),
    ("ips_no_truncation", "size = min(size, e[\"trunc\"])", "pass"),
    ("ips_size_not_from_src", "size = max(len(src), size)", "pass"),
    ("bps_target_copy_from_source", "b = out[a + k]", "b = s(a + k)"),
    ("bps_source_copy_wrong_rel", "src_rel += length\n", "src_rel += length - 1\n"),
    ("ups_xor_ignored", "b = s(t + k) ^ data[a + k]", "b = data[a + k]"),
    ("fill_wrong_byte", "b = a & 0xFF", "b = (a + 1) & 0xFF"),
    ("crc_not_checked", 'if e["flags"] & F_CRC and zlib.crc32(out) != e["crc"]:', "if False:"),
    ("src_size_not_checked", 'if e["flags"] & F_SRCSIZE and len(src) != e["src_size"]:', "if False:"),
    ("past_source_not_zero", "s = lambda i: src[i] if i < len(src) else 0",
     "s = lambda i: src[i] if i < len(src) else 0xFF"),
    ("merge_breaks_lit", "and r[2] == p[2] + p[1]):", "):"),
    ("parse_runs_off_by_one", "roff + 16 * j)", "roff + 16 * j + 16)"),
    ("section_no_pad", "return bytes(b) + bytes(-len(b) % 64)", "return bytes(b)"),
]


def main():
    caught = 0
    for name, old, new in M:
        d = os.path.join(WORK, name)
        shutil.rmtree(d, ignore_errors=True)
        os.makedirs(d)
        for f in ("rompatch.py", "test_hdp3_patch.py"):
            shutil.copy(os.path.join(TOOLS, f), d)
        with open(os.path.join(TOOLS, "hdp3_patch.py"), encoding="utf-8") as f:
            s = f.read()
        n = s.count(old)
        if n != 1:
            print(f"{name}: ANCHOR x{n}")
            continue
        with open(os.path.join(d, "hdp3_patch.py"), "w", encoding="utf-8", newline="") as f:
            f.write(s.replace(old, new))
        r = subprocess.run([sys.executable, "-I", os.path.join(d, "test_hdp3_patch.py")],
                           capture_output=True, text=True)
        ok = r.returncode != 0
        caught += ok
        print(f"{name}: {'CAUGHT' if ok else 'MISSED'}", flush=True)
    print(f"{caught} of {len(M)} caught")


main()
