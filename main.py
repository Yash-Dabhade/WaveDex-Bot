from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
import uvicorn

from app.core.config import settings
from app.core.logging import setup_logging
from app.api.routes import router as api_router
from app.core.telegram import bot_instance

# Initialize FastAPI app
app = FastAPI(
    title="Crypto News Bot API",
    description="API for Crypto News Telegram Bot",
    version="1.0.0",
)

# Setup CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Setup logging
setup_logging()

# Include API routes
app.include_router(api_router, prefix="/api")

@app.on_event("startup")
async def startup_event():
    logger.info("Starting up Crypto News Bot...")
    await bot_instance.initialize()

@app.on_event("shutdown")
async def shutdown_event():
    logger.info("Shutting down Crypto News Bot...")
    await bot_instance.shutdown()

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

if __name__ == "__main__":
    uvicorn.run(
        "main:app",  # Updated to point to root main.py
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.APP_DEBUG
    ) 