#!/bin/sh
# Build the whole-core NES + HD pack Verilator simulation.
#   sh tools/fullsim/build.sh [--lint]
# MSYS2 make cannot build on this box (its TMP override breaks gcc), so verilator_bin.exe and
# g++ are driven directly, as tools/sim/build_tb.sh does.
set -e
# Windows-form path (C:/...): verilator_bin.exe reads the file list itself and cannot resolve /c/...
ROOT=$(cd "$(dirname "$0")/../.." && pwd -W)
FS=$ROOT/tools/fullsim
# OBJ overrides the build folder (so a second build cannot clobber a fullsim.exe still running).
# PAINT=1 builds the display-list route: hd3_pengine + hd3_paint instead of hd3_engine, and
# hdarm4.c linked in as the ARM model (fullsim --arm).
OBJ=${OBJ:-$FS/obj}
mkdir -p "$OBJ"
OBJ=$(cd "$OBJ" && pwd -W)
export VERILATOR_ROOT=C:/msys64/mingw64/share/verilator
export PATH=/c/msys64/mingw64/bin:$PATH
mkdir -p "$OBJ/ghdl"

# 1. T65 (VHDL) -> Verilog with GHDL. Analysis order: package/eReg first, then T65.
GH="--std=08 -fsynopsys -fexplicit --workdir=$OBJ/ghdl"
rm -f "$OBJ/ghdl/"*.cf
for f in rtl/bus_savestates.vhd rtl/t65/T65_Pack.vhd rtl/t65/T65_ALU.vhd rtl/t65/T65_MCode.vhd rtl/t65/T65.vhd; do
	ghdl -a $GH "$ROOT/$f"
done
ghdl synth $GH --out=verilog T65 > "$OBJ/t65_raw.v" 2> "$OBJ/t65_synth.log"
# rename the top so a case-matching wrapper (sim_lib.sv) can sit in front of it; GHDL emits
# signal names that are SystemVerilog keywords (break, do ...), so parse it as Verilog-2005.
{
	echo '`begin_keywords "1364-2005"'
	sed -e 's/^module T65$/module T65_ghdl/' "$OBJ/t65_raw.v"
	echo '`end_keywords'
} > "$OBJ/t65.v"
LINES=$(wc -l < "$OBJ/t65.v")
MODS=$(grep -c '^module ' "$OBJ/t65.v")
grep -q '^module T65_ghdl' "$OBJ/t65.v" || { echo "T65 rename failed"; exit 1; }
# A failed analysis can still emit a port-only shell: insist on a real CPU.
if [ "$LINES" -lt 5000 ] || [ "$MODS" -lt 4 ]; then
	echo "GHDL output looks hollow ($LINES lines, $MODS modules) - see $OBJ/t65_synth.log"; exit 1
fi
echo "T65: $LINES lines, $MODS modules"

# 2. GameLoader extracted from NES.sv so it always tracks the real one.
awk '/^module GameLoader/{f=1} f{print} f&&/^endmodule/{exit}' "$ROOT/NES.sv" > "$OBJ/gameloader.sv"
grep -q '^endmodule' "$OBJ/gameloader.sv" || { echo "GameLoader extraction failed"; exit 1; }

# 3. Constant lookup tables declared as `wire [w] name[n] = '{...};` (a net array with an
#    initialiser) are accepted by Quartus but not by Verilator. Build-time copies of the three
#    files that have them turn exactly those declarations into `localparam logic`; nothing else
#    changes and rtl/ is not touched.
mkdir -p "$OBJ/patched"
for f in rtl/mappers/FDS.sv rtl/mappers/Sunsoft.sv rtl/video.sv; do
	sed -e 's/^\([[:space:]]*\)wire\([[:space:]]*\[[^]]*\][[:space:]]*[A-Za-z0-9_]*[[:space:]]*\[[^]]*\][[:space:]]*=\)/\1localparam logic\2/' \
		"$ROOT/$f" > "$OBJ/patched/$(basename "$f")"
done
NPATCH=$(cat "$OBJ/patched/"*.sv | grep -c '^[[:space:]]*localparam logic[[:space:]]*\[')
[ "$NPATCH" -eq 12 ] || { echo "LUT patch count $NPATCH, expected 12"; exit 1; }

