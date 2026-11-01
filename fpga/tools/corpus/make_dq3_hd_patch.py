"""make_dq3_hd_patch.py <rom.nes> <out.ips> [out.nes] : Dragon Warrior III HD pack driver.

The Dragon Warrior III HD pack (corpus a064/a065, "dq3nes-mesen-hdpack-mod" v0.5.1, written
for Mesen) ships a 665-line Lua script, "Dragon Warrior III Delocalized v1.12.lua". Our core has
no Lua, so this script writes the same behaviour as 6502 code and emits it as an IPS that the
pack's <patch> line applies at load. Every change is in PRG bank 30 (the sound bank), which is
byte-identical in Dragon Warrior III (USA) and in Delocalized v1.13 / v1.14, so one IPS fits all
three; the script checks bank 30's sha1 before it touches anything.

What the Lua does, and where it went:
  1. At load it overwrites the music pointer table (bank 30 $8010 + 8*N) for every song it
     replaces with a silence pattern.            -> the same bytes, written here.
  2. A read callback on that table notices the game starting song N and writes the HD audio
     registers $4100-$4105 (loop, stop, volume 70, album 0, track). Short jingles stop the HD
     track and let the original play.            -> SONGHOOK, called from the two
     `sta $06F0` instructions the driver executes exactly when the song changes ($B8F8, $B90F).
  3. Every frame it writes $07C5-$07C9 from game RAM: $07C6 battle backdrop (town / dungeon /
     track / tile), $07C9 night (distance walked $06DF >= 97) or the current HD track,
     $07C7 the tile, $07C8 underworld (track 34 on, 9 or 31 off). The pack's hires.txt
     conditions read those bytes.                -> FRAMEHOOK, entered from bank 30's $8000
     (`jmp $B365`), which the NMI calls once per frame.
  4. Select (short press) toggles the minimap flag $07C5 (1 overworld, 2 underworld).
                                                 -> FRAMEHOOK reads pad 1 itself ($4016,
     3 bits); the game's own read strobes first and double-reads until two reads agree, so a
     read in the NMI only ever costs it one retry.
  Not ported (drawing or input macros, no effect on what the pack's conditions see): the
  blinking minimap marker, the party-status text, the debug text, the controller-2 menu
  macros, the long-press debug toggle.

One deliberate difference: the Lua's read callback stops at $815F, so its own map entry for
song 42 ($8160, "Into the Legend") never fires while the song is still silenced - the ending
would play in silence. Here song 42 starts HD track 42 as the map says.

RAM: $07C5-$07C9 as the pack defines them; $07E0-$07EF private state. The game never touches
$07C5-$07FF (no decoded absolute or indexed access reaches it; a logged play session from boot
to the first town touched $07C0-$07C4 only).
  python make_dq3_hd_patch.py "<...>/Dragon Warrior III (USA).nes" dq3hd.ips [out.nes]
(not -I: capstone is installed per-user). The shipped pack and ROM (Delocalized v1.14) are built
by make_dq3_hd_overlay.py, which calls this module.
"""
import hashlib
import re
import sys
from capstone import Cs, CS_ARCH_MOS65XX, CS_MODE_MOS65XX_6502

BANK = 30
# bank 30 as it is in Dragon Warrior III (USA) and Delocalized v1.13 and v1.14 (measured)
BANK30_SHA1 = "2786dd45d9ccd310732d4775cee55ba932fb0702"

# ---------------------------------------------------------------- the Lua's tables
# (song N -> HD track); a key in the Lua is the table address $8010 + 8*N
LONG = {0: 1, 3: 7, 4: 9, 5: 34, 6: 23, 7: 12, 8: 15, 9: 21, 10: 16, 11: 22, 12: 26, 13: 13,
        14: 31, 15: 5, 16: 10, 17: 25, 18: 40, 19: 11, 24: 41, 25: 42, 26: 39, 27: 27, 39: 1,
        40: 2, 42: 42, 31: 1, 32: 1}
