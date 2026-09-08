#!/usr/bin/env python3
"""
CROIT Uptime Monitor — Windows Server Agent v2
Collects OS, CPU cores/threads, RAM, disk mounts per drive, disk type, uptime.

Requirements:
    pip install psutil

Usage:
    python agent_windows.py --url https://frm-rbautodev01:9443 --token YOUR_TOKEN

Install as Scheduled Task (run install_agent.ps1 instead):
    schtasks /create /tn "CROIT Agent" /tr "python C:\\croit\\agent_windows.py --url https://frm-rbautodev01:9443 --token YOUR_TOKEN --once" /sc minute /mo 1 /f
"""

import argparse
import json
import os
import platform
import socket
import ssl
import subprocess
import sys
import time
import urllib.request
import urllib.error

# ── OS Info ───────────────────────────────────────────────────────────────────

def get_os_info():
    os_name    = "Windows"
    os_version = ""
    kernel     = platform.version()
    try:
        import winreg
        key     = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                 r"SOFTWARE\Microsoft\Windows NT\CurrentVersion")
        product = winreg.QueryValueEx(key, "ProductName")[0]
        build   = winreg.QueryValueEx(key, "CurrentBuildNumber")[0]
        try:
            ubr        = winreg.QueryValueEx(key, "UBR")[0]
            os_version = f"{build}.{ubr}"
        except Exception:
            os_version = build
        os_name = product
        winreg.CloseKey(key)
    except Exception:
        os_version = platform.version()
    return os_name, os_version, kernel


# ── CPU ───────────────────────────────────────────────────────────────────────

def get_cpu_info_psutil():
    import psutil
    cpu_pct     = round(psutil.cpu_percent(interval=1), 1)
    cpu_cores   = psutil.cpu_count(logical=False) or psutil.cpu_count(logical=True)
    cpu_threads = psutil.cpu_count(logical=True)
    return cpu_pct, cpu_cores, cpu_threads


def get_cpu_info_wmic():
    """Fallback CPU info via wmic."""
    cpu_pct = cpu_cores = cpu_threads = None
    try:
        r = subprocess.run(["wmic", "cpu", "get", "LoadPercentage,NumberOfCores,NumberOfLogicalProcessors", "/value"],
                           capture_output=True, text=True, timeout=10)
        for line in r.stdout.splitlines():
            line = line.strip()
            if "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip()
            if k == "LoadPercentage" and v:
                try: cpu_pct = float(v)
                except: pass
            elif k == "NumberOfCores" and v:
                try: cpu_cores = int(v)
                except: pass
            elif k == "NumberOfLogicalProcessors" and v:
                try: cpu_threads = int(v)
                except: pass
    except Exception:
        pass
    return cpu_pct, cpu_cores, cpu_threads


# ── RAM ───────────────────────────────────────────────────────────────────────

def get_ram_psutil():
    import psutil
    ram = psutil.virtual_memory()
    return (round(ram.total / 1024**3, 2),
            round(ram.used  / 1024**3, 2),
            round(ram.percent, 1))


def get_ram_wmic():
    ram_total_gb = ram_used_gb = ram_pct = None
    try:
        r1 = subprocess.run(["wmic", "ComputerSystem", "get", "TotalPhysicalMemory", "/value"],
                            capture_output=True, text=True, timeout=10)
        r2 = subprocess.run(["wmic", "OS", "get", "FreePhysicalMemory", "/value"],
                            capture_output=True, text=True, timeout=10)
        total_b = int([l.split("=")[1] for l in r1.stdout.splitlines() if "=" in l][0])
        free_kb = int([l.split("=")[1] for l in r2.stdout.splitlines() if "=" in l][0])
        ram_total_gb = round(total_b / 1024**3, 2)
        ram_used_gb  = round((total_b - free_kb * 1024) / 1024**3, 2)
        ram_pct      = round(ram_used_gb / ram_total_gb * 100, 1)
    except Exception:
        pass
    return ram_total_gb, ram_used_gb, ram_pct


