"""Write a copy of a format-3 pack whose FRAME memory conditions reach the paths no recorded frame
does, so the hd3_resolve test can see them:

  - no corpus fixture pack (a034, p053, p002, a057) has a frame-class two-slot memoryCheck, so
    every 4th frame memoryCheckConstant (ci % 4 == 0) becomes a memoryCheck comparing slot A with
    another watched slot B = (A + 1) % nwatched;
  - the masked frame conditions in a034/p002 never change a result on the recorded frames, so
    every 4th one (ci % 4 == 1) with mask 0xFF gets mask 0x0F.

q1 holds slot A in byte 0 and, for memoryCheck, slot B in byte 1 (for memoryCheckConstant byte 1
is the constant): hdref.eval_cond and hd3_resolve read the same layout. resolve_golden.py reads the
same modified pack. The copy is a test fixture, never a pack to ship.

usage: python make_mem_frame.py <in.hdp> <out.hdp>
"""
import os
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import hdref  # noqa: E402

MEM_CHECK, MEM_CONST = 0, 1


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    data = bytearray(open(sys.argv[1], "rb").read())
    h = hdref.Hdp3(bytes(data))
    if h.nwatched < 2:
        sys.exit("pack watches fewer than 2 addresses - cannot make a two-slot check")
    base = h.s(2)
    two_slot = masked = 0
    for ci in range(h.nconds):
        o = base + 32 * ci
        q0, q1 = struct.unpack_from("<QQ", data, o)
        if not (q0 >> 11) & 1 or q0 & 0xFF != MEM_CONST:
            continue
        if ci % 4 == 0:
            a = q1 & 0xFF
            b = (a + 1) % h.nwatched
            struct.pack_into("<QQ", data, o, (q0 & ~0xFF) | MEM_CHECK, (q1 & ~0xFF00) | (b << 8))
            two_slot += 1
        elif ci % 4 == 1 and (q0 >> 16) & 0xFF == 0xFF:
            struct.pack_into("<Q", data, o, (q0 & ~(0xFF << 16)) | (0x0F << 16))
            masked += 1
    if not two_slot or not masked:
        sys.exit(f"nothing to change (two-slot {two_slot}, masked {masked})")
    open(sys.argv[2], "wb").write(data)
    print(f"{sys.argv[2]}: {two_slot} conditions made two-slot memoryCheck, {masked} given mask 0x0F")
    return 0


if __name__ == "__main__":
    sys.exit(main())
