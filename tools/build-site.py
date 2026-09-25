#!/usr/bin/env python3
"""Build the Scriptura website into docs/, which GitHub Pages serves.

    python3 tools/build-site.py                  # the pages, from site/
    python3 tools/build-site.py --data SWORD_DIR # also re-read the passages
    python3 tools/build-site.py --assets         # also re-cut fonts and icons

The pages come from `site/page.html`, the words from `site/strings/*.toml`
and the live reading pane's text from `site/data/*.json`. The version and
the three starting libraries come from the app itself (`_version`,
`welcome.bundles_for`), so the site cannot drift from what installs.

`--data` reads John 1:1-5 and the entries a click opens through the app's
own lookups (`sword_bridge.lookup_dict_entry`, `word_links.key_for`), from a
SWORD library holding KJVA, BSB, SpaRV1909, RusOpenBible, StrongsGreek,
Wikcionario and RussianBibleWords, and from the eBible store for the two
eBible texts. Only open texts: every one is public domain or CC BY / BY-SA,
and the colophon credits each.

Nothing here runs when the site is served; the output is plain files.
"""
import argparse
import html
import json
import os
import re
import shutil
import sys
import tomllib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = os.path.join(ROOT, 'site')
DOCS = os.path.join(ROOT, 'docs')
BASE_URL = 'https://andresmessina-sdg.github.io/scriptura/'
LANGS = ('en', 'es', 'ru')
PASSAGE = ('John', 1, range(1, 6))

# The pane's two texts and the dictionary a click opens, per language.
# `left` is Strong's-tagged and clickable; `right` is plain.
TEXTS = {
    'en': {'left': ('sword', 'KJVA'), 'right': ('sword', 'BSB'),
           'lookup': 'strongs'},
    'es': {'left': ('sword', 'SpaRV1909'), 'right': ('ebible', 'spabes'),
           'lookup': 'Wikcionario'},
    'ru': {'left': ('sword', 'RusOpenBible'), 'right': ('ebible', 'russyn'),
           'lookup': 'RussianBibleWords'},
}


# ── the passage data (--data) ─────────────────────────────────────────────
_W = re.compile(r'<w\b([^>]*)>(.*?)</w>', re.S)
_STRONG = re.compile(r'strong:([GH])0*(\d+)', re.I)


def _plain(markup):
    return html.unescape(re.sub(r'<[^>]+>', '', markup))


def _clean(raw):
    """A verse's markup without its notes and headings, which are not text."""
    return re.sub(r'<(note|title)\b.*?</\1>', '', raw, flags=re.S)


def _tokens(raw):
    """[text, strongs-or-None] runs for one verse of OSIS markup."""
    raw = _clean(raw)
    out, pos = [], 0
    for m in _W.finditer(raw):
        if m.start() > pos:
            out.append([_plain(raw[pos:m.start()]), None])
        nums = ['%s%s' % (a.upper(), b) for a, b in _STRONG.findall(m.group(1))]
        # "the Word" carries the article's number beside the noun's; the
        # noun is the word a reader means to look up.
        nums = [n for n in nums if n != 'G3588'] or nums
        out.append([_plain(m.group(2)), nums[-1] if nums else None])
        pos = m.end()
    if pos < len(raw):
        out.append([_plain(raw[pos:]), None])
    return [t for t in out if t[0]]


def _strongs_entry(mgr, number):
    """Strong's Greek entry as {g, t, p, d, u}, or None when unreadable."""
    if not number.startswith('G'):
        return None
    mod = mgr.getModule('StrongsGreek')
    mod.setKeyText(number[1:].zfill(5))
    text = mod.stripText().strip()
    # G3739 in the CrossWire module carries a stray Chinese fragment; an
    # entry we cannot parse cleanly is left out rather than shown broken.
    if re.search(r'[\u3000-\u9fff]', text):
        return None
    m = re.match(r'\d+\.\s+(\S+)\s+\S+\s+(\S+)\s+\{([^}]*)\}\s*(.*)', text, re.S)
    if not m:
        return None
    greek, translit, pron, rest = m.groups()
    rest = re.sub(r'\s*see GREEK for \d+', '', rest).strip()
    defn, _sep, uses = rest.partition(':--')
    return {'g': greek, 't': translit, 'p': pron,
            'd': defn.strip().rstrip(';'), 'u': uses.strip().rstrip('.')}


