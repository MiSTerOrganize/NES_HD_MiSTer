#!/bin/sh
# hd3_render unit test: fixture frames through tb_render.exe (dict -> resolve -> fmap -> render),
# each frame compared pixel for pixel with hdref.HdRef.render (check_render.py).
#   sh tools/sim3/run_render.sh [testdata dir] [pack dir] [extra tb args...]
# EXE overrides the testbench binary (a negative control passes its mutants' builds).
# BASE_ONLY=1 runs only the four recorded-pack sets.
# SLOT_EXE / SMALL_EXE, if set, rerun the four base sets on builds with lowered limits and
# require the rare path to have been TAKEN (a pass with the path untaken proves nothing):
#   SLOT_EXE   built with VFLAGS=-GNSLOT=4     -> uncached tiles through the scratch slot
#   SMALL_EXE  built with VFLAGS=-GRS_MAX=64   -> unfiltered (kind 2) rule lists walked from DDR3
#   FIFO_EXE   built with VFLAGS=-GOF_LOG2=1   -> compose held by a full (2-entry) output FIFO
#   RAW_EXE    built with VFLAGS=-GRAW=6       -> 64 record ids: every Castlevania frame overflows
#              the dictionary and is drawn with no HD lookups (HDPACK_DESIGN.md "8o"); the
#              other three games stay under 64 keys, so the same run checks both sides
# Use a plain integer with -G: a sized literal (-GNSLOT=8'd4) is silently ignored.
#   NL_EXE     built with VFLAGS=-GNL=64      -> the addition fixtures again with 64 lanes per line,
#              so the heavy fixtures draw their lanes instead of overflowing (REF gains --nl 64)
#   RS1_EXE    built with VFLAGS="-GNL=64 -GRS_MAX=1" -> the lane fixtures with every rule list
#              unfiltered, so render's own condition walk decides the lane conditions
# REF adds check_render.py flags (default: none, so additions are in the reference - 8a; the
# reference decides lane overflow itself with the hd3_add model, --nl tells it the build's NL).
# Backgrounds are drawn (8j) and checked. ADD_ONLY=1 runs only the addition fixtures.
# the real Python, never the WindowsApps alias (it leaked ~96 GB of commit)
PY=${PY:-/c/Users/miste/AppData/Local/Python/pythoncore-3.14-64/python.exe}
cd "$(dirname "$0")"
T=${1:-C:/Users/miste/OneDrive/Desktop/MiSTerOrganize/MiSTerFrontier/NES_HDPack_testdata}
P=${2:-Z:/NES_HDPack_work/out}
[ $# -ge 2 ] && shift 2 || shift $#
EXE=${EXE:-$(pwd -W)/obj/tb_render.exe}
OUT=${OUT:-$(pwd -W)/obj/render}
REF=${REF-}
RTL=$(cd ../../rtl/hdpack && pwd -W)          # the ROM .hex files are read from the cwd
mkdir -p "$OUT"
fail=0
run() {   # name pack game_ram recdir "bank:frame ..." [tb args]
	name=$1 pack=$2 gr=$3 dir=$4 fr=$5; shift 5
	args=""
	nums=""
	case $dir in ?:/*) ;; */*) dir=$(pwd -W)/$dir ;; *) dir=$T/$dir ;; esac
	for bf in $fr; do
		args="$args --frame ${bf%%:*}:$dir/rec_${bf#*:}.bin"
		nums="$nums $(echo ${bf#*:} | sed 's/^0*//')"
	done
	case $pack in ?:/*) ;; */*) pack=$(pwd -W)/$pack ;; *) pack=$P/$pack ;; esac
	if ! (cd "$RTL" && "$EXE" "$pack" "$OUT/$name" --game-ram "$gr" $args "$@") > "$OUT/$name.log" 2>&1; then
		echo "$name: testbench failed: $(tail -1 "$OUT/$name.log")"; fail=1; return
	fi
	cat "$OUT/$name.log"
	"$PY" -I check_render.py "$pack" "$dir" "$OUT/$name" $nums --game-ram "$gr" $REF > "$OUT/$name.chk" 2>&1
	st=$?
	sed "s/^/  /" "$OUT/$name.chk"
	[ $st -eq 0 ] || fail=1
}
base() {
	# Super Mario Bros. 3 frames, SMB pack p053
	run smb p053.hdp 0 rec_smb3 "0:0240 1:0270 0:0300" "$@"
	# Metroid a034: the 495-rule title list, rewrite-sensitive walk conditions
	run mmm a034.hdp 0 rec_mmm "0:0200 1:0400 0:0880 1:1020" "$@"
	# Castlevania p002: CHR-RAM, fingerprint data conditions, the most frame conditions
	run cv p002.hdp 1 rec_cv "0:0250 1:0450 0:0700 1:1000 0:1300" "$@"
	# Zelda II a057: fallback tiles
	run z2 a057.hdp 0 rec_z2 "0:0300 1:0420 0:0700 1:1000" "$@"
}
taken() {   # counter [line tag] [sets]: the sum over the sets' last "<tag>:" lines must be > 0
	tag=${2:-paths} n=0
	for s in ${3:-smb mmm cv z2}; do
		v=$(grep "$tag:" "$OUT/$s.log" | tail -1 | sed -n "s/.* $1 \([0-9]*\).*/\1/p")
		n=$((n + ${v:-0}))
	done
	if [ "$n" -gt 0 ]; then echo "  path $1 taken $n times"; else echo "  path $1 NEVER TAKEN"; fail=1; fi
}
decisive() {   # name pack game_ram recdir "frames" must: is the no-addition reference different?
	name=$1 pack=$2 gr=$3 dir=$4 fr=$5 must=$6
	case $dir in ?:/*) ;; */*) dir=$(pwd -W)/$dir ;; *) dir=$T/$dir ;; esac
	case $pack in ?:/*) ;; */*) pack=$(pwd -W)/$pack ;; *) pack=$P/$pack ;; esac
	nums=""; for bf in $fr; do nums="$nums $(echo ${bf#*:} | sed 's/^0*//')"; done
	if "$PY" -I check_render.py "$pack" "$dir" "$OUT/$name" $nums --game-ram "$gr" --no-add > "$OUT/$name.noadd" 2>&1; then
		if [ "$must" = 1 ]; then
			echo "  $name: additions NOT decisive (the no-addition reference matches too)"; fail=1
		else
			echo "  $name: additions do not change these frames (correctness check only)"
		fi
	else
		echo "  $name: additions decisive on frames:$(sed -n 's/^frame \([0-9]*\): \([1-9][0-9]*\) of .*/ \1(\2px)/p' "$OUT/$name.noadd" | tr -d '\n')"
	fi
}
# 8a additions: the converted packs' own tables and the synthetic fixtures run_add.sh uses
# (HDPACK_DESIGN.md "8a"), each checked with additions in the reference. The 4th field 1 means
# the frames MUST change without additions, or the fixture proves nothing about the lanes:
#   z2d/cvd   make_add_draw.sh - the added keys have HD payloads, so the lanes are DRAWN (at NL=16
#             cvd and z2d frame 700 overflow instead; the NL_EXE pass draws them)
#   z2mix/cvmix  over NL lanes on a line even at 64: the frame must be drawn without lookups
# The rest only check correctness: their added sprites find no HD payload, or a transparent one.
adds() {
	Z="0:0300 1:0420 0:0700 1:1000" C="0:0250 1:0450 0:0700 1:1000 0:1300"
	for s in "z2d obj/dict/a057_addd.hdp 0 rec_z2 1|0:0700 1:0300" \
	         "cvd obj/dict/p002_addd.hdp 1 rec_cv 1|0:0250 1:0700" \
	         "z2t obj/dict/a057_tab.hdp 0 rec_z2 0|$Z" "cvt obj/dict/p002_tab.hdp 1 rec_cv 0|$C" \
	         "z2s obj/dict/a057_addt.hdp 0 rec_z2 0|$Z" "cvs obj/dict/p002_addt.hdp 1 rec_cv 0|$C" \
	         "z2e obj/dict/a057_edge.hdp 0 rec_z2edge 0|0:0700 1:0700" \
	         "z2mix obj/dict/h_z2_mixed_t.hdp 0 rec_z2 1|$Z" "cvmix obj/dict/h_cv_mixed_t.hdp 1 rec_cv 1|$C" \
	         "z2dh obj/dict/a057_addd.hdp 0 obj/dict/rec_z2dhid 1|0:0700 1:0300" \
	         "cvdh obj/dict/p002_addd.hdp 1 obj/dict/rec_cvdhid 1|0:0250 1:0700" \
	         "cvl0 obj/dict/p002_adddnb.hdp 1 obj/dict/rec_cvl0 1|0:0250 1:0700"; do
		set -- ${s%%|*}
		run "$1" "$2" "$3" "$4" "${s#*|}"
		decisive "$1" "$2" "$3" "$4" "${s#*|}" "$5"
	done
}
# the synthetic lane pack (make_lane_pack.py) on Metroid 880 with sprites hidden on the left half
# and line 0 grayscale: every 8a lane rule decides pixels here (each of its HD images is drawn, or
# - for the rules that must never fire - would be drawn by a render that broke the rule). Run on
# the NL=64 builds only, so the lanes are drawn rather than the line overflowing.
lanes() {
	for s in "lane obj/dict/lane.hdp" "lanenz obj/dict/lane_nz.hdp"; do
		set -- $s
		run "$1" "$2" 0 obj/dict/rec_mmml0 "0:0880"
		decisive "$1" "$2" 0 obj/dict/rec_mmml0 "0:0880" 1
	done
}
rs1() {
	# RS_MAX=1: every rule list is unfiltered, so frame conditions that resolve evaluates in the
	# normal build are evaluated by render's own walk instead (its lanes and its (0,0) rule)
	echo "--- NL=64 RS_MAX=1 build (lane fixtures) ---"
	REF1=$REF EXE1=$EXE OUT1=$OUT
	EXE=$RS1_EXE OUT=$OUT1/rs1 REF="$REF1 --nl 64"; mkdir -p "$OUT"; lanes; taken kind2 paths "lane lanenz"
	REF=$REF1 EXE=$EXE1 OUT=$OUT1
}
# ADD_ONLY (the negative control's "add" mutants, built with NL=64): the addition and lane
# fixtures, and the lane fixtures again on the RS_MAX=1 build if there is one
if [ -n "$ADD_ONLY" ]; then adds; lanes; [ -n "$RS1_EXE" ] && rs1; exit $fail; fi
base "$@"
adds
taken steps bg
EXE0=$EXE OUT0=$OUT
if [ -n "$SLOT_EXE" ]; then
	echo "--- NSLOT=4 build ---"
	# both kinds of uncached row: tiles and sprites (scratch) and background cells (uncached)
	EXE=$SLOT_EXE OUT=$OUT0/slot; mkdir -p "$OUT"; base "$@"; taken scratch; taken uncached bg
	# two sprites of one HD block at different tile rows over the same pixels on a line whose
	# slots ran out (make_slotrow_rec.py --dx 0): consecutive steps share the scratch slot, the
	# only scene where its row check decides a pixel
	run smbscr p053.hdp 0 obj/dict/rec_smbscr "0:0240 1:0300" "$@"