# ── Disk Mounts ───────────────────────────────────────────────────────────────

def get_disk_type_windows(drive_letter):
    """Detect SSD or HDD for a Windows drive letter using wmic."""
    try:
        # Get the physical disk index for this drive
        r = subprocess.run(
            ["wmic", "logicaldisk", "where", f"DeviceID='{drive_letter}:'",
             "assoc", "/assocclass:Win32_LogicalDiskToPartition"],
            capture_output=True, text=True, timeout=10
        )
        # Try PowerShell as it's more reliable for disk type
        ps_cmd = (
            f"$d = Get-Partition -DriveLetter {drive_letter} -ErrorAction SilentlyContinue; "
            f"if ($d) {{ $disk = Get-Disk -Number $d.DiskNumber -ErrorAction SilentlyContinue; "
            f"if ($disk) {{ $disk.MediaType }} else {{ 'Unknown' }} }} else {{ 'Unknown' }}"
        )
        r2 = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
            capture_output=True, text=True, timeout=10
        )
        result = r2.stdout.strip()
        if "SSD" in result or "Solid" in result:
            return "SSD"
        elif "HDD" in result or "Rotational" in result:
            return "HDD"
        elif result and result not in ("Unknown", "Unspecified", ""):
            return result
    except Exception:
        pass
    return "Unknown"


def get_disk_mounts_psutil():
    import psutil
    mounts = []
    for part in psutil.disk_partitions(all=False):
        try:
            usage = psutil.disk_usage(part.mountpoint)
            total_gb = round(usage.total / 1024**3, 1)
            used_gb  = round(usage.used  / 1024**3, 1)
            free_gb  = round(usage.free  / 1024**3, 1)
            pct      = round(usage.percent, 1)
            # Extract drive letter for disk type lookup
            drive_letter = part.device.rstrip(":\\").rstrip(":/")
            disk_type = get_disk_type_windows(drive_letter) if len(drive_letter) == 1 else "Unknown"
            mounts.append({
                "mount":     part.mountpoint,
                "device":    part.device,
                "total_gb":  total_gb,
                "used_gb":   used_gb,
                "free_gb":   free_gb,
                "pct":       pct,
                "disk_type": disk_type,
            })
        except Exception:
            pass
    mounts.sort(key=lambda m: m["mount"])
    return mounts


def get_disk_mounts_wmic():
    """Fallback disk info via wmic — all logical drives."""
    mounts = []
    try:
        r = subprocess.run(
            ["wmic", "logicaldisk", "get",
             "DeviceID,Size,FreeSpace,DriveType", "/value"],
            capture_output=True, text=True, timeout=15
        )
        current = {}
        for line in r.stdout.splitlines():
            line = line.strip()
            if not line:
                if current.get("DeviceID") and current.get("Size"):
                    try:
                        total_b  = int(current["Size"])
                        free_b   = int(current.get("FreeSpace", 0))
                        used_b   = total_b - free_b
                        total_gb = round(total_b / 1024**3, 1)
                        used_gb  = round(used_b  / 1024**3, 1)
                        free_gb  = round(free_b  / 1024**3, 1)
                        pct      = round(used_gb / total_gb * 100, 1) if total_gb else 0
                        drive    = current["DeviceID"].rstrip(":")
                        mounts.append({
                            "mount":     current["DeviceID"] + "\\",
                            "device":    current["DeviceID"],
                            "total_gb":  total_gb,
                            "used_gb":   used_gb,
                            "free_gb":   free_gb,
                            "pct":       pct,
                            "disk_type": "Unknown",
                        })
                    except Exception:
                        pass
                current = {}
            elif "=" in line:
                k, v = line.split("=", 1)
                current[k.strip()] = v.strip()
    except Exception:
        pass
    return mounts


# ── Uptime / Processes ────────────────────────────────────────────────────────

