; 问渠有限元 WenQuest FEA 安装包（ADR-0096 第 5 步）。由 build.ps1 -Edition fea 调用：
;   ISCC /DAppVersion=0.0.1 /DSourceDir=<FreeCAD 与问渠有限元的目录> /DOutputDir=<输出目录> /DDocsDir=<验证手册目录> wenquest-fea.iss
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
; 与 FreeCAD AI Parts 不同的 AppId：两个可以装在同一台电脑上
AppId={{3B8E5D21-9C47-4F6A-B0D3-7E2A19C4F58D}
AppName=WenQuest FEA
AppVerName=WenQuest FEA {#AppVersion}
AppVersion={#AppVersion}
AppPublisher=Guoqing Zhang
DefaultDirName={autopf}\WenQuest FEA
DefaultGroupName=WenQuest FEA
DisableProgramGroupPage=yes
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog commandline
LicenseFile=NOTICES.txt
OutputDir={#OutputDir}
OutputBaseFilename=WenQuest-FEA-Setup-{#AppVersion}
SetupIconFile=wenquest-fea.ico
Compression=lzma2/max
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\wenquest-fea.ico
UninstallDisplayName=WenQuest FEA
WizardStyle=modern

[Languages]
#if FileExists(CompilerPath + "Languages\ChineseSimplified.isl")
Name: "zh"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
#elif FileExists(CompilerPath + "Languages\Unofficial\ChineseSimplified.isl")
Name: "zh"; MessagesFile: "compiler:Languages\Unofficial\ChineseSimplified.isl"
#endif
Name: "en"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
zh.AppTitle=问渠有限元
en.AppTitle=WenQuest FEA
zh.Notices=许可证与源码获取说明
en.Notices=Licenses and source code
zh.Manual=验证手册
en.Manual=Verification manual

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "NOTICES.txt"; DestDir: "{app}"; DestName: "NOTICES.txt"; Flags: ignoreversion
Source: "wenquest-fea.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#DocsDir}\问渠有限元验证手册.pdf"; DestDir: "{app}\docs"; Flags: ignoreversion
Source: "{#DocsDir}\WenQuest-FEA-Verification-Manual.pdf"; DestDir: "{app}\docs"; Flags: ignoreversion

[Icons]
Name: "{group}\{cm:AppTitle}"; Filename: "{app}\bin\FreeCAD.exe"; WorkingDir: "{app}\bin"; IconFilename: "{app}\wenquest-fea.ico"
Name: "{group}\{cm:Manual} (中文)"; Filename: "{app}\docs\问渠有限元验证手册.pdf"
Name: "{group}\{cm:Manual} (English)"; Filename: "{app}\docs\WenQuest-FEA-Verification-Manual.pdf"
Name: "{group}\{cm:Notices}"; Filename: "{app}\NOTICES.txt"
Name: "{group}\{cm:UninstallProgram,WenQuest FEA}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{cm:AppTitle}"; Filename: "{app}\bin\FreeCAD.exe"; WorkingDir: "{app}\bin"; IconFilename: "{app}\wenquest-fea.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\bin\FreeCAD.exe"; Description: "{cm:LaunchProgram,{cm:AppTitle}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\Mod\FreeCADAIParts\lib\__pycache__"
