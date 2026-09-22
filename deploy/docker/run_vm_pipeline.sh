#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"

COMPOSE_FILE="${REPO_ROOT}/deploy/docker/docker-compose.yml"
VM_ENV_FILE="${REPO_ROOT}/deploy/docker/vm.env"
PIPELINE_ENV_FILE="${REPO_ROOT}/deploy/docker/pipeline.env"

timestamp() {
  date -u +"%Y-%m-%dT%H:%M:%SZ"
}

log() {
  echo "[$(timestamp)] $*"
}

# `set -e` normally exits immediately on a failed pipeline step. Emit a final,
# machine-readable status first so operational reporting never mislabels a
# failed run as still running.
current_step="initializing"
on_pipeline_error() {
  local exit_code=$?
  trap - ERR
  log "vm_pipeline_failed exit_code=${exit_code} step=${current_step}"
  exit "${exit_code}"
}

trap on_pipeline_error ERR

require_file() {
  local path="$1"
  if [[ ! -f "${path}" ]]; then
    log "missing required file: ${path}"
    exit 1
  fi
}

load_env_defaults() {
  local path="$1"
  local line
  local key
  local value

  while IFS= read -r line || [[ -n "${line}" ]]; do
    [[ -n "${line//[[:space:]]/}" ]] || continue
    [[ "${line}" =~ ^[[:space:]]*# ]] && continue
    [[ "${line}" == *=* ]] || continue
    key="${line%%=*}"
    value="${line#*=}"
    key="${key#"${key%%[![:space:]]*}"}"
    key="${key%"${key##*[![:space:]]}"}"
    if [[ -z "${!key+x}" ]]; then
      export "${key}=${value}"
    fi
  done < "${path}"
}

compose() {
  docker compose --env-file "${VM_ENV_FILE}" -f "${COMPOSE_FILE}" "$@"
}

run_job() {
  current_step="$*"
  log "job_start: ${current_step}"
  compose --profile ops run --rm --no-deps job "$@"
  log "job_done: ${current_step}"
  current_step="idle"
}

run_job_python() {
  local description="$1"
  shift
  current_step="${description}"
  log "job_start: ${current_step}"
  compose --profile ops run --rm --no-deps job python "$@"
  log "job_done: ${current_step}"
  current_step="idle"
}

resolve_months() {
  if [[ -n "${PIPELINE_UNIFIED_MONTHS}" ]]; then
    IFS=',' read -r -a requested_months <<< "${PIPELINE_UNIFIED_MONTHS}"
    printf '%s\n' "${requested_months[@]}" | sed '/^[[:space:]]*$/d' | awk '{$1=$1; print}'
    return
  fi

  local current_month
  local previous_month
  current_month="$(date -u +%Y-%m)"
  previous_month="$(date -u -d "$(date -u +%Y-%m-01) -1 day" +%Y-%m)"
  if [[ "${previous_month}" == "${current_month}" ]]; then
    printf '%s\n' "${current_month}"
    return
  fi
  printf '%s\n%s\n' "${previous_month}" "${current_month}"
}

wait_for_api_healthy() {
  local timeout_seconds="$1"
  local started_at
  local container_id
  local status

  started_at="$(date +%s)"
  while true; do
    container_id="$(compose ps -q api)"
    if [[ -n "${container_id}" ]]; then
      status="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "${container_id}" 2>/dev/null || true)"
      if [[ "${status}" == "healthy" ]]; then
        log "api_health_check_passed container_id=${container_id}"
        return 0
      fi
    else
      status="missing"
    fi

    if (( "$(date +%s)" - started_at >= timeout_seconds )); then
      log "api_health_check_failed status=${status} timeout_seconds=${timeout_seconds}"
      compose ps
      return 1
    fi

    log "api_health_waiting status=${status} timeout_seconds=${timeout_seconds}"
    sleep 5
  done
}

verify_db_state() {
  local db_path="$1"
  shift
  run_job_python "verify_db_state" -c '
import json
import sqlite3
import sys

db_path = sys.argv[1]
months = sys.argv[2:]

conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row

raw_row = conn.execute("""
SELECT
  MAX(publish_time) AS latest_publish_time,
  MAX(ingested_at) AS latest_ingested_at,
  COUNT(*) AS raw_fb_post_rows
FROM raw_fb_posts
""").fetchone()

month_rows = conn.execute(f"""
SELECT
  ue.month_bucket,
  COUNT(*) AS unified_event_count,
  COUNT(DISTINCT CASE WHEN ues.source_type = '"'"'fb_post'"'"' THEN ue.unified_event_id END) AS fb_backed_event_count,
  COUNT(DISTINCT CASE WHEN ues.source_type = '"'"'fb_post'"'"' THEN ues.source_id END) AS linked_fb_post_count,
  MAX(CASE WHEN ues.source_type = '"'"'fb_post'"'"' THEN fb.publish_time END) AS latest_linked_fb_publish_time
FROM unified_events ue
LEFT JOIN unified_event_sources ues
  ON ues.unified_event_id = ue.unified_event_id
LEFT JOIN raw_fb_posts fb
  ON fb.source_post_id = ues.source_id
 AND ues.source_type = '"'"'fb_post'"'"'
WHERE ue.month_bucket IN ({",".join("?" for _ in months)})
GROUP BY ue.month_bucket
ORDER BY ue.month_bucket
""", months).fetchall()

summary = {
    "latest_publish_time": raw_row["latest_publish_time"],
    "latest_ingested_at": raw_row["latest_ingested_at"],
    "raw_fb_post_rows": int(raw_row["raw_fb_post_rows"] or 0),
    "months": [dict(row) for row in month_rows],
}

available_months = {str(row["month_bucket"]) for row in month_rows}
missing_months = [month for month in months if month not in available_months]
empty_months = [str(row["month_bucket"]) for row in month_rows if int(row["unified_event_count"] or 0) <= 0]

print("db_verification_summary")
print(json.dumps(summary, ensure_ascii=False, indent=2))

if int(raw_row["raw_fb_post_rows"] or 0) <= 0:
    raise SystemExit("raw_fb_posts is empty")
if raw_row["latest_publish_time"] is None:
    raise SystemExit("raw_fb_posts has no publish_time")
if missing_months:
    raise SystemExit(f"missing unified_events month buckets: {missing_months}")
if empty_months:
    raise SystemExit(f"empty unified_events month buckets: {empty_months}")
' "${db_path}" "$@"
}

require_file "${VM_ENV_FILE}"
require_file "${PIPELINE_ENV_FILE}"
load_env_defaults "${VM_ENV_FILE}"
load_env_defaults "${PIPELINE_ENV_FILE}"

DB_PATH="${DB_PATH:-/app/data/warehouse.db}"
CONFIG_PATH="${CONFIG_PATH:-/app/examples/config.json}"
SOCIALDATA_SYNC_LOOKBACK_DAYS="${SOCIALDATA_SYNC_LOOKBACK_DAYS:-10}"
SENSORTOWER_SYNC_LOOKBACK_DAYS="${SENSORTOWER_SYNC_LOOKBACK_DAYS:-3}"
PIPELINE_RESTART_API="${PIPELINE_RESTART_API:-1}"
PIPELINE_UNIFIED_MONTHS="${PIPELINE_UNIFIED_MONTHS:-}"
PIPELINE_VERIFY_API="${PIPELINE_VERIFY_API:-1}"
PIPELINE_VERIFY_DB="${PIPELINE_VERIFY_DB:-1}"
PIPELINE_API_HEALTH_TIMEOUT_SECONDS="${PIPELINE_API_HEALTH_TIMEOUT_SECONDS:-180}"

mapfile -t TARGET_MONTHS < <(resolve_months)

log "vm_pipeline_started repo_root=${REPO_ROOT}"
log "pipeline_config db_path=${DB_PATH} config_path=${CONFIG_PATH} socialdata_lookback_days=${SOCIALDATA_SYNC_LOOKBACK_DAYS} sensortower_lookback_days=${SENSORTOWER_SYNC_LOOKBACK_DAYS} target_months=$(IFS=,; echo "${TARGET_MONTHS[*]}")"

run_job vn-event-dw sync-socialdata-posts \
  --db "${DB_PATH}" \
  --config "${CONFIG_PATH}" \
  --lookback-days "${SOCIALDATA_SYNC_LOOKBACK_DAYS}"

run_job vn-event-dw sync-sensortower-raw \
  --config "${CONFIG_PATH}" \
  --lookback-days "${SENSORTOWER_SYNC_LOOKBACK_DAYS}"

run_job vn-event-dw load-sensortower-raw \
  --db "${DB_PATH}"

for month in "${TARGET_MONTHS[@]}"; do
  [[ -n "${month}" ]] || continue
  run_job vn-event-dw build-unified-events-llm \
    --db "${DB_PATH}" \
    --month "${month}"
done

if [[ "${PIPELINE_RESTART_API}" == "1" ]]; then
  current_step="restart API"
  log "api_restart_started"
  compose restart api
  log "api_restart_completed"
  current_step="idle"
fi

if [[ "${PIPELINE_VERIFY_API}" == "1" ]]; then
  current_step="verify API health"
  wait_for_api_healthy "${PIPELINE_API_HEALTH_TIMEOUT_SECONDS}"
  current_step="idle"
fi

if [[ "${PIPELINE_VERIFY_DB}" == "1" ]]; then
  current_step="verify database state"
  verify_db_state "${DB_PATH}" "${TARGET_MONTHS[@]}"
  current_step="idle"
fi

log "vm_pipeline_completed"
