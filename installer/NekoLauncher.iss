#define MyAppName "Neko Family Launcher"
#ifndef MyAppVersion
  #define MyAppVersion "5.0.0-alpha.1"
#endif
#define MyAppPublisher "Neko Family"
#define MyAppExeName "NekoLauncher.exe"

[Setup]
AppId={{EE798AAD-6A5E-49CE-81D0-63A7E09BAA03}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\Neko Family Launcher
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=output
OutputBaseFilename=NekoFamilyLauncher-{#MyAppVersion}-Setup
SetupIconFile=..\icon_app.ico
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
WizardStyle=modern
UninstallDisplayIcon={app}\{#MyAppExeName}

[Files]
Source: "..\launcher\dist\NekoLauncher.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\launcher\.env.example"; DestDir: "{localappdata}\NEKO FAMILY"; DestName: "launcher.env.example"; Flags: onlyifdoesntexist
Source: "..\RUNTIME_DISTRIBUTION.md"; DestDir: "{app}"; DestName: "RUNTIME.md"; Flags: ignoreversion

[Dirs]
Name: "{localappdata}\NEKO FAMILY\ProxyCore"

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent
