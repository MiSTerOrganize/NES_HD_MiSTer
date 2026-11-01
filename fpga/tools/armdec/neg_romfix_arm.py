"""Negative control for romfix_arm.c (the ARM half of the ROM patcher): each mutant is one
deliberate defect in a copy of the source, built into its own DLL and run against
test_romfix_arm.py - the quick part (SHA-1, decisions, every co-sim fixture), then, if that
misses it, the full patch battery. Every mutant must be CAUGHT.

    python -I neg_romfix_arm.py [only-name ...]     ->  ../sim3/obj/neg_romfix_arm.txt
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "romfix_arm.c")
WORK = os.path.join(HERE, "..", "sim3", "obj", "neg_romfix_arm")
TEST = os.path.join(HERE, "test_romfix_arm.py")

M = [
    # SHA-1 and the two passes
    ("sha_round_const", "k = 0x8F1BBCDC;", "k = 0x8F1BBCDD;"),
    ("sha_pad_boundary", "if (r >= 56) { sha1_block(h, blk); memset(blk, 0, 64); }",
     "if (r > 56) { sha1_block(h, blk); memset(blk, 0, 64); }"),
    ("pass2_range_short", "sha1_z(rom, L, 7, 15, st->sha_n);", "sha1_z(rom, L, 7, 14, st->sha_n);"),
    ("pass2_magic_unchecked", "st->n_cand = L >= 16 && !memcmp(rom, \"NES\\x1a\", 4);",
     "st->n_cand = L >= 16;"),
    ("pass2_header_zero_unchecked", "st->n_cand = nz != 0;", "st->n_cand = 1;"),
    ("no_second_pass", "if (ek < 0 && st->n_cand)", "if (0)"),
    ("second_pass_overrides", "if (ek < 0 && st->n_cand)", "if (st->n_cand)"),
    ("hash_not_redone", "if (!st->hashed || st->hrseq != st->rseq)", "if (!st->hashed)"),
    ("search_past_section", " || (uint64_t)ek * 64 + 128 > plen) return -1;", ") return -1;"),
    # the build
    ("size_from_src_ignored", "((flags & 2) && L > tsz) ? L : tsz", "tsz"),
    ("trunc_ignored", "((flags & 4) && trunc < szs) ? trunc : szs", "szs"),
    ("src_size_unchecked", "((flags & 8) && ssz != L) || ", ""),
    ("run_table_unchecked", "(uint64_t)roff + (uint64_t)rn * 16 > plen || ", ""),
    ("data_unchecked", "(uint64_t)doff + dlen > plen || ", ""),
    ("no_base_fill", "if (base & 1) for", "if (0) for"),
    ("past_source_not_zero", "#define SRCB(i) ((i) >= L || ", "#define SRCB(i) (0 || "),
    ("pass2_header_kept", "(p2 && (i) >= 7 && (i) <= 15)", "(0)"),
    ("mode_unchecked", "if (rm > 4) return 0;", ""),
    ("lit_unchecked", "case 0:  if (aidx >= dlen) return 0; b = data[aidx]; break;",
     "case 0:  b = data[aidx]; break;"),
    ("lit_reads_source", "case 0:  if (aidx >= dlen) return 0; b = data[aidx]; break;",
     "case 0:  b = SRCB(aidx); break;"),
    ("tgt_unchecked", "if (aidx >= tpos) return 0; b = tgt[aidx];", "b = tgt[aidx];"),
    ("xor_index_aidx", "case 3:  b = SRCB(tpos);", "case 3:  b = SRCB(aidx);"),
    ("xor_operand_dropped", "b ^= data[aidx];", "b = data[aidx];"),
    ("fill_byte_zero", "default: b = (uint8_t)ra; break;", "default: b = 0; break;"),
    ("run_stops_at_size", "if (ri + 1 >= n || tpos + 1 >= size) break;", "if (ri + 1 >= n) break;"),
    ("crc_unchecked", "if ((flags & 1) && crc32_of(tgt, size) != crc)", "if (0)"),
    ("record_budget_ignored", "        if (span > budget) return 0;\n", ""),
    ("session_never_reset", "    if (!st->have || cmd_now != 0) return 0;\n", "    return 0;\n"),
    ("session_reset_on_any_command", "    if (!st->have || cmd_now != 0) return 0;\n",
     "    if (!st->have) return 0;\n"),
    ("crc_init_zero", "uint32_t c = 0xFFFFFFFFu;", "uint32_t c = 0;"),
    # the decision and the command
    ("no_revert", "if (!action && RF_CONTENT(s) != 0) action = 2;", ""),
    ("id_not_skipped", "if (st->id == RF_LASTID(s)) st->id++;", ""),
    ("answered_twice", "return !st->have || RF_RSEQ(s) != st->rseq", "return 1 || RF_RSEQ(s) != st->rseq"),
    ("inactive_patched", "if (RF_ACTIVE(s) && s14 && s14_len >= 64)", "if (s14 && s14_len >= 64)"),
    ("len_not_reported", "(uint64_t)result << 27 | len;", "(uint64_t)result << 27;"),
    ("result_not_reported", "(uint64_t)action << 30 | (uint64_t)result << 27", "(uint64_t)action << 30 | 1ull << 27"),
]


def run(dll, quick):
    env = dict(os.environ, ROMFIX_DLL=dll, ROMFIX_C=dll[:-4] + ".c")
    a = [sys.executable, "-I", TEST] + (["--quick"] if quick else [])
    try:
        p = subprocess.run(a, env=env, capture_output=True, text=True, timeout=3600)
        return p.returncode == 0
    except subprocess.TimeoutExpired:
        return False                              # a hang counts as caught


def main():
    only = set(sys.argv[1:])
    src = open(SRC, encoding="utf-8").read()
    os.makedirs(WORK, exist_ok=True)
    lines, caught, todo = [], 0, [m for m in M if not only or m[0] in only]
    for name, old, new in todo:
        n = src.count(old)
        if n != 1:
            lines.append(f"{name}: BAD MUTANT (anchor found {n} times)")
            print(lines[-1], flush=True)
            continue
        c = os.path.join(WORK, name + ".c")
        open(c, "w", encoding="utf-8", newline="\n").write(src.replace(old, new))
        dll = c[:-2] + ".dll"
        verdict = "MISSED"
        if not run(dll, True):
            verdict = "CAUGHT (quick)"
        elif not run(dll, False):
            verdict = "CAUGHT (battery)"
        caught += verdict.startswith("CAUGHT")
        lines.append(f"{name}: {verdict}")
        print(lines[-1], flush=True)
    lines.append(f"{caught} of {len(todo)} caught")
    print(lines[-1])
    open(os.path.join(WORK, "..", "neg_romfix_arm.txt"), "w").write("\n".join(lines) + "\n")
    return 0 if caught == len(todo) else 1


if __name__ == "__main__":
    sys.exit(main())
