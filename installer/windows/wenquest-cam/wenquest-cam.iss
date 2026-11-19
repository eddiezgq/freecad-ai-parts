; 问渠CAM WenQuest CAM 安装包（ADR-0104 产品化）。由 build.ps1 -Edition cam 调用：
;   ISCC /DAppVersion=0.0.1 /DSourceDir=<FreeCAD 与问渠CAM 的目录> /DOutputDir=<输出目录> /DDocsDir=<验证手册目录>
;        /DHelpDir=<用户手册目录> /DExamplesDir=<入门例子目录> wenquest-cam.iss
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
#ifndef HelpDir
  #error 需要 /DHelpDir
#endif
#ifndef ExamplesDir
  #error 需要 /DExamplesDir
#endif
#ifndef OutputDir
  #define OutputDir "."
#endif

[Setup]
; 与 FreeCAD AI Parts、问渠有限元、问渠多体动力学都不同的 AppId：四个可以装在同一台电脑上
AppId={{3E7B1C59-A402-4D86-9F31-6C8D2B5E0A77}
AppName=WenQuest CAM
AppVerName=WenQuest CAM {#AppVersion}
AppVersion={#AppVersion}
AppPublisher=Guoqing Zhang
DefaultDirName={autopf}\WenQuest CAM
DefaultGroupName=WenQuest CAM
DisableProgramGroupPage=yes
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog commandline
LicenseFile=NOTICES.txt
OutputDir={#OutputDir}
OutputBaseFilename=WenQuest-CAM-Setup-{#AppVersion}
SetupIconFile=wenquest-cam.ico
Compression=lzma2/max
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\wenquest-cam.ico
UninstallDisplayName=WenQuest CAM
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
en.AppTitle=WenQuest CAM
en.Notices=Licenses and source code
en.Manual=Verification manual
en.Guide=User guide
en.Examples=Getting-started examples
#ifdef HaveZh
zh.AppTitle=问渠CAM
zh.Notices=许可证与源码获取说明
zh.Manual=验证手册
zh.Guide=用户手册
zh.Examples=入门例子
#endif

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "NOTICES.txt"; DestDir: "{app}"; DestName: "NOTICES.txt"; Flags: ignoreversion
Source: "wenquest-cam.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#DocsDir}\问渠CAM验证手册.pdf"; DestDir: "{app}\docs"; Flags: ignoreversion
Source: "{#DocsDir}\WenQuest-CAM-Verification-Manual.pdf"; DestDir: "{app}\docs"; Flags: ignoreversion
Source: "{#HelpDir}\问渠CAM用户手册.pdf"; DestDir: "{app}\docs"; Flags: ignoreversion
Source: "{#HelpDir}\WenQuest-CAM-User-Guide.pdf"; DestDir: "{app}\docs"; Flags: ignoreversion
Source: "{#ExamplesDir}\*"; DestDir: "{app}\examples"; Excludes: "*.py,__pycache__"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{cm:AppTitle}"; Filename: "{app}\bin\FreeCAD.exe"; WorkingDir: "{app}\bin"; IconFilename: "{app}\wenquest-cam.ico"
Name: "{group}\{cm:Guide} (中文)"; Filename: "{app}\docs\问渠CAM用户手册.pdf"
Name: "{group}\{cm:Guide} (English)"; Filename: "{app}\docs\WenQuest-CAM-User-Guide.pdf"
Name: "{group}\{cm:Examples}"; Filename: "{app}\examples"
Name: "{group}\{cm:Manual} (中文)"; Filename: "{app}\docs\问渠CAM验证手册.pdf"
Name: "{group}\{cm:Manual} (English)"; Filename: "{app}\docs\WenQuest-CAM-Verification-Manual.pdf"
Name: "{group}\{cm:Notices}"; Filename: "{app}\NOTICES.txt"
Name: "{group}\{cm:UninstallProgram,WenQuest CAM}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{cm:AppTitle}"; Filename: "{app}\bin\FreeCAD.exe"; WorkingDir: "{app}\bin"; IconFilename: "{app}\wenquest-cam.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\bin\FreeCAD.exe"; Description: "{cm:LaunchProgram,{cm:AppTitle}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\Mod\FreeCADAIParts\lib\__pycache__"
