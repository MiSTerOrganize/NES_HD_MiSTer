"""Negative control for the hd3_loader unit test: each mutant of the RTL must FAIL tb_loader.

Covers the watched-address list copy (lw_* port) and its header check (reject 10), and the
streaming section-table check (reject 8). The header checks for reasons 1-9 also have their
own corrupted-file variants inside tb_loader.
Each anchor must occur exactly once in the source, so a stale anchor fails loudly instead of
producing an unmutated "mutant" that passes.

usage: python neg_loader.py PACK.hdp [PACK.hdp ...]     (small packs keep it quick)

The pack set must include a pack with a watched-address list, one with ROM patches and one with
addition tables (else FIXTURE ERROR) - e.g. out/p080.hdp, fixtures/romfix/uc.hdp,
obj/dict/lane.hdp. Six mutants need particular header values (legacy flag bits, a non-zero
fallback map, render_orig option bits, a pack that leaves the game's type to the cart and one that
records it); without such a pack they are reported NOT OBSERVABLE and the exit code is 3. Full coverage: add out/p132.hdp and out/a058.hdp (62 MB, ~11 min a run).
"""
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
# HD3_LOADER_RTL / HD3_LOADER_TB / SIM3 override where the RTL, the testbench sources and
# build_one.sh come from (defaults: rtl/hdpack and this folder)
RTL = os.environ.get("HD3_LOADER_RTL", os.path.join(ROOT, "rtl", "hdpack", "hd3_loader_stream.sv"))
TB = os.environ.get("HD3_LOADER_TB", HERE)
SIM3 = os.environ.get("SIM3", HERE)