fi
if [ -n "$SMALL_EXE" ]; then
	echo "--- RS_MAX=64 build ---"
	EXE=$SMALL_EXE OUT=$OUT0/small; mkdir -p "$OUT"; base "$@"; taken kind2
fi
if [ -n "$FIFO_EXE" ]; then
	echo "--- OF_LOG2=1 build ---"
	EXE=$FIFO_EXE OUT=$OUT0/fifo; mkdir -p "$OUT"; base "$@"; taken ofstall
fi
if [ -n "$RAW_EXE" ]; then
	echo "--- RAW=6 build ---"
	REF0=$REF
	EXE=$RAW_EXE OUT=$OUT0/raw REF="$REF0 --raw 6"; mkdir -p "$OUT"; base "$@"; taken fovf
	# every Castlevania frame overflows here, so backgrounds drawn on cv prove the background
	# engine runs on an overflowed frame (the reference keeps them: check_render.py)
	taken steps bg cv
	REF=$REF0
fi
if [ -n "$NL_EXE" ]; then
	echo "--- NL=64 build (addition fixtures) ---"
	REF0=$REF
	EXE=$NL_EXE OUT=$OUT0/nl64 REF="$REF0 --nl 64"; mkdir -p "$OUT"; adds; lanes
	REF=$REF0
