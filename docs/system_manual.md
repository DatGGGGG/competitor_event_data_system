# VN Competitor Event Data System Manual

## Purpose

This document is the operator and handoff manual for the VN Competitor Event Data System.

Use it when you need to understand:

- what the system is
- how data flows through it
- how it is deployed
- how to run loads and rebuilds
- how to verify freshness
- how to troubleshoot common failures

## 1. System Overview

The system turns raw external signals into a unified monthly event layer for tracked games.

It combines:

- Socialdata Facebook posts and metrics
- Sensor Tower app-update and version signals
- LLM-based cross-source event merging

It also exposes a public read-only API that agents and analysts can query instead of touching the database directly.

## 2. Main Business Goal

The warehouse exists to answer questions like:

- what events happened for a game in a month
- what are the hottest events by social score
- what Facebook posts support a given event
- what coverage exists for a game and time window
- whether an event name from a user roughly matches an event in the warehouse

## 3. High-Level Architecture

```text
Socialdata API -------+
                      +--> raw_fb_posts ---------------+
Sensor Tower API -----+                                |
                                                       +--> unified_events
Sensor Tower raw snapshots -> raw_st_* -> st_*_events -+    unified_event_sources

unified_events + unified_event_sources -> FastAPI read API -> ngrok public URL
```

## 4. Core Data Model

### `config_app_mapping`

Tracks the authoritative relationship between:

- `unified_app_id`
- `fb_page_id`
- `app_name`

This table is critical because Socialdata sync relies on `fb_page_id` matching.

### `raw_fb_posts`

Landing table for Facebook posts.

Typical important fields:

- `source_post_id`
- `unified_app_id`
- `fb_page_id`
- `channel_id`
- `channel_name`
- `page_name`
- `publish_time`
- `ingested_at`
- `reaction`
- `comment`
- `share`
- `view`
- `engagement`

### `raw_st_app_update` and `raw_st_version`

Raw Sensor Tower landing tables loaded from replayable manifests.

### `st_app_update_events` and `st_version_events`

Deterministic event layers derived from Sensor Tower raw snapshots.

### `unified_events`

Final business-level event table.

Important fields typically include:

- `unified_event_id`
- `unified_app_id`
- `month_bucket`
- `canonical_event_name`
- `canonical_event_description`
- `event_category`
- `social_score`

### `unified_event_sources`

Lineage table connecting each unified event back to source evidence:

- `fb_post`
- `st_app_update_event`
- `st_version_event`

## 5. Runtime Components

### API container

Serves the event lookup API.

### ngrok container

Publishes the API to a public HTTPS URL.

### job container

Reusable container profile for:

- Socialdata sync
- Sensor Tower sync
- Sensor Tower raw load
- unified-event rebuilds
- DB inspection commands

## 6. Environment and Secrets

### VM env file

Path:

- `deploy/docker/vm.env`

Typical responsibilities:

- host mount paths
- ngrok token and domain
- port settings

### Pipeline env file

Path:

- `deploy/docker/pipeline.env`

Typical responsibilities:

- Sensor Tower API secret
- Socialdata app slug
- Socialdata auth settings
- Compass / OpenAI-compatible API key
- overlap windows
- verification behavior

### Model policy file

Path:

- `deploy/docker/pipeline.models.env`

This tracked file defines the non-sensitive Compass model policy used by every
Docker job. It currently uses `gpt-5.6-luna` for high-volume detection and
legacy Facebook merging, and `gpt-5.6-terra` for unified-event merge and
harvest work. Do not place API keys or other secrets in this file.

For an existing VM, preserve `deploy/docker/pipeline.env` outside the repo,
reset that tracked file, pull the repository change, then copy the secret file
back. The deployment manual contains the exact migration commands.

### Important authentication notes

#### Public read API

Optional:

- `VN_EVENT_DW_API_KEY`
- `VN_EVENT_DW_API_KEYS_FILE`

When both are blank, `/api/...`, `/api/v2/...`, and `/api/events/v2/...` remain public.
Use `VN_EVENT_DW_API_KEY` for one simple shared key. Use `VN_EVENT_DW_API_KEYS_FILE` for the recommended multi-person setup where each person gets their own generated key and revoked keys do not affect everyone else.

When protection is configured, callers must include a valid key in either:

- `X-API-Key`
- `Authorization: Bearer`

The admin UI is separate and still uses `ADMIN_PASSWORD`.

#### Socialdata

Recommended unattended auth:

- Google service-account JSON mounted into `/app/secrets/socialdata-service-account.json`

Required scope:

- `https://www.googleapis.com/auth/userinfo.email`

Why:

- Socialdata needs an email-bearing Google token so it can identify the granted service-account user

#### Sensor Tower

Required:

- `SENSOR_TOWER_AUTH_TOKEN`

#### Compass / OpenAI-compatible API

Required:

- `OPENAI_API_KEY`
- `OPENAI_BASE_URL`
- `OPENAI_PROVIDER`

Used by:

- monthly unified-event build

## 7. Main Operational Flows

### Flow A: Socialdata sync

Command shape:

