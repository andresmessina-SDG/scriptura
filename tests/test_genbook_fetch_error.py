"""A Generic Book that raises while it is read says so.

The fetch ran on a bare thread: when sword_bridge raised, nothing came back
to the main loop and the pane kept the last book's page. It now runs on
tasks.py, whose on_error names the module and the error.
"""
import genbook_reader
import sword_bridge
import tasks


class _Pane:
    module = 'Broken'


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
