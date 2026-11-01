#!/bin/sh
# Render fixtures for 8a (*_addd.hdp): make_add_frame.py --draw (added keys that have an HD
# payload, so the added sprites are drawn) on the pre-8a packs, then hdp3_addtab.py adds the
# addition tables (sections 16/17) for the rewritten records. run_render.sh requires these to
# be DECISIVE: the reference without additions must differ. Also the hidden-sprite, line-0 and
# synthetic lane fixtures below (each says what only it decides).
#   sh tools/sim3/make_add_draw.sh [testdata dir] [pre-8a pack dir]
# the real Python, never the WindowsApps alias (it leaked ~96 GB of commit)
PY=${PY:-/c/Users/miste/AppData/Local/Python/pythoncore-3.14-64/python.exe}
set -e
cd "$(dirname "$0")"
T=${1:-C:/Users/miste/OneDrive/Desktop/MiSTerOrganize/MiSTerFrontier/NES_HDPack_testdata}
P=${2:-Z:/NES_HDPack_work/out/pre8a}
mkdir -p obj/dict
"$PY" -I make_add_frame.py "$P/a057.hdp" "$T/rec_z2" 0 700 obj/dict/a057_adddraw.tmp --draw
"$PY" -I ../hdp3_addtab.py obj/dict/a057_adddraw.tmp obj/dict/a057_addd.hdp
"$PY" -I make_add_frame.py "$P/p002.hdp" "$T/rec_cv" 1 250 obj/dict/p002_adddraw.tmp --draw
"$PY" -I ../hdp3_addtab.py obj/dict/p002_adddraw.tmp obj/dict/p002_addd.hdp
rm -f obj/dict/a057_adddraw.tmp obj/dict/p002_adddraw.tmp
# the same frames with sprites hidden on the left half of every line (make_hidden_rec.py): no
# recording hides sprites where an added sprite lands, so without these nothing decides whether
# a lane is appended at a pixel whose sprites are not shown (it is - the reference does too)
"$PY" -I make_hidden_rec.py "$T/rec_z2" obj/dict/rec_z2dhid 0700 0300 --hide 0700 0300
"$PY" -I make_hidden_rec.py "$T/rec_cv" obj/dict/rec_cvdhid 0250 0700 --hide 0250 0700
# line 0 under additions (Mesen draws it with line 239's line fields, and pixel (0,0) is line
# 239's pixel 0): Castlevania's line 0 equals line 239 and its backgrounds cover pixel (0,0), so
# the pack loses its backgrounds (make_nobg_pack.py) and line 0's own grayscale bit / pixel 0
# are made to differ (make_line0_rec.py)
"$PY" -I make_nobg_pack.py obj/dict/p002_addd.hdp obj/dict/p002_adddnb.hdp
"$PY" -I make_line0_rec.py "$T/rec_cv" obj/dict/rec_cvl0 0250 0700 --gray 0250 --pixel 0700
# the synthetic lane pack (make_lane_pack.py documents each rule) on Metroid 880, with sprites
# hidden on the left half of every line and line 0's grayscale bit set; lane_nz leaves out the
# addition whose sprite covers pixel (0,0), so that pixel's BG tile shows
"$PY" -I make_hidden_rec.py "$T/rec_mmm" obj/dict/rec_mmmlh 0880 --hide 0880
"$PY" -I make_line0_rec.py obj/dict/rec_mmmlh obj/dict/rec_mmml0 0880 --gray 0880
rm -rf obj/dict/rec_mmmlh
# (built from the fixture's own record, so every choice sees the hidden half)
"$PY" -I make_lane_pack.py obj/dict/rec_mmml0/rec_0880.bin obj/dict/lanepack
"$PY" -I ../hdp3_convert.py obj/dict/lanepack obj/dict/lane.hdp
"$PY" -I make_lane_pack.py obj/dict/rec_mmml0/rec_0880.bin obj/dict/lanepack_nz --no-z240
"$PY" -I ../hdp3_convert.py obj/dict/lanepack_nz obj/dict/lane_nz.hdp