MUTANTS = {
    "list entry bytes in the wrong order":
        ("lw_addr <= {load_data, qasm[63:40]};", "lw_addr <= {qasm[63:40], load_data};"),
    "list index off by one":
        ("lw_idx  <= w_rel[9:2];", "lw_idx  <= w_rel[9:2] + 8'd1;"),
    "list count ignored (copies the whole section)":
        ("{5'd0, w_rel[28:2]} < w_wcnt", "1'b1"),
    "wrong section (8 instead of 9)":
        ("7'd50: w_s9off <= b_word;", "7'd48: w_s9off <= b_word;"),
    "oversized list accepted":
        ("sections_ok && !herr && wlist_ok &&", "sections_ok && !herr &&"),
    "only the first section-table entry checked":
        ("(cnt[8:3] >= 6'd16) & (cnt[8:3] < 6'd34)", "(cnt[8:3] == 6'd16)"),
    "section table checked to entry 15 only":
        ("(cnt[8:3] >= 6'd16) & (cnt[8:3] < 6'd34)", "(cnt[8:3] >= 6'd16) & (cnt[8:3] < 6'd32)"),
    "section table not required to be complete":
        ("wire        sections_ok = ~sec_bad & (cnt > 29'h10F);",
         "wire        sections_ok = ~sec_bad;"),
    # the addition tables (8a)
    "addition table check dropped":
        ("wlist_ok &&\n\t\t           atab_ok;", "wlist_ok;"),
    "stale conversion (additions, no table) accepted":
        ("(w_nadd == 0 && w_anb == 0", "(w_anb == 0"),
    "add_en always on":
        ("assign add_en       = w_s16len != 32'd0;", "assign add_en       = 1'b1;"),
    "addition key base from section 17":
        ("7'd64: h_s16off <= b_word;", "7'd66: h_s16off <= b_word;"),
    "addition lists base from section 16":
        ("7'd66: h_s17off <= b_word;", "7'd64: h_s17off <= b_word;"),
    "addition bucket count from header 0x50":
        ("7'd19: w_anb   <= b_word;", "7'd20: w_anb   <= b_word;"),
    "addition max probe from header 0x4C":
        ("7'd20: w_amp   <= b_word;", "7'd19: w_amp   <= b_word;"),
    "addition table size not checked":
        ("w_s16len == {w_anb[25:0], 6'd0} && ", ""),
    # the hd3_dict / hd3_resolve exports
    "game_ram ignores the cart when the pack does not know":
        ("assign game_ram     = flags[5] ? flags[4] : cart_no_chr_rom;",
         "assign game_ram     = flags[4];"),
    "game_ram ignores the pack when it does know":
        ("assign game_ram     = flags[5] ? flags[4] : cart_no_chr_rom;",
         "assign game_ram     = cart_no_chr_rom;"),
    "legacy from the wrong flag bit":
        ("assign legacy       = flags[0];", "assign legacy       = flags[1];"),
    "fallback map base from section 9":
        ("7'd52: h_s10off <= b_word;", "7'd50: h_s10off <= b_word;"),
    "fallback map length from the wrong header word":
        ("7'd17: h_44    <= b_word;", "7'd16: h_44    <= b_word;"),
    # the hd3_resolve / hd3_render exports (stage 3)
    "conditions base from section 3":
        ("assign conds_base   = PACK_Q + h_s2off[27:3];", "assign conds_base   = PACK_Q + h_s3off[27:3];"),
    "image blocks base from section 5":
        ("7'd40: h_s4off <= b_word;", "7'd42: h_s4off <= b_word;"),
    "background map base from section 8":
        ("7'd46: h_s7off <= b_word;", "7'd48: h_s7off <= b_word;"),
    "palette base from section 13":
        ("7'd56: h_s12off <= b_word;", "7'd58: h_s12off <= b_word;"),
    "value index base not a byte address":
        ("assign bgi_base     = {PACK_Q, 3'b000} + h_s13off[27:0];",
         "assign bgi_base     = {3'b000, PACK_Q} + h_s13off[27:0];"),
    "overscan left from the right-hand field":
        ("7'd7:  h_ov[3] <= b_word;", "7'd5:  h_ov[3] <= b_word;"),
    "negative overscan not clamped to 0":
        ("clamp8 = v[31] ? 8'd0 : ", "clamp8 = "),
    "overscan over 255 not clamped":
        ("(v[30:8] != 0) ? 8'd255 : v[7:0]", "v[7:0]"),
    "cache_en not inverted":
        ("assign cache_en     = ~h_opt[3];", "assign cache_en     = h_opt[3];"),
    "render_orig from option bit 3":
        ("assign render_orig  = ~h_opt[4];", "assign render_orig  = ~h_opt[3];"),
    "has_pal from flag bit 0":
        ("assign has_pal      = flags[1];", "assign has_pal      = flags[0];"),
    # section 14, ROM patches: observable only on a pack that HAS patches (main() checks). Its
    # base is not an output any more (2026-10-28: the ARM reads the section, hd3_romfix only
    # needs to know there is one), so only the length is checked.
    "patch length dropped (pack treated as patch-free)":
        ("assign patch_len    = h_s14len;", "assign patch_len    = 32'd0;"),
}


