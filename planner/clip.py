# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Sergei Labutin
# Additional terms under GPL-3.0 section 7: see NOTICE.md
"""Буфер обмена: текст вещи, которую игрок скопировал в игре.

Правило GGG для программ рядом с игрой: буфер можно читать, если игрок знает, что читается, и одно
чтение приходится на одно нажатие клавиши самим игроком. Здесь так и есть: игра кладёт текст вещи
в буфер по Ctrl+Alt+C, программа замечает, что буфер сменился, и читает его один раз. В игру программа
ничего не посылает и клавиш не нажимает.

Буфер — общий на весь компьютер: в нём бывают пароли и письма. Поэтому:
  * содержимое читается, только если в этот момент активно окно игры — программа, запущенная из её
    папки; всё, что скопировано в другом окне, не читается вовсе;
  * то, что лежало в буфере до запуска программы, не читается: ждём следующей смены;
  * прочитанное, если это не текст вещи, сразу отбрасывается — не хранится и никуда не пишется
    (см. itemcopy.is_item); текст вещи живёт только в памяти программы.

Здесь же — клавиши страницы в самой игре (WinKeys): «Надеть» (игрок говорит, что надевает скопированную вещь) и
«Закрыть» (убрать верхнее окно страницы — сравнение, путевой камень, очки дерева), не уходя из игры в браузер. Как у
Awakened PoE Trade и Exiled Exchange 2, клавиши регистрируются в системе только пока впереди окно игры и снимаются, когда
активно другое; в игру программа и тут ничего не посылает и ничего не читает.

Единственное место, где программа сама нажимает клавиши в игре, — клавиша «Сравнить» (она же «Надеть»; Copier): по одному
нажатию игрока она один раз нажимает то же, что нажал бы он сам (Ctrl + клавиша подробных свойств + C), один раз
читает буфер и возвращает в него то, что лежало раньше. Правила GGG это допускают: действие только по ручному нажатию
(не по таймеру, не по логу, не по экрану), одно действие в игре на нажатие; так же устроена оценка предмета у
Exiled Exchange 2. То, что лежало в буфере, при этом не разбирается и не хранится: байты держатся в памяти долю
секунды и кладутся обратно как были.
"""
import ctypes
import os
import sys
import threading
import time
from pathlib import Path

import itemcopy
from i18n import tr

CF_UNICODETEXT = 13
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
MAX_BYTES = 200_000          # текст вещи — несколько килобайт; больше — в буфере не она
GAME_TITLES = ('Path of Exile 2',)
# Буфер перед своей копией запоминается целиком и возвращается: форматы, которые лежат в нём блоком памяти (текст,
# RTF, HTML, список файлов, картинка DIB / PNG). Форматы-объекты (растр GDI, метафайл, палитра) блоком не являются —
# Windows сама воссоздаёт их из запомненных; «отображаемые» форматы владельца не трогаем. Больше SNAP_BYTES в буфере —
# не запоминаем (копировать сотни мегабайт на каждое нажатие нельзя): тогда буфер после копии остаётся с текстом предмета,
# как и при обычном Ctrl+Alt+C.
SNAP_SKIP = frozenset((2, 3, 9, 14, 0x80, 0x82, 0x83, 0x8E))
SNAP_BYTES = 32 * 1024 * 1024
VK_CONTROL, VK_MENU, VK_C = 0x11, 0x12, 0x43


