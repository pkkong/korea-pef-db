#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$SERVICE_ROOT/../.." && pwd)"

cd "$REPO_ROOT"

REPORT_DATE="${NEWSLETTER_REPORT_DATE:-$(TZ=Asia/Seoul date +%F)}"
PUBLIC_REPO_URL="${NEWSLETTER_PUBLIC_REPO_URL:-https://github.com/pkkong/kpef-newsletter.git}"
PUBLIC_BRANCH="${NEWSLETTER_PUBLIC_BRANCH:-gh-pages}"
PUBLIC_BASE_URL="${NEWSLETTER_PUBLIC_BASE_URL:-https://pkkong.github.io/kpef-newsletter}"
PUBLIC_VERIFY_TIMEOUT_SECONDS="${NEWSLETTER_PUBLIC_VERIFY_TIMEOUT_SECONDS:-180}"
PUBLIC_VERIFY_INTERVAL_SECONDS="${NEWSLETTER_PUBLIC_VERIFY_INTERVAL_SECONDS:-10}"
STRICT_ICON_CHECK="${NEWSLETTER_STRICT_ICON_CHECK:-0}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
LIMIT_PER_SOURCE="${NEWSLETTER_LOCAL_LIMIT_PER_SOURCE:-50}"
BRIEF_LIMIT="${NEWSLETTER_LOCAL_BRIEF_LIMIT:-30}"
REVIEW_LIMIT="${NEWSLETTER_LOCAL_REVIEW_LIMIT:-80}"
LP_MONITOR_DAYS="${NEWSLETTER_LP_MONITOR_DAYS:-180}"
LP_LIMIT_PER_SOURCE="${NEWSLETTER_LP_LIMIT_PER_SOURCE:-50}"
ARCHIVE_LIMIT="${NEWSLETTER_ARCHIVE_LIMIT:-30}"
BUILD_SERVICES="${NEWSLETTER_BUILD_SERVICES:-newsletter}"
AI_PROVIDER="${NEWSLETTER_AI_PROVIDER:-local}"
AI_STRICT="${NEWSLETTER_AI_STRICT:-0}"
AI_APPLY_SECTIONS="${NEWSLETTER_AI_APPLY_SECTIONS:-0}"
NO_PUSH=0
SKIP_GENERATE=0
TEMP_ROOT=""
BUILD_SERVICES_ARG=0

usage() {
  cat <<'USAGE'
Usage: services/newsletter/scripts/publish_newsletter_pages_local.sh [options]

Options:
  --date YYYY-MM-DD    Report date. Defaults to today's date in Asia/Seoul.
  --services LIST      Build services: newsletter,lp,gp or all. Wiki is explicit-only. Defaults to newsletter.
  --no-push            Build and validate, but do not push the public mirror.
  --skip-generate      Publish the existing services/newsletter/deploy/site bundle.
  -h, --help           Show this help.

Environment overrides:
  NEWSLETTER_PUBLIC_REPO_URL, NEWSLETTER_PUBLIC_BRANCH, NEWSLETTER_PUBLIC_BASE_URL
  NEWSLETTER_PUBLIC_VERIFY_TIMEOUT_SECONDS, NEWSLETTER_PUBLIC_VERIFY_INTERVAL_SECONDS, PYTHON_BIN
  NEWSLETTER_LOCAL_LIMIT_PER_SOURCE, NEWSLETTER_LOCAL_BRIEF_LIMIT
  NEWSLETTER_LOCAL_REVIEW_LIMIT, NEWSLETTER_LP_MONITOR_DAYS
  NEWSLETTER_LP_LIMIT_PER_SOURCE, NEWSLETTER_ARCHIVE_LIMIT
  NEWSLETTER_BUILD_SERVICES, NEWSLETTER_STRICT_ICON_CHECK
  NEWSLETTER_AI_PROVIDER, NEWSLETTER_AI_STRICT, NEWSLETTER_AI_APPLY_SECTIONS
  NEWSLETTER_NOTEBOOKLM_NOTEBOOK_ID, NEWSLETTER_AI_COMMAND
USAGE
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --date)
      REPORT_DATE="${2:?--date requires YYYY-MM-DD}"
      shift 2
      ;;
    --services)
      BUILD_SERVICES="${2:?--services requires a comma-separated service list}"
      BUILD_SERVICES_ARG=1
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

