"""Guards for the shipped translation catalogues.

A translation is data that runs: `_('({step}/{total}) Downloading {label}…')`
is handed to .format(), so a catalogue that drops or renames a placeholder
raises KeyError in front of the user, in that language only, on a path the
English tests all pass. These checks read every catalogue in LINGUAS, so a
future language is covered the moment it is added.
"""

import os
import re
import shutil
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PO_DIR = os.path.join(ROOT, 'po')

BRACE = re.compile(r'\{[^}{]*\}')
PRINTF = re.compile(r'%[sdifgr%]')


def languages():
    """Codes listed in LINGUAS — the same list meson builds."""
    path = os.path.join(PO_DIR, 'LINGUAS')
    with open(path, encoding='utf-8') as f:
        return [ln.strip() for ln in f
                if ln.strip() and not ln.startswith('#')]


def _parse_po(path):
    """[(msgid, msgid_plural, [msgstr…])] — enough to check placeholders."""
    entries, cur = [], None

    def flush():
        if cur and cur['id']:
            entries.append((cur['id'], cur['plural'], cur['strs']))

    key = None
    for raw in open(path, encoding='utf-8'):
        line = raw.rstrip('\n')
        if not line.strip():
            continue
        if line.startswith('#'):
            continue
        if line.startswith('msgid_plural '):
            key = 'plural'
            cur['plural'] = line[13:].strip()[1:-1]
        elif line.startswith('msgid '):
            flush()
            cur = {'id': line[6:].strip()[1:-1], 'plural': None, 'strs': []}
            key = 'id'
        elif line.startswith('msgstr'):
            cur['strs'].append(line.split(' ', 1)[1].strip()[1:-1])
            key = 'str'
        elif line.startswith('"'):
            chunk = line.strip()[1:-1]
            if key == 'id':
                cur['id'] += chunk
            elif key == 'plural':
                cur['plural'] += chunk
            elif key == 'str':
                cur['strs'][-1] += chunk
    flush()
    return entries


def _parse_po_contexts(path):
    """[(msgid, msgctxt|None, [msgstr…])] — _parse_po drops the context,
    which is exactly what the check below needs to see."""
    entries, cur, key = [], None, None

    def flush():
        if cur and cur['id']:
            entries.append((cur['id'], cur['ctx'], cur['strs']))

    for raw in open(path, encoding='utf-8'):
        line = raw.rstrip('\n')
        if not line.strip() or line.startswith('#'):
            continue
        if line.startswith('msgctxt '):
            flush()
            cur = {'id': '', 'ctx': line[8:].strip()[1:-1], 'strs': []}
            key = 'ctx'
        elif line.startswith('msgid '):
            if key != 'ctx':
                flush()
                cur = {'id': '', 'ctx': None, 'strs': []}
            cur['id'] = line[6:].strip()[1:-1]
            key = 'id'
        elif line.startswith('msgstr'):
            cur['strs'].append(line.split(' ', 1)[1].strip()[1:-1])
            key = 'str'
        elif line.startswith('"'):
            chunk = line.strip()[1:-1]
            if key == 'id':
                cur['id'] += chunk
            elif key == 'ctx':
                cur['ctx'] += chunk
            elif key == 'str':
                cur['strs'][-1] += chunk
    flush()
    return entries


@pytest.fixture(params=languages())
def catalogue(request):
    lang = request.param
    path = os.path.join(PO_DIR, f'{lang}.po')
    assert os.path.exists(path), f'LINGUAS lists {lang} but {path} is missing'
    return lang, path


def test_every_language_in_linguas_has_a_catalogue(catalogue):
    """meson reads LINGUAS, so a code listed without its .po fails the build
    rather than this test — which is exactly why it is cheap to check here."""
    _lang, path = catalogue
    assert os.path.getsize(path) > 0


def test_placeholders_survive_translation(catalogue):
    """The failure this file exists for: a translated string is formatted, so
    a lost or invented placeholder is a KeyError in that language only."""
    lang, path = catalogue
    bad = []
    for msgid, plural, strs in _parse_po(path):
        sources = [msgid] + ([plural] if plural else [])
        for i, translated in enumerate(strs):
            if not translated:
                continue                      # untranslated falls back to English
            source = sources[min(i, len(sources) - 1)]
            for pattern in (BRACE, PRINTF):
                if sorted(pattern.findall(source)) != \
                        sorted(pattern.findall(translated)):
                    bad.append((source, translated))
    assert not bad, (
        f'{lang}: {len(bad)} placeholder mismatches, first: {bad[:3]}')


