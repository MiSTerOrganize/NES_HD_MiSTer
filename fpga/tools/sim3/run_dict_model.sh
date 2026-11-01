#!/bin/sh
# Model-level negative control for the stage-3 dictionary (hwmodel --dict): every mutant of the
# RESOLVE filter / prefix use must make the model differ from the Mesen-order reference.
#   1. Castlevania p002 on its recorded frames (catches the two filter mutants)
#   2. obj/dict/a057_prefix.hdp on Zelda II frame 700 - the fixture make_prefix_frame.py builds
#      for the third mutant ("the cache flag ignores filtered-out rules"), which no recorded frame
#      can expose: it needs a fallback rewrite read by a rewrite-sensitive tile condition.
# The fixture is regenerated each run from the current a057 build.
#   sh tools/sim3/run_dict_model.sh [testdata dir] [pack dir]
# the real Python, never the WindowsApps alias (it leaked ~96 GB of commit)
PY=${PY:-/c/Users/miste/AppData/Local/Python/pythoncore-3.14-64/python.exe}
cd "$(dirname "$0")"
T=${1:-C:/Users/miste/OneDrive/Desktop/MiSTerOrganize/MiSTerFrontier/NES_HDPack_testdata}
P=${2:-Z:/NES_HDPack_work/out}
ROMS="Z:/MiSTer_Organize/RomRoot/MiSTer_Console/MiSTer_Console/games/NES/1 NES/1 USA"
fail=0
rm -f obj/dict/a057_prefix.hdp      # a stale fixture must not pass for a fresh one
"$PY" -I make_prefix_frame.py "$P/a057.hdp" obj/dict/a057_prefix.hdp "$T/rec_z2" 0700 --max 40 \
	| tail -1 || fail=1
[ -f obj/dict/a057_prefix.hdp ] || { echo "FAIL: no prefix fixture built"; exit 1; }
echo "== a057_prefix frame 700"
"$PY" -I neg_dict_model.py obj/dict/a057_prefix.hdp "$T/rec_z2" 700 \
	"$ROMS/Zelda II - The Adventure of Link (USA).nes" || fail=1
for f in 250 700 1000; do
	echo "== p002 frame $f (filter mutants)"
	"$PY" -I neg_dict_model.py "$P/p002.hdp" "$T/rec_cv" "$f" "$T/roms/cv.nes" | head -3 \
		| tail -2
done
exit $fail
