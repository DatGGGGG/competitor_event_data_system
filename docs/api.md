# Event Lookup API

This project exposes a read-only HTTP API on top of the SQLite warehouse.

For new agents and analyst tools, prefer the clearer `/api/events/v2` contract:

- [Agent-Friendly API v2](./api_v2.md)
- [Agent Instructions For API v2](./api_v2_agent_instructions.md)

This document describes the legacy `/api` endpoints kept for backward compatibility.

Source implementation:

- [api.py](C:/Users/VEE0634/Desktop/Coding/vn_competitor_event_data_system/src/vn_event_dw/api.py)
- [api_service.py](C:/Users/VEE0634/Desktop/Coding/vn_competitor_event_data_system/src/vn_event_dw/api_service.py)

## Run Locally

```bash
python -m vn_event_dw.cli serve-api --db data/warehouse.db
```

Default local URL:

- `http://127.0.0.1:8765`

To expose it through ngrok:

```bash
python -m vn_event_dw.cli serve-api-ngrok --db data/warehouse.db
```

## Authentication

Set `VN_EVENT_DW_API_KEY` to require one shared key, or set `VN_EVENT_DW_API_KEYS_FILE` to use a managed JSON key store for multiple people.

Recommended managed-key commands:

```bash
python -m vn_event_dw.cli api-key-generate --keys-file local_secrets/api_keys.json --name teammate-name
python -m vn_event_dw.cli api-key-list --keys-file local_secrets/api_keys.json
python -m vn_event_dw.cli api-key-revoke --keys-file local_secrets/api_keys.json --name teammate-name
```

The generated raw key is printed once. The key store saves only a SHA-256 hash.

When configured, callers must send either:

```text
X-API-Key: your_api_key
```

or:

```text
Authorization: Bearer your_api_key
```

Example:

```bash
curl \
  -H "X-API-Key: your_api_key" \
  "https://market-data.garena.vn/api/events/v2/games"
```

If both `VN_EVENT_DW_API_KEY` and `VN_EVENT_DW_API_KEYS_FILE` are blank, the read API remains public.

## Base Concepts

- `unified_app_id` is the canonical game identifier.
- `unified_event_id` is the canonical merged event identifier.
- `source_post_id` is the Facebook post identifier from `raw_fb_posts`.
- collection endpoints use warehouse `month_bucket` filtering.
- FB metrics are aggregated from all FB posts linked to an event.
- `social_score = 2 * reaction + 3 * comment + 5 * share + view`

## Endpoint Summary

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

## Shared Collection Query Contract

Applies to:

- `GET /api/events`
- `GET /api/events/compact`
- `GET /api/events/summary`

Required query params:

- `unified_app_id` repeatable
- `time_range_start` in `YYYY-MM-DD`
- `time_range_end` in `YYYY-MM-DD`

Optional filters:

- `event_category` repeatable
- `source_type` repeatable
  - allowed values:
    - `fb_post`
    - `st_app_update_event`
    - `st_version_event`
- `min_social_score`
- `has_fb_posts`

Filter semantics:

- OR within repeated `event_category`
- OR within repeated `source_type`
- AND across different filter types

Month-bucket behavior:

- `2026-04-01` to `2026-04-30` -> `2026-04`
- `2026-04-15` to `2026-05-02` -> `2026-04`, `2026-05`

An event is included when its stored `month_bucket` is one of the derived buckets.

## `GET /api/games`

Purpose:

- list all games
- search games by name, id, or acronym such as `MLBB`

Query params:

- `q` optional

Example:

```text
/api/games?q=MLBB
```

Response:

```json
{
  "results": [
    {
      "unified_app_id": "57955d280211a6718a000002",
      "app_name": "Mobile Legends: Bang Bang"
    }
  ]
}
```

## `GET /api/events`

Purpose:

- return detailed event rows
- optionally return only top N events per app

Optional query params:

- all shared collection filters
- `top`

Example:

```text
/api/events?unified_app_id=57955d280211a6718a000002&time_range_start=2026-05-01&time_range_end=2026-05-31&top=5
```

## `GET /api/events/compact`

Purpose:

- return a compact ID/name/category event list

Response event shape:

```json
{
  "unified_event_id": "...",
  "canonical_event_name": "...",
  "event_category": "..."
}
```

## `GET /api/events/summary`

Purpose:

- return aggregate event counts and FB metrics per app

Response statistics fields:

- `event_count_total`
- `event_count_st_app_update`
- `event_count_st_version`
- `event_count_fb`
- `total_engagement_fb`
- `total_reaction_fb`
- `total_comment_fb`
- `total_share_fb`
- `total_view_fb`
- `top_socially_active_events`

## `GET /api/events/coverage`

Purpose:

- show app-level availability and freshness
- help agents distinguish “no events” from “no loaded data”

Optional query params:

- `unified_app_id` repeatable
- `time_range_start`
- `time_range_end`

Response fields:

- `unified_app_id`
- `app_name`
- `min_month_bucket`
- `max_month_bucket`
- `months_available`
- `event_count`
- `fb_post_count`
- `latest_ingested_at`

## `GET /api/events/search`

Purpose:

- search events by approximate event name
- support imperfect user input, including crossovers or partially wrong names

Query params:

- `q` required
- `unified_app_id` repeatable optional
- `time_range_start` optional
- `time_range_end` optional
- `top` optional, default `10`

Behavior:

- searches requested games first when `unified_app_id` is supplied
- falls back cross-game only if scoped results are not strong enough
- uses normalized substring matching plus moderate fuzzy scoring

Response fields per match:

- `unified_event_id`
- `unified_app_id`
- `app_name`
- `canonical_event_name`
- `event_category`
- `canonical_event_description`
- `month_bucket`
- `social_score`
- `fb_post_count`
- `match_score`
- `match_scope`

## `GET /api/events/{unified_event_id}`

Purpose:

- full detail for one event

## `GET /api/events/{unified_event_id}/post-stats`

Purpose:

- FB-post aggregate metrics for one event

Response fields:

- `fb_post_count`
- `total_engagement_fb`
- `total_reaction_fb`
- `total_comment_fb`
- `total_share_fb`
- `total_view_fb`
- `social_score`

## `GET /api/events/{unified_event_id}/top-posts`

Purpose:

- top FB posts for one event

Optional query params:

- `top` default `5`

## `GET /api/events/{unified_event_id}/posts`

Purpose:

- compact list of all FB posts for one event

## `GET /api/posts/{source_post_id}`

Purpose:

- full detail for one FB post

## Status / Error Behavior

- `200` success
- `400` invalid business rules
  - reversed date ranges
  - only one date supplied to optional date-window endpoints
- `404` missing event or post
- `422` invalid query shapes
  - missing required params
  - bad date format
  - unsupported `source_type`

## Recommended Agent Flow

1. Call `/api/games`
2. For overview, call `/api/events/summary`
3. For compact browsing, call `/api/events/compact`
4. For full event rows, call `/api/events`
5. For uncertain event-name input, call `/api/events/search`
6. For data availability checks, call `/api/events/coverage`
7. Drill into `/api/events/{unified_event_id}` only when needed