SHORT = {1: 56, 20: 45, 21: 47, 22: 43, 23: 49, 28: 38, 30: 53, 38: 55, 29: 54}
SILENCE = bytes.fromhex("6881698169816981")
NSONGS = 43            # the pointer table ends at $8167 (song 42); the driver reads it only at $B922-$B937
# isInTown / isInDungeon targets in the Lua's precedence order: (x, y, size, $07C6 value)
PLACES = [(0x34, 0x58, 2, 0x0F), (0x23, 0x89, 1, 0x0F), (0x24, 0x8A, 1, 0x0F),   # arenas
          (0xD7, 0x9A, 2, 0x0F), (0x5C, 0x6F, 2, 0x0F),
          (0x66, 0xD8, 1, 0x15),                                                  # solo dungeon
          (0xBE, 0xD1, 1, 0x0E), (0x34, 0xB4, 1, 0x0E), (0x78, 0x92, 1, 0x0E),     # dungeons
          (0x2F, 0x15, 1, 0x0E), (0x30, 0x42, 1, 0x0E),
          (0x9D, 0x93, 1, 0x10), (0x9E, 0x92, 1, 0x11),                           # Jipang, cave
          (0x33, 0xAB, 2, 0x14), (0x43, 0x3A, 2, 0x12)]                           # Baramos, Zoma

EQU = {
    "MAP": 0x07C5, "BACK": 0x07C6, "TILE": 0x07C7, "UNDER": 0x07C8, "NIGHT": 0x07C9,
    "CURTRK": 0x07E0, "CURBGM": 0x07E1, "NOTFIELD": 0x07E2, "BTIMER": 0x07E3,
    "ISUNDER": 0x07E4, "SELTIME": 0x07E5, "PREVSEL": 0x07E6, "CURADDR": 0x07E7,
    "MAGIC": 0x07EF,
    "PX": 0x2A, "PY": 0x2B, "MYTILE": 0x92, "GS3": 0x0581, "BUF": 0x02C0, "TIME": 0x06DF,
    "SONGCUR": 0x06F0, "SNDFRAME": 0xB365,
    "T1": 0x07E8, "T2": 0x07E9,
}

