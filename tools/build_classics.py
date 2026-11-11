#!/usr/bin/env python3
"""Build a Common Weal Press classic as a SWORD general-book module.

Source: the press's signed EPUB of one book, from a release of
https://github.com/freely-given-books/books (every edition CC0). The
release's catalog.json names each book's signed version and the SHA-256 of
every file; a book not signed off, or a file that does not match, is
refused. A book in volumes has one EPUB per volume and becomes one module
with a part per volume. Each module is written as a zip, with its conf
beside it in DIR/mods.d for the module list.

The EPUB, not the press's TEI, because the EPUB is the edition: the TEI
keeps every word of the old printing, and what this edition leaves out
(an editor's preface, a printer's marginal heading, italics set roman) is
decided by rules the press applies in its own build. Reading the EPUB
takes the result.

The tree is the EPUB's table of contents: each file it lists is an entry,
under the entry that lists it. The cover and the press's colophon are
left out. Footnotes are numbered as the EPUB numbers them and listed under
a rule at the end of their entry.

Scripture references become <reference osisRef="Bible:…">. The press sets
every reference in one modern style ("Heb 12:5", "1 Cor 9:27; 13:12",
"Isa 57:16–18"), so they are found by that style, and each is kept only if
its verse is in the KJV. A bare chapter ("Ps 88") is linked only after a
book abbreviation that is not also a name ("John 3" in a sentence about
the apostle is left alone).

Usage:  gh release download TAG -R freely-given-books/books \\
            -p catalog.json -p '*.epub' -D RELEASE
        python3 tools/build_classics.py --release RELEASE --out DIR
Needs imp2gbs (sword-utils) and the SWORD Python binding; run it in
tools/in-fedora44.sh on a host without them.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import os
import posixpath
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile

X = '{http://www.w3.org/1999/xhtml}'
EPUB_TYPE = '{http://www.idpf.org/2007/ops}type'
OPF = '{http://www.idpf.org/2007/opf}'
DC = '{http://purl.org/dc/elements/1.1/}'

# ── Scripture references ────────────────────────────────────────────────────

# The press's abbreviations (counted across every signed EPUB) and the
# full names it sometimes leaves, each to its OSIS book.
_ABBR = {
    'Gen': 'Gen', 'Exod': 'Exod', 'Lev': 'Lev', 'Num': 'Num', 'Deut': 'Deut',
    'Josh': 'Josh', 'Judg': 'Judg', 'Ruth': 'Ruth', '1 Sam': '1Sam',
    '2 Sam': '2Sam', '1 Kgs': '1Kgs', '2 Kgs': '2Kgs', '1 Chr': '1Chr',
    '2 Chr': '2Chr', 'Ezra': 'Ezra', 'Neh': 'Neh', 'Esth': 'Esth', 'Job': 'Job',
    'Ps': 'Ps', 'Prov': 'Prov', 'Eccl': 'Eccl', 'Song': 'Song', 'Isa': 'Isa',
    'Jer': 'Jer', 'Lam': 'Lam', 'Ezek': 'Ezek', 'Dan': 'Dan', 'Hos': 'Hos',
    'Joel': 'Joel', 'Amos': 'Amos', 'Obad': 'Obad', 'Jonah': 'Jonah',
    'Mic': 'Mic', 'Nah': 'Nah', 'Hab': 'Hab', 'Zeph': 'Zeph', 'Hag': 'Hag',
    'Zech': 'Zech', 'Mal': 'Mal', 'Matt': 'Matt', 'Mark': 'Mark',
    'Luke': 'Luke', 'John': 'John', 'Acts': 'Acts', 'Rom': 'Rom',
    '1 Cor': '1Cor', '2 Cor': '2Cor', 'Gal': 'Gal', 'Eph': 'Eph',
    'Phil': 'Phil', 'Col': 'Col', '1 Thess': '1Thess', '2 Thess': '2Thess',
    '1 Tim': '1Tim', '2 Tim': '2Tim', 'Titus': 'Titus', 'Phlm': 'Phlm',
    'Heb': 'Heb', 'Jas': 'Jas', '1 Pet': '1Pet', '2 Pet': '2Pet',
    '1 John': '1John', '2 John': '2John', '3 John': '3John', 'Jude': 'Jude',
    'Rev': 'Rev',
    'Genesis': 'Gen', 'Exodus': 'Exod', 'Leviticus': 'Lev', 'Numbers': 'Num',
    'Deuteronomy': 'Deut', 'Joshua': 'Josh', 'Judges': 'Judg',
    '1 Samuel': '1Sam', '2 Samuel': '2Sam', '1 Kings': '1Kgs',
    '2 Kings': '2Kgs', '1 Chronicles': '1Chr', '2 Chronicles': '2Chr',
    'Nehemiah': 'Neh', 'Esther': 'Esth', 'Psalm': 'Ps', 'Psalms': 'Ps',
    'Proverbs': 'Prov', 'Ecclesiastes': 'Eccl', 'Isaiah': 'Isa',
    'Jeremiah': 'Jer', 'Lamentations': 'Lam', 'Ezekiel': 'Ezek',
    'Daniel': 'Dan', 'Hosea': 'Hos', 'Obadiah': 'Obad', 'Micah': 'Mic',
    'Nahum': 'Nah', 'Habakkuk': 'Hab', 'Zephaniah': 'Zeph', 'Haggai': 'Hag',
    'Zechariah': 'Zech', 'Malachi': 'Mal', 'Matthew': 'Matt',
    'Romans': 'Rom', '1 Corinthians': '1Cor', '2 Corinthians': '2Cor',
    'Galatians': 'Gal', 'Ephesians': 'Eph', 'Philippians': 'Phil',
    'Colossians': 'Col', '1 Thessalonians': '1Thess',
    '2 Thessalonians': '2Thess', '1 Timothy': '1Tim', '2 Timothy': '2Tim',
    'Philemon': 'Phlm', 'Hebrews': 'Heb', 'James': 'Jas', '1 Peter': '1Pet',
    '2 Peter': '2Pet', 'Revelation': 'Rev',
}
# A bare chapter after one of these is a word in a sentence as often as a
# reference ("Job 3 times", "James 2 sons"): it needs chapter and verse.
_NEEDS_VERSE = {'Ruth', 'Job', 'Ezra', 'Joel', 'Amos', 'Jonah', 'Mark',
                'Luke', 'John', 'Jude', 'Titus', 'Song', 'Daniel',
                'Esther', 'Micah', 'Hosea', 'James', 'Numbers', 'Judges',
                'Psalm', 'Psalms'}

_SP = '[ \u00a0]'
_N = r'\d{1,3}'
# A verse list: 13 · 13–14 · 17, 18 · 1, 4–6. A number after a comma is a
# verse unless a book name follows it ("Gen 3:15, 1 Cor 10:4").
_VLIST = (rf'{_N}(?:[–-]{_N})?'
          rf'(?:,{_SP}?{_N}(?:[–-]{_N})?(?!{_SP}?[A-Z]|:|\d))*')
_BOOK = '|'.join(sorted((re.escape(b).replace(r'\ ', _SP) for b in _ABBR),
                        key=len, reverse=True))
# Not before a digit or a letter; a colon may follow ("Rom 8:13: …").
_END = r'(?![\d\w]|:\d)'
_REF_RE = re.compile(rf'(?<![\w])({_BOOK})\.?{_SP}({_N})(?::({_VLIST})(?:ff)?)?{_END}')
_MORE_RE = re.compile(rf';{_SP}({_N}):({_VLIST}){_END}')
# The old style the press keeps in some notes: "Isa. liii. 12".
_ROMAN_RE = re.compile(
    rf'(?<![\w])({_BOOK})\.?{_SP}([ivxlc]+)\.{_SP}({_VLIST}){_END}')
# A reference into the book and chapter last named in the paragraph:
# "verse 4", "verses 17, 18", "ch. 3:16".
_VERSE_RE = re.compile(rf'(?<![\w])(?:verses?|ver\.|vv?\.){_SP}({_VLIST}){_END}')
_CHAPTER_RE = re.compile(
    rf'(?<![\w])(?:ch\.|chap\.|chapter){_SP}({_N}):({_VLIST}){_END}')
_PATTERNS = (('full', _REF_RE), ('roman', _ROMAN_RE), ('verse', _VERSE_RE),
             ('chapter', _CHAPTER_RE))
_ONE_CHAPTER = {'Obad', 'Phlm', '2John', '3John', 'Jude'}


def _from_roman(s: str) -> int:
    vals = {'i': 1, 'v': 5, 'x': 10, 'l': 50, 'c': 100}
    total = 0
    for a, b in zip(s, s[1:] + ' '):
        v = vals[a]
        total += -v if b != ' ' and vals[b] > v else v
    return total

_CANON = None


def verse_exists(book: str, chapter: int, verse: int) -> bool:
    global _CANON
    if _CANON is None:
        import Sword
        _CANON = Sword.VerseKey()
    _CANON.setText(f'{book} {chapter}:{verse}')
    return (str(_CANON.getOSISBookName()) == book
            and _CANON.getChapter() == chapter and _CANON.getVerse() == verse)


def _osis(book: str, chapter: str, vlist: str | None) -> str | None:
    """The OSIS target of one reference: its first verse, or its first run
    ("Isa.57.16-Isa.57.18"). None when the verse is not in the KJV."""
    c = int(chapter)
    if not vlist:
        return f'{book}.{c}.1' if verse_exists(book, c, 1) else None
    m = re.match(r'(\d+)(?:[–-](\d+))?', vlist)
    a = int(m.group(1)) if m else 0
    if not verse_exists(book, c, a):
        return None
    b = int(m.group(2)) if m and m.group(2) else 0
    if b > a and verse_exists(book, c, b):
        return f'{book}.{c}.{a}-{book}.{c}.{b}'
    return f'{book}.{c}.{a}'


class Refs:
    """Finds references in plain text and counts what it found."""

    def __init__(self) -> None:
        self.linked = 0
        self.kinds: dict[str, list[str]] = {}
        self.refused: list[str] = []
        self.context: tuple[str, str] | None = None

    def reset(self) -> None:
        """A new paragraph: "verse 4" no longer means the last book's."""
        self.context = None

    def _target(self, kind: str, m: re.Match[str]) -> tuple[str | None, str]:
        """The OSIS target of one match and the book it sets as context."""
        if kind == 'full':
            name = re.sub(_SP, ' ', m.group(1))
            book = _ABBR[name]
            chapter, vlist = m.group(2), m.group(3)
            if book in _ONE_CHAPTER and (not vlist or chapter != '1'):
                # "Jude 4": the one chapter's verse 4.
                chapter, vlist = '1', m.group(2)
            elif not vlist and name in _NEEDS_VERSE:
                return None, ''
            return _osis(book, chapter, vlist), book
        if kind == 'roman':
            book = _ABBR[re.sub(_SP, ' ', m.group(1))]
            return _osis(book, str(_from_roman(m.group(2))), m.group(3)), book
        if self.context is None:
            return None, ''
        book, chapter = self.context
        if kind == 'chapter':
            return _osis(book, m.group(1), m.group(2)), book
        return _osis(book, chapter, m.group(1)), book      # 'verse'

    def link(self, text: str) -> str:
        """Escaped text with each reference wrapped. `text` is raw."""
        found = sorted(((m.start(), kind, m) for kind, rx in _PATTERNS
                        for m in rx.finditer(text)), key=lambda x: x[0])
        out, pos = [], 0
        for start, kind, m in found:
            if start < pos:
                continue
            target, book = self._target(kind, m)
            if target is None:
                if book:
                    self.refused.append(m.group(0))
                continue
            out.append(_esc(text[pos:start]))
            out.append(self._wrap(target, m.group(0)))
            self.kinds.setdefault(kind, []).append(target)
            pos = m.end()
            self.context = (book, target.split('.')[1])
            # "Ezek 11:19; 36:26": a chapter after a semicolon is the same
            # book's.
            while (more := _MORE_RE.match(text, pos)) is not None:
                t = _osis(book, more.group(1), more.group(2))
                if t is None:
                    break
                out.append(_esc('; '))
                out.append(self._wrap(t, more.group(0)[2:]))
                pos = more.end()
                self.context = (book, more.group(1))
        out.append(_esc(text[pos:]))
        return ''.join(out)

    def _wrap(self, target: str, shown: str) -> str:
        self.linked += 1
        return f'<reference osisRef="Bible:{target}">{_esc(shown)}</reference>'


