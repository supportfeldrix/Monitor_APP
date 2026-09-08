# CROIT Uptime Monitor — Windows Agent Installation Guide

**Version:** 1.0  
**Date:** April 2026  

---

## Overview

The Windows agent collects live server metrics and reports them to the CROIT dashboard every minute.

**Metrics collected:**
- OS name and version (from registry)
- Kernel / Windows build number
- CPU usage %
- RAM usage (used / total GB + %)
- Disk usage on C: drive (used / total GB + %)
- System uptime
- Running process count

**Requirements:**
- Windows Server 2016 / 2019 / 2022 or Windows 10/11
- Python 3.6+ (free, no admin needed to install for current user)
- Network access to `frm-rbautodev01:9443`
- No admin / elevated rights required

---

## Step 1 — Add the Server in the Dashboard

1. Open `https://frm-rbautodev01:9443` and log in
2. Click **Server Inventory** → **+ Add Server**
3. Fill in:
   - **Hostname** — e.g. `frm-rbwinprd01`
   - **IP Address** — e.g. `172.20.24.50`
   - **Environment** — PROD / UAT / DEV
   - **OS** — e.g. `Windows Server 2022`
   - **Role** — e.g. `Application Server`
   - **Last Patched** — date of last Windows Update
4. Click **Save Server**
5. Click the server card → **🤖 Agent Setup** to get your token

---

## Step 2 — Install Python (if not already installed)

Check if Python is installed:
```powershell
python --version
```

If not installed, install without admin rights:
```powershell
winget install Python.Python.3
```

Or download from [python.org](https://www.python.org/downloads/) and install for current user only (uncheck "Install for all users").

---

## Step 3 — Copy Agent Files

Copy the `WINDOWS_AGENT` folder to the target server. Place it anywhere, e.g.:
```
C:\Users\f5151422\croit-agent\
```

Files needed:
- `agent_windows.py`
- `install_agent.ps1`

---

## Step 4 — Run the Installer

Open PowerShell and run:

```powershell
cd C:\Users\f5151422\croit-agent
.\install_agent.ps1 -Token "YOUR_TOKEN_HERE"
```

The installer will:
1. Verify Python is installed
2. Install `psutil` (for accurate metrics)
3. Test the connection to the dashboard
4. Create a Windows Scheduled Task that runs every minute

**Expected output:**
```
[1/5] Checking Python...
  Found: Python 3.11.x (python)
[2/5] Installing psutil...
  psutil ready.
[3/5] Setting up agent directory...
  Agent script copied.
[4/5] Testing agent connection...
  Connection successful!
  [2026-04-24 10:00:00] OK — CPU:5.2% RAM:42.1% Disk:38.7%
[5/5] Creating Scheduled Task 'CROIT-Agent'...
  Scheduled Task created successfully.
Installation complete!
```

---

## Step 5 — Verify

Check the agent is running:
```powershell
schtasks /query /tn "CROIT-Agent"
```

View the log:
```powershell
Get-Content "$env:USERPROFILE\croit-agent\agent.log" -Tail 20
```

Refresh the dashboard — the server card will show live CPU/RAM/Disk within 1-2 minutes.

---

## Manual Installation (if installer fails)

### Option A — Scheduled Task manually

```powershell
$python = (Get-Command python).Source
$script = "C:\Users\f5151422\croit-agent\agent_windows.py"
$token  = "YOUR_TOKEN"
$url    = "https://frm-rbautodev01:9443"
$log    = "C:\Users\f5151422\croit-agent\agent.log"

schtasks /create /tn "CROIT-Agent" `
  /tr "`"$python`" `"$script`" --url `"$url`" --token `"$token`" --once >> `"$log`" 2>&1" `
  /sc minute /mo 1 /f
```

### Option B — Run continuously in background

```powershell
Start-Process python -ArgumentList "C:\Users\f5151422\croit-agent\agent_windows.py --url https://frm-rbautodev01:9443 --token YOUR_TOKEN --interval 60" -WindowStyle Hidden
```

### Option C — Add to Windows startup (no task scheduler)

```powershell
$startup = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup"
$script  = "C:\Users\f5151422\croit-agent\agent_windows.py"
$token   = "YOUR_TOKEN"
$url     = "https://frm-rbautodev01:9443"

$shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut("$startup\CROIT-Agent.lnk")
$shortcut.TargetPath  = (Get-Command python).Source
$shortcut.Arguments   = "`"$script`" --url `"$url`" --token `"$token`" --interval 60"
$shortcut.WindowStyle = 7  # Minimized
$shortcut.Save()
Write-Host "Startup shortcut created."
```

---

## Uninstall

```powershell
.\install_agent.ps1 -Token "x" -Uninstall
```

Or manually:
```powershell
schtasks /delete /tn "CROIT-Agent" /f
Remove-Item -Recurse "$env:USERPROFILE\croit-agent"
```

---

## Troubleshooting

| Error | Cause | Fix |
|---|---|---|
| `python not found` | Python not installed | Install from python.org or via winget |
| `403 Forbidden` | Proxy blocking request | Check proxy settings — internal URL should bypass proxy |
| `Invalid token` | Wrong token | Regenerate via Agent Setup button in dashboard |
| `Connection refused` | Monitoring app down | Check `https://frm-rbautodev01:9443` is accessible |
| `Access denied` on task | No task scheduler access | Use Option B or C above |
| Metrics show `–` | psutil not installed | Run `pip install psutil` |

---

## psutil vs wmic

| Feature | psutil | wmic fallback |
|---|---|---|
| CPU % | ✅ Accurate | ✅ Works |
| RAM | ✅ Accurate | ✅ Works |
| Disk | ✅ Accurate | ✅ Works |
| Process count | ✅ | ❌ Not available |
| Speed | Fast | Slower (~3s per check) |
| Requirement | `pip install psutil` | Built into Windows |

**Recommendation:** Always use psutil. The installer handles this automatically.

---

## Agent Command Reference

```
python agent_windows.py [OPTIONS]

Options:
  --url URL          Monitoring app URL (required)
  --token TOKEN      Agent token from dashboard (required)
  --once             Run once and exit (for Scheduled Task)
  --interval N       Collection interval seconds (default: 60)
  --verify-ssl       Verify SSL certificate (default: off)
```

---

*CROIT Uptime Monitoring · Windows Agent · April 2026*
