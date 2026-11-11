"""Keep printed book notes available as both endnotes and clickable markers."""
import html
import re

NOTE_MARKER = re.compile(r'<hi\b[^>]*n="note"[^>]*>(.*?)</hi>', re.S)
_BLOCK = re.compile(r'<div\b[^>]*type="x-notes"[^>]*>(.*?)</div>', re.S)
_ENDNOTE = re.compile(r'<p\b[^>]*>\s*<hi\b[^>]*type="super"[^>]*>(.*?)</hi>\s*(.*?)</p>', re.S)
_INLINE = re.compile(r'<note\b([^>]*?)(?<!/)>(.*?)</note>', re.S)


def prepare_notes(raw):
    notes = {}
    for block in _BLOCK.finditer(raw):
        for item in _ENDNOTE.finditer(block.group(1)):
            label = html.unescape(re.sub(r'<[^>]*>', '', item.group(1))).strip()
            if label:
                notes[label] = item.group(2)
    added = []

    def inline(match):
        body = match.group(2)
        if not body.strip():
            return match.group(0)
        if re.sub(r'<[^>]*>', '', body).strip().lower() == 'auto-modernized':
            return ''
        number = len(notes)+1
        while str(number) in notes:
            number += 1
        printed = re.search(r'\bn="([^"]+)"', match.group(1))
        label = html.unescape(printed.group(1)) if printed else str(number)
        if label in notes or not re.fullmatch(r'[\w*†‡.-]{1,16}', label):
            label = str(number)
        notes[label] = body
        added.append((label, body))
        return f'<hi type="super" n="note">{html.escape(label)}</hi>'

    raw = _INLINE.sub(inline, raw)
    if added:
        raw += '<div type="x-notes"><title>Notes</title>' + ''.join(
            f'<p><hi type="super">{n}</hi> {body}</p>' for n, body in added) + '</div>'
    return raw, notes
