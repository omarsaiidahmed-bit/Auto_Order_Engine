; ---------------------------------------------------------------------------
; Inno Setup script -- wraps the PyInstaller output in a real Setup.exe.
;
;   1. build the app (from the project root):
;
;        python -m PyInstaller --noconfirm --noconsole --onedir --name="AutoOrder" ^
;            --add-data "app.py;." --add-data "app_config.py;." --add-data "company_logo.png;." --add-data "core;core" ^
;            --collect-all streamlit --collect-all pandas --collect-all openpyxl ^
;            --collect-all xlrd --collect-all plotly --collect-all xlsxwriter ^
;            --collect-all streamlit_option_menu launcher.py
;
;   2. compile this file:
;        "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" setup_installer.iss
;        (or "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" for a machine-wide install)
;
; The installer is written to installer\AutoOrder_Setup_<version>.exe and the
; target machine needs nothing installed -- no Python, no pip, no browser
; extension.  Everything the app reads or writes at run time lives in
; %LOCALAPPDATA%\AutoOrder (log + pid file) or in the browser's temp folder.
;
; openpyxl and xlrd look optional but are not: pandas imports them lazily by
; name for .xlsx/.xls files, so PyInstaller cannot see them and the app would
; fail on the first upload without those two --collect-all flags.
; ---------------------------------------------------------------------------

#define AppName "Auto Order"
#define AppVersion "2.0.0"
#define AppPublisher "Auto Order"
#define AppExeName "AutoOrder.exe"
#define BuildDir "dist\AutoOrder"

; Fail early instead of producing an empty installer.
#if !FileExists(BuildDir + "\" + AppExeName)
  #error "dist\AutoOrder\AutoOrder.exe is missing -- run PyInstaller first."
#endif

[Setup]
; A fixed AppId keeps upgrades in the same place and gives uninstall a stable key.
AppId={{B7E1F0A2-5C3D-4F6B-9A21-7D4C8E3B1F05}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
VersionInfoVersion={#AppVersion}
VersionInfoProductName={#AppName}
VersionInfoDescription={#AppName} Setup

; Program Files by default; a user without admin rights may install per-user.
DefaultDirName={autopf}\AutoOrder
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes

; The PyInstaller bundle is 64-bit and needs Windows 10 or newer.
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0

OutputDir=installer
OutputBaseFilename=AutoOrder_Setup_{#AppVersion}
Compression=none
SolidCompression=no
WizardStyle=modern
SetupLogging=yes

; Ask the running instance to close instead of failing on locked files.
CloseApplications=yes
RestartApplications=no
UninstallDisplayName={#AppName}
UninstallDisplayIcon={app}\{#AppExeName}

; Optional: drop a 256x256 icon in assets\AutoOrder.ico and uncomment.
; SetupIconFile=assets\AutoOrder.ico

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "arabic"; MessagesFile: "compiler:Languages\Arabic.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; The whole onedir bundle: AutoOrder.exe + _internal (Python runtime, Streamlit
; static assets, pandas/numpy/pyarrow, app.py, app_config.py, company_logo.png,
; core).
Source: "{#BuildDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; Upgrades must not keep files from the previous runtime: delete the old
; _internal tree and the old exe before copying the new build.
Type: filesandordirs; Name: "{app}\_internal"
Type: files; Name: "{app}\{#AppExeName}"

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Comment: "Pharmacy auto-order"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(AppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
; Optional post-install smoke test: writes to %LOCALAPPDATA%\AutoOrder\launcher.log
Filename: "{app}\{#AppExeName}"; Parameters: "--selftest"; Flags: runhidden nowait skipifsilent

[UninstallRun]
; Stop the browser-facing server before the files are removed.
Filename: "{app}\{#AppExeName}"; Parameters: "--stop"; Flags: runhidden; RunOnceId: "StopAutoOrder"
