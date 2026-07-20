"""Guards for the bundled collects pack: full-year coverage (every key the
engine can emit resolves to a text), no orphaned pack keys, and the
epigraph fallback order (devotional wins, collect fills the gap)."""
import datetime
import re

import church_year
import collects
import today_page


def _emitted_keys(tradition, years=range(2020, 2041)):
    """Every designation key the engine emits for `tradition` across a
    21-year daily sweep — wide enough to include the rare shapes (27
    Sundays after Trinity, Christmas on a Sunday, earliest Easter)."""
    keys = set()
    for year in years:
        day = datetime.date(year, 1, 1)
        while day.year == year:
            desig = church_year.day_designation(day, tradition)
            assert desig is not None
            keys.add(desig[0])
            day += datetime.timedelta(days=1)
    return keys


class TestAnglicanCoverage:
    def test_every_emitted_key_has_a_text(self):
        for key in sorted(_emitted_keys('anglican')):
            assert collects.collect_for(key) is not None, key

    def test_no_orphan_pack_keys(self):
        pack = collects._pack()['anglican']
        emitted = {k.split(':', 1)[1] for k in _emitted_keys('anglican')}
        reachable = {pack['aliases'].get(s, s) for s in emitted}
        for sub in pack['texts']:
            assert sub in reachable, f'unreachable pack text: {sub}'
        for alias, target in pack['aliases'].items():
            assert target in pack['texts'], f'alias to nowhere: {alias}'

    def test_texts_look_like_collects(self):
        pack = collects._pack()['anglican']
        for sub, text in pack['texts'].items():
            assert text.endswith('Amen.'), sub
            assert 100 < len(text) < 900, sub

    def test_source_line(self):
        found = collects.collect_for('anglican:trinity7')
        assert found is not None
        assert found[1] == 'The Collect · The Book of Common Prayer, 1662'

    def test_unknown_keys_are_none(self):
        assert collects.collect_for('anglican:nonsense') is None
        assert collects.collect_for('roman:good_friday') is None
        assert collects.collect_for('') is None


class TestOrthodoxTones:
    """The Sundays after Pentecost are keyed by Octoechos tone, not by
    Sunday: the resurrectional Troparion cycles through eight tones, so 36
    emitted Sunday keys resolve to 8 texts. The great feasts have proper
    hymns and are covered separately below — between them the year is still
    only partly filled, which these tests assert rather than paper over."""

    def _sunday_keys(self):
        return sorted(
            (k for k in _emitted_keys('orthodox')
             if k.split(':', 1)[1].startswith('pentecost')
             and k.split(':', 1)[1][9:].isdigit()),
            key=lambda k: int(k.split(':', 1)[1][9:]))

    def test_every_sunday_after_pentecost_resolves(self):
        keys = self._sunday_keys()
        assert len(keys) >= 32, f'expected the full cycle, got {len(keys)}'
        for key in keys:
            assert collects.collect_for(key) is not None, key

    def test_tone_cycle_matches_hapgood_rubric(self):
        # Hapgood: the Second Sunday takes the First Tone, and "on the tenth
        # Sunday after Pentecost, the First Tone is used again."
        pack = collects._pack()['orthodox']
        for n in range(2, 38):
            expected = f'tone{((n - 1) % 8) or 8}'
            assert pack['aliases'][f'pentecost{n}'] == expected, n
        assert pack['aliases']['pentecost2'] == 'tone1'
        assert pack['aliases']['pentecost10'] == 'tone1'

    def test_eight_distinct_tone_texts(self):
        texts = collects._pack()['orthodox']['texts']
        tones = {k: v for k, v in texts.items() if k.startswith('tone')}
        assert len(tones) == 8
        assert len(set(tones.values())) == 8

    def test_aliases_all_land(self):
        pack = collects._pack()['orthodox']
        for alias, target in pack['aliases'].items():
            assert target in pack['texts'], f'alias to nowhere: {alias}'

    def test_texts_are_clean_of_scan_artifacts(self):
        # The source is OCR; these are the failure signatures a bad
        # extraction leaves behind (stray marks, run-on words, page furniture).
        import re
        for sub, text in collects._pack()['orthodox']['texts'].items():
            assert not re.search(r'[\\%_{}|]', text), sub
            assert 'Digitized' not in text, sub
            assert 'exultinglyto' not in text, sub
            assert text[-1] in '.!', sub

    def test_source_line(self):
        found = collects.collect_for('orthodox:pentecost7')
        assert found is not None
        assert found[1].startswith('The Troparion · Hapgood')


