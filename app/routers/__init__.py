from app.routers.config import router as config_router
from app.routers.logs import router as logs_router
from app.routers.api import router as api_router

__all__ = ["config_router", "logs_router", "api_router"]
