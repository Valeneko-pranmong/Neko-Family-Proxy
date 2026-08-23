; ============================================================================
;  NEKO FAMILY PROXY - Closed Beta single-EXE installer (production-like)
; ----------------------------------------------------------------------------
;  Design contract (Closed Beta installer gate, 2026-08-23):
;    * Deploys the APPROVED NekoLauncher.exe + complete external ProxyCore
;      bundle into the existing runtime topology:
;          %LOCALAPPDATA%\NEKO FAMILY\{NekoLauncher.exe, ProxyCore\...}
;    * PrivilegesRequired=lowest: per-user install, cannot touch HKLM or
;      machine state. Elevation is requested ONLY if the netfilter2 driver
;      needs registration (single UAC prompt, existing supported path).
;    * Launcher -> external ProxyCore resolution is preserved. ProxyCore is
;      NEVER embedded in NekoLauncher.exe and no _MEI resolution is added.
;    * Post-install verification of the external Core against
;      core-manifest.json (authority source_commit pinned below) runs before
;      the finish step; a clear failure message is shown and the optional
;      launch action is suppressed when verification fails.
;    * netfilter2 policy: already-valid/running -> verify only, no UAC.
;      Missing/stopped -> copy bin\nfdriver.sys to
;      System32\drivers\netfilter2.sys and register through the proven
;      Redirector.bin nf_registerDriver entry point (exactly what Core's own
;      NFController does). An INCOMPATIBLE RUNNING driver is never silently
;      overwritten. The driver is treated as a SHARED MACHINE PREREQUISITE
;      and is intentionally PRESERVED on uninstall.
; ============================================================================

#define MyAppName "NEKO FAMILY PROXY"
#define MyAppVersion "1.0.0.1"
#define MyAppDisplayVersion "1.0.0-beta.1"

; Staging root lives OUTSIDE the repository (never committed). Override both
; from the build orchestrator with:  ISCC /DPayloadDir=... /DBuildOutDir=...
#ifndef PayloadDir
  #define PayloadDir "D:\Build\NekoBetaInstaller\payload"
#endif
#ifndef BuildOutDir
  #define BuildOutDir "D:\Build\NekoBetaInstaller\out"
#endif

[Setup]
AppId={{D4A7C182-6B3E-4F19-9C05-2E8AF7B31D64}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppDisplayVersion}
AppPublisher=NEKO FAMILY

; Existing production-like runtime topology (per-user Local AppData).
DefaultDirName={localappdata}\NEKO FAMILY
DisableDirPage=yes
UsePreviousAppDir=no

PrivilegesRequired=lowest

ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

Compression=lzma2
SolidCompression=yes

