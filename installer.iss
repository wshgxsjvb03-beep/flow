; Flow 安装包脚本 (Inno Setup 6)
; 用法: ISCC.exe installer.iss /DAppVersion=1.0.0
; 升级: 直接下载新版 Flow-Setup-x.y.z.exe 双击安装即可原地覆盖旧版（AppId 不变）。
; 用户设置（规则设置、模板预设、运镜、账号备注、API Key）保存在 %APPDATA%\Flow口播工具，
; 安装/升级/卸载均不会触碰该目录。

#ifndef AppVersion
  #define AppVersion "1.8.0"
#endif

[Setup]
AppId={{B7E4C1A2-5D3F-4E8A-9C61-FA10C0E3C001}
AppName=Flow
AppVersion={#AppVersion}
AppVerName=Flow {#AppVersion}
AppPublisher=wshgxsjvb03-beep
AppPublisherURL=https://github.com/wshgxsjvb03-beep/flow
DefaultDirName={localappdata}\Programs\Flow
DefaultGroupName=Flow
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=dist
OutputBaseFilename=Flow-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=force
RestartApplications=no
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "chinesesimplified"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加图标:"

[Files]
Source: "dist\Flow\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "extension\*"; DestDir: "{app}\extension"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: ".env.example"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Flow"; Filename: "{app}\Flow.exe"
Name: "{group}\卸载 Flow"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Flow"; Filename: "{app}\Flow.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Flow.exe"; Description: "启动 Flow"; Flags: nowait postinstall
