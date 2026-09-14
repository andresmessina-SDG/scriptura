"""Unit tests for the Today page's pure helpers (whisper + epigraph)."""
import os

import pytest

import reading_plans
import scribal_field
import today_page

_DATA_COLLECTS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'data', 'collects.toml')


class TestProgressWhisper:
    def test_degenerate_totals_are_silent(self):
        assert today_page.progress_whisper(1, 0) == ''
        assert today_page.progress_whisper(1, 1) == ''
        assert today_page.progress_whisper(0, 365) == ''

    def test_ladder_is_monotonic_over_a_year(self):
        # Every day of a 365-day plan gets some phrase, and the sequence
        # only ever moves forward through the ladder (no regressions).
        phrases = [today_page.progress_whisper(d, 365) for d in range(1, 366)]
        assert all(phrases)
        order = []
        for p in phrases:
            if not order or order[-1] != p:
                order.append(p)
        assert len(order) == len(set(order))  # each tier appears once

    def test_halfway_reads_as_halfway(self):
        assert 'halfway' in today_page.progress_whisper(183, 365)

    def test_final_day(self):
        assert today_page.progress_whisper(365, 365) == 'the final days'

    def test_short_plan_hits_the_same_ladder(self):
        assert today_page.progress_whisper(1, 30) == 'just getting started'
        assert 'finished' in today_page.progress_whisper(29, 30)


class TestPassageDisplay:
    def test_full_names_and_ranges(self):
        readings = [('Psalms', 111), ('Psalms', 112), ('Psalms', 113),
                    ('Psalms', 114), ('Psalms', 115)]
        assert today_page.passage_display(readings) == 'Psalms 111–115'

    def test_blended_day_joins_with_middots(self):
        readings = [('1 Kings', 12), ('1 Kings', 13), ('Psalms', 88),
                    ('Romans', 6)]
        assert (today_page.passage_display(readings)
                == '1 Kings 12–13 · Psalms 88 · Romans 6')

    def test_empty(self):
        assert today_page.passage_display([]) == ''


RAW = (
    '<title>July 18</title>'
    '<p><hi type="italic">My grace is  sufficient\n for thee.</hi>'
    ' <reference osisRef="Bible:2Cor.12.9">2 Corinthians'
    ' 12:9</reference></p>'
    '<p>Body text follows.</p>'
)


class TestParseEpigraph:
    def test_extracts_quote_and_reference(self):
        quote, ref = today_page.parse_epigraph(RAW)
        assert quote == 'My grace is sufficient for thee.'
        assert ref == '2 Corinthians 12:9'

    def test_no_quote_is_none(self):
        assert today_page.parse_epigraph('<p>plain body only</p>') is None
        assert today_page.parse_epigraph('') is None

    def test_quote_without_reference_still_serves(self):
        quote, ref = today_page.parse_epigraph(
            '<p><hi type="italic">A word in season.</hi></p>')
        assert quote == 'A word in season.'
        assert ref == ''

    def test_existing_quotation_marks_are_stripped(self):
        quote, _ref = today_page.parse_epigraph(
            '<p><hi type="italic">“Fear not.”</hi></p>')
        assert quote == 'Fear not.'

    TWO_SECTIONS = (
        '<title>July 18</title>'
        '<p><hi type="italic">Morning word.</hi>'
        ' <reference osisRef="Bible:Ps.5.3">Psalm 5:3</reference></p>'
        '<p>Morning body.</p>'
        '<p><hi type="italic">Evening word.</hi>'
        ' <reference osisRef="Bible:Ps.4.8">Psalm 4:8</reference></p>'
        '<p>Evening body.</p>'
    )

    def test_morning_takes_first_section(self):
        assert today_page.parse_epigraph(self.TWO_SECTIONS) == (
            'Morning word.', 'Psalm 5:3')

    def test_evening_takes_second_section(self):
        assert today_page.parse_epigraph(self.TWO_SECTIONS, evening=True) == (
            'Evening word.', 'Psalm 4:8')

    def test_evening_falls_back_when_single_section(self):
        assert today_page.parse_epigraph(RAW, evening=True) == (
            'My grace is sufficient for thee.', '2 Corinthians 12:9')

    def test_overlong_quote_is_cut_at_a_word(self):
        long = ' '.join(['word'] * 100)
        quote, _ref = today_page.parse_epigraph(
            f'<p><hi type="italic">{long}</hi></p>')
        assert len(quote) <= today_page._EPIGRAPH_MAX + 1
        assert quote.endswith('…')
        assert ' word…' in quote or quote.startswith('word')


