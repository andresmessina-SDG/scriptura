project('scriptura',
  version: '1.2.0',
  meson_version: '>= 0.59.0',
  license: 'GPL-3.0-or-later',
)

python = import('python').find_installation('python3')
i18n = import('i18n')

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
  'a11y.py',
  'annotation_dialogs.py',
  'annotations.py',
  'archaeology_bridge.py',
  'archaeology_reader.py',
  'backup.py',
  'bookmarks.py',
  'catena_bridge.py',
  'catena_reader.py',
  'content.py',
  'crossref_panel.py',
  'devotional.py',
  'ebible_bridge.py',
  'empty_state.py',
  'genbook_reader.py',
  'gtk_utils.py',
  'i18n.py',
  'imagery_bridge.py',
  'imagery_reader.py',
  'lexicon_panel.py',
  'module_manager.py',
  'module_picker.py',
  'module_positions.py',
  'onboarding.py',
  'open_data.py',
  'pane.py',
  'pane_search.py',
  'paths.py',
  'reading_plans.py',
  'search_controller.py',
  'search_panel.py',
  'search_query.py',
  'settings.py',
  'study_journal.py',
  'styles.py',
  'sword_bridge.py',
  'welcome.py',
  'window.py',
)

install_data(py_sources, install_dir: pkgdatadir)

install_data('LICENSE', install_dir: licensedir)

subdir('po')
subdir('data')

meson.add_install_script('meson_post_install.py')
