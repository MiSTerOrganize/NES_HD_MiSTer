#!/bin/sh
# memo_parity.sh - an hdarm4 speed change must not change one decision. Builds hdarm4 three
# ways (as is; -DNO_DEPMEMO; -DMUT_DEPLOOSE negative control) plus the parity-verified hdarm3,
# and compares the decision dumps (--out) of every recorded frame.
#   PASS = hdarm4 == hdarm4 NO_DEPMEMO == hdarm3 on every frame, AND the loose mutant differs
#          on at least one frame (proof the frames exercise the memo's dependency check).
# usage: sh memo_parity.sh WORKDIR     (gcc from /c/msys64/mingw64/bin)
set -u
W=$1; mkdir -p "$W"
HERE=$(cd "$(dirname "$0")" && pwd)
T=$HERE/../../../NES_HDPack_testdata
OUT=Z:/NES_HDPack_work/out
GCC=/c/msys64/mingw64/bin/gcc
b() { PATH=/c/msys64/mingw64/bin:$PATH "$GCC" -O2 "$@" -lm || { echo "build failed: $*"; exit 1; }; }
b -o "$W/h4.exe" "$HERE/hdarm4.c"
b -DNO_DEPMEMO -o "$W/h4n.exe" "$HERE/hdarm4.c"
b -DMUT_DEPLOOSE -o "$W/h4l.exe" "$HERE/hdarm4.c"
b -o "$W/h3.exe" "$HERE/hdarm3.c"
frames=0; ok=0; loose=0
for pr in a034:rec_mmm p002:rec_cv p053:rec_smb3 a057:rec_z2; do
    pk=${pr%%:*}; rd=${pr##*:}
    for r in "$T/$rd"/rec_*.bin; do
        f=$(basename "$r" .bin); f=${f#rec_}
        [ -f "$T/$rd/watch_$f.bin" ] || continue
        frames=$((frames + 1))
        for v in h4 h4n h4l h3; do
            "$W/$v.exe" "$OUT/$pk.hdp" "$r" "$T/$rd/watch_$f.bin" --out "$W/$v.txt" 2>"$W/$v.err" \
                || { echo "$v FAILED $pk $f"; cat "$W/$v.err"; }
        done
        if cmp -s "$W/h4.txt" "$W/h4n.txt" && cmp -s "$W/h4.txt" "$W/h3.txt"; then ok=$((ok + 1))
        else echo "MISMATCH $pk $f"; fi
        cmp -s "$W/h4l.txt" "$W/h4.txt" || loose=$((loose + 1))
        hits=$(sed -n 's/.*dep_reuse \([0-9]*\).*/\1/p' "$W/h4.err")
        echo "$pk $f dep_reuse=$hits"
    done
done
echo "decisions identical: $ok of $frames"
echo "loose mutant differs on $loose frames"
[ "$ok" -eq "$frames" ] && [ "$loose" -gt 0 ]
