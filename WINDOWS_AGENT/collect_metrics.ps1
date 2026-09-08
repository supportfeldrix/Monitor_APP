$ErrorActionPreference = 'SilentlyContinue'

# OS Info - use multiple fallback methods
$os_name = $null
$os_version = $null
$kernel = $null
$ram_total_kb = 0
$ram_free_kb = 0
$boot_time = $null

try {
  $os = Get-CimInstance Win32_OperatingSystem
  if ($os) {
    $os_name = $os.Caption
    $os_version = $os.Version
    $kernel = $os.BuildNumber
    $ram_total_kb = $os.TotalVisibleMemorySize
    $ram_free_kb = $os.FreePhysicalMemory
    $boot_time = $os.LastBootUpTime
  }
} catch {}

# Fallback for OS info via WMI if CIM failed
if (-not $os_name) {
  try {
    $wmi_os = Get-WmiObject Win32_OperatingSystem
    if ($wmi_os) {
      $os_name = $wmi_os.Caption
      $os_version = $wmi_os.Version
      $kernel = $wmi_os.BuildNumber
      $ram_total_kb = $wmi_os.TotalVisibleMemorySize
      $ram_free_kb = $wmi_os.FreePhysicalMemory
      $boot_time = $wmi_os.ConvertToDateTime($wmi_os.LastBootUpTime)
    }
  } catch {}
}

# RAM calculation
$ram_total_gb = 0
$ram_used_gb = 0
$ram_pct = 0
if ($ram_total_kb -gt 0) {
  $ram_total_gb = [math]::Round($ram_total_kb / 1MB, 2)
  $ram_free_gb = [math]::Round($ram_free_kb / 1MB, 2)
  $ram_used_gb = [math]::Round($ram_total_gb - $ram_free_gb, 2)
  $ram_pct = [math]::Round(($ram_used_gb / $ram_total_gb) * 100, 1)
}

# CPU - try Get-Counter first, fallback to WMI
$cpu_pct = 0
$cpu_cores = 0
$cpu_threads = 0

try {
  $counter = Get-Counter '\Processor(_Total)\% Processor Time' -SampleInterval 1
  if ($counter) {
    $cpu_pct = [math]::Round($counter.CounterSamples[0].CookedValue, 1)
  }
} catch {}

# Fallback CPU via WMI
if ($cpu_pct -eq 0) {
  try {
    $wmi_cpu = Get-WmiObject Win32_Processor
    if ($wmi_cpu) {
      $cpu_pct = [math]::Round(($wmi_cpu | Measure-Object -Property LoadPercentage -Average).Average, 1)
    }
  } catch {}
}

# CPU cores/threads
try {
  $proc_info = Get-CimInstance Win32_Processor | Select-Object -First 1
  if ($proc_info) {
    $cpu_cores = [int]$proc_info.NumberOfCores
    $cpu_threads = [int]$proc_info.NumberOfLogicalProcessors
  }
} catch {}

if ($cpu_cores -eq 0) {
  try {
    $wmi_proc = Get-WmiObject Win32_Processor | Select-Object -First 1
    if ($wmi_proc) {
      $cpu_cores = [int]$wmi_proc.NumberOfCores
      $cpu_threads = [int]$wmi_proc.NumberOfLogicalProcessors
    }
  } catch {}
}

# Disks
$disk_mounts = @()
try {
  Get-CimInstance Win32_LogicalDisk -Filter 'DriveType=3' | ForEach-Object {
    $dtotal = [math]::Round($_.Size / 1GB, 1)
    $dfree = [math]::Round($_.FreeSpace / 1GB, 1)
    $dused = [math]::Round($dtotal - $dfree, 1)
    $dpct = 0
    if ($dtotal -gt 0) { $dpct = [math]::Round(($dused / $dtotal) * 100, 1) }
    $disk_mounts += @{
      mount = $_.DeviceID + '\'
      device = $_.DeviceID
      total_gb = $dtotal
      used_gb = $dused
      free_gb = $dfree
      pct = $dpct
      disk_type = 'Unknown'
    }
  }
} catch {}

# Fallback disks via WMI
if ($disk_mounts.Count -eq 0) {
  try {
    Get-WmiObject Win32_LogicalDisk -Filter 'DriveType=3' | ForEach-Object {
      $dtotal = [math]::Round([double]$_.Size / 1GB, 1)
      $dfree = [math]::Round([double]$_.FreeSpace / 1GB, 1)
      $dused = [math]::Round($dtotal - $dfree, 1)
      $dpct = 0
      if ($dtotal -gt 0) { $dpct = [math]::Round(($dused / $dtotal) * 100, 1) }
      $disk_mounts += @{
        mount = $_.DeviceID + '\'
        device = $_.DeviceID
        total_gb = $dtotal
        used_gb = $dused
        free_gb = $dfree
        pct = $dpct
        disk_type = 'Unknown'
      }
    }
  } catch {}
}

# Uptime
$uptime_sec = 0
if ($boot_time) {
  try {
    $uptime_sec = [int]((Get-Date) - $boot_time).TotalSeconds
  } catch {}
}

$proc_count = (Get-Process).Count

