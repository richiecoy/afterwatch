import httpx
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class EmbyClient:
    """Client for interacting with Emby API."""
    
    def __init__(self, url: str, api_key: str):
        self.base_url = url.rstrip("/")
        self.api_key = api_key
        self.headers = {
            "X-Emby-Token": api_key,
            "Content-Type": "application/json"
        }
    
    async def test_connection(self) -> dict:
        """Test the connection to Emby and return server info."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/System/Info",
                headers=self.headers,
                timeout=10.0
            )
            response.raise_for_status()
            return response.json()
    
    async def get_users(self) -> list[dict]:
        """Get all users from Emby."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/Users",
                headers=self.headers,
                timeout=10.0
            )
            response.raise_for_status()
            return response.json()
    
    async def get_libraries(self) -> list[dict]:
        """Get all media libraries from Emby."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/Library/VirtualFolders",
                headers=self.headers,
                timeout=10.0
            )
            response.raise_for_status()
            return response.json()
    
    async def get_user_library_access(self, user_id: str) -> list[str]:
        """Get which libraries a user has access to."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/Users/{user_id}",
                headers=self.headers,
                timeout=10.0
            )
            response.raise_for_status()
            user_data = response.json()
            
            policy = user_data.get("Policy", {})
            if policy.get("EnableAllFolders", True):
                return []
            return policy.get("EnabledFolders", [])
    
    async def get_all_user_access_details(self) -> dict[str, dict]:
        """
        Get full library access details for all users.
        Returns dict of user_id -> {
            'all_access': bool,
            'enabled_folders': set of library GUIDs,
            'excluded_subfolders': set of subfolder IDs (integers)
        }
        """
        users = await self.get_users()
        access_map = {}
        
        async with httpx.AsyncClient() as client:
            for user in users:
                user_id = user["Id"]
                response = await client.get(
                    f"{self.base_url}/Users/{user_id}",
                    headers=self.headers,
                    timeout=10.0
                )
                response.raise_for_status()
                user_data = response.json()
                
                policy = user_data.get("Policy", {})
                
                # Parse excluded subfolders - format is "libraryGuid_subfolderId"
                excluded = set()
                for item in policy.get("ExcludedSubFolders", []):
                    if "_" in item:
                        parts = item.rsplit("_", 1)
                        if len(parts) == 2:
                            try:
                                excluded.add(int(parts[1]))
                            except ValueError:
                                pass
                
                access_map[user_id] = {
                    'all_access': policy.get("EnableAllFolders", True),
                    'enabled_folders': set(policy.get("EnabledFolders", [])),
                    'excluded_subfolders': excluded
                }
        
        return access_map
    
    async def get_watched_episodes(self, user_id: str, library_id: str) -> list[dict]:
        """Get all watched episodes for a user in a specific library."""
        async with httpx.AsyncClient() as client:
            params = {
                "UserId": user_id,
                "ParentId": library_id,
                "IncludeItemTypes": "Episode",
                "Recursive": "true",
                "IsPlayed": "true",
                "Fields": "Path,MediaSources,SeriesName,SeasonName"
            }
            response = await client.get(
                f"{self.base_url}/Items",
                headers=self.headers,
                params=params,
                timeout=30.0
            )
            response.raise_for_status()
            data = response.json()
            return data.get("Items", [])
    
    async def check_episode_watched(
        self, 
        episode_id: str, 
        user_ids: list[str]
    ) -> dict[str, bool]:
        """Check if an episode is watched by specific users."""
        results = {}
        async with httpx.AsyncClient() as client:
            for user_id in user_ids:
                response = await client.get(
                    f"{self.base_url}/Users/{user_id}/Items/{episode_id}",
                    headers=self.headers,
                    timeout=10.0
                )
                if response.status_code == 200:
                    data = response.json()
                    user_data = data.get("UserData", {})
                    results[user_id] = user_data.get("Played", False)
                else:
                    results[user_id] = False
        return results
    
    async def refresh_library(self, library_id: Optional[str] = None):
        """Trigger a library refresh."""
        async with httpx.AsyncClient() as client:
            if library_id:
                url = f"{self.base_url}/Items/{library_id}/Refresh"
            else:
                url = f"{self.base_url}/Library/Refresh"
            
            response = await client.post(
                url,
                headers=self.headers,
                timeout=10.0
            )
            response.raise_for_status()
