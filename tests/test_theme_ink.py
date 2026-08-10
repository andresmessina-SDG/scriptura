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
    `dark`."""

    class Stub:
        def get_dark(self):
            return dark

    monkeypatch.setattr(pane_mod.Adw.StyleManager, 'get_default',
                        staticmethod(lambda: Stub()))


class Pane:
    """Just enough pane to own a buffer."""

    _INK_ORDER = BiblePane._INK_ORDER
    _MARKUP_FG_PREFIX = BiblePane._MARKUP_FG_PREFIX
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
    """Enough pane to flip the theme on an already-rendered chapter.

    Driven through `_on_theme_changed`, not `_recolour_for_theme`: the split
    between what the entry point does for every pane and what the recolouring
    path does for a rendered one is itself load-bearing, and testing the inner
    half alone once let a stale current-verse tag through.
    """

    _CURRENT_VERSE_TAG_NAME = BiblePane._CURRENT_VERSE_TAG_NAME
    _DROPCAP_TAG = BiblePane._DROPCAP_TAG
    _on_theme_changed = BiblePane._on_theme_changed
    _recolour_for_theme = BiblePane._recolour_for_theme
    _is_verse_navigable = BiblePane._is_verse_navigable
    _ensure_current_verse_tag = BiblePane._ensure_current_verse_tag
    _set_current_verse_indicator = BiblePane._set_current_verse_indicator
    _sync_dropcap_ink = BiblePane._sync_dropcap_ink
    _verse_ranges = BiblePane._verse_ranges

    def __init__(self, selected=None, module_type='Biblical Texts',
                 devotional=False, rendered=True):
        super().__init__()
        self._module, self._book, self._chapter = 'BSB', 'Genesis', 2
        self._module_type = module_type
        self._is_devotional = devotional
        self._rendered_verses = [(1, '')] if rendered else None
        self._selected_verse = selected
        self._colored_dropcap = False
        self._view = _View()
        self.refetched = 0

    # The three things _on_theme_changed does before the branch.
    def get_root(self):
        return self

    def _update_font_css(self):
        pass

    def _apply_reading_page_edge(self):
        pass

    def _fetch_and_render(self):
        self.refetched += 1


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
    _force_theme(monkeypatch, dark=True)
    p = _rendered_chapter(dark=True)

    def ink_matches(want_hex):
        """Every ink tag the chapter actually has carries `want_hex`."""
        table = p._buffer.get_tag_table()
        seen = 0
        for name, hexcol in want_hex.items():
            tag = table.lookup(name)
            if tag is None:      # this chapter had no span of that colour
                continue
            seen += 1
            want = Gdk.RGBA()
            want.parse(hexcol)
            if not tag.get_property('foreground-rgba').equal(want):
                return name
        assert seen, 'the chapter carried no ink tags at all'
        return None

    # Prove the flip MOVED: the chapter has to be holding dark ink first.
    # (Asking the real StyleManager what it said before proves only what
    # the machine running the test has its desktop set to — True here,
    # False in a CI container where get_default() is NULL.)
    assert ink_matches(theme_ink(True)) is None

    _force_theme(monkeypatch, dark=False)
    p._on_theme_changed()

    assert ink_matches(theme_ink(False)) is None


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
    p._on_theme_changed()

    now = p._buffer.get_tag_table().lookup(p._CURRENT_VERSE_TAG_NAME)
    assert now is not None, 'the indicator vanished with the old theme'
    assert now.get_property('foreground-rgba').to_string() != dark_fg
    assert p._selected_verse == 1
    assert colour_at(p._buffer, 10) is not None


def test_a_flip_does_not_light_a_cap_the_reader_turned_off(monkeypatch):
    """`_ink_dropcap` is in the theme table like the other three, but its
    colour is conditional — and setting a foreground also sets
    `foreground-set`. Without the sync afterwards, flipping the theme would
    gild a cap nobody asked for."""
    monkeypatch.setattr('pane.annotations.get_annotations', lambda *a, **k: {})
    _force_theme(monkeypatch, dark=True)
    p = _rendered_chapter(dark=True)
    cap = p._buffer.create_tag(p._DROPCAP_TAG)
    p._buffer.apply_tag(cap, p._buffer.get_iter_at_offset(13),
                        p._buffer.get_iter_at_offset(14))
    assert p._colored_dropcap is False

    _force_theme(monkeypatch, dark=False)
    p._on_theme_changed()

    assert cap.get_property('foreground-set') is False
    assert colour_at(p._buffer, 13) is None


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


# ── Adoption takes the parser's tags and only the parser's tags ──────────

def test_the_parser_still_names_its_colour_tags_the_way_we_expect():
    """`_MARKUP_FG_PREFIX` is a fact about GTK, not about us. If a GTK release
    ever renames these, adoption stops finding anything and the theme flip goes
    stale — so pin it here, where the failure is legible."""
    p = Pane()
    p._buffer.insert_markup(p._buffer.get_end_iter(),
                            '<span foreground="#bb0000">red</span>', -1)
    assert [n for n in tag_names(p._buffer)
            if (n or '').startswith(BiblePane._MARKUP_FG_PREFIX)]


def test_the_lexicon_hover_survives_a_render():
    """`_strg_hover` carries the link blue by intent — it is the same colour
    for the same reason. Adopting by colour alone deleted it from the table on
    every single render."""
    p = Pane()
    p._buffer.insert(p._buffer.get_end_iter(), 'In the beginning')
    hover = p._buffer.create_tag('_strg_hover',
                                 foreground=theme_ink(False)['_ink_link'])
    p._buffer.apply_tag(hover, p._buffer.get_iter_at_offset(3),
                        p._buffer.get_iter_at_offset(6))

    p._adopt_theme_ink(False)

    assert p._buffer.get_tag_table().lookup('_strg_hover') is not None
    assert colour_at(p._buffer, 4) is not None


def test_a_reader_may_choose_a_drop_cap_colour_we_already_use(monkeypatch):
    """The custom cap colour is any hex the reader likes, so it can equal a
    colour we style something else with. The cap's colour is never written into
    the markup, so a match can only ever be a false positive — and a false
    positive DELETES the tag it matched, taking its bold weight with it."""
    monkeypatch.setattr(pane_mod.settings, 'get',
                        lambda key: '#5b8def' if key == 'dropcap_color' else None)
    p = Pane()
    p._buffer.insert_markup(p._buffer.get_end_iter(),
                            '<span foreground="gray"> 3 </span>plain text', -1)
    note = p._buffer.create_tag('_note_marker', foreground='#5b8def',
                                weight=pane_mod.Pango.Weight.BOLD)
    p._buffer.apply_tag(note, p._buffer.get_start_iter(),
                        p._buffer.get_iter_at_offset(3))

    p._adopt_theme_ink(False)

    assert p._buffer.get_tag_table().lookup('_note_marker') is not None
    assert note.get_property('weight') == pane_mod.Pango.Weight.BOLD
    assert '_ink_dropcap' not in tag_names(p._buffer)


def test_the_current_verse_indicator_is_not_adopted(monkeypatch):
    """Same collision, on the tag whose disappearance is most visible: the
    indicator is applied during the render, just before adoption runs."""
    monkeypatch.setattr(pane_mod.settings, 'get',
                        lambda key: '#7a4dbf' if key == 'dropcap_color' else None)
    _force_theme(monkeypatch, dark=False)
    p = RecolourPane(selected=1)
    p._buffer.insert_markup(p._buffer.get_end_iter(),
                            '<span foreground="gray"> 1 </span>Thus the heavens',
                            -1)
    vnum = p._buffer.create_tag('vnum_1')
    p._buffer.apply_tag(vnum, p._buffer.get_start_iter(),
                        p._buffer.get_end_iter())
    p._set_current_verse_indicator(1)

    p._adopt_theme_ink(False)

    assert p._buffer.get_tag_table().lookup(p._CURRENT_VERSE_TAG_NAME) is not None


# ── What the flip owes every pane, not just a rendered chapter ───────────

def test_a_flip_drops_the_indicator_tag_even_with_nothing_to_recolour(monkeypatch):
    """A pane showing a devotional re-fetches instead of recolouring — but it
    still holds the indicator tag from the Bible it showed before, and
    `_ensure_current_verse_tag` hands an existing tag back without looking at
    its colour. Left behind, that Bible comes back wearing the old theme."""
    _force_theme(monkeypatch, dark=False)
    p = RecolourPane(selected=1, module_type='Daily Devotional',
                     devotional=True)
    light_tag = p._ensure_current_verse_tag()
    light_fg = light_tag.get_property('foreground-rgba').to_string()

    _force_theme(monkeypatch, dark=True)
    p._on_theme_changed()

    assert p.refetched == 1, 'a devotional still has to be re-rendered'
    assert p._buffer.get_tag_table().lookup(p._CURRENT_VERSE_TAG_NAME) is None
    # And the Bible it goes back to gets a tag built against the new theme.
    p._module_type, p._is_devotional = 'Biblical Texts', False
    assert p._ensure_current_verse_tag().get_property(
        'foreground-rgba').to_string() != light_fg