```bash
python -m vn_event_dw.cli sync-socialdata-posts --db data/warehouse.db --config examples/config.json --lookback-days 10
```

What it does:

1. authenticates to Socialdata
2. resolves the configured app slug
3. lists channels
4. keeps only channels whose `sub` matches tracked `fb_page_id`
5. fetches recent posts and metrics
6. upserts them into `raw_fb_posts`

The sync stops at the cutoff only when every post on the current Socialdata page is older than the cutoff. This protects newly onboarded games if Socialdata returns a mixed page where one older post appears before another recent post.

Diagnostic command for one game:

```bash
python -m vn_event_dw.cli diagnose-socialdata-game \
  --db data/warehouse.db \
  --config examples/config.json \
  --unified-app-id 5da680bb42fa0c4364eb64c8 \
  --lookback-days 30
```

This prints:

- configured FB page IDs
- matched Socialdata channel ID/name/status
- latest Socialdata posts
- latest DB posts
- recent Socialdata source post IDs missing from `raw_fb_posts`

For admin/automation checks, add `--fail-on-missing`.

### Flow B: Sensor Tower raw sync

Command shape:

```bash
python -m vn_event_dw.cli sync-sensortower-raw --config examples/config.json --lookback-days 3
```

What it does:

1. queries the configured Sensor Tower targets
2. writes replayable raw snapshots under `data_ingest/sensortower/raw`
3. records a manifest for the run

### Flow C: Sensor Tower raw load

Command shape:

```bash
python -m vn_event_dw.cli load-sensortower-raw --db data/warehouse.db
```

What it does:

1. loads any pending raw manifests
2. updates raw landing tables
3. regenerates deterministic Sensor Tower event tables

### Flow D: Unified-event build

Command shape:

```bash
python -m vn_event_dw.cli build-unified-events-llm --db data/warehouse.db --month 2026-07
```

What it does:

1. scopes source evidence to a month
2. runs merge logic over FB and Sensor Tower evidence
3. writes final monthly rows into `unified_events`
4. writes lineage into `unified_event_sources`

## 8. Production Deployment Shape

Recommended production layout on the Ubuntu VM:

- repo:
  - `/opt/vn_event_dw/vn_competitor_event_data_system`
- DB:
  - `/opt/vn_event_dw/data/warehouse.db`
- raw ingest:
  - `/opt/vn_event_dw/data_ingest`
- mounted secrets:
  - `/opt/vn_event_dw/secrets`
- cron log:
  - `/opt/vn_event_dw/pipeline-cron.log`

Full deployment guide:

- [Ubuntu VM Deployment (Docker Compose)](./deploy_ubuntu_vm_docker.md)

## 9. Public API

The system exposes a read-only event API.

New agents should use the `/api/events/v2` endpoints because they distinguish event `month_bucket` filters from actual FB post `publish_time` filters and fit the shared `market-data.garena.vn` API namespace.

Recommended v2 docs:

- [Agent-Friendly API v2](./api_v2.md)
- [Agent Instructions For API v2](./api_v2_agent_instructions.md)

Legacy endpoints:

Core endpoints:

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

Detailed docs:

- [Event Lookup API](./api.md)
- [Event Lookup API Technical Spec](./api_technical_spec.md)

## 10. Weekly Production Refresh

### Current intended behavior

Each scheduled pipeline run should:

1. sync recent Socialdata posts
2. sync recent Sensor Tower raw data
3. load pending Sensor Tower manifests
4. rebuild the previous month and current month
5. restart the API
6. verify API health
7. verify DB freshness

### Current overlap windows

- Socialdata:
  - `10` days
- Sensor Tower:
  - `3` days

### Current schedule

Current cron example:

```bash
0 2 * * 1 cd /opt/vn_event_dw/vn_competitor_event_data_system && /opt/vn_event_dw/vn_competitor_event_data_system/deploy/docker/run_vm_pipeline.sh >> /opt/vn_event_dw/pipeline-cron.log 2>&1
```

Meaning:

- every Monday
- at `02:00 UTC`

## 11. Manual Catch-Up Procedure

Use this when a scheduled run was missed and you need to catch the system up.

### Goal

- backfill missed raw posts
- backfill missed Sensor Tower data
- rebuild recent months

### Typical pattern

From the VM repo root:

```bash
export SOCIALDATA_SYNC_LOOKBACK_DAYS=21
export SENSORTOWER_SYNC_LOOKBACK_DAYS=21
./deploy/docker/run_vm_pipeline.sh
```

Why:

- this widens the overlap just for the current shell session
- it helps safely recover from missed weekly runs without permanently changing defaults

### After the run

Verify latest raw FB publish time and rebuilt month coverage.

## 12. Operational Verification Commands

### Check latest raw FB timestamps

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

### Check rebuilt unified-event months

```bash
sudo docker compose --env-file deploy/docker/vm.env -f deploy/docker/docker-compose.yml --profile ops run --rm --no-deps job \
python - <<'PY'
import sqlite3
conn = sqlite3.connect("/app/data/warehouse.db")
rows = conn.execute("""
SELECT
  month_bucket,
  COUNT(*) AS unified_event_count
FROM unified_events
GROUP BY month_bucket
ORDER BY month_bucket DESC
LIMIT 12
""").fetchall()
for r in rows:
    print(r)
PY
```

