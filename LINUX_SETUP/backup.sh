#!/bin/bash
# ============================================================
# CROIT Uptime Monitoring - Daily Backup Script
# Scheduled by deploy.sh at 02:00 daily
# ============================================================

APP_DIR="/opt/croit-monitor"
BACKUP_DIR="$APP_DIR/backups"
DATE=$(date +%Y%m%d_%H%M%S)
KEEP_DAYS=30

echo "[$DATE] Starting backup..."

# Create backup
BACKUP_FILE="$BACKUP_DIR/uptime_${DATE}.db"
cp "$APP_DIR/uptime.db" "$BACKUP_FILE"

if [ $? -eq 0 ]; then
  # Compress it
  gzip "$BACKUP_FILE"
  echo "[$DATE] Backup created: ${BACKUP_FILE}.gz"
else
  echo "[$DATE] ERROR: Backup failed!"
  exit 1
fi

# Remove backups older than KEEP_DAYS days
find "$BACKUP_DIR" -name "uptime_*.db.gz" -mtime +$KEEP_DAYS -delete
echo "[$DATE] Old backups cleaned (kept last $KEEP_DAYS days)"

# Show backup directory size
TOTAL=$(du -sh "$BACKUP_DIR" 2>/dev/null | cut -f1)
echo "[$DATE] Backup directory size: $TOTAL"
echo "[$DATE] Backup complete."
