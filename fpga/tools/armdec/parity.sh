#!/bin/sh
# parity.sh - hdarm (C) must reproduce hdref_decisions.py (Python) byte for byte on every
# recorded frame, and each negative-control mutant must differ on at least one frame.
# usage: CC=/c/msys64/mingw64/bin/gcc [SRC=hdarm2.c] sh parity.sh WORKDIR
#   SRC defaults to hdarm.c (the straight port). For hdarm2.c the extra mutant MUT_MEMOALL
#   (memoise every key, not just static ones) is also run and REPORTED, not required: it says
#   whether these frames exercise the static/non-static distinction at all.
# Do NOT put mingw64/bin first on PATH: it carries its own python without numpy, and hdref
# then fails (2026-10-21: every reference came out empty).
# the real Python, never the WindowsApps alias (it leaked ~96 GB of commit)
PY=${PY:-/c/Users/miste/AppData/Local/Python/pythoncore-3.14-64/python.exe}
set -u
W=$1; mkdir -p "$W"
CC=${CC:-gcc}
HERE=$(cd "$(dirname "$0")" && pwd)
SRC=${SRC:-hdarm.c}
T=$HERE/../../../NES_HDPack_testdata
OUT=Z:/NES_HDPack_work/out
PAIRS="a034:rec_mmm p002:rec_cv p053:rec_smb3 a057:rec_z2"
MUTS="NEGATE NOADD NEARBY"
case "$SRC" in hdarm2.c) MUTS="$MUTS MEMOALL";; hdarm3.c) MUTS="$MUTS MEMOALL NOP0 NOWT";; esac
for m in NONE $(for x in $MUTS; do echo MUT_$x; done); do
    PATH="$(dirname "$CC"):$PATH" "$CC" -O2 -D$m -o "$W/hdarm_$m.exe" "$HERE/$SRC" \
        || { echo "build $m failed"; exit 1; }
done
frames=0; ok=0
diffs_NEGATE=0; diffs_NOADD=0; diffs_NEARBY=0; diffs_MEMOALL=0; diffs_NOP0=0; diffs_NOWT=0
for pr in $PAIRS; do
    pk=${pr%%:*}; rd=${pr##*:}
    for r in "$T/$rd"/rec_*.bin; do
        f=$(basename "$r" .bin); f=${f#rec_}
        [ -f "$T/$rd/watch_$f.bin" ] || continue
        ref="$W/${pk}_$f.ref"
        if [ ! -s "$ref" ]; then
            "$PY" "$HERE/hdref_decisions.py" "$OUT/$pk.hdp" "$T/$rd" --frame $((10#$f)) \
                2>"$W/py.err" | tr -d '\r' > "$ref"
            if [ ! -s "$ref" ]; then echo "REFERENCE FAILED $pk $f:"; cat "$W/py.err"; exit 1; fi
        fi
        frames=$((frames + 1))
        if ! "$W/hdarm_NONE.exe" "$OUT/$pk.hdp" "$r" "$T/$rd/watch_$f.bin" --out "$W/c.txt" 2>"$W/c.err"; then
            echo "RUN FAILED $pk frame $f:"; cat "$W/c.err"
        fi
        if cmp -s "$W/c.txt" "$ref"; then ok=$((ok + 1)); else echo "MISMATCH $pk frame $f"; fi
        for m in $MUTS; do
            "$W/hdarm_MUT_$m.exe" "$OUT/$pk.hdp" "$r" "$T/$rd/watch_$f.bin" --out "$W/m.txt" 2>/dev/null
            if ! cmp -s "$W/m.txt" "$ref"; then eval "diffs_$m=\$((diffs_$m + 1))"; fi
        done
    done
done
echo "parity ($SRC): $ok of $frames frames identical"
echo "mutant MUT_NEGATE differs on $diffs_NEGATE frames"
echo "mutant MUT_NOADD  differs on $diffs_NOADD frames"
echo "mutant MUT_NEARBY differs on $diffs_NEARBY frames"
case " $MUTS " in *" MEMOALL "*) echo "mutant MUT_MEMOALL differs on $diffs_MEMOALL frames (informational)";; esac
case " $MUTS " in *" NOP0 "*)
    echo "mutant MUT_NOP0   differs on $diffs_NOP0 frames (informational: (0,0) line alias)"
    echo "mutant MUT_NOWT   differs on $diffs_NOWT frames (informational: tile-rewrite overlay)";; esac
[ "$ok" -eq "$frames" ] && [ "$diffs_NEGATE" -gt 0 ] && [ "$diffs_NOADD" -gt 0 ] && [ "$diffs_NEARBY" -gt 0 ]
