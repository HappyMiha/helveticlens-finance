; Inno Setup script for the Financial Lens Windows installer (per-user, no admin rights needed).
#define AppVersion GetEnv("FL_VERSION")
[Setup]
AppId={{6F3A1C2E-8B9D-4E21-9C11-0F1A5C0000A1}
AppName=Financial Lens
AppVersion={#AppVersion}
AppPublisher=Helvetic Lens contributors
AppPublisherURL=https://finance.helveticlens.ch
DefaultDirName={localappdata}\Programs\Financial Lens
DefaultGroupName=Financial Lens
PrivilegesRequired=lowest
OutputDir=..\..\dist
OutputBaseFilename=FinancialLens-Setup-x64
SetupIconFile=..\icon.ico
UninstallDisplayIcon={app}\FinancialLens.exe
Compression=lzma2/max
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
LicenseFile=..\..\LICENSE

[Languages]
Name: "en"; MessagesFile: "compiler:Default.isl"
Name: "de"; MessagesFile: "compiler:Languages\German.isl"
Name: "fr"; MessagesFile: "compiler:Languages\French.isl"
Name: "it"; MessagesFile: "compiler:Languages\Italian.isl"
Name: "uk"; MessagesFile: "compiler:Languages\Ukrainian.isl"

[Files]
Source: "..\..\build\pyi\dist\FinancialLens\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\Financial Lens"; Filename: "{app}\FinancialLens.exe"
Name: "{userdesktop}\Financial Lens"; Filename: "{app}\FinancialLens.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; Flags: unchecked

[Run]
Filename: "{app}\FinancialLens.exe"; Description: "{cm:LaunchProgram,Financial Lens}"; Flags: nowait postinstall skipifsilent