# ── EPUB to OSIS ────────────────────────────────────────────────────────────

def _esc(s: str) -> str:
    return html.escape(s, quote=False)


_RUN = re.compile(r'(<reference [^>]*>.*?</reference>|<hi [^>]*>.*?</hi>)')


def _wrap(kind: str, body: str) -> str:
    """`<hi>` around `body`, closed before each reference or inner `<hi>`
    and opened after it. The reader inserts a reference as its own link,
    and its patterns for `<hi>` do not nest, so emphasis that spanned
    either would be cut open and lost. The inner run keeps its own style
    (small caps inside an italic summary stay small caps)."""
    return ''.join(part if _RUN.fullmatch(part) else
                   (f'<hi type="{kind}">{part}</hi>' if part.strip() else part)
                   for part in _RUN.split(body))


def _classes(e: ET.Element) -> set[str]:
    return set((e.get('class') or '').split())


def _text(e: ET.Element) -> str:
    return ' '.join(''.join(e.itertext()).split())


class Entry:
    """One EPUB file → the OSIS body of one tree entry."""

    def __init__(self, refs: Refs, notes: dict[str, ET.Element]) -> None:
        self.refs = refs
        self.note_bodies = notes
        self.notes: list[tuple[str, str]] = []
        self.heading_seen = False

    # Inline ------------------------------------------------------------

    def inline(self, e: ET.Element) -> str:
        out = [self.refs.link(e.text or '')]
        for c in e:
            out.append(self.element(c))
            out.append(self.refs.link(c.tail or ''))
        return ''.join(out)

    def element(self, e: ET.Element) -> str:
        tag = e.tag.replace(X, '')
        cls = _classes(e)
        if tag == 'a' and 'noteref' in cls:
            n = _text(e)
            target = (e.get('href') or '').lstrip('#')
            aside = self.note_bodies.get(target)
            if aside is not None:
                self.notes.append((n, self.note(aside)))
            return f'<hi type="super" n="note">{_esc(n)}</hi>'
        if tag in ('p', 'div', 'blockquote'):
            # A paragraph the EPUB nests inside another (Sinners): a break,
            # since an OSIS <p> cannot hold one.
            return '<br/><br/>' + self.inline(e)
        if tag in ('em', 'i', 'cite'):
            return _wrap('italic', self.inline(e))
        if tag in ('strong', 'b'):
            return _wrap('bold', self.inline(e))
        if tag == 'span' and 'smallcaps' in cls:
            return _wrap('small-caps', self.inline(e))
        if tag == 'sup':
            return f'<hi type="super">{self.inline(e)}</hi>'
        if tag == 'br':
            return '<br/>'
        if tag == 'img':
            return ''
        return self.inline(e)

    def note(self, aside: ET.Element) -> str:
        saved, self.refs.context = self.refs.context, None
        parts = []
        for p in aside:
            # The backlink ("8.") opens the note; the number is shown
            # beside it already.
            for a in p.iter(X + 'a'):
                if a.get('role') == 'doc-backlink':
                    a.text, a.tail = '', (a.tail or '').lstrip()
            parts.append(self.inline(p).strip())
        self.refs.context = saved
        return ' '.join(x for x in parts if x)

    # Blocks ------------------------------------------------------------

    def blocks(self, e: ET.Element, depth: int = 0) -> str:
        return ''.join(self.block(c, depth) for c in e)

    def block(self, e: ET.Element, depth: int = 0) -> str:
        self.refs.reset()
        tag = e.tag.replace(X, '')
        cls = _classes(e)
        if tag == 'section' and 'notes' in cls:
            return ''
        if tag in ('section', 'div', 'blockquote', 'header', 'footer',
                   'article', 'figure'):
            return self.blocks(e, depth)
        if re.fullmatch(r'h[1-6]', tag):
            if not self.heading_seen:
                # The file's own title is the entry's name in the tree.
                self.heading_seen = True
                return ''
            return f'<title>{self.inline(e).strip()}</title>'
        if tag in ('ol', 'ul'):
            return self.listing(e, depth)
        if tag == 'dl':
            out = []
            for c in e:
                t = c.tag.replace(X, '')
                body = self.inline(c).strip()
                out.append(f'<p>{_wrap("bold", body)}</p>' if t == 'dt'
                           else f'<p>{body}</p>')
            return ''.join(out)
        if tag == 'table':
            rows = []
            for tr in e.iter(X + 'tr'):
                cells = [self.inline(td).strip()
                         for td in tr if td.tag in (X + 'td', X + 'th')]
                rows.append('<p>' + ' — '.join(c for c in cells if c) + '</p>')
            return ''.join(rows)
        if tag in ('hr', 'img', 'nav', 'aside'):
            return ''
        body = self.inline(e).strip()
        return f'<p>{body}</p>' if body else ''

    def listing(self, e: ET.Element, depth: int) -> str:
        """A list as numbered paragraphs: the reader has no list layout.
        Nested lists indent with spaces the reader keeps."""
        ordered = e.tag == X + 'ol' and 'plain' not in _classes(e)
        roman = 'roman' in _classes(e)
        n = int(e.get('start') or 1)
        out = []
        for li in e:
            if li.tag != X + 'li':
                continue
            inner = [c for c in li if c.tag in (X + 'ol', X + 'ul')]
            for c in inner:
                li.remove(c)
            mark = ''
            if ordered and e.get('type') != 'none':
                mark = (_roman(n) if roman else str(n)) + '. '
            indent = '\u2003' * depth
            body = self.inline(li).strip()
            if body:
                out.append(f'<p>{indent}{mark}{body}</p>')
            for c in inner:
                out.append(self.listing(c, depth + 1))
            n += 1
        return ''.join(out)

    def finish(self, body: str) -> str:
        if not self.notes:
            return body
        notes = ''.join(f'<p><hi type="super">{_esc(n)}</hi> {t}</p>'
                        for n, t in self.notes)
        return f'{body}<div type="x-notes"><title>Notes</title>{notes}</div>'


