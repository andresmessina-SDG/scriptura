"""Importable gettext helpers.

main._setup_gettext() installs ``_`` / ``ngettext`` into builtins for the bulk
of the UI, but builtins injected at runtime are invisible to static analysis
(mypy reports ``Name "_" is not defined``). Modules type-checked under
mypy-strict import the same callables from here instead, so the names resolve.
Both paths use the 'scriptura' domain bound in _setup_gettext, so they
translate identically (gettext.gettext honours the domain set with
gettext.textdomain()).
"""
import datetime as _dt
import gettext as _gettext
from collections.abc import Callable

#: The app's gettext domain, shared by main's bootstrap and the switcher.
DOMAIN = 'scriptura'

#: The catalogue in effect, and the environment that chose it. `gettext`'s
#: own module-level functions resolve the catalogue on EVERY call — a `find()`
#: that stats the locale tree — which measured **30µs a string** against
#: **0.06µs** for the object gettext.install binds into builtins. Nobody had
#: measured it, and the `from i18n import _` migration was quietly moving
#: modules onto the slow one: 19 files, every string they draw. The Module
#: Manager paid it 866 times for one list rebuild — 27ms of stat calls.
#:
#: Keyed on the environment rather than invalidated by hand, so the promise
#: the switcher relies on still holds — these re-read the environment, they
#: just stop re-reading the disk when nothing has changed.
_env_key: tuple[str | None, ...] | None = None
_catalogue_cache: _gettext.NullTranslations | None = None
_lang_cache: str | None = None
_lang_key: tuple[str | None, ...] | None = None


def _env() -> tuple[str | None, ...]:
    """Everything that decides which catalogue answers.

    The locale directory belongs in the key as much as the environment does:
    it never moves in a running app, but the tests that pin a temporary one
    move it, and a cache that ignored it answered them from the previous
    directory — which is how the existing ui-language tests caught this cache
    the first time it was written.
    """
    import os
    return (os.environ.get('LANGUAGE'), os.environ.get('LC_ALL'),
            os.environ.get('LC_MESSAGES'), os.environ.get('LANG'),
            localedir())


def _catalogue() -> _gettext.NullTranslations:
    """The compiled catalogue for the language in effect.

    `fallback=True` returns a NullTranslations when nothing is installed, so
    a source checkout answers in the untranslated source rather than raising
    — the same thing gettext.gettext does, and the reason a repo run shows
    English.
    """
    global _env_key, _catalogue_cache, _lang_cache
    env = _env()
    if _catalogue_cache is None or env != _env_key:
        try:
            _catalogue_cache = _gettext.translation(
                DOMAIN, localedir(), fallback=True)
        except Exception:
            # `fallback=True` covers "no catalogue"; it does not cover a
            # catalogue that is there and unreadable — a truncated .mo raises
            # out of the parser. English is the right answer to that, and a
            # crash is not.
            _catalogue_cache = _gettext.NullTranslations()
        _lang_cache = None
        _env_key = env
    return _catalogue_cache


def _(message: str) -> str:
    """Translate a message via the current (scriptura) text domain."""
    return _catalogue().gettext(message)


def ngettext(singular: str, plural: str, n: int) -> str:
    """Plural-aware translation."""
    return _catalogue().ngettext(singular, plural, n)


def C_(context: str, message: str) -> str:
    """Translate `message` in `context`.

    English reuses one word where other languages need two. "Search" is the
    search panel's heading — a noun, `Búsqueda` — and also the button that
    opens it, a verb, `Buscar`. One msgid cannot be both, and whichever
    translation wins, the other place reads wrong in a way no English
    reader can see. The context splits them.

    Named C_ after the GNOME convention; meson's `glib` gettext preset
    already extracts it.
    """
    return _catalogue().pgettext(context, message)


#: The UI languages the app can offer, in their own names. A code only
#: reaches the picker when its compiled catalogue is actually installed
#: (see available_languages), so this table may name more than a given
#: install can use. English is the source language and needs no catalogue.
LANGUAGE_NAMES = {
    'en': 'English',
    'es': 'Español',
    'ru': 'Русский',
}


_localedir_cache: str | None = None


