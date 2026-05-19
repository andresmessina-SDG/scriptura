"""First-run welcome window — shown when no SWORD or eBible modules are
installed yet. Offers a one-click bundle install of the essentials and an
escape hatch into the Module Manager for users who want to pick their own.

The bundle is intentionally minimal: one Bible with Strong's tagging,
both Strong's lexicons, one cross-reference source, plus the two open-data
sources we use by preference. Anything else can be added later from the
Module Manager."""

import threading
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib, Pango

import sword_bridge
import open_data


_SWORD_ESSENTIALS = [
    ('KJVA',          'King James (with Apocrypha)',  'Bible with Strong\'s word tagging'),
    ('StrongsHebrew', 'Strong\'s Hebrew Lexicon',     'Required for OT word study'),
    ('StrongsGreek',  'Strong\'s Greek Lexicon',      'Required for NT word study'),
    ('TSK',           'Treasury of Scripture Knowledge', 'Cross-references between verses'),
]

_OPEN_DATA_ESSENTIALS = [
    ('cross_references', 'OpenBible Cross-References', '340k refs — 5× more than TSK'),
    ('dodson',           'Dodson Greek Lexicon',       'Readable NT Greek definitions'),
]


class WelcomeWindow(Adw.ApplicationWindow):
    def __init__(self, on_ready, **kwargs):
        super().__init__(**kwargs)
        self._on_ready = on_ready
        self.set_title('Bible Reader — Welcome')
        self.set_default_size(620, 540)

        toolbar_view = Adw.ToolbarView()
        toolbar_view.add_top_bar(Adw.HeaderBar())
        self.set_content(toolbar_view)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        outer.set_margin_top(24)
        outer.set_margin_bottom(24)
        outer.set_margin_start(36)
        outer.set_margin_end(36)
        toolbar_view.set_content(outer)

        # ── Hero ──────────────────────────────────────────────────────────
        title = Gtk.Label(label='Welcome to Bible Reader')
        title.add_css_class('title-1')
        title.set_xalign(0)
        outer.append(title)

        subtitle = Gtk.Label(
            label="To get started you'll need a Bible and a few reference "
                  "resources. The recommended bundle below is a one-click "
                  "install of everything we use by default.")
        subtitle.set_wrap(True)
        subtitle.set_wrap_mode(Pango.WrapMode.WORD)
        subtitle.set_xalign(0)
        subtitle.add_css_class('dim-label')
        outer.append(subtitle)

        # ── Bundle list ───────────────────────────────────────────────────
        list_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        list_card.add_css_class('boxed-list')
        for _id, name, desc in _SWORD_ESSENTIALS + _OPEN_DATA_ESSENTIALS:
            row = Adw.ActionRow()
            row.set_title(name)
            row.set_subtitle(desc)
            list_card.append(row)
        outer.append(list_card)

        # ── Status label ──────────────────────────────────────────────────
        self._status = Gtk.Label(label='')
        self._status.set_wrap(True)
        self._status.set_xalign(0)
        self._status.add_css_class('caption')
        self._status.add_css_class('dim-label')
        outer.append(self._status)

        # ── Buttons ───────────────────────────────────────────────────────
        btn_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        btn_row.set_halign(Gtk.Align.END)
        btn_row.set_margin_top(8)

        self._mgr_btn = Gtk.Button(label='Open Module Manager')
        self._mgr_btn.connect('clicked', self._on_open_mgr)
        btn_row.append(self._mgr_btn)

        self._install_btn = Gtk.Button(label='Install essentials')
        self._install_btn.add_css_class('suggested-action')
        self._install_btn.add_css_class('pill')
        self._install_btn.connect('clicked', self._on_install_clicked)
        btn_row.append(self._install_btn)

        outer.append(btn_row)

    # ── Install flow ──────────────────────────────────────────────────────

    def _on_install_clicked(self, _btn):
        self._install_btn.set_sensitive(False)
        self._mgr_btn.set_sensitive(False)
        self._status.set_text('Starting download…')
        threading.Thread(target=self._install_worker, daemon=True).start()

    def _install_worker(self):
        failed = []
        total = len(_SWORD_ESSENTIALS) + len(_OPEN_DATA_ESSENTIALS)
        step = 0

        for module_id, name, _desc in _SWORD_ESSENTIALS:
            step += 1
            GLib.idle_add(self._set_status,
                          f'({step}/{total}) Downloading {name}…')
            try:
                sword_bridge.install_module(module_id)
            except Exception as e:
                failed.append((name, str(e)))

        for source_id, name, _desc in _OPEN_DATA_ESSENTIALS:
            step += 1
            label = f'({step}/{total}) Downloading {name}…'
            GLib.idle_add(self._set_status, label)
            try:
                def _progress(done, tot, _label=label):
                    if tot > 0:
                        pct = int(done * 100 / tot)
                        GLib.idle_add(self._set_status,
                                      f'{_label} {pct}% ({done >> 20} of {tot >> 20} MB)')
                    else:
                        GLib.idle_add(self._set_status,
                                      f'{_label} {done >> 20} MB')
                open_data.download_source(source_id, on_progress=_progress)
            except Exception as e:
                failed.append((name, str(e)))

        GLib.idle_add(self._finish_install, failed)

    def _set_status(self, msg):
        self._status.set_text(msg)
        return GLib.SOURCE_REMOVE

    def _finish_install(self, failed):
        # Verify at least one Bible-text module is now installed; without
        # that the main window can't open. Anything else is recoverable
        # from the Module Manager later.
        installed = sword_bridge.module_names()
        has_bible = any(
            sword_bridge.module_type(m) == 'Biblical Texts' for m in installed
        )

        if not has_bible:
            details = '; '.join(f'{n}: {e}' for n, e in failed) or 'unknown error'
            self._status.set_text(
                f'Install failed — no Bible module is available. {details}')
            self._install_btn.set_label('Try again')
            self._install_btn.set_sensitive(True)
            self._mgr_btn.set_sensitive(True)
            return GLib.SOURCE_REMOVE

        if failed:
            names = ', '.join(n for n, _ in failed)
            self._status.set_text(
                f'Installed with warnings — these failed and can be retried '
                f'later from the Module Manager: {names}')
        else:
            self._status.set_text('Done. Opening Bible Reader…')

        # Hand off to main.py to construct the real window.
        GLib.timeout_add(600, self._handoff)
        return GLib.SOURCE_REMOVE

    def _handoff(self):
        self._on_ready()
        self.close()
        return GLib.SOURCE_REMOVE

    # ── Manual route ──────────────────────────────────────────────────────

    def _on_open_mgr(self, _btn):
        # Import lazily so the welcome window doesn't pull the whole
        # module-manager dependency chain on the no-op path.
        from module_manager import ModuleManagerWindow

        win = ModuleManagerWindow(application=self.get_application())
        win.connect('close-request', self._on_mgr_closed)
        win.present()

    def _on_mgr_closed(self, _win):
        # User may have installed modules manually; re-check and hand off
        # to the real window if so. Otherwise stay on welcome.
        if sword_bridge.module_names():
            self._handoff()
        return False
