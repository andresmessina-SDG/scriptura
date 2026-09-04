"""The UI language picker.

The app's language followed the desktop and nothing else, which is wrong for
a reader whose desktop is in a language they do not read the app in. Two
controls now override it: one in the welcome window (first run, applies at
once) and one in the menu (applies next launch).

The checks here are about the parts that can silently do nothing — offering
a language whose catalogue was never compiled, or naming a code with no
name to show — rather than about widget layout.
"""

import os
import subprocess


import i18n
import settings


def test_the_setting_follows_the_desktop_by_default():
    """Most readers never think about this, and should not have to."""
    assert settings._defaults['ui_language'] is None


def test_english_is_always_offered(tmp_path, monkeypatch):
    """It is the source language: the strings are already in it, so it needs
    no catalogue and cannot be missing."""
    monkeypatch.setattr(i18n, 'localedir', lambda: str(tmp_path))
    assert i18n.available_languages() == [('en', 'English')]


def test_a_language_is_offered_only_once_its_catalogue_is_installed(tmp_path,
                                                                    monkeypatch):
    """Read from disk rather than from po/LINGUAS. A catalogue that was
    listed but never compiled — or a partial install — would otherwise be
    offered and then quietly change nothing."""
    monkeypatch.setattr(i18n, 'localedir', lambda: str(tmp_path))
    for code in ('es', 'fr'):
        d = tmp_path / code / 'LC_MESSAGES'
        d.mkdir(parents=True)
    # Only Spanish gets a compiled catalogue.
    (tmp_path / 'es' / 'LC_MESSAGES' / 'scriptura.mo').write_bytes(b'')
    assert i18n.available_languages() == [('en', 'English'), ('es', 'Español')]


def test_a_missing_locale_directory_is_not_an_error(tmp_path, monkeypatch):
    """A source checkout has none — main.py resolves it relative to an
    installed layout — so this path is taken every time the app is run from
    the repository."""
    monkeypatch.setattr(i18n, 'localedir', lambda: str(tmp_path / 'nope'))
    assert i18n.available_languages() == [('en', 'English')]


def test_an_unnamed_code_still_shows_something(tmp_path, monkeypatch):
    """A catalogue can land before its native name does. Showing the bare
    code is poor, but it is a great deal better than dropping the language
    a translator just added."""
    monkeypatch.setattr(i18n, 'localedir', lambda: str(tmp_path))
    d = tmp_path / 'sw' / 'LC_MESSAGES'
    d.mkdir(parents=True)
    (d / 'scriptura.mo').write_bytes(b'')
    assert ('sw', 'sw') in i18n.available_languages()


