"""The two ways of showing which sense-unit is being read, and their seam.

The margin rule (shipped) and the focus veil (new) both read the same
`_cur_unit` tag, and each can run without the other. That sharing is the only
thing here worth testing without a display: whichever one is switched off must
not take the other's mark away with it, and the rule must never appear
uninvited because the veil happened to create the tag.

No widgets: the pane's own methods are borrowed onto a stand-in, as in
test_reading_audio.
"""
from pane import BiblePane


class FakeView:
    def __init__(self):
        self.rule = None
        self.paper = None
        self.dim = None
        self.draws = 0

    def set_unit_rule(self, enabled):
        self.rule = bool(enabled)

    def set_focus_paper(self, paper, dim):
        self.paper, self.dim = paper, dim

    def queue_draw(self):
        self.draws += 1


class Pane:
    """The current-unit state machine, widgets stubbed out."""

    set_mark_current_unit = BiblePane.set_mark_current_unit
    set_focus_current_unit = BiblePane.set_focus_current_unit
    _update_current_unit = BiblePane._update_current_unit

    def _at_chapter_foot(self):
        return self.at_foot

    def _first_visible_verse(self):
        return self.first_visible

    def __init__(self, rule=False, veil=False):
        self._view = FakeView()
        self._mark_current_unit = rule
        self._focus_unit = veil
        self._module_type = 'Biblical Texts'
        self._current_unit = None
        self._rendered_verses = [(1, 0), (2, 0), (3, 0)]
        self._top = 1
        self.at_foot = False
        self.first_visible = None
        self.applied = []
        self.cleared = 0
        self.css = 0

    # what the real pane does around the tag
    def _find_topmost_visible_verse(self):
        return self._top

    def _unit_bounds(self, verse):
        return (1, 3) if verse else None

    def _apply_unit_tag(self, first, last):
        self.applied.append((first, last))

    def _clear_unit_tag(self):
        self.cleared += 1
        self._current_unit = None

    def _update_font_css(self):
        self.css += 1


def test_the_veil_alone_still_tracks_the_unit():
    """The mark used to be the only reader of the tag, so the tracking was
    gated on it. The veil needs the same tag and no rule."""
    pane = Pane()
    pane.set_focus_current_unit(True)
    assert pane.applied == [(1, 3)]
    assert pane._view.rule is None          # the rule was never asked for


def test_switching_the_rule_off_leaves_the_veil_its_mark():
    pane = Pane(rule=True, veil=True)
    pane.set_mark_current_unit(False)
    assert pane.cleared == 0
    assert pane._view.rule is False


def test_switching_the_veil_off_leaves_the_rule_its_mark():
    pane = Pane(rule=True, veil=True)
    pane.set_focus_current_unit(False)
    assert pane.cleared == 0


def test_the_last_one_out_clears_the_tag():
    pane = Pane(rule=True, veil=False)
    pane.set_mark_current_unit(False)
    assert pane.cleared == 1


def test_the_rule_is_drawn_only_where_it_was_asked_for():
    """The bug this guards: the rule painted from the tag's presence alone,
    so turning the veil on would have drawn a rule nobody switched on."""
    pane = Pane()
    pane.set_mark_current_unit(True)
    assert pane._view.rule is True
    pane.set_mark_current_unit(False)
    assert pane._view.rule is False


def test_the_veil_restates_its_paper_when_it_changes():
    """It is drawn in the reader's own paper, which only _update_font_css
    knows — so the toggle has to go back through it."""
    pane = Pane()
    pane.set_focus_current_unit(True)
    assert pane.css == 1


def test_neither_tracks_a_unit_on_a_module_that_is_not_scripture():
    pane = Pane(veil=True)
    pane._module_type = 'Commentaries'
    pane._update_current_unit()
    assert pane.applied == []


# ── Which line is the unit's heading ─────────────────────────────────────────
# A real Gtk.TextBuffer, which needs no display — the buffer walk is where
# this can silently go wrong, and the render only shows one chapter of one
# module.

