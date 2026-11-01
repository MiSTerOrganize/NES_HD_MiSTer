"""word_sections.py - where hd3_render's logic goes, from a WORD-level yosys netlist.

`synth -run :fine` stops before technology mapping, so every mux, adder, comparator and shifter
is still one cell carrying the source line it came from (the gate-level netlist keeps a source
line on ~4% of its cells, which is useless). Each cell gets a rough LUT-equivalent cost from its
type and widths; the absolute numbers are approximate, the DISTRIBUTION is the point
(OPEN_ITEMS item 11: can serialising the renderer reach the ~3.6x it needs?).

Cost model (6-input LUTs):
  $mux                Y bits              (one LUT per bit, often merged)
  $pmux               Y bits * cases / 4  (a wide case statement)
  $add $sub $alu $neg Y bits              (carry chain)
  $mul                A*B / 8             (reported; usually DSP)
  $eq $ne $lt...      A bits / 3
  $shl $shr $shiftx   Y * log2(range)     ($shiftx = array indexing / part-select by variable)
  $and $or $xor $not  Y / 3
  $reduce_* $logic_*  A / 5
  flip-flops          counted separately; memories ($mem*) counted separately
usage: python word_sections.py RENDER_WORD.json HD3_RENDER.sv [--top N]
"""
import json, math, re, sys
from collections import defaultdict


def marks_of(sv):
    marks = []
    with open(sv, encoding='utf-8', errors='replace') as f:
        for n, line in enumerate(f, 1):
            s = line.strip()
            m = re.match(r'//\s*-{3,}\s*(.+?)\s*-*$', s)
            if m:
                marks.append((n, m.group(1)[:58]))
                continue
            m = re.match(r'function\s+(?:automatic\s+)?(?:\[[^\]]*\]\s*)?(\w+)', s)
            if m:
                marks.append((n, 'function ' + m.group(1)))
                continue
            m = re.match(r'([A-Z][A-Z0-9_]*)\s*:\s*begin', s)
            if m and not line.startswith('\t\t\t'):
                marks.append((n, 'state ' + m.group(1)))
    return marks


def cost(c):
    t, p = c['type'], c.get('parameters', {})
    w = lambda k: int(p.get(k, '0'), 2) if isinstance(p.get(k), str) else int(p.get(k, 0))
    Y, A, B = w('Y_WIDTH'), w('A_WIDTH'), w('B_WIDTH')
    if t == '$mux':
        return w('WIDTH')
    if t == '$pmux':
        return w('WIDTH') * max(1, w('S_WIDTH')) / 4
    if t in ('$add', '$sub', '$alu', '$neg', '$lcu', '$macc'):
        return Y
    if t == '$mul':
        return A * B / 8
    if t in ('$eq', '$ne', '$lt', '$le', '$gt', '$ge', '$eqx', '$nex'):
        return max(A, B) / 3
    if t in ('$shl', '$shr', '$sshl', '$sshr', '$shift', '$shiftx'):
        # a barrel shifter has one mux level per bit of DISTANCE that can matter: bounded by
        # the select width and by how far the A input can actually be moved (A + Y bits)
        levels = min(B, math.ceil(math.log2(max(2, A + Y))))
        return Y * max(1, levels) / 2      # two mux inputs per 6-LUT level, roughly
    if t in ('$and', '$or', '$xor', '$xnor', '$not'):
        return Y / 3
    if t.startswith('$reduce') or t.startswith('$logic'):
        return A / 5
    return 0


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    top = int(sys.argv[sys.argv.index('--top') + 1]) if '--top' in sys.argv else 40
    net = json.load(open(sys.argv[1]))
    marks = marks_of(sys.argv[2])
    mod = net['modules']['hd3_render']
    logic, ffs, mems = defaultdict(float), defaultdict(int), defaultdict(int)
    bytype = defaultdict(float)
    unattr = 0.0
    for c in mod['cells'].values():
        src = c.get('attributes', {}).get('src', '')
        m = re.search(r'hd3_render\.sv:(\d+)', src)
        t = c['type']
        if 'dff' in t.lower() or t in ('$dlatch', '$sr'):
            n = int(c['parameters'].get('WIDTH', '1'), 2) if isinstance(c['parameters'].get('WIDTH'), str) else 1
            key = 'unattributed'
            if m:
                key = section(marks, int(m.group(1)))
            ffs[key] += n
            continue
        if t.startswith('$mem'):
            mems[section(marks, int(m.group(1))) if m else 'unattributed'] += 1
            continue
        k = cost(c)
        bytype[t] += k
        if not m:
            unattr += k
            continue
        logic[section(marks, int(m.group(1)))] += k
    tot = sum(logic.values()) + unattr
    print(f'estimated LUT-equivalents {tot:,.0f}  (unattributed {unattr:,.0f} = {100*unattr/tot:.1f}%)'
          f'  flip-flops {sum(ffs.values()):,}  memories {sum(mems.values())}\n')
    print('by cell type:')
    for t, v in sorted(bytype.items(), key=lambda kv: -kv[1])[:10]:
        print(f'  {t:12s} {v:10,.0f}  {100*v/tot:5.1f}%')
    print(f'\n{"section (source line, label)":62s} {"LUT-eq":>9s} {"%":>6s} {"FF":>7s}')
    rows = sorted(logic.items(), key=lambda kv: -kv[1])
    cum = 0
    for s, v in rows[:top]:
        cum += v
        print(f'{s:62s} {v:9,.0f} {100*v/tot:5.1f}% {ffs.get(s, 0):7,}   cum {100*cum/tot:5.1f}%')


def section(marks, line):
    sec = 'top (before first banner)'
    for n, label in marks:
        if n <= line:
            sec = f'{n:5d} {label}'
        else:
            break
    return sec


if __name__ == '__main__':
    main()
