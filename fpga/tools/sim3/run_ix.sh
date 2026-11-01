#!/bin/sh
# 8k: an index-form Castlevania pack (make_ixram_cond.py) through EXE, compared with hdref.
#   sh run_ix.sh <exe> <out dir> [pack]
# FRAMES overrides the bank:frame list. The default alternates banks like the real engine;
# "0:0250 0:0450 0:0700" puts three different frames in the SAME bank back to back, so an
# index read that went through the condition cache (flushed only on pack load) would see
# the previous frame's record at the same address.
# the real Python, never the WindowsApps alias (it leaked ~96 GB of commit)
PY=${PY:-/c/Users/miste/AppData/Local/Python/pythoncore-3.14-64/python.exe}
SIM=$(cd "$(dirname "$0")" && pwd -W)
T=C:/Users/miste/OneDrive/Desktop/MiSTerOrganize/MiSTerFrontier/NES_HDPack_testdata/rec_cv
EXE=$1 OUT=$2 PACK=${3:-$SIM/obj/dict/p002_ix.hdp}
FRAMES=${FRAMES:-"0:0250 1:0450 0:0700 1:1000 0:1300"}
RTL=$(cd $SIM/../../rtl/hdpack && pwd -W)
mkdir -p "$OUT"
args="" nums=""
for bf in $FRAMES; do
	args="$args --frame ${bf%%:*}:$T/rec_${bf#*:}.bin"
	nums="$nums $(echo ${bf#*:} | sed 's/^0*//')"
done
if ! (cd "$RTL" && "$EXE" "$PACK" "$OUT/cv" --game-ram 1 $args) > "$OUT/cv.log" 2>&1; then
	echo "testbench failed: $(tail -1 "$OUT/cv.log")"; exit 1
fi
grep -E "frame|paths:" "$OUT/cv.log"
# REQUIRE_IXR=1: every frame must have made uncached (byp) index reads. STRUCTURAL check, not
# an outcome check: the condition cache is direct-mapped and a frame's rule traffic evicts the
# frame-record lines before the next frame, so a cached (stale-prone) index read does not
# reach a pixel in these fixtures. The bypass itself is proven by neg_cache.py.
if [ "${REQUIRE_IXR:-0}" = 1 ] && grep -q "ixr 0\b" "$OUT/cv.log"; then
	echo "FAIL: a frame made no uncached index read (index read went through the cache?)"; exit 1
fi
# backgrounds are drawn by the RTL since 8j; additions are not yet (8a), so the reference
# leaves only them out
cd $SIM && "$PY" -I check_render.py "$PACK" "$T" "$OUT/cv" $nums --game-ram 1 --no-add