SRC = """
; ---------------------------------------------------------------- once, then on every reset
CHKINIT: lda MAGIC
         cmp #$5A
         beq CI_RTS
         lda #$00
         ldx #$0E
CI_L:    sta CURTRK,x
         dex
         bpl CI_L
         ldx #$04
CI_L2:   sta MAP,x
         dex
         bpl CI_L2
         lda #$5A
         sta MAGIC
CI_RTS:  rts

; ---------------------------------------------------------------- song started (A = 2N)
SONGHOOK: sta SONGCUR
         pha
         jsr CHKINIT
         pla
         pha
         lsr a                  ; N (the asl dropped bit 7; songs end at 42)
         cmp #NSONGS
         bcs SH_DONE
         tax
         inx
         cpx CURADDR            ; currentTrackAddress: same address as last time -> nothing
         beq SH_DONE
         lda LONGMAP-1,x
         beq SH_SHORT
         stx CURADDR
         sta NIGHT              ; the Lua writes the HD track to $07C9
         ldy #$01
         jsr PLAYTRACK
         jmp SH_DONE
SH_SHORT: lda SHORTMAP-1,x
         beq SH_DONE
         stx CURADDR
         lda #$FF
         ldy #$00
         jsr PLAYTRACK
SH_DONE: jsr UWCHK
         pla
         rts

; ---------------------------------------------------------------- playTrack(A, loop=Y)
PLAYTRACK: cmp CURBGM
         beq PT_RTS
         cmp #$FF
         bne PT_NS
         ldx #$02
         stx $4101              ; stop BGM
         jmp PT_GO
PT_NS:   cmp #10                ; the battle theme does not change currentTrack
         beq PT_GO
         sta CURTRK
PT_GO:   sty $4100
         ldx #$00
         stx $4101
         ldx #70
         stx $4102
         ldx #$00
         stx $4104
         sta $4105
         sta CURBGM
PT_RTS:  rts

; ---------------------------------------------------------------- once per frame (NMI)
FRAMEHOOK: jsr CHKINIT
         lda BUF                ; checkBattleStatus
         cmp #$F8
         bne FB1
         lda #$00
         sta NOTFIELD
FB1:     lda GS3
         cmp #$FF
         bne FB2
         lda #$01
         sta NOTFIELD
         lda #$00
         sta BTIMER
FB2:     lda NOTFIELD
         bne FB_NF
         lda #$00
         sta BACK
         sta NIGHT
         lda MYTILE
         sta TILE
         jmp INP
FB_NF:   lda BTIMER
         cmp #10
         bcs FB_BAT
         inc BTIMER
         jmp INP
FB_BAT:  lda TIME
         cmp #97
         bcc FB_DAY
         lda #$01
         sta NIGHT
FB_DAY:  jsr BACKDROP
         bcc INP
         sta BACK
; checkInput runs at inputPolled in the Lua, before the frame's song change and before
; checkUnderworld at endFrame, so the minimap toggle sees last frame's underworld flag
INP:     lda #$01               ; checkInput: Select on pad 1
         sta $4016
         lda #$00
         sta $4016
         lda $4016
         lda $4016
         lda $4016
         and #$03
         beq IN_UP
         lda SELTIME
         cmp #$FF
         beq IN_H1
         inc SELTIME
IN_H1:   lda #$01
         sta PREVSEL
         jmp UW
IN_UP:   lda PREVSEL
         beq UW
         lda SELTIME            ; released
         cmp #40
         bcs IN_RST             ; long press: the Lua's debug toggle, nothing drawn here
         lda MAP
         beq IN_ON
         lda #$00
         sta MAP
         jmp IN_RST
IN_ON:   lda ISUNDER
         beq IN_ON1
         lda #$02
         bne IN_ON2
IN_ON1:  lda #$01
IN_ON2:  sta MAP
IN_RST:  lda #$00
         sta SELTIME
         sta PREVSEL
UW:      jsr UWCHK
         jmp SNDFRAME

; checkUnderworld. The Lua runs it at endFrame, i.e. after a song started in the same frame,
; so SONGHOOK runs it too: $07C8 changes in the frame the song does.
UWCHK:   lda CURTRK
         cmp #34
         bne UW1
         lda #$01
         sta ISUNDER
         sta UNDER
         rts
UW1:     cmp #9
         beq UW0
         cmp #31
         bne UW_RTS
UW0:     lda #$00
         sta ISUNDER
         sta UNDER
UW_RTS:  rts

; ---------------------------------------------------------------- battle backdrop
; C=1, A=value: write it.  C=0: leave $07C6 as it is (the Lua's commented-out tiles).
BACKDROP: ldx #$00
BD_L:    lda PX
         sec
         sbc PLACES,x
         bcc BD_N
         cmp PLACES+2,x
         bcs BD_N
         lda PY
         cmp PLACES+1,x
         bne BD_N
         lda PLACES+3,x
         sec
         rts
BD_N:    inx
         inx
         inx
         inx
         cpx #PLACESLEN
         bne BD_L
         lda CURTRK
         ldx #$00
BD_T:    cmp TRKTAB,x
         beq BD_TF
         inx
         inx
         cpx #TRKLEN
         bne BD_T
         lda MYTILE
         ldx #$00
BD_M:    cmp TILETAB,x
         beq BD_MF
         inx
         inx
         cpx #TILELEN
         bne BD_M
         lda #$0C               ; anything else: cloud
         sec
         rts
BD_TF:   lda TRKTAB+1,x
         sec
         rts
BD_MF:   lda TILETAB+1,x
         cmp #$FF
         beq BD_KEEP
         sec
         rts
BD_KEEP: clc
         rts
"""