def _roman(n: int) -> str:
    out = ''
    for v, s in ((1000, 'm'), (900, 'cm'), (500, 'd'), (400, 'cd'),
                 (100, 'c'), (90, 'xc'), (50, 'l'), (40, 'xl'), (10, 'x'),
                 (9, 'ix'), (5, 'v'), (4, 'iv'), (1, 'i')):
        while n >= v:
            out, n = out + s, n - v
    return out


class Book:
    """One EPUB: its title, its contents tree, its files."""

    def __init__(self, path: str) -> None:
        self.zip = zipfile.ZipFile(path)
        container = ET.fromstring(self.zip.read('META-INF/container.xml'))
        rootfile = next(e for e in container.iter() if e.tag.endswith('rootfile'))
        self.opf_path = rootfile.get('full-path') or ''
        self.base = posixpath.dirname(self.opf_path)
        opf = ET.fromstring(self.zip.read(self.opf_path))
        self.title = _text(opf.find(f'.//{DC}title'))
        creator = opf.find(f'.//{DC}creator')
        self.author = _text(creator) if creator is not None else ''
        nav_item = next(i for i in opf.iter(OPF + 'item')
                        if 'nav' in (i.get('properties') or '').split())
        self.nav_path = posixpath.join(self.base, nav_item.get('href') or '')

    def read(self, href: str) -> ET.Element:
        return ET.fromstring(self.zip.read(
            posixpath.normpath(posixpath.join(posixpath.dirname(self.nav_path), href))))

    def toc(self) -> list[tuple[int, str, str]]:
        """(depth, label, file) in reading order. A link into the middle
        of a file names a heading inside an entry, not an entry."""
        nav = ET.fromstring(self.zip.read(self.nav_path))
        toc = next(n for n in nav.iter(X + 'nav') if n.get(EPUB_TYPE) == 'toc')
        out: list[tuple[int, str, str]] = []

        def walk(ol: ET.Element, depth: int) -> None:
            for li in ol.findall(X + 'li'):
                a = li.find(X + 'a')
                if a is not None and '#' not in (a.get('href') or ''):
                    out.append((depth, _text(a), a.get('href') or ''))
                sub = li.find(X + 'ol')
                if sub is not None:
                    walk(sub, depth + 1)
        walk(toc.find(X + 'ol'), 0)
        return out


