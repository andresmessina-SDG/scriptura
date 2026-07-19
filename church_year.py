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

Strings are English for now (composing ~150 proper names through gettext
tables is its own project — noted as a known limitation).
"""

import datetime

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

_UNITS = ['', 'First', 'Second', 'Third', 'Fourth', 'Fifth', 'Sixth',
          'Seventh', 'Eighth', 'Ninth', 'Tenth', 'Eleventh', 'Twelfth',
          'Thirteenth', 'Fourteenth', 'Fifteenth', 'Sixteenth',
          'Seventeenth', 'Eighteenth', 'Nineteenth']
_TENS = {20: 'Twentieth', 30: 'Thirtieth', 40: 'Fortieth'}
_TENS_PREFIX = {20: 'Twenty', 30: 'Thirty'}


def _ordinal(n: int) -> str:
    if 0 < n < 20:
        return _UNITS[n]
    if n in _TENS:
        return _TENS[n]
    tens, unit = divmod(n, 10)
    prefix = _TENS_PREFIX.get(tens * 10)
    if prefix and 0 < unit < 10:
        return f'{prefix}-{_UNITS[unit].lower()}'
    return str(n)


# ── Principal fixed feasts (month, day) → (key suffix, display) ──────────────

_ANGLICAN_FEASTS = {
    (1, 1):   'The Circumcision of Christ',
    (1, 6):   'The Epiphany',
    (1, 25):  'The Conversion of St Paul',
    (2, 2):   'The Presentation of Christ in the Temple',
    (2, 24):  'St Matthias the Apostle',
    (3, 25):  'The Annunciation',
    (4, 25):  'St Mark the Evangelist',
    (5, 1):   'St Philip and St James, Apostles',
    (6, 11):  'St Barnabas the Apostle',
    (6, 24):  'The Nativity of St John the Baptist',
    (6, 29):  'St Peter the Apostle',
    (7, 25):  'St James the Apostle',
    (8, 24):  'St Bartholomew the Apostle',
    (9, 21):  'St Matthew the Apostle',
    (9, 29):  'St Michael and All Angels',
    (10, 18): 'St Luke the Evangelist',
    (10, 28): 'St Simon and St Jude, Apostles',
    (11, 1):  "All Saints' Day",
    (11, 30): 'St Andrew the Apostle',
    (12, 21): 'St Thomas the Apostle',
    (12, 25): 'Christmas Day',
    (12, 26): 'St Stephen the Martyr',
    (12, 27): 'St John the Evangelist',
    (12, 28): 'The Holy Innocents',
}

_ROMAN_FEASTS = {
    (1, 1):   'The Circumcision of Our Lord',
    (1, 6):   'The Epiphany of Our Lord',
    (2, 2):   'The Purification of the Blessed Virgin Mary',
    (3, 19):  'St Joseph, Spouse of the Blessed Virgin Mary',
    (3, 25):  'The Annunciation',
    (6, 24):  'The Nativity of St John the Baptist',
    (6, 29):  'Ss Peter and Paul, Apostles',
    (7, 25):  'St James the Apostle',
    (8, 6):   'The Transfiguration of Our Lord',
    (8, 15):  'The Assumption of the Blessed Virgin Mary',
    (9, 29):  'St Michael the Archangel',
    (11, 1):  'All Saints',
    (11, 2):  'All Souls',
    (12, 8):  'The Immaculate Conception',
    (12, 25): 'The Nativity of Our Lord',
    (12, 26): 'St Stephen the Protomartyr',
}

_ORTHODOX_FEASTS = {
    (9, 8):   'The Nativity of the Theotokos',
    (9, 14):  'The Exaltation of the Holy Cross',
    (11, 21): 'The Entry of the Theotokos into the Temple',
    (12, 25): 'The Nativity of Christ',
    (1, 1):   'The Circumcision of Christ',
    (1, 6):   'Theophany',
    (2, 2):   'The Meeting of the Lord',
    (3, 25):  'The Annunciation',
    (6, 24):  'The Nativity of the Forerunner',
    (6, 29):  'Ss Peter and Paul, Apostles',
    (8, 6):   'The Transfiguration',
    (8, 15):  'The Dormition of the Theotokos',
    (8, 29):  'The Beheading of the Forerunner',
}

_FEASTS = {'anglican': _ANGLICAN_FEASTS, 'roman': _ROMAN_FEASTS,
           'orthodox': _ORTHODOX_FEASTS}


# ── Movable holy days (exact weekdays, not Sundays) ──────────────────────────

def _western_movables(easter: datetime.date,
                      roman: bool) -> dict[datetime.date, Designation]:
    days = {
        easter - datetime.timedelta(days=46): ('ash_wednesday', 'Ash Wednesday'),
        easter - datetime.timedelta(days=3):  ('maundy_thursday', 'Maundy Thursday'),
        easter - datetime.timedelta(days=2):  ('good_friday', 'Good Friday'),
        easter - datetime.timedelta(days=1):  ('easter_even', 'Easter Even'),
        easter + datetime.timedelta(days=39): ('ascension', 'Ascension Day'),
    }
    if roman:
        days[easter + datetime.timedelta(days=60)] = (
            'corpus_christi', 'Corpus Christi')
    return days


def _orthodox_movables(pascha: datetime.date) -> dict[datetime.date, Designation]:
    return {
        pascha - datetime.timedelta(days=48): ('clean_monday', 'Clean Monday'),
        pascha - datetime.timedelta(days=8):  ('lazarus_saturday', 'Lazarus Saturday'),
        pascha - datetime.timedelta(days=2):  ('great_friday', 'Great and Holy Friday'),
        pascha - datetime.timedelta(days=1):  ('great_saturday', 'Great and Holy Saturday'),
        pascha + datetime.timedelta(days=39): ('ascension', 'The Ascension'),
    }


# ── Sunday designations ──────────────────────────────────────────────────────

def _western_sunday(s: datetime.date, roman: bool) -> Designation:
    year = s.year
    easter = easter_gregorian(year)
    advent1 = advent_sunday(year)
    if s >= advent1:
        if s >= datetime.date(year, 12, 26):
            return 'christmas1', 'The Sunday after Christmas Day'
        if s == datetime.date(year, 12, 25):
            # Christmas on a Sunday: its week is Christmastide, not Advent.
            return 'christmastide', 'Christmastide'
        n = (s - advent1).days // 7 + 1
        return f'advent{n}', f'The {_ordinal(n)} Sunday in Advent'
    if s <= datetime.date(year, 1, 5):
        return 'christmas2', 'The Second Sunday after Christmas'
    septuagesima = easter - datetime.timedelta(days=63)
    if s < septuagesima:
        jan6 = datetime.date(year, 1, 6)
        first = jan6 + datetime.timedelta(days=((6 - jan6.weekday()) % 7 or 7))
        n = (s - first).days // 7 + 1
        if n < 1:
            # Epiphany itself fell on this Sunday; its feast serves the week.
            return 'epiphany_week', 'The Epiphany'
        n = min(n, 6)
        return (f'epiphany{n}',
                f'The {_ordinal(n)} Sunday after the Epiphany')
    pre_lent = {
        septuagesima: ('septuagesima', 'Septuagesima'),
        easter - datetime.timedelta(days=56): ('sexagesima', 'Sexagesima'),
        easter - datetime.timedelta(days=49): ('quinquagesima', 'Quinquagesima'),
    }
    if s in pre_lent:
        return pre_lent[s]
    if s < easter:
        n = (s - (easter - datetime.timedelta(days=42))).days // 7 + 1
        if n == 6:
            return 'palm_sunday', 'Palm Sunday'
        if n == 5 and roman:
            return 'passion_sunday', 'Passion Sunday'
        return f'lent{n}', f'The {_ordinal(n)} Sunday in Lent'
    n = (s - easter).days // 7
    if n == 0:
        return 'easter', 'Easter Day'
    if n <= 5:
        if n == 1 and roman:
            return 'low_sunday', 'Low Sunday'
        return f'easter{n}', f'The {_ordinal(n)} Sunday after Easter'
    if n == 6:
        return 'ascension1', 'The Sunday after Ascension Day'
    if n == 7:
        return ('pentecost', 'Pentecost') if roman else ('whitsun', 'Whitsunday')
    if n == 8:
        return 'trinity', 'Trinity Sunday'
    last = s + datetime.timedelta(days=7) >= advent1
    if roman:
        if last:
            return 'pentecost_last', 'The Last Sunday after Pentecost'
        return (f'pentecost{n - 7}',
                f'The {_ordinal(n - 7)} Sunday after Pentecost')
    if last:
        return 'next_before_advent', 'The Sunday next before Advent'
    return (f'trinity{n - 8}',
            f'The {_ordinal(n - 8)} Sunday after Trinity')


_LENT_SUNDAYS = ['Sunday of Orthodoxy', 'Sunday of St Gregory Palamas',
                 'Sunday of the Holy Cross', 'Sunday of St John Climacus',
                 'Sunday of St Mary of Egypt']

_PASCHAL_SUNDAYS = ['Thomas Sunday', 'Sunday of the Myrrh-bearing Women',
                    'Sunday of the Paralytic', 'Sunday of the Samaritan Woman',
                    'Sunday of the Blind Man']


def _orthodox_sunday(s: datetime.date) -> Designation:
    pascha = pascha_gregorian(s.year)
    triodion = pascha - datetime.timedelta(days=70)
    if s < triodion:
        # Winter Sundays continue last year's after-Pentecost count.
        pascha = pascha_gregorian(s.year - 1)
    pre = {
        pascha - datetime.timedelta(days=70):
            ('publican_pharisee', 'Sunday of the Publican and the Pharisee'),
        pascha - datetime.timedelta(days=63):
            ('prodigal_son', 'Sunday of the Prodigal Son'),
        pascha - datetime.timedelta(days=56):
            ('meatfare', 'Sunday of the Last Judgment (Meatfare)'),
        pascha - datetime.timedelta(days=49):
            ('cheesefare', 'Sunday of Forgiveness (Cheesefare)'),
    }
    if s in pre:
        return pre[s]
    if s < pascha:
        n = (s - (pascha - datetime.timedelta(days=42))).days // 7 + 1
        if n == 6:
            return 'palm_sunday', 'Palm Sunday'
        return f'great_lent{n}', _LENT_SUNDAYS[n - 1]
    n = (s - pascha).days // 7
    if n == 0:
        return 'pascha', 'Pascha'
    if n <= 5:
        return f'pascha{n}', _PASCHAL_SUNDAYS[n - 1]
    if n == 6:
        return 'nicaea_fathers', 'Sunday of the Fathers of the First Council'
    if n == 7:
        return 'pentecost', 'Pentecost'
    if n == 8:
        return 'all_saints', 'The Sunday of All Saints'
    return (f'pentecost{n - 7}',
            f'The {_ordinal(n - 7)} Sunday after Pentecost')


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
        return f'{tradition}:{key}', name
    feast = _FEASTS[tradition].get((date.month, date.day))
    if feast:
        return f'{tradition}:feast:{date.month}-{date.day}', feast
    sunday = date - datetime.timedelta(days=(date.weekday() + 1) % 7)
    if tradition == 'orthodox':
        key, name = _orthodox_sunday(sunday)
    else:
        key, name = _western_sunday(sunday, tradition == 'roman')
    return f'{tradition}:{key}', name
