#!/bin/sh
# Every hd3_audio comparison (the FPGA half, with the ARM half tools/armdec/aud_arm.c linked
# into the testbench): default and alternate registers, scripted and random writes, several
# seeds, PAL, a contended DDR, a second build whose overflow window starts inside the entry
# table (file offset 0x2100: the table read crosses from the low window into the high one), the
# shipped delay (AUD_D 512), an ARM that runs rarely, one that never runs, and one with an
# event queue of 2.
#   sh tools/audio/tb_audio_all.sh        (build, run all; exit 0 = all identical)
# the real Python, never the WindowsApps alias (it leaked ~96 GB of commit)
PY=${PY:-/c/Users/miste/AppData/Local/Python/pythoncore-3.14-64/python.exe}
set -e
cd "$(dirname "$0")/../.."
sh tools/sim3/build_audio.sh >/dev/null
sh tools/sim3/build_audio.sh 8448 >/dev/null
AUD_D=512 EXE=tb_audio_d512 sh tools/sim3/build_audio.sh >/dev/null
AUD_QN=2 EXE=tb_audio_q2 sh tools/sim3/build_audio.sh >/dev/null
fail=0
# the ARM half's unit checks (a second pack load, an SFX ending under a full voice list)
PATH=/c/msys64/mingw64/bin:$PATH gcc -O2 -std=gnu11 -I tools/armdec tools/armdec/test_aud_arm.c \
	tools/armdec/aud_arm.c -o tools/sim3/obj/test_aud_arm.exe || fail=1
u=$(PATH=/c/msys64/mingw64/bin:$PATH tools/sim3/obj/test_aud_arm.exe) || fail=1
echo "test_aud_arm: $(echo "$u" | tail -1)"
for exe in tools/sim3/obj/tb_audio_201326592.exe "tools/sim3/obj/tb_audio_8448.exe --need-hi"; do
	for seed in 1 2 3; do
		"$PY" -I tools/audio/tb_audio_run.py --exe $exe --seed $seed || fail=1
		"$PY" -I tools/audio/tb_audio_run.py --exe $exe --seed $seed --alt || fail=1
		"$PY" -I tools/audio/tb_audio_run.py --exe $exe --seed $seed --random --frames 6000 || fail=1
	done
	"$PY" -I tools/audio/tb_audio_run.py --exe $exe --seed 4 --random --alt --frames 6000 || fail=1
	"$PY" -I tools/audio/tb_audio_run.py --exe $exe --seed 5 --random --pal --frames 3000 || fail=1
	"$PY" -I tools/audio/tb_audio_run.py --exe $exe --seed 6 --busy || fail=1
	"$PY" -I tools/audio/tb_audio_run.py --exe $exe --seed 7 --random --busy --frames 3000 || fail=1
done
E=tools/sim3/obj/tb_audio_201326592.exe
# the ARM half running about every 17 ticks (30,000 clk_f; a status every 16 ticks, D = 40): it still keeps up
"$PY" -I tools/audio/tb_audio_run.py --exe $E --seed 8 --random --frames 3000 --arm 30000 || fail=1
# the ARM half never running: every slot missing, counted; the NES path alone comes out
"$PY" -I tools/audio/tb_audio_run.py --exe $E --seed 9 --random --frames 1500 --arm 0 || fail=1
# a section not 64-byte aligned (the table bursts start below it and skip the head)
"$PY" -I tools/audio/tb_audio_run.py --exe $E --seed 3 --off 0x2028 || fail=1
"$PY" -I tools/audio/tb_audio_run.py --exe $E --seed 4 --off 0x2038 --random --frames 3000 || fail=1
"$PY" -I tools/audio/tb_audio_run.py --exe "tools/sim3/obj/tb_audio_8448.exe" --need-hi --seed 2 --off 0x2028 || fail=1
# PCM slots arriving about a tick late: a late tick is heard without its voices, never half-read
"$PY" -I tools/audio/tb_audio_run.py --exe $E --seed 3 --pcm-late --frames 3000 || fail=1
# the write port stalled long enough to fill the log FIFO: writes dropped and counted, ticks go on
"$PY" -I tools/audio/tb_audio_run.py --exe $E --seed 3 --flood --frames 600 || fail=1
# pack resets landing at every point of a tick (S_TRK, S_NES, S_MIX and idle): a tick being
# mixed finishes, the reset is stamped after it, and the ARM half sees every reset
"$PY" -I tools/audio/tb_audio_run.py --exe $E --seed 1 --reset-mid || fail=1
"$PY" -I tools/audio/tb_audio_run.py --exe $E --seed 3 --random --frames 3000 --reset-mid || fail=1
# the ARM half started late (long after the pack reset) with the BGM playing, or held by pause
# and resumed later: it begins at the FPGA's latest state event, so the BGM is heard at its frame
"$PY" -I tools/audio/tb_audio_run.py --exe $E --seed 1 --frames 3500 --arm-late playing || fail=1
"$PY" -I tools/audio/tb_audio_run.py --exe $E --seed 1 --frames 3500 --arm-late paused || fail=1
# an ARM event queue of 2 (events of one tick outnumber it: the queue-full path)
Q=tools/sim3/obj/tb_audio_q2.exe
"$PY" -I tools/audio/tb_audio_run.py --exe $Q --seed 1 || fail=1
"$PY" -I tools/audio/tb_audio_run.py --exe $Q --seed 3 --random --frames 6000 || fail=1
# the shipped delay
D=tools/sim3/obj/tb_audio_d512.exe
"$PY" -I tools/audio/tb_audio_run.py --exe $D --d 512 --seed 1 --frames 3000 || fail=1
"$PY" -I tools/audio/tb_audio_run.py --exe $D --d 512 --seed 2 --random --frames 6000 || fail=1
# the shipped delay against the worst gap measured on the A9 (2026-10-29): a 2 ms sleep, a
# checkpoint-builder pass and a restore from a checkpoint (AUD_CK - 1 frames) = ~5.7 ms, ~274
# ticks; an ARM running only that often must still keep up
"$PY" -I tools/audio/tb_audio_run.py --exe $D --d 512 --seed 3 --random --frames 3000 --arm 490000 || fail=1
"$PY" -I tools/audio/tb_audio_run.py --exe $D --d 512 --seed 6 --busy --arm 490000 || fail=1
# a pack built before 2026-10-29 (no checkpoint table in the section): the builder's path
"$PY" -I tools/audio/tb_audio_run.py --exe $D --d 512 --seed 4 --random --frames 6000 --no-ck || fail=1
"$PY" -I tools/audio/tb_audio_run.py --exe $E --seed 5 --random --alt --frames 3000 --no-ck || fail=1
# the control: an ARM slower than the delay (~600 ticks a pass) must be caught as a mismatch
if "$PY" -I tools/audio/tb_audio_run.py --exe $D --d 512 --seed 3 --random --frames 3000 --arm 1074000 >/dev/null 2>&1; then
	echo "CONTROL FAILED: an ARM slower than AUD_D was not caught"; fail=1
else
	echo "control: an ARM slower than AUD_D is caught"
fi
[ $fail = 0 ] && echo "ALL IDENTICAL" || { echo "MISMATCHES"; exit 1; }
