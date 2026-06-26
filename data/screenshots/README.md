# Screenshots

These PNGs are the app's store screenshots. They are referenced by
the AppStream metainfo
(`data/page.codeberg.andresmessina.Scriptura.metainfo.xml.in`) and
shown by GNOME Software on the app's detail page. The repo README also
embeds a few of them.

The `<screenshots>` block is **already wired up** — no restoration
needed. The metainfo is installed automatically by meson
(`data/meson.build`), so there's no manual install line to maintain in
the Flatpak manifest either.

## How the metainfo points at these files

Each `<image>` URL tracks the `main` branch:

```
https://codeberg.org/andresmessina/scriptura/raw/branch/main/data/screenshots/<file>.png
```

Because the URLs follow `branch/main` (not a pinned commit), refreshing
a screenshot is just: **overwrite the file in place and push to
`main`.** No URL edit, no commit-SHA bump.

## The files

These exact filenames are referenced by the metainfo `<image>` URLs and
captions. Renaming one means editing the metainfo to match.

| File | Caption (must match metainfo) |
| --- | --- |
| `01-two-pane-lexicon.png` | Two-pane reading with the Strong's lexicon open on a Greek word |
| `02-translation-comparison.png` | Two translations side by side, sharing a verse selection |
| `03-study-journal.png` | Study Journal — every annotation in one filterable surface |
| `04-reading-plan.png` | Built-in reading plans with day-by-day progress |
| `05-reading-mode-dark.png` | F11 reading mode hides all chrome for distraction-free reading |

## Capture guidance

Take them on a real machine (not a VM) for crisp text. Target roughly
**1280×720 to 1600×900**, PNG, opaque (RGB). Light or dark mode is
fine — `05` is the dark-mode shot.
