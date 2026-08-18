"""The books outside the 66, and the silent lie that makes them dangerous.

A SWORD VerseKey does not fail on a book its versification has never heard
of — it *clamps* to that versification's last book. Asking for Tobit reads
back Revelation 1 under KJV, 2 Chronicles 1 under MT, Laodiceans 1 under
Vulg. Nothing raises, nothing is empty, and the wrong chapter arrives under
the heading that was asked for. These tests hold the guards that catch it.

They use the real Sword library for the versification behaviour (that is
the thing under test) and a fake module for the module's own answer, so
nothing here depends on which modules are installed.
"""

import pytest

import settings
import sword_bridge
import window


class _FakeBibleMod:
    """SWModule stand-in: a versification, and a set of OSIS books it holds."""

    def __init__(self, v11n, osis_books=()):
        self._v11n = v11n
        self._books = set(osis_books)

    def getConfigEntry(self, key):
        return self._v11n if key == 'Versification' else None

    def hasEntry(self, vk):
        return str(vk.getOSISRef()).split('.')[0] in self._books


def _patch_mgr(monkeypatch, mods):
    class _FakeMgr:
        def getModule(self, name):
            return mods.get(name)
    monkeypatch.setattr(sword_bridge, 'mgr', lambda: _FakeMgr())
    sword_bridge._module_dc.clear()


# ── The clamp itself, so the guards below have something to stand on ─────────

def test_a_verse_key_clamps_an_unknown_book_instead_of_failing():
    """The defect this whole module exists for. If this ever starts raising
    or returning empty, the guards can be simplified — until then they are
    the only thing between a reader and Revelation under a Tobit heading."""
    import Sword
    for v11n, book, clamped_to in (('KJV', 'Tobit', 'Rev'),
                                   ('MT', 'Tobit', '2Chr'),
                                   ('Vulg', '4 Maccabees', 'EpLao')):
        vk = Sword.VerseKey()
        vk.setVersificationSystem(v11n)
        vk.setText(f'{book} 1:1')
        assert str(vk.getOSISRef()).split('.')[0] == clamped_to


# ── module_books ─────────────────────────────────────────────────────────────

def test_a_66_book_module_reports_no_deuterocanon(monkeypatch):
    _patch_mgr(monkeypatch, {'ESV': _FakeBibleMod('KJV')})
    assert sword_bridge.module_books('ESV') == ()


def test_a_hebrew_module_is_not_fooled_by_its_own_clamp(monkeypatch):
    """MT clamps to 2 Chronicles, so a naive text probe found 'Tobit' in
    OSHB — nineteen books of it — because 2 Chronicles 1:1 is not empty."""
    _patch_mgr(monkeypatch, {'OSHB': _FakeBibleMod('MT', ['Gen', '2Chr'])})
    assert sword_bridge.module_books('OSHB') == ()


def test_a_versification_that_knows_a_book_is_not_enough(monkeypatch):
    """RusSynodalLIO's key addresses all twelve and the module answers
    every one of them with nothing. The versification is not the module."""
    _patch_mgr(monkeypatch, {'LIO': _FakeBibleMod('Synodal', ['Gen'])})
    assert sword_bridge.module_books('LIO') == ()


def test_a_module_that_holds_them_reports_them_in_canon_order(monkeypatch):
    _patch_mgr(monkeypatch, {
        'KJVA': _FakeBibleMod('KJVA', ['Tob', 'Jdt', 'Wis', 'Sir', '1Macc'])})
    assert sword_bridge.module_books('KJVA') == (
        'Tobit', 'Judith', 'Wisdom', 'Sirach', '1 Maccabees')


def test_a_book_outside_the_versification_is_dropped_even_when_held(monkeypatch):
    """4 Maccabees is not in Vulg, so its key lands on Laodiceans — which
    the Vulgate does hold. Only the OSIS check tells the two apart."""
    _patch_mgr(monkeypatch, {
        'Vulgate': _FakeBibleMod('Vulg', ['Tob', 'EpLao'])})
    assert sword_bridge.module_books('Vulgate') == ('Tobit',)


