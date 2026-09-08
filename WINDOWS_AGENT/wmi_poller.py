#!/usr/bin/env python3
"""
CROIT WMI Poller — Option A (agentless Windows monitoring)
Runs on the dashboard server (frm-rbautodev01) and polls Windows servers
via WMI over the network. No agent or firewall change needed on Windows servers.

Requirements (on the dashboard server):
    pip install impacket wmi pywin32   # if running on Windows
    pip install impacket               # if running on Linux (uses impacket WMI)

Usage:
    # Poll one server once
    python3 wmi_poller.py --host 172.20.0.24 --user DOMAIN\\username --password SECRET \
        --token SERVER_TOKEN --url https://localhost:9443 --once

    # Poll continuously every 60 seconds
    python3 wmi_poller.py --host 172.20.0.24 --user DOMAIN\\username --password SECRET \
        --token SERVER_TOKEN --url https://localhost:9443

    # Poll multiple servers from a config file
    python3 wmi_poller.py --config wmi_targets.json --url https://localhost:9443
"""

import argparse
import json
import ssl
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime

# ── WMI Query via impacket (works from Linux) ─────────────────────────────────

def wmi_query(host, username, password, namespace, query):
    """Run a WMI query against a remote Windows host using impacket."""
    try:
        from impacket.dcerpc.v5.dcom import wmi as impacket_wmi
        from impacket.dcerpc.v5.dcomrt import DCOMConnection
        from impacket.dcerpc.v5.dtypes import NULL

        dcom = DCOMConnection(host, username=username, password=password,
                              ntlmFallback=True)
        iInterface = dcom.CoCreateInstanceEx(impacket_wmi.CLSID_WbemLevel1Login,
                                             impacket_wmi.IID_IWbemLevel1Login)
        iWbemLevel1Login = impacket_wmi.IWbemLevel1Login(iInterface)
        iWbemServices = iWbemLevel1Login.NTLMLogin(namespace, NULL, NULL)
        iWbemLevel1Login.RemRelease()

        iEnumWbemClassObject = iWbemServices.ExecQuery(query)
        results = []
        while True:
            try:
                pEnum = iEnumWbemClassObject.Next(0xffffffff, 1)[0]
                record = {}
                for prop in pEnum.getProperties():
                    record[prop] = pEnum.getProperties()[prop]['value']
                results.append(record)
            except Exception:
                break
        dcom.disconnect()
        return results
    except ImportError:
        raise RuntimeError("impacket not installed. Run: pip install impacket")
    except Exception as e:
        raise RuntimeError(f"WMI query failed: {e}")


# ── PowerShell remoting fallback (if WinRM is enabled) ───────────────────────

