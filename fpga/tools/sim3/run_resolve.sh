#!/bin/sh
# hd3_resolve unit test: every fixture frame through tb_resolve.exe, checked against its
# resolve_golden.py golden (obj/dict/rg_<game>_<frame>.tsv; regenerate with resolve_golden.py)
# and its background selection against bg_golden.py (obj/dict/bgg_<game>_<frame>.tsv, made
# on first use).
#   sh tools/sim3/run_resolve.sh [testdata dir] [pack dir] [extra tb args...]
# EXE overrides the testbench binary (the negative control passes its mutants' builds).
# SMALL_EXE, if set, is a build with RS_MAX lowered (VFLAGS=-GRS_MAX=64): it must fill the
# rule store on the Metroid title and still be right on every list it did filter.
# the real Python, never the WindowsApps alias (it leaked ~96 GB of commit)
PY=${PY:-/c/Users/miste/AppData/Local/Python/pythoncore-3.14-64/python.exe}
cd "$(dirname "$0")"
T=${1:-C:/Users/miste/OneDrive/Desktop/MiSTerOrganize/MiSTerFrontier/NES_HDPack_testdata}
P=${2:-Z:/NES_HDPack_work/out}
[ $# -ge 2 ] && shift 2 || shift $#
EXE=${EXE:-./obj/tb_resolve.exe}
OUT=${OUT:-obj/dict}
fail=0
CHK=""
run() {   # name pack game_ram recdir "bank:frame ..." [tb args]
	name=$1 pack=$2 gr=$3 dir=$4 fr=$5; shift 5
	args=""
	case $dir in */*) ;; *) dir=$T/$dir ;; esac        # a fixture folder, or a recording in $T
	for bf in $fr; do args="$args --frame ${bf%%:*}:$dir/rec_${bf#*:}.bin"; done
	case $pack in */*) ;; *) pack=$P/$pack ;; esac      # a fixture path, or a pack in $P
	if ! "$EXE" "$pack" "$OUT/r_$name.tsv" --game-ram "$gr" $args "$@" > "$OUT/r_$name.log" 2>&1; then
		echo "$name: testbench failed: $(tail -1 "$OUT/r_$name.log")"; fail=1; return
	fi
	g=""
	for bf in $fr; do g="$g $OUT/rg_${name%%_*}_$(echo ${bf#*:} | sed 's/^0*//').tsv"; done
	"$PY" -I check_resolve.py "$OUT/r_$name.tsv" $g $CHK | tail -1
	[ "$(tail -1 "$OUT/r_$name.tsv" | cut -c1)" = "#" ] || { echo "$name: no read-back"; fail=1; }
	"$PY" -I check_resolve.py "$OUT/r_$name.tsv" $g $CHK > /dev/null || fail=1
	# background selection (8i): each level's entry and the memo seed, vs bg_golden.py
	# (generated on first use; the negative control copies them in with the rg_ goldens)
	b=""
	for bf in $fr; do
		f=$(echo ${bf#*:} | sed 's/^0*//')
		bg=$OUT/bgg_${name%%_*}_$f.tsv
		[ -f "$bg" ] || "$PY" -I bg_golden.py "$pack" "$dir" "$f" "$bg" --game-ram "$gr" > /dev/null \
			|| { echo "$name: background golden failed"; fail=1; return; }
		b="$b $bg"
	done
	printf '%s backgrounds: ' "$name"
	"$PY" -I check_bg.py "$OUT/r_$name.tsv" $b | tail -1
	"$PY" -I check_bg.py "$OUT/r_$name.tsv" $b > /dev/null || fail=1
}
# Metroid a034: frame types 1-4, the 495-rule title list, memo + list cache
run mmm_a a034.hdp 0 rec_mmm "0:0200 1:0400 0:0880 1:1020" "$@"
# SMB p053: frame types 2-3
run smb_a p053.hdp 0 rec_smb3 "0:0240 1:0270 0:0300" "$@"
# Castlevania p002: CHR-RAM, fingerprint data conditions, the most frame conditions (1,182)
run cv_a p002.hdp 1 rec_cv "0:0250 1:0450 0:0700 1:1000 0:1300" "$@"
# Zelda II a057: fallback tiles in tileAt
run z2_a a057.hdp 0 rec_z2 "0:0300 1:0420 0:0700 1:1000" "$@"
# Metroid with a third of its frame conditions flagged rewrite-sensitive (make_sens_frame.py):
# no corpus pack flags a frame condition, so only this fixture reaches the deferral path
run mmmsens_a obj/dict/a034_sens.hdp 0 rec_mmm "0:0200 1:0400 0:0880 1:1020" "$@"
run cvsens_a obj/dict/p002_sens.hdp 1 rec_cv "0:0250 1:0450 0:0700 1:1000 0:1300" "$@"
run z2sens_a obj/dict/a057_sens.hdp 0 rec_z2 "0:0300 1:0420 0:0700 1:1000" "$@"
# a rule whose frame list was cleared and whose walk condition reads a rewritten pixel
# (make_rewrite_frame.py)
run z2rw_a obj/dict/a057_rw.hdp 0 rec_z2 "0:0300 1:0420" "$@"
run z2rw0_a obj/dict/a057_rw0.hdp 0 rec_z2 "0:0300 1:0420" "$@"
# Castlevania and Metroid with some frame memory checks made two-slot and some given mask 0x0F
# (make_mem_frame.py): no fixture pack has a frame-class two-slot memoryCheck, and its masked
# conditions never change a result on the recorded frames
run cvmem_a obj/dict/p002_mem.hdp 1 rec_cv "0:0250 1:0450 0:0700 1:1000 0:1300" "$@"
run mmmmem_a obj/dict/a034_mem.hdp 0 rec_mmm "0:0200 1:0400 0:0880 1:1020" "$@"
# the same two packs with frameRange and ordered memoryCheckConstant conditions set exactly on
# their boundary (make_edge_frame.py): tells >= from > and <= from <. Each one is placed only
# where its frame evaluates it and inverting it changes the golden (fixture_pick.py)
run cvedge_a obj/dict/p002_edge.hdp 1 rec_cv "0:0250 1:0450 0:0700 1:1000 0:1300" "$@"
run mmmedge_a obj/dict/a034_edge.hdp 0 rec_mmm "0:0200 1:0400 0:0880 1:1020" "$@"
# Metroid, Zelda II and Castlevania with frame conditions turned into positional traps
# (make_pos_frame.py): a wrong palette, a tile on the last line of its row, a fallback tile, a
# sprite's tile one pixel right of the sprite, a sprite where sprites are hidden, a sprite whose
# BG-group palette differs - none of which a recorded condition hits. Each trap is placed only
# where its frame evaluates it and inverting it changes the golden (fixture_pick.py).
# (the Metroid frames come from make_hidden_rec.py: 0880/1020 with sprites hidden on the left half,
# since no recording has a sprite on a dot where sprites are not shown; Castlevania, the only
# CHR-RAM pack, gets fingerprint traps). Metroid gets NO fallback (tile_fb) trap and that is
# correct, not a gap: hdref makes 0 fallback rewrites on all four frames (every displayed tile
# has its exact key), so a fallback trap cannot change its golden there. Zelda II's two tile_fb
# traps carry that path - the "fallback never tried" / "halves swapped" mutants are caught there.
run mmmpos_a obj/dict/a034_pos.hdp 0 obj/dict/rec_mmmhid "0:0200 1:0400 0:0880 1:1020" "$@"
run z2pos_a obj/dict/a057_pos.hdp 0 rec_z2 "0:0300 1:0420 0:0700 1:1000" "$@"
run cvpos_a obj/dict/p002_pos.hdp 1 rec_cv "0:0250 1:0450 0:0700 1:1000 0:1300" "$@"
# a LEGACY pack with conditions: no corpus legacy pack has any (all 7 have 0), so the legacy
# palette path (top byte 0) is only reached here - Super Mario Bros. p125 with positional
# conditions on its tile rules (make_legacy_cond.py, converted with hdp3_convert.py --base),
# then trapped by make_pos_frame.py, on the SMB3 frames its keys hit
run smbleg_a obj/dict/p125_pos.hdp 0 rec_smb3 "0:0240 1:0270 0:0300" "$@"
# background index signatures with real term masks that clear set snapshot bits
# (make_sigmask.py): the corpus only writes 0xFF masks, so nothing else tests the mask
run z2mask_a obj/dict/a057_mask.hdp 0 rec_z2 "0:0300 1:0420 0:0700 1:1000" "$@"
# a rewrite-sensitive frame condition a background tests first (make_seed_frame.py): the only
# fixture with a nonzero memo seed
run z2seed_a obj/dict/a057_seed.hdp 0 rec_z2 "0:0300" "$@"
# an index candidate of frame 200 that is not one on frame 400, inside frame 400's scanned
# bitmap words, with an empty condition list (make_bgstale.py): a bitmap not cleared between
# frames selects it on 400. No recorded frame pair has such an entry.
run mmmstale_a obj/dict/a034_stale.hdp 0 rec_mmm "0:0200 1:0400 0:0880 1:1020" "$@"
if [ -n "$SMALL_EXE" ]; then
	EXE=$SMALL_EXE CHK=--expect-unfiltered
	run mmm_small a034.hdp 0 rec_mmm "0:0200 1:0400" "$@"
fi
exit $fail
