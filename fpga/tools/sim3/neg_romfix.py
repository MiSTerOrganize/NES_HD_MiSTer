"""Negative control for hd3_romfix: each mutant is one deliberate defect, built into its own
tb_engine.exe and run against romfix_cases.CASES (in order, stopping at the first failure).
Every mutant must be CAUGHT; a missed one is a coverage gap unless shown output-equivalent.
One mutant at a time (memory).

    python -I neg_romfix.py [--first PREFIX] [only-name ...]   ->  neg_romfix.txt
(--first tries the cases named PREFIX* first, so a mutant aimed at them is caught quickly; a
mutant they miss still runs every other case before it is called MISSED)
"""
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import romfix_cases as RC  # noqa: E402
RTL = os.path.normpath(os.path.join(HERE, "..", "..", "rtl", "hdpack"))
WORK = os.path.join(HERE, "obj", "neg_romfix")
F = "hd3_romfix.sv"

M = [
    # staging into DDR3 (the ARM hashes and builds from what this module stages)
    ("no_stall", "assign stall = stg & wq;", "assign stall = 1'b0;"),
    ("stall_not_during_mem", "wire        stg  = (st == S_STAGE) | (st == S_MEM && ret == S_STAGE);",
     "wire        stg  = (st == S_STAGE);"),
    ("byte_lane_wrong", "asmq[{L[2:0], 3'b000} +: 8] <= din;", "asmq[7:0] <= din;"),
    ("full_qword_lost", "if (!bad) mem(0, SRC_Q + {4'd0, wq_a}, wq_d, S_STAGE);", "if (1'b0) mem(0, SRC_Q + {4'd0, wq_a}, wq_d, S_STAGE);"),
    ("last_part_qword_lost", "if (L[2:0] != 3'd0 && !bad) mem(0, SRC_Q + {4'd0, L[23:3]}, asmq, S_SFIN);",
     "if (1'b0) mem(0, SRC_Q + {4'd0, L[23:3]}, asmq, S_SFIN);"),
    ("src_window_off", "parameter [27:3] SRC_Q  = 25'h1900000,", "parameter [27:3] SRC_Q  = 25'h1900001,"),
    ("tgt_window_off", "parameter [27:3] TGT_Q  = 25'h1980000,", "parameter [27:3] TGT_Q  = 25'h1980001,"),
    ("mailbox_off", "parameter [27:3] RF_Q   = 25'h1880008,", "parameter [27:3] RF_Q   = 25'h1880009,"),
    # what the status tells the ARM
    ("status_length_zero", "mem(0, RF_Q, {8'hA6, rseq, aseq + 8'd1, last_id, active, has14, content, ~bad, 3'd0, L},",
     "mem(0, RF_Q, {8'hA6, rseq, aseq + 8'd1, last_id, active, has14, content, ~bad, 3'd0, 24'd0},"),
    ("status_inactive", "mem(0, RF_Q, {8'hA6, rseq, aseq + 8'd1, last_id, active, has14, content, ~bad, 3'd0, L},",
     "mem(0, RF_Q, {8'hA6, rseq, aseq + 8'd1, last_id, 1'b0, has14, content, ~bad, 3'd0, L},"),
    ("pack_change_ignored", "if (active != old_act) act_dirty <= 1;", ""),
    ("content_not_kept", "content <= rp_tgt ? 2'd1 : 2'd0;", "content <= 2'd0;"),
    # waiting for and checking the command
    ("timeout_ignored", "if (tmo >= TMO) begin", "if (1'b0) begin"),
    ("magic_unchecked", "wire cmd_ok = mq[63:56] == 8'hC7 && ", "wire cmd_ok = "),
    ("rseq_unchecked", " && mq[55:48] == rseq && ", " && "),
    ("aseq_unchecked", " && mq[47:40] == aseq && ", " && "),
    ("id_unchecked", " && mq[39:32] != last_id;", ";"),
    ("result_not_taken", "result  <= mq[29:27];", "result  <= 3'd1;"),
    ("no_revert", "2'd2: begin rp_tgt <= 0; rp_len <= L;         st <= S_RP0; end",
     "2'd2: begin rp_tgt <= 0; rp_len <= L;         st <= S_IDLE; end"),
    ("revert_wrong_length", "2'd2: begin rp_tgt <= 0; rp_len <= L; ", "2'd2: begin rp_tgt <= 0; rp_len <= mq[23:0]; "),
    ("target_wrong_length", "2'd1: begin rp_tgt <= 1; rp_len <= mq[23:0]; st <= S_RP0; end",
     "2'd1: begin rp_tgt <= 1; rp_len <= L; st <= S_RP0; end"),
    ("target_from_source", "2'd1: begin rp_tgt <= 1; ", "2'd1: begin rp_tgt <= 0; "),
    # holding the core and the replay
    ("hold_only_replay", "assign hold = (st != S_IDLE && from_dl) || replaying;", "assign hold = replaying;"),
    ("replay_addr_off", "rp_addr <= {1'b0, rp_k};", "rp_addr <= {1'b0, rp_k + 24'd1};"),
    ("replay_byte_lane", "rp_b <= mq[{rp_k[2:0], 3'b000} +: 8];", "rp_b <= mq[7:0];"),
    ("replay_ignores_wait", "else if (!core_wait) begin\n\t\t\trp_wr <= 1;", "else begin\n\t\t\trp_wr <= 1;"),
    ("replay_filetype", "assign o_ft   = rp ? ft_rom  : ft;", "assign o_ft   = ft;"),
    ("replay_tail_short", "if (rp_k[2:0] == 3'd7 || rp_k + 24'd1 >= rp_len) st <= S_RPQ;",
     "if (rp_k[2:0] == 3'd7) st <= S_RPQ;"),
    # power-up: the last session's handshake is not this session's
    ("rseq_not_moved_at_powerup", "begin rseq <= rseq + mq[55:48] + 8'h40; mem(", "begin rseq <= rseq; mem("),
    ("old_status_not_read", "S_INIT0: mem(1, RF_Q, 64'd0, S_INIT);", "S_INIT0: st <= S_INIT;"),
    # a target length the ARM never writes
    ("bad_length_accepted", "if (mq[31:30] == 2'd1 && (mq[23:0] == 24'd0 || mq[23:0] > {1'b0, MAXB})) begin",
     "if (1'b0) begin"),
    ("zero_length_accepted", "(mq[23:0] == 24'd0 || mq[23:0] > {1'b0, MAXB})", "(mq[23:0] > {1'b0, MAXB})"),
    # An access abandoned by a new download (case swap_midaccess) has NO mutant here, by
    # measurement (2026-10-28), not by assumption:
    # - `take`'s `drop == 0` term: while drop != 0 the state machine is held (the `else if (drop
    #   != 2'd0)` branch), so it is never in S_MEM to take an answer - an equivalent mutant.
    # - `drop <= 2'd0` (never swallow): swap_midaccess drives it - the abandoned read is held
    #   back past the download until the patcher has a second access in flight (2 outstanding,
    #   in S_MEM) - and every case still passes. The answers shift by one access and the shift
    #   heals at the next answer that arrives while the patcher is idle (nout counts it, nothing
    #   takes it); the only access in between is the status write, whose data the patcher never
    #   reads. Not observable at the module boundary, so not a battery entry (it would report
    #   MISSED for ever); `drop` stays as the guard that keeps answers paired by construction.
]


