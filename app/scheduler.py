from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from datetime import datetime
from typing import Optional
import logging

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()
_next_run_time: Optional[datetime] = None


def get_next_run_time() -> Optional[datetime]:
    """Get the next scheduled run time."""
    jobs = scheduler.get_jobs()
    if jobs:
        return jobs[0].next_run_time
    return None


async def scheduled_process():
    """Run the processing job."""
    from app.services.processor import process_watched_episodes
    logger.info("Starting scheduled processing run")
    await process_watched_episodes(trigger="scheduled")


async def update_schedule_from_db():
    """Update scheduler based on database settings."""
    from app.database import async_session
    from app.models import Schedule
    from sqlalchemy import select
    
    # Remove existing jobs
    scheduler.remove_all_jobs()
    
    async with async_session() as session:
        result = await session.execute(select(Schedule))
        schedule = result.scalar_one_or_none()
        
        if not schedule or not schedule.enabled:
            logger.info("Scheduling disabled")
            return
        
        # Parse enabled days
        days_list = [int(d) for d in schedule.days_enabled.split(",") if d]
        if not days_list:
            days_list = [0, 1, 2, 3, 4, 5, 6]
        
        # Convert to cron day_of_week format (mon-sun)
        day_names = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
        cron_days = ",".join([day_names[d] for d in days_list])
        
        if schedule.schedule_type == "daily":
            # Run once per day at specified time
            trigger = CronTrigger(
                hour=schedule.daily_hour,
                minute=schedule.daily_minute,
                day_of_week=cron_days
            )
            scheduler.add_job(scheduled_process, trigger, id="afterwatch_daily")
            logger.info(f"Scheduled daily at {schedule.daily_hour:02d}:{schedule.daily_minute:02d} on {cron_days}")
            
        elif schedule.schedule_type == "hourly":
            # Run every hour (optionally filtered by odd/even)
            if schedule.hour_filter == "odd":
                hours = "1,3,5,7,9,11,13,15,17,19,21,23"
            elif schedule.hour_filter == "even":
                hours = "0,2,4,6,8,10,12,14,16,18,20,22"
            else:
                hours = "*"
            
            trigger = CronTrigger(
                hour=hours,
                minute=schedule.daily_minute,
                day_of_week=cron_days
            )
            scheduler.add_job(scheduled_process, trigger, id="afterwatch_hourly")
            logger.info(f"Scheduled hourly ({schedule.hour_filter}) at minute {schedule.daily_minute:02d} on {cron_days}")
            
        elif schedule.schedule_type == "interval":
            # Run every N hours
            trigger = IntervalTrigger(hours=schedule.interval_hours)
            scheduler.add_job(scheduled_process, trigger, id="afterwatch_interval")
            logger.info(f"Scheduled every {schedule.interval_hours} hour(s)")


def start_scheduler():
    """Start the scheduler."""
    if not scheduler.running:
        scheduler.start()
        logger.info("Scheduler started")


def stop_scheduler():
    """Stop the scheduler."""
    if scheduler.running:
        scheduler.shutdown()
        logger.info("Scheduler stopped")


# Legacy function for compatibility
def update_schedule(hour: int, minute: int):
    """Legacy function - use update_schedule_from_db instead."""
    pass
