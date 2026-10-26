; NEKO FAMILY PROXY - launcher login-fix patch installer.
;
; Replaces only {app}\NekoLauncher.exe on an existing 5.2.0 install. Core,
; state, trust, baseline, and the release envelope are not touched. This is a
; test-only patch: the launcher hash will no longer match the signed release
; envelope, so the update subsystem reports a mismatch until a full installer
; is rebuilt and re-signed.

#define MyPatchName "NEKO FAMILY PROXY Launcher Patch"
#define MyAppVersion "5.2.0"

#ifndef PayloadDir
  #define PayloadDir "..\..\launcher\dist"
#endif

#ifndef ExpectedPatchSha256
  #define ExpectedPatchSha256 "61242d24388234ea0b2b5197d5e2e663a4e030f0768678b8252efe3fe6079fb1"
#endif

[Setup]
AppId={{7E3C2A5F-9B41-4F8A-9D2E-6C1B7A4E8F30}
AppName={#MyPatchName}
AppVersion={#MyAppVersion}
AppVerName={#MyPatchName} {#MyAppVersion}
AppPublisher=NEKO FAMILY
DefaultDirName={localappdata}\NEKO FAMILY
DefaultGroupName=NEKO FAMILY PROXY
DisableDirPage=yes
DisableProgramGroupPage=yes
UsePreviousAppDir=no
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
OutputDir=..\..\launcher\dist
OutputBaseFilename=NekoLauncher-Patch-5.2.0-login-fix
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
Uninstallable=no
CloseApplications=no
RestartApplications=no
SetupLogging=yes
SetupIconFile=..\..\Asset\icon_app.ico
VersionInfoVersion=5.2.0.0
VersionInfoCompany=NEKO FAMILY
VersionInfoDescription=NEKO FAMILY PROXY launcher login-fix patch
VersionInfoProductName={#MyPatchName}
VersionInfoProductVersion={#MyAppVersion}

[Files]
Source: "{#PayloadDir}\NekoLauncher.exe"; DestDir: "{app}"; DestName: "NekoLauncher.exe"; Flags: ignoreversion

[Run]
Filename: "{app}\NekoLauncher.exe"; Description: "Launch NEKO FAMILY PROXY"; Flags: nowait postinstall skipifsilent

[Code]
const
  UninstallKey = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{D4A7C182-6B3E-4F19-9C05-2E8AF7B31D64}_is1';
  BackupName = 'NekoLauncher.exe.pre-login-fix.bak';
  ExpectedPatchSha256 = '{#ExpectedPatchSha256}';

var
  ForcePatch: Boolean;

function InitializeSetup(): Boolean;
var
  InstalledVersion: String;
  ForceValue: String;
begin
  Result := True;
  ForceValue := ExpandConstant('{param:FORCE|0}');
  ForcePatch := (ForceValue = '1') or (CompareText(ForceValue, 'true') = 0);

  if not ForcePatch then
  begin
    if not RegQueryStringValue(HKCU, UninstallKey, 'DisplayVersion', InstalledVersion) then
    begin
      MsgBox('NEKO FAMILY PROXY 5.2.0 is not registered for this user.' + #13#10 + #13#10 +
             'Install 5.2.0 first, or use /FORCE=1 only for a portable test.',
             mbCriticalError, MB_OK);
      Result := False;
      Exit;
    end;

    if InstalledVersion <> '5.2.0' then
    begin
      MsgBox('This patch is for 5.2.0 only. Found version: ' + InstalledVersion,
             mbCriticalError, MB_OK);
      Result := False;
      Exit;
    end;
  end;

  if not ForcePatch then
    SuppressibleMsgBox(
      'This patch replaces only NekoLauncher.exe for the login test.' + #13#10 + #13#10 +
      'Core, state, trust, and the release envelope are not changed. The signed ' +
      'update identity will report a mismatch until a full installer is rebuilt.',
      mbInformation, MB_OK, IDOK);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Target, Backup, StateDir, StateJson, StateBin: String;
  ResultCode: Integer;
begin
  Result := '';
  NeedsRestart := False;

  Target := ExpandConstant('{app}\NekoLauncher.exe');
  Backup := ExpandConstant('{app}\' + BackupName);
  StateDir := ExpandConstant('{app}\state\');
  StateJson := StateDir + 'installation-credential.json';
  StateBin := StateDir + 'installation-credential.bin';

  if not FileExists(Target) then
  begin
    Result := 'NekoLauncher.exe was not found in ' + ExpandConstant('{app}') + '.' + #13#10 +
              'Install NEKO FAMILY PROXY 5.2.0 first.';
    Exit;
  end;

  if not ForcePatch and (not FileExists(StateJson) or not FileExists(StateBin)) then
  begin
    Result := 'The installer credential is missing or incomplete.' + #13#10 + #13#10 +
              'Reinstall NEKO FAMILY PROXY 5.2.0 first so the installer can ' +
              'provision state, then run this patch.';
    Exit;
  end;

  Exec(ExpandConstant('{cmd}'), '/c taskkill /F /IM NekoLauncher.exe /T >nul 2>&1',
       '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Exec(ExpandConstant('{cmd}'), '/c taskkill /F /IM NekoUpdater.exe /T >nul 2>&1',
       '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Exec(ExpandConstant('{cmd}'), '/c taskkill /F /IM NekoProxyCore.exe /T >nul 2>&1',
       '', SW_HIDE, ewWaitUntilTerminated, ResultCode);

  if not FileExists(Backup) then
  begin
    if not CopyFile(Target, Backup, False) then
    begin
      Result := 'Could not back up the current launcher to:' + #13#10 + Backup;
      Exit;
    end;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Target: String;
begin
  if CurStep = ssPostInstall then
  begin
    Target := ExpandConstant('{app}\NekoLauncher.exe');
    if not FileExists(Target) then
    begin
      MsgBox('The patched launcher was not installed.', mbCriticalError, MB_OK);
      Exit;
    end;

    if CompareText(GetSHA256OfFile(Target), ExpectedPatchSha256) <> 0 then
      MsgBox('The installed launcher hash does not match the approved patch.' + #13#10 + #13#10 +
             'Restore NekoLauncher.exe.pre-login-fix.bak and contact the operator.',
             mbCriticalError, MB_OK);
  end;
end;
