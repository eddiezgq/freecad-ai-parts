# 生成 Windows 单机安装包（ADR-0066 第 2 项）。在 Windows 上、仓库根目录运行：
#   powershell -ExecutionPolicy Bypass -File installer\windows\build.ps1 [-Work 目录] [-Out 目录]
# 步骤：取 FreeCAD 1.0.2 便携版（核对 SHA-256）→ 依赖装进它自带的 Python → 工作台自包含装进它的 Mod
#      → 冒烟检查（从包导入、找到 CalculiX）→ Inno Setup 打包。需要 7z 与 Inno Setup 6（GitHub 的 Windows 机器都有）。
param(
  [string]$Work = "$env:RUNNER_TEMP\fap-win",
  [string]$Out = "dist"
)
# 外部程序（pip、7z、ISCC）往 stderr 写进度；Windows PowerShell 5.1 在输出被重定向时会把它当成错误。
# 所以这里不用 Stop，每一步按退出码或结果自己判断；PowerShell 自己的命令加 -ErrorAction Stop。
$ErrorActionPreference = "Continue"
$ProgressPreference = "SilentlyContinue"
$Repo = (Resolve-Path "$PSScriptRoot\..\..").Path
$Version = "1.0.2"
$AssetName = "FreeCAD_$Version-conda-Windows-x86_64-py311.7z"
if (-not $Work -or $Work -eq "\fap-win") { $Work = Join-Path $env:TEMP "fap-win" }
New-Item -ItemType Directory -Force -Path $Work, $Out -ErrorAction Stop | Out-Null

# 1. FreeCAD 便携版
$archive = Join-Path $Work $AssetName
$headers = @{ "User-Agent" = "fap-installer" }
if ($env:GITHUB_TOKEN) { $headers["Authorization"] = "Bearer $env:GITHUB_TOKEN" }
$release = Invoke-RestMethod -ErrorAction Stop -Headers $headers "https://api.github.com/repos/FreeCAD/FreeCAD/releases/tags/$Version"
$asset = $release.assets | Where-Object { $_.name -eq $AssetName }
if (-not $asset) { throw "FreeCAD $Version 的发布里没有 $AssetName" }
$expected = $null
if ($asset.digest -and $asset.digest.StartsWith("sha256:")) { $expected = $asset.digest.Substring(7) }
else {
  $shaAsset = $release.assets | Where-Object { $_.name -like "$AssetName*SHA256*" } | Select-Object -First 1
  if (-not $shaAsset) { throw "找不到 $AssetName 的 SHA-256" }
  $expected = ((Invoke-WebRequest -ErrorAction Stop -UseBasicParsing $shaAsset.browser_download_url).Content -split "\s+")[0]
}
if (-not (Test-Path $archive) -or (Get-FileHash $archive -Algorithm SHA256).Hash -ne $expected.ToUpper()) {
  Write-Host "下载 $AssetName ..."
  Invoke-WebRequest -ErrorAction Stop -UseBasicParsing $asset.browser_download_url -OutFile $archive
}
$actual = (Get-FileHash $archive -Algorithm SHA256).Hash
if ($actual -ne $expected.ToUpper()) { throw "SHA-256 不符：期望 $expected，实际 $actual" }
Write-Host "FreeCAD $Version 核对通过：$actual"

$unpack = Join-Path $Work "unpack"
if (Test-Path $unpack) { Remove-Item -Recurse -Force -ErrorAction Stop $unpack }
& 7z x $archive "-o$unpack" -y | Out-Null
if ($LASTEXITCODE -ne 0) { throw "解压失败" }
$app = Get-ChildItem $unpack -Directory | Where-Object { Test-Path (Join-Path $_.FullName "bin\FreeCAD.exe") } | Select-Object -First 1
if (-not $app) { throw "解压后找不到 bin\FreeCAD.exe" }
$app = $app.FullName
$py = Join-Path $app "bin\python.exe"

# 2. 依赖装进 FreeCAD 自带的 Python
$reqs = Join-Path $Work "requirements.txt"
& $py "$Repo\installer\windows\deps.py" | Set-Content -Encoding ascii $reqs
& $py -m pip install --no-warn-script-location --disable-pip-version-check --progress-bar off -r $reqs 2>&1 | Write-Host
if ($LASTEXITCODE -ne 0) { throw "依赖安装失败" }

# 3. 工作台自包含装进 FreeCAD 的 Mod
Push-Location $Repo
try {
  & $py -m freecad_addon.install --standalone --mod-dir (Join-Path $app "Mod")
  if ($LASTEXITCODE -ne 0) { throw "工作台安装失败" }
} finally { Pop-Location }

# 4. 冒烟检查：在别的目录，从包里导入，找到 CalculiX，选型校验跑一道 golden 题
$lib = Join-Path $app "Mod\FreeCADAIParts\lib"
$probe = @"
import sys; sys.path.insert(0, sys.argv[1])
import engine.rules, freecad_addon.gui
from analysis.common.solvers import find_ccx
from analysis import modules
assert engine.rules.__file__.startswith(sys.argv[1]), engine.rules.__file__
ccx = find_ccx(); assert ccx, 'no ccx'
mods = {m['id']: m for m in modules()}
print('ccx', ccx)
print('modules', {k: m['available'] for k, m in mods.items()})
assert mods['fea']['available'], mods['fea']['missing']
"@
$probeFile = Join-Path $Work "probe.py"
[IO.File]::WriteAllText($probeFile, $probe, (New-Object Text.UTF8Encoding $false))
Push-Location $Work
try {
  & $py $probeFile $lib
  if ($LASTEXITCODE -ne 0) { throw "冒烟检查失败" }
} finally { Pop-Location }

# 5. 打包
$iscc = @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe") |
  Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw "找不到 Inno Setup 6（ISCC.exe）" }
$appVersion = (& $py -c "import tomllib;print(tomllib.load(open(r'$Repo\pyproject.toml','rb'))['project']['version'])").Trim()
$outAbs = (Resolve-Path $Out).Path
& $iscc "/DAppVersion=$appVersion" "/DSourceDir=$app" "/DOutputDir=$outAbs" "$PSScriptRoot\fap.iss"
if ($LASTEXITCODE -ne 0) { throw "Inno Setup 打包失败" }
Get-ChildItem $outAbs -Filter "FreeCAD-AI-Parts-Setup-*.exe" | ForEach-Object { Write-Host ("安装包：{0}（{1:N0} MB）" -f $_.FullName, ($_.Length / 1MB)) }
