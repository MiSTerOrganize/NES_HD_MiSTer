#!/bin/sh
# Build the HD engine Verilator testbench. MSYS2 make cannot build on this box (its TMP
# override breaks gcc), so g++ is driven directly.
#   sh tools/sim/build_tb.sh <out_dir>
set -e
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
OUT=${1:-$ROOT/tools/sim/obj}
export VERILATOR_ROOT=C:/msys64/mingw64/share/verilator
export PATH=/c/msys64/mingw64/bin:$PATH
mkdir -p "$OUT"
verilator_bin.exe --cc --build-jobs 0 -O3 -Wno-fatal -Wno-WIDTH -Wno-GENUNNAMED \
	--top-module hd_tb_top -Mdir "$OUT" \
	"$ROOT/tools/sim/hd_tb_top.sv" "$ROOT/rtl/hdpack/hd_engine.sv" "$ROOT/rtl/hdpack/hd_ddr.sv"
VI=$VERILATOR_ROOT/include
g++ -O2 -std=c++17 -I"$OUT" -I"$VI" -I"$VI/vltstd" -o "$OUT/tb.exe" \
	"$ROOT/tools/sim/tb.cpp" "$OUT"/Vhd_tb_top*.cpp \
	"$VI/verilated.cpp" "$VI/verilated_threads.cpp"
echo "built $OUT/tb.exe"
