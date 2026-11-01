#!/bin/sh
# hd3_fmap unit test: drive the capture writer's record stream (gen_fmap_stream.py) into one
# hd3_fmap through tb_fmap.exe, and check every map dump against the generator's byte model of
# the two record buffers. Two seeds; phase 1 fills bank 0 from a Castlevania record and bank 1
# from a Super Mario Bros. 3 record, phases 2-4 are the writer's partial shapes on random bytes.
#   sh run_fmap.sh [testdata dir]
# EXE overrides the testbench binary (the negative control passes its mutants' builds); OUT the
# output folder.
# the real Python, never the WindowsApps alias (it leaked ~96 GB of commit)
PY=${PY:-/c/Users/miste/AppData/Local/Python/pythoncore-3.14-64/python.exe}
cd "$(dirname "$0")"
T=${1:-C:/Users/miste/OneDrive/Desktop/MiSTerOrganize/MiSTerFrontier/NES_HDPack_testdata}
EXE=${EXE:-$(pwd -W)/obj/tb_fmap.exe}
OUT=${OUT:-$(pwd -W)/obj/fmap}
mkdir -p "$OUT"
A=$T/rec_cv/rec_0250.bin
B=$T/rec_smb3/rec_0300.bin
fail=0
for seed in 1 2; do
	S=$OUT/stream_$seed.bin
	[ -f "$S" ] || "$PY" -I gen_fmap_stream.py gen "$S" "$A" "$B" $seed > /dev/null \
		|| { echo "[seed $seed] stream generation failed"; fail=1; continue; }
	if ! "$EXE" "$OUT/s$seed" "$S" > "$OUT/s$seed.log" 2>&1; then
		echo "[seed $seed] testbench failed: $(tail -3 "$OUT/s$seed.log" | tr '\n' ' ')"; fail=1; continue
	fi
	echo "[seed $seed] $(cat "$OUT/s$seed.log")"
	r=$("$PY" -I gen_fmap_stream.py check "$S" "$A" "$B" $seed "$OUT/s$seed" 2>&1)
	echo "[seed $seed] $(echo "$r" | tail -1)"
	echo "$r" | grep -q "^PASS$" || { echo "$r" | head -12; fail=1; }
done
[ $fail -eq 0 ] && echo "ALL PASS" || echo "FAIL"
exit $fail
