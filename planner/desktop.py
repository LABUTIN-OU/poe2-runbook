# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Sergei Labutin
# Additional terms under GPL-3.0 section 7: see NOTICE.md
"""Окно программы для игроков: страницы — в своём окне, а не во вкладке браузера (PoE2Runbook.exe).

Что происходит при запуске:
  * на компьютере работает одна программа: запущена уже — её окно выходит вперёд, вторая не стартует;
  * файлы игрока — в папке данных %APPDATA%\\PoE2 Runbook: планы, герои, архив фильтров, резервные копии, файлы
    планов для обмена (export), настройки (где игра, размер окна) и журнал запуска program.log (журналы пяти
    прежних запусков — program.1.log … program.5.log). Папка самой программы только читается: новая версия ставится
    поверх и ничего из этого не трогает;
  * при первом запуске в пустую библиотеку кладутся планы, пришедшие с программой;
  * адрес страниц игрок не видит; порт — постоянный (первый свободный из 4727…4736): настройки страниц
    (язык, свёрнутые блоки) окно хранит по адресу, и они не теряются от запуска к запуску;
  * окно — движок Microsoft Edge WebView2 (он есть в Windows 11, в Windows 10 его ставит Центр обновления); нет
    его — так и сказано, с предложением открыть страницу загрузки Microsoft;
  * поверх окна игры стоят два маленьких окна программы — список шага и ответ на копию предмета (overlay.py): видны,
    только пока игра активна, фокус у неё не забирают; выключаются кнопкой «поверх игры» на странице «Игра»;
  * в заголовке окна — версия программы: «версия игры, под которую она сделана» и номер сборки (appversion.py);
  * о новой версии программа узнаёт сама — с официального адреса, при запуске и раз в 6 часов (update.py; настройка
    «Проверять обновления»); «Обновить» скачивает установщик, сверяет его с подписанным файлом, запускает и закрывает
    программу — установщик дожидается её выхода (мьютекс update.APP_MUTEX) и открывает уже новую;
  * закрыли окно — программа закончила работу.

Для проверок: --data <папка> (вместо %APPDATA%\\PoE2 Runbook), --selftest (окно не показывается: страница
загрузилась и сказала статус — код выхода 0); остальные параметры уходят серверу как есть (--log, --clip-file…).
"""
import argparse
import ctypes
import hashlib
import os
import re
import shutil
import socket
import sys
import threading
import time
import traceback
import webbrowser
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import appsettings  # noqa: E402
import appversion  # noqa: E402
import gamepaths  # noqa: E402
import i18n  # noqa: E402
import logtext  # noqa: E402
import planlib  # noqa: E402
import update  # noqa: E402
from i18n import tr  # noqa: E402

APP = 'PoE2 Runbook'
# Заголовок окна программы — «PoE2 Runbook 0.5.5.4» (версия — appversion.py); у прежних сборок — без версии. Окна
# поверх игры называются иначе («PoE2 Runbook · list») и под это правило не подходят.
MAIN_TITLE = re.compile(r'%s( \d[\d.]*)?' % re.escape(APP))
PORTS = range(4727, 4737)
WEBVIEW2 = '{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}'          # номер движка WebView2 у Центра обновления Microsoft
WEBVIEW2_PAGE = 'https://developer.microsoft.com/microsoft-edge/webview2/'
# Пока сервер читает лог (при большом логе — несколько секунд), окно показывает заставку
SPLASH = ('<html><body style="margin:0;background:#15120e;color:#c9b98f;font:600 22px Segoe UI,sans-serif;'
          'display:flex;align-items:center;justify-content:center;height:100vh">' + APP + '</body></html>')
PANE_BLANK = '<html><body style="margin:0;background:#111316"></body></html>'      # окно поверх игры до своей страницы
# Где лежат данные, пришедшие с программой (catalog, knowledge, plans): у собранной программы — её папка
# _internal (sys._MEIPASS), у программы из исходников — папка проекта.
BUNDLE = Path(getattr(sys, '_MEIPASS', HERE.parent))


def data_dir(given=None):
    """Папка данных игрока: --data, иначе %APPDATA%\\PoE2 Runbook (туда, где Windows держит AppData)."""
    if given:
        return Path(given)
    base = gamepaths.known_folder(26) or (Path(os.environ['APPDATA']) if os.environ.get('APPDATA') else Path.home())
    return base / APP


def catalog_dir():
    """Каталог данных игры: у собранной программы — её копия, у исходников — catalog/data проекта."""
    return BUNDLE / 'catalog' / 'data'


