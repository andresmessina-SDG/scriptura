"""Three faults on the paths into Compare and the word study, found
2026-09-26 on a fresh Flatpak install."""
from types import SimpleNamespace

import annotation_dialogs
import interlinear_data
import lexicon_panel
import window


def _word(verse, surface, strongs):
    return interlinear_data.Word(verse, 1, surface, '', '', strongs.split()[0],
                                 strongs, '', '', '')


def test_the_word_study_reads_the_interlinears_own_words(monkeypatch):
    """Without OSHB or MorphGNT the scan read the interlinear through
    `content`, which has no text for it: 0 occurrences for every word."""
    monkeypatch.setattr(interlinear_data, 'load_chapter', lambda n, b, c: [
        _word(1, 'וּמֹשֶׁ֗ה', 'H4872'), _word(1, 'הָיָ֥ה', 'H1961'),
        _word(2, 'בָּנִ֔י מִן', 'H1137 H4480'), _word(3, 'אֶת־', 'H853')])
    rows = lexicon_panel._scan_chapter(interlinear_data.HEBREW, 'Exodus', 3)
    assert [v for v, _h in rows] == [1, 2, 3]
    for strong, verses in (('H4872', [1]), ('H4480', [2]), ('H04480', [2])):
        pattern = lexicon_panel._scan_pattern(strong)
        assert [v for v, h in rows if pattern.search(h)] == verses
    assert lexicon_panel._make_verse_markup(rows[0][1], 'H4872') \
        == '<b>וּמֹשֶׁ֗ה</b> הָיָ֥ה'


def test_a_bible_is_still_read_through_content(monkeypatch):
    monkeypatch.setattr(lexicon_panel.content, 'load_chapter',
                        lambda m, b, c: [(1, 'text')])
    assert lexicon_panel._scan_chapter('KJV', 'John', 3) == [(1, 'text')]


class _View:
    def __init__(self, y):
        self._y = y

    def get_iter_location(self, _it):
        return SimpleNamespace(x=40, y=self._y)

    def buffer_to_window_coords(self, _w, x, y):
        return x, y

    def get_width(self):
        return 600

    def get_height(self):
        return 400


def test_compare_points_from_the_edge_at_a_verse_out_of_sight():
    """A verse scrolled away gave a rect thousands of pixels off, and GTK
    opened Compare in the window's top-left corner."""
    def rect(y):
        pane = SimpleNamespace(view=_View(y), _verse_ranges=lambda v: (0, 1))
        r = annotation_dialogs._verse_rect(pane, 16)
        return r.x, r.y
    assert rect(120) == (40, 120)
    assert rect(-6583) == (40, 0)
    assert rect(7237) == (40, 399)


class _Pane:
    def __init__(self, navigable, family=False):
        self._navigable = navigable
        self._is_family = family
        self._names = []
        self.module = 'X'

    def _is_verse_navigable(self):
        return self._navigable

    def get_visible(self):
        return True


def _offered_compare(pane):
    shown = {}
    win = SimpleNamespace(
        pane1=pane, pane2=_Pane(True),
        _family_card=SimpleNamespace(
            show=lambda *a, **kw: shown.update(kw), focus_start=lambda: None),
        _card_split=SimpleNamespace(set_show_sidebar=lambda v: None))
    window.BibleWindow.show_family_card(win, 'esv', pane)
    return shown['can_compare']


def test_the_card_offers_compare_only_beside_verses():
    """Beside an interlinear, Compare this verse only said to choose one."""
    assert _offered_compare(_Pane(True)) is True
    assert _offered_compare(_Pane(False)) is False
