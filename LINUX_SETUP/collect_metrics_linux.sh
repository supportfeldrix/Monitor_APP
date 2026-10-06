#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════════════
# CROIT Monitor — Linux Metrics Collection Script
# Outputs JSON to stdout — designed to be run via Ansible SSH
# ═══════════════════════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════════════════════
# Critical Process/Service Config — now sourced from the CROIT_PROCESS_CONFIG env var
# ═══════════════════════════════════════════════════════════════════════════════
# The config is NO LONGER hardcoded here. It comes from the CROIT_PROCESS_CONFIG
# environment variable, which Ansible sets per-host-group from the inventory
# variable `croit_process_config`. Only the ACR (AlertController) Fircosoft hosts
# define it; every other host leaves it empty, so NO process monitoring happens
# (an empty config emits "process_services":[]).
#
# These are shell-launched java/FKRUN processes under the `fircosoft` user that
# `systemctl` never lists, so we detect them by command-line pattern via `ps`.
#
# Format per entry:  name|pattern|expected_ports(comma-sep)|critical(true|false)
#   - `pattern` is matched with `grep -F` (fixed string) against `ps -eo pid,args`.
# Entries are separated by `;;` in the env var (newlines don't survive the Ansible
# shell env cleanly), and are translated back into newlines below so the existing
# `while IFS='|' read ... done <<EOF` loop keeps working unchanged.
PROCESS_SERVICE_CONFIG="${CROIT_PROCESS_CONFIG:-}"
# Translate the `;;` record separator back into newlines (one entry per line).
PROCESS_SERVICE_CONFIG=$(printf '%s' "$PROCESS_SERVICE_CONFIG" | sed 's/;;/\n/g')

# OS Info
OS_NAME=$(grep -m1 '^NAME=' /etc/os-release 2>/dev/null | cut -d'"' -f2)
OS_VERSION=$(grep -m1 '^VERSION_ID=' /etc/os-release 2>/dev/null | cut -d'"' -f2)
KERNEL=$(uname -r)

# CPU
CPU_IDLE1=$(awk '/^cpu /{print $5}' /proc/stat)
CPU_TOTAL1=$(awk '/^cpu /{s=0; for(i=2;i<=NF;i++) s+=$i; print s}' /proc/stat)
sleep 0.5
CPU_IDLE2=$(awk '/^cpu /{print $5}' /proc/stat)
CPU_TOTAL2=$(awk '/^cpu /{s=0; for(i=2;i<=NF;i++) s+=$i; print s}' /proc/stat)
CPU_DIFF_IDLE=$((CPU_IDLE2 - CPU_IDLE1))
CPU_DIFF_TOTAL=$((CPU_TOTAL2 - CPU_TOTAL1))
if [ "$CPU_DIFF_TOTAL" -gt 0 ]; then
  CPU_PCT=$(awk "BEGIN {printf \"%.1f\", (1 - $CPU_DIFF_IDLE/$CPU_DIFF_TOTAL) * 100}")
else
  CPU_PCT="0.0"
fi

CPU_CORES=$(grep -c '^processor' /proc/cpuinfo)
CPU_THREADS=$CPU_CORES

# RAM
MEM_TOTAL=$(awk '/^MemTotal:/{print $2}' /proc/meminfo)
MEM_AVAIL=$(awk '/^MemAvailable:/{print $2}' /proc/meminfo)
if [ -z "$MEM_AVAIL" ]; then
  MEM_AVAIL=$(awk '/^MemFree:/{print $2}' /proc/meminfo)
fi
MEM_USED=$((MEM_TOTAL - MEM_AVAIL))
RAM_TOTAL_GB=$(awk "BEGIN {printf \"%.2f\", $MEM_TOTAL/1048576}")
RAM_USED_GB=$(awk "BEGIN {printf \"%.2f\", $MEM_USED/1048576}")
RAM_PCT=$(awk "BEGIN {printf \"%.1f\", $MEM_USED/$MEM_TOTAL*100}")

