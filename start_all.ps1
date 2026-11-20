﻿﻿param(
    [switch]$NoWait
)

$ErrorActionPreference = "Stop"
$RootDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonExe = Join-Path $RootDir ".venv\Scripts\python.exe"
$WebDir = Join-Path $RootDir "web"

if (-not (Test-Path $PythonExe)) {
    Write-Error "未找到虚拟环境 Python: $PythonExe"
    exit 1
}

# 1. 启动银行业务中台 (8000)
Write-Host "[1/3] 正在启动银行业务中台 (127.0.0.1:8000)..." -ForegroundColor Cyan
$AppProc = Start-Process -FilePath "powershell.exe" -ArgumentList @(
    "-NoExit", "-Command", "Set-Location '$RootDir'; & '$PythonExe' -m app.main"
) -PassThru

# 2. 启动智能客服后端 (8001)
Write-Host "[2/3] 正在启动智能客服后端 (127.0.0.1:8001)..." -ForegroundColor Cyan
$ChatProc = Start-Process -FilePath "powershell.exe" -ArgumentList @(
    "-NoExit", "-Command", "Set-Location '$RootDir'; & '$PythonExe' -m chat_app.main"
) -PassThru

# 先等待两个后端服务直接就绪，再启动 Vite，避免前端代理在 8001 监听前报 ECONNREFUSED
Write-Host "等待后端服务 (8000 / 8001) 就绪..." -ForegroundColor Yellow
$BackendReady = $false
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 1
    try {
        $r8000 = Invoke-WebRequest -Uri "http://127.0.0.1:8000/docs" -UseBasicParsing -TimeoutSec 2
        $r8001 = Invoke-WebRequest -Uri "http://127.0.0.1:8001/health" -UseBasicParsing -TimeoutSec 2
        if ($r8000.StatusCode -eq 200 -and $r8001.StatusCode -eq 200) {
            $BackendReady = $true
            break
        }
    } catch {
        # 后端尚未就绪时继续轮询
    }
}

# 3. 启动前端开发服务器 (5173)
Write-Host "[3/3] 正在启动前端服务 (127.0.0.1:5173)..." -ForegroundColor Cyan
$WebProc = Start-Process -FilePath "powershell.exe" -ArgumentList @(
    "-NoExit", "-Command", "Set-Location '$WebDir'; npm run dev"
) -PassThru

# 等待前端代理就绪
$Ready = $false
for ($i = 0; $i -lt 20; $i++) {
    Start-Sleep -Seconds 1
    try {
        $res = Invoke-WebRequest -Uri "http://127.0.0.1:5173/health" -UseBasicParsing -TimeoutSec 2
        if ($res.StatusCode -eq 200) {
            $Ready = $true
            break
        }
    } catch {
        # 前端尚未就绪时继续轮询
    }
}

if ($BackendReady -and $Ready) {
    Write-Host "三端服务已全部就绪！" -ForegroundColor Green
} else {
    Write-Host "服务仍在启动中，请查看各服务窗口日志。" -ForegroundColor Yellow
}

Write-Host "前端访问地址: http://127.0.0.1:5173/" -ForegroundColor Green
Write-Host "中台接口文档: http://127.0.0.1:8000/docs" -ForegroundColor Gray
Write-Host "客服健康检查: http://127.0.0.1:8001/health" -ForegroundColor Gray

if ($NoWait) {
    exit 0
}

Read-Host "按 Enter 键停止以上全部服务窗口" | Out-Null

foreach ($p in @($WebProc, $ChatProc, $AppProc)) {
    if ($p -and -not $p.HasExited) {
        # 使用 taskkill /T 一并清理子进程树（如 vite/node 与 uvicorn）
        & taskkill.exe /PID $p.Id /T /F | Out-Null
    }
}
Write-Host "已停止全部服务。" -ForegroundColor Cyan
