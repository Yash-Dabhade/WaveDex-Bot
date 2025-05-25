from fastapi import APIRouter
from app.api.routes import webhook, health

router = APIRouter()

router.include_router(webhook.router, prefix="/webhook", tags=["webhook"])
router.include_router(health.router, prefix="/health", tags=["health"]) 