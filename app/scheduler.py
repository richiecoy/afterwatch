from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from app.config import settings
import logging

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


async def scheduled_process():
    """Run the main processing job."""
    from app.services.processor import process_watched_episodes
    logger.info("Starting scheduled processing run")
    await process_watched_episodes()
    logger.info("Scheduled processing run completed")


async def init_scheduler():
    """Initialize and start the scheduler."""
    if settings.schedule_enabled:
        scheduler.add_job(
            scheduled_process,
            CronTrigger(hour=settings.schedule_hour, minute=settings.schedule_minute),
            id="process_watched",
            replace_existing=True
        )
        scheduler.start()
        logger.info(
            f"Scheduler started - running daily at {settings.schedule_hour:02d}:{settings.schedule_minute:02d}"
        )
    else:
        logger.info("Scheduler disabled")


async def shutdown_scheduler():
    """Shutdown the scheduler gracefully."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler shut down")


def update_schedule(hour: int, minute: int):
    """Update the schedule time."""
    if scheduler.get_job("process_watched"):
        scheduler.reschedule_job(
            "process_watched",
            trigger=CronTrigger(hour=hour, minute=minute)
        )
        logger.info(f"Schedule updated to {hour:02d}:{minute:02d}")