TRK = [(22, 0x04), (12, 0x08), (15, 0x09), (21, 0x0A), (25, 0x0B)]
TILES = [(2, 0x01), (3, 0x01), (5, 0x05), (7, 0x06), (4, 0x02), (0x13, 0xFF), (0x0D, 0xFF),
         (0x2C, 0xFF), (0x8F, 0xFF), (1, 0x03), (0x1E, 0x07)]


def tables():
    longmap = bytes(LONG.get(n, 0) for n in range(NSONGS))
    shortmap = bytes(SHORT.get(n, 0) for n in range(NSONGS))
    places = b"".join(bytes(p) for p in PLACES)
    trk = b"".join(bytes(t) for t in TRK)
    tiles = b"".join(bytes(t) for t in TILES)
    return [("LONGMAP", longmap), ("SHORTMAP", shortmap), ("PLACES", places),
            ("TRKTAB", trk), ("TILETAB", tiles)], {"PLACESLEN": len(places), "TRKLEN": len(trk),
                                                   "TILELEN": len(tiles)}

# ---------------------------------------------------------------- a complete 6502 assembler
OPC = {}
def _op(m, **modes):
    for mode, code in modes.items():
        OPC[(m, mode)] = code
for m, base in (("ora", 0x00), ("and", 0x20), ("eor", 0x40), ("adc", 0x60), ("sta", 0x80),
                ("lda", 0xA0), ("cmp", 0xC0), ("sbc", 0xE0)):
    _op(m, indx=base + 0x01, zp=base + 0x05, abs=base + 0x0D, indy=base + 0x11, zpx=base + 0x15,
        absy=base + 0x19, absx=base + 0x1D)
    if m != "sta":
        _op(m, imm=base + 0x09)
for m, base in (("asl", 0x00), ("rol", 0x20), ("lsr", 0x40), ("ror", 0x60)):
    _op(m, zp=base + 0x06, acc=base + 0x0A, abs=base + 0x0E, zpx=base + 0x16, absx=base + 0x1E)
_op("inc", zp=0xE6, abs=0xEE, zpx=0xF6, absx=0xFE)
_op("dec", zp=0xC6, abs=0xCE, zpx=0xD6, absx=0xDE)
_op("ldx", imm=0xA2, zp=0xA6, abs=0xAE, zpy=0xB6, absy=0xBE)
_op("ldy", imm=0xA0, zp=0xA4, abs=0xAC, zpx=0xB4, absx=0xBC)
_op("stx", zp=0x86, abs=0x8E, zpy=0x96)
_op("sty", zp=0x84, abs=0x8C, zpx=0x94)
_op("cpx", imm=0xE0, zp=0xE4, abs=0xEC)
_op("cpy", imm=0xC0, zp=0xC4, abs=0xCC)
_op("bit", zp=0x24, abs=0x2C)
_op("jmp", abs=0x4C, ind=0x6C)
_op("jsr", abs=0x20)
for m, c in (("bpl", 0x10), ("bmi", 0x30), ("bvc", 0x50), ("bvs", 0x70), ("bcc", 0x90),
             ("bcs", 0xB0), ("bne", 0xD0), ("beq", 0xF0)):
    _op(m, rel=c)
for m, c in (("brk", 0x00), ("php", 0x08), ("clc", 0x18), ("plp", 0x28), ("sec", 0x38),
             ("rti", 0x40), ("pha", 0x48), ("cli", 0x58), ("rts", 0x60), ("pla", 0x68),
             ("sei", 0x78), ("dey", 0x88), ("txa", 0x8A), ("tya", 0x98), ("txs", 0x9A),
             ("tay", 0xA8), ("tax", 0xAA), ("clv", 0xB8), ("tsx", 0xBA), ("iny", 0xC8),
             ("dex", 0xCA), ("cld", 0xD8), ("inx", 0xE8), ("nop", 0xEA), ("sed", 0xF8)):
    _op(m, imp=c)
SIZE = {"imp": 1, "acc": 1, "imm": 2, "zp": 2, "zpx": 2, "zpy": 2, "indx": 2, "indy": 2,
        "rel": 2, "abs": 3, "absx": 3, "absy": 3, "ind": 3}