def get_uptime_psutil():
    import psutil
    try:
        return int(time.time() - psutil.boot_time())
    except Exception:
        return None


def get_uptime_wmic():
    try:
        r = subprocess.run(["wmic", "OS", "get", "LastBootUpTime", "/value"],
                           capture_output=True, text=True, timeout=10)
        for line in r.stdout.splitlines():
            if "=" in line:
                boot_raw = line.split("=")[1].strip()[:14]
                from datetime import datetime
                boot_dt  = datetime.strptime(boot_raw, "%Y%m%d%H%M%S")
                return int((datetime.now() - boot_dt).total_seconds())
    except Exception:
        pass
    return None


# ── Patch Metrics ─────────────────────────────────────────────────────────────

def classify_patch_status(updates):
    """
    Pure function: classify patch status from a list of update dicts.
    Each dict has a "severity" key (string).
    Returns "up_to_date" | "updates_pending" | "critical"
    """
    if not updates:
        return "up_to_date"
    critical_severities = {"Critical", "Important"}
    if any(u.get("severity", "") in critical_severities for u in updates):
        return "critical"
    return "updates_pending"


def get_reboot_required():
    """
    Check Windows registry for pending reboot.
    Returns True, False, or None (if winreg unavailable or exception).
    """
    try:
        import winreg
        # Check 1: RebootRequired key exists
        try:
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired"
            )
            winreg.CloseKey(key)
            return True
        except FileNotFoundError:
            pass
        except Exception:
            pass

        # Check 2: PendingFileRenameOperations is non-empty
        try:
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SYSTEM\CurrentControlSet\Control\Session Manager"
            )
            value, _ = winreg.QueryValueEx(key, "PendingFileRenameOperations")
            winreg.CloseKey(key)
            if value:
                return True
        except FileNotFoundError:
            pass
        except Exception:
            pass

        return False

    except ImportError:
        return None
    except Exception:
        return None


def collect_patch_metrics():
    """
    Collect pending update count, reboot-required flag, and patch status for Windows.
    Primary: WUA COM API (win32com.client)
    Fallback 1: PSWindowsUpdate PowerShell module
    Fallback 2: Native COM via PowerShell
    Returns {"pending_updates": int|None, "reboot_required": bool|None, "patch_status": str|None}
    """
    reboot_required = get_reboot_required()

    # ── Primary: WUA COM API ──────────────────────────────────────────────────
    try:
        import win32com.client
        import pythoncom
        pythoncom.CoInitialize()
        try:
            session  = win32com.client.Dispatch("Microsoft.Update.Session")
            searcher = session.CreateUpdateSearcher()
            result   = searcher.Search("IsInstalled=0 and IsHidden=0")
            updates  = []
            for i in range(result.Updates.Count):
                u = result.Updates.Item(i)
                severity = getattr(u, "MsrcSeverity", None) or ""
                updates.append({"severity": severity})
            patch_status    = classify_patch_status(updates)
            pending_updates = len(updates)
            return {
                "pending_updates": pending_updates,
                "reboot_required": reboot_required,
                "patch_status":    patch_status,
            }
        finally:
            pythoncom.CoUninitialize()

    except ImportError:
        pass  # fall through to PowerShell fallbacks
    except Exception as e:
        print(f"[CROIT Agent v2] WARNING: WUA COM failed: {e}", file=sys.stderr)

    # ── Fallback 1: PSWindowsUpdate PowerShell module ─────────────────────────
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-WindowsUpdate -NotInstalled | Select-Object -Property Title,MsrcSeverity | ConvertTo-Json -Compress"],
            capture_output=True, text=True, timeout=120
        )
        if r.returncode == 0 and r.stdout.strip():
            import json as _json
            raw = r.stdout.strip()
            # ConvertTo-Json returns object (not array) for single item
            data = _json.loads(raw)
            if isinstance(data, dict):
                data = [data]
            updates = []
            for item in data:
                severity = item.get("MsrcSeverity") or ""
                updates.append({"severity": severity})
            patch_status    = classify_patch_status(updates)
            pending_updates = len(updates)
            return {
                "pending_updates": pending_updates,
                "reboot_required": reboot_required,
                "patch_status":    patch_status,
            }
        elif "not recognized" in r.stderr.lower() or "not found" in r.stderr.lower():
            raise RuntimeError("PSWindowsUpdate not installed")
    except Exception as e:
        print(f"[CROIT Agent v2] WARNING: PSWindowsUpdate fallback failed: {e}", file=sys.stderr)

    # ── Fallback 2: Native COM via PowerShell ─────────────────────────────────
    try:
        ps_cmd = (
            "$s = New-Object -ComObject Microsoft.Update.Session; "
            "$r = $s.CreateUpdateSearcher().Search('IsInstalled=0'); "
            "$r.Updates.Count"
        )
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
            capture_output=True, text=True, timeout=120
        )
        if r.returncode == 0 and r.stdout.strip().isdigit():
            count = int(r.stdout.strip())
            # Without severity info, classify as updates_pending if count > 0
            patch_status = "up_to_date" if count == 0 else "updates_pending"
            return {
                "pending_updates": count,
                "reboot_required": reboot_required,
                "patch_status":    patch_status,
            }
    except Exception as e:
        print(f"[CROIT Agent v2] WARNING: PowerShell COM fallback failed: {e}", file=sys.stderr)

    # ── All methods failed ────────────────────────────────────────────────────
    print("[CROIT Agent v2] WARNING: All patch collection methods failed; returning null patch fields.",
          file=sys.stderr)
    return {"pending_updates": None, "reboot_required": None, "patch_status": None}


