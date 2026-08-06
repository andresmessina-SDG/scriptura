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
from gi.repository import Gtk  # noqa: E402

from pane import BiblePane, theme_ink  # noqa: E402


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
