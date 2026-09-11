"""Local pilot authentication endpoints. Entra ID can replace these later."""
from fastapi import APIRouter, Depends, HTTPException, status

from app.core.config import settings
from app.schemas.auth import LocalLoginRequest, LocalRegistrationRequest, LocalSessionResponse, LocalUserRole
from app.services.local_auth import authenticate_local_user, create_access_token, create_local_user, get_optional_current_user

router = APIRouter(prefix="/auth", tags=["local authentication"])


@router.get("/config")
async def get_local_auth_config() -> dict[str, bool]:
    """Expose only UI-safe pilot mode flags; never expose a signing secret."""
    return {
        "auth_required": settings.auth_required,
        "validator_registration_allowed": settings.local_auth_allow_validator_registration,
    }


@router.post("/register", response_model=LocalSessionResponse, status_code=status.HTTP_201_CREATED)
async def register_local_user(request: LocalRegistrationRequest) -> LocalSessionResponse:
    if request.role == LocalUserRole.VALIDATOR and not settings.local_auth_allow_validator_registration:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Validator accounts must be provisioned by an administrator for this pilot.")
    try:
        user = create_local_user(request.full_name, str(request.email), request.password, request.role)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="PostgreSQL is required before local accounts can be created.") from exc
    return LocalSessionResponse(access_token=create_access_token(user), expires_in_seconds=settings.local_auth_token_minutes * 60, user=user.as_response())


@router.post("/login", response_model=LocalSessionResponse)
async def login_local_user(request: LocalLoginRequest) -> LocalSessionResponse:
    try:
        user = authenticate_local_user(str(request.email), request.password)
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="PostgreSQL is required for local account sign-in.") from exc
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Email or password is incorrect.")
    return LocalSessionResponse(access_token=create_access_token(user), expires_in_seconds=settings.local_auth_token_minutes * 60, user=user.as_response())


@router.get("/me")
async def get_current_local_user(user=Depends(get_optional_current_user)):
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No local session is active.")
    return user.as_response()
