# SatDashboard Rust 單機版：同時建置 Windows x86_64 與 ARM64，輸出至 dist\
# 用法：pwsh -File scripts\build.ps1   （需 Rust stable、VS2022 Build Tools；ARM64 主機另需 LLVM clang）
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

# ring（DuckDB 建置期相依）在 aarch64-windows 需要 clang
$llvm = 'C:\Program Files\LLVM\bin'
if ((Test-Path "$llvm\clang.exe") -and -not ($env:PATH -split ';' -contains $llvm)) {
    $env:PATH = "$env:PATH;$llvm"
}

$targets = @(
    @{ triple = 'x86_64-pc-windows-msvc';  name = 'SatDashboard-x64.exe' },
    @{ triple = 'aarch64-pc-windows-msvc'; name = 'SatDashboard-arm64.exe' }
)
foreach ($t in $targets) { rustup target add $t.triple | Out-Null }

New-Item -ItemType Directory -Force dist | Out-Null
foreach ($t in $targets) {
    Write-Host "== 建置 $($t.triple) ==" -ForegroundColor Cyan
    cargo build --release --target $t.triple
    if ($LASTEXITCODE -ne 0) { throw "建置失敗：$($t.triple)" }
    Copy-Item "target\$($t.triple)\release\SatDashboard.exe" "dist\$($t.name)" -Force
}

# 啟動捷徑：依本機架構挑對應執行檔
@'
@echo off
chcp 65001 >nul
cd /d "%~dp0"
if /I "%PROCESSOR_ARCHITECTURE%"=="ARM64" (set EXE=SatDashboard-arm64.exe) else (set EXE=SatDashboard-x64.exe)
"%EXE%" %*
pause
'@ -replace "`n", "`r`n" | Set-Content -Encoding ascii dist\SatDashboard.bat

Get-ChildItem dist | Format-Table Name, @{n='MB';e={[math]::Round($_.Length/1MB,1)}}
Write-Host "完成。DB 預設以相對路徑 ..\scenario-advanced01\DB\space_db_slim.duckdb 尋找（可用 --db 覆寫）。" -ForegroundColor Green
