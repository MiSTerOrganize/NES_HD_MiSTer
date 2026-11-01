"""make_bundle.py - package the A9 benchmark inputs small enough to send over the MiSTer's Wi-Fi.

The decision pass never reads section 4 (the image blocks, most of every .hdp), so each pack is
copied with section 4 zero-filled and then gzipped; offsets are unchanged, so hdarm reads it
exactly like the real file. Frame records and watch files go in as they are.

Writes BUNDLE_DIR/ with: <pack>.hdp.gz, <rd>/rec_*.bin.gz, <rd>/watch_*.bin, expected.md5
(md5 of the reference decision dump for every frame, for the on-device parity check) and
frames.txt (pack rd frame per line).

usage: python make_bundle.py OUT_DIR PACK_DIR TESTDATA_DIR REF_DIR
"""
import gzip
import hashlib
import os
import struct
import sys

PAIRS = [("a034", "rec_mmm"), ("p002", "rec_cv"), ("p053", "rec_smb3"), ("a057", "rec_z2")]


def main():
    out, packs, td, refs = sys.argv[1:5]
    os.makedirs(out, exist_ok=True)
    lines, md5s = [], []
    for pk, rd in PAIRS:
        d = bytearray(open(os.path.join(packs, pk + ".hdp"), "rb").read())
        off, ln = struct.unpack_from("<II", d, 0x80 + 8 * 4)
        if off + ln > len(d):
            sys.exit(f"{pk}: section 4 ({off}+{ln}) past end of file ({len(d)})")
        d[off:off + ln] = bytes(ln)
        with gzip.open(os.path.join(out, pk + ".hdp.gz"), "wb", compresslevel=6) as g:
            g.write(d)
        print(f"{pk}: {len(d)} bytes, section 4 = {ln} bytes zeroed")
        os.makedirs(os.path.join(out, rd), exist_ok=True)
        for fn in sorted(os.listdir(os.path.join(td, rd))):
            if not (fn.startswith("rec_") and fn.endswith(".bin")):
                continue
            f = fn[4:8]
            wf = os.path.join(td, rd, f"watch_{f}.bin")
            if not os.path.exists(wf):
                continue
            ref = os.path.join(refs, f"{pk}_{f}.ref")
            if not os.path.exists(ref):
                sys.exit(f"missing reference {ref}")
            with gzip.open(os.path.join(out, rd, fn + ".gz"), "wb") as g:
                g.write(open(os.path.join(td, rd, fn), "rb").read())
            open(os.path.join(out, rd, f"watch_{f}.bin"), "wb").write(open(wf, "rb").read())
            md5s.append(f"{hashlib.md5(open(ref, 'rb').read()).hexdigest()}  {pk}_{f}")
            lines.append(f"{pk} {rd} {f}")
    with open(os.path.join(out, "expected.md5"), "w", newline="\n") as fo:
        fo.write("\n".join(md5s) + "\n")
    with open(os.path.join(out, "frames.txt"), "w", newline="\n") as fo:
        fo.write("\n".join(lines) + "\n")
    print(f"{len(lines)} frames")


if __name__ == "__main__":
    main()