# 4. File list (LF). Package first, then ppu.sv (its file-scope import serves the other files).
LIST="$OBJ/files.f"
: > "$LIST"
for f in rtl/regs_savestates.sv rtl/ppu.sv rtl/compat.v rtl/dsp.v rtl/apu.sv rtl/cart.sv \
         OBJ/patched/FDS.sv rtl/mappers/JYCompany.sv rtl/mappers/MMC1.sv rtl/mappers/MMC2.sv \
         rtl/mappers/MMC3.sv rtl/mappers/MMC5.sv rtl/mappers/Mapper99.sv rtl/mappers/Namco.sv \
         rtl/mappers/Sachen.sv OBJ/patched/Sunsoft.sv rtl/mappers/VRC.sv rtl/mappers/generic.sv \
         rtl/mappers/misc.sv rtl/EEPROM_24C0x.sv rtl/cheatcodes.sv rtl/composite_board.sv \
         OBJ/patched/video.sv rtl/nes.v rtl/hdpack/hd_tap.sv \
         rtl/hdpack/hd3_engine.sv rtl/hdpack/hd3_pengine.sv rtl/hdpack/hd3_paint.sv \
         rtl/hdpack/hd3_cross.sv rtl/hdpack/hd3_scanout.sv \
         rtl/hdpack/hd3_loader.sv rtl/hdpack/hd3_ddr.sv rtl/hdpack/hd3_dict.sv rtl/hdpack/hd3_add.sv \
         rtl/hdpack/hd3_resolve.sv rtl/hdpack/hd3_fmap.sv rtl/hdpack/hd3_render.sv \
         rtl/hdpack/hd3_ccache.sv rtl/hdpack/hd3_rcache.sv rtl/hdpack/hd3_lookup.sv \
         rtl/hdpack/hd3_romfix.sv rtl/hdpack/hd3_audio.sv \
         rtl/hdpack/hd_chrfp.sv rtl/hdpack/hd_capture.sv rtl/hdpack/hd_watch.sv \
         rtl/hdpack/hd_sdram_port.sv rtl/hdpack/hd_stage2.sv rtl/zapper.sv rtl/hd_reticle.sv \
         sys/iir_filter.v; do
	case "$f" in OBJ/*) printf '%s\n' "$OBJ/${f#OBJ/}" >> "$LIST" ;; *) printf '%s\n' "$ROOT/$f" >> "$LIST" ;; esac
done
printf '%s\n' "$OBJ/gameloader.sv" "$OBJ/t65.v" "$FS/sim_lib.sv" "$FS/sim_top.sv" >> "$LIST"

VFLAGS="-Wno-fatal -Wno-lint -Wno-style -Wno-PINMISSING -Wno-MULTIDRIVEN -Wno-UNOPTFLAT \
	-Wno-BLKANDNBLK -Wno-COMBDLY -Wno-SYMRSVDWORD -Wno-TIMESCALEMOD -Wno-INITIALDLY -Wno-ASSIGNIN -Wno-PROCASSWIRE \
	--no-timing --top-module sim_top -Mdir $OBJ/vl \
	+define+HD3_HEX_PROJECT"
EXTRA_CXX=""
if [ "${PAINT:-0}" = 1 ]; then
	VFLAGS="$VFLAGS +define+HD_PAINT"
	EXTRA_CXX="-DFULLSIM_ARM"
fi
# HD3_HEX_PROJECT: fullsim runs from the project folder, so hd3_render's $readmemh takes the
# project paths ("rtl/hdpack/...") exactly as Quartus does; fullsim.cpp refuses to start if
# they are not there (a missing file only warns and leaves the ROM all zeros).

if [ "$1" = "--lint" ]; then
	verilator_bin.exe --lint-only $VFLAGS -f "$LIST"
	echo "lint ok"; exit 0
fi

rm -rf "$OBJ/vl"
# THREADS=n sh build.sh  -> Verilator multithreaded model (default 1)
verilator_bin.exe --cc -O3 --threads "${THREADS:-1}" --x-assign fast --x-initial fast $VFLAGS -f "$LIST"
VI=$VERILATOR_ROOT/include
# Compile each generated file separately (parallel) then link.
cd "$OBJ/vl"
CXXF="-O3 -march=native -std=c++17 -Wno-attributes -I. -I$VI -I$VI/vltstd"
pids=""
# JOBS caps the parallel compiles (each -O3 unit of the whole core takes ~1-2 GB; unlimited ran
# this box out of memory while other builds were running). Default: all at once.
JOBS=${JOBS:-0}
n=0
for c in Vsim_top*.cpp "$VI/verilated.cpp" "$VI/verilated_threads.cpp"; do
	o=$(basename "$c" .cpp).o
	g++ $CXXF -c "$c" -o "$o" &
	pids="$pids $!"
	n=$((n + 1))
	if [ "$JOBS" -gt 0 ] && [ $((n % JOBS)) = 0 ]; then
		for p in $pids; do wait $p || { echo "compile failed"; exit 1; }; done
		pids=""
	fi
done
g++ $CXXF $EXTRA_CXX -c "$FS/fullsim.cpp" -o fullsim.o &
pids="$pids $!"
# the ARM half of the ROM patcher (every build: hd3_romfix waits for its answer)
gcc -O2 -std=gnu11 -c "$ROOT/tools/armdec/romfix_arm.c" -o romfix_arm.o &
pids="$pids $!"
# the ARM half of HD audio (every build: hd3_audio mixes the PCM slots it writes)
gcc -O2 -std=gnu11 -c "$ROOT/tools/armdec/aud_arm.c" -o aud_arm.o &
pids="$pids $!"
if [ "${PAINT:-0}" = 1 ]; then
	# the ARM program's decisions, as a library (tools/armdec/hdarm4.c, HDARM_LIB)
	gcc -O2 -std=gnu11 -DHDARM_LIB -c "$ROOT/tools/armdec/hdarm4.c" -o hdarm4.o &
	pids="$pids $!"
fi
fail=0
for p in $pids; do wait $p || fail=1; done
[ $fail = 0 ] || { echo "compile failed"; exit 1; }
g++ -O2 -o "$OBJ/fullsim.exe" *.o -lz -pthread
echo "built $OBJ/fullsim.exe"
