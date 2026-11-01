"""The hd3_romfix test cases, run in full by this script and by neg_romfix.py (each mutant runs
them in order and stops at the first failure). Every case runs with the ROM loaded after the
pack and before it, with savestate traffic sharing the DDR3 crossing.

    python -I romfix_cases.py [exe [name-prefix]]    ->  obj/romfix_results.txt
Fixtures in fixtures/romfix: uc.hdp / uc_bad.hdp / uc_expect.bin (Urban Champion's corpus BPS,
rom_expect.py; uc_bad.hdp from check_s14.py) and synth/ (make_synth.py + make_bad.py). The
per-case logs and testbench output go to obj/romfix.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
P = os.path.join(HERE, "fixtures", "romfix").replace("\\", "/")
L = os.path.join(HERE, "obj", "romfix").replace("\\", "/")
os.makedirs(L, exist_ok=True)
RTL = os.path.normpath(os.path.join(HERE, "..", "..", "rtl", "hdpack"))   # palette .hex files
S = P + "/synth"
LIB = "Z:/MiSTer_Organize/RomRoot/MiSTer_Console/MiSTer_Console/games/NES/1 NES"
UC = LIB + "/1 World/Urban Champion (World).nes"
MM = LIB + "/1 USA/Mega Man (USA).nes"

# name, pack, rom, expect, result, loads, extra args
CASES = [
    ("uc_ok", P + "/uc.hdp", UC, P + "/uc_expect.bin", 1, 2, []),
    ("uc_nomatch", P + "/uc.hdp", MM, MM, 2, 1, []),
    ("uc_damaged", P + "/uc_bad.hdp", UC, UC, 4, 1, []),
    # DDR3 busy for 200 clk_f at a time: the staging FIFO fills during the download, so the
    # patcher must hold the download with `stall` (without it the FIFO overflows, result 5).
    # The --busy 20 pacing alone only fills it by chance of the random sequence.
    ("uc_ok_backpressure", P + "/uc.hdp", UC, P + "/uc_expect.bin", 1, 2, ["--busy-burst", "200"]),
    # the ARM never answers: after TMO clocks the core runs the ROM as loaded, result 6. With the
    # ROM loaded BEFORE the pack the core is never held (no section 14 at staging: result 2, the
    # core runs at once) and the pack's later question just goes unanswered, so result stays 2
    ("arm_silent", P + "/uc.hdp", UC, UC, {"after": 6, "before": 2}, 1, ["--arm", "0"]),
    # before each real command the ARM leaves a decoy the FPGA must not carry out: wrong magic,
    # an old rseq, an old aseq, the id it last carried out (each would replay with result 7)
    ("uc_ok_decoys", P + "/uc.hdp", UC, P + "/uc_expect.bin", 1, 2, ["--arm", "junk"]),
    # DDR3 already holds the last session's status and command for the question {rseq 1, aseq 2}
    # - the one a session that started its count at 0 asks once the pack is in and the ROM staged
    # - over a 0x5A target (a core reload keeps DDR3), and the ARM, which never saw that status
    # answered, works one out and writes it after this session has started. The FPGA starts its
    # count 0x40 past the old status's, so neither is taken for its question
    ("uc_ok_stale", P + "/uc.hdp", UC, P + "/uc_expect.bin", 1, 2, ["--stale-cmd", "1:2"]),
    # the same after a second reload: the old session itself started 0x40 on, so its first ROM
    # asked {rseq 0x41 = 65, aseq 2} - exactly the question a FIXED 0x40 jump would ask again;
    # the jump is from the status DDR3 holds, so this session asks 0x82 instead
    ("uc_ok_stale2", P + "/uc.hdp", UC, P + "/uc_expect.bin", 1, 2, ["--stale-cmd", "65:2"]),
    # the ARM's "replay the target" carries a length past the 4 MB target area, or 0: refused
    # (result 3), the core keeps the ROM as loaded
    ("uc_badlen", P + "/uc.hdp", UC, UC, 3, 1, ["--arm", "badlen"]),
    ("uc_badlen0", P + "/uc.hdp", UC, UC, 3, 1, ["--arm", "badlen0"]),
]
CASES += [(f"synth{k}", S + "/synth.hdp", f"{S}/rom{k}.nes", f"{S}/exp{k}.bin", 1, 2, []) for k in range(7)]
CASES += [
    ("synth_nomatch", S + "/synth.hdp", S + "/nomatch.nes", S + "/nomatch.nes", 2, 1, []),
    ("bad_mode", S + "/bad_mode.hdp", S + "/rom0.nes", S + "/rom0.nes", 3, 1, []),
    ("bad_tgt", S + "/bad_tgt.hdp", S + "/rom4.nes", S + "/rom4.nes", 3, 1, []),
    ("bad_runs", S + "/bad_runs.hdp", S + "/rom2.nes", S + "/rom2.nes", 3, 1, []),
    ("bad_data", S + "/bad_data.hdp", S + "/rom0.nes", S + "/rom0.nes", 3, 1, []),
    ("bad_ssz", S + "/bad_ssz.hdp", S + "/rom2.nes", S + "/rom2.nes", 3, 1, []),
    ("bad_runs_out", S + "/bad_runs_out.hdp", S + "/rom0.nes", S + "/rom0.nes", 3, 1, []),
    # patched, then a pack with no entry for this ROM: the original is replayed (3 loads)
    ("swap", S + "/synth.hdp", S + "/rom2.nes", S + "/rom2.nes", 2, 3, ["--pack2", P + "/uc.hdp"]),
    # patched, then a pack whose entry for this ROM fails its CRC: the original comes back
    ("swap_bad", P + "/uc.hdp", UC, UC, 4, 3, ["--pack2", P + "/uc_bad.hdp"]),
    # the second pack's download starts while the patcher's idle poll is still waiting for DDR3:
    # that answer arrives after the download began and must be swallowed, not taken for the
    # status write the new pack triggers (or the arbiter's one held request is replaced and the
    # patcher waits for an answer that never comes)
    ("swap_midaccess", S + "/synth.hdp", S + "/rom2.nes", S + "/rom2.nes", 2, 3,
     ["--pack2", P + "/uc.hdp", "--dl-mid-access", "1"]),
    # the same with decoys: the second command comes from a pack load, while the game runs
    ("swap_decoys", S + "/synth.hdp", S + "/rom2.nes", S + "/rom2.nes", 2, 3,
     ["--pack2", P + "/uc.hdp", "--arm", "junk"]),
]
# the second pass (make_ines1.py): NES 2.0 style ROMs whose entry names their iNES 1.0 form
I = P + "/ines1"
CASES += [
    ("ines1_ips", I + "/ines1.hdp", I + "/rom0.nes", I + "/exp0.bin", 1, 2, []),
    ("ines1_bps", I + "/ines1.hdp", I + "/rom1.nes", I + "/exp1.bin", 1, 2, []),
    ("ines1_ups_header", I + "/ines1.hdp", I + "/rom2.nes", I + "/exp2.bin", 1, 2, []),
    ("ines1_file_wins", I + "/ines1.hdp", I + "/rom3.nes", I + "/exp3.bin", 1, 2, []),
    ("ines1_bad_crc", I + "/ines1_bad.hdp", I + "/rom4.nes", I + "/rom4.nes", 4, 1, []),
    ("ines1_no_magic", I + "/ines1.hdp", I + "/rom5.nes", I + "/rom5.nes", 2, 1, []),
    # patched through the iNES 1.0 form, then a pack with no entry: the ORIGINAL file comes back
    ("ines1_swap", I + "/ines1.hdp", I + "/rom1.nes", I + "/rom1.nes", 2, 3, ["--pack2", P + "/uc.hdp"]),
]


def run(exe, case, when, log):
    name, pack, rom, exp, res, loads, extra = case
    if isinstance(res, dict):                      # a result that depends on the load order
        res = res[when]
    env = dict(os.environ, PATH="C:/msys64/mingw64/bin;" + os.environ.get("PATH", ""))
    args = [exe, pack, L + "/o", "--game-ram", "0", "--rom", rom, "--rom-when", when,
            "--rom-expect", exp, "--rom-result", str(res), "--rom-loads", str(loads),
            "--ss", "2", "--busy", "20"] + extra
    try:
        p = subprocess.run(args, cwd=RTL, env=env, capture_output=True,
                           text=True, timeout=1800)
        out, rc = p.stdout + p.stderr, p.returncode
    except subprocess.TimeoutExpired:
        out, rc = "TIMEOUT", 99
    with open(log, "w") as f:
        f.write(out)
    rom_line = next((l for l in out.splitlines() if l.startswith("ROM:")), "")
    return rc == 0, rom_line, [l for l in out.splitlines() if "FAIL" in l][:4]


def main():
    exe = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "obj", "engine", "tb_engine.exe")
    only = sys.argv[2] if len(sys.argv) > 2 else ""      # run only cases whose name starts with this
    out = []
    bad = 0
    for c in CASES:
        if not c[0].startswith(only):
            continue
        for when in ("after", "before"):
            ok, rom_line, fails = run(exe, c, when, f"{L}/rf_{c[0]}_{when}.log")
            line = f"{c[0]} {when}: {'PASS' if ok else 'FAIL'} ({rom_line})"
            out.append(line)
            out += ["  " + f for f in fails]
            print(line, flush=True)
            bad += not ok
    out.append("ALL PASS" if not bad else f"{bad} FAILURES")
    print(out[-1])
    open(os.path.join(HERE, "obj", "romfix_results.txt"), "w").write("\n".join(out) + "\n")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