# ── Collect all ───────────────────────────────────────────────────────────────

def collect_metrics():
    os_name, os_version, kernel = get_os_info()

    try:
        import psutil
        use_psutil = True
        print("[CROIT Agent v2] Using psutil")
    except ImportError:
        use_psutil = False
        print("[CROIT Agent v2] psutil not found, using wmic fallback")

    if use_psutil:
        cpu_pct, cpu_cores, cpu_threads = get_cpu_info_psutil()
        ram_total, ram_used, ram_pct    = get_ram_psutil()
        disk_mounts                     = get_disk_mounts_psutil()
        uptime_sec                      = get_uptime_psutil()
        try:
            process_count = len(__import__("psutil").pids())
        except Exception:
            process_count = None
    else:
        cpu_pct, cpu_cores, cpu_threads = get_cpu_info_wmic()
        ram_total, ram_used, ram_pct    = get_ram_wmic()
        disk_mounts                     = get_disk_mounts_wmic()
        uptime_sec                      = get_uptime_wmic()
        process_count                   = None

    # Windows has no load average — use CPU % as approximation
    load_approx = round((cpu_pct or 0) / 100, 2)

    # C: drive for backward compat root disk fields
    c_drive = next((m for m in disk_mounts if m["mount"].upper().startswith("C:")), None)
    disk_total = c_drive["total_gb"] if c_drive else None
    disk_used  = c_drive["used_gb"]  if c_drive else None
    disk_pct   = c_drive["pct"]      if c_drive else None

    return {
        "os_name":       os_name,
        "os_version":    os_version,
        "kernel":        kernel,
        "cpu_pct":       cpu_pct,
        "cpu_cores":     cpu_cores,
        "cpu_threads":   cpu_threads,
        "ram_total_gb":  ram_total,
        "ram_used_gb":   ram_used,
        "ram_pct":       ram_pct,
        "disk_total_gb": disk_total,
        "disk_used_gb":  disk_used,
        "disk_pct":      disk_pct,
        "disk_mounts":   disk_mounts,
        "uptime_sec":    uptime_sec,
        "load_1m":       load_approx,
        "load_5m":       load_approx,
        "load_15m":      load_approx,
        "process_count": process_count,
    }


