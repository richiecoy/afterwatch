import httpx
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class SonarrClient:
    """Client for interacting with Sonarr API."""
    
    def __init__(self, url: str, api_key: str):
        self.base_url = url.rstrip("/")
        self.api_key = api_key
        self.headers = {
            "X-Api-Key": api_key,
            "Content-Type": "application/json"
        }
    
    async def test_connection(self) -> dict:
        """Test the connection to Sonarr and return system status."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/api/v3/system/status",
                headers=self.headers,
                timeout=10.0
            )
            response.raise_for_status()
            return response.json()
    
    async def get_series(self) -> list[dict]:
        """Get all series from Sonarr."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/api/v3/series",
                headers=self.headers,
                timeout=30.0
            )
            response.raise_for_status()
            return response.json()
    
    async def get_series_by_path(self, path: str) -> Optional[dict]:
        """Find a series by its path."""
        series_list = await self.get_series()
        for series in series_list:
            if path.startswith(series.get("path", "")):
                return series
        return None
    
    async def get_episode_file(self, file_id: int) -> dict:
        """Get episode file info by ID."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/api/v3/episodefile/{file_id}",
                headers=self.headers,
                timeout=10.0
            )
            response.raise_for_status()
            return response.json()
    
    async def get_episode_file_by_path(self, path: str) -> Optional[dict]:
        """Find an episode file by its path."""
        async with httpx.AsyncClient() as client:
            # Get series first
            series = await self.get_series_by_path(path)
            if not series:
                return None
            
            # Get episode files for this series
            response = await client.get(
                f"{self.base_url}/api/v3/episodefile",
                headers=self.headers,
                params={"seriesId": series["id"]},
                timeout=30.0
            )
            response.raise_for_status()
            files = response.json()
            
            for f in files:
                if f.get("path") == path:
                    return f
        return None
    
    async def get_episodes_by_series(self, series_id: int) -> list[dict]:
        """Get all episodes for a series."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/api/v3/episode",
                headers=self.headers,
                params={"seriesId": series_id},
                timeout=30.0
            )
            response.raise_for_status()
            return response.json()
    
    async def refresh_series(self, series_id: int):
        """Trigger a refresh for a series."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/api/v3/command",
                headers=self.headers,
                json={
                    "name": "RefreshSeries",
                    "seriesId": series_id
                },
                timeout=10.0
            )
            response.raise_for_status()
            return response.json()
    
    async def rename_files(self, series_id: int, file_ids: list[int]):
        """Trigger a rename for specific files."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/api/v3/command",
                headers=self.headers,
                json={
                    "name": "RenameFiles",
                    "seriesId": series_id,
                    "files": file_ids
                },
                timeout=10.0
            )
            response.raise_for_status()
            return response.json()
    
    async def set_episode_monitored(self, episode_id: int, monitored: bool):
        """Set the monitored status of an episode."""
        async with httpx.AsyncClient() as client:
            # Get current episode data
            response = await client.get(
                f"{self.base_url}/api/v3/episode/{episode_id}",
                headers=self.headers,
                timeout=10.0
            )
            response.raise_for_status()
            episode = response.json()
            
            # Update monitored status
            episode["monitored"] = monitored
            response = await client.put(
                f"{self.base_url}/api/v3/episode/{episode_id}",
                headers=self.headers,
                json=episode,
                timeout=10.0
            )
            response.raise_for_status()
            return response.json()
    
    async def set_season_monitored(self, series_id: int, season_number: int, monitored: bool):
        """Set the monitored status of a season."""
        async with httpx.AsyncClient() as client:
            # Get series data
            response = await client.get(
                f"{self.base_url}/api/v3/series/{series_id}",
                headers=self.headers,
                timeout=10.0
            )
            response.raise_for_status()
            series = response.json()
            
            # Update the specific season
            for season in series.get("seasons", []):
                if season["seasonNumber"] == season_number:
                    season["monitored"] = monitored
                    break
            
            # Save series
            response = await client.put(
                f"{self.base_url}/api/v3/series/{series_id}",
                headers=self.headers,
                json=series,
                timeout=10.0
            )
            response.raise_for_status()
            return response.json()
    
    async def check_season_complete(
        self, 
        series_id: int, 
        season_number: int,
        exclude_episode_id: Optional[int] = None
    ) -> bool:
        """
        Check if all episodes in a season are unmonitored 
        (or will be after excluding one episode).
        """
        episodes = await self.get_episodes_by_series(series_id)
        season_episodes = [
            ep for ep in episodes 
            if ep.get("seasonNumber") == season_number
        ]
        
        for ep in season_episodes:
            if exclude_episode_id and ep["id"] == exclude_episode_id:
                continue
            if ep.get("monitored", True):
                return False
        
        return True
