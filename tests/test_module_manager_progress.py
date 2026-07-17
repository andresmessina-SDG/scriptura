"""Determinate download-bar semantics (_progress_fraction).

Pure helper — the window bar is determinate exactly while download bytes
flow, and returns to the activity pulse for size-unknown downloads and
for the post-download tail (extract/parse/commit), where a bar frozen at
100% would read as hung.
"""
from module_manager import _progress_fraction


def test_fraction_while_bytes_flow():
    assert _progress_fraction(1, 4) == 0.25
    assert _progress_fraction(3, 4) == 0.75


def test_unknown_total_pulses():
    assert _progress_fraction(1024, 0) is None


def test_nothing_reported_yet_pulses():
    assert _progress_fraction(0, 4) is None


def test_tail_after_last_byte_pulses():
    assert _progress_fraction(4, 4) is None
    assert _progress_fraction(5, 4) is None
