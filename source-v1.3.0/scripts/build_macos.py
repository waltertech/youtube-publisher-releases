#!/usr/bin/env python3
"""Build universal 1.3.2 packages from the original compiled runtime baseline."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import tempfile
import stat
import zipfile

SOURCE = Path(__file__).resolve().parents[1]
VERSION = '1.3.2'
APP_NAME = 'YouTube发布工作台.app'


def run(*args, **kwargs):
    subprocess.run([str(x) for x in args], check=True, **kwargs)


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest() if hasattr(hashlib, 'file_digest') else hash_stream(stream)


def hash_stream(stream):
    h = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024 * 1024), b''):
        h.update(chunk)
    return h.hexdigest()


def zip_app(app, archive):
    # ditto omits the ZIP UTF-8 filename flag on this host; Python's updater
    # consequently sees garbled Chinese paths. Explicit UTF-8 ZIP entries avoid it.
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for p in [app, *sorted(app.rglob('*'))]:
            name = p.relative_to(app.parent).as_posix()
            if p.is_symlink():
                item = zipfile.ZipInfo(name)
                item.create_system = 3
                item.external_attr = (stat.S_IFLNK | 0o777) << 16
                z.writestr(item, os.readlink(p).encode('utf-8'))
            else:
                z.write(p, name)


def main():
    parser = argparse.ArgumentParser()
    base = parser.add_mutually_exclusive_group(required=True)
    base.add_argument('--baseline-app', type=Path)
    base.add_argument('--baseline-zip', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='ypp-build-120-') as temp:
        stage = Path(temp)
        if args.baseline_zip:
            base_dir = stage / 'baseline'; base_dir.mkdir()
            run('/usr/bin/ditto', '-x', '-k', args.baseline_zip.resolve(), base_dir)
            baseline = base_dir / APP_NAME
        else:
            baseline = args.baseline_app.resolve()
        info = plistlib.loads((baseline / 'Contents/Info.plist').read_bytes())
        if info.get('CFBundleIdentifier') != 'local.ypp.publisher':
            raise ValueError('基线应用身份不匹配')
        run('/usr/bin/codesign', '--verify', '--deep', '--strict', baseline)
        app = stage / 'package' / APP_NAME
        app.parent.mkdir()
        shutil.copytree(baseline, app, symlinks=True)
        resources = app / 'Contents/Resources'
        shutil.rmtree(resources / 'payload')
        shutil.copytree(SOURCE / 'Resources/payload', resources / 'payload')
        for name in ('bootstrap.py', 'runtime_upgrade.py', 'update_install.py', 'update-config.json', 'dependency-sources.json'):
            shutil.copy2(SOURCE / 'Resources' / name, resources / name)
        shutil.copy2(SOURCE / 'Info.plist', app / 'Contents/Info.plist')
        for p in (resources / 'payload').rglob('*'):
            if p.is_file() and (p.name.endswith(('.sqlite3', '.pyc')) or p.name.startswith('.')):
                raise ValueError('程序目录含运行数据或隐藏文件：' + str(p))
        run('/usr/bin/codesign', '--force', '--deep', '--sign', '-', app)
        run('/usr/bin/codesign', '--verify', '--deep', '--strict', app)
        # Initialize only in a temporary data directory; do not start any services.
        python = resources / 'runtime' / ('arm64' if os.uname().machine == 'arm64' else 'x86_64') / 'python/bin/python3'
        env = {**os.environ, 'YPP_APP_DATA': str(stage / 'isolated-data'),
               'YPP_DASHBOARD_PORT': '19741', 'PYTHONDONTWRITEBYTECODE': '1'}
        run(python, resources / 'bootstrap.py', '--init-only', env=env)
        for name in ('material_rules.py', 'scan_materials.py'):
            if not (stage / 'isolated-data' / name).is_file():
                raise ValueError('初始化缺少新版文件：' + name)
        archive = out / f'YouTubePublisher-Mac-{VERSION}.zip'
        zip_app(app, archive)
        image_dir = stage / 'dmg'; image_dir.mkdir()
        shutil.copytree(app, image_dir / APP_NAME, symlinks=True)
        (image_dir / 'Applications').symlink_to('/Applications')
        disk = out / f'YouTubePublisher-Mac-{VERSION}.dmg'
        run('/usr/bin/hdiutil', 'create', '-ov', '-volname', f'YouTube发布工作台 {VERSION}',
            '-srcfolder', image_dir, '-format', 'UDZO', disk)
        metadata = {
            'version': VERSION,
            'url': f'https://github.com/waltertech/youtube-publisher-releases/releases/download/v{VERSION}/{archive.name}',
            'sha256': digest(archive), 'size': archive.stat().st_size,
            'notes': '展示全部排队任务；并行任务独立读取上传进度，标记过期进度并区分处理中百分比；任务预览展示草稿或正式发布类型。',
            'minimum_macos': '12.0'}
        (out / 'update.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        (out / 'BUILD-INFO.json').write_text(json.dumps({
            'version': VERSION, 'architectures': ['arm64', 'x86_64'],
            'launcher': 'Unmodified compiled universal launcher from installed 1.1.10 baseline; launcher Swift sources unavailable',
            'launcher_sha256': digest(app / 'Contents/MacOS/YouTubePublisher'),
            'baseline_version': info.get('CFBundleShortVersionString'),
            'codesign': 'ad-hoc; verified deep/strict', 'notarized': False,
            'bootstrap_init_only': 'passed using isolated data directory',
            'online_update_signature': 'pending original publisher signing key'}, ensure_ascii=False, indent=2) + '\n')
        checks = [archive, disk, out / 'update.json', out / 'BUILD-INFO.json']
        (out / 'SHA256SUMS.txt').write_text(''.join(digest(p) + '  ' + p.name + '\n' for p in checks))
        print('BUILT', archive, disk, flush=True)


if __name__ == '__main__':
    main()
