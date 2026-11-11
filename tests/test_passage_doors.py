"""No passage door acts on a pane that is not verse-keyed.

The passage doors are the `…` button in the pane's toolbar, Ctrl+P, Ctrl+E,
Ctrl+Shift+C, and Ctrl+D, Ctrl+Shift+J and Ctrl+Shift+M, which bookmarked or
wrote about the header's last chapter over a resource that has none. Each used to ask "is this a Bible?" its own way, and most
never asked. Measured on 1.10.0 at John 3: Ctrl+P on a devotional printed
the whole module, 215,000 characters, titled "John 3"; on the Harmony it
printed "Text from GospelHarmony." and nothing else; and the `…` button
stayed on every resource and did nothing there.

`BiblePane._is_verse_navigable()` is the one question: Bibles and
commentaries, not devotionals. Stand-ins only, with the real methods
borrowed onto them, so this runs without a display.
"""
import itertools
import types

import pytest

from pane import BiblePane


# (label, module type, is a devotional). The module types are the ones
# `BiblePane._apply_module_change` sets.
VERSE_KEYED = [
    ('Bible', 'Biblical Texts', False),
    ('commentary', 'Commentaries', False),
]
NOT_VERSE_KEYED = [
    ('generic book', 'Generic Books', False),
    ('devotional', 'Lexicons / Dictionaries', True),
    ('dictionary', 'Lexicons / Dictionaries', False),
    ('catena', 'Historical Commentaries', False),
    ('imagery', 'Bible Imagery', False),
    ('Scripture in Stone', 'Scripture in Stone', False),
    ('Book of Generations', 'The Book of Generations', False),
    ('Creeds', 'The Creeds', False),
    ('Harmony', 'The Harmony of the Gospels', False),
    ('interlinear', 'Interlinear', False),
]


def _ids(rows):
    return [r[0] for r in rows]


_CHAPTERS = itertools.count(1)


class _Pane:
    _is_verse_navigable = BiblePane._is_verse_navigable

    def __init__(self, module_type, devotional=False, visible=True):
        self._module_type = module_type
        self._is_devotional = devotional
        self._is_family = False
        self._visible = visible
        self.book = 'John'
        self.chapter = next(_CHAPTERS)
        self.toasts = []
        self._on_toast = self.toasts.append

    def get_visible(self):
        return self._visible

    def current_verses(self):
        return [16]


def _window(pane1, pane2):
    import window

    class _Win:
        _compare_verse = window.BibleWindow._compare_verse
        _print_passage = window.BibleWindow._print_passage
        _export_passage = window.BibleWindow._export_passage
        _bible_pane_in_view = window.BibleWindow._bible_pane_in_view
        _bookmark_here = window.BibleWindow._bookmark_here
        _write_about_here = window.BibleWindow._write_about_here
        _sermon_about_here = window.BibleWindow._sermon_about_here

        def __init__(self):
            self.pane1, self.pane2 = pane1, pane2
            self.toasts = []
            self.calls = []

        def _save_bookmark(self, book, chapter):
            self.calls.append(('bookmark', book, chapter))

        # Ctrl+D saves the header's chapter, as the bookmark button's Add
        # row does; the pane it reaches stands in for the header here.
        def nav_books(self):
            return ['John']

        @property
        def book_drop(self):
            return types.SimpleNamespace(get_selected=lambda: 0)

        @property
        def chapter_drop(self):
            pane = self._bible_pane_in_view()
            return types.SimpleNamespace(get_selected=lambda: pane.chapter - 1)

        def _open_annotations(self, *a, **k):
            self.calls.append(('write', a, k))

        def _today_collect(self):
            return None

        def _pane_in_view(self):
            return self.pane1

        def _toast(self, message):
            self.toasts.append(message)
    return _Win()


@pytest.fixture
def doors(monkeypatch):
    """Each door's target recorded instead of a dialog opened."""
    import annotation_dialogs
    import export_dialog
    import passage_print
    calls = []
    monkeypatch.setattr(passage_print, 'print_passage',
                        lambda pane, verses: calls.append(('print', pane)))
    monkeypatch.setattr(export_dialog, 'export_passage',
                        lambda pane, verses: calls.append(('export', pane)))
    monkeypatch.setattr(annotation_dialogs, 'compare_translations',
                        lambda pane, verse: calls.append(('compare', pane)))
    return calls


_DOORS = ['_print_passage', '_export_passage', '_compare_verse',
          '_bookmark_here', '_write_about_here', '_sermon_about_here']


def _targets(win, doors):
    """The panes the door acted on; the write doors name a chapter, and
    each pane here is a different one so the chapter says which pane."""
    reached = [pane for _door, pane in doors]
    for call in win.calls:
        chapter = (call[2] if call[0] == 'bookmark' else
                   (call[1][0] if call[1] else call[2]['new_sermon'])
                   ['anchors'][0]['chapter'])
        reached += [p for p in (win.pane1, win.pane2) if p.chapter == chapter]
    return reached


