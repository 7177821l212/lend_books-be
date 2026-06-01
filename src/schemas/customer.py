from pydantic import BaseModel

from src.constants.enums import RiskLevel


class CustomerCreate(BaseModel):
    name: str
    phone: str
    location: str | None = None
    risk_level: RiskLevel = RiskLevel.MEDIUM


class CustomerUpdate(BaseModel):
    name: str | None = None
    phone: str | None = None
    location: str | None = None
    risk_level: RiskLevel | None = None


class CustomerResponse(BaseModel):
    id: str
    name: str
    phone: str
    location: str | None
    risk_level: RiskLevel
    is_blacklisted: bool
    active_loan_count: int = 0
    total_outstanding: int = 0

    model_config = {"from_attributes": True}


class BlacklistRequest(BaseModel):
    reason: str
