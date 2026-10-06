# CROIT Uptime Monitoring â€” Linux Production Setup
**Server:** frm-rbautodev01  
**App location:** `/opt/croit-monitor`  
**URL after deployment:** `https://frm-rbautodev01:9443/`

---

## What's in this folder

| File | Purpose |
|---|---|
| `deploy.sh` | One-time deployment script â€” run once on the server |
| `update.sh` | Update script â€” run whenever you make changes |
| `croit-monitor.service` | Systemd service definition |
| `nginx-croit-monitor.conf` | Nginx reverse proxy config |
| `app.env` | Environment variables template |
| `backup.sh` | Daily backup script (auto-scheduled by deploy.sh) |
| `README.md` | This file |

---

## Architecture on Linux

```
Browser (HTTPS 443)
       â”‚
       â–¼
   Nginx (reverse proxy)
   - Handles SSL termination
   - Uses your existing FNB certs
   - Serves app at /monitor/
       â”‚
       â–¼
   Gunicorn (4 workers, port 5000, localhost only)
   - Production WSGI server
   - Runs as f5151422 user
       â”‚
       â–¼
   Flask app (app.py)
   - SQLite database
   - Background monitoring threads
   - SSL checker + weekly report
```

---

## First-time Deployment

### Step 1 â€” Copy files to the server

From your Windows laptop, copy the entire `Podman_Dashboard_UAT` folder to the server:

```bash
# Option A: SCP from Windows (run in PowerShell)
scp -r "C:\Users\F5151422\OneDrive - FRG\Desktop\Podman_Dashboard_UAT" f5151422@frm-rbautodev01:/tmp/

# Option B: Use WinSCP or FileZilla to copy the folder
```

### Step 2 â€” Run the deployment script

SSH into the server and run:

```bash
ssh f5151422@frm-rbautodev01
cd /tmp/Podman_Dashboard_UAT/LINUX_SETUP
sudo bash deploy.sh
```

That's it. The script will:
1. Install Python 3, nginx, and dependencies
2. Create `/opt/croit-monitor` with all app files
3. Set up a Python virtual environment with gunicorn
4. Generate a persistent secret key
5. Install and start the systemd service
6. Configure nginx with your SSL certs
7. Schedule daily database backups at 02:00

### Step 3 â€” Open the firewall (if needed)

```bash
sudo firewall-cmd --permanent --add-service=https
sudo firewall-cmd --permanent --add-service=http
sudo firewall-cmd --reload
```

### Step 4 â€” Access the app

Open your browser:
```
https://frm-rbautodev01:9443/
```

Login with:
- Username: `croitadmin`
- Password: `N03ntry#_PCR3m0T#`

---

## Updating After Changes

When you make changes on your Windows laptop and want to deploy them:

```bash
ssh f5151422@frm-rbautodev01
cd /tmp/Podman_Dashboard_UAT/LINUX_SETUP
sudo bash update.sh
```

This copies the updated files, preserves your database and secret key, and restarts the service.

---

## Useful Commands

### Service management
```bash
# Check status
sudo systemctl status croit-monitor

# View live logs
sudo journalctl -u croit-monitor -f

# Restart
sudo systemctl restart croit-monitor

# Stop
sudo systemctl stop croit-monitor
```

### Nginx
```bash
# Test config
sudo nginx -t

# Reload after config change
sudo systemctl reload nginx

# View nginx logs
tail -f /opt/croit-monitor/logs/nginx-access.log
tail -f /opt/croit-monitor/logs/nginx-error.log
```

### Database backup
```bash
# Manual backup
sudo -u f5151422 bash /opt/croit-monitor/backup.sh

# List backups
ls -lh /opt/croit-monitor/backups/

# Restore from backup
sudo systemctl stop croit-monitor
sudo -u f5151422 gunzip -c /opt/croit-monitor/backups/uptime_YYYYMMDD_HHMMSS.db.gz > /opt/croit-monitor/uptime.db
sudo systemctl start croit-monitor
```

### Reset admin password
```bash
sudo -u f5151422 /opt/croit-monitor/venv/bin/python3 -c "
import sqlite3, hashlib
conn = sqlite3.connect('/opt/croit-monitor/uptime.db')
new_pw = 'YourNewPassword'
hashed = hashlib.sha256(new_pw.encode()).hexdigest()
conn.execute(\"UPDATE users SET password=? WHERE username='croitadmin'\", (hashed,))
conn.commit()
conn.close()
print('Password updated')
"
```

---

## File Locations on Server

| Path | Contents |
|---|---|
| `/opt/croit-monitor/` | Application root |
| `/opt/croit-monitor/app.py` | Main application |
| `/opt/croit-monitor/uptime.db` | SQLite database |
| `/opt/croit-monitor/secret.key` | Session secret key |
| `/opt/croit-monitor/frontend/dist/` | Web frontend |
| `/opt/croit-monitor/logo/` | Logo files |
| `/opt/croit-monitor/ssl/` | SSL certificates |
| `/opt/croit-monitor/backups/` | Daily DB backups |
| `/opt/croit-monitor/logs/` | Application and nginx logs |
| `/etc/systemd/system/croit-monitor.service` | Systemd service |
| `/etc/nginx/conf.d/nginx-croit-monitor.conf` | Nginx config |

---

## Differences from Windows (UAT)

| Feature | Windows (UAT) | Linux (Production) |
|---|---|---|
| Web server | Flask dev server | Gunicorn (4 workers) |
| HTTPS | No | Yes (nginx + FNB certs) |
| URL | `http://localhost:5000` | `https://frm-rbautodev01:9443/` |
| Auto-start | Manual (start.bat) | Systemd (starts on boot) |
| Secret key | Regenerated on restart | Persistent in secret.key |
| Backups | None | Daily at 02:00 |
| Logs | Console only | Files in /logs/ |

---

## Critical Service Monitoring — TCP backstop (operator action)

The agent/collector detects the Fircosoft critical processes (AlertReview,
AlertController-Orchestrator, AlertController-CoreEngine, AppDynamics-AppAgent) by
command-line pattern and alerts when a *watched* service goes down. As a
network-reachability backstop for the frontend-facing AlertReview port, an operator
should **manually add a TCP monitor** against port **8443** in both environments:

- **UAT:** `cro-r1fxacruat:8443`
- **PROD:** the prod application server on `:8443`

Add these from the dashboard (Monitors → add TCP monitor). This is intentionally a
manual operator step — the application does not auto-create these monitors and does
not hard-code the hostnames anywhere in its logic.

---

*Created: April 2026 | Server: frm-rbautodev01 | Maintained by: f5151422*