@pytest.mark.parametrize('door', _DOORS)
@pytest.mark.parametrize('label,module_type,devotional', NOT_VERSE_KEYED,
                         ids=_ids(NOT_VERSE_KEYED))
def test_a_door_refuses_a_resource_alone_with_one_toast(
        doors, door, label, module_type, devotional):
    win = _window(_Pane(module_type, devotional),
                  _Pane('Biblical Texts', visible=False))
    getattr(win, door)()
    toasts = win.toasts + win.pane1.toasts
    assert doors == [] and win.calls == [] and len(toasts) == 1
    # The old words were only true beside the Family Tree.
    assert 'Family Tree' not in toasts[0]


@pytest.mark.parametrize('door', _DOORS)
@pytest.mark.parametrize('label,module_type,devotional', NOT_VERSE_KEYED,
                         ids=_ids(NOT_VERSE_KEYED))
def test_a_door_reaches_the_bible_beside_a_resource(
        doors, door, label, module_type, devotional):
    win = _window(_Pane(module_type, devotional), _Pane('Biblical Texts'))
    getattr(win, door)()
    assert _targets(win, doors) == [win.pane2]


@pytest.mark.parametrize('door', _DOORS)
def test_a_door_does_not_reach_a_devotional_beside_the_family_tree(
        doors, door):
    """With the Family Tree in pane 1, Ctrl+E exported from the devotional
    in pane 2: anything that was not the Family Tree counted as a Bible."""
    family = _Pane('The Bible Family Tree')
    family._is_family = True
    family._family_tree = types.SimpleNamespace(can_print=lambda: False)
    win = _window(family, _Pane('Lexicons / Dictionaries', devotional=True))
    getattr(win, door)()
    assert doors == [] and win.calls == []


@pytest.mark.parametrize('door', _DOORS)
@pytest.mark.parametrize('label,module_type,devotional', VERSE_KEYED,
                         ids=_ids(VERSE_KEYED))
def test_a_door_acts_on_a_verse_text(doors, door, label, module_type,
                                     devotional):
    win = _window(_Pane(module_type, devotional), _Pane('Biblical Texts'))
    getattr(win, door)()
    assert _targets(win, doors) == [win.pane1]


@pytest.mark.parametrize('door', _DOORS)
def test_a_door_does_not_reach_a_hidden_pane(doors, door):
    """A narrow window shows one pane. With pane 2 picked and the focus in
    the header, the doors used to act on the Bible hidden in pane 1."""
    win = _window(_Pane('Biblical Texts', visible=False),
                  _Pane('The Creeds'))
    getattr(win, door)()
    toasts = win.toasts + win.pane1.toasts + win.pane2.toasts
    assert doors == [] and win.calls == [] and len(toasts) == 1


@pytest.mark.parametrize('door', _DOORS)
def test_a_door_reaches_the_shown_bible_past_a_hidden_one(doors, door):
    win = _window(_Pane('Biblical Texts', visible=False),
                  _Pane('Biblical Texts'))
    getattr(win, door)()
    assert _targets(win, doors) == [win.pane2]


# ── The `…` button ─────────────────────────────────────────────────────────

class _Shown:
    def __init__(self):
        self.visible = None

    def set_visible(self, visible):
        self.visible = visible


def _chrome_pane(module_type, devotional):
    p = _Pane(module_type, devotional)
    p._is_genbook = module_type == 'Generic Books'
    p._passage_btn = _Shown()
    p._chapter_note_btn = _Shown()
    p._copy_chapter_btn = _Shown()
    p._search = types.SimpleNamespace(button=_Shown(), sync_mode=lambda book: None)
    p._genbook = types.SimpleNamespace(update_visibility=lambda on: None)
    p._update_sync_visible = lambda: None
    return p


@pytest.mark.parametrize('label,module_type,devotional',
                         VERSE_KEYED + NOT_VERSE_KEYED,
                         ids=_ids(VERSE_KEYED + NOT_VERSE_KEYED))
def test_the_passage_button_shows_only_on_a_verse_text(
        label, module_type, devotional):
    p = _chrome_pane(module_type, devotional)
    BiblePane._sync_chrome(p)
    keyed = (module_type, devotional) in [(t, d) for _l, t, d in VERSE_KEYED]
    assert p._passage_btn.visible is keyed
    # …and it moves with the rest of the verse-text chrome.
    assert p._chapter_note_btn.visible is keyed
    assert p._copy_chapter_btn.visible is keyed
    assert p._search.button.visible is (keyed or p._is_genbook)
