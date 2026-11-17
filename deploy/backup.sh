#!/usr/bin/env bash
# Daily SQLite backup. Uses `.backup` (safe with WAL), NOT a raw file copy.
# Deliberately does NOT back up .env / ENCRYPTION_KEY — keep that somewhere
# else (password manager). Losing the key makes every stored Alibaba secret
# unrecoverable, and keeping it next to the DB backup defeats encrypting them.
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DB="$APP_DIR/instance/mail_dashboard.db"
DEST="${BACKUP_DIR:-$HOME/backups}"
KEEP_DAYS="${KEEP_DAYS:-14}"

mkdir -p "$DEST"
sqlite3 "$DB" ".backup '$DEST/mail_dashboard-$(date +%F).db'"
find "$DEST" -name 'mail_dashboard-*.db' -mtime +"$KEEP_DAYS" -delete
echo "Backup written to $DEST"
