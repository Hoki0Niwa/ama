"""Import public simulator encodings from locally saved Namoko article HTML.

Colors are relabelled canonically. These are web references, not Steam samples.
Image-only entries are reported missing; their boards are never guessed.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
from .model import settled_field

ARTICLES = {'hirazumi': 74224, 'hasamikomi': 74107, 'kaidan': 74093, 'zabuton': 74096}


def decode(encoded):
    tokens = re.findall(r'([a-e])(\d*)', encoded)
    if ''.join(c + n for c, n in tokens) != encoded:
        raise ValueError('unsupported simulator encoding')
    counts = [int(n) if n else 1 for _, n in tokens]
    if sum(counts) != 78 or any(n < 1 for n in counts):
        raise ValueError('expected exactly 13 rows of six cells')
    cells = ''.join(c*n for (c, _), n in zip(tokens, counts)).translate(str.maketrans('abcde', '.RGBY'))
    return settled_field(['......'] + [cells[i:i+6] for i in range(0, 78, 6)])


def collect(directory):
    entries, missing, sources = [], [], []
    for kind, article in ARTICLES.items():
        path = Path(directory) / f'{kind}.html'
        raw = path.read_bytes()
        url = f'https://puyo-camp.jp/posts/{article}'
        sources.append(dict(url=url, html_sha256=hashlib.sha256(raw).hexdigest()))
        for figure in re.findall(r'<figure\b[^>]*>(.*?)</figure>', raw.decode('utf-8'), re.S):
            label = re.search(r'<figcaption[^>]*>(\d+)連鎖</figcaption>', figure)
            if label is None:
                continue
            level = int(label[1])
            link = re.search(r'href="(http://1st.geocities.jp/mattulwan/puyo_simulator/\?([a-e0-9]+))"', figure)
            if not link:
                missing.append(dict(kind=kind, seed_chain=level, reason='image_only_no_encoding', source=url))
                continue
            entries.append(dict(id=f'{kind}-{level}', kind=kind, seed_chain=level, field=decode(link[2]),
                                source=url, simulator_url=link[1], encoding=link[2]))
    return dict(schema_version=1, status='public_reference_canonical_colors_not_local_steam_verified',
                checked_date='2026-10-05', color_mapping='a=empty,b=R,c=G,d=B,e=Y (canonical relabelling)',
                color_mapping_verified_on_steam=False, sources=sources, seeds=entries, missing=missing)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--html-directory', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    data = collect(args.html_directory)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(dict(imported=len(data['seeds']), missing=data['missing']), ensure_ascii=False))


if __name__ == '__main__':
    main()
