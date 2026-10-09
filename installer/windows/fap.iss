; FreeCAD AI Parts 单机安装版（ADR-0066 第 2 项）。由 build.ps1 调用：
;   ISCC /DAppVersion=0.0.1 /DSourceDir=<FreeCAD 与工作台的目录> /DOutputDir=<输出目录> fap.iss
; 静默安装：Setup.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART [/DIR=目录] [/CURRENTUSER]

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef SourceDir
  #error 需要 /DSourceDir
#endif
#ifndef OutputDir
  #define OutputDir "."
#endif

[Setup]
AppId={{6C1F3B7A-4E1D-4C9B-9F2A-FA0D2E18A766}
AppName=FreeCAD AI Parts
AppVersion={#AppVersion}
AppPublisher=Guoqing Zhang
AppPublisherURL=https://github.com/eddiezgq/freecad-ai-parts
DefaultDirName={autopf}\FreeCAD AI Parts
DefaultGroupName=FreeCAD AI Parts
DisableProgramGroupPage=yes
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog commandline
LicenseFile=NOTICES.txt
OutputDir={#OutputDir}
OutputBaseFilename=FreeCAD-AI-Parts-Setup-{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\bin\FreeCAD.exe
WizardStyle=modern

[Languages]
#if FileExists(CompilerPath + "Languages\ChineseSimplified.isl")
Name: "zh"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
#elif FileExists(CompilerPath + "Languages\Unofficial\ChineseSimplified.isl")
Name: "zh"; MessagesFile: "compiler:Languages\Unofficial\ChineseSimplified.isl"
#endif
Name: "en"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "NOTICES.txt"; DestDir: "{app}"; DestName: "许可证与源码获取说明.txt"; Flags: ignoreversion

[Icons]
Name: "{group}\FreeCAD AI Parts"; Filename: "{app}\bin\FreeCAD.exe"; WorkingDir: "{app}\bin"
Name: "{group}\许可证与源码获取说明"; Filename: "{app}\许可证与源码获取说明.txt"
Name: "{group}\{cm:UninstallProgram,FreeCAD AI Parts}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\FreeCAD AI Parts"; Filename: "{app}\bin\FreeCAD.exe"; WorkingDir: "{app}\bin"; Tasks: desktopicon

[Run]
Filename: "{app}\bin\FreeCAD.exe"; Description: "{cm:LaunchProgram,FreeCAD AI Parts}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\Mod\FreeCADAIParts\lib\__pycache__"
