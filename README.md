# Uptime Monitor – UAT

A custom URL monitoring app with a **Status Page that lets you filter uptime by date and timeframe**.  
Built with Python (Flask) + vanilla HTML/JS — no Docker needed for local testing.

---

## Features

| Feature | Details |
|---|---|
| URL monitoring | HTTP/HTTPS checks on configurable intervals |
| Status Page | Live uptime view with **timeframe dropdown** |
| Timeframe presets | Last 1h · 6h · 24h · 7 days · 30 days |
| Custom date range | Pick any From → To datetime |
| Sparkline timeline | Visual up/down bar chart per monitor |
| Uptime % | Calculated for the selected timeframe |
| Avg latency | Average response time for the period |
| Manage Monitors | Add / pause / delete monitors via UI |
| Auto-refresh | Status page refreshes every 30 seconds |
| SQLite storage | All history stored locally in `uptime.db` |

---

## Quick Start (Local)

### 1. Double-click `start.bat`

That's it. It will:
- Create a Python virtual environment
- Install Flask and dependencies
- Start the server on port 5000

### 2. Open browser

```
http://localhost:5000
```

---

## Manual Start (if you prefer)

```bash
# From the Podman_Dashboard_UAT folder:
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

---

## Pre-loaded Monitors

Edit `monitors.json` to change the default monitors that load on first run:

```json
{
  "monitors": [
    { "name": "Jenkins HTTPS", "url": "https://frm-rbautodev01:8443", "interval": 60 },
    { "name": "Jenkins HTTP",  "url": "http://localhost:8080",         "interval": 60 }
  ]
}
```

> Monitors are only seeded from this file on the **first run** (when the database is empty).  
> After that, use the **Manage Monitors** tab in the UI.

---

## How the Timeframe Filter Works

On the Status Page, select a timeframe from the dropdown buttons:

- **Last 1 Hour** — shows uptime % for the past 60 minutes
- **Last 6 Hours**
- **Last 24 Hours** (default)
- **Last 7 Days**
- **Last 30 Days**
- **Custom** — pick any start and end datetime

The uptime %, average latency, check counts, and sparkline bars all update to reflect the selected period.

---

## File Structure

```
Podman_Dashboard_UAT/
├── app.py              ← Flask backend + monitoring engine
├── monitors.json       ← Default monitors (seeded on first run)
├── requirements.txt    ← Python dependencies
├── start.bat           ← One-click startup for Windows
├── uptime.db           ← SQLite database (created on first run)
├── frontend/
│   └── dist/
│       └── index.html  ← Full frontend (single file, no build needed)
└── ssl/                ← Your existing SSL certs
```

---

## API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/status?preset=24h` | Status + uptime for all monitors |
| GET | `/api/status?from_dt=...&to_dt=...` | Custom date range |
| GET | `/api/monitors` | List all monitors |
| POST | `/api/monitors` | Add a monitor |
| DELETE | `/api/monitors/:id` | Delete a monitor |
| POST | `/api/monitors/:id/toggle` | Pause / resume |
| GET | `/api/heartbeats/:id` | Raw heartbeat history |

---

## Moving to Server (Podman)

When ready to deploy on the server, run:

```bash
podman run -d \
  --name uptime-monitor \
  -p 5000:5000 \
  -v ./uptime.db:/app/uptime.db \
  -v ./monitors.json:/app/monitors.json \
  python:3.11-slim \
  bash -c "pip install flask flask-cors requests urllib3 && python app.py"
```

Or use the `Containerfile` (to be added).

---

**Created:** April 2026  
**Environment:** frm-rbautodev01 / Podman_Dashboard_UAT
# Monitor_APP
