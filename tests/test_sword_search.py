"""Tests for the SWORD FTS5 search path (sword_bridge.search_module /
_build_module_index).

SWORD modules aren't available in the test env, so we inject synthetic
verses by patching load_chapter / chapter_count / _ALL_BOOKS. That still
exercises the real FTS5 index build, the shared query grammar, ORDER BY
canonical, the int CAST, case-sensitive post-filtering, and the on-disk
index file — everything the new code path owns."""

from concurrent.futures import ThreadPoolExecutor
import threading

import pytest

import sword_bridge as sb


_VERSES = {
    ('Genesis', 1): [
        (1, 'In the beginning God created the heavens and the earth'),
        (2, 'And the earth was without form and void'),
    ],
    ('John', 3): [
        (16, 'For God so loved the world'),
        (17, 'For God did not send his Son to condemn the world'),
    ],
}


@pytest.fixture
def fts_module(tmp_path, monkeypatch):
    """Point the index dir at a tmp path and feed synthetic verses."""
    monkeypatch.setattr(sb, 'FTS_INDEX_DIR', str(tmp_path / 'idx'))
    monkeypatch.setattr(sb, '_ALL_BOOKS', ['Genesis', 'John'])
    monkeypatch.setattr(sb, 'chapter_count',
                        lambda book, module=None: {'Genesis': 1, 'John': 3}[book])
    monkeypatch.setattr(sb, 'load_chapter',
                        lambda module, book, ch: _VERSES.get((book, ch), []))
    # Clear any in-flight indexing thread bookkeeping between tests.
    with sb._indexing_lock:
        sb._indexing_threads.clear()
    return 'TestMod'


def _books(results):
    return [(b, c, v) for (b, c, v, _t) in results]


def test_builds_and_searches(fts_module):
    res = sb.search_module(fts_module, 'God')
    # All three verses contain "God"; Genesis 1:2 does not.
    assert _books(res) == [('Genesis', 1, 1), ('John', 3, 16), ('John', 3, 17)]


def test_results_are_canonical_order(fts_module):
    res = sb.search_module(fts_module, 'the')
    # Genesis before John — rowid (insertion) order, not relevance.
    assert _books(res)[0][0] == 'Genesis'
    assert [b for b, _c, _v in _books(res)] == sorted(
        [b for b, _c, _v in _books(res)], key=['Genesis', 'John'].index)


def test_chapter_verse_are_ints(fts_module):
    res = sb.search_module(fts_module, 'God')
    _b, c, v, _t = res[0]
    assert isinstance(c, int) and isinstance(v, int)


def test_word_boundary_not_substring(fts_module):
    # "art" must NOT match inside "earth" (the old Whoosh/substring gap).
    assert sb.search_module(fts_module, 'art') == []


def test_phrase(fts_module):
    res = sb.search_module(fts_module, '"loved the world"')
    assert _books(res) == [('John', 3, 16)]


def test_exclude(fts_module):
    res = _books(sb.search_module(fts_module, 'God -world'))
    assert ('John', 3, 16) not in res     # has "world"
    assert ('Genesis', 1, 1) in res


def test_prefix(fts_module):
    res = _books(sb.search_module(fts_module, 'creat*'))
    assert res == [('Genesis', 1, 1)]


def test_case_sensitive(fts_module):
    # Content has capital "God"; a lowercase case-sensitive query matches none.
    assert sb.search_module(fts_module, 'god', case_sensitive=True) == []
    assert _books(sb.search_module(fts_module, 'God', case_sensitive=True))


def test_case_sensitive_does_not_accept_a_substring(fts_module, monkeypatch):
    monkeypatch.setitem(_VERSES, ('Genesis', 1), [
        (1, 'He saw the people'), (2, 'And he saw the people')])
    assert _books(sb.search_module(fts_module, 'he', case_sensitive=True)) == [
        ('Genesis', 1, 2)]


def test_empty_query(fts_module):
    assert sb.search_module(fts_module, '') == []
    assert sb.search_module(fts_module, '   ') == []