def _buffer(text, verse_lines):
    import gi
    gi.require_version('Gtk', '4.0')
    from gi.repository import Gtk
    buf = Gtk.TextBuffer()
    buf.set_text(text)
    tag = buf.create_tag('vnum_1')
    for line in verse_lines:
        start = buf.get_iter_at_line(line)[1]
        end = start.copy()
        end.forward_to_line_end()
        buf.apply_tag(tag, start, end)
    return buf


def _heading_text(buf, verse_line):
    from reading_view import heading_line
    got = heading_line(buf, buf.get_iter_at_line(verse_line)[1])
    if got is None:
        return None
    end = got.copy()
    end.forward_to_line_end()
    return buf.get_text(got, end, False)


def test_the_heading_above_a_unit_is_found_across_the_blank_line():
    buf = _buffer('The Parable of the Lamp\n\n21 And he said to them\n', [2])
    assert _heading_text(buf, 2) == 'The Parable of the Lamp'


def test_a_unit_that_opens_without_a_heading_has_none():
    """Most of the canon in most modules: KJV, ASV and the Vulgate carry no
    section headings at all, and the veil must simply start at the verse."""
    buf = _buffer('20 And those are the ones\n\n21 And he said\n', [0, 2])
    assert _heading_text(buf, 2) is None


def test_the_walk_stops_rather_than_climbing_the_whole_chapter():
    buf = _buffer('A Heading\n\n\n\n\n21 And he said\n', [5])
    assert _heading_text(buf, 5) is None


def test_the_first_line_of_the_buffer_has_nothing_above_it():
    buf = _buffer('1 In the beginning\n', [0])
    assert _heading_text(buf, 0) is None


# ── Where the controls can act at all ────────────────────────────────────────

def test_a_module_that_marks_no_sections_is_measured_not_declared(monkeypatch):
    """RusSynodal and KJVA both declare `GlobalOptionFilter=OSISHeadings` and
    carry not one heading, so the config cannot be the oracle — the text is.
    """
    import sword_bridge
    asked = []

    def fake_headings(module, book, chapter):
        asked.append((module, book, chapter))
        return {} if module == 'Silent' else {1: ['A Heading']}

    monkeypatch.setattr(sword_bridge, 'chapter_headings', fake_headings)
    monkeypatch.setattr(sword_bridge, '_marks_sections', {})
    assert sword_bridge.module_marks_sections('Loud') is True
    assert sword_bridge.module_marks_sections('Silent') is False
    # The silent one was probed across the whole list before answering no;
    # the loud one stopped at the first hit.
    assert len([a for a in asked if a[0] == 'Silent']) == len(
        sword_bridge._SECTION_PROBE)
    assert len([a for a in asked if a[0] == 'Loud']) == 1


def test_the_answer_is_cached_per_module(monkeypatch):
    import sword_bridge
    calls = []
    monkeypatch.setattr(sword_bridge, '_marks_sections', {})
    monkeypatch.setattr(sword_bridge, 'chapter_headings',
                        lambda m, b, c: calls.append(m) or {1: ['H']})
    sword_bridge.module_marks_sections('Once')
    sword_bridge.module_marks_sections('Once')
    assert calls == ['Once']


# ── Where the units are ──────────────────────────────────────────────────────

class Bounds:
    _unit_bounds = BiblePane._unit_bounds

    def __init__(self, heading_verses, last_verse=21):
        self._rendered_headings = {v: ['A Heading'] for v in heading_verses}
        self._rendered_verses = [(v, 0) for v in range(1, last_verse + 1)]
        self._show_headings = True


def test_the_passage_before_the_first_heading_is_a_unit_too():
    """2 Peter 1 carries its first heading at verse 3 (RusSynodalLIO, BSB),
    so a reader who opens the chapter is ABOVE every heading. Returning no
    unit there left both controls silent exactly where a chapter is opened —
    which is what made the feature look broken."""
    assert Bounds([3, 16])._unit_bounds(1) == (1, 2)


def test_a_chapter_whose_first_heading_opens_it_has_no_preface():
    assert Bounds([1, 10])._unit_bounds(1) == (1, 9)


def test_units_run_to_the_verse_before_the_next_heading():
    b = Bounds([3, 16])
    assert b._unit_bounds(3) == (3, 15)
    assert b._unit_bounds(16) == (16, 21)


