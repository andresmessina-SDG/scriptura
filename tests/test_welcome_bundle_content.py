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


def _bundle(bundle_id):
    return next(b for b in welcome._BUNDLES if b['id'] == bundle_id)


def _idents(bundle, kind):
    return [i for k, i, _label in bundle['items'] if k == kind]


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


def test_study_and_full_install_a_dictionary():
    for bundle_id in ('study', 'full'):
        sword = _idents(_bundle(bundle_id), 'sword')
        assert any(m.lower() not in sword_bridge._DICT_SKIP
                   and m.lower() in _KNOWN_DICTIONARIES
                   for m in sword), bundle_id


def test_the_strongs_lexicons_do_not_count_as_a_dictionary():
    """The reason the gap was invisible: every bundle already carried two
    lexicons, so 'it has a dictionary' looked true from the item list."""
    for name in ('StrongsHebrew', 'StrongsGreek'):
        assert name.lower() in sword_bridge._DICT_SKIP


# Dictionary/encyclopedia modules the peek accepts, by CrossWire module name.
# Named here rather than probed, so the test needs no installed library.
_KNOWN_DICTIONARIES = frozenset(['easton', 'smith', 'isbe'])


def test_bsb_leads_every_english_bundle_and_its_opening_pair():
    """His call: the BSB reads more naturally to a newcomer than the KJV,
    and it is the translation with CC0 chapter audio, so the listening pill
    works from day one. The Spanish bundle answers the same question with
    its own texts, so it is excluded rather than exempted quietly."""
    for bundle in welcome._BUNDLES:
        if bundle['id'] == 'espanol':
            continue
        assert _idents(bundle, 'sword')[0] == 'BSB', bundle['id']
        assert bundle['opens'][0] == 'BSB', bundle['id']


def test_the_spanish_bundle_opens_on_spanish_and_can_speak():
    """The two properties that make it the Spanish equivalent of the English
    default rather than a list of Spanish files: it opens on a modern Spanish
    text, and it carries the one module the spoken reading is bound to."""
    import bible_audio

    es = _bundle('espanol')
    assert es['opens'] == ('NBLA', 'eBible: spaRV1909')
    assert _idents(es, 'sword')[0] == 'NBLA'

    spoken = [i for k, i, _l in es['items'] if k == 'ebible']
    assert 'spabes' in spoken
    # Asked of the audio table rather than restated: the reading names the
    # module key it plays against, and a bundle promising audio has to carry
    # exactly that one.
    bound = {m for r in bible_audio.READINGS for m in r.modules}
    assert any(f'ebible{tid}' in bound for tid in spoken)


def test_every_step_names_a_kind_the_installer_dispatches():
    """A bundle step whose kind has no branch installs nothing and reports
    no failure — it is simply skipped, silently."""
    dispatched = {'sword', 'opendata', 'catena', 'ebible'}
    for bundle in welcome._BUNDLES:
        for kind, _ident, label in bundle['items']:
            assert kind in dispatched, f'{bundle["id"]}: {label}'


def test_summaries_count_the_bibles_they_promise():
    """The card's summary is the only place a reader learns what they are
    about to download, and it was hand-maintained against the item list."""
    for bundle in welcome._BUNDLES:
        bibles = (len(_idents(bundle, 'ebible'))
                  + sum(1 for m in _idents(bundle, 'sword')
                        if m.lower() not in _NOT_A_BIBLE))
        promised = int(bundle['summary'].split()[0]) if \
            bundle['summary'][0].isdigit() else 1
        assert bibles == promised, f'{bundle["id"]}: {bundle["summary"]}'


# Bundle members that are not Bible texts, so the summary must not count them.
_NOT_A_BIBLE = frozenset([
    'strongshebrew', 'strongsgreek', 'tsk', 'mhcc', 'jfb', 'easton',
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
    win._install_worker(_bundle('espanol'))

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