class TestAccentedEpigraph:
    """Church Slavonic carries its accents as combining marks, and a mark
    only sits over its letter when the font gives it zero advance.

    Georgia does not. Measured at 19px the acute takes 13px of its own —
    wider than the letter it belongs to — so «Све́тлую» drew as "Све ́тлую"
    with the mark stranded after the vowel, in both roman and italic. It is
    a face the picker offers and one people choose, and the Today epigraph
    takes the reader's chosen family, so the Orthodox troparia landed in it.

    The earlier check that "Georgia shapes the accented text in a single
    run" was counting runs, which one font with a detached mark passes.
    """

    SLAVONIC = ('Све́тлую воскресе́ния про́поведь от А́нгела уве́девша '
                'Госпо́дни учени́цы')

    def test_accented_text_gets_a_mark_safe_face(self):
        assert today_page._mark_safe_attrs(self.SLAVONIC) is not None

    def test_unaccented_text_keeps_the_reader_s_own_face(self):
        """The override is for the text that needs it and nothing else — an
        English or Spanish collect stays in the face the reader chose."""
        assert today_page._mark_safe_attrs(
            'Almighty God, who hast given us thy Son') is None
        assert today_page._mark_safe_attrs('Dios todopoderoso') is None

    def test_every_shipped_slavonic_collect_is_covered(self):
        """A new troparion must not be able to slip in unguarded."""
        import tomllib
        with open(_DATA_COLLECTS, 'rb') as fh:
            texts = tomllib.load(fh)['orthodox']['ru']['texts']
        assert len(texts) >= 22
        bare = [k for k, v in texts.items()
                if today_page._mark_safe_attrs(v) is None]
        assert not bare, f'no accents at all in {bare}'

    def test_the_mark_actually_stops_taking_space(self):
        """The measurement the run count could not make. Without the
        attribute the acute advances 13px under Georgia; with it, none."""
        import gi
        gi.require_version('Pango', '1.0')
        gi.require_version('PangoCairo', '1.0')
        from gi.repository import Pango, PangoCairo

        ctx = PangoCairo.font_map_get_default().create_context()
        desc = Pango.FontDescription.from_string('Georgia 19')
        if desc.get_family().lower() != 'georgia':
            pytest.skip('Georgia not installed')

        def acute_advance(attrs):
            lay = Pango.Layout(ctx)
            lay.set_font_description(desc)
            if attrs is not None:
                lay.set_attributes(attrs)
            lay.set_text('е', -1)
            plain = lay.get_size()[0]
            lay.set_text('е́', -1)
            return (lay.get_size()[0] - plain) / Pango.SCALE

        if acute_advance(None) == 0:
            pytest.skip('this Georgia already attaches the mark')
        assert acute_advance(today_page._mark_safe_attrs('е́')) == 0


@pytest.fixture
def display():
    """Skip when there is no screen — TodayView is a real widget tree.

    `Gdk.Display.get_default()`, never `Gtk.init_check()`, whose True means
    nothing (GUIDANCE §4).
    """
    from gi.repository import Gdk, Gtk
    Gtk.init_check()
    if Gdk.Display.get_default() is None:
        pytest.skip('needs a display: TodayView builds real widgets')


def _settle():
    """Run the idles the page defers its widget moves onto (a breakpoint may
    not reparent from inside size-allocate — see TodayView._place_marks)."""
    from gi.repository import GLib
    ctx = GLib.MainContext.default()
    for _i in range(20):
        if not ctx.iteration(False):
            break


