# Scriptura

A native Linux Bible study app for people who study and teach the
Word. Two-pane reading, SWORD modules, Greek and Hebrew interlinears,
Strong's lexicon, full-text search, per-verse notes: all on your own
machine, all in service of a quiet, focused hour with Scripture.

Built on GNOME with GTK4 + libadwaita, in Python, GPL-3.0.
Website: <https://andresmessina-sdg.github.io/scriptura/>

> _"For the word of God is living and active, sharper than any
> two-edged sword..."_ — Hebrews 4:12

![Scriptura: two-pane reading with the Strong's lexicon panel open](data/screenshots/01-two-pane-lexicon.png)

---

## What it does

- **Read two translations side by side**, from CrossWire's SWORD
  library or eBible.org, or a module you already have on disk.
- **Study the Greek and Hebrew.** Click a word for its Strong's entry,
  or read an interlinear with the meaning and grammar under every word.
- **Commentaries, devotionals and confessions**, plus an optional pack
  of how the church read each verse, from Irenaeus to Calvin.
- **Cross-references and search.** 340,000 cross-references, and fast
  search across a whole Bible.
- **Mark and write.** Highlights, notes and tags that show in every
  translation, a journal, and sermon manuscripts.
- **Reading plans** and a Today page with the day's reading.
- **Art, archaeology and genealogies.** Paintings and maps for the
  passage you read, a gallery of finds from the ground, and the
  Bible's family lists drawn as charts.
- **Listen.** Chapters and devotionals read aloud.
- **Present.** F5 shows a passage full screen on a projector.
- **In English, Spanish and Russian.**

Scriptura runs entirely on your computer. There is no telemetry,
no account, no background phone-home. The only time the app uses the
network is when you explicitly download a module, fetch a translation
from eBible.org, or install an open-data file. Your study is your
own.

| | |
|:---:|:---:|
| ![The Greek New Testament interlinear: gloss, parsing, and Strong's number under every word](data/screenshots/06-interlinear-greek.png) | ![The Historical Commentaries pane: the church's voices on a verse, across the centuries](data/screenshots/02-historical-commentaries.png) |
| _Greek NT interlinear_ | _Historical Commentaries_ |
| ![Annotations: every mark you have made in one filterable view](data/screenshots/03-study-journal.png) | ![Distraction-free reading mode in dark theme](data/screenshots/05-reading-mode-dark.png) |
| _Annotations_ | _Reading mode (dark)_ |

---

## Install

[![Install as Flatpak](https://img.shields.io/badge/Install-Flatpak-4A86CF?logo=flatpak&logoColor=white)](https://andresmessina-sdg.github.io/scriptura-flatpak/scriptura.flatpakref)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)

The easiest way to run Scriptura (one click, automatic updates):

**[➜ Install Scriptura (Flatpak)](https://andresmessina-sdg.github.io/scriptura-flatpak/scriptura.flatpakref)**

Or from a terminal:

```bash
flatpak install https://andresmessina-sdg.github.io/scriptura-flatpak/scriptura.flatpakref
```

You'll need [Flatpak](https://flatpak.org/setup/) with the Flathub remote (for
the GNOME runtime). Updates arrive automatically with `flatpak update`. The
build is GPG-signed and served from this project's own repository.

Prefer to run from source? See **Installing dependencies** below.

---

## Installing dependencies

Use whichever section matches your distribution.

### Fedora

```sh
sudo dnf install python3-gobject gtk4 libadwaita \
                 sword python3-sword
```

### Ubuntu / Debian / Zorin OS / Pop!_OS / Mint

```sh
sudo apt install python3-gi python3-gi-cairo \
                 gir1.2-gtk-4.0 gir1.2-adw-1 \
                 python3-sword git
```

Full-text search uses SQLite FTS5, which ships with Python's standard
`sqlite3` module; there's no separate search package to install.

### Arch / Manjaro / EndeavourOS / CachyOS

```sh
sudo pacman -S --needed python-gobject gtk4 libadwaita \
                        sword git
```

Arch ships both `libsword` and the Python bindings in the same
`sword` package. You can launch the app with `python main.py`;
the `python3` alias works too.

---

## Running

The app is plain Python, with no build step:

```sh
git clone https://github.com/andresmessina-SDG/scriptura.git
cd scriptura
python3 main.py
```

On first launch the welcome screen offers three curated starting
points, framed by what you get rather than by module names: *Just
reading* (one Bible, quick download), *Reading + study* (recommended:
a few translations, historical commentary, and original-language
study tools), and *Full library* (the complete set). Pick one and
start reading; everything can be added or removed later from the
Module Manager.

---

## Tiling compositors (Hyprland, sway, river)

Mutter (GNOME) floats child windows above their parent automatically.
Tiling compositors need a hint. For Hyprland:

```hyprlang
windowrulev2 = float, title:^(Module Manager|Annotations|Tag Manager|Keyboard Shortcuts)$
windowrulev2 = float, title:^(Save .*|Export .*|Rename .*|Remove .*)$
windowrulev2 = float, title:^(Scriptura)$, floating:1
```

`xdg-desktop-portal-gtk` (or `-hyprland`) needs to be installed
for the Export Annotations file picker to work:

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

The pytest suite covers the pure-Python layers (`sword_bridge`,
`open_data`, `annotations`, `reading_plans`, `paths`, `bookmarks`,
`settings`, `ebible_bridge`, etc.) and a growing GTK layer (panes,
the lexicon panel, interlinear and presentation paging): about
2,000 tests, under a minute.

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

Beyond the suite, a scroll-stability harness
(`tools/verify-scroll-stability.py`) drives the real app headless to
guard the reading view's scroll anchoring, and Woodpecker CI runs the
tests and mypy on every push. See
[`ARCHITECTURE.md`](ARCHITECTURE.md) for the internal map: file
layout, render pipeline, known SWORD and GTK4 quirks worth knowing
before touching the rendering code.

---

## What goes where

Your data lives in standard XDG directories so it survives across
installs and is easy to back up:

- `~/.config/bible-reader/`: preferences, bookmarks, reading-plan
  progress, per-module reading positions.
- `~/.local/share/bible-reader/`: annotations, eBible database,
  downloaded reference files.
- `~/.cache/bible-reader/`: search history, regenerable indexes.
- `~/.sword/`: SWORD's own module library (CrossWire convention,
  shared with any other SWORD-compatible tool you use).

Wipe any of these to reset the corresponding part of the app to
factory defaults.

---

## Reporting bugs

If something misbehaves, especially anything SWORD-related (a module
fails to load, a chapter is blank, search returns nothing), re-run
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

- **The SWORD Project**: CrossWire Bible Society, who have spent
  decades building the cross-platform Bible-software library this
  app is built on, and have curated more than two hundred text
  modules in over fifty languages.
- **STEPBible / Tyndale House, Cambridge**: the amalgamated Greek
  New Testament and Hebrew Old Testament word data behind the
  interlinears (TAGNT, TAHOT), and the Abbott-Smith and
  Liddell-Scott-Jones data behind the scholar's Greek lexicon (TBESG,
  TFLSJ). All CC BY 4.0, fetched from their repository at install
  time.
- **OpenBible.info**: cross-references and topical tags, released
  under CC-BY. The reason a click on a verse can show you everywhere
  else Scripture has interpreted Scripture.
- **Dodson Greek Lexicon**: public-domain NT Greek definitions.
- **eBible.org**: the modern licensed translations (LEB, BSB, ASV,
  and many more) that complete the picture.
- **HistoricalChristianFaith Commentaries Database**: the
  public-domain patristic, medieval, and Reformation commentary that
  powers the Historical Commentaries pack.
- **Wikimedia Commons & Project Gutenberg**: the public-domain and
  openly-licensed scans behind the Scripture in Art pack: Schnorr von
  Carolsfeld and Doré engravings, Tissot watercolours, Old Master
  paintings, Byzantine icons, stained glass, illuminated manuscripts,
  Hurlbut's *Bible Atlas* (1882), modern public-domain journey maps,
  and the place photographs (per-item credits shown in the app).
- **GNOME**: the platform that makes a clean reading experience
  possible on Linux: GTK4, libadwaita, PyGObject.
- **SQLite FTS5**: the full-text search engine, built into Python's
  standard library, that indexes every Bible the moment you ask.

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

[github.com/andresmessina-SDG/scriptura](https://github.com/andresmessina-SDG/scriptura)
