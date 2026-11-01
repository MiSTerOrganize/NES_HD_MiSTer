#!/bin/sh
# time_dl.sh - hdarm4 per-phase medians (ms) on every recorded frame, on this machine.
# usage: sh time_dl.sh HDARM4_EXE [ITERS]
X=$1; IT=${2:-30}
HERE=$(cd "$(dirname "$0")" && pwd)
T=$HERE/../../../NES_HDPack_testdata
OUT=Z:/NES_HDPack_work/out
printf "%-10s %8s %8s %8s %8s %8s %8s\n" frame records levels addit lookups dlist TOTAL
for pr in a034:rec_mmm p002:rec_cv p053:rec_smb3 a057:rec_z2; do
    pk=${pr%%:*}; rd=${pr##*:}
    for r in "$T/$rd"/rec_*.bin; do
        f=$(basename "$r" .bin); f=${f#rec_}
        [ -f "$T/$rd/watch_$f.bin" ] || continue
        o=$("$X" "$OUT/$pk.hdp" "$r" "$T/$rd/watch_$f.bin" --iters "$IT" 2>&1)
        m() { echo "$o" | sed -n "s/^$1 *min *[0-9.]* ms *median *\([0-9.]*\).*/\1/p"; }
        printf "%-10s %8s %8s %8s %8s %8s %8s\n" "${pk}_$f" "$(m records)" "$(m levels)" "$(m additions)" \
            "$(m lookups)" "$(m displaylist)" "$(m TOTAL)"
    done
done
