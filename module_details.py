"""A module's own description, as its publisher wrote it, beside the
Module Manager's list: About, Copyright, Version and Source from its conf.
Shares the Family Card's side sheet and type."""
import re

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, GLib, Pango

from a11y import set_accessible_label
from i18n import _

_URL = re.compile(r'https?://[^\s<>"]+[^\s<>".,;:)\]]')


def _linked(text):
    """Escaped markup with each web address a link."""
    out, pos = [], 0
    for m in _URL.finditer(text):
        out.append(GLib.markup_escape_text(text[pos:m.start()]))
        url = GLib.markup_escape_text(m.group(0))
        out.append(f'<a href="{url}">{url}</a>')
        pos = m.end()
    out.append(GLib.markup_escape_text(text[pos:]))
    return ''.join(out)


class ModuleDetails(Gtk.Box):
    """`show(title, source, meta, about, copyright, text_source)` fills it.
    Sans for the header block and labels, serif for the publisher's prose."""

    def __init__(self, on_close):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.add_css_class('search-panel')
        # The publisher shares Close's row; the module's name is the title.
        header = Gtk.Box()
        header.set_margin_start(18)
        header.set_margin_end(8)
        header.set_margin_top(10)
        self._kicker = Gtk.Label(xalign=0, hexpand=True)
        self._kicker.add_css_class('family-card-kicker')
        header.append(self._kicker)
        self._close_btn = Gtk.Button(icon_name='scriptura-window-close-symbolic')
        self._close_btn.add_css_class('flat')
        self._close_btn.set_tooltip_text(_('Close (Esc)'))
        set_accessible_label(self._close_btn, _('Close'))
        self._close_btn.connect('clicked', lambda _b: on_close())
        header.append(self._close_btn)
        self.append(header)
        self._scroll = Gtk.ScrolledWindow(vexpand=True)
        self._scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self._body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._body.set_margin_start(18)
        self._body.set_margin_end(18)
        self._body.set_margin_bottom(20)
        self._scroll.set_child(self._body)
        self.append(self._scroll)

    def show(self, title, source, meta, about, copyright, text_source):
        child = self._body.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self._body.remove(child)
            child = nxt
        self._kicker.set_label(source)
        self._label(title, 'family-card-title')
        if meta:
            self._label(meta, 'family-card-meta')
        # A source that only names the publisher repeats the kicker.
        if text_source.lower().startswith(source.lower()):
            text_source = ''
        fields = [(_('About'), about), (_('Copyright'), copyright),
                  (_('Source'), text_source)]
        fields = [(head, text) for head, text in fields if text]
        for head, text in fields:
            self._label(head, 'family-card-kicker').set_margin_top(24)
            self._label(text, 'family-card-body', markup=True).set_margin_top(6)
        if not fields:
            self._label(_('Its publisher gives no description.'),
                        'dim-label').set_margin_top(20)
        self._scroll.get_vadjustment().set_value(0)

    def focus_start(self):
        self._close_btn.grab_focus()

    def _label(self, text, *classes, markup=False):
        lbl = Gtk.Label(xalign=0, wrap=True)
        lbl.set_natural_wrap_mode(Gtk.NaturalWrapMode.WORD)
        # A long web address must break rather than widen the sheet.
        lbl.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        if markup:
            lbl.set_markup(_linked(text))
        else:
            lbl.set_label(text)
        for c in classes:
            lbl.add_css_class(c)
        self._body.append(lbl)
        return lbl