def main():
    packs = [p.replace("\\", "/") for p in sys.argv[1:]]
    if not packs:
        print(__doc__)
        return 2
    # The list mutants are only observable on a pack WITH a watched-address list (header word
    # 0x34); a run on list-less packs "misses" them for the fixture's sake, not the RTL's.
    counts = []
    plens = []
    alens = []
    for p in packs:
        with open(p, "rb") as f:
            h = f.read(0x110)
        counts.append(int.from_bytes(h[0x34:0x38], "little"))
        plens.append(int.from_bytes(h[0xF4:0xF8], "little"))
        alens.append(int.from_bytes(h[0x104:0x108], "little"))     # section 16 length
    # the section-16/17 mutants (addition table bases) need a pack WITH addition tables
    if not any(alens):
        print(f"FIXTURE ERROR: none of {packs} has addition tables (section 16 lengths {alens}); "
              "give at least one pack with them (e.g. obj/dict/lane.hdp, made by make_add_draw.sh)")
        return 2
    # the same holds for the section-14 mutants: they need a pack WITH ROM patches
    if not any(plens):
        print(f"FIXTURE ERROR: none of {packs} has a ROM patch section (0xF4 lengths {plens}); "
              "give at least one pack with one (e.g. the Urban Champion test pack)")
        return 2
    if not any(counts):
        print(f"FIXTURE ERROR: none of {packs} has a watched-address list (counts {counts}); "
              "give at least one pack with one (e.g. Road Fighter, Kung Fu Guy)")
        return 2
    # Four mutants only show on packs with particular header values. The two section-10
    # mutants reuse an existing case label, so the register keeps its reset value 0 and only a
    # NON-ZERO real value differs; the smallest corpus pack with fallbacks is a058 (62 MB, ~11
    # minutes a run). A mutant no given pack can observe is reported NOT OBSERVABLE and left out
    # of the total - never counted as a miss, never as a catch.
    def hw(h, o):
        return int.from_bytes(h[o:o + 4], "little")
    obs = {"legacy from the wrong flag bit": False, "fallback map base from section 9": False,
           "fallback map length from the wrong header word": False,
           "render_orig from option bit 3": False,
           "game_ram ignores the cart when the pack does not know": False,
           "game_ram ignores the pack when it does know": False}
    for p in packs:
        with open(p, "rb") as f:
            h = f.read(0x100)
        obs["legacy from the wrong flag bit"] |= (h[7] & 1) != ((h[7] >> 1) & 1)          # e.g. p132
        # tb_loader checks game_ram against the cart only for a pack that leaves it unknown (flag
        # bit 5 clear) and against the pack's bit 4 only for one that knows it
        obs["game_ram ignores the cart when the pack does not know"] |= (h[7] & 0x20) == 0
        obs["game_ram ignores the pack when it does know"] |= (h[7] & 0x20) != 0
        obs["fallback map base from section 9"] |= (hw(h, 0xD0) >> 3) != 0                # e.g. a058
        obs["fallback map length from the wrong header word"] |= hw(h, 0x44) != 0         # e.g. a058
        obs["render_orig from option bit 3"] |= ((hw(h, 0x0C) >> 4) & 1) != ((hw(h, 0x0C) >> 3) & 1)  # a058
    with open(RTL, encoding="utf-8") as f:
        src = f.read()
    work = os.environ.get("NEG_LOADER_WORK", os.path.join(HERE, "obj", "neg_loader"))
    os.makedirs(work, exist_ok=True)
    caught = 0
    skipped = 0
    for name, (old, new) in MUTANTS.items():
        n = src.count(old)
        if n != 1:
            print(f"ANCHOR ERROR [{name}]: found {n} times")
            return 2
        if name in obs and not obs[name]:
            print(f"NOT OBSERVABLE  {name}  (no given pack has the header value it changes)")
            skipped += 1
            continue
        tag = "".join(c if c.isalnum() else "_" for c in name)
        mdir = os.path.join(work, tag)
        shutil.rmtree(mdir, ignore_errors=True)
        os.makedirs(mdir)
        mrtl = os.path.join(mdir, "hd3_loader_stream.sv")
        with open(mrtl, "w", encoding="utf-8", newline="\n") as f:
            f.write(src.replace(old, new))
        env = dict(os.environ, OBJ=mdir.replace("\\", "/"))
        b = subprocess.run(["sh", os.path.join(SIM3, "build_one.sh"), "hd3_loader_tb_top",
                            os.path.join(TB, "tb_loader.cpp").replace("\\", "/"),
                            os.path.join(TB, "hd3_loader_tb_top.sv").replace("\\", "/"),
                            mrtl.replace("\\", "/")],
                           env=env, capture_output=True, text=True)
        if b.returncode:
            print(f"BUILD FAILED [{name}]\n{b.stdout[-800:]}{b.stderr[-800:]}")
            return 2
        r = subprocess.run([os.path.join(mdir, "tb_loader.exe")] + packs, capture_output=True, text=True)
        failed = r.returncode != 0
        print(f"{'CAUGHT' if failed else 'MISSED'}  {name}", flush=True)
        caught += failed
    tried = len(MUTANTS) - skipped
    print(f"{caught}/{tried} mutants caught" + (f", {skipped} NOT OBSERVABLE with these packs" if skipped else ""))
    # 0 = every mutant tried and caught; 1 = a miss; 3 = all tried caught but some not observable
    if caught != tried:
        return 1
    return 3 if skipped else 0


if __name__ == "__main__":
    sys.exit(main())
