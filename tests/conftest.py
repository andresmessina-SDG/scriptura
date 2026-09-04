"""Install gettext builtins (_ / ngettext) for the test session.

The app installs these in main._setup_gettext() at startup. Tests import
modules directly without that bootstrap, so any function that uses _() or
ngettext() at call time — content.info(), open_data.get_sources(), the
feature-pack display names, etc. — would otherwise hit NameError. Installing
a no-catalog gettext here resolves them to identity (English) output.
"""
import builtins
import gettext
import os
import tempfile

# ── The suite must not read, or write, the tester's own settings ───────────
# `main._setup_gettext()` runs at main.py's module level, and two test files
# import main. It reads the saved `ui_language` and, if there is one, writes
# it into os.environ['LANGUAGE'] and rebinds the builtins `_` through
# gettext.install — process-wide, and past any monkeypatch. So on a machine
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

gettext.install('scriptura', names=['ngettext'])

# book_label() is installed as a builtin by main._setup_gettext() alongside
# _ / ngettext; mirror that here so modules that display book names resolve it.
import i18n  # noqa: E402  (after gettext.install so its module-level _ binds)

# setattr (not `builtins.book_label = …`): the builtins module has no declared
# book_label attribute, so a direct assignment trips mypy's [attr-defined].
setattr(builtins, 'book_label', i18n.book_label)
# C_() disambiguates one English word that needs two Spanish ones (the search
# panel's heading is a noun, the button that opens it a verb). Same bootstrap,
# same reason: without it a test that builds such a widget hits NameError.
setattr(builtins, 'C_', i18n.C_)
