# VN Competitor Event Data System

This repository is the event warehouse and read API for tracking game events across:

- Facebook post data from Socialdata
- Sensor Tower raw app-update / version data
- an LLM-based merge layer that turns source evidence into unified business events

It is designed to support two main use cases:

1. operate a continuously refreshed warehouse on an Ubuntu VM
2. expose a lightweight public API for agents, analysts, and internal tools

## What This System Does

At a high level, the system:

1. maps tracked games and Facebook pages in `config_app_mapping`
2. ingests raw Facebook posts into `raw_fb_posts`
3. ingests replayable Sensor Tower snapshots into `data_ingest/sensortower/raw`
4. loads deterministic Sensor Tower events into warehouse tables
5. builds monthly `unified_events` and `unified_event_sources`
6. serves a read-only event lookup API on top of the warehouse

## Documentation Map

Start here depending on your goal:

- Full system handbook:
  - [System Manual](./docs/system_manual.md)
- API:
  - [Agent-Friendly API v2](./docs/api_v2.md)
  - [Agent Instructions For API v2](./docs/api_v2_agent_instructions.md)
  - [Event Lookup API](./docs/api.md)
  - [Event Lookup API Technical Spec](./docs/api_technical_spec.md)
  - [Event SQL Catalog Contract](./docs/sql_catalog.md)
- Deployment:
  - [Ubuntu VM Deployment](./docs/deploy_ubuntu_vm.md)
  - [Ubuntu VM Deployment (Docker Compose)](./docs/deploy_ubuntu_vm_docker.md)
- Socialdata setup:
  - [Socialdata guide for non-technical users (VI)](./docs/socialdata_huong_dan_nguoi_dung_vi.md)
  - [Socialdata guide for Claude/Codex (VI)](./docs/socialdata_huong_dan_agent_vi.md)
  - [Socialdata connector handoff](./docs/socialdata_connector_handoff.md)
  - [Claude prompt for Socialdata connector reuse](./docs/socialdata_connector_claude_prompt.md)

## Current Recommended Operating Mode

The recommended production setup is:

- Ubuntu VM
- Docker Compose deployment
- SQLite database stored on the VM host
- tracked-game config managed through `examples/config.json`
- Portal SSO-protected admin UI for adding tracked games (with an optional
  password fallback during rollout)
- Socialdata sync via Google service-account authentication
- Sensor Tower sync via API token
- unified-event build via Compass Gateway / OpenAI-compatible API
- weekly scheduled refresh on the VM

When Portal SSO is enabled, the tracked-games admin UI is available at
`/workspaces/tracked-games/events/games`. The temporary
`/api/events/admin/games` path redirects there during rollout.
The Event API joins the private `market-data-gateway` Docker network so it can
consume grants from the Portal without exposing its service token to browsers.

The current VM-side pipeline wrapper:

- syncs Socialdata posts
- syncs Sensor Tower raw snapshots
- loads pending Sensor Tower raw manifests
- rebuilds the previous month and current month
- restarts the API
- verifies API health and DB freshness

## System Architecture

### Core Warehouse Layers

- `config_app_mapping`
  - source-of-truth mapping from tracked Facebook pages to `unified_app_id`
- `raw_fb_posts`
  - landing table for Facebook posts and metrics
- `raw_st_app_update`
  - raw Sensor Tower app-update snapshots
- `raw_st_version`
  - raw Sensor Tower version snapshots
- `st_app_update_events`
  - deterministic Sensor Tower app-update events
- `st_version_events`
  - deterministic Sensor Tower version events
- `post_event_detection`
  - legacy/debug FB detection layer
- `post_event_objects`
  - legacy/debug FB extracted event layer
- `unified_events`
  - final monthly event layer
- `unified_event_sources`
  - lineage links from unified events back to FB posts and Sensor Tower evidence

### Runtime Components

- `api`
  - serves the event API and optional tracked-game admin UI
- `ngrok`
  - exposes the API publicly
- `job`
  - reusable Compose profile for ETL / sync / rebuild commands

## Main API Endpoints

New agents should use `/api/events/v2` because it separates event month buckets from actual Facebook post publish dates and fits the shared `market-data.garena.vn` API namespace:

- [Agent-Friendly API v2](./docs/api_v2.md)
- [Agent Instructions For API v2](./docs/api_v2_agent_instructions.md)