@pytest.fixture
def view(display):
    v = today_page.TodayView(lambda *a: None, lambda *a: None, lambda *a: None,
                             on_listen=lambda: None, on_write=lambda: None)
    v.populate(('John', 3), 'KJV', church_line='The Second Sunday in Advent')
    return v


class TestAdaptiveLayout:
    """The page answers the width it is given. These hold the two moves that
    a later refactor could silently undo."""

    def test_the_listen_mark_leaves_the_margin_when_there_is_none(self, view):
        # The whole point of the narrow mode: at 640px and under the disc
        # used to be drawn on top of the line beneath it.
        view.set_listen('Today’s reading')
        assert view._listen_mark.get_parent() is view._listen_card
        view._set_mode('narrow')
        _settle()
        assert view._listen_mark.get_parent() is view._listen_slot
        assert view._listen_slot.get_visible()
        assert not view._listen_card.get_visible()
        view._set_mode('')
        _settle()
        assert view._listen_mark.get_parent() is view._listen_card

    def test_a_mark_that_was_never_offered_stays_unoffered(self, view):
        # The journal door is always there, so the narrow slot still stands;
        # what must not appear is a play disc for a reading nobody has.
        view.clear_listen()
        view._set_mode('narrow')
        _settle()
        assert not view._listen_mark.get_visible()
        assert view._write_mark.get_visible()
        assert not view._listen_card.get_visible()

    def test_the_journal_door_is_a_mark_not_a_line_in_the_column(self, view):
        # It was a third centred link under Continue; it is now the left-hand
        # mark, and the column carries only the day and its two reading doors.
        assert view._write_btn.get_parent() is not None
        assert view._write_mark.get_parent() is view._write_holder
        assert view._write_btn.get_label() is None

    def test_a_page_with_no_journal_door_keeps_its_margins(self, display):
        # The margins are structural: without the pair the column would sit
        # off the page's centre whenever one mark was missing.
        v = today_page.TodayView(lambda *a: None, lambda *a: None,
                                 lambda *a: None, on_listen=lambda: None)
        assert not v._write_holder.get_visible()
        assert (v._margin_left.get_size_request().width
                == v._margin_right.get_size_request().width)

    def test_the_date_lines_move_to_the_rail_and_back(self, view):
        assert view._eyebrow.get_visible() and not view._rail.get_visible()
        view._set_mode('wide')
        _settle()
        assert view._rail.get_visible()
        assert not view._eyebrow.get_visible()
        assert not view._church.get_visible()
        assert view._rail_date.get_text() == view._eyebrow.get_text()
        assert view._rail_church.get_text() == view._church.get_text()
        # The margins hold their width on both sides, so the column stays on
        # the page's own centre whether or not a mark is in them.
        assert (view._margin_left.get_size_request().width
                == view._margin_right.get_size_request().width)
        view._set_mode('')
        _settle()
        assert view._eyebrow.get_visible() and view._church.get_visible()
        assert not view._rail.get_visible()

    def test_a_day_with_no_designation_leaves_the_rail_line_empty(self, view):
        view.populate(('John', 3), 'KJV', church_line=None)
        view._set_mode('wide')
        _settle()
        assert not view._rail_church.get_visible()
        view._set_mode('')
        _settle()
        assert not view._church.get_visible()


