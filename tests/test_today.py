"""Unit tests for the Today page's pure helpers (whisper + epigraph)."""
import today_page


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