def program_version():
    """Версия программы — «версия игры.номер сборки» (appversion.py): версия игры — из каталога данных в программе."""
    try:
        current = (catalog_dir() / 'current.txt').read_text(encoding='utf-8').strip()
    except OSError:
        current = None
    return appversion.program(current) or '%s.%d' % (appversion.GAME, appversion.BUILD)


def seed_plans(data):
    """Библиотека пуста (первый запуск) — кладём в неё планы, пришедшие с программой."""
    plans = data / 'plans'
    if planlib.scan(plans):
        return []
    added = []
    src = BUNDLE / 'plans'
    for d in sorted(src.iterdir()) if src.is_dir() else []:
        if d.is_dir() and (d / planlib.MANIFEST).is_file() and not (plans / d.name).exists():
            shutil.copytree(d, plans / d.name)
            added.append(d.name)
    return added


def free_port():
    """Первый свободный порт из PORTS; все заняты — любой свободный (настройки страниц тогда начнутся заново)."""
    for port in list(PORTS) + [0]:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(('127.0.0.1', port))
            return s.getsockname()[1]
        except OSError:
            continue
        finally:
            s.close()
    return 0


# --- одна программа на компьютере ------------------------------------------------------------------------

_MUTEX = []


def first_instance(data):
    """True — эта программа первая (для этой папки данных); False — такая уже работает."""
    if sys.platform != 'win32':
        return True
    from ctypes import wintypes as w
    k = ctypes.WinDLL('kernel32', use_last_error=True)
    k.CreateMutexW.argtypes, k.CreateMutexW.restype = [ctypes.c_void_p, w.BOOL, w.LPCWSTR], w.HANDLE
    name = 'Local\\PoE2Runbook-' + hashlib.sha1(os.path.normcase(str(data)).encode('utf-8')).hexdigest()[:12]
    handle = k.CreateMutexW(None, False, name)
    if not handle:
        return True
    _MUTEX.append(handle)               # держим до конца работы программы
    return ctypes.get_last_error() != 183     # ERROR_ALREADY_EXISTS


def bring_front():
    """Окно уже работающей программы — вперёд (и из свёрнутого)."""
    if sys.platform != 'win32':
        return
    from ctypes import wintypes as w
    u = ctypes.WinDLL('user32', use_last_error=True)
    u.FindWindowExW.argtypes, u.FindWindowExW.restype = [w.HWND, w.HWND, w.LPCWSTR, w.LPCWSTR], w.HWND
    u.ShowWindow.argtypes, u.SetForegroundWindow.argtypes = [w.HWND, ctypes.c_int], [w.HWND]
    u.IsIconic.argtypes = [w.HWND]
    u.GetWindowTextW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
    wins = gamepaths.windows()
    me = os.path.normcase(os.path.abspath(sys.executable))
    hwnd, title = None, ctypes.create_unicode_buffer(128)
    for _ in range(4096):                      # все окна верхнего уровня: в заголовке окна программы — её версия
        hwnd = u.FindWindowExW(None, hwnd, None, None)
        if not hwnd:
            return
        u.GetWindowTextW(hwnd, title, 128)
        if not MAIN_TITLE.fullmatch(title.value):
            continue
        exe = wins.exe(hwnd) if wins else None
        if exe and os.path.normcase(os.path.abspath(exe)) == me:      # не окно проводника с тем же названием
            if u.IsIconic(hwnd):
                u.ShowWindow(hwnd, 9)          # SW_RESTORE
            u.SetForegroundWindow(hwnd)
            return


# --- язык сообщений и окна Windows -------------------------------------------------------------------------

WIN_LANGS = {0x19: 'ru', 0x09: 'en', 0x07: 'de', 0x0C: 'fr', 0x0A: 'es', 0x16: 'pt', 0x11: 'ja', 0x12: 'ko', 0x1E: 'th'}


def message_lang():
    """Язык сообщений окна: язык клиента игры из её настроек, иначе язык Windows, иначе английский."""
    try:
        with open(gamepaths.config_in(gamepaths.game_docs()), encoding='utf-8-sig', errors='replace') as f:
            for line in f:
                if line.startswith('language='):
                    code = logtext.CONFIG_LANGS.get(line.split('=', 1)[1].strip().lower())
                    if code:
                        return i18n.pick(code)
    except OSError:
        pass
    try:
        code = WIN_LANGS.get(ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF)
    except (OSError, AttributeError):
        code = None
    return i18n.pick(code or 'en')


