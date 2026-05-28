#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$SERVICE_ROOT/../.." && pwd)"

LABEL="${DATA_REFRESH_LAUNCHD_LABEL:-com.kpef.data.nightly-refresh}"
HOUR="${DATA_REFRESH_HOUR:-1}"
MINUTE="${DATA_REFRESH_MINUTE:-30}"
RUN_NOW=0
UNINSTALL=0

usage() {
  cat <<'USAGE'
Usage: services/ops/scripts/install_data_nightly_refresh_launchd.sh [options]

Options:
  --hour H       Hour in local time, 0-23. Default: 1.
  --minute M     Minute in local time, 0-59. Default: 30.
  --run-now      Start one run immediately after installing.
  --uninstall    Remove the launchd job.
  -h, --help     Show this help.
USAGE
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --hour)
      HOUR="${2:?--hour requires 0-23}"
      shift 2
      ;;
    --minute)
      MINUTE="${2:?--minute requires 0-59}"
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

if ! [[ "$HOUR" =~ ^[0-9]+$ ]] || [ "$HOUR" -lt 0 ] || [ "$HOUR" -gt 23 ]; then
  echo "--hour must be an integer from 0 to 23" >&2
  exit 2
fi
if ! [[ "$MINUTE" =~ ^[0-9]+$ ]] || [ "$MINUTE" -lt 0 ] || [ "$MINUTE" -gt 59 ]; then
  echo "--minute must be an integer from 0 to 59" >&2
  exit 2
fi

PLIST_DIR="$HOME/Library/LaunchAgents"
PLIST_PATH="$PLIST_DIR/$LABEL.plist"
RUNNER="$SERVICE_ROOT/scripts/run_data_nightly_refresh.sh"
LOG_DIR="$REPO_ROOT/exports/ops/logs"
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
  <string>$LOG_DIR/launchd-data-nightly-refresh.out.log</string>
  <key>StandardErrorPath</key>
  <string>$LOG_DIR/launchd-data-nightly-refresh.err.log</string>
  <key>RunAtLoad</key>
  <false/>
</dict>
</plist>
PLIST

plutil -lint "$PLIST_PATH" >/dev/null
launchctl bootout "gui/$(id -u)" "$PLIST_PATH" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST_PATH"
launchctl enable "gui/$(id -u)/$LABEL"

echo "Installed $LABEL at ${HOUR}:$(printf '%02d' "$MINUTE") local time."
echo "Plist: $PLIST_PATH"

if [ "$RUN_NOW" -eq 1 ]; then
  launchctl kickstart -k "gui/$(id -u)/$LABEL"
  echo "Started one run now."
fi
