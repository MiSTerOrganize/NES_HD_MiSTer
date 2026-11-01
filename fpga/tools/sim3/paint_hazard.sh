#!/bin/sh
# paint_hazard.sh - hd3_paint must not start a span before the last one's writes have landed.
# For each display list paint_parity.sh produced, paint_hazard.py makes TIGHT (a span starting
# on the pixel the previous one wrote last) and GAP (the same, delayed by FX commands that
# change nothing); tb_paint must paint both to the same picture.
# usage: sh tools/sim3/paint_hazard.sh DL_DIR WORKDIR [seed]
#   DL_DIR = a paint_parity.sh WORKDIR (holds <pack>_<frame>.dl); run from NES_HDPack after
#   sh tools/sim3/build_one.sh hd3_paint tools/sim3/tb_paint.cpp rtl/hdpack/hd3_paint.sv
# the real Python, never the WindowsApps alias (it leaked ~96 GB of commit)
PY=${PY:-/c/Users/miste/AppData/Local/Python/pythoncore-3.14-64/python.exe}
D=$1; W=$2; SEED=${3:-1}; mkdir -p "$W"
R=$(pwd)
OUT=Z:/NES_HDPack_work/out
TB=$R/tools/sim3/obj/tb_paint.exe
frames=0; ok=0; skip=0
for dl in "$D"/*.dl; do
    n=$(basename "$dl" .dl); pk=${n%%_*}
    case "$n" in *_tight|*_gap) continue ;; esac
    "$PY" -I "$R/tools/sim3/paint_hazard.py" "$dl" "$W/${n}_tight.dl" "$W/${n}_gap.dl" > /dev/null
    rc=$?
    [ $rc -eq 3 ] && { skip=$((skip + 1)); continue; }      # no BLIT in the frame
    frames=$((frames + 1))
    [ $rc -eq 0 ] || { echo "$n transform FAILED"; continue; }
    for v in tight gap; do
        (cd "$R/rtl/hdpack" && "$TB" "$OUT/$pk.hdp" "$W/${n}_$v.dl" "$W/${n}_$v.ppm" "$SEED") \
            > /dev/null 2>&1 || echo "$n $v TB FAILED"
    done
    if cmp -s "$W/${n}_tight.ppm" "$W/${n}_gap.ppm"; then ok=$((ok + 1)); else echo "$n DIFFERS"; fi
done
echo "PAINT HAZARD: $ok of $frames frames identical with and without the gap ($skip without a BLIT)"
[ "$frames" -gt 0 ] && [ "$ok" -eq "$frames" ]
