# Changelog

## Overview and hardening release

Front end
- New overview page at `/` with a live 60-ward tile map, forecast chart, allocation and SMS previews, accuracy bars and an in-page offline stress test. Command center moved to `/app`.
- Command center: KPI strip, selected-ward forecast panel (with 10th-90th percentile range), color-by switch, CSV export, error toasts, loading bar, saved controls, reset button, keyboard skip link, phone-width fixes.
- Fixed stale responses overwriting newer ones when sliders move quickly.

Backend and repo
- Added `requirements.txt`, `requirements-dev.txt` (the README referenced a missing file).
- Added pytest suite (allocation limits, bed conservation, determinism, HTML escaping, fallback engine parity, API checks).
- Engine creation is now thread-safe; added `/api/health`, gzip, Content-Security-Policy and related headers, `no-store` on API responses.
- Stress test scans only text assets for external URLs.