The deployed `GET /openapi.json` schema is the Portal-facing source of truth
for this canonical contract. The Portal imports it server-to-server through an
explicit configured URL, so API documentation changes become visible in
production only after this module is deployed.

Legacy `/api` endpoints remain live for backward compatibility:

- `GET /api/games`
- `GET /api/events`
- `GET /api/events/compact`
- `GET /api/events/summary`
- `GET /api/events/coverage`
- `GET /api/events/search`
- `GET /api/events/{unified_event_id}`
- `GET /api/events/{unified_event_id}/post-stats`
- `GET /api/events/{unified_event_id}/top-posts`
- `GET /api/events/{unified_event_id}/posts`
- `GET /api/posts/{source_post_id}`

Use the detailed API docs for request / response contracts:

- [Agent-Friendly API v2](./docs/api_v2.md)
- [Event Lookup API](./docs/api.md)
- [Event Lookup API Technical Spec](./docs/api_technical_spec.md)

## Quick Start

### Local Python Flow

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
python -m vn_event_dw.cli init-db --db data/warehouse.db
python -m vn_event_dw.cli run --db data/warehouse.db --config examples/config.json --input-dir examples
python -m vn_event_dw.cli sync-sensortower-raw --config examples/config.json --lookback-days 3
python -m vn_event_dw.cli load-sensortower-raw --db data/warehouse.db
python -m vn_event_dw.cli build-unified-events-llm --db data/warehouse.db
python -m vn_event_dw.cli summary --db data/warehouse.db
```

### Local API

```bash
python -m vn_event_dw.cli serve-api --db data/warehouse.db
```

To require a simple shared key for `/api/...`, `/api/v2/...`, and `/api/events/v2/...`, set:

```bash
VN_EVENT_DW_API_KEY=replace_with_shared_api_key
```

For multiple people, prefer managed keys. The raw key is printed once; only its hash is stored:

```bash
python -m vn_event_dw.cli api-key-generate --keys-file local_secrets/api_keys.json --name teammate-name
VN_EVENT_DW_API_KEYS_FILE=local_secrets/api_keys.json python -m vn_event_dw.cli serve-api --db data/warehouse.db
```

Useful management commands:

```bash
python -m vn_event_dw.cli api-key-list --keys-file local_secrets/api_keys.json
python -m vn_event_dw.cli api-key-revoke --keys-file local_secrets/api_keys.json --name teammate-name
```

Callers can then use either:

```bash
curl -H "X-API-Key: replace_with_api_key" "http://127.0.0.1:8765/api/events/v2/games"
```

or:

```bash
curl -H "Authorization: Bearer replace_with_api_key" "http://127.0.0.1:8765/api/events/v2/games"
```

### VM Docker Flow

See:

- [Ubuntu VM Deployment (Docker Compose)](./docs/deploy_ubuntu_vm_docker.md)

## Admin UI For Adding Tracked Games

The admin UI lets an internal operator add a tracked game without manually editing JSON or running ETL commands.

Enable it on the VM by setting these values in `deploy/docker/pipeline.env`:

```bash
ADMIN_UI_ENABLED=1
ADMIN_PASSWORD=replace_with_shared_internal_password
ADMIN_CONFIG_PATH=/app/examples/config.json
ADMIN_REPO_ROOT=/repo
ADMIN_REPO_CONFIG_PATH=examples/config.json
ADMIN_GIT_BRANCH=main
ADMIN_GIT_ENABLED=1
ADMIN_GIT_USER_NAME=VN Event DW Admin
ADMIN_GIT_USER_EMAIL=vn-event-dw-admin@localhost
ADMIN_GITHUB_TOKEN=replace_with_fine_scoped_github_token
ADMIN_BACKFILL_LOOKBACK_DAYS=30
ADMIN_API_VERIFY_URL=http://127.0.0.1:8765/api/games
```

`ADMIN_GITHUB_TOKEN` is used only inside the VM/container for non-interactive `git push`.
Keep the real token in `deploy/docker/pipeline.env` on the VM only; never commit it.

The Docker deployment also needs the repo mounted through `HOST_REPO_DIR` in `deploy/docker/vm.env`:

```bash
HOST_REPO_DIR=/opt/vn_event_dw/vn_competitor_event_data_system
```

After changing env or Docker mounts, rebuild and recreate the API container:

```bash
cd /opt/vn_event_dw/vn_competitor_event_data_system
sudo docker compose --env-file deploy/docker/vm.env -f deploy/docker/docker-compose.yml up -d --build --force-recreate api
```

Then open:

```text
https://market-data.garena.vn/workspaces/tracked-games/events/games
```

What the UI does after a game is applied:

- validates duplicate IDs and required Android/iOS SensorTower targets
- updates `examples/config.json`
- validates the JSON file
- commits and pushes the config change to GitHub
- syncs Socialdata posts for the new `unified_app_id`
- verifies the newest Socialdata posts for that game landed in `raw_fb_posts`
- syncs and loads SensorTower data for the new `unified_app_id`
- rebuilds unified events for previous month and current month
- verifies the game appears through `/api/games`

Operational notes:

- The VM must have working GitHub push credentials for `git push origin main`.
- If `VN_EVENT_DW_API_KEY` or `VN_EVENT_DW_API_KEYS_FILE` is set, public read API callers must send a valid key in `X-API-Key` or `Authorization: Bearer`.
- The admin UI always uses `ADMIN_PASSWORD`; do not reuse the API key as the admin password.
- If the admin job fails, open the job page shown by the UI and read the command log from top to bottom.
- If the job fails after GitHub push, the game remains tracked; fix the operational issue and rerun targeted sync/build.

## Main CLI Workflows

### 1. Socialdata Post Sync

Recommended weekly overlap load:

```bash
python -m vn_event_dw.cli sync-socialdata-posts --db data/warehouse.db --config examples/config.json --lookback-days 10
```

First backfill from a date:

```bash
python -m vn_event_dw.cli sync-socialdata-posts --db data/warehouse.db --config examples/config.json --since 2026-01-01
```

What it does:

- resolves the Socialdata app by slug
- matches Socialdata channels to `config_app_mapping.fb_page_id`
- fetches post lists and post metrics
- upserts posts into `raw_fb_posts`
- only stops pagination when a whole fetched page is older than the cutoff, which avoids missing recent posts on mixed-order pages

Diagnose one game by comparing Socialdata source posts against DB rows:

```bash
python -m vn_event_dw.cli diagnose-socialdata-game \
  --db data/warehouse.db \
  --config examples/config.json \
  --unified-app-id 5da680bb42fa0c4364eb64c8 \
  --lookback-days 30
