# Agent Instructions For API v2

Use `/api/events/v2` for all new SeaTalk, Claude, Codex, and analyst-agent lookups.
`/api/v2` remains a legacy alias during migration, but new calls should use `/api/events/v2`.

Base URL:

```text
https://market-data.garena.vn
```

## API Authentication

The API may require an API key. The system owner should provide the key through a secure agent secret/config variable, not by hard-coding it in the public instruction text.

Recommended secret/config variable names:

```text
EVENT_API_KEY
VN_EVENT_DW_API_KEY
```

For every `/api/...`, `/api/v2/...`, or `/api/events/v2/...` request except health endpoints, include the key in the HTTP request headers:

```text
X-API-Key: <api_key>
```

Alternative accepted format:

```text
Authorization: Bearer <api_key>
```

Authentication rules:

- Do not call protected endpoints without the API key if a key is available.
- Do not put the API key in the URL query string.
- Do not print, summarize, or expose the API key in the final answer.
- If a tool log or error includes the API key, redact it before showing the user.
- If `/api/events/v2/health` works but other endpoints return `401`, retry once with `X-API-Key`.
- If an endpoint returns `403` while the key was already sent, tell the user the configured API key appears invalid or revoked and ask for a valid key.
- If no API key is configured and the endpoint returns `401`, tell the user an API key is required.

The key rule:

- Event endpoints answer questions about `unified_events.month_bucket`.
- Post endpoints answer questions about actual Facebook `raw_fb_posts.publish_time`.

Do not use an event `month_bucket` as proof that a Facebook post was published in that month.

## When The User Asks About Events

Use event endpoints when the user asks about campaigns, events, event rankings, event categories, event coverage, or social score by event.

Examples:

- "Top events of MLBB in August"
- "List monetization events for PUBG"
- "Search for the Naruto event in MLBB"

Recommended endpoints:

- `GET /api/events/v2/games`
- `GET /api/events/v2/games/{unified_app_id}/events?month=YYYY-MM`
- `GET /api/events/v2/games/{unified_app_id}/events?start_month=YYYY-MM&end_month=YYYY-MM`
- `GET /api/events/v2/games/{unified_app_id}/events/summary?month=YYYY-MM`
- `GET /api/events/v2/games/{unified_app_id}/events/search?q=...`
- `GET /api/events/v2/events/{unified_event_id}`
- `GET /api/events/v2/events/{unified_event_id}/post-stats`
- `GET /api/events/v2/events/{unified_event_id}/posts`

State clearly that `month=YYYY-MM` filters event month buckets, not raw FB publish dates.

## When The User Asks About Facebook Posts

Use post endpoints when the user asks whether there are posts in a date range, asks for latest posts, asks for post text, or asks about actual publication dates.

Examples:

- "Are there any posts in August?"
- "Latest FB posts for LMHT: Toc Chien"
- "Posts published from 2026-08-01 to 2026-08-06"
- "Search posts containing sinh nhat"

Recommended endpoint:

- `GET /api/events/v2/games/{unified_app_id}/posts?publish_start=YYYY-MM-DD&publish_end=YYYY-MM-DD`

Optional params:

- `limit`, default `20`, max `100`
- `q`, searches post text

Raw post responses include:

- `publish_time`
- `engagement_count`
- `reaction_count`
- `comment_count`
- `share_count`
- `view_count`
- `social_score`
- `linked_events`

Use `linked_events` only as lineage. A post can exist even if it is not linked to an event yet.

## LMHT-Style Regression Rule

If a user asks:

```text
co post nao trong thang 8 nay khong?
```

Do this:

1. Resolve the game via `GET /api/events/v2/games`.
2. Query raw posts:

```text
GET /api/events/v2/games/{unified_app_id}/posts?publish_start=2026-08-01&publish_end=2026-08-31&limit=20
```

3. Answer based on `publish_time`.
4. Do not answer from `/events?month=2026-08`.

Correct reasoning:

- `/events?month=2026-08` means event records bucketed into August.
- `/posts?publish_start=2026-08-01&publish_end=2026-08-31` means FB posts actually published in August.

## Response Guidance

When answering users, prefer:

- game name
- endpoint semantics used
- actual dates when discussing posts
- `month_bucket` only when discussing events

Avoid saying "there are no posts in August" unless `/api/events/v2/games/{id}/posts` with August `publish_start` / `publish_end` returned no results.