def localedir() -> str:
    """Where the compiled catalogues live.

    Resolved relative to this file — installed at {prefix}/share/scriptura/,
    catalogues at {prefix}/share/locale — which is the same __file__-relative
    trick main.py uses for the icon search path.

    A source checkout has no such directory, and used to offer English only
    for that reason: the language picker hides itself below two languages,
    so running from the repo silently lost a shipped feature and anything
    reached through it. So fall back to a `locale/` beside this file, which
    `tools/build-locale.py` fills from `po/`. The fallback is only ever
    consulted when the installed path is absent, so it cannot shadow a real
    install, and it is gitignored.
    """
    global _localedir_cache
    if _localedir_cache is None:
        import os
        here = os.path.dirname(os.path.abspath(__file__))
        installed = os.path.join(here, '..', 'locale')
        _localedir_cache = (installed if os.path.isdir(installed)
                            else os.path.join(here, 'locale'))
    return _localedir_cache


def available_languages() -> list[tuple[str, str]]:
    """[(code, native name)] for every language this install can show.

    Read from the disk rather than from po/LINGUAS: a catalogue that was
    never compiled, or a partial install, would otherwise be offered and
    then quietly do nothing. English is always first — it is the source
    language, so it needs no catalogue and is always available.
    """
    import os
    out = [('en', LANGUAGE_NAMES['en'])]
    base = localedir()
    try:
        codes = sorted(os.listdir(base))
    except OSError:
        return out
    for code in codes:
        if code == 'en':
            continue
        mo = os.path.join(base, code, 'LC_MESSAGES', 'scriptura.mo')
        if os.path.isfile(mo):
            out.append((code, LANGUAGE_NAMES.get(code, code)))
    return out


def translator_for(
        code: str) -> tuple[Callable[[str], str],
                            Callable[[str, str, int], str]]:
    """`(gettext, ngettext)` that translate into `code`, whatever is installed.

    The welcome window's language cards each have to speak their own language
    at the same moment — a Spanish card under an English interface says
    "3 Biblias", because a reader who needs that page is choosing between
    words they may not read. `_()` cannot do that: it answers in the one
    language the app is running in.

    Falls back to the untranslated source (English) for a code with no
    compiled catalogue, which is what a run from a source checkout gets.
    """
    tr = _gettext.translation(DOMAIN, localedir(), languages=[code],
                              fallback=True)
    return tr.gettext, tr.ngettext


def current_language() -> str:
    """The language actually in effect — what the reader is looking at.

    Not the same as the `ui_language` setting. With no override the desktop
    decides, so a picker that preselected the setting would show English to
    a reader whose Spanish desktop is handing them a Spanish app, and then
    change nothing when they chose Spanish. Ask gettext which catalogue it
    resolved; no catalogue means the untranslated source, i.e. English.

    Cached alongside the catalogue, because the answer costs a `find()` and
    the Module Manager asks it twice for every row it draws.
    """
    global _lang_cache, _lang_key
    env = _env()
    if _lang_cache is not None and env == _lang_key:
        return _lang_cache
    _lang_key = env
    import os
    path = _gettext.find(DOMAIN, localedir())
    if not path:
        _lang_cache = 'en'
    else:
        parts = os.path.normpath(path).split(os.sep)
        # <localedir>/<code>/LC_MESSAGES/<domain>.mo — and a regional code
        # like es_MX shares this app's es catalogue, so keep the language
        # half.
        _lang_cache = 'en' if len(parts) < 3 else parts[-3].split('_')[0]
    return _lang_cache


def install_language(code: str | None) -> None:
    """Switch the running app's catalogue.

    Only the welcome flow uses this. Everywhere else the language is read
    once at startup, because `_()` resolves when a widget is built: the
    strings already on screen were translated at construction and no
    re-binding reaches back to change them. The welcome window can do it
    because it rebuilds itself afterwards.

    The builtins have to be re-installed, not just re-bound: gettext.install
    binds `_` to one translation object, and that object does not notice a
    later change of language. i18n's own `_` needs nothing: it re-reads the
    environment per call and re-resolves the catalogue whenever that answer
    changes (see `_catalogue`).
    """
    import os
    if code:
        os.environ['LANGUAGE'] = code
    else:
        os.environ.pop('LANGUAGE', None)
    base = localedir()
    try:
        _gettext.bindtextdomain(DOMAIN, base)
        _gettext.textdomain(DOMAIN)
        _gettext.install(DOMAIN, base, names=['ngettext'])
    except OSError:
        return


def N_(message: str) -> str:
    """No-op gettext marker: tags a string for xgettext extraction without
    translating at definition time (module-level data tables), then translated
    at display via _()."""
    return message


