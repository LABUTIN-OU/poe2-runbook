; SPDX-License-Identifier: GPL-3.0-only
; Copyright © 2026 Sergei Labutin
; Additional terms under GPL-3.0 section 7: see NOTICE.md
; Установщик PoE2 Runbook (Inno Setup 6). Собирается packaging\build.py: он передаёт версию и папки.
; Ставит только для текущего пользователя (%LOCALAPPDATA%\Programs\PoE2 Runbook) — без прав администратора.
; Новая версия ставится поверх: старая папка программы заменяется целиком. Файлы игрока лежат не здесь, а в
; %APPDATA%\PoE2 Runbook — ни обновление, ни удаление программы их не трогают.
; Чья программа: издатель, копирайт и официальный адрес — в свойствах установщика и в «Установке и удалении программ».
; LICENSE, NOTICE.md и THIRD-PARTY.md лежат в папке программы (их кладёт туда build.py) и ставятся вместе с ней.
; Страницы «примите лицензию» нет: GPL согласия на использование не требует.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "dist\PoE2Runbook"
#endif
#ifndef OutDir
  #define OutDir "..\dist"
#endif

[Setup]
AppId={{6B3F1C2E-5A1D-4C8B-9E27-2F4D7A9C1B50}
AppName=PoE2 Runbook
AppVersion={#AppVersion}
AppVerName=PoE2 Runbook {#AppVersion}
AppPublisher=Sergei Labutin
AppCopyright=© 2026 Sergei Labutin
AppPublisherURL=https://poe2.labutin.gg
AppSupportURL=https://poe2.labutin.gg
AppUpdatesURL=https://poe2.labutin.gg
DefaultDirName={autopf}\PoE2 Runbook
DefaultGroupName=PoE2 Runbook
DisableProgramGroupPage=yes
DisableDirPage=auto
PrivilegesRequired=lowest
OutputDir={#OutDir}
OutputBaseFilename=PoE2Runbook-Setup-{#AppVersion}
SetupIconFile=app.ico
UninstallDisplayIcon={app}\PoE2Runbook.exe
UninstallDisplayName=PoE2 Runbook
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ShowLanguageDialog=auto
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no
VersionInfoVersion={#AppVersion}
VersionInfoProductName=PoE2 Runbook
VersionInfoCompany=Sergei Labutin
VersionInfoCopyright=© 2026 Sergei Labutin
VersionInfoDescription=PoE2 Runbook Setup

[Languages]
Name: "en"; MessagesFile: "compiler:Default.isl"
Name: "ru"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "de"; MessagesFile: "compiler:Languages\German.isl"
Name: "fr"; MessagesFile: "compiler:Languages\French.isl"
Name: "es"; MessagesFile: "compiler:Languages\Spanish.isl"
Name: "pt"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"
Name: "ja"; MessagesFile: "compiler:Languages\Japanese.isl"
Name: "ko"; MessagesFile: "compiler:Languages\Korean.isl"
Name: "th"; MessagesFile: "compiler:Languages\Thai.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[InstallDelete]
; файлы прежней версии программы — не копить: папка _internal ставится заново целиком
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\PoE2 Runbook"; Filename: "{app}\PoE2Runbook.exe"
Name: "{autodesktop}\PoE2 Runbook"; Filename: "{app}\PoE2Runbook.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\PoE2Runbook.exe"; Description: "{cm:LaunchProgram,PoE2 Runbook}"; Flags: nowait postinstall skipifsilent

; обновление из самой программы: тихая установка ждёт её выхода и открывает её снова (planner/update.py)
#include "update.iss"
