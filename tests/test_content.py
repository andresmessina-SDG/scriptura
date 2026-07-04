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


# ── Cross-source edition works ───────────────────────────────────────────────

def test_edition_work_pairs_known_editions():
    assert content.edition_work('sword', 'ASV') == 'asv'
    assert content.edition_work('ebible', 'eng-asv') == 'asv'
    assert content.edition_work('sword', 'KJVA') == 'kjv'
    assert content.edition_work('ebible', 'eng-kjv2006') == 'kjv'


def test_edition_work_unknown_is_none():
    assert content.edition_work('sword', 'MHCC') is None
    assert content.edition_work('ebible', 'spaRV1909') is None
    assert content.edition_work('nonsense', 'ASV') is None


def test_edition_work_title():
    assert content.edition_work_title('asv') == 'American Standard Version (1901)'


def test_edition_table_is_consistent():
    """Every work id is unique and no per-source key is claimed twice —
    a duplicate claim would silently merge two different translations."""
    ids = [w['id'] for w in content.EDITION_WORKS]
    assert len(ids) == len(set(ids))
    for source in ('sword', 'ebible'):
        keys = [k for w in content.EDITION_WORKS for k in w[source]]
        assert len(keys) == len(set(keys))