# Disk mounts
DISK_MOUNTS="["
FIRST=1
while IFS= read -r line; do
  MOUNT=$(echo "$line" | awk '{print $6}')
  DEVICE=$(echo "$line" | awk '{print $1}')
  TOTAL=$(echo "$line" | awk '{print $2}')
  USED=$(echo "$line" | awk '{print $3}')
  FREE=$(echo "$line" | awk '{print $4}')
  PCT=$(echo "$line" | awk '{gsub(/%/,""); print $5}')
  TOTAL_GB=$(awk "BEGIN {printf \"%.1f\", $TOTAL/1048576}")
  USED_GB=$(awk "BEGIN {printf \"%.1f\", $USED/1048576}")
  FREE_GB=$(awk "BEGIN {printf \"%.1f\", $FREE/1048576}")
  if [ "$FIRST" -eq 0 ]; then DISK_MOUNTS="$DISK_MOUNTS,"; fi
  DISK_MOUNTS="$DISK_MOUNTS{\"mount\":\"$MOUNT\",\"device\":\"$DEVICE\",\"total_gb\":$TOTAL_GB,\"used_gb\":$USED_GB,\"free_gb\":$FREE_GB,\"pct\":$PCT,\"disk_type\":\"Virtual\"}"
  FIRST=0
done < <(df -P -x tmpfs -x devtmpfs -x squashfs | tail -n +2)
DISK_MOUNTS="$DISK_MOUNTS]"

# Root disk for backward compat
ROOT_TOTAL=$(df -P / | tail -1 | awk '{printf "%.1f", $2/1048576}')
ROOT_USED=$(df -P / | tail -1 | awk '{printf "%.1f", $3/1048576}')
ROOT_PCT=$(df -P / | tail -1 | awk '{gsub(/%/,""); print $5}')

# Uptime
UPTIME_SEC=$(awk '{print int($1)}' /proc/uptime)

# Load
LOAD_1M=$(awk '{print $1}' /proc/loadavg)
LOAD_5M=$(awk '{print $2}' /proc/loadavg)
LOAD_15M=$(awk '{print $3}' /proc/loadavg)

# Process count
PROC_COUNT=$(ls -d /proc/[0-9]* 2>/dev/null | wc -l)

# Listening ports (using ss)
PORTS="["
FIRST=1
while IFS= read -r line; do
  PORT=$(echo "$line" | awk '{print $4}' | rev | cut -d: -f1 | rev)
  ADDR=$(echo "$line" | awk '{print $4}' | rev | cut -d: -f2- | rev | tr -d '[]')
  # Try to get process name
  PROC=""
  if echo "$line" | grep -q 'users:'; then
    PROC=$(echo "$line" | grep -oP '\(\("\K[^"]+')
  fi
  if [ -n "$PORT" ] && [ "$PORT" -eq "$PORT" ] 2>/dev/null; then
    if [ "$FIRST" -eq 0 ]; then PORTS="$PORTS,"; fi
    PORTS="$PORTS{\"port\":$PORT,\"protocol\":\"tcp\",\"address\":\"$ADDR\",\"pid\":null,\"process\":\"$PROC\",\"state\":\"LISTEN\"}"
    FIRST=0
  fi
done < <(ss -tlnp 2>/dev/null | tail -n +2)
PORTS="$PORTS]"

# Systemd services (active, non-system)
SERVICES="["
FIRST=1
while IFS= read -r line; do
  SVC_NAME=$(echo "$line" | awk '{print $1}' | sed 's/\.service//')
  SVC_STATE=$(echo "$line" | awk '{print $4}')
  SVC_DESC=$(echo "$line" | awk '{for(i=5;i<=NF;i++) printf "%s ", $i; print ""}' | sed 's/"/\\"/g' | xargs)
  # Skip system services
  case "$SVC_NAME" in
    systemd-*|dbus*|polkit*|NetworkManager*|firewalld*|auditd*|irqbalance*|tuned*|chronyd*|crond*|sssd*|rsyslog*|getty@*|user@*) continue ;;
  esac
  if [ "$SVC_STATE" = "running" ]; then
    if [ "$FIRST" -eq 0 ]; then SERVICES="$SERVICES,"; fi
    SERVICES="$SERVICES{\"name\":\"$SVC_NAME\",\"status\":\"running\",\"description\":\"$SVC_DESC\",\"type\":\"systemd\"}"
    FIRST=0
  fi
done < <(systemctl list-units --type=service --state=active --no-pager --plain --no-legend 2>/dev/null)
SERVICES="$SERVICES]"

# Installed software (RPM-based, top 100 non-system)
SOFTWARE="["
FIRST=1
COUNT=0
while IFS=$'\t' read -r NAME VERSION VENDOR; do
  # Skip system packages
  case "$NAME" in
    lib*|kernel*|glibc*|systemd*|bash|coreutils|util-linux|rpm*|dnf*|yum*|python3-*|perl-*|fonts-*) continue ;;
  esac
  [ "$COUNT" -ge 100 ] && break
  NAME_ESC=$(echo "$NAME" | sed 's/"/\\"/g')
  VERSION_ESC=$(echo "$VERSION" | sed 's/"/\\"/g')
  VENDOR_ESC=$(echo "$VENDOR" | sed 's/"/\\"/g')
  if [ "$FIRST" -eq 0 ]; then SOFTWARE="$SOFTWARE,"; fi
  SOFTWARE="$SOFTWARE{\"name\":\"$NAME_ESC\",\"version\":\"$VERSION_ESC\",\"vendor\":\"$VENDOR_ESC\"}"
  FIRST=0
  COUNT=$((COUNT + 1))
