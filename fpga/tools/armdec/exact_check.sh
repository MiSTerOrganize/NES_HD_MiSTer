#!/bin/sh
# exact_check.sh - after any hdarm4 speed change: every recorded frame must give
#   (1) the same decision dump as hdarm3 (whose dump matches hdref_decisions.py),
#   (2) the same display list, byte for byte, as a reference build's lists in REFDL, and
#   (3) that same display list again from a run WITHOUT the decision dump. The dump forces
#       every pixel through the full loop body (hdarm4's fast paths are off while it is on),
#       so (2) alone would never exercise the paths the daemon and the timing builds take.
# usage: sh exact_check.sh HDARM4_EXE HDARM3_EXE REFDL_DIR WORKDIR
#   REFDL_DIR holds <pack>_<frame>.dl from a build already proven pixel-exact
#   (dl_parity.sh / paint_parity.sh). Exit 0 only if all frames match on all three.
set -u
X=$1; H3=$2; REF=$3; W=$4; mkdir -p "$W"
HERE=$(cd "$(dirname "$0")" && pwd)
T=$HERE/../../../NES_HDPack_testdata
OUT=Z:/NES_HDPack_work/out
n=0; dec=0; dl=0; dln=0
for pr in a034:rec_mmm p002:rec_cv p053:rec_smb3 a057:rec_z2; do
    pk=${pr%%:*}; rd=${pr##*:}
    for r in "$T/$rd"/rec_*.bin; do
        f=$(basename "$r" .bin); f=${f#rec_}
        [ -f "$T/$rd/watch_$f.bin" ] || continue
        n=$((n + 1))
        rm -f "$W/a.txt" "$W/a.dl" "$W/c.dl"
        "$X" "$OUT/$pk.hdp" "$r" "$T/$rd/watch_$f.bin" --out "$W/a.txt" --dl "$W/a.dl" >/dev/null 2>&1 \
            || echo "RUN FAILED $pk $f"
        "$X" "$OUT/$pk.hdp" "$r" "$T/$rd/watch_$f.bin" --dl "$W/c.dl" >/dev/null 2>&1 \
            || echo "RUN FAILED (no dump) $pk $f"
        "$H3" "$OUT/$pk.hdp" "$r" "$T/$rd/watch_$f.bin" --out "$W/b.txt" >/dev/null 2>&1
        if cmp -s "$W/a.txt" "$W/b.txt"; then dec=$((dec + 1)); else echo "DECISIONS DIFFER $pk $f"; fi
        if cmp -s "$W/a.dl" "$REF/${pk}_$f.dl"; then dl=$((dl + 1)); else echo "DISPLAY LIST DIFFERS $pk $f"; fi
        if cmp -s "$W/c.dl" "$REF/${pk}_$f.dl"; then dln=$((dln + 1)); else echo "DISPLAY LIST (no dump) DIFFERS $pk $f"; fi
    done
done
echo "decisions identical: $dec of $n   display lists identical: $dl of $n   without the dump: $dln of $n"
[ "$dec" -eq "$n" ] && [ "$dl" -eq "$n" ] && [ "$dln" -eq "$n" ]
