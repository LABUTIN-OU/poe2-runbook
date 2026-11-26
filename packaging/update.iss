; SPDX-License-Identifier: GPL-3.0-only
; Copyright © 2026 Sergei Labutin
; Additional terms under GPL-3.0 section 7: see NOTICE.md
; Обновление из самой программы (planner/update.py). Подключается из PoE2Runbook.iss (#include).
; Программа скачивает этот установщик, сверяет его с подписанным файлом обновления, запускает тихо —
; /VERYSILENT /SUPPRESSMSGBOXES /CLOSEAPPLICATIONS /RESTARTAPPLICATIONS — и закрывается сама. Тогда:
;   * пока прежняя программа не завершилась, её файлы заняты: установщик ждёт, пока исчезнет её отметка — мьютекс
;     AppMutex (его держит окно программы, desktop.py, до самого выхода), — не дольше 30 секунд; дальше ставит как
;     обычно (CloseApplications закроет то, что ещё держит файлы);
;   * после такой тихой установки (в ней есть /RESTARTAPPLICATIONS) открывает программу снова — уже новую.
; Обычная установка с окнами — как раньше: ничего не ждёт, а открыть ли программу, решает галочка на последней странице.
; Проверка — planner/test_update.py: собирает пробный установщик с этим же файлом и запускает его.

#ifndef AppMutex
  #define AppMutex "Local\PoE2RunbookApp"
#endif
#ifndef AppExe
  #define AppExe "PoE2Runbook.exe"
#endif

[Run]
Filename: "{app}\{#AppExe}"; Flags: nowait; Check: UpdateRestart

[Code]
// Тихая установка: прежняя программа ещё закрывается — ждём, пока исчезнет её мьютекс, не дольше 30 секунд
<event('InitializeSetup')>
function UpdateWaitForApp(): Boolean;
var
  Waited: Integer;
begin
  Waited := 0;
  if WizardSilent then
    while CheckForMutexes('{#AppMutex}') and (Waited < 30000) do
    begin
      Sleep(250);
      Waited := Waited + 250;
    end;
  Result := True;
end;

// Открыть программу после установки — только после тихой установки из программы (с /RESTARTAPPLICATIONS)
function UpdateRestart(): Boolean;
begin
  Result := WizardSilent and (Pos('/RESTARTAPPLICATIONS', Uppercase(GetCmdTail)) > 0);
end;
