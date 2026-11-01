#!/bin/sh
# rec_subset_check.sh - run rec_subset_test on every recorded frame of the four test packs.
# usage: sh rec_subset_check.sh WORKDIR     (builds into WORKDIR; SUBSET_BREAK=1 = the control)
set -u
W=$1; mkdir -p "$W"
HERE=$(cd "$(dirname "$0")" && pwd)
T=$HERE/../../../NES_HDPack_testdata
OUT=Z:/NES_HDPack_work/out
export PATH=/c/msys64/mingw64/bin:$PATH
gcc -O2 -DHDARM_LIB -c -o "$W/h4lib.o" "$HERE/hdarm4.c" || exit 2
gcc -O2 -Wall -o "$W/rec_subset_test.exe" "$HERE/rec_subset_test.c" "$W/h4lib.o" -lm || exit 2
rc=0
for pr in a034:rec_mmm p002:rec_cv p053:rec_smb3 a057:rec_z2; do
    pk=${pr%%:*}; rd=${pr##*:}
    set --
    for r in "$T/$rd"/rec_*.bin; do
        f=$(basename "$r" .bin); f=${f#rec_}
        [ -f "$T/$rd/watch_$f.bin" ] || continue
        set -- "$@" "$r" "$T/$rd/watch_$f.bin"
    done
    "$W/rec_subset_test.exe" "$OUT/$pk.hdp" "$@" | tail -1 | sed "s/^/$pk: /" || rc=1
    "$W/rec_subset_test.exe" "$OUT/$pk.hdp" "$@" >/dev/null || rc=1
done
exit $rc
