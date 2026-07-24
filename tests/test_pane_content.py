"""Dispatch behaviour of the pane content strategies (no GTK needed)."""
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pane_content


class _Reader:
    """Records the calls the strategies route to a pane's reader."""

    def __init__(self):
        self.calls = []

    def render_for(self, *args):
        self.calls.append(('render_for', args))

    def render(self):
        self.calls.append(('render', ()))

    def select_verse(self, verse):
        self.calls.append(('select_verse', (verse,)))

    def apply_font_size(self, pt):
        self.calls.append(('apply_font_size', (pt,)))


def _fake_pane():
    p = types.SimpleNamespace(
        _book='John', _chapter=3, _selected_verse=None, _module='TAGNT',
        _catena=_Reader(), _imagery=_Reader(), _archaeology=_Reader(),
        _interlinear=_Reader())
    return p


def test_build_keys_match_the_registry_card_modes():
    p = _fake_pane()
    contents = pane_content.build(p)
    assert set(contents) == {'imagery', 'catena', 'archaeology', 'interlinear'}
    assert {k: c.stack_child for k, c in contents.items()} == {
        'imagery': 'imagery', 'catena': 'catena',
        'archaeology': 'archaeology', 'interlinear': 'interlinear'}


def test_card_render_defaults_to_verse_one():
    p = _fake_pane()
    c = pane_content.build(p)
    c['imagery'].render()
    c['catena'].render()
    assert p._imagery.calls == [('render_for', ('John', 3, 1))]
    assert p._catena.calls == [('render_for', ('John', 3, 1))]


def test_interlinear_render_passes_module_and_lighter_on_verse():
    p = _fake_pane()
    c = pane_content.build(p)['interlinear']
    c.render()
    assert p._interlinear.calls == [('render_for', ('TAGNT', 'John', 3, 1))]
    p._interlinear.calls.clear()
    c.on_verse(9)
    # on_verse moves the highlight only — no full re-render.
    assert p._selected_verse == 9
    assert p._interlinear.calls == [('select_verse', (9,))]


def test_card_on_verse_records_and_rerenders():
    p = _fake_pane()
    pane_content.build(p)['catena'].on_verse(7)
    assert p._selected_verse == 7
    assert p._catena.calls == [('render_for', ('John', 3, 7))]


def test_archaeology_is_standalone_not_verse_keyed():
    p = _fake_pane()
    c = pane_content.build(p)['archaeology']
    c.render()
    c.on_verse(5)  # no-op — standalone document
    assert p._archaeology.calls == [('render', ())]
    assert p._selected_verse is None


def test_font_size_scales_only_the_document_modes():
    p = _fake_pane()
    contents = pane_content.build(p)
    for mode in contents.values():
        mode.apply_font_size(18)
    assert p._catena.calls == [('apply_font_size', (18,))]
    assert p._archaeology.calls == [('apply_font_size', (18,))]
    assert p._imagery.calls == []       # card views don't re-scale
    assert p._interlinear.calls == []