def test_a_module_with_no_headings_has_no_units():
    assert Bounds([])._unit_bounds(1) is None


# ── The foot of a chapter ────────────────────────────────────────────────────

class FakeAdj:
    def __init__(self, value, upper, page):
        self._v, self._u, self._p = value, upper, page

    def get_value(self):
        return self._v

    def get_upper(self):
        return self._u

    def get_page_size(self):
        return self._p


class Foot:
    _at_chapter_foot = BiblePane._at_chapter_foot

    def __init__(self, value, upper, page=800.0, verses=True):
        self._rendered_verses = [(1, 0)] if verses else []
        self._reading_scroll = type(
            'S', (), {'get_vadjustment': lambda _s: FakeAdj(value, upper, page)})()


def test_the_foot_of_a_scrolling_chapter_is_recognised():
    """The reader cannot scroll further, so a last unit shorter than the
    viewport can never reach the top — it would sit quieted while being
    read."""
    assert Foot(value=1200.0, upper=2000.0, page=800.0)._at_chapter_foot()


def test_mid_chapter_is_not_the_foot():
    assert not Foot(value=400.0, upper=2000.0, page=800.0)._at_chapter_foot()


def test_a_chapter_that_fits_the_viewport_is_never_at_its_foot():
    """It is 'scrolled to the end' from the moment it opens, and there the
    topmost verse is the honest answer."""
    assert not Foot(value=0.0, upper=600.0, page=800.0)._at_chapter_foot()


def test_nothing_rendered_is_not_the_foot():
    assert not Foot(value=1200.0, upper=2000.0, verses=False)._at_chapter_foot()


# ── A viewport whose top row carries no verse ────────────────────────────────

def test_a_heading_on_the_top_row_does_not_freeze_the_mark():
    """It used to keep the unit it had, which is defensible for a hairline in
    the margin and fatal for a veil: the kept unit scrolls away, and then
    either nothing is quieted (the veil fails open) or everything is (only a
    sliver of the unit is left on screen). Both were measured off real
    screenshots."""
    pane = Pane(veil=True)
    pane._current_unit = 1
    pane._top = None                    # the top row is a heading
    pane.first_visible = 3              # the verse under it
    pane._unit_bounds = lambda v: (3, 15) if v == 3 else None
    pane._update_current_unit()
    assert pane._current_unit == 3
    assert pane.applied == [(3, 15)]


def test_an_empty_viewport_keeps_what_it_had():
    """Nothing visible anywhere is the one case where holding still is
    right — there is no better answer to move to."""
    pane = Pane(veil=True)
    pane._current_unit = 3
    pane._top = None
    pane.first_visible = None
    pane._update_current_unit()
    assert pane._current_unit == 3
    assert pane.applied == []


def test_an_opening_chapter_with_no_mark_yet_falls_back_to_its_first_verse():
    pane = Pane(veil=True)
    pane._top = None
    pane.first_visible = None
    pane._update_current_unit()
    assert pane.applied == [(1, 3)]


def test_a_unit_that_begins_mid_paragraph_has_no_heading_of_its_own():
    """Why the focus veil only ever dimmed BELOW the unit.

    In continuous prose a paragraph is one buffer line, so a unit that does
    not open the paragraph shares it with the verses before. Walking back a
    line from such a unit leaves it entirely and lands on the paragraph
    above — in practice the CHAPTER TITLE, a dozen lines up. The veil took
    that as its top edge, `_veil` draws nothing when its bottom is above its
    top, and every verse between the title and the unit stayed lit.

    Measured in the app on Genesis 5: the unit at verse 3 sits at y=189 and
    was handed a heading at y=5.
    """
    buf = _buffer('Genesis 5\n\nThis is the book 2 Male and female 3 When Adam\n',
                  [2])
    line = buf.get_iter_at_line(2)[1]
    mid = line.copy()
    mid.forward_chars(20)                     # inside the paragraph
    assert not mid.starts_line()
    from reading_view import heading_line
    assert heading_line(buf, mid) is None
    # …and a unit that DOES open its paragraph still keeps its heading.
    assert _heading_text(buf, 2) == 'Genesis 5'
