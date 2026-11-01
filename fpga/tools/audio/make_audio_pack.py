"""Append a synthetic section 15 (tb_audio_run's) to a small pack, for the loader window test.

    python tools/audio/make_audio_pack.py BASE.hdp OUT.hdp [seed]

The base must carry no audio. The section goes at the end, 64-byte aligned, and header 0xF8/0xFC
(section 15) and 0x20 (file size) are updated. Prints `MAXB=... MAXT=...`: a main-window end
inside the audio stream data (past the section's header and entry table, as the converter
guarantees) and a MAX_TOTAL just above the file, for a loader build that exercises the overflow
window and the size limit with a small file.
"""
import os
import random
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import tb_audio_run as T


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    base = bytearray(open(sys.argv[1], "rb").read())
    seed = int(sys.argv[3]) if len(sys.argv) > 3 else 1
    if base[:4] != b"NHDP":
        print("not a pack")
        return 1
    if struct.unpack_from("<I", base, 0xFC)[0]:
        print("base pack already carries audio")
        return 1
    sec = T.build_pack(random.Random(seed))
    data_off = struct.unpack_from("<I", sec, 8)[0]
    base += bytes((-len(base)) & 63)
    off = len(base)
    base += sec
    # five bytes past the section: the file ends mid-qword, so the loader's final partial-qword
    # flush lands in the overflow window
    base += b"\x5a\xa5\x3c\xc3\x99"
    struct.pack_into("<II", base, 0xF8, off, len(sec))
    struct.pack_into("<I", base, 0x20, len(base))
    open(sys.argv[2], "wb").write(base)
    maxb = off + data_off + 128
    maxt = (len(base) + 4096) & ~4095
    assert maxb % 64 == 0 and maxb < len(base) <= maxt
    print("MAXB=%d MAXT=%d" % (maxb, maxt))
    return 0


sys.exit(main())
