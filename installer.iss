; FlowCue 安装包脚本 (Inno Setup 6)
; 用法: ISCC.exe installer.iss /DAppVersion=1.0.0
; 升级: 直接下载新版 FlowCue-Setup-x.y.z.exe 双击安装即可原地覆盖旧版（AppId 不变）。
; 用户设置（规则设置、模板预设、运镜、账号备注、API Key）保存在 %APPDATA%\Flow口播工具，
; 安装/升级/卸载均不会触碰该目录。

#ifndef AppVersion
  #define AppVersion "1.8.0"
#endif

[Setup]
AppId={{B7E4C1A2-5D3F-4E8A-9C61-FA10C0E3C001}
AppName=FlowCue
AppVersion={#AppVersion}
AppVerName=FlowCue {#AppVersion}
AppPublisher=wshgxsjvb03-beep
AppPublisherURL=https://github.com/wshgxsjvb03-beep/flow
DefaultDirName={localappdata}\Programs\FlowCue
DefaultGroupName=FlowCue
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=dist
OutputBaseFilename=FlowCue-Setup-{#AppVersion}
SetupIconFile=logo.ico
UninstallDisplayIcon={app}\FlowCue.exe
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
Source: "dist\FlowCue\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "extension\*"; DestDir: "{app}\extension"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: ".env.example"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\FlowCue"; Filename: "{app}\FlowCue.exe"
Name: "{group}\卸载 FlowCue"; Filename: "{uninstallexe}"
Name: "{autodesktop}\FlowCue"; Filename: "{app}\FlowCue.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\FlowCue.exe"; Description: "启动 FlowCue"; Flags: nowait postinstall