class TestAntiphon:
    """The day's opening line — the page's only guaranteed Scripture."""

    @pytest.fixture
    def chapter(self, monkeypatch):
        import content
        rows: list = []

        def fake(_name, _book, _chapter):
            return rows

        monkeypatch.setattr(content, 'load_chapter', fake)
        return rows

    def test_the_day_opens_at_verse_one(self, chapter):
        # Verse 0 is a Psalm superscription where a module carries one, and
        # a day does not open at "A Psalm of David".
        chapter.extend([(0, 'A Psalm of David'), (1, 'The LORD is my shepherd')])
        assert (today_page.fetch_antiphon('KJV', 'Psalms', 23)
                == 'The LORD is my shepherd')

    def test_a_chapter_that_is_all_preamble_still_answers(self, chapter):
        chapter.append((0, 'A Song of degrees'))
        assert today_page.fetch_antiphon('KJV', 'Psalms', 120) == 'A Song of degrees'

    def test_a_chapter_the_module_cannot_answer_is_silent(self, chapter):
        assert today_page.fetch_antiphon('KJV', 'Psalms', 23) is None

    def test_a_long_verse_is_cut_at_a_word(self, chapter):
        chapter.append((1, 'word ' * 60))
        got = today_page.fetch_antiphon('KJV', 'Esther', 8)
        assert got is not None
        assert got.endswith('…')
        assert len(got) <= today_page._ANTIPHON_MAX + 1
        assert 'wor…' not in got          # never mid-word

    def test_the_target_is_the_plan_day_then_the_last_place(self, view):
        assert view.antiphon_target() == view._begin_target or \
            view.antiphon_target() == ('John', 3)
        view._begin_target = None
        view._continue_target = ('Romans', 2)
        assert view.antiphon_target() == ('Romans', 2)
        view._continue_target = None
        assert view.antiphon_target() is None


class TestTheFootLine:
    """A prayer is not a quotation, and the page says a thing once."""

    def test_a_collect_is_set_roman(self, view):
        view.set_epigraph('Almighty God, give us grace', 'Book of Common Prayer',
                          quoted=False)
        assert view._epigraph_verse.has_css_class('today-prayer')
        assert '“' not in view._epigraph_verse.get_text()

    def test_a_cited_verse_keeps_the_italic_and_the_marks(self, view):
        view.set_epigraph('For God so loved the world', 'John 3:16', quoted=True)
        assert not view._epigraph_verse.has_css_class('today-prayer')
        assert view._epigraph_verse.get_text().startswith('“')

    def test_the_face_changes_back(self, view):
        view.set_epigraph('Almighty God', 'BCP', quoted=False)
        view.set_epigraph('For God so loved', 'John 3:16', quoted=True)
        assert not view._epigraph_verse.has_css_class('today-prayer')

    def test_the_days_name_is_not_printed_twice(self, view):
        view.populate(('John', 3), 'KJV',
                      church_line='The First Sunday in Advent')
        view.set_epigraph(
            'Almighty God, give us grace',
            'The First Sunday in Advent — Book of Common Prayer', quoted=False)
        assert view._epigraph_src.get_text() == 'Book of Common Prayer'

    def test_a_source_that_is_not_the_days_name_is_left_alone(self, view):
        view.populate(('John', 3), 'KJV',
                      church_line='The First Sunday in Advent')
        view.set_epigraph('For God so loved', 'John 3:16 — Daily Strength')
        assert view._epigraph_src.get_text() == 'John 3:16 — Daily Strength'

    def test_no_calendar_leaves_every_source_whole(self, view):
        view.populate(('John', 3), 'KJV', church_line=None)
        view.set_epigraph('x', 'The First Sunday in Advent — BCP', quoted=False)
        assert view._epigraph_src.get_text().startswith('The First Sunday')