def _key(label: str) -> str:
    # A key is a path; a slash in a title would split it.
    return label.replace('/', '–').strip()


def convert(paths: list[str], refs: Refs) -> tuple[list[tuple[str, str]], Book]:
    books = [Book(p) for p in paths]
    entries: list[tuple[str, str]] = []
    seen: set[str] = set()
    volumes = len(books) > 1
    for v, book in enumerate(books, 1):
        stack: list[str] = [f'/Volume {v}'] if volumes else []
        if volumes:
            entries.append((stack[0], ''))
        base = len(stack)
        for depth, label, href in book.toc():
            del stack[base + depth:]
            key = _key(label)
            first = '/'.join([''] + [s.lstrip('/') for s in stack] + [key])
            path, n = first, 2
            while path in seen:
                path, n = f'{first} ({n})', n + 1
            seen.add(path)
            stack.append(path.rsplit('/', 1)[1])
            root = book.read(href)
            body = root.find(X + 'body')
            notes = {a.get('id') or '': a for a in body.iter(X + 'aside')}
            entry = Entry(refs, notes)
            entries.append((path, entry.finish(entry.blocks(body))))
    return entries, books[0]


def plain_words(osis: str) -> list[str]:
    """The words a module entry reads, without its note list and markers:
    what the build compares against the EPUB."""
    osis = osis.split('<div type="x-notes">')[0]
    osis = re.sub(r'<hi type="super" n="note">[^<]*</hi>', '', osis)
    osis = re.sub(r'<(?:p|title|br)\b[^>]*>', ' ', osis)
    return html.unescape(re.sub(r'<[^>]+>', '', osis)).split()


