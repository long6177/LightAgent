"""Iteratively apply archify's own suggested label fixes to lifecycle specs.

For each spec: run validate, parse diagnostics for `Label "X" ... Suggested
fix: labelAt [x, y]` / `labelDy +N` / `labelDx +N` patterns, apply them to the
matching transition, repeat up to N rounds or until clean.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

ARCHIFY = r"C:\Users\long\.zcode\skills\archify\bin\archify.mjs"
SPECS = Path(__file__).resolve().parents[1] / "_specs"
MAX_ROUNDS = 6

AT = re.compile(r'labelAt \[(-?[\d.]+), (-?[\d.]+)\]')
DY = re.compile(r'labelDy \+(\d+(?:\.\d+)?)')
DYn = re.compile(r'labelDy -(\d+(?:\.\d+)?)')
DX = re.compile(r'labelDx \+(\d+(?:\.\d+)?)')
DXn = re.compile(r'labelDx -(\d+(?:\.\d+)?)')
LBL = re.compile(r'Labels "([^"]+)" and "([^"]+)" overlap')
LBL1 = re.compile(r'Label "([^"]+)"')


def validate(path):
    p = subprocess.run(
        ['node', ARCHIFY, 'validate', 'lifecycle', str(path), '--quality', 'showcase', '--json'],
        capture_output=True, text=True, encoding='utf-8')
    try:
        return json.loads(p.stdout)
    except json.JSONDecodeError:
        return {'ok': False, 'diagnostics': [], 'error': p.stdout[-400:]}


def apply_fixes(spec_path, diagnostics):
    d = json.loads(spec_path.read_text(encoding='utf-8'))
    by_label = {}
    for t in d.get('transitions', []):
        key = t.get('label') or ''
        by_label.setdefault(key, []).append(t)
    changed = 0
    for e in diagnostics:
        msg = e.get('message', '') + json.dumps(e.get('evidence', {}), ensure_ascii=False)
        m = AT.search(msg)
        lm = LBL.search(msg) or LBL1.search(msg)
        if not (m or DY.search(msg) or DYn.search(msg) or DX.search(msg) or DXn.search(msg)):
            continue
        if not lm:
            continue
        name = lm.group(1)
        targets = by_label.get(name, [])
        if not targets:
            continue
        t = targets[0]
        if m and 'overlaps node' in msg or (m and 'overlaps state' in msg):
            t['labelAt'] = [float(m.group(1)), float(m.group(2))]
            t.pop('labelDx', None); t.pop('labelDy', None)
            changed += 1
            continue
        if m:
            t['labelAt'] = [float(m.group(1)), float(m.group(2))]
            t.pop('labelDx', None); t.pop('labelDy', None)
            changed += 1
            continue
        if DY.search(msg):
            t['labelDy'] = float(DY.search(msg).group(1)); changed += 1
        elif DYn.search(msg):
            t['labelDy'] = -float(DYn.search(msg).group(1)); changed += 1
        elif DX.search(msg):
            t['labelDx'] = float(DX.search(msg).group(1)); changed += 1
        elif DXn.search(msg):
            t['labelDx'] = -float(DXn.search(msg).group(1)); changed += 1
    if changed:
        spec_path.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding='utf-8')
    return changed


def main():
    names = sys.argv[1:]
    files = [SPECS / f'{n}.lifecycle.json' for n in names]
    for path in files:
        for round_ in range(MAX_ROUNDS):
            res = validate(path)
            diags = res.get('diagnostics', [])
            layout = [e for e in diags if e['code'].startswith('layout/')]
            if res.get('ok') or not layout:
                print(f'{path.name}: ok={res.get("ok")} (round {round_})')
                break
            changed = apply_fixes(path, layout)
            if not changed:
                print(f'{path.name}: no fixable layout diagnostics left; {len(layout)} remain')
                for e in layout[:6]:
                    print('   -', e['message'][:160])
                break
        else:
            print(f'{path.name}: giving up after {MAX_ROUNDS} rounds')


if __name__ == '__main__':
    main()
