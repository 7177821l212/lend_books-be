from enum import Enum


class UserRole(str, Enum):
    INVESTOR = "investor"
    COLLECTOR = "collector"


class LoanStatus(str, Enum):
    ACTIVE = "active"
    OVERDUE = "overdue"
    CLOSED = "closed"
    CANCELLED = "cancelled"


class InstallmentStatus(str, Enum):
    PENDING = "pending"
    DUE_TODAY = "due_today"
    OVERDUE = "overdue"
    PAID = "paid"
    PARTIAL = "partial"
    MISSED = "missed"


class PaymentMode(str, Enum):
    CASH = "CASH"
    UPI = "UPI"
    BANK = "BANK"


class RepaymentFrequency(str, Enum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    HALF_YEARLY = "half_yearly"
    YEARLY = "yearly"
    CUSTOM = "custom"


class InterestType(str, Enum):
    PCT = "pct"  # percentage of principal
    FIXED = "fixed"  # fixed rupee amount


class LendingModel(str, Enum):
    MODEL_A = "model_a"  # interest deducted up-front: customer receives principal - interest
    MODEL_B = "model_b"  # interest added on top: customer repays principal + interest


class CollectionMode(str, Enum):
    """How a loan tracks what is owed.

    SCHEDULE loans are the original model: the repayable amount is split into
    dated installments and collections are allocated against them. BALANCE loans
    keep no schedule at all — a running total collected against the repayable
    amount, the way a collector keeps a notebook.
    """

    SCHEDULE = "schedule"
    BALANCE = "balance"


class RescheduleMode(str, Enum):
    """How the investor wants a replacement plan derived."""

    SAME_END_DATE = "same_end_date"  # keep the finish day, shrink each visit
    SAME_INSTALLMENT = "same_installment"  # keep the visit amount, shorten the term
    MANUAL = "manual"  # investor supplies every row explicitly


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class CollectorStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"


# Statuses whose installments still expect money. MISSED is deliberately absent:
# a missed visit is compensated by an extra row appended to the schedule, so
# counting the missed row too would double the outstanding balance.
OPEN_INSTALLMENT_STATUSES: tuple[str, ...] = (
    InstallmentStatus.PENDING.value,
    InstallmentStatus.DUE_TODAY.value,
    InstallmentStatus.OVERDUE.value,
    InstallmentStatus.PARTIAL.value,
)
