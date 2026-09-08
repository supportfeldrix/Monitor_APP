#!/bin/bash
# ============================================================
# CROIT Uptime Monitoring - Update Script (no sudo)
# Usage: bash update.sh
# ============================================================

set -e

APP_DIR="$HOME/croit-monitor"

echo ""
echo "============================================================"
echo "  CROIT Uptime Monitoring - Updating..."
echo "============================================================"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_SOURCE="$(dirname "$SCRIPT_DIR")"

# Backup DB before update
echo "[1/4] Backing up database..."
cp "$APP_DIR/uptime.db" "$APP_DIR/backups/uptime_pre_update_$(date +%Y%m%d_%H%M%S).db" 2>/dev/null || true

# Stop running instance
echo "[2/4] Stopping service..."
bash "$APP_DIR/stop.sh" 2>/dev/null || true
sleep 1

# Copy updated files (preserves uptime.db and secret.key)
echo "[3/4] Copying updated files..."
cp "$APP_SOURCE/app.py"       "$APP_DIR/"
cp -r "$APP_SOURCE/frontend/" "$APP_DIR/"
cp -r "$APP_SOURCE/logo/"     "$APP_DIR/"

# Update Python packages if requirements changed
"$APP_DIR/venv/bin/pip" install --quiet -r "$APP_SOURCE/requirements.txt" 2>/dev/null || true

# Restart
echo "[4/4] Restarting service..."
bash "$APP_DIR/start.sh"

echo ""
echo "  Update complete!"
echo "  Dashboard: https://frm-rbautodev01:9443/"
echo ""
