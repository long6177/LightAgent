"""Verify every source anchor referenced in archify specs against the working tree.

Checks, for each notes/architecture/_specs/*.json:
  1. structured "sources" arrays: path exists, line <= file length,
     and the identifier implied by `label` appears on that line (best effort).
  2. every `xxx.py:123` style reference in any string field: file resolvable
     (try as-is, LightAgent/-prefixed, example/-prefixed), line <= length.

Exit code 1 if any violation. Usage: python verify_anchors.py
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SPECS = ROOT / 'notes' / 'architecture' / '_specs'
IDENT = re.compile(r'[A-Za-z_][A-Za-z0-9_]*')
REF = re.compile(r'([A-Za-z0-9_\-./]+\.py):(\d+)')

problems = []


def resolve(path: str):
    for cand in (ROOT / path, ROOT / 'LightAgent' / path, ROOT / 'LightAgent' / 'builtin_tools' / path):
        if cand.is_file():
            return cand
    return None


def check_ref(path: str, line: int, where: str, token: str | None = None):
    f = resolve(path)
    if f is None:
        problems.append(f'{where}: path not found: {path}')
        return
    lines = f.read_text(encoding='utf-8').splitlines()
    if line < 1 or line > len(lines):
        problems.append(f'{where}: {path}:{line} out of range (file has {len(lines)} lines)')
        return
    if token:
        text = lines[line - 1]
        if token not in text:
            problems.append(f'{where}: {path}:{line} does not contain "{token}" (line: {text.strip()[:90]})')


def walk(node, where):
    if isinstance(node, dict):
        if 'sources' in node and isinstance(node['sources'], list):
            for i, s in enumerate(node['sources']):
                if not isinstance(s, dict):
                    continue
                w = f"{where}#sources[{i}]"
                path, line, label = s.get('path'), s.get('line'), s.get('label', '')
                toks = IDENT.findall(label or '')
                token = toks[0] if toks else None
                if path and line:
                    check_ref(path, line, w, token)
                elif path and not line:
                    if resolve(path) is None:
                        problems.append(f'{w}: path not found: {path}')
        for k, v in node.items():
            walk(v, f'{where}/{k}')
    elif isinstance(node, list):
        for i, v in enumerate(node):
            walk(v, f'{where}[{i}]')
    elif isinstance(node, str):
        for m in REF.finditer(node):
            check_ref(m.group(1), int(m.group(2)), f'{where} ref "{m.group(0)}"')


def main():
    for spec in sorted(SPECS.glob('*.json')):
        if spec.name.startswith('_'):
            continue
        data = json.loads(spec.read_text(encoding='utf-8'))
        walk(data, spec.name)
    if problems:
        print(f'FAIL: {len(problems)} anchor problem(s)')
        for p in problems:
            print(' -', p)
        sys.exit(1)
    print('all anchors verified OK')


if __name__ == '__main__':
    main()
