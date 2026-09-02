"""Tests for the pair of modules the welcome window hands to the reader.

The welcome window is the only place that knows WHY a module was installed,
so it records what the reading window should open on instead of leaving the
main window to infer a default. Settings are isolated by monkeypatching the
module globals, never env vars (paths bind at import).
"""

import pytest

import ebible_bridge
import settings
import welcome


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    if settings._save_timer is not None:
        settings._save_timer.cancel()
    monkeypatch.setattr(settings, '_FILE', str(tmp_path / 'settings.json'))
    monkeypatch.setattr(settings, '_cache', None)
    monkeypatch.setattr(settings, '_load_failed', False)
    monkeypatch.setattr(settings, '_save_timer', None)
    yield tmp_path
    if settings._save_timer is not None:
        settings._save_timer.cancel()


def _record(monkeypatch, bundle, sword=(), catena=()):
    """Drive the recorder against a stated library. Unbound: it touches no
    widget state, so no window has to be constructed for a display-free run."""
    monkeypatch.setattr(welcome.sword_bridge, 'module_names',
                        lambda: list(sword))
    monkeypatch.setattr(welcome.catena_bridge, 'module_names',
                        lambda: list(catena))
    welcome.WelcomeWindow._record_opening_pair(None, bundle)


def test_it_records_both_panes_when_both_arrived(isolated, monkeypatch):
    _record(monkeypatch, {'opens': ('BSB', 'Historical Commentaries')},
            sword=['BSB', 'KJVA'], catena=['Historical Commentaries'])
    assert settings.get('pane1_module') == 'BSB'
    assert settings.get('pane2_module') == 'Historical Commentaries'
    assert settings.get('split_pane_mode') is True


def test_a_reading_only_bundle_opens_single_pane(isolated, monkeypatch):
    """One text is not a split. Filling pane 2 with a copy of pane 1 is the
    bug this whole pair exists to stop."""
    _record(monkeypatch, {'opens': ('BSB', None)}, sword=['BSB'])
    assert settings.get('pane1_module') == 'BSB'
    assert settings.get('pane2_module') is None
    assert settings.get('split_pane_mode') is False


def test_a_commentary_that_failed_to_install_collapses_the_split(
        isolated, monkeypatch):
    _record(monkeypatch, {'opens': ('BSB', 'Historical Commentaries')},
            sword=['BSB'], catena=[])
    assert settings.get('pane1_module') == 'BSB'
    assert settings.get('pane2_module') is None
    assert settings.get('split_pane_mode') is False


def test_a_bible_that_failed_to_install_is_not_recorded(isolated, monkeypatch):
    """Leaving it unset sends the main window to its own fallback, which picks
    from what is actually there. Writing a name for an absent module would
    make every later launch resolve nothing."""
    _record(monkeypatch, {'opens': ('BSB', 'Historical Commentaries')},
            sword=['KJVA'], catena=['Historical Commentaries'])
    assert settings.get('pane1_module') is None
    assert settings.get('pane2_module') == 'Historical Commentaries'


_ALL_BUNDLES = [b for lang in welcome._CATALOGUE
                for b in welcome.bundles_for(lang)]


@pytest.mark.parametrize('bundle', _ALL_BUNDLES,
                         ids=[f'{b["language"]}-{b["id"]}'
                              for b in _ALL_BUNDLES])
def test_every_bundle_opens_on_something_it_installs(bundle):
    """A bundle that opens on a module it never downloads sends the reader to
    the fallback it was written to avoid."""
    # An eBible step names the bare translation id, but a pane names the
    # module key — the id behind ebible_bridge.PREFIX. Both forms count as
    # installed, or a bundle opening on an eBible text reads as a typo.
    installed = set()
    for kind, ident, label, _facet in bundle['items']:
        installed.add(ident or label)
        if kind == 'ebible':
            installed.add(f'{ebible_bridge.PREFIX}{ident}')
    pane1, pane2 = bundle['opens']
    assert pane1 in installed, f'{bundle["id"]} opens pane 1 on {pane1}'
    if pane2 is not None:
        assert pane2 in installed, f'{bundle["id"]} opens pane 2 on {pane2}'
