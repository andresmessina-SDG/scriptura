"""Guards for the bundled collects pack: full-year coverage (every key the
engine can emit resolves to a text), no orphaned pack keys, and the
epigraph fallback order (devotional wins, collect fills the gap)."""
import datetime

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
    emitted Sunday keys resolve to 8 texts. Feast Tropária are not yet
    extracted, so this asserts the Sunday cycle only — deliberately not
    full-year coverage, which would be a false claim."""

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

    def test_eight_distinct_texts(self):
        texts = collects._pack()['orthodox']['texts']
        assert len(texts) == 8
        assert len(set(texts.values())) == 8

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
