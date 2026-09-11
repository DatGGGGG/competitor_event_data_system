# Event SQL Catalog

`src/vn_event_dw/sql_catalog.json` is the versioned business-semantics catalog
for the Event SQLite warehouse. It complements SQLite `PRAGMA table_info`,
which provides physical column names and types but not the grain, metric units,
join rules, or business meaning needed by analysts and query agents.

## Ownership And Scope

The Event data-system owns the catalog and must update it in the same change as
any warehouse schema change. The VN Market Data Portal is a consumer: it uses
the catalog for browsing, autocomplete, and generated query guidance, while it
continues to read the live SQLite schema for the physical source of truth.

The approved analyst objects are deliberately limited to:

- `config_app_mapping`
- `raw_fb_posts`
- `raw_st_app_update`
- `raw_st_version`
- `st_app_update_events`
- `st_version_events`
- `post_event_detection`
- `post_event_objects`
- `unified_events`
- `unified_event_sources`

Pipeline audit, internal matching, and LLM-cost tables are not part of the
analyst catalog. Supplier payload columns, `*_raw` columns, `source_file`, and
`*_payload` columns are metadata-only operational fields and must not be
exposed through the Portal query endpoint.

## Important Semantics

- `raw_fb_posts.publish_time` is the actual Facebook publication timestamp.
- `unified_events.month_bucket` is an event reporting bucket, not an FB post
  publication month.
- `unified_event_sources.source_id` is polymorphic. Always filter by
  `source_type` before joining it to a source table.
- `unified_event_sources.source_post_id` is populated only for `fb_post`
  lineage rows.
- Facebook metrics in `raw_fb_posts` are stored as text. Cast them to
  `INTEGER` before summing or comparing numeric values.
- Confidence fields are ratios on a `0_to_1` scale, not percentages.

## Validation

Run this after a schema/catalog change and before deploying the Portal:

```bash
vn-event-dw validate-sql-catalog --db data/warehouse.db
```

The validator checks all approved tables, every documented column, primary-key
grain columns, relationship columns, and each example SQL query. A malformed
or stale catalog fails this explicit command and the test suite; it is not
loaded by the public Event API, so it cannot prevent the API from starting.

For the VM containerized warehouse:

```bash
sudo docker compose --env-file deploy/docker/vm.env -f deploy/docker/docker-compose.yml \
  --profile ops run --rm --no-deps job \
  vn-event-dw validate-sql-catalog --db /app/data/warehouse.db
```

## Portal Consumer Contract

The Portal must set `EVENT_CATALOG_PATH` to the deployed file (the default VM
path is `/opt/vn_event_dw/vn_competitor_event_data_system/src/vn_event_dw/sql_catalog.json`).
It must keep its Event SQL allowlist equal to the approved-object list above,
apply the catalog only after checking `version: 1`, and enforce hidden-column
restrictions in the SQLite authorizer rather than relying on the UI alone.
