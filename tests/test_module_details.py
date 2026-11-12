"""A module row opens what its publisher says of it: About, Copyright,
Version and Source from the conf, beside the Module Manager's list."""
import types

import pytest

import sword_bridge


def _display():
    from gi.repository import Gdk
    if Gdk.Display.get_default() is None:
        pytest.skip('builds module widgets; no display here')


def test_the_catalogue_keeps_about_copyright_and_source_as_plain_text():
    info = sword_bridge._parse_conf_lines([
        '[Institutes]', 'About=By John Calvin\\par Published by CCEL \\',
        'Grand Rapids', 'Copyright=Public domain', 'TextSource=CCEL'])
    assert info['about'] == 'By John Calvin\nPublished by CCEL Grand Rapids'
    assert info['copyright'] == 'Public domain'
    assert info['textsource'] == 'CCEL'


def test_catalogue_rows_carry_the_publishers_description(monkeypatch, tmp_path):
    mods = tmp_path / 'mods.d'
    mods.mkdir()
    (mods / 'kjv.conf').write_text(
        '[KJV]\nModDrv=zText\nDescription=King James Version\n'
        'About=The KJV.\\par Strong\'s numbers\nTextSource=https://x.org/kjv\n')
    monkeypatch.setattr(sword_bridge, '_catalog_cache', None)
    monkeypatch.setattr(sword_bridge, '_shadow_path', lambda: str(tmp_path))
    monkeypatch.setattr(sword_bridge, 'module_names', lambda: [])
    found = [m for m in sword_bridge.list_available_modules() if m['name'] == 'KJV']
    assert found and found[0]['about'] == "The KJV.\nStrong's numbers"
    assert found[0]['textsource'] == 'https://x.org/kjv'


def _labels(widget):
    from gi.repository import Gtk
    out, stack = [], [widget]
    while stack:
        w = stack.pop()
        if isinstance(w, Gtk.Label):
            out.append(w.get_text())
        child = w.get_last_child()
        while child is not None:
            stack.append(child)
            child = child.get_prev_sibling()
    return out


def test_pressing_a_row_opens_its_details():
    _display()
    import module_manager
    shown = []
    fake = types.SimpleNamespace(_add_actions=lambda *a: None,
                                 _on_install=lambda *a: None,
                                 _show_details=lambda m, t: shown.append((m['name'], t)))
    mod = {'name': 'KJV', 'description': 'King James Version', 'about': 'A Bible.'}
    row = module_manager.ModuleManagerWindow._make_sword_row(fake, mod, False)
    assert row.get_activatable()
    row.emit('activated')
    assert shown and shown[0][0] == 'KJV'


def test_the_details_show_each_field_and_link_web_addresses():
    _display()
    from module_details import ModuleDetails
    details = ModuleDetails(on_close=lambda: None)
    details.show('King James Version', 'CrossWire', 'KJV · Version 3.1',
                 'The KJV.\nSee http://www.bf.org.', '', 'https://gitlab.com/kjv')
    labels = _labels(details)
    assert 'The KJV.\nSee http://www.bf.org.' in labels
    assert 'Copyright' not in labels          # empty fields are left out
    assert 'Source' in labels and 'KJV · Version 3.1' in labels
    from module_details import _linked
    assert _linked('See http://www.bf.org. & more') == \
        'See <a href="http://www.bf.org">http://www.bf.org</a>. &amp; more'


def test_a_source_that_only_names_the_publisher_is_left_out():
    _display()
    from module_details import ModuleDetails
    details = ModuleDetails(on_close=lambda: None)
    details.show('Mortification', 'Common Weal Press', 'Version 2', 'Owen.', '',
                 'Common Weal Press, commonwealpress.org')
    assert 'Source' not in _labels(details)
    details.show('KJV', 'CrossWire', '', 'A Bible.', '',
                 'https://gitlab.com/crosswire-bible-society/kjv')
    assert 'Source' in _labels(details)


def test_sizes_drop_a_useless_decimal():
    import module_manager
    assert module_manager._fmt_size(str(290 * 1024)) == '290 KB'
    assert module_manager._fmt_size(str(int(4.4 * 1024 * 1024))) == '4.4 MB'


def test_a_module_with_nothing_to_say_says_so():
    _display()
    from module_details import ModuleDetails
    details = ModuleDetails(on_close=lambda: None)
    details.show('Sideloaded', 'CrossWire', 'Sideloaded', '', '', '')
    assert 'Its publisher gives no description.' in _labels(details)


def test_a_classics_author_moves_from_the_title_to_the_byline():
    import module_manager
    shown = []
    fake = types.SimpleNamespace(
        _details=types.SimpleNamespace(show=lambda *a: shown.append(a),
                                       focus_start=lambda: None),
        _sheet=types.SimpleNamespace(set_visible_child_name=lambda n: None),
        _card_split=types.SimpleNamespace(set_show_sidebar=lambda v: None))
    classic = {'name': 'CWPSinners', 'collection': 'Classics', 'version': '9',
               'size': str(40 * 1024)}
    module_manager.ModuleManagerWindow._show_details(
        fake, classic, 'Sinners in the Hands of an Angry God (Jonathan Edwards)')
    title, source, meta = shown[0][:3]
    assert title == 'Sinners in the Hands of an Angry God'
    assert meta == 'Jonathan Edwards · Version 9 · 40 KB'
    # CrossWire titles follow no one pattern; they stay as given.
    module_manager.ModuleManagerWindow._show_details(
        fake, {'name': 'X', 'version': '1'}, 'Commentary (Abridged)')
    assert shown[1][0] == 'Commentary (Abridged)'
