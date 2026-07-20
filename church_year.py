"""The church year — liturgical day designations for the Today page.

Three traditions, chosen by the `church_calendar` setting (default None —
the app stays ecumenical by staying silent until asked):

- ``anglican``  — the historic BCP (1662/1928) calendar: Advent → Christmas
  → Epiphany → Pre-Lent (Septuagesima) → Lent → Easter → Whitsun →
  Trinitytide, with the classic red-letter feasts.
- ``roman``     — the traditional Roman calendar (the public-domain missal
  translations key to this shape): Sundays after Pentecost, Passion
  Sunday, Corpus Christi, and the principal feasts.
- ``orthodox``  — the Byzantine year on the New (Revised Julian) calendar:
  the Triodion and Pentecostarion cycles around Pascha (which stays on
  the *Julian* reckoning even for New-Calendar churches) and the Great
  Feasts on their fixed dates.

Deliberately principal-only: seasons, Sundays, and the major feasts — no
full sanctorale, and no precedence/transfer rules (a fixed feast simply
names its civil day; the week designation serves every other day, as the
BCP's weekly collect does). Pure computation over curated tables; the
golden-date tests in tests/test_church_year.py are the guard.

Display strings are translated where they are produced, never at the point of
use: the first half of every pair this module returns is a stable key, read by
the collects pack and by the tests, and it must stay English whatever the UI
language is. Data tables are marked with ``N_()`` and translated at the lookup.

The numbered Sundays are composed from a template and an ordinal word rather
than spelled out one by one, which keeps the catalog to a few dozen entries
instead of a couple of hundred. Translators can reorder the two freely; a
language needing the ordinal to agree with each season's noun can vary the
template, since there is one per season.
"""

import datetime

from i18n import _, N_

Designation = tuple[str, str]   # (stable key for the collects pack, display)

TRADITIONS = ('anglican', 'roman', 'orthodox')


# ── Computus ─────────────────────────────────────────────────────────────────

