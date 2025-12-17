from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pathlib import Path

from app.database import init_db
from app.routers import config_router, logs_router, api_router, schedule_router
from app.scheduler import start_scheduler, stop_scheduler, update_schedule_from_db
from app.config import load_settings_from_db, settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await init_db()
    await load_settings_from_db()
    start_scheduler()
    await update_schedule_from_db()
    yield
    # Shutdown
    stop_scheduler()


app = FastAPI(title="Afterwatch", lifespan=lifespan)

# Mount static files
app.mount("/static", StaticFiles(directory=Path(__file__).parent.parent / "static"), name="static")

# Templates
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")

# Include routers
app.include_router(config_router, prefix="/config", tags=["config"])
app.include_router(logs_router, prefix="/logs", tags=["logs"])
app.include_router(api_router, prefix="/api", tags=["api"])
app.include_router(schedule_router, prefix="/schedule", tags=["schedule"])


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """Home page with dashboard."""
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "dry_run": settings.dry_run
        }
    )
