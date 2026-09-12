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


class CollectorPerformance(BaseModel):
    id: str
    name: str
    collected: int
    missed: int
    visits: int


class DashboardResponse(BaseModel):
    kpis: DashboardKPIs
    trend_30d: list[TrendPoint]
    collector_performance: list[CollectorPerformance]


class OverdueLoanRow(BaseModel):
    loan_id: str
    customer_id: str
    customer_name: str
    collector_id: str
    collector_name: str
    overdue_installments: int
    overdue_amount: int


class BlacklistedCustomerRow(BaseModel):
    customer_id: str
    name: str
    phone: str
    reason: str | None = None


class ReportsResponse(BaseModel):
    overdue: list[OverdueLoanRow]
    blacklisted: list[BlacklistedCustomerRow]
    total_interest_earned: int
    avg_loan_size: int
    avg_interest_rate: float
