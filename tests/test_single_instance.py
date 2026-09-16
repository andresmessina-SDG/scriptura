"""One copy of the app at a time.

Each copy holds the reader's notes, journal and sermons in memory and
rewrites the whole file on save. With two copies open — a second launch, or a
`bible:` link clicked while the app was running — the last one to save
erased what the other had written. The launcher now asks for a single copy,
and a second launch hands its link to the window already open.
"""

from gi.repository import Gio

import main


def test_the_launcher_asks_for_one_copy():
    flags = main.BibleApp(unique=True).get_flags()
    assert not flags & Gio.ApplicationFlags.NON_UNIQUE
    assert flags & Gio.ApplicationFlags.HANDLES_OPEN


def test_tools_keep_their_own_copy_by_default():
    """A verify tool builds the app beside whatever copy the reader has
    open. Unique by default, it would hand its work to the reader's window
    and exit."""
    assert main.BibleApp().get_flags() & Gio.ApplicationFlags.NON_UNIQUE


def test_a_link_passed_on_through_gio_still_parses():
    """A link sent to the running copy arrives as a Gio.File, which rewrites
    `bible:John+3:16` as `bible:///John+3:16`."""
    uri = Gio.File.new_for_uri('bible:John+3:16').get_uri()
    assert main._parse_bible_uri(uri) == 'John 3:16'
    assert main._parse_bible_uri('bible:1+Corinthians+13:4') == '1 Corinthians 13:4'


class _FakeMain:
    def __init__(self):
        self.refs, self.presented = [], 0

    def open_reference(self, ref):
        self.refs.append(ref)

    def present(self):
        self.presented += 1


def _app_with(monkeypatch, windows):
    monkeypatch.setattr(main, 'BibleWindow', _FakeMain)
    app = main.BibleApp(unique=True)
    app._argv_ref = None
    monkeypatch.setattr(app, 'get_windows', lambda: windows)
    built = []
    monkeypatch.setattr(app, '_present_main_or_welcome',
                        lambda *a, **k: built.append(k))
    return app, built


def test_a_second_launch_raises_the_open_window(monkeypatch):
    win = _FakeMain()
    app, built = _app_with(monkeypatch, [win])
    app._on_activate(app)
    assert win.presented == 1 and not built


def test_a_link_goes_to_the_open_window(monkeypatch):
    win = _FakeMain()
    app, built = _app_with(monkeypatch, [win])
    app._on_open(app, [Gio.File.new_for_uri('bible:John+3:16')], 1, '')
    assert win.refs == ['John 3:16'] and win.presented == 1 and not built


def test_the_first_launchs_own_link_is_spent_on_its_first_window(monkeypatch):
    """Otherwise every link sent on later would take the reader back to the
    one the app was first opened with."""
    app, built = _app_with(monkeypatch, [])
    app._argv_ref = 'Psalm 23'
    app._on_open(app, [], 0, '')
    assert built == [{'startup_ref': 'Psalm 23'}]
    win = _FakeMain()
    monkeypatch.setattr(app, 'get_windows', lambda: [win])
    app._on_open(app, [Gio.File.new_for_uri('bible:John+3:16')], 1, '')
    assert win.refs == ['John 3:16']