def _article(markup, limit=900):
    """A dictionary article as paragraphs, cut at a paragraph near `limit`."""
    paras = [_plain(p).strip() for p in re.split(r'<br\s*/?>', markup)]
    paras = [p for p in paras if p]
    out, size = [], 0
    for p in paras:
        if out and size + len(p) > limit:
            out.append('…')
            break
        out.append(p)
        size += len(p)
    return out


def _ebible_verses(path, translation):
    import sqlite3
    con = sqlite3.connect(path)
    rows = con.execute(
        'SELECT verse, text FROM verses WHERE translation=? AND book=? '
        'AND chapter=? AND verse BETWEEN ? AND ? ORDER BY verse',
        (translation, PASSAGE[0], PASSAGE[1], PASSAGE[2][0], PASSAGE[2][-1]))
    return [t for _v, t in rows]


def _cross_refs(path, book_osis, chapter, verse, limit=6):
    """The passages OpenBible links to one verse, most-voted first, as
    (book, chapter, verse) of each target's first verse."""
    import csv
    sys.path.insert(0, ROOT)
    import open_data
    # A link may be filed under a range ("John.1.1-John.1.2"), as the app
    # reads it: match every verse the range covers.
    key = open_data._vid(open_data._OSIS_BOOKS[book_osis], chapter, verse)
    rows = []
    with open(path, encoding='utf-8') as fh:
        reader = csv.reader(fh, delimiter='\t')
        next(reader)
        for row in reader:
            if (len(row) >= 3 and row[0].startswith(book_osis + '.')
                    and key in (open_data._osis_to_vids(row[0]) or ())):
                target = open_data._osis_first_tuple(row[1])
                if target:
                    rows.append((int(row[2]), target))
    rows.sort(key=lambda r: -r[0])
    return [target for _votes, target in rows[:limit]]


def _voices(path, book, chapter, verse, limit=4):
    """The church's quotations on one verse: the narrowest passages first,
    one per author, then set in date order."""
    import sqlite3
    con = sqlite3.connect(path)
    loc = chapter * 1_000_000 + verse
    rows = con.execute(
        'SELECT author, year, source_title, text, loc_end - loc_start AS span '
        'FROM quotes WHERE book=? AND loc_start<=? AND loc_end>=? '
        'AND condemned=0 AND author NOT IN (SELECT DISTINCT book FROM quotes) '
        'ORDER BY span, year', (book, loc, loc)).fetchall()
    # A reading written to explain the verse comes before one met in passing;
    # a work that reports what heretics taught is not the church's reading.
    def genre(title):
        if re.search(r'Gospel of John|on John|Joan|Catena Aurea', title):
            return 0            # written on this Gospel
        if re.search(r'Commentar|Homil|Tractate|Sermon|Exposition', title):
            return 1            # written to explain Scripture
        return 2
    rows = sorted(rows, key=lambda r: (genre(r[2] or ''), r[4], r[1] or 0))
    picked, seen = [], set()
    for author, year, source, text, _span in rows:
        if author in seen or not text or 'Refutation of All Heresies' in (source or ''):
            continue
        seen.add(author)
        picked.append((year or 0, author, source or '', _excerpt(text)))
        if len(picked) == limit:
            break
    return sorted(picked)


