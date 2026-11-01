#!/bin/sh
# Build tools/sim3/obj/tb_audio*.exe (rtl/hdpack/hd3_audio.sv under tb_audio.cpp, with the ARM
# half tools/armdec/aud_arm.c linked in).
#   sh tools/sim3/build_audio.sh [WIN_BYTES]
# WIN_BYTES (decimal, default 192 MB) is the file offset where the overflow window starts; the
# tests set it inside the section's entry table so its read crosses into the high window.
# Environment: AUDIO_RTL = the hd3_audio.sv to build, AUD_ARM = the aud_arm.c to link (both for
# the negative control), AUD_D = the delay in ticks (default 40: the tests then hear the voices
# within a few hundred frames; the shipped 512 is built and run by tb_audio_all.sh), AUD_QN =
# the ARM half's event queue (default 256; 2 runs the queue-full path), OBJ = output folder,
# EXE = output name.
set -e
ROOT=$(cd "$(dirname "$0")/../.." && pwd -W)
S3=$ROOT/tools/sim3
OBJ=${OBJ:-$S3/obj}
RTL=${AUDIO_RTL:-$ROOT/rtl/hdpack/hd3_audio.sv}
ARMC=${AUD_ARM:-$ROOT/tools/armdec/aud_arm.c}
WIN=${1:-201326592}
D=${AUD_D:-40}
QN=${AUD_QN:-256}
EXE=${EXE:-tb_audio_$WIN}
export VERILATOR_ROOT=C:/msys64/mingw64/share/verilator
export PATH=/c/msys64/mingw64/bin:$PATH
VI=$VERILATOR_ROOT/include
MD=$OBJ/$EXE
rm -rf "$MD"
mkdir -p "$MD"
verilator_bin.exe --cc -O3 -Wall -Wno-fatal -Wno-DECLFILENAME -Wno-UNUSEDSIGNAL -Wno-BLKSEQ \
	--top-module hd3_audio -GWIN_BYTES=29\'d$WIN -GAUD_D=$D -Mdir "$MD" "$RTL" 2> "$MD.lint"
if grep -q "%Error" "$MD.lint"; then cat "$MD.lint"; exit 1; fi
( cd "$MD" && gcc -O2 -std=gnu11 -Wall -I"$ROOT/tools/armdec" -DAUD_QN=$QN -c "$ARMC" -o aud_arm.o && \
	g++ -O2 -std=c++17 -DWIN_BYTES=${WIN}ULL -DAUD_D=$D -DAUD_QN=$QN -I. -I"$VI" -I"$VI/vltstd" \
	-I"$ROOT/tools/armdec" -o "$OBJ/$EXE.exe" "$S3/tb_audio.cpp" Vhd3_audio*.cpp aud_arm.o \
	"$VI/verilated.cpp" "$VI/verilated_threads.cpp" )
echo "built $OBJ/$EXE.exe (AUD_D $D, AUD_QN $QN, $(grep -c '%Warning' "$MD.lint") warnings)"
