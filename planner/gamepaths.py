# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Sergei Labutin
# Additional terms under GPL-3.0 section 7: see NOTICE.md
"""Где у игрока стоит игра: папка игры, её лог, настройки игры и фильтры с сайта.

Клиент игры ставят по-разному:
  * через Steam — в любую из библиотек Steam, на любом диске (…\\steamapps\\common\\Path of Exile 2);
  * установщиком с сайта игры — по умолчанию в C:\\Program Files (x86)\\Grinding Gear Games\\Path of Exile 2,
    но папку игрок выбирает сам;
  * в Корее — через Kakao Games.
Лог у всех клиентов лежит в папке игры, в logs: Client.txt (корейский клиент Kakao звал его KakaoClient.txt).
Настройки игры и фильтры с сайта у всех клиентов — в «Документах»: My Games\\Path of Exile 2. «Документы» Windows
переносит в OneDrive и на другой диск, поэтому их папку спрашиваем у самой Windows, а не собираем из имени
пользователя.

Как ищется папка игры (find):
  1. запущенная игра — папка программы её окна: та игра, в которую играют сейчас;
  2. папка, которую программа помнит (нашла раньше или её указал игрок), если в ней есть лог;
  3. известные места: библиотеки Steam, папка клиента с сайта по умолчанию и записи установщиков в Windows
     («Установленные приложения» — туда и Steam, и установщик с сайта пишут папку игры). Если игр нашлось
     несколько (стоят и Steam, и клиент с сайта), берётся та, чей лог писался последним.
Папка без лога игрой не считается: в ней ни разу не запускали игру, читать нечего.
"""
import ctypes
import os
import re
import sys
from pathlib import Path

GAME = 'Path of Exile 2'              # папка игры, название в «Установленных приложениях» и заголовок окна игры
LOGS = ('Client.txt', 'KakaoClient.txt')
CONFIG = 'poe2_production_Config.ini'
STEAM_APP = '2694490'                 # номер игры в Steam
EXE = 'pathofexile'                   # программа игры: PathOfExile.exe, PathOfExileSteam.exe, PathOfExile_KG.exe…

# Записи установщиков: у программ «для всех» — в HKLM (64- и 32-битные), «только для меня» — в HKCU.
UNINSTALL = (('HKCU', r'Software\Microsoft\Windows\CurrentVersion\Uninstall'),
             ('HKLM', r'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall'),
             ('HKLM', r'SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall'))
STEAM_KEYS = (('HKCU', r'Software\Valve\Steam', 'SteamPath'),
              ('HKLM', r'SOFTWARE\WOW6432Node\Valve\Steam', 'InstallPath'),
              ('HKLM', r'SOFTWARE\Valve\Steam', 'InstallPath'))
# Библиотеки в steamapps\libraryfolders.vdf: «"path" "D:\\SteamLibrary"»; в старом виде файла — «"1" "D:\\…"»
RE_LIBRARY = re.compile(r'^\s*"(?:path|\d+)"\s+"([^"]+)"', re.M)
RE_INSTALLDIR = re.compile(r'"installdir"\s+"([^"]+)"')


class Registry:
    """Реестр Windows — только чтение. В проверках вместо него подставляется словарь с теми же двумя вопросами."""

    def __init__(self):
        import winreg
        self._w = winreg
        self._roots = {'HKCU': winreg.HKEY_CURRENT_USER, 'HKLM': winreg.HKEY_LOCAL_MACHINE}

    def value(self, root, key, name):
        """Строковое значение name ключа key; None — нет ключа, значения или оно не строка."""
        try:
            with self._w.OpenKey(self._roots[root], key) as k:
                v, _ = self._w.QueryValueEx(k, name)
        except OSError:
            return None
        return v if isinstance(v, str) else None

    def subkeys(self, root, key):
        """Имена подразделов ключа key; нет ключа — пусто."""
        out = []
        try:
            with self._w.OpenKey(self._roots[root], key) as k:
                while True:
                    try:
                        out.append(self._w.EnumKey(k, len(out)))
                    except OSError:
                        return out
        except OSError:
            return out


def registry():
    """Реестр этого компьютера; не Windows — None (тогда ищем только в папках по умолчанию)."""
    if sys.platform != 'win32':
        return None
    try:
        return Registry()
    except ImportError:
        return None


def mtime(path):
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


