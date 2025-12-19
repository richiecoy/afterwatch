# Afterwatch Changelog

## v0.6.0 - Dashboard Overhaul
- Renamed "Dry Run" to "Test Mode" throughout the application
- Redesigned dashboard with status cards layout
- Added schedule and delay display on dashboard
- Added "Process Pending" modal with episode selection
- Added test mode toggle button on dashboard
- Fixed stats counting to include all processed episodes
- Added pending and orphan counts to dashboard

## v0.5.0 - Delay Feature
- Added configurable delay days before processing
- Added pending deletion tracking and display
- Settings now persist across container restarts
- Episode log now sorted by date (newest first)

## v0.4.0 - Monitoring & Cleanup
- Added live progress indicator during processing
- Added CSV export for failed episodes
- Added orphan file detection and cleanup
- Added duplicate entry prevention
- Processing now skips already-processed files

## v0.3.0 - Production Fixes
- Fixed timezone display (UTC → local time)
- Dry run logs now clear before live runs
- Added console logging for processing

## v0.2.0 - Access Control
- Added folder-level user access control
- Added excluded users feature
- Added library configuration UI
- Fixed folder name display in logs

## v0.1.0 - Initial Release
- Emby and Sonarr integration
- STRM placeholder file creation
- Episode and season unmonitoring
- Basic web UI with dashboard, config, schedule, and logs
- Scheduled and manual processing runs
- Test mode for simulating actions
