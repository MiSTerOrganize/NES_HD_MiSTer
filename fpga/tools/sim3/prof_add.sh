#!/bin/sh
# hd3_add cycle cost per frame (8a): clocks from start to done, per fixture and DDR3 setting.
# The budget is vblank (~114,000 clocks) shared with hd3_resolve, which needs ADD's lanes.
#   sh tools/sim3/prof_add.sh [testdata dir]
cd "$(dirname "$0")"
T=${1:-C:/Users/miste/OneDrive/Desktop/MiSTerOrganize/MiSTerFrontier/NES_HDPack_testdata}
EXE=${EXE:-./obj/add64/tb_add.exe}
OUT=obj/add_out
mkdir -p "$OUT"
z2="0:0300 1:0420 0:0700 1:1000"
cv="0:0250 1:0450 0:0700 1:1000 0:1300"
one() {   # label pack game_ram recdir frames tb args
	label=$1 pack=$2 gr=$3 dir=$T/$4 fr=$5; shift 5
	args=""
	for bf in $fr; do args="$args --frame ${bf%%:*}:$dir/rec_${bf#*:}.bin"; done
	"$EXE" "$pack" "$OUT/prof.tsv" --game-ram "$gr" $args "$@" > /dev/null 2>&1 \
		|| { echo "$label: testbench failed"; return; }
	printf '%-26s %s\n' "$label" "$(grep '^#frame' "$OUT/prof.tsv" | awk '{printf "%8s", $NF}')"
}
for d in "--busy 0 --lat 12" "--busy 40 --lat 60" "--busy 40 --lat 60 --pipelined"; do
	echo "== $d (clocks per frame)"
	one "z2 real (a057_tab)" obj/dict/a057_tab.hdp 0 rec_z2 "$z2" --gap 25 $d --seed 3
	one "cv real (p002_tab)" obj/dict/p002_tab.hdp 1 rec_cv "$cv" --gap 25 $d --seed 3
	one "z2 synthetic (a057_addt)" obj/dict/a057_addt.hdp 0 rec_z2 "$z2" --gap 25 $d --seed 3
	one "cv synthetic (p002_addt)" obj/dict/p002_addt.hdp 1 rec_cv "$cv" --gap 25 $d --seed 3
done
