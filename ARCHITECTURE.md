# Scriptura — Architecture Brief

Internal architecture and design notes for anyone working on the
codebase. For the user-facing introduction, see [README.md](README.md).

## What we're building

A GNOME-native Bible study app for Linux. The goal is something like Logos Bible
Software but simpler: multiple resource panes (translations, commentaries,
lexicons, concordances, devotionals) navigable to a shared verse reference, with
a clean GNOME look and feel and an emphasis on quiet, distraction-free reading.

## Tech stack

- **Language:** Python 3 with PyGObject (GTK4 bindings)
- **UI toolkit:** GTK4 + libadwaita
- **Primary data layer:** SWORD Project library (`python3-sword` / `libsword`)
- **Secondary data layer:** eBible.org SQLite catalog (modern translations not
  available as SWORD modules — e.g. LEB, BSB)
- **Open data:** OpenBible.info cross-references + topics (CC-BY); Dodson Greek
  Lexicon (CC-BY). Downloaded on demand via Module Manager.
- **Text rendering:** Native `Gtk.TextView` + Pango markup (WebKitGTK was tried
  and reverted — do not suggest switching back)
- **Search:** SQLite FTS5 full-text indexing (per-module, lazy-built;
  shared query grammar across the SWORD and eBible backends — see
  `search_query.py`)
- **Build:** No build step; plain Python scripts
- **Platform:** Fedora Linux, GNOME desktop (Zorin Blue-Dark theme on this
  development machine; should work on any GNOME)

**Why native GtkTextView over WebKitGTK:** WebKit was implemented and replaced
by the user. Native GtkTextView starts faster, uses less memory, scrolls
smoothly, and inherits system fonts and theme colors without hardcoded values.

**Why SWORD:** CrossWire's SWORD Project provides a standardized module format
with thousands of free resources and a stable verse-reference data model.

## Architecture

Multi-pane layout. All panes can share an active verse reference; per-pane
sync toggles let the user lock a pane to its own location. Each pane has its
own module selector dropdown.

```
+----------------------------------------------------------------------------+
| HeaderBar  [menu] [back] [fwd]  [Book N v]  [Heb/Grk]  ...  [view] [srch] [bm] |
+----------------------------------+-----------------------------------------+
| [Module v] [lock][note][search]  | [Module v] [lock][note][search]         |
| Pane 1 — Bible / Commentary      | Pane 2 — Bible / Commentary /           |
| (Bibles render with chapter      |          Devotional                     |
| heading + drop-cap on v1)        |                                         |
|                                  |                                         |
+----------------------------------+-----------------------------------------+
| [Verse N:V]  cross-ref pills...                                       [x]  |
+----------------------------------------------------------------------------+

  Per-pane (below the Bible text): Lexicon panel
    [Definition view + clickable cross-numbers]  |  [Word study list]

  Overlays:  menu panel (left slide-in)   search panel (right slide-in)
             quick-jump bar (top, Ctrl+L)  F11 reading mode (hides chrome)
             dictionary popup on double-click of a plain word
```

## File layout

```
scriptura/
+-- ARCHITECTURE.md       # this file
+-- README.md             # user-facing overview, install, credits, license
+-- LICENSE               # GPL-3.0-or-later (canonical text)
+-- pytest.ini            # testpaths + pythonpath config
+-- requirements-dev.txt  # pytest + dev tools
+-- mypy.ini              # gradual strict-typing config (per-module sections)
+-- meson.build           # install rules (Flatpak builds via meson)
+-- main.py               # app entry, Adw.Application (io.github.andresmessina_SDG.Scriptura)
+-- i18n.py               # importable gettext helpers (_ / ngettext / N_ / book_label)
+-- window.py             # BibleWindow — header, panes, navigation funnels, About dialog
+-- pane.py               # BiblePane — text rendering, annotations, click handling
+-- pane_search.py        # PaneSearch — per-pane Ctrl+F bar + match highlight
+-- genbook_reader.py     # GenbookReader — Generic Books (TreeKey) subsystem extracted from pane.py
+-- catena_reader.py      # CatenaReader — verse-synced commentary card view (pane subsystem)
+-- imagery_reader.py     # ImageryReader — Art/Where tabs, traditions expander, zoom viewer
+-- archaeology_reader.py # ArchaeologyReader — Scripture in Stone bundled gallery
+-- styles.py             # Loads data/style.css once at startup; per-pane dynamic CSS stays in pane.py
+-- lexicon_panel.py      # LexiconPanel — definition view + word study (own class)
+-- annotation_dialogs.py # Right-click study menu, note editor, chapter note, compare translations
+-- devotional.py         # Devotional OSIS rendering (Spurgeon-style multi-section labels)
+-- sword_bridge.py       # SWORD library wrapper + FTS5 indexing
+-- search_query.py       # Shared user-query → FTS5 MATCH grammar translator
+-- ebible_bridge.py      # eBible.org SQLite translation backend
+-- catena_bridge.py      # Historical Commentaries pack — SQLite query layer + download/install
+-- imagery_bridge.py     # Scripture in Art pack — SQLite query layer + multi-part download
+-- archaeology_bridge.py # Scripture in Stone — bundled artifact catalog
+-- content.py            # Routing facade — which bridge owns a module key (names/display/info/remove)
+-- open_data.py          # OpenBible refs/topics + Dodson Greek (CC-BY)
+-- paths.py              # XDG config/data/cache resolution + legacy-file migration
+-- annotations.py        # Per-verse JSON persistence
+-- bookmarks.py          # Bookmark list
+-- settings.py           # User preferences (debounced atomic writes)
+-- module_positions.py   # Per-module scroll/entry-path memory shared across panes
+-- reading_plans.py      # Built-in plans + progress
+-- search_panel.py       # Search overlay (right-side revealer)
+-- study_journal.py      # Study Journal window (master-detail) + TagManagerWindow
+-- crossref_panel.py     # Cross-reference bar (slim single row)
+-- module_manager.py     # Module Manager (kind tabs: Bibles / Commentaries / Study Tools / Books & More, all sources merged per tab)
+-- module_picker.py      # ModulePicker — pane's module selector (MenuButton popover, info, remove)
+-- welcome.py            # First-run welcome: 3 curated bundle choices (reading / study / full)
+-- empty_state.py        # Shared compact empty-state widget
+-- a11y.py               # set_accessible_label helper
+-- po/                   # gettext scaffolding (LINGUAS, POTFILES.in)
+-- tools/                # offline pack builders (dev-only, not shipped)
|   +-- build_catena_pack.py   # HCF database -> catena pack
|   +-- build_imagery_pack.py  # ten ingest sources -> imagery pack (see *_plates.toml)
|   +-- gen_tissot.py          # Tissot plate-list generator
+-- tests/                # Pytest suite for the pure-Python bridges + helpers
+-- flatpak/              # manifest patches (e.g. sword-curl-libraries.patch)
+-- data/
|   +-- icons/             # app + bundled symbolic icons
|   +-- io.github.andresmessina_SDG.Scriptura.desktop
|   +-- style.css          # Centralised application stylesheet (loaded by styles.py)
```