class TestOrthodoxFeasts:
    """The great feasts carry proper Tropária rather than the week's tone.
    Hapgood's feast chapters are dense with troparia that are not the day's —
    a canon has dozens, and the Paschal chapter labels the hymn of the Hours
    the same way it labels the Paschal Troparion. So these guard the ways a
    plausible-reading wrong hymn gets in."""

    def _feasts(self):
        texts = collects._pack()['orthodox']['texts']
        return {k: v for k, v in texts.items() if not k.startswith('tone')}

    def test_keyed_to_days_the_engine_emits(self):
        emitted = {k.split(':', 1)[1] for k in _emitted_keys('orthodox')}
        for sub in self._feasts():
            assert sub in emitted, f'troparion keyed to a non-existent day: {sub}'

    def test_pascha_is_the_paschal_troparion(self):
        # The one assignment worth naming: the chapter's labelled troparion is
        # "In the Grave with the body ...", the hymn of the Paschal Hours. It
        # reads perfectly and it is the wrong hymn for the day.
        found = collects.collect_for('orthodox:pascha')
        assert found is not None
        assert found[0].startswith('Christ is risen from the dead')

    def test_no_two_feasts_share_a_hymn(self):
        seen = {}
        for sub, text in self._feasts().items():
            assert text[:60] not in seen, f'{sub} duplicates {seen[text[:60]]}'
            seen[text[:60]] = sub

    def test_hymns_are_whole(self):
        # A slice that stops short keeps the rubric that follows, or ends
        # mid-clause; one that runs long swallows the Kondák or the
        # Velitchánie, which belong to the feast but are not its Troparion.
        for sub, text in self._feasts().items():
            assert 90 < len(text) < 900, f'{sub}: implausible length'
            assert text[-1] in '.!', f'{sub}: ends mid-clause'
            assert not re.search(r'The Exaltation|Collect-Hymn|Velitch|Kond'
                                 r'|Thrice|See page', text), f'{sub}: rubric'
            assert not re.search(r'[\\%_{}|<>^]|Digitized|VjOOQ',
                                 text), f'{sub}: scan mark'


