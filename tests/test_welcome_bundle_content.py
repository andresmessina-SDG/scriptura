"""Ties the welcome bundles to the gestures onboarding teaches.

Tips & Gestures promises a newcomer that double-clicking a word looks it up
in a dictionary, and the verse cursor offers the same thing on Enter. Both
are reachable only if a bundle actually installed a dictionary — and the
Strong's lexicons do not count, because `_DICT_SKIP` rejects them by name.
So the bundles shipped a taught gesture that did nothing on every profile
they created, which is the failure the onboarding audit opened on: a hint
spent on a surface the reader cannot reach.

These tests read both sides rather than restating either, so a bundle edit
or a Tips edit has to keep them agreed.
"""

import onboarding
import sword_bridge
import welcome


def _bundle(bundle_id, language='en'):
    return next(b for b in welcome.bundles_for(language)
                if b['id'] == bundle_id)


def _every_bundle():
    for language in welcome._CATALOGUE:
        yield from welcome.bundles_for(language)


def _idents(bundle, kind):
    return [i for k, i, _l, _f in bundle['items'] if k == kind]


def _teaches_the_dictionary():
    """True when some Tips row promises a dictionary lookup."""
    for _section, rows in onboarding.GESTURES:
        for gesture, result in rows:
            if 'dictionary' in result.lower():
                return True
    return False


def test_tips_still_teaches_the_dictionary():
    """Guards the premise. If this row goes, the tie below is vacuous and
    should be deleted rather than left passing for the wrong reason."""
    assert _teaches_the_dictionary()


def test_every_language_puts_a_dictionary_in_its_study_tiers():
    """Not just English. A Spanish reader met the same two taught gestures
    and had no dictionary to reach, because none existed until Scriptura
    built one — so this is per language, and a new language's table fails
    here until it names one too."""
    for language in welcome._CATALOGUE:
        offered = {b['id'] for b in welcome.bundles_for(language)}
        for bundle_id in ('study', 'full'):
            # A tier a language does not offer is not a broken promise — the
            # rule is that a study/full card must reach a dictionary, not that
            # every language must have those cards. Russian offers no full
            # tier because its catalogue holds no commentary to fill one.
            if bundle_id not in offered:
                continue
            sword = _idents(_bundle(bundle_id, language), 'sword')
            assert any(m.lower() not in sword_bridge._DICT_SKIP
                       and m.lower() in _KNOWN_DICTIONARIES
                       for m in sword), f'{language}/{bundle_id}'


def test_the_strongs_lexicons_do_not_count_as_a_dictionary():
    """The reason the gap was invisible: every bundle already carried two
    lexicons, so 'it has a dictionary' looked true from the item list."""
    for name in ('StrongsHebrew', 'StrongsGreek'):
        assert name.lower() in sword_bridge._DICT_SKIP


# Dictionary/encyclopedia modules the peek accepts, by CrossWire module name.
# Named here rather than probed, so the test needs no installed library.
_KNOWN_DICTIONARIES = frozenset(['easton', 'smith', 'isbe',
                                 'wikcionario', 'russianbiblewords'])


def test_bsb_leads_every_english_bundle_and_its_opening_pair():
    """His call: the BSB reads more naturally to a newcomer than the KJV,
    and it is the translation with CC0 chapter audio, so the listening pill
    works from day one. The Spanish bundle answers the same question with
    its own texts, so it is excluded rather than exempted quietly."""
    for bundle in welcome.bundles_for('en'):
        assert _idents(bundle, 'sword')[0] == 'BSB', bundle['id']
        assert bundle['opens'][0] == 'BSB', bundle['id']


def test_the_spanish_bundles_open_on_spanish():
    """Every Spanish tier opens on a modern Spanish text, and where there is
    a second pane it is the one Spanish text carrying Strong's numbers, so
    word study has somewhere to happen."""
    for bundle in welcome.bundles_for('es'):
        assert _idents(bundle, 'sword')[0] == 'NBLA', bundle['id']
        assert bundle['opens'][0] == 'NBLA', bundle['id']
        if bundle['opens'][1] is not None:
            assert bundle['opens'][1] == 'eBible: spaRV1909', bundle['id']


def test_the_russian_bundles_open_on_the_modern_text():
    """The modern text leads, not the Synodal beside it. Every Russian Bible
    that exists is the 1876 Synodal or a revision of it, so RusOpenBible is
    the one text a reader meets in today's language — and pane 2's Synodal
    is the Licht im Osten edition, which carries the Strong's numbers the
    lexicons key on in all 66 books."""
    for bundle in welcome.bundles_for('ru'):
        assert _idents(bundle, 'sword')[0] == 'RusOpenBible', bundle['id']
        assert bundle['opens'][0] == 'RusOpenBible', bundle['id']