# ── Dates ───────────────────────────────────────────────────────────────────
#
# Dates are written here rather than handed to strftime. `%A`, `%B` and `%b`
# follow LC_TIME, which the app deliberately leaves on the desktop's setting
# so that a Spanish reader on an English system keeps their own number and
# sort order (see main._setup_gettext). That reasoning holds on a host with
# the locales installed and fails completely where the app actually ships:
# the Flatpak runtime's locale extension is subsetted to the host's own
# languages, and a sandbox built on an English host carries 35 locales, every
# one of them en_*, C or POSIX. setlocale to es_ES or ru_RU there does not
# fall back — it raises. So the Today page read "WEDNESDAY · 2 SEPTEMBER
# 2026" above a Russian heading, in every language, on every install.
#
# Translating the names moves the problem into the catalogue, where the app
# already controls it. The order moves with them: a format string per surface
# rather than a hard-coded one, because a language that writes the day first
# should not have to accept English word order to get its own month names.

#: Weekday names, indexed by `date.weekday()` — Monday is 0. Standalone
#: text, so the plain nominative is what every language wants here.
_WEEKDAYS = (N_('Monday'), N_('Tuesday'), N_('Wednesday'), N_('Thursday'),
             N_('Friday'), N_('Saturday'), N_('Sunday'))


def month_name(month: int) -> str:
    """The month's name as it is written *inside a date*, 1-based.

    The context is not decoration. Russian declines the month when a day
    stands before it — 2 сентября, not 2 сентябрь — so the string a date
    needs is not the string a standalone month header would need. Naming
    that in the msgid is what stops a translator supplying one and the app
    using it for the other; a nominative set can be added beside this one
    if a surface ever wants it.
    """
    return (C_('month, in a date', 'January'),
            C_('month, in a date', 'February'),
            C_('month, in a date', 'March'),
            C_('month, in a date', 'April'),
            C_('month, in a date', 'May'),
            C_('month, in a date', 'June'),
            C_('month, in a date', 'July'),
            C_('month, in a date', 'August'),
            C_('month, in a date', 'September'),
            C_('month, in a date', 'October'),
            C_('month, in a date', 'November'),
            C_('month, in a date', 'December'))[month - 1]


def weekday_name(weekday: int) -> str:
    """The weekday's name, as `date.weekday()` numbers them (Monday = 0)."""
    return _(_WEEKDAYS[weekday])


def month_abbr(month: int) -> str:
    """The month's short form, 1-based, for the calendar tiles.

    The literals sit inside the call so xgettext can see them, and carry a
    context because English collides with itself: `May` is both the full
    name and the abbreviation, one msgid for two translations — `mayo` and
    `may` in Spanish. Twelve pgettext lookups a call, at 0.06µs each.
    """
    return (C_('month abbreviation', 'Jan'), C_('month abbreviation', 'Feb'),
            C_('month abbreviation', 'Mar'), C_('month abbreviation', 'Apr'),
            C_('month abbreviation', 'May'), C_('month abbreviation', 'Jun'),
            C_('month abbreviation', 'Jul'), C_('month abbreviation', 'Aug'),
            C_('month abbreviation', 'Sep'), C_('month abbreviation', 'Oct'),
            C_('month abbreviation', 'Nov'), C_('month abbreviation', 'Dec')
            )[month - 1]


def format_date(date: _dt.date) -> str:
    """A full date the way the Today page writes it — `2 September 2026`.

    The order is the translator's: Spanish and Russian put the day first and
    lower-case the month, which no rearrangement of English can produce.
    """
    return C_('date, day first', '{day} {month} {year}').format(
        day=date.day, month=month_name(date.month), year=date.year)


def format_date_heading(date: _dt.date) -> str:
    """A full date the way the devotional heads its reading —
    `September 2, 2026`. Separate from format_date because the two surfaces
    print the date differently in English and need not agree elsewhere."""
    return C_('date, month first', '{month} {day}, {year}').format(
        day=date.day, month=month_name(date.month), year=date.year)


def book_label(name: str) -> str:
    """Localized *display* name for a Bible book.

    The English name stays canonical everywhere it acts as a key — SWORD
    VerseKey text, OSIS mapping, persisted annotation/bookmark/position
    records — and is translated only here, at the point it is shown to the
    user. The names are marked for extraction with ``N_()`` in window.BOOKS
    and window.DEUTEROCANON; any other name has no catalog entry and falls
    through to English unchanged."""
    return _(name)
