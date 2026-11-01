"""mesen_tune.py - run every corpus group's ROM in Mesen (no HD pack) with its input script and
save screenshots, so each game's input can be checked and tuned cheaply before the slow fullsim
recording. Frame numbers are fullsim's; Mesen frame = fullsim frame + 2 (MESEN_INPUT_OFFSET=2
replays the script on the same frames, and screenshot F+2 is fullsim frame F).

    python -I mesen_tune.py WORK [g03,g07,...]

Reads WORK/plan.tsv; per group uses scripts/<group>.txt if it exists, else scripts/generic.txt.
Writes WORK/<group>/tune_<frame>.png and WORK/<group>/tune.png (a contact sheet if PIL is
available).
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MESEN = os.path.normpath(os.path.join(HERE, "..", "..", "..", "NES_HDPack_testdata", "tools", "mesen2"))
FRAMES = [120, 300, 600, 900, 1200, 1500]

work = sys.argv[1]
only = set(sys.argv[2].split(",")) if len(sys.argv) > 2 else None
rows = [l.split("\t") for l in open(os.path.join(work, "plan.tsv"), encoding="utf-8").read().splitlines()[1:]]
for r in rows:
    g = r[0]
    if only and g not in only:
        continue
    gd = os.path.abspath(os.path.join(work, g))
    script = os.path.join(HERE, "scripts", g + ".txt")
    if not os.path.exists(script):
        script = os.path.join(HERE, "scripts", "generic.txt")
    frames = FRAMES
    for line in open(script):
        if line.startswith("#frames"):            # per-game shot frames, used by the batch too
            frames = [int(x) for x in line.split()[1].split(",")]
    env = dict(os.environ, MESEN_SHOTS=",".join(str(f + 2) for f in frames),
               MESEN_OUT=os.path.join(gd, "mtune"), MESEN_INPUT=script, MESEN_INPUT_OFFSET="2")
    # Mesen looks for HdPacks/<rom name>; "rom.nes" has none, so this is the plain picture
    p = subprocess.run([os.path.join(MESEN, "Mesen.exe"), "--testrunner", os.path.join(gd, "rom.nes"),
                        os.path.join(MESEN, "shots.lua")], cwd=MESEN, env=env, timeout=300,
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    shots = []
    for old in os.listdir(gd):                    # a previous run's frames must not linger
        if old.startswith("tune_") and old.endswith(".png"):
            os.remove(os.path.join(gd, old))
    for f in frames:
        src = os.path.join(gd, f"mtune_{f + 2:04d}.png")
        if os.path.exists(src):
            dst = os.path.join(gd, f"tune_{f:04d}.png")
            os.replace(src, dst)
            shots.append(dst)
    print(f"{g} rc={p.returncode} shots={len(shots)}/{len(frames)} script={os.path.basename(script)} {r[1]}")
    try:
        from PIL import Image
    except ImportError:
        continue
    if shots:
        ims = [Image.open(s).convert("RGB") for s in shots]
        w, h = ims[0].size
        sheet = Image.new("RGB", (w * len(ims), h))
        for i, im in enumerate(ims):
            sheet.paste(im.resize((w, h)), (i * w, 0))
        sheet.save(os.path.join(gd, "tune.png"))
