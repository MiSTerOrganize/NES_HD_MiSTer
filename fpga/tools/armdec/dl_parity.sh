#!/bin/sh
# dl_parity.sh - the display-list design, checked end to end: hdarm4 makes its decisions, turns
# them into the display list, and the C painter (the FPGA's job) draws the frame from the list
# alone. Every recorded frame must equal hdref.py's render pixel for pixel.
# usage: sh dl_parity.sh HDARM4_EXE GOLD_DIR WORKDIR
#   GOLD_DIR holds <pack>_<frame>.png from hdref.py (e.g. scratchpad gold/make_gold.sh)
# the real Python, never the WindowsApps alias (it leaked ~96 GB of commit)
PY=${PY:-/c/Users/miste/AppData/Local/Python/pythoncore-3.14-64/python.exe}
X=$1; G=$2; W=$3; mkdir -p "$W"
HERE=$(cd "$(dirname "$0")" && pwd)
T=$HERE/../../../NES_HDPack_testdata
OUT=Z:/NES_HDPack_work/out
frames=0; ok=0
for pr in a034:rec_mmm p002:rec_cv p053:rec_smb3 a057:rec_z2; do
    pk=${pr%%:*}; rd=${pr##*:}
    for r in "$T/$rd"/rec_*.bin; do
        f=$(basename "$r" .bin); f=${f#rec_}
        [ -f "$T/$rd/watch_$f.bin" ] || continue
        frames=$((frames + 1))
        if ! "$X" "$OUT/$pk.hdp" "$r" "$T/$rd/watch_$f.bin" --img "$W/${pk}_$f.ppm" > "$W/${pk}_$f.log" 2>&1; then
            echo "$pk $f RUN FAILED"; cat "$W/${pk}_$f.log"; continue
        fi
        res=$("$PY" "$HERE/img_cmp.py" "$G/${pk}_$f.png" "$W/${pk}_$f.ppm")
        rc=$?
        cmds=$(sed -n 's/^display list: \([0-9]*\) commands.*needed per-pixel order/\1/p' "$W/${pk}_$f.log")
        pp=$(sed -n 's/^display list: .*commands (.*), \([0-9]*\) lines needed.*/\1/p' "$W/${pk}_$f.log")
        echo "$pk $f cmds=$cmds perpixel_lines=$pp : $(echo "$res" | head -1)"
        [ $rc -eq 0 ] && ok=$((ok + 1)) || echo "$res" | tail -n +2
    done
done
echo "PIXEL-EXACT $ok of $frames"
[ "$ok" -eq "$frames" ]