# Listening Ports
$ports = @()
try {
  Get-NetTCPConnection -State Listen | Sort-Object LocalPort -Unique | ForEach-Object {
    $pname = ''
    try { $pname = (Get-Process -Id $_.OwningProcess).Name } catch {}
    $ports += @{
      port = [int]$_.LocalPort
      protocol = 'tcp'
      address = $_.LocalAddress
      pid = [int]$_.OwningProcess
      process = $pname
      state = 'LISTEN'
    }
  }
} catch {}

# Fallback ports via netstat if Get-NetTCPConnection failed
if ($ports.Count -eq 0) {
  try {
    $netstat = netstat -ano | Select-String 'LISTENING'
    foreach ($line in $netstat) {
      $parts = $line.ToString().Trim() -split '\s+'
      if ($parts.Count -ge 5) {
        $local = $parts[1]
        $lastColon = $local.LastIndexOf(':')
        if ($lastColon -gt 0) {
          $port = [int]$local.Substring($lastColon + 1)
          $addr = $local.Substring(0, $lastColon)
          $pid_val = [int]$parts[4]
          $pname = ''
          try { $pname = (Get-Process -Id $pid_val).Name } catch {}
          $ports += @{
            port = $port
            protocol = 'tcp'
            address = $addr
            pid = $pid_val
            process = $pname
            state = 'LISTEN'
          }
        }
      }
    }
    $ports = $ports | Sort-Object { $_.port } | Select-Object -Unique -Property port, protocol, address, pid, process, state
  } catch {}
}

# Windows Services (non-system)
$skip_prefixes = @('Windows','Microsoft','DCOM','RPC','Plug and Play','Security','Base Filtering','Network','DNS Client','DHCP','Group Policy','Task Scheduler','User Profile','WMI','COM+','Cryptographic','Diagnostic','IP Helper','Server','Workstation','Print Spooler','Shell Hardware','System Events','Themes','Volume Shadow')
$services = @()
try {
  Get-Service | Where-Object { $_.Status -eq 'Running' } | ForEach-Object {
    $display = $_.DisplayName
    $skip = $false
    foreach ($p in $skip_prefixes) { if ($display.StartsWith($p)) { $skip = $true; break } }
    if (-not $skip) {
      $services += @{
        name = $_.Name
        status = 'running'
        description = $display
        type = 'windows_service'
      }
    }
  }
} catch {}

# Installed Software (non-Microsoft, max 200)
$software = @()
$seen = @{}
try {
  $regPaths = @(
    'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*',
    'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*'
  )
  Get-ItemProperty $regPaths -ErrorAction SilentlyContinue |
    Where-Object { $_.DisplayName -and $_.Publisher -notlike 'Microsoft*' } |
    ForEach-Object {
      if (-not $seen[$_.DisplayName] -and $software.Count -lt 200) {
        $seen[$_.DisplayName] = $true
        $software += @{
          name = $_.DisplayName
          version = $_.DisplayVersion
          vendor = $_.Publisher
          install_path = $_.InstallLocation
        }
      }
    }
} catch {}

# Build payload
$d_total = 0; $d_used = 0; $d_pct = 0
if ($disk_mounts.Count -gt 0) {
  $d_total = $disk_mounts[0].total_gb
  $d_used = $disk_mounts[0].used_gb
  $d_pct = $disk_mounts[0].pct
}

# Top folder sizes for each drive (top 15 largest folders)
$folder_sizes = @()
foreach ($disk in $disk_mounts) {
  $drive = $disk.device
  try {
    $folders = Get-ChildItem -Path "$drive\" -Directory -ErrorAction SilentlyContinue | ForEach-Object {
      $size = 0
      try {
        $size = (Get-ChildItem -Path $_.FullName -Recurse -File -ErrorAction SilentlyContinue | Measure-Object -Property Length -Sum).Sum
      } catch {}
      @{
        path = $_.FullName
        size_gb = [math]::Round($size / 1GB, 2)
        size_mb = [math]::Round($size / 1MB, 0)
      }
    } | Sort-Object { $_.size_gb } -Descending | Select-Object -First 15
    foreach ($f in $folders) {
      if ($f.size_mb -gt 10) {
        $folder_sizes += $f
      }
    }
  } catch {}
}

$payload = @{
  os_name = $os_name
  os_version = $os_version
  kernel = $kernel
  cpu_pct = $cpu_pct
  cpu_cores = $cpu_cores
  cpu_threads = $cpu_threads
  ram_total_gb = $ram_total_gb
  ram_used_gb = $ram_used_gb
  ram_pct = $ram_pct
  disk_total_gb = $d_total
  disk_used_gb = $d_used
  disk_pct = $d_pct
  disk_mounts = $disk_mounts
  uptime_sec = $uptime_sec
  load_1m = [math]::Round($cpu_pct / 100, 2)
  load_5m = [math]::Round($cpu_pct / 100, 2)
  load_15m = [math]::Round($cpu_pct / 100, 2)
  process_count = $proc_count
  installed_software = $software
  folder_sizes = $folder_sizes
  discovered_services = @{
    listening_ports = $ports
    systemd_services = $services
    containers = @()
  }
}

$payload | ConvertTo-Json -Depth 4 -Compress
