; 问渠多体动力学 WenQuest MBD 安装包（ADR-0102 第 4 步）。由 build.ps1 -Edition mbd 调用：
;   ISCC /DAppVersion=0.0.1 /DSourceDir=<FreeCAD 与问渠多体动力学的目录> /DOutputDir=<输出目录> /DDocsDir=<验证手册目录> wenquest-mbd.iss
; 用户手册与入门例子在第 5 步加进来。
; 静默安装：Setup.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART [/DIR=目录] [/CURRENTUSER]

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef SourceDir
  #error 需要 /DSourceDir
#endif
#ifndef DocsDir
  #error 需要 /DDocsDir
#endif
#ifndef OutputDir
  #define OutputDir "."
#endif

[Setup]
; 与 FreeCAD AI Parts、问渠有限元都不同的 AppId：三个可以装在同一台电脑上
AppId={{8C2F6A47-1D93-4E58-A6B2-5F0E7D3C9B14}
AppName=WenQuest MBD
AppVerName=WenQuest MBD {#AppVersion}
AppVersion={#AppVersion}
AppPublisher=Guoqing Zhang
DefaultDirName={autopf}\WenQuest MBD
DefaultGroupName=WenQuest MBD
DisableProgramGroupPage=yes
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog commandline
LicenseFile=NOTICES.txt
OutputDir={#OutputDir}
OutputBaseFilename=WenQuest-MBD-Setup-{#AppVersion}
SetupIconFile=wenquest-mbd.ico
Compression=lzma2/max
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\wenquest-mbd.ico
UninstallDisplayName=WenQuest MBD
WizardStyle=modern

[Languages]
#if FileExists(CompilerPath + "Languages\ChineseSimplified.isl")
Name: "zh"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
  #define HaveZh
#elif FileExists(CompilerPath + "Languages\Unofficial\ChineseSimplified.isl")
Name: "zh"; MessagesFile: "compiler:Languages\Unofficial\ChineseSimplified.isl"
  #define HaveZh
#endif
Name: "en"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
; 打包机没有中文语言文件时只有英文界面（GitHub 的 Windows 机器就没有）
en.AppTitle=WenQuest MBD
en.Notices=Licenses and source code
en.Manual=Verification manual
#ifdef HaveZh
zh.AppTitle=问渠多体动力学
zh.Notices=许可证与源码获取说明
zh.Manual=验证手册
#endif

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "NOTICES.txt"; DestDir: "{app}"; DestName: "NOTICES.txt"; Flags: ignoreversion
Source: "wenquest-mbd.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#DocsDir}\问渠多体动力学验证手册.pdf"; DestDir: "{app}\docs"; Flags: ignoreversion
Source: "{#DocsDir}\WenQuest-MBD-Verification-Manual.pdf"; DestDir: "{app}\docs"; Flags: ignoreversion

[Icons]
Name: "{group}\{cm:AppTitle}"; Filename: "{app}\bin\FreeCAD.exe"; WorkingDir: "{app}\bin"; IconFilename: "{app}\wenquest-mbd.ico"
Name: "{group}\{cm:Manual} (中文)"; Filename: "{app}\docs\问渠多体动力学验证手册.pdf"
Name: "{group}\{cm:Manual} (English)"; Filename: "{app}\docs\WenQuest-MBD-Verification-Manual.pdf"
Name: "{group}\{cm:Notices}"; Filename: "{app}\NOTICES.txt"
Name: "{group}\{cm:UninstallProgram,WenQuest MBD}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{cm:AppTitle}"; Filename: "{app}\bin\FreeCAD.exe"; WorkingDir: "{app}\bin"; IconFilename: "{app}\wenquest-mbd.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\bin\FreeCAD.exe"; Description: "{cm:LaunchProgram,{cm:AppTitle}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\Mod\FreeCADAIParts\lib\__pycache__"
