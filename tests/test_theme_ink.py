"""The theme-dependent ink of a rendered chapter, and who owns it.

`insert_markup` names every span it creates after its own attributes, so a
chapter's theme colours arrive on tags called `foreground_rgba=rgb(…)`. Nothing
can recolour those: the name encodes the value, so mutating one leaves a lying
name and the next render mints a second tag for the new colour. The render
therefore re-tags each of them with an `_ink_*` tag of ours.

What matters is that adoption is invisible — every character keeps the colour
it had — and that the nesting order survives it, since a foreground is a single
value and the innermost span has to win.

No widgets: the pane's own methods are borrowed onto a stand-in, as in
test_focus_unit.
"""
import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
from gi.repository import Gdk, Gtk  # noqa: E402

import pane as pane_mod  # noqa: E402
from pane import BiblePane, theme_ink  # noqa: E402


def _force_theme(monkeypatch, dark):
    """Make the pane's own `Adw.StyleManager.get_default().get_dark()` answer
    `dark`. Returns what it answered before, so a test can prove it moved."""
    was = pane_mod.Adw.StyleManager.get_default().get_dark()

    class Stub:
        def get_dark(self):
            return dark

    monkeypatch.setattr(pane_mod.Adw.StyleManager, 'get_default',
                        staticmethod(lambda: Stub()))
    return was


class Pane:
    """Just enough pane to own a buffer."""

    _INK_ORDER = BiblePane._INK_ORDER
    _adopt_theme_ink = BiblePane._adopt_theme_ink
    _tag_ranges = BiblePane._tag_ranges

    def __init__(self):
        self._buffer = Gtk.TextBuffer()


def colour_at(buf, offset):
    """The foreground actually painted at `offset` — the highest-priority tag
    that sets one, which is how GTK resolves it."""
    out = None
    for tag in buf.get_iter_at_offset(offset).get_tags():
        if tag.get_property('foreground-set'):
            c = tag.get_property('foreground-rgba')
            out = (round(c.red, 3), round(c.green, 3), round(c.blue, 3))
    return out


def signature(buf):
    return [colour_at(buf, i) for i in range(buf.get_char_count())]


def tag_names(buf):
    names = []
    buf.get_tag_table().foreach(lambda t, _d=None:
                                names.append(t.get_property('name')), None)
    return names


def test_adoption_leaves_every_character_the_colour_it_had():
    ink = theme_ink(True)
    p = Pane()
    p._buffer.insert_markup(
        p._buffer.get_end_iter(),
        f'<span foreground="{ink["_ink_heading"]}">Genesis 2</span>\n'
        f'<span foreground="gray"> 1 </span>Thus the heavens'
        f'<span foreground="{ink["_ink_link"]}">a</span> were completed.',
        -1)
    before = signature(p._buffer)

    p._adopt_theme_ink(True)

    assert signature(p._buffer) == before
    names = tag_names(p._buffer)
    assert '_ink_heading' in names and '_ink_link' in names
    # The parser's colour tags are gone, so the table cannot grow one per flip.
    assert not [n for n in names if (n or '').startswith('foreground_rgba')
                and 'gray' not in (n or '')
                and n != 'foreground_rgba=rgb(128,128,128)']


def test_a_colour_we_do_not_own_is_left_alone():
    """The verse number's gray is the same in both themes. Adopting it would
    hand a fixed colour to the recolouring path."""
    p = Pane()
    p._buffer.insert_markup(p._buffer.get_end_iter(),
                            '<span foreground="#808080"> 1 </span>text', -1)
    p._adopt_theme_ink(True)
    assert not [n for n in tag_names(p._buffer) if (n or '').startswith('_ink_')]


def test_the_inner_span_still_wins_after_adoption():
    """A footnote marker sits inside red-letter text. Both are adopted, and a
    foreground is one value — so the marker must keep the blue, not the red."""
    ink = theme_ink(True)
    p = Pane()
    p._buffer.insert_markup(
        p._buffer.get_end_iter(),
        f'<span foreground="{ink["_ink_redletter"]}">I am the way'
        f'<span foreground="{ink["_ink_link"]}">b</span></span>',
        -1)
    marker = p._buffer.get_text(p._buffer.get_start_iter(),
                                p._buffer.get_end_iter(), False).index('b')
    before = colour_at(p._buffer, marker)

    p._adopt_theme_ink(True)

    assert colour_at(p._buffer, marker) == before
    assert p._buffer.get_tag_table().lookup('_ink_link').get_priority() > \
        p._buffer.get_tag_table().lookup('_ink_redletter').get_priority()