OutputDir={#BuildOutDir}
OutputBaseFilename=NekoFamilyProxy-Beta-Setup

SetupIconFile=..\icon_app.ico

Uninstallable=yes
UninstallDisplayName={#MyAppName}
UninstallDisplayIcon={app}\NekoLauncher.exe

DisableProgramGroupPage=yes
WizardStyle=modern
CloseApplications=no
RestartIfNeededByRun=no

[Files]
; Approved Launcher EXE (fail-closed hash-gated by build_beta_installer.py).
Source: "{#PayloadDir}\NekoLauncher.exe"; \
    DestDir: "{app}"; \
    Flags: ignoreversion

; Complete approved external Core bundle -> {app}\ProxyCore (external
; runtime; NOT embedded into the Launcher).
Source: "{#PayloadDir}\CoreBundle\*"; \
    DestDir: "{app}\ProxyCore"; \
    Flags: ignoreversion recursesubdirs createallsubdirs

; Installer helper scripts (tracked, inspectable, removed by uninstall).
Source: "scripts\verify-core-install.ps1"; \
    DestDir: "{app}\tools\installer"; \
    Flags: ignoreversion
Source: "scripts\ensure-netfilter2.ps1"; \
    DestDir: "{app}\tools\installer"; \
    Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\NekoLauncher.exe"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\NekoLauncher.exe"

[Run]
Filename: "{app}\NekoLauncher.exe"; \
    Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; \
    Flags: nowait postinstall skipifsilent; \
    Check: LaunchAllowed

[Code]
const
  HideCmd = 0;

var
  g_CoreVerifyOK: Boolean;
  g_DriverOK: Boolean;
  g_Detail: String;

function B2S(B: Boolean): String;
begin
  if B then Result := '1' else Result := '0';
end;

procedure AddDetail(const S: String);
begin
  if g_Detail <> '' then
    g_Detail := g_Detail + #13#10;
  g_Detail := g_Detail + S;
end;

function PSExePath(): String;
begin
  Result := ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe');
end;

function RunPSFile(const PSFile, ExtraArgs: String; var ExitCode: Integer): Boolean;
begin
  ExitCode := 0;
  Result := Exec(PSExePath(),
    '-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File "' +
    PSFile + '"' + ExtraArgs,
    ExtractFileDir(PSFile), HideCmd, ewWaitUntilTerminated, ExitCode);
  if not Result then
    ExitCode := -1;
end;

function ReadSmallFile(const Path: String): String;
var
  S: AnsiString;
begin
  Result := '';
  if LoadStringFromFile(Path, S) then
    Result := String(S);
end;

function LaunchAllowed(): Boolean;
begin
  Result := g_CoreVerifyOK;
end;

function InitializeSetup(): Boolean;
begin
  g_CoreVerifyOK := False;
  g_DriverOK := False;
  g_Detail := '';
  Result := True;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  AppDir, CoreDir, BinDir, ToolsDir: String;
  VerifyScript, DriverScript, ResFile: String;
  RC: Integer;
  Ok: Boolean;
  Msg: String;
begin
  if CurStep <> ssPostInstall then
    Exit;

  AppDir := ExpandConstant('{app}');
  CoreDir := AppDir + '\ProxyCore';
  BinDir := CoreDir + '\bin';
  ToolsDir := AppDir + '\tools\installer';
  VerifyScript := ToolsDir + '\verify-core-install.ps1';
  DriverScript := ToolsDir + '\ensure-netfilter2.ps1';

  { ---- 1. External Core manifest verification (unelevated) ---- }
  if not FileExists(VerifyScript) then begin
    AddDetail('internal error: verify-core-install.ps1 missing');
  end else begin
    Ok := RunPSFile(VerifyScript, ' -CoreDir "' + CoreDir + '"', RC);
    g_CoreVerifyOK := Ok and (RC = 0);
    Log('core manifest verification exit code: ' + IntToStr(RC));
    if not g_CoreVerifyOK then begin
      AddDetail('Core verification FAILED (exit ' + IntToStr(RC) + ')');
      SuppressibleMsgBox(
        'Setup could not verify the installed NEKO FAMILY PROXY Core runtime ' +
        'against core-manifest.json.'#13#10#13#10 +
        'The installation must not be used. Please run the uninstaller and ' +
        'contact the operator.'#13#10#13#10 +
        'Verification exit code: ' + IntToStr(RC),
        mbCriticalError, MB_OK, IDOK);
    end;
  end;

  { ---- 2. netfilter2 driver readiness (elevation only when required) ---- }
  if not FileExists(DriverScript) then begin
    AddDetail('internal error: ensure-netfilter2.ps1 missing');
  end else begin
    Ok := RunPSFile(DriverScript, ' -CoreBinDir "' + BinDir + '" -CheckOnly', RC);
    Log('netfilter2 check exit code: ' + IntToStr(RC));
    case RC of
      0: g_DriverOK := True; { already valid and running; no elevation needed }
      10: begin
            ResFile := ToolsDir + '\nf-result.txt';
            DeleteFile(ResFile);
            Log('requesting elevation for netfilter2 registration');
            Ok := ShellExec('runas', PSExePath(),
              '-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File "' +
              DriverScript + '" -CoreBinDir "' + BinDir + '" -Apply -ResultFile "' +
              ResFile + '"',
              ExtractFileDir(DriverScript), HideCmd, ewWaitUntilTerminated, RC);
            Log('elevated apply: shell=' + B2S(Ok) + ' rc=' + IntToStr(RC));
            { Authoritative outcome = fresh unelevated re-check of real state. }
            Ok := RunPSFile(DriverScript, ' -CoreBinDir "' + BinDir + '" -CheckOnly', RC);
            g_DriverOK := Ok and (RC = 0);
          end;
      20: AddDetail('incompatible netfilter2 driver is running; overwrite refused');
    else
      AddDetail('netfilter2 precheck failed (exit ' + IntToStr(RC) + ')');
    end;

    if not g_DriverOK then begin
      Msg := ReadSmallFile(ToolsDir + '\nf-result.txt');
      if Msg <> '' then
        AddDetail(Msg);
      SuppressibleMsgBox(
        'Setup could not prepare the netfilter2 network driver.'#13#10#13#10 +
        'Installation files are in place, but game traffic proxying will not ' +
        'work until the driver is ready. Resolve the cause below and re-run ' +
        'setup if needed.'#13#10#13#10 +
        'Detail: ' + Msg,
        mbError, MB_OK, IDOK);
    end;
  end;

  Log('postinstall summary: core_verify=' + B2S(g_CoreVerifyOK) +
      ' netfilter2_ok=' + B2S(g_DriverOK));
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then begin
    SuppressibleMsgBox(
      'Note: the netfilter2 network driver is treated as a shared machine ' +
      'prerequisite and is intentionally PRESERVED by this uninstaller.'#13#10#13#10 +
      'Only NEKO FAMILY PROXY program files, shortcuts, and their uninstall ' +
      'entries are removed.',
      mbInformation, MB_OK, IDOK);
  end;
end;