def epub_words(book: Book, href: str) -> list[str]:
    raw = book.zip.read(posixpath.normpath(posixpath.join(
        posixpath.dirname(book.nav_path), href))).decode('utf-8')
    raw = raw[raw.index('<body'):]
    raw = re.sub(r'<section class="notes">.*?</section>', '', raw, flags=re.S)
    raw = re.sub(r'<a class="noteref".*?</a>', '', raw, flags=re.S)
    # The file's own title is the entry's name, as in the module.
    raw = re.sub(r'<h[1-6][^>]*>.*?</h[1-6]>', '', raw, count=1, flags=re.S)
    raw = re.sub(r'</?(?:p|h[1-6]|li|dt|dd|td|th|br|div|section|blockquote)\b[^>]*>',
                 ' ', raw)
    return html.unescape(re.sub(r'<[^>]+>', '', raw)).split()


def check(paths: list[str], entries: list[tuple[str, str]]) -> list[str]:
    """Every entry's words against its EPUB file's. Two differences are
    the module's own: list numbers (the EPUB numbers lists in CSS) and the
    dash set between a table's cells."""
    problems = []
    by_path = dict(entries)
    books = [Book(p) for p in paths]
    i = 0
    for v, book in enumerate(books, 1):
        if len(books) > 1:
            i += 1
        for _depth, _label, href in book.toc():
            path = entries[i][0]
            i += 1
            got = [w for w in plain_words(by_path[path])
                   if not re.fullmatch(r'[0-9ivxlcdm]+\.|—', w)]
            want = [w for w in epub_words(book, href)
                    if not re.fullmatch(r'[0-9ivxlcdm]+\.|—', w)]
            if got != want:
                import difflib
                sm = difflib.SequenceMatcher(None, got, want, autojunk=False)
                op = next(o for o in sm.get_opcodes() if o[0] != 'equal')
                _t, a1, a2, b1, b2 = op
                problems.append(f'{path}: module {" ".join(got[a1-3 if a1 > 3 else 0:a2+3])!r}'
                                f' / epub {" ".join(want[b1-3 if b1 > 3 else 0:b2+3])!r}')
    return problems


