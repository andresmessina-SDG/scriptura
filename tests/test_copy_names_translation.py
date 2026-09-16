"""Copied verses name the translation, never its internal id.

1.6.2 fixed exports that signed an eBible text `eBible: engwebp`. The two
copy paths built the same line on their own and kept the id: a selection
copied with Ctrl+C, and Copy on the verse menu.
"""

import types

import annotation_dialogs
import content
import ebible_bridge
import pane
import sword_bridge

KEY = ebible_bridge.PREFIX + 'engwebp'


class _Clipboard:
    text = None

    def set(self, text):
        self.text = text


class _View:
    def __init__(self):
        self.clipboard = _Clipboard()

    def get_clipboard(self):
        return self.clipboard

    def stop_emission_by_name(self, _name):
        pass


def _name_it(monkeypatch):
    monkeypatch.setattr(content, 'type_key', lambda m: 'ebible')
    monkeypatch.setattr(sword_bridge, 'display_name',
                        lambda m: 'World English Bible')


def test_the_verse_menu_copy_names_the_translation(monkeypatch):
    _name_it(monkeypatch)
    monkeypatch.setattr(content, 'load_chapter',
                        lambda *a: [(16, 'For God so loved the world')])
    fake = types.SimpleNamespace(module=KEY, book='John', chapter=3,
                                 view=_View(), _on_toast=None)
    popover = types.SimpleNamespace(popdown=lambda: None)
    annotation_dialogs.copy_verse(fake, [16], popover)
    first = fake.view.clipboard.text.splitlines()[0]
    assert first.endswith('(World English Bible)') and 'eBible' not in first


def test_a_copied_selection_names_the_translation(monkeypatch):
    _name_it(monkeypatch)
    buffer = types.SimpleNamespace(
        get_selection_bounds=lambda: (0, 1),
        get_text=lambda s, e, h: 'For God so loved the world')
    fake = types.SimpleNamespace(_module=KEY, _book='John', _chapter=3,
                                 _buffer=buffer,
                                 _verses_in_range=lambda s, e: [16])
    view = _View()
    pane.BiblePane._on_copy_clipboard(fake, view)
    first = view.clipboard.text.splitlines()[0]
    assert first.endswith('(World English Bible)') and 'eBible' not in first

