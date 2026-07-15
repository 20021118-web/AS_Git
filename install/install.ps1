# ============================================================
#  ServerBox 설치 스크립트 (Windows 10)
#  관리자 PowerShell 에서 실행:
#    Set-ExecutionPolicy Bypass -Scope Process -Force
#    .\install.ps1
#
#  하는 일:
#   1) Python 3.11 확인/설치 (winget)
#   2) 각 서비스용 가상환경 생성 + 패키지 설치
#   3) NSSM 으로 윈도우 서비스 등록 (부팅 시 자동 시작)
#   4) Caddy 게이트웨이 설치 (http://서버주소/parts)
#   5) 방화벽 개방 (80)
# ============================================================
$ErrorActionPreference = "Stop"
$ROOT = Split-Path -Parent $PSScriptRoot   # ServerBox 폴더
Write-Host "ServerBox 루트: $ROOT" -ForegroundColor Cyan

# ---------- 1) Python ----------
$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py -or -not ((& python --version) -match "3\.1[1-9]")) {
    Write-Host "Python 3.11 설치 중 (winget)..." -ForegroundColor Yellow
    winget install -e --id Python.Python.3.11 --accept-source-agreements --accept-package-agreements
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")
}
Write-Host ("Python: " + (& python --version)) -ForegroundColor Green

# ---------- 2) 가상환경 + 패키지 ----------
function New-Venv($name, $reqFile) {
    $venv = Join-Path $ROOT "venvs\$name"
    if (-not (Test-Path "$venv\Scripts\python.exe")) {
        Write-Host "[$name] 가상환경 생성..." -ForegroundColor Yellow
        python -m venv $venv
    }
    Write-Host "[$name] 패키지 설치... (수 분 소요)" -ForegroundColor Yellow
    & "$venv\Scripts\python.exe" -m pip install --upgrade pip -q
    & "$venv\Scripts\python.exe" -m pip install -r $reqFile
    return $venv
}
$venvParts = New-Venv "parts" (Join-Path $ROOT "apps\parts\requirements.txt")
$venvAi    = New-Venv "ai"    (Join-Path $ROOT "ai-server\requirements.txt")

# ---------- 3) NSSM (서비스 관리자) ----------
$nssm = Join-Path $ROOT "install\nssm.exe"
if (-not (Test-Path $nssm)) {
    Write-Host "NSSM 다운로드..." -ForegroundColor Yellow
    $zip = Join-Path $env:TEMP "nssm.zip"
    Invoke-WebRequest "https://nssm.cc/release/nssm-2.24.zip" -OutFile $zip
    Expand-Archive $zip -DestinationPath $env:TEMP -Force
    Copy-Item "$env:TEMP\nssm-2.24\win64\nssm.exe" $nssm
}

function Install-Svc($name, $exe, $args, $dir) {
    & $nssm stop $name 2>$null; & $nssm remove $name confirm 2>$null
    & $nssm install $name $exe $args
    & $nssm set $name AppDirectory $dir
    & $nssm set $name AppStdout (Join-Path $ROOT "logs\$name.log")
    & $nssm set $name AppStderr (Join-Path $ROOT "logs\$name.err.log")
    & $nssm set $name AppRotateFiles 1
    & $nssm set $name Start SERVICE_AUTO_START
    & $nssm start $name
    Write-Host "서비스 등록: $name" -ForegroundColor Green
}
New-Item -ItemType Directory -Force (Join-Path $ROOT "logs") | Out-Null

Install-Svc "ServerBox-AI"    "$venvAi\Scripts\python.exe"    "-m uvicorn main:app --host 127.0.0.1 --port 8100" (Join-Path $ROOT "ai-server")
Install-Svc "ServerBox-Parts" "$venvParts\Scripts\python.exe" "-m uvicorn main:app --host 127.0.0.1 --port 8001" (Join-Path $ROOT "apps\parts")

# ---------- 4) Caddy 게이트웨이 ----------
$caddy = Join-Path $ROOT "gateway\caddy.exe"
if (-not (Test-Path $caddy)) {
    Write-Host "Caddy 다운로드..." -ForegroundColor Yellow
    Invoke-WebRequest "https://caddyserver.com/api/download?os=windows&arch=amd64" -OutFile $caddy
}
Install-Svc "ServerBox-Gateway" $caddy "run --config Caddyfile" (Join-Path $ROOT "gateway")

# ---------- 5) 방화벽 ----------
New-NetFirewallRule -DisplayName "ServerBox HTTP" -Direction Inbound -Protocol TCP -LocalPort 80 -Action Allow -ErrorAction SilentlyContinue | Out-Null

$ip = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.*" } | Select-Object -First 1).IPAddress
Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host " 설치 완료!" -ForegroundColor Green
Write-Host " 다른 PC 에서 접속:  http://$ip/parts" -ForegroundColor Green
Write-Host " (AI 모델은 최초 사용 시 자동 다운로드됩니다)" -ForegroundColor Yellow
Write-Host "============================================" -ForegroundColor Cyan
