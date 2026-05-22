# Screenshots

These PNGs are referenced by the AppStream metainfo and by Flathub's
store page. Once captured, restore the `<screenshots>` block in
`data/org.codeberg.andresmessina.BibleReader.metainfo.xml` and the
metainfo install line in `org.codeberg.andresmessina.BibleReader.yml`.

## Capture checklist

Take all five on a real machine (not the VM) for crisp rendering.
Target dimensions: roughly **1280 × 720** to **1600 × 900** depending
on your panel, in **PNG** format. Light or dark mode is fine —
some Flathub apps ship both. Captions below match what's already in
the metainfo draft.

| File | What's in the shot |
| --- | --- |
| `reading.png` | Two-pane reading view with Strong's lexicon and cross-references. KJVA in pane 1, a modern translation in pane 2, lexicon panel visible at the bottom of pane 1 showing a Greek word's definition, cross-ref bar populated at the bottom of the window. |
| `module-manager.png` | Module Manager open on the SWORD tab (or eBible) showing a populated module list with at least one installed and several Available. |
| `study-journal.png` | Study Journal in master-detail layout. Sidebar with several entries (mix of highlights / notes / chapter notes), detail pane on the right with a note being edited or a recent entry selected. |
| `search.png` | Search panel open with results for something content-rich like "covenant" or "spirit" — the canon distribution chart visible at the top. |
| `lexicon.png` | Close-up of the lexicon panel showing a Strong's lookup (e.g., G2316 / θεός) with the Dodson definition and word-study list. Bible-text view above with the matching word hovered. |

## File names matter

The metainfo references these exact filenames via the Codeberg
`raw.codeberg.org/...` URLs:

- `data/screenshots/reading.png`
- `data/screenshots/module-manager.png`
- `data/screenshots/study-journal.png`
- `data/screenshots/search.png`
- `data/screenshots/lexicon.png`

If you rename, update the metainfo `<image>` URLs to match.

## Quick checklist after capture

1. Drop the PNGs into this directory.
2. Restore the `<screenshots>` block in the metainfo (was last
   present at commit `31610f6`; the captions match the table above).
3. Restore the metainfo `install` line in the Flatpak manifest.
4. Push.
