"""Customer-related Pydantic schemas."""

from datetime import datetime

from pydantic import BaseModel, Field

from src.constants.enums import RiskLevel


class CustomerCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    phone: str = Field(min_length=10, max_length=20)
    location: str | None = Field(default=None, max_length=255)
    risk_level: RiskLevel = RiskLevel.MEDIUM


class CustomerUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    phone: str | None = Field(default=None, min_length=10, max_length=20)
    location: str | None = Field(default=None, max_length=255)
    risk_level: RiskLevel | None = None
    photo_url: str | None = Field(default=None, max_length=1024)


class CustomerResponse(BaseModel):
    id: str
    name: str
    phone: str
    location: str | None = None
    risk_level: RiskLevel
    is_blacklisted: bool
    blacklist_reason: str | None = None
    active_loan_count: int = 0
    total_outstanding: int = 0
    photo_url: str | None = None

    model_config = {"from_attributes": True}


class BlacklistRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class DocumentUploadRequest(BaseModel):
    doc_type: str = Field(min_length=1, max_length=50)
    file_url: str = Field(min_length=1, max_length=500)


class DocumentResponse(BaseModel):
    id: str
    customer_id: str
    doc_type: str
    file_url: str
    uploaded_by: str
    uploaded_at: datetime

    model_config = {"from_attributes": True}
