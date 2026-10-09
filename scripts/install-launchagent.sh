#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PLIST="$HOME/Library/LaunchAgents/com.trevor.bike-angels-sf.plist"
PYTHON="$ROOT/.venv/bin/python"
LOG_DIR="$ROOT/data"
mkdir -p "$LOG_DIR"

if [[ ! -x "$PYTHON" ]]; then
  echo "Create the venv first: python3 -m venv .venv && source .venv/bin/activate && pip install -e ."
  exit 1
fi

cat >"$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.trevor.bike-angels-sf</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PYTHON</string>
    <string>-m</string>
    <string>bike_angels.cli</string>
    <string>collect</string>
  </array>
  <key>WorkingDirectory</key>
  <string>$ROOT</string>
  <key>StartInterval</key>
  <integer>300</integer>
  <key>RunAtLoad</key>
  <true/>
  <key>StandardOutPath</key>
  <string>$LOG_DIR/launchd.out.log</string>
  <key>StandardErrorPath</key>
  <string>$LOG_DIR/launchd.err.log</string>
</dict>
</plist>
EOF

launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"
echo "Installed and loaded: $PLIST"
echo "Logs: $LOG_DIR/launchd.*.log"
