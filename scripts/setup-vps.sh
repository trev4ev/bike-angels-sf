#!/usr/bin/env bash
# One-shot bootstrap for an Ubuntu VPS (e.g. Google Cloud free e2-micro).
# Run from the cloned repo root:
#   bash scripts/setup-vps.sh
# Then authenticate and install cron:
#   source .venv/bin/activate
#   bike-angels login --phone +1XXXXXXXXXX
#   bike-angels probe
#   bash scripts/install-cron.sh

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "==> Installing system packages"
if command -v apt-get >/dev/null 2>&1; then
  sudo apt-get update -y
  sudo apt-get install -y python3 python3-venv python3-pip git
else
  echo "This script expects apt (Ubuntu/Debian)."
  exit 1
fi

echo "==> Creating virtualenv"
python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install -U pip setuptools wheel
pip install -e .

mkdir -p data
touch data/cron.log

echo
echo "Setup complete."
echo
echo "Next:"
echo "  source .venv/bin/activate"
echo "  bike-angels login --phone +1XXXXXXXXXX"
echo "  bike-angels probe"
echo "  bash scripts/install-cron.sh"
