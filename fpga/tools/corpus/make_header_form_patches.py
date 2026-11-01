"""make_header_form_patches.py [x-root] [--apply] - a <patch> whose hash is a library ROM with a
DIFFERENT header (the pack author's dump set header flags the No-Intro file does not).

A BPS patch checks the CRC of the exact source file, so it can never apply to the No-Intro
file - not in Mesen, not in the core. This writes an equivalent IPS for the library file: the
author's patch is applied to the library data under the author's header (the form its hash
names, rebuilt and checked by SHA1), and the IPS records every byte that changes AFTER the
16-byte header - the library header is kept, so the core configures the cart from the No-Intro
header exactly as for the unpatched game. Each overlay gets that IPS plus a hires.txt = the
base hires.txt with one more <patch> line keyed to the library file's SHA1.

Each entry is explicit (which line, which ROM, which header bytes, the patch file's MD5), so it
can never apply to a pack it was not written for. Dry run unless --apply.
"""
import hashlib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import rompatch  # noqa: E402

LIB = "Z:/MiSTer_Organize/RomRoot/MiSTer_Console/MiSTer_Console/games/NES"
FIXES = [
    # Super Mario Bros. 2 NEA music (LiQuiDz collection a105/_inner13, overlays nea_smb2_doki
    # and nea_smb2_remix): NEA-smb2.bps names D9F36F09... = "Super Mario Bros. 2 (USA)
    # (Rev 1).nes" with header byte 6 = 0x41 (No-Intro 0x40) and bytes 7-15 zero.
    dict(base="a105/_inner13", overlays=["zz_var/nea_smb2_doki", "zz_var/nea_smb2_remix"],
         rom="1 NES/1 USA/Super Mario Bros. 2 (USA) (Rev 1).nes",
         header={6: 0x41, 7: 0, 8: 0, 9: 0, 10: 0, 11: 0, 12: 0, 13: 0, 14: 0, 15: 0},
         line_hash="D9F36F09B863ACC8DE374EA886ABB146959078B3",
         patch="NEA-smb2.bps", patch_md5="bc7e609850b78e81f58fba62a5c07f58",
         out="NEA-smb2 (No-Intro header).ips"),
]


def ips(src, dst):
    """IPS turning src into dst (same size), header bytes 0-15 excluded."""
    assert len(src) == len(dst)
    out, i = bytearray(b"PATCH"), 16
    while i < len(dst):
        if src[i] == dst[i]:
            i += 1
            continue
        j = i
        while j < len(dst) and j - i < 0xFFFF and (src[j] != dst[j] or (
                j + 1 < len(dst) and src[j + 1] != dst[j + 1] and j + 2 - i < 0xFFFF)):
            j += 1
        if i == 0x454F46:              # "EOF" as an offset would end the patch early
            i -= 1
        out += i.to_bytes(3, "big") + (j - i).to_bytes(2, "big") + dst[i:j]
        i = j
    return bytes(out + b"EOF")


def main():
    x = next((a for a in sys.argv[1:] if not a.startswith("--")), "Z:/NES_HDPack_work/x")
    apply_ = "--apply" in sys.argv
    bad = 0
    for fx in FIXES:
        base = os.path.join(x, fx["base"])
        rom = open(os.path.join(LIB, fx["rom"]), "rb").read()
        lib_sha = hashlib.sha1(rom).hexdigest().upper()
        author = bytearray(rom)
        for k, v in fx["header"].items():
            author[k] = v
        if hashlib.sha1(author).hexdigest().upper() != fx["line_hash"]:
            print(f"REFUSED {fx['base']}: rebuilt author header does not hash to {fx['line_hash']}")
            bad += 1
            continue
        pdata = open(os.path.join(base, fx["patch"]), "rb").read()
        if hashlib.md5(pdata).hexdigest() != fx["patch_md5"]:
            print(f"REFUSED {fx['base']}: {fx['patch']} is not the file this entry was written for")
            bad += 1
            continue
        patched = rompatch.apply(bytes(author), pdata)
        want = rom[:16] + patched[16:]
        lips = ips(rom, want)
        if rompatch.apply(rom, lips) != want:
            print(f"REFUSED {fx['base']}: the IPS does not reproduce the patched ROM")
            bad += 1
            continue
        raw = open(os.path.join(base, "hires.txt"), "rb").read()
        nl = b"\r\n" if b"\r\n" in raw else b"\n"
        tag = f"<patch>{fx['patch']},{fx['line_hash']}".encode()
        if tag.lower() not in raw.lower():
            print(f"REFUSED {fx['base']}: hires.txt has no line {tag.decode()}")
            bad += 1
            continue
        i = raw.lower().index(tag.lower())
        j = raw.index(b"\n", i) + 1
        hires = raw[:j] + f"<patch>{fx['out']},{lib_sha}".encode() + nl + raw[j:]
        diff = sum(1 for a, b in zip(rom, want) if a != b)
        for ov in fx["overlays"]:
            od = os.path.join(x, ov)
            print(f"{'WRITE' if apply_ else 'would write'} {ov}: {fx['out']} ({len(lips)} bytes, "
                  f"{diff} ROM bytes changed, patched sha1 {hashlib.sha1(want).hexdigest()[:12]}) "
                  f"+ hires.txt with <patch> keyed {lib_sha[:12]}")
            if apply_:
                open(os.path.join(od, fx["out"]), "wb").write(lips)
                open(os.path.join(od, "hires.txt"), "wb").write(hires)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
