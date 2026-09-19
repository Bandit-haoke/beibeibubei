# ============================================================================
#  背备不悲 · 一键启动
#
#  做四件事：
#    1. 检查 Linux 虚拟机里的 MySQL / Milvus 是否可达
#    2. 启动 beibei-agent（Python，新窗口）
#    3. 等它就绪后启动 beibei-server（Java，新窗口）
#    4. 等 8080 起来后自动打开浏览器
#
#  用法（在项目根目录）：
#    powershell -ExecutionPolicy Bypass -File scripts\一键启动.ps1
#  或直接双击 scripts\一键启动.bat
# ============================================================================

$ErrorActionPreference = 'Continue'

# ---------------------------- 路径与配置 ----------------------------
$Root        = Split-Path -Parent $PSScriptRoot
$AgentDir    = Join-Path $Root 'beibei-agent'
$ServerDir   = Join-Path $Root 'beibei-server'
$PythonExe   = 'D:\conda-envs\beibei\python.exe'
$JavaExe     = 'D:\java\bin\java.exe'
$ServerJar   = Join-Path $ServerDir 'target\beibei-server-0.1.0.jar'
$VmHost      = '192.168.1.100'
$AgentPort   = 8000
$ServerPort  = 8080

function Write-Step($text) { Write-Host "`n>>> $text" -ForegroundColor Cyan }
function Write-Ok($text)   { Write-Host "    [OK]   $text" -ForegroundColor Green }
function Write-Bad($text)  { Write-Host "    [FAIL] $text" -ForegroundColor Red }
function Write-Warn($text) { Write-Host "    [WARN] $text" -ForegroundColor Yellow }

function Test-Port($computer, $port) {
    try {
        $c = New-Object System.Net.Sockets.TcpClient
        $r = $c.BeginConnect($computer, $port, $null, $null)
        $ok = $r.AsyncWaitHandle.WaitOne(3000, $false) -and $c.Connected
        $c.Close()
        return $ok
    } catch { return $false }
}

function Wait-Port($computer, $port, $timeoutSec, $label) {
    for ($i = 1; $i -le $timeoutSec; $i++) {
        if (Test-Port $computer $port) { return $true }
        Start-Sleep -Seconds 1
    }
    return $false
}

Write-Host ""
Write-Host "================================================================" -ForegroundColor White
Write-Host "   背备不悲 · 一键启动" -ForegroundColor White
Write-Host "   背得会 · 备得全 · 考不悲" -ForegroundColor DarkGray
Write-Host "================================================================" -ForegroundColor White

# ---------------------------- 1. 中间件自检 ----------------------------
Write-Step "检查 Linux 虚拟机（$VmHost）里的中间件"

if (Test-Port $VmHost 3306) { Write-Ok "MySQL   $VmHost`:3306 可达" } else { Write-Bad "MySQL   $VmHost`:3306 不可达 —— 请先启动虚拟机" }
if (Test-Port $VmHost 19530) { Write-Ok "Milvus  $VmHost`:19530 可达" } else { Write-Bad "Milvus  $VmHost`:19530 不可达 —— docker ps 看下 milvus-standalone" }

# ---------------------------- 2. 环境检查 ----------------------------
Write-Step "检查本地运行环境"

if (Test-Path $PythonExe) { Write-Ok "Python  $PythonExe" } else { Write-Bad "找不到 $PythonExe（conda 环境 beibei）"; Read-Host "按回车退出"; exit 1 }
if (Test-Path $JavaExe)   { Write-Ok "Java    $JavaExe" }   else { Write-Bad "找不到 $JavaExe"; Read-Host "按回车退出"; exit 1 }

if (-not (Test-Path $ServerJar)) {
    Write-Warn "还没打包，正在用 Maven 构建 ..."
    $env:JAVA_HOME = 'D:\java'
    Push-Location $ServerDir
    & 'D:\tools\maven\bin\mvn.cmd' -B clean package -DskipTests
    Pop-Location
}
if (Test-Path $ServerJar) { Write-Ok "Jar     $ServerJar" } else { Write-Bad "构建失败，请手动在 IDEA 里打包"; Read-Host "按回车退出"; exit 1 }

# ---------------------------- 3. 启动 Python ----------------------------
Write-Step "启动 beibei-agent（Python 智能体）"

if (Test-Port '127.0.0.1' $AgentPort) {
    Write-Warn "$AgentPort 端口已被占用，跳过启动（可能已经在运行）"
} else {
    Start-Process -FilePath $PythonExe `
        -ArgumentList 'run.py' `
        -WorkingDirectory $AgentDir `
        -WindowStyle Minimized
    Write-Host "    等待智能体就绪 ..." -NoNewline
    if (Wait-Port '127.0.0.1' $AgentPort 90) { Write-Host "" ; Write-Ok "beibei-agent 已就绪 http://127.0.0.1:$AgentPort/docs" }
    else { Write-Host "" ; Write-Bad "智能体 90 秒内未就绪 —— 去那个最小化的窗口看报错" }
}

# ---------------------------- 4. 启动 Java ----------------------------
Write-Step "启动 beibei-server（Java 网关）"

if (Test-Port '127.0.0.1' $ServerPort) {
    Write-Warn "$ServerPort 端口已被占用，跳过启动（可能已经在运行）"
} else {
    $env:JAVA_HOME = 'D:\java'
    Start-Process -FilePath $JavaExe `
        -ArgumentList @('-Duser.timezone=Asia/Shanghai', '-jar', $ServerJar) `
        -WorkingDirectory $ServerDir `
        -WindowStyle Minimized
    Write-Host "    等待后端就绪 ..." -NoNewline
    if (Wait-Port '127.0.0.1' $ServerPort 120) { Write-Host "" ; Write-Ok "beibei-server 已就绪" }
    else { Write-Host "" ; Write-Bad "后端 120 秒内未就绪 —— 去那个最小化的窗口看报错" }
}

# ---------------------------- 5. 打开浏览器 ----------------------------
Write-Step "打开浏览器"

$url = "http://localhost:$ServerPort"
Start-Process $url
Write-Ok $url

Write-Host ""
Write-Host "================================================================" -ForegroundColor White
Write-Host "  两个服务都跑在独立窗口里，关掉窗口即停止对应服务" -ForegroundColor DarkGray
Write-Host "  Java 日志 → beibei-server 窗口" -ForegroundColor DarkGray
Write-Host "  Python 日志 → beibei-agent 窗口，也可看 beibei-agent\logs\agent.log" -ForegroundColor DarkGray
Write-Host "================================================================" -ForegroundColor White
Write-Host ""
