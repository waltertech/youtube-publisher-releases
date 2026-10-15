"""User-configured filename matching; one matching file per material role."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PATH = ROOT / '素材识别设置.json'
DEFAULTS = {'copy_keywords': ['发布文案', '新文案'], 'cover_keywords': ['封面', 'cover'], 'fallback_description': ''}
EXTENSIONS = {'copy': {'.txt'}, 'cover': {'.jpg', '.jpeg', '.png'}}


def validate(value):
    if not isinstance(value, dict):
        raise ValueError('素材识别设置格式无效')
    result = {}
    for key, label in (('copy_keywords', '文案'), ('cover_keywords', '封面')):
        words = value.get(key)
        if not isinstance(words, list) or not 1 <= len(words) <= 50:
            raise ValueError(label + '关键词需要填写 1–50 项')
        clean = []
        for word in words:
            if not isinstance(word, str) or not word.strip() or len(word.strip()) > 64:
                raise ValueError(label + '关键词不能为空，且每项最多 64 个字符')
            word = word.strip()
            if any(c in word for c in '\r\n/\\\0'):
                raise ValueError(label + '关键词不能包含换行或路径分隔符')
            if word.casefold() not in {w.casefold() for w in clean}:
                clean.append(word)
        result[key] = clean
    fallback = value.get('fallback_description', '')
    if not isinstance(fallback, str) or len(fallback) > 5000:
        raise ValueError('兜底详情内容需要是文本，最多 5000 个字符')
    result['fallback_description'] = fallback.strip()
    return result


def read():
    return validate(json.loads(PATH.read_text(encoding='utf-8')) if PATH.exists() else DEFAULTS)


def save(value):
    result = validate(value)
    temp = PATH.with_suffix('.tmp')
    temp.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(PATH)
    return result


def matches(folder, role, rules):
    words = rules[role + '_keywords']
    return sorted(p for p in folder.iterdir()
                  if p.is_file() and not p.name.startswith('.')
                  and p.suffix.casefold() in EXTENSIONS[role]
                  and any(word.casefold() in p.stem.casefold() for word in words))