def test_module_has_book_grants_the_66_without_asking(monkeypatch):
    _patch_mgr(monkeypatch, {'ESV': _FakeBibleMod('KJV')})
    assert sword_bridge.module_has_book('ESV', 'Genesis')
    assert sword_bridge.module_has_book('ESV', 'Revelation')
    assert not sword_bridge.module_has_book('ESV', 'Tobit')


# ── The guards that use it ───────────────────────────────────────────────────

def test_load_chapter_refuses_a_book_the_module_lacks(monkeypatch):
    """One guard for every reader of a chapter — the panes, search, export
    and presentation all come through here."""
    monkeypatch.setattr(sword_bridge, 'module_has_book', lambda m, b: False)
    assert sword_bridge.load_chapter('ESV', 'Tobit', 1) == []


def test_chapter_count_does_not_answer_with_the_clamped_books_count():
    """Revelation has 22 chapters and Tobit has 14. A key with no Tobit
    would have offered 22 of them in the chapter grid."""
    assert sword_bridge.chapter_count('Tobit') == 1
    assert sword_bridge.chapter_count('Genesis') == 50


# ── The two copies of the list ───────────────────────────────────────────────

def test_the_two_book_lists_agree():
    """window.DEUTEROCANON exists to mark the names for translation and
    sword_bridge.DEUTEROCANON to check them against a module. They are the
    same list written twice, and drift would show as a book that navigates
    but never renders."""
    assert window.DEUTEROCANON == sword_bridge.DEUTEROCANON


def test_every_deuterocanonical_book_has_an_osis_name():
    assert set(sword_bridge.DEUTEROCANON) == set(sword_bridge._DC_OSIS)


def test_laodiceans_is_not_offered():
    """It is the last book of the Vulg versification, which is where every
    unknown name lands, so its presence could never be told from a miss."""
    assert 'Laodiceans' not in sword_bridge.DEUTEROCANON


def test_no_deuterocanonical_name_collides_with_the_66():
    assert not set(sword_bridge.DEUTEROCANON) & set(sword_bridge._ALL_BOOKS)


# ── nav_books ────────────────────────────────────────────────────────────────

def test_nav_books_is_the_66_by_default(monkeypatch):
    monkeypatch.setattr(settings, 'get',
                        lambda k, *a: False if k == 'show_deuterocanon' else None)
    assert window.nav_books() == window.BOOKS


def test_nav_books_appends_the_rest_after_revelation(monkeypatch):
    monkeypatch.setattr(settings, 'get',
                        lambda k, *a: True if k == 'show_deuterocanon' else None)
    books = window.nav_books()
    assert books[:66] == window.BOOKS
    assert books[65] == 'Revelation'
    assert books[66:] == window.DEUTEROCANON


def test_the_setting_ships_off():
    assert settings._defaults['show_deuterocanon'] is False


# ── What the other pane says ─────────────────────────────────────────────────

class _EmptyChapterPane:
    """Enough pane to run the empty-chapter status page."""

    from pane import BiblePane as _BP
    _display_empty_chapter = _BP._display_empty_chapter

    def __init__(self, module):
        self._module = module
        self.shown = None
        self._view = self
        self._buffer = self

    def _show_status_page(self, icon, title, description, action=None):
        self.shown = (title, description)

    # _display_empty_chapter ends by scrolling the view to the top.
    def get_start_iter(self):
        return None

    def scroll_to_iter(self, *_a):
        pass


def test_a_canon_miss_is_not_reported_as_missing_coverage():
    """The stock empty state says the module covers only one Testament and
    tells the reader to pick a Bible with full coverage. For Tobit in the
    ESV that names the wrong problem — a 66-book Bible is complete on its
    own terms."""
    pane = _EmptyChapterPane('ESV')
    pane._display_empty_chapter('Tobit', 1)
    title, body = pane.shown
    assert title == 'Tobit 1'
    assert '66 books' in body
    assert 'coverage' not in body


def test_a_real_coverage_gap_still_says_so():
    pane = _EmptyChapterPane('SBLGNT')
    pane._display_empty_chapter('Psalms', 23)
    _title, body = pane.shown
    assert 'Old or New Testament' in body


# ── chapter_count_in ─────────────────────────────────────────────────────────

