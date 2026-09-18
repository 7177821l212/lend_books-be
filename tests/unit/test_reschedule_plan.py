"""Unit tests for the investor reschedule plan builder."""

from datetime import date

import pytest

from src.constants.enums import RepaymentFrequency
from src.core.services.loan_terms import build_reschedule_plan


def _daily_dates(start: date, count: int) -> list[date]:
    from datetime import timedelta

    return [start + timedelta(days=i) for i in range(count)]


class TestSameEndDate:
    """Keep the contracted finish day; each remaining visit gets smaller."""

    def test_redistributes_remaining_across_the_same_dates(self) -> None:
        dates = _daily_dates(date(2026, 9, 18), 5)
        rows = build_reschedule_plan(
            mode="same_end_date",
            remaining=5_000,
            open_due_dates=dates,
            first_due_date=dates[0],
            frequency=RepaymentFrequency.DAILY,
            frequency_meta=None,
        )
        assert [row.due_date for row in rows] == dates
        assert [row.due_amount for row in rows] == [1_000] * 5
        assert sum(row.due_amount for row in rows) == 5_000

    def test_uneven_split_still_sums_exactly(self) -> None:
        dates = _daily_dates(date(2026, 9, 18), 3)
        rows = build_reschedule_plan(
            mode="same_end_date",
            remaining=1_000,
            open_due_dates=dates,
            first_due_date=dates[0],
            frequency=RepaymentFrequency.DAILY,
            frequency_meta=None,
        )
        assert [row.due_amount for row in rows] == [334, 333, 333]
        assert sum(row.due_amount for row in rows) == 1_000
        assert rows[-1].due_date == dates[-1], "the end date must not move"

    def test_fewer_rupees_than_dates_still_keeps_the_end_date(self) -> None:
        dates = _daily_dates(date(2026, 9, 18), 5)
        rows = build_reschedule_plan(
            mode="same_end_date",
            remaining=3,
            open_due_dates=dates,
            first_due_date=dates[0],
            frequency=RepaymentFrequency.DAILY,
            frequency_meta=None,
        )
        assert [row.due_amount for row in rows] == [1, 1, 1]
        assert sum(row.due_amount for row in rows) == 3
        # Dates come off the front, never the contracted finish day.
        assert rows[-1].due_date == dates[-1]
        assert [row.due_date for row in rows] == dates[-3:]


class TestSameInstallment:
    """Keep the per-visit amount; the term shortens instead."""

    def test_keeps_the_daily_amount_and_shortens_the_term(self) -> None:
        rows = build_reschedule_plan(
            mode="same_installment",
            remaining=2_400,
            open_due_dates=_daily_dates(date(2026, 9, 18), 20),
            first_due_date=date(2026, 9, 18),
            frequency=RepaymentFrequency.DAILY,
            frequency_meta=None,
            installment_amount=240,
        )
        assert len(rows) == 10
        assert all(row.due_amount == 240 for row in rows)
        assert rows[0].due_date == date(2026, 9, 18)
        assert rows[-1].due_date == date(2026, 9, 27)
        assert sum(row.due_amount for row in rows) == 2_400

    def test_indivisible_remainder_rides_on_the_final_visit(self) -> None:
        rows = build_reschedule_plan(
            mode="same_installment",
            remaining=2_500,
            open_due_dates=_daily_dates(date(2026, 9, 18), 20),
            first_due_date=date(2026, 9, 18),
            frequency=RepaymentFrequency.DAILY,
            frequency_meta=None,
            installment_amount=240,
        )
        assert sum(row.due_amount for row in rows) == 2_500
        assert rows[-1].due_amount == 340, "no token ₹100 row tacked on the end"
        assert all(row.due_amount == 240 for row in rows[:-1])

    def test_amount_larger_than_balance_collapses_to_one_row(self) -> None:
        rows = build_reschedule_plan(
            mode="same_installment",
            remaining=150,
            open_due_dates=[date(2026, 9, 18)],
            first_due_date=date(2026, 9, 18),
            frequency=RepaymentFrequency.DAILY,
            frequency_meta=None,
            installment_amount=240,
        )
        assert [row.due_amount for row in rows] == [150]

    def test_weekly_cadence_is_respected(self) -> None:
        rows = build_reschedule_plan(
            mode="same_installment",
            remaining=3_000,
            open_due_dates=[date(2026, 9, 18)],
            first_due_date=date(2026, 9, 18),
            frequency=RepaymentFrequency.WEEKLY,
            frequency_meta=None,
            installment_amount=1_000,
        )
        assert [row.due_date for row in rows] == [
            date(2026, 9, 18),
            date(2026, 9, 25),
            date(2026, 10, 2),
        ]


class TestRejections:
    def test_nothing_left_to_reschedule(self) -> None:
        with pytest.raises(ValueError, match="nothing left"):
            build_reschedule_plan(
                mode="same_end_date",
                remaining=0,
                open_due_dates=[date(2026, 9, 18)],
                first_due_date=date(2026, 9, 18),
                frequency=RepaymentFrequency.DAILY,
                frequency_meta=None,
            )

    def test_same_installment_requires_a_positive_amount(self) -> None:
        with pytest.raises(ValueError, match="installment_amount"):
            build_reschedule_plan(
                mode="same_installment",
                remaining=1_000,
                open_due_dates=[date(2026, 9, 18)],
                first_due_date=date(2026, 9, 18),
                frequency=RepaymentFrequency.DAILY,
                frequency_meta=None,
                installment_amount=None,
            )

    def test_unknown_mode_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="unsupported reschedule mode"):
            build_reschedule_plan(
                mode="whatever",
                remaining=1_000,
                open_due_dates=[date(2026, 9, 18)],
                first_due_date=date(2026, 9, 18),
                frequency=RepaymentFrequency.DAILY,
                frequency_meta=None,
            )
