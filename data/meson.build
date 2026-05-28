datadir = get_option('prefix') / get_option('datadir')

desktop_file = 'page.codeberg.andresmessina.Scriptura.desktop'
metainfo_file = 'page.codeberg.andresmessina.Scriptura.metainfo.xml'
icon_file = 'icons/hicolor/scalable/apps/page.codeberg.andresmessina.Scriptura.svg'

install_data(desktop_file,  install_dir: datadir / 'applications')
install_data(metainfo_file, install_dir: datadir / 'metainfo')
install_data(icon_file,     install_dir: datadir / 'icons' / 'hicolor' / 'scalable' / 'apps')
install_data('style.css',   install_dir: pkgdatadir / 'data')

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
