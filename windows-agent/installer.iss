#define MyAppName "HomeGuard Agent"
#define MyAppVersion "0.4.0"
#define MyAppExeName "HomeGuardAgent.exe"

[Setup]
AppId={{829EBA38-5988-4F4A-AE28-537D84D3B676}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
DefaultDirName={autopf}\HomeGuard Agent
DefaultGroupName=HomeGuard Agent
OutputDir=..\dist
OutputBaseFilename=HomeGuard-Setup
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
UninstallDisplayIcon={app}\{#MyAppExeName}
CloseApplications=yes
RestartApplications=no

[Files]
Source: "dist\HomeGuardAgent\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\HomeGuard Agent"; Filename: "{app}\{#MyAppExeName}"
Name: "{userstartup}\HomeGuard Agent"; Filename: "{app}\{#MyAppExeName}"; Tasks: startup

[Tasks]
Name: "startup"; Description: "Start HomeGuard Agent with Windows"; Flags: unchecked

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch HomeGuard"; Flags: postinstall nowait skipifsilent
