# 问渠数字工厂 · 企业安装版（Windows 本机，ADR-0063）
# Windows 上经 WSL2 运行同一个 install.sh：先装 Docker Desktop（开启 WSL2 集成）和一个 Ubuntu 发行版。
#   .\factory\enterprise\install.ps1 -Domain factory.local -Admin admin            # 本机 / 内网：自签证书
# 其他选项与 install.sh 相同，原样传过去，例如 -Extra "--demo --region cn"
param(
  [Parameter(Mandatory = $true)][string]$Domain,
  [string]$Admin = "admin",
  [string]$Extra = ""
)
$ErrorActionPreference = "Stop"
if (-not (Get-Command wsl -ErrorAction SilentlyContinue)) { throw "没有 WSL：管理员 PowerShell 里运行 wsl --install，重启后再试" }
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { throw "没有 Docker Desktop：安装后在 Settings → Resources → WSL integration 打开 Ubuntu" }
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$wslPath = (wsl wslpath -a ($here -replace '\\', '/')).Trim()
Write-Host "在 WSL 里安装到 ~/fap（数据在 Docker 卷里）..."
wsl bash -lc "mkdir -p ~/fap && cp -r '$wslPath'/. ~/fap/ && cd ~/fap && ./install.sh --domain $Domain --tls-internal --admin $Admin $Extra"
Write-Host "装好后在本机 hosts 文件（C:\Windows\System32\drivers\etc\hosts）加：127.0.0.1 $Domain erp.$Domain"