class RecolourPane(Pane):
    """Enough pane to flip the theme on an already-rendered chapter."""

    _CURRENT_VERSE_TAG_NAME = BiblePane._CURRENT_VERSE_TAG_NAME
    _recolour_for_theme = BiblePane._recolour_for_theme
    _ensure_current_verse_tag = BiblePane._ensure_current_verse_tag
    _set_current_verse_indicator = BiblePane._set_current_verse_indicator
    _verse_ranges = BiblePane._verse_ranges

    def __init__(self, selected=None):
        super().__init__()
        self._module, self._book, self._chapter = 'BSB', 'Genesis', 2
        self._module_type = 'Biblical Texts'
        self._selected_verse = selected
        self._view = _View()


class _View:
    def __init__(self):
        self.draws = 0

    def queue_draw(self):
        self.draws += 1


def _rendered_chapter(dark, selected=None):
    ink = theme_ink(dark)
    p = RecolourPane(selected=selected)
    p._buffer.insert_markup(
        p._buffer.get_end_iter(),
        f'<span foreground="{ink["_ink_heading"]}">Genesis 2</span>\n'
        f'<span foreground="gray"> 1 </span>Thus the heavens'
        f'<span foreground="{ink["_ink_link"]}">a</span> were completed.',
        -1)
    vnum = p._buffer.create_tag('vnum_1')
    start = p._buffer.get_iter_at_offset(10)
    p._buffer.apply_tag(vnum, start, p._buffer.get_end_iter())
    p._adopt_theme_ink(dark)
    return p


def test_a_flip_leaves_no_span_holding_the_old_theme_colour(monkeypatch):
    monkeypatch.setattr('pane.annotations.get_annotations',
                        lambda *a, **k: {})
    was_dark = _force_theme(monkeypatch, dark=True)
    p = _rendered_chapter(dark=True)
    _force_theme(monkeypatch, dark=False)

    p._recolour_for_theme()

    light = theme_ink(False)
    table = p._buffer.get_tag_table()
    for name, hexcol in light.items():
        tag = table.lookup(name)
        if tag is None:      # this chapter had no span of that colour
            continue
        want = Gdk.RGBA()
        want.parse(hexcol)
        assert tag.get_property('foreground-rgba').equal(want), name
    assert was_dark is True


def test_the_flip_rebuilds_the_current_verse_indicator(monkeypatch):
    """Its colour is baked at creation, so the tag has to be dropped and
    remade — and a reader who had a verse selected must still have it."""
    monkeypatch.setattr('pane.annotations.get_annotations',
                        lambda *a, **k: {})
    _force_theme(monkeypatch, dark=True)
    p = _rendered_chapter(dark=True, selected=1)
    before = p._buffer.get_tag_table().lookup(p._CURRENT_VERSE_TAG_NAME)
    assert before is None      # created on demand by the indicator
    p._set_current_verse_indicator(1)
    dark_tag = p._buffer.get_tag_table().lookup(p._CURRENT_VERSE_TAG_NAME)
    dark_fg = dark_tag.get_property('foreground-rgba').to_string()

    _force_theme(monkeypatch, dark=False)
    p._recolour_for_theme()

    now = p._buffer.get_tag_table().lookup(p._CURRENT_VERSE_TAG_NAME)
    assert now is not None, 'the indicator vanished with the old theme'
    assert now.get_property('foreground-rgba').to_string() != dark_fg
    assert p._selected_verse == 1
    assert colour_at(p._buffer, 10) is not None


def test_every_range_of_a_repeated_colour_is_carried_over():
    """A chapter has many footnote markers and they arrive on ONE parser tag.
    Adopting only its first range would silently drop the rest."""
    ink = theme_ink(False)
    p = Pane()
    blue = ink['_ink_link']
    p._buffer.insert_markup(
        p._buffer.get_end_iter(),
        f'one<span foreground="{blue}">a</span> two'
        f'<span foreground="{blue}">b</span> three'
        f'<span foreground="{blue}">c</span>',
        -1)
    before = signature(p._buffer)

    p._adopt_theme_ink(False)

    assert signature(p._buffer) == before
    ours = p._buffer.get_tag_table().lookup('_ink_link')
    assert len(p._tag_ranges(ours)) == 3
