# Release runbook

How a desktop change gets from `main` into the Microsoft Store. Written
2026-11-22 while preparing 1.1.0, with the real Partner Center state verified
in the browser rather than taken from notes.

## Partner Center, verified 2026-11-22

Checked directly in the dashboard. **Both of the previous records were wrong.**

| | The docs said | Actually true |
|---|---|---|
| Live package version | 1.0.1.0 | **1.0.3.0** (`ComprslyStore-New.msix`, x64) |
| Submission 2 | "back in draft, waiting on a new MSIX" | **Passed and shipped.** Last modified 08/04/2026, Store presence is read only |
| Pending submission | implied | **None.** Clean slate, "Start update" available |

Minimum OS on the live package: `Windows.Desktop 10.0.17763.0`.

**Any new package must be numbered above 1.0.3.0.** This is why the next
release is 1.1.0.0 and not something in the 1.0.x range.

Partner Center is also showing a policy banner: Store Policies were updated
**2026-09-15, effective 2026-10-22**. `msix-certification-prompt.md` predates
that by two months, so its six findings are against the OLD policy text. Re-read
the current policy before relying on it.

## The chain

```
main  →  PyInstaller  →  dist/Comprsly.exe
      →  Inno Setup   →  installer-output/ComprslySetup.exe
      →  MSIX tool    →  installer-output/ComprslyStore.msix
      →  Package Editor (GUI, mandatory)
      →  Partner Center upload and submit
      →  certification  →  live
```

Steps 1 and 5 onward can be automated. Steps 2, 3 and 4 cannot, for reasons
below that are not a matter of permissions.

## Version bump: all four files move together

This has drifted twice and been written up twice. On 2026-11-22 the MSIX
template was still at `1.0.2.0` while everything else said `1.0.67`, which
would have produced a package numbered BELOW what is already live and been
rejected.

- `main.py` → `APP_VERSION`
- `version_info.txt` → `filevers`, `prodvers`, and the `FileVersion` /
  `ProductVersion` StringStructs
- `installer.iss` → `MyAppVersion`, `VersionInfoVersion`
- `msix-conversion-template.xml` → `PackageInformation Version`

Check them against each other before building, every time.

## Step 1: build the exe (automatable)

```
cd desktop
"C:/Users/anton/AppData/Local/Python/pythoncore-3.14-64/python.exe" -m PyInstaller Comprsly.spec --noconfirm --clean
```

Then confirm the version actually landed inside the binary, rather than
trusting the source file:

```
powershell -NoProfile -Command "(Get-Item 'dist\Comprsly.exe').VersionInfo | Select FileVersion,ProductVersion"
```

## Step 2: build the installer (BLOCKED, needs a one time install)

`installer.iss` is compiled by Inno Setup's `ISCC.exe`, which is **not
installed on this machine**. CI installs it with `choco install innosetup -y`,
but Chocolatey is not on PATH here either.

One time fix, from an elevated terminal:

```
winget install -e --id JRSoftware.InnoSetup
```

Then the build itself is scriptable:

```
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer.iss
```

The installer bundles the local model from
`%LOCALAPPDATA%\Comprsly\model\qwen2.5-1.5b-instruct-int4-cpu` (975 MB,
present and verified 2026-11-22), which is why the finished package is ~1 GB.

## Step 3: MSIX package (REQUIRES A HUMAN)

```
"%LOCALAPPDATA%\Microsoft\WindowsApps\MsixPackagingTool.exe" create-package --template "C:\Dev\Claude Code\Projects\Comprsly\desktop\msix-conversion-template.xml" -v
```

**Must run elevated.** The UAC prompt renders on Windows' secure desktop,
which by design no software can see or interact with. This is not a
permissions setting that can be changed; it is the point of the secure
desktop. Unelevated it fails immediately with "the requested operation
requires elevation".

## Step 4: Package Editor (REQUIRES A HUMAN)

The CLI template schema has no field for `Description` or custom
`Extensions`, so `create-package` always emits `<Description>None</Description>`.
The GUI Package Editor is the only way to fix it, because it regenerates the
block map and re-signs, and Microsoft ships no CLI equivalent.

Known and accepted quirk: saving in Package Editor auto-increments the
manifest's fourth version segment, so a `1.1.0.0` template commonly comes out
as `1.1.1.0`. Do not fight it. Record whatever it lands on.

## Step 5: verify before uploading

1. Extract `Comprsly.exe` from inside the `.msix`, SHA256 it, and compare
   against the freshly built `dist/Comprsly.exe`. They must match exactly.
2. Extract and read `AppxManifest.xml`. Confirm `Description` and `Version`
   by eye, never by assumption.
3. `Add-AppxPackage -Path "..."` locally, launch it, and confirm
   `%LOCALAPPDATA%\Comprsly\debug.log` shows a clean startup.

## Step 6: submit

Partner Center → the product → Start update → Packages. Upload, then walk the
six sections. On a packaging-only update the listing sections do not need
redoing.

Package files exceed the browser upload limit that automation can drive, so
the upload itself has been a manual step every previous time.
