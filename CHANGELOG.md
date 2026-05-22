# Changelog

All notable changes to Bible Reader. Format roughly follows
[Keep a Changelog](https://keepachangelog.com/). Versioning is
semver-ish — 0.x is the pre-Flathub testing track.

## [0.9.0] — 2026-05-21

First public testing release. Everything below is stable and
exercised in real reading sessions; the only thing standing between
this and a 1.0 tag is the Flathub submission round-trip.

### Reader

- Two-pane reading view with per-pane sync locks and an independent
  module selector on each pane.
- SWORD module support: Bibles, commentaries, devotionals, and
  Generic Books (tree-keyed reference works).
- eBible.org modern translations (LEB, BSB, etc.) via a SQLite
  backend, surfaced as just-another module in the picker.
- Greek and Hebrew Strong's lexicon with hover-only word underlines,
  a per-pane lexicon panel, word-study list across the current
  book, and Greek (Robinson via MorphGNT) + Hebrew (OSHB)
  morphology displayed in the header.
- Adjustable reading-column width via Text Appearance slider
  (540–1600 px); scrollbar sits at the pane's outer edge for a
  modern reader feel.
- F11 reading mode with a hover-to-reveal exit affordance at the
  top of the window for users who don't remember Esc/F11.

### Annotations

- Four highlight colors plus underlines plus per-verse and
  per-chapter notes with topical tags.
- All annotation actions are in-place tag mutations — the scroll
  position never moves on save.
- Soft pastel highlight palette at render time; underlying storage
  values unchanged for forward compatibility.
- Drag-select across verses works; Ctrl+C copies with the verse
  reference prepended.

### Cross-references and topics

- Slim single-row cross-reference bar at the bottom of the window.
- OpenBible.info's 340 000-reference database (CC-BY), with TSK as
  the fallback.
- OpenBible topical tags surfaced as Suggested chips inside the
  note editor.

### Search

- Whoosh full-text per-module search with a canon-distribution
  bar chart and click-to-navigate results.
- F3 / Shift+F3 step through results without re-opening the
  panel; tolerates a closed panel by re-revealing.
- Aa match-case toggle (Whoosh post-filter for SWORD modules;
  SQLite GLOB for eBible).
- Matched-word highlighting in the chapter on arrival from a
  search result (5-second amber highlight, distinct from the
  yellow verse flash).

### Study Journal

- Master-detail layout: sidebar with type / tag / module / book
  filters + free-text search; detail editor on the right with
  color swatches, underline toggle, tags entry, and a note
  TextView.
- Live-save for color and underline; explicit Save for note +
  tags so unsaved text isn't blown away by a swatch click.
- Clickable tag chips on rows filter by that tag.
- Tag Manager dialog (rename / merge / delete) launched from a
  header button.

### Reading plans

- Six built-in plans: Bible in a Year, Blended (4-stream
  OT+NT+Psalms+Proverbs), OT in a Year, NT in 90 Days, Psalms in
  30 Days, Proverbs in 31 Days.
- Day-by-day progress tracking with a today highlight; multi-passage
  days surface a small popover.

### Devotionals

- Spurgeon's Morning and Evening (SME) with morning/evening
  section split; other devotionals supported through the standard
  Daily Devotional SWORD convention.

### Generic Books

- Tree-keyed reference works (Didache, Westminster Confession,
  Book of Concord, Dark Night of the Soul, Apostolic Fathers)
  read via a TOC popover and prev/next entry buttons.
- Breadcrumb title above the entry body for deep hierarchies.
- Per-pane reading position persistence — switching modules and
  coming back returns to the last-read entry; same across app
  restarts.
- Section-heading entries (no body, only sub-entries) get a hint
  pointing the user to the TOC.

### Navigation

- Ctrl+L quick jump (`Goto: John 3:16`, abbreviations supported).
- Alt+←/→ for chapter; Alt+↑/↓ for book.
- Home / End for first / last verse of current chapter.
- Ctrl+1 / Ctrl+2 / Ctrl+Tab for pane focus.
- Ctrl++ / Ctrl+- for font size; Ctrl+scroll and touchpad pinch
  for the same.
- Mouse wheel over the title button cycles chapters.
- Right-click a chapter in the picker to slide over to a verse
  picker for that chapter.
- Recent-passages menu (header clock icon, 10 distinct passages,
  persistent across sessions).

### State

- Per-pane scroll position restored on next launch.
- Per-pane Generic Book reading position restored on next launch
  and across module switches.
- Window size, maximized state, split-pane mode, last book /
  chapter, and pane modules all persisted.
- All data lives under XDG locations
  (`$XDG_{CONFIG,DATA,CACHE}_HOME/bible-reader/`). One-shot
  migration moves legacy in-tree state out on first launch.

### Module Manager

- Three tabs: SWORD modules, Open Databases (OpenBible cross-refs
  + topics, Dodson Greek), eBible.org translations.
- Module picker has language chips, per-module info popover, and
  free-text filtering.

### Internals

- 124 pytest tests across `sword_bridge`, `open_data`,
  `annotations`, `reading_plans`. GTK-side code verified by
  running the app.
- Performance audit pass (release-blocker hot paths): eBible SQLite
  thread-local singleton, BiblePane module-language memoization,
  SearchPanel display cap at 500 rows, settings.put debounce,
  tag-table bounded per render.

### Packaging

- Flatpak manifest for `org.codeberg.andresmessina.BibleReader`
  is checked in but the SWORD-Python binding integration step is
  pending Flathub-maintainer help. See `flatpak/STATUS.md`.

### Known limitations

- Generic Books cannot be searched (Whoosh indexes verse-keyed
  modules).
- Annotations and bookmarks are not yet extendable to genbook
  entries.
- Some long-form dictionaries (Webster's 1913) ship HTML markup
  that renders fine but isn't perfectly typeset.
- Module Manager doesn't filter out Maps / Images or
  "Cults / Unorthodox / Questionable Material" categories — they
  can be installed but won't render in panes.
