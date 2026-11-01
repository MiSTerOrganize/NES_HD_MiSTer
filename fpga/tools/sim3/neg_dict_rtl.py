"""Negative control for the hd3_dict unit test: each mutant of the RTL must FAIL the check.

A check that has never been seen to fail proves nothing. Each mutation below is a plausible
real bug; the runner copies hd3_dict.sv with that one change, builds it into its own folder,
runs the two suites and requires a failure: a mismatch from check_dict.py, a testbench error
(frame_done for the wrong bank, a timeout) or a hang. The anchor of every mutation must occur
exactly once in the source, so a stale anchor fails loudly instead of producing an unmutated
"mutant" that passes. The real RTL is run first and must PASS both suites, or the control
means nothing.

Suites (both need their goldens, made by dict_golden.py, in obj/dict/):
  A  Zelda II, a057 with chained fallbacks (make_fb_chain.py): CHR-ROM keys, fallback tiles,
     second-hop fallbacks; frames 300, 420 in banks 0, 1.
  B  Castlevania, p002: CHR-RAM fingerprint keys, default-palette results; frames 250, 450,
     700 in banks 0, 1, 0 (bank reuse, stale index), --overlap, line 100 header dropped.
  C  Super Mario Bros., p125 (a legacy pack: no backdrop / 0xFF byte in the key); frames
     300, 270, --overlap.

usage: python neg_dict_rtl.py <testdata dir> <pack dir>
"""
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
RTL = os.path.join(ROOT, "rtl", "hdpack", "hd3_dict.sv")
LOOKUP = os.path.join(ROOT, "rtl", "hdpack", "hd3_lookup.sv")
GOLD = os.path.join(HERE, "obj", "dict")

MUTANTS = {
    "backdrop byte dropped from the BG key":
        ("{2'b00, c6(pal, 5'd0)}", "8'h00"),
    "sprite palette taken from the BG groups":
        ("{1'b1, qa[47:46]}", "{1'b0, qa[47:46]}"),
    "palette entries out of order":
        ("c6(pal, {grp, 2'd1}), 2'b00, c6(pal, {grp, 2'd2}),",
         "c6(pal, {grp, 2'd2}), 2'b00, c6(pal, {grp, 2'd1}),"),
    "CHR-RAM key uses the tile index":
        ("game_ram ? ls_q : {48'd0, lin[19:4]}", "{48'd0, lin[19:4]}"),
    "line read from the wrong slot":
        ("slot <= proc_y[1:0];", "slot <= proc_y[1:0] + 2'd1;"),
    "index never cleared between frames":
        ("begin ix_we = 1; ix_wa = clr", "begin ix_we = 0; ix_wa = clr"),
    "hash collision taken as a new record":
        ("h   <= h + 12'd1;\n\t\t\t\tlst <= K_I0;", "h   <= h;\n\t\t\t\tlst <= K_ALLOC;"),
    "bank ignored when a key is stored":
        ("ka_a = {fr_bank, nrec[fr_bank][RAW-1:0]}", "ka_a = {1'b0, nrec[fr_bank][RAW-1:0]}"),
    "invalid sprite fetch given a record":
        ("if (is_spr && !qa[54]) begin", "if (1'b0) begin"),
    "header-seen bit ignored":
        ("if (slot_ok[slot]) begin", "if (1'b1) begin"),
    "fallback tile never tried":
        ("end else if (fb[16]) begin", "end else if (1'b0) begin"),
    "fallback map word halves swapped":
        ("fm_idx[0] ? rd_data[63:32] : rd_data[31:0]", "fm_idx[0] ? rd_data[31:0] : rd_data[63:32]"),
    "second-hop fallback never read":
        ("if (fb[16] && {16'd0, fb[15:0]} < fb_len) begin", "if (1'b0) begin"),
    "default palette never tried":
        ("via  <= lk_found ? 2'd3 : 2'd0;", "via  <= 2'd0;"),
    "frame_done does not wait for the resolver":
        ("if (started[res_bank] && res_ptr != nrec[res_bank]) begin", "if (1'b0) begin"),
    # only suite C (a legacy pack) can show this one
    "legacy flag ignored":
        ("wire  [7:0] top     = legacy ? 8'h00 :", "wire  [7:0] top     = 1'b0 ? 8'h00 :"),
}


