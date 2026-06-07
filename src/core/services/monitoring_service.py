import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import google.auth
import google.auth.transport.requests
import httpx

from src.config.settings import settings

logger = logging.getLogger(__name__)

_MONITORING_BASE = "https://monitoring.googleapis.com/v3"
_SERVICE = "lendbook-be"

_CLOUD_RUN_PRICE_PER_MILLION_REQ = 0.40
_CLOUD_RUN_FREE_REQUESTS = 2_000_000
_CLOUD_SQL_MONTHLY_USD = 10.00
_CLOUD_STORAGE_MONTHLY_USD = 1.00


def _get_token() -> str | None:
    try:
        creds, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/monitoring.read"]
        )
        creds.refresh(google.auth.transport.requests.Request())
        return creds.token
    except Exception as e:
        logger.warning("Could not obtain monitoring credentials: %s", e)
        return None


async def _query_request_counts(token: str, start: datetime, end: datetime) -> list[dict]:
    params = {
        "filter": (
            f'metric.type="run.googleapis.com/request_count"'
            f' AND resource.type="cloud_run_revision"'
            f' AND resource.labels.service_name="{_SERVICE}"'
        ),
        "interval.startTime": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "interval.endTime": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "aggregation.alignmentPeriod": "86400s",
        "aggregation.perSeriesAligner": "ALIGN_SUM",
        "aggregation.crossSeriesReducer": "REDUCE_SUM",
        "aggregation.groupByFields": "resource.labels.service_name",
    }
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"{_MONITORING_BASE}/projects/{settings.GCP_PROJECT}/timeSeries",
            headers={"Authorization": f"Bearer {token}"},
            params=params,
        )
    if resp.status_code != 200:
        logger.warning("Cloud Monitoring returned %d: %s", resp.status_code, resp.text[:300])
        return []
    return resp.json().get("timeSeries", [])


def _extract_daily(series: list[dict]) -> list[dict[str, Any]]:
    by_date: dict[str, int] = {}
    for ts in series:
        for point in ts.get("points", []):
            date = point.get("interval", {}).get("endTime", "")[:10]
            val = point.get("value", {})
            count = int(val.get("int64Value", val.get("doubleValue", 0)))
            by_date[date] = by_date.get(date, 0) + count
    return [{"date": d, "count": c} for d, c in sorted(by_date.items())]


async def get_metrics() -> dict[str, Any]:
    now = datetime.now(UTC)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    thirty_ago = now - timedelta(days=30)

    token = _get_token()
    if not token:
        return _fallback(now)

    try:
        series = await _query_request_counts(token, thirty_ago, now)
        daily = _extract_daily(series)

        requests_month = sum(d["count"] for d in daily if d["date"] >= month_start.strftime("%Y-%m-%d"))
        requests_today = daily[-1]["count"] if daily else 0

        billable = max(0, requests_month - _CLOUD_RUN_FREE_REQUESTS)
        cloud_run_cost = (billable / 1_000_000) * _CLOUD_RUN_PRICE_PER_MILLION_REQ
        total = cloud_run_cost + _CLOUD_SQL_MONTHLY_USD + _CLOUD_STORAGE_MONTHLY_USD

        return {
            "requests": {
                "today": requests_today,
                "this_month": requests_month,
                "free_tier_remaining": max(0, _CLOUD_RUN_FREE_REQUESTS - requests_month),
                "daily": daily,
            },
            "cost_estimate": {
                "cloud_run_usd": round(cloud_run_cost, 4),
                "cloud_sql_usd": _CLOUD_SQL_MONTHLY_USD,
                "cloud_storage_usd": _CLOUD_STORAGE_MONTHLY_USD,
                "total_usd": round(total, 2),
                "cost_per_1k_requests_usd": round((total / max(requests_month, 1)) * 1000, 4),
            },
            "period": now.strftime("%Y-%m"),
            "last_updated": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
    except Exception as e:
        logger.error("Metrics fetch failed: %s", e, exc_info=True)
        return _fallback(now)


def _fallback(now: datetime) -> dict[str, Any]:
    total = _CLOUD_SQL_MONTHLY_USD + _CLOUD_STORAGE_MONTHLY_USD
    return {
        "requests": {
            "today": 0,
            "this_month": 0,
            "free_tier_remaining": _CLOUD_RUN_FREE_REQUESTS,
            "daily": [],
        },
        "cost_estimate": {
            "cloud_run_usd": 0.0,
            "cloud_sql_usd": _CLOUD_SQL_MONTHLY_USD,
            "cloud_storage_usd": _CLOUD_STORAGE_MONTHLY_USD,
            "total_usd": total,
            "cost_per_1k_requests_usd": 0.0,
        },
        "period": now.strftime("%Y-%m"),
        "last_updated": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "error": "monitoring_unavailable",
    }
