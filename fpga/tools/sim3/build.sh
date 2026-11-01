#!/bin/sh
# Build the stage-2 unit testbenches. MSYS2 make cannot build on this box (its TMP override
# breaks gcc), so verilator_bin.exe and g++ are driven directly.
#   sh tools/sim3/build.sh            -> tools/sim3/obj/tb_lookup.exe
# Environment overrides (used by the negative-control runner): LOOKUP_RTL = path of the
# hd3_lookup.sv to build, OBJ = output folder.
set -e
ROOT=$(cd "$(dirname "$0")/../.." && pwd -W)
S3=$ROOT/tools/sim3
OBJ=${OBJ:-$S3/obj}
LOOKUP_RTL=${LOOKUP_RTL:-$ROOT/rtl/hdpack/hd3_lookup.sv}
export VERILATOR_ROOT=C:/msys64/mingw64/share/verilator
export PATH=/c/msys64/mingw64/bin:$PATH
VI=$VERILATOR_ROOT/include

build() {   # build <top> <tb.cpp> <rtl files...>
	top=$1; tb=$2; shift 2
	rm -rf "$OBJ/$top"
	mkdir -p "$OBJ/$top"
	verilator_bin.exe --cc -O3 -Wall -Wno-fatal -Wno-DECLFILENAME -Wno-UNUSEDSIGNAL -Wno-BLKSEQ \
		--top-module "$top" -Mdir "$OBJ/$top" "$@" 2> "$OBJ/$top.lint"
	if grep -q "%Error" "$OBJ/$top.lint"; then cat "$OBJ/$top.lint"; exit 1; fi
	( cd "$OBJ/$top" && g++ -O2 -std=c++17 -I. -I"$VI" -I"$VI/vltstd" -o "$OBJ/$(basename "$tb" .cpp).exe" \
		"$tb" V"$top"*.cpp "$VI/verilated.cpp" "$VI/verilated_threads.cpp" )
	echo "built $OBJ/$(basename "$tb" .cpp).exe ($(grep -c '%Warning' "$OBJ/$top.lint") warnings, see $OBJ/$top.lint)"
}

build hd3_tb_top "$S3/tb_lookup.cpp" "$S3/hd3_tb_top.sv" "$LOOKUP_RTL"
[ -n "$ONLY_LOOKUP" ] && exit 0
build hd3_loader_tb_top "$S3/tb_loader.cpp" "$S3/hd3_loader_tb_top.sv" "$ROOT/rtl/hdpack/hd3_loader_stream.sv"
build hd_chrfp_tb_top "$S3/tb_chrfp.cpp" "$S3/hd_chrfp_tb_top.sv" "${CHRFP_RTL:-$ROOT/rtl/hdpack/hd_chrfp.sv}"
build hd_capture_tb_top "$S3/tb_capture.cpp" "$S3/hd_capture_tb_top.sv" "${CAPTURE_RTL:-$ROOT/rtl/hdpack/hd_capture.sv}" "$ROOT/rtl/hdpack/hd_chrfp.sv"
build hd_watch "$S3/tb_watch.cpp" "${WATCH_RTL:-$ROOT/rtl/hdpack/hd_watch.sv}"
