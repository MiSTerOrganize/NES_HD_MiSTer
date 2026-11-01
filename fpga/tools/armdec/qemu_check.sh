#!/bin/sh
# Run inside the arm32v7 container: /bin = hdarm_a9 + references, /packs = .hdp, /td = testdata.
# One frame per game; the ARM build must equal the (CR-stripped) Python reference.
set -u
ok=0; n=0
for pr in a034:rec_mmm:0200 p002:rec_cv:0250 p053:rec_smb3:0040 a057:rec_z2:0300; do
    pk=${pr%%:*}; rest=${pr#*:}; rd=${rest%%:*}; f=${rest#*:}
    n=$((n + 1))
    if ! /bin2/hdarm_a9 /packs/$pk.hdp /td/$rd/rec_$f.bin /td/$rd/watch_$f.bin --out /tmp/a.txt; then
        echo "$pk $f: hdarm FAILED (see above)"; continue
    fi
    if cmp -s /tmp/a.txt /bin2/par3/${pk}_$f.ref; then ok=$((ok + 1)); echo "$pk $f identical"; else echo "$pk $f DIFFERS"; fi
done
echo "arm32 under QEMU: $ok of $n identical"
