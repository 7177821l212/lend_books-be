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
