"""test_dq3_hd_patch.py <rom.nes> <pack lua> [frames] [seed] : differential test of the
Dragon Warrior III HD patch against the pack's own Lua script.

Builds the patch in memory (make_dq3_hd_patch.build), runs its bank-30 code on a 6502 emulator
(py65) and the pack's original "Dragon Warrior III Delocalized v1.12.lua" in a Lua 5.4 runtime
(lupa) with a fake `emu` API, feeds both the same randomized game states frame by frame, and
compares the five pack bytes $07C5-$07C9 and the HD audio register writes $4100-$4106.

Event order per frame, as on the console (Mesen's frame runs startFrame .. endFrame; the NMI that
calls the sound driver comes after endFrame, so it opens the next period):
    NMI       -> FRAMEHOOK (patch)        | Lua: (nothing)
    startFrame                            | Lua: checkBattleStatus
    input poll                            | Lua: checkInput
    main loop -> song request: SONGHOOK   | Lua: read callback on the pointer table
    endFrame                              | Lua: checkUnderworld; compare here
One deliberate difference: song 42 ($8160) is outside the Lua's callback range, so the Lua never
plays it; the patch does. It is checked separately.
Needs py65 and lupa (pip install --target <dir> py65 lupa; put <dir> on PYTHONPATH).
"""
import os
import random
import sys

from lupa.lua54 import LuaRuntime
from py65.devices.mpu6502 import MPU
from py65.memory import ObservableMemory

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import make_dq3_hd_patch as P  # noqa: E402

PACK = (0x7C5, 0x7C6, 0x7C7, 0x7C8, 0x7C9)
INPUTS = {"tile": 0x92, "gs3": 0x581, "buf": 0x2C0, "time": 0x6DF, "px": 0x2A, "py": 0x2B}
SENT = 0xFFF0            # return sentinel for jsr-style calls


class Six502:
    def __init__(self, rom):
        out, _, sym, _ = P.build(rom)
        self.sym = sym
        self.mem = ObservableMemory()
        bank = out[P.fofs(0x8000):P.fofs(0x8000) + 0x4000]
        for i, b in enumerate(bank):
            self.mem[0x8000 + i] = b
        self.writes = []
        self.select = False
        self.pad_idx = 0
        self.strobe = 0
        self.mem.subscribe_to_write(range(0x4100, 0x4107), self._w41)
        self.mem.subscribe_to_write([0x4016], self._w4016)
        self.mem.subscribe_to_read([0x4016], self._r4016)
        self.cpu = MPU(memory=self.mem)

    def _w41(self, addr, val):
        self.writes.append("%04X=%02X" % (addr, val))

    def _w4016(self, addr, val):
        if self.strobe and not (val & 1):
            self.pad_idx = 0
        self.strobe = val & 1

    def _r4016(self, addr):
        bits = [0, 0, 1 if self.select else 0, 0, 0, 0, 0, 0]  # A B Select Start U D L R
        v = bits[self.pad_idx] if self.pad_idx < 8 else 1
        self.pad_idx += 1
        return 0x40 | v

    def run(self, pc, stop, a=0, x=0x55, y=0x66):
        c = self.cpu
        c.sp = 0xFD
        r = SENT - 1
        self.mem[0x100 + c.sp] = r >> 8
        self.mem[0x100 + c.sp - 1] = r & 0xFF
        c.sp -= 2
        c.pc, c.a, c.x, c.y = pc, a, x, y
        for _ in range(20000):
            if c.pc in stop:
                return c.pc
            c.step()
        raise SystemExit(f"runaway at {c.pc:04X}")

    def frame(self):
        if self.run(self.sym["FRAMEHOOK"], (0xB365, SENT)) != 0xB365:
            raise SystemExit("FRAMEHOOK returned instead of jumping to $B365")

    def song(self, n):
        a = (2 * n) & 0xFF
        self.run(self.sym["SONGHOOK"], (SENT,), a=a)
        if self.cpu.a != a or self.mem[0x6F0] != a:
            raise SystemExit(f"SONGHOOK broke A or $06F0 for song {n}")


class LuaSide:
    def __init__(self, path):
        self.L = LuaRuntime(unpack_returned_tuples=True)
        self.ram = {}
        self.writes = []
        self.prg = {}
        self.cb = {}
        self.mcb = None
        self.select = False
        g = self.L.globals()
        emu = self.L.table()
        emu.memType = self.L.table(nesDebug=1, nesMemory=2, nesPrgRom=3)
        emu.eventType = self.L.table(inputPolled=1, endFrame=2, startFrame=3)
        emu.callbackType = self.L.table(read=1)
        emu.cpuType = self.L.table(nes=1)
        emu.drawSurface = self.L.table(scriptHud=1, consoleScreen=2)
        emu.read = lambda a, mt=None, s=None: self.ram.get(int(a), 0)
        emu.readWord = lambda a, mt=None, s=None: (self.ram.get(int(a), 0)
                                                   | self.ram.get(int(a) + 1, 0) << 8)
        emu.write = self._write
        emu.getInput = lambda p: self.L.table(select=self.select) if int(p) == 0 else self.L.table()
        emu.addEventCallback = lambda fn, t: self.cb.setdefault(t, []).append(fn)
        emu.addMemoryCallback = self._addm
        for name in ("log", "drawString", "drawRectangle", "selectDrawSurface", "drawPixel"):
            emu[name] = lambda *a: None
        g.emu = emu
        src = open(path, encoding="utf-8").read()
        self.L.execute(src)

    def _write(self, a, v, mt=None):
        a, v = int(a), int(v)
        if mt == 3:
            self.prg[a] = v
        elif 0x4100 <= a <= 0x4106:
            self.writes.append("%04X=%02X" % (a, v))
        else:
            self.ram[a] = v

    def _addm(self, fn, t, lo, hi, *rest):
        self.mcb = (fn, int(lo), int(hi))

    def fire(self, t):
        for fn in self.cb.get(t, []):
            fn()

    def song(self, n):
        fn, lo, hi = self.mcb
        base = 0x8010 + 8 * n                     # the driver reads +7 .. +0
        for k in range(7, -1, -1):
            # the Lua registered PRG-ROM offsets ($78010-$7815F); compare in that space
            if lo <= 0x70000 + base + k <= hi:
                fn(base + k, 0)