# ── Installed Software ────────────────────────────────────────────────────────

def _is_windows_system_software(name, vendor):
    """
    Returns True if the entry is a Windows system component or Microsoft built-in,
    and should be excluded from the 3rd-party software inventory.
    """
    name_lower   = name.lower()
    vendor_lower = (vendor or "").lower()

    # ── Vendor-based exclusions ───────────────────────────────────────────────
    # Skip anything published by Microsoft (OS components, .NET, VC++ runtimes, etc.)
    microsoft_vendors = (
        "microsoft corporation",
        "microsoft corp",
        "microsoft windows",
        "microsoft office",
        "microsoft.",
        "microsoft ",
    )
    if any(vendor_lower.startswith(v) for v in microsoft_vendors):
        return True

    # ── Name-based exclusions ─────────────────────────────────────────────────
    system_name_prefixes = (
        "microsoft ",
        "windows ",
        "update for windows",
        "security update for",
        "hotfix for windows",
        "service pack ",
        "kb",                          # Windows KB patches (e.g. "KB5034441")
    )
    if any(name_lower.startswith(p) for p in system_name_prefixes):
        return True

    system_name_substrings = (
        "visual c++ ",
        "visual c++ redistributable",
        ".net framework",
        ".net runtime",
        ".net desktop runtime",
        "asp.net",
        "windows sdk",
        "windows driver kit",
        "windows assessment",
        "directx",
        "windows media player",
        "windows subsystem",
        "hyper-v",
        "remote desktop",
        "windows powershell",
        "windows terminal",          # built-in in newer Windows
    )
    if any(s in name_lower for s in system_name_substrings):
        return True

    return False


def collect_installed_software_windows():
    """
    Collect 3rd-party installed software from Windows registry uninstall keys.
    Reads both 64-bit and 32-bit (WOW6432Node) uninstall hives.
    Excludes Microsoft / Windows system components and built-in runtimes.
    Returns a list of dicts: {name, version, vendor, install_path}.
    Capped at 500 entries.
    """
    packages = []
    seen     = set()

    registry_paths = [
        r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
        r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
    ]

    try:
        import winreg

        for reg_path in registry_paths:
            try:
                hive = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, reg_path)
            except Exception:
                continue

            try:
                i = 0
                while True:
                    try:
                        subkey_name = winreg.EnumKey(hive, i)
                        i += 1
                    except OSError:
                        break

                    try:
                        subkey = winreg.OpenKey(hive, subkey_name)
                        try:
                            name = winreg.QueryValueEx(subkey, "DisplayName")[0].strip()
                        except Exception:
                            winreg.CloseKey(subkey)
                            continue

                        if not name or name in seen:
                            winreg.CloseKey(subkey)
                            continue

                        try:
                            version = winreg.QueryValueEx(subkey, "DisplayVersion")[0].strip()
                        except Exception:
                            version = ""

                        try:
                            vendor = winreg.QueryValueEx(subkey, "Publisher")[0].strip()
                        except Exception:
                            vendor = ""

                        # Skip Windows system components — only keep 3rd-party software
                        if _is_windows_system_software(name, vendor):
                            winreg.CloseKey(subkey)
                            continue

                        seen.add(name)

                        try:
                            install_path = winreg.QueryValueEx(subkey, "InstallLocation")[0].strip()
                        except Exception:
                            install_path = ""

                        packages.append({
                            "name":         name,
                            "version":      version,
                            "vendor":       vendor,
                            "install_path": install_path,
                        })
                        winreg.CloseKey(subkey)
                    except Exception:
                        pass
            finally:
                winreg.CloseKey(hive)

    except ImportError:
        # winreg not available — try PowerShell fallback
        try:
            ps_cmd = (
                "Get-ItemProperty "
                "HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*, "
                "HKLM:\\SOFTWARE\\WOW6432Node\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\* "
                "-ErrorAction SilentlyContinue | "
                "Where-Object { $_.DisplayName } | "
                "Select-Object DisplayName, DisplayVersion, Publisher, InstallLocation | "
                "ConvertTo-Json -Compress"
            )
            r = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_cmd],
                capture_output=True, text=True, timeout=30
            )
            if r.returncode == 0 and r.stdout.strip():
                import json as _json
                data = _json.loads(r.stdout.strip())
                if isinstance(data, dict):
                    data = [data]
                for item in data:
                    name   = (item.get("DisplayName") or "").strip()
                    vendor = (item.get("Publisher") or "").strip()
                    if not name or name in seen:
                        continue
                    # Skip Windows system components
                    if _is_windows_system_software(name, vendor):
                        continue
                    seen.add(name)
                    packages.append({
                        "name":         name,
                        "version":      (item.get("DisplayVersion") or "").strip(),
                        "vendor":       vendor,
                        "install_path": (item.get("InstallLocation") or "").strip(),
                    })
        except Exception as e:
            print(f"[CROIT Agent v2] WARNING: PowerShell software collection failed: {e}",
                  file=sys.stderr)

    return packages[:500]


