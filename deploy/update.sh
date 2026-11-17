#!/usr/bin/env bash
# Pull the latest code from GitHub, apply migrations, restart services.
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$APP_DIR"

git pull --ff-only
venv/bin/pip install -q -r requirements.txt
venv/bin/flask db upgrade
sudo systemctl restart mail-dashboard-web mail-dashboard-worker mail-dashboard-beat
sleep 2
systemctl --no-pager --lines=0 status mail-dashboard-web mail-dashboard-worker mail-dashboard-beat | grep -E 'Active:|●'