def test_the_catalogue_compiles(catalogue):
    """msgfmt --check is what the build runs; failing here names the language
    instead of failing an install with a wall of gettext output."""
    lang, path = catalogue
    msgfmt = shutil.which('msgfmt')
    if msgfmt is None:
        pytest.skip('msgfmt not installed')
    r = subprocess.run([msgfmt, '--check', '-o', os.devnull, path],
                       capture_output=True, text=True)
    assert r.returncode == 0, f'{lang}: {r.stderr}'


def test_no_string_is_left_behind_by_the_source(catalogue, tmp_path):
    """Re-extract from source and check nothing falls through to English.

    This is the only check that compares a catalogue against the authority
    rather than against itself. It caught three strings whose msgid carried
    an escape (`\\n`, `\\"`): the catalogue held a literal backslash-n where
    the source has a newline, so the ids never matched and those strings
    silently rendered in English — while msgfmt, and every check written
    around the catalogue's own idea of its ids, passed happily.

    It fires on drift too: change an English string without updating the
    translations and this names the language that fell behind.
    """
    lang, path = catalogue
    for tool in ('xgettext', 'msgmerge', 'msgattrib'):
        if shutil.which(tool) is None:
            pytest.skip(f'{tool} not installed')

    pot = tmp_path / 'scriptura.pot'
    r = subprocess.run(
        ['xgettext', '--files-from=po/POTFILES.in', '--from-code=UTF-8',
         '--keyword=_', '--keyword=N_', '--keyword=C_:1c,2',
         # welcome._summarise takes its translators as `gt`/`ngt` arguments so
         # the language cards can each speak their own language, and naming
         # them `_` would shadow the builtin for that whole function. xgettext
         # cannot guess an alias: without these two the eight strings of the
         # welcome contents line ("{n} Bible", "dictionary", "Detected"…) are
         # invisible to this check, and a catalogue can be short by exactly
         # those eight while this test stays green. Russian shipped that way
         # until a screenshot showed "1 Bible" in English on a Russian card.
         '--keyword=gt', '--keyword=ngt:1,2',
         '-o', str(pot)],
        cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr

    merged = tmp_path / 'merged.po'
    subprocess.run(['msgmerge', '--quiet', '--no-fuzzy-matching',
                    '-o', str(merged), path, str(pot)], check=True)
    left = subprocess.run(['msgattrib', '--untranslated', str(merged)],
                          capture_output=True, text=True, check=True).stdout

    stranded = [ln for ln in left.splitlines()
                if ln.startswith('#:')]
    assert not stranded, (
        f'{lang}: {len(stranded)} strings the source has but the catalogue '
        f'does not translate — {stranded[:5]}')


def test_a_context_actually_buys_a_different_translation(catalogue):
    """A msgid carrying a msgctxt exists only because one English word needs
    two words in some other language — "Search" is the panel's heading, a
    noun, and also the button that opens it, a verb. If both entries end up
    with the same string the context earned nothing, and the most likely
    cause is a merge that quietly copied one onto the other.
    """
    import window

    lang, path = catalogue
    plain, with_ctx = {}, {}
    for msgid, ctx, strs in _parse_po_contexts(path):
        if not strs or not strs[0]:
            continue
        (with_ctx if ctx else plain).setdefault(msgid, []).append(strs[0])

    # Six books are named after the person the genealogy charts also draw, so
    # `Ruth` is a book msgid and a `person` one and both are "Rut". That is the
    # structure of the canon, not a merge that copied one entry onto another:
    # the context still earns its keep in a language that declines a title
    # differently from a name, and dropping it would make the person name
    # collide with the navigation key. Every other context must still differ.
    named_for_a_person = set(window.BOOKS) | set(window.DEUTEROCANON)

    collapsed = [msgid for msgid, vals in with_ctx.items()
                 if msgid in plain and any(v in plain[msgid] for v in vals)
                 and msgid not in named_for_a_person]
    assert not collapsed, (
        f'{lang}: {collapsed} is translated the same with and without its '
        f'context, so the context distinguishes nothing')


def test_every_book_name_is_translated(catalogue):
    """Book names are the one string set a reader meets on every screen, and
    they are dual-role — English stays the key, this is only the display
    path — so a half-translated set reads as a bug rather than a gap."""
    import window

    lang, path = catalogue
    have = {msgid: strs[0] for msgid, _p, strs in _parse_po(path) if strs}
    books = window.BOOKS + window.DEUTEROCANON
    missing = [b for b in books if not have.get(b)]
    assert not missing, f'{lang}: untranslated books {missing}'


def test_book_names_stay_distinct(catalogue):
    """Two books translating to one name would make the picker ambiguous and
    silently send a reader to the wrong place."""
    import window

    lang, path = catalogue
    have = {msgid: strs[0] for msgid, _p, strs in _parse_po(path) if strs}
    books = window.BOOKS + window.DEUTEROCANON
    names = [have[b] for b in books if have.get(b)]
    assert len(set(names)) == len(names), f'{lang}: duplicate book names'


def test_the_module_filter_follows_the_language_the_app_is_running_in(monkeypatch):
    """The in-app picker sets `LANGUAGE`; `LC_ALL`/`LANG` keep whatever the
    desktop said. Reading the environment meant a reader who chose Русский on
    an English desktop got a Russian interface over a Module Manager filtered
    to «Английский (en)» — the one catalogue they had just declined."""
    import i18n
    import module_manager

    monkeypatch.setenv('LANG', 'en_US.UTF-8')
    monkeypatch.setenv('LC_ALL', 'en_US.UTF-8')
    monkeypatch.setattr(i18n, 'current_language', lambda: 'ru')
    assert module_manager._ui_lang() == 'ru'

    monkeypatch.setattr(i18n, 'current_language', lambda: 'es')
    assert module_manager._ui_lang() == 'es'


#: The paper chip is a fixed 56px circle (`_make_swatch`), its label set at
#: 0.74em and semibold, with the theme's padding zeroed so the text cannot
#: inflate it. Two borders and a little air leave about this much room.
_CHIP_INNER_PX = 50


def _chip_label_width(text):
    """How wide `text` sets in the paper chip's own font, measured."""
    import cairo
    import gi
    gi.require_version('Pango', '1.0')
    gi.require_version('PangoCairo', '1.0')
    from gi.repository import Pango, PangoCairo

    ctx = cairo.Context(cairo.ImageSurface(cairo.FORMAT_ARGB32, 200, 60))
    layout = PangoCairo.create_layout(ctx)
    desc = Pango.FontDescription('Adwaita Sans')
    desc.set_weight(Pango.Weight.SEMIBOLD)
    desc.set_absolute_size(0.74 * 14.7 * Pango.SCALE)
    layout.set_font_description(desc)
    layout.set_text(text, -1)
    return layout.get_pixel_size().width


#: Four tabs share the Module Manager's 688px header, so a label has about
#: this much before Adw ellipsizes it. English asks for 102 at its widest.
_TAB_LABEL_PX = 110


def _ui_label_width(text):
    """How wide `text` sets in the interface font, measured."""
    import cairo
    import gi
    gi.require_version('Pango', '1.0')
    gi.require_version('PangoCairo', '1.0')
    from gi.repository import Pango, PangoCairo

    ctx = cairo.Context(cairo.ImageSurface(cairo.FORMAT_ARGB32, 400, 60))
    layout = PangoCairo.create_layout(ctx)
    desc = Pango.FontDescription('Adwaita Sans')
    desc.set_absolute_size(14.7 * Pango.SCALE)
    layout.set_font_description(desc)
    layout.set_text(text, -1)
    return layout.get_pixel_size().width


def test_no_module_manager_tab_outgrows_its_strip(catalogue):
    """A tab that does not fit is not wrong, it is cut: «Переводы Библии»
    showed as "Переводы Б…" and «Herramientas de estudio» as
    "Herramientas…", which is the one place a reader is choosing between
    four words. The English labels are terse — "Bibles", "Study Tools" — and
    a translation that spells them out stops being a tab."""
    lang, path = catalogue
    titles = {'Bibles', 'Commentaries', 'Study Tools', 'Books & More'}
    over = []
    for msgid, _plural, strs in _parse_po(path):
        if msgid not in titles or not strs or not strs[0]:
            continue
        width = _ui_label_width(strs[0])
        if width > _TAB_LABEL_PX:
            over.append(f'{msgid} → {strs[0]!r} is {width}px')
    assert not over, f'{lang}: tab labels too wide: ' + '; '.join(over)


def test_no_paper_name_overflows_its_chip(catalogue):
    """A paper chip shows its name *inside* the circle, in that paper's own
    ink — the chip previews the whole pairing. A name too long for the circle
    does not ellipsize, it spills: Russian «Грифельный» ran 69px through a
    50px opening and lost its Г, and Spanish «Personalizado» ran 75px and had
    been doing so since Spanish shipped, unnoticed.

    English fits with nothing to spare — "Charcoal" is 47px — so this is a
    real constraint on the translation, not a cushion. A language that cannot
    say it short enough needs a shorter word, the way Slate became «Сланец».
    """
    lang, path = catalogue
    names = {'Paper', 'White', 'Sepia', 'Green',
             'Slate', 'Charcoal', 'Black', 'Custom'}
    over = []
    for msgid, _plural, strs in _parse_po(path):
        if msgid not in names or not strs or not strs[0]:
            continue
        width = _chip_label_width(strs[0])
        if width > _CHIP_INNER_PX:
            over.append(f'{msgid} → {strs[0]!r} is {width}px')
    assert not over, (
        f'{lang}: paper names too wide for the 56px chip: ' + '; '.join(over))
