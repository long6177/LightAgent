"""Extract the text outline of an archify-delivered atlas HTML for baseline review.

Usage: python extract_baseline.py <html files...> <out.md>
Writes one markdown outline per file: title, description, nodes (with text),
edge labels, cards, legend.
"""
import re
import sys
from pathlib import Path
from xml.etree import ElementTree as ET


def strip_ns(tag: str) -> str:
    return tag.rsplit('}', 1)[-1]


def main() -> None:
    files = [Path(p) for p in sys.argv[1:-1]]
    out = Path(sys.argv[-1])
    chunks = []
    for f in files:
        html = f.read_text(encoding='utf-8')
        title_m = re.search(r'<title>([^<]*)</title>', html)
        # main svg
        svg_m = re.search(r'(<svg\b.*?</svg>)', html, re.S)
        chunks.append(f'\n\n# FILE: {f.name}')
        if title_m:
            chunks.append(f'title: {title_m.group(1)}')
        if not svg_m:
            chunks.append('(no svg found)')
            continue
        svg = svg_m.group(1)
        # svg uses xlink etc; register namespaces defensively
        try:
            root = ET.fromstring(svg)
        except ET.ParseError as e:
            chunks.append(f'(svg parse error: {e})')
            continue

        def walk(el, ancestors):
            tag = strip_ns(el.tag)
            if tag == 'text':
                txt = ''.join(el.itertext()).strip()
                if txt:
                    ctx = ' > '.join(ancestors[-3:])
                    chunks.append(f'  [{ctx}] {txt}')
                return
            nid = el.get('data-node-id') or el.get('data-edge-id') or ''
            cls = el.get('class') or ''
            label = f'{tag}'
            if nid:
                label += f'#{nid}'
            if cls:
                label += f'.{cls.split()[0]}'
            if tag == 'g' and nid:
                chunks.append(f'- {label}')
            walk_children(el, ancestors + [label])

        def walk_children(el, ancestors):
            for child in el:
                walk(child, ancestors)

        # skip defs to reduce noise
        for child in root:
            if strip_ns(child.tag) == 'defs':
                continue
            walk(child, [])
    out.write_text('\n'.join(chunks), encoding='utf-8')
    print(f'wrote {out}')


if __name__ == '__main__':
    main()
