#!/bin/sh
# Rebuild the hd3_render testbench (normal, NSLOT=4, RS_MAX=64, OF_LOG2=1, RAW=6, NL=64, NL=64 with RS_MAX=1)
# and run the full render suite,
# then the PROFILE=1 build on the two slowest recorded frames to report the cycle profile.
#   sh tools/sim3/test_render_all.sh            -> exit 1 on any build or test failure
# the real Python, never the WindowsApps alias (it leaked ~96 GB of commit)
PY=${PY:-/c/Users/miste/AppData/Local/Python/pythoncore-3.14-64/python.exe}
cd "$(dirname "$0")"
W=$(pwd -W)
R=../../rtl/hdpack
L="hd3_render_tb.sv $R/hd3_dict.sv $R/hd3_lookup.sv $R/hd3_add.sv $R/hd3_resolve.sv $R/hd3_fmap.sv $R/hd3_render.sv $R/hd3_rcache.sv $R/hd3_ccache.sv"
T=${T:-C:/Users/miste/OneDrive/Desktop/MiSTerOrganize/MiSTerFrontier/NES_HDPack_testdata}
P=${P:-Z:/NES_HDPack_work/out}
# the two caches on their own first: a random requester (combinational and registered) against
# a DDR3 model whose contents change at every flush
OBJ=obj/cache_unit sh build_one.sh hd3_cache_tb tb_cache.cpp hd3_cache_tb.sv $R/hd3_rcache.sv $R/hd3_ccache.sv \
	> obj/build_cache.log 2>&1 || { cat obj/build_cache.log; exit 1; }
cst=0
for a in "--gap 0 --seed 1" "--gap 0 --seed 2 --busy 30 --lat 4" "--gap 1 --seed 3 --busy 20 --lat 20"; do
	out=$(obj/cache_unit/tb_cache.exe $a 2>&1) || cst=1      # the exit status, not a pipe's
	echo "$out" | sed "s/^/cache ($a): /"
done
[ $cst -eq 0 ] || { echo "cache unit test FAILED"; exit 1; }
# hd3_fmap on its own: the capture writer's record stream snooped, every map dump checked against
# a byte model of the record buffers (run_fmap.sh, gen_fmap_stream.py)
sh build_one.sh hd3_fmap tb_fmap.cpp $R/hd3_fmap.sv > obj/build_fmap.log 2>&1 || { cat obj/build_fmap.log; exit 1; }
sh run_fmap.sh "$T" > obj/fmap.txt 2>&1 || { cat obj/fmap.txt; echo "fmap unit test FAILED"; exit 1; }
tail -1 obj/fmap.txt | sed "s/^/fmap: /"
sh build_one.sh hd3_render_tb tb_render.cpp $L > obj/build_render.log 2>&1 || { cat obj/build_render.log; exit 1; }
OBJ=obj/slot VFLAGS=-GNSLOT=4 sh build_one.sh hd3_render_tb tb_render.cpp $L > obj/build_slot.log 2>&1 || { cat obj/build_slot.log; exit 1; }
OBJ=obj/rsmax VFLAGS=-GRS_MAX=64 sh build_one.sh hd3_render_tb tb_render.cpp $L > obj/build_rsmax.log 2>&1 || { cat obj/build_rsmax.log; exit 1; }
OBJ=obj/fifo VFLAGS=-GOF_LOG2=1 sh build_one.sh hd3_render_tb tb_render.cpp $L > obj/build_fifo.log 2>&1 || { cat obj/build_fifo.log; exit 1; }
OBJ=obj/raw6 VFLAGS=-GRAW=6 sh build_one.sh hd3_render_tb tb_render.cpp $L > obj/build_raw6.log 2>&1 || { cat obj/build_raw6.log; exit 1; }
OBJ=obj/prof VFLAGS=-GPROFILE=2 sh build_one.sh hd3_render_tb tb_render.cpp $L > obj/build_prof.log 2>&1 || { cat obj/build_prof.log; exit 1; }
OBJ=obj/nl64 VFLAGS=-GNL=64 sh build_one.sh hd3_render_tb tb_render.cpp $L > obj/build_nl64.log 2>&1 || { cat obj/build_nl64.log; exit 1; }
OBJ=obj/rs1 VFLAGS="-GNL=64 -GRS_MAX=1" sh build_one.sh hd3_render_tb tb_render.cpp $L > obj/build_rs1.log 2>&1 || { cat obj/build_rs1.log; exit 1; }
# 8a render fixtures (make_add_draw.sh writes them once)
ok=1
for f in a057_addd.hdp p002_addd.hdp p002_adddnb.hdp lane.hdp lane_nz.hdp rec_z2dhid/rec_0700.bin \
         rec_cvdhid/rec_0700.bin rec_cvl0/rec_0700.bin rec_mmml0/rec_0880.bin; do
	[ -f "obj/dict/$f" ] || ok=0
