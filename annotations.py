import json
import os

import paths

ANNOTATIONS_FILE = paths.annotations_path()

_cache = None
_load_failed = False  # Set if an existing file failed to parse; the
                      # window reads this once at startup to surface a toast.


def load_failed():
    _load()  # ensure load was attempted before we read the flag
    return _load_failed


def _load():
    global _cache, _load_failed
    if _cache is not None:
        return _cache
    if not os.path.exists(ANNOTATIONS_FILE):
        _cache = {}
        return _cache
    try:
        with open(ANNOTATIONS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        # Corrupted file producing a non-dict — start over rather than crash.
        if isinstance(data, dict):
            _cache = data
        else:
            _cache = {}
            _load_failed = True
    except Exception as e:
        print(f'[annotations] load failed, using defaults: {e}')
        _cache = {}
        _load_failed = True
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


def get_tag_counts():
    """Return {tag: count} across every verse annotation and chapter note."""
    counts = {}
    for verses in _load().values():
        for anno in verses.values():
            if not isinstance(anno, dict):
                continue
            for t in anno.get('tags', []) or []:
                if isinstance(t, str) and t.strip():
                    counts[t] = counts.get(t, 0) + 1
    return counts


def rename_tag(old, new):
    """Rename tag `old` → `new` across every annotation. If `new` already
    sits on the same annotation as `old`, the result is deduped, so this
    doubles as a merge. No-op when either side is empty or the names match."""
    old = (old or '').strip()
    new = (new or '').strip()
    if not old or not new or old == new:
        return
    data = _load()
    changed = False
    for verses in data.values():
        for anno in verses.values():
            if not isinstance(anno, dict):
                continue
            tags = anno.get('tags')
            if not tags or old not in tags:
                continue
            seen = set()
            out = []
            for t in tags:
                if not isinstance(t, str):
                    continue
                replaced = new if t == old else t
                if replaced not in seen:
                    seen.add(replaced)
                    out.append(replaced)
            anno['tags'] = out
            changed = True
    if changed:
        _save(data)


def delete_tag(tag):
    """Remove `tag` from every annotation it appears on. Notes/highlights
    are untouched."""
    tag = (tag or '').strip()
    if not tag:
        return
    data = _load()
    changed = False
    for verses in data.values():
        for anno in verses.values():
            if not isinstance(anno, dict):
                continue
            tags = anno.get('tags')
            if not tags or tag not in tags:
                continue
            anno['tags'] = [t for t in tags if t != tag]
            changed = True
    if changed:
        _save(data)


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
