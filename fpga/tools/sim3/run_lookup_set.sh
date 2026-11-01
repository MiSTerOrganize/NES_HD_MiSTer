#!/bin/sh
# Run the hd3_lookup unit test over a set of converted packs, two DDR3 timing profiles each.
#   sh tools/sim3/run_lookup_set.sh <hdp_dir> <name> [<name> ...]
# Exits non-zero if any pack has a mismatch.
# the real Python, never the WindowsApps alias (it leaked ~96 GB of commit)
PY=${PY:-/c/Users/miste/AppData/Local/Python/pythoncore-3.14-64/python.exe}
D=$1; shift
S3=$(cd "$(dirname "$0")" && pwd)
mkdir -p "$S3/obj/runs"
fail=0
for n in "$@"; do
	# third profile: --key-only (stage 3's record dictionary mode, no rule-list read)
	for prof in "12 0" "40 30" "40 30 --key-only"; do
		set -- $prof
		out="$S3/obj/runs/$n.lat$1.busy$2$3.tsv"
		"$S3/obj/tb_lookup.exe" "$D/$n.hdp" "$out" --lat "$1" --busy "$2" --seed 7 $3 || { echo "TB FAILED: $n"; fail=1; continue; }
		"$PY" -I "$S3/check_lookup.py" "$D/$n.hdp" "$out" $3 || fail=1
	done
done
exit $fail
