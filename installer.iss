; Comprsly — Windows installer script (Inno Setup)
; Produces a real, interactive setup wizard: welcome screen, requirements,
; progress bar, and a finished screen with a "launch now" option, the same
; pattern any legitimate downloaded app uses. Installs to the user's own
; AppData folder, same as Grammarly's own desktop installer, so no
; admin/UAC prompt is needed.

#define MyAppName "Comprsly"
#define MyAppVersion "0.9.81"
#define MyAppPublisher "Comprsly"
; Renamed from TokenSaver.exe 2026-07-21. The exe file name is what Windows
; shows in Task Manager and the taskbar when there's no version resource,
; and renaming it also gives the shell a brand new icon-cache key, which is
; what made the old icon finally stop showing on the taskbar.
#define MyAppExeName "Comprsly.exe"
; Install FOLDER renamed "Token Saver" -> "Compresly" -> "Comprsly" (real ask
; 2026-07-25, second rebrand). Same mechanism as the first rename: [Code]
; below migrates the small user-data files AND the ~1GB model out of
; MyLegacyFolder and deletes it, and the app self-migrates the small files
; too (main.py _migrate_legacy_data_dir), so nothing is orphaned. Only the
; IMMEDIATELY PREVIOUS folder is tracked, not a full chain back to "Token
; Saver" -- see the matching comment in main.py for why that's an
; acceptable trade.
#define MyAppFolder "Comprsly"
#define MyLegacyFolder "Compresly"
; The AI model is NO LONGER bundled (2026-07-22, real ask: "decrease the
; download size"). It was 974 MB of the ~1 GB installer while the app itself
; is only ~40 MB. The installer now ships just the app; the model is a
; one-time in-app download (Settings -> Model -> Download AI model, or the
; first time "Make it Concise" is used). Spelling/grammar/punctuation work
; with no model at all, so the install is fully functional immediately; only
; the optional AI compression needs the ~1 GB download. See
; local_model.download_model.

[Setup]
AppId={{B4E1F1A0-6C6D-4A1E-9F2A-TOKEN0SAVER1}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\{#MyAppFolder}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
; Critical for the Token Saver -> Comprsly rename (real ask 2026-07-22):
; with a constant AppId, re-running setup normally defaults the install dir
; to the PREVIOUS location (the old Token Saver folder), which would silently
; defeat the rename. This forces DefaultDirName ({localappdata}\Comprsly)
; on every run. Safe because DisableDirPage=yes below means the location
; really is always {localappdata}\Comprsly — there is no user-chosen custom
; path for this to stomp.
UsePreviousAppDir=no
OutputDir=installer-output
OutputBaseFilename=ComprslySetup
; Small payload now that the model isn't bundled, so LZMA + solid is fine
; and keeps the ~40 MB app installer as small as possible.
Compression=lzma
SolidCompression=yes
WizardStyle=modern
; The app is ~40 MB. The optional AI model is downloaded later and needs
; ~1.2 GB then; require a little headroom now, not the whole model up front.
ExtraDiskSpaceRequired=120000000
; Add/Remove Programs metadata only (the Comments field in Programs and
; Features); Inno never shows it inside the wizard itself.
AppComments=~40 MB app. Spelling/grammar/punctuation work offline right away. The optional AI "Make it Concise" step downloads a ~1 GB model on first use (needs 8 GB RAM, 16 GB recommended).
; The onboarding flow, in order: Welcome -> Requirements -> Acknowledgements
; -> Preferences -> Install -> Done.
InfoBeforeFile=ACKNOWLEDGEMENTS.txt
DisableWelcomePage=no
; No install-location page ON PURPOSE: the app itself hardcodes ALL of its
; runtime data (settings.json, history, the ~1 GB model, the dedup and
; migration checks in [Code] below, and what uninstall cleans up) to
; %LOCALAPPDATA%\Comprsly. A custom {app} would put the exe in one place
; while everything else silently lands in — or is orphaned at — AppData,
; so offering the choice was a trap, not a courtesy.
DisableDirPage=yes
DisableReadyPage=no
AppVerName={#MyAppName} {#MyAppVersion}
VersionInfoDescription=Comprsly setup
VersionInfoVersion=0.9.81.0
; In-place upgrade support (real ask 2026-07-22): a re-run of setup over an
; existing install must replace the locked Comprsly.exe. This is handled by
; StopRunningApp() in PrepareToInstall() (a direct taskkill), NOT by Inno's
; CloseApplications: that was tried and REMOVED 2026-07-22 because it hung a
; silent install indefinitely when the running copy lived in a different
; folder than the install target (the exact scenario during testing). The
; taskkill is folder-independent and doesn't hang, so it's the only mechanism
; used. Combined with a constant AppId + UsePreviousAppDir=no, re-running
; setup upgrades cleanly and keeps the user's settings/history/model.
; Gives the downloaded setup file itself the Comprsly logo, which is what
; shows in the Downloads folder before anything is installed.
SetupIconFile=assets\icon.ico
; Replaces Inno's stock light-blue box-and-disc artwork with the real mark on
; the app's own dark background. That bitmap is the very first thing anyone
; sees of Comprsly and the default makes it look like generic shareware.
; Several sizes are listed so Windows can pick the right one per display
; scaling; generated by tools_make_installer_art.py.
WizardImageFile=assets\wizard_large_164x314.bmp,assets\wizard_large_192x386.bmp,assets\wizard_large_256x515.bmp,assets\wizard_large_320x644.bmp,assets\wizard_large_384x773.bmp
WizardSmallImageFile=assets\wizard_small_55x58.bmp,assets\wizard_small_64x68.bmp,assets\wizard_small_83x80.bmp,assets\wizard_small_92x97.bmp,assets\wizard_small_110x106.bmp,assets\wizard_small_119x123.bmp,assets\wizard_small_138x140.bmp,assets\wizard_small_150x161.bmp,assets\wizard_small_164x161.bmp,assets\wizard_small_192x192.bmp
; The mark sits on a dark panel, so stretching it would letterbox oddly.
WizardImageStretch=yes
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Messages]
; Real ask 2026-07-22: tell users they can delete the downloaded setup file
; afterwards to save space. Shown on the final "finished" page.
FinishedLabelNoIcons=Setup has finished installing [name] on your computer.%n%nYou can now delete the ComprslySetup file you downloaded — it isn't needed once Comprsly is installed, and removing it frees up space.
FinishedLabel=Setup has finished installing [name] on your computer.%n%nYou can now delete the ComprslySetup file you downloaded — it isn't needed once Comprsly is installed, and removing it frees up space.

[Tasks]
; These are the app's real preferences, chosen before anything is written,
; rather than settings the user has to go hunting for afterwards.
Name: "startupicon"; Description: "Start Comprsly when I sign in to Windows"; \
    GroupDescription: "Preferences:"
; Real bug found live 2026-07-25 (Antonio, on stream): these two descriptions
; used to carry a second explanatory sentence ("Downloads a ~1 GB model the
; first time it's used." / "Otherwise it downloads later, on first use.").
; At ~420-430px they crossed this wizard's task-list wrap width (measured:
; the desktop-shortcut line below fits at 408px, these wrapped at 417-428px),
; and Inno Setup's checkbox control has a well-documented rendering glitch
; where the checkbox glyph clips against a wrapped two-line item. Shortened
; to single clauses (163px/194px, well under the ~410px threshold) rather
; than patching the control itself -- the dropped detail is redundant
; anyway, the very next line already explains the model-download timing.
Name: "aienabled"; Description: "Enable AI compression (Step 2)"; \
    GroupDescription: "Preferences:"
; Optional: fetch the ~1 GB AI model NOW during install instead of on first
; use. Unchecked by default so the standard install stays fast; the app
; downloads it later either way. Real ask 2026-07-22.
Name: "downloadai"; Description: "Download the AI model now (~1 GB)"; \
    GroupDescription: "Preferences:"; Flags: unchecked
; Desktop shortcut, on by default now (real ask 2026-07-22, "add a taskbar
; shortcut"). NOTE: modern Windows blocks installers from pinning to the
; taskbar programmatically (the taskbarpin verb was removed in Win10), so the
; honest best is a shortcut the user can right-click -> Pin to taskbar. The
; description says exactly that.
Name: "desktopicon"; Description: "Create a desktop shortcut (right-click it → Pin to taskbar for one-click access)"; \
    GroupDescription: "Shortcuts:"

[Files]
Source: "dist\Comprsly.exe"; DestDir: "{app}"; Flags: ignoreversion
; The AI model is intentionally NOT bundled anymore (see the header note): it
; was 974 MB of the old ~1 GB installer. It's fetched in-app on first use of
; the AI step. Everything else works without it.
; Licences and notices travel with the app, which is what Apache 2.0 and the
; LGPL both ask for. Also reachable after install, not only during it.
Source: "ACKNOWLEDGEMENTS.txt"; DestDir: "{app}"; Flags: ignoreversion

[InstallDelete]
; Clear out the pre-rename binary and its Startup shortcut so an upgrade
; doesn't leave a second, older copy of the app launching itself on login.
Type: files; Name: "{app}\TokenSaver.exe"
Type: files; Name: "{userstartup}\Token Saver.lnk"
; And the Startup shortcut that lived in the OLD 'Token Saver' folder, so the
; folder rename doesn't leave a login shortcut pointing at a deleted exe.
Type: files; Name: "{userstartup}\Comprsly.lnk"

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
; NO Startup-folder shortcut here on purpose (real bug 2026-07-22): autostart
; is owned solely by the app's HKCU\...\Run entry (set_launch_on_login /
; heal_launch_on_login in main.py, and the Settings toggle). A Startup
; shortcut PLUS that Run key meant TWO launches on login: the second hit the
; single-instance guard and popped the Settings window every login. The
; "startupicon" task still records the user's preference into settings.json
; (see CurStepChanged); heal_launch_on_login writes the Run key on first run.

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName} now"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Files the APP creates at runtime (not installed by [Files], so Inno's
; uninstaller doesn't track them). Without this they'd be left behind and the
; install folder wouldn't fully delete. Real bug 2026-07-22.
Type: files; Name: "{app}\settings.json"
Type: files; Name: "{app}\history.json"
Type: files; Name: "{app}\badge_position.json"
Type: files; Name: "{app}\debug.log"
Type: files; Name: "{app}\debug.log.old"
Type: files; Name: "{app}\download_progress.json"
Type: files; Name: "{app}\download_request.flag"
Type: files; Name: "{app}\unload_request.flag"
Type: files; Name: "{app}\model_status.json"
; The AI model is downloaded at runtime into {app}\model, so Inno doesn't
; track it and wouldn't remove it, leaving ~974MB behind after uninstall
; (real gap 2026-07-22). Delete the whole model tree so uninstall reclaims it.
Type: filesandordirs; Name: "{app}\model"
Type: dirifempty; Name: "{app}"

[Code]
// The AI stage loads a ~1.5GB model into RAM. On a small machine that means
// paging, which is exactly the lag that dominated this project's history, so
// warn honestly up front rather than let it feel broken. A warning, not a
// block: the rules engine (spelling, grammar, wordiness) is useful on its
// own and needs almost nothing.
type
  TMemoryStatusEx = record
    dwLength: Cardinal;
    dwMemoryLoad: Cardinal;
    ullTotalPhys: Int64;
    ullAvailPhys: Int64;
    ullTotalPageFile: Int64;
    ullAvailPageFile: Int64;
    ullTotalVirtual: Int64;
    ullAvailVirtual: Int64;
    ullAvailExtendedVirtual: Int64;
  end;

function GlobalMemoryStatusEx(var lpBuffer: TMemoryStatusEx): Boolean;
  external 'GlobalMemoryStatusEx@kernel32.dll stdcall';

// Not a Pascal Script built-in despite the name -- needed for
// RunModelDownload's poll-loop timeout.
function GetTickCount: Cardinal;
  external 'GetTickCount@kernel32.dll stdcall';

var
  ReqPage: TWizardPage;
  ModelDownloadPage: TOutputProgressWizardPage;

function TotalRamGB(): Integer;
var
  MemStatus: TMemoryStatusEx;
begin
  Result := 0;
  MemStatus.dwLength := SizeOf(MemStatus);
  if GlobalMemoryStatusEx(MemStatus) then
    Result := Integer(MemStatus.ullTotalPhys div 1073741824);
end;

// One check row: a bold-ish label, its measured value, and a verdict. Shows
// what THIS machine has, not a generic spec list, so the requirements page
// answers "will this work for me" instead of "here are some numbers".
procedure AddCheck(Page: TWizardPage; var Top: Integer; Caption, Detail: String; Ok: Boolean);
var
  Mark, Title, Sub: TNewStaticText;
begin
  Mark := TNewStaticText.Create(Page);
  Mark.Parent := Page.Surface;
  Mark.Left := 0;
  Mark.Top := Top;
  Mark.Font.Style := [fsBold];
  if Ok then
  begin
    Mark.Caption := 'OK';
    Mark.Font.Color := $2E9E5B;
  end
  else
  begin
    Mark.Caption := '!';
    Mark.Font.Color := $0080D0;
  end;

  Title := TNewStaticText.Create(Page);
  Title.Parent := Page.Surface;
  Title.Left := ScaleX(28);
  Title.Top := Top;
  Title.Font.Style := [fsBold];
  Title.Caption := Caption;

  Sub := TNewStaticText.Create(Page);
  Sub.Parent := Page.Surface;
  Sub.Left := ScaleX(28);
  Sub.Top := Top + ScaleY(15);
  Sub.Width := Page.SurfaceWidth - ScaleX(28);
  Sub.AutoSize := False;
  Sub.WordWrap := True;
  // 26px fit one line and clipped the second: "Windows only, no Mac build
  // yet" rendered as "build yet" sliced in half. WordWrap labels do not
  // report the height they need, so this has to be sized for the worst case
  // and checked by looking at the rendered wizard.
  Sub.Height := ScaleY(30);
  Sub.Caption := Detail;

  Top := Top + ScaleY(52);
end;

procedure InitializeWizard();
var
  Top, Ram: Integer;
  FreeMB: Cardinal;
begin
  // Real ask 2026-07-25 (Antonio, on stream): the wizard was opening off to
  // one side instead of centered. CenterOnShow is TSetupForm's own, documented
  // property for exactly this (distinct from the generic VCL Position
  // property TForm also has) -- the dedicated, correct mechanism rather than
  // hand-computing screen bounds ourselves.
  WizardForm.CenterOnShow := True;

  ReqPage := CreateCustomPage(wpWelcome,
    'Before you install',
    'What Comprsly needs, and what this PC has.');

  Top := 0;
  Ram := TotalRamGB();

  AddCheck(ReqPage, Top, 'Windows 10 or later',
    'Uses Windows'' own accessibility and spell-check APIs. Windows only for now.',
    True);

  if Ram >= 16 then
    AddCheck(ReqPage, Top, 'Memory: ' + IntToStr(Ram) + ' GB',
      'Comfortable. The AI model uses ~1.5 GB while running and unloads when idle.',
      True)
  else if Ram >= 8 then
    AddCheck(ReqPage, Top, 'Memory: ' + IntToStr(Ram) + ' GB',
      'Workable. The AI step wants ~1.5 GB. 16 GB recommended for headroom.',
      True)
  else
    AddCheck(ReqPage, Top, 'Memory: ' + IntToStr(Ram) + ' GB, below the 8 GB recommendation',
      'Spelling and grammar work fine. The AI step may be slow; it can be turned off.',
      False);

  FreeMB := 0;
  AddCheck(ReqPage, Top, 'Disk: ~40 MB now',
    'The app is tiny. The optional AI "Make it Concise" model is a one-time ~1 GB download later, only if you use it.',
    True);

  AddCheck(ReqPage, Top, 'No account, no telemetry',
    'Your text never leaves this machine. The only network use is the one-time AI-model download, if you choose to use compression.',
    True);

  // Progress page used only when "downloadai" is selected (see RunModelDownload,
  // called from CurStepChanged after the app itself is installed). A plain
  // TOutputProgressWizardPage, not Inno's own TDownloadWizardPage: the actual
  // download runs inside Comprsly.exe itself (local_model.download_model),
  // this page just mirrors its progress -- see the 2026-07-24 note above
  // RunModelDownload for why.
  ModelDownloadPage := CreateOutputProgressPage(
    'Downloading the AI model',
    'Fetching the ~1 GB model so AI compression is ready immediately. This is optional; you can skip and the app will download it later on first use.');
end;

// Is a real (complete) model already on this machine, so a download would be
// a wasteful duplicate? Real ask 2026-07-22: "recognize if they already have
// anything set up, this is a safe download for anyone." Checks the target
// folder AND the legacy 'Token Saver' folder (an upgrade from an old bundled
// install), keyed on the big weights file actually being present.
function ModelAlreadyPresent(): Boolean;
begin
  Result :=
    FileExists(ExpandConstant('{app}\model\qwen2.5-1.5b-instruct-int4-cpu\model.onnx.data')) or
    FileExists(ExpandConstant('{localappdata}\{#MyLegacyFolder}\model\qwen2.5-1.5b-instruct-int4-cpu\model.onnx.data'));
end;

// Now downloads straight into {app}\model (see RunModelDownload) instead of
// a separate {tmp} copy that then gets duplicated into {app} -- so this only
// needs headroom for ONE ~1 GB copy, not two. ExtraDiskSpaceRequired in
// [Setup] deliberately budgets only the ~40 MB app: the model is optional,
// so a low-disk machine must still be able to install and just skip it.
function EnoughSpaceForModel(): Boolean;
var
  FreeBytes, TotalBytes: Int64;
begin
  // If the free-space query itself fails, don't block the download over it;
  // the download's own failure handling copes with running out of disk.
  Result := True;
  if GetSpaceOnDisk64(ExpandConstant('{localappdata}'), FreeBytes, TotalBytes) then
    Result := (FreeBytes div 1048576) >= 1200;  // ~1.2 GB, small buffer over the ~1 GB model
end;

// Tiny hand-rolled reader for the flat, fixed-shape JSON local_model.py's
// _write_progress_file() produces ({"active":bool,"done":int,"total":int,
// "file":str,"error":str|null}) -- Inno's Pascal has no JSON parser built
// in, and pulling in a real one is overkill for a shape we fully control on
// both ends. Good enough because it only ever has to survive OUR OWN output.
function ExtractJsonInt(const Json, Key: String): Int64;
var
  P, S: Integer;
  Digits: String;
begin
  Result := 0;
  P := Pos('"' + Key + '":', Json);
  if P = 0 then exit;
  P := P + Length(Key) + 3;
  while (P <= Length(Json)) and (Json[P] = ' ') do P := P + 1;
  S := P;
  while (P <= Length(Json)) and (Json[P] >= '0') and (Json[P] <= '9') do P := P + 1;
  Digits := Copy(Json, S, P - S);
  if Digits <> '' then
    Result := StrToInt64Def(Digits, 0);
end;

function JsonSaysActive(const Json: String): Boolean;
begin
  Result := (Pos('"active": true', Json) > 0) or (Pos('"active":true', Json) > 0);
end;

// Real ask 2026-07-24, going-to-market hardening: this used to run Inno
// Setup's OWN built-in downloader (TDownloadWizardPage) at the wizard's
// "Ready" step, before the app itself was even copied to disk. That closed,
// unauditable component hit two different real failures live on the same
// evening: a genuine dropped connection at 94% (fair enough, networks drop),
// and once a full, error-free 100% completion that silently restarted the
// same ~950MB file from zero anyway (NOT a network issue -- it happened
// after a clean finish, inside Inno's engine, with nothing in OUR log to
// explain it). Rather than keep debugging a black box we can't see the
// source of, this now runs AFTER the app's own files are copied (see
// CurStepChanged), shelling out to Comprsly.exe --download-model, which
// just calls local_model.download_model() -- the SAME code path Settings
// and onboarding already use, with its own proven per-file retry+backoff
// and atomic swap-into-place. One downloader, not two.
procedure RunModelDownload();
var
  ResultCode: Integer;
  ProgressPath: String;
  Json: AnsiString;  // LoadStringFromFile requires AnsiString, not String
  DoneVal, TotalVal: Int64;
  StartTicks: Cardinal;
  TimedOut: Boolean;
begin
  if not WizardIsTaskSelected('downloadai') then exit;
  if ModelAlreadyPresent() then
  begin
    Log('AI model already present, skipping the post-install download (no duplicate).');
    exit;
  end;
  if not EnoughSpaceForModel() then
  begin
    MsgBox('There isn''t enough free disk space to download the AI model right now '
      + '(it needs about 1.2 GB free).'#13#10#13#10
      + 'Setup will finish without it. Comprsly can download the model later, '
      + 'from Settings, once space is freed up.', mbInformation, MB_OK);
    Log('skipping post-install model download: under 1.2 GB free on the {localappdata} drive.');
    exit;
  end;

  ProgressPath := ExpandConstant('{localappdata}\Comprsly\download_progress.json');
  DeleteFile(ProgressPath);  // clear any stale file so "not active" can't false-positive on tick 1

  if not Exec(ExpandConstant('{app}\Comprsly.exe'), '--download-model', '',
              SW_HIDE, ewNoWait, ResultCode) then
  begin
    Log('failed to launch Comprsly.exe --download-model; the app will download it on first use.');
    exit;
  end;

  ModelDownloadPage.SetText('Downloading the AI model', 'This is a one-time ~1 GB download so AI compression is ready right away.');
  ModelDownloadPage.SetProgress(0, 100);
  ModelDownloadPage.Show;
  StartTicks := GetTickCount;
  TimedOut := False;
  try
    // Sleep() in [Code] pumps the message queue, so the wizard stays
    // responsive while this polls -- a real blocking Exec(ewWaitUntilTerminated)
    // would freeze the whole window for the download's full duration instead.
    Sleep(500);
    while True do
    begin
      Sleep(300);
      if LoadStringFromFile(ProgressPath, Json) then
      begin
        TotalVal := ExtractJsonInt(Json, 'total');
        DoneVal := ExtractJsonInt(Json, 'done');
        // Longint (32-bit signed, max ~2.1 GB) comfortably fits the ~1 GB
        // model; this pairing was never going to be used for anything bigger.
        if TotalVal > 0 then
          ModelDownloadPage.SetProgress(Longint(DoneVal), Longint(TotalVal));
        if not JsonSaysActive(Json) then break;
      end;
      // Safety net only -- download_model()'s own per-file retries mean this
      // should never actually run long enough to matter, but Setup must
      // never hang forever if the child process dies without updating the
      // progress file.
      if (GetTickCount - StartTicks) > 900000 then
      begin
        TimedOut := True;
        break;
      end;
    end;
  finally
    ModelDownloadPage.Hide;
  end;

  if TimedOut then
    Log('post-install model download timed out after 15 minutes; the app will offer it again on first use.')
  else if ModelAlreadyPresent() then
    Log('AI model download (post-install) succeeded.')
  else
  begin
    Log('AI model download (post-install) did not complete; the app will offer it again on first use.');
    MsgBox('The AI model didn''t finish downloading (likely a network hiccup on the ~1 GB '
      + 'transfer).'#13#10#13#10
      + 'Setup has already finished installing Comprsly, which still works for grammar/'
      + 'spelling right away. It will offer to download the model again the first time you '
      + 'open Settings or use AI compression.', mbInformation, MB_OK);
  end;
end;

// Close any running Comprsly before files are copied (real ask
// 2026-07-22, in-place upgrade). CloseApplications=yes handles a same-folder
// upgrade, but the running copy may be the OLD install in the 'Token Saver'
// folder, which it can't detect because that isn't the folder being written.
// A direct taskkill covers both. Harmless when nothing is running.
procedure StopRunningApp();
var
  ResultCode: Integer;
begin
  Exec('taskkill.exe', '/IM Comprsly.exe /F', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Exec('taskkill.exe', '/IM TokenSaver.exe /F', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  StopRunningApp();
  // taskkill /F returns before Windows releases the exe's file lock; the
  // uninstall side needed exactly this wait for the identical situation.
  Sleep(700);
  Result := '';
end;

// Copy the small user-data files out of the legacy 'Token Saver' folder into
// the new 'Comprsly' folder, only where the new one doesn't already have
// them, so an in-place upgrade keeps settings/history/badge position.
procedure MigrateLegacyData();
var
  OldDir, NewDir: String;
  I: Integer;
  Names: array[0..2] of String;
begin
  OldDir := ExpandConstant('{localappdata}\{#MyLegacyFolder}');
  NewDir := ExpandConstant('{app}');
  if not DirExists(OldDir) then exit;
  Names[0] := 'settings.json';
  Names[1] := 'history.json';
  Names[2] := 'badge_position.json';
  for I := 0 to 2 do
    if FileExists(OldDir + '\' + Names[I]) and not FileExists(NewDir + '\' + Names[I]) then
      CopyFile(OldDir + '\' + Names[I], NewDir + '\' + Names[I], False);
end;

// Real ask 2026-07-22 ("don't download duplicates, recognize what they
// already have"): an old BUNDLED install has a full ~1GB model in the legacy
// 'Token Saver' folder. MOVE it into the new folder instead of letting
// RemoveLegacyFolder delete it and then re-downloading a gigabyte. Only moves
// when the new folder doesn't already have a model, and a move within the same
// drive is near-instant.
// Returns True when the legacy folder is SAFE to delete afterwards: either
// there was no legacy model to save, or the move landed. False means the
// legacy folder still holds the user's only good model copy, and the caller
// must NOT DelTree it.
function MigrateLegacyModel(): Boolean;
var
  OldModel, NewModel: String;
begin
  Result := True;
  OldModel := ExpandConstant('{localappdata}\{#MyLegacyFolder}\model\qwen2.5-1.5b-instruct-int4-cpu');
  NewModel := ExpandConstant('{app}\model\qwen2.5-1.5b-instruct-int4-cpu');
  if FileExists(OldModel + '\model.onnx.data')
     and not FileExists(NewModel + '\model.onnx.data') then
  begin
    ForceDirectories(ExpandConstant('{app}\model'));
    // Anything already at NewModel here is junk by definition (the weights
    // file is missing — checked above), e.g. an interrupted download.
    // RemoveDir only clears EMPTY dirs, so a non-empty partial used to make
    // the RenameFile below fail silently; DelTree clears it for real.
    if DirExists(NewModel) then
      DelTree(NewModel, True, True, True);
    if RenameFile(OldModel, NewModel) then
      Log('moved existing model from the legacy folder, no re-download needed')
    else
    begin
      Log('could not move legacy model; keeping the legacy folder so its copy isn''t destroyed');
      Result := False;
    end;
  end;
end;

// After migrating, remove the whole legacy folder (old exe, ~1GB model, old
// uninstaller, logs) so the rename doesn't leave a gigabyte orphaned.
procedure RemoveLegacyFolder();
var
  OldDir: String;
begin
  OldDir := ExpandConstant('{localappdata}\{#MyLegacyFolder}');
  if DirExists(OldDir) then
    DelTree(OldDir, True, True, True);
end;

// Repoint the app's own autostart Run entry if it still targets the old
// folder's exe. The app self-heals this on next launch too (main.py
// heal_launch_on_login); doing it here makes it correct even before the
// first start. Only rewrites an entry that already exists, never creates one.
procedure FixAutostartRegistry();
var
  RunKey, Val, NewVal: String;
begin
  RunKey := 'Software\Microsoft\Windows\CurrentVersion\Run';
  if RegQueryStringValue(HKCU, RunKey, 'Comprsly', Val) then
  begin
    NewVal := '"' + ExpandConstant('{app}\{#MyAppExeName}') + '"';
    if Val <> NewVal then
      RegWriteStringValue(HKCU, RunKey, 'Comprsly', NewVal);
  end;
end;

// Preferences chosen on the Tasks page are written to the app's own settings
// file, but ONLY for a fresh install: an upgrade must never silently reset
// choices the user has already made in the app.
procedure CurStepChanged(CurStep: TSetupStep);
var
  SettingsPath, Json, AiVal, LoginVal: String;
  LegacySafeToRemove: Boolean;
begin
  if CurStep = ssPostInstall then
  begin
    // Migrate BEFORE the task-based settings write below, so a carried-over
    // settings.json wins and the task defaults only apply to a truly fresh
    // install with no legacy folder.
    MigrateLegacyData();
    // Keep a model the user already had (old bundled install) instead of
    // deleting + re-downloading it. Runs before RemoveLegacyFolder, and its
    // result GATES RemoveLegacyFolder: if the move failed, the legacy folder
    // still holds the only good model copy and must not be DelTree'd.
    LegacySafeToRemove := MigrateLegacyModel();

    SettingsPath := ExpandConstant('{app}\settings.json');
    if not FileExists(SettingsPath) then
    begin
      // Real gap found 2026-07-24: 'aienabled' and 'downloadai' are two
      // independent checkboxes, so choosing "download the model now" while
      // leaving "enable AI compression" at whatever state it's in could
      // write ai_enabled: false right after successfully installing the
      // model -- the app would then sit on a fully-downloaded model it
      // never offers to use. Downloading it now always means AI should be
      // on; the reverse (aienabled checked, download deferred) is still the
      // normal, valid "use it, fetch the model on first use" case.
      if WizardIsTaskSelected('aienabled') or WizardIsTaskSelected('downloadai')
        then AiVal := 'true' else AiVal := 'false';
      if WizardIsTaskSelected('startupicon') then LoginVal := 'true' else LoginVal := 'false';
      Json := '{"launch_on_login": ' + LoginVal
        + ', "ai_enabled": ' + AiVal + '}';
      SaveStringToFile(SettingsPath, Json, False);
    end;

    FixAutostartRegistry();
    // Reclaim the old folder last, after its data has been migrated out —
    // but ONLY if the model migration didn't leave the user's sole model
    // copy behind in it (see MigrateLegacyModel).
    if LegacySafeToRemove then
      RemoveLegacyFolder()
    else
      Log('legacy folder kept: it still holds the model that could not be moved');
    // Last: {app}\Comprsly.exe now genuinely exists (just copied above), so
    // this is the earliest point RunModelDownload can shell out to it.
    RunModelDownload();
  end;
end;

// Uninstall (real bug 2026-07-22: "it's not allowing the user to delete the
// app"). Two causes, both fixed here:
//   1. Comprsly is almost always running (tray + autostart), so its
//      Comprsly.exe is LOCKED and the uninstaller can't delete it. Kill it
//      first, before any file removal.
//   2. The app's autostart Run entry is created at RUNTIME (main.py
//      set_launch_on_login / heal_launch_on_login), not by this installer,
//      so Inno's uninstaller has no record of it and leaves it behind, which
//      then relaunches a half-deleted exe on next login and makes the app
//      look undeletable. Remove it explicitly.
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  ResultCode: Integer;
begin
  if CurUninstallStep = usUninstall then
  begin
    Exec('taskkill.exe', '/IM Comprsly.exe /F', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
    Exec('taskkill.exe', '/IM TokenSaver.exe /F', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
    RegDeleteValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', 'Comprsly');
    Sleep(700);  // let Windows release the locked exe handle before deletion
  end;
end;
