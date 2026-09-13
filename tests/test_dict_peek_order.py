"""Which dictionary tab opens when a word is double-clicked.

The ordering rule itself — an exact hit first, then the language you are
reading in — was already covered by `content.language_code`'s own tests. What
was not covered was the CALLER, and that is where it broke: the method that
builds the peek binds a local `content` (the popover's box), so inside its
nested worker `content.language_code` resolved to a `Gtk.Box` and every
double-click raised `AttributeError`. The task machinery reports a failed
lookup as "no entry", so the dictionary looked empty rather than broken, and
it shipped that way in 1.6.2.

The lookup lives at method scope now, where nothing shadows the module — and
where a test can reach it without a display.

No widgets: the pane's own method is borrowed onto a stand-in, as in
test_footnote_markers.
"""
import gi

gi.require_version('Gtk', '4.0')

import content  # noqa: E402
import sword_bridge  # noqa: E402
from pane import BiblePane  # noqa: E402


class Pane:
    """Enough pane to look a word up."""

    _dict_results = BiblePane._dict_results

    def __init__(self, module):
        self._module = module


_DICTS = [('Easton', "Easton's Bible Dictionary"),
          ('Wikcionario', 'Wikcionario en español'),
          ('Webster', "Webster's Dictionary")]


def _stub(monkeypatch, *, hits, languages):
    """`hits` maps a module to (html, exact); anything else answers nothing."""
    monkeypatch.setattr(
        sword_bridge, 'lookup_dict_entry',
        lambda mod, word: hits.get(mod, ('', False)))
    monkeypatch.setattr(content, 'language_code',
                        lambda mod: languages.get(mod, ''))


def test_the_lookup_runs_at_all(monkeypatch):
    """The whole regression in one assertion: this raised AttributeError on
    every double-click, and the peek said "no entry"."""
    _stub(monkeypatch, hits={'Easton': ('<p>love</p>', True)},
          languages={'KJV': 'en', 'Easton': 'en'})
    results = Pane('KJV')._dict_results('love', _DICTS)
    assert [mod for mod, _desc, _html in results] == ['Easton']


def test_the_reading_language_opens_first(monkeypatch):
    """A reader in a Spanish Bible should not have to click past French."""
    _stub(monkeypatch,
          hits={'Easton': ('<p>en</p>', True),
                'Wikcionario': ('<p>es</p>', True)},
          languages={'NBLA': 'es', 'Wikcionario': 'es', 'Easton': 'en'})
    results = Pane('NBLA')._dict_results('amor', _DICTS)
    assert [mod for mod, _desc, _html in results] == ['Wikcionario', 'Easton']


def test_an_ebible_bible_still_knows_its_language(monkeypatch):
    """The defect the ordering was written for: `module_language` answers ''
    for an eBible key, so `content.language_code` is the one that must be
    asked — which is exactly the call the shadow swallowed."""
    key = 'ebible:spaonbv'
    _stub(monkeypatch,
          hits={'Easton': ('<p>en</p>', True),
                'Wikcionario': ('<p>es</p>', True)},
          languages={key: 'es', 'Wikcionario': 'es', 'Easton': 'en'})
    results = Pane(key)._dict_results('amor', _DICTS)
    assert results[0][0] == 'Wikcionario'


def test_an_exact_hit_beats_the_reading_language(monkeypatch):
    """De-inflection is English: it strips the `s` from `pues` and offers
    Webster's `Pue`. An exact answer in another language is still the better
    answer."""
    _stub(monkeypatch,
          hits={'Webster': ('<p>Pue</p>', False),
                'Easton': ('<p>exact</p>', True)},
          languages={'NBLA': 'es', 'Webster': 'en', 'Easton': 'en'})
    results = Pane('NBLA')._dict_results('pues', _DICTS)
    assert [mod for mod, _desc, _html in results] == ['Easton', 'Webster']


def test_a_dictionary_with_nothing_to_say_gets_no_tab(monkeypatch):
    _stub(monkeypatch, hits={}, languages={'KJV': 'en'})
    assert Pane('KJV')._dict_results('xyzzy', _DICTS) == []


def test_no_reading_language_falls_back_to_the_titles(monkeypatch):
    _stub(monkeypatch,
          hits={mod: ('<p>x</p>', True) for mod, _d in _DICTS},
          languages={})
    results = Pane('Unknown')._dict_results('love', _DICTS)
    assert [mod for mod, _desc, _html in results] == \
        ['Easton', 'Webster', 'Wikcionario']
