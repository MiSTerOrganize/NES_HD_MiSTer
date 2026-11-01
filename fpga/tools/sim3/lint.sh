#!/bin/sh
# lint the stage-3 engine top in rtl/hdpack: sh lint.sh [top] ; writes obj/lint_<top>.txt
cd "$(dirname "$0")"
mkdir -p obj
O=$(pwd -W)/obj
cd ../../rtl/hdpack
export VERILATOR_ROOT=C:/msys64/mingw64/share/verilator
export PATH=/c/msys64/mingw64/bin:$PATH
top=${1:-hd3_engine}
verilator_bin.exe --lint-only -Wall -Wno-fatal -Wno-DECLFILENAME -Wno-UNUSEDSIGNAL -Wno-BLKSEQ \
	--top-module "$top" hd3_engine.sv hd3_cross.sv hd3_scanout.sv hd3_loader_stream.sv hd3_ddr.sv \
	hd3_dict.sv hd3_add.sv hd3_resolve.sv hd3_fmap.sv hd3_render.sv hd3_ccache.sv \
	hd3_rcache.sv hd3_lookup.sv hd3_romfix.sv hd3_audio.sv >$O/lint_$top.txt 2>&1
echo "errors $(grep -c '^%Error' $O/lint_$top.txt) warnings $(grep -c '^%Warning' $O/lint_$top.txt)"
grep -E '^%Error' $O/lint_$top.txt | head -40
grep -E '^%Warning-(PINMISSING|PINNOTFOUND|WIDTH|IMPLICIT|UNDRIVEN|MULTIDRIVEN|PINCONNECTEMPTY)' $O/lint_$top.txt | head -60
