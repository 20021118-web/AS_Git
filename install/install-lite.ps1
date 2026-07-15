# ============================================================
#  ServerBox 1단계 설치 — "일단 연결만" (초경량)
#
#  파이썬·AI 없이 게이트웨이(Caddy)만 설치해서
#  다른 PC 에서  http://서버IP  로 부품 매칭 웹(브라우저 계산판)을
#  바로 쓸 수 있게 한다.  램 사용량 ~30MB.
#
#  관리자 PowerShell 에서 실행:
#    Set-ExecutionPolicy Bypass -Scope Process -Force
#    .\install-lite.ps1
#
#  나중에 서버 계산판(SIFT+배경제거)까지 쓰려면 install.ps1 을 추가 실행.
# ============================================================
$ErrorActionPreference = "Stop"
$ROOT = Split-Path -Parent $PSScriptRoot   # ServerBox 폴더
Write-Host "ServerBox 루트: $ROOT" -ForegroundColor Cyan

# ---------- 1) NSSM (서비스 등록 도구) ----------
$nssm = Join-Path $ROOT "install\nssm.exe"
if (-not (Test-Path $nssm)) {
    Write-Host "NSSM 다운로드..." -ForegroundColor Yellow
    $zip = Join-Path $env:TEMP "nssm.zip"
    Invoke-WebRequest "https://nssm.cc/release/nssm-2.24.zip" -OutFile $zip
    Expand-Archive $zip -DestinationPath $env:TEMP -Force
    Copy-Item "$env:TEMP\nssm-2.24\win64\nssm.exe" $nssm
}

# ---------- 2) Caddy (게이트웨이 웹서버) ----------
$caddy = Join-Path $ROOT "gateway\caddy.exe"
if (-not (Test-Path $caddy)) {
    Write-Host "Caddy 다운로드... (~40MB)" -ForegroundColor Yellow
    Invoke-WebRequest "https://caddyserver.com/api/download?os=windows&arch=amd64" -OutFile $caddy
}

# ---------- 3) 서비스 등록 (부팅 자동시작) ----------
New-Item -ItemType Directory -Force (Join-Path $ROOT "logs") | Out-Null
& $nssm stop ServerBox-Gateway 2>$null; & $nssm remove ServerBox-Gateway confirm 2>$null
& $nssm install ServerBox-Gateway $caddy "run --config Caddyfile"
& $nssm set ServerBox-Gateway AppDirectory (Join-Path $ROOT "gateway")
& $nssm set ServerBox-Gateway AppStdout (Join-Path $ROOT "logs\gateway.log")
& $nssm set ServerBox-Gateway AppStderr (Join-Path $ROOT "logs\gateway.err.log")
& $nssm set ServerBox-Gateway Start SERVICE_AUTO_START
& $nssm start ServerBox-Gateway
Write-Host "서비스 등록: ServerBox-Gateway" -ForegroundColor Green

# ---------- 4) 방화벽 개방 (80) ----------
New-NetFirewallRule -DisplayName "ServerBox HTTP" -Direction Inbound -Protocol TCP `
    -LocalPort 80 -Action Allow -Profile Any -ErrorAction SilentlyContinue | Out-Null

# ---------- 완료 안내 ----------
Start-Sleep 2
$ip = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.*" } | Select-Object -First 1).IPAddress
Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host " 1단계 설치 완료!  (게이트웨이만, 램 ~30MB)" -ForegroundColor Green
Write-Host ""
Write-Host " 이 PC 에서 확인   :  http://localhost/web" -ForegroundColor Green
Write-Host " 업무 PC 에서 접속 :  http://$ip/web" -ForegroundColor Green
Write-Host ""
Write-Host " * 서버 계산판(/parts)까지 쓰려면 나중에 install.ps1 실행" -ForegroundColor Yellow
Write-Host "============================================" -ForegroundColor Cyan
