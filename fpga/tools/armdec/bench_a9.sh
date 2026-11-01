#!/bin/sh
# bench_a9.sh - run on the MiSTer (busybox sh). Unpacks the bundle, proves the decision output
# equals the reference on EVERY frame (md5), then times each frame on core 0 (the render core).
# usage: sh bench_a9.sh BUNDLE_DIR [ITERS] [BINARY]   (BINARY defaults to hdarm_a9)
B=$1; IT=${2:-20}; X=./${3:-hdarm_a9}
cd "$B" || exit 1
echo "binary=$X md5=$(md5sum "$X" | cut -d' ' -f1)"
echo "CORENAME=$(cat /tmp/CORENAME 2>/dev/null)  date=$(date)"
for g in *.hdp.gz */rec_*.bin.gz; do
    [ -f "$g" ] || continue
    [ -f "${g%.gz}" ] || gunzip -k "$g" 2>/dev/null || gunzip -c "$g" > "${g%.gz}"
done
chmod +x "$X"
pass=0; dlpass=0; n=0
while read pk rd f; do
    n=$((n + 1))
    "$X" "$pk.hdp" "$rd/rec_$f.bin" "$rd/watch_$f.bin" --out /tmp/hd_dec.txt 2>/dev/null
    got=$(md5sum /tmp/hd_dec.txt | cut -d' ' -f1)
    want=$(grep " ${pk}_$f\$" expected.md5 | cut -d' ' -f1)
    if [ "$got" = "$want" ]; then pass=$((pass + 1)); else echo "PARITY FAIL $pk $f"; fi
    # the display list without the decision dump (the dump turns the fast paths off)
    if [ -f expected_dl.md5 ]; then
        rm -f /tmp/hd_dl.bin
        "$X" "$pk.hdp" "$rd/rec_$f.bin" "$rd/watch_$f.bin" --dl /tmp/hd_dl.bin 2>/dev/null
        got=$(md5sum /tmp/hd_dl.bin 2>/dev/null | cut -d' ' -f1)
        want=$(grep " ${pk}_$f\$" expected_dl.md5 | cut -d' ' -f1)
        if [ -n "$want" ] && [ "$got" = "$want" ]; then dlpass=$((dlpass + 1)); else echo "LIST FAIL $pk $f"; fi
    fi
done < frames.txt
rm -f /tmp/hd_dec.txt /tmp/hd_dl.bin
echo "PARITY $pass of $n   DISPLAY LIST $dlpass of $n"
echo "TIMING (taskset core 0, $IT iterations per frame, ms)"
while read pk rd f; do
    r=$(taskset 0x01 "$X" "$pk.hdp" "$rd/rec_$f.bin" "$rd/watch_$f.bin" --iters "$IT" 2>&1)
    w=$(echo "$r" | sed -n 's/^rules_walked \([0-9]*\) conds_evaluated \([0-9]*\).*/\1 \2/p')
    tot=$(echo "$r" | sed -n 's/^TOTAL *min *\([0-9.]*\) ms *median *\([0-9.]*\) ms *max *\([0-9.]*\) ms/\1 \2 \3/p')
    rec=$(echo "$r" | sed -n 's/^records *min *\([0-9.]*\) ms *median *\([0-9.]*\).*/\2/p')
    lk=$(echo "$r" | sed -n 's/^lookups *min *\([0-9.]*\) ms *median *\([0-9.]*\).*/\2/p')
    ad=$(echo "$r" | sed -n 's/^additions *min *\([0-9.]*\) ms *median *\([0-9.]*\).*/\2/p')
    lv=$(echo "$r" | sed -n 's/^levels *min *\([0-9.]*\) ms *median *\([0-9.]*\).*/\2/p')
    dl=$(echo "$r" | sed -n 's/^displaylist *min *\([0-9.]*\) ms *median *\([0-9.]*\).*/\2/p')
    echo "$pk $f work[rules conds]=$w total[min med max]=$tot records=$rec levels=$lv additions=$ad lookups=$lk displaylist=$dl"
done < frames.txt
