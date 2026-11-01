"""Run hd3_audio (tools/sim3/tb_audio) against the reference model hdaudio.Device.

    python tools/audio/tb_audio_run.py [--exe tb.exe] [--win BYTES] [--seed N] [--frames N]
                                       [--alt] [--random] [--keep DIR]

A synthetic section 15 is built with hdaudio's own encoder (short streams, so ends, loops and
restarts all happen within a few thousand frames), placed at file offset OFF in a memory
image, and a script of register writes, reads and NES samples is played against both the RTL
and the model. Every 48 kHz frame and every register read must agree exactly. --win puts the
overflow-window boundary inside the stream data so the hi address path is exercised.
Exit 0 = identical.
"""
import argparse, os, random, struct, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import hdaudio as H

ROOT = os.path.dirname(os.path.dirname(HERE))
OFF = 0x2000
RESET_DELAYS = list(range(16))                   # --reset-mid: clk_f from a tick's start to a reset


def stream(rng, n, loop):
    """random-ish PCM (a few sines + noise) -> (bytes, state0, statel)"""
    import math
    f1, f2 = rng.uniform(0.01, 0.2), rng.uniform(0.01, 0.2)
    a = rng.randint(2000, 30000)
    pcm = []
    for i in range(n):
        l = int(a * math.sin(i * f1)) + rng.randint(-500, 500)
        r = int(a * math.sin(i * f2 + 1)) + rng.randint(-500, 500)
        pcm.append((H.clamp16(l), H.clamp16(r)))
    return H.encode_stereo(pcm, loop)


