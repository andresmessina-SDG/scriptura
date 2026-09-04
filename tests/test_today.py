"""Unit tests for the Today page's pure helpers (whisper + epigraph)."""
import os

import pytest

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
