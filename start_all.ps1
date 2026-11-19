param(
    [switch]$Restart,
    [switch]$Stop
)

$ErrorActionPreference = "Stop"
$RootDir = $PSScriptRoot
$FrontendDir = Join-Path $RootDir "customer-service-frontend"

function Get-PortPids([int]$Port) {
    $conns = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if (-not $conns) { return @() }
    return ($conns | Select-Object -ExpandProperty OwningProcess -Unique)
}

function Stop-ServicePort([int]$Port, [string]$Label) {
    $pids = Get-PortPids $Port
    foreach ($procId in $pids) {
        if ($procId -gt 0) {
            Write-Host "停止 $Label (端口 $Port, PID $procId)..." -ForegroundColor Yellow
            Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
        }
    }
}

if ($Stop) {
    Stop-ServicePort 8000 "银行中台 (app.main)"
    Stop-ServicePort 8001 "银行智能客服 (atguigu.main)"
    Stop-ServicePort 5173 "前端页面 (Vite)"
    Write-Host "所有服务已停止。" -ForegroundColor Green
    exit 0
}

$services = @(
    @{
        Port  = 8000
        Name  = "银行中台 (app.main)"
        Dir   = $RootDir
        Cmd   = "uv run -m app.main"
    },
    @{
        Port  = 8001
        Name  = "银行智能客服 (atguigu.main)"
        Dir   = $RootDir
        Cmd   = "uv run -m atguigu.main"
    },
    @{
        Port  = 5173
        Name  = "前端页面 (Vite)"
        Dir   = $FrontendDir
        Cmd   = "npm run dev"
    }
)

foreach ($svc in $services) {
    $existing = Get-PortPids $svc.Port
    if ($existing.Count -gt 0) {
        if ($Restart) {
            Stop-ServicePort $svc.Port $svc.Name
            Start-Sleep -Milliseconds 500
        } else {
            Write-Host "[跳过] $($svc.Name) 端口 $($svc.Port) 已被占用 (PID: $($existing -join ', '))。如需重启请加 -Restart" -ForegroundColor DarkYellow
            continue
        }
    }

    Write-Host "[启动] $($svc.Name) -> 端口 $($svc.Port)..." -ForegroundColor Cyan
    $psCmd = "`$Host.UI.RawUI.WindowTitle = '$($svc.Name) [$($svc.Port)]'; Set-Location -LiteralPath '$($svc.Dir)'; $($svc.Cmd)"
    Start-Process powershell -ArgumentList "-NoExit", "-Command", $psCmd | Out-Null
}

Write-Host ""
Write-Host "访问地址：" -ForegroundColor Green
Write-Host "  前端聊天页面 : http://127.0.0.1:5173"
Write-Host "  智能客服接口 : http://127.0.0.1:8001/docs"
Write-Host "  银行中台接口 : http://127.0.0.1:8000/docs"
Write-Host ""
Write-Host "常用参数：.\start_all.ps1 -Restart (重启全部) | .\start_all.ps1 -Stop (停止全部)" -ForegroundColor Gray
