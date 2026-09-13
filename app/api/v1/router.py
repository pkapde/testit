from fastapi import APIRouter
from app.api.v1.routes.claims import rag_router, router as claims_router
from app.api.v1.routes.policy import router as policy_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(rag_router)
api_router.include_router(claims_router)
api_router.include_router(policy_router)
