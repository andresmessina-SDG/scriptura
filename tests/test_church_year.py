"""Golden-date tests for the church-year engine."""
import datetime

import church_year as cy

D = datetime.date


class TestComputus:
    def test_gregorian_easter(self):
        for y, m, d in [(2008, 3, 23), (2011, 4, 24), (2016, 3, 27),
                        (2024, 3, 31), (2025, 4, 20), (2026, 4, 5),
                        (2027, 3, 28), (2038, 4, 25)]:
            assert cy.easter_gregorian(y) == D(y, m, d), y

    def test_orthodox_pascha_gregorian_dates(self):
        for y, m, d in [(2016, 5, 1), (2021, 5, 2), (2024, 5, 5),
                        (2025, 4, 20), (2026, 4, 12), (2027, 5, 2)]:
            assert cy.pascha_gregorian(y) == D(y, m, d), y

    def test_advent_sunday(self):
        assert cy.advent_sunday(2024) == D(2024, 12, 1)
        assert cy.advent_sunday(2025) == D(2025, 11, 30)
        assert cy.advent_sunday(2026) == D(2026, 11, 29)


def name(date, trad):
    d = cy.day_designation(date, trad)
    assert d is not None
    return d[1]


class TestAnglican:
    def test_trinitytide_week(self):
        # Sat 18 Jul 2026 is served by Sunday 12 Jul, the 6th after Trinity.
        assert name(D(2026, 7, 18), 'anglican') == 'The Sixth Sunday after Trinity'

    def test_whitsun_and_trinity(self):
        assert name(D(2026, 5, 24), 'anglican') == 'Whitsunday'
        assert name(D(2026, 5, 31), 'anglican') == 'Trinity Sunday'

    def test_pre_lent_and_lent(self):
        assert name(D(2026, 2, 1), 'anglican') == 'Septuagesima'
        assert name(D(2026, 2, 15), 'anglican') == 'Quinquagesima'
        assert name(D(2026, 2, 18), 'anglican') == 'Ash Wednesday'
        assert name(D(2026, 3, 22), 'anglican') == 'The Fifth Sunday in Lent'
        assert name(D(2026, 3, 29), 'anglican') == 'Palm Sunday'
        assert name(D(2026, 4, 3), 'anglican') == 'Good Friday'
        assert name(D(2026, 4, 5), 'anglican') == 'Easter Day'

    def test_ascension_and_after(self):
        assert name(D(2026, 5, 14), 'anglican') == 'Ascension Day'
        assert name(D(2026, 5, 17), 'anglican') == 'The Sunday after Ascension Day'

    def test_advent_and_stir_up(self):
        assert name(D(2026, 11, 22), 'anglican') == 'The Sunday next before Advent'
        assert name(D(2026, 11, 29), 'anglican') == 'The First Sunday in Advent'
        assert name(D(2026, 12, 20), 'anglican') == 'The Fourth Sunday in Advent'

    def test_christmastide(self):
        assert name(D(2026, 12, 25), 'anglican') == 'Christmas Day'
        assert name(D(2026, 12, 27), 'anglican') == 'St John the Evangelist'
        assert name(D(2026, 12, 30), 'anglican') == 'The Sunday after Christmas Day'
        assert name(D(2027, 1, 3), 'anglican') == 'The Second Sunday after Christmas'

    def test_epiphany_on_sunday_serves_its_week(self):
        # 2030: Jan 6 is a Sunday; Jan 7–12 carry the feast's week.
        assert D(2030, 1, 6).weekday() == 6
        assert name(D(2030, 1, 6), 'anglican') == 'The Epiphany'
        assert name(D(2030, 1, 9), 'anglican') == 'The Epiphany'
        assert name(D(2030, 1, 13), 'anglican') == 'The First Sunday after the Epiphany'

    def test_christmas_on_sunday_week_is_christmastide(self):
        # 2033: Dec 25 is a Sunday; Dec 29 sits in its week.
        assert D(2033, 12, 25).weekday() == 6
        assert name(D(2033, 12, 29), 'anglican') == 'Christmastide'

    def test_red_letter_feast(self):
        assert name(D(2026, 9, 29), 'anglican') == 'St Michael and All Angels'


class TestRoman:
    def test_after_pentecost_numbering(self):
        assert name(D(2026, 7, 18), 'roman') == 'The Seventh Sunday after Pentecost'

    def test_passion_and_low_sunday(self):
        assert name(D(2026, 3, 22), 'roman') == 'Passion Sunday'
        assert name(D(2026, 4, 12), 'roman') == 'Low Sunday'

    def test_corpus_christi(self):
        # Thursday after Trinity 2026.
        assert name(D(2026, 6, 4), 'roman') == 'Corpus Christi'

    def test_last_sunday_after_pentecost(self):
        assert name(D(2026, 11, 22), 'roman') == 'The Last Sunday after Pentecost'

    def test_principal_feasts(self):
        assert name(D(2026, 8, 15), 'roman') == 'The Assumption of the Blessed Virgin Mary'
        assert name(D(2026, 12, 8), 'roman') == 'The Immaculate Conception'


