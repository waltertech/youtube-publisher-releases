#!/usr/bin/env python3
"""Write a portable SHA256SUMS.txt without including itself or hidden sidecars."""
import argparse
import hashlib
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('directory', type=Path)
parser.add_argument('--recursive', action='store_true')
args = parser.parse_args()
root = args.directory
paths = root.rglob('*') if args.recursive else root.iterdir()
rows = []
for path in sorted(paths):
    if not path.is_file() or path == root / 'SHA256SUMS.txt' or path.name.startswith('._'):
        continue
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    rows.append(h.hexdigest() + '  ' + path.relative_to(root).as_posix())
(root / 'SHA256SUMS.txt').write_text('\n'.join(rows) + '\n', encoding='utf-8')
print('SHA256SUMS:', len(rows), 'files')
