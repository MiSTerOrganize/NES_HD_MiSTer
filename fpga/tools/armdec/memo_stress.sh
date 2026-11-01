#!/bin/sh
# memo_stress.sh - stress the hdarm4 reuse memos beyond the 29 reference frames.
# For every pack (the real ones plus the synthetic condition packs in tools/sim3/obj/dict)
# and every recorded frame of the matching game:
#   (1) a MEMO_VERIFY build does the full walk at every memo hit and counts mismatches;
#   (2) the normal build's decision dump must equal hdarm3's (the proven reference);
#   (3) its display list without the dump must equal the one with it (fast paths).
# usage: sh memo_stress.sh H4_EXE H4_VERIFY_EXE HDARM3_EXE WORKDIR
# Exit 0 only if no memo mismatch and no decision difference anywhere.
set -u
X=$1; XV=$2; H3=$3; W=$4; mkdir -p "$W"
HERE=$(cd "$(dirname "$0")" && pwd)
T=$HERE/../../../NES_HDPack_testdata
D=$HERE/../sim3/obj/dict
OUT=Z:/NES_HDPack_work/out
frames=0; checked=0; failed=0; dec_bad=0; dl_bad=0; skipped=0
recdirs() {   # game prefix -> recording directories
    case "$1" in
        a034*|mms*) echo "$T/rec_mmm $D/rec_mmmfx $D/rec_mmmhid $D/rec_mmml0 $D/rec_mmmvs" ;;
        a057*|h_z2*) echo "$T/rec_z2 $T/rec_z2b $T/rec_z2edge $D/rec_z2dhid $D/rec_z2ph $D/rec_z2slot $D/rec_z2vs" ;;
        p002*|h_cv*) echo "$T/rec_cv $D/rec_cvdhid $D/rec_cvl0" ;;
        p053*) echo "$T/rec_smb3 $D/rec_smbscr $D/rec_smbslot" ;;
        *) echo "" ;;
    esac
}
for pk in "$OUT/a034.hdp" "$OUT/a057.hdp" "$OUT/p002.hdp" "$OUT/p053.hdp" "$D"/*.hdp; do
    name=$(basename "$pk" .hdp)
    for rd in $(recdirs "$name"); do
        [ -d "$rd" ] || continue
        for r in "$rd"/rec_*.bin; do
            [ -f "$r" ] || continue
            f=$(basename "$r" .bin); f=${f#rec_}
            wf="$rd/watch_$f.bin"
            [ -f "$wf" ] || continue
            v=$("$XV" "$pk" "$r" "$wf" 2>&1)
            line=$(echo "$v" | grep "MEMO_VERIFY")
            if [ -z "$line" ]; then skipped=$((skipped + 1)); continue; fi
            frames=$((frames + 1))
            c=$(echo "$line" | sed 's/.*checked \([0-9]*\) failed \([0-9]*\).*/\1/')
            e=$(echo "$line" | sed 's/.*checked \([0-9]*\) failed \([0-9]*\).*/\2/')
            checked=$((checked + c)); failed=$((failed + e))
            [ "$e" -ne 0 ] && { echo "MEMO MISMATCH $name $(basename "$rd") $f: $e"; echo "$v" | grep "MEMO MISMATCH" | head -3; }
            rm -f "$W/a.dl" "$W/c.dl"
            "$X" "$pk" "$r" "$wf" --out "$W/a.txt" --dl "$W/a.dl" >/dev/null 2>&1
            "$H3" "$pk" "$r" "$wf" --out "$W/b.txt" >/dev/null 2>&1
            if ! cmp -s "$W/a.txt" "$W/b.txt"; then dec_bad=$((dec_bad + 1)); echo "DECISIONS DIFFER $name $(basename "$rd") $f"; fi
            # (3) the display list WITHOUT the decision dump must equal the one WITH it: the dump
            #     forces every pixel through the full loop, so this is what checks the fast paths
            "$X" "$pk" "$r" "$wf" --dl "$W/c.dl" >/dev/null 2>&1
            if ! cmp -s "$W/a.dl" "$W/c.dl"; then dl_bad=$((dl_bad + 1)); echo "FAST-PATH LIST DIFFERS $name $(basename "$rd") $f"; fi
        done
    done
done
echo "frames $frames (skipped $skipped)  memo hits checked $checked  mismatches $failed  decision diffs $dec_bad  fast-path list diffs $dl_bad"
[ "$failed" -eq 0 ] && [ "$dec_bad" -eq 0 ] && [ "$dl_bad" -eq 0 ] && [ "$frames" -gt 0 ]
