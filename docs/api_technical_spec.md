# Event Lookup API Technical Specification

This document describes the current HTTP API contract implemented by:

- [api.py](C:/Users/VEE0634/Desktop/Coding/vn_competitor_event_data_system/src/vn_event_dw/api.py)
- [api_service.py](C:/Users/VEE0634/Desktop/Coding/vn_competitor_event_data_system/src/vn_event_dw/api_service.py)

New agents should prefer `/api/events/v2`:

- [Agent-Friendly API v2](./api_v2.md)
- [Agent Instructions For API v2](./api_v2_agent_instructions.md)

The legacy `/api` contract below remains available during migration.

## Base URL

- Public:
  - `https://market-data.garena.vn`
- Local:
  - `http://127.0.0.1:8765`

## General Characteristics

- Protocol: HTTP/1.1
- Content type: `application/json`
- Authentication: none
- API style: read-only JSON endpoints
- Date format: `YYYY-MM-DD`

## Core Identifiers

- `unified_app_id`
  - canonical game identifier
- `unified_event_id`
  - canonical merged event identifier
- `source_post_id`
  - Facebook post identifier from `raw_fb_posts`

## Shared Validation Rules

### Required collection lookup

Applies to:

- `GET /api/events`
- `GET /api/events/compact`
- `GET /api/events/summary`

Rules:

- at least one `unified_app_id` is required
- `time_range_start` must be on or before `time_range_end`
- query dates must be valid ISO dates

### Optional date-window endpoints

Applies to:

- `GET /api/events/coverage`
- `GET /api/events/search`

Rules:

- `time_range_start` and `time_range_end` must either both be present or both be absent
- if both are present, `time_range_start <= time_range_end`

### Status behavior

- `200` success
- `400` business-rule validation failure
- `404` missing single resource
- `422` invalid query shape or type

## Month-Bucket Filtering

The event collection endpoints use warehouse `month_bucket` filtering, not event-date overlap.

Applies to:

- `GET /api/events`
- `GET /api/events/compact`
- `GET /api/events/summary`
- `GET /api/events/search` when a date window is supplied
- `GET /api/events/coverage` when a date window is supplied

Rule:

1. Convert the requested date range into one or more `YYYY-MM` buckets.
2. Include rows where `unified_events.month_bucket` is in that bucket set.

Examples:

- `2026-05-01` to `2026-05-31` -> `2026-05`
- `2026-05-15` to `2026-05-15` -> `2026-05`
- `2026-04-20` to `2026-05-03` -> `2026-04`, `2026-05`

## Metric Parsing

Facebook metrics in `raw_fb_posts` are stored as strings and normalized to integers by:

- trimming whitespace
- removing commas
- removing periods
- removing spaces
- removing `+`
- defaulting blank values to `0`

Derived numeric fields:

- `engagement_num`
- `reaction_num`
- `comment_num`
- `share_num`
- `view_num`

## Social Score

Weights:

- reaction = `2`
- comment = `3`
- share = `5`
- view = `1`

Formula:

```text
social_score = 2 * reaction + 3 * comment + 5 * share + view
```

## Collection Filters

Applies to:

- `GET /api/events`
- `GET /api/events/compact`
- `GET /api/events/summary`

Optional query params:

- `event_category`
  - type: `string`
  - repeatable: yes
- `source_type`
  - type: enum
  - repeatable: yes
  - allowed values:
    - `fb_post`
    - `st_app_update_event`
    - `st_version_event`
- `min_social_score`
  - type: integer
  - minimum: `0`
- `has_fb_posts`
  - type: boolean

Semantics:

- OR within repeated `event_category`
- OR within repeated `source_type`
- AND across different filter types

`source_type` behavior:

- `fb_post` means `fb_post_count > 0`
- `st_app_update_event` means `st_app_update_event_count > 0`
- `st_version_event` means `st_version_event_count > 0`

`has_fb_posts` behavior:

- `true` means `fb_post_count > 0`
- `false` means `fb_post_count = 0`

## Endpoint Specification

### 1. GET `/api/games`

