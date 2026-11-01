#!/bin/sh
# paint_parity.sh - hd3_paint (RTL, Verilator) on every recorded frame: hdarm4 writes the
# display list, tb_paint paints it from the pack's blocks with random DDR3 latency and line_ok,
# and the picture must equal hdref.py's render pixel for pixel.
# usage: sh tools/sim3/paint_parity.sh HDARM4_EXE GOLD_DIR WORKDIR [seed] [pub]
#   pub = the list is published progressively and unpublished qwords hold garbage
#   run from the NES_HDPack folder, after: sh tools/sim3/build_one.sh hd3_paint
#   tools/sim3/tb_paint.cpp rtl/hdpack/hd3_paint.sv
# the real Python, never the WindowsApps alias (it leaked ~96 GB of commit)
PY=${PY:-/c/Users/miste/AppData/Local/Python/pythoncore-3.14-64/python.exe}
X=$1; G=$2; W=$3; SEED=${4:-1}; MODE=${5:-}; mkdir -p "$W"
R=$(pwd)
T=$R/../NES_HDPack_testdata
OUT=Z:/NES_HDPack_work/out
TB=$R/tools/sim3/obj/tb_paint.exe
frames=0; ok=0
for pr in a034:rec_mmm p002:rec_cv p053:rec_smb3 a057:rec_z2; do
    pk=${pr%%:*}; rd=${pr##*:}
    for r in "$T/$rd"/rec_*.bin; do
        f=$(basename "$r" .bin); f=${f#rec_}
        [ -f "$T/$rd/watch_$f.bin" ] || continue
        frames=$((frames + 1))
        "$X" "$OUT/$pk.hdp" "$r" "$T/$rd/watch_$f.bin" --dl "$W/${pk}_$f.dl" > /dev/null 2>&1 || { echo "$pk $f hdarm4 FAILED"; continue; }
        tbo=$(cd "$R/rtl/hdpack" && "$TB" "$OUT/$pk.hdp" "$W/${pk}_$f.dl" "$W/${pk}_${f}_rtl.ppm" "$SEED" $MODE 2>&1) || { echo "$pk $f TB FAILED: $tbo"; continue; }
        res=$("$PY" "$R/tools/armdec/img_cmp.py" "$G/${pk}_$f.png" "$W/${pk}_${f}_rtl.ppm")
        rc=$?
        per=$(echo "$tbo" | sed -n 's/.*(\([0-9.]*\) per NES line).*/\1/p')
        echo "$pk $f clocks/line=$per : $(echo "$res" | head -1)"
        [ $rc -eq 0 ] && ok=$((ok + 1)) || echo "$res" | tail -n +2
    done
done
echo "RTL PIXEL-EXACT $ok of $frames"
[ "$ok" -eq "$frames" ]
