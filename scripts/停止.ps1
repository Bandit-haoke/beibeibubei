# ============================================================================
#  背备不悲 · 停止全部服务
#
#  只停宿主机上的 Java 与 Python 进程，不碰虚拟机里的 Docker 容器。
# ============================================================================

$ErrorActionPreference = 'Continue'

function Write-Step($t) { Write-Host "`n>>> $t" -ForegroundColor Cyan }
function Write-Ok($t)   { Write-Host "    [OK]   $t" -ForegroundColor Green }
function Write-Warn($t) { Write-Host "    [WARN] $t" -ForegroundColor Yellow }

Write-Host ""
Write-Host "================================================================" -ForegroundColor White
Write-Host "   背备不悲 · 停止服务" -ForegroundColor White
Write-Host "================================================================" -ForegroundColor White

foreach ($port in 8080, 8000) {
    Write-Step "停止占用 $port 端口的进程"
    $conns = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if (-not $conns) { Write-Warn "端口 $port 没有监听进程"; continue }
    foreach ($procId in ($conns.OwningProcess | Select-Object -Unique)) {
        try {
            $p = Get-Process -Id $procId -ErrorAction Stop
            Stop-Process -Id $procId -Force
            Write-Ok "已停止 $($p.ProcessName) (PID $procId)"
        } catch { Write-Warn "PID $procId 停止失败：$($_.Exception.Message)" }
    }
}

Write-Host ""
Write-Host "完成。虚拟机里的 MySQL / Milvus 未受影响。" -ForegroundColor DarkGray
Write-Host ""
