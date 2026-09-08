# ============================================================
# CROIT Uptime Monitor - Windows PowerShell Agent
# No Python required — runs on any Windows server with PS 5.1+
#
# Usage:
#   .\agent_windows.ps1 -Url "https://frm-rbautodev01:9443" -Token "YOUR_TOKEN"
#   .\agent_windows.ps1 -Url "https://frm-rbautodev01:9443" -Token "YOUR_TOKEN" -Once
# ============================================================

param(
    [Parameter(Mandatory=$true)]
    [string]$Url,

    [Parameter(Mandatory=$true)]
    [string]$Token,

    [int]$Interval      = 60,   # seconds between heartbeats
    [int]$PatchInterval = 60,   # minutes between patch checks
    [switch]$Once,              # run once and exit
    [switch]$VerifySsl          # verify SSL cert (default: skip)
)

# Ignore SSL errors unless -VerifySsl specified
if (-not $VerifySsl) {
    [System.Net.ServicePointManager]::ServerCertificateValidationCallback = { $true }
    [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12
}

# ── OS Info ──────────────────────────────────────────────────────────────────

function Get-OsInfo {
    try {
        $os  = Get-CimInstance Win32_OperatingSystem
        $cs  = Get-CimInstance Win32_ComputerSystem
        return @{
            os_name    = $os.Caption
            os_version = $os.BuildNumber
            kernel     = $os.Version
        }
    } catch {
        return @{ os_name = "Windows"; os_version = ""; kernel = "" }
    }
}

# ── CPU ──────────────────────────────────────────────────────────────────────

function Get-CpuInfo {
    try {
        $load    = (Get-CimInstance Win32_Processor | Measure-Object -Property LoadPercentage -Average).Average
        $cpu     = Get-CimInstance Win32_Processor | Select-Object -First 1
        $cores   = ($cpu.NumberOfCores)
        $threads = ($cpu.NumberOfLogicalProcessors)
        return @{
            cpu_pct     = [math]::Round($load, 1)
            cpu_cores   = $cores
            cpu_threads = $threads
        }
    } catch {
        return @{ cpu_pct = $null; cpu_cores = $null; cpu_threads = $null }
    }
}

# ── RAM ──────────────────────────────────────────────────────────────────────

function Get-RamInfo {
    try {
        $os        = Get-CimInstance Win32_OperatingSystem
        $totalKB   = $os.TotalVisibleMemorySize
        $freeKB    = $os.FreePhysicalMemory
        $usedKB    = $totalKB - $freeKB
        $totalGB   = [math]::Round($totalKB / 1MB, 2)
        $usedGB    = [math]::Round($usedKB  / 1MB, 2)
        $pct       = [math]::Round($usedKB  / $totalKB * 100, 1)
        return @{
            ram_total_gb = $totalGB
            ram_used_gb  = $usedGB
            ram_pct      = $pct
        }
    } catch {
        return @{ ram_total_gb = $null; ram_used_gb = $null; ram_pct = $null }
    }
}

# ── Disk Mounts ───────────────────────────────────────────────────────────────

function Get-DiskType($driveLetter) {
    try {
        $partition = Get-Partition -DriveLetter $driveLetter -ErrorAction SilentlyContinue
        if ($partition) {
            $disk = Get-Disk -Number $partition.DiskNumber -ErrorAction SilentlyContinue
            if ($disk) {
                switch ($disk.MediaType) {
                    "SSD"          { return "SSD" }
                    "HDD"          { return "HDD" }
                    "Unspecified"  { return "Virtual" }
                    default        { return $disk.MediaType }
                }
            }
        }
    } catch {}
    return "Unknown"
}

function Get-DiskMounts {
    $mounts = @()
    try {
        $drives = Get-PSDrive -PSProvider FileSystem | Where-Object { $_.Root -match '^[A-Z]:\\$' }
        foreach ($d in $drives) {
            try {
                $letter    = $d.Name
                $totalGB   = [math]::Round(($d.Used + $d.Free) / 1GB, 1)
                $usedGB    = [math]::Round($d.Used / 1GB, 1)
                $freeGB    = [math]::Round($d.Free / 1GB, 1)
                $pct       = if ($totalGB -gt 0) { [math]::Round($usedGB / $totalGB * 100, 1) } else { 0 }
                $diskType  = Get-DiskType $letter
                $mounts   += @{
                    mount     = "$letter`:\"
                    device    = "$letter`:"
                    total_gb  = $totalGB
                    used_gb   = $usedGB
                    free_gb   = $freeGB
                    pct       = $pct
                    disk_type = $diskType
                }
            } catch {}
        }
    } catch {}
    return $mounts
}

# ── Uptime ────────────────────────────────────────────────────────────────────

function Get-UptimeSec {
    try {
        $os   = Get-CimInstance Win32_OperatingSystem
        $boot = $os.LastBootUpTime
        return [int](New-TimeSpan -Start $boot -End (Get-Date)).TotalSeconds
    } catch { return $null }
}

# ── Process Count ─────────────────────────────────────────────────────────────

function Get-ProcessCount {
    try { return (Get-Process).Count } catch { return $null }
}

# ── Reboot Required ───────────────────────────────────────────────────────────

function Get-RebootRequired {
    try {
        # Check 1: WindowsUpdate RebootRequired key
        $key1 = "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired"
        if (Test-Path $key1) { return $true }

        # Check 2: PendingFileRenameOperations
        $key2 = "HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager"
        $val  = (Get-ItemProperty -Path $key2 -Name "PendingFileRenameOperations" -ErrorAction SilentlyContinue).PendingFileRenameOperations
        if ($val) { return $true }

        return $false
    } catch { return $null }
}

# ── Patch Metrics ─────────────────────────────────────────────────────────────

function Get-PatchMetrics {
    $rebootRequired = Get-RebootRequired
    $pendingUpdates = $null
    $patchStatus    = $null

    try {
        # Primary: WUA COM API
        $session  = New-Object -ComObject Microsoft.Update.Session
        $searcher = $session.CreateUpdateSearcher()
        $result   = $searcher.Search("IsInstalled=0 and IsHidden=0")
        $updates  = $result.Updates
        $count    = $updates.Count
        $hasCrit  = $false

        for ($i = 0; $i -lt $count; $i++) {
            $sev = $updates.Item($i).MsrcSeverity
            if ($sev -eq "Critical" -or $sev -eq "Important") {
                $hasCrit = $true
                break
            }
        }

        $pendingUpdates = $count
        if ($count -eq 0)      { $patchStatus = "up_to_date" }
        elseif ($hasCrit)      { $patchStatus = "critical" }
        else                   { $patchStatus = "updates_pending" }

    } catch {
        # Fallback: PowerShell COM via command line count only
        try {
            $ps  = '$s=New-Object -ComObject Microsoft.Update.Session;$s.CreateUpdateSearcher().Search(\"IsInstalled=0\").Updates.Count'
            $out = powershell -NoProfile -Command $ps 2>$null
            if ($out -match '^\d+$') {
                $pendingUpdates = [int]$out
                $patchStatus    = if ($pendingUpdates -eq 0) { "up_to_date" } else { "updates_pending" }
            }
        } catch {
            Write-Warning "[CROIT Agent] Patch collection failed: $_"
        }
    }

    return @{
        pending_updates = $pendingUpdates
        reboot_required = $rebootRequired
        patch_status    = $patchStatus
    }
}

# ── Installed Software ────────────────────────────────────────────────────────

function Get-InstalledSoftware {
    $packages = @()
    $seen     = @{}

    $regPaths = @(
        "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*",
        "HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*"
    )

    foreach ($path in $regPaths) {
        try {
            $items = Get-ItemProperty -Path $path -ErrorAction SilentlyContinue |
                     Where-Object { $_.DisplayName }
            foreach ($item in $items) {
                $name = ($item.DisplayName -as [string]).Trim()
                if (-not $name -or $seen.ContainsKey($name)) { continue }
                $seen[$name] = $true
                $packages += @{
                    name         = $name
                    version      = if ($item.DisplayVersion) { ($item.DisplayVersion -as [string]).Trim() } else { "" }
                    vendor       = if ($item.Publisher)      { ($item.Publisher      -as [string]).Trim() } else { "" }
                    install_path = if ($item.InstallLocation){ ($item.InstallLocation -as [string]).Trim() } else { "" }
                }
            }
        } catch {
            Write-Warning "[CROIT Agent PS] Software collection error for ${path}: $_"
        }
    }

    # Cap at 500
    if ($packages.Count -gt 500) { $packages = $packages[0..499] }
    return $packages
}

# ── Collect All Metrics ───────────────────────────────────────────────────────

function Get-AllMetrics($cachedPatch, $cachedSoftware) {
    $os    = Get-OsInfo
    $cpu   = Get-CpuInfo
    $ram   = Get-RamInfo
    $disks = Get-DiskMounts
    $up    = Get-UptimeSec
    $procs = Get-ProcessCount

    # C: drive for backward compat root disk fields
    $cDrive     = $disks | Where-Object { $_.mount -eq "C:\" } | Select-Object -First 1
    $diskTotal  = if ($cDrive) { $cDrive.total_gb } else { $null }
    $diskUsed   = if ($cDrive) { $cDrive.used_gb  } else { $null }
    $diskPct    = if ($cDrive) { $cDrive.pct       } else { $null }

    # Load approx from CPU - PS 5.1 compatible null handling
    $cpuVal     = if ($cpu.cpu_pct -ne $null) { $cpu.cpu_pct } else { 0 }
    $loadApprox = [math]::Round($cpuVal / 100, 2)

    $metrics = @{
        os_name            = $os.os_name
        os_version         = $os.os_version
        kernel             = $os.kernel
        cpu_pct            = $cpu.cpu_pct
        cpu_cores          = $cpu.cpu_cores
        cpu_threads        = $cpu.cpu_threads
        ram_total_gb       = $ram.ram_total_gb
        ram_used_gb        = $ram.ram_used_gb
        ram_pct            = $ram.ram_pct
        disk_total_gb      = $diskTotal
        disk_used_gb       = $diskUsed
        disk_pct           = $diskPct
        disk_mounts        = $disks
        uptime_sec         = $up
        load_1m            = $loadApprox
        load_5m            = $loadApprox
        load_15m           = $loadApprox
        process_count      = $procs
        pending_updates    = $cachedPatch.pending_updates
        reboot_required    = $cachedPatch.reboot_required
        patch_status       = $cachedPatch.patch_status
        installed_software = $cachedSoftware
    }
    return $metrics
}

# ── POST to Dashboard ─────────────────────────────────────────────────────────

function Send-Metrics($metrics) {
    $endpoint = $Url.TrimEnd("/") + "/api/agent/heartbeat"
    $body     = $metrics | ConvertTo-Json -Depth 5 -Compress
    $headers  = @{
        "Content-Type"  = "application/json"
        "Authorization" = "Bearer $Token"
        "User-Agent"    = "CROIT-Agent-Windows-PS/2.0"
    }
    try {
        $response = Invoke-RestMethod -Uri $endpoint -Method POST -Body $body -Headers $headers
        return $true, $response
    } catch {
        return $false, $_.Exception.Message
    }
}

# ── Main Loop ─────────────────────────────────────────────────────────────────

Write-Host "[CROIT Agent PS] Starting - reporting to $Url"
Write-Host "[CROIT Agent PS] Hostname: $env:COMPUTERNAME"
Write-Host "[CROIT Agent PS] OS: $([System.Environment]::OSVersion.VersionString)"

$patchIntervalSec = $PatchInterval * 60
$lastPatchTime    = 0
$cachedPatch      = @{ pending_updates = $null; reboot_required = $null; patch_status = $null }

# Software collection interval: every 60 minutes
$swIntervalSec  = 3600
$lastSwTime     = 0
$cachedSoftware = @()

do {
    try {
        # Refresh patch metrics if interval elapsed
        $now = [int][double]::Parse((Get-Date -UFormat %s))
        if (($now - $lastPatchTime) -ge $patchIntervalSec) {
            Write-Host "[CROIT Agent PS] Collecting patch metrics..."
            $cachedPatch   = Get-PatchMetrics
            $lastPatchTime = $now
        }

        # Refresh installed software if interval elapsed
        if (($now - $lastSwTime) -ge $swIntervalSec) {
            Write-Host "[CROIT Agent PS] Collecting installed software..."
            $cachedSoftware = Get-InstalledSoftware
            $lastSwTime     = $now
            Write-Host "[CROIT Agent PS] Collected $($cachedSoftware.Count) software entries"
        }

        $metrics = Get-AllMetrics $cachedPatch $cachedSoftware
        $ok, $result = Send-Metrics $metrics

        $ts        = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
        $mountsStr = ""
        foreach ($m in $metrics.disk_mounts) {
            if ($mountsStr -ne "") { $mountsStr += " | " }
            $mountsStr += "$($m.mount):$($m.pct)%($($m.disk_type))"
        }

        if ($ok) {
            Write-Host "[$ts] OK - CPU:$($metrics.cpu_pct)%($($metrics.cpu_cores)c/$($metrics.cpu_threads)t) RAM:$($metrics.ram_pct)% Disks:[$mountsStr] Patches:$($metrics.patch_status)($($metrics.pending_updates))"
        } else {
            Write-Warning "[$ts] ERROR - $result"
        }
    } catch {
        Write-Warning "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] EXCEPTION - $_"
    }

    if (-not $Once) { Start-Sleep -Seconds $Interval }

} while (-not $Once)