write_ops_status_on_exit() {
  local status="$?"
  if [ "$NO_PUSH" -eq 1 ]; then
    "$PYTHON_BIN" "$REPO_ROOT/services/newsletter/src/newsletter_ops_status.py" \
      --date "$REPORT_DATE" \
      --site-dir "$REPO_ROOT/services/newsletter/deploy/site" \
      --public-base-url "$PUBLIC_BASE_URL" \
      --publish-exit-code "$status" \
      --log-file "$LOG_FILE" \
      --no-public || true
  else
    "$PYTHON_BIN" "$REPO_ROOT/services/newsletter/src/newsletter_ops_status.py" \
      --date "$REPORT_DATE" \
      --site-dir "$REPO_ROOT/services/newsletter/deploy/site" \
      --public-base-url "$PUBLIC_BASE_URL" \
      --publish-exit-code "$status" \
      --log-file "$LOG_FILE" || true
  fi
  if [ -n "$TEMP_ROOT" ] && [ -d "$TEMP_ROOT" ]; then
    rm -rf "$TEMP_ROOT"
  fi
  exit "$status"
}
trap write_ops_status_on_exit EXIT

if [ -f "$REPO_ROOT/config/daily_news.env" ]; then
  set -a
  # shellcheck disable=SC1091
  . "$REPO_ROOT/config/daily_news.env"
  set +a
fi

PUBLIC_REPO_URL="${NEWSLETTER_PUBLIC_REPO_URL:-$PUBLIC_REPO_URL}"
PUBLIC_BRANCH="${NEWSLETTER_PUBLIC_BRANCH:-$PUBLIC_BRANCH}"
PUBLIC_BASE_URL="${NEWSLETTER_PUBLIC_BASE_URL:-$PUBLIC_BASE_URL}"
PUBLIC_VERIFY_TIMEOUT_SECONDS="${NEWSLETTER_PUBLIC_VERIFY_TIMEOUT_SECONDS:-$PUBLIC_VERIFY_TIMEOUT_SECONDS}"
PUBLIC_VERIFY_INTERVAL_SECONDS="${NEWSLETTER_PUBLIC_VERIFY_INTERVAL_SECONDS:-$PUBLIC_VERIFY_INTERVAL_SECONDS}"
STRICT_ICON_CHECK="${NEWSLETTER_STRICT_ICON_CHECK:-$STRICT_ICON_CHECK}"
LIMIT_PER_SOURCE="${NEWSLETTER_LOCAL_LIMIT_PER_SOURCE:-$LIMIT_PER_SOURCE}"
BRIEF_LIMIT="${NEWSLETTER_LOCAL_BRIEF_LIMIT:-$BRIEF_LIMIT}"
REVIEW_LIMIT="${NEWSLETTER_LOCAL_REVIEW_LIMIT:-$REVIEW_LIMIT}"
LP_MONITOR_DAYS="${NEWSLETTER_LP_MONITOR_DAYS:-$LP_MONITOR_DAYS}"
LP_LIMIT_PER_SOURCE="${NEWSLETTER_LP_LIMIT_PER_SOURCE:-$LP_LIMIT_PER_SOURCE}"
ARCHIVE_LIMIT="${NEWSLETTER_ARCHIVE_LIMIT:-$ARCHIVE_LIMIT}"
if [ "$BUILD_SERVICES_ARG" -eq 0 ]; then
  BUILD_SERVICES="${NEWSLETTER_BUILD_SERVICES:-$BUILD_SERVICES}"
fi
AI_PROVIDER="${NEWSLETTER_AI_PROVIDER:-$AI_PROVIDER}"
AI_STRICT="${NEWSLETTER_AI_STRICT:-$AI_STRICT}"
AI_APPLY_SECTIONS="${NEWSLETTER_AI_APPLY_SECTIONS:-$AI_APPLY_SECTIONS}"

echo "newsletter_local_publish_start=$(date -u +%FT%TZ)"
echo "repo_root=$REPO_ROOT"
echo "report_date=$REPORT_DATE"
echo "public_repo_url=$PUBLIC_REPO_URL"
echo "public_branch=$PUBLIC_BRANCH"
echo "public_base_url=$PUBLIC_BASE_URL"
echo "build_services=$BUILD_SERVICES"
echo "strict_icon_check=$STRICT_ICON_CHECK"
echo "ai_provider=$AI_PROVIDER"
echo "ai_strict=$AI_STRICT"
echo "ai_apply_sections=$AI_APPLY_SECTIONS"
echo "log_file=$LOG_FILE"

export NEWSLETTER_AI_APPLY_SECTIONS="$AI_APPLY_SECTIONS"

google_date_args=()
if [ "${NEWSLETTER_GOOGLE_DATE_WINDOW:-1}" != "0" ]; then
  google_date_args=(--google-date-window)
fi

normalized_services="${BUILD_SERVICES//[[:space:]]/}"
service_selected() {
  local service="$1"
  case ",$normalized_services," in
    *,all,*|*,"$service",*) return 0 ;;
    *) return 1 ;;
  esac
}

