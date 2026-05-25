#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$SERVICE_ROOT/../.." && pwd)"

LABEL="${NEWSLETTER_LAUNCHD_LABEL:-com.kpef.newsletter.local-publish}"
HOUR="${NEWSLETTER_LAUNCHD_HOUR:-8}"
MINUTE="${NEWSLETTER_LAUNCHD_MINUTE:-30}"
RUN_NOW=0
UNINSTALL=0

usage() {
  cat <<'USAGE'
Usage: services/newsletter/scripts/install_newsletter_local_publisher_launchd.sh [options]

Options:
  --hour HOUR       Local macOS hour, 0-23. Default: 8.
  --minute MINUTE   Local macOS minute, 0-59. Default: 30.
  --run-now         Start one run immediately after installing.
  --uninstall       Remove the launchd job.
  -h, --help        Show this help.
USAGE
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --hour)
      HOUR="${2:?--hour requires a value}"
      shift 2
      ;;
    --minute)
      MINUTE="${2:?--minute requires a value}"
      shift 2
      ;;
    --run-now)
      RUN_NOW=1
      shift
      ;;
    --uninstall)
      UNINSTALL=1
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

PLIST_DIR="$HOME/Library/LaunchAgents"
PLIST_PATH="$PLIST_DIR/$LABEL.plist"
RUNNER="$SERVICE_ROOT/scripts/publish_newsletter_pages_local.sh"
LOG_DIR="$REPO_ROOT/exports/daily_news/logs"
mkdir -p "$PLIST_DIR" "$LOG_DIR"
chmod +x "$RUNNER"

if [ "$UNINSTALL" -eq 1 ]; then
  launchctl bootout "gui/$(id -u)" "$PLIST_PATH" 2>/dev/null || true
  rm -f "$PLIST_PATH"
  echo "Uninstalled $LABEL"
  exit 0
fi

cat > "$PLIST_PATH" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$RUNNER</string>
  </array>
  <key>WorkingDirectory</key>
  <string>$REPO_ROOT</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
  </dict>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key>
    <integer>$HOUR</integer>
    <key>Minute</key>
    <integer>$MINUTE</integer>
  </dict>
  <key>StandardOutPath</key>
  <string>$LOG_DIR/launchd-newsletter-local-publish.out.log</string>
  <key>StandardErrorPath</key>
  <string>$LOG_DIR/launchd-newsletter-local-publish.err.log</string>
  <key>RunAtLoad</key>
  <false/>
</dict>
</plist>
PLIST

plutil -lint "$PLIST_PATH" >/dev/null
launchctl bootout "gui/$(id -u)" "$PLIST_PATH" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST_PATH"
launchctl enable "gui/$(id -u)/$LABEL"

echo "Installed $LABEL at $(printf "%02d:%02d" "$HOUR" "$MINUTE") local time."
echo "Plist: $PLIST_PATH"

if [ "$RUN_NOW" -eq 1 ]; then
  launchctl kickstart -k "gui/$(id -u)/$LABEL"
  echo "Started one run now."
fi
