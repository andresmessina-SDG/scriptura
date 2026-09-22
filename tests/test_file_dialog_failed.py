"""A file dialog that fails must say so; one the reader closed must not.

Both reach `*_finish` as the same GLib.Error. Every site used to treat any
error as a cancel, so on a desktop with no file-chooser portal Export,
Backup, Restore and the imports did nothing at all. No display needed:
the sites are driven with a fake dialog that raises.
"""
import pytest
from gi.repository import Gio, GLib, Gtk

import export_dialog
from gtk_utils import file_dialog_failed


def _err(domain, code):
    return GLib.Error.new_literal(domain, 'boom', code)


DISMISSED = _err(Gtk.DialogError.quark(), Gtk.DialogError.DISMISSED)
CANCELLED = _err(Gtk.DialogError.quark(), Gtk.DialogError.CANCELLED)
IO_CANCELLED = _err(Gio.io_error_quark(), Gio.IOErrorEnum.CANCELLED)
FAILED = _err(Gtk.DialogError.quark(), Gtk.DialogError.FAILED)
NO_PORTAL = _err(Gio.dbus_error_quark(), Gio.DBusError.SERVICE_UNKNOWN)


@pytest.mark.parametrize('err', [DISMISSED, CANCELLED, IO_CANCELLED])
def test_a_closed_dialog_is_not_a_failure(err):
    assert not file_dialog_failed(err)


@pytest.mark.parametrize('err', [FAILED, NO_PORTAL])
def test_a_failed_dialog_is(err):
    assert file_dialog_failed(err)


class _Dialog:
    def __init__(self, err):
        self._err = err

    def save_finish(self, _result):
        raise self._err


@pytest.mark.parametrize('cls', [export_dialog.ExportSheet,
                                 export_dialog.CardSheet])
@pytest.mark.parametrize('err, told', [(FAILED, True), (DISMISSED, False)])
def test_export_reports_a_failed_chooser(cls, err, told):
    sheet = cls.__new__(cls)
    said = []
    sheet._report = said.append
    sheet._on_chosen(_Dialog(err), None)
    assert bool(said) is told