def evaluate(expr, sym, final):
    """sum of terms; returns None in pass 1 when a symbol is not known yet."""
    total = 0
    for sign, term in re.findall(r"([+-]?)\s*([^+\-\s]+)", expr.strip()):
        if term.startswith("$"):
            v = int(term[1:], 16)
        elif term[0].isdigit():
            v = int(term)
        elif term in sym:
            v = sym[term]
        elif not final:
            return None
        else:
            raise SystemExit(f"unknown symbol {term!r}")
        total += -v if sign == "-" else v
    return total


def assemble(src, org, sym, final):
    out = bytearray()
    pc = org
    for raw in src.splitlines():
        line = raw.split(";")[0].rstrip()
        m = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]*):(.*)$", line)
        if m:
            label, line = m.group(1), m.group(2)
            if not final and label in sym and sym[label] != pc:
                raise SystemExit(f"duplicate label {label}")
            sym[label] = pc
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 1)
        mn, op = parts[0].lower(), (parts[1].strip() if len(parts) > 1 else "")
        if mn == ".byte":
            vals = [evaluate(v, sym, final) or 0 for v in op.split(",")]
            out += bytes(v & 0xFF for v in vals)
            pc += len(vals)
            continue
        if op in ("", "a", "A"):
            mode = "acc" if (mn, "acc") in OPC and op else ("imp" if (mn, "imp") in OPC else "acc")
            expr = None
        elif op.startswith("#"):
            mode, expr = "imm", op[1:]
        elif re.match(r"^\(.*,\s*x\)$", op, re.I):
            mode, expr = "indx", op[1:op.index(",")]
        elif re.match(r"^\(.*\)\s*,\s*y$", op, re.I):
            mode, expr = "indy", op[1:op.index(")")]
        elif op.startswith("("):
            mode, expr = "ind", op[1:-1]
        else:
            idx = None
            mm = re.match(r"^(.*),\s*([xy])$", op, re.I)
            if mm:
                expr, idx = mm.group(1), mm.group(2).lower()
            else:
                expr = op
            if (mn, "rel") in OPC:
                mode = "rel"
            else:
                v = evaluate(expr, sym, False)
                zp = "zp" + (idx or "")
                ab = "abs" + (idx or "")
                mode = zp if (v is not None and v < 0x100 and (mn, zp) in OPC) else ab
        if (mn, mode) not in OPC:
            raise SystemExit(f"no opcode for {mn} {mode}: {raw!r}")
        code, n = OPC[(mn, mode)], SIZE[mode]
        if final:
            if n == 1:
                out += bytes([code])
            elif mode == "rel":
                t = evaluate(expr, sym, True)
                d = t - (pc + 2)
                if not -128 <= d <= 127:
                    raise SystemExit(f"branch out of range at {pc:04X}: {raw!r}")
                out += bytes([code, d & 0xFF])
            elif n == 2:
                v = evaluate(expr, sym, True)
                if not 0 <= v <= 0xFF:
                    raise SystemExit(f"operand {v:#x} too big at {pc:04X}: {raw!r}")
                out += bytes([code, v])
            else:
                v = evaluate(expr, sym, True)
                out += bytes([code, v & 0xFF, v >> 8])
        pc += n
    return bytes(out), pc - org


# ---------------------------------------------------------------- the patch
CODE_ORG, CODE_END = 0xBB60, 0xBFD8          # bank 30 erased run ($FF), measured on all three
SITES = [  # (address, original bytes, replacement source)
    (0x8000, "4c65b3", "jmp FRAMEHOOK"),
    (0xB8F8, "8df006", "jsr SONGHOOK"),
    (0xB90F, "8df006", "jsr SONGHOOK"),
]
H = 16


def fofs(addr):
    return H + BANK * 0x4000 + (addr - 0x8000)