# ── Service Discovery ─────────────────────────────────────────────────────────

def discover_listening_ports_windows():
    """
    Discover services listening on TCP ports using netstat.
    Returns list of dicts: {port, protocol, address, pid, process, state}
    """
    import subprocess
    services = []
    seen_ports = set()

    try:
        r = subprocess.run(
            ["netstat", "-ano", "-p", "TCP"],
            capture_output=True, text=True, timeout=15
        )
        if r.returncode == 0:
            for line in r.stdout.splitlines():
                line = line.strip()
                if 'LISTENING' not in line:
                    continue
                parts = line.split()
                if len(parts) < 5:
                    continue
                local = parts[1]
                if ':' in local:
                    addr, port_str = local.rsplit(':', 1)
                    try:
                        port = int(port_str)
                    except ValueError:
                        continue
                    if port in seen_ports:
                        continue
                    seen_ports.add(port)
                    pid = None
                    try:
                        pid = int(parts[4])
                    except (ValueError, IndexError):
                        pass
                    services.append({
                        "port":     port,
                        "protocol": "tcp",
                        "address":  addr,
                        "pid":      pid,
                        "process":  "",
                        "state":    "LISTEN",
                    })
    except Exception:
        pass

    # Resolve process names from PIDs using tasklist
    if services:
        pid_map = {}
        try:
            r = subprocess.run(
                ["tasklist", "/FO", "CSV", "/NH"],
                capture_output=True, text=True, timeout=15
            )
            if r.returncode == 0:
                for line in r.stdout.splitlines():
                    parts = line.strip().strip('"').split('","')
                    if len(parts) >= 2:
                        try:
                            name = parts[0]
                            pid  = int(parts[1])
                            pid_map[pid] = name
                        except (ValueError, IndexError):
                            pass
        except Exception:
            pass
        for svc in services:
            if svc["pid"] and svc["pid"] in pid_map:
                svc["process"] = pid_map[svc["pid"]]

    # Well-known port labels as fallback for unresolved ports
    WELL_KNOWN_PORTS = {
        22: "sshd", 25: "smtp", 53: "dns", 80: "httpd", 110: "pop3",
        143: "imap", 443: "https", 465: "smtps", 587: "submission",
        993: "imaps", 995: "pop3s",
        1433: "mssql", 1521: "oracle", 1556: "veritas-pbx",
        1557: "veritas", 2049: "nfs", 2181: "zookeeper",
        3000: "grafana", 3306: "mysql", 3389: "rdp",
        5432: "postgresql", 5433: "postgresql",
        5600: "wso2", 5666: "nrpe",
        5672: "rabbitmq", 6379: "redis",
        6443: "k8s-api", 6556: "checkmk",
        8080: "http-alt", 8443: "https-alt",
        9090: "prometheus", 9091: "prometheus-push",
        9092: "kafka", 9200: "elasticsearch",
        9443: "https-app",
        10050: "zabbix-agent", 10051: "zabbix-server",
        11211: "memcached", 15672: "rabbitmq-mgmt",
        27017: "mongodb", 50000: "jenkins-agent",
    }
    for svc in services:
        if not svc["process"] and svc["port"] in WELL_KNOWN_PORTS:
            svc["process"] = WELL_KNOWN_PORTS[svc["port"]]

    return services


