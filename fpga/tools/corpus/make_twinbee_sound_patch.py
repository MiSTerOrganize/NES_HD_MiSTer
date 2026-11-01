"""make_twinbee_sound_patch.py <rom.nes> <out.ips> [out.nes] : assemble the TwinBee HD-audio hook
and write it as an IPS against the ROM file as given (header untouched).

TwinBee HD pack a048 names tbs.ips in its <patch> line but does not ship it; this script writes
it from scratch (2026-10-29). The overlay Z:/NES_HDPack_work/x/zz_var/tbsound_a048 holds the
result plus a hires.txt that differs from a048's in three ways: the <patch> line is keyed to the
No-Intro ROM (632B2FCC...) as well as the pack author's mapper-3 header form (A1C47B35...), the
two <bgm> lines that need a loop point carry one (twinbee_loop_points.py), and the
<bgm>0,0,twin.ogg line is dropped (that file is not in the pack and nothing requests track 0).
  python -I make_twinbee_sound_patch.py "<...>/2 Japan/TwinBee (Japan) (En).nes" tbs.ips
Verified in Mesen 2 with tools/mesen2/tblog.lua (requests, $4015 and $41xx writes, mute mask).

What it does to the game (the sound driver is otherwise untouched; every request is still
processed by the game exactly as before, so all its state - $48, $FA, $FB, $4A, chains,
priorities - stays original):
  $EEF5  jsr HOOK ; nop      (was lda $27 ; and #$3f - the point every ACCEPTED start AND stop
                              request passes, after the channel's caches were reset)
  HOOK   pulse 1 track 26/31 -> HD SFX 26/31, pulse 1 muted ($4015) while it plays
         pulse 1 any other   -> pulse 1 unmuted
         pulse 2 track 24/27/32 -> HD BGM (looped), pulse 2 + triangle muted
         pulse 2 track 29    -> nothing (the boss-warning chain; the BGM started on 32 goes on)
         pulse 2 any other   -> HD BGM stopped, pulse 2 + triangle unmuted
         triangle / noise    -> nothing
         Unmuting sets the channel's period cache $08,x to $FF so its next note rewrites
         $4003/$4007 (a re-enabled channel stays silent until that write).
  $9358  jsr PON ; nop ; nop (was jsr $ee67 ; inc $bf - the pause) -> HD BGM paused too
  $9362  jmp UNP             (was lda #0 ; sta $bf ; rts - the unpause) -> HD BGM resumed
  $9429  lda #0 ; sta $0e ; sta $07c2 ; jmp UNP   (same three stores, $bf via UNP)
Code goes only in regions proven unused (tb_reach/tb_islands + coverage): the Konami build tag
$8000-$8010, dead routines $8624, $CC78, $CD09, $F1C4, and the erased tail $FFDF-$FFF9.
Mute state lives in $0140 (bit0 p1, bit1 p2, bit2 triangle); RAM is cleared at reset.
"""
import hashlib, sys
from capstone import Cs, CS_ARCH_MOS65XX, CS_MODE_MOS65XX_6502

OPS = {  # (mnemonic, mode) -> opcode
    ("lda", "imm"): 0xA9, ("lda", "zp"): 0xA5, ("lda", "abs"): 0xAD,
    ("sta", "zp"): 0x85, ("sta", "abs"): 0x8D, ("sta", "zpx"): 0x95,
    ("ldy", "imm"): 0xA0, ("sty", "abs"): 0x8C, ("iny", "imp"): 0xC8, ("tya", "imp"): 0x98,
    ("cpx", "imm"): 0xE0, ("cmp", "imm"): 0xC9, ("and", "imm"): 0x29, ("and", "abs"): 0x2D,
    ("ora", "abs"): 0x0D, ("eor", "imm"): 0x49, ("inc", "zp"): 0xE6,
    ("beq", "rel"): 0xF0, ("bne", "rel"): 0xD0, ("jmp", "abs"): 0x4C, ("jsr", "abs"): 0x20,
    ("rts", "imp"): 0x60, ("nop", "imp"): 0xEA,
}
SIZE = {"imp": 1, "imm": 2, "zp": 2, "zpx": 2, "rel": 2, "abs": 3}

# region start, capacity, source. Labels are global across regions.
REGIONS = [
    (0xCD09, 57, """
HOOK:  lda $27
       and #$3f
       cpx #$10
       beq P1
       cpx #$21
       bne RTSD
       cmp #29
       beq RTSD
       jmp P2
P1:    cmp #26
       beq SFXJ
       cmp #31
       beq SFXJ
       ldy #$0E
UNM:   lda #$FF
       sta $08,x
       tya
       and $0140
SET:   sta $0140
       eor #$0F
       sta $4015
       lda $27
       and #$3f
RTSD:  rts
SFXJ:  jmp SFX
"""),
    (0xFFDF, 27, """
P2:    cmp #24
       beq BGMF
       cmp #27
       beq BGMF
       cmp #32
       beq BGMF
       lda #$02
       sta $4101
       ldy #$09
       jmp UNM
BGMF:  jmp BGM
"""),
    (0x8000, 17, """
BGM:   ldy #$00
       sty $4101
       iny
       sty $4100
       sta $4105
       lda #$06
       jmp MUTE
"""),
    (0xF1C4, 14, """
SFX:   sta $4106
       lda #$01
MUTE:  ora $0140
       jmp SET
"""),
    (0x8624, 14, """
PON:   jsr $EE67
       inc $bf
       lda #$01
       sta $4101
       rts
"""),
    (0xCC78, 10, """
UNP:   lda #$00
       sta $bf
       sta $4101
       rts
"""),
]
# patch site, original bytes (checked), replacement source
SITES = [
    (0xEEF5, "a527293f", "jsr HOOK\n nop"),
    (0x9358, "2067eee6bf", "jsr PON\n nop\n nop"),
    (0x9362, "a90085", "jmp UNP"),
    (0x9429, "a900850e85bf8dc20760", "lda #$00\n sta $0e\n sta $07c2\n jmp UNP"),
]

