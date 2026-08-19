"""Install gettext builtins (_ / ngettext) for the test session.

The app installs these in main._setup_gettext() at startup. Tests import
modules directly without that bootstrap, so any function that uses _() or
ngettext() at call time — content.info(), open_data.get_sources(), the
feature-pack display names, etc. — would otherwise hit NameError. Installing
a no-catalog gettext here resolves them to identity (English) output.
"""
import builtins
import gettext

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