def discover_windows_services():
    """
    Discover running Windows services (non-system).
    Returns list of dicts: {name, status, description, type}
    """
    import subprocess
    services = []

    # System services to skip
    system_prefixes = (
        "Windows", "Microsoft", "DCOM", "RPC", "Plug and Play",
        "Security", "Base Filtering", "Network", "DNS Client",
        "DHCP", "Group Policy", "Task Scheduler", "User Profile",
        "WMI", "COM+", "Cryptographic", "Diagnostic", "Distributed",
        "IP Helper", "Server", "Workstation", "Print Spooler",
        "Shell Hardware", "System Events", "Themes", "Time",
        "Update Orchestrator", "User Access", "Virtual Disk",
        "Volume Shadow", "Windows Audio", "Windows Connection",
        "Windows Defender", "Windows Error", "Windows Event",
        "Windows Firewall", "Windows Font", "Windows Installer",
        "Windows License", "Windows Management", "Windows Push",
        "Windows Remote", "Windows Search", "Windows Time",
        "Windows Update", "WinHTTP", "WLAN",
    )

    try:
        ps_cmd = (
            "Get-Service | Where-Object {$_.Status -eq 'Running'} | "
            "Select-Object Name, DisplayName, Status | "
            "ConvertTo-Json -Compress"
        )
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
            capture_output=True, text=True, timeout=20
        )
        if r.returncode == 0 and r.stdout.strip():
            import json as _json
            data = _json.loads(r.stdout.strip())
            if isinstance(data, dict):
                data = [data]
            for svc in data:
                display = svc.get("DisplayName", "")
                name    = svc.get("Name", "")
                # Skip system services
                if any(display.startswith(p) for p in system_prefixes):
                    continue
                services.append({
                    "name":        name,
                    "status":      "running",
                    "description": display,
                    "type":        "windows_service",
                })
    except Exception:
        pass

    return services[:100]


def discover_containers_windows():
    """
    Discover running Docker containers on Windows.
    Returns list of dicts: {name, image, status, ports, type, container_id}
    """
    import subprocess
    containers = []

    try:
        r = subprocess.run(
            ["docker", "ps", "--format",
             "{{.ID}}\t{{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}"],
            capture_output=True, text=True, timeout=10
        )
        if r.returncode == 0 and r.stdout.strip():
            for line in r.stdout.splitlines():
                parts = line.split('\t')
                if len(parts) < 4:
                    continue
                containers.append({
                    "name":         parts[1] if len(parts) > 1 else "",
                    "image":        parts[2] if len(parts) > 2 else "",
                    "status":       parts[3] if len(parts) > 3 else "",
                    "ports":        parts[4] if len(parts) > 4 else "",
                    "type":         "docker",
                    "container_id": parts[0][:12],
                })
    except FileNotFoundError:
        pass
    except Exception:
        pass

    return containers[:50]


def collect_discovered_services_windows():
    """
    Collect all discovered services on Windows.
    Returns a dict with all categories.
    """
    return {
        "listening_ports":    discover_listening_ports_windows(),
        "systemd_services":   discover_windows_services(),
        "containers":         discover_containers_windows(),
    }


# ── HTTP POST ─────────────────────────────────────────────────────────────────

