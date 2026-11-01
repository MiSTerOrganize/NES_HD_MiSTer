"""render_sections.py - where hd3_render's logic goes, by section of the source file.

Reads the yosys netlist (write_json after synth_intel_alm) and buckets every cell by the
source line yosys recorded for it, then maps line ranges to the renderer's sections. Yosys's
absolute counts are lower than Quartus's; the DISTRIBUTION is what this is for (OPEN_ITEMS
item 11, 2026-10-22: does a few wide parallel structures dominate, or is the size spread?).

usage: python render_sections.py RENDER.json HD3_RENDER.sv
"""
import json, re, sys
from collections import defaultdict

LUT = re.compile(r'^MISTRAL_ALUT')


def sections(sv_path):
    """(start_line, label) for every '// ----' banner, function, and state group."""
    marks = []
    with open(sv_path, encoding='utf-8', errors='replace') as f:
        for n, line in enumerate(f, 1):
            s = line.strip()
            m = re.match(r'//\s*-{3,}\s*(.+?)\s*-*$', s)
            if m:
                marks.append((n, m.group(1)[:60]))
            elif s.startswith('function'):
                m = re.match(r'function\s+(?:automatic\s+)?(?:\[[^\]]*\]\s*)?(\w+)', s)
                if m:
                    marks.append((n, 'function ' + m.group(1)))
            else:
                # a state-machine arm ("S_LINE: begin", "W_S0: begin") gets its own row
                m = re.match(r'([A-Z][A-Z0-9_]*)\s*:\s*begin', s)
                if m and not line.startswith('\t\t\t'):
                    marks.append((n, 'state ' + m.group(1)))
    return marks


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    with open(sys.argv[1]) as f:
        net = json.load(f)
    marks = sections(sys.argv[2])
    mod = net['modules']['hd3_render']
    luts, ffs, arith, other = defaultdict(int), defaultdict(int), defaultdict(int), defaultdict(int)
    unattributed = 0
    for cell in mod['cells'].values():
        src = cell.get('attributes', {}).get('src', '')
        m = re.search(r'hd3_render\.sv:(\d+)', src)
        if not m:
            unattributed += 1
            continue
        line = int(m.group(1))
        sec = 'top (before first banner)'
        for n, label in marks:
            if n <= line:
                sec = f'{n:5d} {label}'
            else:
                break
        t = cell['type']
        if t == 'MISTRAL_ALUT_ARITH':
            arith[sec] += 1
        elif LUT.match(t):
            luts[sec] += 1
        elif t in ('MISTRAL_FF', '$_DFF_P_', '$_DFFE_PP_', '$_SDFF_PP0_', '$_SDFFE_PP0P_',
                   '$_DFFE_PN0P_', '$_DFF_PN0_') or t.startswith('$_DFF') or t.startswith('$_SDFF'):
            ffs[sec] += 1
        elif t.startswith('$_'):      # generic gate from `synth -noabc`: AND/OR/XOR/MUX/NOT
            luts[sec] += 1
        else:
            other[sec] += 1
    rows = sorted(set(luts) | set(ffs) | set(arith), key=lambda s: -(luts[s] + arith[s]))
    tl = sum(luts.values()) + sum(arith.values())
    print(f'logic cells attributed {tl}, flip-flops {sum(ffs.values())}, '
          f'cells with no source line {unattributed}\n')
    print(f'{"section (source line, label)":66s} {"LUT":>6s} {"arith":>6s} {"FF":>6s} {"%logic":>7s}')
    for s in rows:
        lg = luts[s] + arith[s]
        print(f'{s:66s} {luts[s]:6d} {arith[s]:6d} {ffs[s]:6d} {100 * lg / tl:6.1f}%')


if __name__ == '__main__':
    main()
