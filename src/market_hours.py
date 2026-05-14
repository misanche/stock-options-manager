"""US market hours detection utility.

Determines whether the US stock market is currently open based on
regular trading hours (Mon–Fri 9:30 AM – 4:00 PM Eastern), excluding
federal holidays observed by NYSE/NASDAQ.
"""

import logging
from datetime import date, datetime, time

import pytz

logger = logging.getLogger(__name__)

_ET = pytz.timezone("US/Eastern")

# Regular trading hours (Eastern Time)
_MARKET_OPEN = time(9, 30)
_MARKET_CLOSE = time(16, 0)

# -------------------------------------------------------------------
# US market holidays — rule-based for any year
# -------------------------------------------------------------------

def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """Return the *n*-th occurrence of *weekday* (0=Mon) in *month*."""
    first = date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return date(year, month, 1 + offset + 7 * (n - 1))


def _easter(year: int) -> date:
    """Anonymous Gregorian algorithm for Easter Sunday."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7  # noqa: E741
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return date(year, month, day + 1)


def _good_friday(year: int) -> date:
    from datetime import timedelta
    return _easter(year) - timedelta(days=2)


def us_market_holidays(year: int) -> set[date]:
    """Return the set of NYSE-observed holidays for *year*.

    Covers: New Year's Day, MLK Day, Presidents' Day, Good Friday,
    Memorial Day, Juneteenth, Independence Day, Labor Day,
    Thanksgiving, Christmas.

    When a holiday falls on Saturday it is observed on Friday; when it
    falls on Sunday it is observed on Monday.
    """
    holidays: set[date] = set()

    def _observe(d: date) -> date:
        if d.weekday() == 5:  # Saturday → Friday
            return d.replace(day=d.day - 1)
        if d.weekday() == 6:  # Sunday → Monday
            return d.replace(day=d.day + 1)
        return d

    # Fixed-date holidays (with weekend adjustment)
    holidays.add(_observe(date(year, 1, 1)))    # New Year's Day
    holidays.add(_observe(date(year, 6, 19)))   # Juneteenth
    holidays.add(_observe(date(year, 7, 4)))    # Independence Day
    holidays.add(_observe(date(year, 12, 25)))  # Christmas

    # Floating holidays
    holidays.add(_nth_weekday(year, 1, 0, 3))   # MLK Day — 3rd Monday Jan
    holidays.add(_nth_weekday(year, 2, 0, 3))   # Presidents' Day — 3rd Mon Feb
    holidays.add(_good_friday(year))             # Good Friday
    # Memorial Day — last Monday in May
    last_mon_may = date(year, 5, 31)
    while last_mon_may.weekday() != 0:
        last_mon_may = last_mon_may.replace(day=last_mon_may.day - 1)
    holidays.add(last_mon_may)
    holidays.add(_nth_weekday(year, 9, 0, 1))   # Labor Day — 1st Monday Sep
    holidays.add(_nth_weekday(year, 11, 3, 4))  # Thanksgiving — 4th Thursday Nov

    return holidays


def is_us_market_open(now: datetime | None = None) -> bool:
    """Return *True* if the US stock market is currently in regular
    trading hours.

    Parameters
    ----------
    now : datetime, optional
        Override for current time (must be timezone-aware).  Defaults to
        ``datetime.now(pytz.UTC)``.
    """
    if now is None:
        now = datetime.now(pytz.UTC)

    et_now = now.astimezone(_ET)

    # Weekend check
    if et_now.weekday() >= 5:
        return False

    # Holiday check
    if et_now.date() in us_market_holidays(et_now.year):
        return False

    # Time-of-day check
    current_time = et_now.time()
    return _MARKET_OPEN <= current_time < _MARKET_CLOSE
