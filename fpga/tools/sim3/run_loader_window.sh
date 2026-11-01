#!/bin/sh
# The loader's overflow window and size limit, on a small pack: tools/audio/make_audio_pack.py
# appends an audio section to obj/loader_fix.hdp, and hd3_loader is built with MAX_BYTES inside
# that section's stream data and MAX_TOTAL just above the file. tb_loader then checks every byte
# lands in the right window, that the pack is accepted, that a non-audio section past the window
# is refused (8) and that a file over MAX_TOTAL is refused (6).
#   sh tools/sim3/run_loader_window.sh          (exit 0 = all checks pass)
# Environment: LOADER_RTL = the hd3_loader_stream.sv to build, OBJ = output folder (negative controls).
# the real Python, never the WindowsApps alias (it leaked ~96 GB of commit)
PY=${PY:-/c/Users/miste/AppData/Local/Python/pythoncore-3.14-64/python.exe}
set -e
ROOT=$(cd "$(dirname "$0")/../.." && pwd -W)
S3=$ROOT/tools/sim3
OBJ=${OBJ:-$S3/obj/loader_win}
LOADER_RTL=${LOADER_RTL:-$ROOT/rtl/hdpack/hd3_loader_stream.sv}
mkdir -p "$OBJ"
export VERILATOR_ROOT=C:/msys64/mingw64/share/verilator
export PATH=/c/msys64/mingw64/bin:$PATH
VI=$VERILATOR_ROOT/include
eval "$("$PY" -I "$ROOT/tools/audio/make_audio_pack.py" "$S3/obj/loader_fix.hdp" "$OBJ/audio_win.hdp")"
echo "pack $(stat -c %s "$OBJ/audio_win.hdp") bytes, MAX_BYTES $MAXB, MAX_TOTAL $MAXT"
rm -rf "$OBJ/v"
mkdir -p "$OBJ/v"
verilator_bin.exe --cc -O3 -Wall -Wno-fatal -Wno-DECLFILENAME -Wno-UNUSEDSIGNAL -Wno-BLKSEQ \
	--top-module hd3_loader_tb_top -GMAXB=32\'d$MAXB -GMAXT=32\'d$MAXT -Mdir "$OBJ/v" \
	"$S3/hd3_loader_tb_top.sv" "$LOADER_RTL" 2> "$OBJ/lint.txt"
if grep -q "%Error" "$OBJ/lint.txt"; then cat "$OBJ/lint.txt"; exit 1; fi
( cd "$OBJ/v" && g++ -O2 -std=c++17 -I. -I"$VI" -I"$VI/vltstd" -o "$OBJ/tb_loader_win.exe" \
	"$S3/tb_loader.cpp" Vhd3_loader_tb_top*.cpp "$VI/verilated.cpp" "$VI/verilated_threads.cpp" )
"$OBJ/tb_loader_win.exe" "$OBJ/audio_win.hdp"
