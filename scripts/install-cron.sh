#!/usr/bin/env bash
# Install a user crontab entry that collects every 15 minutes for ~2 weeks.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BIN="$ROOT/.venv/bin/bike-angels"
LOG="$ROOT/data/cron.log"
MARKER="# bike-angels-sf"

if [[ ! -x "$BIN" ]]; then
  echo "Missing $BIN — run scripts/setup-vps.sh first."
  exit 1
fi

mkdir -p "$ROOT/data"
touch "$LOG"

# +2 min after Lyft's :00/:15/:30/:45 points refresh — settled points, little dock churn.
CRON_LINE="2,17,32,47 * * * * cd $ROOT && $BIN collect >> $LOG 2>&1 $MARKER"

# Remove any previous marker line, then append.
EXISTING="$(crontab -l 2>/dev/null || true)"
FILTERED="$(printf '%s\n' "$EXISTING" | grep -v "$MARKER" || true)"
{
  printf '%s\n' "$FILTERED"
  printf '%s\n' "$CRON_LINE"
} | crontab -

echo "Installed crontab:"
crontab -l | grep "$MARKER" || true
echo
echo "Logs: $LOG"
echo "Status: $BIN status"
echo "To remove later: crontab -e  (delete the bike-angels-sf line)"