User-mutable state does **not** live in the tree: `paths.py` resolves
settings/bookmarks/plans/positions to `$XDG_CONFIG_HOME/bible-reader/`,
annotations + the eBible DB + downloaded packs/open-data to
`$XDG_DATA_HOME/bible-reader/`, and search history + the eBible catalog
to `$XDG_CACHE_HOME/bible-reader/` (with one-shot migration of legacy
in-tree files).

### Naming convention: `Bible*` vs `Scriptura`

Internal class names use `Bible*` (`BibleApp`, `BibleWindow`,
`BiblePane`); the user-facing brand is "Scriptura". This split is
deliberate — `Bible` describes the *domain* (what the objects work
on), `Scriptura` is the *product name*. Same pattern most apps
follow (Firefox's classes aren't `Firefox*`). The app-ID, window
title, About dialog, desktop entry, and `.flatpak` all use
Scriptura; the class hierarchy stays domain-named so it remains
accurate if the product is ever rebranded again.

If you're grepping for the main application class and expected
`ScripturaApp`, it's `BibleApp` in `main.py`.

## pane.py — key internals

### Rendering pipeline

- `_html_to_markup(html, dark, strip=True)` — converts SWORD `renderText()`
  output to Pango markup. Pipeline: map known tags to placeholder tokens →
  strip remaining HTML → `GLib.markup_escape_text()` → swap tokens back to
  Pango spans. Annotation styling (highlight/underline/note) is **not** baked
  in here — those are named buffer tags applied after insertion (see "in-place
  annotations" below). `strip=False` keeps inter-segment whitespace for the
  commentary reference-splitting path.

- `_extract_segments(html)` → `[(text, strong_num, morph)]` for per-word
  Strong's tagging. Captures both `lemma="strong:..."` and `savlm="strong:..."`
  plus `morph="robinson:..."`.

- `_make_verse_markup(html, target_strong)` — verse markup with words matching
  `target_strong` rendered bold. Used by the word study panel.

### Per-verse tagging

- Each verse range gets a named TextTag `vnum_N` (covers verse number + text).
- Verse text range (excluding the gray number prefix) is targeted by the
  annotation helpers via `_verse_ranges(N)` which returns
  `(vnum_start, vtext_start, vtext_end)`. `vtext_start = vnum_start +
  len(str(N)) + 2 chars` (the " N " prefix).

### In-place annotations (recent, important)

Highlights, underlines, and note indicators are applied as **named buffer
tags**, not baked into Pango markup. This means right-click annotation changes
are pure tag-application — no `set_text` / re-render / scroll restoration.
Scroll position is genuinely untouched.

- `hl_bg_<hex>` tag — **zero-visual marker** (no properties). The highlight
  is *painted* as a uniform band by `BibleTextView` (see "Highlight bands"
  below); this tag only records the verse's range + color (parsed back from
  the name). A separate `hl_fg` tag (`foreground=black`) covers the verse
  *text* so it stays readable on the band, leaving the gray verse number on
  the tint. Soft palette via `_HIGHLIGHT_RENDER` (stored colors map to softer
  rendered colors; existing JSON data unchanged).
- `_ul_text` tag — `underline=Pango.Underline.DOUBLE`. Applied to verse text.
- `_note_marker` tag — `foreground=#5b8def, weight=BOLD`. Applied to verse
  *number* only — gives notes a subtle accent-colored number instead of the
  old 📝 emoji at end of verse.

`_apply_anno_tags(verse_num, anno)` — idempotent: clears any prior annotation
tags from the verse's ranges, then applies new ones from the anno dict. Bumps
each tag's priority to `table.get_size() - 1` on every apply, so subsequent
chapter renders don't out-prioritize the persistent tags via newly-created
anonymous insert_markup tags.

`_refresh_verse_annotation(verse_num)` — re-reads `annotations.get_annotations`
and calls `_apply_anno_tags`. Called from `_apply_highlight`,
`_toggle_underline`, and `_save_note_window` instead of any `_fetch_and_render`.

### Highlight bands (`BibleTextView`) — important