verify_public_site() {
  "$PYTHON_BIN" - "$REPORT_DATE" "$PUBLIC_BASE_URL" "$PUBLIC_VERIFY_TIMEOUT_SECONDS" "$PUBLIC_VERIFY_INTERVAL_SECONDS" <<'PY'
import json
import sys
import time
from urllib.error import URLError
from urllib.request import Request, urlopen

report_date, base_url, timeout_raw, interval_raw = sys.argv[1:5]
base_url = base_url.rstrip("/")
timeout = max(1, int(timeout_raw))
interval = max(1, int(interval_raw))
deadline = time.time() + timeout
last_error = ""

def fetch_json(path: str) -> object:
    bust = f"{int(time.time())}-{report_date}"
    req = Request(
        f"{base_url}/{path}?verify={bust}",
        headers={"Cache-Control": "no-cache", "Pragma": "no-cache"},
    )
    with urlopen(req, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))

while time.time() <= deadline:
    try:
        health = fetch_json("health.json")
        archive = fetch_json("archive.json")
        if not isinstance(health, dict):
            raise RuntimeError("public health.json is not an object")
        if str(health.get("report_date") or "") != report_date:
            raise RuntimeError(f"public health report_date={health.get('report_date')} expected={report_date}")
        article_count = int(health.get("article_count") or 0)
        if article_count <= 0:
            raise RuntimeError("public health article_count is 0")
        if not isinstance(archive, list):
            raise RuntimeError("public archive.json is not a list")
        entry = next((row for row in archive if isinstance(row, dict) and row.get("reportDate") == report_date), None)
        if entry is None:
            raise RuntimeError(f"public archive missing reportDate={report_date}")
        archive_count = len(entry.get("articles") or [])
        if archive_count <= 0:
            raise RuntimeError(f"public archive article_count is {archive_count}")
        print(f"public_verify_status=ok report_date={report_date} health_articles={article_count} archive_articles={archive_count}")
        sys.exit(0)
    except (RuntimeError, URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        last_error = str(exc)
        print(f"public_verify_wait={last_error}")
        time.sleep(interval)

raise SystemExit(f"public verification failed after {timeout}s: {last_error}")
PY
}

if [ "$SKIP_GENERATE" -eq 0 ]; then
  if service_selected newsletter; then
    "$PYTHON_BIN" services/newsletter/src/run_daily_news_pipeline.py \
      --date "$REPORT_DATE" \
      --limit-per-source "$LIMIT_PER_SOURCE" \
      --brief-limit "$BRIEF_LIMIT" \
      --review-limit "$REVIEW_LIMIT" \
      --allow-insecure-ssl \
      "${google_date_args[@]}"

    "$PYTHON_BIN" services/newsletter/src/build_newsletter_source_audit.py \
      --date "$REPORT_DATE"

    normalized_ai_provider="$(printf '%s' "$AI_PROVIDER" | tr '[:upper:]' '[:lower:]')"
    case "$normalized_ai_provider" in
      local|local-rule|fallback|off|none|0|false)
        ;;
      *)
        if ! "$PYTHON_BIN" services/newsletter/src/enrich_daily_news_ai.py \
          --date "$REPORT_DATE" \
          --provider "$AI_PROVIDER" \
          --check-only; then
          if [ "$AI_STRICT" = "1" ]; then
            echo "ai_enrichment_check=failed_strict provider=$AI_PROVIDER" >&2
            exit 1
          fi
          echo "WARNING: ai_enrichment_check_failed provider=$AI_PROVIDER; enrichment step may fall back to local-rule" >&2
        fi
        ;;
    esac

    if ! "$PYTHON_BIN" services/newsletter/src/enrich_daily_news_ai.py \
      --date "$REPORT_DATE" \
      --provider "$AI_PROVIDER"; then
      if [ "$AI_STRICT" = "1" ]; then
        echo "ai_enrichment_status=failed_strict provider=$AI_PROVIDER" >&2
        exit 1
      fi
      echo "WARNING: ai_enrichment_failed provider=$AI_PROVIDER; falling back to local-rule" >&2
      "$PYTHON_BIN" services/newsletter/src/enrich_daily_news_ai.py \
        --date "$REPORT_DATE" \
        --provider local
    fi
  fi

  if service_selected lp; then
    "$PYTHON_BIN" services/lp/src/build_lp_commitment_monitor.py \
      --date "$REPORT_DATE" \
      --days "$LP_MONITOR_DAYS" \
      --limit-per-source "$LP_LIMIT_PER_SOURCE" \
      --allow-insecure-ssl
  fi

  if service_selected newsletter; then
    "$PYTHON_BIN" services/newsletter/src/validate_daily_news_pipeline.py \
      --date "$REPORT_DATE"
  fi

  "$PYTHON_BIN" scripts/build_site_bundle.py \
    --date "$REPORT_DATE" \
    --archive-limit "$ARCHIVE_LIMIT" \
    --services "$BUILD_SERVICES"
fi

