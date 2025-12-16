from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime


@dataclass
class ProcessingProgress:
    """Tracks current processing progress."""
    is_running: bool = False
    run_id: Optional[int] = None
    current_series: str = ""
    current_episode: str = ""
    processed_count: int = 0
    failed_count: int = 0
    total_count: int = 0
    bytes_reclaimed: int = 0
    started_at: Optional[datetime] = None
    
    def start(self, run_id: int, total: int):
        self.is_running = True
        self.run_id = run_id
        self.current_series = ""
        self.current_episode = ""
        self.processed_count = 0
        self.failed_count = 0
        self.total_count = total
        self.bytes_reclaimed = 0
        self.started_at = datetime.now()
    
    def update(self, series: str, episode: str, success: bool, size_bytes: int = 0):
        self.current_series = series
        self.current_episode = episode
        if success:
            self.processed_count += 1
            self.bytes_reclaimed += size_bytes
        else:
            self.failed_count += 1
    
    def finish(self):
        self.is_running = False
        self.current_series = ""
        self.current_episode = ""
    
    def to_dict(self) -> dict:
        return {
            "is_running": self.is_running,
            "run_id": self.run_id,
            "current_series": self.current_series,
            "current_episode": self.current_episode,
            "processed_count": self.processed_count,
            "failed_count": self.failed_count,
            "total_count": self.total_count,
            "bytes_reclaimed": self.bytes_reclaimed,
            "started_at": self.started_at.isoformat() if self.started_at else None
        }


# Global progress instance
progress = ProcessingProgress()
