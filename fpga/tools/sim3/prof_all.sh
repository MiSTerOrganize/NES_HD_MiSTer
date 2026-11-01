#!/bin/sh
# Per-line cycle profile of every base fixture frame (PROFILE=2 build, obj/prof): for each
# frame the mean / worst line and the worst backlog against the 5,456-clock NES line, assuming
# lines are consumed one per line period. Run after test_render_all.sh (it builds obj/prof).
#   sh tools/sim3/prof_all.sh
cd "$(dirname "$0")"
W=$(pwd -W)
RTL=$(cd ../../rtl/hdpack && pwd -W)
T=${T:-C:/Users/miste/OneDrive/Desktop/MiSTerOrganize/MiSTerFrontier/NES_HDPack_testdata}
P=${P:-Z:/NES_HDPack_work/out}
mkdir -p obj/render_prof
one() {   # tag pack game_ram recdir frame
	out="$W/obj/render_prof/all_$1.txt"
	# a second frame makes the first one's per-frame line print; only the first is measured
	( cd "$RTL" && "$W/obj/prof/tb_render.exe" "$P/$2" "$W/obj/render_prof/all_$1" --game-ram "$3" \
		--frame 0:$T/$4/rec_$5.bin --frame 1:$T/$4/rec_$5.bin > "$out" )
	awk -v f=$1 '/render line/ { if (seen[$3]++) next; t=$4; s+=t; n++; if(t>m){m=t; ml=$3}
		b+=t-5456; if(b<0)b=0; if(b>mb)mb=b }
		END { printf "%-10s lines %3d mean %5d worst %6d (line %s) backlog %.1f\n", f, n, s/n, m, ml, mb/5456 }' "$out"
}
for f in 0240 0270 0300; do one smb$f p053.hdp 0 rec_smb3 $f; done
for f in 0200 0400 0880 1020; do one mmm$f a034.hdp 0 rec_mmm $f; done
for f in 0250 0450 0700 1000 1300; do one cv$f p002.hdp 1 rec_cv $f; done
for f in 0300 0420 0700 1000; do one z2$f a057.hdp 0 rec_z2 $f; done
