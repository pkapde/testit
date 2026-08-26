from fastapi import APIRouter
from app.api.v1.routes.claims import router as claims_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(claims_router)
