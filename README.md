# Bible Reader

A GNOME-native Bible study app for Linux. Two-pane layout, SWORD modules,
full-text search, per-verse annotations, cross-references, Strong's lexicon,
reading plans, and devotional support — built with Python 3, GTK4, and
libadwaita.

## Features

- **Two-pane layout** with independent module selectors. Lock either pane to
  hold its place while you navigate in the other.
- **SWORD modules** (KJVA, KJV, MHCC, TSK, Strongs, MorphGNT, devotionals)
  plus **eBible.org translations** (LEB, BSB, ASV, and more) via a SQLite
  backend.
- **Strong's lexicon** with hover-only word underlines, definition view,
  clickable cross-references, and a word-study panel that lists every verse
  in the current book containing the Strong's number.
- **Greek and Hebrew morphology** shown in the lexicon header — Robinson
  codes for Greek (via MorphGNT), OSHB codes for Hebrew.
- **Verse annotations** — four highlight colors, underlines, notes with
  topical tags. All annotation actions are in-place tag mutations: the
  scroll position never moves.
- **Cross-references** — slim bottom bar with clickable pills. Uses
  OpenBible.info's 340k references if downloaded, falls back to TSK.
- **Topical tag suggestions** in the note editor sourced from OpenBible's
  topic database.
- **Full-text search** per module (Whoosh-backed), with a bar-chart
  distribution view across the canon and click-to-navigate results.
- **Study Journal** — all annotations across all modules in one filterable
  surface with export.
- **Reading plans** — six built-in plans (Bible in a Year, Blended,
  OT/NT, Psalms, Proverbs) with progress tracking.
- **Devotionals** with multi-section detection (e.g. Spurgeon's Morning &
  Evening labels its two readings).
- **F11 reading mode** — hides all chrome for distraction-free reading.

## Requirements

- Linux (developed on Fedora; should run on any modern GNOME desktop)
- Python 3
- PyGObject (GTK4 + libadwaita bindings)
- SWORD library and Python bindings
- Whoosh (full-text search)

### Fedora

```sh
sudo dnf install python3-gobject gtk4 libadwaita sword python3-sword python3-whoosh
```

### Ubuntu / Debian / Zorin OS / Pop!_OS / Mint

```sh
sudo apt install python3-gi python3-gi-cairo \
                 gir1.2-gtk-4.0 gir1.2-adw-1 \
                 python3-sword python3-whoosh \
                 git
```

If `python3-whoosh` is not available in your repos (older Ubuntu / Debian
stable), install it in a venv with system-package access:

```sh
python3 -m venv --system-site-packages ~/.venvs/bible-reader
source ~/.venvs/bible-reader/bin/activate
pip install whoosh
# Activate this venv before running the app from now on.
```

### Arch / Manjaro / EndeavourOS / CachyOS

```sh
sudo pacman -S --needed python-gobject gtk4 libadwaita \
                        sword python-whoosh git
```

Arch's `sword` package bundles both `libsword` and the Python bindings in
one package. On Arch you can run the app with `python main.py` (the
`python3` alias also works).

## Running

The app is plain Python scripts — no build step.

```sh
python3 main.py
```

On first run you'll need at least one SWORD Bible installed. Use the
**Module Manager** (burger menu → Modules) to install KJVA (the recommended
starter — includes Strong's tagging) plus `StrongsHebrew`, `StrongsGreek`,
and `TSK`. Optionally download OpenBible cross-references, OpenBible
topics, and the Dodson Greek lexicon from the "Open Databases" tab.

## Running on tiling compositors (Hyprland, river, sway)

The app passes `transient_for` + `modal=True` on every dialog and child
window, which Mutter (GNOME) automatically floats above its parent.
Tiling compositors honor those hints only if you tell them to. A few
recommended rules for Hyprland users:

```hyprlang
# Float dialogs and child windows of the Bible Reader instead of tiling
# them into the workspace. Match by title until Flatpak ships a stable
# WM_CLASS / app_id you can pin to.
windowrulev2 = float, title:^(Module Manager|Study Journal|Tag Manager|Keyboard Shortcuts)$
windowrulev2 = float, title:^(Save .*|Export .*|Rename .*|Remove .*)$
windowrulev2 = float, title:^(Bible Reader)$, floating:1
```

Sway / river users can translate these to `for_window [title=…] floating enable`
and the river equivalent.

**File picker (Export Study Journal):** uses `xdg-desktop-portal`. Make
sure `xdg-desktop-portal-gtk` (or `xdg-desktop-portal-hyprland`) is
installed under your Hyprland session, otherwise the picker may silently
fall back or fail.

```sh
# Fedora
sudo dnf install xdg-desktop-portal-gtk

# Ubuntu / Debian / Zorin
sudo apt install xdg-desktop-portal-gtk

# Arch
sudo pacman -S xdg-desktop-portal-gtk
```

## Development

Tests for the pure-Python bridges (sword_bridge, open_data, annotations,
reading_plans):

```sh
# Fedora
sudo dnf install python3-pytest
# Ubuntu / Debian / Zorin
sudo apt install python3-pytest
# Arch
sudo pacman -S python-pytest
# Or for any distro:
pip install -r requirements-dev.txt

python3 -m pytest
```

124 tests, runs in well under a second. The GTK-side code (`pane.py`,
`window.py`, dialogs, lexicon panel) is verified by running the app.

See `PROJECT.md` for the architecture brief — file layout, internal
contracts, known SWORD and GTK4 gotchas.

## Privacy

Bible Reader runs entirely on your computer. There is no telemetry,
analytics, account, or background phone-home. Network access is
used only when you explicitly install a module (Module Manager),
download an open-data file (cross-references, topics, Dodson
lexicon), or fetch an eBible translation.

Your data lives in standard XDG directories:

- `~/.config/bible-reader/` — preferences, bookmarks, reading-plan
  progress.
- `~/.local/share/bible-reader/` — annotations, eBible database,
  downloaded reference files.
- `~/.cache/bible-reader/` — search history, eBible catalog (all
  regenerable).
- `~/.sword/` — SWORD's own module directory (CrossWire convention).

You can back up, sync, or wipe any of these. Removing them resets
the corresponding part of the app to a clean state.

## Data attributions

- **SWORD Project** modules — CrossWire Bible Society
- **OpenBible Cross-References** and **OpenBible Topics** —
  [openbible.info](https://www.openbible.info/), CC-BY
- **Dodson Greek Lexicon** — public-domain NT Greek definitions
- **eBible.org** — modern translation catalog and texts

## License

GPL-3.0-or-later. See [`LICENSE`](LICENSE). The SWORD library this app
links against is also GPL-licensed.

## Repository

[codeberg.org/andresmessina/bible-reader](https://codeberg.org/andresmessina/bible-reader)
