from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession
import csv
import io

from app.database import get_session
from app.models import ProcessRun, ProcessLog
from app.config import settings
from app.progress import progress

router = APIRouter()


def format_size(bytes_val: int) -> str:
    """Format bytes to human readable size."""
    if bytes_val >= 1024 ** 4:
        return f"{bytes_val / (1024 ** 4):.2f} TB"
    elif bytes_val >= 1024 ** 3:
        return f"{bytes_val / (1024 ** 3):.2f} GB"
    elif bytes_val >= 1024 ** 2:
        return f"{bytes_val / (1024 ** 2):.2f} MB"
    elif bytes_val >= 1024:
        return f"{bytes_val / 1024:.2f} KB"
    else:
        return f"{bytes_val} B"


@router.get("/stats")
async def get_stats(session: AsyncSession = Depends(get_session)):
    """Get dashboard statistics."""
    # Get latest run
    result = await session.execute(
        select(ProcessRun).order_by(desc(ProcessRun.started_at)).limit(1)
    )
    last_run = result.scalar_one_or_none()
    
    # Get totals from all live runs
    result = await session.execute(
        select(ProcessRun).where(ProcessRun.dry_run == False)
    )
    runs = result.scalars().all()
    
    total_episodes = sum(r.episodes_processed for r in runs)
    total_bytes = sum(r.bytes_reclaimed for r in runs)
    
    return {
        "episodes_processed": total_episodes,
        "space_reclaimed": format_size(total_bytes),
        "last_run_status": last_run.status if last_run else "never",
        "dry_run": settings.dry_run
    }

@router.get("/last-run")
async def get_last_run(session: AsyncSession = Depends(get_session)):
    """Get the last processing run."""
    result = await session.execute(
        select(ProcessRun).order_by(desc(ProcessRun.started_at)).limit(1)
    )
    run = result.scalar_one_or_none()
    
    if not run:
        return JSONResponse(None, status_code=204)
    
    return {
        "started_at": run.started_at.strftime('%m/%d/%Y, %I:%M:%S %p'),
        "status": run.status,
        "episodes_processed": run.episodes_processed,
        "dry_run": run.dry_run
    }


@router.post("/process")
async def trigger_process():
    """Trigger a processing run."""
    from app.services.processor import process_watched_episodes
    import asyncio
    
    # Run in background
    asyncio.create_task(process_watched_episodes(trigger="manual"))
    
    return {"status": "started"}


@router.get("/progress")
async def get_progress():
    """Get current processing progress."""
    return JSONResponse(progress.to_dict())


@router.get("/export-failures")
async def export_failures(session: AsyncSession = Depends(get_session)):
    """Export failed processing logs as CSV."""
    result = await session.execute(
        select(ProcessLog).where(
            ProcessLog.success == False,
            ProcessLog.dry_run == False
        ).order_by(
            ProcessLog.series_name,
            ProcessLog.season_number,
            ProcessLog.episode_number
        )
    )
    logs = result.scalars().all()
    
    # Create CSV in memory
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Header
    writer.writerow([
        "Series", "Season", "Episode", "Title", "Folder", "Path", "Error"
    ])
    
    # Data
    for log in logs:
        writer.writerow([
            log.series_name,
            log.season_number,
            log.episode_number,
            log.episode_title,
            log.folder_name,
            log.original_path,
            log.error_message
        ])
    
    output.seek(0)
    
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=afterwatch_failures.csv"}
    )
@router.get("/orphans")
async def get_orphans(session: AsyncSession = Depends(get_session)):
    """Get list of orphaned files (in Emby but not in Sonarr)."""
    result = await session.execute(
        select(ProcessLog).where(
            ProcessLog.success == False,
            ProcessLog.dry_run == False,
            ProcessLog.error_message.like("%Could not find file in Sonarr%")
        ).order_by(
            ProcessLog.series_name,
            ProcessLog.season_number,
            ProcessLog.episode_number
        )
    )
    logs = result.scalars().all()
    
    orphans = []
    total_size = 0
    
    for log in logs:
        # Check if file still exists
        import os
        exists = os.path.exists(log.original_path)
        size = 0
        if exists:
            try:
                size = os.path.getsize(log.original_path)
                total_size += size
            except OSError:
                pass
        
        orphans.append({
            "id": log.id,
            "series_name": log.series_name,
            "season_number": log.season_number,
            "episode_number": log.episode_number,
            "episode_title": log.episode_title,
            "folder_name": log.folder_name,
            "path": log.original_path,
            "size": size,
            "size_formatted": format_size(size),
            "exists": exists
        })
    
    return {
        "orphans": orphans,
        "total_count": len(orphans),
        "total_size": total_size,
        "total_size_formatted": format_size(total_size)
    }

@router.post("/delete-orphans")
async def delete_orphans(session: AsyncSession = Depends(get_session)):
    """Delete all orphaned files."""
    import os
    
    result = await session.execute(
        select(ProcessLog).where(
            ProcessLog.success == False,
            ProcessLog.dry_run == False,
            ProcessLog.error_message.like("%Could not find file in Sonarr%")
        )
    )
    logs = result.scalars().all()
    
    deleted_count = 0
    deleted_bytes = 0
    cleared_count = 0
    errors = []
    
    for log in logs:
        if os.path.exists(log.original_path):
            try:
                size = os.path.getsize(log.original_path)
                os.remove(log.original_path)
                deleted_count += 1
                deleted_bytes += size
            except Exception as e:
                errors.append(f"{log.original_path}: {str(e)}")
                continue
        else:
            # File already missing
            cleared_count += 1
        
        # Mark as handled either way
        log.error_message = "Orphaned file deleted"
        log.success = True
    
    await session.commit()
    
    return {
        "deleted_count": deleted_count,
        "cleared_count": cleared_count,
        "deleted_bytes": deleted_bytes,
        "deleted_size_formatted": format_size(deleted_bytes),
        "errors": errors
    }

@router.get("/pending")
async def get_pending(session: AsyncSession = Depends(get_session)):
    """Get list of episodes waiting for delay period to pass."""
    from app.models import WatchedEpisode
    from app.config import settings
    from datetime import datetime, timedelta
    
    result = await session.execute(
        select(WatchedEpisode).order_by(WatchedEpisode.first_seen_at)
    )
    watched = result.scalars().all()
    
    pending = []
    for w in watched:
        days_elapsed = (datetime.now() - w.first_seen_at).days
        days_remaining = max(0, settings.delay_days - days_elapsed)
        process_date = w.first_seen_at + timedelta(days=settings.delay_days)
        
        pending.append({
            "id": w.id,
            "series_name": w.series_name,
            "season_number": w.season_number,
            "episode_number": w.episode_number,
            "file_path": w.file_path,
            "first_seen_at": w.first_seen_at.strftime('%Y-%m-%d %H:%M'),
            "days_remaining": days_remaining,
            "process_date": process_date.strftime('%Y-%m-%d')
        })
    
    return {
        "pending": pending,
        "total_count": len(pending),
        "delay_days": settings.delay_days
    }
