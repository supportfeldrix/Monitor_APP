#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
CROIT Uptime Monitor - Linux Server Agent v2 (Python 2.7 compatible)
Collects OS, CPU, RAM, disk mounts, uptime metrics and POSTs to the monitoring app.

Usage:
    python agent_py27.py --url https://frm-rbautodev01:9443 --token YOUR_TOKEN --once

Install as cron (every 60s):
    * * * * * python /opt/wso2/agent_monitor/agent_py27.py \
        --url https://frm-rbautodev01:9443 \
        --token YOUR_TOKEN --once >> /opt/wso2/agent_monitor/agent.log 2>&1
"""

from __future__ import print_function
import argparse
import json
import os
import platform
import socket
import ssl
import subprocess
import sys
import time

# Python 2/3 compatible HTTP
try:
    import urllib2 as urllib_request
    def make_request(url, data, headers):
        req = urllib_request.Request(url, data, headers)
        return req
    def urlopen(req, ctx, timeout):
        return urllib_request.urlopen(req, context=ctx, timeout=timeout)
except ImportError:
    import urllib.request as urllib_request
    def make_request(url, data, headers):
        req = urllib_request.Request(url, data=data, headers=headers, method="POST")
        return req
    def urlopen(req, ctx, timeout):
        return urllib_request.urlopen(req, context=ctx, timeout=timeout)

# ── OS Info ───────────────────────────────────────────────────────────────────

def get_os_info():
    os_name    = platform.system()
    os_version = ""
    kernel     = platform.release()
    try:
        with open("/etc/os-release") as f:
            data = {}
            for line in f:
                line = line.strip()
                if "=" in line:
                    k, v = line.split("=", 1)
                    data[k] = v.strip('"')
        os_name    = data.get("NAME", os_name)
        os_version = data.get("VERSION_ID", data.get("VERSION", ""))
    except Exception:
        pass
    return os_name, os_version, kernel


# ── CPU ───────────────────────────────────────────────────────────────────────

def get_cpu_info():
    def read_stat():
        with open("/proc/stat") as f:
            line = f.readline()
        vals = list(map(int, line.split()[1:]))
        return vals[3], sum(vals)

    try:
        idle1, total1 = read_stat()
        time.sleep(0.5)
        idle2, total2 = read_stat()
        diff_idle  = idle2 - idle1
        diff_total = total2 - total1
        cpu_pct = round((1.0 - float(diff_idle) / diff_total) * 100, 1) if diff_total else 0.0
    except Exception:
        cpu_pct = None

    cpu_cores   = None
    cpu_threads = None
    try:
        cores_set    = set()
        thread_count = 0
        with open("/proc/cpuinfo") as f:
            current_core = None
            current_phys = None
            for line in f:
                line = line.strip()
                if line.startswith("physical id"):
                    current_phys = line.split(":")[1].strip()
                elif line.startswith("core id"):
                    current_core = line.split(":")[1].strip()
                elif line.startswith("processor"):
                    thread_count += 1
                if current_phys is not None and current_core is not None:
                    cores_set.add((current_phys, current_core))
                    current_phys = None
                    current_core = None
        cpu_cores   = len(cores_set) if cores_set else thread_count
        cpu_threads = thread_count
    except Exception:
        pass

    return cpu_pct, cpu_cores, cpu_threads


# ── RAM ───────────────────────────────────────────────────────────────────────

def get_ram():
    mem = {}
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 2:
                    mem[parts[0].rstrip(":")] = int(parts[1])
    except Exception:
        return None, None, None

    total_kb     = mem.get("MemTotal", 0)
    available_kb = mem.get("MemAvailable", mem.get("MemFree", 0))
    used_kb      = total_kb - available_kb
    total_gb = round(total_kb / 1024.0 / 1024.0, 2)
    used_gb  = round(used_kb  / 1024.0 / 1024.0, 2)
    pct      = round(float(used_kb) / total_kb * 100, 1) if total_kb else 0
    return total_gb, used_gb, pct


# ── Disk Mounts ───────────────────────────────────────────────────────────────

INTERESTING_MOUNTS = {"/", "/var", "/data", "/home", "/opt", "/tmp", "/boot"}

def get_disk_type(device):
    try:
        import re
        dev = os.path.basename(device)
        dev = re.sub(r'p?\d+$', '', dev)
        if device.startswith("/dev/mapper") or device.startswith("/dev/dm-"):
            return "Virtual"
        if device.startswith("/dev/vd"):
            return "Virtual"
        rotational_path = "/sys/block/%s/queue/rotational" % dev
        if os.path.exists(rotational_path):
            with open(rotational_path) as f:
                val = f.read().strip()
            return "HDD" if val == "1" else "SSD"
    except Exception:
        pass
    return "Virtual"


def get_disk_mounts():
    mounts = []
    seen   = set()
    try:
        with open("/proc/mounts") as f:
            for line in f:
                parts = line.split()
                if len(parts) < 3:
                    continue
                device, mount, fstype = parts[0], parts[1], parts[2]
                if fstype in ("tmpfs", "devtmpfs", "sysfs", "proc", "cgroup",
                              "cgroup2", "pstore", "debugfs", "securityfs",
                              "hugetlbfs", "mqueue", "fusectl", "binfmt_misc"):
                    continue
                if mount in seen:
                    continue
                if mount not in INTERESTING_MOUNTS and not device.startswith("/dev/"):
                    continue
                seen.add(mount)
                try:
                    st       = os.statvfs(mount)
                    total_gb = round(st.f_blocks * st.f_frsize / 1024.0**3, 1)
                    free_gb  = round(st.f_bfree  * st.f_frsize / 1024.0**3, 1)
                    used_gb  = round(total_gb - free_gb, 1)
                    pct      = round(used_gb / total_gb * 100, 1) if total_gb > 0 else 0
                    disk_type = get_disk_type(device) if device.startswith("/dev/") else "Virtual"
                    mounts.append({
                        "mount":     mount,
                        "device":    device,
                        "total_gb":  total_gb,
                        "used_gb":   used_gb,
                        "free_gb":   free_gb,
                        "pct":       pct,
                        "disk_type": disk_type,
                    })
                except Exception:
                    pass
    except Exception:
        pass
    mounts.sort(key=lambda m: (0 if m["mount"] == "/" else 1, m["mount"]))
    return mounts


# ── Uptime / Load / Processes ─────────────────────────────────────────────────

def get_uptime():
    try:
        with open("/proc/uptime") as f:
            return int(float(f.read().split()[0]))
    except Exception:
        return None


def get_load():
    try:
        with open("/proc/loadavg") as f:
            parts = f.read().split()
        return float(parts[0]), float(parts[1]), float(parts[2])
    except Exception:
        return None, None, None


def get_process_count():
    try:
        return len([d for d in os.listdir("/proc") if d.isdigit()])
    except Exception:
        return None


# ── Patch Metrics ─────────────────────────────────────────────────────────────

def collect_patch_metrics_linux():
    """Collect patch metrics - Python 2.7 compatible."""
    try:
        distro_id      = ""
        distro_id_like = ""
        try:
            with open("/etc/os-release") as f:
                for line in f:
                    line = line.strip()
                    if "=" in line:
                        k, v = line.split("=", 1)
                        v = v.strip('"').lower()
                        if k == "ID":
                            distro_id = v
                        elif k == "ID_LIKE":
                            distro_id_like = v
        except Exception:
            pass

        combined      = distro_id + " " + distro_id_like
        is_debian     = any(x in combined for x in ("debian", "ubuntu"))
        is_rhel       = any(x in combined for x in ("rhel", "centos", "fedora"))

        pending_updates = None
        has_security    = False

        if is_debian:
            try:
                proc = subprocess.Popen(
                    ["apt", "list", "--upgradable"],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE
                )
                out, _ = proc.communicate()
                lines = [l for l in out.decode("utf-8", errors="replace").splitlines()
                         if "upgradable" in l.lower()]
                pending_updates = len(lines)
                has_security    = any("security" in l.lower() for l in lines)
            except Exception as e:
                print("[Agent] WARNING: apt list failed: %s" % e, file=sys.stderr)

        elif is_rhel:
            pkg_cmd = "dnf" if os.path.exists("/usr/bin/dnf") else "yum"
            try:
                proc = subprocess.Popen(
                    [pkg_cmd, "check-update", "--cacheonly", "-q"],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE
                )
                out, _ = proc.communicate()
                lines = [l for l in out.decode("utf-8", errors="replace").splitlines()
                         if l and l[0].isalpha()
                         and not l.startswith("Last")
                         and not l.startswith("Loaded")]
                pending_updates = len(lines)
            except Exception as e:
                print("[Agent] WARNING: %s check-update failed: %s" % (pkg_cmd, e), file=sys.stderr)

        if pending_updates is None:
            patch_status = None
        elif pending_updates == 0:
            patch_status = "up_to_date"
        elif has_security:
            patch_status = "critical"
        else:
            patch_status = "updates_pending"

        reboot_required = os.path.exists("/var/run/reboot-required")

        return {
            "pending_updates": pending_updates,
            "reboot_required": reboot_required,
            "patch_status":    patch_status,
        }

    except Exception as e:
        print("[Agent] WARNING: collect_patch_metrics_linux failed: %s" % e, file=sys.stderr)
        return {"pending_updates": None, "reboot_required": None, "patch_status": None}


# ── Collect all ───────────────────────────────────────────────────────────────

def collect_metrics():
    os_name, os_version, kernel = get_os_info()
    cpu_pct, cpu_cores, cpu_threads = get_cpu_info()
    ram_total, ram_used, ram_pct    = get_ram()
    disk_mounts                     = get_disk_mounts()
    uptime_sec                      = get_uptime()
    load_1m, load_5m, load_15m      = get_load()
    process_count                   = get_process_count()

    root       = next((m for m in disk_mounts if m["mount"] == "/"), None)
    disk_total = root["total_gb"] if root else None
    disk_used  = root["used_gb"]  if root else None
    disk_pct   = root["pct"]      if root else None

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
        "load_1m":       load_1m,
        "load_5m":       load_5m,
        "load_15m":      load_15m,
        "process_count": process_count,
    }


# ── Installed Software ────────────────────────────────────────────────────────

def collect_installed_software_linux():
    """
    Collect installed packages via dpkg or rpm.
    Python 2.7 compatible. Returns list of dicts: {name, version, vendor}.
    Capped at 500 packages.
    """
    packages = []

    distro_id = ""
    try:
        with open("/etc/os-release") as f:
            for line in f:
                line = line.strip()
                if "=" in line:
                    k, v = line.split("=", 1)
                    if k == "ID":
                        distro_id = v.strip('"').lower()
    except Exception:
        pass

    is_debian = distro_id in ("debian", "ubuntu", "linuxmint", "pop")
    is_rhel   = distro_id in ("rhel", "centos", "fedora", "rocky", "almalinux", "ol")

    if not is_debian and not is_rhel:
        if os.path.exists("/usr/bin/dpkg") or os.path.exists("/bin/dpkg"):
            is_debian = True
        elif os.path.exists("/usr/bin/rpm") or os.path.exists("/bin/rpm"):
            is_rhel = True

    if is_debian:
        try:
            proc = subprocess.Popen(
                ["dpkg-query", "-W", "-f=${Package}\t${Version}\t${Maintainer}\n"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
            out, _ = proc.communicate()
            for line in out.decode("utf-8", errors="replace").splitlines():
                parts = line.split("\t")
                if len(parts) >= 2 and parts[0].strip():
                    name   = parts[0].strip()
                    ver    = parts[1].strip() if len(parts) > 1 else ""
                    vendor = parts[2].strip() if len(parts) > 2 else ""
                    if "<" in vendor:
                        vendor = vendor.split("<")[0].strip()
                    packages.append({"name": name, "version": ver, "vendor": vendor})
        except Exception as e:
            print("[Agent] WARNING: dpkg-query failed: %s" % e, file=sys.stderr)

    elif is_rhel:
        try:
            proc = subprocess.Popen(
                ["rpm", "-qa", "--queryformat", "%{NAME}\t%{VERSION}-%{RELEASE}\t%{VENDOR}\n"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
            out, _ = proc.communicate()
            for line in out.decode("utf-8", errors="replace").splitlines():
                parts = line.split("\t")
                if len(parts) >= 1 and parts[0].strip():
                    name   = parts[0].strip()
                    ver    = parts[1].strip() if len(parts) > 1 else ""
                    vendor = parts[2].strip() if len(parts) > 2 else ""
                    if vendor.lower() in ("(none)", "none", ""):
                        vendor = ""
                    packages.append({"name": name, "version": ver, "vendor": vendor})
        except Exception as e:
            print("[Agent] WARNING: rpm -qa failed: %s" % e, file=sys.stderr)

    return packages[:500]


# ── HTTP POST ─────────────────────────────────────────────────────────────────

def post_metrics(url, token, metrics, verify_ssl=False):
    endpoint = url.rstrip("/") + "/api/agent/heartbeat"
    data     = json.dumps(metrics).encode("utf-8")
    headers  = {
        "Content-Type":  "application/json",
        "Authorization": "Bearer %s" % token,
        "User-Agent":    "CROIT-Agent/2.0",
    }
    req = make_request(endpoint, data, headers)
    ctx = ssl.create_default_context()
    if not verify_ssl:
        ctx.check_hostname = False
        ctx.verify_mode    = ssl.CERT_NONE
    try:
        resp = urlopen(req, ctx, 10)
        return True, json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return False, str(e)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="CROIT Server Agent v2 (Python 2.7)")
    parser.add_argument("--url",            required=True)
    parser.add_argument("--token",          required=True)
    parser.add_argument("--verify-ssl",     action="store_true", default=False)
    parser.add_argument("--once",           action="store_true", default=False)
    parser.add_argument("--interval",       type=int, default=60)
    parser.add_argument("--patch-interval", type=int, default=60)
    args = parser.parse_args()

    print("[CROIT Agent v2] Starting - reporting to %s" % args.url)
    print("[CROIT Agent v2] Hostname: %s" % socket.gethostname())

    patch_interval_s = args.patch_interval * 60
    last_patch_time  = 0
    cached_patch     = {"pending_updates": None, "reboot_required": None, "patch_status": None}

    sw_interval_s   = 3600
    last_sw_time    = 0
    cached_software = []

    while True:
        try:
            if time.time() - last_patch_time >= patch_interval_s:
                cached_patch    = collect_patch_metrics_linux()
                last_patch_time = time.time()

            if time.time() - last_sw_time >= sw_interval_s:
                cached_software = collect_installed_software_linux()
                last_sw_time    = time.time()
                print("[CROIT Agent v2] Collected %d installed packages" % len(cached_software))

            metrics = collect_metrics()
            metrics.update(cached_patch)
            metrics["installed_software"] = cached_software

            ok, result = post_metrics(args.url, args.token, metrics, args.verify_ssl)
            ts = time.strftime("%Y-%m-%d %H:%M:%S")
            if ok:
                mounts_str = " | ".join(
                    "%s:%s%%(%s)" % (m["mount"], m["pct"], m["disk_type"])
                    for m in metrics.get("disk_mounts", [])
                )
                print("[%s] OK - CPU:%s%%(%sc/%st) RAM:%s%% Disks:[%s] Load:%s Patches:%s(%s)" % (
                    ts, metrics["cpu_pct"], metrics["cpu_cores"], metrics["cpu_threads"],
                    metrics["ram_pct"], mounts_str, metrics["load_1m"],
                    metrics.get("patch_status", "?"), metrics.get("pending_updates", "?")
                ))
            else:
                print("[%s] ERROR - %s" % (ts, result), file=sys.stderr)
        except Exception as e:
            print("[%s] EXCEPTION - %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), e), file=sys.stderr)

        if args.once:
            break
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