def build_pack(rng):
    lines = []
    def add(is_sfx, album, track, n, loop=0, data=None):
        if n == 0:
            lines.append((is_sfx, album * 256 + track, b"", 0, 0, 0, 0))
            return None
        if data is None:
            b, s0, sl = stream(rng, n, loop)
            data = (b, s0, sl)
        b, s0, sl = data
        lines.append((is_sfx, album * 256 + track, b, n, loop, s0, sl))
        return data
    add(False, 0, 0, 300, 100)          # loops at 100
    add(False, 0, 1, 150, 0)            # no loop position: restarts at 0 when looping
    add(False, 1, 5, 90, 80)            # loop near the end, inside the last block
    add(False, 0, 3, 0)                 # does not decode
    add(False, 0, 4, 64 * 5, 64 * 2)    # block-aligned end and loop
    for t in range(10):
        add(True, 0, t, 40 + 13 * t)
    add(True, 0, 10, 0)                 # does not decode
    shared = add(False, 2, 0, 120, 7)
    add(True, 2, 0, 120, 7, shared)     # same stream as BGM 2:0
    for t in range(1, 5):               # four more on the same stream: they cross blocks together
        add(True, 2, t, 120, 7, shared)
    # full-scale square: drives the IMA step index to its 88 ceiling (sines never get there)
    sq = [((32767, -32768) if (i // 24) % 2 else (-32768, 32767)) for i in range(200)]
    add(False, 3, 0, 200, 0, H.encode_stereo(sq, 0))
    # album 4: one SFX long enough to outlive a video frame, then seven short ones (7 SFX
    # voices), so the voice the eighth replaces (the oldest = the long one) shows in the status
    # bit a frame later
    add(True, 4, 0, 6000)
    for t in range(1, 8):
        add(True, 4, t, 40)
    sec = H.build_section(lines)
    return sec


def scenario(alt, rng, nframes, random_ops):
    """list of per-frame op lists; ops: ('W', addr, val) / ('R', addr)"""
    W = (lambda reg, v: ('W', 0x3002 + 0x10 * reg, v)) if alt else \
        (lambda reg, v: ('W', 0x4100 + reg, v))
    # a write timed to land just before a 48 kHz tick (play of an undefined id: it runs the
    # key search but changes nothing, so a tick arriving mid-search must still produce its frame)
    Q = (lambda reg, v: ('Q', 0x3002 + 0x10 * reg, v)) if alt else \
        (lambda reg, v: ('Q', 0x4100 + reg, v))
    R = (lambda reg: ('R', 0x4018 + reg)) if alt else (lambda reg: ('R', 0x4100 + reg))
    # a save into a slot with a write between the reads of its two words
    X = (lambda reg, v, slot: ('X', 0x3002 + 0x10 * reg, v, slot)) if alt else \
        (lambda reg, v, slot: ('X', 0x4100 + reg, v, slot))
    ops = [[] for _ in range(nframes)]

    def at(f, *o):
        if f < nframes:
            ops[f].extend(o)
    # (a frame has room for ~10 reads; the register sweep is spread over frames 0-2)
    at(0, R(1), R(2), R(3), R(4))
    if not alt:
        at(2, R(5), R(6), ('R', 0x4107), ('R', 0x4018))
    else:
        at(2, ('R', 0x4100), ('W', 0x4105, 0))      # default range not taken in alt mode
    at(0, W(6, 3), R(0))                             # an SFX at the power-on volume (128)
    at(1, W(0, 1), W(5, 0), R(0))                    # BGM, still at the power-on volume
    at(4, W(2, 0xC0), W(3, 0xFF))
    at(5, W(6, 0), W(6, 1), R(0))
    at(40, W(3, 0x40))
    at(60, W(1, 1), R(0))                            # pause BGM
    at(80, W(1, 0), R(0))                            # resume
    at(90, *[W(6, t) for t in range(2, 9)], R(0))    # more SFX than voices: oldest replaced
    at(100, W(6, 9), W(6, 9))                        # a read-modify-write's double write
    at(130, W(5, 3), R(0))                           # undecodable BGM: current one keeps on
    at(131, W(6, 10), R(0))                          # undecodable SFX: error bit
    at(132, W(5, 77), R(0))                          # undefined BGM
    at(200, W(1, 4), R(0))                           # stop all SFX
    at(310, W(0, 0))                                 # loop off: BGM 0 ends at its end
    at(420, W(4, 1), W(0, 1), W(5, 5), R(0))         # album 1, loop near the end
    at(700, W(4, 0), W(5, 4), W(2, 0xFF))            # block-aligned stream
    at(800, W(1, 2), R(0))                           # stop BGM
    at(810, W(4, 2), W(5, 0), *[W(6, t) for t in range(5)], R(0))  # one stream, six voices
    for f in (20, 50, 150, 300, 500, 850):
        at(f, Q(5, 77))                              # tick lands during the key search
    at(900, W(2, 0), W(3, 0))                        # volume 0
    at(905, W(2, 1), W(3, 255))
    at(1000, W(1, 3), W(4, 0), W(5, 1))              # pause + stop, then BGM 1 while paused
    at(1010, W(1, 0))
    at(1030, W(4, 3), W(5, 0), W(2, 255))            # full-scale square: IMA index ceiling
    # the long SFX then seven short: the eighth replaces the oldest (the long one), so the SFX
    # bit is off a frame later; replacing any other voice would keep the long one playing
    at(1040, W(4, 4), W(6, 0), *[W(6, t) for t in range(1, 8)], R(0))
    # a save before any volume write (the power-on volumes) restored much later
    at(2, ('V', 7))
    at(1060, ('L', 7), R(0))
    # savestates ('V' slot = save, 'L' slot = load of what that save produced)
    at(150, ('V', 0))                                # BGM 0 mid-stream, volumes C0/40
    at(250, ('L', 0), R(0))                          # back to frame 150's BGM position
    at(430, ('V', 1))                                # album 1, BGM 1:5 with loop on
    at(450, W(1, 2), W(2, 0x30), R(0))               # BGM stopped, volume changed
    at(460, ('L', 1), R(0))                          # BGM 1:5 resumes, volume restored
    at(805, ('V', 2))                                # no BGM, album 0
    at(812, ('L', 2), R(0))                          # BGM 2:0 (playing since 810) stops
    at(1000, ('V', 3))                               # just after a play: maybe not fetched yet
    at(1020, ('L', 3), R(0))
    # (frames 940-990: the full-scale square from 1030 must play to the end, so the IMA index
    # reaches its ceiling)
    # the DDR stalled ('H' clk_f cycles) so a save lands before the BGM's entry is fetched:
    # after a play (saved as "use state 0"), and after a load (saved as restored)
    at(940, ('H', 400), W(4, 0), W(5, 1), ('V', 4, 2))
    at(955, ('L', 4), R(0))
    at(965, ('H', 400), ('L', 0), ('V', 5, 2))
    at(970, W(1, 2), R(0))
    at(975, ('L', 5), R(0))
    # a play while a restored BGM still waits for its entry: the play wins, from its frame 0
    at(985, ('H', 400), ('L', 1), W(4, 0), W(5, 0), R(0))
    # a loaded BGM entry one past the last (a state from another pack): no BGM
    at(992, ('LW', 'past-end'), R(0))
    # the BGM restarted (1:5 from frame 0) between the reads of a save's two words
    at(600, X(5, 5, 6), R(0))
    for f in range(min(1100, nframes)):
        ops[f].append(R(0))                          # status every frame: when each voice ends
    if random_ops:
        for f in range(1100, nframes):
            if rng.random() < 0.08:
                k = rng.choice([0, 1, 2, 3, 4, 5, 5, 6, 6, 6])
                v = {0: rng.randint(0, 1), 1: rng.choice([0, 1, 2, 4, 6]),
                     2: rng.randint(0, 255), 3: rng.randint(0, 255), 4: rng.choice([0, 0, 1, 2]),
                     5: rng.choice([0, 1, 3, 4, 5, 77]), 6: rng.randint(0, 11)}[k]
                at(f, W(k, v), R(0))
            elif rng.random() < 0.05:
                at(f, Q(5, 77))
            elif rng.random() < 0.02:
                at(f, ('V', 10 + rng.randint(0, 2)))
            elif rng.random() < 0.02:
                at(f, ('L', 10 + rng.randint(0, 2)), R(0))
    for o in ops:                                    # a timed write goes last in its frame: it
        o.sort(key=lambda x: x[0] == 'Q')            # waits until just before the tick
    return ops


def run(args):
    rng = random.Random(args.seed)
    sec = build_pack(rng)
    if args.no_ck:          # a section built before 2026-10-29: no checkpoint table
        sec = bytearray(sec)
        struct.pack_into("<I", sec, 12, 0)
        sec = bytes(sec)
    # the pack's own header, as in DDR3: "NHDP" and section 15's offset/length at 0xF8 (a late
    # ARM half finds the section there - aud_arm.c late_load)
    head = bytearray(OFF)
    head[0:4] = b"NHDP"
    struct.pack_into("<II", head, 0xF8, OFF, len(sec))
    mem = bytes(head) + sec + bytes(64)
    ops = scenario(args.alt, rng, args.frames, args.random)
    if args.arm_late and args.frames > 2100:
        # a looping BGM (album 1, track 5, loop on) from frame 2000 with every SFX stopped, and
        # for "paused" a pause at 2100: what the late ARM half must pick up from a state event
        ops[2000] += [('W', 0x4101, 4), ('W', 0x4100, 1), ('W', 0x4104, 1), ('W', 0x4105, 5)]
        if args.arm_late == "paused" and args.frames > 3000:
            ops[2100].append(('W', 0x4101, 1))       # held from 2100...
            ops[2900].append(('W', 0x4101, 0))       # ...and resumed at its frame from 2900
    if args.flood:
        # the write port alone stalled for ~84 ticks while the CPU writes 8 times a tick: the
        # 256-entry log FIFO fills (2 entries an event), the device stops taking events, its
        # 3-entry write queue fills, and the writes after that must be dropped and counted - not
        # wrap the queue and lose four at once. The ticks must keep coming throughout (the tb
        # fails with "no frame" if the FSM waits on the FIFO).
        ops[300].insert(0, ('G', 150000))
        for f in range(300, 380):
            ops[f][1 if f == 300 else 0:0] = [('W', 0x4102, i & 0xFF) for i in range(8)]
    nes = [rng.randint(0, 65535) for _ in range(args.frames)]

    # ---- model. Since 2026-10-28 the voices are rendered on the ARM and mixed AUD_D ticks later
    # (hd3_audio.sv), so tick k's output is the NES sample and the voices of tick k - D; the
    # registers, status reads and savestate words are immediate, as before.
    D = args.d
    dev = H.Device(sec, alternate=args.alt)
    nes_hist, vhist = [0], [dev.voices()]            # the RTL's priming tick (NES sample 0)

    def out_at(k):
        # before the first D ticks: the delay line's signed 0 and no voices; the DC blocker runs
        # once a tick, on the delayed sample. Also the tick without its voices (its PCM slot not
        # in: --pcm-late accepts either)
        j = k - D
        n = dev.nes_level(dev.dc_block(nes_hist[j] if j >= 0 else 0x8000))
        return dev.mix(n, n, vhist[j] if j >= 0 else []), dev.mix(n, n, [])
    out_at(0)
    exp = []
    alt = {}                                         # line -> the tick without its voices
    bgm_play, bgm_held, sfx_any = [], [], []         # per frame, before its voices (--arm-late)
    slots = {}                                       # savestate slot -> the saved words
    loads = {}                                       # (frame, index in frame) -> words loaded
    for f in range(args.frames):
        for j, o in enumerate(ops[f]):
            if o[0] in ('W', 'Q'):
                if dev.maps_write(o[1]):
                    dev.write(o[1], o[2])
            elif o[0] == 'V':
                slots[o[1]] = dev.save()
                exp.append("V %016x %016x" % slots[o[1]])
            elif o[0] == 'L':
                if o[1] in slots:                    # a load of a slot never saved: skipped
                    loads[(f, j)] = slots[o[1]]
                    dev.load(*slots[o[1]])
            elif o[0] in ('H', 'G'):
                pass                                 # DDR / write-port stall: timing only
            elif o[0] == 'LW':                       # a load of made-up words
                n = len(dev.ent_list)
                w = ((0x80 << 48) | (0x80 << 40) | (1 << 38) | (n << 29) | 9, 0)
                loads[(f, j)] = w
                dev.load(*w)
            elif o[0] == 'X':
                slots[o[3]] = dev.save()
                exp.append("V %016x %016x" % slots[o[3]])
                if dev.maps_write(o[1]):
                    dev.write(o[1], o[2])
            else:
                hit = dev.maps_read(o[1])
                exp.append("R %d %d" % (int(hit), dev.read(o[1]) if hit else 0))
        nes_hist.append(nes[f])
        bgm_play.append(dev.bgm is not None and not dev.paused)
        bgm_held.append(dev.bgm is not None and dev.paused)
        sfx_any.append(bool(dev.sfx))
        v = dev.voices()
        vhist.append(v if args.arm else [])          # the ARM stopped: no voice ever arrives
        w, wo = out_at(f + 1)
        if args.pcm_late:
            alt[len(exp)] = "F %d %d" % wo
        exp.append("F %d %d" % w)

    # --arm-late: the ARM half starts at frame fs, long after the session's pack reset (so it
    # takes the late path), with the BGM playing (or held by pause) and no SFX for 300 frames
    # before (an SFX playing when it starts is lost by design; the BGM resumes from the state
    # event at its frame). Its sound is compared from fs + D + 64 on.
    fs = None
    if args.arm_late:
        want = bgm_play if args.arm_late == "playing" else bgm_held
        for f in range(2300, args.frames - args.d - 200):
            if all(want[g] and not sfx_any[g] for g in range(f - 300, f + 1)):
                fs = f
                break
        if fs is None:
            print("--arm-late %s: no frame with the BGM %s and no SFX for 300 frames before it "
                  "(the run would test nothing)" % (args.arm_late, args.arm_late))
            return 1

    # ---- RTL
    tmp = args.keep or tempfile.mkdtemp()
    os.makedirs(tmp, exist_ok=True)
    mp, sp, op = (os.path.join(tmp, n) for n in ("mem.bin", "script.txt", "out.txt"))
    if args.keep:
        with open(os.path.join(tmp, "expected.txt"), "w") as f:
            f.write("\n".join(exp) + "\n")
    with open(mp, "wb") as f:
        f.write(mem)
    with open(sp, "w") as f:
        data_off = struct.unpack_from("<I", sec, 8)[0]
        f.write("Z %d %d\n" % (OFF, OFF + data_off))
        for s in sorted({e.start for e in H.parse_section(sec) if e.frames}):
            f.write("S %d\n" % (OFF + s))
        f.write("A %d\n" % (0 if fs is not None else args.arm))
        if args.busy:
            f.write("B 300 450\n")
        if args.pcm_late:
            f.write("P 900 1500\n")
        # a savestate load before the pack is ready (BGM 0:0 at frame 50, odd volumes): the
        # pack's arrival resets the device, so none of it may apply (the model never sees it)
        e0 = next(i for i, e in enumerate(H.parse_section(sec)) if e.key == 0)
        f.write("L %x %x\n" % ((7 << 56) | (0x11 << 48) | (0x22 << 40) | (1 << 39) |
                               (1 << 38) | (e0 << 29) | 50, 0x0005123400031234))
        f.write("C %d %d %d\n" % (OFF, len(sec), int(args.alt)))
        for i in range(args.frames):
            if i == fs:
                f.write("A %d\n" % args.arm)        # the ARM half starts now
            for j, o in enumerate(ops[i]):
                if o[0] == 'R':
                    f.write("R %x\n" % o[1])
                elif o[0] == 'V':
                    f.write("V %d\n" % (o[2] if len(o) > 2 else 8))
                elif o[0] in ('H', 'G'):
                    f.write("%s %d\n" % o)
                elif o[0] == 'X':
                    f.write("X %x %x\n" % (o[1], o[2]))
                elif o[0] in ('L', 'LW'):
                    if (i, j) in loads:
                        f.write("L %x %x\n" % loads[(i, j)])
                else:
                    f.write("%s %x %x\n" % o)
            f.write("F %d\n" % nes[i])
        if args.reset_mid:
            for dd in RESET_DELAYS:
                f.write("K %d\n" % dd)
            f.write("N 200\n")                       # the ARM half catches up to the last reset
    exe = os.path.abspath(args.exe)
    if not os.path.isfile(exe):
        print("tb exe not found: " + exe)
        return 1
    r = subprocess.run([exe, mp, sp, op, str(args.seed), str(int(args.pal))],
                       capture_output=True, text=True)
    if r.returncode:
        print("tb failed: " + r.stderr.strip())
        return 1
    got = [l.strip() for l in open(op) if l.strip()]
    und = got.pop() if got and got[-1].startswith("U ") else "U ?"
    bursts = got.pop() if got and got[-1].startswith("H ") else "H ? ?"
    _, nlo, nhi = bursts.split()
    rate = got.pop() if got and got[-1].startswith("T ") else "T ? ?"
    _, t_exp, t_got = rate.split()
    rate_ok = t_exp != "?" and abs(int(t_exp) - int(t_got)) <= 1
    # the ARM half's counters: ticks rendered, events applied, pack resets, events lost or of an
    # unknown kind, sections it could not fetch; and the qwords the FPGA wrote
    armst = got.pop().split() if got and got[-1].startswith("A ") else ["A"] + ["?"] * 8
    dline = got.pop().split() if got and got[-1].startswith("D ") else ["D", "?"]
    # writes dropped (write queue full), writes the device took, write events it logged
    eline = got.pop().split() if got and got[-1].startswith("E ") else ["E", "?", "?", "?"]
    # clocks the device took or drove the bus while its tables were reloading (--reset-mid)
    lline = got.pop().split() if got and got[-1].startswith("L ") else ["L", "?"]
    if lline[1] != "0":
        print("  the device took the bus %s times while its tables reloaded (want 0)" % lline[1])
        return 1
    kres = [l.split() for l in got if l.startswith("K ")]
    got = [l for l in got if not l.startswith("K ")]
    if args.reset_mid:
        # each reset: a tick being mixed (S_TRK 4, S_TRKV 12, S_TRKC 11, S_NES 5, S_MIX 6)
        # finishes - one frame, and the reset stamped with the tick count after it; a reset in
        # any other state none
        mid = {4, 5, 6, 11, 12}
        kbad = [k for k in kres if k[3] != "1" or k[2] != ("1" if int(k[1]) in mid else "0")]
        hit = sorted({int(k[1]) for k in kres} & mid)
        print("  pack resets: %d, states at the edge %s, %d wrong" %
              (len(kres), sorted({int(k[1]) for k in kres}), len(kbad)))
        for k in kbad[:5]:
            print("    state %s: %s frames between the reset and the reload, stamp %s" %
                  (k[1], k[2], "ok" if k[3] == "1" else "WRONG"))
        if len(kres) != len(RESET_DELAYS) or kbad or hit != sorted(mid):
            if hit != sorted(mid):
                print("  want the reset to land in each of S_TRK, S_TRKV, S_TRKC, S_NES and "
                      "S_MIX at least once")
            return 1
    if args.flood:
        lost, took, logged = (int(x) if x.isdigit() else -1 for x in eline[1:4])
        print("%s: flood: %d writes taken, %d logged, %d dropped (queue full); ARM %s bad events, "
              "%s outside the log" % (os.path.basename(args.exe), took, logged, lost, armst[4], armst[7]))
        ok = lost > 0 and took - logged == lost and armst[4] == "0" and armst[7] == "0"
        if not ok:
            print("  want writes dropped, and every write taken either logged or counted dropped")
        return 0 if ok else 1
    if eline[1] != "0":
        print("  %s writes dropped (the write queue was full) - not expected here" % eline[1])
        return 1
    nsave = sum(1 for e in exp if e[0] == 'V')
    # --pcm-late: a tick whose slot was late is the NES path alone; any other output (a slot
    # half-read, or another tick's) is a mismatch
    n_with = n_without = 0
    bad = []
    fidx, nf = [], 0                                 # the frame of each expected line
    for e in exp:
        fidx.append(nf)
        nf += e.startswith("F ")
    from_f = fs + args.d + 64 if fs is not None else -1
    for i, (e, g) in enumerate(zip(exp, got)):
        if e.startswith("F ") and fidx[i] < from_f:
            continue                                 # before the late ARM half's sound is due
        if e == g:
            n_with += i in alt and alt[i] != e
        elif i in alt and g == alt[i]:
            n_without += 1
        else:
            bad.append((i, e, g))
    if len(got) != len(exp):
        bad.append((min(len(got), len(exp)), "%d lines" % len(exp), "%d lines" % len(got)))
    print("%s: %d frames, %d reads, %d saves, %d loads, %s, ticks %s/%s, bursts lo %s hi %s, "
          "%d mismatches" % (
        os.path.basename(args.exe), args.frames, sum(1 for e in exp if e[0] == 'R'), nsave,
        len(loads), und, t_got, t_exp, nlo, nhi, len(bad)))
    print("  ARM: %s ticks, %s events, %s resets, %s bad events, %s fetch failures; "
          "%s qwords written, %s outside the status and the log; checkpoint table taken %s"
          % tuple(armst[1:9]))
    if args.arm and armst[8] != ("0" if args.no_ck else "1"):
        print("  the section's checkpoint table was %s, want %s" %
              ("taken" if armst[8] == "1" else "not taken", "not taken" if args.no_ck else "taken"))
        return 1
    if armst[7] != "0":
        print("  the FPGA wrote outside its status qword and event log")
        return 1
    if not rate_ok and not args.reset_mid:      # (no ticks while the tables reload)
        print("  48 kHz rate wrong: %s frames for %s ticks" % (t_got, t_exp))
        return 1
    if dline[1] != str(args.d):
        print("  the testbench was built with AUD_D %s, the model ran with %d" % (dline[1], args.d))
        return 1
    want_resets = str(1 + (len(RESET_DELAYS) if args.reset_mid else 0))
    if fs is not None:
        want_resets = armst[3]                       # a late start begins after the pack reset
        print("  late start at frame %d (BGM %s), sound compared from frame %d" %
              (fs, args.arm_late, from_f))
    if args.arm and (armst[3] != want_resets or armst[4] != "0" or armst[5] != "0"):
        print("  the ARM half saw %s resets, %s bad events, %s fetch failures (want %s, 0, 0)" %
              (armst[3], armst[4], armst[5], want_resets))
        return 1
    if args.need_hi and nhi in ("0", "?"):
        print("  no read went through the overflow window - the hi path was not exercised")
        return 1
    for i, e, g in bad[:10]:
        print("  line %d: expected %s, got %s" % (i, e, g))
    # with the ARM stopped every tick from the D-th on finds its PCM slot missing (counted), and
    # the output is the NES path alone (already in the expected lines)
    want_u = "U %d" % (args.frames + 1 - args.d) if not args.arm else "U 0"
    if args.pcm_late:
        # every tick heard without its voices was an underrun (a silent-voice tick can be one
        # too, unseen), and the run must have had both kinds or it tested nothing
        u = int(und.split()[1]) if und[2:].isdigit() else -1
        print("  late slots: %d ticks with their voices, %d without, %s" % (n_with, n_without, und))
        ok = n_without <= u and n_with > 50 and n_without > 50
        if not ok:
            print("  want both kinds (> 50 each) and underruns >= the ticks heard without voices")
        return 1 if bad or not ok else 0
    if fs is not None:
        want_u = und                                 # every tick before the start underruns
    if und != want_u:
        print("  underruns: %s, want %s" % (und, want_u))
    return 1 if bad or und != want_u else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--exe", default=os.path.join(ROOT, "tools", "sim3", "obj", "tb_audio_201326592.exe"))
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--frames", type=int, default=1100)
    ap.add_argument("--alt", action="store_true")
    ap.add_argument("--random", action="store_true")
    ap.add_argument("--pal", action="store_true", help="PAL clk_f (106.4 MHz)")
    ap.add_argument("--busy", action="store_true", help="contended DDR: 300-450 clock reads")
    ap.add_argument("--need-hi", action="store_true", help="fail unless some reads used the hi window")
    ap.add_argument("--d", type=int, default=40, help="the testbench's AUD_D (build_audio.sh)")
    ap.add_argument("--arm", type=int, default=700,
                    help="clk_f cycles between passes of the ARM half; 0 = the ARM never runs")
    ap.add_argument("--keep")
    ap.add_argument("--flood", action="store_true",
                    help="stall the write port while the CPU keeps writing: check the drop count "
                         "(the output is not compared - the dropped writes never reach the model)")
    ap.add_argument("--pcm-late", action="store_true",
                    help="PCM slot reads take about a tick (900-1,500 clk_f, then up to 100 "
                         "between beats; a tick is ~1,790): a late slot's tick is heard without "
                         "its voices, never half-read")
    ap.add_argument("--arm-late", choices=("playing", "paused"),
                    help="the ARM half starts late (after frame 2300), with the BGM playing or "
                         "held by pause: it must resume from the FPGA's latest state event")
    ap.add_argument("--reset-mid", action="store_true",
                    help="after the frames, pack resets landing 0..15 clk_f after a tick is "
                         "taken: a tick being mixed must still finish and the reset be stamped "
                         "after it (the S_TRK, S_TRKV, S_TRKC, S_NES and S_MIX states must all be hit)")
    ap.add_argument("--off", type=lambda s: int(s, 0), default=OFF,
                    help="the section's file offset (a multiple of 8; one that is not a multiple "
                         "of 64 makes the table bursts start below it)")
    ap.add_argument("--no-ck", action="store_true",
                    help="clear the section's checkpoint-table offset, as in a pack built "
                         "before 2026-10-29 (the ARM's background builder makes them)")
    args = ap.parse_args()
    if args.off % 8:
        sys.exit("--off must be a multiple of 8 (sections are qword-aligned)")
    OFF = args.off
    sys.exit(run(args))
