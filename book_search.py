"""Literal, cancellable general-book search; no GTK calls on the worker."""
import html
import re

import sword_bridge
from book_notes import prepare_notes


def plain_text(raw):
    raw = re.sub(r'<note\b[^>]*>\s*Auto-modernized\s*</note>', '', raw, flags=re.I)
    raw = re.sub(r'<hi\b[^>]*n="note"[^>]*>.*?</hi>', '', raw, flags=re.S)
    raw = re.sub(r'</(?:p|title|h[1-6]|li)>|<br\s*/?>', ' ', raw, flags=re.I)
    return ' '.join(html.unescape(re.sub(r'<[^>]*>', '', raw)).split())


def search_book(module, query, case_sensitive, task, limit=None):
    from genbook_reader import _strip_restated_title
    query = ' '.join(query.split())
    if len(query) < 2:
        return [], 0, 0
    pattern = re.compile(re.escape(query), 0 if case_sensitive else re.I)
    hits, sections, total = [], 0, 0
    for path, label, depth in sword_bridge.list_genbook_entries(module):
        if not task.is_current():
            break
        label = label.replace('_', ' ')
        raw = sword_bridge.load_genbook_entry(module, path)
        raw, _notes = prepare_notes(raw)
        text = label + ' ' + plain_text(_strip_restated_title(raw, label))
        first = pattern.search(text)
        if first is None:
            continue
        count = sum(1 for _ in pattern.finditer(text))
        total += count
        sections += 1
        if limit is None or len(hits) < limit:
            start, end = max(0, first.start()-55), min(len(text), first.end()+100)
            snippet = ('…' if start else '') + text[start:end] + ('…' if end<len(text) else '')
            hits.append((path, label, count, snippet))
    return hits, sections, total
