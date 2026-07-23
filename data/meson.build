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
icon_file = 'icons/hicolor/scalable/apps/io.github.andresmessina_SDG.Scriptura.svg'
symbolic_icon = 'icons/hicolor/symbolic/apps/scriptura-keyboard-symbolic.svg'
globe_icon = 'icons/hicolor/symbolic/apps/scriptura-globe-symbolic.svg'
commentary_icon = 'icons/hicolor/symbolic/apps/scriptura-commentary-symbolic.svg'
imagery_icon = 'icons/hicolor/symbolic/apps/scriptura-imagery-symbolic.svg'
artifact_icon = 'icons/hicolor/symbolic/apps/scriptura-artifact-symbolic.svg'
timeline_icon = 'icons/hicolor/symbolic/apps/scriptura-timeline-symbolic.svg'
theme_system_icon = 'icons/hicolor/symbolic/apps/scriptura-theme-system-symbolic.svg'
tips_icon = 'icons/hicolor/symbolic/apps/scriptura-tips-symbolic.svg'
justify_icon = 'icons/hicolor/symbolic/apps/scriptura-justify-symbolic.svg'
church_icon = 'icons/hicolor/symbolic/apps/scriptura-church-symbolic.svg'

install_data(icon_file,     install_dir: datadir / 'icons' / 'hicolor' / 'scalable' / 'apps')
install_data(symbolic_icon, install_dir: datadir / 'icons' / 'hicolor' / 'symbolic' / 'apps')
install_data(globe_icon,    install_dir: datadir / 'icons' / 'hicolor' / 'symbolic' / 'apps')
install_data(commentary_icon, install_dir: datadir / 'icons' / 'hicolor' / 'symbolic' / 'apps')
install_data(imagery_icon,  install_dir: datadir / 'icons' / 'hicolor' / 'symbolic' / 'apps')
install_data(artifact_icon, install_dir: datadir / 'icons' / 'hicolor' / 'symbolic' / 'apps')
install_data(timeline_icon, install_dir: datadir / 'icons' / 'hicolor' / 'symbolic' / 'apps')
install_data(theme_system_icon, install_dir: datadir / 'icons' / 'hicolor' / 'symbolic' / 'apps')
install_data(tips_icon,     install_dir: datadir / 'icons' / 'hicolor' / 'symbolic' / 'apps')
install_data(justify_icon,  install_dir: datadir / 'icons' / 'hicolor' / 'symbolic' / 'apps')
install_data(church_icon,   install_dir: datadir / 'icons' / 'hicolor' / 'symbolic' / 'apps')
install_data('style.css',   install_dir: pkgdatadir / 'data')
install_data('collects.toml', install_dir: pkgdatadir / 'data')
# Bundled "Scripture in Stone" archaeology document + its images.
install_subdir('archaeology', install_dir: pkgdatadir / 'data')

# Bundled reading fonts (all OFL) so typography is identical on every machine
# instead of falling back to whatever serif the host happens to have. The
# Flatpak runtime's fontconfig scans /app/share/fonts. Newsreader is the
# editorial serif (Stone, glossary, footnotes); EB Garamond is the Voices
# column's reading serif with Roboto for its labels; Noto Serif and Noto Serif
# Hebrew back the interlinear's polytonic Greek and pointed Hebrew.
install_data(
  'fonts/Newsreader[opsz,wght].ttf',
  'fonts/Newsreader-Italic[opsz,wght].ttf',
  'fonts/EBGaramond[wght].ttf',
  'fonts/EBGaramond-Italic[wght].ttf',
  'fonts/Roboto[wdth,wght].ttf',
  'fonts/NotoSerif[wdth,wght].ttf',
  'fonts/NotoSerifHebrew[wdth,wght].ttf',
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