class TestTheGround:
    """Parchment, with the alphabet written in the margins."""

    DARK = ((0.118, 0.118, 0.118), (0.847, 0.824, 0.780))
    LIGHT = ((0.969, 0.957, 0.933), (0.169, 0.149, 0.133))
    SEPIA = ((0.957, 0.925, 0.847), (0.227, 0.184, 0.133))

    def test_the_letters_run_in_order_so_nothing_spells_anything(self):
        # An abecedary, not a scatter: a reader of Hebrew must find a
        # familiar object, and no run of letters can land on the Name.
        assert scribal_field._ALEF == sorted(scribal_field._ALEF)
        # Twenty-two, not the block's twenty-seven: the five final forms are
        # positional variants, not letters of the alphabet.
        assert len(scribal_field._ALEF) == 22
        assert not set(scribal_field._ALEF) & set(scribal_field._FINALS)
        # Greek is twenty-four, with no second sigma.
        assert len(scribal_field._ALPHA) == 24

    def test_no_greek_letter_can_be_read_as_latin(self):
        # Half the Greek capitals are Latin homographs and with no word
        # around them a capital beta simply reads as a B.
        assert not set(scribal_field._ALPHA) & set(
            'ABEZHIKMNOPTYXΑΒΕΖΗΙΚΜΝΟΡΤΥΧ')

    def test_the_ink_is_weighed_against_the_paper_not_fixed(self):
        # The bug this replaced: a flat alpha, scaled DOWN for light paper,
        # left the field invisible there. Light and sepia need MORE ink than
        # the dark page, not less.
        dark = scribal_field.alpha_for(*self.DARK)
        assert scribal_field.alpha_for(*self.LIGHT) > dark
        assert scribal_field.alpha_for(*self.SEPIA) > dark

    @pytest.mark.parametrize('paper,ink', [DARK, LIGHT, SEPIA,
                                           ((0.0, 0.0, 0.0), (0.8, 0.8, 0.8))])
    def test_every_paper_lands_at_one_perceived_weight(self, paper, ink):
        a = scribal_field.alpha_for(paper, ink)
        mixed = tuple(paper[k] * (1 - a) + ink[k] * a for k in range(3))
        got = abs(scribal_field._lstar(scribal_field._luminance(mixed))
                  - scribal_field._lstar(scribal_field._luminance(paper)))
        assert abs(got - scribal_field.WEIGHT_FIELD) < 0.05

    def test_the_type_column_never_stands_on_letters(self):
        w = 1366.0
        band, fade = scribal_field._margin_band(w)
        assert scribal_field._margin_weight(w / 2, w, band, fade) == 0.0
        assert scribal_field._margin_weight(4.0, w, band, fade) == 1.0

    def test_a_narrow_page_stands_on_bare_skin(self):
        # Below about 906px there is no margin left to write in, and two
        # cramped strips of letters read worse than none.
        assert scribal_field._margin_band(900.0) == (0.0, 0.0)
        assert scribal_field._margin_band(1100.0)[0] > 0
        widths = [scribal_field._margin_band(float(w))[0]
                  for w in range(960, 1920, 40)]
        assert widths == sorted(widths)

    def test_the_sheet_is_the_same_every_time_it_is_drawn(self):
        # A random one would reshuffle the moment anything repainted.
        import cairo
        out = []
        for _i in range(2):
            surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 400, 200)
            cr = cairo.Context(surf)
            scribal_field.draw_parchment(cr, 400, 200, self.DARK[1], 0.02)
            scribal_field.draw_abecedary(cr, 400, 200, self.DARK[1], 0.04)
            surf.flush()
            out.append(bytes(surf.get_data()))
        assert out[0] == out[1]

    def test_the_sheet_is_struck_once_and_then_blitted(self):
        # It costs ~43ms to draw and the page repaints on every frame of an
        # animation, so a second ask for the same page must not redraw it.
        scribal_field.forget()
        first = scribal_field.sheet(300, 200, *self.DARK)
        assert first is not None
        assert scribal_field.sheet(300, 200, *self.DARK) is first
        assert scribal_field.sheet(300, 200, *self.LIGHT) is not first

    def test_a_resized_window_cannot_grow_the_cache_without_bound(self):
        scribal_field.forget()
        for w in range(200, 260):
            scribal_field.sheet(w, 100, *self.DARK)
        assert len(scribal_field._cache) <= 4