def test_no_russian_tier_offers_the_central_asian_translations():
    """RusCARS and its two siblings are Russian by language tag and Muslim in
    idiom — Иса for Jesus, Юнус for Jonah — so a reader who asked for Russian
    would meet names they did not expect on a card that never said so. They
    stay in the Module Manager, where the description explains them."""
    for bundle in welcome.bundles_for('ru'):
        for ident in _idents(bundle, 'sword'):
            assert not ident.lower().startswith('ruscars'), bundle['id']


def test_a_summary_promises_audio_only_if_a_pane_it_opens_on_has_it():
    """The listening pill is per-pane and keyed to the module in it, so a
    bundle can install a spoken reading and still never show the reader a
    player. The Spanish bundle did exactly that: it downloaded the Español
    Sencillo reading, opened on NBLA and the Reina Valera, and promised
    "audio" on a card whose panes could not produce any.
    """
    import bible_audio

    for bundle in _every_bundle():
        if 'audio' not in bundle['summary'].lower():
            continue
        panes = [p for p in bundle['opens'] if p]
        assert any(bible_audio.reading_for_module(p) for p in panes), (
            f'{bundle["id"]}: summary promises audio, but neither of '
            f'{panes} is bound to a reading')


def test_every_step_names_a_kind_the_installer_dispatches():
    """A bundle step whose kind has no branch installs nothing and reports
    no failure — it is simply skipped, silently."""
    dispatched = {'sword', 'opendata', 'catena', 'ebible'}
    for bundle in _every_bundle():
        for kind, _ident, label, _facet in bundle['items']:
            assert kind in dispatched, f'{bundle["id"]}: {label}'


def test_summaries_count_the_bibles_they_promise():
    """The card's summary is the only place a reader learns what they are
    about to download. It used to be hand-maintained against the item list
    and drifted; it is now counted from the items, and this holds the count
    to the facets the table actually declares."""
    for bundle in _every_bundle():
        bibles = sum(1 for _k, _i, _l, f in bundle['items']
                     if f == welcome._BIBLE)
        promised = int(bundle['summary'].split()[0])
        assert bibles == promised, f'{bundle["id"]}: {bundle["summary"]}'


def test_a_facet_the_table_does_not_declare_is_not_promised():
    """The Spanish catalogue has no commentary in it — none exists that is
    both Spanish and free — so no Spanish card may offer one."""
    for bundle in welcome.bundles_for('es'):
        assert 'commentar' not in bundle['summary'].lower(), bundle['id']


def test_the_spoken_reading_installs_without_being_promised():
    """Audio is a facet the summary deliberately never prints: the listening
    pill is per-pane, so a card promising it while opening on two silent
    texts promises what the first screen cannot deliver."""
    full = _bundle('full', 'es')
    assert any(f == welcome._AUDIO for _k, _i, _l, f in full['items'])
    assert 'audio' not in full['summary'].lower()


def test_a_language_card_counts_the_largest_tier():
    """The language page's line is the ceiling of what choosing that language
    leads to, not what any one card installs — so it counts the last tier the
    language has, and it is counted, never written."""
    for code in welcome._CATALOGUE:
        largest = next(b for b in reversed(welcome.bundles_for(code)))
        assert welcome.language_summary(code) == largest['summary']


def test_a_language_card_speaks_its_own_language(monkeypatch):
    """Both cards are on screen at once, so each has to answer in its own
    language rather than in the one the app is running in. `_()` cannot do
    that, and a later simplification back to it would leave a Spanish card
    reading "3 Bibles · notes" under an English interface — wrong for exactly
    the reader who needs the page and cannot read the rest of it."""
    asked = []

    def fake_translator_for(code):
        asked.append(code)
        return (lambda m: f'<{code}:{m}>',
                lambda s, p, n: f'<{code}:{p if n != 1 else s}>')

    monkeypatch.setattr(welcome.i18n, 'translator_for', fake_translator_for)
    line = welcome.language_summary('es')
    assert asked == ['es']
    assert line.startswith('<es:')
    assert '<es:dictionary>' in line


# Bundle members that are not Bible texts, so the summary must not count them.
_NOT_A_BIBLE = frozenset([
    'strongshebrew', 'strongsgreek', 'tsk', 'mhcc', 'jfb', 'easton',
    'wikcionario',
])


# ── the catalogue a first run does not have ──────────────────────────────────

