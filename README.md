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
- SWORD library and Python bindings (`python3-sword` / `libsword`)
- Whoosh (`python3-whoosh`)

On Fedora:

```sh
sudo dnf install python3-gobject gtk4 libadwaita sword python3-sword python3-whoosh
```

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

## Development

Tests for the pure-Python bridges (sword_bridge, open_data, annotations,
reading_plans):

```sh
sudo dnf install python3-pytest    # or: pip install -r requirements-dev.txt
python3 -m pytest
```

113 tests, runs in under a second. The GTK-side code (`pane.py`,
`window.py`, dialogs, lexicon panel) is verified by running the app.

See `PROJECT.md` for the architecture brief — file layout, internal
contracts, known SWORD and GTK4 gotchas.

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
