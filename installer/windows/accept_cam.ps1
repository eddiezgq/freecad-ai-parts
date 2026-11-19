# 问渠CAM Windows 安装包验收（ADR-0104 产品化）：静默安装 → 用装好的 FreeCAD 跑 acceptance_cam.py → 静默卸载。
#   powershell -ExecutionPolicy Bypass -File installer\windows\accept_cam.ps1 -Dist dist -Dir C:\wq-cam-test
param([string]$Dist = "dist", [string]$Dir = "C:\wq-cam-test")
$ErrorActionPreference = "Continue"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$Repo = (Resolve-Path "$PSScriptRoot\..\..").Path
$setup = (Get-ChildItem $Dist -Filter "WenQuest-CAM-Setup-*.exe" | Select-Object -First 1).FullName
if (-not $setup) { Write-Host "找不到问渠CAM 安装包"; exit 1 }
$log = Join-Path $env:TEMP "wq-cam-setup.log"
Write-Host "静默安装 $setup 到 $Dir"
$p = Start-Process -FilePath $setup -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/DIR=$Dir", "/LOG=$log" -Wait -PassThru
if ($p.ExitCode -ne 0) { Get-Content $log -Tail 30; Write-Host "安装失败：$($p.ExitCode)"; exit 1 }
foreach ($f in @("Mod\FreeCADAIParts\InitGui.py", "Mod\FreeCADAIParts\lib\edition.json", "NOTICES.txt", "wenquest-cam.ico",
                 "docs\WenQuest-CAM-Verification-Manual.pdf", "docs\问渠CAM验证手册.pdf",
                 "docs\WenQuest-CAM-User-Guide.pdf", "docs\问渠CAM用户手册.pdf",
                 "examples\01-shaft-turning\shaft.step", "examples\01-shaft-turning\O1001_fanuc.nc",
                 "examples\02-block-milling\block.step", "examples\02-block-milling\sample-card.en.pdf")) {
  if (-not (Test-Path (Join-Path $Dir $f))) { Write-Host "安装目录里没有 $f"; exit 1 }
}
Push-Location $env:TEMP
& "$Dir\bin\python.exe" "$PSScriptRoot\acceptance_cam.py" $Dir $Repo 2>&1 | ForEach-Object { "$_" }
$rc = $LASTEXITCODE
Pop-Location
if ($rc -ne 0) { Write-Host "验收不通过"; exit 1 }
Write-Host "静默卸载"
$u = Start-Process -FilePath "$Dir\unins000.exe" -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART" -Wait -PassThru
Start-Sleep -Seconds 5
if ($u.ExitCode -ne 0 -or (Test-Path "$Dir\bin\FreeCAD.exe")) { Write-Host "卸载没有清干净"; exit 1 }
Write-Host "问渠CAM：静默安装、验收、卸载都通过"
exit 0
