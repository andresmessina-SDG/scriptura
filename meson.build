project('scriptura',
  version: '1.0.1',
  meson_version: '>= 0.59.0',
  license: 'GPL-3.0-or-later',
)

python = import('python').find_installation('python3')

app_id = 'page.codeberg.andresmessina.Scriptura'
pkgdatadir = get_option('prefix') / get_option('datadir') / meson.project_name()
bindir = get_option('prefix') / get_option('bindir')
licensedir = get_option('prefix') / get_option('datadir') / 'licenses' / app_id

conf = configuration_data()
conf.set('PYTHON', python.full_path())
conf.set('VERSION', meson.project_version())
conf.set('pkgdatadir', pkgdatadir)

configure_file(
  input: 'scriptura.in',
  output: app_id,
  configuration: conf,
  install: true,
  install_dir: bindir,
  install_mode: 'rwxr-xr-x',
)

py_sources = files(
  'main.py',
  '_version.py',
  'annotation_dialogs.py',
  'annotations.py',
  'bookmarks.py',
  'catena_bridge.py',
  'catena_reader.py',
  'crossref_panel.py',
  'devotional.py',
  'ebible_bridge.py',
  'empty_state.py',
  'genbook_reader.py',
  'imagery_bridge.py',
  'lexicon_panel.py',
  'module_manager.py',
  'module_picker.py',
  'module_positions.py',
  'open_data.py',
  'pane.py',
  'pane_search.py',
  'paths.py',
  'reading_plans.py',
  'search_panel.py',
  'settings.py',
  'study_journal.py',
  'styles.py',
  'sword_bridge.py',
  'welcome.py',
  'window.py',
)

install_data(py_sources, install_dir: pkgdatadir)

install_data('LICENSE', install_dir: licensedir)

subdir('data')

meson.add_install_script('meson_post_install.py')
