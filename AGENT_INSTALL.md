# CROIT Uptime Monitor — Server Agent Installation Guide

**Version:** 1.0  
**Date:** April 2026  
**Author:** CROIT Team  

---

## Overview

The CROIT Server Agent is a lightweight Python script that runs on each monitored server and reports live metrics to the CROIT Uptime Dashboard every 60 seconds.

**What it collects:**
- OS name and version
- Kernel version
- CPU usage %
- RAM usage (used / total GB + %)
- Disk usage (used / total GB + %)
- System uptime
- Load averages (1m / 5m / 15m)
- Running process count

**Requirements:**
- Python 3.6 or higher (standard on RHEL 7/8/9, Ubuntu 18+)
- Network access to `frm-rbautodev01:9443`
- No root / sudo required
- No additional Python packages needed (uses only stdlib)

---

## Step 1 — Add the Server in the Dashboard

1. Open `https://frm-rbautodev01:9443` and log in
2. Click **Server Inventory** in the left sidebar
3. Click **+ Add Server**
4. Fill in the server details:
   - **Hostname** — e.g. `frm-rbtomprd01`
   - **IP Address** — e.g. `172.20.24.100`
   - **Environment** — PROD / UAT / DEV
   - **OS** — e.g. `Red Hat Enterprise Linux 9.7`
   - **Role** — e.g. `TOM Application Server`
   - **Last Patched** — date of last OS patch/update
   - **CPU / RAM / Disk** — server specs (optional, for reference)
5. Click **Save Server**
6. Note the server ID (shown in the URL or card)

---

## Step 2 — Copy the Agent Script

From `frm-rbautodev01`, copy the agent to the target server:

```bash
scp /home/f5151422/agent.py f5151422@TARGET_HOSTNAME:/home/f5151422/agent.py
```

Or from your Windows laptop using PowerShell:

```powershell
scp "C:\Users\F5151422\OneDrive - FRG\Desktop\Podman_Dashboard_UAT\LINUX_SETUP\agent.py" f5151422@TARGET_HOSTNAME:/home/f5151422/agent.py
```

---

## Step 3 — Get the Agent Token

1. In the dashboard, click your server card
2. Click **🤖 Agent Setup** button at the bottom of the detail panel
3. The popup shows your unique token and all install commands pre-filled

Or generate manually via Python on the monitoring server:

```bash
python3 -c "
import sqlite3, secrets
conn = sqlite3.connect('/home/f5151422/croit-monitor/uptime.db')
sid = conn.execute('SELECT id FROM servers WHERE hostname=?', ('YOUR_HOSTNAME',)).fetchone()[0]
token = secrets.token_hex(32)
conn.execute('''INSERT INTO agent_tokens (server_id, token)
  VALUES (?, ?) ON CONFLICT(server_id) DO UPDATE SET token=excluded.token''', (sid, token))
conn.commit()
print('Token:', token)
conn.close()
"
```

---

## Step 4 — Test the Agent

SSH into the target server and run once to verify:

```bash
python3 /home/f5151422/agent.py \
  --url https://frm-rbautodev01:9443 \
  --token YOUR_TOKEN_HERE \
  --once
```

**Expected output:**
```
[CROIT Agent] Starting — reporting to https://frm-rbautodev01:9443
[CROIT Agent] Hostname: frm-rbtomprd01
[2026-04-24 10:00:00] OK — CPU:12.3% RAM:45.6% Disk:23.1% Load:0.45
```

If you see `OK` — the agent is working. Refresh the dashboard to see live metrics.

---

## Step 5 — Schedule the Agent (Choose One Option)

### Option A — Crontab (Recommended if available)

```bash
(crontab -l 2>/dev/null; echo "* * * * * python3 /home/f5151422/agent.py --url https://frm-rbautodev01:9443 --token YOUR_TOKEN --once >> /home/f5151422/agent.log 2>&1") | crontab -
```

Verify it was added:
```bash
crontab -l
```

### Option B — systemd User Service (No sudo required)

Use this if crontab is not available. The service auto-starts on login and restarts if it crashes.