def test_a_bundle_with_sword_modules_fetches_the_catalogue_first(monkeypatch):
    """Which repository a module lives in is recorded in the catalogue, and a
    fresh profile has none — so install_module falls back to the released
    repository's zip. That is the wrong place for anything the Lockman repo
    owns, and it publishes no zips at all, so NBLA and LBLA failed outright
    and the Spanish bundle opened on the distro KJV instead. Only a real
    install caught it; this is the cheap guard.
    """
    calls = []
    monkeypatch.setattr(welcome.sword_bridge, 'catalog_timestamp',
                        lambda: None)
    monkeypatch.setattr(welcome.sword_bridge, 'refresh_source',
                        lambda: calls.append('refresh'))
    monkeypatch.setattr(welcome.sword_bridge, 'install_module',
                        lambda ident: calls.append(ident))
    monkeypatch.setattr(welcome.ebible_bridge, 'catalog_entries', lambda: [])
    monkeypatch.setattr(welcome.open_data, 'download_source',
                        lambda *a, **k: None)
    monkeypatch.setattr(welcome.catena_bridge, 'download_and_install',
                        lambda *a, **k: None)

    win = welcome.WelcomeWindow.__new__(welcome.WelcomeWindow)
    monkeypatch.setattr(win, '_set_status', lambda *_a: None, raising=False)
    monkeypatch.setattr(win, '_mk_progress', lambda base: None, raising=False)
    monkeypatch.setattr(win, '_finish_install', lambda *_a: None,
                        raising=False)
    win._install_worker(_bundle('study', 'es'))

    assert calls and calls[0] == 'refresh', (
        f'the catalogue must be read before any module install, got {calls[:3]}')
    assert 'NBLA' in calls


def test_the_catalogue_is_not_refetched_when_one_is_cached(monkeypatch):
    """It is a download; a profile that already has a catalogue should not
    pay for it on every bundle install."""
    from datetime import datetime

    calls = []
    monkeypatch.setattr(welcome.sword_bridge, 'catalog_timestamp',
                        lambda: datetime(2026, 8, 16))
    monkeypatch.setattr(welcome.sword_bridge, 'catalogue_has',
                        lambda _name: True)
    monkeypatch.setattr(welcome.sword_bridge, 'refresh_source',
                        lambda: calls.append('refresh'))
    monkeypatch.setattr(welcome.sword_bridge, 'install_module',
                        lambda ident: calls.append(ident))
    monkeypatch.setattr(welcome.ebible_bridge, 'catalog_entries', lambda: [])
    monkeypatch.setattr(welcome.open_data, 'download_source',
                        lambda *a, **k: None)
    monkeypatch.setattr(welcome.catena_bridge, 'download_and_install',
                        lambda *a, **k: None)

    win = welcome.WelcomeWindow.__new__(welcome.WelcomeWindow)
    monkeypatch.setattr(win, '_set_status', lambda *_a: None, raising=False)
    monkeypatch.setattr(win, '_mk_progress', lambda base: None, raising=False)
    monkeypatch.setattr(win, '_finish_install', lambda *_a: None,
                        raising=False)
    win._install_worker(_bundle('reading'))

    assert 'refresh' not in calls


def test_a_catalogue_older_than_the_module_is_refetched(monkeypatch):
    """The cached list is a snapshot. A profile that read it before a module
    was published has no row for it, `install_module` falls back to the
    released repository where a module Scriptura publishes itself has never
    been, and the download 404s for something that exists. Every profile that
    had ever opened the Module Manager was in that state when the Spanish
    dictionary shipped, and nothing ages the catalogue out on its own.
    """
    from datetime import datetime

    calls = []
    monkeypatch.setattr(welcome.sword_bridge, 'catalog_timestamp',
                        lambda: datetime(2026, 8, 17))
    monkeypatch.setattr(welcome.sword_bridge, 'catalogue_has',
                        lambda name: name != 'Wikcionario')
    monkeypatch.setattr(welcome.sword_bridge, 'refresh_source',
                        lambda: calls.append('refresh'))
    monkeypatch.setattr(welcome.sword_bridge, 'install_module',
                        lambda ident: calls.append(ident))
    monkeypatch.setattr(welcome.ebible_bridge, 'catalog_entries', lambda: [])
    monkeypatch.setattr(welcome.open_data, 'download_source',
                        lambda *a, **k: None)

    win = welcome.WelcomeWindow.__new__(welcome.WelcomeWindow)
    monkeypatch.setattr(win, '_set_status', lambda *_a: None, raising=False)
    monkeypatch.setattr(win, '_mk_progress', lambda base: None, raising=False)
    monkeypatch.setattr(win, '_finish_install', lambda *_a: None,
                        raising=False)
    win._install_worker(_bundle('study', 'es'))

    assert calls and calls[0] == 'refresh', (
        f'a catalogue with no row for Wikcionario was used as-is: {calls[:3]}')
    assert 'Wikcionario' in calls
