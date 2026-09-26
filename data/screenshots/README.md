# Screenshots

These PNGs are the app's store screenshots. The AppStream metainfo
(`data/io.github.andresmessina_SDG.Scriptura.metainfo.xml.in`) lists
them, GNOME Software shows them on the app's page, and the repo README
embeds them. The first is the default.

## How they are made

They are rendered from the real app, not captured by hand:

```
python3 tools/render-site-shots.py --sword SWORD_DIR --only en
```

renders every shot at 1366×733 in light and dark into `site-shots/`
(and the website's copies into `docs/assets/img/`). The store set is the
English light shots, and the reading-mode shot in dark, saved here as
PNG. Only open Bible texts appear: the tool runs the app with a
scratch home that holds nothing else.

## How the metainfo points at these files

Each `<image>` URL tracks the `main` branch:

```
https://raw.githubusercontent.com/andresmessina-SDG/scriptura/main/data/screenshots/<file>.png
```

So a refreshed screenshot is the file overwritten in place and pushed to
`main`. Push before building the Flatpak: `appstreamcli compose` drops a
URL that does not answer yet, without an error.

## The files

Renaming one means editing the metainfo to match.

| File | Caption (as in the metainfo) |
| --- | --- |
| `01-read-the-difference.png` | One verse in every English Bible you have, with the Hebrew above, beside the Bible you are reading |
| `02-bible-family-tree.png` | The Bible Family Tree: the English Bibles read today and the Bibles they came from |
| `03-interlinear-greek.png` | The Greek New Testament word by word, with meaning, grammar and Strong's number under each word |
| `04-voices-of-the-church.png` | Voices of the Church: what the fathers and the Reformers wrote on the verse you are reading |
| `05-scripture-in-art.png` | Art for the passage: Caravaggio's Calling of Saint Matthew beside Matthew 9 |
| `06-sermon-writing.png` | Write a sermon beside the passage, with its series, dates and verses |
| `07-reading-mode-dark.png` | Reading mode hides everything but the text |