def test_every_shipped_catalogue_has_a_native_name():
    """The picker lists languages in their own names, for readers who by
    definition may not read the language the app is currently in. A code in
    LINGUAS with no entry in LANGUAGE_NAMES would show as 'es'."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, 'po', 'LINGUAS'), encoding='utf-8') as f:
        codes = [ln.strip() for ln in f
                 if ln.strip() and not ln.startswith('#')]
    missing = [c for c in codes if c not in i18n.LANGUAGE_NAMES]
    assert not missing, f'no native name for {missing}'


def test_install_language_sets_the_gettext_override(monkeypatch):
    """LANGUAGE is what steers the catalogue; LC_ALL stays on the desktop so
    dates and numbers keep following the system."""
    monkeypatch.delenv('LANGUAGE', raising=False)
    i18n.install_language('es')
    assert os.environ.get('LANGUAGE') == 'es'
    i18n.install_language(None)
    assert 'LANGUAGE' not in os.environ


def test_choosing_english_is_not_the_same_as_following_the_desktop():
    """None means 'whatever the desktop says'; 'en' means 'English even
    though the desktop is Spanish'. Collapsing them would take the override
    away from the reader who most needs it."""
    assert settings._defaults['ui_language'] is None
    assert 'en' in dict(i18n.LANGUAGE_NAMES)


def test_the_picker_reports_the_language_actually_in_effect(tmp_path,
                                                            monkeypatch):
    """With no override the desktop decides, so preselecting the *setting*
    showed English to a reader whose Spanish desktop had handed them a
    Spanish app — and then changed nothing when they chose Spanish."""
    monkeypatch.setattr(i18n, 'localedir', lambda: str(tmp_path))
    d = tmp_path / 'es' / 'LC_MESSAGES'
    d.mkdir(parents=True)
    (d / 'scriptura.mo').write_bytes(b'')
    monkeypatch.setenv('LANGUAGE', 'es')
    assert i18n.current_language() == 'es'


def test_a_regional_code_keeps_its_language(tmp_path, monkeypatch):
    """es_MX reads the same es catalogue, and the picker lists 'es'."""
    monkeypatch.setattr(i18n, 'localedir', lambda: str(tmp_path))
    d = tmp_path / 'es_MX' / 'LC_MESSAGES'
    d.mkdir(parents=True)
    (d / 'scriptura.mo').write_bytes(b'')
    monkeypatch.setenv('LANGUAGE', 'es_MX')
    assert i18n.current_language() == 'es'


def test_no_catalogue_means_english(tmp_path, monkeypatch):
    """English is the source language and ships no catalogue, so 'gettext
    found nothing' is the same statement as 'the app is in English'."""
    monkeypatch.setattr(i18n, 'localedir', lambda: str(tmp_path))
    monkeypatch.setenv('LANGUAGE', 'en')
    assert i18n.current_language() == 'en'


# ── The offer to reopen ─────────────────────────────────────────────────────

class _Overlay:
    def __init__(self):
        self.toasts = []

    def add_toast(self, t):
        self.toasts.append(t)


class _Drop:
    def __init__(self, i):
        self.i = i

    def get_selected(self):
        return self.i


def _pick(language_in_effect, chosen, monkeypatch):
    """Run the menu picker's handler with a stub window."""
    import window
    monkeypatch.setattr(i18n, 'current_language', lambda: language_in_effect)
    written = {}
    monkeypatch.setattr(settings, 'put',
                        lambda k, v: written.__setitem__(k, v))
    langs = [('en', 'English'), ('es', 'Español')]
    codes = [c for c, _n in langs]

    win = window.BibleWindow.__new__(window.BibleWindow)
    win._toast_overlay = _Overlay()
    window.BibleWindow._on_language_selected(
        win, codes, langs, _Drop(codes.index(chosen)))
    return written, win._toast_overlay.toasts


def test_choosing_a_new_language_offers_to_reopen(monkeypatch):
    """The window cannot change language where it stands, so the honest
    options are to wait or to start again. The toast says the first and
    offers the second."""
    written, toasts = _pick('en', 'es', monkeypatch)
    assert written == {'ui_language': 'es'}
    assert len(toasts) == 1
    assert 'Español' in toasts[0].get_title()
    assert toasts[0].get_button_label()


def test_choosing_the_language_already_running_offers_nothing(monkeypatch):
    """Reopening would change nothing, and an offer that does nothing is
    worse than no offer."""
    written, toasts = _pick('es', 'es', monkeypatch)
    assert written == {'ui_language': 'es'}
    assert toasts == []


def test_a_relaunch_request_reaches_the_copy_of_main_that_is_running():
    """Run as `python main.py`, this file exists twice — as `__main__` and
    as the `main` window.py imports. A module global set through one copy
    is invisible to the main() running in the other, so the app quit and
    never came back. The flag lives in the environment, which belongs to
    the process rather than to a module object.

    Loading a second, independent copy of the module is the whole test:
    under a global it fails, under the environment it cannot.
    """
    import importlib.util
    import os
    import main

    os.environ.pop(main._RELAUNCH_ENV, None)
    spec = importlib.util.spec_from_file_location('main_other', main.__file__)
    other = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(other)
    assert other is not main

    other.request_relaunch()
    try:
        assert main.relaunch_requested(), (
            'the request did not reach the other copy of main')
    finally:
        os.environ.pop(main._RELAUNCH_ENV, None)
    assert not main.relaunch_requested()


