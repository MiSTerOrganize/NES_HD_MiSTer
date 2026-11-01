#!/bin/sh
# Builds and runs tb_loadpct (hd_loadpct.sv on NES timing). Run from the NES_HDPack folder:
#   sh tools/sim/build_loadpct.sh <out dir>
# MSYS2 make cannot build on this box (its TMP override breaks gcc), so verilator_bin.exe and
# g++ are driven directly, as tools/sim/build_tb.sh does.
set -e
export VERILATOR_ROOT=C:/msys64/mingw64/share/verilator
export PATH=/c/msys64/mingw64/bin:$PATH
ROOT=$(pwd -W)
OUT=${1:-tools/sim/obj_loadpct/out}
OBJ=tools/sim/obj_loadpct
rm -rf "$OBJ/vl"; mkdir -p "$OBJ/vl" "$OUT"
verilator_bin.exe --cc -O2 -Wall -Wno-fatal --top-module hd_loadpct -Mdir "$OBJ/vl" \
	"$ROOT/rtl/hdpack/hd_loadpct.sv"
VI=$VERILATOR_ROOT/include
cd "$OBJ/vl"
g++ -O2 -std=c++17 -I. -I$VI -I$VI/vltstd -o ../tb_loadpct.exe \
	"$ROOT/tools/sim/tb_loadpct.cpp" Vhd_loadpct*.cpp "$VI/verilated.cpp" "$VI/verilated_threads.cpp"
cd - >/dev/null
"$OBJ/tb_loadpct.exe" "$OUT"