def log_in(game_dir):
    """Лог игры в её папке; None — лога нет (игру отсюда ни разу не запускали) или папка не та."""
    if not game_dir:
        return None
    for name in LOGS:
        path = Path(game_dir) / 'logs' / name
        if path.is_file():
            return path
    return None


def game_at(path):
    """Папка игры по тому, что указал игрок: саму папку игры, её папку logs, файл лога или папку, в которой
    лежит папка игры (Grinding Gear Games, steamapps\\common). None — игры там нет."""
    if not path:
        return None
    p = Path(path)
    for cand in (p, p.parent, p.parent.parent, p / GAME):
        if log_in(cand):
            return cand
    return None


def steam_libraries(reg):
    """Папки библиотек Steam: сам Steam и все библиотеки из его steamapps\\libraryfolders.vdf."""
    roots, libs = [], []
    for root, key, name in STEAM_KEYS:
        v = reg.value(root, key, name) if reg else None
        if v:
            roots.append(Path(v.replace('/', os.sep)))
    for steam in roots:
        libs.append(steam)
        try:
            text = (steam / 'steamapps' / 'libraryfolders.vdf').read_text(encoding='utf-8', errors='replace')
        except OSError:
            continue
        for m in RE_LIBRARY.finditer(text):
            value = m.group(1).replace('\\\\', '\\')
            if ':' in value or '\\' in value or '/' in value:      # не путь — число из списка игр библиотеки
                libs.append(Path(value))
    return libs


def steam_dirs(reg):
    """Где игра стоит в библиотеках Steam: папка из её манифеста (appmanifest_2694490.acf), иначе
    steamapps\\common\\Path of Exile 2."""
    out = []
    for lib in steam_libraries(reg):
        name = GAME
        try:
            text = (lib / 'steamapps' / ('appmanifest_%s.acf' % STEAM_APP)).read_text(encoding='utf-8', errors='replace')
            m = RE_INSTALLDIR.search(text)
            if m:
                name = m.group(1)
        except OSError:
            pass
        out.append(lib / 'steamapps' / 'common' / name)
    return out


def installed_dirs(reg):
    """Папки игры из записей установщиков («Установленные приложения»): запись, чьё название начинается с
    «Path of Exile 2». Папка — InstallLocation, а если её не записали — папка значка программы (DisplayIcon)."""
    out = []
    if not reg:
        return out
    for root, key in UNINSTALL:
        for sub in reg.subkeys(root, key):
            path = key + '\\' + sub
            title = (reg.value(root, path, 'DisplayName') or '').strip().lower()
            if not title.startswith(GAME.lower()):
                continue
            where = (reg.value(root, path, 'InstallLocation') or '').strip().strip('"')
            if not where:
                icon = (reg.value(root, path, 'DisplayIcon') or '').strip()
                icon = icon.split(',')[0].strip().strip('"')
                where = str(Path(icon).parent) if icon else ''
            if where:
                out.append(Path(where))
    return out


def default_dirs(env):
    """Папки по умолчанию: установщика с сайта и Steam — в Program Files (и в 32-, и в 64-битной)."""
    bases = []
    for var in ('ProgramFiles(x86)', 'ProgramFiles', 'ProgramW6432'):
        if env.get(var):
            bases.append(Path(env[var]))
    if not bases:                     # переменных окружения нет (запуск без них) — обычное место
        bases.append(Path('C:\\Program Files (x86)'))
    out = []
    for base in bases:
        out.append(base / 'Grinding Gear Games' / GAME)
        out.append(base / 'Steam' / 'steamapps' / 'common' / GAME)
    return out


def candidates(reg=None, env=None):
    """Все места, где игра может стоять, без повторов — по порядку: Steam, установщики, по умолчанию."""
    env = os.environ if env is None else env
    seen, out = set(), []
    for d in steam_dirs(reg) + installed_dirs(reg) + default_dirs(env):
        key = os.path.normcase(os.path.abspath(str(d)))
        if key not in seen:
            seen.add(key)
            out.append(d)
    return out


def find(saved=None, running=None, reg=None, env=None):
    """(папка игры, её лог) — по порядку из описания модуля; игры нет нигде — (None, None)."""
    for d in (running, saved):
        log = log_in(d)
        if log:
            return Path(d), log
    best = None
    for d in candidates(reg, env):
        log = log_in(d)
        if log and (best is None or mtime(log) > mtime(best[1])):
            best = (d, log)
    return best if best else (None, None)


