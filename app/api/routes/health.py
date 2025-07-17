from fastapi import APIRouter, Response
from loguru import logger
from typing import Dict

router = APIRouter()

@router.get("")
async def health_check() -> Dict:
    """Check system health status"""
    status = {
        "status": "healthy",
        "services": {
            "database": "unhealthy",
        }
    }

    try:
        # Check database connection
        await prisma_service.connect()
        await prisma_service.disconnect()
        status["services"]["database"] = "healthy"
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
    # Set overall status
    if any(v == "unhealthy" for v in status["services"].values()):
        status["status"] = "unhealthy"
        return Response(status_code=503, content=status)

    return status 