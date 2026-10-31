"""Small muted text reaches 4.5:1 on every paper.

The verse numerals and section headings were a fixed grey (#808080) and the
footnote markers a fixed blue, chosen once for the default paper: 3.6:1 and
3.8:1 there, 3.1:1 and 3.3:1 on Green. Both are now worked out from the
paper, and high contrast asks 7:1.
"""
import pytest

from pane import (HIGH_CONTRAST, SMALL_TEXT_CONTRAST, auto_reading_ink,
                  contrast_ratio, is_dark_paper, paper_inks, theme_ink)

PAPERS = ['#f7f4ee', '#fbfbfb', '#f8f1e3', '#dce8d0',   # the light presets
          '#1e1e1e', '#2a2622', '#000000',              # the dark presets
          '#c9b99a', '#3b4a5c']                         # two custom papers


def inks(paper, target=SMALL_TEXT_CONTRAST):
    return paper_inks(paper, auto_reading_ink(paper), is_dark_paper(paper),
                      target)


@pytest.mark.parametrize('paper', PAPERS)
def test_muted_and_link_clear_small_text_contrast(paper):
    for name, col in inks(paper).items():
        assert contrast_ratio(col, paper) >= 4.5, (name, col)


@pytest.mark.parametrize('paper', PAPERS)
def test_high_contrast_asks_seven_to_one(paper):
    # Never past the reading ink itself: on a mid-dark custom paper the text
    # is 6.9:1, and a numeral louder than the text would be wrong.
    ceiling = contrast_ratio(auto_reading_ink(paper), paper)
    for name, col in inks(paper, HIGH_CONTRAST).items():
        assert contrast_ratio(col, paper) >= min(7.0, ceiling) - 0.01, (name, col)


def test_no_paper_loses_contrast_it_had():
    # The old grey already gave 5.3:1 on Black; it stays.
    assert inks('#000000')['_ink_muted'] == '#808080'


def test_muted_ink_is_quieter_than_the_text():
    for paper in PAPERS:

        assert (contrast_ratio(inks(paper)['_ink_muted'], paper)
                < contrast_ratio(auto_reading_ink(paper), paper))


def test_theme_ink_is_the_default_papers_inks():
    assert theme_ink(False)['_ink_muted'] == inks('#f7f4ee')['_ink_muted']
    assert theme_ink(True)['_ink_link'] == inks('#1e1e1e')['_ink_link']


def test_muted_differs_from_every_other_theme_colour():
    # Adoption matches spans to tags by colour; two equal entries would
    # hand one tag's spans to the other.
    for dark in (False, True):
        cols = [v for k, v in theme_ink(dark).items() if k != '_ink_dropcap']
        assert len(cols) == len(set(cols))
