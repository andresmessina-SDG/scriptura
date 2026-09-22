"""Session-wide floors: no test reads or writes the tester's own files.

Nothing installs `_` into builtins any more, here or in the app: every
module imports its helpers from i18n, so a module that forgets to fails
the suite with NameError instead of passing on a name the test run lent it.
"""
import os
import tempfile

# ── The suite must not read, or write, the tester's own settings ───────────
# `main._setup_gettext()` runs at main.py's module level, and two test files
# import main. It reads the saved `ui_language` and, if there is one, writes
# it into os.environ['LANGUAGE'], which i18n's `_` reads on every call —
# process-wide, and past any monkeypatch. So on a machine
# where the app is set to Russian the whole suite switched language the
# moment `import main` first ran: 20 tests in test_reading_audio asserting
# "John 3" and getting «От Иоанна 3», in whatever file happened to follow.
#
# It could not show until a checkout had compiled catalogues to switch into
# (tools/build-locale.py), which is why it stood for so long — and it made
# the result depend on a file outside the repo either way. A scratch file,
# set before anything imports settings, closes both: nothing is read from
# ~/.config, and no test can write there.
import settings as _settings  # noqa: E402

_settings._FILE = os.path.join(tempfile.mkdtemp(prefix='scriptura-tests-'),
                               'settings.json')
_settings._cache = None

# ── Nor the tester's own study data ────────────────────────────────────────
# The same reasoning one block up, and it has now fired for real: a journal
# entry from a test landed in ~/.local/share/bible-reader/journal.json,
# because a window built in one test left an autosave timer armed and it went
# off in a later test, by which time the store pointed at the real file
# again. Fixtures that isolate a store per test cannot catch that — the write
# happens between them.
#
# So every store the UI can write gets a scratch default at import, before
# any test touches one. A test that monkeypatches its own path still wins;
# this is only the floor. Nothing here is read either, so a machine with a
# full annotation history runs the suite the same as a fresh checkout.
_SCRATCH = tempfile.mkdtemp(prefix='scriptura-stores-')

import annotations as _annotations  # noqa: E402
import bookmarks as _bookmarks  # noqa: E402
import journal as _journal  # noqa: E402
import module_positions as _module_positions  # noqa: E402
import reading_plans as _reading_plans  # noqa: E402
import sermons as _sermons  # noqa: E402

_annotations.ANNOTATIONS_FILE = os.path.join(_SCRATCH, 'annotations.json')
_annotations._cache = None
_journal.JOURNAL_FILE = os.path.join(_SCRATCH, 'journal.json')
_journal._cache = None
_bookmarks._FILE = os.path.join(_SCRATCH, 'bookmarks.json')
_reading_plans._FILE = os.path.join(_SCRATCH, 'reading_plans.json')
_reading_plans._cache = None
_module_positions._FILE = os.path.join(_SCRATCH, 'module_positions.json')
_sermons.SERMONS_FILE = os.path.join(_SCRATCH, 'sermons.json')
_sermons._cache = None


# ── No test may put a file chooser on the tester's screen ──────────────────
# Gtk.FileDialog's save() and open() are the calls that present one. A test
# that reaches a handler ending in either of those throws a real chooser onto
# the desktop, parented to a real window, where it sits until the test
# destroys that window — which is how the Annotations single-entry export
# test came to flash "Export — Journal" on every run of the suite.
#
# CI can never catch this: it has no screen, so the dialog is a no-op there
# and the test passes. The floor has to be here.
#
# A test that means to exercise such a handler stubs the call itself, and its
# monkeypatch wins over this one for the length of that test. This only
# refuses the calls nobody asked for, and names the method so the failure
# says what to do about it.
import gi  # noqa: E402

gi.require_version('Gtk', '4.0')
from gi.repository import Gtk  # noqa: E402


def _refuse_to_present(method):
    def refused(self, *args, **kwargs):
        raise AssertionError(
            f'Gtk.FileDialog.{method}() would put a file chooser on the '
            f'screen. Stub it in this test:\n'
            f"    monkeypatch.setattr(Gtk.FileDialog, '{method}',\n"
            f'                        lambda self, parent, cancellable, cb: '
            f'None)')
    return refused


for _method in ('save', 'open', 'select_folder'):
    setattr(Gtk.FileDialog, _method, _refuse_to_present(_method))
