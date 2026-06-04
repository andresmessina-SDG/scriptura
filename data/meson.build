datadir = get_option('prefix') / get_option('datadir')

desktop_file = 'page.codeberg.andresmessina.Scriptura.desktop'
metainfo_file = 'page.codeberg.andresmessina.Scriptura.metainfo.xml'
icon_file = 'icons/hicolor/scalable/apps/page.codeberg.andresmessina.Scriptura.svg'
symbolic_icon = 'icons/hicolor/symbolic/apps/scriptura-keyboard-symbolic.svg'
globe_icon = 'icons/hicolor/symbolic/apps/scriptura-globe-symbolic.svg'
commentary_icon = 'icons/hicolor/symbolic/apps/scriptura-commentary-symbolic.svg'
imagery_icon = 'icons/hicolor/symbolic/apps/scriptura-imagery-symbolic.svg'
artifact_icon = 'icons/hicolor/symbolic/apps/scriptura-artifact-symbolic.svg'
timeline_icon = 'icons/hicolor/symbolic/apps/scriptura-timeline-symbolic.svg'
theme_system_icon = 'icons/hicolor/symbolic/apps/scriptura-theme-system-symbolic.svg'

install_data(desktop_file,  install_dir: datadir / 'applications')
install_data(metainfo_file, install_dir: datadir / 'metainfo')
install_data(icon_file,     install_dir: datadir / 'icons' / 'hicolor' / 'scalable' / 'apps')
install_data(symbolic_icon, install_dir: datadir / 'icons' / 'hicolor' / 'symbolic' / 'apps')
install_data(globe_icon,    install_dir: datadir / 'icons' / 'hicolor' / 'symbolic' / 'apps')
install_data(commentary_icon, install_dir: datadir / 'icons' / 'hicolor' / 'symbolic' / 'apps')
install_data(imagery_icon,  install_dir: datadir / 'icons' / 'hicolor' / 'symbolic' / 'apps')
install_data(artifact_icon, install_dir: datadir / 'icons' / 'hicolor' / 'symbolic' / 'apps')
install_data(timeline_icon, install_dir: datadir / 'icons' / 'hicolor' / 'symbolic' / 'apps')
install_data(theme_system_icon, install_dir: datadir / 'icons' / 'hicolor' / 'symbolic' / 'apps')
install_data('style.css',   install_dir: pkgdatadir / 'data')
# Bundled "Scripture in Stone" archaeology document + its images.
install_subdir('archaeology', install_dir: pkgdatadir / 'data')

desktop_validate = find_program('desktop-file-validate', required: false)
if desktop_validate.found()
  test('validate-desktop',
    desktop_validate,
    args: [desktop_file],
    workdir: meson.current_source_dir())
endif

appstreamcli = find_program('appstreamcli', required: false)
if appstreamcli.found()
  test('validate-appstream',
    appstreamcli,
    args: ['validate', '--no-net', metainfo_file],
    workdir: meson.current_source_dir())
endif
