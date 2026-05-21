import json
import os
import threading

_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'settings.json')
_defaults = {
    'font_size':          12.5,
    'font_family':        'serif',
    'line_spacing':       1.6,
    'font_bold':          False,
    'font_justify':       False,
    'reading_width':      720,
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
    'pane1_top_verse':    None,
    'pane2_top_verse':    None,
    'recent_passages':    [],
    # Per-pane dict: {module_name: last-read TreeKey path}. Keeps the
    # user's place across module switches and app restarts so genbooks
    # don't always re-open at the first entry.
    'pane1_genbook_entries': {},
    'pane2_genbook_entries': {},
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


# ── Debounced save ───────────────────────────────────────────────────────────
# Writes used to fire on every put(), which under bursts (Ctrl+scroll font
# adjustment, recent_passages on every navigation) meant many small full-file
# rewrites in quick succession. The debounce coalesces a burst into a single
# write 500ms after the last put. flush() forces an immediate synchronous
# write — called from close-request so nothing is lost on exit.

_SAVE_DEBOUNCE_S = 0.5
_save_timer = None
_save_lock = threading.Lock()


def _save_now():
    """Synchronous write. Snapshots _cache under the lock to avoid the
    'dictionary changed size during iteration' race if a put() lands
    mid-serialise."""
    with _save_lock:
        snapshot = dict(_cache) if _cache is not None else {}
    try:
        with open(_FILE, 'w', encoding='utf-8') as f:
            json.dump(snapshot, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f'[settings] {e}')


def _on_debounce_fire():
    global _save_timer
    with _save_lock:
        _save_timer = None
    _save_now()


def _schedule_save():
    global _save_timer
    with _save_lock:
        if _save_timer is not None:
            _save_timer.cancel()
        _save_timer = threading.Timer(_SAVE_DEBOUNCE_S, _on_debounce_fire)
        _save_timer.daemon = True
        _save_timer.start()


def flush():
    """Cancel any pending debounce timer and write synchronously. Call
    this from close-request before the process exits — otherwise a recent
    put() may still be waiting for its debounce window when the GLib loop
    stops, and the change is lost."""
    global _save_timer
    with _save_lock:
        if _save_timer is not None:
            _save_timer.cancel()
            _save_timer = None
    _save_now()


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
    _schedule_save()
