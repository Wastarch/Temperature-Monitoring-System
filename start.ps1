#Requires -Version 5.1
<#
.SYNOPSIS
    多通道温度监控系统 - 启动脚本
.DESCRIPTION
    提供菜单选择启动上位机、下位机或安装依赖
#>

$ErrorActionPreference = "Stop"

# 项目路径
$RootDir   = Split-Path -Parent $MyInvocation.MyCommand.Path
$UpperDir  = Join-Path $RootDir "upper computer"
$LowerDir  = Join-Path $RootDir "lower computer"

# 颜色函数
function Write-Banner {
    Write-Host ""
    Write-Host "=====================================" -ForegroundColor Cyan
    Write-Host "  多通道温度监控系统 - 启动脚本 v1.0" -ForegroundColor Cyan
    Write-Host "=====================================" -ForegroundColor Cyan
    Write-Host ""
}

function Write-Menu {
    Write-Host ""
    Write-Host "请选择操作：" -ForegroundColor White
    Write-Host "  1. 启动上位机 (GUI 界面)" -ForegroundColor Green
    Write-Host "  2. 启动下位机 (数据模拟器)" -ForegroundColor Green
    Write-Host "  3. 同时启动上位机和下位机" -ForegroundColor Green
    Write-Host "  4. 仅安装/更新依赖" -ForegroundColor Green
    Write-Host "  0. 退出" -ForegroundColor Red
    Write-Host ""
}

function Test-CommandExists {
    param([string]$Command)
    $null -ne (Get-Command $Command -ErrorAction SilentlyContinue)
}

function Install-ProjectDeps {
    param(
        [string]$Path,
        [string]$Label
    )
    Write-Host "  [$Label] 正在安装依赖..." -ForegroundColor Cyan
    Push-Location $Path
    try {
        & uv sync
        if ($LASTEXITCODE -eq 0) {
            Write-Host "  [$Label] 依赖安装完成" -ForegroundColor Green
        } else {
            Write-Host "  [$Label] 依赖安装失败 (exit code: $LASTEXITCODE)" -ForegroundColor Red
        }
    } catch {
        Write-Host "  [$Label] 依赖安装异常: $_" -ForegroundColor Red
    } finally {
        Pop-Location
    }
}

function Start-Upper {
    Write-Host ""
    Write-Host "--- 启动上位机 ---" -ForegroundColor White
    Write-Host ""
    Install-ProjectDeps -Path $UpperDir -Label "上位机"

    if (-not (Test-Path (Join-Path $UpperDir "main.py"))) {
        Write-Host "  [上位机] 未找到入口文件 main.py" -ForegroundColor Red
        return
    }

    Write-Host "  [上位机] 正在启动..." -ForegroundColor Green
    Start-Process -FilePath "uv" -ArgumentList "run", "main.py" -WorkingDirectory $UpperDir
    Write-Host "  [上位机] 已在新窗口启动" -ForegroundColor Green
    Write-Host ""
}

function Start-Lower {
    Write-Host ""
    Write-Host "--- 启动下位机 ---" -ForegroundColor White
    Write-Host ""
    Install-ProjectDeps -Path $LowerDir -Label "下位机"

    if (-not (Test-Path (Join-Path $LowerDir "main.py"))) {
        Write-Host "  [下位机] 未找到入口文件 main.py" -ForegroundColor Red
        return
    }

    Write-Host "  [下位机] 正在启动..." -ForegroundColor Green
    Start-Process -FilePath "uv" -ArgumentList "run", "main.py" -WorkingDirectory $LowerDir
    Write-Host "  [下位机] 已在新窗口启动" -ForegroundColor Green
    Write-Host ""
}

function Start-Both {
    Write-Host ""
    Write-Host "--- 同时启动上位机和下位机 ---" -ForegroundColor White
    Write-Host ""
    Install-ProjectDeps -Path $UpperDir -Label "上位机"
    Install-ProjectDeps -Path $LowerDir -Label "下位机"

    if (Test-Path (Join-Path $LowerDir "main.py")) {
        Write-Host "  [下位机] 正在启动..." -ForegroundColor Green
        Start-Process -FilePath "uv" -ArgumentList "run", "main.py" -WorkingDirectory $LowerDir
        Write-Host "  [下位机] 已在新窗口启动" -ForegroundColor Green
    } else {
        Write-Host "  [下位机] 未找到入口文件 main.py" -ForegroundColor Red
    }

    if (Test-Path (Join-Path $UpperDir "main.py")) {
        Write-Host "  [上位机] 正在启动..." -ForegroundColor Green
        Start-Process -FilePath "uv" -ArgumentList "run", "main.py" -WorkingDirectory $UpperDir
        Write-Host "  [上位机] 已在新窗口启动" -ForegroundColor Green
    } else {
        Write-Host "  [上位机] 未找到入口文件 main.py" -ForegroundColor Red
    }
    Write-Host ""
}

function Install-AllDeps {
    Write-Host ""
    Write-Host "--- 安装依赖 ---" -ForegroundColor White
    Write-Host ""
    Install-ProjectDeps -Path $UpperDir -Label "上位机"
    Install-ProjectDeps -Path $LowerDir -Label "下位机"
    Write-Host ""
}

# ========== 主程序 ==========

# 检查 uv
if (-not (Test-CommandExists "uv")) {
    Write-Host ""
    Write-Host "错误: 未找到 uv 命令行工具" -ForegroundColor Red
    Write-Host "请先安装 uv:" -ForegroundColor Yellow
    Write-Host "  irm https://astral.sh/uv/install.ps1 | iex" -ForegroundColor Cyan
    Write-Host ""
    Read-Host "按回车键退出"
    exit 1
}

# 检查项目目录
if (-not (Test-Path $UpperDir) -or -not (Test-Path $LowerDir)) {
    Write-Host ""
    Write-Host "错误: 未找到项目子目录" -ForegroundColor Red
    Write-Host "  期望路径: $UpperDir" -ForegroundColor Yellow
    Write-Host "  期望路径: $LowerDir" -ForegroundColor Yellow
    Write-Host ""
    Read-Host "按回车键退出"
    exit 1
}

# 主循环
try {
    :mainLoop while ($true) {
        Write-Banner
        Write-Menu

        $choice = Read-Host "请输入选项 (0-4)"

        switch ($choice) {
            "1" { Start-Upper }
            "2" { Start-Lower }
            "3" { Start-Both }
            "4" { Install-AllDeps }
            "0" {
                Write-Host ""
                Write-Host "再见！" -ForegroundColor Green
                Write-Host ""
                break mainLoop
            }
            default {
                Write-Host ""
                Write-Host "无效选项，请重新输入" -ForegroundColor Yellow
                Write-Host ""
            }
        }
    }
} finally {
    Write-Host ""
    Write-Host "已退出" -ForegroundColor Green
}