fi
EXE=$EXE0 OUT=$OUT0
[ -n "$RS1_EXE" ] && rs1
EXE=$EXE0 OUT=$OUT0
[ -n "$BASE_ONLY" ] && exit $fail
# the resolve fixtures (run_resolve.sh documents each): rewrite-sensitive frame conditions,
# two-slot / masked memory checks, boundary frameRange / memoryCheckConstant, positional traps,
# a legacy pack with conditions, and Zelda II's prefix / chain fixtures
run mmmsens obj/dict/a034_sens.hdp 0 rec_mmm "0:0200 1:0400 0:0880 1:1020" "$@"
# deferred frame conditions whose memoised value changes between frames (cv) and that are negated
# (z2): without these no fixture sees a stale or un-negated memo entry
run cvsens obj/dict/p002_sens.hdp 1 rec_cv "0:0250 1:0450 0:0700 1:1000 0:1300" "$@"
run z2sens obj/dict/a057_sens.hdp 0 rec_z2 "0:0300 1:0420 0:0700 1:1000" "$@"
# a rewrite-sensitive tileNearby reading its own group's earlier pixel, which that pixel's
# fallback lookup has rewritten (make_rewrite_frame.py): the per-pixel restart and the
# rewrite-aware nearby path only decide a pixel here
run z2rw obj/dict/a057_rw.hdp 0 rec_z2 "0:0300 1:0420" "$@"
# offset 0: the record being looked up reads itself, already rewritten by Mesen
run z2rw0 obj/dict/a057_rw0.hdp 0 rec_z2 "0:0300 1:0420" "$@"
# a sensitive spriteNearby(0,0) whose target sprite Mesen looks up after the evaluated one
# (make_phase_frame.py): only the sprites' phase within the pixel decides it
run z2ph obj/dict/a057_ph.hdp 0 obj/dict/rec_z2ph "0:1000" "$@"
# a rewrite-sensitive frame condition a background tests first and a lookup tests after the
# tile it reads has been rewritten (make_seed_frame.py): only the memo SEED decides a pixel
run z2seed obj/dict/a057_seed.hdp 0 rec_z2 "0:0300" "$@"
# background index signatures with real term masks that clear set snapshot bits (8i,
# make_sigmask.py): the corpus only writes 0xFF masks
run z2mask obj/dict/a057_mask.hdp 0 rec_z2 "0:0300 1:0420 0:0700 1:1000" "$@"
# an index candidate on frame 200 only, with an empty condition list (make_bgstale.py)
run mmmstale obj/dict/a034_stale.hdp 0 rec_mmm "0:0200 1:0400 0:0880 1:1020" "$@"
# two consecutive sprite instances of one HD block on a line at different tile rows
# (make_slotrow_rec.py): the image-slot cache's row check only decides a pixel here
run z2slot a057.hdp 0 obj/dict/rec_z2slot "0:0700 1:1000" "$@"
# Metroid frames with grayscale and colour emphasis set on bands of lines (make_effects_rec.py):
# no recording turns either on, so only this fixture makes the output stage's effects decisive
run mmmfx a034.hdp 0 obj/dict/rec_mmmfx "0:0200 1:0880" "$@"
run cvmem obj/dict/p002_mem.hdp 1 rec_cv "0:0250 1:0450 0:0700 1:1000 0:1300" "$@"
run mmmmem obj/dict/a034_mem.hdp 0 rec_mmm "0:0200 1:0400 0:0880 1:1020" "$@"
run cvedge obj/dict/p002_edge.hdp 1 rec_cv "0:0250 1:0450 0:0700 1:1000 0:1300" "$@"
run mmmedge obj/dict/a034_edge.hdp 0 rec_mmm "0:0200 1:0400 0:0880 1:1020" "$@"
run mmmpos obj/dict/a034_pos.hdp 0 obj/dict/rec_mmmhid "0:0200 1:0400 0:0880 1:1020" "$@"
run z2pos obj/dict/a057_pos.hdp 0 rec_z2 "0:0300 1:0420 0:0700 1:1000" "$@"
run cvpos obj/dict/p002_pos.hdp 1 rec_cv "0:0250 1:0450 0:0700 1:1000 0:1300" "$@"
run smbleg obj/dict/p125_pos.hdp 0 rec_smb3 "0:0240 1:0270 0:0300" "$@"
run z2pre obj/dict/a057_prefix.hdp 0 rec_z2 "0:0300 1:0420 0:0700 1:1000" "$@"
run z2chain obj/dict/a057_chain.hdp 0 rec_z2 "0:0300 1:0420 0:0700 1:1000" "$@"
# backgrounds the recorded frames never draw (make_bg_frame.py): Add and Subtract blends,
# records moved inside their maps (cell phase, image row, bottom edge) and negative scroll
# ratios (leading pixels / lines not drawn, records running off their right / bottom edge)
run mmmbg obj/dict/a034_bg.hdp 0 rec_mmm "0:0200 1:0400 0:0880 1:1020" "$@"
run cvbg obj/dict/p002_bg.hdp 1 rec_cv "0:0250 1:0450 0:0700 1:1000 0:1300" "$@"
run z2bg obj/dict/a057_bg.hdp 0 rec_z2 "0:0300 1:0420 0:0700 1:1000" "$@"
# records narrowed / shortened so their right and bottom edges fall on screen (make_bg_frame.py
# --edges): the only frames where the right-edge clip and the bottom-line test decide a pixel
run z2bge obj/dict/a057_bge.hdp 0 rec_z2 "0:0300 1:0420 0:0700 1:1000" "$@"
run cvbge obj/dict/p002_bge.hdp 1 rec_cv "0:0250 1:0450 0:0700 1:1000 0:1300" "$@"
# vertical scroll changed every 16 lines (make_vscroll_rec.py): the only frames where a level's
# cached vertical ratio goes stale mid-frame
run mmmbgv obj/dict/a034_bg.hdp 0 obj/dict/rec_mmmvs "0:0200 1:0400 0:0880 1:1020" "$@"
run z2bgv obj/dict/a057_bg.hdp 0 obj/dict/rec_z2vs "0:0300 1:0420 0:0700 1:1000" "$@"
taken add bg "mmmbg cvbg z2bg"
taken sub bg "mmmbg cvbg z2bg"
exit $fail
