# 在 Windows + FreeCAD 1.1（Qt 6）里真的打开 AI 设计面板（ADR-0100 42.4 之三）：中、英文界面 × 普通 / 比屏幕宽的主窗口。
# 每次限时；卡住就截屏、停掉、判不通过。CI（windows.yml 的 windows-gui）与问渠 CAD 的 tests-wqcad.ps1 都用 tests/gui/gui_panel_check.py。
# -Wrapper / -WrapperArgs：经环境激活程序启动（例如 micromamba run -n fc11），否则 PySide6 等找不到（CI 第二次跑时截屏发现）
param([Parameter(Mandatory = $true)][string]$FreeCAD, [string]$Out = "gui-out", [int]$Seconds = 150,
      [string]$Wrapper = "", [string]$WrapperArgs = "")

$ErrorActionPreference = "Stop"
New-Item -ItemType Directory -Force $Out | Out-Null
$script = (Resolve-Path (Join-Path $PSScriptRoot "gui_panel_check.py")).Path
Add-Type -AssemblyName System.Windows.Forms, System.Drawing
function Shot($path) {
    $b = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
    $bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.CopyFromScreen($b.Location, [System.Drawing.Point]::Empty, $b.Size)
    $bmp.Save($path, [System.Drawing.Imaging.ImageFormat]::Png)
    $g.Dispose(); $bmp.Dispose()
}
$failed = 0
foreach ($lang in @("en", "zh")) {
    foreach ($wide in @("", "1")) {
        $name = "$lang" + $(if ($wide) { "-wide" } else { "" })
        $env:FAP_LANG = $lang
        $env:WQCAD_WIDE = $wide
        $env:WQCAD_OUT = Join-Path (Resolve-Path $Out) "$name.json"
        Remove-Item $env:WQCAD_OUT -ErrorAction SilentlyContinue
        if ($Wrapper) { $p = Start-Process -FilePath $Wrapper -ArgumentList "$WrapperArgs `"$FreeCAD`" `"$script`"" -PassThru }
        else { $p = Start-Process -FilePath $FreeCAD -ArgumentList "`"$script`"" -PassThru }
        if (-not $p.WaitForExit($Seconds * 1000)) {
            Shot (Join-Path $Out "$name-hang.png")
            & taskkill /T /F /PID $p.Id | Out-Null
            Write-Host "$name：$Seconds 秒没有结果，界面卡住 —— NOT OK（截屏 $name-hang.png）"
            $failed++
            continue
        }
        if (-not (Test-Path $env:WQCAD_OUT)) { Write-Host "$name：没有结果 —— NOT OK"; $failed++; continue }
        $j = Get-Content $env:WQCAD_OUT -Raw -Encoding UTF8 | ConvertFrom-Json
        $ok = if ($j.ok) { "OK" } else { $failed++; "NOT OK" }
        Write-Host "$name：主窗口 $($j.main_window) panel $($j.panel) inside_screen $($j.inside_screen) $ok $($j.error)"
    }
}
if ($failed) { Write-Host "界面测试：$failed 项不通过"; exit 1 }
Write-Host "界面测试：4 项全部通过"