def main():
    args = sys.argv[1:]
    first = ""                       # --first PREFIX: try those cases before the rest
    if "--first" in args:
        i = args.index("--first")
        first = args[i + 1]
        del args[i:i + 2]
    cases = sorted(RC.CASES, key=lambda c: 0 if first and c[0].startswith(first) else 1)
    only = set(a for a in args if a != "--check")
    src = open(os.path.join(RTL, F), encoding="utf-8").read()
    if "--check" in sys.argv:                     # anchors only, no builds
        for name, old, _ in M:
            print(f"{name}: anchor found {src.count(old)} time(s)")
        return
    lines = []
    caught = 0
    todo = [m for m in M if not only or m[0] in only]
    # one snapshot of rtl/hdpack, taken now: the run takes hours, and every mutant must be built
    # against the same RTL even if rtl/hdpack is edited meanwhile
    base = os.path.join(WORK, "_base_rtl")
    shutil.rmtree(base, ignore_errors=True)
    shutil.copytree(RTL, base, ignore=shutil.ignore_patterns("obj"))
    for name, old, new in todo:
        n = src.count(old)
        if n != 1:
            lines.append(f"{name}: BAD MUTANT (anchor found {n} times)")
            print(lines[-1], flush=True)
            continue
        d = os.path.join(WORK, name).replace("\\", "/")
        shutil.rmtree(d, ignore_errors=True)
        shutil.copytree(base, os.path.join(d, "rtl"))
        open(os.path.join(d, "rtl", F), "w", encoding="utf-8", newline="\n").write(src.replace(old, new))
        env = dict(os.environ, RTLDIR=os.path.join(d, "rtl").replace("\\", "/"))
        b = subprocess.run(["sh", HERE.replace("\\", "/") + "/build_engine.sh", d + "/obj"],
                           cwd=HERE, env=env, capture_output=True, text=True)
        exe = os.path.join(d, "obj", "tb_engine.exe")
        if b.returncode != 0 or not os.path.exists(exe):
            lines.append(f"{name}: BUILD FAILED")
            print(lines[-1], flush=True)
            continue
        verdict = "MISSED"
        for c in cases:
            for when in ("after", "before"):
                ok, _, _ = RC.run(exe, c, when, os.path.join(d, f"{c[0]}_{when}.log"))
                if not ok:
                    verdict = f"CAUGHT ({c[0]} {when})"
                    break
            if verdict != "MISSED":
                break
        caught += verdict.startswith("CAUGHT")
        lines.append(f"{name}: {verdict}")
        print(lines[-1], flush=True)
        shutil.rmtree(os.path.join(d, "obj", "hd3_engine"), ignore_errors=True)
    lines.append(f"{caught} of {len(todo)} caught")
    print(lines[-1])
    open(os.path.join(HERE, "obj", "neg_romfix.txt"), "w").write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