done
[ $ok -eq 1 ] || sh make_add_draw.sh "$T" "$P/pre8a" > obj/add_draw.txt 2>&1 || { cat obj/add_draw.txt; exit 1; }
SLOT_EXE=$W/obj/slot/tb_render.exe SMALL_EXE=$W/obj/rsmax/tb_render.exe FIFO_EXE=$W/obj/fifo/tb_render.exe \
	RAW_EXE=$W/obj/raw6/tb_render.exe NL_EXE=$W/obj/nl64/tb_render.exe RS1_EXE=$W/obj/rs1/tb_render.exe \
	sh run_render.sh "$T" "$P" > obj/render/all.txt 2>&1
st=$?
grep -E "PASS|FAIL|failed|path |---" obj/render/all.txt | uniq -c
# 8k: CHR-RAM index-form tile conditions (no corpus pack has one) - Castlevania's pack with its
# data-form conditions converted (make_ixram_cond.py), four runs; see HDPACK_DESIGN.md "8k"
TC=$T/rec_cv
for f in "ix:" "ixh:--shift 3 --palmix" "ixf:--palflip"; do
	[ -f "obj/dict/p002_${f%%:*}.hdp" ] || "$PY" -I make_ixram_cond.py "$P/p002.hdp" "obj/dict/p002_${f%%:*}.hdp" \
		"$TC" ${f#*:} 0250 0450 0700 1000 1300 > /dev/null || { echo "make_ixram_cond failed"; st=1; }
done
for r in "ix:" "ixh:" "ixf:" "ix:0:0250 0:0450 0:0700"; do
	p=${r%%:*} fr=${r#*:}
	out=$(FRAMES=${fr:-"0:0250 1:0450 0:0700 1:1000 0:1300"} REQUIRE_IXR=1 \
		sh run_ix.sh "$W/obj/tb_render.exe" "$W/obj/render/ix_$p" "$W/obj/dict/p002_$p.hdp" 2>&1)
	echo "$out" | grep -qx PASS && echo "8k p002_$p ${fr:+(same bank)}: PASS" || { echo "$out" | tail -4; echo "8k p002_$p: FAIL"; st=1; }
done
mkdir -p obj/render_prof
RTL=$(cd $R && pwd -W)
( cd "$RTL" && "$W/obj/prof/tb_render.exe" "$P/p053.hdp" "$W/obj/render_prof/smb" --game-ram 0 \
	--frame 0:$T/rec_smb3/rec_0300.bin > "$W/obj/render_prof/smb300.txt" )
( cd "$RTL" && "$W/obj/prof/tb_render.exe" "$P/p002.hdp" "$W/obj/render_prof/cv" --game-ram 1 \
	--frame 0:$T/rec_cv/rec_0250.bin > "$W/obj/render_prof/cv250.txt" )
for f in smb300 cv250; do
	grep "render line" "obj/render_prof/$f.txt" | awk -v f=$f '{t=$4; s+=t; n++; if(t>m)m=t; b+=t-5456; if(b<0)b=0; if(b>mb)mb=b; for(i=7;i<=21;i+=2)c[$i]+=$(i+1)}
		END{printf "%s: mean %d max %d backlog %.1f lines |", f, s/n, m, mb/5456; for(k in c) printf " %s %d", k, c[k]/n; print ""}'
done
exit $st