Purpose:

- list all registered games
- or search for a game by name, id, or acronym

Query params:

- `q`
  - type: `string`
  - required: no
  - minimum length: `1` when supplied

Matching behavior:

- normalized `unified_app_id`
- normalized `app_name`
- acronym of `app_name`

Sorting:

- `LOWER(app_name) ASC`
- `LOWER(unified_app_id) ASC`

Response:

```json
{
  "results": [
    {
      "unified_app_id": "string",
      "app_name": "string"
    }
  ]
}
```

### 2. GET `/api/events`

Purpose:

- return detailed event objects for one or more apps in a scoped month-bucket window
- optionally return top `N` events per app

Query params:

- shared required collection lookup params
- shared optional collection filters
- `top`
  - type: integer
  - required: no
  - minimum: `1`

Sorting:

- without `top`
  - `effective_start_date ASC`
  - `canonical_event_name ASC`
- with `top`
  - `social_score DESC`
  - `total_engagement_fb DESC`
  - `canonical_event_name ASC`

Response event fields:

- `unified_event_id`
- `canonical_event_name`
- `event_category`
- `estimated_start_date`
- `estimated_end_date`
- `canonical_event_description`
- `anchor_source_type`
- `merge_confidence`
- `month_bucket`
- `fb_post_count`
- `st_app_update_event_count`
- `st_version_event_count`
- `total_engagement_fb`
- `total_reaction_fb`
- `total_comment_fb`
- `total_share_fb`
- `total_view_fb`
- `social_score`

### 3. GET `/api/events/compact`

Purpose:

- return compact event rows for one or more apps

Query params:

- shared required collection lookup params
- shared optional collection filters

Sorting:

- `effective_start_date ASC`
- `canonical_event_name ASC`

Response event fields:

- `unified_event_id`
- `canonical_event_name`
- `event_category`

### 4. GET `/api/events/summary`

Purpose:

- return aggregated event statistics for one or more apps

Query params:

- shared required collection lookup params
- shared optional collection filters

Statistics fields:

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

Top social event fields:

- `unified_event_id`
- `canonical_event_name`
- `event_category`
- `social_score`
- `total_engagement_fb`
- `total_reaction_fb`
- `total_comment_fb`
- `total_share_fb`
- `total_view_fb`

Source-type count semantics are non-exclusive.

### 5. GET `/api/events/coverage`

Purpose:

- return app-level availability and freshness metadata

Query params:

- `unified_app_id`
  - type: `string`
  - required: no
  - repeatable: yes
- `time_range_start`
  - type: `date`
  - required: no
- `time_range_end`
  - type: `date`
  - required: no

Behavior:

- if `unified_app_id` is omitted, include all games in registry order
- if a date window is provided, scope coverage to the derived month buckets
- if a requested app has no matching events in scope, return a zero-count block

Response fields:

- `unified_app_id`
- `app_name`
- `min_month_bucket`
- `max_month_bucket`
- `months_available`
- `event_count`
- `fb_post_count`
- `latest_ingested_at`

Definitions:

- `months_available`
  - count of distinct `month_bucket` values after scoping
- `event_count`
  - count of distinct unified events after scoping
- `fb_post_count`
  - count of distinct linked FB posts after scoping
- `latest_ingested_at`
  - max linked `raw_fb_posts.ingested_at`
  - `null` if no linked FB posts exist

### 6. GET `/api/events/search`

Purpose:

- return candidate event matches for imperfect event-name queries

Query params:

- `q`
  - type: `string`
  - required: yes
  - minimum length: `1`
- `unified_app_id`
  - type: `string`
  - required: no
  - repeatable: yes
- `time_range_start`
  - type: `date`
  - required: no
- `time_range_end`
  - type: `date`
  - required: no
- `top`
  - type: integer
  - required: no
  - default: `10`
  - minimum: `1`

Search behavior:

1. Normalize query and candidate texts.
2. Score candidates using:
   - normalized substring matches on `canonical_event_name`
   - normalized substring matches on `canonical_event_description`
   - token overlap
   - moderate fuzzy similarity on event name and description
