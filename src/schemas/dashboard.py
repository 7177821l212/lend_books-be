"""Dashboard + reports schemas."""

from datetime import date

from pydantic import BaseModel


class DashboardKPIs(BaseModel):
    """Investor home-screen aggregates."""

    capital_disbursed: int
    outstanding: int
    collected_lifetime: int
    collected_today: int
    profit_realised: int
    active_loans: int
    closed_loans: int
    overdue_loans: int
    overdue_amount: int
    active_customers: int
    total_customers: int


class TrendPoint(BaseModel):
    day: date
    amount: int


class CollectionSummary(BaseModel):
    start_date: date
    end_date: date
    total_collected: int
    total_payments: int
    cash_collected: int
    upi_collected: int
    bank_collected: int
    active_collectors: int


class CollectorPerformance(BaseModel):
    id: str
    name: str
    collected: int
    missed: int
    visits: int
    collection_days: int = 0
    average_per_day: int = 0
    last_collection_date: date | None = None


class DashboardResponse(BaseModel):
    kpis: DashboardKPIs
    trend_30d: list[TrendPoint]
    collection_summary: CollectionSummary
    collector_performance: list[CollectorPerformance]


class BlacklistedCustomerRow(BaseModel):
    customer_id: str
    name: str
    phone: str
    reason: str | None = None


class ReportsResponse(BaseModel):
    """Reports no longer carry an overdue list.

    Overdue is an installment concept, and new lending is balance-only — those
    loans have no due dates, so the list could only ever shrink toward covering
    nothing while appearing to report on everything.
    """

    blacklisted: list[BlacklistedCustomerRow]
    collection_summary: CollectionSummary
    collection_trend: list[TrendPoint]
    collector_performance: list[CollectorPerformance]
    total_interest_earned: int
    avg_loan_size: int
    avg_interest_rate: float
