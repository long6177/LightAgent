"""Extract info cards (HTML section) from archify atlas HTML files."""
import re
import sys
from pathlib import Path

base = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('.')
out = []
for p in sorted(base.glob('*.html')):
    if p.name == 'index.html':
        continue
    html = p.read_text(encoding='utf-8')
    out.append(f'\n# FILE: {p.name}')
    m = re.search(r'<!-- Info Cards -->(.*?)(?=<!-- |\Z)', html, re.S)
    if not m or '<h3' not in m.group(1):
        out.append('  (no cards)')
        continue
    seg = m.group(1)
    # split per card div
    parts = re.split(r'<div class="card">', seg)
    for part in parts[1:]:
        h = re.search(r'<h3>(.*?)</h3>', part, re.S)
        items = re.findall(r'<li[^>]*>(.*?)</li>', part, re.S)
        clean = [re.sub(r'<[^>]+>', '', it).strip() for it in items]
        out.append(f'  CARD: {h.group(1).strip() if h else "?"}')
        for it in clean:
            out.append(f'    - {it}')
print('\n'.join(out))
