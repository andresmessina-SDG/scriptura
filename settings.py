import json
import os

_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'settings.json')
_defaults = {
    'font_size':          12.5,
    'font_family':        'serif',
    'line_spacing':       1.6,
    'font_bold':          False,
    'font_justify':       False,
    'text_color_light':   None,
    'text_color_dark':    None,
    'text_color_default': None,
    'color_scheme':       'default',
    'default_module':     None,
    'startup_devotional': None,
}
_cache = None


def _load():
    global _cache
    try:
        with open(_FILE, encoding='utf-8') as f:
            data = json.load(f)
        _cache = data if isinstance(data, dict) else {}
    except Exception:
        _cache = {}


def _save():
    try:
        with open(_FILE, 'w', encoding='utf-8') as f:
            json.dump(_cache, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f'[settings] {e}')


def get(key):
    global _cache
    if _cache is None:
        _load()
    return _cache.get(key, _defaults.get(key))


def put(key, value):
    global _cache
    if _cache is None:
        _load()
    _cache[key] = value
    _save()
