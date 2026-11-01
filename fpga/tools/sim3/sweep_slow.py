"""Sweep the slow-DDR3 run's settings with a given tb_engine.exe and report, per setting,
the slow_check verdict, the testbench verdict and the first-underflow line.

    python -I sweep_slow.py <tb_engine.exe> <outdir> busy:lat[:seed] ...
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
T = "C:/Users/miste/OneDrive/Desktop/MiSTerOrganize/MiSTerFrontier/NES_HDPack_testdata/rec_smb3"
P = "Z:/NES_HDPack_work/out/p053.hdp"
GOOD = os.path.join(HERE, "obj", "engine_out", "smb_0240.rgb")      # run_engine.sh's smb run
RTL = os.path.normpath(os.path.join(HERE, "..", "..", "rtl", "hdpack"))


def main():
    exe, out = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
    os.environ["PATH"] = "C:\\msys64\\mingw64\\bin;" + os.environ["PATH"]
    os.makedirs(out, exist_ok=True)
    for spec in sys.argv[3:]:
        parts = spec.split(":")
        busy, lat = parts[0], parts[1]
        seed = parts[2] if len(parts) > 2 else "1"
        pre = os.path.join(out, f"s_{busy}_{lat}_{seed}").replace("\\", "/")
        args = [exe, P, pre, "--game-ram", "0", "--frame", f"0:{T}/rec_0240.bin",
                "--frame", f"1:{T}/rec_0270.bin", "--busy", busy, "--lat", lat,
                "--seed", seed, "--expect-late", "1"]
        r = subprocess.run(args, cwd=RTL, capture_output=True, text=True,
                           timeout=3600)
        uf = [l for l in r.stdout.splitlines() if l.startswith("underflow first")]
        fl = [l for l in r.stdout.splitlines() if l.startswith("FAIL")]
        c = subprocess.run([sys.executable, "-I", os.path.join(HERE, "slow_check.py"), GOOD,
                            pre + "_0240.rgb"], capture_output=True, text=True)
        print(f"{spec}: tb rc {r.returncode} ({fl[0] if fl else 'no FAIL'}); "
              f"slow_check rc {c.returncode} {c.stdout.strip().splitlines()[0] if c.stdout.strip() else ''}; "
              f"{uf[0] if uf else 'no underflow'}", flush=True)


if __name__ == "__main__":
    main()
