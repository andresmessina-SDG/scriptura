"""The decoration registry: what paints, where, and when.

These guard the declaration rather than the drawing — the pixels are
verified by the scroll matrix and by eye. What can go wrong here silently
is ordering (a cue disappearing under the band it should sit over) and the
enable flags (a mark painting when the reader never asked for it).
"""
import reading_view as rv


class _View:
    """Just enough view for the registry's callables."""

    def __init__(self, **kw):
        self.__dict__.update(kw)

    def get_color(self):
        return 'text-colour'


def _by_name(name):
    return next(d for d in rv._DECORATIONS if d.name == name)


def test_paint_order_is_bottom_up():
    # A search hit on a highlighted verse, and a flash on either, must stay
    # visible — so each of these paints over the one before it.
    order = [d.name for d in rv._DECORATIONS]
    assert order.index('verse highlights') < order.index('search match')
    assert order.index('search match') < order.index('search match (current)')
    assert order.index('search match (current)') < order.index(
        'navigation flash')


def test_every_decoration_declares_a_known_layer_and_style():
    styles = {'highlights', 'band', 'underline', 'dotted', 'rule', 'veil'}
    for dec in rv._DECORATIONS:
        assert dec.layer in (rv._BELOW, rv._ABOVE), dec.name
        assert dec.style in styles, dec.name
        # Only the highlight family has no single tag: it is a tag family.
        assert (dec.tag is None) == (dec.style == 'highlights'), dec.name


def test_the_veil_is_the_only_thing_painted_over_the_text():
    above = [d.name for d in rv._DECORATIONS if d.layer == rv._ABOVE]
    assert above == ['focus veil']


def test_rule_and_veil_share_the_unit_tag():
    # They are independent settings over one tag, so either can run alone.
    assert _by_name('sense-unit rule').tag == '_cur_unit'
    assert _by_name('focus veil').tag == '_cur_unit'


def test_the_unit_tag_wakes_the_paint_pass():
    """Regression: the sense-unit rule drew nothing on a clean chapter.

    The paint pass returns early unless some decoration's tag exists, and
    every other tag is created on demand — a pane that has not yet searched,
    flashed a verse or drawn an annotation has none of them. `_cur_unit` was
    left out of that check, so the rule was invisible exactly when nothing
    else was marked. Measured on a clean chapter: 0 rule pixels, 70 after.
    """
    below = [d for d in rv._DECORATIONS if d.layer == rv._BELOW]
    assert '_cur_unit' in [d.tag for d in below]


def test_unit_rule_is_off_unless_asked_for():
    rule = _by_name('sense-unit rule')
    assert not rule.on(_View())                      # never set
    assert not rule.on(_View(_show_unit_rule=False))
    assert rule.on(_View(_show_unit_rule=True))


def test_veil_is_off_at_zero_dim():
    veil = _by_name('focus veil')
    assert not veil.on(_View())                 # never set
    assert not veil.on(_View(_focus_dim=0.0))   # the default: off
    assert veil.on(_View(_focus_dim=0.55))


def test_veil_colour_carries_the_dim_as_alpha():
    colour = rv._veil_colour(_View(_focus_paper='#ffffff', _focus_dim=0.55))
    assert colour is not None
    assert abs(colour.alpha - 0.55) < 1e-6


def test_veil_colour_refuses_an_unparseable_paper():
    assert rv._veil_colour(
        _View(_focus_paper='not-a-colour', _focus_dim=0.55)) is None


def test_decorations_with_a_fixed_colour_resolve_without_a_display():
    for name in ('search match', 'search match (current)',
                 'navigation flash'):
        dec = _by_name(name)
        assert isinstance(dec.colour(rv.BibleTextView), str)


# ── What may be called from inside a paint ──────────────────────────────────

