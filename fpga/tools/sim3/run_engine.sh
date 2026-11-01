#!/bin/sh
# hd3_engine integration test: fixture frames through tb_engine.exe (pack load over the OSD
# port, records at the NES line rate on the core clock, the engine on the HD clock, its own
# scan-out captured), each shown frame compared pixel for pixel with hdref (check_render.py).
#   sh run_engine.sh [quick|full] [testdata dir] [pack dir]
# quick: the small packs only (SMB p053 and the lane fixtures) - the negative control's set.
# full:  also the 40-75 MB packs (Metroid, Castlevania, Zelda II, the Castlevania addition
#        fixtures); the pack load alone is ~1.25 core clocks per byte, so this takes an hour.
# EXE overrides the binary; OUT the output folder; REF adds check_render.py flags;
# TBARGS adds testbench flags (default: --busy 20 --ss 2 - DDR3 stalls and savestate traffic).
# ABORT_EXE, if set (built with -GADD_BUDGET=20), reruns the addition fixture with every ADD
# aborted: every frame must then be drawn without lookups (the reference with --raw 0).
# the real Python, never the WindowsApps alias (it leaked ~96 GB of commit)
PY=${PY:-/c/Users/miste/AppData/Local/Python/pythoncore-3.14-64/python.exe}
cd "$(dirname "$0")"
MODE=${1:-quick}
T=${2:-C:/Users/miste/OneDrive/Desktop/MiSTerOrganize/MiSTerFrontier/NES_HDPack_testdata}
P=${3:-Z:/NES_HDPack_work/out}
S3=$(pwd -W)
EXE=${EXE:-$S3/obj/engine/tb_engine.exe}
OUT=${OUT:-$S3/obj/engine_out}
REF=${REF-}
TBARGS=${TBARGS:---busy 20 --ss 2}
# the testbench runs in the RTL folder: hd3_scanout reads its palette .hex files from there
RTL=${RTLDIR:-$(cd ../../rtl/hdpack && pwd -W)}
FIX=$S3/obj/engine_fix                   # fixtures this script makes (make_ov_pack.py, make_light.py)
mkdir -p "$OUT" "$FIX"
fail=0
run() {   # name pack game_ram recdir "bank:frame ..." [extra testbench flags]
	name=$1 pack=$2 gr=$3 dir=$4 fr=$5 extra=$6
	args="" nums=""
	case $dir in ?:/*) ;; obj/*) dir=$S3/$dir ;; fix/*) dir=$FIX/${dir#fix/} ;; *) dir=$T/$dir ;; esac
	for bf in $fr; do
		args="$args --frame ${bf%%:*}:$dir/rec_${bf#*:}.bin"
		nums="$nums $(echo ${bf#*:} | sed 's/^0*//')"
	done
	case $pack in ?:/*) ;; obj/*) pack=$S3/$pack ;; fix/*) pack=$FIX/${pack#fix/} ;; *) pack=$P/$pack ;; esac
	if ! (cd "$RTL" && "$EXE" "$pack" "$OUT/$name" --game-ram "$gr" $args $TBARGS $extra) > "$OUT/$name.log" 2>&1; then
		echo "$name: testbench failed:"; grep -E "FAIL|timeout|underflow first" "$OUT/$name.log" | head -5 | sed 's/^/  /'
		fail=1; return
	fi
	grep -E "shown|accesses|pack loaded" "$OUT/$name.log" | sed 's/^/  /'
	(cd "$S3" && "$PY" -I check_render.py "$pack" "$dir" "$OUT/$name" $nums --game-ram "$gr" $REF) > "$OUT/$name.chk" 2>&1
	st=$?
	echo "$name:"; sed "s/^/  /" "$OUT/$name.chk"
	[ $st -eq 0 ] || fail=1
}
quick() {
	run smb p053.hdp 0 rec_smb3 "0:0240 1:0270 0:0300"
	run lane obj/dict/lane.hdp 0 obj/dict/rec_mmml0 "0:0880"
	# DDR3 busy in long bursts (150 HD clocks): the pack-load and record crossings fill and must
	# hold the loader / capture back without losing a qword
	run lanenz obj/dict/lane_nz.hdp 0 obj/dict/rec_mmml0 "0:0880" "--busy 1 --busy-burst 150"
	# the lane pack with an asymmetric overscan window (make_ov_pack.py 8 16 4 8; the packs
	# above have -1, clamped to 0): black outside it, the window at the right place
	[ -f "$FIX/lane_ov.hdp" ] || "$PY" -I make_ov_pack.py "$S3/obj/dict/lane.hdp" "$FIX/lane_ov.hdp" 8 16 4 8 > /dev/null
	run laneov fix/lane_ov.hdp 0 obj/dict/rec_mmml0 "0:0880"
	# SMB frames alternating with light ones (make_light.py: one tile row repeated, no sprites
	# or spans), whose ADD + RESOLVE finish so early that RENDER starts the next frame at
	# disp_y 238 - before the frame on screen has shown its last line, which must then still
	# be shown (the finished frame, not the one starting)
	[ -f "$FIX/light/rec_9300.bin" ] || { "$PY" -I make_light.py "$T/rec_smb3" 0270 9270 > /dev/null &&
		"$PY" -I make_light.py "$T/rec_smb3" 0300 9300 > /dev/null &&
		cp "$T/rec_smb3/rec_0240.bin" "$T/rec_smb3/watch_0240.bin" "$T/rec_smb3/rec_0300.bin" \
		   "$T/rec_smb3/watch_0300.bin" "$FIX/light/"; }
	run light p053.hdp 0 fix/light "0:0240 1:9270 0:0300 1:9300"
	slow
}
# a DDR3 slow enough that RENDER falls behind the scan-out part-way through SMB frame 240:
# underflow must be reported, and every line must be either the in-time picture (the smb run's)
# or wholly black - never a line shown part-drawn or from another frame (slow_check.py)
slow() {
	d=$T/rec_smb3
	if ! (cd "$RTL" && "$EXE" "$P/p053.hdp" "$OUT/slow" --game-ram 0 --frame 0:$d/rec_0240.bin \
	      --frame 1:$d/rec_0270.bin --busy 60 --lat 300 --expect-late 1) > "$OUT/slow.log" 2>&1; then
		echo "slow: testbench failed:"; grep -E "FAIL" "$OUT/slow.log" | head -5 | sed 's/^/  /'; fail=1; return
	fi
	"$PY" -I slow_check.py "$OUT/smb_0240.rgb" "$OUT/slow_0240.rgb" > "$OUT/slow.chk" 2>&1
	st=$?
	echo "slow:"; sed "s/^/  /" "$OUT/slow.chk"
	[ $st -eq 0 ] || fail=1
	# a DDR3 just slow enough that RENDER keeps roughly the scan-out's pace (latency 250 here:
	# 150 is in time, 300 falls behind for good): it is caught and passed repeatedly, so lines are
	# decided while RENDER is drawing the very line being shown - which must then be blanked,
	# never shown part-drawn (the testbench checks no shown line is written while on screen)
	if ! (cd "$RTL" && "$EXE" "$P/p053.hdp" "$OUT/pace" --game-ram 0 --frame 0:$d/rec_0240.bin \
	      --frame 1:$d/rec_0270.bin --busy 60 --lat 250 --expect-late 1) > "$OUT/pace.log" 2>&1; then
		echo "pace: testbench failed:"; grep -E "FAIL" "$OUT/pace.log" | head -5 | sed 's/^/  /'; fail=1; return
	fi
	"$PY" -I slow_check.py "$OUT/smb_0240.rgb" "$OUT/pace_0240.rgb" > "$OUT/pace.chk" 2>&1
	st=$?
	echo "pace:"; sed "s/^/  /" "$OUT/pace.chk"
	[ $st -eq 0 ] || fail=1
}
full() {
	run mmm a034.hdp 0 rec_mmm "0:0200 1:0400 0:0880 1:1020"
	run cv p002.hdp 1 rec_cv "0:0250 1:0450 0:0700 1:1000 0:1300"
	# the watch snapshot finishing 14 lines late (the bank answers noise until then): RESOLVE
	# must wait for it, and the frames still be drawn in time
	run cvw p002.hdp 1 rec_cv "0:0250 1:0450 0:0700" "--watch-line 255"
	run z2 a057.hdp 0 rec_z2 "0:0300 1:0420 0:0700 1:1000"
	run cvd obj/dict/p002_addd.hdp 1 rec_cv "0:0250 1:0700"
	run cvmix obj/dict/h_cv_mixed_t.hdp 1 rec_cv "0:0250 1:0450 0:0700 1:1000 0:1300"
}
case $MODE in
	quick) quick ;;
	full) quick; full ;;
	cvw) run cvw p002.hdp 1 rec_cv "0:0250 1:0450 0:0700" "--watch-line 255" ;;
	abort) ;;                                   # only the ABORT_EXE pass below
	*) echo "unknown mode $MODE"; exit 2 ;;
esac
# NL=64 builds, where the lane frame's 52 lanes fit, so ADD completes unless the budget stops it:
#   LANES_EXE (-GNL=64 -GADD_BUDGET=1000000): the lanes are drawn through the engine (reference
#             with --nl 64; the fixture is decisive - tb_render's run_render.sh proves it)
#   ABORT_EXE (-GNL=64 -GADD_BUDGET=20): every ADD aborted, so the frame must be drawn without
#             lookups (reference --raw 0) - a different picture from the lanes drawn
if [ -n "$LANES_EXE" ]; then
	echo "--- NL=64, no ADD budget: the lanes drawn ---"
	E0=$EXE O0=$OUT R0=$REF
	EXE=$LANES_EXE OUT=$O0/lanes REF="$R0 --nl 64"; mkdir -p "$OUT"
	# ADD takes ~161 k clocks on this synthetic frame - more than NTSC's vblank, as
	# HDPACK_DESIGN.md "8a" says; on PAL timing (70 lines of vblank) it fits
	run lane obj/dict/lane.hdp 0 obj/dict/rec_mmml0 "0:0880" "--lines 312"
	EXE=$E0 OUT=$O0 REF=$R0
fi
if [ -n "$ABORT_EXE" ]; then
	echo "--- NL=64, ADD_BUDGET=20: every ADD aborted ---"
	E0=$EXE O0=$OUT R0=$REF
	EXE=$ABORT_EXE OUT=$O0/abort REF="$R0 --raw 0"; mkdir -p "$OUT"
	run lane obj/dict/lane.hdp 0 obj/dict/rec_mmml0 "0:0880"
	if ! grep -q "aborted_add [1-9]" "$OUT/lane.log"; then echo "  the abort never happened"; fail=1; fi
	EXE=$E0 OUT=$O0 REF=$R0
fi
[ $fail -eq 0 ] && echo "ALL PASS" || echo "FAILURES"
exit $fail
