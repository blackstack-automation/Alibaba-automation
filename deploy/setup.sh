#!/usr/bin/env bash
# One-shot setup for a fresh Ubuntu 24.04 VPS.
#
# Run as a NON-root user that has sudo, from inside the cloned repo:
#   bash deploy/setup.sh
#
# Safe to re-run: it never overwrites an existing .env (so it can't replace
# your ENCRYPTION_KEY), and it only creates an admin if you say yes.
set -euo pipefail

if [ "$(id -u)" -eq 0 ]; then
    echo "Don't run this as root. Create a normal user first (see DEPLOY.md), then run it as that user." >&2
    exit 1
fi

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_USER="$(id -un)"
cd "$APP_DIR"

echo "==> Installing system packages"
sudo apt-get update -y
sudo apt-get install -y python3-venv python3-pip git redis-server nginx sqlite3 build-essential tmux

echo "==> Starting Redis"
sudo systemctl enable --now redis-server
redis-cli ping | grep -q PONG || { echo "Redis is not answering — check: sudo systemctl status redis-server" >&2; exit 1; }

echo "==> Python environment"
[ -d venv ] || python3 -m venv venv
venv/bin/pip install -q --upgrade pip
venv/bin/pip install -q -r requirements.txt

echo "==> Configuration (.env)"
if [ -f .env ]; then
    echo ".env already exists — leaving it untouched."
else
    SECRET_KEY="$(venv/bin/python -c 'import secrets; print(secrets.token_hex(32))')"
    ENCRYPTION_KEY="$(venv/bin/python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
    umask 077
    cat > .env <<EOF
FLASK_ENV=production
FLASK_DEBUG=0
SECRET_KEY=$SECRET_KEY
ENCRYPTION_KEY=$ENCRYPTION_KEY
DATABASE_URL=sqlite:///$APP_DIR/instance/mail_dashboard.db
REDIS_URL=redis://localhost:6379/0
SEND_RATE_LIMIT_PER_SECOND=5
JOB_FAILURE_THRESHOLD_PERCENT=5
EOF
    echo
    echo "################################################################"
    echo " NEW ENCRYPTION_KEY (save this in a password manager NOW):"
    echo "   $ENCRYPTION_KEY"
    echo " It encrypts every Alibaba AccessKey secret. If it is lost, all"
    echo " stored account credentials are unrecoverable and must be"
    echo " re-entered."
    echo "################################################################"
    echo
fi

echo "==> Database"
mkdir -p instance
venv/bin/flask db upgrade

read -r -p "Create an admin login now? [Y/n] " ans
if [[ "${ans:-Y}" =~ ^[Yy]$ ]]; then
    read -r -p "Admin email: " ADMIN_EMAIL
    read -r -s -p "Admin password: " ADMIN_PASSWORD; echo
    venv/bin/flask create-admin --email "$ADMIN_EMAIL" --password "$ADMIN_PASSWORD"
    unset ADMIN_PASSWORD
fi

echo "==> systemd services"
for unit in web worker beat; do
    sed -e "s|__APP_USER__|$APP_USER|g" -e "s|__APP_DIR__|$APP_DIR|g" \
        "deploy/systemd/mail-dashboard-$unit.service" \
        | sudo tee "/etc/systemd/system/mail-dashboard-$unit.service" >/dev/null
done
sudo systemctl daemon-reload
sudo systemctl enable --now mail-dashboard-web mail-dashboard-worker mail-dashboard-beat

chmod +x deploy/update.sh

echo "==> Health check"
sleep 3
if curl -fsS http://127.0.0.1:8000/healthz >/dev/null; then
    echo "Web app is up on 127.0.0.1:8000"
else
    echo "Web app did not answer — check: journalctl -u mail-dashboard-web -n 50" >&2
fi
systemctl is-active mail-dashboard-web mail-dashboard-worker mail-dashboard-beat

cat <<EOF

Done. The app listens on 127.0.0.1:8000 only (not exposed publicly yet).

Next, pick ONE way to reach it (details in deploy/DEPLOY.md):
  - Testing:  from your PC run   ssh -L 8000:127.0.0.1:8000 $APP_USER@<vps-ip>
              then open http://localhost:8000
  - Real use: point a domain at this server and set up nginx + HTTPS.
EOF
