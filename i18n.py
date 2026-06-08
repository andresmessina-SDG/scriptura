"""Importable gettext helpers.

main._setup_gettext() installs ``_`` / ``ngettext`` into builtins for the bulk
of the UI, but builtins injected at runtime are invisible to static analysis
(mypy reports ``Name "_" is not defined``). Modules type-checked under
mypy-strict import the same callables from here instead, so the names resolve.
Both paths use the 'scriptura' domain bound in _setup_gettext, so they
translate identically (gettext.gettext honours the domain set with
gettext.textdomain()).
"""
import gettext as _gettext

#: Translate a message via the current (scriptura) text domain.
_ = _gettext.gettext
#: Plural-aware translation.
ngettext = _gettext.ngettext


def N_(message: str) -> str:
    """No-op gettext marker: tags a string for xgettext extraction without
    translating at definition time (module-level data tables), then translated
    at display via _()."""
    return message
