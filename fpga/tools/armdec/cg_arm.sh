#!/bin/sh
# cg_arm.sh - ARM instruction counts for hdarm4 on recorded frames, without the MiSTer.
# Runs inside an emulated linux/arm/v7 debian:bookworm, for example:
#   docker run --rm --platform linux/arm/v7 -v <tools/armdec>:/src:ro -v <bundle>:/b:ro \
#       -v <work>:/o -v <tools/armdec>:/s:ro debian:bookworm sh /s/cg_arm.sh p002:rec_cv:0060
# /b holds <pack>.hdp.gz and <recdir>/{rec,watch}_<frame>.bin[.gz] (make_bundle.py output).
# Each frame runs with --iters 1 and --iters 3; the WARM per-frame count is
#   (I refs at iters=3 - I refs at iters=1) / 2
# which removes the load and first-frame setup. Built with the shipped flags (xbuild.sh).
# Timing estimate used on 2026-10-22: ~1.03 ns per ARM instruction on the A9 (an earlier A9
# bench gave 1.29 ns per x86 instruction, and ARM runs ~1.25 instructions per x86 one), so a
# 14 ms decision budget is about 13.6M instructions. The real A9 bench (bench_a9.sh) decides.
if ! command -v valgrind >/dev/null 2>&1; then
    apt-get update -qq >/dev/null
    apt-get install -y -qq valgrind gcc libc6-dev >/dev/null
fi
cd /o || exit 1
gcc -O3 -fno-pie -no-pie -mcpu=cortex-a9 -mfpu=neon ${CF:--DHD_NOOUT} -o /o/h4arm /src/${SRC:-hdarm4.c} -lm || exit 1
for spec in "$@"; do
    pk=${spec%%:*}; rest=${spec#*:}; rd=${rest%%:*}; f=${rest#*:}
    [ -f /o/$pk.hdp ] || gunzip -c /b/$pk.hdp.gz > /o/$pk.hdp
    mkdir -p /o/$rd
    for k in rec watch; do
        if [ -f /b/$rd/${k}_$f.bin.gz ]; then [ -s /o/$rd/${k}_$f.bin ] || gunzip -c /b/$rd/${k}_$f.bin.gz > /o/$rd/${k}_$f.bin; else cp /b/$rd/${k}_$f.bin /o/$rd/; fi
    done
    a=; b=
    for it in 1 3; do
        timeout 3000 valgrind --tool=cachegrind --cache-sim=no --cachegrind-out-file=/dev/null \
            /o/h4arm /o/$pk.hdp /o/$rd/rec_$f.bin /o/$rd/watch_$f.bin --iters $it > /o/cga_$it.out 2>&1
        rc=$?
        n=$(sed -n 's/.*I *refs: *//p' /o/cga_$it.out | tr -d ,)
        [ $rc -eq 0 ] && [ -n "$n" ] || { echo "$pk $f iters=$it FAILED rc=$rc"; n=; }
        [ $it -eq 1 ] && a=$n || b=$n
    done
    if [ -n "$a" ] && [ -n "$b" ]; then
        echo "$pk $f warm $(( (b - a) / 2 ))"
    fi
done