class TestRomanPartial:
    """The Roman section is a VERIFIED SUBSET, not full-year coverage: its
    source is OCR, and a key ships only when two public-domain witnesses
    attest it. So these guard the invariants that make a partial pack safe —
    never that every day resolves, which would be a false claim."""

    def _pack(self):
        return collects._pack()['roman']

    def test_only_real_keys(self):
        # A collect on a key the engine never emits is a prayer nobody sees;
        # worse, it means the extractor invented a day (a "lent6" once did).
        emitted = {k.split(':', 1)[1] for k in _emitted_keys('roman')}
        for sub in self._pack()['texts']:
            assert sub in emitted, f'roman text keyed to a non-existent day: {sub}'

    def test_no_two_days_share_a_collect(self):
        # A duplicate means a heading was double-counted upstream, which puts
        # a real prayer on the wrong day — the failure this pack most risks.
        texts = self._pack()['texts']
        seen = {}
        for sub, text in texts.items():
            key = text[:80]
            assert key not in seen, f'{sub} duplicates {seen.get(key)}'
            seen[key] = sub

    def test_texts_are_lexically_clean(self):
        # Both witnesses are Google OCR, so a corruption present in both never
        # becomes a divergence. This is the only check that catches it.
        import re
        words = {w.strip().lower() for w in open('/usr/share/dict/words')}
        for sub, text in self._pack()['texts'].items():
            for w in re.findall(r"[A-Za-z']{3,}", text):
                t = w.lower().strip("'")
                # A possessive is a noun plus a clitic and no wordlist carries
                # the joined form; "Son's" once looked like a corruption and
                # cost Easter Sunday its collect.
                if t.endswith("'s"):
                    t = t[:-2]
                # Archaic verb morphology no wordlist carries. The -y verbs
                # take -ie- ("purify" -> "purifiest"), which is why the stem
                # is also tried with its final i restored to y.
                def archaic(tok):
                    for x in ('eth', 'est', 'edst'):
                        if not tok.endswith(x):
                            continue
                        stem = tok[:-len(x)]
                        if (stem in words or stem + 'e' in words
                                or (stem.endswith('i')
                                    and stem[:-1] + 'y' in words)):
                            return True
                    return False

                ok = t in words or t.rstrip('s') in words or archaic(t)
                assert ok, f'{sub}: suspect token {w!r}'

    def test_texts_look_like_collects(self):
        for sub, text in self._pack()['texts'].items():
            assert 60 < len(text) < 900, sub
            # Trinity Sunday is set "O almighty and everlasting God" — the
            # book does not capitalise the adjective there, and the address is
            # no less an address for it.
            assert re.search(r'\bO (?:God|Lord|[Aa]lmighty)|\bAlmighty\b',
                             text), sub

    def test_texts_end_at_the_prayer(self):
        # The missal's printed conclusion ("Thro'." / "Who liveth.") is the
        # collect's right edge; it is dropped as the printing abbreviation it
        # is, and everything past it is page furniture made of ordinary
        # English — a rubric, a signature mark, a page cross-reference. The
        # lexical sweep is blind to that, so it is checked structurally here.
        for sub, text in self._pack()['texts'].items():
            assert text.endswith('.'), f'{sub}: no full stop at the edge'
            tail = re.sub(r'[^A-Za-z ]', '', text.split('.')[-2][-24:])
            assert not re.search(r'\b(Thro|Thio|Who liveth|Who livest|M m)\b',
                                 tail), f'{sub}: conclusion or mark left in'
            assert '|' not in text, f'{sub}: column rule left in'

    def test_no_saints_collect_on_a_temporal_day(self):
        # The Proper of Time's collects never commemorate a named saint, so
        # one that does was reached from the Proper of Saints and is on the
        # wrong day. Quinquagesima once held the collect of St Andrew Corsini
        # — a real prayer, correctly transcribed, and wrong.
        #
        # The feast keys are the Proper of Saints itself and are exempt:
        # naming a saint is what those collects are for.
        for sub, text in self._pack()['texts'].items():
            if sub.startswith('feast:'):
                continue
            assert not re.search(r'\bblessed\s+[A-Z]|\bthy\s+(?:Confessor'
                                 r'|Martyr|Bishop)\b', text), \
                f'{sub}: a saint\'s collect on a day of the Proper of Time'

    def test_lent_is_in_its_printed_order(self):
        # The Lent series once shipped shifted by two, because "FRIDAY before
        # the I. Sunday in Lent." was read as Lent I's own heading and pushed
        # every Sunday down. Nothing in the pack looked wrong. Lent I is the
        # one collect of the four that names the season's yearly observance,
        # so it pins the series to the missal's printed numerals.
        texts = self._pack()['texts']
        lent = {k: v for k, v in texts.items() if re.fullmatch(r'lent\d', k)}
        assert 'lent1' in lent, 'Lent I is the anchor of the series'
        assert 'yearly observation of Lent' in lent['lent1'], \
            'lent1 is not the collect the missal prints under "I. SUNDAY IN LENT."'
        assert len(set(lent.values())) == len(lent)

    def test_advent_is_in_its_printed_order(self):
        # Advent I and IV open on the same words, because the missal prints
        # the same Latin incipit over both ("Excita, quaesumus, Domine,
        # potentiam tuam, et veni"). A one-Sunday shift between them would
        # therefore look right at a glance. They part at the petition, and
        # that is what pins them: the First Sunday asks deliverance from the
        # dangers of our sins, the Fourth succour by God's great might.
        texts = self._pack()['texts']
        assert 'imminent dangers' in texts['advent1'], \
            'advent1 is not the collect under "FIRST SUNDAY OF ADVENT."'
        assert 'great might' in texts['advent4'], \
            'advent4 is not the collect under "FOURTH SUNDAY IN ADVENT."'
        assert len({texts[f'advent{n}'] for n in range(1, 5)}) == 4

    def test_sanctorale_collects_name_their_own_saint(self):
        # The Proper of Saints is reached by a different route from the Proper
        # of Time, and its collects are built on shared formulas — "that what
        # we cannot obtain by our own weakness may be granted us by his
        # prayers" serves any number of saints. Whoever the prayer names is
        # the one thing that cannot be shared, so each keyed feast is pinned
        # to its own.
        texts = self._pack()['texts']
        for sub, whom in [('feast:6-24', 'John the Baptist'),
                          ('feast:7-25', 'James'),
                          ('feast:12-26', 'martyrdom'),
                          ('feast:8-6', 'transfiguration'),
                          ('feast:9-29', 'angels'),
                          ('feast:11-1', 'all thy saints'),
                          ('feast:6-29', 'Peter and Paul')]:
            assert whom in texts[sub], f'{sub} does not name {whom}'

    def test_all_souls_is_the_only_prayer_for_the_dead(self):
        # A collect praying for the departed is, on any other day, a sign that
        # the parse wandered into the burial office — which is how Advent IV
        # once came to hold it. On the second of November it is the Mass
        # itself. Both halves are worth pinning: that the day has that prayer,
        # and that no other day does.
        texts = self._pack()['texts']
        assert 'souls of thy servants departed' in texts['feast:11-2']
        for sub, text in texts.items():
            if sub == 'feast:11-2':
                continue
            assert not re.search(r'pains of hell|carried into paradise'
                                 r'|souls of thy servants departed', text), sub
        # All Saints stands the day before, and in the book the two Masses are
        # a page apart.
        assert texts['feast:11-1'] != texts['feast:11-2']

    def test_the_purification_is_the_presentation_in_the_temple(self):
        # Its collect sits nearly six thousand characters from its heading,
        # with the blessing of the candles in between, so the risk is not a
        # wrong prayer but a stray one.
        text = self._pack()['texts']['feast:2-2']
        assert 'presented in the temple' in text

    def test_the_annunciation_is_the_prayer_it_was_sent_to(self):
        # The missal prints no collect under the Annunciation: it sends the
        # reader to the second collect of the first Sunday of Advent, which is
        # the commemoration of Our Lady. So this text is fetched from the
        # Advent pages, and the two things worth pinning are that it is the
        # right prayer — it speaks of the angel's message — and that it did
        # not come back holding Advent's own collect instead.
        texts = self._pack()['texts']
        assert 'angel delivered his message' in texts['feast:3-25']
        assert texts['feast:3-25'] != texts['advent1']

    def test_the_gesima_sundays_are_not_confused(self):
        # Septuagesima and Quinquagesima are both printed under the incipit
        # "Preces" and both open "Mercifully hear ... we beseech thee, O
        # Lord", because the Latin differs only in whose prayers are meant:
        # "preces populi tui" against "preces nostras". That one word is the
        # whole difference between the two days.
        texts = self._pack()['texts']
        assert 'the prayers of thy people' in texts['septuagesima']
        assert 'Mercifully hear our prayers' in texts['quinquagesima']

    def test_source_line(self):
        found = collects.collect_for('roman:easter3')
        assert found is not None
        assert found[1] == ('The Collect · The Roman Missal for the '
                            'Use of the Laity, 1861')

    def test_unfilled_days_stay_silent(self):
        # Partial coverage must degrade to silence, never to a wrong prayer.
        # Good Friday stands for the days the source cannot give: its prayers
        # are introduced by "Let us pray", not by a COLLECT rubric, with the
        # veneration of the Cross between the heading and the Mass.
        assert collects.collect_for('roman:good_friday') is None


