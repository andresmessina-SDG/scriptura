"""The interlinear's Variants chip.

With the chip off the reading stream shows as before; with it on, the
words other editions add appear in place in ⟦ ⟧, and the words the
editions disagree about carry their apparatus lines. Built against a
database of real TAGNT rows (John 1:18, the θεός / υἱός substitution).
"""
import time

import pytest

import interlinear_data as idata
from tests.test_interlinear_data import ROW_SUBSTITUTION, ROW_SIMPLE

ROW_ARTICLE = (
    'Jhn.1.18#05=ko\tὁ (ho)\tthe\tG3588=T-NSM\tὁ=the/this/who\tTyn+TR+Byz'
    '\t\t\tel\tthe\t#05»07:G2316\tG3588_a\t\t\t\t\t')
ROW_COMMON = (
    'Jhn.1.18#06=NKO\tμονογενὴς (monogenēs)\tonly begotten\tG3439=A-NSM\t'
    'μονογενής=unique\tNA28+NA27+Tyn+SBL+WH+Treg+TR+Byz\t\t\tunigénito\t'
    'unique\t#06\tG3439\t\t\t\t\t')


@pytest.fixture
def display():
    from gi.repository import Gdk, Gtk
    Gtk.init_check()
    if Gdk.Display.get_default() is None:
        pytest.skip('needs a display: builds real widgets')


@pytest.fixture
def greek_db(tmp_path, monkeypatch):
    raw = tmp_path / 'tagnt.txt'
    raw.write_text('\n'.join([ROW_SIMPLE, ROW_ARTICLE, ROW_COMMON,
                              ROW_SUBSTITUTION]) + '\n', encoding='utf-8')
    import urllib.request
    monkeypatch.setitem(idata._DB_FILES, idata.GREEK,
                        str(tmp_path / 'greek.sqlite'))
    monkeypatch.setitem(idata._MODULES[idata.GREEK], 'urls',
                        ['file://' + urllib.request.pathname2url(str(raw))])
    monkeypatch.setitem(idata._MODULES[idata.GREEK], 'min_words', 1)
    monkeypatch.setattr(idata, '_migrated', set())
    idata.download_and_build(idata.GREEK)


def _pump_until(predicate, timeout_s=5.0):
    from gi.repository import GLib
    ctx = GLib.MainContext.default()
    deadline = time.monotonic() + timeout_s
    while not predicate() and time.monotonic() < deadline:
        ctx.iteration(False)
        time.sleep(0.001)
    return predicate()


def _texts(box):
    child, out = box.get_first_child(), []
    while child is not None:
        out.append(child.get_label())
        child = child.get_next_sibling()
    return out


def test_the_variants_chip_shows_the_apparatus_in_place(display, greek_db,
                                                        monkeypatch):
    import settings
    monkeypatch.setattr(settings, 'get', lambda key: None)
    monkeypatch.setattr(settings, 'put', lambda key, value: None)
    from interlinear_view import InterlinearReader
    reader = InterlinearReader(pane=None)
    reader.render_for(idata.GREEK, 'John', 1, 18)
    assert _pump_until(lambda: len(reader._cells) == 3)

    by_word = {labels['_surface_full']: (cell, labels)
               for cell, labels in reader._cells}
    article, theos, common = by_word['ὁ'], by_word['θεὸς'], by_word['μονογενὴς']
    # Off by default: the added word is not in the flow, the tags are hidden.
    assert not article[0].get_visible()
    assert article[1]['surface'].get_label() == '⟦ὁ⟧'
    assert not theos[1]['variants'].get_visible()
    assert common[1]['variants'] is None
    assert theos[0].get_tooltip_text().startswith("υἱός (huios) 'son' occurs")

    reader._chip_btns['variants'].set_active(True)
    assert article[0].get_visible()
    assert theos[1]['variants'].get_visible()
    assert _texts(theos[1]['variants']) == ['− Tyn TR Byz',
                                            'Tyn TR Byz: υἱός “son”']
    assert _texts(article[1]['variants']) == ['Tyn TR Byz']
    assert article[0].get_tooltip_text() == \
        'In Tyn, TR and Byz; not in the Nestle-Aland text.'

    reader._chip_btns['variants'].set_active(False)
    assert not article[0].get_visible()
    assert not theos[1]['variants'].get_visible()


