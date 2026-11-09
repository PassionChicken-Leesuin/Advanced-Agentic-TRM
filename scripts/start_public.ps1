# 공개 운영 시작 스크립트: 에이전트 서버(8765)와 고정 주소 터널(api.suinlee-trm.com)을 켠다.
# 이미 켜져 있으면 건너뛴다. 로그인할 때 예약 작업(TRM public server)이 실행한다. 직접 실행해도 된다.
$ErrorActionPreference = "Continue"
$code = Split-Path -Parent $PSScriptRoot
$py = "C:\Users\User\AppData\Local\Python\bin\python.exe"
$cf = "C:\Users\User\dev\tools\cloudflared.exe"
$cfg = "C:\ProgramData\cloudflared\config.yml"
$logs = Join-Path $env:LOCALAPPDATA "trmkb-logs"
New-Item -ItemType Directory -Force $logs | Out-Null
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"

if (-not (Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue)) {
    Start-Process -FilePath $py -ArgumentList "-m","uvicorn","viz.server:app","--port","8765" -WorkingDirectory $code `
        -WindowStyle Hidden -RedirectStandardOutput "$logs\server_$stamp.out.log" -RedirectStandardError "$logs\server_$stamp.err.log"
    "server started"
} else { "server already running" }

$named = Get-CimInstance Win32_Process -Filter "name='cloudflared.exe'" | Where-Object { $_.CommandLine -match "trm-api" }
if (-not $named) {
    Start-Process -FilePath $cf -ArgumentList "tunnel","--config",$cfg,"run","trm-api" -WindowStyle Hidden `
        -RedirectStandardOutput "$logs\tunnel_$stamp.out.log" -RedirectStandardError "$logs\tunnel_$stamp.err.log"
    "tunnel started"
} else { "tunnel already running" }
