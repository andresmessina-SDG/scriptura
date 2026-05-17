import json
import os

ANNOTATIONS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'annotations.json')

_cache = None


def _load():
    global _cache
    if _cache is not None:
        return _cache
    if not os.path.exists(ANNOTATIONS_FILE):
        _cache = {}
        return _cache
    try:
        with open(ANNOTATIONS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        # Corrupted file producing a non-dict — start over rather than crash.
        _cache = data if isinstance(data, dict) else {}
    except Exception:
        _cache = {}
    return _cache


def _save(data):
    global _cache
    _cache = data
    try:
        with open(ANNOTATIONS_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f'[annotations] Failed to save: {e}')

def get_annotations(module, book, chapter):
    data = _load()
    key = f"{module}/{book}/{chapter}"
    return data.get(key, {})

def save_highlight(module, book, chapter, verse, color):
    data = _load()
    key = f"{module}/{book}/{chapter}"
    if key not in data: data[key] = {}
    
    # Migrate old string data to dict if necessary
    vkey = str(verse)
    if vkey not in data[key] or not isinstance(data[key][vkey], dict):
        old_val = data[key].get(vkey)
        data[key][vkey] = {'highlight': old_val if isinstance(old_val, str) else None}
    
    data[key][vkey]['highlight'] = color
    _save(data)

def save_underline(module, book, chapter, verse, enabled):
    data = _load()
    key = f"{module}/{book}/{chapter}"
    if key not in data: data[key] = {}
    
    vkey = str(verse)
    if vkey not in data[key] or not isinstance(data[key][vkey], dict):
        old_val = data[key].get(vkey)
        data[key][vkey] = {'highlight': old_val if isinstance(old_val, str) else None}
    
    data[key][vkey]['underline'] = enabled
    _save(data)

def save_note(module, book, chapter, verse, text):
    data = _load()
    key = f"{module}/{book}/{chapter}"
    if key not in data: data[key] = {}

    vkey = str(verse)
    if vkey not in data[key] or not isinstance(data[key][vkey], dict):
        old_val = data[key].get(vkey)
        data[key][vkey] = {'highlight': old_val if isinstance(old_val, str) else None}

    data[key][vkey]['note'] = text
    _save(data)


def _ensure_verse_dict(data, key, vkey):
    if key not in data:
        data[key] = {}
    if vkey not in data[key] or not isinstance(data[key][vkey], dict):
        old_val = data[key].get(vkey)
        data[key][vkey] = {'highlight': old_val if isinstance(old_val, str) else None}


def save_tags(module, book, chapter, verse, tags):
    data = _load()
    key = f"{module}/{book}/{chapter}"
    _ensure_verse_dict(data, key, str(verse))
    # Coerce to strings before stripping — defensive against None / non-string
    # entries that can sneak in from corrupt JSON or tests.
    data[key][str(verse)]['tags'] = [
        str(t).strip() for t in tags if t is not None and str(t).strip()
    ]
    _save(data)


def get_all_tags():
    tags = set()
    for verses in _load().values():
        for anno in verses.values():
            if isinstance(anno, dict):
                tags.update(anno.get('tags', []))
    return sorted(tags)


def _chapter_note_data(raw):
    """Normalise chapter_note storage: string (old) or dict (new) → dict."""
    if isinstance(raw, str):
        return {'note': raw, 'tags': []}
    if isinstance(raw, dict):
        return {'note': raw.get('note', ''), 'tags': raw.get('tags', [])}
    return None


def get_chapter_note(module, book, chapter):
    raw = _load().get(f"{module}/{book}/{chapter}", {}).get('chapter_note')
    d = _chapter_note_data(raw)
    return d['note'] if d and d['note'].strip() else None


def get_chapter_note_data(module, book, chapter):
    raw = _load().get(f"{module}/{book}/{chapter}", {}).get('chapter_note')
    return _chapter_note_data(raw)


def save_chapter_note(module, book, chapter, text):
    data = _load()
    key = f"{module}/{book}/{chapter}"
    if key not in data:
        data[key] = {}
    existing = _chapter_note_data(data[key].get('chapter_note'))
    tags = existing['tags'] if existing else []
    if text.strip() or tags:
        data[key]['chapter_note'] = {'note': text, 'tags': tags}
    else:
        data[key].pop('chapter_note', None)
    _save(data)


def save_chapter_note_tags(module, book, chapter, tags):
    data = _load()
    key = f"{module}/{book}/{chapter}"
    if key not in data:
        data[key] = {}
    existing = _chapter_note_data(data[key].get('chapter_note'))
    note = existing['note'] if existing else ''
    if note.strip() or tags:
        data[key]['chapter_note'] = {'note': note, 'tags': tags}
    else:
        data[key].pop('chapter_note', None)
    _save(data)


def delete_annotation(module, book, chapter, verse):
    """Remove all annotation data for a verse. verse=None removes the chapter note."""
    data = _load()
    key = f"{module}/{book}/{chapter}"
    if key not in data:
        return
    if verse is None:
        data[key].pop('chapter_note', None)
    else:
        data[key].pop(str(verse), None)
    _save(data)
