"""Request and response contracts for the policy-wording enquiry API."""
from datetime import datetime, timezone

from pydantic import BaseModel, Field


class PolicyEnquiryRequest(BaseModel):
    query: str = Field(min_length=3, max_length=2000)
    policyNumber: str | None = Field(default=None, max_length=100)
    claimId: str | None = Field(default=None, max_length=100)


class PolicyEnquirySource(BaseModel):
    title: str
    section: str
    excerpt: str
    confidence: float = Field(ge=0, le=1)


class PolicyEnquiryResponse(BaseModel):
    answer: str
    sources: list[PolicyEnquirySource]
    confidence: float = Field(ge=0, le=1)
    model: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