def test_the_decorations_never_map_an_x_to_a_byte_index_while_painting():
    """The crash his session hit, kept out by a rule on the source.

    `_draw_highlights` and the focus veil run inside `snapshot`, and both
    asked `get_iter_at_location(0, y)` for the first and last visible lines.
    That call maps an X coordinate to a byte index WITHIN the line it lands
    on — a step neither one wants, since both pass x=0 and use the answer as
    a line bound. It is also the step that aborted the process:

        Gtk-ERROR: Byte index 1435 is off the end of the line
        #4  iter_set_from_byte_offset
        #8  gtk_text_view_get_iter_at_location   ← ours
        #19 draw_text                            ← inside GtkTextView's paint

    Navigating to a shorter chapter with the reading view focused leaves the
    visible rect reaching past the end of the new text, and GTK aborts from
    inside its own paint. It crashed four runs in six.

    A race cannot be caught by a test that runs it once, so this guards the
    call. Read from the parse tree and not the text: the first version of
    this test searched the source for a name that its own docstring
    contains, and passed against the very line it was written to forbid.

    The pointer-driven callers in `pane.py` do want a character and do not
    run during a paint; they are not covered here.
    """
    import ast
    import inspect
    tree = ast.parse(inspect.getsource(rv))
    painting = {'_visible_lines', '_draw_highlights', '_draw_veil'}
    seen = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name not in painting:
            continue
        seen.add(node.name)
        called = {c.func.attr for c in ast.walk(node)
                  if isinstance(c, ast.Call)
                  and isinstance(c.func, ast.Attribute)}
        assert 'get_iter_at_location' not in called, \
            '%s runs during a paint and must not map an x to a byte index' \
            % node.name
    assert '_visible_lines' in seen, 'the helper this rule is about is gone'
    src = inspect.getsource(rv._visible_lines)
    assert 'get_line_at_y' in src.split('"""')[-1], \
        '_visible_lines must ask for the line, not a position in it'


# ── Highlight bands across a wrap ───────────────────────────────────────────
# GTK cannot be trusted about x within a character of a soft wrap, at either
# end. Measured on a wrapped line of the reading view:
#
#     '0'  x= 26 y=221 w=11   ← the line's LAST glyph, reported on the next
#     '3'  x=638 y=189 w= 0
#     '1'  x=625 y=189 w=13   → x+w = 638, the true right edge
#
# and at the other end, the first glyph of a continuation line is reported at
# x=47 while GTK draws it at 26, the view's own left margin.


class _FakeIter:
    """Enough of a GtkTextIter to walk a string."""

    def __init__(self, text, pos):
        self.text, self.pos = text, pos

    def copy(self):
        return _FakeIter(self.text, self.pos)

    def compare(self, other):
        return (self.pos > other.pos) - (self.pos < other.pos)

    def backward_char(self):
        if self.pos <= 0:
            return False
        self.pos -= 1
        return True

    def forward_char(self):
        if self.pos >= len(self.text):
            return False
        self.pos += 1
        return True

    def get_char(self):
        return self.text[self.pos] if self.pos < len(self.text) else ''


class _WrapView:
    """A view whose reports lie at the wrap exactly as GTK's do: the last
    glyph of a display line is reported on the NEXT line."""

    PER_LINE = 10

    def __init__(self, text):
        self.text = text

    def get_iter_location(self, it):
        class R:
            pass
        r = R()
        line, col = divmod(it.pos, self.PER_LINE)
        if col == self.PER_LINE - 1:        # the lie
            r.y, r.x, r.width = (line + 1) * 20, 0, 10
        else:
            r.y, r.x, r.width = line * 20, col * 10, 10
        return r

    @property
    def _BAND_WS(self):
        return rv.BibleTextView._BAND_WS

    def _line_right_edge(self, cur, seg_last, y0):
        return rv.BibleTextView._line_right_edge(self, cur, seg_last, y0)

    def _skip_ws_fwd(self, start, end):
        return rv.BibleTextView._skip_ws_fwd(self, start, end)

    def _resume_after(self, seg_end, cur, end):
        return rv.BibleTextView._resume_after(self, seg_end, cur, end)


