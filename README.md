# Scriptura

A native Linux Bible study app for the new generation that wants to
study and teach the old truth with digital efficiency. Two-pane
reading, SWORD modules, Strong's lexicon, full-text search, per-verse
notes — all on your own machine, all in service of a quiet, focused
hour with the Word.

Built on GNOME with GTK4 + libadwaita, in Python, GPL-3.0.

> _"For the word of God is living and active, sharper than any
> two-edged sword..."_ — Hebrews 4:12

---

## What it does

- **Read two translations side by side.** Each pane has its own
  module picker; lock one in place while you navigate in the other.
- **Strong's lexicon at a hover.** Click any tagged Hebrew or Greek
  word for the original lexeme, its morphology, and a word-study
  list of every verse in the current book that uses the same Strong's
  number.
- **Commentaries, devotionals, and confessions.** Matthew Henry,
  Calvin, Clarke, Spurgeon's Morning & Evening, the Westminster
  Confession, the Augsburg Confession, the Didache, the Apostolic
  Fathers — anything CrossWire packages in SWORD format.
- **Annotate your study.** Four highlight colors, underlines, notes
  with topical tags, chapter-level notes. Everything you mark lives
  in plain JSON in your XDG config directory — yours to back up,
  sync, or migrate.
- **Cross-references.** OpenBible.info's 340,000-reference database
  is one click away (Module Manager → Open Databases). TSK is the
  fallback when you're offline.
- **Full-text search.** Per-module Whoosh index, distribution chart
  across the canon, case-sensitive option, F3 step-through.
- **Study Journal.** Every annotation, across every module, in one
  filterable surface. Search free-text, filter by tag or module or
  book, click a row to jump back to the verse.
- **Reading plans.** Six built-in: Bible in a Year, OT/NT, Blended
  four-stream, Psalms in 30 days, Proverbs in 31 days.
- **Modern translations.** LEB, BSB, ASV, and the rest of the
  eBible.org catalog — modules SWORD doesn't carry, fetched on
  demand into a local SQLite store.
- **F11 reading mode** when you want chrome to disappear.

Scriptura runs entirely on your computer. There is no telemetry,
no account, no background phone-home. The only time the app uses the
network is when you explicitly download a module, fetch a translation
from eBible.org, or install an open-data file. Your study is your
own.

---

## Installing dependencies

Use whichever section matches your distribution.

### Fedora

```sh
sudo dnf install python3-gobject gtk4 libadwaita \
                 sword python3-sword python3-whoosh
```

### Ubuntu / Debian / Zorin OS / Pop!_OS / Mint

```sh
sudo apt install python3-gi python3-gi-cairo \
                 gir1.2-gtk-4.0 gir1.2-adw-1 \
                 python3-sword python3-whoosh git
```

If your distribution doesn't ship `python3-whoosh` (older Debian /
Ubuntu stable), install it into a system-aware venv:

```sh
python3 -m venv --system-site-packages ~/.venvs/scriptura
source ~/.venvs/scriptura/bin/activate
pip install whoosh
# Activate this venv before running the app from now on.
```

### Arch / Manjaro / EndeavourOS / CachyOS

```sh
sudo pacman -S --needed python-gobject gtk4 libadwaita \
                        sword python-whoosh git
```

Arch ships both `libsword` and the Python bindings in the same
`sword` package. You can launch the app with `python main.py` —
the `python3` alias works too.

---

## Running

The app is plain Python — no build step:

```sh
git clone https://codeberg.org/andresmessina/scriptura.git
cd scriptura
python3 main.py
```

On first launch the welcome window will offer to download a starter
bundle: KJVA (King James with Apocrypha — includes Strong's word
tagging), Strong's Hebrew, Strong's Greek, the Treasury of Scripture
Knowledge for cross-references, plus the OpenBible cross-references
and Dodson Greek lexicon. Click "Install essentials" and let it run;
everything else can be added later from the Module Manager.

---

## A few quiet design choices

- **No web view.** The Bible text renders in a native `GtkTextView`
  with Pango markup — starts faster, scrolls smoother, inherits your
  system fonts and theme without us hardcoding anything.
- **Annotations apply in place.** Highlighting a verse doesn't reload
  the chapter or jump your scroll position. The mark just appears
  where the verse is.
- **Soft palette.** Highlight colors render as muted pastels at view
  time even though stored as their familiar yellow / green / blue /
  orange — easier on the eyes for long sessions.
