# Event Lookup API v2

`/api/events/v2` is the agent-friendly Event API surface for event and Facebook post lookup.
It keeps the legacy `/api/v2/...` and old `/api/...` endpoints live while making one distinction explicit:

- event endpoints filter by `unified_events.month_bucket`
- raw post endpoints filter by `raw_fb_posts.publish_time`

Base URLs:

- Public: `https://market-data.garena.vn`
- Local VM: `http://127.0.0.1:8765`

## Authentication

The API can be protected with a shared key by setting `VN_EVENT_DW_API_KEY`, or with a managed key store by setting `VN_EVENT_DW_API_KEYS_FILE`.

When both values are blank, `/api/...`, `/api/v2/...`, and `/api/events/v2/...` are public. `/api/events/v2/health` and `/api/v2/health` stay public so Docker health checks can keep working.

For multiple teammates, generate one key per person:

```bash
python -m vn_event_dw.cli api-key-generate --keys-file local_secrets/api_keys.json --name teammate-name
python -m vn_event_dw.cli api-key-list --keys-file local_secrets/api_keys.json
python -m vn_event_dw.cli api-key-revoke --keys-file local_secrets/api_keys.json --name teammate-name
```

When protection is configured, every `/api/...`, `/api/v2/...`, and `/api/events/v2/...` request except health endpoints must include one of:

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

The tracked-games admin UI is hosted at
`/workspaces/tracked-games/events/...` and is opened through a short-lived,
one-time Portal grant. During rollout it can retain `ADMIN_PASSWORD` as a
fallback with `ADMIN_AUTH_MODE=portal_with_password_fallback`; production
should switch to `ADMIN_AUTH_MODE=portal` after SSO is verified. The legacy
`/api/events/admin/...` route temporarily redirects to the workspace path.

## Response Shape

Collection endpoints return:

```json
{
  "results": [],
  "meta": {
    "api_version": "v2",
    "generated_at": "2026-08-07T00:00:00+00:00",
    "scope": {},
    "semantics": "raw_fb_post_publish_time",
    "count": 0
  }
}
```

Single-resource endpoints return `result` plus the same `meta` block.

## Endpoints

### `GET /api/events/v2/health`

Lists available v2 endpoints.

Legacy alias: `GET /api/v2/health`

### `GET /api/events/v2/games`

Lists tracked games.

Query params:

- `q`, optional search text

Legacy alias: `GET /api/v2/games`

### `GET /api/events/v2/games/{unified_app_id}`

Returns one tracked game with its configured Facebook page IDs.

Legacy alias: `GET /api/v2/games/{unified_app_id}`

### `GET /api/events/v2/games/{unified_app_id}/events`

Lists events for one game.

Event time filters use event month buckets, not Facebook post dates.

Query params:

- `month=YYYY-MM`, repeatable
- or `start_month=YYYY-MM&end_month=YYYY-MM`
- `top`, optional, ranks by social score
- `event_category`, repeatable
- `source_type`, repeatable: `fb_post`, `st_app_update_event`, `st_version_event`
- `min_social_score`
- `has_fb_posts`

Example:

```bash
curl "https://market-data.garena.vn/api/events/v2/games/5da680bb42fa0c4364eb64c8/events?month=2026-08"
```

Legacy alias: `GET /api/v2/games/{unified_app_id}/events`

### `GET /api/events/v2/games/{unified_app_id}/events/summary`

Aggregates event counts and FB metrics for one game.

Uses the same event month-bucket filters as `/events`.

Legacy alias: `GET /api/v2/games/{unified_app_id}/events/summary`

### `GET /api/events/v2/games/{unified_app_id}/events/search`

Fuzzy event-name search scoped to one game, with cross-game fallback behavior inherited from the event search service.

Query params:

- `q`, required
- `month=YYYY-MM`, repeatable
- or `start_month=YYYY-MM&end_month=YYYY-MM`
- `top`, default `10`

Legacy alias: `GET /api/v2/games/{unified_app_id}/events/search`

### `GET /api/events/v2/games/{unified_app_id}/events/coverage`

Returns event coverage/freshness for one game.

Uses event month buckets when month filters are provided.

Legacy alias: `GET /api/v2/games/{unified_app_id}/events/coverage`

### `GET /api/events/v2/games/{unified_app_id}/posts`

Lists raw Facebook posts for one game, even if the posts are not linked to any event.

This is the endpoint to use for questions like:

- "Does this game have FB posts in August?"
- "What are the latest FB posts for this game?"

Query params:

- `publish_start=YYYY-MM-DD`, optional
- `publish_end=YYYY-MM-DD`, optional
- `limit`, default `20`, max `100`
- `q`, optional text search over post description

Post metric fields:

- `engagement_count`
- `reaction_count`
- `comment_count`
- `share_count`
- `view_count`
- `social_score`

Each post includes:

```json
"linked_events": [
  {
    "unified_event_id": "uev_...",
    "canonical_event_name": "Event name",
    "month_bucket": "2026-08"
  }
]
```

Example:

```bash
curl "https://market-data.garena.vn/api/events/v2/games/5da680bb42fa0c4364eb64c8/posts?publish_start=2026-08-01&publish_end=2026-08-31"
```

Legacy alias: `GET /api/v2/games/{unified_app_id}/posts`

### `GET /api/events/v2/events/{unified_event_id}`

Returns one event detail row.

Legacy alias: `GET /api/v2/events/{unified_event_id}`

### `GET /api/events/v2/events/{unified_event_id}/post-stats`

Returns FB post totals linked to one event.

Legacy alias: `GET /api/v2/events/{unified_event_id}/post-stats`

### `GET /api/events/v2/events/{unified_event_id}/posts`

Returns posts linked to one event using v2 metric field names.

Legacy alias: `GET /api/v2/events/{unified_event_id}/posts`

### `GET /api/events/v2/posts/{source_post_id}`

Returns one raw FB post with normalized metrics and linked event references.

Legacy alias: `GET /api/v2/posts/{source_post_id}`

## Agent Guidance

Use `/api/events/v2/games/{game_id}/posts` to answer raw post questions.
Do not infer post publish dates from event `month_bucket`.

Use `/api/events/v2/games/{game_id}/events` or `/events/summary` to answer event questions.
When reporting event results, describe `month_bucket` as the event bucket used by the warehouse, not as the actual date of every linked post.
