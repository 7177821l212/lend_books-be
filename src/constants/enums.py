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


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class CollectorStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
