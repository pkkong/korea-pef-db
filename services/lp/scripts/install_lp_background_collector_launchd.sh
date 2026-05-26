#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$SERVICE_ROOT/../.." && pwd)"

LABEL="${LP_COLLECTOR_LAUNCHD_LABEL:-com.kpef.lp.background-collector}"
INTERVAL_HOURS="${LP_COLLECTOR_INTERVAL_HOURS:-6}"
RUN_NOW=0
UNINSTALL=0

usage() {
  cat <<'USAGE'
Usage: services/lp/scripts/install_lp_background_collector_launchd.sh [options]

Options:
  --interval-hours N  Run every N hours. Default: 6.
  --run-now           Start one run immediately after installing.
  --uninstall         Remove the launchd job.
  -h, --help          Show this help.
USAGE
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --interval-hours)
      INTERVAL_HOURS="${2:?--interval-hours requires a value}"
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

if ! [[ "$INTERVAL_HOURS" =~ ^[0-9]+$ ]] || [ "$INTERVAL_HOURS" -lt 1 ]; then
  echo "--interval-hours must be a positive integer" >&2
  exit 2
fi

PLIST_DIR="$HOME/Library/LaunchAgents"
PLIST_PATH="$PLIST_DIR/$LABEL.plist"
RUNNER="$SERVICE_ROOT/scripts/run_lp_background_collector.sh"
LOG_DIR="$REPO_ROOT/exports/lp/logs"
START_INTERVAL=$((INTERVAL_HOURS * 3600))
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
  <key>StartInterval</key>
  <integer>$START_INTERVAL</integer>
  <key>StandardOutPath</key>
  <string>$LOG_DIR/launchd-lp-background-collector.out.log</string>
  <key>StandardErrorPath</key>
  <string>$LOG_DIR/launchd-lp-background-collector.err.log</string>
  <key>RunAtLoad</key>
  <false/>
</dict>
</plist>
PLIST

plutil -lint "$PLIST_PATH" >/dev/null
launchctl bootout "gui/$(id -u)" "$PLIST_PATH" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST_PATH"
launchctl enable "gui/$(id -u)/$LABEL"

echo "Installed $LABEL every $INTERVAL_HOURS hours."
echo "Plist: $PLIST_PATH"

if [ "$RUN_NOW" -eq 1 ]; then
  launchctl kickstart -k "gui/$(id -u)/$LABEL"
  echo "Started one run now."
fi