def _excerpt(text, limit=420):
    """The opening of a quotation, cut at a sentence near `limit`."""
    text = re.sub(r'\s+', ' ', text).strip()
    # Catena Aurea opens many extracts on its own citation, "(Hom. v. in Joan.)".
    text = re.sub(r'^\([^)]{1,60}\)\s*', '', text)
    # ...and cites its sources in passing, "(Prov. 16. Vulg.)": the editor's
    # references, not the father's words.
    text = re.sub(r'\s*\((?=[^)]*(?:\d|\bc\.|\b[ivxl]+\.))[^()]{1,40}\)', '', text)
    if len(text) <= limit:
        return text
    cut = max(text.rfind('. ', 0, limit), text.rfind('? ', 0, limit),
              text.rfind('; ', 0, limit))
    return text[:cut + 1 if cut > limit // 2 else limit].rstrip() + ' …'


def _dodson(path):
    """Strong's number -> Dodson's brief gloss (public domain)."""
    import csv
    out = {}
    with open(path, encoding='utf-8') as fh:
        for row in csv.DictReader(fh, delimiter='\t'):
            num = (row.get("Strong's") or '').strip().lstrip('0')
            gloss = (row.get('English Definition (brief)') or '').strip()
            if num and gloss:
                out['G' + num] = gloss
    return out


def build_data(sword_dir, ebible_db, open_dir, catena_db):
    os.environ['SWORD_PATH'] = sword_dir
    sys.path.insert(0, ROOT)
    import Sword
    import sword_bridge
    import word_links
    import i18n
    mgr = Sword.SWMgr(sword_dir)
    book, chapter, verses = PASSAGE
    glosses = _dodson(os.path.join(open_dir, 'dodson.csv'))
    xref_file = os.path.join(open_dir, 'cross_references.txt')
    for lang, spec in TEXTS.items():
        i18n.install_language(lang)

        def verse_raw(module, v, where=None):
            mod = mgr.getModule(module)
            if mod is None:
                sys.exit(f'{module} is not in {sword_dir}')
            b, c = where or (book, chapter)
            mod.setKey(Sword.VerseKey(f'{b} {c}:{v}'))
            return mod.getRawEntry()

        def verse_text(b, c, v):
            """A cross-reference's verse in this page's Bible, or in its
            companion when the first lacks the book."""
            text = _plain(_clean(verse_raw(spec['left'][1], v, (b, c)))).strip()
            if not text and spec['right'][0] == 'ebible':
                import sqlite3
                row = sqlite3.connect(ebible_db).execute(
                    'SELECT text FROM verses WHERE translation=? AND book=? '
                    'AND chapter=? AND verse=?',
                    (spec['right'][1], b, c, v)).fetchone()
                text = row[0] if row else ''
            text = re.sub(r'\s+', ' ', text)
            # RV1909 sets a book's first word in capitals ("EN el principio").
            return re.sub(r'^(\w)(\w+)\b', lambda m: m.group(1) + m.group(2).lower()
                          if m.group(2).isupper() else m.group(0), text)

        left = [_tokens(verse_raw(spec['left'][1], v)) for v in verses]
        kind, name = spec['right']
        right = ([_plain(_clean(verse_raw(name, v))).strip() for v in verses]
                 if kind == 'sword' else _ebible_verses(ebible_db, name))
        entries, lookup = {}, spec['lookup']
        for v, toks in zip(verses, left):
            for tok in toks:
                word, number = tok
                # A one-letter word ("у", "a") shares its number with the
                # noun beside it; a click there would open the noun.
                if not number or len(re.sub(r'\W', '', word)) < 2:
                    tok[1] = None
                    continue
                if lookup == 'strongs':
                    key = number
                    if key not in entries:
                        entries[key] = _strongs_entry(mgr, number)
                else:
                    if lookup == 'RussianBibleWords':
                        key = word_links.key_for(lookup, book, chapter, v,
                                                 [number])
                        found = sword_bridge.lookup_dict_entry(lookup, key)[0] if key else ''
                    else:
                        found, exact = sword_bridge.lookup_dict_entry(lookup, word)
                        key = word.lower() if exact else None
                        found = found if exact else ''
                    if not key or not found:
                        tok[1] = None
                        continue
                    if key not in entries:
                        head = _strongs_entry(mgr, number) or {}
                        paras = _article(found)
                        # The Russian articles open on their own title.
                        if paras and paras[0].upper() == key.upper():
                            paras = paras[1:]
                        entries[key] = {'g': head.get('g', ''),
                                        't': head.get('t', ''),
                                        'n': number, 'h': key.upper()
                                        if lookup == 'RussianBibleWords'
                                        else word, 'a': paras}
                if entries.get(key) is None:
                    tok[1] = None
                else:
                    tok[1] = key
        entries = {k: e for k, e in entries.items() if e}
        for key, e in entries.items():
            gloss = glosses.get(e.get('n') or key)
            if gloss:
                e['b'] = gloss
        xrefs = []
        for v in verses:
            refs = []
            for b, c, rv in _cross_refs(xref_file, 'John', chapter, v):
                text = verse_text(b, c, rv)
                if text:
                    refs.append({'r': f'{i18n.book_label(b)} {c}:{rv}',
                                 't': text})
            xrefs.append(refs)
        voices = [[{'a': a, 'y': (i18n._('c. {year} AD').format(year=y) if y > 0
                                  else i18n._('c. {year} BC').format(year=-y)
                                  if y < 0 else ''),
                    's': s, 't': q}
                   for y, a, s, q in _voices(catena_db, book, chapter, v)]
                  for v in verses]
        path = os.path.join(SITE, 'data', f'{lang}.json')
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as fh:
            json.dump({'left': left, 'right': right, 'entries': entries,
                       'lookup': lookup, 'xrefs': xrefs, 'voices': voices,
                       'ref': f'{i18n.book_label(book)} {chapter}'},
                      fh, ensure_ascii=False, indent=1)
            fh.write('\n')
        print(f'{lang}: {len(entries)} entries, '
              f'{sum(map(len, xrefs))} cross-references, '
              f'{sum(map(len, voices))} quotations')
    i18n.install_language(None)


# ── fonts and icons (--assets) ────────────────────────────────────────────
LATIN = ('U+0020-007E,U+00A0-00FF,U+0131,U+0152-0153,U+2013-2014,'
         'U+2018-201E,U+2022,U+2026,U+2039-203A,U+00B7,U+2009,U+2192')
GREEK = 'U+0370-03FF,U+1F00-1FFF,U+0300-036F'
CYRILLIC = 'U+0400-045F,U+0490-0491,U+2116'
FONTS = [
    # (source, output, ranges, pinned axes or None)
    ('AdwaitaSans-Regular.ttf', 'sans-latin', LATIN, None),
    ('AdwaitaSans-Regular.ttf', 'sans-cyrillic', CYRILLIC, None),
    ('Newsreader[opsz,wght].ttf', 'prose', LATIN, None),
    # Italic sets only transliterations, which are plain Latin letters.
    ('Newsreader-Italic[opsz,wght].ttf', 'prose-italic', 'U+0020-007E',
     {'opsz': 18, 'wght': 400}),
    ('NotoSerif[wdth,wght].ttf', 'scripture-latin', LATIN + ',' + GREEK,
     {'wdth': 100, 'wght': 400}),
    ('NotoSerif[wdth,wght].ttf', 'scripture-cyrillic', CYRILLIC,
     {'wdth': 100, 'wght': 400}),
    ('NotoSerif[wdth,wght].ttf', 'scripture-medium-latin', LATIN,
     {'wdth': 100, 'wght': 600}),
    ('NotoSerif[wdth,wght].ttf', 'scripture-medium-cyrillic', CYRILLIC,
     {'wdth': 100, 'wght': 600}),
    # The wordmark's seven letters: the S is the icon's own initial.
    ('EBGaramond[wght].ttf', 'wordmark', 'U+0061,U+0063,U+0069,U+0070,U+0072,U+0074,U+0075',
     {'wght': 500}),
    # The margins' alphabet: the twenty-two letters, no final forms.
    ('NotoSerifHebrew[wdth,wght].ttf', 'hebrew', ','.join(
        'U+%04X' % c for c in range(0x05D0, 0x05EB)
        if c not in (0x05DA, 0x05DD, 0x05DF, 0x05E3, 0x05E5)),
     {'wdth': 100, 'wght': 400}),
]


def build_assets():
    from fontTools import subset
    from fontTools.ttLib import TTFont
    from fontTools.varLib import instancer
    out = os.path.join(DOCS, 'assets', 'fonts')
    os.makedirs(out, exist_ok=True)
    for src, name, ranges, pin in FONTS:
        font = TTFont(os.path.join(ROOT, 'data', 'fonts', src), lazy=False)
        if pin:
            font = instancer.instantiateVariableFont(font, pin)
        opts = subset.Options()
        opts.flavor = 'woff2'
        opts.layout_features = ['*']
        # Keep every name record: the OFL asks that the copyright and the
        # licence travel with the font, and they live in records 0, 13, 14.
        opts.name_IDs = ['*']
        opts.name_languages = ['*']
        sub = subset.Subsetter(opts)
        sub.populate(unicodes=subset.parse_unicodes(ranges))
        sub.subset(font)
        subset.save_font(font, os.path.join(out, name + '.woff2'), opts)
    # The icon is a PNG inside the app's SVG; cut the sizes a browser asks for.
    import base64
    import io
    from PIL import Image
    svg = open(os.path.join(ROOT, 'data', 'icons', 'hicolor', 'scalable', 'apps',
                            'io.github.andresmessina_SDG.Scriptura.svg')).read()
    png = base64.b64decode(re.search(r'base64,([^"]+)', svg).group(1))
    icon = Image.open(io.BytesIO(png)).convert('RGBA')
    for size in (32, 64, 180):
        icon.resize((size, size), Image.LANCZOS).save(
            os.path.join(DOCS, 'assets', f'icon-{size}.png'), optimize=True)
    # Browsers ask for /favicon.ico whatever the page names.
    icon.resize((32, 32), Image.LANCZOS).save(
        os.path.join(DOCS, 'favicon.ico'), sizes=[(16, 16), (32, 32)])
    # One notice for the folder: each face's own copyright line, then the
    # licence they share.
    notices = []
    for src in sorted({f[0] for f in FONTS}):
        name = TTFont(os.path.join(ROOT, 'data', 'fonts', src))['name']
        notices.append(f'{src}: {name.getDebugName(0)}')
    with open(os.path.join(ROOT, 'data', 'fonts', 'AdwaitaSans-OFL.txt'),
              encoding='utf-8') as fh:
        licence = fh.read()
    licence = licence[licence.index('This Font Software is licensed'):]
    with open(os.path.join(out, 'LICENSE.txt'), 'w', encoding='utf-8') as fh:
        fh.write('The fonts in this folder are subsets of these faces, each\n'
                 'under the SIL Open Font License 1.1:\n\n'
                 + '\n'.join(notices) + '\n\n' + licence)
    stale = os.path.join(out, 'OFL.txt')
    if os.path.exists(stale):
        os.remove(stale)


# ── the pages ─────────────────────────────────────────────────────────────
_LOCALE = None


def _catalogues():
    """po/ compiled into a scratch folder, once per run.

    The library cards are translated by the app's own catalogues. A source
    checkout's locale/ is whatever `tools/build-locale.py` last wrote, and
    may be behind po/; the site is built from po/ as it stands."""
    global _LOCALE
    if _LOCALE is None:
        import atexit
        import subprocess
        import tempfile
        _LOCALE = tempfile.mkdtemp(prefix='scriptura-site-locale-')
        atexit.register(shutil.rmtree, _LOCALE, True)
        for code in LANGS[1:]:
            d = os.path.join(_LOCALE, code, 'LC_MESSAGES')
            os.makedirs(d)
            subprocess.run(['msgfmt', '-o', os.path.join(d, 'scriptura.mo'),
                            os.path.join(ROOT, 'po', f'{code}.po')], check=True)
    return _LOCALE


class _InLanguage:
    """The app's catalogues answering in `lang` for the length of a block.

    The library cards, the release notes and the dates are all the app's own
    words, translated by its own catalogues, compiled fresh from po/."""

    def __init__(self, lang):
        self.lang = lang

    def __enter__(self):
        sys.path.insert(0, ROOT)
        import i18n
        self.i18n = i18n
        self.before = os.environ.get('LANGUAGE')
        self.saved = i18n.localedir
        locale = _catalogues()
        i18n.localedir = lambda: locale
        i18n.install_language(self.lang)
        return i18n

    def __exit__(self, *_exc):
        # Put the caller's language back: a test run shares this process.
        self.i18n.localedir = self.saved
        self.i18n.install_language(self.before)


def _bundles(lang):
    """The welcome screen's starting libraries, in `lang`, from the app."""
    with _InLanguage(lang) as i18n:
        import welcome
        return [{'title': i18n._(b['title']), 'summary': b['summary'],
                 'mb': b['mb'], 'recommended': b['recommended']}
                for b in welcome.bundles_for(lang)]


def _releases(lang):
    """The store listing's release notes, newest first, in `lang` where the
    catalogue has them. Each release says whether it was translated."""
    import datetime
    import glob
    import xml.etree.ElementTree as ET
    path = glob.glob(os.path.join(ROOT, 'data', '*.metainfo.xml.in'))[0]
    out = []
    with _InLanguage(lang) as i18n:
        for rel in ET.parse(path).getroot().iter('release'):
            desc = rel.find('description')
            if desc is None:
                continue
            texts = []
            for el in desc:
                if el.tag == 'p':
                    texts.append(' '.join((el.text or '').split()))
                elif el.tag == 'ul':
                    texts += [' '.join((li.text or '').split())
                              for li in el.findall('li')]
            # Each line carries whether the catalogue had it, so a release
            # translated only in part marks its English lines as English.
            said = [(i18n._(t), lang == 'en' or i18n._(t) != t) for t in texts]
            lead = desc[0].tag == 'p'
            out.append({
                'version': rel.get('version'),
                'date': i18n.format_date(datetime.date.fromisoformat(rel.get('date'))),
                'iso': rel.get('date'),
                'summary': said[0] if lead else ('', True),
                'items': said[1:] if lead else said,
                'translated': any(ok for _t, ok in said),
            })
    return out


def _template(name):
    """A page template with its `{{> part}}` includes filled in."""
    with open(os.path.join(SITE, name), encoding='utf-8') as fh:
        text = fh.read()

    def include(m):
        with open(os.path.join(SITE, 'parts', m.group(1) + '.html'),
                  encoding='utf-8') as fh:
            return fh.read().rstrip('\n')
    return re.sub(r'\{\{> ([a-z_]+)\}\}', include, text)


def _fill(template, values):
    def sub(m):
        key = m.group(1)
        if key not in values:
            raise KeyError(f'no value for {{{{{key}}}}}')
        return str(values[key])
    return re.sub(r'\{\{([a-z0-9_.]+)\}\}', sub, template)


# Each page, and the folder it is served from beneath a language's own.
PAGES = {'home': ('page.html', ''), 'news': ('news.html', 'whats-new/')}
NAMES = (('en', 'English'), ('es', 'Español'), ('ru', 'Русский'))


def _prefix(code):
    return '' if code == 'en' else code + '/'


def _common(lang, s, root, page_path, version):
    """The values every page shares: head, header, colophon, scripts."""
    esc = html.escape
    values = {f't.{k}': (v if k.endswith('_html') else esc(v))
              for k, v in s.items() if isinstance(v, str)}
    home = root + _prefix(lang)
    here = BASE_URL + _prefix(lang) + page_path
    values.update({
        'lang': lang, 'root': root, 'version': version, 'robots': '',
        'home': home or './', 'home_install': (home or './') + '#install',
        'news_href': home + PAGES['news'][1],
        'news_current': ' aria-current="page"' if page_path == PAGES['news'][1] else '',
        'version_anchor': 'v' + version.replace('.', '-'),
        'canonical': here,
        'og_image': BASE_URL + f'assets/img/{lang}/reading.jpg',
        # The faces above the fold, fetched before the stylesheet asks.
        # (Russian prose is set in the sans; its name is still Latin.)
        'font_sans': 'sans-latin',
        'font_lede': 'sans-cyrillic' if lang == 'ru' else 'prose',
        'page_title': esc(s['title']), 'page_description': esc(s['description']),
    })
    values['alternates'] = '\n'.join(
        f'<link rel="alternate" hreflang="{code}" href="{BASE_URL}{_prefix(code)}{page_path}">'
        for code in LANGS) + \
        f'\n<link rel="alternate" hreflang="x-default" href="{BASE_URL}{page_path}">'
    current = ' aria-current="page"'
    values['lang_name'] = dict(NAMES)[lang]
    values['lang_menu'] = '\n'.join(
        f'<a lang="{code}" hreflang="{code}" '
        f'href="{(root + _prefix(code) + page_path) or "./"}"'
        f'{current if code == lang else ""}>{name}'
        '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="m3.5 8.5 3 3 6-7"/></svg></a>'
        for code, name in NAMES)
    values['credits'] = '\n'.join(f'<li>{c}</li>' for c in s['credits_html'])
    values['t.hero_meta'] = esc(s['hero_meta'].format(version=version))
    return values


def _strings(lang):
    with open(os.path.join(SITE, 'strings', f'{lang}.toml'), 'rb') as fh:
        return tomllib.load(fh)


def _payload(values, text, js, **extra):
    values['data_json'] = json.dumps(dict({'text': text, 'strings': js}, **extra),
                                     ensure_ascii=False,
                                     separators=(',', ':')).replace('</', '<\\/')


def render(lang, page='home'):
    sys.path.insert(0, ROOT)
    from _version import __version__ as version
    s = _strings(lang)
    template_name, page_path = PAGES[page]
    depth = (lang != 'en') + (page_path != '')
    root = '../' * depth
    values = _common(lang, s, root, page_path, version)
    esc = html.escape
    js = dict(s['js'], papers=s['papers'], copy=s['copy'])
    if page == 'news':
        values['page_title'] = esc(s['news_title'])
        values['page_description'] = esc(s['news_description'])
        releases = _releases(lang)
        note = s['news_english_note'] if not all(r['translated'] for r in releases) else ''
        values['news_note'] = f'    <p class="note">{esc(note)}</p>' if note else ''

        def english(ok, whole):
            # Mark a line English where the rest of its release is not.
            return '' if ok or not whole['translated'] else ' lang="en"'

        def release(r):
            lang_attr = '' if r['translated'] else ' lang="en"'
            items = ''.join(f'<li{english(ok, r)}>{esc(i)}</li>' for i, ok in r['items'])
            items = f'<ul class="rel-list">{items}</ul>' if items else ''
            text, ok = r['summary']
            summary = (f'<p class="rel-sum"{english(ok, r)}>{esc(text)}</p>'
                       if text else '')
            return (f'<li class="release" id="v{r["version"].replace(".", "-")}"{lang_attr}>'
                    f'<div class="rel-head"><h2>{esc(s["release_heading"].format(version=r["version"]))}</h2>'
                    f'<time datetime="{r["iso"]}">{esc(r["date"])}</time></div>'
                    f'{summary}{items}</li>')
        values['releases'] = '\n'.join(release(r) for r in releases)
        _payload(values, None, js)
        return _fill(_template(template_name), values)

    with open(os.path.join(SITE, 'data', f'{lang}.json'), encoding='utf-8') as fh:
        data = json.load(fh)
    values['rows'] = '\n'.join(
        f'<div class="row"><h3>{esc(r["title"])}</h3><p>{esc(r["text"])}</p></div>'
        for r in s['rows'])

    def band(sh):
        """A feature at a size you can read: the picture follows the paper
        (a dark one on a dark paper), and a click opens it full size."""
        src = f'{root}assets/img/{lang}/{sh["img"]}'
        return (
            f'<article class="band"><button type="button" class="zoom" '
            f'aria-label="{esc(s["zoom_label"])}: {esc(sh["title"])}">'
            f'<picture><source media="(prefers-color-scheme: dark)" '
            f'srcset="{src}-dark.webp"><img class="shot" src="{src}.webp" '
            f'width="1366" height="733" alt="{esc(sh["alt"])}" loading="lazy">'
            f'</picture></button><div class="band-text"><h3>{esc(sh["title"])}</h3>'
            f'<p>{esc(sh["text"])}</p></div></article>')
    values['bands'] = '\n'.join(band(sh) for sh in s['shots'])
    values['teach_band'] = band(s['teach_shot'])
    values['teach_rows'] = '\n'.join(
        f'<div class="row"><h3>{esc(r["title"])}</h3><p>{esc(r["text"])}</p></div>'
        for r in s['teach_rows'])
    values['claims'] = '\n'.join(
        f'<div><h3>{esc(c["title"])}</h3><p>{esc(c["text"])}</p></div>'
        for c in s['claims'])
    values['bundles'] = '\n'.join(
        f'<div class="bundle{" rec" if b["recommended"] else ""}"><b>{esc(b["title"])}</b>'
        f'<span>{esc(b["summary"])}</span><em>'
        + (esc(s['recommended']) + ' · ' if b['recommended'] else '')
        + esc(s['about_mb'].format(n=b['mb'])) + '</em></div>'
        for b in _bundles(lang))
    _payload(values, data, js)
    return _fill(_template(template_name), values)


def render_404():
    """One page for every missing address. GitHub Pages serves it at any
    depth, so its links are absolute; it is written in English and turns to
    Spanish or Russian in the browser, by the address or the reader's
    language."""
    sys.path.insert(0, ROOT)
    from _version import __version__ as version
    s = _strings('en')
    root = '/scriptura/'
    values = _common('en', s, root, '', version)
    nf = s['notfound']
    values.update({f'nf.{k}': html.escape(v) for k, v in nf.items()})
    values['nf.verse_initial'] = html.escape(nf['verse'][0])
    values['nf.verse_rest'] = html.escape(nf['verse'][1:])
    values['page_title'] = html.escape(nf['title'])
    values['robots'] = '<meta name="robots" content="noindex">'
    notfound = {}
    for lang in LANGS:
        t = _strings(lang)
        notfound[lang] = dict(t['notfound'], root=root + _prefix(lang))
    _payload(values, None, dict(s['js'], papers=s['papers'], copy=s['copy']),
             notfound=notfound)
    return _fill(_template('404.html'), values)


def build_pages(out=DOCS):
    for lang in LANGS:
        for page, (_name, page_path) in PAGES.items():
            path = os.path.join(out, _prefix(lang), page_path, 'index.html')
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, 'w', encoding='utf-8') as fh:
                fh.write(render(lang, page))
    with open(os.path.join(out, '404.html'), 'w', encoding='utf-8') as fh:
        fh.write(render_404())
    os.makedirs(os.path.join(out, 'assets'), exist_ok=True)
    for f in ('site.css', 'site.js', 'initial-s.svg'):
        shutil.copy(os.path.join(SITE, f), os.path.join(out, 'assets', f))
    with open(os.path.join(out, '.nojekyll'), 'w'):
        pass


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--data', metavar='SWORD_DIR',
                    help='re-read the passages from this SWORD library')
    ap.add_argument('--ebible', default=os.path.expanduser(
        '~/.local/share/bible-reader/ebible.db'),
        help='the eBible store holding spabes and russyn')
    ap.add_argument('--open-data', default=os.path.expanduser(
        '~/.local/share/bible-reader/open_data'),
        help='the folder holding cross_references.txt and dodson.csv')
    ap.add_argument('--catena', default=os.path.expanduser(
        '~/.local/share/bible-reader/catena.db'),
        help='the Voices of the Church pack')
    ap.add_argument('--assets', action='store_true',
                    help='re-cut the fonts and icons')
    args = ap.parse_args()
    if args.data:
        build_data(os.path.abspath(args.data), args.ebible,
                   args.open_data, args.catena)
    if args.assets:
        build_assets()
    build_pages()
    print('docs/ written')


if __name__ == '__main__':
    main()
