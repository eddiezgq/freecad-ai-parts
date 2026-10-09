# Windows 单机安装版验收（ADR-0066 第 4 项）：静默安装 → 用装好的 FreeCAD 跑 acceptance.py → 静默卸载。
#   powershell -ExecutionPolicy Bypass -File installer\windows\accept.ps1 -Dist dist -Dir C:\fap-test
param([string]$Dist = "dist", [string]$Dir = "C:\fap-test")
$ErrorActionPreference = "Continue"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$setup = (Get-ChildItem $Dist -Filter "FreeCAD-AI-Parts-Setup-*.exe" | Select-Object -First 1).FullName
if (-not $setup) { Write-Host "找不到安装包"; exit 1 }
$log = Join-Path $env:TEMP "fap-setup.log"
Write-Host "静默安装 $setup 到 $Dir"
$p = Start-Process -FilePath $setup -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/DIR=$Dir", "/LOG=$log" -Wait -PassThru
if ($p.ExitCode -ne 0) { Get-Content $log -Tail 30; Write-Host "安装失败：$($p.ExitCode)"; exit 1 }
if (-not (Test-Path "$Dir\Mod\FreeCADAIParts\InitGui.py")) { Write-Host "安装目录里没有工作台"; exit 1 }
Push-Location $env:TEMP
& "$Dir\bin\python.exe" "$PSScriptRoot\acceptance.py" $Dir 2>&1 | ForEach-Object { "$_" }
$rc = $LASTEXITCODE
Pop-Location
if ($rc -ne 0) { Write-Host "验收不通过"; exit 1 }
Write-Host "静默卸载"
$u = Start-Process -FilePath "$Dir\unins000.exe" -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART" -Wait -PassThru
Start-Sleep -Seconds 5
if ($u.ExitCode -ne 0 -or (Test-Path "$Dir\bin\FreeCAD.exe")) { Write-Host "卸载没有清干净"; exit 1 }
Write-Host "静默安装、验收、卸载都通过"
exit 0