def build(rom):
    if rom[:4] != b"NES\x1a" or rom[4] != 0x20 or (rom[6] >> 4 | (rom[7] & 0xF0)) != 1:
        raise SystemExit("not a 512 KB MMC1 Dragon Warrior III ROM")
    bank = rom[fofs(0x8000):fofs(0x8000) + 0x4000]
    sha = hashlib.sha1(bank).hexdigest()
    if sha != BANK30_SHA1:
        raise SystemExit(f"bank 30 sha1 {sha}, expected {BANK30_SHA1} (USA / Delocalized 1.13-1.14)")
    if any(b != 0xFF for b in rom[fofs(CODE_ORG):fofs(CODE_END)]):
        raise SystemExit("bank 30 $BB60-$BFD7 is not erased")
    for org, orig, _ in SITES:
        have = rom[fofs(org):fofs(org) + 3].hex()
        if have != orig:
            raise SystemExit(f"site {org:04X} holds {have}, expected {orig}")
    tabs, lens = tables()
    sym = dict(EQU)
    sym.update(lens)
    sym["NSONGS"] = NSONGS
    for final in (False, True):
        code, n = assemble(SRC, CODE_ORG, sym, final)
        pc = CODE_ORG + n
        tdata = bytearray()
        for name, data in tabs:
            sym[name] = pc
            tdata += data
            pc += len(data)
        if pc > CODE_END:
            raise SystemExit(f"code+tables end at {pc:04X} > {CODE_END:04X}")
        sites = [(org, assemble(src, org, sym, final)[0]) for org, _, src in SITES]
    # nothing in bank 30 may branch or jump into the middle of a replaced instruction
    md = Cs(CS_ARCH_MOS65XX, CS_MODE_MOS65XX_6502)
    md.skipdata = True
    interior = {a for org, _, _ in SITES for a in (org + 1, org + 2)}
    for ins in md.disasm(bytes(bank), 0x8000):
        if ins.mnemonic in ("beq", "bne", "bcc", "bcs", "bpl", "bmi", "bvc", "bvs", "jmp", "jsr"):
            try:
                t = int(ins.op_str, 16)
            except ValueError:
                continue
            if t in interior:
                raise SystemExit(f"{ins.address:04X} {ins.mnemonic} {ins.op_str} lands inside a site")
    out = bytearray(rom)
    recs = []
    blob = code + bytes(tdata)
    out[fofs(CODE_ORG):fofs(CODE_ORG) + len(blob)] = blob
    recs.append((fofs(CODE_ORG), blob))
    for org, b in sites:
        out[fofs(org):fofs(org) + 3] = b
        recs.append((fofs(org), b))
    for n in sorted(LONG):
        a = 0x8010 + 8 * n
        out[fofs(a):fofs(a) + 8] = SILENCE
        recs.append((fofs(a), SILENCE))
    return out, recs, sym, len(blob)


def ips(recs):
    data = bytearray(b"PATCH")
    for off, b in sorted(recs):
        if off == 0x454F46:
            raise SystemExit("record at the EOF offset")
        data += off.to_bytes(3, "big") + len(b).to_bytes(2, "big") + b
    return bytes(data + b"EOF")


def main():
    rom = open(sys.argv[1], "rb").read()
    out, recs, sym, nblob = build(rom)
    open(sys.argv[2], "wb").write(ips(recs))
    if len(sys.argv) > 3:
        open(sys.argv[3], "wb").write(out)
    for k in ("CHKINIT", "SONGHOOK", "PLAYTRACK", "FRAMEHOOK", "BACKDROP", "LONGMAP", "SHORTMAP",
              "PLACES", "TRKTAB", "TILETAB"):
        print(f"  {k:9s} ${sym[k]:04X}")
    print(f"  code+tables {nblob} bytes at ${CODE_ORG:04X}-${CODE_ORG + nblob - 1:04X} "
          f"(room to ${CODE_END - 1:04X})")
    print(f"  source sha1 {hashlib.sha1(rom).hexdigest().upper()}  patched sha1 "
          f"{hashlib.sha1(out).hexdigest().upper()}")


if __name__ == "__main__":
    main()
