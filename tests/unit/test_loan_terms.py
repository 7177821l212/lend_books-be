"""Unit tests for loan terms calculator + schedule generator."""

from datetime import date

import pytest

from src.constants.enums import InterestType, LendingModel, RepaymentFrequency
from src.core.services.loan_terms import (
    compute_terms,
    generate_schedule,
    split_installment,
)


@pytest.mark.unit
class TestComputeTerms:
    def test_model_a_pct_basic(self) -> None:
        terms = compute_terms(
            principal=10000,
            interest_type=InterestType.PCT,
            interest_value=10,
            lending_model=LendingModel.MODEL_A,
        )
        assert terms.interest_amount == 1000
        assert terms.disbursed == 9000
        assert terms.repayable == 10000
        assert terms.profit == 1000

    def test_model_b_pct_basic(self) -> None:
        terms = compute_terms(
            principal=10000,
            interest_type=InterestType.PCT,
            interest_value=10,
            lending_model=LendingModel.MODEL_B,
        )
        assert terms.interest_amount == 1000
        assert terms.disbursed == 10000
        assert terms.repayable == 11000
        assert terms.profit == 1000

    def test_model_a_fixed_interest(self) -> None:
        terms = compute_terms(
            principal=15000,
            interest_type=InterestType.FIXED,
            interest_value=1500,
            lending_model=LendingModel.MODEL_A,
        )
        assert terms.interest_amount == 1500
        assert terms.disbursed == 13500
        assert terms.repayable == 15000

    def test_model_b_fixed_interest(self) -> None:
        terms = compute_terms(
            principal=20000,
            interest_type=InterestType.FIXED,
            interest_value=2400,
            lending_model=LendingModel.MODEL_B,
        )
        assert terms.disbursed == 20000
        assert terms.repayable == 22400
        assert terms.profit == 2400

    def test_model_a_interest_exceeding_principal_raises(self) -> None:
        with pytest.raises(ValueError, match="interest cannot exceed principal"):
            compute_terms(
                principal=1000,
                interest_type=InterestType.FIXED,
                interest_value=2000,
                lending_model=LendingModel.MODEL_A,
            )

    def test_negative_principal_raises(self) -> None:
        with pytest.raises(ValueError, match="principal must be positive"):
            compute_terms(
                principal=-100,
                interest_type=InterestType.PCT,
                interest_value=10,
                lending_model=LendingModel.MODEL_A,
            )

    def test_pct_above_100_raises(self) -> None:
        with pytest.raises(ValueError, match="between 0 and 100"):
            compute_terms(
                principal=1000,
                interest_type=InterestType.PCT,
                interest_value=150,
                lending_model=LendingModel.MODEL_B,
            )

    def test_zero_interest_allowed(self) -> None:
        terms = compute_terms(
            principal=10000,
            interest_type=InterestType.PCT,
            interest_value=0,
            lending_model=LendingModel.MODEL_A,
        )
        assert terms.disbursed == 10000
        assert terms.repayable == 10000
        assert terms.profit == 0


@pytest.mark.unit
class TestSplitInstallment:
    def test_evenly_divides(self) -> None:
        base, amounts = split_installment(10000, 10)
        assert base == 1000
        assert sum(amounts) == 10000
        assert all(a == 1000 for a in amounts)

    def test_unevenly_divides_to_exact_total(self) -> None:
        base, amounts = split_installment(10003, 10)
        assert sum(amounts) == 10003
        assert base == 1000
        # Remainder distributed to first 3 rows
        assert amounts[0] == 1001
        assert amounts[1] == 1001
        assert amounts[2] == 1001
        assert amounts[3] == 1000


@pytest.mark.unit
class TestGenerateSchedule:
    def test_daily_schedule(self) -> None:
        _, rows = generate_schedule(
            start_date=date(2026, 1, 1),
            frequency=RepaymentFrequency.DAILY,
            frequency_meta=None,
            total_installments=5,
            repayable=5000,
        )
        assert len(rows) == 5
        assert rows[0].due_date == date(2026, 1, 1)
        assert rows[1].due_date == date(2026, 1, 2)
        assert rows[4].due_date == date(2026, 1, 5)
        assert sum(r.due_amount for r in rows) == 5000

    def test_weekly_schedule(self) -> None:
        _, rows = generate_schedule(
            start_date=date(2026, 1, 1),
            frequency=RepaymentFrequency.WEEKLY,
            frequency_meta=None,
            total_installments=4,
            repayable=8000,
        )
        assert rows[0].due_date == date(2026, 1, 1)
        assert rows[1].due_date == date(2026, 1, 8)
        assert rows[3].due_date == date(2026, 1, 22)

    def test_monthly_schedule_handles_short_months(self) -> None:
        # Starting 31 Jan; February has 28 days
        _, rows = generate_schedule(
            start_date=date(2026, 1, 31),
            frequency=RepaymentFrequency.MONTHLY,
            frequency_meta=None,
            total_installments=3,
            repayable=30000,
        )
        assert rows[0].due_date == date(2026, 1, 31)
        assert rows[1].due_date == date(2026, 2, 28)  # clamped
        assert rows[2].due_date == date(2026, 3, 31)

    def test_yearly_schedule(self) -> None:
        _, rows = generate_schedule(
            start_date=date(2026, 6, 15),
            frequency=RepaymentFrequency.YEARLY,
            frequency_meta=None,
            total_installments=3,
            repayable=30000,
        )
        assert rows[2].due_date == date(2028, 6, 15)

    def test_custom_schedule(self) -> None:
        _, rows = generate_schedule(
            start_date=date(2026, 1, 1),
            frequency=RepaymentFrequency.CUSTOM,
            frequency_meta={"dates": ["2026-01-15", "2026-03-20", "2026-08-01"]},
            total_installments=3,
            repayable=9000,
        )
        assert [r.due_date for r in rows] == [
            date(2026, 1, 15),
            date(2026, 3, 20),
            date(2026, 8, 1),
        ]

    def test_custom_missing_dates_raises(self) -> None:
        with pytest.raises(ValueError, match="frequency_meta.dates"):
            generate_schedule(
                start_date=date(2026, 1, 1),
                frequency=RepaymentFrequency.CUSTOM,
                frequency_meta=None,
                total_installments=2,
                repayable=2000,
            )