def ask(text, yes_no=False):
    """Окно сообщения Windows; True — нажали «Да»."""
    flags = 0x04 | 0x30 if yes_no else 0x10          # MB_YESNO + MB_ICONWARNING / MB_ICONERROR
    try:
        return ctypes.windll.user32.MessageBoxW(None, str(text), APP, flags) == 6
    except (OSError, AttributeError):
        return False


def webview2():
    """Версия движка WebView2 на этом компьютере (так её узнаёт сама Microsoft); None — его нет."""
    reg = gamepaths.registry()
    if not reg:
        return None
    for root, key in (('HKLM', 'SOFTWARE\\WOW6432Node\\Microsoft\\EdgeUpdate\\Clients\\' + WEBVIEW2),
                      ('HKLM', 'SOFTWARE\\Microsoft\\EdgeUpdate\\Clients\\' + WEBVIEW2),
                      ('HKCU', 'Software\\Microsoft\\EdgeUpdate\\Clients\\' + WEBVIEW2)):
        v = reg.value(root, key, 'pv')
        if v and v != '0.0.0.0':
            return v
    return None


def on_screen(geo):
    """Место окна из настроек — только если оно на одном из нынешних мониторов (монитор могли отключить)."""
    try:
        m = ctypes.windll.user32.GetSystemMetrics
        left, top, width, height = m(76), m(77), m(78), m(79)
    except (OSError, AttributeError):
        return False
    x, y = geo.get('x'), geo.get('y')
    return isinstance(x, int) and isinstance(y, int) and left <= x < left + width - 100 and top <= y < top + height - 100


# --- журнал программы ---------------------------------------------------------------------------------------

LOG_NAME = 'program.log'
LOGS_KEPT = 5               # журналов прежних запусков рядом: program.1.log (предыдущий) … program.5.log


class Stamped:
    """Журнал программы: в начале каждой строки — день и время. По ним строку журнала сопоставляют с тем, что игрок
    видел на экране (снимок экрана, «около трёх часов дня»). Пустые строки остаются пустыми."""

    def __init__(self, file):
        self.file, self.fresh, self.lock = file, True, threading.Lock()
        self.encoding = file.encoding

    def write(self, text):
        if not text:
            return 0
        with self.lock:
            out = []
            for i, part in enumerate(text.split('\n')):
                if i:
                    out.append('\n')
                    self.fresh = True
                if part:
                    if self.fresh:
                        out.append(time.strftime('%m-%d %H:%M:%S  '))
                        self.fresh = False
                    out.append(part)
            self.file.write(''.join(out))
        return len(text)

    def flush(self):
        self.file.flush()

    def fileno(self):
        return self.file.fileno()

    def isatty(self):
        return False


def open_log(data):
    """Журнал этого запуска — <папка данных>/program.log, новый на каждый запуск. Журналы прежних запусков не
    стираются: прежний program.log становится program.1.log, тот — program.2.log, и так до LOGS_KEPT; самый старый
    уходит. Файл, который не переименовался (открыт в другой программе), остаётся как есть."""
    data = Path(data)
    for n in range(LOGS_KEPT, 0, -1):
        old = data / ('program.%d.log' % (n - 1)) if n > 1 else data / LOG_NAME
        try:
            if old.is_file():
                os.replace(old, data / ('program.%d.log' % n))
        except OSError:
            pass
    return Stamped(open(data / LOG_NAME, 'w', encoding='utf-8', errors='replace', buffering=1))


def about_check(url):
    """Проверка сборки: окну «О программе» есть что показать — в папке программы лежат LICENSE, NOTICE.md и
    THIRD-PARTY.md, а список сторонних компонентов собран (их кладёт packaging/build.py). Ответ — что не так ('' — всё
    на месте); сказанное попадает в журнал."""
    import json
    import urllib.request
    try:
        with urllib.request.urlopen(url.rstrip('/') + '/api/about', timeout=20) as r:
            got = json.loads(r.read().decode('utf-8'))
    except Exception as e:      # noqa: BLE001 — любой отказ — это провал проверки
        problem = 'no answer: %s' % e
    else:
        import about
        missing = [n for n in about.LEGAL if n not in (got.get('files') or [])]
        count = len(got.get('components') or [])
        problem = ('missing files: %s' % ', '.join(missing)) if missing else '' if count else 'no third-party list'
        print('SELFTEST about: version %s, files %s, components %d' % (got.get('version'), ', '.join(got.get('files') or []),
                                                                       count))
    if problem:
        print('SELFTEST about: %s' % problem)
    return problem


