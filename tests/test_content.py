"""Tests for the content routing facade — that each call lands on the
bridge that owns the module key, and the catena info dict has the right
shape. Bridge calls are monkeypatched so no SWORD/SQLite is touched."""

import content
import catena_bridge
import ebible_bridge
import sword_bridge
import imagery_bridge
import archaeology_bridge
import interlinear_data


def test_language_catena():
    assert content.language(catena_bridge.MODULE_KEY) == 'en'


# ── Registry routing: every source resolves to its own descriptor, and each
# router lands on that descriptor (the guard the ladder-per-function lacked). ──

def _reps():
    """A representative key per registered content type."""
    return {
        'catena': catena_bridge.MODULE_KEY,
        'imagery': imagery_bridge.MODULE_KEY,
        'archaeology': archaeology_bridge.MODULE_KEY,
        'interlinear': interlinear_data.GREEK,
        'ebible': ebible_bridge.PREFIX + 'eng-web',
        'sword': 'KJV',
    }


def test_every_source_resolves_to_its_own_descriptor():
    # The membership predicates are disjoint and the SWORD catch-all is last,
    # so each representative key lands on exactly its own descriptor.
    for expected_key, name in _reps().items():
        assert content._type_for(name).key == expected_key


def test_type_key_matches_the_owning_descriptor():
    # type_key is the single membership source the pane's mode flags resolve
    # against; it must agree with _type_for for every source.
    for expected_key, name in _reps().items():
        assert content.type_key(name) == expected_key


def test_registry_covers_every_type_once():
    keys = [ct.key for ct in content._TYPES]
    assert keys == ['catena', 'imagery', 'archaeology', 'interlinear',
                    'ebible', 'sword']
    assert keys[-1] == 'sword', 'the catch-all must stay last'


def test_kind_per_source():
    reps = _reps()
    assert content.kind(reps['catena']) == 'commentary'
    assert content.kind(reps['imagery']) == 'imagery'
    assert content.kind(reps['archaeology']) == 'books'
    assert content.kind(reps['interlinear']) == 'bible'


def test_every_router_is_total_over_the_registry(monkeypatch):
    # No router may raise on any registered type — the failure mode the
    # copy-pasted ladder had (one function missing a branch). Bridge calls
    # that would touch disk/SQLite are stubbed to harmless values.
    monkeypatch.setattr(ebible_bridge, 'module_info', lambda n: {})
    monkeypatch.setattr(ebible_bridge, 'module_language', lambda n: 'en')
    monkeypatch.setattr(ebible_bridge, 'module_has_footnotes', lambda n: False)
    monkeypatch.setattr(sword_bridge, 'module_info', lambda n: {})
    monkeypatch.setattr(sword_bridge, 'module_language', lambda n: 'en')
    monkeypatch.setattr(sword_bridge, 'module_type', lambda n: 'Biblical Texts')
    monkeypatch.setattr(sword_bridge, 'is_devotional_module', lambda n: False)
    monkeypatch.setattr(sword_bridge, 'module_has_footnotes', lambda n: False)
    monkeypatch.setattr(sword_bridge, 'can_remove_module', lambda n: True)
    monkeypatch.setattr(catena_bridge, 'pack_info', lambda: {})
    monkeypatch.setattr(imagery_bridge, 'pack_info', lambda: {})
    monkeypatch.setattr(archaeology_bridge, 'info', lambda: {})
    for name in _reps().values():
        assert content.kind(name) in ('bible', 'commentary', 'imagery', 'books')
        assert isinstance(content.has_footnotes(name), bool)
        assert isinstance(content.language(name), str)
        assert isinstance(content.info(name), dict)
        assert isinstance(content.can_remove(name), bool)
        fc = content.feature_card(name)
        assert fc is None or isinstance(fc, dict)


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


# ── has_strongs: measured, never declared ────────────────────────────────────
# The conf lies in both directions, so the answer comes from the markup.
# SpaRV1909 and MorphGNT declare no Feature at all and are tagged throughout;
# RusVZh declares Feature=StrongsNumbers and renders nothing the app can read.

def _probe_stub(monkeypatch, markup):
    """Point both loaders at one fixed verse of markup and clear the cache."""
    monkeypatch.setattr(content, '_marks_strongs', {})
    monkeypatch.setattr(sword_bridge, 'load_chapter',
                        lambda n, b, c: [(1, markup)])
    monkeypatch.setattr(ebible_bridge, 'load_chapter',
                        lambda n, b, c: [(1, markup)])


def test_has_strongs_reads_the_markup_not_the_conf(monkeypatch):
    _probe_stub(monkeypatch, '<w lemma="strong:G2316">God</w> loves us')
    assert content.has_strongs('KJV') is True
    _probe_stub(monkeypatch, 'En el principio creó Dios')
    assert content.has_strongs('NBLA') is False


def test_has_strongs_accepts_the_capitalised_prefix(monkeypatch):
    """SpaRV1909 writes savlm="Strong:H7225" on nearly every word. Reading
    only the lowercase form called a fully tagged Bible untagged."""
    _probe_stub(monkeypatch, '<w savlm="Strong:H7225">EN el principio</w>')
    assert content.has_strongs('SpaRV1909') is True


def test_has_strongs_is_false_for_non_bibles(monkeypatch):
    """A commentary or dictionary is never word-study ground, and asking
    must not cost it a chapter load."""
    def explode(n, b, c):
        raise AssertionError('probed a non-Bible')
    monkeypatch.setattr(content, '_marks_strongs', {})
    monkeypatch.setattr(sword_bridge, 'load_chapter', explode)
    monkeypatch.setattr(sword_bridge, 'module_type', lambda n: 'Commentaries')
    assert content.has_strongs('MHCC') is False


def test_has_strongs_caches_per_module(monkeypatch):
    calls = []
    monkeypatch.setattr(content, '_marks_strongs', {})
    monkeypatch.setattr(sword_bridge, 'load_chapter',
                        lambda n, b, c: (calls.append(n),
                                         [(1, '<w lemma="strong:G1">a</w>')])[1])
    content.has_strongs('KJV')
    content.has_strongs('KJV')
    assert calls == ['KJV']
