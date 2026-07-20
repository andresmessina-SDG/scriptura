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
        assert collects.collect_for('roman:advent1') is None
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
            assert re.search(r'\bO (?:God|Lord|Almighty)|\bAlmighty\b', text), sub

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

    def test_source_line(self):
        found = collects.collect_for('roman:easter3')
        assert found is not None
        assert found[1] == ('The Collect · The Roman Missal for the '
                            'Use of the Laity, 1861')

    def test_unfilled_days_stay_silent(self):
        # Partial coverage must degrade to silence, never to a wrong prayer.
        assert collects.collect_for('roman:advent1') is None


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