# --- запуск -------------------------------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument('--data')
    ap.add_argument('--selftest', action='store_true')
    own, rest = ap.parse_known_args(argv)
    data = data_dir(own.data)
    data.mkdir(parents=True, exist_ok=True)
    if not first_instance(data):
        bring_front()
        return 0
    # отметка для установщика новой версии: он ждёт, пока её нет (программа закрылась), — packaging/update.iss
    _MUTEX.append(update.hold_app_mutex())

    # Журнал запуска: что нашла программа, что не так. У окна программы нет консоли — пишем в файл. Журналы прежних
    # запусков остаются рядом (open_log): программу закрыли или она упала, запустили заново — что было, читается.
    log = open_log(data)
    sys.stdout = sys.stderr = log
    version = program_version()
    print('%s %s · Python %s · %s' % (APP, version, sys.version.split()[0], time.strftime('%Y-%m-%d %H:%M:%S')))
    print('update key: %s' % update.key_name())     # ключ подписи обновлений в этой сборке (отпечаток) или none
    i18n.CONSOLE[0] = 'en'
    lang = message_lang()

    if sys.platform == 'win32' and not webview2():
        print('WebView2: not found')
        text = tr('Для окна программы нужен движок Microsoft Edge WebView2 — его нет на этом компьютере. Открыть страницу загрузки Microsoft?')
        if not own.selftest and ask(i18n.to(text, lang), yes_no=True):
            webbrowser.open(WEBVIEW2_PAGE)
        return 3

    import webview      # pywebview: окно с движком WebView2
    import server       # noqa: E402 — сервер страниц; его модули рядом

    added = seed_plans(data)
    if added:
        print('plans added: %s' % ', '.join(added))
    port = free_port()
    args = ['--port', str(port), '--plans', str(data / 'plans'), '--runs', str(data / 'runs'),
            '--archive', str(data / 'filters'), '--settings', str(data / 'settings.json'),
            '--catalog', str(catalog_dir()), '--knowledge', str(BUNDLE / 'knowledge')] + rest

    settings = appsettings.load(data / 'settings.json')
    geo = settings.get('window') if isinstance(settings.get('window'), dict) else {}
    size = {'width': geo['w'], 'height': geo['h']} if isinstance(geo.get('w'), int) and isinstance(geo.get('h'), int) \
        and geo['w'] >= 640 and geo['h'] >= 480 else {'width': 1440, 'height': 920}
    place = {'x': geo['x'], 'y': geo['y']} if on_screen(geo) else {}
    win = webview.create_window('%s %s' % (APP, version), html=SPLASH, min_size=(760, 520), background_color='#15120e',
                                hidden=own.selftest, text_select=True, **size, **place)
    dialog = getattr(getattr(webview, 'FileDialog', None), 'FOLDER', None) or getattr(webview, 'FOLDER_DIALOG', 20)
    result = {'code': 0, 'update': False}

    # Окна поверх игры (overlay.py): список шага, ответ на копию и дерево. Создаются скрытыми вместе с окном программы, за краем
    # экрана; свои свойства и место получают от overlay.Overlay (start_overlay), страницы — когда готов сервер (boot).
    panes, over = {}, []
    if sys.platform == 'win32':
        try:
            import overlay
            bridge = overlay.Bridge()
            for part in ('list', 'answer', 'tree'):
                wide, tall = overlay.SIZE[part]
                # text_select=True: запрет выделения текста — правило самой страницы (html.ov body); свой <style>,
                # который pywebview вставил бы для этого, Content-Security-Policy страницы не пускает
                panes[part] = webview.create_window('%s · %s' % (APP, part), html=PANE_BLANK, js_api=bridge, width=wide,
                                                    height=tall, x=-20000, y=-20000, hidden=True, frameless=True,
                                                    easy_drag=False, shadow=False, focus=False, on_top=True,
                                                    resizable=False, min_size=(60, 20), background_color='#111316',
                                                    text_select=True)
        except Exception:
            traceback.print_exc()
            panes = {}

    def main_window():
        try:
            return win.native.Handle.ToInt32()
        except Exception:
            return None

    def start_overlay(app):
        """Окна поверх игры — в работу. До server.serve(): клавишу «Программа ↔ игра» он берёт из app при старте."""
        wins = gamepaths.windows()

        def game_front():
            src = app.clip_source           # тот же ответ «впереди ли игра», что у буфера обмена и клавиш
            return bool(src is not None and hasattr(src, 'game_in_front') and src.game_in_front())
        # герой в игре — по логу: тот же признак, по которому программа останавливает время («вне игры»)
        o = overlay.Overlay(app, game_front, find_game=wins.game_window if wins else None, api=bridge,
                            playing=lambda: bool(app.parser.in_game))
        for part, pane in panes.items():
            o.add(part, pane)
        over.append(o)
        app.overlay = dict(server.overlay_from(settings), can=True)
        app.window_toggle = lambda: o.switch(main_window())
        app.window_front = lambda: o.win.foreground() == main_window()
        threading.Thread(target=o.run, daemon=True).start()

    def after_close():
        """Окно программы закрыли — закрыть и окна поверх игры: пока открыто хоть одно окно, программа не завершается.
        Не завершилась сама за несколько секунд — завершаем: без окна программа работать не должна (вторую не запустить)."""
        for o in over:
            o.stop = True
        for _ in range(3):
            for pane in panes.values():
                try:
                    pane.destroy()
                except Exception:
                    pass
            time.sleep(0.5)
        time.sleep(0 if result['update'] else 3)      # установщик новой версии ждёт выхода программы
        print('closed by watchdog, code %d' % result['code'])
        log.flush()
        os._exit(result['code'])

    def pick_folder():
        """Окно выбора папки игры (кнопка «указать папку игры» на странице)."""
        start = os.environ.get('ProgramFiles(x86)') or ''
        got = win.create_file_dialog(dialog, directory=start)
        return got[0] if got else None

    def remember_window():
        try:
            appsettings.update(data / 'settings.json', window={'w': int(win.width), 'h': int(win.height),
                                                               'x': int(win.x), 'y': int(win.y)})
        except Exception:
            pass

    def quit_for_update():
        """Установщик новой версии запущен: окно запоминает своё место и закрывается, программа завершается —
        установщик ждёт её выхода, ставит новую версию и открывает её. Не завершилась за 10 секунд — завершаем."""
        result['update'] = True
        remember_window()
        threading.Timer(10, lambda: os._exit(0)).start()
        try:
            win.destroy()
        except Exception:
            traceback.print_exc()
            os._exit(0)

    def start_updates(app):
        """Обновление программы (update.py): проверка при запуске и раз в 6 часов (чаще, пока игра новее программы),
        «Обновить» на страницах. Только у собранной программы: из исходников обновлять нечего."""
        made = (app.base_catalog or {}).get('version')
        upd = update.Updater(version, data / 'update', data / 'settings.json', update.embedded_key(),
                             quit=quit_for_update, urgent=lambda: appversion.newer(app.game_tag, made))
        upd.changed = app._bump
        app.updater = upd
        upd.start()

    def boot():
        try:
            ready = server.prepare(args)
            if ready is None:
                raise RuntimeError('port %d is busy' % port)
            app = ready[0]
            app.picker = pick_folder
            if getattr(sys, 'frozen', False) and not own.selftest:
                try:
                    start_updates(app)
                except Exception:
                    traceback.print_exc()       # без проверки обновлений программа работает как раньше
            if panes:
                try:
                    start_overlay(app)
                except Exception:
                    traceback.print_exc()       # без окон поверх игры программа работает как раньше
            threading.Thread(target=server.serve, args=ready, daemon=True).start()
            win.load_url(ready[2])
            if over:
                for part, pane in panes.items():
                    pane.load_url(ready[2] + '?ov=' + part)
        except Exception as e:
            traceback.print_exc()
            result['code'] = 1
            if not own.selftest:
                ask(i18n.to(tr('Программа не запустилась: %s') % e, lang))
            win.destroy()
            return
        if own.selftest:
            # проверка сборки: страница загрузилась, её код отработал и показал строку состояния
            status = None
            for _ in range(240):
                time.sleep(0.5)
                try:
                    status = win.evaluate_js("(function(){var s=document.querySelector('.status');"
                                             "return s?s.textContent:''})()")
                except Exception:
                    status = None
                if status:
                    break
            print('SELFTEST status: %r' % (status,))
            legal = about_check(ready[2]) if getattr(sys, 'frozen', False) else ''
            result['code'] = 0 if status and not legal else 2
            win.destroy()

    if not own.selftest:
        win.events.closing += remember_window
    win.events.closed += after_close
    webview.settings['ALLOW_DOWNLOADS'] = True             # «Скачать файл плана» — в папку «Загрузки»
    webview.settings['OPEN_EXTERNAL_LINKS_IN_BROWSER'] = True
    webview.start(boot, gui='edgechromium', private_mode=False, storage_path=str(data / 'webview'))
    print('closed, code %d' % result['code'])
    log.flush()
    return result['code']


if __name__ == '__main__':
    code = main()
    os._exit(code)          # фоновые потоки сервера не ждём: всё нужное записано по ходу работы
