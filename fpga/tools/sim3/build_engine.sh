#!/bin/sh
# build tb_engine.exe from rtl/hdpack (RTLDIR overrides, for the negative controls' mutant copies):
#   sh build_engine.sh [outdir] [extra verilator flags]        (default outdir obj/engine)
set -e
HERE=$(cd "$(dirname "$0")" && pwd -W)
OUT=${1:-$HERE/obj/engine}
if [ $# -gt 0 ]; then shift; fi
mkdir -p "$OUT"
OUT=$(cd "$OUT" && pwd -W)
export VERILATOR_ROOT=C:/msys64/mingw64/share/verilator
export PATH=/c/msys64/mingw64/bin:$PATH
VI=$VERILATOR_ROOT/include
R=${RTLDIR:-$HERE/../../rtl/hdpack}
rm -rf "$OUT/hd3_engine"
mkdir -p "$OUT/hd3_engine"
# the ROM patcher's ARM timeout: 2^25 core clocks on the device (~1.5 s), which the
# arm_silent case cannot wait out in simulation; 2^20 here (SIM_TMO overrides)
SIM_TMO=${SIM_TMO:-"26'h100000"}
verilator_bin.exe --cc -O3 "+define+HD3_SIM_TMO=$SIM_TMO" "$@" -Wall -Wno-fatal -Wno-DECLFILENAME -Wno-UNUSEDSIGNAL -Wno-BLKSEQ \
	--public-flat-rw --top-module hd3_engine -Mdir "$OUT/hd3_engine" \
	$R/hd3_engine.sv $R/hd3_cross.sv $R/hd3_scanout.sv $R/hd3_loader_stream.sv $R/hd3_ddr.sv \
	$R/hd3_dict.sv $R/hd3_add.sv $R/hd3_resolve.sv $R/hd3_fmap.sv $R/hd3_render.sv \
	$R/hd3_ccache.sv $R/hd3_rcache.sv $R/hd3_lookup.sv $R/hd3_romfix.sv $R/hd3_audio.sv 2> "$OUT/hd3_engine.lint"
if grep -q "%Error" "$OUT/hd3_engine.lint"; then cat "$OUT/hd3_engine.lint"; exit 1; fi
# the ARM half of the ROM patcher, linked in as the device runs it (ROMFIX_C: a mutant copy)
RF=${ROMFIX_C:-$HERE/../armdec/romfix_arm.c}
( cd "$OUT/hd3_engine" && gcc -O2 -std=gnu11 -Wall -I"$HERE/../armdec" -c "$RF" -o romfix_arm.o && \
  g++ -O2 -std=c++17 -I. -I"$VI" -I"$VI/vltstd" -o "$OUT/tb_engine.exe" \
	"$HERE/tb_engine.cpp" Vhd3_engine*.cpp "$VI/verilated.cpp" "$VI/verilated_threads.cpp" romfix_arm.o )
echo "built $OUT/tb_engine.exe ($(grep -c '%Warning' "$OUT/hd3_engine.lint") warnings)"
