"""publish_repo.py - assemble the public NES_HD_MiSTer layout (the MiSTer Frontier hybrid-core
shape, same as MiSTer_PICO-8 / MiSTer_OpenBOR_7533) from this dev workspace.

    python publish_repo.py <clone of NES_HD_MiSTer> [--apply]

Dry run by default: prints what it would copy. --apply writes into the clone's working tree
(git mv for the upstream files on the first run, then plain copies); committing is left to you.

Layout written:
    fpga/          Quartus project: NES.qpf/.qsf/.sdc/.srf/.sv, NES_PAINT.qsf, files.qip, rtl/, sys/,
                   the Quartus 13 project, clean.bat, output_files/NES_PAINT.*.summary
    src/           the ARM daemon source + build_arm.sh (CI builds games/NES_HD/NES_HD from it)
    games/NES_HD/  _handler.sh, Palette/ (NES_HD is the CI-built daemon, not copied here)
    _Other/        NES_HD_<date>.rbf
    docs/NES_HD/README.md (= README.md), docs/dev/  design notes
    tools/         the HD pack converter (.hdp maker) and its audio decoder source
The dev log (OPEN_ITEMS.md), the corpus pipeline, simulators, recordings and test ROMs stay
private. Nothing here reads or writes ROMs.
"""
import hashlib
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
WS = os.path.normpath(os.path.join(HERE, ".."))          # NES_HDPack
RBF_DATE = "20261029"
RBF_MD5 = "cee5a8b1"                                     # NES_PAINT.rbf on the MiSTer, prefix

FPGA_FILES = ["NES.qpf", "NES.qsf", "NES.sdc", "NES.srf", "NES.sv", "NES_PAINT.qsf", "files.qip",
              "NES_Q13.qpf", "NES_Q13.qsf", "NES_Q13.srf", "clean.bat"]
FPGA_TREES = ["rtl", "sys"]
SUMMARIES = ["NES_PAINT.sta.summary", "NES_PAINT.fit.summary", "NES_PAINT.map.summary"]
SRC = ["hdarm4.c", "hdarm_daemon.c", "hdarm_rec.h", "romfix_arm.c", "romfix_arm.h", "aud_arm.c",
       "aud_arm.h"]
DOCS_DEV = ["HDPACK_DESIGN.md", "MESEN_HD_RUNTIME_SPEC.md", "LUA_SCOPE.md"]
TOOLS = ["hdp3_convert.py", "hdpack_model.py", "hdp3_patch.py", "hdp3_addtab.py", "hdp3_read.py",
         "pngdec.py", "pngio.py", "pack_fixes.py", "rompatch.py", "rommatch.py",
         # test_hdp3_patch.py / test_rommatch.py stay private: they read the dev corpus (Z:)
         "test_rompatch.py", "test_pngdec_fast.py",
         "audio/hdaudio.py", "audio/oggdecode.cpp", "audio/pch.h", "audio/build.sh"]
TOOL_TREES = ["audio/mesen"]
SKIP_DIRS = {"obj", "__pycache__", "db", "incremental_db"}
SKIP_EXT = {".pyc", ".bak", ".orig", ".exe", ".o"}


def files_under(root):
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d not in SKIP_DIRS]
        for f in fns:
            if os.path.splitext(f)[1].lower() not in SKIP_EXT:
                yield os.path.join(dp, f)


def plan(repo):
    out = []                                              # (src, dst)
    for f in FPGA_FILES:
        out.append((os.path.join(WS, f), os.path.join(repo, "fpga", f)))
    for t in FPGA_TREES:
        for p in files_under(os.path.join(WS, t)):
            out.append((p, os.path.join(repo, "fpga", os.path.relpath(p, WS))))
    for f in SUMMARIES:
        out.append((os.path.join(WS, "output_files", f), os.path.join(repo, "fpga", "output_files", f)))
    for f in SRC:
        out.append((os.path.join(WS, "tools", "armdec", f), os.path.join(repo, "src", f)))
    out.append((os.path.join(WS, "games", "NES_HD", "_handler.sh"),
                os.path.join(repo, "games", "NES_HD", "_handler.sh")))
    for p in files_under(os.path.join(WS, "Palette")):
        out.append((p, os.path.join(repo, "games", "NES_HD", os.path.relpath(p, WS))))
    out.append((os.path.join(WS, "output_files", "NES_PAINT.rbf"),
                os.path.join(repo, "_Other", f"NES_HD_{RBF_DATE}.rbf")))
    for f in DOCS_DEV:
        out.append((os.path.join(WS, f), os.path.join(repo, "docs", "dev", f)))
    for f in TOOLS:
        out.append((os.path.join(WS, "tools", f), os.path.join(repo, "tools", f)))
    for t in TOOL_TREES:
        for p in files_under(os.path.join(WS, "tools", t)):
            out.append((p, os.path.join(repo, "tools", os.path.relpath(p, os.path.join(WS, "tools")))))
    out.append((os.path.join(WS, "tools", "corpus", "romindex.tsv"),
                os.path.join(repo, "tools", "corpus", "romindex.tsv")))
    return out


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    repo, apply_it = os.path.abspath(sys.argv[1]), "--apply" in sys.argv
    if not os.path.isdir(os.path.join(repo, ".git")):
        raise SystemExit(f"not a git clone: {repo}")
    rbf = os.path.join(WS, "output_files", "NES_PAINT.rbf")
    if not hashlib.md5(open(rbf, "rb").read()).hexdigest().startswith(RBF_MD5):
        raise SystemExit("output_files/NES_PAINT.rbf is not the RBF on the MiSTer - rebuilt? update RBF_DATE/RBF_MD5")
    items = plan(repo)
    missing = [s for s, _ in items if not os.path.isfile(s)]
    if missing:
        raise SystemExit("missing source files:\n  " + "\n  ".join(missing))
    git = lambda *a: subprocess.run(["git", "-C", repo, *a], check=True)  # noqa: E731
    if apply_it and os.path.isfile(os.path.join(repo, "NES.qpf")):
        # first run: move the upstream files so history follows them
        os.makedirs(os.path.join(repo, "fpga"), exist_ok=True)
        for f in FPGA_FILES + FPGA_TREES:
            if os.path.exists(os.path.join(repo, f)):
                git("mv", f, f"fpga/{f}")
        os.makedirs(os.path.join(repo, "games", "NES_HD"), exist_ok=True)
        git("mv", "Palette", "games/NES_HD/Palette")
        git("rm", "-r", "-q", "releases", "COPYING")
    n = 0
    for s, d in items:
        same = os.path.isfile(d) and open(s, "rb").read() == open(d, "rb").read()
        if not same:
            n += 1
            print(("copy " if apply_it else "would copy ") + os.path.relpath(d, repo))
            if apply_it:
                os.makedirs(os.path.dirname(d), exist_ok=True)
                shutil.copyfile(s, d)
    print(f"{len(items)} files, {n} {'copied' if apply_it else 'to copy'}")


if __name__ == "__main__":
    main()
