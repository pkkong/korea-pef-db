#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$SERVICE_ROOT/../.." && pwd)"

cd "$REPO_ROOT"

REPORT_DATE="${NEWSLETTER_REPORT_DATE:-$(TZ=Asia/Seoul date +%F)}"
PUBLIC_REPO_URL="${NEWSLETTER_PUBLIC_REPO_URL:-https://github.com/pkkong/kpef-newsletter.git}"
PUBLIC_BRANCH="${NEWSLETTER_PUBLIC_BRANCH:-main}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
LIMIT_PER_SOURCE="${NEWSLETTER_LOCAL_LIMIT_PER_SOURCE:-30}"
BRIEF_LIMIT="${NEWSLETTER_LOCAL_BRIEF_LIMIT:-30}"
REVIEW_LIMIT="${NEWSLETTER_LOCAL_REVIEW_LIMIT:-80}"
LP_MONITOR_DAYS="${NEWSLETTER_LP_MONITOR_DAYS:-180}"
LP_LIMIT_PER_SOURCE="${NEWSLETTER_LP_LIMIT_PER_SOURCE:-50}"
ARCHIVE_LIMIT="${NEWSLETTER_ARCHIVE_LIMIT:-30}"
NO_PUSH=0
SKIP_GENERATE=0

usage() {
  cat <<'USAGE'
Usage: services/newsletter/scripts/publish_newsletter_pages_local.sh [options]

Options:
  --date YYYY-MM-DD    Report date. Defaults to today's date in Asia/Seoul.
  --no-push            Build and validate, but do not push the public mirror.
  --skip-generate      Publish the existing services/newsletter/deploy/site bundle.
  -h, --help           Show this help.

Environment overrides:
  NEWSLETTER_PUBLIC_REPO_URL, NEWSLETTER_PUBLIC_BRANCH, PYTHON_BIN
  NEWSLETTER_LOCAL_LIMIT_PER_SOURCE, NEWSLETTER_LOCAL_BRIEF_LIMIT
  NEWSLETTER_LOCAL_REVIEW_LIMIT, NEWSLETTER_LP_MONITOR_DAYS
  NEWSLETTER_LP_LIMIT_PER_SOURCE, NEWSLETTER_ARCHIVE_LIMIT
USAGE
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --date)
      REPORT_DATE="${2:?--date requires YYYY-MM-DD}"
      shift 2
      ;;
    --no-push)
      NO_PUSH=1
      shift
      ;;
    --skip-generate)
      SKIP_GENERATE=1
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

LOG_DIR="$REPO_ROOT/exports/daily_news/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/newsletter_local_publish_${REPORT_DATE}_$(date +%Y%m%d_%H%M%S).log"
exec > >(tee -a "$LOG_FILE") 2>&1

echo "newsletter_local_publish_start=$(date -u +%FT%TZ)"
echo "repo_root=$REPO_ROOT"
echo "report_date=$REPORT_DATE"
echo "public_repo_url=$PUBLIC_REPO_URL"
echo "public_branch=$PUBLIC_BRANCH"
echo "log_file=$LOG_FILE"

if [ -f "$REPO_ROOT/config/daily_news.env" ]; then
  set -a
  # shellcheck disable=SC1091
  . "$REPO_ROOT/config/daily_news.env"
  set +a
fi

google_date_args=()
if [ "${NEWSLETTER_GOOGLE_DATE_WINDOW:-1}" != "0" ]; then
  google_date_args=(--google-date-window)
fi

if [ "$SKIP_GENERATE" -eq 0 ]; then
  "$PYTHON_BIN" services/newsletter/src/run_daily_news_pipeline.py \
    --date "$REPORT_DATE" \
    --limit-per-source "$LIMIT_PER_SOURCE" \
    --brief-limit "$BRIEF_LIMIT" \
    --review-limit "$REVIEW_LIMIT" \
    --allow-insecure-ssl \
    "${google_date_args[@]}"

  "$PYTHON_BIN" services/newsletter/src/build_newsletter_source_audit.py \
    --date "$REPORT_DATE"

  "$PYTHON_BIN" services/lp/src/build_lp_commitment_monitor.py \
    --date "$REPORT_DATE" \
    --days "$LP_MONITOR_DAYS" \
    --limit-per-source "$LP_LIMIT_PER_SOURCE" \
    --allow-insecure-ssl

  "$PYTHON_BIN" services/newsletter/src/validate_daily_news_pipeline.py \
    --date "$REPORT_DATE"

  "$PYTHON_BIN" services/newsletter/src/build_newsletter_deploy.py \
    --date "$REPORT_DATE" \
    --archive-limit "$ARCHIVE_LIMIT"
fi

"$PYTHON_BIN" - "$REPORT_DATE" <<'PY'
import json
import sys
from pathlib import Path

report_date = sys.argv[1]
site = Path("services/newsletter/deploy/site")
required = ["index.html", "daily-news.html", "archive.json", "health.json", ".nojekyll"]
missing = [name for name in required if not (site / name).exists()]
if missing:
    raise SystemExit(f"Missing deploy files: {', '.join(missing)}")

health = json.loads((site / "health.json").read_text(encoding="utf-8"))
print(json.dumps(health, ensure_ascii=False, indent=2))
if health.get("report_date") != report_date:
    raise SystemExit(f"health.json report_date is {health.get('report_date')}, expected {report_date}")
if int(health.get("article_count") or 0) <= 0:
    raise SystemExit("article_count is 0; refusing to publish an empty newsletter")
if int(health.get("lp_monitor_count") or 0) <= 0:
    print("WARNING: lp_monitor_count is 0; publishing can continue because LP monitor is not the core newsletter.")

archive = json.loads((site / "archive.json").read_text(encoding="utf-8"))
if not isinstance(archive, list) or not archive:
    raise SystemExit("archive.json is empty or invalid")
print(f"archive_count={len(archive)}")
PY

SITE_DIR="$REPO_ROOT/services/newsletter/deploy/site"
TEMP_ROOT="$(mktemp -d)"
trap 'rm -rf "$TEMP_ROOT"' EXIT
MIRROR_DIR="$TEMP_ROOT/kpef-newsletter"

git clone --depth 1 --branch "$PUBLIC_BRANCH" "$PUBLIC_REPO_URL" "$MIRROR_DIR"
find "$MIRROR_DIR" -mindepth 1 -maxdepth 1 ! -name .git -exec rm -rf {} +
cp -R "$SITE_DIR"/. "$MIRROR_DIR"/
touch "$MIRROR_DIR/.nojekyll"

cd "$MIRROR_DIR"
git config user.name "${NEWSLETTER_GIT_USER_NAME:-kpef-local-publisher}"
git config user.email "${NEWSLETTER_GIT_USER_EMAIL:-41898282+github-actions[bot]@users.noreply.github.com}"
git add -A

if git diff --cached --quiet; then
  echo "public_mirror_status=no_changes"
  exit 0
fi

git status --short

if [ "$NO_PUSH" -eq 1 ]; then
  git diff --cached --stat
  echo "public_mirror_status=changes_ready_no_push"
  exit 0
fi

git commit -m "Deploy newsletter $REPORT_DATE from local Mac"
git push origin "$PUBLIC_BRANCH"
echo "public_mirror_status=pushed"
echo "public_url=https://pkkong.github.io/kpef-newsletter/"
echo "newsletter_local_publish_finish=$(date -u +%FT%TZ)"