```

Use `--fail-on-missing` in automation to fail when Socialdata has recent posts that are not present in `raw_fb_posts`.

### 2. Sensor Tower Raw Sync

Incremental overlap load:

```bash
python -m vn_event_dw.cli sync-sensortower-raw --config examples/config.json --lookback-days 3
```

Backfill from a date:

```bash
python -m vn_event_dw.cli sync-sensortower-raw --config examples/config.json --since 2025-01-01
```

Load raw manifests into the warehouse:

```bash
python -m vn_event_dw.cli load-sensortower-raw --db data/warehouse.db
```

### 3. Unified Event Build

Build the final cross-source monthly event layer:

```bash
python -m vn_event_dw.cli build-unified-events-llm --db data/warehouse.db
```

Or a specific month:

```bash
python -m vn_event_dw.cli build-unified-events-llm --db data/warehouse.db --month 2026-07
```

### 4. VM Scheduled Pipeline

On the VM, the wrapper script is:

```bash
./deploy/docker/run_vm_pipeline.sh
```

Its default behavior is:

- Socialdata overlap sync
- Sensor Tower overlap sync
- Sensor Tower raw load
- rebuild previous month + current month
- restart API
- verify API health
- verify DB freshness

## Required Runtime Secrets

### Socialdata

- `SOCIALDATA_BASE_URL`
- `SOCIALDATA_TIMEOUT_SECONDS`
- `SOCIALDATA_APP_SLUG`
- `SOCIALDATA_GOOGLE_SERVICE_ACCOUNT_FILE`
- `SOCIALDATA_GOOGLE_SCOPES`
- optional fallback:
  - `SOCIALDATA_USESSION`
  - `SOCIALDATA_GOOGLE_ACCESS_TOKEN`

Important:

- service-account token minting should use:
  - `https://www.googleapis.com/auth/userinfo.email`
- this is required so Socialdata can map the Google token to the granted service-account email

### Sensor Tower

- `SENSOR_TOWER_AUTH_TOKEN`
- optional:
  - `SENSOR_TOWER_BASE_URL`

### Compass / OpenAI-Compatible LLM

