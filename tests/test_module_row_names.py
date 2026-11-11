"""What a CrossWire row calls a module (_friendly_name).

The Module Manager used to title every row from the module's own SWORD
`Description`, which bypassed the curated name tables entirely. A Russian
tester read the result: RusSynodal describes itself as «Синодального
Перевода Библии», a genitive fragment that is correct only as the tail of
a sentence and reads as broken standing alone as a title.
"""
import i18n
import module_manager


def test_a_curated_name_beats_the_packagers_description():
    assert module_manager._friendly_name(
        {'name': 'RusSynodal',
         'description': 'Синодального Перевода Библии'}) \
        == 'Russian Synodal Bible'


def test_the_native_name_wins_for_a_reader_of_that_language(monkeypatch):
    monkeypatch.setattr(i18n, 'current_language', lambda: 'ru')
    assert module_manager._friendly_name(
        {'name': 'RusSynodal',
         'description': 'Синодального Перевода Библии'}) \
        == 'Синодальный перевод'


def test_an_uncurated_module_keeps_its_description():
    """Most of the 400-module catalogue is uncurated, and there the
    Description is the only readable thing the row has — display_name
    would hand back the bare key."""
    assert module_manager._friendly_name(
        {'name': 'NoSuchModule', 'description': 'A packager blurb'}) \
        == 'A packager blurb'


def test_a_module_with_neither_falls_back_to_its_key():
    assert module_manager._friendly_name({'name': 'NoSuchModule'}) \
        == 'NoSuchModule'


def test_an_installed_classic_keeps_its_collection_and_credit_offline(monkeypatch):
    import types
    import sword_bridge
    import pytest
    from gi.repository import Gtk, Gdk
    if Gdk.Display.get_default() is None:
        pytest.skip('builds a module row; no display here')
    mod = types.SimpleNamespace(
        getType=lambda: 'Generic Books',
        getConfigMap=lambda: types.SimpleNamespace(items=lambda: [
            ('Description', 'The Mortification of Sin (John Owen)'),
            ('Collection', 'Classics'), ('DistributionLicense', 'Public Domain'),
            ('Lang', 'en'), ('Version', '2')]))
    monkeypatch.setattr(sword_bridge, 'mgr',
                        lambda: types.SimpleNamespace(getModule=lambda n: mod))
    info = sword_bridge.installed_module_metadata('CWPMortification')
    assert info['installed'] and info['collection'] == 'Classics'
    fake = types.SimpleNamespace(_add_actions=lambda *args: None,
                                 _on_install=lambda *args: None)
    row = module_manager.ModuleManagerWindow._make_sword_row(fake, info, False)
    assert 'Common Weal Press' in row.get_subtitle()
    assert 'CrossWire' not in row.get_subtitle()
    assert 'John Owen' in row.get_title()
    assert isinstance(row, Gtk.Widget)
