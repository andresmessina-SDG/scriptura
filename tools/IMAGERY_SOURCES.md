# Bible Imagery — source roster & backlog

Status of every imagery layer for the download-on-demand pack
(`build_imagery_pack.py`). "Register" = which tab/visual family it belongs to
(Art = the per-verse "other traditions" expander; Where = the place tab).

Counts are rows in the pack. Oils + glass + illuminated manuscripts are **built
locally** but not yet in the **hosted** Codeberg pack (batched upload pending —
needs the `write:repository` token; outward-facing, the user's call). Build all
three pending sources with `--source oils --source glass --source manuscripts`.

## Built

| Layer / tradition | Register | Status | Count |
|---|---|---|---|
| Engravings — Schnorr + Doré | Art (engraving) | ✅ shipped | 437 |
| Color narrative — Tissot | Art (watercolour) | ✅ shipped | 448 |
| Byzantine icons | Art (icon) | ✅ shipped | 17 |
| Old Master oils | Art (painting) | ✅ built — host pending | 14 |
| Stained glass | Art (glass) | ✅ built — host pending | 9 |
| Illuminated manuscripts | Art (illumination) | ✅ built — host pending | 27 |
| Maps — Hurlbut antique | Where (maps) | ✅ shipped | 30 |
| Maps — modern SVG | Where (maps) | ✅ shipped | 11 |
| Place photos — OpenBible | Where (photos) | ✅ shipped | 1335 |

## Researched — to build

| Layer / tradition | Register | Priority | Notes |
|---|---|---|---|
| **Historical Holy Land photographs** | Where (photos) | **HIGH — next** | Matson Collection (Library of Congress) ~thousands of PD photos, geo-tagged → maps to existing OpenBible places as a "then vs. now" layer; + Frith / Bonfils / American Colony (19th c.). Hundreds easily. The biggest photo source available. |
| Illuminated manuscripts — *volume expansion* | Art (illumination) | low | The curated set (27, below) is built. Raw-numbers expansion path: bulk-ingest the full Morgan Crusader Bible (~340 OT scenes via its published folio scene-IDs) and/or the Très Riches Heures full-page cycle. Multi-register folios would break the single-scene-per-card consistency the curated set holds to — only worth it if volume is the goal. |
| Engravings — Merian / Holbein / Dalziel | Art (engraving) | low | Same register as Schnorr/Doré — deepens, doesn't widen. Cheap (PD) but marginal. |
| Maps — Smith atlas | Where (maps) | low | Same antique-map register as Hurlbut. Only worth it if Hurlbut has real gaps. |

## Separate module — "Scripture in Stone" (archaeology)

NOT part of this imagery pack — it became its **own bundled module** (a chaptered
illustrated "book" read in biblical sequence; verse chips drive the Bible pane).
**Vertical slice built & verified 2026-06-02** (6 of ~40 artifacts). Full research,
roster, licensing, and tone rules in `tools/ARTIFACTS_RESEARCH.md`; data in
`data/archaeology/`. Remaining: one-pane fallback, expand 6 → ~40.

## Volume option (deepens, doesn't widen)

Verse-indexed historical print archives if raw numbers are the goal — all
*engraving/woodcut* register, but the verse mapping already exists:
- **Pitts Theology Library Digital Image Archive** — tens of thousands, indexed by scripture reference; mostly PD.
- **Phillip Medhurst / Bowyer Bible** (Commons) — thousands, each captioned book:ch:verse.
- **Foster Bible Pictures (1897)** — ~200, captioned.
