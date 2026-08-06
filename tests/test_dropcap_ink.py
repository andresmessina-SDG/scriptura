"""The drop cap's colour, and the tag that carries it.

The cap used to have its colour written into the markup, which meant both the
toggle and the custom-colour picker could only change it by rebuilding the
whole chapter. The colour is now a tag over the cap character, so the size and
the weight stay put while the ink comes and goes.

Two things have to hold. The cap character is found by counting the text the
markup contributes — entities are one character, tags none — so that count has
to be right. And an uncoloured cap must stay uncoloured through a theme flip,
which is the one entry in the `theme_ink` table whose colour is conditional.

No widgets: the pane's methods are borrowed onto a stand-in, as in
test_theme_ink.
"""
import gi

gi.require_version('Gtk', '4.0')
from gi.repository import Gtk  # noqa: E402

import pane as pane_mod  # noqa: E402
from pane import BiblePane, _DROPCAP_SPAN, _plain_len, dropcap_color_hex  # noqa: E402


class Pane:
    """Just enough pane to own a buffer and colour a cap."""

    _DROPCAP_TAG = BiblePane._DROPCAP_TAG
    _apply_dropcap_tag = BiblePane._apply_dropcap_tag
    _sync_dropcap_ink = BiblePane._sync_dropcap_ink
    _raise_dropcap = BiblePane._raise_dropcap

    def __init__(self, colored=True):
        self._buffer = Gtk.TextBuffer()
        self._colored_dropcap = colored


def _force_theme(monkeypatch, dark):
    class Stub:
        def get_dark(self):
            return dark

    monkeypatch.setattr(pane_mod.Adw.StyleManager, 'get_default',
                        staticmethod(lambda: Stub()))


def colour_at(buf, offset):
    out = None
    for tag in buf.get_iter_at_offset(offset).get_tags():
        if tag.get_property('foreground-set'):
            c = tag.get_property('foreground-rgba')
            out = (round(c.red, 3), round(c.green, 3), round(c.blue, 3))
    return out


# ── Finding the cap ─────────────────────────────────────────────────────────

def test_plain_len_counts_what_reaches_the_buffer():
    assert _plain_len('') == 0
    assert _plain_len('Thus') == 4
    assert _plain_len('<span foreground="#fff">') == 0
    assert _plain_len('&quot;') == 1            # one character, not six
    assert _plain_len('&amp;&lt;&gt;') == 3
    assert _plain_len('<i>a</i>&quot;b') == 3


def test_plain_len_agrees_with_what_insert_markup_produces():
    """The count is only worth anything if Pango agrees with it."""
    for markup in ('<span weight="bold">The</span> beginning',
                   '&quot;Do not&quot; <i>he</i> said',
                   '<span size="200%">I</span>n the beginning'):
        buf = Gtk.TextBuffer()
        buf.insert_markup(buf.get_end_iter(), markup, -1)
        assert buf.get_char_count() == _plain_len(markup), markup


def test_the_index_lands_on_the_letter_the_split_capped():
    """A verse opening on a quotation mark — BSB and LEB both do at Matthew
    6:1 — puts an entity ahead of the cap. The offset has to step over it as
    one character, not six."""
    markup = f'&quot;{_DROPCAP_SPAN}B{"</span>"}eware of practicing'
    buf = Gtk.TextBuffer()
    buf.insert_markup(buf.get_end_iter(), markup, -1)
    index = _plain_len(markup[:markup.index(_DROPCAP_SPAN)])
    text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
    assert text[index] == 'B'


# ── The ink ─────────────────────────────────────────────────────────────────

def _capped(monkeypatch, dark=False, colored=True):
    _force_theme(monkeypatch, dark)
    p = Pane(colored=colored)
    p._buffer.insert_markup(p._buffer.get_end_iter(),
                            f'{_DROPCAP_SPAN}T{"</span>"}hus the heavens', -1)
    mark = p._buffer.create_mark(None, p._buffer.get_start_iter(), True)
    p._apply_dropcap_tag(mark, 0)
    return p


def test_the_cap_is_coloured_where_the_reader_asked_for_it(monkeypatch):
    p = _capped(monkeypatch, dark=False, colored=True)
    want = Gtk.TextTag(name='want')
    want.set_property('foreground', dropcap_color_hex(False))
    c = want.get_property('foreground-rgba')
    assert colour_at(p._buffer, 0) == (round(c.red, 3), round(c.green, 3),
                                       round(c.blue, 3))


def test_an_uncoloured_cap_carries_no_foreground(monkeypatch):
    """Off is not black — it is no colour at all, so the cap wears the
    reading ink like every other letter."""
    p = _capped(monkeypatch, colored=False)
    assert colour_at(p._buffer, 0) is None
    tag = p._buffer.get_tag_table().lookup(Pane._DROPCAP_TAG)
    assert tag is not None          # the tag still exists, ready to be lit


def test_the_toggle_only_moves_the_colour(monkeypatch):
    p = _capped(monkeypatch, colored=True)
    lit = colour_at(p._buffer, 0)

    p._colored_dropcap = False
    assert p._sync_dropcap_ink() is True
    assert colour_at(p._buffer, 0) is None

    p._colored_dropcap = True
    assert p._sync_dropcap_ink() is True
    assert colour_at(p._buffer, 0) == lit


def test_the_cap_follows_the_theme(monkeypatch):
    p = _capped(monkeypatch, dark=False, colored=True)
    light = colour_at(p._buffer, 0)
    _force_theme(monkeypatch, dark=True)
    p._sync_dropcap_ink()
    assert colour_at(p._buffer, 0) != light


def test_no_cap_reports_false_so_the_caller_can_re_render(monkeypatch):
    """A devotional, a generic book, a verse 1 with no letter to enlarge."""
    _force_theme(monkeypatch, False)
    p = Pane()
    assert p._sync_dropcap_ink() is False


def test_the_cap_outranks_the_red_letter(monkeypatch):
    """In a red-letter Bible the cap sits inside the Lord's words. A
    foreground is one value, so the gold has to win."""
    p = _capped(monkeypatch, colored=True)
    red = p._buffer.create_tag('_ink_redletter', foreground='#bb0000')
    red.set_priority(p._buffer.get_tag_table().get_size() - 1)
    p._buffer.apply_tag(red, p._buffer.get_start_iter(),
                        p._buffer.get_end_iter())
    # The red was applied last and outranks the cap — the state the render
    # leaves behind, since adoption re-prioritises the ink tags.
    assert colour_at(p._buffer, 0) == (round(red.props.foreground_rgba.red, 3),
                                       round(red.props.foreground_rgba.green, 3),
                                       round(red.props.foreground_rgba.blue, 3))

    p._raise_dropcap()

    cap = p._buffer.get_tag_table().lookup(Pane._DROPCAP_TAG)
    assert cap.get_priority() > red.get_priority()
    assert colour_at(p._buffer, 0) == (round(cap.props.foreground_rgba.red, 3),
                                       round(cap.props.foreground_rgba.green, 3),
                                       round(cap.props.foreground_rgba.blue, 3))