# The press's books this app offers, by their folder in the press's
# catalogue, each with its module key. A book in the catalogue but not here
# is left out: The 1689 Baptist Confession is a module already
# (BaptistConfession1689), and Owen on Sin is two of the books below bound
# as one paperback, with no EPUB of its own.
CLASSICS = {
    'anonymous/the-anatomy-of-simon-magus': 'CWPSimonMagus',
    'charles-spurgeon/all-of-grace': 'CWPAllOfGrace',
    'john-bunyan/grace-abounding': 'CWPGraceAbounding',
    'john-bunyan/the-pilgrims-progress': 'CWPPilgrim',
    'john-owen/indwelling-sin': 'CWPIndwellingSin',
    'john-owen/of-temptation': 'CWPTemptation',
    'john-owen/the-death-of-death': 'CWPDeathOfDeath',
    'john-owen/the-mortification-of-sin': 'CWPMortification',
    'jonathan-edwards/sinners-in-the-hands-of-an-angry-god': 'CWPSinners',
    'richard-sibbes/the-glorious-feast-of-the-gospel': 'CWPGloriousFeast',
    'thomas-boston/the-crook-in-the-lot': 'CWPCrookInTheLot',
    'thomas-brooks/precious-remedies-against-satans-devices': 'CWPPreciousRemedies',
    'thomas-brooks/the-secret-key-of-heaven': 'CWPSecretKey',
    'thomas-watson/a-divine-cordial': 'CWPDivineCordial',
    'william-gouge/domestical-duties': 'CWPDomesticalDuties',
    'william-perkins/christian-economy': 'CWPChristianEconomy',
}