Verse highlights, search matches, and the navigation flash are **painted by
`BibleTextView.do_snapshot`**, not drawn as GTK tag backgrounds. A tag
`background` hugs each line's run/line metrics, so the 200% verse-1 drop cap
(which makes its wrapped line ~2× taller) and the small superscript verse
numbers (shorter runs) produced uneven block heights and notches/gaps. The
painter instead draws each line of a highlight as a band of
`body_height + 2·pad`, anchored to the **display-line start** (every band on a
line shares one top, so a verse that begins mid-line with the raised number
can't drift). Bands are drawn before the text (chained `super().do_snapshot`);
the `.bible-view` background is transparent, so they sit behind the glyphs.

Three stacked layers, bottom to top, via `_draw_tag_layer`: verse highlights
(`hl_bg_<hex>`), search matches (`_search_hl`, amber `_SEARCH_COLOR`), and the
navigation flash (`_flash`, yellow `_FLASH_COLOR`) — all **zero-visual marker
tags** the painter reads ranges/colors from.

**Don't** give these tags a `background=` property — that reintroduces the
line-height/notch problems. When their ranges change, repaint with
`self._view.queue_draw()` (done in `_apply_anno_tags`, the search apply/clear/
expire, the flash apply/expire, and `_cancel_all_flashes`; also on appearance
changes in `_update_font_css`).

### Scroll stability — the "north star" invariant (recent, important)

The reading text's position is fixed; chrome and side effects move around
it. Never regress these mechanisms:

- **Chrome overlays, never reflows.** The pane toolbar / date nav /
  find bar live in `_chrome_band`, an overlay child (`Gtk.Overlay`) above
  the reading page. The band's strip is reserved as `margin_top` on the
  page card (`_sync_view_top_margin`) so the card keeps its original
  below-the-toolbar look. Auto-hide reclaims the strip via
  `_animate_page_strip`: each frame moves the card top by dm AND the
  scroll value by dm, so hiding unveils earlier text while the glyphs
  stay screen-fixed (fresh-chapter renders snap it open uncompensated —
  there is no locus to preserve). Reading mode reuses the same animation
  (a hidden toolbar measures 0).
- **The window split is fraction-pinned** (`_FractionPaned`, window.py):
  a plain GtkPaned with no set position re-derives the divider from the
  children's natural widths, so the lexicon panel appearing/loading
  wobbled both reading columns horizontally. The divider follows a
  width-fraction (user drags update it) and ignores child requests.
- **The reading anchor** (`_reading_anchor`: verse, visible-char offset,
  intra-line px delta) is the persisted reading locus. Captured after
  user scrolls settle (250ms debounce) and after programmatic jumps;
  cleared only by user scrolls and navigation — **not** by re-renders.
  Content-mutating re-renders (footnote toggle, theme flip) restore it
  via `_apply_scroll_anchor`: `scroll_to_mark` for rough placement, then
  corrective `set_value` polls until the anchor's y stops moving (GTK
  revalidates line-height estimates long after render/resize).
  Offsets count **visible chars only** (skip `fnote:`-tagged marker
  glyphs) so they round-trip between marker states. Capture snaps along
  display lines against the **converted** buffer y (`window_to_buffer_coords`
  subtracts the top margin — never compare `get_iter_location` values
  against raw adjustment values).
- **Viewport resizes re-assert the anchor** (`_on_viewport_resized` via
  `_ReadingScrolledWindow.on_height_change`): a resize makes GTK correct
  its line-height estimates, silently shifting which text sits under a
  constant adjustment value (this was the "first lexicon click moves the
  text" bug).
- **Lexicon toggle never re-renders** — Strong's/morph/phrase tags are
  applied/removed in place (`_tag_strong_words_in_place` /
  `_remove_strong_tags`); commentaries are a no-op.
- **Auto-hide listens to the reader, not the layout.** `value-changed`
  cannot distinguish user scrolling from validation churn, so
  `_on_reading_scroll` only acts when a scroll input was seen recently
  (wheel/scroll-keys/scrollbar controllers → `_user_scroll_recent`), and
  `_mark_programmatic_scroll` shields known code-driven scrolls.
- **Fetch generations** (`_fetch_gen`): only the newest requested render
  may display. Without it, rapid toggling (faster than the fetch thread)
  landed two `_display` calls for the same chapter — the second found no
  scroll restore and jumped to the chapter start.

Verified headless (broadway + scratch XDG dirs): every interaction above
holds the top-of-viewport text to 0px; footnote toggling 10× cumulative
drift is 0px. The committed regression matrix is
`tools/verify-scroll-stability.py` — one command, spawns its own
broadwayd, quiescence-gated judgments, retry-once for Broadway flakiness
— and CI runs it on every push (the `scroll-stability` step in
`.woodpecker.yml`). Run it after touching pane.py scroll/render/chrome
code or window.py pane sizing.

### Strong's hover model

- Strong's-tagged words no longer carry a static underline (the wall of
  underlines made every page look like a contract).
- A `Gtk.EventControllerMotion` on the textview tracks the cursor. When over
  a `strg:`-tagged word, a transient `_strg_hover` tag (single underline +
  soft accent foreground) is applied to that word's range. Removed when the
  cursor leaves the word or the view.
- Word boundaries detected with `iter.backward_word_start()` /
  `forward_word_end()` (same pattern as the dict popup).
- Motion handler bails when `_lexicon_enabled` is False so non-Strong's
  Bibles aren't affected.

### Other notable bits

- **Chapter heading** — muted `[Book Chapter]` rendered at top of buffer for
  Bibles (not commentaries). Scrolls with the text.
- **Drop-cap on v1** — first letter rendered at `size="200%" weight="bold"`
  (no `rise` — a negative rise once caused scroll ghost-fragments) via a regex
  that skips leading Pango span tags. Always shown; it rises above the uniform
  highlight band rather than inflating the block.
- **Soft highlight palette** — `_HIGHLIGHT_RENDER` maps the four stored
  highlight colors to muted pastels for rendering. Storage values unchanged
  so legacy annotations.json data still loads.
- **Flash highlight** — `_flash_verse(N)` applies a zero-visual `_flash`
  marker tag (painted as a yellow band by `BibleTextView`, top layer; black-fg
  text), priority bumped to top, with
  per-flash independent timers held in `self._flash_timers: set[int]` so
  rapid clicks don't cancel each other. `_cancel_all_flashes()` runs before
  `set_text('')` in `_display` / `_display_devotional` to clear stale flashes.
- **Scroll** — `_scroll_to_verse(N)` uses `scroll_to_mark` (not
  `scroll_to_iter`) because line heights are stale right after a chapter
  render. Defers `_flash_verse` by 150ms so the scroll fully settles before
  the flash applies (verses deep in long chapters would otherwise flash off
  screen).
