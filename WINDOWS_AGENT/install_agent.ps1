# ============================================================
# CROIT Uptime Monitor - Windows Agent Installer
# Supports: Python agent (agent_windows.py) OR
#           PowerShell agent (agent_windows.ps1) - no Python needed
#
# Run as: .\install_agent.ps1 -Token "YOUR_TOKEN"
# No admin rights required
# ============================================================

param(
    [Parameter(Mandatory=$true)]
    [string]$Token,

    [string]$Url        = "https://frm-rbautodev01:9443",
    [string]$InstallDir = "$env:USERPROFILE\croit-agent",
    [switch]$Uninstall,
    [switch]$ForcePowerShell
)

$TaskName = "CROIT-Agent"
$LogFile  = "$InstallDir\agent.log"

# ---- Uninstall -------------------------------------------------------------
if ($Uninstall) {
    Write-Host "Removing CROIT Agent..." -ForegroundColor Yellow
    schtasks /delete /tn $TaskName /f 2>$null
    if (Test-Path $InstallDir) { Remove-Item -Recurse -Force $InstallDir }
    Write-Host "Agent removed." -ForegroundColor Green
    exit 0
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  CROIT Uptime Monitor - Windows Agent Installer" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# ---- Step 1: Detect agent type ---------------------------------------------
$usePowerShell = $false
$python        = $null

if ($ForcePowerShell) {
    Write-Host "[1/4] Using PowerShell agent (forced)" -ForegroundColor Cyan
    $usePowerShell = $true
} else {
    Write-Host "[1/4] Checking Python..." -ForegroundColor White
    foreach ($cmd in @("python", "python3", "py")) {
        try {
            $ver = & $cmd --version 2>&1
            if ($ver -match "Python 3") {
                $python = $cmd
                Write-Host "  Found: $ver ($cmd)" -ForegroundColor Green
                break
            }
        } catch {}
    }
    if (-not $python) {
        Write-Host "  Python not found - switching to PowerShell agent" -ForegroundColor Yellow
        $usePowerShell = $true
    }
}

# ---- Step 2: Create install directory and copy agent -----------------------
Write-Host "[2/4] Setting up agent directory: $InstallDir" -ForegroundColor White
if (-not (Test-Path $InstallDir)) {
    New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
}

if ($usePowerShell) {
    $agentScript  = "$InstallDir\agent_windows.ps1"
    $scriptSource = Join-Path $PSScriptRoot "agent_windows.ps1"
    if (-not (Test-Path $scriptSource)) {
        Write-Host "  ERROR: agent_windows.ps1 not found next to this script." -ForegroundColor Red
        exit 1
    }
    Copy-Item $scriptSource $agentScript -Force
    Write-Host "  PowerShell agent copied." -ForegroundColor Green
} else {
    $agentScript  = "$InstallDir\agent_windows.py"
    $scriptSource = Join-Path $PSScriptRoot "agent_windows.py"
    if (-not (Test-Path $scriptSource)) {
        Write-Host "  ERROR: agent_windows.py not found next to this script." -ForegroundColor Red
        exit 1
    }
    Copy-Item $scriptSource $agentScript -Force
    try {
        & $python -m pip install psutil --quiet 2>&1 | Out-Null
        Write-Host "  psutil ready." -ForegroundColor Green
    } catch {
        Write-Host "  WARNING: Could not install psutil. Using wmic fallback." -ForegroundColor Yellow
    }
    Write-Host "  Python agent copied." -ForegroundColor Green
}

@{ url = $Url; token = $Token } | ConvertTo-Json | Out-File "$InstallDir\config.json" -Encoding UTF8
Write-Host "  Config saved." -ForegroundColor Green

# ---- Step 3: Test connection -----------------------------------------------
Write-Host "[3/4] Testing agent connection..." -ForegroundColor White

if ($usePowerShell) {
    $testOutput = & powershell -NoProfile -ExecutionPolicy Bypass -File $agentScript `
        -Url $Url -Token $Token -Once 2>&1
} else {
    $testOutput = & $python $agentScript --url $Url --token $Token --once 2>&1
}

$testStr = $testOutput | Out-String
if ($testStr -match "OK") {
    Write-Host "  Connection successful!" -ForegroundColor Green
} else {
    Write-Host "  WARNING: Test output:" -ForegroundColor Yellow
    $testOutput | ForEach-Object { Write-Host "    $_" -ForegroundColor Yellow }
    Write-Host "  Continuing with installation anyway..." -ForegroundColor Yellow
}

# ---- Step 4: Create Scheduled Task -----------------------------------------
Write-Host "[4/4] Creating Scheduled Task '$TaskName'..." -ForegroundColor White
schtasks /delete /tn $TaskName /f 2>$null | Out-Null

if ($usePowerShell) {
    $taskCmd = "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$agentScript`" -Url `"$Url`" -Token `"$Token`" -Once"
} else {
    $pythonPath = (Get-Command $python).Source
    $taskCmd    = "`"$pythonPath`" `"$agentScript`" --url `"$Url`" --token `"$Token`" --once >> `"$LogFile`" 2>&1"
}

$result = schtasks /create /tn $TaskName /tr $taskCmd /sc minute /mo 1 /ru "$env:USERDOMAIN\$env:USERNAME" /f 2>&1

if ($LASTEXITCODE -eq 0) {
    Write-Host "  Scheduled Task created successfully." -ForegroundColor Green
    schtasks /run /tn $TaskName | Out-Null
    Start-Sleep -Seconds 3
    Write-Host "  Task started." -ForegroundColor Green
} else {
    Write-Host "  WARNING: Could not create Scheduled Task." -ForegroundColor Yellow
    Write-Host "  Run manually:" -ForegroundColor Cyan
    if ($usePowerShell) {
        Write-Host "  powershell -ExecutionPolicy Bypass -File `"$agentScript`" -Url `"$Url`" -Token `"$Token`"" -ForegroundColor White
    } else {
        Write-Host "  $python `"$agentScript`" --url `"$Url`" --token `"$Token`"" -ForegroundColor White
    }
}

# ---- Done ------------------------------------------------------------------
$agentType = if ($usePowerShell) { "PowerShell (no Python needed)" } else { "Python" }
Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Installation complete!" -ForegroundColor Green
Write-Host ""
Write-Host "  Agent type: $agentType" -ForegroundColor White
Write-Host "  Dashboard:  $Url" -ForegroundColor White
Write-Host "  Agent dir:  $InstallDir" -ForegroundColor White
Write-Host "  Log file:   $LogFile" -ForegroundColor White
Write-Host ""
Write-Host "  Check logs:    Get-Content '$LogFile' -Tail 20" -ForegroundColor Gray
Write-Host "  Check task:    schtasks /query /tn '$TaskName'" -ForegroundColor Gray
Write-Host "  Uninstall:     .\install_agent.ps1 -Token x -Uninstall" -ForegroundColor Gray
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""
