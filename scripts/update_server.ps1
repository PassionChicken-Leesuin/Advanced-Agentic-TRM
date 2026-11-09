# 서버 갱신: GitHub 최신 코드를 받고 에이전트 서버를 다시 켠다. 원격 데스크톱으로 접속해 오른쪽 클릭 → "PowerShell에서 실행".
# 진행 중인 업로드 작업이 있으면 멈춘다. 새 코드가 불러지지 않으면 이전 커밋으로 되돌리고 서버는 건드리지 않는다.
$code = Split-Path -Parent $PSScriptRoot
$py = "C:\Users\User\AppData\Local\Python\bin\python.exe"
Set-Location $code

$active = Get-ChildItem "$code\runs\up_*\job.json" -ErrorAction SilentlyContinue | Where-Object {
    $s = (Get-Content $_.FullName -Raw -Encoding UTF8 | ConvertFrom-Json).status
    $s -notin @("done", "error")
}
if ($active) { "An upload job is still running: $($active[0].Directory.Name). Try again after it finishes."; Read-Host "Press Enter to close"; exit 1 }

$before = (git rev-parse HEAD).Trim()
git pull --ff-only origin main
if ($LASTEXITCODE -ne 0) { "git pull failed (local changes or diverged history). Server left as is."; Read-Host "Press Enter to close"; exit 1 }
$after = (git rev-parse HEAD).Trim()

& $py -c "import viz.server"
if ($LASTEXITCODE -ne 0) {
    "New code does not load. Rolling back to $before; server left as is."
    git reset --hard $before
    Read-Host "Press Enter to close"; exit 1
}

$conn = Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue
if ($conn) { Stop-Process -Id $conn.OwningProcess -Force; Start-Sleep -Seconds 2 }
& "$PSScriptRoot\start_public.ps1"
Start-Sleep -Seconds 6
try { $r = Invoke-WebRequest "https://api.suinlee-trm.com/api/v2/runs" -UseBasicParsing -TimeoutSec 20; "public check: HTTP $($r.StatusCode)" } catch { "public check failed: $_" }
if ($before -eq $after) { "Already up to date ($after)." } else { "Updated $before -> $after." }
Read-Host "Press Enter to close"
