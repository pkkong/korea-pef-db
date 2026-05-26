#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$SERVICE_ROOT/../.." && pwd)"

cd "$REPO_ROOT"

TODAY="$(TZ=Asia/Seoul date +%F)"
REPORT_DATE="${LP_COLLECTOR_REPORT_DATE:-$TODAY}"
SITE_DATE="${LP_COLLECTOR_SITE_DATE:-}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
LP_MONITOR_DAYS="${LP_COLLECTOR_DAYS:-365}"
LP_LIMIT_PER_SOURCE="${LP_COLLECTOR_LIMIT_PER_SOURCE:-80}"
ARCHIVE_LIMIT="${NEWSLETTER_ARCHIVE_LIMIT:-30}"
PUBLISH="${LP_COLLECTOR_PUBLISH:-1}"
NO_PUSH=0

usage() {
  cat <<'USAGE'
Usage: services/lp/scripts/run_lp_background_collector.sh [options]

Options:
  --date YYYY-MM-DD       Collection date. Defaults to today's date in Asia/Seoul.
  --site-date YYYY-MM-DD  Newsletter site date to rebuild. Defaults to latest local brief date.
  --no-push               Rebuild and validate public bundle, but do not push GitHub Pages.
  --no-publish            Refresh LP data and deploy bundle only.
  -h, --help              Show this help.

Environment overrides:
  LP_COLLECTOR_REPORT_DATE, LP_COLLECTOR_SITE_DATE, LP_COLLECTOR_DAYS
  LP_COLLECTOR_LIMIT_PER_SOURCE, LP_COLLECTOR_PUBLISH, PYTHON_BIN
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
    --no-push)
      NO_PUSH=1
      shift
      ;;
    --no-publish)
      PUBLISH=0
      shift
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

LOG_DIR="$REPO_ROOT/exports/lp/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/lp_background_collector_${REPORT_DATE}_$(date +%Y%m%d_%H%M%S).log"
exec > >(tee -a "$LOG_FILE") 2>&1

echo "lp_background_collector_start=$(date -u +%FT%TZ)"
echo "repo_root=$REPO_ROOT"
echo "report_date=$REPORT_DATE"
echo "site_date=$SITE_DATE"
echo "log_file=$LOG_FILE"

if [ -f "$REPO_ROOT/config/daily_news.env" ]; then
  set -a
  # shellcheck disable=SC1091
  . "$REPO_ROOT/config/daily_news.env"
  set +a
fi

"$PYTHON_BIN" services/lp/src/build_lp_commitment_monitor.py \
  --date "$REPORT_DATE" \
  --days "$LP_MONITOR_DAYS" \
  --limit-per-source "$LP_LIMIT_PER_SOURCE" \
  --allow-insecure-ssl

"$PYTHON_BIN" services/lp/src/build_lp_profile_backlog.py \
  --date "$REPORT_DATE"

"$PYTHON_BIN" services/newsletter/src/build_newsletter_deploy.py \
  --date "$SITE_DATE" \
  --archive-limit "$ARCHIVE_LIMIT"

if [ "$PUBLISH" = "1" ]; then
  publish_args=(--date "$SITE_DATE" --skip-generate)
  if [ "$NO_PUSH" -eq 1 ]; then
    publish_args+=(--no-push)
  fi
  services/newsletter/scripts/publish_newsletter_pages_local.sh "${publish_args[@]}"
fi

echo "lp_background_collector_finish=$(date -u +%FT%TZ)"