def test_index_reused_not_rebuilt(fts_module):
    sb.search_module(fts_module, 'God')
    assert sb._index_is_valid(sb._get_index_path(fts_module), fts_module)
    # A second search hits the existing index (build callback must not fire).
    started = []
    sb.search_module(fts_module, 'world',
                     on_indexing_start=lambda: started.append(1))
    assert started == []


def test_indexing_callbacks_fire_on_build(fts_module):
    events = []
    sb.search_module(
        fts_module, 'God',
        on_indexing_start=lambda: events.append('start'),
        on_indexing_progress=lambda i, n, b: events.append(('progress', b)),
        on_indexing_done=lambda: events.append('done'))
    assert events[0] == 'start'
    assert events[-1] == 'done'
    assert ('progress', 'Genesis') in events


@pytest.mark.parametrize('reset_caches', [False, True])
def test_concurrent_searches_share_one_builder(
        fts_module, monkeypatch, reset_caches):
    announced = threading.Event()
    release = threading.Event()
    second_joining = threading.Event()
    second_ident = []
    builds = []
    original_build = sb._build_module_index
    original_join = threading.Thread.join

    def build(*args, **kwargs):
        builds.append(args[0])
        original_build(*args, **kwargs)

    def on_start():
        announced.set()
        assert release.wait(5)

    def join(thread, *args, **kwargs):
        if second_ident == [threading.get_ident()]:
            second_joining.set()
        return original_join(thread, *args, **kwargs)

    def second_search():
        second_ident.append(threading.get_ident())
        return sb.search_module(fts_module, 'God')

    monkeypatch.setattr(sb, '_build_module_index', build)
    monkeypatch.setattr(threading.Thread, 'join', join)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(sb.search_module, fts_module, 'God', on_start)
        try:
            assert announced.wait(5)
            if reset_caches:
                sb._reset()
            second = pool.submit(second_search)
            assert second_joining.wait(5)
        finally:
            release.set()
        assert _books(first.result(timeout=5)) == [
            ('Genesis', 1, 1), ('John', 3, 16), ('John', 3, 17)]
        assert second.result(timeout=5) == first.result()
    assert builds == [fts_module]
    assert sb._index_is_valid(sb._get_index_path(fts_module), fts_module)


def test_search_rechecks_index_after_waiting_for_lock(fts_module, monkeypatch):
    expected = sb.search_module(fts_module, 'God')
    original_valid = sb._index_is_valid
    checks = []
    builds = []

    def valid(*args):
        checks.append(1)
        return False if len(checks) == 1 else original_valid(*args)

    def unexpected_build(*args, **kwargs):
        builds.append(1)

    monkeypatch.setattr(sb, '_index_is_valid', valid)
    monkeypatch.setattr(sb, '_build_module_index', unexpected_build)
    assert sb.search_module(fts_module, 'God') == expected
    assert builds == []


# ── The deuterocanon a module carries ────────────────────────────────────────
# Tobit was readable and never found: the index walked the 66 books only.

def test_the_appendix_a_module_carries_is_indexed(fts_module, monkeypatch):
    monkeypatch.setattr(sb, 'module_books', lambda module: ('Tobit',))
    monkeypatch.setattr(sb, 'chapter_count_in', lambda module, book: 1)
    monkeypatch.setitem(_VERSES, ('Tobit', 1),
                        [(9, 'and of her I begat Tobias, and God was with him')])
    assert _books(sb.search_module(fts_module, 'Tobias')) == [('Tobit', 1, 9)]
    # Appended after Revelation, so the canonical rowid order holds.
    assert _books(sb.search_module(fts_module, 'God'))[-1] == ('Tobit', 1, 9)


def test_an_older_index_rebuilds_only_where_the_appendix_is(
        fts_module, monkeypatch):
    import sqlite3
    sb.search_module(fts_module, 'God')
    path = sb._get_index_path(fts_module)
    conn = sqlite3.connect(path)
    conn.execute('PRAGMA user_version = 4')
    conn.commit()
    conn.close()
    monkeypatch.setattr(sb, 'module_books', lambda module: ())
    assert sb._index_is_valid(path, fts_module)
    monkeypatch.setattr(sb, 'module_books', lambda module: ('Tobit',))
    assert not sb._index_is_valid(path, fts_module)