def main():
    rom = open(sys.argv[1], "rb").read()
    lua_path = sys.argv[2]
    frames = int(sys.argv[3]) if len(sys.argv) > 3 else 200000
    rng = random.Random(int(sys.argv[4]) if len(sys.argv) > 4 else 1)
    six = Six502(rom)
    lua = LuaSide(lua_path)

    # the silence the Lua writes at load must equal the bytes the patch writes
    for n in P.LONG:
        for j in range(8):
            a = 0x78010 + 8 * n + j
            if lua.prg.get(a) != P.SILENCE[j]:
                raise SystemExit(f"silence mismatch at song {n}")
    if len(lua.prg) != 8 * len(P.LONG):
        raise SystemExit("the Lua silences a different song set")

    st = {"tile": 2, "gs3": 0, "buf": 0xF8, "time": 0, "px": 0x80, "py": 0x80}
    mode = "field"
    sel_left = 0
    sel_gap = 30
    song = None
    stats = {"songs": 0, "battles": 0, "toggles": 0, "back": set(), "night": 0, "under": 0}
    for f in range(frames):
        # ---- this period's game state
        if rng.random() < 0.05:
            st["tile"] = rng.choice([0, 1, 2, 3, 4, 5, 7, 0x0D, 0x13, 0x1E, 0x2C, 0x8F, 0x50, 0xFF])
        if mode == "field" and rng.random() < 0.004:
            mode, stats["battles"] = "enter", stats["battles"] + 1
        elif mode == "battle" and rng.random() < 0.01:
            mode = "field"
        if mode == "enter":
            st["gs3"], st["buf"], mode = 0xFF, 0x00, "battle"
        elif mode == "battle":
            st["gs3"] = rng.choice([0x00, 0x12, 0x1E, 0x28])
            st["buf"] = rng.choice([0x00, 0x20, 0x98])
        else:
            st["gs3"] = rng.choice([0x00, 0x12, 0x1E])
            st["buf"] = 0xF8 if rng.random() < 0.8 else 0x98
        if rng.random() < 0.01:                 # sit on and around the night threshold (97)
            st["time"] = rng.choice([0, 50, 95, 96, 96, 97, 97, 98, 120, 200, 255])
        elif rng.random() < 0.3:
            st["time"] = max(0, min(255, st["time"] + rng.choice([-2, -1, 1, 2])))
        if rng.random() < 0.02:
            if rng.random() < 0.6:
                x, y, size, _ = rng.choice(P.PLACES)
                st["px"] = (x + rng.choice([-1, 0, 0, 1, size - 1, size])) & 0xFF
                st["py"] = y if rng.random() < 0.8 else (y + 1) & 0xFF
            else:
                st["px"], st["py"] = rng.randrange(256), rng.randrange(256)
        if sel_left > 0:
            sel_left -= 1
            pressed = True
        elif sel_gap > 0:
            sel_gap -= 1
            pressed = False
        else:
            sel_left = rng.choice([1, 3, 8, 20, 38, 39, 40, 41, 60, 260, 300])
            sel_gap = rng.randrange(1, 90)
            pressed = False
        six.select = lua.select = pressed
        for k, a in INPUTS.items():
            six.mem[a] = st[k]
            lua.ram[a] = st[k]
        # ---- NMI, startFrame, input, main loop, endFrame
        six.writes, lua.writes = [], []
        six.frame()
        lua.fire(3)
        lua.fire(1)
        if rng.random() < 0.02:
            n = rng.choice([x for x in range(48) if x != 42])
            if n != song:                       # the driver only stores a CHANGED song
                song = n
                stats["songs"] += 1
                six.song(n)
                lua.song(n)
        lua.fire(2)
        mine = [six.mem[a] for a in PACK]
        theirs = [lua.ram.get(a, 0) for a in PACK]
        if mine != theirs or six.writes != lua.writes:
            raise SystemExit(f"frame {f}: patch {['%02X' % v for v in mine]} {six.writes}\n"
                             f"          lua   {['%02X' % v for v in theirs]} {lua.writes}\n"
                             f"          state {st} select={pressed} song={song}")
        if mine[1]:
            stats["back"].add(mine[1])
        stats["night"] += mine[4] == 1 and mine[1] != 0
        stats["under"] += mine[3]
        stats["toggles"] += 0
    print(f"  {frames} frames identical: {stats['songs']} song changes, {stats['battles']} battles,"
          f" backdrops seen {sorted('%02X' % b for b in stats['back'])},"
          f" night-battle frames {stats['night']}, underworld frames {stats['under']}")

    # song 42: the Lua never sees it (outside its callback range); the patch plays it
    six.writes = []
    six.song(41 if song == 42 else 42)
    six.song(42) if six.mem[0x6F0] != 84 else None
    if "4105=2A" not in six.writes or six.mem[0x7C9] != 0x2A:
        raise SystemExit(f"song 42 did not start HD track 42: {six.writes}")
    print("  song 42 (Into the Legend) starts HD track 42")


if __name__ == "__main__":
    main()
