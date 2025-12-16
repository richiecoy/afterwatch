from fastapi import APIRouter, Depends, BackgroundTasks
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import ProcessLog, ProcessRun
from app.services.processor import process_watched_episodes
from app.config import settings

router = APIRouter()


@router.post("/process")
async def trigger_processing(background_tasks: BackgroundTasks):
    """Manually trigger processing."""
    background_tasks.add_task(process_watched_episodes, "manual")
    return {"status": "started", "dry_run": settings.dry_run}


@router.get("/stats")
async def get_stats(session: AsyncSession = Depends(get_session)):
    """Get dashboard statistics."""
    # Total episodes processed
    total_result = await session.execute(
        select(func.count(ProcessLog.id)).where(
            ProcessLog.success == True,
            ProcessLog.dry_run == False
        )
    )
    total_processed = total_result.scalar() or 0
    
    # Total bytes reclaimed
    bytes_result = await session.execute(
        select(func.sum(ProcessLog.original_size_bytes)).where(
            ProcessLog.success == True,
            ProcessLog.dry_run == False
        )
    )
    total_bytes = bytes_result.scalar() or 0
    
    # Recent runs
    runs_result = await session.execute(
        select(ProcessRun).order_by(ProcessRun.started_at.desc()).limit(5)
    )
    recent_runs = runs_result.scalars().all()
    
    # Last run status
    last_run = recent_runs[0] if recent_runs else None
    
    return {
        "total_episodes_processed": total_processed,
        "total_bytes_reclaimed": total_bytes,
        "total_gb_reclaimed": round(total_bytes / (1024**3), 2),
        "last_run": {
            "timestamp": last_run.started_at.isoformat() if last_run else None,
            "status": last_run.status if last_run else None,
            "episodes": last_run.episodes_processed if last_run else 0,
            "dry_run": last_run.dry_run if last_run else False
        } if last_run else None,
        "dry_run_enabled": settings.dry_run
    }


@router.get("/status")
async def get_status():
    """Get current processing status."""
    return {
        "dry_run": settings.dry_run,
        "schedule_enabled": settings.schedule_enabled,
        "schedule_time": f"{settings.schedule_hour:02d}:{settings.schedule_minute:02d}"
    }