class WinClipboard:
    """Буфер обмена Windows через системные вызовы (без сторонних библиотек)."""

    def __init__(self, game_dir=None, titles=GAME_TITLES):
        if sys.platform != 'win32':
            raise OSError(tr('буфер обмена читается только в Windows'))
        from ctypes import wintypes as w
        self.game_dir = os.path.normcase(os.path.abspath(str(game_dir))) if game_dir else None
        self.titles = tuple(titles)
        self._w = w
        u = self.user32 = ctypes.WinDLL('user32', use_last_error=True)
        k = self.kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        u.GetClipboardSequenceNumber.restype = w.DWORD
        u.OpenClipboard.argtypes, u.OpenClipboard.restype = [w.HWND], w.BOOL
        u.CloseClipboard.restype = w.BOOL
        u.IsClipboardFormatAvailable.argtypes, u.IsClipboardFormatAvailable.restype = [w.UINT], w.BOOL
        u.GetClipboardData.argtypes, u.GetClipboardData.restype = [w.UINT], w.HANDLE
        u.GetForegroundWindow.restype = w.HWND
        u.GetWindowTextW.argtypes, u.GetWindowTextW.restype = [w.HWND, w.LPWSTR, ctypes.c_int], ctypes.c_int
        u.GetWindowThreadProcessId.argtypes = [w.HWND, ctypes.POINTER(w.DWORD)]
        u.GetWindowThreadProcessId.restype = w.DWORD
        k.GlobalLock.argtypes, k.GlobalLock.restype = [w.HGLOBAL], w.LPVOID
        k.GlobalUnlock.argtypes, k.GlobalUnlock.restype = [w.HGLOBAL], w.BOOL
        k.GlobalSize.argtypes, k.GlobalSize.restype = [w.HGLOBAL], ctypes.c_size_t
        k.OpenProcess.argtypes, k.OpenProcess.restype = [w.DWORD, w.BOOL, w.DWORD], w.HANDLE
        k.QueryFullProcessImageNameW.argtypes = [w.HANDLE, w.DWORD, w.LPWSTR, ctypes.POINTER(w.DWORD)]
        k.QueryFullProcessImageNameW.restype = w.BOOL
        k.CloseHandle.argtypes, k.CloseHandle.restype = [w.HANDLE], w.BOOL
        # своя копия («Сравнить»): запомнить и вернуть буфер, нажать клавиши копии, где курсор
        u.EnumClipboardFormats.argtypes, u.EnumClipboardFormats.restype = [w.UINT], w.UINT
        u.EmptyClipboard.restype = w.BOOL
        u.SetClipboardData.argtypes, u.SetClipboardData.restype = [w.UINT, w.HANDLE], w.HANDLE
        u.GetCursorPos.argtypes, u.GetCursorPos.restype = [ctypes.POINTER(w.POINT)], w.BOOL
        u.GetAsyncKeyState.argtypes, u.GetAsyncKeyState.restype = [ctypes.c_int], ctypes.c_short
        u.MapVirtualKeyW.argtypes, u.MapVirtualKeyW.restype = [w.UINT, w.UINT], w.UINT
        k.GlobalAlloc.argtypes, k.GlobalAlloc.restype = [w.UINT, ctypes.c_size_t], w.HGLOBAL
        k.GlobalFree.argtypes, k.GlobalFree.restype = [w.HGLOBAL], w.HGLOBAL

    def seq(self):
        """Счётчик смен буфера: число растёт при каждой записи в буфер. Само содержимое не читается."""
        return self.user32.GetClipboardSequenceNumber()

    def _front_exe_dir(self, hwnd):
        """Папка программы, которой принадлежит окно; None — узнать не удалось."""
        w = self._w
        pid = w.DWORD(0)
        self.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return None
        handle = self.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
        if not handle:
            return None
        try:
            size = w.DWORD(1024)
            path = ctypes.create_unicode_buffer(1024)
            if not self.kernel32.QueryFullProcessImageNameW(handle, 0, path, ctypes.byref(size)):
                return None
            return os.path.normcase(os.path.dirname(os.path.abspath(path.value)))
        finally:
            self.kernel32.CloseHandle(handle)

    def game_in_front(self):
        """Активно ли сейчас окно игры: его программа запущена из папки игры. Если папку программы
        узнать не удалось (или папка игры не задана), окно узнаётся по точному заголовку. Ответ для одного и того
        же окна помнится секунду: клавиши в игре (WinKeys) спрашивают об этом много раз в секунду."""
        hwnd = self.user32.GetForegroundWindow()
        if not hwnd:
            return False
        now = time.monotonic()
        last = getattr(self, '_front', None)
        if last and last[0] == hwnd and now - last[2] < 1.0:
            return last[1]
        exe_dir = self._front_exe_dir(hwnd) if self.game_dir else None
        if exe_dir is not None:
            yes = exe_dir == self.game_dir
        else:
            title = ctypes.create_unicode_buffer(256)
            self.user32.GetWindowTextW(hwnd, title, 256)
            yes = title.value in self.titles
        self._front = (hwnd, yes, now)
        return yes

    def text(self):
        """Текст из буфера, если сейчас активно окно игры. Иначе None — и буфер не открывается вовсе."""
        if not self.game_in_front():
            return None
        for _ in range(4):
            if self.user32.OpenClipboard(None):
                break
            time.sleep(0.03)        # буфер на миг занят другой программой
        else:
            return None
        try:
            if not self.user32.IsClipboardFormatAvailable(CF_UNICODETEXT):
                return None
            handle = self.user32.GetClipboardData(CF_UNICODETEXT)
            if not handle:
                return None
            size = self.kernel32.GlobalSize(handle)
            if not size or size > MAX_BYTES:
                return None
            ptr = self.kernel32.GlobalLock(handle)
            if not ptr:
                return None
            try:
                return ctypes.wstring_at(ptr, size // 2).split('\0', 1)[0]
            finally:
                self.kernel32.GlobalUnlock(handle)
        finally:
            self.user32.CloseClipboard()

    def cursor(self):
        """Где сейчас курсор мыши на экране: (x, y) в точках экрана; None — узнать не удалось. По нему окно поверх игры
        встаёт рядом с предметом, который скопировали."""
        p = self._w.POINT()
        return (p.x, p.y) if self.user32.GetCursorPos(ctypes.byref(p)) else None

    def _open(self):
        for _ in range(4):
            if self.user32.OpenClipboard(None):
                return True
            time.sleep(0.03)        # буфер на миг занят другой программой
        return False

    def snapshot(self):
        """Запомнить буфер, чтобы вернуть его после своей копии: [(формат, байты)]. Содержимое не разбирается — байты
        кладутся обратно как были (restore). None — буфер не открылся или в нём слишком много: тогда не возвращаем."""
        if not self._open():
            return None
        try:
            snap, total, fmt = [], 0, 0
            while True:
                fmt = self.user32.EnumClipboardFormats(fmt)
                if not fmt:
                    break
                if fmt in SNAP_SKIP or 0x300 <= fmt <= 0x3FF:
                    continue
                handle = self.user32.GetClipboardData(fmt)
                if not handle:
                    continue
                size = self.kernel32.GlobalSize(handle)
                if not size:
                    continue
                total += size
                if total > SNAP_BYTES:
                    return None
                ptr = self.kernel32.GlobalLock(handle)
                if not ptr:
                    continue
                try:
                    snap.append((fmt, ctypes.string_at(ptr, size)))
                finally:
                    self.kernel32.GlobalUnlock(handle)
            return snap
        finally:
            self.user32.CloseClipboard()

    def restore(self, snap):
        """Вернуть в буфер запомненное (snapshot). Пустой список — буфер был пуст: очищаем. Возвращает, удалось ли."""
        if snap is None or not self._open():
            return False
        try:
            self.user32.EmptyClipboard()
            for fmt, data in snap:
                handle = self.kernel32.GlobalAlloc(0x0002, len(data))          # GMEM_MOVEABLE
                if not handle:
                    continue
                ptr = self.kernel32.GlobalLock(handle)
                if not ptr:
                    self.kernel32.GlobalFree(handle)
                    continue
                ctypes.memmove(ptr, data, len(data))
                self.kernel32.GlobalUnlock(handle)
                if not self.user32.SetClipboardData(fmt, handle):
                    self.kernel32.GlobalFree(handle)                             # буфер блок не взял — он остался наш
            return True
        finally:
            self.user32.CloseClipboard()

    def send_copy(self, mod=VK_MENU):
        """Нажать в игре копию предмета с подробными свойствами: Ctrl + mod + C (mod — клавиша «показывать подробное
        описание» из настроек игры, обычно Alt). Клавиша, которую игрок и так держит (Alt — он смотрит тиры), не
        нажимается и не отпускается за него. Зовётся только из Copier — по ручному нажатию клавиши «Сравнить»."""
        w = self._w

        class MOUSEINPUT(ctypes.Structure):       # самая большая часть объединения INPUT: по ней его размер
            _fields_ = [('dx', w.LONG), ('dy', w.LONG), ('mouseData', w.DWORD), ('dwFlags', w.DWORD),
                        ('time', w.DWORD), ('dwExtraInfo', ctypes.c_size_t)]

        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [('wVk', w.WORD), ('wScan', w.WORD), ('dwFlags', w.DWORD), ('time', w.DWORD),
                        ('dwExtraInfo', ctypes.c_size_t)]

        class _U(ctypes.Union):
            _fields_ = [('mi', MOUSEINPUT), ('ki', KEYBDINPUT)]

        class INPUT(ctypes.Structure):
            _fields_ = [('type', w.DWORD), ('u', _U)]

        user32 = self.user32
        user32.SendInput.argtypes = [w.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
        user32.SendInput.restype = w.UINT

        def keys(pairs):
            arr = (INPUT * len(pairs))()
            for n, (vk, up) in enumerate(pairs):
                arr[n].type = 1                                                  # INPUT_KEYBOARD
                arr[n].u.ki = KEYBDINPUT(vk, user32.MapVirtualKeyW(vk, 0), 0x0002 if up else 0, 0, 0)
            return user32.SendInput(len(pairs), arr, ctypes.sizeof(INPUT)) == len(pairs)

        mods = [VK_CONTROL] + ([mod] if mod and mod not in (VK_CONTROL, VK_C) else [])
        mine = [vk for vk in mods if not user32.GetAsyncKeyState(vk) & 0x8000]
        ok = keys([(vk, False) for vk in mine] + [(VK_C, False)])
        time.sleep(0.015)           # игре нужно увидеть клавиши нажатыми: мгновенное отпускание она пропускает
        return keys([(VK_C, True)] + [(vk, True) for vk in reversed(mine)]) and ok


class FileClipboard:
    """Вместо буфера — файл: для пробных запусков и проверок. Настоящий буфер при этом не трогается."""

    def __init__(self, path):
        self.path = Path(path)

    def seq(self):
        try:
            st = self.path.stat()
            return (st.st_mtime_ns, st.st_size)
        except OSError:
            return None

    def text(self):
        try:
            return self.path.read_text(encoding='utf-8-sig')
        except (OSError, UnicodeError):
            return None


MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312
PM_REMOVE = 0x0001

# Клавиши страницы в игре — одиночные функциональные клавиши: Ctrl+Alt+V оказалось неудобным («ctrl+alt+v это сложно» —
# их слова после 12 часов игры). Игра по умолчанию держит из них только F1 (счётчик производительности) и F8 (снимок
# экрана) — так в её файле настроек версии 0.5.5 (разделы ACTION_KEYS и WASD_ACTION_KEYS, оба режима управления); F12
# Windows держит за отладчиком, F5 по умолчанию занимают программы торговли (/hideout). Программа берёт первые две
# клавиши из KEY_ORDER, которые игрок в игре ни к чему не привязал: первая — «Надеть», вторая — «Закрыть».
# Функциональные клавиши в чат не печатают — пока клавиша за программой, игрок ничего не теряет.
# F4 программа не берёт никогда: игрок то и дело держит Alt (подробное описание предмета, подсветка), а Alt+F4
# закрывает игру — клавиша программы рядом с этим сочетанием стоила бы героя.
VK_F1 = 0x70
KEY_ORDER = (2, 3, 7, 6, 9, 10, 11)          # F2, F3, F7, F6, F9, F10, F11
# Номера клавиш программы в системе (RegisterHotKey): «Сравнить / Надеть», «Закрыть» и, с окном поверх игры,
# «Программа ↔ игра» (окно программы вперёд и обратно). «Сравнить» и «Надеть» — ОДНА клавиша: по предмету под
# курсором — сравнить (своя копия предмета, Copier), по тому же предмету ещё раз — «Надеть» (server.App.hotkey_item).
# Отдельная «Сравнить» на F6 прожила день: их слова 2026-11-25 — «между ней и F2 и F3 неудобно перемещаться…
# тянуться далеко и руку придётся оторвать от клавиатуры». Свободных клавиш ближе нет: клавиша слева от 1 в игре
# занята («Направить приспешников»), буквы и цифры печатают в чат, F1 держит игра, F4 опасна, F5 — программы торговли.
# Клавиша «Список» (свернуть / раскрыть список шага, F6) прожила одну сборку: это настройка, а не действие в игре —
# их слова 2026-11-25: «сделать настройки программы в отдельную кнопку, куда вынести и убрать F6… по идее это
# настройки». Выбор — в окне «Настройки» страницы.
KEY_IDS = {'wear': 0x5E01, 'close': 0x5E02, 'app': 0x5E04}
BASE_KEYS = ('wear', 'close')
ALL_KEYS = ('wear', 'close', 'app')
# Клавиша сравнения слушается и с зажатым Alt: игрок держит его, чтобы видеть тиры предмета, и тут же сравнивает. В
# системе это вторая клавиша (Alt + та же) со своим номером; не взялась (её держит другая программа) — работает без Alt.
ALT_TOO = ('wear',)
ALT_ID = 0x100
MOD_ALT = 0x0001
GAME_KEY_SECTIONS = ('ACTION_KEYS', 'WASD_ACTION_KEYS')


def key_name(vk):
    """Имя клавиши для страницы: 0x71 -> 'F2'; не функциональная — None."""
    return 'F%d' % (vk - VK_F1 + 1) if isinstance(vk, int) and VK_F1 <= vk < VK_F1 + 12 else None


def game_keys(text):
    """Клавиши, которые игра держит за своими действиями, — по тексту её файла настроек: строки «действие=код» или
    «действие=код модификаторы» в разделах привязок обоих режимов управления. Привязка с модификатором (Ctrl+Q — «81 2»)
    одиночной клавише не мешает и не считается. Возвращает множество кодов клавиш Windows."""
    taken, section = set(), None
    for line in (text or '').splitlines():
        s = line.strip()
        if s.startswith('[') and s.endswith(']'):
            section = s[1:-1].strip()
            continue
        if section not in GAME_KEY_SECTIONS or '=' not in s:
            continue
        parts = s.split('=', 1)[1].split()
        try:
            vk = int(parts[0]) if parts else 0
            mods = int(parts[1]) if len(parts) > 1 else 0
        except ValueError:
            continue
        if vk and not mods:
            taken.add(vk)
    return taken


def pick_keys(taken=(), names=BASE_KEYS):
    """Клавиши программы: {'wear': код, 'close': код} — первые из KEY_ORDER, которых нет среди taken (клавиш игры), по
    одной на каждое имя из names (по умолчанию — «Надеть» и «Закрыть»; ALL_KEYS — ещё «Программа ↔ игра»)."""
    free = [VK_F1 + n - 1 for n in KEY_ORDER if VK_F1 + n - 1 not in taken]
    return dict(zip(names, free))


def game_key(text, action):
    """Клавиша, которую игра держит за действием action (строка «действие=код» в разделах привязок её настроек), без
    модификаторов; None — действие не привязано или привязано с модификатором. Так программа узнаёт клавишу
    «показывать подробное описание предмета» (обычно Alt): с ней игра копирует предмет вместе с тирами."""
    section = None
    for line in (text or '').splitlines():
        s = line.strip()
        if s.startswith('[') and s.endswith(']'):
            section = s[1:-1].strip()
            continue
        if section not in GAME_KEY_SECTIONS or not s.startswith(action + '='):
            continue
        parts = s.split('=', 1)[1].split()
        try:
            if len(parts) == 1 and int(parts[0]):
                return int(parts[0])
        except ValueError:
            pass
    return None


class WinKeys:
    """Клавиши страницы в игре: «Надеть» (то же, что кнопка в сравнении) и «Закрыть» (убрать верхнее окно страницы).

    Клавиши регистрируются в системе (RegisterHotKey), только пока впереди окно игры, и снимаются, как только активно
    другое окно: в браузере и других программах они работают как обычно. Пока клавиша за программой, игра её не
    получает — поэтому берутся клавиши, которые игра ни к чему не привязала (pick_keys). В игру программа ничего не
    посылает, клавиш не нажимает, с экрана и из буфера по этим клавишам ничего не читает: они лишь говорят странице
    «надеть» и «закрыть» (правила GGG для программ рядом с игрой это допускают). Окно игры узнаётся так же, как для
    буфера обмена (front — WinClipboard.game_in_front).

    keys — функция без аргументов -> {'wear': код, 'close': код}: какие клавиши держать сейчас (по настройкам игры —
    игрок может переназначить клавиши в игре, тогда программа перейдёт на другие); press — {'wear': f, 'close': f}:
    программа держит только те клавиши, для которых здесь есть действие.
    fronts — {клавиша: функция}: у этой клавиши своё условие «когда слушать» вместо «впереди окно игры» — «Программа ↔
    игра» слушается и когда впереди само окно программы (иначе из него не вернуться в игру той же клавишей).
    state — по клавише: 'idle' — окно игры не впереди, клавиша свободна; 'on' — клавиша за программой; 'busy' — её
    держит другая программа (тогда — только кнопкой на странице; повторная попытка — при следующем переходе в игру)."""

    def __init__(self, front, keys, press, fronts=None):
        if sys.platform != 'win32':
            raise OSError(tr('клавиша в игре слушается только в Windows'))
        from ctypes import wintypes as w
        self.front, self.keys, self.press = front, keys, press
        self.fronts = dict(fronts or {})
        self.names = [name for name in KEY_IDS if name in press]
        self.state = {name: 'idle' for name in self.names}
        self.held = {}        # клавиша программы -> код, который сейчас за ней в системе
        self.busy = {}        # клавиша программы -> код, который держит другая программа
        self._msg_type = w.MSG
        u = self.user32 = ctypes.WinDLL('user32', use_last_error=True)
        u.RegisterHotKey.argtypes, u.RegisterHotKey.restype = [w.HWND, ctypes.c_int, w.UINT, w.UINT], w.BOOL
        u.UnregisterHotKey.argtypes, u.UnregisterHotKey.restype = [w.HWND, ctypes.c_int], w.BOOL
        u.PeekMessageW.argtypes = [ctypes.POINTER(w.MSG), w.HWND, w.UINT, w.UINT, w.UINT]
        u.PeekMessageW.restype = w.BOOL

    def _listens(self, name, game):
        """Слушается ли сейчас клавиша name: впереди окно игры — или выполнено её собственное условие (fronts)."""
        return bool(self.fronts[name]()) if name in self.fronts else game

    def step(self):
        """Один шаг слежения (в потоке, который регистрирует клавиши: сообщение о нажатии приходит в его очередь)."""
        game = bool(self.front())
        want = self.keys() or {}
        for name in self.names:
            kid, vk, on = KEY_IDS[name], want.get(name), self._listens(name, game)
            if name in self.held and (not on or self.held[name] != vk):
                self.user32.UnregisterHotKey(None, kid)       # игра ушла назад или клавишу пора сменить
                if name in ALT_TOO:
                    self.user32.UnregisterHotKey(None, kid + ALT_ID)
                del self.held[name]
            if not on or vk is None:
                self.state[name] = 'idle'
                self.busy.pop(name, None)
                continue
            if name in self.held or self.busy.get(name) == vk:
                continue
            if self.user32.RegisterHotKey(None, kid, MOD_NOREPEAT, vk):
                self.held[name], self.state[name] = vk, 'on'
                self.busy.pop(name, None)
                if name in ALT_TOO:
                    self.user32.RegisterHotKey(None, kid + ALT_ID, MOD_NOREPEAT | MOD_ALT, vk)
            else:
                self.busy[name], self.state[name] = vk, 'busy'
        msg = self._msg_type()
        while self.user32.PeekMessageW(ctypes.byref(msg), None, WM_HOTKEY, WM_HOTKEY, PM_REMOVE):
            name = next((n for n in self.names if msg.wParam in (KEY_IDS[n], KEY_IDS[n] + ALT_ID)), None)
            if name in self.held and self._listens(name, bool(self.front())):
                self.press[name]()

    def run(self, pause=0.05):
        while True:
            try:
                self.step()
            except Exception as e:  # слежение не должно умирать из-за одной ошибки
                print(tr('Ошибка клавиши в игре: %r') % e, flush=True)
            time.sleep(pause)


class FileKeys:
    """Вместо клавиш в игре — файл: каждая его смена — одно нажатие. В файле слово close — нажата «Закрыть», app —
    «Программа ↔ игра» (если для неё задано действие), иначе — «Надеть». Для пробных запусков и проверок."""

    def __init__(self, path, press):
        self.path, self.press = Path(path), press
        self.state = {name: 'on' for name in KEY_IDS if name in BASE_KEYS or name in press}
        self.last = self._seq()

    def _seq(self):
        try:
            st = self.path.stat()
            return (st.st_mtime_ns, st.st_size)
        except OSError:
            return None

    def poll(self):
        """Одна проверка: файл сменился — одно нажатие. Клавишу называет первое слово файла (после него пробы пишут
        время, чтобы файл менялся: «close 1795.2»); слова нет или оно не клавиша — «Надеть»."""
        now = self._seq()
        if now == self.last:
            return None
        self.last = now
        try:
            word = (self.path.read_text(encoding='utf-8-sig').split() or [''])[0].lower()
        except (OSError, UnicodeError):
            word = ''
        name = word if word in self.press and word in KEY_IDS else 'wear'
        self.press[name]()
        return name

    def run(self, pause=0.1):
        while True:
            time.sleep(pause)
            try:
                self.poll()
            except Exception as e:
                print(tr('Ошибка клавиши в игре: %r') % e, flush=True)


class Watcher:
    """Следит за сменой буфера и отдаёт дальше только текст вещи."""

    def __init__(self, source, on_item):
        self.source = source
        self.on_item = on_item
        self.last = source.seq()     # что лежит в буфере сейчас, не читаем: ждём следующей смены
        self.lock = threading.Lock()  # своя копия (Copier) меняет буфер сама: пока она идёт, слежение ждёт

    def poll(self):
        """Одна проверка. Возвращает True, если в буфере оказалась вещь и она отдана дальше."""
        with self.lock:
            now = self.source.seq()
            if now == self.last:
                return False
            self.last = now
            text = self.source.text()
        if not itemcopy.is_item(text):
            return False             # не вещь (или буфер не наш): ничего не храним
        self.on_item(text)
        return True

    def run(self, pause=0.2):
        while True:
            time.sleep(pause)
            try:
                self.poll()
            except Exception as e:  # слежение не должно умирать из-за одной ошибки
                print(tr('Ошибка чтения буфера обмена: %r') % e, flush=True)


class Copier:
    """Своя копия предмета под курсором — вместо Ctrl+Alt+C рукой: одна копия на одно нажатие клавиши игроком.

    По нажатию: запомнить буфер, нажать в игре копию с подробными свойствами (source.send_copy), дождаться, пока игра
    положит текст в буфер, прочитать его один раз, вернуть в буфер прежнее. Под курсором не предмет — игра ничего не
    кладёт, буфер остаётся как был. Слежение за буфером (watcher) на это время ждёт и своих перемен буфера за новую
    копию не принимает. Окно игры не впереди — ничего не делается: клавиши в чужое окно не нажимаются.

    source — WinClipboard (или его подмена в проверках: seq, text, game_in_front, snapshot, restore, send_copy);
    mod — функция без аргументов -> код клавиши подробного описания из настроек игры; wait — сколько ждать игру."""

    def __init__(self, source, watcher, mod=lambda: VK_MENU, wait=0.4, pause=0.01):
        self.source, self.watcher, self.mod = source, watcher, mod
        self.wait, self.pause = wait, pause

    def grab(self):
        """Одно нажатие. Возвращает текст предмета под курсором; None — под курсором не предмет (или игра не впереди)."""
        src = self.source
        if not src.game_in_front():
            return None
        text = None
        with self.watcher.lock:
            snap = src.snapshot()
            before = src.seq()
            src.send_copy(self.mod())
            end = time.monotonic() + self.wait
            while time.monotonic() < end:
                time.sleep(self.pause)
                if src.seq() != before:
                    text = src.text()
                    break
            if src.seq() != before and snap is not None:
                src.restore(snap)
            self.watcher.last = src.seq()      # всё, что буфер пережил за это нажатие, — наше: слежение этого не читает
        return text if itemcopy.is_item(text) else None
