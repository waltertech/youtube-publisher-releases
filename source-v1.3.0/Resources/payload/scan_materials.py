"""Read publishing copy as data and resolve materials using filename rules."""
import json
import re
from pathlib import Path
from publisher import ROOT, Ledger
from local_settings import source
import material_rules

HEADINGS = re.compile(
    r'^\s*(发布标题|详情内容|YouTube\s+Studio\s*(?:[｜|]\s*)?(?:Tags|Text)|Hashtags)\s*[:：]?\s*$',
    re.IGNORECASE)


def parse_copy(text, fallback_description=""):
    """Description wins as a whole; Hashtags are only an empty-description fallback."""
    sections = {'title': [], 'description': [], 'tags': [], 'hashtags': []}
    current = None
    seen = set()
    for line in text.lstrip('\ufeff').splitlines():
        match = HEADINGS.fullmatch(line)
        if match:
            heading = match[1].casefold()
            current = ('title' if heading == '发布标题' else
                       'description' if heading == '详情内容' else
                       'hashtags' if heading == 'hashtags' else 'tags')
            if current in seen:
                raise ValueError('文案段落重复：' + match[1])
            seen.add(current)
        elif current:
            sections[current].append(line)
    values = {key: '\n'.join(lines).strip() for key, lines in sections.items()}
    values['raw_description'] = values['description']
    values['description_source'] = ('详情内容' if values['description'] else
                                    'Hashtags' if values['hashtags'] else '兜底配置' if fallback_description.strip() else '空')
    values['description'] = values['description'] or values['hashtags'] or fallback_description.strip()
    values['tags'] = [tag.strip() for tag in re.split(r'[,，\n]+', values['tags']) if tag.strip()]
    return values


def completeness_errors(item):
    errors = list(item.get('recognition_errors', []))
    for key, label in (('video', '视频'), ('thumbnail', '封面'), ('copy_file', '文案')):
        path = item.get(key)
        if not path or not Path(path).is_file():
            message = label + '文件未识别或不存在'
            if not any(label in error for error in errors):
                errors.append(message)
    if not item.get('title'):
        errors.append('“发布标题”段落为空或未识别')
    if not item.get('description'):
        errors.append('“详情内容”和“Hashtags”均为空，且未配置兜底详情内容')
    return errors


def discover(source_dir=None):
    source_dir = Path(source_dir) if source_dir else source()
    rules = material_rules.read()
    manifest = ROOT / '素材任务清单.json'
    previous = {p['video']: p for p in json.loads(manifest.read_text())} if manifest.exists() else {}
    rows = []
    for video in sorted(source_dir.rglob('*')):
        if (not video.is_file() or video.suffix.casefold() != '.mp4'
                or any(part.startswith('.') for part in video.relative_to(source_dir).parts)):
            continue
        folder = video.parent
        copies = material_rules.matches(folder, 'copy', rules)
        covers = material_rules.matches(folder, 'cover', rules)
        copy = copies[0] if len(copies) == 1 else None
        cover = covers[0] if len(covers) == 1 else None
        errors = []
        for candidates, label in ((copies, '文案'), (covers, '封面')):
            if not candidates:
                errors.append(label + '未匹配：检查文件名关键词及扩展名')
            elif len(candidates) > 1:
                errors.append(label + '匹配多个文件：' + '、'.join(p.name for p in candidates))
        prepared = previous.get(str(video), {}).get('thumbnail')
        if prepared and Path(prepared).is_file() and Path(prepared).parent == ROOT / '封面副本':
            cover = Path(prepared)
            errors = [e for e in errors if not e.startswith('封面')]
        parsed = {'title': '', 'description': '', 'tags': [], 'hashtags': '', 'description_source': '空', 'raw_description': ''}
        if copy:
            try:
                parsed = parse_copy(copy.read_text(encoding='utf-8-sig'), rules['fallback_description'])
            except (OSError, UnicodeError, ValueError) as exc:
                errors.append('文案读取或解析失败：' + str(exc))
        item = {'folder': str(folder), 'video': str(video),
                'thumbnail': str(cover) if cover else None,
                'copy_file': str(copy) if copy else None,
                **parsed, 'recognition_errors': errors}
        item['missing_reasons'] = completeness_errors(item)
        item['status'] = 'incomplete' if item['missing_reasons'] else 'ready'
        rows.append(item)
    return rows


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--refresh', action='store_true')
    args = parser.parse_args()
    rows = discover()
    (ROOT / '素材任务清单.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2))
    ledger = Ledger()
    try:
        ledger.refresh_materials(rows) if args.refresh else ledger.scan(rows)
    finally:
        ledger.db.close()
