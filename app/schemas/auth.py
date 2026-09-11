"""Schemas for the temporary local-account pilot, not enterprise SSO."""
from enum import Enum
from pydantic import BaseModel, Field, field_validator


class LocalUserRole(str, Enum):
    CLAIMANT = "CLAIMANT"
    VALIDATOR = "VALIDATOR"


class LocalRegistrationRequest(BaseModel):
    full_name: str = Field(min_length=2, max_length=255)
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=12, max_length=128)
    role: LocalUserRole = LocalUserRole.CLAIMANT


class LocalLoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=128)


class LocalUserResponse(BaseModel):
    user_id: str
    full_name: str
    email: str
    role: LocalUserRole

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if "@" not in normalized or normalized.startswith("@") or normalized.endswith("@"):
            raise ValueError("Enter a valid email address.")
        return normalized


class LocalSessionResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in_seconds: int
    user: LocalUserResponse