SITE_DIR="$REPO_ROOT/services/newsletter/deploy/site"

"$PYTHON_BIN" - "$REPORT_DATE" "$BUILD_SERVICES" <<'PY'
import json
import sys
from pathlib import Path

report_date = sys.argv[1]
requested_services = {
    part.strip().lower()
    for chunk in sys.argv[2].split(",")
    for part in chunk.split()
    if part.strip()
}
if not requested_services or "all" in requested_services:
    requested_services = {"newsletter", "lp", "gp"}

site = Path("services/newsletter/deploy/site")
required = {
    "index.html",
    "daily-news.html",
    "archive.json",
    "health.json",
    ".nojekyll",
    "assets/service.css",
    "assets/service.js",
    "apple-touch-icon.png",
}
if requested_services & {"lp", "gp", "wiki"}:
    required.update(
        {
            "db.html",
            "assets/app.css",
            "assets/app.js",
            "data/service_data.json",
        }
    )
if "lp" in requested_services:
    required.update(
        {
            "lp-notices.html",
            "lp-official-notices.html",
        }
    )
if "gp" in requested_services:
    required.update({"gps.html", "market.html"})

missing = [name for name in required if not (site / name).exists()]
if missing:
    raise SystemExit(f"Missing deploy files: {', '.join(missing)}")

health = json.loads((site / "health.json").read_text(encoding="utf-8"))
print(json.dumps(health, ensure_ascii=False, indent=2))
if health.get("report_date") != report_date:
    raise SystemExit(f"health.json report_date is {health.get('report_date')}, expected {report_date}")
if int(health.get("article_count") or 0) <= 0:
    raise SystemExit("article_count is 0; refusing to publish an empty newsletter")
if "lp" in requested_services and int(health.get("lp_monitor_count") or 0) <= 0:
    print("WARNING: lp_monitor_count is 0; publishing can continue because LP monitor is not the core newsletter.")

archive = json.loads((site / "archive.json").read_text(encoding="utf-8"))
if not isinstance(archive, list) or not archive:
    raise SystemExit("archive.json is empty or invalid")
print(f"archive_count={len(archive)}")
PY

"$PYTHON_BIN" services/newsletter/src/validate_daily_news_pipeline.py \
  --date "$REPORT_DATE" \
  --public-dir "$SITE_DIR" \
  --site-dir "$SITE_DIR"

icon_check_args=(
  services/newsletter/src/check_newsletter_brand_icons.py
  --site-dir "$SITE_DIR"
  --report-date "$REPORT_DATE"
)
if [ "$STRICT_ICON_CHECK" = "1" ]; then
  icon_check_args+=(--fail-on-missing)
fi
"$PYTHON_BIN" "${icon_check_args[@]}"

TEMP_ROOT="$(mktemp -d)"
MIRROR_DIR="$TEMP_ROOT/kpef-newsletter"

git clone --depth 1 --branch "$PUBLIC_BRANCH" "$PUBLIC_REPO_URL" "$MIRROR_DIR"
if service_selected lp || service_selected gp || service_selected wiki; then
  find "$MIRROR_DIR" -mindepth 1 -maxdepth 1 ! -name .git ! -name .github -exec rm -rf {} +
  cp -R "$SITE_DIR"/. "$MIRROR_DIR"/
else
  mkdir -p "$MIRROR_DIR/assets"
  for path in index.html daily-news.html archive.json health.json .nojekyll robots.txt 404.html site.webmanifest apple-touch-icon.png; do
    if [ -e "$SITE_DIR/$path" ]; then
      cp -R "$SITE_DIR/$path" "$MIRROR_DIR/$path"
    fi
  done
  cp "$SITE_DIR/assets/service.css" "$MIRROR_DIR/assets/service.css"
  cp "$SITE_DIR/assets/service.js" "$MIRROR_DIR/assets/service.js"
  if [ -d "$SITE_DIR/assets/brand-marks" ]; then
    rm -rf "$MIRROR_DIR/assets/brand-marks"
    cp -R "$SITE_DIR/assets/brand-marks" "$MIRROR_DIR/assets/brand-marks"
  fi
fi
touch "$MIRROR_DIR/.nojekyll"

cd "$MIRROR_DIR"
git config user.name "${NEWSLETTER_GIT_USER_NAME:-kpef-local-publisher}"
git config user.email "${NEWSLETTER_GIT_USER_EMAIL:-41898282+github-actions[bot]@users.noreply.github.com}"
git add -A

if git diff --cached --quiet; then
  echo "public_mirror_status=no_changes"
  verify_public_site
  echo "newsletter_local_publish_finish=$(date -u +%FT%TZ)"
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
echo "public_url=$PUBLIC_BASE_URL/"
verify_public_site
echo "newsletter_local_publish_finish=$(date -u +%FT%TZ)"