- **Right-click menu** — 4 highlight colors (yellow/green/blue/orange),
  underline, note editor (Adw.Window, not popover — see "popover lifecycle"
  below), copy verse, compare translations. Multi-verse selection supported
  (highlight/underline/copy all selected verses).
- **Dictionary popup** — double-click any word opens an Adw.Window with
  tabbed Easton's/Smith's results. Strong's-tagged words also trigger this
  on double-click (the lexicon panel opens on the first click of the same
  double-click).
- **Devotional support** — `_is_devotional` detected on construction;
  separate render path `_render_devotional_osis` with date navigation.
  Detects multi-section devotionals (SME — Spurgeon Morning & Evening) and
  labels them.
- **Sync** — per-pane lock button. When a pane is locked, it ignores
  window-level navigation (sync_btn `active=True` returns from
  `load_reference*`). On unlock, `_on_sync_toggled` catches up to the
  window's current location. Auto-unlocks when switching from a devotional
  module to a Bible.
- **Reading column cap** — TextView is a direct child of a custom
  `_ReadingScrolledWindow` subclass that pushes symmetric
  `left_margin`/`right_margin` onto the view on every `size_allocate`,
  so the column stays centered and the scrollbar sits at the pane's
  outer edge (not inside the column). User-tunable via the Width slider
  in the Text Appearance card (range 540–1600 px, default 720, stored
  in `settings.reading_width`). **Earlier `Adw.Clamp(ScrolledWindow)` is
  gone** — it kept TextView a Gtk.Scrollable direct child but forced
  the scrollbar inside the reading column, which the user disliked.
  Clamping the TextView itself still forces a Viewport that breaks
  `scroll_to_iter` — don't go back to that path.
