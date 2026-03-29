# openbook installer for Windows PowerShell
$ErrorActionPreference = "Stop"

$repo = "mjwsolo/openbook"
$installDir = "$env:USERPROFILE\.openbook"

Write-Host ""
Write-Host "  ⣿ installing openbook..." -ForegroundColor DarkYellow
Write-Host ""

# Check Python
try {
    $pyVersion = python3 --version 2>&1
    Write-Host "  ✓ $pyVersion found" -ForegroundColor Green
} catch {
    try {
        $pyVersion = python --version 2>&1
        Write-Host "  ✓ $pyVersion found" -ForegroundColor Green
    } catch {
        Write-Host "  ✗ Python 3 is required. Install from https://python.org" -ForegroundColor Red
        exit 1
    }
}

# Create install directory
New-Item -ItemType Directory -Force -Path $installDir | Out-Null

# Download
Write-Host "  ↓ Downloading openbook..."
Invoke-WebRequest -Uri "https://raw.githubusercontent.com/$repo/main/openbook.py" -OutFile "$installDir\openbook.py"
Write-Host "  ✓ Downloaded to $installDir\openbook.py" -ForegroundColor Green

# Create batch launcher
@"
@echo off
python3 "%USERPROFILE%\.openbook\openbook.py" %*
"@ | Out-File -FilePath "$installDir\openbook.cmd" -Encoding ASCII

# Add to PATH
$currentPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($currentPath -notlike "*\.openbook*") {
    [Environment]::SetEnvironmentVariable("Path", "$installDir;$currentPath", "User")
    $env:Path = "$installDir;$env:Path"
    Write-Host "  ✓ Added to PATH" -ForegroundColor Green
} else {
    Write-Host "  ✓ Already in PATH" -ForegroundColor Green
}

Write-Host ""
Write-Host "  ✓ openbook installed!" -ForegroundColor Green
Write-Host ""
Write-Host "  Run it now:" -ForegroundColor DarkYellow
Write-Host "    openbook"
Write-Host ""

# Run immediately
python3 "$installDir\openbook.py"
