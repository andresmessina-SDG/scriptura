"""An unreadable store must be set aside, not overwritten.

Every JSON store here loads into a cache, falls back to an empty cache
when the parse fails, and later writes that cache back over the file. So
a corrupt read used to destroy the only copy of the user's data on the
next save — while the startup toast told them "your file is preserved".
These tests hold that promise to the fire.
"""

import json

import pytest

import annotations
import bookmarks
import module_positions
import paths
import reading_plans
import settings

CORRUPT = '{"font_size": 18}\n{"trailing": "garbage"}'


# ── The helper ──────────────────────────────────────────────────────────────

def test_quarantine_moves_the_file_aside(tmp_path):
    f = tmp_path / 'store.json'
    f.write_text(CORRUPT)
    dest = paths.quarantine_unreadable(str(f))
    assert dest == str(tmp_path / 'store.json.corrupt')
    assert not f.exists()
    assert (tmp_path / 'store.json.corrupt').read_text() == CORRUPT


def test_quarantine_does_not_clobber_an_earlier_corruption(tmp_path):
    (tmp_path / 'store.json.corrupt').write_text('the first one')
    f = tmp_path / 'store.json'
    f.write_text(CORRUPT)
    dest = paths.quarantine_unreadable(str(f))
    assert dest is not None
    assert dest != str(tmp_path / 'store.json.corrupt')
    assert (tmp_path / 'store.json.corrupt').read_text() == 'the first one'
    assert open(dest).read() == CORRUPT


def test_a_third_corruption_in_the_same_second_keeps_the_second(tmp_path):
    """The timestamp suffix has one-second resolution. The test above only
    ever proved the promise for two corruptions; the third landed on the
    second's name and os.replace overwrote it silently."""
    f = tmp_path / 'store.json'
    kept = []
    for i in range(4):
        f.write_text(f'corruption {i}')
        dest = paths.quarantine_unreadable(str(f))
        assert dest is not None
        kept.append(dest)
    assert len(set(kept)) == 4, kept
    for i, dest in enumerate(kept):
        assert open(dest).read() == f'corruption {i}', dest


def test_quarantine_of_a_missing_file_is_a_no_op(tmp_path):
    assert paths.quarantine_unreadable(str(tmp_path / 'nope.json')) is None


def test_quarantine_failure_is_survivable(tmp_path, monkeypatch):
    """Best-effort: if the move fails the app must still start."""
    f = tmp_path / 'store.json'
    f.write_text(CORRUPT)

    def boom(*a):
        raise OSError('read-only filesystem')

    monkeypatch.setattr(paths.os, 'replace', boom)
    assert paths.quarantine_unreadable(str(f)) is None
    assert f.read_text() == CORRUPT  # untouched


# ── Per-store: corrupt contents survive the next save ───────────────────────

def test_settings_corrupt_file_survives_a_later_save(tmp_path, monkeypatch):
    f = tmp_path / 'settings.json'
    f.write_text(CORRUPT)
    monkeypatch.setattr(settings, '_FILE', str(f))
    monkeypatch.setattr(settings, '_cache', None)
    monkeypatch.setattr(settings, '_load_failed', False)
    monkeypatch.setattr(settings, '_save_timer', None)

    assert settings.get('font_size') == 12.5   # fell back to defaults
    assert settings.load_failed() is True
    settings.put('font_size', 20)
    settings.flush()                            # the write that used to destroy it

    assert (tmp_path / 'settings.json.corrupt').read_text() == CORRUPT
    assert json.loads(f.read_text())['font_size'] == 20
    if settings._save_timer is not None:
        settings._save_timer.cancel()


def test_annotations_corrupt_file_survives_a_later_save(tmp_path, monkeypatch):
    f = tmp_path / 'annotations.json'
    f.write_text(CORRUPT)
    monkeypatch.setattr(annotations, 'ANNOTATIONS_FILE', str(f))
    monkeypatch.setattr(annotations, '_cache', None)
    monkeypatch.setattr(annotations, '_load_failed', False)

    assert annotations.load_failed() is True
    annotations.save_highlight('KJV', 'John', 3, 16, 'yellow')

    assert (tmp_path / 'annotations.json.corrupt').read_text() == CORRUPT


def test_bookmarks_corrupt_file_survives_a_later_save(tmp_path, monkeypatch):
    f = tmp_path / 'bookmarks.json'
    f.write_text(CORRUPT)
    monkeypatch.setattr(bookmarks, '_FILE', str(f))
    monkeypatch.setattr(bookmarks, '_load_failed', False)

    assert bookmarks.load_failed() is True
    bookmarks.add('John', 3, 16)

    assert (tmp_path / 'bookmarks.json.corrupt').read_text() == CORRUPT


def test_reading_plans_corrupt_file_survives_a_later_save(tmp_path, monkeypatch):
    f = tmp_path / 'reading_plans.json'
    f.write_text(CORRUPT)
    monkeypatch.setattr(reading_plans, '_FILE', str(f))
    monkeypatch.setattr(reading_plans, '_cache', None)
    monkeypatch.setattr(reading_plans, '_load_failed', False)

    assert reading_plans.load_failed() is True

    assert (tmp_path / 'reading_plans.json.corrupt').read_text() == CORRUPT