```bash
mkdir -p ~/.config/systemd/user

cat > ~/.config/systemd/user/croit-agent.service << 'EOF'
[Unit]
Description=CROIT Server Agent
After=network.target

[Service]
ExecStart=python3 /home/f5151422/agent.py --url https://frm-rbautodev01:9443 --token YOUR_TOKEN
Restart=always
RestartSec=60

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now croit-agent
```

Check status:
```bash
systemctl --user status croit-agent
journalctl --user -u croit-agent -f
```

### Option C — nohup Background Process (No crontab, no systemd)

Use this as a last resort when neither crontab nor systemd is available.

```bash
nohup python3 /home/f5151422/agent.py \
  --url https://frm-rbautodev01:9443 \
  --token YOUR_TOKEN \
  --interval 60 \
  >> /home/f5151422/agent.log 2>&1 &

echo $! > /home/f5151422/agent.pid
echo "Agent started with PID: $(cat /home/f5151422/agent.pid)"
```

**Note:** This does NOT survive a server reboot. Add to `~/.bashrc` or `~/.bash_profile` to auto-start on login:

```bash
echo "nohup python3 /home/f5151422/agent.py --url https://frm-rbautodev01:9443 --token YOUR_TOKEN --interval 60 >> /home/f5151422/agent.log 2>&1 &" >> ~/.bash_profile
```

---

## Verifying the Agent is Running

Check the agent log:
```bash
tail -f /home/f5151422/agent.log
```

Check if the process is running:
```bash
ps aux | grep agent.py
```

In the dashboard — the server card shows:
- **● Agent online** (green dot) — data received within last 3 minutes
- **○ No agent** (grey dot) — no recent data

---

## Stopping the Agent

**Crontab:**
```bash
crontab -e   # remove the agent line
```

**systemd:**
```bash
systemctl --user stop croit-agent
systemctl --user disable croit-agent
```

**nohup:**
```bash
kill $(cat /home/f5151422/agent.pid)
rm /home/f5151422/agent.pid
```

---

## Troubleshooting

| Error | Cause | Fix |
|---|---|---|
| `403 Forbidden` | Proxy intercepting the request | Use `--url https://frm-rbautodev01:9443` (not localhost from remote servers) |
| `Invalid token` | Wrong token or server ID mismatch | Regenerate token via Agent Setup button |
| `Connection refused` | Monitoring app not running | Check `bash ~/croit-monitor/status.sh` on frm-rbautodev01 |
| `SSL error` | Self-signed cert | Agent ignores SSL errors by default — should not occur |
| `No such file` | agent.py not copied | Re-run the scp command from Step 2 |

---

## Agent Command Reference

```
python3 agent.py [OPTIONS]

Options:
  --url URL          Monitoring app URL (required)
  --token TOKEN      Agent token from dashboard (required)
  --once             Run once and exit (for cron)
  --interval N       Collection interval in seconds (default: 60)
  --verify-ssl       Verify SSL certificate (default: off)
```

---

## Server Inventory — Last Patched Field

The **Last Patched** date tracks when the server last received OS updates/patches.

| Colour | Meaning |
|---|---|
| 🟢 Green | Patched within 30 days — up to date |
| 🟡 Yellow | 30–90 days ago — consider scheduling updates |
| 🔴 Red | Over 90 days ago — security updates overdue |

Update this field after each patching cycle via **Server Inventory → Edit Server → Last Patched**.

---

## Windows Servers

For Windows servers, use the dedicated Windows agent instead.

See: **`WINDOWS_AGENT/WINDOWS_AGENT_INSTALL.md`**

Files:
- `WINDOWS_AGENT/agent_windows.py` — the agent script
- `WINDOWS_AGENT/install_agent.ps1` — one-command PowerShell installer
- `WINDOWS_AGENT/WINDOWS_AGENT_INSTALL.md` — full Windows guide

Quick install on Windows:
```powershell
.\install_agent.ps1 -Token "YOUR_TOKEN_HERE"
```

---

*CROIT Uptime Monitoring · frm-rbautodev01 · April 2026*
