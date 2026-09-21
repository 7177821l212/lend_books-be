"""Business-calendar helpers used for collection and reporting dates."""

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func
from sqlalchemy.sql.elements import ColumnElement

from src.config.settings import settings


def business_today() -> date:
    return datetime.now(ZoneInfo(settings.BUSINESS_TIMEZONE)).date()


def utc_day_bounds(day: date) -> tuple[datetime, datetime]:
    """Return the UTC interval covering one calendar day in the business timezone."""
    start = datetime.combine(day, time.min, tzinfo=ZoneInfo(settings.BUSINESS_TIMEZONE))
    start_utc = start.astimezone(UTC)
    return start_utc, start_utc + timedelta(days=1)


def business_noon_utc(day: date) -> datetime:
    """A UTC instant that always falls on `day` in the business timezone.

    A back-dated receipt only carries a date, but `collected_at` is a timestamp.
    Storing midnight would land on the previous day for timezones ahead of UTC
    and make the receipt appear under the wrong day; noon is comfortably inside
    the business day whichever way the offset runs.
    """
    local_noon = datetime.combine(
        day, time(hour=12), tzinfo=ZoneInfo(settings.BUSINESS_TIMEZONE)
    )
    return local_noon.astimezone(UTC)


def business_day_expr(column: ColumnElement[datetime]) -> ColumnElement[date]:
    """SQL expression for the business-calendar DAY a timestamp falls on.

    Grouping collections by day has to use the same timezone the rest of the
    app calls "today", or a trend chart drifts from the figures beside it. The
    zone was written literally into each query while every Python helper read
    it from settings, so changing the setting would have moved one and not the
    other.
    """
    return func.date(func.timezone(settings.BUSINESS_TIMEZONE, column))