def test_an_appendix_book_is_counted_against_the_module(monkeypatch):
    """Tobit has 14 chapters and Revelation has 22. Counting Tobit against
    the app-space key — which every caller used to do — offered a chapter
    grid of the wrong length, and clamped a restored Tobit 12 to Tobit 1."""
    _patch_mgr(monkeypatch, {'KJVA': _FakeBibleMod('KJVA', ['Tob'])})
    assert sword_bridge.chapter_count_in('KJVA', 'Tobit') == 14


def test_an_appendix_book_with_no_module_to_count_it_falls_back_to_one(monkeypatch):
    _patch_mgr(monkeypatch, {})
    assert sword_bridge.chapter_count_in(None, 'Tobit') == 1


def test_the_66_are_still_counted_in_app_space(monkeypatch):
    """The whole app addresses the 66 in KJV numbers — bookmarks, notes,
    cross-refs — so passing a module here must not switch them to its own
    numbering. Psalms under Vulg is the case that would show it."""
    _patch_mgr(monkeypatch, {'Vulgate': _FakeBibleMod('Vulg', ['Ps'])})
    assert sword_bridge.chapter_count_in('Vulgate', 'Psalms') == \
        sword_bridge.chapter_count('Psalms')


# ── The probe cache ──────────────────────────────────────────────────────────

def test_a_failed_probe_is_not_remembered_as_an_answer(monkeypatch):
    """Caching a raised probe would make one bad moment permanent for the
    session: Tobit would stay dim on a module that holds it."""
    def boom():
        raise RuntimeError('SWORD is not up yet')
    monkeypatch.setattr(sword_bridge, 'mgr', boom)
    sword_bridge._module_dc.clear()
    assert sword_bridge.module_books('KJVA') == ()

    _patch_mgr(monkeypatch, {'KJVA': _FakeBibleMod('KJVA', ['Tob'])})
    assert sword_bridge.module_books('KJVA') == ('Tobit',)


def test_an_unknown_module_is_a_real_answer_and_is_cached(monkeypatch):
    """An eBible id is not a SWORD module. 'no deuterocanon' is the right
    answer and re-probing it on every chooser open is waste."""
    calls = []

    class _CountingMgr:
        def getModule(self, name):
            calls.append(name)
            return None
    monkeypatch.setattr(sword_bridge, 'mgr', lambda: _CountingMgr())
    sword_bridge._module_dc.clear()
    assert sword_bridge.module_books('eBible: spabes') == ()
    assert sword_bridge.module_books('eBible: spabes') == ()
    assert len(calls) == 1


# ── Stepping over the books a module does not carry ──────────────────────────

def _nav(holds, monkeypatch):
    """A NavigationController whose panes hold exactly `holds`."""
    import types
    import navigation
    monkeypatch.setattr(settings, 'get',
                        lambda k, *a: True if k == 'show_deuterocanon' else None)
    nav = navigation.NavigationController(types.SimpleNamespace())
    nav._book_module = lambda b: 'M' if b in holds else None
    return nav


def test_stepping_skips_the_books_the_module_lacks(monkeypatch):
    """The Vulgate carries Baruch and 1 Maccabees but not the three books
    listed between them, so a plain +1 left next-book dead on Baruch with
    half the appendix still ahead."""
    holds = set(window.BOOKS) | {'Baruch', '1 Maccabees'}
    nav = _nav(holds, monkeypatch)
    assert nav._step_book('Baruch', 1) == '1 Maccabees'
    assert nav._step_book('1 Maccabees', -1) == 'Baruch'


def test_stepping_stops_at_the_end_rather_than_wrapping(monkeypatch):
    nav = _nav(set(window.BOOKS), monkeypatch)
    assert nav._step_book('Revelation', 1) is None
    assert nav._step_book('Genesis', -1) is None


def test_stepping_moves_one_book_inside_the_66(monkeypatch):
    """Every module answers for the 66, so nothing is skipped there."""
    nav = _nav(set(window.BOOKS), monkeypatch)
    assert nav._step_book('Genesis', 1) == 'Exodus'
    assert nav._step_book('Matthew', -1) == 'Malachi'


def test_stepping_off_revelation_reaches_the_appendix(monkeypatch):
    nav = _nav(set(window.BOOKS) | {'Tobit'}, monkeypatch)
    assert nav._step_book('Revelation', 1) == 'Tobit'