- `OPENAI_API_KEY`
- `OPENAI_BASE_URL`
- `OPENAI_PROVIDER`
- optional:
  - `OPENAI_TIMEOUT_SECONDS`
  - `OPENAI_MAX_RETRIES`

Model choices are version-controlled in
[`deploy/docker/pipeline.models.env`](./deploy/docker/pipeline.models.env), not
in the VM-only secret file. The current policy uses `gpt-5.6-luna` for
high-volume detection and legacy Facebook merging, and `gpt-5.6-terra` for
unified-event merge and harvest work.

## Recommended Schedules

### VM Weekly Refresh

The repo includes a cron example:

- [deploy/docker/vn-event-dw-pipeline.cron.example](./deploy/docker/vn-event-dw-pipeline.cron.example)

Current schedule pattern:

- every Monday
- `02:00 UTC`
- intended to rebuild:
  - previous month
  - current month

### Default Overlap Windows

- `SOCIALDATA_SYNC_LOOKBACK_DAYS=10`
- `SENSORTOWER_SYNC_LOOKBACK_DAYS=3`

These are overlap windows, not full-history rebuilds.

## Common Operations

### Check latest raw FB freshness

```bash
sudo docker compose --env-file deploy/docker/vm.env -f deploy/docker/docker-compose.yml --profile ops run --rm --no-deps job \
python - <<'PY'
import sqlite3
conn = sqlite3.connect("/app/data/warehouse.db")
row = conn.execute("""
SELECT
  MAX(publish_time) AS latest_publish_time,
  MAX(ingested_at) AS latest_ingested_at,
  COUNT(*) AS raw_fb_post_rows
FROM raw_fb_posts
""").fetchone()
print("latest_publish_time:", row[0])
print("latest_ingested_at:", row[1])
print("raw_fb_post_rows:", row[2])
PY
```

More verification commands are in:

- [System Manual](./docs/system_manual.md)

### Pull latest code on VM

```bash
cd /opt/vn_event_dw/vn_competitor_event_data_system
git pull origin main
docker compose --env-file deploy/docker/vm.env -f deploy/docker/docker-compose.yml up -d --build
```

### Overwrite the VM DB with a local DB

Copy the file to the VM host, replace `/opt/vn_event_dw/data/warehouse.db`, then restart the API. Full steps are in:

- [Ubuntu VM Deployment (Docker Compose)](./docs/deploy_ubuntu_vm_docker.md)

### Manual catch-up after a missed scheduled run

Typical pattern:

1. temporarily widen Socialdata and Sensor Tower lookback windows
2. run `./deploy/docker/run_vm_pipeline.sh`
3. verify latest raw FB publish time
4. verify rebuilt months in `unified_events`

The exact operational commands are documented in the system manual.

## WSL Recommendation

This repo is happiest in WSL Ubuntu rather than a Windows shell.

Recommended layout:

- keep the repo on the Linux filesystem if possible
- use a local virtualenv
- avoid running the main dev workflow from `/mnt/c/...` when you can

Basic setup:

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip
cd ~/code/vn_competitor_event_data_system
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Project Layout

- `src/vn_event_dw/`
  - ETL, API, and warehouse logic
- `examples/`
  - sample config and sample inputs
- `examples/fb_posts/`
  - optional CSV landing folder for manual FB imports
- `data_ingest/sensortower/raw/`
  - replayable raw Sensor Tower snapshots and manifests
- `deploy/docker/`
  - Docker deployment assets, runtime env examples, pipeline wrapper, cron and systemd examples
- `docs/`
  - API docs, deployment guides, Socialdata setup guides, and system manual
- `tests/`
  - unit and integration tests

## If You Are Handing This Repo To Someone Else

Give them these docs first:

- [System Manual](./docs/system_manual.md)
- [Ubuntu VM Deployment (Docker Compose)](./docs/deploy_ubuntu_vm_docker.md)
- [Event Lookup API](./docs/api.md)

If they need Socialdata setup help:

- [Socialdata guide for non-technical users (VI)](./docs/socialdata_huong_dan_nguoi_dung_vi.md)
- [Socialdata guide for Claude/Codex (VI)](./docs/socialdata_huong_dan_agent_vi.md)

## Status Notes

This system currently uses:

- SQLite as the production warehouse database
- Docker Compose on the Ubuntu VM
- ngrok for public API exposure
- cron or systemd-timer style scheduling on the VM

If needed later, SQLite can be migrated to PostgreSQL, but that is not the current production path.