def test_the_catalogue_cache_still_answers_the_environment(tmp_path, monkeypatch):
    """The catalogue is resolved once per language instead of once per
    string — 30µs of stat calls a string became 3. The saving is only safe
    while the cache still notices a language change, which is the whole
    contract `install_language` relies on."""
    import i18n

    monkeypatch.setattr(i18n, 'localedir', lambda: str(tmp_path))
    for code, word in (('es', 'Buscar'), ('ru', 'Искать')):
        d = tmp_path / code / 'LC_MESSAGES'
        d.mkdir(parents=True)
        po = tmp_path / f'{code}.po'
        po.write_text(
            'msgid ""\nmsgstr "Content-Type: text/plain; charset=UTF-8\\n"\n\n'
            f'msgid "Search"\nmsgstr "{word}"\n', encoding='utf-8')
        subprocess.run(['msgfmt', '-o', str(d / 'scriptura.mo'), str(po)],
                       check=True)

    monkeypatch.setenv('LANGUAGE', 'es')
    assert i18n._('Search') == 'Buscar'
    monkeypatch.setenv('LANGUAGE', 'ru')
    assert i18n._('Search') == 'Искать', 'the cache went stale on a switch'
    assert i18n.current_language() == 'ru'


def test_an_unreadable_catalogue_falls_back_to_english(tmp_path, monkeypatch):
    """`fallback=True` covers a catalogue that is absent, not one that is
    present and truncated — that raises out of the parser. English is the
    right answer to a corrupt .mo; taking the app down with it is not."""
    import i18n

    monkeypatch.setattr(i18n, 'localedir', lambda: str(tmp_path))
    d = tmp_path / 'es' / 'LC_MESSAGES'
    d.mkdir(parents=True)
    (d / 'scriptura.mo').write_bytes(b'not a catalogue')
    monkeypatch.setenv('LANGUAGE', 'es')
    assert i18n._('Search') == 'Search'


# ── Where the catalogues are looked for ────────────────────────────────────

def _localedir_from(tmp_path, monkeypatch, layout):
    """Resolve localedir() as if i18n.py lived at `layout`, cache cleared."""
    fake = tmp_path / layout
    fake.parent.mkdir(parents=True, exist_ok=True)
    fake.write_text('')
    monkeypatch.setattr(i18n, '_localedir_cache', None)
    monkeypatch.setattr(i18n, '__file__', str(fake))
    return os.path.normpath(i18n.localedir())


def test_an_install_uses_the_catalogues_beside_it(tmp_path, monkeypatch):
    """{prefix}/share/scriptura/i18n.py → {prefix}/share/locale, which is
    where meson puts them."""
    (tmp_path / 'share' / 'locale').mkdir(parents=True)
    got = _localedir_from(tmp_path, monkeypatch, 'share/scriptura/i18n.py')
    assert got == str(tmp_path / 'share' / 'locale')


def test_a_source_checkout_falls_back_to_its_own_locale_dir(tmp_path,
                                                            monkeypatch):
    """A repo run has no {prefix}/share/locale, and used to answer English
    alone — which hid the picker, since it will not show one language."""
    got = _localedir_from(tmp_path, monkeypatch, 'repo/i18n.py')
    assert got == str(tmp_path / 'repo' / 'locale')


def test_the_fallback_never_shadows_a_real_install(tmp_path, monkeypatch):
    """The whole safety of the fallback is that it is consulted only when
    the installed directory is absent. Build both and the install wins."""
    (tmp_path / 'share' / 'locale').mkdir(parents=True)
    (tmp_path / 'share' / 'scriptura' / 'locale').mkdir(parents=True)
    got = _localedir_from(tmp_path, monkeypatch, 'share/scriptura/i18n.py')
    assert got == str(tmp_path / 'share' / 'locale')