def suites(td, packs):
    z, c, s = os.path.join(td, "rec_z2"), os.path.join(td, "rec_cv"), os.path.join(td, "rec_smb3")
    g = lambda n: os.path.join(GOLD, n)
    return [
        ("A", [os.path.join(GOLD, "a057_chain.hdp"), "--game-ram", "0",
               "--frame", f"0:{z}/rec_0300.bin", "--frame", f"1:{z}/rec_0420.bin",
               "--gap", "25", "--busy", "40", "--lat", "60", "--seed", "5"],
         [g("gc_z2_0300.tsv"), g("gc_z2_0420.tsv")]),
        ("B", [os.path.join(packs, "p002.hdp"), "--game-ram", "1",
               "--frame", f"0:{c}/rec_0250.bin", "--frame", f"1:{c}/rec_0450.bin",
               "--frame", f"0:{c}/rec_0700.bin", "--frame", f"1:{c}/rec_1000.bin",
               "--frame", f"0:{c}/rec_1300.bin", "--overlap", "--drop-header", "100",
               "--gap", "25", "--busy", "40", "--lat", "60", "--seed", "11"],
         [g("g_cv_0250.tsv"), g("g_cv_0450.tsv"), g("g_cv_0700.tsv"), g("g_cv_1000.tsv"),
          g("g_cv_1300.tsv"), "--drop-header", "100"]),
        ("C", [os.path.join(packs, "p125.hdp"), "--game-ram", "0",
               "--frame", f"0:{s}/rec_0300.bin", "--frame", f"1:{s}/rec_0270.bin",
               "--overlap", "--gap", "25", "--busy", "40", "--seed", "13"],
         [g("gl_p125_0300.tsv"), g("gl_p125_0270.tsv")]),
    ]


def build(rtl, mdir):
    env = dict(os.environ, OBJ=mdir.replace("\\", "/"))
    b = subprocess.run(["sh", os.path.join(HERE, "build_one.sh"), "hd3_dict",
                        os.path.join(HERE, "tb_dict.cpp"), rtl, LOOKUP],
                       env=env, capture_output=True, text=True)
    return b.returncode == 0, b.stdout[-800:] + b.stderr[-800:]


def run_suites(exe, mdir, td, packs):
    """Return a list of (suite, verdict) where verdict is 'pass' or why it failed."""
    out = []
    for name, tb_args, chk_args in suites(td, packs):
        tsv = os.path.join(mdir, f"suite_{name}.tsv")
        try:
            r = subprocess.run([exe, tb_args[0], tsv] + tb_args[1:], capture_output=True,
                               text=True, timeout=1200)
        except subprocess.TimeoutExpired:
            out.append((name, "testbench hung"))
            continue
        if r.returncode:
            out.append((name, "testbench: " + (r.stderr.strip().splitlines() or ["?"])[-1]))
            continue
        c = subprocess.run([sys.executable, "-I", os.path.join(HERE, "check_dict.py"), tsv] + chk_args,
                           capture_output=True, text=True)
        last = (c.stdout.strip().splitlines() or ["?"])[-1]
        out.append((name, "pass" if c.returncode == 0 else last.split(": ", 1)[-1]))
    return out


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    td, packs = sys.argv[1], sys.argv[2]
    with open(RTL, encoding="utf-8") as f:
        src = f.read()
    work = os.path.join(HERE, "obj", "neg_dict")
    os.makedirs(work, exist_ok=True)

    # the real RTL first: a control is meaningless unless the unmutated design passes
    base = os.path.join(work, "_baseline")
    shutil.rmtree(base, ignore_errors=True)
    os.makedirs(base)
    ok, log = build(RTL, base)
    if not ok:
        print(f"BUILD FAILED [baseline]\n{log}")
        return 2
    res = run_suites(os.path.join(base, "tb_dict.exe"), base, td, packs)
    print("baseline: " + ", ".join(f"{s} {v}" for s, v in res), flush=True)
    if any(v != "pass" for _, v in res):
        print("FAIL: the unmutated RTL does not pass - fix that before trusting the control")
        return 2

    caught = 0
    missed = []
    for name, (old, new) in MUTANTS.items():
        n = src.count(old)
        if n != 1:
            print(f"ANCHOR ERROR [{name}]: found {n} times")
            return 2
        tag = "".join(ch if ch.isalnum() else "_" for ch in name)
        mdir = os.path.join(work, tag)
        shutil.rmtree(mdir, ignore_errors=True)
        os.makedirs(mdir)
        mrtl = os.path.join(mdir, "hd3_dict.sv")
        with open(mrtl, "w", encoding="utf-8", newline="\n") as f:
            f.write(src.replace(old, new))
        ok, log = build(mrtl, mdir)
        if not ok:
            print(f"BUILD FAILED [{name}]\n{log}")
            return 2
        res = run_suites(os.path.join(mdir, "tb_dict.exe"), mdir, td, packs)
        fails = [f"{s}: {v}" for s, v in res if v != "pass"]
        if fails:
            caught += 1
            print(f"CAUGHT  {name}  ({'; '.join(fails)})", flush=True)
        else:
            missed.append(name)
            print(f"MISSED  {name}", flush=True)
    print(f"{caught}/{len(MUTANTS)} mutants caught")
    for m in missed:
        print(f"  not caught: {m}")
    return 0 if not missed else 1


if __name__ == "__main__":
    sys.exit(main())