def post_metrics(url, token, metrics, verify_ssl=False):
    endpoint = url.rstrip("/") + "/api/agent/heartbeat"
    data     = json.dumps(metrics).encode("utf-8")
    req      = urllib.request.Request(
        endpoint,
        data    = data,
        headers = {
            "Content-Type":  "application/json",
            "Authorization": f"Bearer {token}",
            "User-Agent":    "CROIT-Agent-Windows/2.0",
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

def main():
    parser = argparse.ArgumentParser(description="CROIT Windows Server Agent v2")
    parser.add_argument("--url",            required=True)
    parser.add_argument("--token",          required=True)
    parser.add_argument("--verify-ssl",     action="store_true", default=False)
    parser.add_argument("--once",           action="store_true", default=False)
    parser.add_argument("--interval",       type=int, default=60)
    parser.add_argument("--patch-interval", type=int, default=60,
                        help="Patch collection interval in minutes (default: 60)")
    args = parser.parse_args()

    print(f"[CROIT Agent v2] Starting — reporting to {args.url}")
    print(f"[CROIT Agent v2] Hostname: {socket.gethostname()}")
    print(f"[CROIT Agent v2] OS: {platform.system()} {platform.version()}")

    patch_interval_s = args.patch_interval * 60
    last_patch_time  = 0  # 0 forces immediate collection on first run
    cached_patch     = {"pending_updates": None, "reboot_required": None, "patch_status": None}

    # Software collection interval: every 60 minutes
    sw_interval_s   = 3600
    last_sw_time    = 0   # 0 forces immediate collection on first run
    cached_software = []

    # Service discovery interval: every 5 minutes
    svc_interval_s    = 300
    last_svc_time     = 0   # 0 forces immediate collection on first run
    cached_services   = {}

    while True:
        try:
            # Refresh patch metrics if interval has elapsed (or first run)
            if time.time() - last_patch_time >= patch_interval_s:
                patch_data = collect_patch_metrics()
                # Merge reboot_required into cached dict (already included in collect_patch_metrics)
                cached_patch    = patch_data
                last_patch_time = time.time()

            # Refresh installed software if interval has elapsed (or first run)
            if time.time() - last_sw_time >= sw_interval_s:
                cached_software = collect_installed_software_windows()
                last_sw_time    = time.time()
                print(f"[CROIT Agent v2] Collected {len(cached_software)} installed software entries")

            # Refresh discovered services if interval has elapsed (or first run)
            if time.time() - last_svc_time >= svc_interval_s:
                cached_services = collect_discovered_services_windows()
                last_svc_time   = time.time()
                port_count = len(cached_services.get("listening_ports", []))
                svc_count  = len(cached_services.get("systemd_services", []))
                ctr_count  = len(cached_services.get("containers", []))
                print(f"[CROIT Agent v2] Discovered services: {port_count} ports, {svc_count} win-services, {ctr_count} containers")

            metrics = collect_metrics()
            metrics.update(cached_patch)
            metrics["installed_software"]   = cached_software
            metrics["discovered_services"]  = cached_services

            ok, result = post_metrics(args.url, args.token, metrics, args.verify_ssl)
            ts = time.strftime("%Y-%m-%d %H:%M:%S")
            if ok:
                mounts_str = " | ".join(
                    f"{m['mount']}:{m['pct']}%({m['disk_type']})"
                    for m in metrics.get("disk_mounts", [])
                )
                print(f"[{ts}] OK — CPU:{metrics.get('cpu_pct')}%"
                      f"({metrics.get('cpu_cores')}c/{metrics.get('cpu_threads')}t) "
                      f"RAM:{metrics.get('ram_pct')}% "
                      f"Disks:[{mounts_str}] "
                      f"Patches:{metrics.get('patch_status','?')}({metrics.get('pending_updates','?')})")
            else:
                print(f"[{ts}] ERROR — {result}", file=sys.stderr)
        except Exception as e:
            print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] EXCEPTION — {e}", file=sys.stderr)

        if args.once:
            break
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