class TestOrthodox:
    def test_after_pentecost(self):
        assert name(D(2026, 7, 18), 'orthodox') == 'The Sixth Sunday after Pentecost'

    def test_triodion(self):
        # Pascha 2026 (Julian) = 12 Apr Gregorian.
        assert name(D(2026, 2, 1), 'orthodox') == 'Sunday of the Publican and the Pharisee'
        assert name(D(2026, 2, 22), 'orthodox') == 'Sunday of Forgiveness (Cheesefare)'
        assert name(D(2026, 2, 23), 'orthodox') == 'Clean Monday'
        assert name(D(2026, 3, 1), 'orthodox') == 'Sunday of Orthodoxy'

    def test_holy_week_and_pascha(self):
        assert name(D(2026, 4, 4), 'orthodox') == 'Lazarus Saturday'
        assert name(D(2026, 4, 5), 'orthodox') == 'Palm Sunday'
        assert name(D(2026, 4, 10), 'orthodox') == 'Great and Holy Friday'
        assert name(D(2026, 4, 12), 'orthodox') == 'Pascha'
        assert name(D(2026, 4, 19), 'orthodox') == 'Thomas Sunday'

    def test_pentecost_and_all_saints(self):
        assert name(D(2026, 5, 31), 'orthodox') == 'Pentecost'
        assert name(D(2026, 6, 7), 'orthodox') == 'The Sunday of All Saints'

    def test_winter_continues_last_years_count(self):
        # Jan 2027 Sundays precede the 2027 Triodion (Pascha 2 May 2027),
        # so they continue counting from Pentecost 2026 (31 May).
        assert 'Sunday after Pentecost' in name(D(2027, 1, 10), 'orthodox')

    def test_great_feasts(self):
        assert name(D(2026, 8, 6), 'orthodox') == 'The Transfiguration'
        assert name(D(2026, 1, 6), 'orthodox') == 'Theophany'


class TestSweep:
    def test_every_day_designates_across_years(self):
        # Corpus sweep: every day of 2024–2030 yields a non-empty
        # designation in every tradition (edge years included).
        day = D(2024, 1, 1)
        end = D(2030, 12, 31)
        while day <= end:
            for trad in cy.TRADITIONS:
                d = cy.day_designation(day, trad)
                assert d and d[0] and d[1], (day, trad)
            day += datetime.timedelta(days=1)

    def test_unknown_tradition_is_none(self):
        assert cy.day_designation(D(2026, 7, 18), 'martian') is None


class TestLocalization:
    """The pair this module returns is half key, half prose.

    The key is read by the collects pack and persisted nowhere else; it must
    stay English in every locale. The display half is the only part a reader
    sees, and it must follow the UI language. Translating the wrong half would
    silence every collect in a translated build, and nothing else would look
    wrong."""

    def _translated(self, monkeypatch, catalog):
        monkeypatch.setattr(cy, '_', lambda s: catalog.get(s, s))

    def test_display_translates_and_the_key_does_not(self, monkeypatch):
        self._translated(monkeypatch, {
            'The {ordinal} Sunday after Trinity': 'Le {ordinal} dimanche',
            'Seventh': 'septième',
            'The Annunciation': "L'Annonciation",
        })
        key, shown = cy.day_designation(D(2026, 7, 20), 'anglican')
        assert key == 'anglican:trinity7'
        assert shown == 'Le septième dimanche'
        key, shown = cy.day_designation(D(2026, 3, 25), 'anglican')
        assert key == 'anglican:feast:3-25'
        assert shown == "L'Annonciation"

    def test_every_designation_passes_through_the_catalog(self, monkeypatch):
        # A display string that never reaches _() stays English however the
        # app is translated. Sweeping with a catalog that marks everything it
        # is asked for finds any that slipped past.
        seen = []
        monkeypatch.setattr(cy, '_', lambda s: seen.append(s) or f'<{s}>')
        day = D(2024, 1, 1)
        while day <= D(2027, 12, 31):
            for trad in cy.TRADITIONS:
                shown = cy.day_designation(day, trad)[1]
                assert shown.startswith('<'), (day, trad, shown)
            day += datetime.timedelta(days=1)
        assert 'Christmas Day' in seen


class TestOrdinalCoverage:
    def test_every_ordinal_the_engine_asks_for_has_a_word(self, monkeypatch):
        # The longest series is not the one it looks like. Trinity stops at
        # twenty-six, but the Orthodox count after Pentecost runs on through
        # the winter until the Triodion opens and reaches thirty-seven. A
        # table that stops short does not fail: it renders "The 37 Sunday
        # after Pentecost", which is correct in no language at all.
        asked = set()
        real = cy._ordinal
        monkeypatch.setattr(cy, '_ordinal',
                            lambda n: (asked.add(n) or real(n)))
        day = D(1900, 1, 1)
        while day <= D(2099, 12, 31):
            for trad in cy.TRADITIONS:
                cy.day_designation(day, trad)
            day += datetime.timedelta(days=365)
        # A yearly stride would miss the winter tail, so walk those weeks too.
        day = D(2024, 11, 1)
        while day <= D(2027, 3, 1):
            cy.day_designation(day, 'orthodox')
            day += datetime.timedelta(days=1)
        assert asked, 'no ordinals were requested at all'
        assert max(asked) >= 37, max(asked)
        for n in asked:
            assert real(n) != str(n), f'no ordinal word for {n}'
