# Afterwatch

Automatically replace watched TV episodes with STRM placeholder files to reclaim disk space while preserving Emby library integrity and watch history.

## What it does

1. Monitors Emby for watched episodes
2. Checks if all configured users have watched (for shared libraries)
3. Unmonitors the episode in Sonarr (prevents re-download)
4. Deletes the original media file
5. Creates an empty STRM placeholder file
6. Triggers Sonarr to rename the STRM file
7. Unmonitors the season if all episodes are done

## Installation

### Docker Compose (Recommended)

1. Create a directory for Afterwatch:
```bash
mkdir -p /path/to/afterwatch/data
cd /path/to/afterwatch
```

2. Create a `docker-compose.yml`:
```yaml
services:
  afterwatch:
    image: ghcr.io/richiecoy/afterwatch:latest
    container_name: afterwatch
    restart: unless-stopped
    ports:
      - "8199:8199"
    volumes:
      - ./data:/app/data
      # Mount your media directories
      - /path/to/tvshows:/media/tvshows
      - /path/to/cartoons:/media/cartoons
    environment:
      - TZ=America/New_York
```

3. Start the container:
```bash
docker compose up -d
```

4. Access the web UI at `http://your-server:8199`

## Configuration

### Initial Setup

1. **Connect Emby**: Enter your Emby server URL and API key
2. **Connect Sonarr**: Enter your Sonarr server URL and API key  
3. **Sync Users & Libraries**: Click "Sync from Emby" to pull your users and libraries
4. **Configure Libraries**: 
   - Enable libraries you want to process
   - Select which users must have watched before processing

### Settings

- **Dry Run Mode**: Enabled by default. Simulates processing without making changes. Disable when ready for production.
- **Schedule Time**: Set when daily processing runs (default: 3:00 AM)

## Usage

### Manual Processing

Click "Run Now" on the dashboard to trigger processing immediately.

### Scheduled Processing

Processing runs automatically at the configured schedule time.

### Logs

View processing history in the Logs section, including:
- Episodes processed
- Storage reclaimed
- Success/failure status
- Dry run vs live mode

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `TZ` | `UTC` | Timezone for scheduling |
| `AFTERWATCH_DRY_RUN` | `true` | Start in dry run mode |
| `AFTERWATCH_SCHEDULE_HOUR` | `3` | Hour to run (0-23) |
| `AFTERWATCH_SCHEDULE_MINUTE` | `0` | Minute to run (0-59) |

## Volume Mounts

The container needs access to:
- `/app/data` - Persistent storage for config and database
- Your media directories - Same paths Emby/Sonarr see

**Important**: Mount your media directories at paths that match what Emby and Sonarr expect. The paths in Afterwatch must match the paths in your media servers.

## Development

### Running locally

```bash
# Install dependencies
pip install -r requirements.txt

# Run the app
uvicorn app.main:app --reload --port 8199
```

### Building the Docker image

```bash
docker build -t afterwatch .
```

## License

MIT