done < <(rpm -qa --queryformat '%{NAME}\t%{VERSION}-%{RELEASE}\t%{VENDOR}\n' 2>/dev/null | sort)
SOFTWARE="$SOFTWARE]"

# Critical process/service detection (by command-line pattern, no root needed)
PROCESS_SERVICES="["
FIRST=1
while IFS='|' read -r PS_NAME PS_PATTERN PS_PORTS PS_CRITICAL; do
  [ -z "$PS_NAME" ] && continue
  # Collect matching PIDs via ps (exclude the grep itself)
  PS_PIDS=$(ps -eo pid,args --no-headers 2>/dev/null | grep -F -- "$PS_PATTERN" | grep -v 'grep' | awk '{print $1}')
  # Build the PIDs JSON array and status
  PIDS_JSON="["
  PID_FIRST=1
  PID_COUNT=0
  for p in $PS_PIDS; do
    if [ "$PID_FIRST" -eq 0 ]; then PIDS_JSON="$PIDS_JSON,"; fi
    PIDS_JSON="$PIDS_JSON$p"
    PID_FIRST=0
    PID_COUNT=$((PID_COUNT + 1))
  done
  PIDS_JSON="$PIDS_JSON]"
  if [ "$PID_COUNT" -ge 1 ]; then PS_STATUS="running"; else PS_STATUS="down"; fi

  # Build the ports JSON array from the configured expected ports.
  # Best-effort: also add any ss -tlnp port whose PID is in the matched set.
  PORTS_JSON="["
  PORT_FIRST=1
  if [ "$PS_PORTS" != "{EMPTY}" ] && [ -n "$PS_PORTS" ]; then
    OLD_IFS="$IFS"; IFS=','
    for prt in $PS_PORTS; do
      prt=$(echo "$prt" | tr -d ' ')
      [ -z "$prt" ] && continue
      if [ "$PORT_FIRST" -eq 0 ]; then PORTS_JSON="$PORTS_JSON,"; fi
      PORTS_JSON="$PORTS_JSON$prt"
      PORT_FIRST=0
    done
    IFS="$OLD_IFS"
  fi
  PORTS_JSON="$PORTS_JSON]"

  # JSON-escape the pattern
  PS_PATTERN_ESC=$(echo "$PS_PATTERN" | sed 's/\\/\\\\/g; s/"/\\"/g')
  if [ "$FIRST" -eq 0 ]; then PROCESS_SERVICES="$PROCESS_SERVICES,"; fi
  PROCESS_SERVICES="$PROCESS_SERVICES{\"name\":\"$PS_NAME\",\"status\":\"$PS_STATUS\",\"pattern\":\"$PS_PATTERN_ESC\",\"pids\":$PIDS_JSON,\"ports\":$PORTS_JSON,\"critical\":$PS_CRITICAL}"
  FIRST=0
done <<EOF
$PROCESS_SERVICE_CONFIG
EOF
PROCESS_SERVICES="$PROCESS_SERVICES]"

# Output JSON
cat << ENDJSON
{"os_name":"$OS_NAME","os_version":"$OS_VERSION","kernel":"$KERNEL","cpu_pct":$CPU_PCT,"cpu_cores":$CPU_CORES,"cpu_threads":$CPU_THREADS,"ram_total_gb":$RAM_TOTAL_GB,"ram_used_gb":$RAM_USED_GB,"ram_pct":$RAM_PCT,"disk_total_gb":$ROOT_TOTAL,"disk_used_gb":$ROOT_USED,"disk_pct":$ROOT_PCT,"disk_mounts":$DISK_MOUNTS,"uptime_sec":$UPTIME_SEC,"load_1m":$LOAD_1M,"load_5m":$LOAD_5M,"load_15m":$LOAD_15M,"process_count":$PROC_COUNT,"installed_software":$SOFTWARE,"discovered_services":{"listening_ports":$PORTS,"systemd_services":$SERVICES,"containers":[],"process_services":$PROCESS_SERVICES}}
ENDJSON