- **Footnotes** — translator notes as clickable superscript labels
  (a b c … z aa ab, bijective base-26 via `_fn_label`, so every note in
  a chapter is unique; chapter-continuous, print-Bible style). Rendered
  as plain letters in a `rise`+`size` span, not Unicode superscript
  glyphs — the superscript block has no q. Toggled by the *f\** header
  button (linked pair with אΩ; persisted as `settings.show_footnotes`,
  default **on** — safe because markers only appear where notes exist).
  The window disables the toggle (tooltip explains, layout stays put)
  when neither pane's module can show notes: `content.has_footnotes`
  dispatches to `sword_bridge.module_has_footnotes` (conf declares a
  `*Footnotes` `GlobalOptionFilter`; walks `getConfigMap().items()` —
  `getConfigEntry` only returns the FIRST repeated key) or
  `ebible_bridge.module_has_footnotes` (any stored notes rows), and
  re-evaluates via the panes' `on_module_switched` callback plus
  `_on_modules_changed`. Pipeline: both backends leave an empty
  `<note swordFootnote="N"/>` anchor per note (SWORD bodies live in
  entry attributes, eBible bodies in the `notes` table — see each
  bridge's `chapter_footnotes`); `_display` swaps anchors to `[[FN_n]]`
  tokens before `_html_to_markup` (markers-off = the generic strip
  removing them, i.e. the pre-feature rendering), then
  `_substitute_footnote_markers` turns tokens into styled labels on the
  **final markup string** — for Bibles never segmented insertion, so
  Pango spans crossing an anchor (red-letter text) stay paired — and
  returns plain-text offsets for `_apply_footnote_tags` to tag
  `fnote:{verse}:{n}` ranges by offset arithmetic (no buffer search).
  Commentaries run the same substitution **per plain segment** inside
  `_insert_commentary_body` (insertion there is segmented around
  `<reference>` links, so offsets are taken against each segment's own
  start mark). Click → note body in the shared peek popover
  (`_ensure_peek_popover`, same instance + dismissal paths as the dict
  peek; opens at full opacity — no fetch, and a footnote click
  deliberately doesn't broadcast verse selection, so no cross-pane
  reflow). Hit-test probes ±1 char around the clicked iter: a click on
  a glyph's right half resolves to the *next* character, which missed
  half of every marker's width.
- **Module picker** — `pane.module_drop` is a `Gtk.MenuButton` (was
  `Gtk.DropDown`) opening a popover with a two-page `Gtk.Stack`: a list
  page (SearchEntry + language chip row + scrollable module list, each
  row with an ⓘ button) and an info page (description / language /
  version / type / copyright / license / about). `_apply_module_change
  (name)` takes a module name string and applies all the side effects;
  the picker row activation drives it. `_module_lang_cache` is a
  class-level memoization so the picker doesn't probe SWORD or eBible
  on every keystroke.

## window.py — key internals

- `_go_to(book, chapter, verse, record)` — central navigation. Updates the
  hidden book/chapter dropdowns and the visible "Book N" ref button, then
  calls `pane.load_reference(_at_verse)` on both panes.
- `book_drop` / `chapter_drop` — kept alive as state holders but `set_visible(False)`.
  Navigation flows through `_go_to`, the combined Book+Chapter popover, the
  quick-jump bar, or Alt+arrows — never via direct user manipulation of
  the dropdowns. The old `_on_book_changed` / `_on_chapter_changed` handlers
  have been removed.
- **Combined Book + Chapter popover** (`_ref_btn`, `_build_ref_popover_content`)
  — 420×360 popover with `Gtk.ListBox` of 66 books on the left, `Gtk.FlowBox`
  of chapter buttons (4-per-row) on the right. Clicking a chapter calls
  `_go_to(book, ch)` directly.
- **Toast overlay** — `self._toast_overlay = Adw.ToastOverlay()` wraps the
  main content. `self._toast(msg)` helper emits transient toasts (2s) for
  bookmark add/remove, copy-verse, etc.
- **Reading mode** — F11 toggles `self._reading_mode`. On entry: hides
  `Adw.HeaderBar`, both pane toolbars (`pane._toolbar` references), dismisses
  any open overlay panels. Exit affordance: a circular `window-close-symbolic`
  button in a SLIDE_DOWN revealer at top-center reveals after the cursor
  sits in the top 12px hot zone for 2s, stays visible while the cursor is
  within 80px of the top, hides on cursor-out / leave / mode-exit. Motion
  controller attached to `self` (the window), not the overlay, so events
  reach us regardless of which child widget has the cursor.
- **Recent passages** — `document-open-recent-symbolic` button between
  forward and the title button. Popover shows the last 10 distinct
  `(book, chapter)` pairs (`settings.recent_passages`), deduped, with a
  trash icon to clear. `_push_recent` called from `_go_to` only when
  `record=True` (back/forward stack moves and initial restore don't push).
- **Cross-ref clicks** target pane 2 in split mode, pane 1 in single-pane mode
  (with fallback if pane 2 is on a devotional / sync-locked).
- **Global shortcuts are window GActions** registered in
  `_install_actions` with `app.set_accels_for_action`. GTK dispatches
  these via a global-scope shortcut controller that fires regardless of
  which widget (if any) holds focus — so they survive the NULL-focus a
  window-level `EventControllerKey` could not (fresh launch, suspend/
  resume, a popover closing). Only the contextual keys — `Esc` and
  `Home`/`End` — stay on a CAPTURE-phase key controller, and the reading
  view grabs focus on first map so those work from launch too.
- **Keyboard shortcuts** (the bindings; all but Esc/Home/End are actions):
  - `Ctrl+=` / `Ctrl+-` — font size (also `Ctrl+scroll` and touchpad
    pinch — see `BiblePane._on_zoom_scroll` / `_on_zoom_gesture`)
  - `Ctrl+L` — quick jump bar
  - `Ctrl+F` — open / close window search panel
  - `F3` / `Shift+F3` — next / previous search result. Routes to whichever
    surface has cached results (window panel preferred; falls back to
    re-revealing a closed panel if results are still in memory).
  - `Alt+←/→` — prev/next chapter (wraps across books)
  - `Alt+↑/↓` — prev/next book
  - `Home` / `End` — first / last verse of current chapter (gated on
    `_focus_is_text_input()` so typing in entries still works)
  - `Ctrl+1` / `Ctrl+2` / `Ctrl+Tab` — focus pane / cycle panes
  - Mouse wheel over the Book/Chapter title button — cycle chapters
  - `Esc` — dismiss jump bar, search panel, menu panel, or exit reading mode
  - `F11` — reading mode
- **Book/Chapter popover** with right-click verse picker. The right
  column is a `Gtk.Stack(SLIDE_LEFT_RIGHT, 180ms)` flipping between a
  chapter FlowBox and a verse FlowBox. Left-click on a chapter still
  navigates immediately; right-click slides over to the verse picker for
  that chapter. Title flips from "Chapter" to "Chapter N Verse"; a back
  button appears in the verse view. Uses `sword_bridge.verse_count`
  (wraps `VerseKey.getVerseMax()`).
- **Menu panel (left overlay)** — burger button opens. Contains: Study
  Journal button, Modules button, Text Appearance toggle (font family, size,
  line spacing, bold, justify, color, **reading column width**),
  Hotkeys reference, Reading Plan selector + day list with progress.

## sword_bridge.py — key internals

- `load_chapter(module, book, chapter)` — thread-safe (RLock), in-memory
  cache, returns `[(verse_num, rendered_html)]`. Falls back to `ebible_bridge`
  for eBible modules.
- `get_cross_refs(book, chapter, verse)` — tries `open_data.get_cross_refs()`
  first; falls back to the SWORD TSK module. OpenBible has ~5× more refs
  than TSK.
- `lookup_strong(strong_num)` — tries `open_data.lookup_dodson()` first for
  Greek; falls back to SWORD `StrongsHebrew` / `StrongsGreek` modules. Uses
  `mod.setKeyText()` + `mod.getRawEntry()` (NOT `setKey/renderText` — see
  SWORD quirks).
- `lookup_dict_word(word)` — looks up English dictionaries (Easton, Smith).
  Creates a fresh `Sword.SWMgr()` per call because a failed `setKeyText`
  corrupts subsequent lookups. Calls `getRawEntry()` unconditionally to clear
  the internal error state.
- `lookup_morph_for_strong(book, ch, v, strong)` — MorphGNT lookup for Greek
  morphology. Pairs with `decode_robinson(morph)` which converts
  `robinson:V-2AAI-3S` to readable strings.
- `lookup_morph_for_strong_heb(...)` + `decode_hebrew_morph(...)` — OSHB
  morphology for Hebrew.
- `search_module(module, query)` — FTS5 full-text search via the shared
  `search_query` grammar (phrase / AND / OR / exclude / prefix). Lazy-builds
  a per-module FTS5 index (`~/.sword/fts5_indexes/<module>.db`) on first use
  (background thread, atomic rename). Canonical (rowid) result order. Max
  5000 results. The eBible backend uses the same grammar over an
  external-content FTS5 table in `ebible.db`.
- `chapter_footnotes(module, book, chapter)` → `{verse: [(marker_index,
  type, body_html), ...]}`. The main SWMgr always renders with
  `setGlobalOption('Footnotes', 'On')`; `load_chapter`'s render pass
  reads each verse's note bodies out of `getEntryAttributesMap()
  ['Footnote']` (must happen right after `renderText()` — the next
  render replaces the map) into `_notes_cache`, evicted in lockstep
  with the chapter cache. `marker_index` matches the `swordFootnote="N"`
  attribute on the inline anchor. OSIS `type` distinguishes
  `crossReference` / `study` / `variant` / plain.
- `module_has_footnotes(module)` — conf-level capability probe (does any
  `GlobalOptionFilter` line name a `*Footnotes` filter). Must walk
  `getConfigMap().items()`: `getConfigEntry` returns only the first of a
  repeated conf key, and e.g. SBLGNT lists `UTF8GreekAccents` first.
- `get_devotional_raw(module, date)` / `load_devotional(...)` — fresh SWMgr
  per call for the same reason as dict lookup.
- `parse_devotional_refs(raw_osis)` — extracts the first `osisRef` from a
  devotional entry. Used to navigate pane 1 to the day's passage on startup.
- `_OSIS_BOOKS` — book-abbreviation map used by `parse_osis_ref()`.
- `_parse_conf(path)` — reads a SWORD `.conf` file with `utf-8-sig`
  (BOM-safe) and backslash line-continuation handling. The actual
  parsing lives in `_parse_conf_lines(lines)` so the same logic works on
  `.conf` text pulled straight from a zip in memory.
- **Module sideload** (import a `.zip` you already have, no network):
  `inspect_module_zip(bytes)` validates the archive and returns one dict
  per module (name, type, lang, version, size, locked, installed,
  installed_version) without writing anything; `install_module_from_zip`
  extracts only the chosen modules' conf + datapath, guarded by
  `_safe_extract` against zip-slip paths. `cmp_version` drives the
  install/update/reinstall/replace label. The UI side is the import
  button + drag-target + preview sheet in `module_manager.py`.
- **Cipher-locked modules:** `is_encrypted_module(name)` reports whether
  a conf declares a `CipherKey`; `set_cipher_key(name, key)` writes the
  key and resets. A wrong key decrypts to garbage, which the pane catches
  on render (see `_printable_ratio` / `_display_cipher_locked`) and the
  window turns into an "Edit Key" toast.
- **Cross-versification mapping** — app-space references (navigation,
  pane sync, bookmarks, TSK cross-refs, annotation keys) are KJV-shaped;
  modules keyed to another system (Vulg, Synodal, …) number the same
  text differently, most visibly the Greek/Latin psalter (one behind the
  KJV for most of the book). `VerseKey.positionFrom` applies the
  engine's av11n tables; a per-(module, book) chapter map — each app
  chapter anchored by its first verse, cached in `_book_maps`, adopted
  only when non-identity — translates inside `load_chapter`,
  `chapter_count`, `verse_count` and `chapter_in_index`, and
  `map_target_verse` converts a verse target for the pane scroll
  (`pane._display`). Merged chapters (KJV Ps 9+10 = Vulg 9) share a
  target; split chapters (KJV Ps 116 = Vulg 114+115) render the anchor
  chapter and lose direct access to the split-off tail — range-rendering
  across module chapters is the known follow-up if that residue matters.
  Systems without mapping tables read back as identity and keep plain
  module-space behavior. Verse numbers shown are always the module's own
  printed numbering (Vulgate title-verses shift by one). FTS index rows
  store app-space chapter numbers (`_FTS_INDEX_VERSION` 2).

## Historical Commentaries (catena)

A fourth pane mode (`_is_catena` in pane.py, alongside `_is_devotional`
and `_is_genbook`) showing how the church read each verse across time.

- **The pack** is a single SQLite file built offline by
  `tools/build_catena_pack.py` from a checkout of the
  [HistoricalChristianFaith Commentaries Database]. The builder keeps
  only public-domain authors (those before a 1928 cutoff — the upstream's
  fair-use excerpts aren't ours to redistribute), normalises book names,
  derives a church-history era from each author's year, and writes one
  denormalised `quotes` table (verse keys encoded as
  `chapter*1_000_000 + verse`, so a range row's `[loc_start, loc_end]`
  span surfaces on every verse it covers) plus a `pack_meta` table. It's
  hosted gzipped (~31 MB) on GitHub Releases and downloaded on demand —
  never bundled in the Flatpak.
- **`catena_bridge.py`** is the read layer: a read-only thread-local
  connection (reopened via a generation counter when the pack is
  installed/removed), `lookup(book, ch, v)` returning `CatenaEntry`
  dicts oldest-first, install-state, `pack_info()`, and
  `download_and_install()` (stream gz → gunzip → atomic rename).
- **`catena_reader.py`** (`CatenaReader`) is the pane subsystem,
  mirroring `genbook_reader`'s shape: chronological cards grouped by era,
  a per-author filter, lazy quote previews. The pane hosts it in a
  `Gtk.Stack` that flips between the flowing reading view and the card
  view; it follows the partnered Bible pane via `load_reference` /
  `select_verse`.
- **Module Manager** lists the pack in the Open Databases tab
  (Download/Remove); install/remove refresh both panes' pickers.

## Scripture in Art (imagery)

A verse-synced imagery pane mode (`_is_imagery` in pane.py), three layers:
narrative **art**, **maps**, and **photos of the places** named in the verse.

- **The pack** is a directory (`$XDG_DATA_HOME/bible-reader/imagery/`)
  holding `imagery.sqlite` plus an `images/` tree, built offline by
  `tools/build_imagery_pack.py` from ten ingest sources, each driven by a
  hand-curated per-plate TOML in `tools/`: Schnorr + Doré engravings,
  Tissot watercolours (via `gen_tissot.py`), Byzantine icons, stained
  glass, Old Master oils, illuminated manuscripts, OpenBible place photos,
  Hurlbut atlas maps, and modern PD vector SVG journey maps. Verse ranges
  use the catena encoding (`chapter*1_000_000 + verse`, `[loc_start,
  loc_end]`). Hosted on GitHub Releases; large pack — downloaded on
  demand with multi-part support (`imagery_bridge._resolve_parts`).
- **`imagery_bridge.py`** is the read layer: read-only thread-local
  connection with a generation counter, `art_for` / `maps_for` /
  `places_for(book, ch, v)`. Items carry `book`/`chapter`/`verse` decoded
  from `loc_start` — the navigation target for the reader's clickable map
  passage chips.
- **`imagery_reader.py`** (`ImageryReader`) renders two tabs: **Art**
  (house engraving first, the rest behind a "See this scene in other
  traditions" expander) and **Where** (modern map first, then antique
  maps, then place cards with credit + a low-confidence cue). Cards
  click-through to a zoom/pan dialog (`_ZoomViewer`: pinch, drag,
  header-bar zoom buttons). Map cards carry an outline passage chip that
  drives the partnered Bible pane to the start of the covered range.
- **Catena cross-link:** the catena pane shows outline chips for the
  places named in the verse under commentary (`imagery_bridge.places_for`,
  silent when the pack isn't installed); clicking opens a small place
  dialog (`imagery_reader.present_place_dialog`) — photo, identification,
  credit — rather than swapping a pane to the imagery module.

## Scripture in Stone (archaeology)

A bundled (not downloaded) standalone gallery of biblical-world artifacts
(`archaeology_bridge.py` + `archaeology_reader.py`; `_is_archaeology` pane
mode). Not verse-synced — it renders once; its verse chips drive the
partnered Bible pane, and Bible verses that an artifact attests carry a
small inline amphora marker that opens the gallery scrolled to that
artifact (`window._on_open_artifact`).

## open_data.py — key internals

- `_OSIS_BOOKS` — local copy of book abbreviations (to avoid circular import
  from sword_bridge).
- `_osis_to_vids(s)` — converts `Gen.1.1` or `Exod.20.1-Exod.20.26` to
  8-digit numeric verse IDs. Expands single-chapter ranges; clips
  cross-chapter / cross-book ranges to the start verse.
- `get_cross_refs(book, ch, v)` → `[(book, ch, v, label), ...]` or `None` if
  the file isn't downloaded.
- `get_topics(book, ch, v)` → list of CC-BY topic tags. Used by the
  annotation "Suggested topics" chip row in the note editor.
- `lookup_dodson(strong_num)` → readable NT Greek definition.
- `download_source(id)` — fetches + extracts OpenBible cross-references ZIP,
  topics ZIP, or Dodson CSV into `data/`.

## Logging

App-wide logging lives on the `scriptura.*` logger tree. `main.py` calls
`_setup_logging()` before any module import, which:

- reads `SCRIPTURA_LOG_LEVEL` (default `WARNING`),
- attaches one `StreamHandler` to the `scriptura` logger with format
  `name [LEVEL] message`,
- sets `propagate = False` so we don't double-print through the root logger.

Each module declares its own logger near the top of the file, e.g.
`_log = logging.getLogger('scriptura.sword')`. Component names preserve
the historical `[tag]` prefixes used before the migration — including
the deliberate split inside `sword_bridge.py`, which carries both
`scriptura.sword` (module load / verse keys / genbook walks) and
`scriptura.search` (index build / FTS5 query path).

Convention: `_log.exception(msg)` inside `except` blocks (logs at ERROR
with the traceback — the main reason this exists is debugging weird
SWORD setups from user reports), `_log.info(msg)` for one-shot
informational events like the legacy-file migrations in `paths.py`.
There are no `_log.debug()` sites yet; they're available when a tricky
bug needs them.

To debug a user report: `SCRIPTURA_LOG_LEVEL=DEBUG python3 main.py`.
The Flatpak install writes the same stream to the journal — viewable
with `journalctl --user -f` while the app runs.

## Type hints (gradual)

Scriptura uses gradual typing. The persistence layer is fully
annotated and mypy-clean: `paths`, `bookmarks`, `settings`,
`annotations`, `module_positions`, `reading_plans`. TypedDicts capture
the on-disk shapes (`Bookmark`, `Plan`, `ChapterNoteData`,
`PlanSummary`).

Conventions:

- **Modern syntax.** PEP 585 (`list[str]`, `dict[str, Any]`) and
  PEP 604 (`str | None`). No `from typing import List, Optional`
  in new code. `python_version = 3.10` in `mypy.ini`.
- **`dict[str, Any]` at the JSON I/O boundary.** Real on-disk data is
  schemaless across versions; helpers narrow via `isinstance()` once
  inside. Using `cast()` at the I/O boundary is preferred over
  `# type: ignore`.
- **mypy scope widens module-by-module.** `mypy.ini` enforces
  `disallow_untyped_defs` only on already-typed modules. Other
  modules are listed in the `[mypy-…] ignore_errors = True` section
  at the bottom; when you finish typing a file, move it from the
  ignore list to the strict list.

Run: `mypy .` (uses `mypy.ini`; excludes `build-dir/`).

## annotations.py

Per-verse study data persisted in `annotations.json`. Key format:
`"{module}/{book}/{chapter}"` → `{"{verse}": {...}, "chapter_note": {...}}`.

Per-verse value shape:
```
{
  "highlight": "#ffff00" | null,   # stored colors (mapped to soft tints at render time)
  "underline": bool,
  "note": "text" | null,
  "tags": ["topic1", "topic2", ...]
}
```

Chapter note: same shape (note + tags) under the `"chapter_note"` key.
Includes migration logic for old single-color string format.

## Critical SWORD Python binding quirks

- **Dict modules** (Strongs, Easton, Smith): use `mod.setKeyText(key)` +
  `mod.getRawEntry()`. NOT `setKey/renderText/stripText` (broken).
- `setKeyText()` with a non-existent key corrupts module key state for
  subsequent calls. **Fix:** create a fresh `Sword.SWMgr()` per dict lookup.
- After a failed `setKeyText`, call `getRawEntry()` unconditionally — it
  clears the internal error state so the next `setKeyText` variant works.
- Validate matches: `mod.getKeyText().lstrip('0') == num_bare` (SWORD snaps
  to the last entry on miss).
- **StrongsHebrew key:** 5-digit zero-padded, no `H` prefix (`"00430"`).
- **Easton/Smith keys:** ALL CAPS (`"CHRIST"`, `"ADAM"`).
- **KJVA `<w>` attribute:** uses `savlm="strong:..."` not `lemma=` —
  `_extract_segments()` handles both.
- **Commentary modules** (TSK, MHC, MHCC): use `mod.setKey(VerseKey)` +
  `mod.renderText()` (the dict-module quirks above don't apply).
- **Plain KJV** has no `<w>` tags → Strong's doesn't work; recommend KJVA.
- **Non-UTF-8 dict data:** some SWORD dict modules contain lone surrogates;
  strip them in `_html_to_markup()` before `GLib.markup_escape_text()`.

## Critical GTK4 / Wayland quirks

- **`Adw.Clamp` around a `Gtk.TextView`** forces GTK to inject a Viewport
  (Clamp isn't `Gtk.Scrollable`), and `TextView.scroll_to_iter()` doesn't
  propagate through it. Always clamp the `ScrolledWindow`, not the TextView.
- **`scroll_to_iter` uses currently-computed line heights**, which are stale
  right after a `set_text` / `insert_markup`. Always use `scroll_to_mark`
  with a temporary `TextMark` for post-render scrolling.
- **Tag-priority decay:** tags created earlier have lower priority. Anonymous
  tags from `insert_markup` get created on every chapter render — so any
  long-lived tag (flash, annotation, note marker) needs its priority bumped
  to `table.get_size() - 1` before each apply.
- **`get_iter_at_location` returns False** for points inside the textview's
  `left_margin`. Always probe at `rect.x + max(40, rect.width // 2)`.
- **Popover-inside-popover on Wayland:** the parent's `closed` signal can
  fire synchronously inside `popdown()`, and the standard
  `lambda p: p.unparent()` cleanup races with the new popover's surface
  creation → use-after-free + segfault. **Workaround:** use `Adw.Window` for
  dialogs that originate from inside a popover (note editor, dict popup),
  not nested popovers.
- **`Pango.Underline`** has no DOTTED variant. Use `SINGLE` with a soft
  foreground color for subtle underlines, or no underline at all for
  hover-only schemes.
- **Buffer marks** are deleted by `Gtk.TextBuffer.set_text('')`. Don't try
  to preserve scroll position by saving a mark across a set_text.
- **`set_text('')` does NOT remove tags from the tag table**, only
  unapplies them from now-removed content. The tag table grows
  unbounded if you create named tags per chapter render — `vnum_N`,
  `strg:G…`, `morph:…`, `phrase:…`, `devref:…` all accumulate.
  `_clear_chapter_scoped_tags()` (called in every render path right
  after `set_text('')`) walks the table via `foreach` and removes
  tags matching `_CHAPTER_SCOPED_TAG_PREFIXES`. Two-pass: collect into
  a list, then remove — don't mutate the table during iteration.
- **Don't route global shortcuts through a window `EventControllerKey`.**
  GTK4 delivers key events along the focus chain, so a toplevel key
  controller goes dead whenever no widget holds focus — and on Wayland
  that happens often (fresh launch, suspend/resume, a popover closing),
  silently killing every shortcut. Register global shortcuts as GActions
  with `set_accels_for_action` instead; those dispatch focus-independently.
  Reserve `EventControllerKey` for genuinely contextual keys, and use
  CAPTURE phase + return False there so normal typing still propagates.
- **`Adw.ToolbarView` top bars + `Adw.Window` overlay handling on
  Wayland:** dismissing the panel via row activation auto-closes the
  panel. F3 step-through must therefore tolerate a closed panel —
  re-reveal it if `_results` is still cached rather than refusing to
  step. Same applies to any "stepping through results" UI pattern.
- **`Gtk.EventControllerScroll` with Ctrl modifier** for zoom: check
  `controller.get_current_event().get_modifier_state() &
  Gdk.ModifierType.CONTROL_MASK` and return False when Ctrl isn't held
  so normal scroll passes through to the ScrolledWindow. CAPTURE phase
  on the TextView keeps the zoom shortcut from being shadowed by the
  scroll bubble.
- **`Gtk.GestureZoom` `'begin'` resets cumulative scale to 1.0.** Track
  your own `_accum` ratio and reset on `'begin'` — otherwise a fresh
  pinch's first scale-changed signal triggers a spurious zoom-out
  because the ratio jumps from the previous gesture's final scale to
  1.0.
- **Wayland compositors report raw, unsmoothed pointer motion.** Mutter
  (and X11) apply pointer acceleration / smoothing, so a stationary
  finger on a trackpad delivers a tidy stream of "no motion" events.
  Hyprland (and most wlroots-based compositors) hand you the device's
  raw deltas — a "still" cursor still emits sub-pixel wobbles that
  cross any narrow Y-band. Any "must hover inside an N-px zone for T
  seconds" gesture needs **two thresholds**: a narrow trigger zone to
  arm the timer, and a wider tolerance zone within which the timer
  survives jitter. Only cursor motion past the wider zone should
  cancel. See `_on_reading_mouse_motion` for the F11 exit affordance,
  which uses `_READING_TRIGGER_ZONE_PX = 12` to arm and
  `_READING_KEEP_ZONE_PX = 80` as the cancel boundary.
- **Floating overlays + `.card` CSS class:** `@card_bg_color` is
  semi-transparent in libadwaita's dark palette (designed to layer over
  a solid window bg). Overlays mounted via `Gtk.Overlay.add_overlay`
  need an opaque background — apply your own class with
  `background-color: @view_bg_color`. Hit this with the menu panel
  (fixed earlier) and the Ctrl+L jump bar.
- **`sqlite3.connect` default `check_same_thread=True`** raises when a
  connection is used from a different thread. For app-wide reuse,
  thread-local storage (`threading.local()`) is the simplest correct
  shape; one connection per thread, schema initialised lazily on first
  call per thread. Avoids both the threading error and the
  open/PRAGMA/CREATE churn that "open per call" introduces.

## Known working modules

- **KJVA** — Hebrew/Greek OT+NT with Strong's; `savlm` attribute; hover-only
  underlines on words; clickable for Strong's lookup.
- **LEB / BSB** — via eBible.org SQLite backend.
- **StrongsHebrew + StrongsGreek** — required for the lexicon panel.
- **TSK** — Treasury of Scripture Knowledge; SWORD-side fallback for cross-refs.
- **MHCC** — Matthew Henry's Concise Commentary; commentary mode.
- **SME** — Spurgeon's Morning & Evening; devotional mode with morning/evening
  section split.
- **MorphGNT** — Greek morphology lookup.
- **Open data** (downloadable via Module Manager): OpenBible cross-references
  (340k refs, ~5× TSK), OpenBible topics, Dodson Greek Lexicon.

