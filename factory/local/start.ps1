# 问渠数字工厂 · 本地版（ADR-0058）：Windows 上用 Docker Desktop 启动整座工厂。
# 用法（PowerShell，在仓库根目录）：.\factory\local\start.ps1 [-Prod] [-ErpNext URL]
param([switch]$Prod, [string]$ErpNext = "")
$ErrorActionPreference = "Stop"
$dig = Join-Path $PSScriptRoot "..\digital"
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { throw "没有找到 docker：请先安装并启动 Docker Desktop" }
$envFile = Join-Path $dig ".env"
if (-not (Test-Path $envFile)) {
  Copy-Item (Join-Path $dig ".env.example") $envFile
  $secret = -join ((48..57) + (65..90) + (97..122) | Get-Random -Count 32 | ForEach-Object { [char]$_ })
  (Get-Content $envFile) -replace '^WQ_SECRET=.*', "WQ_SECRET=$secret" | Set-Content -Encoding utf8 $envFile
  Write-Host "已生成 $envFile（登录签名密钥随机生成；AI 助手的密钥可在里面填）"
}
function Set-Env($key, $value) {
  $lines = Get-Content $envFile
  if ($lines -match "^$key=") { $lines = $lines -replace "^$key=.*", "$key=$value" } else { $lines += "$key=$value" }
  $lines | Set-Content -Encoding utf8 $envFile
}
Set-Env "WQ_MODE" ($(if ($Prod) { "prod" } else { "teach" }))
Set-Env "WQ_EDITION" "local"
$profileArgs = @()
if ($ErpNext) { Set-Env "WQ_ERPNEXT_API" $ErpNext; Set-Env "WQ_ERPNEXT_URL" $ErpNext }
else {
  Set-Env "WQ_ERPNEXT_API" "http://mock-erpnext:8091"; Set-Env "WQ_ERPNEXT_URL" "http://localhost:8091"
  $profileArgs = @("--profile", "mock")
}
Push-Location $dig
try { & docker compose @profileArgs up -d --build; if ($LASTEXITCODE -ne 0) { throw "docker compose 启动失败" } } finally { Pop-Location }
Write-Host "等工厂枢纽启动 …"
for ($i = 0; $i -lt 120; $i++) {
  try { Invoke-RestMethod http://localhost:8100/api/health | Out-Null; Write-Host "已启动：打开 http://localhost:8100"; Start-Process "http://localhost:8100"; exit 0 } catch { Start-Sleep 2 }
}
throw "枢纽 4 分钟内没有就绪，看日志：cd factory\digital; docker compose logs hub"
