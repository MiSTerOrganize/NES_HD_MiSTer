#!/bin/sh
# qemu_parity.sh - the parity half of bench_a9.sh, run under QEMU (linux/arm/v7) before a
# bundle goes to the MiSTer: the A9 build's decision output must match expected.md5 on EVERY
# frame. /b = the bundle (read-only); it is copied to a scratch directory to be unpacked.
# usage (inside the container): sh qemu_parity.sh [BINARY]   (BINARY defaults to hdarm4_a9)
X=${1:-hdarm4_a9}
W=/tmp/qp; rm -rf "$W"; mkdir -p "$W"; cp -r /b/. "$W"/; cd "$W" || exit 1
for g in *.hdp.gz */rec_*.bin.gz; do
    [ -f "$g" ] || continue
    [ -f "${g%.gz}" ] || gunzip -c "$g" > "${g%.gz}"
done
chmod +x "./$X"
pass=0; dlpass=0; n=0
while read pk rd f; do
    n=$((n + 1))
    "./$X" "$pk.hdp" "$rd/rec_$f.bin" "$rd/watch_$f.bin" --out /tmp/hd_dec.txt 2>/dev/null
    got=$(md5sum /tmp/hd_dec.txt | cut -d' ' -f1)
    want=$(grep " ${pk}_$f\$" expected.md5 | cut -d' ' -f1)
    if [ -n "$want" ] && [ "$got" = "$want" ]; then pass=$((pass + 1)); else echo "PARITY FAIL $pk $f (got $got want $want)"; fi
    # the display list WITHOUT the decision dump: the dump turns hdarm4's fast paths off, so this
    # is the run the daemon actually makes (expected_dl.md5 = the pixel-exact reference lists)
    rm -f /tmp/hd_dl.bin
    "./$X" "$pk.hdp" "$rd/rec_$f.bin" "$rd/watch_$f.bin" --dl /tmp/hd_dl.bin 2>/dev/null
    got=$(md5sum /tmp/hd_dl.bin 2>/dev/null | cut -d' ' -f1)
    want=$(grep " ${pk}_$f\$" expected_dl.md5 | cut -d' ' -f1)
    if [ -n "$want" ] && [ "$got" = "$want" ]; then dlpass=$((dlpass + 1)); else echo "LIST FAIL $pk $f (got $got want $want)"; fi
done < frames.txt
echo "PARITY $pass of $n   DISPLAY LIST $dlpass of $n"
[ "$pass" -eq "$n" ] && [ "$dlpass" -eq "$n" ] && [ "$n" -gt 0 ]