def easter_gregorian(year: int) -> datetime.date:
    """Western Easter (Anonymous Gregorian algorithm)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    g = (8 * b + 13) // 25
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    n, p = divmod(h + l - 7 * m + 114, 31)
    return datetime.date(year, n, p + 1)


def pascha_gregorian(year: int) -> datetime.date:
    """Orthodox Pascha (Julian computus, Meeus) as a Gregorian civil date.
    The +13-day Julian→Gregorian offset holds for 1900–2099."""
    a = year % 4
    b = year % 7
    c = year % 19
    d = (19 * c + 15) % 30
    e = (2 * a + 4 * b - d + 34) % 7
    month, day = divmod(d + e + 114, 31)
    julian = datetime.date(year, month, day + 1)
    return julian + datetime.timedelta(days=13)


def advent_sunday(year: int) -> datetime.date:
    """Advent 1 — the Sunday on or after 27 November."""
    d = datetime.date(year, 11, 27)
    return d + datetime.timedelta(days=(6 - d.weekday()) % 7)


# ── Ordinal words ────────────────────────────────────────────────────────────

#: Spelled out rather than composed from tens and units. Building "Twenty-
#: fourth" out of "Twenty" and "fourth" works in English and in very little
#: else.
#:
#: The table must cover every value _ordinal() is ever asked for, and the
#: longest series is not the one it looks like: the Sundays after Trinity stop
#: at twenty-six, but the Orthodox count after Pentecost runs on through the
#: winter until the Triodion opens, and reaches THIRTY-SEVEN. A sweep of
#: 1900–2099 asserts the range in tests/test_church_year.py; forty leaves
#: room. Past the table _ordinal falls back to the bare numeral, which reads
#: "The 37 Sunday after Pentecost" — correct in no language at all.
_ORDINALS = [
    '',
    N_('First'), N_('Second'), N_('Third'), N_('Fourth'), N_('Fifth'),
    N_('Sixth'), N_('Seventh'), N_('Eighth'), N_('Ninth'), N_('Tenth'),
    N_('Eleventh'), N_('Twelfth'), N_('Thirteenth'), N_('Fourteenth'),
    N_('Fifteenth'), N_('Sixteenth'), N_('Seventeenth'), N_('Eighteenth'),
    N_('Nineteenth'), N_('Twentieth'), N_('Twenty-first'), N_('Twenty-second'),
    N_('Twenty-third'), N_('Twenty-fourth'), N_('Twenty-fifth'),
    N_('Twenty-sixth'), N_('Twenty-seventh'), N_('Twenty-eighth'),
    N_('Twenty-ninth'), N_('Thirtieth'), N_('Thirty-first'),
    N_('Thirty-second'), N_('Thirty-third'), N_('Thirty-fourth'),
    N_('Thirty-fifth'), N_('Thirty-sixth'), N_('Thirty-seventh'),
    N_('Thirty-eighth'), N_('Thirty-ninth'), N_('Fortieth'),
]


def _ordinal(n: int) -> str:
    """The ordinal word for `n`, translated; the bare numeral past the table."""
    if 0 < n < len(_ORDINALS):
        return _(_ORDINALS[n])
    return str(n)


# ── Principal fixed feasts (month, day) → (key suffix, display) ──────────────

_ANGLICAN_FEASTS = {
    (1, 1):   N_('The Circumcision of Christ'),
    (1, 6):   N_('The Epiphany'),
    (1, 25):  N_('The Conversion of St Paul'),
    (2, 2):   N_('The Presentation of Christ in the Temple'),
    (2, 24):  N_('St Matthias the Apostle'),
    (3, 25):  N_('The Annunciation'),
    (4, 25):  N_('St Mark the Evangelist'),
    (5, 1):   N_('St Philip and St James, Apostles'),
    (6, 11):  N_('St Barnabas the Apostle'),
    (6, 24):  N_('The Nativity of St John the Baptist'),
    (6, 29):  N_('St Peter the Apostle'),
    (7, 25):  N_('St James the Apostle'),
    (8, 24):  N_('St Bartholomew the Apostle'),
    (9, 21):  N_('St Matthew the Apostle'),
    (9, 29):  N_('St Michael and All Angels'),
    (10, 18): N_('St Luke the Evangelist'),
    (10, 28): N_('St Simon and St Jude, Apostles'),
    (11, 1):  N_("All Saints' Day"),
    (11, 30): N_('St Andrew the Apostle'),
    (12, 21): N_('St Thomas the Apostle'),
    (12, 25): N_('Christmas Day'),
    (12, 26): N_('St Stephen the Martyr'),
    (12, 27): N_('St John the Evangelist'),
    (12, 28): N_('The Holy Innocents'),
}

_ROMAN_FEASTS = {
    (1, 1):   N_('The Circumcision of Our Lord'),
    (1, 6):   N_('The Epiphany of Our Lord'),
    (2, 2):   N_('The Purification of the Blessed Virgin Mary'),
    (3, 19):  N_('St Joseph, Spouse of the Blessed Virgin Mary'),
    (3, 25):  N_('The Annunciation'),
    (6, 24):  N_('The Nativity of St John the Baptist'),
    (6, 29):  N_('Ss Peter and Paul, Apostles'),
    (7, 25):  N_('St James the Apostle'),
    (8, 6):   N_('The Transfiguration of Our Lord'),
    (8, 15):  N_('The Assumption of the Blessed Virgin Mary'),
    (9, 29):  N_('St Michael the Archangel'),
    (11, 1):  N_('All Saints'),
    (11, 2):  N_('All Souls'),
    (12, 8):  N_('The Immaculate Conception'),
    (12, 25): N_('The Nativity of Our Lord'),
    (12, 26): N_('St Stephen the Protomartyr'),
}

_ORTHODOX_FEASTS = {
    (9, 8):   N_('The Nativity of the Theotokos'),
    (9, 14):  N_('The Exaltation of the Holy Cross'),
    (11, 21): N_('The Entry of the Theotokos into the Temple'),
    (12, 25): N_('The Nativity of Christ'),
    (1, 1):   N_('The Circumcision of Christ'),
    (1, 6):   N_('Theophany'),
    (2, 2):   N_('The Meeting of the Lord'),
    (3, 25):  N_('The Annunciation'),
    (6, 24):  N_('The Nativity of the Forerunner'),
    (6, 29):  N_('Ss Peter and Paul, Apostles'),
    (8, 6):   N_('The Transfiguration'),
    (8, 15):  N_('The Dormition of the Theotokos'),
    (8, 29):  N_('The Beheading of the Forerunner'),
}

_FEASTS = {'anglican': _ANGLICAN_FEASTS, 'roman': _ROMAN_FEASTS,
           'orthodox': _ORTHODOX_FEASTS}


# ── Movable holy days (exact weekdays, not Sundays) ──────────────────────────

def _western_movables(easter: datetime.date,
                      roman: bool) -> dict[datetime.date, Designation]:
    days = {
        easter - datetime.timedelta(days=46): ('ash_wednesday', N_('Ash Wednesday')),
        easter - datetime.timedelta(days=3):  ('maundy_thursday', N_('Maundy Thursday')),
        easter - datetime.timedelta(days=2):  ('good_friday', N_('Good Friday')),
        easter - datetime.timedelta(days=1):  ('easter_even', N_('Easter Even')),
        easter + datetime.timedelta(days=39): ('ascension', N_('Ascension Day')),
    }
    if roman:
        days[easter + datetime.timedelta(days=60)] = (
            'corpus_christi', N_('Corpus Christi'))
    return days


def _orthodox_movables(pascha: datetime.date) -> dict[datetime.date, Designation]:
    return {
        pascha - datetime.timedelta(days=48): ('clean_monday', N_('Clean Monday')),
        pascha - datetime.timedelta(days=8):  ('lazarus_saturday', N_('Lazarus Saturday')),
        pascha - datetime.timedelta(days=2):  ('great_friday', N_('Great and Holy Friday')),
        pascha - datetime.timedelta(days=1):  ('great_saturday', N_('Great and Holy Saturday')),
        pascha + datetime.timedelta(days=39): ('ascension', N_('The Ascension')),
    }


# ── Sunday designations ──────────────────────────────────────────────────────

def _western_sunday(s: datetime.date, roman: bool) -> Designation:
    year = s.year
    easter = easter_gregorian(year)
    advent1 = advent_sunday(year)
    if s >= advent1:
        if s >= datetime.date(year, 12, 26):
            return 'christmas1', _('The Sunday after Christmas Day')
        if s == datetime.date(year, 12, 25):
            # Christmas on a Sunday: its week is Christmastide, not Advent.
            return 'christmastide', _('Christmastide')
        n = (s - advent1).days // 7 + 1
        return (f'advent{n}',
                _('The {ordinal} Sunday in Advent')
                .format(ordinal=_ordinal(n)))
    if s <= datetime.date(year, 1, 5):
        return 'christmas2', _('The Second Sunday after Christmas')
    septuagesima = easter - datetime.timedelta(days=63)
    if s < septuagesima:
        jan6 = datetime.date(year, 1, 6)
        first = jan6 + datetime.timedelta(days=((6 - jan6.weekday()) % 7 or 7))
        n = (s - first).days // 7 + 1
        if n < 1:
            # Epiphany itself fell on this Sunday; its feast serves the week.
            return 'epiphany_week', _('The Epiphany')
        n = min(n, 6)
        return (f'epiphany{n}',
                _('The {ordinal} Sunday after the Epiphany')
                .format(ordinal=_ordinal(n)))
    pre_lent = {
        septuagesima: ('septuagesima', _('Septuagesima')),
        easter - datetime.timedelta(days=56): ('sexagesima', _('Sexagesima')),
        easter - datetime.timedelta(days=49): ('quinquagesima', _('Quinquagesima')),
    }
    if s in pre_lent:
        return pre_lent[s]
    if s < easter:
        n = (s - (easter - datetime.timedelta(days=42))).days // 7 + 1
        if n == 6:
            return 'palm_sunday', _('Palm Sunday')
        if n == 5 and roman:
            return 'passion_sunday', _('Passion Sunday')
        return (f'lent{n}',
                _('The {ordinal} Sunday in Lent')
                .format(ordinal=_ordinal(n)))
    n = (s - easter).days // 7
    if n == 0:
        return 'easter', _('Easter Day')
    if n <= 5:
        if n == 1 and roman:
            return 'low_sunday', _('Low Sunday')
        return (f'easter{n}',
                _('The {ordinal} Sunday after Easter')
                .format(ordinal=_ordinal(n)))
    if n == 6:
        return 'ascension1', _('The Sunday after Ascension Day')
    if n == 7:
        return ('pentecost', _('Pentecost')) if roman else ('whitsun', _('Whitsunday'))
    if n == 8:
        return 'trinity', _('Trinity Sunday')
    last = s + datetime.timedelta(days=7) >= advent1
    if roman:
        if last:
            return 'pentecost_last', _('The Last Sunday after Pentecost')
        return (f'pentecost{n - 7}',
                _('The {ordinal} Sunday after Pentecost')
                .format(ordinal=_ordinal(n - 7)))
    if last:
        return 'next_before_advent', _('The Sunday next before Advent')
    return (f'trinity{n - 8}',
            _('The {ordinal} Sunday after Trinity')
            .format(ordinal=_ordinal(n - 8)))


_LENT_SUNDAYS = [N_('Sunday of Orthodoxy'),
                 N_('Sunday of St Gregory Palamas'),
                 N_('Sunday of the Holy Cross'),
                 N_('Sunday of St John Climacus'),
                 N_('Sunday of St Mary of Egypt')]

_PASCHAL_SUNDAYS = [N_('Thomas Sunday'),
                    N_('Sunday of the Myrrh-bearing Women'),
                    N_('Sunday of the Paralytic'),
                    N_('Sunday of the Samaritan Woman'),
                    N_('Sunday of the Blind Man')]


def _orthodox_sunday(s: datetime.date) -> Designation:
    pascha = pascha_gregorian(s.year)
    triodion = pascha - datetime.timedelta(days=70)
    if s < triodion:
        # Winter Sundays continue last year's after-Pentecost count.
        pascha = pascha_gregorian(s.year - 1)
    pre = {
        pascha - datetime.timedelta(days=70):
            ('publican_pharisee', _('Sunday of the Publican and the Pharisee')),
        pascha - datetime.timedelta(days=63):
            ('prodigal_son', _('Sunday of the Prodigal Son')),
        pascha - datetime.timedelta(days=56):
            ('meatfare', _('Sunday of the Last Judgment (Meatfare)')),
        pascha - datetime.timedelta(days=49):
            ('cheesefare', _('Sunday of Forgiveness (Cheesefare)')),
    }
    if s in pre:
        return pre[s]
    if s < pascha:
        n = (s - (pascha - datetime.timedelta(days=42))).days // 7 + 1
        if n == 6:
            return 'palm_sunday', _('Palm Sunday')
        return f'great_lent{n}', _(_LENT_SUNDAYS[n - 1])
    n = (s - pascha).days // 7
    if n == 0:
        return 'pascha', _('Pascha')
    if n <= 5:
        return f'pascha{n}', _(_PASCHAL_SUNDAYS[n - 1])
    if n == 6:
        return 'nicaea_fathers', _('Sunday of the Fathers of the First Council')
    if n == 7:
        return 'pentecost', _('Pentecost')
    if n == 8:
        return 'all_saints', _('The Sunday of All Saints')
    return (f'pentecost{n - 7}',
            _('The {ordinal} Sunday after Pentecost')
                .format(ordinal=_ordinal(n - 7)))


# ── Public API ───────────────────────────────────────────────────────────────

def day_designation(date: datetime.date, tradition: str) -> Designation | None:
    """The liturgical designation for a civil date under `tradition`.

    Precedence (deliberately simple — no transfer rules): a movable holy
    day names its exact date; a principal fixed feast names its civil day;
    every other day carries its week's Sunday designation, the way the
    Sunday collect serves the week. Returns None for unknown traditions.
    """
    if tradition not in TRADITIONS:
        return None
    if tradition == 'orthodox':
        movables = _orthodox_movables(pascha_gregorian(date.year))
    else:
        movables = _western_movables(easter_gregorian(date.year),
                                     tradition == 'roman')
    if date in movables:
        key, name = movables[date]
        return f'{tradition}:{key}', _(name)
    feast = _FEASTS[tradition].get((date.month, date.day))
    if feast:
        return f'{tradition}:feast:{date.month}-{date.day}', _(feast)
    sunday = date - datetime.timedelta(days=(date.weekday() + 1) % 7)
    if tradition == 'orthodox':
        key, name = _orthodox_sunday(sunday)
    else:
        key, name = _western_sunday(sunday, tradition == 'roman')
    return f'{tradition}:{key}', name