def same(a, b):
    """Одна ли это папка (регистр букв и вид пути не важны)."""
    if not a or not b:
        return False
    return os.path.normcase(os.path.abspath(str(a))) == os.path.normcase(os.path.abspath(str(b)))


# --- запущенная игра ----------------------------------------------------------------------------------

class Windows:
    """Окна Windows: найти окно игры по заголовку и узнать, из какой папки запущена его программа."""

    def __init__(self):
        from ctypes import wintypes as w
        self._w = w
        u = self.user32 = ctypes.WinDLL('user32', use_last_error=True)
        k = self.kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        u.FindWindowExW.argtypes = [w.HWND, w.HWND, w.LPCWSTR, w.LPCWSTR]
        u.FindWindowExW.restype = w.HWND
        u.GetWindowThreadProcessId.argtypes = [w.HWND, ctypes.POINTER(w.DWORD)]
        u.GetWindowThreadProcessId.restype = w.DWORD
        k.OpenProcess.argtypes, k.OpenProcess.restype = [w.DWORD, w.BOOL, w.DWORD], w.HANDLE
        k.QueryFullProcessImageNameW.argtypes = [w.HANDLE, w.DWORD, w.LPWSTR, ctypes.POINTER(w.DWORD)]
        k.QueryFullProcessImageNameW.restype = w.BOOL
        k.CloseHandle.argtypes, k.CloseHandle.restype = [w.HANDLE], w.BOOL

    def exe(self, hwnd):
        """Файл программы окна; None — узнать не удалось."""
        w = self._w
        pid = w.DWORD(0)
        self.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return None
        handle = self.kernel32.OpenProcess(0x1000, False, pid.value)     # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return None
        try:
            size = w.DWORD(1024)
            buf = ctypes.create_unicode_buffer(1024)
            if not self.kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                return None
            return buf.value
        finally:
            self.kernel32.CloseHandle(handle)

    def game(self):
        """Окно запущенной игры и файл её программы: окно с заголовком «Path of Exile 2», чья программа —
        PathOfExile….exe (окно проводника с папкой игры называется так же — его программа другая).
        (None, None) — игра не запущена."""
        hwnd = None
        for _ in range(16):
            hwnd = self.user32.FindWindowExW(None, hwnd, None, GAME)
            if not hwnd:
                break
            exe = self.exe(hwnd)
            if exe and os.path.basename(exe).lower().startswith(EXE):
                return hwnd, exe
        return None, None

    def running_game(self):
        """Папка запущенной игры; None — игра не запущена."""
        exe = self.game()[1]
        return Path(exe).parent if exe else None

    def game_window(self):
        """Окно запущенной игры; None — игра не запущена. Нужно клавише «Программа ↔ игра»: вернуться в игру."""
        return self.game()[0]


def windows():
    """Окна этого компьютера; не Windows — None."""
    if sys.platform != 'win32':
        return None
    try:
        return Windows()
    except (OSError, AttributeError):
        return None


# --- «Документы»: настройки игры и фильтры --------------------------------------------------------------

def known_folder(csidl):
    """Папка Windows по её номеру (5 — «Документы», 26 — AppData\\Roaming) — там, куда её перенесли."""
    if sys.platform == 'win32':
        try:
            buf = ctypes.create_unicode_buffer(1024)
            if ctypes.windll.shell32.SHGetFolderPathW(None, csidl, None, 0, buf) == 0 and buf.value:
                return Path(buf.value)
        except (OSError, AttributeError):
            pass
    return None


def documents():
    """«Документы» пользователя — как их знает Windows (в OneDrive, на другом диске); иначе <профиль>\\Documents."""
    return known_folder(5) or Path.home() / 'Documents'


def game_docs(docs=None):
    """Папка игры в «Документах»: настройки, фильтры с сайта (OnlineFilters)."""
    return Path(docs or documents()) / 'My Games' / GAME


def config_in(folder):
    """Файл настроек игры: poe2_production_Config.ini; у другого издания игры имя другое — тогда самый свежий
    poe2_…Config.ini. Нет ни одного — обычное имя (файл появится, когда игру запустят)."""
    folder = Path(folder)
    std = folder / CONFIG
    if std.is_file():
        return std
    other = sorted(folder.glob('poe2_*Config.ini'), key=mtime, reverse=True)
    return other[0] if other else std