def _conf_value(text: str) -> str:
    return ' '.join(text.split())


def write_module(paths: list[str], module: str, out_dir: str,
                 book_info: dict) -> str:
    """Build one module into `out_dir` and zip it there; return the zip's
    path. The conf's About is the press's own summary of its edition."""
    refs = Refs()
    entries, _book = convert(paths, refs)
    problems = check(paths, entries)
    if problems:
        sys.exit(f'{module} does not read as its EPUB does:\n  '
                 + '\n  '.join(problems[:20]))
    lower = module.lower()
    rel = f'modules/genbook/rawgenbook/{lower}'
    stage = os.path.join(out_dir, 'stage', module)
    os.makedirs(os.path.join(stage, rel), exist_ok=True)
    os.makedirs(os.path.join(stage, 'mods.d'), exist_ok=True)
    imp = os.path.join(stage, f'{lower}.imp')
    with open(imp, 'w', encoding='utf-8') as f:
        for key, body in entries:
            f.write(f'$$${key}\n{body}\n')
    subprocess.run(['imp2gbs', imp, '-o', os.path.join(stage, rel, lower)],
                   check=True, stdout=subprocess.DEVNULL)
    os.remove(imp)
    data = sorted(os.listdir(os.path.join(stage, rel)))
    size = sum(os.path.getsize(os.path.join(stage, rel, n)) for n in data)
    version = book_info['version'].lstrip('v')
    about = (_conf_value(book_info['summary'])
             + f'\\par\\par Common Weal Press edition {book_info["version"]}, '
             'dedicated to the public domain (CC0 1.0): commonwealpress.org')
    conf = (f'[{module}]\n'
            f'DataPath=./{rel}/{lower}\n'
            'ModDrv=RawGenBook\nEncoding=UTF-8\nSourceType=OSIS\nLang=en\n'
            f'Description={_conf_value(book_info["title"])} '
            f'({_conf_value(book_info["author"])})\n'
            f'About={about}\n'
            'Collection=Classics\n'
            'TextSource=Common Weal Press, commonwealpress.org\n'
            'DistributionLicense=Public Domain\n'
            'ShortCopyright=Edition dedicated to the public domain (CC0) '
            'by Common Weal Press\n'
            f'Version={version}\nMinimumVersion=1.7.2\n'
            f'InstallSize={size}\n')
    with open(os.path.join(stage, 'mods.d', f'{lower}.conf'), 'w',
              encoding='utf-8') as f:
        f.write(conf)
    os.makedirs(os.path.join(out_dir, 'mods.d'), exist_ok=True)
    with open(os.path.join(out_dir, 'mods.d', f'{lower}.conf'), 'w',
              encoding='utf-8') as f:
        f.write(conf)
    path = os.path.join(out_dir, f'{module}.zip')
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        z.write(os.path.join(stage, 'mods.d', f'{lower}.conf'),
                f'mods.d/{lower}.conf')
        for n in data:
            z.write(os.path.join(stage, rel, n), f'{rel}/{n}')
    print(f'{module}: {len(entries)} entries, {refs.linked} linked '
          f'references, {len(refs.refused)} refused, {size:,} bytes')
    return path


