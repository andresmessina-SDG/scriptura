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

# Bundled reading fonts (all OFL) so typography is identical on every machine
# instead of falling back to whatever serif the host happens to have. The
# Flatpak runtime's fontconfig scans /app/share/fonts. Newsreader is the
# editorial serif (Stone, glossary, footnotes); EB Garamond is the Voices
# column's reading serif with Roboto for its labels; Noto Serif and Noto Serif
# Hebrew back the interlinear's polytonic Greek and pointed Hebrew.
#
# OpenDyslexic is the one a READER chooses rather than the app: it is offered
# in Appearance ▸ Font. Four static faces, because it ships no variable build —
# and all four are needed, since the reading text sets bold and italic. Its
# licence travels with it (OFL clause 1: the licence must accompany the font,
# and the family name is a Reserved Font Name).
install_data(
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
