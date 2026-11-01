"""make_scripts.py - write the per-game corpus input scripts (scripts/gNN.txt) for groups the
generic script does not get into gameplay. Tuned against Mesen screenshots (mesen_tune.py).
Each spec is the menu part; MOVE (walk/jump/shoot) is appended from the given frame on.

    python -I make_scripts.py
"""
import os
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
TD = os.path.normpath(os.path.join(HERE, "..", "..", "..", "NES_HDPack_testdata"))
OUT = os.path.join(HERE, "scripts")


def press(f, b, n=10):
    return [(f, b), (f + n, "0")]


def move(f):
    """Walk right with jump/shoot taps, a short step left, then right again (~900 frames)."""
    seq = [(f, "RIGHT"), (f + 60, "RIGHT+A"), (f + 70, "RIGHT"), (f + 140, "RIGHT+B"),
           (f + 148, "RIGHT"), (f + 230, "RIGHT+A"), (f + 240, "RIGHT"), (f + 320, "LEFT"),
           (f + 380, "LEFT+B"), (f + 388, "LEFT"), (f + 450, "RIGHT"), (f + 520, "RIGHT+A"),
           (f + 530, "RIGHT"), (f + 600, "RIGHT+B"), (f + 608, "RIGHT"), (f + 700, "UP"),
           (f + 740, "RIGHT"), (f + 820, "DOWN"), (f + 860, "RIGHT"), (f + 950, "0")]
    return seq


def starts(*frames):
    out = []
    for f in frames:
        out += press(f, "START")
    return out


SPECS = {
    # one Start only: a second Start pauses these games
    "g35": ("Duck Hunt: Game A", starts(70) + move(260)),
    "g38": ("Urban Champion", starts(70) + move(260)),
    "g47": ("Mappy (Japan)", starts(70) + move(260)),
    # 1943: the power-up screen only takes a point every ~60 frames once it is ready; spend
    # all 3, then A on YES
    # the power-up screen: each RIGHT press puts one of the 3 points on the selected stat (A
    # does nothing there); with all 3 spent it asks IS THIS OK (cursor YES) and A confirms
    # Dense sampling showed the screen unchanged 330..800 despite RIGHT taps, so its input
    # timing is unclear; the generic script's inputs reach IS THIS OK (cursor YES) by 1500,
    # so replay those and confirm with Start (A does not confirm; tried 1500..1860).
    "g01": ("1943: generic inputs through the power-up screen, then Start on YES",
            starts(70, 150) + move(260)[:-1] + press(1500, "B") + move(1600),
            [300, 1500, 1600, 1800, 2100, 2400]),
    # Castlevania III: Start on the name entry accepts it
    "g06": ("Castlevania III: title, name entry accepted with Start", starts(70, 150, 300, 380) + move(480)),
    # Dragon Warrior III: menu and name entry by repeated A
    "g09": ("Dragon Warrior III: wait out the logo, Start, then A through menus and the intro",
            starts(650, 720) + [x for f in range(800, 2900, 40) for x in press(f, "A")] + move(2950),
            [700, 1000, 1500, 2200, 2900, 3400]),
    # Journey to Silius / Contra (J) / Ninja Gaiden II / Shatterhand: skip the intro with Starts
    "g13": ("Journey to Silius: skip intro", starts(70, 150, 300, 400, 500) + move(600)),
    "g44": ("Contra (Japan): skip intro", starts(70, 150, 300, 400, 500) + move(600)),
    "g28": ("Ninja Gaiden II: Start once the title shows", starts(320, 400, 480) + move(600)),
    "g30": ("Shatterhand: Start once PUSH START shows", starts(400, 480) + move(600)),
    # Mega Man: title, stage select, Start picks the stage
    "g16": ("Mega Man: title, stage select (Start picks)", starts(70, 150, 260) + move(520)),
    "g17": ("Mega Man: title, stage select (Start picks)", starts(70, 150, 260) + move(520)),
    "g18": ("Mega Man: title, stage select (Start picks)", starts(70, 150, 260) + move(520)),
    # Pac-Man / Yie Ar Kung-Fu: Start only after the title menu has appeared
    "g29": ("Pac-Man: Start after the title menu has scrolled in", starts(320, 360) + move(450)),
    # Yie Ar Kung-Fu: Start on the title, then fight Wang with punches and kicks. It used to
    # look as if Start was never taken; the cause was Mesen, not the game (2026-10-23): this ROM
    # has an iNES 1.0 header and no Mesen DB entry, so Mesen attached no controller and every
    # $4016 read was open bus ($40). mesen2/settings.json now sets standard controllers on both
    # ports; a DB entry or NES 2.0 header still overrides it for every other game.
    "g52": ("Yie Ar Kung-Fu: Start on the title, then fight",
            starts(100) + [(300, "RIGHT")] +
            [x for f, b in [(360, "RIGHT+B"), (430, "RIGHT+A"), (500, "B"), (560, "A"),
                            (620, "RIGHT+B"), (700, "UP+B"), (760, "DOWN+A"), (820, "RIGHT+B"),
                            (960, "LEFT+A"), (1040, "RIGHT+B"), (1120, "A"), (1200, "B"),
                            (1300, "RIGHT+A"), (1400, "B")] for x in press(f, b, 8)] +
            [(1500, "0")]),
    # The Legend of Zelda: with no saves the cursor starts on REGISTER; one letter, SELECT to
    # END, Start, then Start on file 1
    "g51": ("Zelda: title, register a name, END, start file 1",
            starts(70, 150) + press(220, "A") + press(250, "SELECT") + press(270, "SELECT") +
            press(290, "SELECT") + starts(320, 400, 480) + move(620)),
}
# The Legend of Zelda (USA) gets to the field sooner than the Europe ROM; a third Start there
# opens the inventory
SPECS["g53"] = ("Zelda (USA): title, register a name, END, start file 1",
                starts(70, 150) + press(220, "A") + press(250, "SELECT") + press(270, "SELECT") +
                press(290, "SELECT") + starts(320, 400) + move(620))

COPIES = {"g32": "zelda2_play.txt", "g33": "zelda2_play.txt"}
for g in ("g19", "g20", "g21", "g22", "g23", "g25"):
    COPIES[g] = "metroid_mmm_play.txt"

os.makedirs(OUT, exist_ok=True)
for g, spec in SPECS.items():
    title, seq = spec[0], spec[1]
    with open(os.path.join(OUT, g + ".txt"), "w", newline="\n") as fh:
        fh.write(f"# {title} (corpus group {g}; make_scripts.py)\n")
        if len(spec) > 2:
            fh.write("#frames " + ",".join(str(f) for f in spec[2]) + "\n")
        fh.write("0 0\n")
        for f, b in sorted(seq):
            fh.write(f"{f} {b}\n")
for g, src in COPIES.items():
    shutil.copyfile(os.path.join(TD, src), os.path.join(OUT, g + ".txt"))
print(f"{len(SPECS)} written, {len(COPIES)} copied")
