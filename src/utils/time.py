"""Business-calendar helpers used for collection and reporting dates."""

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

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
