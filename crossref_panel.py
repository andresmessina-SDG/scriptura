import threading
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, GLib
import sword_bridge


class CrossRefPanel(Gtk.Box):
    def __init__(self, on_ref_clicked, on_close, on_ref_right_clicked=None, **kwargs):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0, **kwargs)
        self._on_ref_clicked = on_ref_clicked
        self._on_close = on_close
        self._on_ref_right_clicked = on_ref_right_clicked
        self._build_ui()

    def _build_ui(self):
        # No separator rule — a faint .crossref-bar surface tint reads as a calm
        # tray attached to the reading page (matches the popover/search de-ruling).
        self.add_css_class('crossref-bar')

        # Single-row chips layout: source-verse eyebrow on the left, scrollable
        # outline chips in the middle, close button on the right.
        ref_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        ref_row.set_margin_start(12)
        ref_row.set_margin_end(8)
        ref_row.set_margin_top(6)
        ref_row.set_margin_bottom(6)

        self._title = Gtk.Label(xalign=0)
        self._title.add_css_class('dim-label')
        self._title.add_css_class('caption')
        ref_row.append(self._title)

        ref_scroll = Gtk.ScrolledWindow()
        # EXTERNAL (not AUTOMATIC) horizontally: no scrollbar is drawn — the slim
        # chips no longer hide it, and a bar across them read as strikethrough.
        ref_scroll.set_policy(Gtk.PolicyType.EXTERNAL, Gtk.PolicyType.NEVER)
        ref_scroll.set_hexpand(True)
        ref_scroll.set_valign(Gtk.Align.CENTER)
        self._ref_scroll = ref_scroll
        # With no scrollbar, drive horizontal scroll from the wheel/trackpad
        # ourselves — GTK won't translate a vertical wheel to horizontal here.
        wheel = Gtk.EventControllerScroll.new(
            Gtk.EventControllerScrollFlags.BOTH_AXES)
        wheel.connect('scroll', self._on_wheel_scroll)
        ref_scroll.add_controller(wheel)
        self._ref_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        ref_scroll.set_child(self._ref_box)
        ref_row.append(ref_scroll)

        close_btn = Gtk.Button(icon_name='window-close-symbolic')
        close_btn.add_css_class('flat')
        close_btn.set_valign(Gtk.Align.CENTER)
        close_btn.set_tooltip_text(_('Hide cross-references'))
        close_btn.connect('clicked', lambda _: self._on_close())
        ref_row.append(close_btn)

        self.append(ref_row)

    def _on_wheel_scroll(self, _ctrl, dx, dy):
        # Map whichever axis the device reports onto the row's horizontal scroll.
        adj = self._ref_scroll.get_hadjustment()
        delta = dx if abs(dx) > abs(dy) else dy
        adj.set_value(adj.get_value() + delta * 60)
        return True

    def load(self, book, chapter, verse):
        self._title.set_text(
            _('Cross-references · {book} {chapter}:{verse}').format(
                book=book, chapter=chapter, verse=verse))
        self._clear_refs()

        spinner = Gtk.Spinner()
        spinner.start()
        self._ref_box.append(spinner)

        def fetch():
            refs = sword_bridge.get_cross_refs(book, chapter, verse)
            GLib.idle_add(self._show_refs, refs)

        threading.Thread(target=fetch, daemon=True).start()

    def _clear_refs(self):
        child = self._ref_box.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self._ref_box.remove(child)
            child = nxt

    def _show_refs(self, refs):
        self._clear_refs()
        if refs is None:
            lbl = Gtk.Label(label=_('Install the TSK module or download OpenBible cross-references.'))
            lbl.add_css_class('dim-label')
            self._ref_box.append(lbl)
        elif not refs:
            lbl = Gtk.Label(label=_('No cross-references found.'))
            lbl.add_css_class('dim-label')
            self._ref_box.append(lbl)
        else:
            for ref_book, ref_ch, ref_v, label in refs:
                btn = Gtk.Button(label=label)
                btn.add_css_class('xref-chip')
                btn.connect('clicked', self._make_handler(ref_book, ref_ch, ref_v))
                if self._on_ref_right_clicked:
                    rc = Gtk.GestureClick.new()
                    rc.set_button(3)
                    rc.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
                    rc.connect('pressed', self._make_right_handler(btn, ref_book, ref_ch, ref_v))
                    btn.add_controller(rc)
                self._ref_box.append(btn)
        return GLib.SOURCE_REMOVE

    def _make_handler(self, book, chapter, verse):
        return lambda _: self._on_ref_clicked(book, chapter, verse)

    def _make_right_handler(self, widget, book, chapter, verse):
        def handler(gesture, n_press, x, y):
            gesture.set_state(Gtk.EventSequenceState.CLAIMED)
            self._on_ref_right_clicked(book, chapter, verse, widget)
        return handler
