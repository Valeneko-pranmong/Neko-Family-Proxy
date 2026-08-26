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

; PM decision D2 (closed-beta P1 batch, 2026-08-26): HARD BLOCK every
; non-x64 host. "x64" excludes ARM64 even when Windows emulates it, so the
; installer refuses to run anywhere except true x64 Windows.
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64

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

; .NET Desktop Runtime 6.x x64 bootstrapper (staged prerequisite).
; Pinned version + SHA-256 are enforced by build_beta_installer.py, which
; FAILS CLOSED before compiling when the approved EXE is absent from
; {#PayloadDir}\Prereqs. Copied to {tmp} (auto-cleaned when Setup exits);
; the post-install step runs it elevated+silent ONLY when detection says
; the runtime is missing.
Source: "{#PayloadDir}\Prereqs\windowsdesktop-runtime-*-win-x64.exe"; \
    DestDir: "{tmp}\Prereqs"; \
    Flags: ignoreversion

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
  g_DotnetOK: Boolean;
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
  { The optional launch is suppressed unless the Core is verified AND the
    .NET Desktop Runtime 6.x x64 prerequisite ended up present. }
  Result := g_CoreVerifyOK and g_DotnetOK;
end;

{ Machine-wide x64 .NET runtime installs live under the NATIVE Program Files
  dotnet tree. With ArchitecturesAllowed=x64 (D2), anything found there is
  the x64 runtime, so a shared Microsoft.WindowsDesktop.App folder with a
  6.x-or-newer version subdirectory is an honest detection of the required
  Desktop Runtime. }
function DesktopRuntimeSharedDir(): String;
begin
  Result := ExpandConstant('{pf}') + '\dotnet\shared\Microsoft.WindowsDesktop.App';
end;

function DesktopRuntime6X64Present(): Boolean;
var
  SharedFx, Entry, MajorText: String;
  DotPos, Major: Integer;
  FR: TFindRec;
begin
  Result := False;
  SharedFx := DesktopRuntimeSharedDir();
  Log('Desktop Runtime probe: ' + SharedFx);
  if not DirExists(SharedFx) then begin
    Log('Desktop Runtime probe: shared Microsoft.WindowsDesktop.App dir absent');
    Exit;
  end;
  if FindFirst(SharedFx + '\*', FR) then begin
    try
      repeat
        if (FR.Attributes and FILE_ATTRIBUTE_DIRECTORY) = FILE_ATTRIBUTE_DIRECTORY then begin
          Entry := FR.Name;
          if (Entry <> '.') and (Entry <> '..') then begin
            DotPos := Pos('.', Entry);
            if DotPos > 1 then begin
              MajorText := Copy(Entry, 1, DotPos - 1);
              Major := StrToIntDef(MajorText, 0);
              if Major >= 6 then begin
                Result := True;
                Log('Desktop Runtime probe: found version ' + Entry);
              end;
            end;
          end;
        end;
      until not FindNext(FR);
    finally
      FindClose(FR);
    end;
  end;
end;

function FindRuntimeBootstrapper(): String;
var
  PrereqDir: String;
  FR: TFindRec;
begin
  Result := '';
  PrereqDir := ExpandConstant('{tmp}\Prereqs');
  if FindFirst(PrereqDir + '\windowsdesktop-runtime-*-win-x64.exe', FR) then begin
    try
      repeat
        if (FR.Attributes and FILE_ATTRIBUTE_DIRECTORY) = 0 then begin
          Result := PrereqDir + '\' + FR.Name;
          Break;
        end;
      until not FindNext(FR);
    finally
      FindClose(FR);
    end;
  end;
end;

function InitializeSetup(): Boolean;
begin
  g_CoreVerifyOK := False;
  g_DriverOK := False;
  g_DotnetOK := False;
  g_Detail := '';
  Result := True;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  AppDir, CoreDir, BinDir, ToolsDir: String;
  VerifyScript, DriverScript, ResFile: String;
  Bootstrapper: String;
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

  { ---- 2. .NET Desktop Runtime 6 x64 readiness (elevation only when required) ---- }
  g_DotnetOK := DesktopRuntime6X64Present();
  if not g_DotnetOK then begin
    Bootstrapper := FindRuntimeBootstrapper();
    if Bootstrapper = '' then begin
      AddDetail('internal error: staged .NET Desktop Runtime bootstrapper missing');
      Log('no staged bootstrapper found in {tmp}\Prereqs');
    end else begin
      Log('requesting elevation for silent .NET Desktop Runtime install');
      Ok := ShellExec('runas', Bootstrapper,
        '/install /quiet /norestart',
        '', HideCmd, ewWaitUntilTerminated, RC);
      Log('elevated dotnet install: shell=' + B2S(Ok) + ' rc=' + IntToStr(RC));
      { Exit codes 0 and 3010 (reboot pending) are both acceptable here; the
        fresh unelevated re-detection below remains authoritative either way. }
    end;
    { Authoritative outcome = re-detect the REAL machine state after any
      elevated attempt (same fail-closed pattern as the netfilter2 step). }
    g_DotnetOK := DesktopRuntime6X64Present();
  end;
  if not g_DotnetOK then begin
    AddDetail('.NET Desktop Runtime 6.x x64 still absent after setup');
    SuppressibleMsgBox(
      'Setup could not prepare the Microsoft .NET Desktop Runtime 6.x (x64). '#13#10#13#10 +
      'ต้องติดตั้ง Microsoft .NET Desktop Runtime 6.x (x64) ก่อนจึงจะเริ่มใช้งานได้'#13#10#13#10 +
      'Installation files are in place, but NEKO FAMILY PROXY cannot start its ' +
      'runtime without it. Please install the runtime and run setup again.'#13#10#13#10 +
      'The launch shortcut is disabled until the runtime is present.',
      mbError, MB_OK, IDOK);
  end;

  { ---- 3. netfilter2 driver readiness (elevation only when required) ---- }
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
      ' dotnet_ok=' + B2S(g_DotnetOK) +
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
