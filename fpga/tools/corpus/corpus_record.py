"""corpus_record.py - record every corpus group with fullsim (no HD pack): --rec, plus --watch on
the group's union list when it has one, --nolimit when its packs set disableSpriteLimit, the
group's input script, and saves at the script's #frames (default 300,600,900). One recording
serves every pack in the group (watch_subset.py cuts each pack's watch file out of it).

Resumable: a group whose WORK/<g>/rec/done exists is skipped. One fullsim per worker; fullsim
is single-threaded, so WORKERS <= cores-1 leaves the machine usable.

    python -I corpus_record.py WORK [WORKERS] [g01,g02,...]
"""
import concurrent.futures as cf
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.normpath(os.path.join(HERE, "..", ".."))
FULLSIM = os.path.join(PROJ, "tools", "fullsim", "obj", "fullsim.exe")
DEFAULT = [300, 600, 900]

work = sys.argv[1]
workers = int(sys.argv[2]) if len(sys.argv) > 2 else 6
only = set(sys.argv[3].split(",")) if len(sys.argv) > 3 else None
rows = [l.split("\t") for l in open(os.path.join(work, "plan.tsv"), encoding="utf-8").read().splitlines()[1:]]


def job(r):
    g, nolimit, nwatch = r[0], r[3] == "1", int(r[4])
    gd = os.path.abspath(os.path.join(work, g))
    out = os.path.join(gd, "rec")
    if os.path.exists(os.path.join(out, "done")):
        return f"{g} already done"
    os.makedirs(out, exist_ok=True)
    script = os.path.join(HERE, "scripts", g + ".txt")
    if not os.path.exists(script):
        script = os.path.join(HERE, "scripts", "generic.txt")
    frames = DEFAULT
    for line in open(script):
        if line.startswith("#frames"):
            frames = [int(x) for x in line.split()[1].split(",")]
    cmd = [FULLSIM, "--rom", os.path.join(gd, "rom.nes"), "--frames", str(max(frames) + 1),
           "--out", out, "--save", ",".join(str(f) for f in frames), "--rec", "--input", script]
    if nwatch:
        cmd += ["--watch", os.path.join(gd, "watch.txt")]
    if nolimit:
        cmd += ["--nolimit"]
    t = time.time()
    with open(os.path.join(out, "fullsim.log"), "w") as log:
        log.write(" ".join(cmd) + "\n")
        log.flush()
        rc = subprocess.run(cmd, cwd=PROJ, stdout=log, stderr=subprocess.STDOUT).returncode
    missing = [f for f in frames if not os.path.exists(os.path.join(out, f"rec_{f:04d}.bin"))]
    if rc == 0 and not missing:
        open(os.path.join(out, "done"), "w").write(f"{time.time() - t:.0f}s\n")
    return f"{g} rc={rc} {time.time() - t:.0f}s missing={missing}"


todo = [r for r in rows if not only or r[0] in only]
todo.sort(key=lambda r: 0 if os.path.exists(os.path.join(HERE, "scripts", r[0] + ".txt")) else 1)
print(f"{len(todo)} groups, {workers} workers, started {time.strftime('%H:%M:%S')}", flush=True)
with cf.ThreadPoolExecutor(workers) as ex:     # report each group as it finishes, not in order
    for fut in cf.as_completed([ex.submit(job, r) for r in todo]):
        print(time.strftime("%H:%M:%S"), fut.result(), flush=True)
print("all done", time.strftime("%H:%M:%S"), flush=True)
