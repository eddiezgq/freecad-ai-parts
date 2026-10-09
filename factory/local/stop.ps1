# 停止本地工厂（数据保留）；加 -Reset 连数据一起删。
param([switch]$Reset)
Push-Location (Join-Path $PSScriptRoot "..\digital")
try { if ($Reset) { docker compose --profile mock down -v } else { docker compose --profile mock down } } finally { Pop-Location }