def test_module_positions_corrupt_file_is_set_aside(tmp_path, monkeypatch):
    f = tmp_path / 'module_positions.json'
    f.write_text(CORRUPT)
    monkeypatch.setattr(module_positions, '_FILE', str(f))
    monkeypatch.setattr(module_positions, '_state', {})
    monkeypatch.setattr(module_positions, '_load_failed', False)

    module_positions._load()

    assert module_positions.load_failed() is True
    assert (tmp_path / 'module_positions.json.corrupt').read_text() == CORRUPT


# ── Every store, every shape of "this isn't our data" ───────────────────────
#
# The tests above all feed CORRUPT, which is a JSON *syntax* error. Every store
# handled that from the start, so it cannot tell them apart — and it did not:
# module_positions was silently missing its wrong-type guard while these passed.
# The two shapes below are the ones that distinguish them.

#: (module, file attribute, what a well-formed file of the WRONG type looks
#: like for this store). Four hold an object, bookmarks holds an array.
_STORES = [
    (settings, '_FILE', '[1, 2, 3]'),
    (annotations, 'ANNOTATIONS_FILE', '[1, 2, 3]'),
    (bookmarks, '_FILE', '{"not": "an array"}'),
    (reading_plans, '_FILE', '[1, 2, 3]'),
    (module_positions, '_FILE', '["KJV", "BSB"]'),
]

#: Valid JSON syntax the parser still cannot build: nested past the C scanner's
#: recursion limit. Raises RecursionError, which is neither ValueError nor
#: OSError — so a store catching only those two crashes on startup instead of
#: falling back, which is the failure this whole file exists to prevent.
TOO_DEEP = '[' * 200_000 + ']' * 200_000


_STORE_IDS = [m.__name__ for m, _a, _w in _STORES]


def _reload(monkeypatch, mod, attr, path):
    """Point `mod` at `path` and make it read it, whatever its cache shape.

    Every global goes through monkeypatch, never a bare setattr: these modules
    are imported once for the whole session, and a cache left pointing at a
    tmp_path outlives the test that made it.
    """
    monkeypatch.setattr(mod, attr, path)
    for name, value in (('_cache', None), ('_state', {}),
                        ('_load_failed', False)):
        if hasattr(mod, name):
            monkeypatch.setattr(mod, name, value)
    mod._load()


@pytest.mark.parametrize('mod,attr,wrong_type', _STORES, ids=_STORE_IDS)
def test_a_well_formed_file_of_the_wrong_type_is_set_aside(
        mod, attr, wrong_type, tmp_path, monkeypatch):
    """`["KJV", "BSB"]` parses perfectly and is not this store's data. Without
    a type check it reads as "nothing to load": no flag, no toast, no
    quarantine — and the next save writes the empty cache over it."""
    f = tmp_path / 'store.json'
    f.write_text(wrong_type)
    _reload(monkeypatch, mod, attr, str(f))

    assert mod.load_failed() is True, 'the user is never told'
    assert (tmp_path / 'store.json.corrupt').read_text() == wrong_type


@pytest.mark.parametrize('mod,attr,_wrong', _STORES, ids=_STORE_IDS)
def test_json_too_deep_to_parse_falls_back_instead_of_raising(
        mod, attr, _wrong, tmp_path, monkeypatch):
    f = tmp_path / 'store.json'
    f.write_text(TOO_DEEP)

    _reload(monkeypatch, mod, attr, str(f))      # must not raise

    assert mod.load_failed() is True
    assert (tmp_path / 'store.json.corrupt').exists()


def test_the_startup_warning_names_every_store_that_can_fail(monkeypatch):
    """Quarantining a file the user is never told about is half a fix. Each
    store here has a `load_failed()`; `module_positions` had one that nothing
    called, so its positions vanished in silence."""
    import window

    for mod, _attr, _wrong in _STORES:
        monkeypatch.setattr(mod, 'load_failed', lambda: True)

    said = []

    class _Win:
        def _toast(self, text):
            said.append(text)

    window.BibleWindow._warn_on_load_failures(_Win())

    assert len(said) == 1
    # One name per store, so a sixth store cannot be wired in unnoticed.
    assert said[0].count(',') == len(_STORES) - 1, said[0]
    assert 'reading positions' in said[0]


# ── An unreadable file is not the same as an unparseable one ────────────────

@pytest.mark.parametrize('mod,attr', [
    (settings, '_FILE'),
    (bookmarks, '_FILE'),
    (reading_plans, '_FILE'),
])
def test_os_error_leaves_the_file_in_place(mod, attr, tmp_path, monkeypatch):
    """A permissions or I/O failure says nothing about the bytes. Moving
    the file there would quarantine a perfectly good store."""
    f = tmp_path / 'store.json'
    f.write_text('{"real": "data"}')
    monkeypatch.setattr(mod, attr, str(f))
    for name, value in (('_cache', None), ('_load_failed', False)):
        if hasattr(mod, name):
            monkeypatch.setattr(mod, name, value)

    def boom(*a, **k):
        raise PermissionError('nope')

    monkeypatch.setattr('builtins.open', boom)
    mod._load()

    monkeypatch.undo()
    assert f.read_text() == '{"real": "data"}'
    assert not (tmp_path / 'store.json.corrupt').exists()
