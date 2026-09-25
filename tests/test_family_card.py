"""The Bible Family Tree's Card: that it builds for every Bible, says only
what the data knows, and offers the right actions.

The widgets are built and walked, never shown. A display is still needed to
build them — without one GTK segfaults rather than failing (see
test_genealogy_reader.py), so this file skips in a headless run.
"""
import pytest
from gi.repository import Gdk, GLib, Gtk

Gtk.init_check()
if Gdk.Display.get_default() is None:
    pytest.skip('needs a display: building real GTK widgets without one '
                'segfaults rather than failing',
                allow_module_level=True)

import bible_family as bf
import family_card as fc


def _card():
    calls = []
    card = fc.FamilyCard(
        on_close=lambda: calls.append(('close',)),
        on_open=lambda m: calls.append(('open', m)),
        on_install=lambda q: calls.append(('install', q)),
        on_compare=lambda: calls.append(('compare',)),
        on_show_in_family=lambda n: calls.append(('family', n)))
    return card, calls


def _walk(widget):
    child = widget.get_first_child()
    while child is not None:
        yield child
        yield from _walk(child)
        child = child.get_next_sibling()


def _texts(card):
    return [w.get_text() for w in _walk(card._body) if isinstance(w, Gtk.Label)]


def _buttons(card):
    return {w.get_label(): w for w in _walk(card._body)
            if isinstance(w, Gtk.Button) and w.get_label()}


def test_every_bible_builds_a_card():
    card, _calls = _card()
    for n in bf._data()['node']:
        if n.get('kind', 'translation') == 'translation':
            card.show(n['id'], [], '')
            assert card.node_id == n['id']
            assert n['name'] in _texts(card)


def test_a_bible_with_no_place_draws_no_mark():
    """The Passion Translation: a plain note, never a mark (decided 7c)."""
    card, _calls = _card()
    card.show('tpt', [], '')
    assert not any(isinstance(w, Gtk.DrawingArea) for w in _walk(card._body))
    assert 'It has no place on the Line.' in _texts(card)
    card.show('esv', [], '')
    assert any(isinstance(w, Gtk.DrawingArea) for w in _walk(card._body))


def test_actions_follow_what_is_installed():
    card, calls = _card()
    card.show('esv', ['KJVA', 'ESV'], 'KJVA')
    assert set(_buttons(card)) == {'Open in this pane', 'Compare this verse',
                                   'Show in the Family'}
    _buttons(card)['Open in this pane'].emit('clicked')
    assert calls[-1] == ('open', 'ESV')

    card.show('kjv', ['KJVA', 'ESV'], 'KJVA')      # the one being read
    assert set(_buttons(card)) == {'Compare this verse', 'Show in the Family'}
    assert 'You are reading this' in _texts(card)

    card.show('nasb2020', ['KJVA'], 'KJVA')
    assert set(_buttons(card)) == {'Install', 'Show in the Family'}
    _buttons(card)['Install'].emit('clicked')
    assert calls[-1] == ('install', bf.node('nasb2020')['installable'][0])

    card.show('nlt', ['KJVA'], 'KJVA')             # nowhere to get it
    assert set(_buttons(card)) == {'Show in the Family'}

    card.show('lsb', ['KJVA'], 'KJVA')             # not in the Family
    assert _buttons(card) == {}


def test_show_in_the_family_is_offered_for_family_bibles_only():
    card, calls = _card()
    members = set(bf.family_members())
    for n in bf._data()['node']:
        if n.get('kind', 'translation') == 'translation':
            card.show(n['id'], [], '')
            offered = 'Show in the Family' in _buttons(card)
            assert offered == (n['id'] in members), n['id']
    card.show('rsv', [], '')
    _buttons(card)['Show in the Family'].emit('clicked')
    assert calls[-1] == ('family', 'rsv')


def test_show_in_the_family_is_not_offered_for_the_bible_it_came_from():
    """Opened from the ESV in the Family, the Card does not offer to show
    the ESV there; followed to the RSV, it offers the RSV."""
    card, _calls = _card()
    card.show('esv', [], '', from_family=True)
    assert 'Show in the Family' not in _buttons(card)
    card._go_to('rsv')
    assert 'Show in the Family' in _buttons(card)


def _settle():
    ctx = GLib.MainContext.default()
    while ctx.pending():
        ctx.iteration(False)


def test_links_move_between_cards_and_back_returns():
    card, _calls = _card()
    card.show('esv', [], '')
    assert not card._back.get_visible()
    assert card._on_link(None, 'card:rsv') is True
    # Not inside the click: the label being clicked would be torn down
    # mid-signal, and the keyboard focus it held with it.
    assert card.node_id == 'esv'
    _settle()
    assert card.node_id == 'rsv' and card._back.get_visible()
    card._go_back()
    assert card.node_id == 'esv' and not card._back.get_visible()
    # A web source is left to GTK, which opens the browser.
    assert card._on_link(None, 'https://en.wikipedia.org/wiki/X') is False


def test_the_short_name_reads_like_running_text():
    assert fc.short_name(bf.node('msg')) == 'The Message'
    assert fc.short_name(bf.node('esv')) == 'ESV'
    assert fc.short_name(bf.node('kjv')) == 'KJV'


def test_the_place_sentences_cover_every_kind():
    assert fc.place_sentences(bf.node('esv'))[0].endswith('“Word for word”.')
    t4t = fc.place_sentences(bf.node('t4t'))
    assert any('free end' in s for s in t4t)       # pinned there (7b)
    web = fc.place_sentences(bf.node('webster'))
    assert any('older English' in s for s in web)  # corrected (7g)
    assert fc.place_sentences(bf.node('tpt')) == ['It has no place on the Line.']


def test_a_described_only_bible_names_no_neighbours():
    """Its makers' word covers a whole zone; the zone's middle is not a
    position, so 'Near X and Y' would claim a precision nobody measured."""
    ids = [n['id'] for n in bf._data()['node']
           if (p := bf.place_of(n)) is not None and p.kind == 'class']
    assert ids
    card, _calls = _card()
    for nid in ids:
        assert bf.neighbours(nid) == (None, None), nid
        card.show(nid, [], '')
        assert not any('on the Line.' in t and t.startswith('Near')
                       for t in _texts(card)), nid


def test_a_translation_with_markup_characters_does_not_break_the_card(
        monkeypatch):
    """A translated sentence goes into markup; an '&' in it must not stop
    the label from parsing (and so from showing the link inside it)."""
    real = fc._
    monkeypatch.setattr(fc, '_', lambda s: 'Near {a} & {b} <here>'
                        if s == 'Near {a} and {b} on the Line.' else real(s))
    card, _calls = _card()
    card.show('esv', [], '')
    near = [t for t in _texts(card) if t.startswith('Near ')]
    assert near and '& ' in near[0] and '<here>' in near[0]