def parse(line):
    line = line.split(";")[0].strip()
    label = None
    if ":" in line:
        label, line = line.split(":", 1); label = label.strip(); line = line.strip()
    if not line: return label, None, None, None
    parts = line.split(None, 1); m = parts[0].lower(); op = parts[1].strip() if len(parts) > 1 else ""
    if not op: return label, m, "imp", None
    if op.startswith("#"): return label, m, "imm", op[1:]
    if op.lower().endswith(",x"): return label, m, "zpx", op[:-2]
    if m in ("beq", "bne"): return label, m, "rel", op
    v = op
    if v.startswith("$") and len(v) <= 3 and m != "jmp" and m != "jsr": return label, m, "zp", v
    return label, m, "abs", v

def val(s, labels):
    s = s.strip()
    if s.startswith("$"): return int(s[1:], 16)
    if s[0].isdigit(): return int(s)
    return labels[s]

def assemble(src, org, labels, final):
    out = bytearray(); pc = org
    for raw in src.strip().splitlines():
        label, m, mode, op = parse(raw)
        if label: labels[label] = pc
        if m is None: continue
        if (m, mode) not in OPS: raise SystemExit(f"no opcode for {m} {mode}: {raw!r}")
        code = OPS[(m, mode)]; n = SIZE[mode]
        if final:
            if mode == "imp": out += bytes([code])
            elif mode == "rel":
                t = val(op, labels); d = t - (pc + 2)
                if not -128 <= d <= 127: raise SystemExit(f"branch out of range at {pc:04x}: {raw!r}")
                out += bytes([code, d & 0xFF])
            elif n == 2:
                v = val(op, labels)
                if v > 0xFF: raise SystemExit(f"operand too big at {pc:04x}: {raw!r}")
                out += bytes([code, v])
            else:
                v = val(op, labels); out += bytes([code, v & 0xFF, v >> 8])
        pc += n
    return out, pc - org

def main():
    rom = bytearray(open(sys.argv[1], "rb").read())
    if rom[:4] != b"NES\x1a" or rom[4] != 2: raise SystemExit("not the 32 KB TwinBee ROM")
    H = 16; prg = lambda a: H + a - 0x8000
    labels = {}
    for final in (False, True):            # pass 1 sizes/labels, pass 2 bytes
        blobs = []
        for org, cap, src in REGIONS:
            b, n = assemble(src, org, labels, final)
            if n > cap: raise SystemExit(f"region {org:04x}: {n} bytes > {cap}")
            blobs.append((org, cap, b, n))
        sites = []
        for org, orig, src in SITES:
            b, n = assemble(src, org, labels, final)
            if n != len(bytes.fromhex(orig)) and final and org != 0x9362:
                raise SystemExit(f"site {org:04x}: {n} bytes replace {len(orig)//2}")
            sites.append((org, orig, b, n))
    # the dead regions must still hold what was analysed (no earlier patch in them)
    expect = {0xCD09: "a5db0848", 0xFFDF: "ffffffff", 0x8000: "52433830", 0xF1C4: "a529c53e",
              0x8624: "a9f4a200", 0xCC78: "85e084e1"}
    for org, cap, b, n in blobs:
        have = rom[prg(org):prg(org) + 4].hex()
        if have != expect[org]: raise SystemExit(f"region {org:04x} holds {have}, expected {expect[org]}")
    for org, orig, b, n in sites:
        have = rom[prg(org):prg(org) + len(orig) // 2].hex()
        if have != orig: raise SystemExit(f"site {org:04x} holds {have}, expected {orig}")
    # no instruction in the ROM may branch/jump INTO the interior of a replaced site
    md = Cs(CS_ARCH_MOS65XX, CS_MODE_MOS65XX_6502); md.skipdata = True
    body = bytes(rom[H:H + 0x8000])
    interior = set()
    for org, orig, b, n in sites:
        interior |= set(range(org + 1, org + len(orig) // 2))
    for i in md.disasm(body, 0x8000):
        if i.mnemonic in ("beq", "bne", "bcc", "bcs", "bpl", "bmi", "bvc", "bvs", "jmp", "jsr"):
            try: t = int(i.op_str, 16)
            except ValueError: continue
            if t in interior: print(f"  note: {i.address:04x} {i.mnemonic} {i.op_str} lands inside a site")
    out = bytearray(rom)
    records = []
    for org, cap, b, n in blobs + [(o, len(orig) // 2, bb, nn) for o, orig, bb, nn in sites]:
        out[prg(org):prg(org) + len(b)] = b
        records.append((prg(org), bytes(b)))
    ips = bytearray(b"PATCH")
    for off, data in sorted(records):
        ips += off.to_bytes(3, "big") + len(data).to_bytes(2, "big") + data
    ips += b"EOF"
    open(sys.argv[2], "wb").write(ips)
    if len(sys.argv) > 3: open(sys.argv[3], "wb").write(out)
    for org, cap, b, n in blobs: print(f"region {org:04x}: {n:2d}/{cap} bytes  {b.hex()}")
    for org, orig, b, n in sites: print(f"site   {org:04x}: {orig} -> {b.hex()}")
    print("labels", {k: f"{v:04x}" for k, v in labels.items()})
    print(f"source sha1 {hashlib.sha1(rom).hexdigest().upper()}  patched sha1 "
          f"{hashlib.sha1(out).hexdigest().upper()}  ips {len(ips)} bytes")

main()