- **The reading column has a cap.** On wide monitors the verse text
  stays at a comfortable reading width; the scrollbar lives at the
  pane edge, not inside the column. Adjustable via the Width slider
  in the menu panel.
- **F11 hides everything.** Chrome, toolbars, panels — just the
  Word.

---

## Tiling compositors (Hyprland, sway, river)

Mutter (GNOME) floats child windows above their parent automatically.
Tiling compositors need a hint. For Hyprland:

```hyprlang
windowrulev2 = float, title:^(Module Manager|Study Journal|Tag Manager|Keyboard Shortcuts)$
windowrulev2 = float, title:^(Save .*|Export .*|Rename .*|Remove .*)$
windowrulev2 = float, title:^(Scriptura)$, floating:1
```

`xdg-desktop-portal-gtk` (or `-hyprland`) needs to be installed
for the Export Study Journal file picker to work:

```sh
# Fedora
sudo dnf install xdg-desktop-portal-gtk
# Debian / Ubuntu / Zorin
sudo apt install xdg-desktop-portal-gtk
# Arch
sudo pacman -S xdg-desktop-portal-gtk
```

---

## Running the tests (for contributors)

The pure-Python layers (`sword_bridge`, `open_data`, `annotations`,
`reading_plans`, `paths`, `bookmarks`, `settings`, `ebible_bridge`,
etc.) have a pytest suite — 227 tests, under two seconds.

```sh
# Fedora
sudo dnf install python3-pytest
# Debian / Ubuntu / Zorin
sudo apt install python3-pytest
# Arch
sudo pacman -S python-pytest
# Or any distribution:
pip install -r requirements-dev.txt

python3 -m pytest
```

The GTK side — panes, dialogs, lexicon panel — is verified by
running the app. See [`ARCHITECTURE.md`](ARCHITECTURE.md) for the
internal map: file layout, render pipeline, known SWORD and GTK4
quirks worth knowing before touching the rendering code.

---

## What goes where

Your data lives in standard XDG directories so it survives across
installs and is easy to back up:

- `~/.config/bible-reader/` — preferences, bookmarks, reading-plan
  progress, per-module reading positions.
- `~/.local/share/bible-reader/` — annotations, eBible database,
  downloaded reference files.
- `~/.cache/bible-reader/` — search history, regenerable indexes.
- `~/.sword/` — SWORD's own module library (CrossWire convention,
  shared with any other SWORD-compatible tool you use).

Wipe any of these to reset the corresponding part of the app to
factory defaults.

---

## Reporting bugs

If something misbehaves — especially anything SWORD-related (a module
fails to load, a chapter is blank, search returns nothing) — re-run
with verbose logging and include the output in the report:

```sh
SCRIPTURA_LOG_LEVEL=DEBUG python3 main.py
```

Logs go to stderr, prefixed with the component (`scriptura.sword`,
`scriptura.search`, `scriptura.ebible`, …) and include full
tracebacks for any caught exception. The default level is `WARNING`
so normal runs stay quiet.

---

## Credits

This app stands on the work of others:

- **The SWORD Project** — CrossWire Bible Society, who have spent
  decades building the cross-platform Bible-software library this
  app is built on, and have curated more than two hundred text
  modules in over fifty languages.
- **OpenBible.info** — cross-references and topical tags, released
  under CC-BY. The reason a click on a verse can show you everywhere
  else Scripture has interpreted Scripture.
- **Dodson Greek Lexicon** — public-domain NT Greek definitions.
- **eBible.org** — the modern licensed translations (LEB, BSB, ASV,
  and many more) that complete the picture.
- **GNOME** — the platform that makes a clean reading experience
  possible on Linux: GTK4, libadwaita, PyGObject.
- **Whoosh** — the pure-Python full-text search engine that indexes
  every Bible the moment you ask.

---

## License

GPL-3.0-or-later. See [`LICENSE`](LICENSE) for the canonical text.
The SWORD library this app links against is also GPL-licensed.

---

## A note on how this app was built

Scriptura is one person's project, built with the help of an AI
assistant. Every feature, every design decision, every bug report
came from sitting with Scripture and thinking about what the tool
should do; the assistant made the implementation faster. The vision,
the choices, and the testing were mine. I wanted a Bible-study app
that fit how I read.

The source is open and the architecture is documented. Pull requests,
bug reports, and translation contributions are all welcome.

---

## Repository

[codeberg.org/andresmessina/scriptura](https://codeberg.org/andresmessina/scriptura)
