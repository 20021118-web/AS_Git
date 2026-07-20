# 서버 PC에서 "관리자 권한 PowerShell"로 실행하세요.
#   예)  powershell -ExecutionPolicy Bypass -File .\join_u2net.ps1
# 같은 폴더의 u2net.part1~7 을 합쳐 u2net.onnx 를 복원하고,
# 무결성(SHA256) 확인 후 rembg 가 찾는 두 위치에 설치, 서비스를 재시작합니다.

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$parts = Get-ChildItem "$here\u2net_part*.txt" | Sort-Object { [int]($_.BaseName -replace '\D','') }
if ($parts.Count -lt 7) { Write-Host "조각 파일이 부족합니다 ($($parts.Count)/7)" -ForegroundColor Red; exit 1 }

$out = Join-Path $here "u2net.onnx"
$fs = [IO.File]::Create($out)
foreach ($p in $parts) {
    $b = [IO.File]::ReadAllBytes($p.FullName)
    $fs.Write($b, 0, $b.Length)
    Write-Host "합침: $($p.Name) ($([math]::Round($b.Length/1MB))MB)"
}
$fs.Close()

# 무결성 확인
$expected = (Get-Content "$here\sha256.txt").Trim()
$actual = (Get-FileHash $out -Algorithm SHA256).Hash
if ($actual -ne $expected) { Write-Host "SHA256 불일치! 조각 파일을 다시 받으세요." -ForegroundColor Red; exit 1 }
Write-Host "무결성 확인 OK ($actual)" -ForegroundColor Green

# 두 위치에 설치 (서비스 계정용 + 로그인 계정용)
$targets = @("C:\Windows\System32\config\systemprofile\.u2net", "$env:USERPROFILE\.u2net")
foreach ($t in $targets) {
    New-Item -ItemType Directory -Force $t | Out-Null
    Copy-Item $out (Join-Path $t "u2net.onnx") -Force
    Write-Host "설치: $t\u2net.onnx" -ForegroundColor Green
}

# 서비스 재시작
Stop-Service ServerBox-Parts -Force -ErrorAction SilentlyContinue
Start-Service ServerBox-Parts
Start-Sleep -Seconds 3
Get-Service ServerBox-Parts | Format-List Name, Status
Write-Host "완료! 웹 화면에서 'AI 배경 제거 사용'을 켜고 1건만 내보내기 테스트해 보세요." -ForegroundColor Green