class TestTheFinishedPlan:
    """The page must not offer an alternative to nothing."""

    @pytest.fixture
    def plan(self, monkeypatch):
        state = {'day': 12, 'total': 30, 'done': set()}
        monkeypatch.setattr(reading_plans, 'get_active',
                            lambda: ('p', '2026-01-01'))
        monkeypatch.setattr(reading_plans, 'today_index',
                            lambda _s: state['day'])
        monkeypatch.setattr(reading_plans, 'get_plan_days',
                            lambda _p: [[('Psalms', 111)]] * state['total'])
        monkeypatch.setattr(reading_plans, 'get_plans',
                            lambda: [{'id': 'p', 'name': 'Psalms in 30 Days'}])
        # Patched too, or the anchor reads the real plan file.
        monkeypatch.setattr(reading_plans, 'get_completed',
                            lambda _p: set(state['done']))
        return state

    def test_a_running_plan_makes_continue_the_alternative(self, view, plan):
        view.populate(('Romans', 2), 'KJV')
        assert view._begin_btn.get_visible()
        assert view._continue_btn.get_label().startswith('Or ')

    def test_a_finished_plan_still_offers_a_way_forward(self, view, plan):
        plan['day'] = 30                       # past the last day
        plan['done'] = set(range(30))          # and every day of it read
        view.populate(('Romans', 2), 'KJV')
        assert view._begin_btn.get_visible()
        assert 'plan' in view._begin_btn.get_label().lower()
        assert view._begin_target is None      # the door goes to the plans

    def test_a_finished_plan_stops_counting_days(self, view, plan):
        plan['day'] = 99
        plan['done'] = set(range(30))
        view.populate(('Romans', 2), 'KJV')
        # The plan's own name, whose words are its own — what must be gone
        # is the running count ("— day 30") the plan page appends.
        assert view._kicker.get_text() == 'Psalms in 30 Days'
        assert '—' not in view._kicker.get_text()

    def test_a_day_with_nothing_appointed_offers_continue_plainly(
            self, view, plan, monkeypatch):
        # The only state left where the page has no primary door: the "Or"
        # must not stand alone above it.
        monkeypatch.setattr(reading_plans, 'get_plan_days',
                            lambda _p: [[]] * plan['total'])
        view.populate(('Romans', 2), 'KJV')
        assert not view._begin_btn.get_visible()
        assert not view._continue_btn.get_label().startswith('Or ')

    def test_the_verse_falls_back_to_the_place_left_off(self, view, plan):
        plan['day'] = 30
        plan['done'] = set(range(30))
        view.populate(('Romans', 2), 'KJV')
        assert view.antiphon_target() == ('Romans', 2)


class TestALapsedSchedule:
    """A plan whose dates have run out but whose days have not been read.

    His: Psalms in 30 Days started 2026-07-19, two days read, opened on
    2026-09-13 — day index 56 of 30. The page said "Plan complete" over a
    panel that said "2 of 30 days read".
    """

    @pytest.fixture
    def lapsed(self, monkeypatch):
        state = {'day': 56, 'total': 30, 'done': {0, 1}}
        monkeypatch.setattr(reading_plans, 'get_active',
                            lambda: ('p', '2026-07-19'))
        monkeypatch.setattr(reading_plans, 'today_index',
                            lambda _s: state['day'])
        monkeypatch.setattr(reading_plans, 'get_plan_days',
                            lambda _p: [[('Psalms', 100 + i)]
                                        for i in range(state['total'])])
        monkeypatch.setattr(reading_plans, 'get_plans',
                            lambda: [{'id': 'p', 'name': 'Psalms in 30 Days'}])
        monkeypatch.setattr(reading_plans, 'get_completed',
                            lambda _p: set(state['done']))
        return state

    def test_it_is_not_called_complete(self, view, lapsed):
        view.populate(('Romans', 2), 'KJV')
        assert view._passage.get_text() != 'Plan complete'

    def test_it_offers_the_earliest_unread_day(self, view, lapsed):
        view.populate(('Romans', 2), 'KJV')
        assert 'day 3' in view._kicker.get_text()      # days 1 and 2 are read
        assert view._begin_target == ('Psalms', 102)

    def test_a_gap_is_picked_up_at_the_gap(self, view, lapsed):
        lapsed['done'] = {0, 1, 5, 6}
        view.populate(('Romans', 2), 'KJV')
        assert view._begin_target == ('Psalms', 102)   # day 3, not day 8

    def test_every_day_read_is_complete_whatever_the_date(self, view, lapsed):
        lapsed['done'] = set(range(30))
        view.populate(('Romans', 2), 'KJV')
        assert view._passage.get_text() == 'Plan complete'
