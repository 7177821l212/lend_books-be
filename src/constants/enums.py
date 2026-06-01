from enum import Enum


class UserRole(str, Enum):
    INVESTOR = "investor"
    COLLECTOR = "collector"


class LoanStatus(str, Enum):
    ACTIVE = "active"
    OVERDUE = "overdue"
    CLOSED = "closed"


class InstallmentStatus(str, Enum):
    PENDING = "pending"
    DUE_TODAY = "due_today"
    OVERDUE = "overdue"
    PAID = "paid"


class PaymentMode(str, Enum):
    CASH = "CASH"
    UPI = "UPI"
    BANK = "BANK"


class RepaymentFrequency(str, Enum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class LendingModel(str, Enum):
    MODEL_A = "model_a"  # deducted up-front: customer receives principal - interest


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class CollectorStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