class TestEpigraphFallback:
    def test_collect_fills_empty_devotional_slot(self, monkeypatch):
        import sword_bridge
        monkeypatch.setattr(
            sword_bridge, 'installed_devotional_modules', lambda: [])
        got = today_page.fetch_epigraph('anglican:advent1')
        assert got is not None
        text, source, quoted = got
        assert text.startswith('Almighty God, give us grace')
        assert quoted is False

    def test_no_tradition_stays_silent(self, monkeypatch):
        import sword_bridge
        monkeypatch.setattr(
            sword_bridge, 'installed_devotional_modules', lambda: [])
        assert today_page.fetch_epigraph(None) is None

    def test_devotional_wins(self, monkeypatch):
        import sword_bridge
        raw = ('<p><hi type="italic">The Lord is my shepherd.</hi> '
               '<reference>Ps. 23:1</reference></p>')
        monkeypatch.setattr(
            sword_bridge, 'installed_devotional_modules', lambda: ['Dev'])
        monkeypatch.setattr(
            sword_bridge, 'get_devotional_raw', lambda _n: raw)
        monkeypatch.setattr(
            sword_bridge, 'module_info',
            lambda _n: {'description': 'A Devotional'})
        got = today_page.fetch_epigraph('anglican:advent1')
        assert got is not None
        assert got[0] == 'The Lord is my shepherd.'
        assert got[2] is True
