from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pathlib import Path

from app.config import settings
from app.database import init_db
from app.scheduler import init_scheduler, shutdown_scheduler
from app.routers import config_router, logs_router, api_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle startup and shutdown events."""
    # Startup
    await init_db()
    await init_scheduler()
    yield
    # Shutdown
    await shutdown_scheduler()


app = FastAPI(
    title="Afterwatch",
    description="Automatically replace watched episodes with STRM placeholders",
    version="0.1.0",
    lifespan=lifespan
)

# Mount static files
static_path = Path(__file__).parent.parent / "static"
app.mount("/static", StaticFiles(directory=static_path), name="static")

# Templates
templates_path = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=templates_path)

# Include routers
app.include_router(config_router, prefix="/config", tags=["Configuration"])
app.include_router(logs_router, prefix="/logs", tags=["Logs"])
app.include_router(api_router, prefix="/api", tags=["API"])


@app.get("/")
async def index(request: Request):
    """Main dashboard page."""
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "version": app.version
        }
    )


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "version": app.version}
