#!/bin/sh
# Build ONE stage-2 unit testbench (same flags as build.sh, which builds them all).
#   sh tools/sim3/build_one.sh <top> <tb.cpp> <rtl files...>
#   e.g. sh tools/sim3/build_one.sh hd_watch tools/sim3/tb_watch.cpp rtl/hdpack/hd_watch.sv
# OBJ overrides the output folder (the negative-control runners use their own); VFLAGS adds
# Verilator flags (e.g. -GRS_MAX=64 to override a top-level parameter).
set -e
ROOT=$(cd "$(dirname "$0")/../.." && pwd -W)
OBJ=${OBJ:-$ROOT/tools/sim3/obj}
mkdir -p "$OBJ"
OBJ=$(cd "$OBJ" && pwd -W)      # absolute: the g++ step runs from inside $OBJ/$top
export VERILATOR_ROOT=C:/msys64/mingw64/share/verilator
export PATH=/c/msys64/mingw64/bin:$PATH
VI=$VERILATOR_ROOT/include
top=$1; tb=$(cd "$(dirname "$2")" && pwd -W)/$(basename "$2"); shift 2
rtl=""
for f in "$@"; do rtl="$rtl $(cd "$(dirname "$f")" && pwd -W)/$(basename "$f")"; done
rm -rf "$OBJ/$top"
mkdir -p "$OBJ/$top"
verilator_bin.exe --cc -O3 $VFLAGS -Wall -Wno-fatal -Wno-DECLFILENAME -Wno-UNUSEDSIGNAL -Wno-BLKSEQ \
	--top-module "$top" -Mdir "$OBJ/$top" $rtl 2> "$OBJ/$top.lint"
if grep -q "%Error" "$OBJ/$top.lint"; then cat "$OBJ/$top.lint"; exit 1; fi
( cd "$OBJ/$top" && g++ -O2 -std=c++17 -I. -I"$VI" -I"$VI/vltstd" -o "$OBJ/$(basename "$tb" .cpp).exe" \
	"$tb" V"$top"*.cpp "$VI/verilated.cpp" "$VI/verilated_threads.cpp" )
echo "built $OBJ/$(basename "$tb" .cpp).exe ($(grep -c '%Warning' "$OBJ/$top.lint") warnings, see $OBJ/$top.lint)"
