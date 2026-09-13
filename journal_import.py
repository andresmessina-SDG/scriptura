"""Reading a Markdown file as a journal entry.

Export has always gone out; nothing came in. A reader arriving with years of
writing — a folder of dated files, an export from another app, or Scriptura's
own `journal.md` from a machine they no longer have — could not bring it.

**What this takes is deliberately small.** One file is one entry. The body is
the file, near enough: whatever notation it carries is the same Markdown the
editor already renders, so an imported entry looks like a written one. The
only things guessed are the title and the date, and both are guessed from
what a file already tells you rather than from its contents:

* a `---` front-matter block, if the file has one (`title`, `date`, `tags`),
  because several journalling tools write one and it costs twenty lines to
  read;
* failing that, an opening `# heading` is the title — it is what the editor's
  own export writes, so a Scriptura export read back keeps its titles;
* failing that, the file's name, cleaned up;
* the date is the front matter's, or an ISO date at the head of the file
  name (`2026-09-11-on-genesis.md`), or the file's own modification time.

**No anchors are guessed.** The references in a body could be read and turned
into anchors, and that would file every imported entry into the canon
automatically — which is exactly the kind of thing §6.9 refuses: an entry
must not claim a passage its writer did not give it. Since anchors can now be
added to an existing entry in the editor, an import that gets this wrong
would be a mess to undo, and an import that leaves it alone costs one click
per entry the reader actually wants filed.

Pure: text in, dicts out. The window does the file reading and the writing.
"""

from __future__ import annotations

import os
import re
from datetime import date, datetime
from typing import Any

#: A front-matter block, if the file opens with one. Not YAML — a `key: value`
#: line reader, which is all any of these files use, and pulling in a YAML
#: parser to read four keys would be the tail wagging the dog.
_FRONT = re.compile(r'\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)',
                    re.DOTALL)

#: `title: A day in Romans` — the key, then everything after the colon.
_FIELD = re.compile(r'^([A-Za-z][A-Za-z_-]*)[ \t]*:[ \t]*(.*)$')

#: An opening heading, which is what our own export writes for each entry.
_HEADING = re.compile(r'\A#{1,3}[ \t]+(.+?)[ \t]*(?:\r?\n|\Z)')

#: A date leading a file name: 2026-09-11-on-genesis.md, 2026_09_11 note.txt
_NAMED_DATE = re.compile(r'\A(\d{4})[-_.](\d{2})[-_.](\d{2})')

#: What a file name loses on its way to being a title.
_NAME_JUNK = re.compile(r'[_-]+')


def _front_matter(text: str) -> tuple[dict[str, str], str]:
    """Split a leading `---` block off `text`. ({}, text) if there is none."""
    match = _FRONT.match(text)
    if not match:
        return {}, text
    fields = {}
    for line in match.group(1).splitlines():
        field = _FIELD.match(line.strip())
        if field:
            fields[field.group(1).lower()] = field.group(2).strip()
    return fields, text[match.end():]


def _as_date(value: str) -> str:
    """An ISO date from `value`, or '' if it is not one.

    Only ISO: a file saying 09/11/2026 means one day in the United States and
    another everywhere else, and an import that silently picks is worse than
    one that falls back to a date it can defend.
    """
    try:
        return date.fromisoformat(value.strip()[:10]).isoformat()
    except ValueError:
        return ''


def _title_from_name(name: str) -> str:
    stem = os.path.splitext(os.path.basename(name))[0]
    stem = _NAMED_DATE.sub('', stem)
    stem = _NAME_JUNK.sub(' ', stem).strip()
    return stem


def _tags(value: str) -> list[str]:
    return [t.strip().lstrip('#') for t in value.replace(';', ',').split(',')
            if t.strip().lstrip('#')]


def read(text: str, name: str, modified: float | None = None
         ) -> dict[str, Any] | None:
    """One file as one entry, or None when there is nothing in it.

    `name` is the file's name (used for the title and the date of last
    resort) and `modified` its mtime, as `os.stat` reports it.
    """
    fields, body = _front_matter(text)

    title = fields.get('title', '').strip()
    if not title:
        heading = _HEADING.match(body)
        if heading:
            title = heading.group(1).strip()
            # Taken as the title, so it does not stay as a heading too — an
            # entry whose body opens by repeating its own title is what our
            # own export would otherwise round-trip into.
            body = body[heading.end():]
    if not title:
        title = _title_from_name(name)

    body = body.strip('\n')
    if not title and not body.strip():
        return None

    when = _as_date(fields.get('date', ''))
    if not when:
        named = _NAMED_DATE.match(os.path.basename(name))
        if named:
            when = _as_date('-'.join(named.groups()))
    if not when and modified is not None:
        when = datetime.fromtimestamp(modified).date().isoformat()
    if not when:
        when = date.today().isoformat()

    return {'title': title, 'body': body, 'date': when,
            'tags': _tags(fields.get('tags', ''))}
