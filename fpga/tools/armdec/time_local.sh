#!/bin/sh
# time_local.sh - time every bundled frame on THIS machine (x86). A ranking of which frames are
# heavy, not an A9 number. usage: sh time_local.sh HDARM_EXE PACK_DIR TESTDATA_DIR FRAMES_TXT [ITERS]
X=$1; P=$2; T=$3; F=$4; IT=${5:-20}
while read pk rd f; do
    r=$("$X" "$P/$pk.hdp" "$T/$rd/rec_$f.bin" "$T/$rd/watch_$f.bin" --iters "$IT" 2>&1)
    w=$(echo "$r" | sed -n 's/^rules_walked \([0-9]*\) conds_evaluated \([0-9]*\).*/\1 \2/p')
    tot=$(echo "$r" | sed -n 's/^TOTAL *min *\([0-9.]*\) ms *median *\([0-9.]*\) ms *max *\([0-9.]*\) ms.*/\2/p')
    lk=$(echo "$r" | sed -n 's/^lookups *min *\([0-9.]*\) ms *median *\([0-9.]*\).*/\2/p')
    echo "$pk $f rules/conds=$w total_med_ms=$tot lookups_med_ms=$lk"
done < "$F"
