"""Password and signed-session helpers for the local pilot account flow.

This module deliberately uses the standard library: no password is logged or
stored directly, and the resulting token contains only identity and role data.
"""
from base64 import urlsafe_b64decode, urlsafe_b64encode
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import os
from typing import Any
from uuid import uuid4

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import settings
from app.infrastructure.postgres import LocalUserRecord, session_scope
from app.schemas.auth import LocalUserResponse, LocalUserRole

_bearer = HTTPBearer(auto_error=False)
_PBKDF2_ITERATIONS = 310_000


class CurrentUser:
    def __init__(self, user_id: str, full_name: str, email: str, role: LocalUserRole):
        self.user_id = user_id
        self.full_name = full_name
        self.email = email
        self.role = role

    def as_response(self) -> LocalUserResponse:
        return LocalUserResponse(user_id=self.user_id, full_name=self.full_name, email=self.email, role=self.role)


def _b64encode(raw: bytes) -> str:
    return urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    return urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _secret() -> bytes:
    configured = settings.local_auth_secret
    if configured:
        return configured.encode("utf-8")
    # Never allow an accidental production start with a predictable key.
    if settings.auth_required:
        raise RuntimeError("LOCAL_AUTH_SECRET must be configured when AUTH_REQUIRED=true")
    return b"contractiq-local-pilot-only-not-for-production"


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${_PBKDF2_ITERATIONS}${_b64encode(salt)}${_b64encode(digest)}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt_value, digest_value = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), _b64decode(salt_value), int(iterations))
        return hmac.compare_digest(candidate, _b64decode(digest_value))
    except (ValueError, TypeError):
        return False


def create_local_user(full_name: str, email: str, password: str, role: LocalUserRole) -> CurrentUser:
    normalized_email = email.strip().lower()
    with session_scope() as session:
        if session.query(LocalUserRecord).filter_by(email=normalized_email).first():
            raise ValueError("An account already exists for this email address.")
        record = LocalUserRecord(
            user_id=str(uuid4()), full_name=full_name.strip(), email=normalized_email,
            password_hash=hash_password(password), role=role.value,
        )
        session.add(record)
        session.flush()
        return CurrentUser(record.user_id, record.full_name, record.email, LocalUserRole(record.role))


def authenticate_local_user(email: str, password: str) -> CurrentUser | None:
    with session_scope() as session:
        record = session.query(LocalUserRecord).filter_by(email=email.strip().lower()).first()
        if not record or not record.is_active or not verify_password(password, record.password_hash):
            return None
        return CurrentUser(record.user_id, record.full_name, record.email, LocalUserRole(record.role))


def create_access_token(user: CurrentUser) -> str:
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": user.user_id, "name": user.full_name, "email": user.email, "role": user.role.value,
        "iat": int(now.timestamp()), "exp": int((now + timedelta(minutes=settings.local_auth_token_minutes)).timestamp()),
    }
    header = {"alg": "HS256", "typ": "JWT"}
    signing_input = f"{_b64encode(json.dumps(header, separators=(',', ':')).encode())}.{_b64encode(json.dumps(payload, separators=(',', ':')).encode())}"
    signature = hmac.new(_secret(), signing_input.encode("ascii"), hashlib.sha256).digest()
    return f"{signing_input}.{_b64encode(signature)}"


def _current_user_from_token(token: str) -> CurrentUser:
    try:
        encoded_header, encoded_payload, encoded_signature = token.split(".")
        signing_input = f"{encoded_header}.{encoded_payload}".encode("ascii")
        expected = hmac.new(_secret(), signing_input, hashlib.sha256).digest()
        if not hmac.compare_digest(expected, _b64decode(encoded_signature)):
            raise ValueError("Invalid signature")
        payload = json.loads(_b64decode(encoded_payload))
        if int(payload["exp"]) <= int(datetime.now(timezone.utc).timestamp()):
            raise ValueError("Session expired")
        return CurrentUser(str(payload["sub"]), str(payload["name"]), str(payload["email"]), LocalUserRole(payload["role"]))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Your local session is invalid or has expired.") from exc


async def get_optional_current_user(
    request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(_bearer)
) -> CurrentUser | None:
    token = credentials.credentials if credentials else None
    if not token:
        token = request.query_params.get("access_token")
    if not token:
        if settings.auth_required:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sign in is required for this request.")
        return None
    return _current_user_from_token(token)


def require_validator(user: CurrentUser | None) -> CurrentUser:
    if not user or user.role != LocalUserRole.VALIDATOR:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="A validator account is required for this action.")
    return user


def can_access_claim(payload: dict, user: CurrentUser | None) -> bool:
    if not user:
        return not settings.auth_required
    if user.role == LocalUserRole.VALIDATOR:
        return True
    return payload.get("owner_user_id") == user.user_id