def test_the_right_edge_ignores_what_wrapped_onto_the_next_line():
    """A band's width came out NEGATIVE — -538px in one measured case — and a
    `max(1.0, ...)` floor drew that as a 1px tick standing in the line above
    the band. A verse over three display lines got one band and two ticks."""
    text = 'abcdefghij' + 'klmnopqrst'
    view = _WrapView(text)
    cur = _FakeIter(text, 2)
    seg_last = _FakeIter(text, 10)          # one past the line's last glyph
    right = view._line_right_edge(cur, seg_last, 0)
    assert right == 90, right               # 'i' at x=80 + its width
    assert right > 2 * 10, 'the band would have no width at all'


def test_a_segment_with_nothing_on_its_line_reports_no_edge():
    text = 'abcdefghij' + 'klmnopqrst'
    view = _WrapView(text)
    cur = _FakeIter(text, 9)                # the lying glyph itself
    assert view._line_right_edge(cur, _FakeIter(text, 10), 0) is None


def test_the_next_segment_resumes_without_skipping_a_letter():
    """A `forward_char()` used to stand in the advance to step over the
    newline a segment ended on. It stepped over a real LETTER when the
    segment ended at a soft wrap, taking the opening glyph off every
    continuation line: «ars old» where the verse says «years old»."""
    text = 'abcdefghij' + 'klmnopqrst'
    view = _WrapView(text)
    end = _FakeIter(text, 20)
    nxt = view._resume_after(_FakeIter(text, 10), _FakeIter(text, 2), end)
    assert nxt is not None and nxt.pos == 10, 'a character was skipped'


def test_whitespace_between_segments_is_still_skipped():
    text = 'abcdefghi ' + 'klmnopqrst'
    view = _WrapView(text)
    end = _FakeIter(text, 20)
    nxt = view._resume_after(_FakeIter(text, 9), _FakeIter(text, 2), end)
    assert nxt is not None and nxt.pos == 10


def test_a_band_with_no_width_is_not_painted():
    """The floor that turned a collapsed segment into a visible mark."""
    import ast
    import inspect
    src = inspect.getsource(rv.BibleTextView._draw_band)
    tree = ast.parse(src.lstrip().replace('\n    ', '\n'))
    assigns = [n for n in ast.walk(tree)
               if isinstance(n, ast.Assign)
               and any(getattr(t, 'id', '') == 'seg_w' for t in n.targets)]
    assert assigns, 'seg_w is gone; this rule needs rewriting'
    for a in assigns:
        assert not (isinstance(a.value, ast.Call)
                    and getattr(a.value.func, 'id', '') == 'max'), \
            'a segment with no width must be dropped, not floored to 1px'


class _LineIter:
    """A position that knows whether it opens a buffer line."""

    def __init__(self, pos, starts, line_start_pos):
        self.pos, self._starts, self._ls = pos, starts, line_start_pos

    def copy(self):
        return _LineIter(self.pos, self._starts, self._ls)

    def compare(self, other):
        return (self.pos > other.pos) - (self.pos < other.pos)

    def starts_line(self):
        return self._starts


class _MarginView:
    LEFT = 26

    def get_left_margin(self):
        return self.LEFT

    def backward_display_line_start(self, it):
        it.pos = it._ls

    def _segment_left(self, cur, r0):
        return rv.BibleTextView._segment_left(self, cur, r0)


class _R:
    def __init__(self, x):
        self.x = x


def test_a_soft_wrapped_line_takes_the_margin_gtk_will_not_admit_to():
    view = _MarginView()
    # Opens its display line, but NOT a buffer line: a continuation.
    cur = _LineIter(pos=10, starts=False, line_start_pos=10)
    assert view._segment_left(cur, _R(47)) == 26


def test_an_indented_line_of_poetry_keeps_the_indent_it_is_drawn_with():
    """The regression the first version of this rule caused.

    A line of poetry is its own buffer line and its indent is real — GTK
    says 58 and means it. Taking the margin there dragged every band on
    every psalm 32px to the left, out from under the indent.
    """
    view = _MarginView()
    cur = _LineIter(pos=10, starts=True, line_start_pos=10)
    assert view._segment_left(cur, _R(58)) == 58


def test_a_segment_starting_mid_line_keeps_what_gtk_reports():
    view = _MarginView()
    cur = _LineIter(pos=40, starts=False, line_start_pos=10)
    assert view._segment_left(cur, _R(441)) == 441