### Check latest FB-backed event evidence by month

```bash
sudo docker compose --env-file deploy/docker/vm.env -f deploy/docker/docker-compose.yml --profile ops run --rm --no-deps job \
python - <<'PY'
import sqlite3
conn = sqlite3.connect("/app/data/warehouse.db")
rows = conn.execute("""
SELECT
  ue.month_bucket,
  COUNT(DISTINCT ue.unified_event_id) AS fb_backed_event_count,
  COUNT(DISTINCT ues.source_id) AS linked_fb_post_count,
  MAX(fb.publish_time) AS latest_linked_fb_publish_time
FROM unified_events ue
JOIN unified_event_sources ues
  ON ues.unified_event_id = ue.unified_event_id
 AND ues.source_type = 'fb_post'
JOIN raw_fb_posts fb
  ON fb.source_post_id = ues.source_id
GROUP BY ue.month_bucket
ORDER BY ue.month_bucket DESC
LIMIT 12
""").fetchall()
for r in rows:
    print(r)
PY
```

### Check API container health

```bash
sudo docker compose --env-file deploy/docker/vm.env -f deploy/docker/docker-compose.yml ps
sudo docker compose --env-file deploy/docker/vm.env -f deploy/docker/docker-compose.yml logs --tail=100 api
```

## 13. Cron and Scheduling Verification

### Show current cron setting

```bash
crontab -l
```

### Show when the user crontab was created or modified

```bash
sudo stat /var/spool/cron/crontabs/garenavn
```

Useful fields:

- `Birth`
- `Modify`

### Show cron-specific run evidence

```bash
sudo grep CRON /var/log/syslog | grep garenavn | tail -n 100
```

### Show pipeline log history

```bash
grep "vm_pipeline_" /opt/vn_event_dw/pipeline-cron.log
tail -n 200 /opt/vn_event_dw/pipeline-cron.log
```

### Cheap smoke test

Temporarily install a 1-minute cron write test:

```bash
(
  crontab -l
  echo '* * * * * date -u >> /opt/vn_event_dw/pipeline-cron.log 2>&1'
) | crontab -
```

If timestamps start appearing in the log, cron is working.

Then restore the real weekly job.

## 14. What Was Fixed In The Recent Cron Incident

Two issues were corrected:

### A. File ownership / write access

The cron log and working area were made writable by the VM user:

```bash
sudo touch /opt/vn_event_dw/pipeline-cron.log
sudo chown garenavn:garenavn /opt/vn_event_dw/pipeline-cron.log
sudo chown -R garenavn:garenavn /opt/vn_event_dw
```

### B. Clean cron line

The crontab was rewritten with a clean single-line command:

```bash
printf '%s\n' '0 2 * * 1 cd /opt/vn_event_dw/vn_competitor_event_data_system && /opt/vn_event_dw/vn_competitor_event_data_system/deploy/docker/run_vm_pipeline.sh >> /opt/vn_event_dw/pipeline-cron.log 2>&1' | crontab -
```

## 15. Common Failure Modes

### Socialdata auth returns `Invalid Email`

Most likely causes:

- wrong Google token scope
- wrong or ungranted service-account email
- service account not added in Socialdata users page

Check:

- `SOCIALDATA_GOOGLE_SCOPES=https://www.googleapis.com/auth/userinfo.email`
- the service-account email exists in Socialdata users

### Socialdata auth returns no `usession`

Possible causes:

- exchange endpoint behavior changed
- token expired
- account not recognized by Socialdata

### `403 Forbidden` from Compass Gateway

Possible causes:

- wrong API key
- key not found
- project balance issue
- VM IP not whitelisted if the gateway enforces allowlisting

### ngrok endpoint offline

Possible causes:

- ngrok container down
- wrong ngrok auth token
- reserved domain already attached elsewhere
- port binding conflict

### API starts but returns old data

Possible causes:

- raw sync has not run recently
- unified-event build has not run for the target month
- API restarted against an old DB

## 16. Recommended Handoff Checklist

When handing this system to another operator, make sure they know:

- where the VM repo lives
- where the DB file lives
- where the secrets are stored
- how to run the manual pipeline
- how to check the public API
- how to verify raw FB freshness
- how to verify rebuilt months
- how to inspect cron logs

Recommended doc bundle:

- [System Manual](./system_manual.md)
- [Ubuntu VM Deployment (Docker Compose)](./deploy_ubuntu_vm_docker.md)
- [Event Lookup API](./api.md)
- [Socialdata guide for non-technical users (VI)](./socialdata_huong_dan_nguoi_dung_vi.md)
- [Socialdata guide for Claude/Codex (VI)](./socialdata_huong_dan_agent_vi.md)

## 17. Current Technology Choices

Current production path:

- SQLite warehouse
- Python ETL / API
- Docker Compose on Ubuntu VM
- ngrok public exposure
- cron or systemd scheduling

Potential future upgrade:

- migrate SQLite to PostgreSQL if multi-user direct DB access becomes important
