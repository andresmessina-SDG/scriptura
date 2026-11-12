"""A Generic Book that raises while it is read says so.

The fetch ran on a bare thread: when sword_bridge raised, nothing came back
to the main loop and the pane kept the last book's page. It now runs on
tasks.py, whose on_error names the module and the error.
"""
import genbook_reader
import sword_bridge
import tasks
from types import SimpleNamespace


class _Pane:
    module = 'Broken'
    _peek = SimpleNamespace(dismiss=lambda: None)


def test_a_raising_book_says_it_failed(monkeypatch):
    calls = {}
    monkeypatch.setattr(tasks, 'submit', lambda **kw: calls.update(kw))

    def boom(_module):
        raise RuntimeError('damaged module')
    monkeypatch.setattr(sword_bridge, 'list_genbook_entries', boom)

    reader = genbook_reader.GenbookReader(_Pane(), lambda *a: '')
    shown = []
    monkeypatch.setattr(reader, '_show_failure', lambda *a: shown.append(a))
    reader.fetch_and_render()

    try:
        calls['work'](None)
    except RuntimeError as exc:
        calls['on_error'](exc)
    assert [(m, str(e)) for m, e in shown] == [('Broken', 'damaged module')]


def test_a_stale_saved_path_is_not_silently_resolved_to_another_chapter(monkeypatch):
    calls, loaded = {}, []
    monkeypatch.setattr(tasks, 'submit', lambda **kw: calls.update(kw))
    monkeypatch.setattr(sword_bridge, 'list_genbook_entries',
                        lambda m: [('/Preface', 'Preface', 0)])
    monkeypatch.setattr(sword_bridge, 'load_genbook_entry',
                        lambda m, p: loaded.append(p) or '<p>The preface.</p>')
    reader = genbook_reader.GenbookReader(_Pane(), lambda *a: '')
    reader._entry_path = '/Removed chapter'
    reader.fetch_and_render()
    entries, path, body = calls['work'](None)
    assert path == '/Preface'
    assert loaded == ['/Preface']


def test_a_worker_uses_the_entry_requested_with_its_module(monkeypatch):
    calls = {}
    monkeypatch.setattr(tasks, 'submit', lambda **kw: calls.update(kw))
    monkeypatch.setattr(sword_bridge, 'list_genbook_entries',
                        lambda m: [('/Chapter I', 'Chapter I', 0),
                                   ('/Chapter II', 'Chapter II', 0)])
    monkeypatch.setattr(sword_bridge, 'load_genbook_entry',
                        lambda m, p: f'<p>{p}</p>')
    reader = genbook_reader.GenbookReader(_Pane(), lambda *a: '')
    reader._entry_path = '/Chapter I'
    reader.fetch_and_render()
    reader._entry_path = '/Chapter II'
    assert calls['work'](None)[1] == '/Chapter I'
