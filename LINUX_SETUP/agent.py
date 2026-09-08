#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CROIT Uptime Monitor - Linux Server Agent v2
Collects OS, CPU, RAM, disk mounts, disk type, uptime metrics and POSTs to the monitoring app.

Usage:
    python3 agent.py --url https://frm-rbautodev01:9443 --token YOUR_TOKEN

Install as cron (every 60s):
    * * * * * python3 /home/f5151422/agent.py \
        --url https://frm-rbautodev01:9443 \
        --token YOUR_TOKEN --once >> /home/f5151422/agent.log 2>&1
"""

import argparse
import json
import os
import platform
import socket
import sys
import time
import urllib.request
import urllib.error
import ssl

# ── OS Info ──────────────────────────────────────────────────────────────────

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
    """Returns (cpu_pct, cpu_cores, cpu_threads)."""
    # CPU usage
    def read_stat():
        with open("/proc/stat") as f:
            line = f.readline()
        vals = list(map(int, line.split()[1:]))
        return vals[3], sum(vals)  # idle, total

    try:
        idle1, total1 = read_stat()
        time.sleep(0.5)
        idle2, total2 = read_stat()
        diff_idle  = idle2 - idle1
        diff_total = total2 - total1
        cpu_pct = round((1 - diff_idle / diff_total) * 100, 1) if diff_total else 0.0
    except Exception:
        cpu_pct = None

    # CPU cores and threads from /proc/cpuinfo
    cpu_cores   = None
    cpu_threads = None
    try:
        cores_set   = set()
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
    total_gb = round(total_kb / 1024 / 1024, 2)
    used_gb  = round(used_kb  / 1024 / 1024, 2)
    pct      = round(used_kb / total_kb * 100, 1) if total_kb else 0
    return total_gb, used_gb, pct


# ── Disk Mounts ───────────────────────────────────────────────────────────────

INTERESTING_MOUNTS = {"/", "/var", "/data", "/home", "/opt", "/tmp", "/boot"}

def get_disk_type(device):
    """Detect SSD or HDD from /sys/block. Returns 'SSD', 'HDD', or 'Virtual'."""
    try:
        import re
        dev = os.path.basename(device)
        # Strip partition numbers: sda1 -> sda, nvme0n1p1 -> nvme0n1
        dev = re.sub(r'p?\d+$', '', dev)

        # LVM / device mapper / virtual
        if device.startswith("/dev/mapper") or device.startswith("/dev/dm-"):
            return "Virtual"
        if device.startswith("/dev/vd"):
            return "Virtual"  # KVM virtio disk

        rotational_path = f"/sys/block/{dev}/queue/rotational"
        if os.path.exists(rotational_path):
            with open(rotational_path) as f:
                val = f.read().strip()
            return "HDD" if val == "1" else "SSD"
    except Exception:
        pass
    return "Virtual"


def get_disk_mounts():
    """Return list of disk mount stats for interesting mount points."""
    mounts = []
    seen   = set()
    try:
        with open("/proc/mounts") as f:
            for line in f:
                parts = line.split()
                if len(parts) < 3:
                    continue
                device, mount, fstype = parts[0], parts[1], parts[2]
                # Skip non-real filesystems
                if fstype in ("tmpfs", "devtmpfs", "sysfs", "proc", "cgroup",
                              "cgroup2", "pstore", "debugfs", "securityfs",
                              "hugetlbfs", "mqueue", "fusectl", "binfmt_misc"):
                    continue
                if mount in seen:
                    continue
                # Only report interesting mounts or any real block device
                if mount not in INTERESTING_MOUNTS and not device.startswith("/dev/"):
                    continue
                seen.add(mount)
                try:
                    st = os.statvfs(mount)
                    total_gb = round(st.f_blocks * st.f_frsize / 1024**3, 1)
                    free_gb  = round(st.f_bfree  * st.f_frsize / 1024**3, 1)
                    used_gb  = round(total_gb - free_gb, 1)
                    pct      = round(used_gb / total_gb * 100, 1) if total_gb > 0 else 0
                    disk_type = get_disk_type(device) if device.startswith("/dev/") else "Virtual"
                    mounts.append({
                        "mount":      mount,
                        "device":     device,
                        "total_gb":   total_gb,
                        "used_gb":    used_gb,
                        "free_gb":    free_gb,
                        "pct":        pct,
                        "disk_type":  disk_type,
                    })
                except Exception:
                    pass
    except Exception:
        pass

    # Sort: root first, then alphabetical
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
    """
    Collect pending update count, reboot-required flag, and patch status for Linux.
    Returns {"pending_updates": int|None, "reboot_required": bool|None, "patch_status": str|None}
    """
    import subprocess
    try:
        # Detect distro family from /etc/os-release
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

        is_debian = any(x in (distro_id + " " + distro_id_like)
                        for x in ("debian", "ubuntu"))
        is_rhel   = any(x in (distro_id + " " + distro_id_like)
                        for x in ("rhel", "centos", "fedora", "suse", "opensuse"))

        pending_updates = None
        has_security    = False

        if is_debian:
            # Debian/Ubuntu: apt list --upgradable
            try:
                r = subprocess.run(
                    ["apt", "list", "--upgradable"],
                    capture_output=True, text=True, timeout=60
                )
                lines = [l for l in r.stdout.splitlines() if "upgradable" in l.lower()]
                pending_updates = len(lines)
                has_security    = any("security" in l.lower() for l in lines)
            except Exception as e:
                print(f"[Agent] WARNING: apt list failed: {e}", file=sys.stderr)

        elif is_rhel:
            # RHEL/CentOS/RHEL9: prefer dnf (RHEL8+), fall back to yum
            # Use --cacheonly to avoid slow network calls to repo servers
            pkg_cmd = "dnf" if os.path.exists("/usr/bin/dnf") else "yum"
            try:
                r = subprocess.run(
                    [pkg_cmd, "check-update", "--cacheonly", "-q"],
                    capture_output=True, text=True, timeout=30
                )
                # exits 100 when updates available, 0 when up-to-date, 1 on error
                lines = [l for l in r.stdout.splitlines()
                         if l and l[0].isalpha() and not l.startswith("Last")
                         and not l.startswith("Loaded") and not l.startswith("Loading")]
                pending_updates = len(lines)
            except subprocess.TimeoutExpired:
                print(f"[Agent] WARNING: {pkg_cmd} check-update timed out (cache miss — run '{pkg_cmd} makecache' on server)", file=sys.stderr)
            except Exception as e:
                print(f"[Agent] WARNING: {pkg_cmd} check-update failed: {e}", file=sys.stderr)

            # Detect security updates via dnf/yum updateinfo (cacheonly)
            try:
                r2 = subprocess.run(
                    [pkg_cmd, "updateinfo", "list", "security", "--cacheonly", "-q"],
                    capture_output=True, text=True, timeout=30
                )
                sec_lines = [l for l in r2.stdout.splitlines()
                             if l.strip() and not l.startswith("Last")
                             and not l.startswith("Loaded") and not l.startswith("Loading")]
                has_security = len(sec_lines) > 0
            except subprocess.TimeoutExpired:
                print(f"[Agent] WARNING: {pkg_cmd} updateinfo timed out", file=sys.stderr)
            except Exception as e:
                print(f"[Agent] WARNING: {pkg_cmd} updateinfo failed: {e}", file=sys.stderr)

        # Classify patch_status
        if pending_updates is None:
            patch_status = None
        elif pending_updates == 0:
            patch_status = "up_to_date"
        elif has_security:
            patch_status = "critical"
        else:
            patch_status = "updates_pending"

        # Detect reboot_required
        reboot_required = False
        try:
            if os.path.exists("/var/run/reboot-required"):
                reboot_required = True
        except Exception:
            reboot_required = None

        return {
            "pending_updates": pending_updates,
            "reboot_required": reboot_required,
            "patch_status":    patch_status,
        }

    except Exception as e:
        print(f"[Agent] WARNING: collect_patch_metrics_linux failed: {e}", file=sys.stderr)
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

    # Root disk for backward compat
    root = next((m for m in disk_mounts if m["mount"] == "/"), None)
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

def _is_linux_system_package(name, vendor):
    """
    Returns True if the package is a low-level OS/system component that should
    be excluded from the 3rd-party software inventory.

    Keeps: application-level software (databases, web servers, monitoring tools,
           language runtimes installed by the user, etc.)
    Filters: kernel, core OS libs, system daemons, distro infrastructure.
    """
    name_lower   = name.lower()
    vendor_lower = (vendor or "").lower()

    # ── Vendor-based exclusions ───────────────────────────────────────────────
    # Packages shipped by the distro itself are OS components, not 3rd-party.
    # NOTE: We do NOT blanket-exclude Red Hat here because Red Hat also ships
    # legitimate 3rd-party tools like Ansible, Podman, Buildah, Skopeo, etc.
    distro_vendors = (
        "ubuntu developers",
        "debian",
        "centos",
        "fedora project",
        "rocky enterprise software foundation",
        "almalinux",
        "oracle america",
        "suse llc",
        "opensuse",
    )
    if any(vendor_lower.startswith(v) for v in distro_vendors):
        return True

    # ── Explicit 3rd-party allowlist — never filter these regardless of vendor ─
    # These are user-installed tools that may be packaged by Red Hat / distro
    # but are genuine applications worth tracking.
    third_party_allowlist = {
        "ansible", "ansible-core", "ansible-lint",
        "podman", "podman-compose", "podman-docker",
        "buildah", "skopeo", "cri-o",
        "docker", "docker-ce", "docker-compose",
        "jenkins", "jenkins-lts",
        "chef", "puppet", "salt",
        "terraform", "vault", "consul",
        "nginx", "httpd", "apache2",
        "postgresql", "postgresql-server", "mysql", "mariadb", "mongodb",
        "redis", "memcached", "rabbitmq", "kafka",
        "java", "java-11-openjdk", "java-17-openjdk", "java-21-openjdk",
        "nodejs", "npm",
        "python3", "python39", "python310", "python311",
        "graylog", "graylog-sidecar",
        "wso2", "wso2am",
        "mdatp",
        "check-mk-agent", "checkmk-agent",
        "zabbix-agent", "zabbix-agent2",
        "prometheus", "grafana", "alertmanager",
        "elasticsearch", "kibana", "logstash", "filebeat", "metricbeat",
        "gitlab-runner", "github-actions-runner",
        "helm", "kubectl", "oc",
        "git",
    }
    if name_lower in third_party_allowlist:
        return False  # always keep these

    # ── Name-based prefix exclusions ─────────────────────────────────────────
    system_prefixes = (
        "lib",          # shared libraries (libssl, libpython, libgcc, …)
        "linux-",       # kernel images and headers
        "kernel",       # kernel packages on RPM distros
        "glibc",        # GNU C library
        "gcc-",         # compiler toolchain
        "binutils",
        "coreutils",
        "util-linux",
        "systemd",
        "dbus",
        "udev",
        "grub",
        "dracut",
        "initramfs",
        "plymouth",
        "selinux",
        "apparmor",
        "audit",
        "pam",          # PAM authentication modules
        "nspr",
        "nss",          # Network Security Services (OS-level)
        "ca-certificates",
        "tzdata",
        "locales",
        "base-files",
        "base-passwd",
        "debianutils",
        "dpkg",
        "apt",
        "rpm",
        "yum",
        "dnf",
        "zypper",
        "update-",      # update-alternatives, update-manager-core, …
        "python3-",     # distro-bundled Python modules (not user-installed)
        "python2-",
        "perl-",        # distro-bundled Perl modules
        "perl5",
        "ruby-",        # distro-bundled Ruby gems
        "fonts-",       # system fonts
        "xfonts-",
        "gsfonts",
        "ucf",
        "debconf",
        "adduser",
        "passwd",
        "shadow",
        "login",
        "mount",
        "procps",
        "psmisc",
        "sysvinit",
        "insserv",
        "lsb-",
        "os-prober",
        "ifupdown",
        "iproute2",
        "iptables",
        "nftables",
        "netbase",
        "network-manager",
        "resolvconf",
        "acl",
        "attr",
        "e2fsprogs",
        "xfsprogs",
        "btrfs-",
        "lvm2",
        "mdadm",
        "multipath-",
        "device-mapper",
        "dmsetup",
        "cryptsetup",
        "keyutils",
        "kmod",
        "module-init-tools",
        "usbutils",
        "pciutils",
        "dmidecode",
        "hdparm",
        "smartmontools",
        "irqbalance",
        "numactl",
        "tuned",
        "cpupowerutils",
        "microcode",
        "firmware-",
        "linux-firmware",
        "alsa-",
        "pulseaudio",
        "dconf",
        "gconf",
        "gsettings-",
        "glib",
        "glib2",
        "gtk",
        "pango",
        "cairo",
        "harfbuzz",
        "freetype",
        "fontconfig",
        "pixman",
        "at-spi",
        "dbus-glib",
        "polkit",
        "udisks",
        "upower",
        "colord",
        "cups",
        "avahi",
        "nss-mdns",
        "libnss",
        "krb5",
        "openldap",
        "cyrus-sasl",
        "openssl",      # OS-level TLS library (not an app)
        "zlib",
        "bzip2",
        "xz-utils",
        "lz4",
        "zstd",
        "tar",
        "gzip",
        "cpio",
        "diffutils",
        "findutils",
        "grep",
        "sed",
        "gawk",
        "bash",
        "dash",
        "tcsh",
        "zsh",
        "readline",
        "ncurses",
        "terminfo",
        "less",
        "man-",
        "manpages",
        "info",
        "texinfo",
        "gettext",
        "intltool",
        "po-debconf",
        "sensible-utils",
        "mime-support",
        "shared-mime-info",
        "xdg-",
        "desktop-file-utils",
        "hicolor-icon-theme",
        "adwaita-icon-theme",
        "gnome-",
        "kde-",
        "xorg-",
        "x11-",
        "xserver-",
        "mesa-",
        "libdrm",
        "libva",
        "libvdpau",
        "vulkan-",
        "wayland",
        "weston",
        "mutter",
        "compiz",
        "accountsservice",
        "packagekit",
        "snapd",
        "flatpak",
        "fwupd",
    )
    if any(name_lower.startswith(p) for p in system_prefixes):
        return True

    # ── Exact name exclusions ─────────────────────────────────────────────────
    system_exact = {
        "bash", "dash", "sh", "zsh", "tcsh", "fish",
        "coreutils", "util-linux", "procps", "psmisc",
        "grep", "sed", "gawk", "awk", "tar", "gzip", "bzip2",
        "less", "more", "nano", "vi", "vim-tiny",
        "login", "passwd", "shadow-utils", "sudo",
        "mount", "umount", "fdisk", "parted",
        "ip", "ss", "ping", "traceroute", "netstat",
        "curl", "wget",   # often system-level on servers; keep if you want them
        "openssl",
        "ca-certificates",
        "tzdata",
        "hostname",
        "dbus",
        "systemd",
        "udev",
        "syslog",
        "rsyslog",
        "logrotate",
        "cron",
        "cronie",
        "at",
        "acpid",
        "lvm2",
        "mdadm",
        "e2fsprogs",
        "xfsprogs",
        "dosfstools",
        "ntfs-3g",
        "nfs-common",
        "nfs-utils",
        "rpcbind",
        "portmap",
        "isc-dhcp-client",
        "dhclient",
        "dhcpcd5",
        "ifupdown",
        "iproute2",
        "iptables",
        "nftables",
        "firewalld",
        "ufw",
        "openssh-client",
        "openssh-server",
        "openssh",
        "sudo",
        "polkit",
        "pam",
        "nscd",
        "sssd",
        "realmd",
        "oddjob",
        "samba-common",
        "krb5-workstation",
        "authconfig",
        "authselect",
        "selinux-policy",
        "selinux-policy-targeted",
        "setroubleshoot",
        "audit",
        "auditd",
        "aide",
        "dracut",
        "grub2",
        "grub2-common",
        "grub2-tools",
        "shim",
        "shim-x64",
        "mokutil",
        "efibootmgr",
        "microcode_ctl",
        "irqbalance",
        "tuned",
        "numad",
        "cpupowerutils",
        "smartmontools",
        "hdparm",
        "dmidecode",
        "pciutils",
        "usbutils",
        "kmod",
        "dkms",
        "fwupdate",
        "fwupd",
        "snapd",
        "flatpak",
        "packagekit",
        "rpm",
        "rpm-libs",
        "rpm-build-libs",
        "dnf",
        "dnf-data",
        "yum",
        "apt",
        "apt-utils",
        "dpkg",
        "debconf",
        "debianutils",
        "adduser",
        "base-files",
        "base-passwd",
        "sensible-utils",
        "mime-support",
        "lsb-release",
        "lsb-base",
    }
    if name_lower in system_exact:
        return True

    return False


def collect_installed_software_linux():
    """
    Collect 3rd-party installed packages via dpkg (Debian/Ubuntu) or rpm (RHEL/CentOS).
    Excludes OS-level system packages, shared libraries, and distro infrastructure.
    Returns a list of dicts: {name, version, vendor}.
    Capped at 500 packages to keep payload size reasonable.
    """
    import subprocess

    packages = []

    # Detect distro
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
        # Fallback: try dpkg first, then rpm
        if os.path.exists("/usr/bin/dpkg") or os.path.exists("/bin/dpkg"):
            is_debian = True
        elif os.path.exists("/usr/bin/rpm") or os.path.exists("/bin/rpm"):
            is_rhel = True

    if is_debian:
        try:
            r = subprocess.run(
                ["dpkg-query", "-W", "-f=${Package}\t${Version}\t${Maintainer}\n"],
                capture_output=True, text=True, timeout=30
            )
            for line in r.stdout.splitlines():
                parts = line.split("\t")
                if len(parts) >= 2 and parts[0].strip():
                    name    = parts[0].strip()
                    version = parts[1].strip() if len(parts) > 1 else ""
                    vendor  = parts[2].strip() if len(parts) > 2 else ""
                    # Shorten vendor to just the org name
                    if "<" in vendor:
                        vendor = vendor.split("<")[0].strip()
                    # Skip OS system packages — only keep 3rd-party software
                    if _is_linux_system_package(name, vendor):
                        continue
                    packages.append({"name": name, "version": version, "vendor": vendor})
        except Exception as e:
            print(f"[Agent] WARNING: dpkg-query failed: {e}", file=sys.stderr)

    elif is_rhel:
        try:
            r = subprocess.run(
                ["rpm", "-qa", "--queryformat", "%{NAME}\t%{VERSION}-%{RELEASE}\t%{VENDOR}\n"],
                capture_output=True, text=True, timeout=30
            )
            for line in r.stdout.splitlines():
                parts = line.split("\t")
                if len(parts) >= 1 and parts[0].strip():
                    name    = parts[0].strip()
                    version = parts[1].strip() if len(parts) > 1 else ""
                    vendor  = parts[2].strip() if len(parts) > 2 else ""
                    if vendor.lower() in ("(none)", "none", ""):
                        vendor = ""
                    # Skip OS system packages — only keep 3rd-party software
                    if _is_linux_system_package(name, vendor):
                        continue
                    packages.append({"name": name, "version": version, "vendor": vendor})
        except Exception as e:
            print(f"[Agent] WARNING: rpm -qa failed: {e}", file=sys.stderr)

    # Cap at 500 packages
    return packages[:500]


# ── Service Discovery ─────────────────────────────────────────────────────────

def discover_listening_ports():
    """
    Discover services listening on TCP ports.
    Strategy:
      1. Parse /proc/net/tcp directly (no root needed to see ports)
      2. Try to resolve process names via /proc/<pid>/fd (works for own processes)
      3. Fall back to ss/netstat output for process names where available
    Returns list of dicts: {port, protocol, address, pid, process, state}
    """
    import subprocess
    import re
    services = []
    seen_ports = set()

    # ── Method 1: Parse /proc/net/tcp for ALL listening ports ─────────────────
    # This always works without root — shows all listening ports on the system
    port_to_inode = {}
    try:
        for proto_file in ["/proc/net/tcp", "/proc/net/tcp6"]:
            if not os.path.exists(proto_file):
                continue
            with open(proto_file) as f:
                for line in f.readlines()[1:]:  # skip header
                    parts = line.split()
                    if len(parts) < 10:
                        continue
                    state = parts[3]
                    if state != "0A":  # 0A = LISTEN
                        continue
                    local = parts[1]
                    addr_hex, port_hex = local.split(":")
                    port = int(port_hex, 16)
                    if port in seen_ports:
                        continue
                    seen_ports.add(port)
                    inode = parts[9]
                    # Decode address
                    if len(addr_hex) == 8:
                        # IPv4
                        addr_int = int(addr_hex, 16)
                        addr = f"{addr_int & 0xFF}.{(addr_int >> 8) & 0xFF}.{(addr_int >> 16) & 0xFF}.{(addr_int >> 24) & 0xFF}"
                    else:
                        addr = "::"  # IPv6 simplified
                    port_to_inode[port] = {"addr": addr, "inode": inode}
                    services.append({
                        "port":     port,
                        "protocol": "tcp",
                        "address":  addr,
                        "pid":      None,
                        "process":  "",
                        "state":    "LISTEN",
                    })
    except Exception:
        pass

    # ── Method 2: Map inodes to PIDs/process names via /proc ──────────────────
    # Walk /proc/<pid>/fd to find socket inodes — works for accessible processes
    inode_to_pid = {}
    try:
        for pid_dir in os.listdir("/proc"):
            if not pid_dir.isdigit():
                continue
            fd_dir = f"/proc/{pid_dir}/fd"
            try:
                for fd in os.listdir(fd_dir):
                    try:
                        link = os.readlink(f"{fd_dir}/{fd}")
                        if link.startswith("socket:["):
                            inode = link[8:-1]
                            inode_to_pid[inode] = int(pid_dir)
                    except (PermissionError, FileNotFoundError, OSError):
                        continue
            except (PermissionError, FileNotFoundError, OSError):
                continue
    except Exception:
        pass

    # Get process names for resolved PIDs
    pid_to_name = {}
    for inode, pid in inode_to_pid.items():
        if pid not in pid_to_name:
            try:
                with open(f"/proc/{pid}/comm") as f:
                    pid_to_name[pid] = f.read().strip()
            except (PermissionError, FileNotFoundError, OSError):
                pid_to_name[pid] = ""

    # Match ports to processes
    for svc in services:
        port_info = port_to_inode.get(svc["port"])
        if port_info:
            inode = port_info["inode"]
            if inode in inode_to_pid:
                pid = inode_to_pid[inode]
                svc["pid"] = pid
                svc["process"] = pid_to_name.get(pid, "")

    # ── Method 3: Try ss -tlnp as supplement (may get more process names) ─────
    try:
        r = subprocess.run(
            ["ss", "-tlnp"],
            capture_output=True, text=True, timeout=10
        )
        if r.returncode == 0:
            for line in r.stdout.splitlines()[1:]:
                parts = line.split()
                if len(parts) < 5:
                    continue
                local = parts[3]
                if ']:' in local:
                    _, port_str = local.rsplit(':', 1)
                else:
                    _, port_str = local.rsplit(':', 1)
                try:
                    port = int(port_str)
                except ValueError:
                    continue
                # Only update if we don't already have a process name
                svc_match = next((s for s in services if s["port"] == port), None)
                if svc_match and not svc_match["process"]:
                    for p in parts:
                        if 'users:' in p or '((' in p:
                            try:
                                m = re.search(r'\(\("([^"]+)",pid=(\d+)', p)
                                if m:
                                    svc_match["process"] = m.group(1)
                                    svc_match["pid"] = int(m.group(2))
                            except Exception:
                                pass
    except Exception:
        pass

    # ── Method 4: Well-known port labels as fallback ──────────────────────────
    WELL_KNOWN_PORTS = {
        22: "sshd", 25: "smtp", 53: "dns", 80: "httpd", 110: "pop3",
        143: "imap", 443: "https", 465: "smtps", 587: "submission",
        993: "imaps", 995: "pop3s",
        1433: "mssql", 1521: "oracle", 1556: "veritas-pbx",
        1557: "veritas", 2049: "nfs", 2181: "zookeeper",
        3000: "grafana", 3306: "mysql", 3389: "rdp",
        4369: "epmd", 5432: "postgresql", 5433: "postgresql",
        5555: "freeciv", 5600: "wso2", 5666: "nrpe",
        5672: "rabbitmq", 5900: "vnc", 6379: "redis",
        6443: "k8s-api", 6556: "checkmk",
        7474: "neo4j", 8080: "http-alt", 8443: "https-alt",
        8888: "http-proxy", 9090: "prometheus", 9091: "prometheus-push",
        9092: "kafka", 9200: "elasticsearch", 9300: "elasticsearch-transport",
        9443: "https-app", 9999: "avrcp",
        10050: "zabbix-agent", 10051: "zabbix-server",
        11211: "memcached", 15672: "rabbitmq-mgmt",
        27017: "mongodb", 50000: "jenkins-agent",
    }
    for svc in services:
        if not svc["process"] and svc["port"] in WELL_KNOWN_PORTS:
            svc["process"] = WELL_KNOWN_PORTS[svc["port"]]

    # Sort by port number
    services.sort(key=lambda s: s["port"])
    return services


def discover_systemd_services():
    """
    Discover active systemd services.
    Returns list of dicts: {name, status, description, type}
    """
    import subprocess
    services = []

    # Skip low-level system services — only report application-level ones
    system_prefixes = (
        "systemd-", "dbus", "polkit", "accounts-daemon", "udisks",
        "NetworkManager", "network", "firewalld", "auditd", "irqbalance",
        "tuned", "chronyd", "crond", "atd", "sssd", "rsyslog", "syslog",
        "getty@", "serial-getty@", "user@", "session-", "init.scope",
        "plymouth", "dracut", "lvm2", "dm-event", "multipathd",
        "blk-availability", "kmod", "proc-sys", "sys-", "dev-",
        "run-", "tmp.mount", "var-", "boot", "swap",
    )

    try:
        r = subprocess.run(
            ["systemctl", "list-units", "--type=service", "--all", "--no-pager",
             "--plain", "--no-legend"],
            capture_output=True, text=True, timeout=15
        )
        if r.returncode == 0:
            for line in r.stdout.splitlines():
                parts = line.split(None, 4)
                if len(parts) < 4:
                    continue
                unit_name = parts[0]
                # Remove .service suffix for cleaner display
                svc_name = unit_name.replace('.service', '')
                # Skip system services
                if any(svc_name.startswith(p) or svc_name == p.rstrip('-') for p in system_prefixes):
                    continue
                load_state = parts[1]   # loaded/not-found
                active     = parts[2]   # active/inactive/failed
                sub_state  = parts[3]   # running/dead/failed/exited
                desc       = parts[4] if len(parts) > 4 else ""

                # Only report loaded services that are running, failed, or explicitly enabled
                if load_state != "loaded":
                    continue
                if active not in ("active", "failed"):
                    continue

                status = "running" if sub_state == "running" else sub_state
                services.append({
                    "name":        svc_name,
                    "status":      status,
                    "description": desc.strip(),
                    "type":        "systemd",
                })
    except Exception:
        pass

    return services[:100]  # Cap at 100


def discover_containers():
    """
    Discover running Docker or Podman containers.
    Returns list of dicts: {name, image, status, ports, type, container_id}
    """
    import subprocess
    containers = []

    # Try podman first (common on RHEL), then docker
    for runtime in ["podman", "docker"]:
        try:
            r = subprocess.run(
                [runtime, "ps", "--format",
                 "{{.ID}}\t{{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}"],
                capture_output=True, text=True, timeout=10
            )
            if r.returncode == 0 and r.stdout.strip():
                for line in r.stdout.splitlines():
                    parts = line.split('\t')
                    if len(parts) < 4:
                        continue
                    container_id = parts[0][:12]
                    name         = parts[1] if len(parts) > 1 else ""
                    image        = parts[2] if len(parts) > 2 else ""
                    status       = parts[3] if len(parts) > 3 else ""
                    ports        = parts[4] if len(parts) > 4 else ""
                    containers.append({
                        "name":         name,
                        "image":        image,
                        "status":       status,
                        "ports":        ports,
                        "type":         runtime,
                        "container_id": container_id,
                    })
                break  # Found a working runtime, don't try the other
        except FileNotFoundError:
            continue
        except Exception:
            continue

    return containers[:50]  # Cap at 50


def collect_discovered_services():
    """
    Collect all discovered services: listening ports, systemd services, containers.
    Returns a dict with all three categories.
    """
    return {
        "listening_ports":    discover_listening_ports(),
        "systemd_services":   discover_systemd_services(),
        "containers":         discover_containers(),
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
            "User-Agent":    "CROIT-Agent/2.0",
        },
        method = "POST"
    )
    ctx = ssl.create_default_context()
    if not verify_ssl:
        ctx.check_hostname = False
        ctx.verify_mode    = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=10) as resp:
            return True, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}: {e.read().decode()}"
    except Exception as e:
        return False, str(e)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="CROIT Server Agent v2")
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
                cached_patch    = collect_patch_metrics_linux()
                last_patch_time = time.time()

            # Refresh installed software if interval has elapsed (or first run)
            if time.time() - last_sw_time >= sw_interval_s:
                cached_software = collect_installed_software_linux()
                last_sw_time    = time.time()
                print(f"[CROIT Agent v2] Collected {len(cached_software)} installed packages")

            # Refresh discovered services if interval has elapsed (or first run)
            if time.time() - last_svc_time >= svc_interval_s:
                cached_services = collect_discovered_services()
                last_svc_time   = time.time()
                port_count = len(cached_services.get("listening_ports", []))
                svc_count  = len(cached_services.get("systemd_services", []))
                ctr_count  = len(cached_services.get("containers", []))
                print(f"[CROIT Agent v2] Discovered services: {port_count} ports, {svc_count} systemd, {ctr_count} containers")

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
                print(f"[{ts}] OK — CPU:{metrics['cpu_pct']}%({metrics['cpu_cores']}c/{metrics['cpu_threads']}t) "
                      f"RAM:{metrics['ram_pct']}% Disks:[{mounts_str}] Load:{metrics['load_1m']} "
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
