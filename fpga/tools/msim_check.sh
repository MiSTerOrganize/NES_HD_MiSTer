#!/bin/sh
# Pre-Quartus front-end check with ModelSim ASE 10.5 (the one in the Quartus 17 install).
# Verilator accepts constructs that standard SystemVerilog - and so likely Quartus 17 - rejects
# (an indexed part-select, a name used before its declaration); this compiles every
# rtl/hdpack file files.qip names with vlog and fails on any error or warning. It then loads
# hd3_render from the PROJECT folder, where Quartus resolves $readmemh paths, and checks that
# all four ROMs read the values in the .hex files (a missing file reads x and only warns).
#   sh tools/msim_check.sh          (run from anywhere; exit 0 = clean)
# Not Quartus: at the final compile still read the map report for $readmemh / 10850 warnings.
M=${MSIM:-/c/intelFPGA_lite/17.0/modelsim_ase/win32aloem}
cd "$(dirname "$0")/.." || exit 9
W=tools/sim3/obj/msim
rm -rf "$W"; mkdir -p "$W"
"$M/vlib.exe" "$W/work" > /dev/null || { echo "vlib failed"; exit 2; }
files=$(sed -n 's/.*SYSTEMVERILOG_FILE \(rtl\/hdpack\/[^ ]*\.sv\).*/\1/p' files.qip)
n=0; bad=0
for f in $files; do
	n=$((n + 1))
	out=$("$M/vlog.exe" -sv -work "$W/work" "$f" 2>&1)
	sum=$(echo "$out" | grep -E "Errors: [0-9]+, Warnings: [0-9]+" | tail -1)
	case "$sum" in
	*"Errors: 0, Warnings: 0"*) ;;
	*) bad=$((bad + 1)); echo "$f: ${sum:-no summary}"; echo "$out" | grep -E "^\*\* " | head -10 ;;
	esac
done
echo "vlog: $n files, $bad with errors or warnings"
[ "$n" -ge 20 ] || { echo "only $n files found in files.qip - list parsing broken?"; exit 2; }
# ROM contents, read in the project folder
cat > "$W/check.do" <<'DO_EOF'
vsim -c -quiet -lib tools/sim3/obj/msim/work hd3_render
run 0
echo "PAL0 [examine -radix hex /hd3_render/pal_rom(0)]"
echo "PAL1 [examine -radix hex /hd3_render/pal_rom(1)]"
echo "PAL48 [examine -radix hex /hd3_render/pal_rom(48)]"
echo "ER100 [examine -radix hex /hd3_render/rom_er(100)]"
echo "EG100 [examine -radix hex /hd3_render/rom_eg(100)]"
echo "EB100 [examine -radix hex /hd3_render/rom_eb(100)]"
quit -f
DO_EOF
sim=$("$M/vsim.exe" -c -do "$W/check.do" 2>&1)
echo "$sim" | grep -qi "Failed to open readmem" && { bad=$((bad + 1)); echo "a ROM file did not open:"; echo "$sim" | grep -i readmem; }
line() { sed -n "$(($2 + 1))p" "rtl/hdpack/$1" | tr -d '\r ' | tr 'A-F' 'a-f'; }
got() { echo "$sim" | sed -n "s/.*# $1 \([0-9a-fA-Fx]*\).*/\1/p" | tail -1 | tr 'A-F' 'a-f' | sed 's/^0*\(.\)/\1/'; }
for c in "PAL0 hd3_pal2c02.hex 0" "PAL1 hd3_pal2c02.hex 1" "PAL48 hd3_pal2c02.hex 48" \
	"ER100 hd3_emph_r.hex 100" "EG100 hd3_emph_g.hex 100" "EB100 hd3_emph_b.hex 100"; do
	set -- $c
	want=$(line "$2" "$3" | sed 's/^0*\(.\)/\1/')
	have=$(got "$1")
	if [ -z "$have" ] || [ "$have" != "$want" ]; then
		bad=$((bad + 1)); echo "$1: read '${have:-nothing}', file has '$want'"
	fi
done
# hd3_paint (the display-list route) loads its own copies of the three emphasis ROMs
printf '%s\n' 'vsim -c -quiet -lib tools/sim3/obj/msim/work hd3_paint' 'run 0' \
	'echo "PER100 [examine -radix hex /hd3_paint/rom_er(100)]"' \
	'echo "PEG100 [examine -radix hex /hd3_paint/rom_eg(100)]"' \
	'echo "PEB100 [examine -radix hex /hd3_paint/rom_eb(100)]"' \
	'echo "PEB7 [examine -radix hex /hd3_paint/rom_eb(7)]"' 'quit -f' > "$W/check_paint.do"
sim=$("$M/vsim.exe" -c -do "$W/check_paint.do" 2>&1)
echo "$sim" | grep -qi "Failed to open readmem" && { bad=$((bad + 1)); echo "a hd3_paint ROM file did not open:"; echo "$sim" | grep -i readmem; }
for c in "PER100 hd3_emph_r.hex 100" "PEG100 hd3_emph_g.hex 100" "PEB100 hd3_emph_b.hex 100" "PEB7 hd3_emph_b.hex 7"; do
	set -- $c
	want=$(line "$2" "$3" | sed 's/^0*\(.\)/\1/')
	have=$(got "$1")
	if [ -z "$have" ] || [ "$have" != "$want" ]; then
		bad=$((bad + 1)); echo "$1: read '${have:-nothing}', file has '$want'"
	fi
done
[ "$bad" -eq 0 ] && { echo "ModelSim front-end check: PASS ($n files, 4 hd3_render ROMs + 3 hd3_paint ROMs)"; exit 0; }
echo "ModelSim front-end check: FAIL ($bad problems)"; exit 1