def build_release(release: str, out_dir: str) -> None:
    """Every book of CLASSICS from a downloaded press release: the folder
    holds its catalog.json and the EPUBs it lists, each checked against
    the catalogue's SHA-256 before it is read."""
    import json
    with open(os.path.join(release, 'catalog.json'), encoding='utf-8') as f:
        catalog = json.load(f)
    books = {b['book']: b for b in catalog['books']}
    missing = sorted(set(CLASSICS) - set(books))
    if missing:
        sys.exit(f'not in this release: {missing}')
    for key, module in CLASSICS.items():
        info = books[key]
        if not (info.get('signed_off') or {}).get('signature_verified'):
            sys.exit(f'{key} {info["version"]}: not signed off')
        epubs = sorted({f['name']: f['sha256'] for f in info['files']
                        if f['name'].endswith('.epub')}.items())
        paths = []
        for name, want in epubs:
            path = os.path.join(release, name)
            with open(path, 'rb') as f:
                got = hashlib.sha256(f.read()).hexdigest()
            if got != want:
                sys.exit(f'{name}: SHA-256 {got}, the catalogue says {want}')
            paths.append(path)
        write_module(paths, module, out_dir, info)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--release', required=True,
                    help='folder with the release\'s catalog.json and EPUBs')
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    build_release(a.release, a.out)


if __name__ == '__main__':
    main()
