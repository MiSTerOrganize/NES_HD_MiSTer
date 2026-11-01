#!/bin/sh
# Regenerate the resolve_golden.py goldens (obj/dict/rg_<name>_<frame>.tsv) for the fixture packs
# whose conditions the fixture generators rewrite. Run after make_pos_frame.py /
# make_edge_frame.py / make_legacy_cond.py; run_resolve.sh then checks the RTL against them.
#   sh tools/sim3/make_fixture_goldens.sh [testdata dir]
# the real Python, never the WindowsApps alias (it leaked ~96 GB of commit)
PY=${PY:-/c/Users/miste/AppData/Local/Python/pythoncore-3.14-64/python.exe}
cd "$(dirname "$0")"
T=${1:-C:/Users/miste/OneDrive/Desktop/MiSTerOrganize/MiSTerFrontier/NES_HDPack_testdata}
fail=0
gold() {   # name pack recdir game_ram frame...
	name=$1 pack=$2 dir=$3 gr=$4; shift 4
	for f in "$@"; do
		n=$(echo "$f" | sed 's/^0*//')
		"$PY" -I resolve_golden.py "$pack" "$dir" "$n" "obj/dict/rg_${name}_$n.tsv" --game-ram "$gr" \
			| tail -1 || fail=1
	done
}
# rewrite-sensitive frame-condition fixtures (make_sens_frame.py, default MOD 3 REM 1): built here
# if missing. Castlevania's and Zelda II's are the only fixtures in which a memoised deferred
# condition changes value between frames (cv) and is negated (z2) - the render memo's checks.
P=${P:-Z:/NES_HDPack_work/out}
for pk in a034 p002 a057; do
	[ -f obj/dict/${pk}_sens.hdp ] || "$PY" -I make_sens_frame.py "$P/$pk.hdp" obj/dict/${pk}_sens.hdp || fail=1
done
gold mmmsens obj/dict/a034_sens.hdp "$T/rec_mmm" 0 0200 0400 0880 1020
gold cvsens obj/dict/p002_sens.hdp "$T/rec_cv" 1 0250 0450 0700 1000 1300
gold z2sens obj/dict/a057_sens.hdp "$T/rec_z2" 0 0300 0420 0700 1000
# Zelda II with a BG lookup that reads a pixel of its own group just rewritten by that group's
# fallback hits (make_rewrite_frame.py): the only fixture where the render's per-pixel restart
# and its rewrite-aware tileNearby decide a pixel
[ -f obj/dict/a057_rw.hdp ] || "$PY" -I make_rewrite_frame.py "$P/a057.hdp" "$T/rec_z2" 300 obj/dict/a057_rw.hdp || fail=1
gold z2rw obj/dict/a057_rw.hdp "$T/rec_z2" 0 0300 0420
# the same with tileNearby(0,0): the condition reads the record being looked up itself, which
# Mesen has already rewritten (real packs have such conditions - Metroid a033/a034)
[ -f obj/dict/a057_rw0.hdp ] || "$PY" -I make_rewrite_frame.py "$P/a057.hdp" "$T/rec_z2" 300 obj/dict/a057_rw0.hdp --dx 0 || fail=1
gold z2rw0 obj/dict/a057_rw0.hdp "$T/rec_z2" 0 0300 0420
# a sensitive spriteNearby(0,0) reading a sprite at the same pixel that Mesen looks up AFTER the
# evaluated one (make_phase_frame.py; edited frame + pack, render-only, run_render.sh z2ph)
[ -f obj/dict/rec_z2ph/rec_1000.bin ] || "$PY" -I make_phase_frame.py "$P/a057.hdp" "$T/rec_z2" 1000 \
	obj/dict/a057_ph.hdp obj/dict/rec_z2ph || fail=1
# Zelda II frames with a second sprite of one tile at another tile row beside the first
# (make_slotrow_rec.py; render-only, run_render.sh z2slot): built here if missing
[ -f obj/dict/rec_z2slot/rec_1000.bin ] || "$PY" -I make_slotrow_rec.py "$P/a057.hdp" "$T/rec_z2" \
	obj/dict/rec_z2slot --game-ram 0 0700 1000 || fail=1
# SMB3 frames with an overlapping second sprite at another tile row (make_slotrow_rec.py --dx 0;
# render-only, run_render.sh smbscr in the NSLOT=4 build)
[ -f obj/dict/rec_smbscr/rec_0300.bin ] || "$PY" -I make_slotrow_rec.py "$P/p053.hdp" "$T/rec_smb3" \
	obj/dict/rec_smbscr --game-ram 0 --dx 0 0240 0300 || fail=1
# Metroid frames with grayscale / emphasis bands (make_effects_rec.py; render-only, run_render.sh mmmfx)
[ -f obj/dict/rec_mmmfx/rec_0880.bin ] || "$PY" -I make_effects_rec.py "$T/rec_mmm" obj/dict/rec_mmmfx \
	0200 0880 || fail=1
# backgrounds drawn with Add / Subtract, moved inside their maps and scrolled by negative ratios
# (make_bg_frame.py; render-only - the selection does not read record contents - run_render.sh
# mmmbg / cvbg / z2bg)
for pk in a034 p002 a057; do
	[ -f obj/dict/${pk}_bg.hdp ] || "$PY" -I make_bg_frame.py "$P/$pk.hdp" obj/dict/${pk}_bg.hdp || fail=1
done
# the same plus every fifth record narrowed and shortened so its right / bottom edge lands on
# screen (make_bg_frame.py --edges; run_render.sh z2bge / cvbge). a034's selected records are
# never in that class, so it gets no edge pack.
for pk in p002 a057; do
	[ -f obj/dict/${pk}_bge.hdp ] || "$PY" -I make_bg_frame.py --edges "$P/$pk.hdp" obj/dict/${pk}_bge.hdp || fail=1
done
# vertical scroll changed on 16-line bands, so cached vertical ratios go stale mid-frame
# (make_vscroll_rec.py; run_render.sh mmmbgv / z2bgv)
[ -f obj/dict/rec_mmmvs/rec_1020.bin ] || "$PY" -I make_vscroll_rec.py "$T/rec_mmm" obj/dict/rec_mmmvs \
	0200 0400 0880 1020 || fail=1
[ -f obj/dict/rec_z2vs/rec_1000.bin ] || "$PY" -I make_vscroll_rec.py "$T/rec_z2" obj/dict/rec_z2vs \
	0300 0420 0700 1000 || fail=1
gold mmmpos obj/dict/a034_pos.hdp obj/dict/rec_mmmhid 0 0200 0400 0880 1020
gold z2pos obj/dict/a057_pos.hdp "$T/rec_z2" 0 0300 0420 0700 1000
gold cvpos obj/dict/p002_pos.hdp "$T/rec_cv" 1 0250 0450 0700 1000 1300
gold cvedge obj/dict/p002_edge.hdp "$T/rec_cv" 1 0250 0450 0700 1000 1300
gold mmmedge obj/dict/a034_edge.hdp "$T/rec_mmm" 0 0200 0400 0880 1020
gold smbleg obj/dict/p125_pos.hdp "$T/rec_smb3" 0 0240 0270 0300
exit $fail
