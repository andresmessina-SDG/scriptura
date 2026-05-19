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
    'window_width':       1100,
    'window_height':      700,
    'window_maximized':   False,
    'last_book':          None,
    'last_chapter':       None,
    'pane1_module':       None,
    'pane2_module':       None,
    'split_pane_mode':    True,
}
_cache = None
_load_failed = False  # Flipped if an existing file failed to parse.


def load_failed():
    if _cache is None:
        _load()
    return _load_failed


def _load():
    global _cache, _load_failed
    if not os.path.exists(_FILE):
        _cache = {}
        return
    try:
        with open(_FILE, encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, dict):
            _cache = data
        else:
            _cache = {}
            _load_failed = True
    except Exception as e:
        print(f'[settings] load failed, using defaults: {e}')
        _cache = {}
        _load_failed = True


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
