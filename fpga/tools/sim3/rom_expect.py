"""Write what the core must end up with for a ROM and a pack: the ROM patched by the pack's
<patch> the core picks for it (rommatch.core_lookup over the section-14 keys the converter
writes: the file's SHA1, then its iNES 1.0 form's), built from the form that matched
(rompatch.apply), or the ROM unchanged when none matches or the patch is refused. Prints the
outcome.

    python -I rom_expect.py pack_dir rom.nes out.bin [--romindex PATH|none]
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import hdpack_model as M  # noqa: E402
import rommatch  # noqa: E402
import rompatch  # noqa: E402
from hdp3_convert import DEFAULT_ROMINDEX  # noqa: E402

args = sys.argv[1:]
index_p = DEFAULT_ROMINDEX
if "--romindex" in args:
    i = args.index("--romindex")
    index_p = args[i + 1]
    del args[i:i + 2]
pack_dir, rom_p, out_p = args[:3]
index = rommatch.load_index(index_p) if index_p != "none" and os.path.isfile(index_p) else None
p = M.load(pack_dir)
rom = open(rom_p, "rb").read()
keys = rommatch.section_keys(p.patches, p.patches_md5, index)
hit = rommatch.core_lookup(rom, set(keys))
out, what = rom, "no match"
if hit:
    src, sha, label = hit
    name = keys[sha]
    try:
        out, what = rompatch.apply(src, p.read(name)), f"patched by {name}{label}"
    except rompatch.PatchError as e:
        what = f"refused: {e}"
open(out_p, "wb").write(out)
print(f"{what}: {len(rom)} -> {len(out)} bytes")
