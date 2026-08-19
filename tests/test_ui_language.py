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

import pytest

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
