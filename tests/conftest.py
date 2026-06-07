"""Install gettext builtins (_ / ngettext) for the test session.

The app installs these in main._setup_gettext() at startup. Tests import
modules directly without that bootstrap, so any function that uses _() or
ngettext() at call time — content.info(), open_data.get_sources(), the
feature-pack display names, etc. — would otherwise hit NameError. Installing
a no-catalog gettext here resolves them to identity (English) output.
"""
import gettext

gettext.install('scriptura', names=['ngettext'])
