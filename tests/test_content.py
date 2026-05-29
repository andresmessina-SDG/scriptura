"""Tests for the content routing facade — that each call lands on the
bridge that owns the module key, and the catena info dict has the right
shape. Bridge calls are monkeypatched so no SWORD/SQLite is touched."""

import content
import catena_bridge
import ebible_bridge
import sword_bridge


def test_language_catena():
    assert content.language(catena_bridge.MODULE_KEY) == 'en'


def test_can_remove_catena_and_ebible():
    assert content.can_remove(catena_bridge.MODULE_KEY) is True
    assert content.can_remove(ebible_bridge.PREFIX + 'eng-web') is True


def test_info_catena_shape(monkeypatch):
    monkeypatch.setattr(catena_bridge, 'pack_info',
                        lambda: {'built': '2026-05-29', 'quote_count': '80931'})
    info = content.info(catena_bridge.MODULE_KEY)
    assert info['type'] == '80931 quotations'
    assert info['version'] == '2026-05-29'
    assert 'HistoricalChristianFaith' in info['about']


def test_remove_routes_to_owning_bridge(monkeypatch):
    calls = []
    monkeypatch.setattr(catena_bridge, 'remove_pack', lambda: calls.append('catena'))
    monkeypatch.setattr(ebible_bridge, 'remove_module', lambda n: calls.append(('ebible', n)))
    monkeypatch.setattr(sword_bridge, 'remove_module', lambda n: calls.append(('sword', n)))

    content.remove(catena_bridge.MODULE_KEY)
    content.remove(ebible_bridge.PREFIX + 'eng-web')
    content.remove('KJV')

    assert calls == ['catena', ('ebible', ebible_bridge.PREFIX + 'eng-web'), ('sword', 'KJV')]
