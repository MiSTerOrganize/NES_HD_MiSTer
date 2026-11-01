#!/bin/sh
# time_all.sh - hdarm4 per-frame cost (median and worst of N iterations) on every recorded frame.
# usage: sh time_all.sh HDARM4_EXE [ITERS]
# Prints one line per frame with hdarm4's own timing summary (total median), then the worst frame.
set -u
X=$1; N=${2:-20}
HERE=$(cd "$(dirname "$0")" && pwd)
T=$HERE/../../../NES_HDPack_testdata
OUT=Z:/NES_HDPack_work/out
for pr in a034:rec_mmm p002:rec_cv p053:rec_smb3 a057:rec_z2; do
    pk=${pr%%:*}; rd=${pr##*:}
    for r in "$T/$rd"/rec_*.bin; do
        f=$(basename "$r" .bin); f=${f#rec_}
        [ -f "$T/$rd/watch_$f.bin" ] || continue
        line=$("$X" "$OUT/$pk.hdp" "$r" "$T/$rd/watch_$f.bin" --iters "$N" 2>&1 | grep -E "^TOTAL" | head -1)
        echo "$pk $f  $line"
    done
done