def ps_remote_query(host, username, password, script):
    """Run a PowerShell script on a remote Windows host via WinRM."""
    try:
        import subprocess
        cmd = [
            "pwsh", "-NoProfile", "-Command",
            f"$cred = New-Object PSCredential('{username}', (ConvertTo-SecureString '{password}' -AsPlainText -Force)); "
            f"Invoke-Command -ComputerName {host} -Credential $cred -ScriptBlock {{ {script} }}"
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return r.stdout.strip(), r.returncode
    except Exception as e:
        return None, -1


# ── Collect metrics via WMI ───────────────────────────────────────────────────

def collect_wmi_metrics(host, username, password):
    """Collect Windows metrics from a remote host via WMI."""
    metrics = {
        "os_name": None, "os_version": None, "kernel": None,
        "cpu_pct": None, "cpu_cores": None, "cpu_threads": None,
        "ram_total_gb": None, "ram_used_gb": None, "ram_pct": None,
        "disk_total_gb": None, "disk_used_gb": None, "disk_pct": None,
        "disk_mounts": [], "uptime_sec": None,
        "load_1m": None, "load_5m": None, "load_15m": None,
        "process_count": None,
        "pending_updates": None, "reboot_required": None, "patch_status": None,
    }

    ns = "//./root/cimv2"

    # OS info + uptime
    try:
        rows = wmi_query(host, username, password, ns,
                         "SELECT Caption, BuildNumber, Version, LastBootUpTime, "
                         "TotalVisibleMemorySize, FreePhysicalMemory "
                         "FROM Win32_OperatingSystem")
        if rows:
            r = rows[0]
            metrics["os_name"]    = r.get("Caption", "Windows")
            metrics["os_version"] = str(r.get("BuildNumber", ""))
            metrics["kernel"]     = str(r.get("Version", ""))
            total_kb = r.get("TotalVisibleMemorySize", 0) or 0
            free_kb  = r.get("FreePhysicalMemory", 0) or 0
            used_kb  = total_kb - free_kb
            metrics["ram_total_gb"] = round(total_kb / 1024 / 1024, 2)
            metrics["ram_used_gb"]  = round(used_kb  / 1024 / 1024, 2)
            metrics["ram_pct"]      = round(used_kb / total_kb * 100, 1) if total_kb else None
            # Uptime from LastBootUpTime (WMI datetime format)
            boot_str = str(r.get("LastBootUpTime", "") or "")
            if boot_str and len(boot_str) >= 14:
                try:
                    boot_dt = datetime.strptime(boot_str[:14], "%Y%m%d%H%M%S")
                    metrics["uptime_sec"] = int((datetime.now() - boot_dt).total_seconds())
                except Exception:
                    pass
    except Exception as e:
        print(f"[WMI Poller] OS query failed for {host}: {e}", file=sys.stderr)

    # CPU
    try:
        rows = wmi_query(host, username, password, ns,
                         "SELECT LoadPercentage, NumberOfCores, NumberOfLogicalProcessors "
                         "FROM Win32_Processor")
        if rows:
            loads   = [r.get("LoadPercentage") for r in rows if r.get("LoadPercentage") is not None]
            metrics["cpu_pct"]     = round(sum(loads) / len(loads), 1) if loads else None
            metrics["cpu_cores"]   = rows[0].get("NumberOfCores")
            metrics["cpu_threads"] = rows[0].get("NumberOfLogicalProcessors")
            load_approx = round((metrics["cpu_pct"] or 0) / 100, 2)
            metrics["load_1m"] = metrics["load_5m"] = metrics["load_15m"] = load_approx
    except Exception as e:
        print(f"[WMI Poller] CPU query failed for {host}: {e}", file=sys.stderr)

    # Disk mounts
    try:
        rows = wmi_query(host, username, password, ns,
                         "SELECT DeviceID, Size, FreeSpace FROM Win32_LogicalDisk "
                         "WHERE DriveType=3")
        mounts = []
        for r in rows:
            size  = r.get("Size") or 0
            free  = r.get("FreeSpace") or 0
            used  = size - free
            total_gb = round(size / 1024**3, 1)
            used_gb  = round(used  / 1024**3, 1)
            free_gb  = round(free  / 1024**3, 1)
            pct      = round(used_gb / total_gb * 100, 1) if total_gb > 0 else 0
            dev      = r.get("DeviceID", "?")
            mounts.append({
                "mount": dev + "\\", "device": dev,
                "total_gb": total_gb, "used_gb": used_gb,
                "free_gb": free_gb, "pct": pct, "disk_type": "Unknown"
            })
        metrics["disk_mounts"] = mounts
        # C: drive for backward compat
        c = next((m for m in mounts if m["device"].upper() == "C:"), None)
        if c:
            metrics["disk_total_gb"] = c["total_gb"]
            metrics["disk_used_gb"]  = c["used_gb"]
            metrics["disk_pct"]      = c["pct"]
    except Exception as e:
        print(f"[WMI Poller] Disk query failed for {host}: {e}", file=sys.stderr)

    # Process count
    try:
        rows = wmi_query(host, username, password, ns,
                         "SELECT Count FROM Win32_Process")
        metrics["process_count"] = len(rows)
    except Exception:
        pass

    return metrics


# ── POST to dashboard ─────────────────────────────────────────────────────────

def post_metrics(url, token, metrics, verify_ssl=False):
    endpoint = url.rstrip("/") + "/api/agent/heartbeat"
    data     = json.dumps(metrics).encode("utf-8")
    req      = urllib.request.Request(
        endpoint,
        data    = data,
        headers = {
            "Content-Type":  "application/json",
            "Authorization": f"Bearer {token}",
            "User-Agent":    "CROIT-WMI-Poller/1.0",
        },
        method = "POST"
    )
    ctx = ssl.create_default_context()
    if not verify_ssl:
        ctx.check_hostname = False
        ctx.verify_mode    = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=15) as resp:
            return True, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}: {e.read().decode()}"
    except Exception as e:
        return False, str(e)


# ── Main ──────────────────────────────────────────────────────────────────────

def poll_server(host, username, password, token, url, verify_ssl=False):
    """Poll one Windows server and post metrics to dashboard."""
    try:
        metrics = collect_wmi_metrics(host, username, password)
        ok, result = post_metrics(url, token, metrics, verify_ssl)
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        if ok:
            print(f"[{ts}] {host} OK - CPU:{metrics['cpu_pct']}% RAM:{metrics['ram_pct']}% "
                  f"Disk:{metrics['disk_pct']}%")
        else:
            print(f"[{ts}] {host} ERROR - {result}", file=sys.stderr)
        return ok
    except Exception as e:
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {host} EXCEPTION - {e}", file=sys.stderr)
        return False


def main():
    parser = argparse.ArgumentParser(description="CROIT WMI Poller v1.0")
    parser.add_argument("--url",        required=True,  help="Dashboard URL")
    parser.add_argument("--host",       help="Windows host IP or hostname")
    parser.add_argument("--user",       help="Domain\\username for WMI auth")
    parser.add_argument("--password",   help="Password for WMI auth")
    parser.add_argument("--token",      help="Dashboard agent token for this server")
    parser.add_argument("--config",     help="JSON config file for multiple servers")
    parser.add_argument("--interval",   type=int, default=60, help="Poll interval seconds")
    parser.add_argument("--once",       action="store_true", help="Poll once and exit")
    parser.add_argument("--verify-ssl", action="store_true", default=False)
    args = parser.parse_args()

    # Build server list
    servers = []
    if args.config:
        with open(args.config) as f:
            servers = json.load(f)  # [{host, user, password, token}, ...]
    elif args.host and args.token:
        servers = [{"host": args.host, "user": args.user,
                    "password": args.password, "token": args.token}]
    else:
        parser.error("Provide --host/--user/--password/--token or --config")

    print(f"[CROIT WMI Poller] Starting - polling {len(servers)} server(s) every {args.interval}s")

    while True:
        for s in servers:
            poll_server(s["host"], s.get("user"), s.get("password"),
                        s["token"], args.url, args.verify_ssl)
        if args.once:
            break
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
