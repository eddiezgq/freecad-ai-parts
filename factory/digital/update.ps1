# 问渠数字工厂：从 GitHub 拉取最新版本并重启（在 digital 目录里运行：.\update.ps1）
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
git pull --ff-only
docker compose up -d --build
docker compose ps
Write-Host "已更新到最新版本：http://localhost:8100"
