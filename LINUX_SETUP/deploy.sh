#!/bin/bash
# ============================================================
# CROIT Uptime Monitoring - No-sudo Deployment Script
# Server: frm-rbautodev01
# Run as: bash deploy.sh  (no sudo needed)
# App runs as your user, Gunicorn serves HTTPS on port 9443
# ============================================================

set -e

APP_DIR="$HOME/croit-monitor"
SERVICE_NAME="croit-monitor"
PID_FILE="$APP_DIR/croit-monitor.pid"
LOG_FILE="$APP_DIR/logs/gunicorn.log"

echo ""
echo "============================================================"
echo "  CROIT Uptime Monitoring - Deployment (no sudo)"
echo "============================================================"
echo ""

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_SOURCE="$(dirname "$SCRIPT_DIR")"

# -- 1. Create app directory ----------------------------------
echo "[1/6] Setting up application directory..."
mkdir -p "$APP_DIR/frontend/dist"
mkdir -p "$APP_DIR/logo"
mkdir -p "$APP_DIR/ssl"
mkdir -p "$APP_DIR/backups"
mkdir -p "$APP_DIR/logs"
echo "  App directory: $APP_DIR"

# -- 2. Copy application files --------------------------------
echo "[2/6] Copying application files..."
cp "$APP_SOURCE/app.py"           "$APP_DIR/"
cp "$APP_SOURCE/monitors.json"    "$APP_DIR/" 2>/dev/null || true
cp -r "$APP_SOURCE/frontend/"     "$APP_DIR/"
cp -r "$APP_SOURCE/logo/"         "$APP_DIR/"

# Copy SSL certs
cp "$APP_SOURCE/ssl/frm-rbautodev01.crt"        "$APP_DIR/ssl/"
cp "$APP_SOURCE/ssl/frm-rbautodev01-nopass.key"  "$APP_DIR/ssl/"
chmod 600 "$APP_DIR/ssl/"*
echo "  Files copied."

# -- 3. Python virtual environment ----------------------------
echo "[3/6] Creating Python virtual environment..."
python3 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install --quiet --upgrade pip
"$APP_DIR/venv/bin/pip" install --quiet \
  flask==3.0.3 \
  flask-cors==4.0.1 \
  flask-login==0.6.3 \
  requests==2.32.3 \
  urllib3==2.2.2 \
  gunicorn==21.2.0
echo "  Python environment ready."

# -- 4. Generate persistent secret key -----------------------
echo "[4/6] Generating secret key..."
if [ ! -f "$APP_DIR/secret.key" ]; then
  python3 -c "import secrets; print(secrets.token_hex(32))" > "$APP_DIR/secret.key"
  chmod 600 "$APP_DIR/secret.key"
  echo "  New secret key generated."
else
  echo "  Existing secret key kept."
fi

# -- 5. Copy helper scripts -----------------------------------
echo "[5/6] Installing helper scripts..."
cp "$SCRIPT_DIR/backup.sh"  "$APP_DIR/backup.sh"
cp "$SCRIPT_DIR/update.sh"  "$APP_DIR/update.sh"
chmod +x "$APP_DIR/backup.sh" "$APP_DIR/update.sh"

# Write the start script
cat > "$APP_DIR/start.sh" << 'EOF'
#!/bin/bash
APP_DIR="$(cd "$(dirname "$0")" && pwd)"
PID_FILE="$APP_DIR/croit-monitor.pid"
LOG_FILE="$APP_DIR/logs/gunicorn.log"

# Stop existing instance if running
if [ -f "$PID_FILE" ]; then
  OLD_PID=$(cat "$PID_FILE")
  if kill -0 "$OLD_PID" 2>/dev/null; then
    echo "Stopping existing instance (PID $OLD_PID)..."
    kill "$OLD_PID"
    sleep 2
  fi
  rm -f "$PID_FILE"
fi

echo "Starting CROIT Uptime Monitor..."
cd "$APP_DIR"
nohup "$APP_DIR/venv/bin/gunicorn" \
  --workers 1 \
  --worker-class sync \
  --bind 0.0.0.0:9443 \
  --certfile "$APP_DIR/ssl/frm-rbautodev01.crt" \
  --keyfile  "$APP_DIR/ssl/frm-rbautodev01-nopass.key" \
  --timeout 120 \
  --keep-alive 5 \
  --pid "$PID_FILE" \
  --access-logfile "$LOG_FILE" \
  --error-logfile  "$LOG_FILE" \
  --log-level info \
  app:app >> "$LOG_FILE" 2>&1 &

sleep 2
if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  echo "  Started! PID: $(cat "$PID_FILE")"
  echo "  Dashboard: https://frm-rbautodev01:9443/"
  echo "  Logs:      tail -f $LOG_FILE"
else
  echo "  ERROR: Failed to start. Check logs: $LOG_FILE"
  exit 1
fi
EOF
chmod +x "$APP_DIR/start.sh"

# Write the stop script
cat > "$APP_DIR/stop.sh" << 'EOF'
#!/bin/bash
APP_DIR="$(cd "$(dirname "$0")" && pwd)"
PID_FILE="$APP_DIR/croit-monitor.pid"

if [ -f "$PID_FILE" ]; then
  PID=$(cat "$PID_FILE")
  if kill -0 "$PID" 2>/dev/null; then
    kill "$PID"
    rm -f "$PID_FILE"
    echo "Stopped (PID $PID)."
  else
    echo "Process not running (stale PID file removed)."
    rm -f "$PID_FILE"
  fi
else
  echo "Not running (no PID file found)."
fi
EOF
chmod +x "$APP_DIR/stop.sh"

# Write the status script
cat > "$APP_DIR/status.sh" << 'EOF'
#!/bin/bash
APP_DIR="$(cd "$(dirname "$0")" && pwd)"
PID_FILE="$APP_DIR/croit-monitor.pid"

if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  echo "RUNNING  (PID $(cat "$PID_FILE"))"
  echo "URL:     https://frm-rbautodev01:9443/"
  echo "Logs:    tail -f $APP_DIR/logs/gunicorn.log"
else
  echo "STOPPED"
fi
EOF
chmod +x "$APP_DIR/status.sh"

# -- 6. Start the app -----------------------------------------
echo "[6/6] Starting the application..."
bash "$APP_DIR/start.sh"

echo ""
echo "============================================================"
echo "  Deployment complete!"
echo ""
echo "  Dashboard:  https://frm-rbautodev01:9443/"
echo "  Login:      https://frm-rbautodev01:9443/login"
echo ""
echo "  Manage the service:"
echo "    Start:    bash $APP_DIR/start.sh"
echo "    Stop:     bash $APP_DIR/stop.sh"
echo "    Status:   bash $APP_DIR/status.sh"
echo "    Logs:     tail -f $APP_DIR/logs/gunicorn.log"
echo "============================================================"
echo ""
