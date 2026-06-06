"""Pure functions for loan term computation and schedule generation.

No DB access — easily unit-testable. All amounts are integer rupees.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from src.constants.enums import InterestType, LendingModel, RepaymentFrequency


@dataclass(frozen=True)
class LoanTerms:
    """Snapshot of a loan's financial terms at creation time."""

    principal: int
    interest_value: float
    interest_type: InterestType
    lending_model: LendingModel
    interest_amount: int  # rounded integer rupees
    disbursed: int  # amount handed to the customer
    repayable: int  # total customer must repay
    profit: int


@dataclass(frozen=True)
class ScheduleRow:
    sequence: int  # 1-based
    due_date: date
    due_amount: int


def compute_terms(
    *,
    principal: int,
    interest_type: InterestType,
    interest_value: float,
    lending_model: LendingModel,
) -> LoanTerms:
    """Compute disbursed/repayable/profit for a loan.

    Model A: customer receives Principal − Interest, repays Principal.
    Model B: customer receives Principal, repays Principal + Interest.
    """
    if principal <= 0:
        raise ValueError("principal must be positive")
    if interest_value < 0:
        raise ValueError("interest_value must be non-negative")

    if interest_type is InterestType.PCT:
        if not 0 <= interest_value <= 100:
            raise ValueError("percentage interest must be between 0 and 100")
        interest_amount = round(principal * interest_value / 100)
    else:  # FIXED
        interest_amount = round(interest_value)

    if lending_model is LendingModel.MODEL_A:
        if interest_amount >= principal:
            raise ValueError("interest cannot exceed principal in Model A")
        disbursed = principal - interest_amount
        repayable = principal
    else:  # MODEL_B
        disbursed = principal
        repayable = principal + interest_amount

    return LoanTerms(
        principal=principal,
        interest_value=interest_value,
        interest_type=interest_type,
        lending_model=lending_model,
        interest_amount=interest_amount,
        disbursed=disbursed,
        repayable=repayable,
        profit=interest_amount,
    )


def split_installment(repayable: int, n: int) -> tuple[int, list[int]]:
    """Split repayable into n integer installments — distribute remainder to first rows.

    Returns (base_amount, amounts_list). All amounts sum exactly to `repayable`.
    """
    if n <= 0:
        raise ValueError("installments must be positive")
    base = repayable // n
    remainder = repayable - base * n
    amounts = [base + (1 if i < remainder else 0) for i in range(n)]
    return base, amounts


def _add_months(d: date, months: int) -> date:
    """Add months, clamping day to end-of-month if necessary."""
    total = d.month - 1 + months
    year = d.year + total // 12
    month = total % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def generate_schedule(
    *,
    start_date: date,
    frequency: RepaymentFrequency,
    frequency_meta: dict[str, Any] | None,
    total_installments: int,
    repayable: int,
) -> tuple[int, int, list[ScheduleRow]]:
    """Generate (installment_base, installment_max, rows).

    The schedule splits `repayable` into `total_installments` integer rows so the
    sum equals `repayable` exactly. Any remainder is added to the first rows
    (each gets +1 rupee), so rows are EITHER `base` OR `base + 1`.

    Returns
    -------
    installment_base : the floor amount most rows carry
    installment_max  : the largest single-row amount (= base + 1 if remainder > 0)
    rows             : the schedule rows themselves
    """
    if total_installments <= 0:
        raise ValueError("total_installments must be positive")

    base, amounts = split_installment(repayable, total_installments)
    max_amount = max(amounts)

    rows: list[ScheduleRow] = []
    for i in range(total_installments):
        rows.append(
            ScheduleRow(
                sequence=i + 1,
                due_date=_date_for_index(start_date, i, frequency, frequency_meta),
                due_amount=amounts[i],
            )
        )
    return base, max_amount, rows


def _date_for_index(
    start: date,
    idx: int,
    frequency: RepaymentFrequency,
    meta: dict[str, Any] | None,
) -> date:
    """Compute the due_date for the (0-indexed) installment idx."""
    if frequency is RepaymentFrequency.DAILY:
        return start + timedelta(days=idx)
    if frequency is RepaymentFrequency.WEEKLY:
        return start + timedelta(days=7 * idx)
    if frequency is RepaymentFrequency.MONTHLY:
        return _add_months(start, idx)
    if frequency is RepaymentFrequency.HALF_YEARLY:
        return _add_months(start, 6 * idx)
    if frequency is RepaymentFrequency.YEARLY:
        return _add_months(start, 12 * idx)
    if frequency is RepaymentFrequency.CUSTOM:
        if not meta:
            raise ValueError("CUSTOM frequency requires frequency_meta")
        if "interval_days" in meta:
            interval = int(meta["interval_days"])
            if interval <= 0:
                raise ValueError("interval_days must be positive")
            return start + timedelta(days=interval * idx)
        if "dates" in meta:
            dates = meta["dates"]
            if idx >= len(dates):
                raise ValueError(
                    f"frequency_meta.dates has {len(dates)} entries; need at least {idx + 1}"
                )
            raw = dates[idx]
            return raw if isinstance(raw, date) else date.fromisoformat(str(raw))
        raise ValueError("CUSTOM frequency requires frequency_meta.interval_days or frequency_meta.dates")
    raise ValueError(f"unsupported frequency: {frequency}")
