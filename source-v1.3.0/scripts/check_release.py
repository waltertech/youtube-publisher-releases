#!/usr/bin/env python3
"""Verify release checksums and the updater-compatible ZIP layout."""
import argparse
import hashlib
import json
from pathlib import Path
import plistlib
import zipfile


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    root = args.directory
    metadata = json.loads((root / 'update.json').read_text())
    assert metadata['version'] == '1.3.0'
    archive = root / ('YouTubePublisher-Mac-' + metadata['version'] + '.zip')
    assert metadata['size'] == archive.stat().st_size
    assert metadata['sha256'] == sha(archive)
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None
        assert all(n.startswith('YouTube发布工作台.app/') and '..' not in Path(n).parts for n in z.namelist())
        prefix = 'YouTube发布工作台.app/Contents/'
        info = plistlib.loads(z.read(prefix + 'Info.plist'))
        assert info['CFBundleShortVersionString'] == info['CFBundleVersion'] == '1.3.0'
        assert prefix + 'Resources/payload/material_rules.py' in z.namelist()
        assert not any(n.endswith(('.sqlite3','.pyc')) for n in z.namelist() if '/payload/' in n)
    for line in (root / 'SHA256SUMS.txt').read_text().splitlines():
        expected, name = line.split('  ', 1)
        assert expected == sha(root / name), name
    print('PASS: release checksums, update metadata, ZIP CRC/layout, bundled version, no user ledger')
    if not (root / 'update.sig').exists():
        print('PENDING: update.sig must be produced with the original publisher Ed25519 key before enabling online updates')


if __name__ == '__main__':
    main()