3. If `unified_app_id` is supplied:
   - search those apps first
   - return scoped results if they clear the internal acceptance threshold
   - otherwise fallback to cross-game search
4. If a date window is supplied:
   - scope by derived month buckets
5. Sort accepted matches by:
   - `match_score DESC`
   - `social_score DESC`
   - `total_engagement_fb DESC`
   - `canonical_event_name ASC`

Response fields:

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
  - `scoped_game`
  - `cross_game_fallback`

### 7. GET `/api/events/{unified_event_id}`

Purpose:

- return full detail for one unified event

Response fields:

- `unified_event_id`
- `unified_app_id`
- `app_name`
- `canonical_event_name`
- `event_category`
- `estimated_start_date`
- `estimated_end_date`
- `canonical_event_description`
- `anchor_source_type`
- `merge_confidence`
- `month_bucket`
- `fb_post_count`
- `st_app_update_event_count`
- `st_version_event_count`
- `total_engagement_fb`
- `total_reaction_fb`
- `total_comment_fb`
- `total_share_fb`
- `total_view_fb`
- `social_score`

404 detail:

- `Unified event not found.`

### 8. GET `/api/events/{unified_event_id}/post-stats`

Purpose:

- return FB-post aggregate metrics for one event

Response fields:

- `unified_event_id`
- `unified_app_id`
- `app_name`
- `canonical_event_name`
- `event_category`
- `estimated_start_date`
- `estimated_end_date`
- `fb_post_count`
- `total_engagement_fb`
- `total_reaction_fb`
- `total_comment_fb`
- `total_share_fb`
- `total_view_fb`
- `social_score`

404 detail:

- `Unified event not found.`

### 9. GET `/api/events/{unified_event_id}/top-posts`

Purpose:

- return the top FB posts for one event

Query params:

- `top`
  - type: integer
  - default: `5`
  - minimum: `1`

Ranking:

- `social_score DESC`
- `engagement_num DESC`
- `source_post_id ASC`

Per-post fields:

- `source_post_id`
- `publish_time`
- `link`
- `engagement_num`
- `reaction_num`
- `comment_num`
- `share_num`
- `view_num`
- `social_score`

404 detail:

- `Unified event not found.`

### 10. GET `/api/events/{unified_event_id}/posts`

Purpose:

- return all linked FB posts for one event in compact form

Per-post fields:

- `source_post_id`
- `publish_time`
- `engagement_num`
- `reaction_num`
- `comment_num`
- `share_num`
- `view_num`
- `social_score`

Sorting:

- `publish_time ASC`
- `source_post_id ASC`

404 detail:

- `Unified event not found.`

### 11. GET `/api/posts/{source_post_id}`

Purpose:

- return the full raw + normalized detail for one FB post

Response fields:

- `source_post_id`
- `unified_app_id`
- `app_name`
- `fb_page_id`
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
- `source_file`
- `ingested_at`
- `engagement_num`
- `reaction_num`
- `comment_num`
- `share_num`
- `view_num`
- `social_score`

404 detail:

- `Post not found.`

## Current Public Endpoint List

- `/api/games`
- `/api/events`
- `/api/events/compact`
- `/api/events/summary`
- `/api/events/coverage`
- `/api/events/search`
- `/api/events/{unified_event_id}`
- `/api/events/{unified_event_id}/post-stats`
- `/api/events/{unified_event_id}/top-posts`
- `/api/events/{unified_event_id}/posts`
- `/api/posts/{source_post_id}`

## Recommended Client Flow

1. Resolve the game with `GET /api/games`.
2. If the user wants a high-level overview, call `GET /api/events/summary`.
3. If the user wants a compact browseable list, call `GET /api/events/compact`.
4. If the user needs detailed rows, call `GET /api/events`.
5. If the event name is uncertain, call `GET /api/events/search`.
6. If zero results may be ambiguous, call `GET /api/events/coverage`.
7. Drill into `GET /api/events/{unified_event_id}` or the post endpoints only when needed.
