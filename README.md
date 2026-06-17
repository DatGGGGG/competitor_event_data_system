# Mini Event Data Warehouse

This project is a compact event-focused data warehouse with full ETL flow:

- `Extract` from CSV landing files and a JSON config file
- `Extract` raw Sensor Tower JSON snapshots for tracked `unified_app_id` targets
- `Transform` into deterministic warehouse tables
- `Load` Sensor Tower app-update events for downstream analysis
- `Analyze` monthly cross-source evidence into unified business-level game events

It is intentionally small, but the structure mirrors a production warehouse:

- `config_app_mapping` acts as the unified app/page mapping dimension
- `raw_*` tables are immutable landing tables
- `st_app_update_events` stores deterministic Sensor Tower app-update events
- `post_event_detection` and `post_event_objects` remain available as legacy/debug FB pipeline tables
- `unified_events` and `unified_event_sources` store the final cross-source merged event layer
- `data_ingest/sensortower/raw` stores replayable raw Sensor Tower snapshots and manifests

## API Docs

The project also exposes a small read-only event lookup API.

Documentation:

- [Event Lookup API](C:/Users/VEE0634/Desktop/Coding/vn_competitor_event_data_system/docs/api.md)
- [Event Lookup API Technical Spec](C:/Users/VEE0634/Desktop/Coding/vn_competitor_event_data_system/docs/api_technical_spec.md)
- [Ubuntu VM Deployment](C:/Users/VEE0634/Desktop/Coding/vn_competitor_event_data_system/docs/deploy_ubuntu_vm.md)
- [Ubuntu VM Deployment (Docker Compose)](C:/Users/VEE0634/Desktop/Coding/vn_competitor_event_data_system/docs/deploy_ubuntu_vm_docker.md)

Main endpoints:

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

## Socialdata Exploration

The repo now includes a minimal Socialdata exploration scaffold so we can validate authentication and inspect the GraphQL schema before building automated post ingestion.

Environment variables:

- `SOCIALDATA_BASE_URL`
- `SOCIALDATA_USESSION`
- `SOCIALDATA_GOOGLE_ACCESS_TOKEN`
- `SOCIALDATA_GOOGLE_SERVICE_ACCOUNT_FILE`
- `SOCIALDATA_GOOGLE_SCOPES`
- `SOCIALDATA_TIMEOUT_SECONDS`
- `SOCIALDATA_APP_SLUG`

CLI commands:

```bash
python -m vn_event_dw.cli socialdata-mint-google-access-token --google-service-account-file /path/to/service-account.json
python -m vn_event_dw.cli socialdata-mint-google-access-token --google-service-account-file /path/to/service-account.json --token-only
python -m vn_event_dw.cli socialdata-auth-check --usession <cookie>
python -m vn_event_dw.cli socialdata-graphql --query "query { __typename }" --usession <cookie>
python -m vn_event_dw.cli socialdata-introspect --usession <cookie> --output tmp/socialdata_schema.json
python -m vn_event_dw.cli sync-socialdata-posts --db data/warehouse.db --config examples/config.json --lookback-days 10
```

Notes:

- `socialdata-mint-google-access-token` is useful when you want to follow the Socialdata manual callback steps yourself before involving the rest of the pipeline.
- Service-account token minting defaults to `https://www.googleapis.com/auth/userinfo.email`, because Socialdata needs the Google token to expose the granted service-account email.
- Use repeatable `--google-scope` or `SOCIALDATA_GOOGLE_SCOPES` only for debugging alternate Google token scopes.
- Use `--token-only` when you want to paste the token directly into `curl` or another manual callback check.
- `--usession` is the fastest way to test connectivity if you already have a cookie.
- If you do not have a cookie, the commands can also exchange a Google access token through `--google-access-token` or `SOCIALDATA_GOOGLE_ACCESS_TOKEN`.
- For unattended VM scheduling, prefer `SOCIALDATA_GOOGLE_SERVICE_ACCOUNT_FILE` so the client can mint a fresh Google access token on each run.
- `sync-socialdata-posts` matches Socialdata channels to your existing `config_app_mapping.fb_page_id` values using the channel `sub` field, then upserts recent posts into `raw_fb_posts`.
- The weekly sync path uses Socialdata `Post.sub` as `source_post_id`, fetches metrics from `getPost(..., withMetrics: true)`, and applies a small mojibake repair step so Vietnamese text is readable in the warehouse.

Recommended weekly load:

```bash
python -m vn_event_dw.cli sync-socialdata-posts --db data/warehouse.db --config examples/config.json --lookback-days 10
```

Recommended first backfill:

```bash
python -m vn_event_dw.cli sync-socialdata-posts --db data/warehouse.db --config examples/config.json --since 2026-01-01
```

## WSL First

This repo is happiest when you run it from WSL Ubuntu, not from a Windows shell.

Recommended layout:

- clone or copy the repo into your Linux home directory, for example `~/code/vn_competitor_event_data_system`
- create a virtual environment there
- keep the working tree on the Linux filesystem instead of `/mnt/c/...` if you can

Basic WSL setup:

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip
cd ~/code/vn_competitor_event_data_system
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
```

## Quick Start

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

## Project Layout

- `examples/` sample inputs
- `examples/fb_posts/` drop folder for many FB post CSV files
- `src/vn_event_dw/` ETL and warehouse code
- `.env.example` sample environment variables for local development
- `.gitignore` ignores local virtualenvs, caches, and generated raw data

## Sensor Tower Raw Layer

The raw Sensor Tower extractor uses the `sensortower_targets` section in `examples/config.json`.

Each target entry should include:

- `unified_app_id`
- `os`
- `app_id`
- `country`

You also need `SENSOR_TOWER_AUTH_TOKEN` set in your environment before running the raw fetch command.
You can copy `.env.example` to `.env` and fill it in for local development.

For the unified cross-source LLM pipeline you also need:

- `OPENAI_API_KEY`
- `OPENAI_BASE_URL`
- `OPENAI_PROVIDER`
- `OPENAI_MODEL`
  - Compass `/v1/responses` example: `gpt-5.4-nano`
- `OPENAI_UNIFIED_EVENT_MERGE_MODEL`
  - Compass `/v1/responses` example: `gpt-5.4-mini`

Raw snapshots are written under:

- `data_ingest/sensortower/raw`

Run the daily raw extract with overlap:

```bash
python -m vn_event_dw.cli sync-sensortower-raw --config examples/config.json --lookback-days 3
```

Backfill from a specific date:

```bash
python -m vn_event_dw.cli sync-sensortower-raw --config examples/config.json --since 2025-01-01
```

Load any pending raw manifests into the warehouse:

```bash
python -m vn_event_dw.cli load-sensortower-raw --db data/warehouse.db
```

## FB Post Folder

Put FB post CSV files in `examples/fb_posts/` and run the ETL with `--input-dir examples`.

The loader will scan that folder recursively, so you can keep files grouped by game, period, or source.

The loader accepts either the simple four-column format or richer export headers like:

- `source_post_id`
- `fb_page_id`
- `post_time`
- `post_content`

The raw landing table stores the richer FB fields directly:

- `channel_id`
- `channel_name`
- `post_type`
- `post_description`
- `duration`
- `link`
- `publish_time`
- `hashtag`
- `engagement`
- `reaction`
- `comment`
- `share`
- `view`

It also recognizes these aliases from the export files you pasted:

- `Post id` -> `source_post_id`
- `Channel id` -> `fb_page_id`
- `Publish time` -> `post_time`
- `Post description` -> `post_content`
- `Link` is used as a fallback when `Post description` is blank

If `examples/fb_posts/` does not exist, the ETL still supports the old `examples/fb_posts.csv` single-file layout.

To rebuild only the FB landing tables without touching Sensor Tower data, use:

```bash
python -m vn_event_dw.cli reload-fb-posts --db data/warehouse.db --config examples/config.json --input-dir examples
```

To build the final monthly unified event layer directly from `raw_fb_posts` plus Sensor Tower deterministic events, run:

```bash
python -m vn_event_dw.cli build-unified-events-llm --db data/warehouse.db
```

Model defaults:

- `OPENAI_UNIFIED_EVENT_MERGE_MODEL=gpt-5.4-mini` for final cross-source merge
- `OPENAI_MODEL=gpt-5.4-nano` remains available only for the older FB step-1 debug pipeline

## How It Maps To Your Diagram

The diagram can be implemented as:

- `Config` -> `config_app_mapping`
- `FB Posts (csv, raw)` -> `raw_fb_posts`
- `FB post event detection (legacy/debug)` -> `post_event_detection`
- `FB extracted event objects (legacy/debug)` -> `post_event_objects`
- `ST_APP_UPDATE` -> `raw_st_app_update`
- `ST_VERSION` -> `raw_st_version`
- `Deterministic ST updates` -> `st_app_update_events`
- `Deterministic ST versions` -> `st_version_events`
- `Unified final events` -> `unified_events`
- `Unified event lineage` -> `unified_event_sources`

If you want, we can extend this next with:

- incremental loading and watermarks
- SCD Type 2 dimensions
- a richer rule engine
- dbt-style transformations
