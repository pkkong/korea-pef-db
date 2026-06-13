#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$SERVICE_ROOT/../.." && pwd)"

cd "$REPO_ROOT"

TODAY="$(TZ=Asia/Seoul date +%F)"
REPORT_DATE="${DATA_REFRESH_REPORT_DATE:-$TODAY}"
SITE_DATE="${DATA_REFRESH_SITE_DATE:-}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
LP_MONITOR_DAYS="${DATA_REFRESH_LP_MONITOR_DAYS:-365}"
LP_LIMIT_PER_SOURCE="${DATA_REFRESH_LP_LIMIT_PER_SOURCE:-80}"
GP_PROFILE_LIMIT="${DATA_REFRESH_GP_PROFILE_LIMIT:-120}"
ARCHIVE_LIMIT="${NEWSLETTER_ARCHIVE_LIMIT:-30}"
LOCK_DIR="$REPO_ROOT/exports/ops/data-nightly-refresh.lock"

usage() {
  cat <<'USAGE'
Usage: services/ops/scripts/run_data_nightly_refresh.sh [options]

Options:
  --date YYYY-MM-DD       Data refresh date. Defaults to today's date in Asia/Seoul.
  --site-date YYYY-MM-DD  Newsletter site date to rebuild. Defaults to latest local brief date.
  --publish               Disabled. Publishing runs only in GitHub Actions.
  -h, --help              Show this help.

Environment overrides:
  DATA_REFRESH_REPORT_DATE, DATA_REFRESH_SITE_DATE
  DATA_REFRESH_LP_MONITOR_DAYS, DATA_REFRESH_LP_LIMIT_PER_SOURCE
  DATA_REFRESH_GP_PROFILE_LIMIT, NEWSLETTER_ARCHIVE_LIMIT, PYTHON_BIN
USAGE
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --date)
      REPORT_DATE="${2:?--date requires YYYY-MM-DD}"
      shift 2
      ;;
    --site-date)
      SITE_DATE="${2:?--site-date requires YYYY-MM-DD}"
      shift 2
      ;;
    --publish)
      echo "Local publishing is disabled. Use the GitHub Actions workflow instead." >&2
      exit 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  echo "Another data refresh is already running: $LOCK_DIR" >&2
  exit 75
fi
trap 'rmdir "$LOCK_DIR"' EXIT

if [ -z "$SITE_DATE" ]; then
  compact_report_date="${REPORT_DATE//-/}"
  if [ -f "$REPO_ROOT/exports/daily_news/daily_news_brief_${compact_report_date}.md" ]; then
    SITE_DATE="$REPORT_DATE"
  else
    latest_brief="$(find "$REPO_ROOT/exports/daily_news" -maxdepth 1 -name 'daily_news_brief_20*.md' -print | sort | tail -1 || true)"
    if [ -z "$latest_brief" ]; then
      SITE_DATE="$REPORT_DATE"
    else
      latest_name="$(basename "$latest_brief")"
      latest_compact="${latest_name#daily_news_brief_}"
      latest_compact="${latest_compact%.md}"
      SITE_DATE="${latest_compact:0:4}-${latest_compact:4:2}-${latest_compact:6:2}"
    fi
  fi
fi

LOG_DIR="$REPO_ROOT/exports/ops/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/data_nightly_refresh_${REPORT_DATE}_$(date +%Y%m%d_%H%M%S).log"
exec > >(tee -a "$LOG_FILE") 2>&1

echo "data_nightly_refresh_start=$(date -u +%FT%TZ)"
echo "repo_root=$REPO_ROOT"
echo "report_date=$REPORT_DATE"
echo "site_date=$SITE_DATE"
echo "log_file=$LOG_FILE"

"$PYTHON_BIN" scripts/run_pipeline.py \
  --lp-monitor-days "$LP_MONITOR_DAYS" \
  --lp-monitor-limit-per-source "$LP_LIMIT_PER_SOURCE" \
  --gp-profile-limit "$GP_PROFILE_LIMIT"

"$PYTHON_BIN" services/lp/src/build_lp_profile_backlog.py \
  --date "$REPORT_DATE"

"$PYTHON_BIN" scripts/build_site_bundle.py \
  --date "$SITE_DATE" \
  --archive-limit "$ARCHIVE_LIMIT" \
  --services newsletter,lp,gp

echo "data_nightly_refresh_finish=$(date -u +%FT%TZ)"
