"""8k negative control: each mutant of the CHR-RAM index-condition path must FAIL at least one
of the index-form Castlevania runs (run_ix.sh). Baseline first: it must PASS all of them.
The fixtures come from make_ixram_cond.py (see HDPACK_DESIGN.md "8k"):
  obj/dict/p002_ix.hdp   plain conversion
  obj/dict/p002_ixh.hdp  --shift 3 --palmix (nearby offsets off the 8-pixel grid)
  obj/dict/p002_ixf.hdp  --palflip (decisive for the palette comparison)
usage: python -I neg_ix.py [hd3_render.sv] [name ...]   (default: rtl/hdpack/hd3_render.sv)"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SIM = HERE
RTL = os.path.normpath(os.path.join(SIM, "..", "..", "rtl", "hdpack"))
WORK = os.path.join(SIM, "obj", "neg_ix")
SH = r"C:\msys64\usr\bin\sh.exe" if os.path.exists(r"C:\msys64\usr\bin\sh.exe") else "sh"

MUTANTS = {
    "span index from the wrong bits": ("t_ri <= rc_q[19:4];", "t_ri <= rc_q[20:5];"),
    "sprite index from the wrong bits": ("t_ri <= rc_q[35:20];", "t_ri <= rc_q[36:21];"),
    "sprite fetch qword offset wrong": ("+ 25'd80 + {20'd0, d_fetch, 1'b0}", "+ 25'd82 + {20'd0, d_fetch, 1'b0}"),
    "span qword offset wrong": ("+ 25'd8 + {18'd0, d_slot, 1'b0}", "+ 25'd10 + {18'd0, d_slot, 1'b0}"),
    "index not re-read per target": ("\t\tt_rx <= 0;\n\t\tif (!t_spr) begin", "\t\tif (!t_spr) begin"),
    "nearby tile index condition sent to the pipeline": ("8'd5: if (!e_uni && !c_ixram) begin",
                                                         "8'd5: if (!e_uni) begin"),
    "index condition ignores the palette": ("tmatch = t_palok && t_hi0 && c2[15:0] == t_ri;",
                                            "tmatch = t_hi0 && c2[15:0] == t_ri;"),
    "index read through the cache": ("rc_req <= 1; rc_byp <= 1; rc_pend <= 1;", "rc_req <= 1; rc_byp <= 0; rc_pend <= 1;", 2),
    "index condition uses the fingerprint key": ("else if (game_ram)                                   // 8k",
                                                 "else if (1'b0)                                   // 8k"),
    # the bug the harder fixture found: a sprite run is not a group, so a nearby index
    # condition evaluated once at the first pixel was applied to the whole run
    "nearby index condition uniform over a sprite run": ("e_uni <= lm_fl || (c_ixram && !c_ixnear) ||",
                                                         "e_uni <= lm_fl || c_ixram ||"),
    "nearby index condition sent to the pipeline": ("8'd6: if (!e_uni && !c_ixram) begin",
                                                    "8'd6: if (!e_uni) begin"),
}


def build(src, tag):
    obj = os.path.join(WORK, tag)
    os.makedirs(obj, exist_ok=True)
    r = [os.path.join(RTL, f) for f in ("hd3_dict.sv", "hd3_lookup.sv", "hd3_add.sv", "hd3_resolve.sv",
                                        "hd3_fmap.sv", "hd3_ccache.sv")]
    files = ["hd3_render_tb.sv"] + r + [src, os.path.join(RTL, "hd3_rcache.sv")]
    env = dict(os.environ, OBJ=obj)
    p = subprocess.run([SH, "build_one.sh", "hd3_render_tb", os.path.join(HERE, "tb_render.cpp")] + files,
                       cwd=SIM, env=env, capture_output=True, text=True)
    if p.returncode:
        return None, p.stdout[-400:] + p.stderr[-400:]
    return os.path.join(obj, "tb_render.exe"), ""


DICT = os.path.join(SIM, "obj", "dict")
# (pack, FRAMES override or None): plain, harder (shifted offsets + mixed palettes),
# palette-flipped, and the plain pack with three frames in the SAME record bank back to back
RUNS = [(os.path.join(DICT, "p002_ix.hdp"), None),
        (os.path.join(DICT, "p002_ixh.hdp"), None),
        (os.path.join(DICT, "p002_ixf.hdp"), None),
        (os.path.join(DICT, "p002_ix.hdp"), "0:0250 0:0450 0:0700")]


def run(exe, tag):
    ok, out = True, ""
    for i, (pack, frames) in enumerate(RUNS):
        env = dict(os.environ, REQUIRE_IXR="1")
        if frames:
            env["FRAMES"] = frames
        p = subprocess.run([SH, os.path.join(HERE, "run_ix.sh"), exe,
                            os.path.join(WORK, "out", f"{tag}_{i}"), pack],
                           capture_output=True, text=True, env=env)
        o = p.stdout + p.stderr
        ok &= p.returncode == 0 and "PASS" in o
        out += f"[{os.path.basename(pack)} {frames or ''}]\n" + o
    return ok, out


def main():
    args = sys.argv[1:]
    src = args.pop(0) if args and args[0].endswith(".sv") else os.path.join(RTL, "hd3_render.sv")
    want = args
    text = open(src).read()
    exe, err = build(src, "base")
    if not exe:
        sys.exit("baseline build failed: " + err)
    ok, out = run(exe, "base")
    print("baseline:", "PASS" if ok else "FAIL")
    if not ok:
        print(out[-1500:])
        return 1
    caught = 0
    names = [n for n in MUTANTS if not want or n in want]
    for i, n in enumerate(names):
        a, b, *cnt = MUTANTS[n]
        if text.count(a) != (cnt[0] if cnt else 1):
            print(f"BAD ANCHOR  {n} (found {text.count(a)})")
            continue
        m = os.path.join(WORK, f"m{i}.sv")
        os.makedirs(os.path.dirname(m), exist_ok=True)
        open(m, "w").write(text.replace(a, b))
        exe, err = build(m, f"m{i}")
        if not exe:
            print(f"CAUGHT  {n}  (build failed: {err.strip().splitlines()[-1] if err.strip() else '?'})")
            caught += 1
            continue
        ok, out = run(exe, f"m{i}")
        if ok:
            print(f"MISSED  {n}")
        else:
            caught += 1
            # pixel differences, testbench failures, and run_ix.sh's structural FAIL lines (the
            # REQUIRE_IXR "no uncached index read" check prints FAIL, not "failed")
            lines = out.splitlines()
            line = ([l for l in lines if l.startswith("FAIL") or "failed" in l] +
                    [l for l in lines if "differ" in l])[:2]
            print(f"CAUGHT  {n}  ({'; '.join(x.strip() for x in line)[:150]})")
    print(f"{caught}/{len(names)} mutants caught")
    return 0 if caught == len(names) else 1


if __name__ == "__main__":
    sys.exit(main())
