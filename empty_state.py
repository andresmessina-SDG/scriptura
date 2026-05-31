"""Shared compact empty-state widget.

Adw.StatusPage's 128px icon is right for full-window empties but overwhelms
sidebars and narrow panels, and its `.compact` style class isn't reliably
honored across libadwaita versions / distro themes (Zorin's themed Adwaita
ignored it). This hand-rolled version gives a stable, identical look in every
confined context — the study-journal list, the tag list, and the search panel
all share it so they can't drift apart.
"""

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk


def compact_empty_state(icon_name, title, description, icon_px=48):
    """A centred icon + heading + dimmed description, sized for panels.

    Returns a Gtk.Box; wrap it in a Gtk.ListBoxRow when placing it inside a
    Gtk.ListBox."""
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
    box.set_margin_start(16)
    box.set_margin_end(16)
    box.set_margin_top(24)
    box.set_margin_bottom(24)
    box.set_halign(Gtk.Align.CENTER)
    box.set_valign(Gtk.Align.CENTER)

    image = Gtk.Image.new_from_icon_name(icon_name)
    image.set_pixel_size(icon_px)
    image.set_halign(Gtk.Align.CENTER)
    image.add_css_class('dim-label')
    box.append(image)

    title_lbl = Gtk.Label(label=title)
    title_lbl.add_css_class('heading')
    title_lbl.set_wrap(True)
    title_lbl.set_justify(Gtk.Justification.CENTER)
    title_lbl.set_halign(Gtk.Align.CENTER)
    box.append(title_lbl)

    desc_lbl = Gtk.Label(label=description)
    desc_lbl.add_css_class('dim-label')
    desc_lbl.set_wrap(True)
    desc_lbl.set_justify(Gtk.Justification.CENTER)
    desc_lbl.set_halign(Gtk.Align.CENTER)
    desc_lbl.set_max_width_chars(40)
    box.append(desc_lbl)

    return box
