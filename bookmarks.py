import json
import os

_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bookmarks.json')


def _load():
    try:
        with open(_FILE, encoding='utf-8') as f:
            data = json.load(f)
        # Defensive: drop any malformed entries (hand-edited file, version skew)
        return [e for e in data
                if isinstance(e, dict) and 'book' in e and 'chapter' in e]
    except Exception:
        return []


def _save(data):
    try:
        with open(_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f'[bookmarks] {e}')


def get_all():
    return _load()


def add(book, chapter, verse=None):
    data = _load()
    label = f'{book} {chapter}' + (f':{verse}' if verse else '')
    for e in data:
        if e.get('book') == book and e.get('chapter') == chapter and e.get('verse') == verse:
            return False
    data.insert(0, {'book': book, 'chapter': chapter, 'verse': verse, 'label': label})
    _save(data)
    return True


def remove(index):
    data = _load()
    if 0 <= index < len(data):
        data.pop(index)
        _save(data)
