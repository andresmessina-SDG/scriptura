datadir = get_option('prefix') / get_option('datadir')

po_dir = meson.project_source_root() / 'po'

# Translated .desktop — msgfmt --desktop merges Name/GenericName/Comment/
# Keywords from the catalogs in po/ into the generated file.
desktop_file = i18n.merge_file(
  input: 'io.github.andresmessina_SDG.Scriptura.desktop.in',
  output: 'io.github.andresmessina_SDG.Scriptura.desktop',
  type: 'desktop',
  po_dir: po_dir,
  install: true,
  install_dir: datadir / 'applications',
)

# Translated AppStream metainfo — msgfmt --xml uses gettext's built-in
# metainfo ITS rules to merge <summary>/<description> translations.
metainfo_file = i18n.merge_file(
  input: 'io.github.andresmessina_SDG.Scriptura.metainfo.xml.in',
  output: 'io.github.andresmessina_SDG.Scriptura.metainfo.xml',
  type: 'xml',
  po_dir: po_dir,
  install: true,
  install_dir: datadir / 'metainfo',
)
# Verse lookup from the GNOME Shell's search (search_provider.py). The .ini
# tells the Shell where to ask; the service file lets it start the app,
# windowless, when it is not already running.
install_data('io.github.andresmessina_SDG.Scriptura.search-provider.ini',
  install_dir: datadir / 'gnome-shell' / 'search-providers')
service_conf = configuration_data()
service_conf.set('bindir', bindir)
configure_file(
  input: 'io.github.andresmessina_SDG.Scriptura.service.in',
  output: 'io.github.andresmessina_SDG.Scriptura.service',
  configuration: service_conf,
  install: true,
  install_dir: datadir / 'dbus-1' / 'services',
)

# Icons. The whole tree installs at once rather than file by file: the app
# now ships its own copy of every symbolic icon it draws (see the NOTICE in
# data/icons), which is far too many to list, and a list is the kind of
# thing that silently falls behind — a named-but-unshipped icon draws as a
# blank square. tests/test_icon_names.py holds that line instead.
# NOTICE is excluded: install_dir here is the SHARED icon namespace that
# every package writes into, and a bare NOTICE file there would collide.
# It ships under the app's own data directory instead.
install_subdir('icons', install_dir: datadir, exclude_files: ['NOTICE'])
install_data('icons/NOTICE', install_dir: pkgdatadir / 'data' / 'icons')

install_data('style.css',   install_dir: pkgdatadir / 'data')
install_data('style-hc.css', install_dir: pkgdatadir / 'data')
install_data('collects.toml', install_dir: pkgdatadir / 'data')
# Bundled "Scripture in Stone" archaeology document + its images.
install_subdir('archaeology', install_dir: pkgdatadir / 'data')

# Bundled "Book of Generations" genealogy table. One TOML: the charts are
# computed from it at draw time, so there are no plate files to ship.
install_subdir('genealogy', install_dir: pkgdatadir / 'data')

# The Bible Family Tree: every English Bible, its descent and its place on
# the word-for-word ↔ free spectrum. Read by bible_family.py.
install_subdir('bible_family', install_dir: pkgdatadir / 'data')

# Bundled fonts (all OFL) so typography is identical on every machine
# instead of falling back to whatever the host happens to have. The
# Flatpak runtime's fontconfig scans /app/share/fonts, and /usr/share/fonts
# is in the system scan path, so a source install is covered too.
#
# The reading faces: Newsreader is the editorial serif (Stone, glossary,
# footnotes); EB Garamond is the Voices column's reading serif with Roboto
# for its labels; Noto Serif and Noto Serif Hebrew back the interlinear's
# polytonic Greek and pointed Hebrew.
#
# Adwaita Sans is the CHROME face — every label, button and menu — and it
# joined this list on 2026-09-19, when a desktop audit found the one gap the
# reasoning above had always covered but never closed. `data/style.css` asks
# for "Adwaita Sans", then "Inter", then sans-serif; measured on Fedora,
# adwaita-sans-fonts is required by NO package (it arrives with the GNOME
# desktop group, not with gtk4 or libadwaita) and Inter is not packaged at
# all. So a source install on KDE, Xfce or a bare WM fell through to
# whichever sans fontconfig picked — Noto Sans there, which sets lines 10.6%
# taller than the line-height table at the top of style.css was measured
# against. The Flatpak was never affected: org.gnome.Platform ships the face.
# Italic ships too, because the chrome really uses it (.interlinear-translit,
# .interlinear-gloss-implicit); without it fontconfig slants the roman.
#
# OpenDyslexic is the one a READER chooses rather than the app: it is offered
# in Appearance ▸ Font. Four static faces, because it ships no variable build —
# and all four are needed, since the reading text sets bold and italic. Its
# licence travels with it (OFL clause 1: the licence must accompany the font,
# and the family name is a Reserved Font Name).
install_data(
  'fonts/AdwaitaSans-Regular.ttf',
  'fonts/AdwaitaSans-Italic.ttf',
  'fonts/AdwaitaSans-OFL.txt',
  'fonts/Newsreader[opsz,wght].ttf',
  'fonts/Newsreader-Italic[opsz,wght].ttf',
  'fonts/EBGaramond[wght].ttf',
  'fonts/EBGaramond-Italic[wght].ttf',
  'fonts/Roboto[wdth,wght].ttf',
  'fonts/NotoSerif[wdth,wght].ttf',
  'fonts/NotoSerifHebrew[wdth,wght].ttf',
  'fonts/OpenDyslexic-Regular.otf',
  'fonts/OpenDyslexic-Bold.otf',
  'fonts/OpenDyslexic-Italic.otf',
  'fonts/OpenDyslexic-Bold-Italic.otf',
  'fonts/OpenDyslexic-OFL.txt',
  install_dir: datadir / 'fonts' / 'scriptura',
)

desktop_validate = find_program('desktop-file-validate', required: false)
if desktop_validate.found()
  test('validate-desktop',
    desktop_validate,
    args: [desktop_file])
endif

appstreamcli = find_program('appstreamcli', required: false)
if appstreamcli.found()
  test('validate-appstream',
    appstreamcli,
    args: ['validate', '--no-net', metainfo_file])
endif