def test_an_older_interlinear_offers_an_update(display, monkeypatch):
    """A database from before the apparatus columns gets an Update button
    on its Module Manager row; a current one does not."""
    from gi.repository import Gtk
    from module_manager import ModuleManagerWindow
    monkeypatch.setattr(idata, 'is_installed', lambda _n: True)

    class Fake:
        _pack_row = ModuleManagerWindow._pack_row
        _update_button = ModuleManagerWindow._update_button
        _download_button = ModuleManagerWindow._download_button
        _add_actions = ModuleManagerWindow._add_actions
        _show_job = ModuleManagerWindow._show_job
        _action_rows: dict = {}

        def _trash_button(self, _cb):
            return Gtk.Button()

        def _confirm_remove_generic(self, *_a):
            pass

        def _on_interlinear_download(self, *_a):
            pass

    def buttons(row):
        out = []
        for child in _walk(row):
            if isinstance(child, Gtk.Button) and child.get_label():
                out.append(child.get_label())
        return out

    monkeypatch.setattr(idata, 'needs_rebuild', lambda _n: True)
    assert 'Update' in buttons(ModuleManagerWindow._make_interlinear_row(Fake(), idata.GREEK))
    monkeypatch.setattr(idata, 'needs_rebuild', lambda _n: False)
    assert 'Update' not in buttons(ModuleManagerWindow._make_interlinear_row(Fake(), idata.GREEK))


def _walk(widget):
    child = widget.get_first_child()
    while child is not None:
        yield child
        yield from _walk(child)
        child = child.get_next_sibling()


from tests.test_interlinear_data import HEB_ROW_QERE_REAL, HEB_ROW_PREFIXED


@pytest.fixture
def hebrew_db(tmp_path, monkeypatch):
    raw = tmp_path / 'tahot.txt'
    raw.write_text('\n'.join([HEB_ROW_PREFIXED, HEB_ROW_QERE_REAL]) + '\n',
                   encoding='utf-8')
    import urllib.request
    monkeypatch.setitem(idata._DB_FILES, idata.HEBREW,
                        str(tmp_path / 'hebrew.sqlite'))
    monkeypatch.setitem(idata._MODULES[idata.HEBREW], 'urls',
                        ['file://' + urllib.request.pathname2url(str(raw))])
    monkeypatch.setitem(idata._MODULES[idata.HEBREW], 'min_words', 1)
    monkeypatch.setattr(idata, '_migrated', set())
    idata.download_and_build(idata.HEBREW)


def test_the_ketiv_chip_shows_the_written_form_under_the_read_one(
        display, hebrew_db, monkeypatch):
    import settings
    monkeypatch.setattr(settings, 'get', lambda key: None)
    monkeypatch.setattr(settings, 'put', lambda key, value: None)
    from interlinear_view import InterlinearReader
    reader = InterlinearReader(pane=None)
    reader.render_for(idata.HEBREW, 'Joshua', 2, 13)
    assert _pump_until(lambda: len(reader._cells) == 1)
    # Hebrew shows the Ketiv chip, not the Greek Variants one.
    assert reader._chip_btns['ketiv'].get_visible()
    assert not reader._chip_btns['variants'].get_visible()
    cell, labels = reader._cells[0]
    assert labels['_surface_full'] == 'אַחְיוֹתַ֔י'
    assert not labels['variants'].get_visible()
    assert cell.get_tooltip_text().startswith('Written (Ketiv) אַחוֹתַי')
    reader._chip_btns['ketiv'].set_active(True)
    assert labels['variants'].get_visible()
    assert _texts(labels['variants']) == ['אַחוֹתַי', '“sister my”']
    reader._chip_btns['ketiv'].set_active(False)
    assert not labels['variants'].get_visible()
