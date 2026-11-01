#!/bin/sh
# hd3_add unit test (8a): every fixture through tb_add.exe (hd3_dict + hd3_add), checked pixel
# by pixel by check_add.py against the lane model (addhw.py, itself checked against
# hdref.process_additions).
#   sh tools/sim3/run_add.sh [testdata dir] [extra tb args...]
# EXE = the NL=64 build (every recorded and synthetic frame fits: the most lanes on a line is
# 52); SMALL_EXE, if set, = an NL=16 build: the heavy frames must come back overflowed and the
# light ones still exact.
#   OBJ=obj/add64 VFLAGS=-GNL=64 sh build_one.sh hd3_add_tb tb_add.cpp hd3_add_tb.sv \
#       ../../rtl/hdpack/hd3_dict.sv ../../rtl/hdpack/hd3_lookup.sv ../../rtl/hdpack/hd3_add.sv
# the real Python, never the WindowsApps alias (it leaked ~96 GB of commit)
PY=${PY:-/c/Users/miste/AppData/Local/Python/pythoncore-3.14-64/python.exe}
cd "$(dirname "$0")"
T=${1:-C:/Users/miste/OneDrive/Desktop/MiSTerOrganize/MiSTerFrontier/NES_HDPack_testdata}
[ $# -ge 1 ] && shift 1
EXE=${EXE:-./obj/add64/tb_add.exe}
OUT=${OUT:-obj/add_out}
mkdir -p "$OUT"
fail=0
run() {   # exe name pack game_ram recdir "bank:frame ..." [tb args]
	exe=$1 name=$2 pack=$3 gr=$4 dir=$T/$5 fr=$6; shift 6
	args="" nums=""
	for bf in $fr; do
		args="$args --frame ${bf%%:*}:$dir/rec_${bf#*:}.bin"
		nums="$nums $(echo ${bf#*:} | sed 's/^0*//')"
	done
	if ! "$exe" "$pack" "$OUT/$name.tsv" --game-ram "$gr" $args "$@" > "$OUT/$name.log" 2>&1; then
		echo "$name: testbench failed: $(tail -1 "$OUT/$name.log")"; fail=1; return
	fi
	printf '%s: ' "$name"
	"$PY" -I check_add.py "$OUT/$name.tsv" "$pack" "$dir" $nums > "$OUT/$name.chk" || fail=1
	tail -1 "$OUT/$name.chk"
}
z2="0:0300 1:0420 0:0700 1:1000"
cv="0:0250 1:0450 0:0700 1:1000 0:1300"
STD="--gap 25 --busy 40 --lat 60"
SER="--gap 25 --busy 90 --lat 1500"          # slow DDR3, frames one at a time
OVL="--gap 25 --busy 40 --lat 60 --overlap"  # ADD runs while the next frame is captured
# the converted packs' own additions, sections 16/17 added by hdp3_addtab.py (*_tab.hdp)
run "$EXE" z2t   obj/dict/a057_tab.hdp 0 rec_z2 "$z2" $STD --seed 5 "$@"
run "$EXE" cvt   obj/dict/p002_tab.hdp 1 rec_cv "$cv" $STD --seed 11 "$@"
# make_add_frame.py + hdp3_addtab.py (*_addt.hdp): BG sources, reversed file order, the
# 4-sprite cap, ignore-palette, fallback matches, a source on line 239 aimed at pixel (0,0)
run "$EXE" z2s   obj/dict/a057_addt.hdp 0 rec_z2 "$z2" $STD --seed 7 "$@"
run "$EXE" cvs   obj/dict/p002_addt.hdp 1 rec_cv "$cv" $STD --seed 13 "$@"
run "$EXE" cvsov obj/dict/p002_addt.hdp 1 rec_cv "$cv" $OVL --seed 17 "$@"
run "$EXE" cvsser obj/dict/p002_addt.hdp 1 rec_cv "$cv" $SER --seed 19 "$@"
# make_add_edge.py (edited frame 700 in rec_z2edge): a fifth covering sprite, hidden sprite
# pixels, two capture slots of one tile under different palettes, a mid-row scroll change,
# a vertically mirrored source, a clipped lane
run "$EXE" z2e   obj/dict/a057_edge.hdp 0 rec_z2edge "0:0700 1:0700" $STD --seed 53 "$@"
# make_add_srcline.py: one source line emits 70 lanes (limit 64) spread over 70 target lines
# (at most 8 on one): only the source-line limit can flag it, so the frame must overflow
run "$EXE" z2srcl obj/dict/a057_srcl.hdp 0 rec_z2 "0:0700 1:0700" $STD --seed 61 "$@"
# all in the SAME bank: frames repeated, and each frame with additions followed by frame 420,
# which has none (its pass ends after the record sweep, skipping the line-240 pass): every
# line, 240 included, must be cleared between frames
run "$EXE" z2rep obj/dict/a057_addt.hdp 0 rec_z2 \
	"0:0300 0:0420 0:0700 0:0700 0:0420 0:1000 0:1000 0:0420" $STD --seed 59 "$@"
# out of time: frames 0 and 2 aborted early and late in their passes (mid-line, bursts in
# flight); frames 1 and 3 (the same banks next) must still be exact
run "$EXE" cvsab obj/dict/p002_addt.hdp 1 rec_cv "$cv" $STD --abort 0:3000 --abort 2:200000 \
	--abort 4:1 --seed 43 "$@"
run "$EXE" z2tab obj/dict/a057_tab.hdp 0 rec_z2 "$z2" $OVL --pipelined --abort 2:20000 --seed 47 "$@"
# make_heavy_add.py: long merged lists (up to 64 entries a record), so source lines exceed the
# NB = 64 lanes one line can emit
run "$EXE" z2mix obj/dict/h_z2_mixed_t.hdp 0 rec_z2 "$z2" $STD --seed 23 "$@"
run "$EXE" cvmix obj/dict/h_cv_mixed_t.hdp 1 rec_cv "$cv" $STD --seed 29 "$@"
if [ -n "$SMALL_EXE" ]; then
	run "$SMALL_EXE" z2s16 obj/dict/a057_addt.hdp 0 rec_z2 "$z2" $STD --seed 31 "$@"
	run "$SMALL_EXE" cvs16 obj/dict/p002_addt.hdp 1 rec_cv "$cv" $OVL --seed 37 "$@"
	run "$SMALL_EXE" z2t16 obj/dict/a057_tab.hdp 0 rec_z2 "$z2" $OVL --seed 41 "$@"
fi
exit $fail
