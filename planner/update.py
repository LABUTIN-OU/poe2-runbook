# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Sergei Labutin
# Additional terms under GPL-3.0 section 7: see NOTICE.md
"""Обновление программы: о новой версии программа узнаёт с официального адреса, ставит её одним нажатием «Обновить».

Договорённость с сайтом и инструментом выпуска (release/publish.py). Менять её нельзя: на неё опираются уже
установленные копии программы.
  * Адрес в программе один — URL ниже, подпись рядом (SIG_URL). Адрес установщика берётся из подписанного файла и
    только https://: место, где лежат установщики, можно сменить, не трогая установленные копии.
  * latest.json: {"format": "poe2-runbook-update", "v": 1, "version": "0.5.5.18", "game": "0.5.5",
    "published": "2026-11-26", "installer": {"url": "https://…/PoE2Runbook-Setup-0.5.5.18.exe", "size": 40897806,
    "sha256": "<64 знака>"}, "notes": {"ru": "…", "en": "…"}, "notice": {"ru": "…", "en": "…"}}. notes — что
    изменилось; notice — необязательное объявление для всех: одна строка до 140 знаков, простой текст. Незнакомые поля
    пропускаются.
  * Подпись — ECDSA P-256 над SHA-256 от точных байтов latest.json; в latest.json.sig — base64 от r‖s (64 байта).
    Проверяет сама Windows (bcrypt.dll) открытым ключом из updatekey.py — его вписывает publish.py keygen. Сторонних
    библиотек шифрования в программе нет. Проверка подписи — общая с каталогом планов (signed.py).

Что делает программа.
  * Спрашивает файл при запуске и потом раз в 6 часов (EVERY), пока игрок не выключил «Проверять обновления» в окне
    «Настройки»; с тем же расписанием и под той же настройкой — каталог одобренных планов (Updater.also, plancat.py).
    Не дозвалась — ещё раз через полчаса (SOON); так же часто, пока игра новее программы, а новой
    программы ещё нет: в день новой версии игры её сборку ждут все. В запросе — только User-Agent:
    PoE2Runbook/<версия>, больше ничего (без cookies, без адреса и имени игрока). Неудача молчит и пишется в журнал
    программы (program.log).
  * Сперва проверяет подпись, и только потом читает файл. Принимает только версию НОВЕЕ своей (сначала версия игры,
    потом номер сборки): равную и старую не берёт, чтобы никто не подсунул прежнюю сборку. Объявление (notice)
    показывается и у равной версии: его видят все, и те, у кого программа уже последняя.
  * «Обновить» (только по нажатию — без него ничего не качается и не ставится): установщик качается в
    <папка данных>\\update, сверяются размер и SHA-256 из подписанного файла, затем он запускается тихо (SWITCHES), а
    программа закрывается. Установщик дожидается, пока она завершится (её отметка — мьютекс APP_MUTEX, см.
    packaging/update.iss), ставит новую версию и открывает её. Недокачанное и уже поставленное убирается.
Сеть — WinHTTP самой Windows: её проверка сертификатов и корневые сертификаты, её настройки прокси; с https на http
она не перенаправляет.
"""
import ctypes
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time
import traceback
import urllib.parse
from pathlib import Path

import appsettings
from i18n import Raw, tr
# подпись — общий код с каталогом планов (plancat.py); имена остаются и здесь: ими пользуются publish.py и проверки
from signed import Refused, SPKI_P256, embedded_key, key_name, public_point, verify  # noqa: F401
import signed

URL = 'https://poe2.labutin.gg/update/latest.json'
SIG_URL = URL + '.sig'
FORMAT = 'poe2-runbook-update'
EVERY = 6 * 3600            # проверка раз в 6 часов
SOON = 30 * 60              # не дозвались или игра новее программы, а новой программы нет — через полчаса
CHECK_TIMEOUT = 10          # секунд на каждый шаг запроса файла (имя, соединение, отправка, ответ)
LOAD_TIMEOUT = 30           # то же при загрузке установщика
MAX_MANIFEST = 64 * 1024    # больше — не файл обновления
MAX_SIG = 1024
MAX_INSTALLER = 512 * 1024 * 1024
NOTICE_MAX = 140            # объявление — одна строка
NOTES_MAX = 4000
# Установщик ставит новую версию тихо, закрывает то, что держит файлы программы, и открывает программу снова
SWITCHES = ('/VERYSILENT', '/SUPPRESSMSGBOXES', '/CLOSEAPPLICATIONS', '/RESTARTAPPLICATIONS')
# Отметка «программа работает» с постоянным именем: установщик ждёт, пока её нет (packaging/update.iss). Её держит
# окно программы (desktop.py) до самого выхода.
APP_MUTEX = 'Local\\PoE2RunbookApp'
SETTING = 'updates'         # ключ настройки «Проверять обновления» в settings.json; нет его — включена
SETUP_NAME = 'PoE2Runbook-Setup-%s.exe'

RE_VERSION = re.compile(r'(\d{1,4})\.(\d{1,4})\.(\d{1,4})\.(\d{1,6})')
RE_SETUP = re.compile(r'PoE2Runbook-Setup-(\d{1,4}\.\d{1,4}\.\d{1,4}\.\d{1,6})\.exe(\.part)?', re.I)
RE_DAY = re.compile(r'\d{4}-\d\d-\d\d')
RE_SHA = re.compile(r'[0-9a-fA-F]{64}')
RE_LANG = re.compile(r'[a-z]{2,3}')
# управляющие знаки и знаки смены направления письма: текст объявления выводится как простой текст и не должен
# переставлять соседние слова
RE_CONTROL = re.compile('[\x00-\x08\x0b-\x1f\x7f-\x9f‎‏‪-‮⁦-⁩]')

# Что ответила проверка — для окна «О программе» (страница пишет перед этим, когда она была)
CHECK_TEXTS = {
    'latest': tr('у вас последняя версия'),
    'offer': tr('есть версия %s'),
    'older': tr('на сайте версия %s — старее этой, не принята'),
    'net': tr('нет связи с сайтом программы'),
    'http': tr('сайт программы ответил ошибкой %s'),
    'tls': tr('защищённое соединение с сайтом программы не установлено'),
    'sig': tr('подпись не сошлась — файл не принят'),
    'format': tr('файл обновления не того формата — не принят'),
    'nokey': tr('в этой сборке нет ключа подписи — проверять нечем'),
    'error': tr('ошибка программы — подробности в журнале программы'),
}
# Почему не удалось «Обновить» — в шапке, рядом с той же кнопкой
JOB_TEXTS = {
    'net': tr('загрузка не удалась: нет связи'),
    'http': tr('загрузка не удалась: сайт не отдал файл'),
    'damaged': tr('скачанный файл не сошёлся с подписью и удалён'),
    'disk': tr('загрузка не удалась: не записывается на диск'),
    'launch': tr('установщик не запустился'),
    'error': tr('ошибка программы — подробности в журнале программы'),
}


class NetError(Exception):
    """Файл не получен. code — net (нет связи, тайм-аут), tls (не прошла проверка сертификата), http (ответ не 200;
    detail — его код), big (больше, чем ждали), url (адрес не https)."""

    def __init__(self, code, detail=''):
        super().__init__('%s %s' % (code, detail))
        self.code, self.detail = code, detail


# --- версии -------------------------------------------------------------------------------------------------------

def version_key(text):
    """Версия программы для сравнения: '0.5.5.18' -> (0, 5, 5, 18) — сначала версия игры, потом номер сборки.
    Не версия программы — None."""
    m = RE_VERSION.fullmatch(text) if isinstance(text, str) else None
    return tuple(int(x) for x in m.groups()) if m else None


def compare(theirs, ours):
    """1 — версия theirs новее ours, 0 — та же, -1 — старее."""
    a, b = version_key(theirs), version_key(ours)
    return (a > b) - (a < b)


# --- файл обновления ----------------------------------------------------------------------------------------------

def _clean(text, one_line):
    """Текст из файла как простой текст: без управляющих знаков (и смены направления письма); одна строка — пробелы
    и переводы строк схлопнуты в один пробел."""
    text = RE_CONTROL.sub('', text.replace('\r\n', '\n').replace('\r', '\n').replace('\t', ' '))
    if one_line:
        return ' '.join(text.split())
    return '\n'.join(line.rstrip() for line in text.strip().split('\n'))


def _texts(value, limit, one_line):
    """{язык: текст} из файла: язык — 2–3 латинские буквы, текст — строка; прочее пропускается. Длиннее limit —
    обрезано (одна строка — с «…»)."""
    out = {}
    for lang, text in (value.items() if isinstance(value, dict) else ()):
        if not (isinstance(lang, str) and RE_LANG.fullmatch(lang) and isinstance(text, str)):
            continue
        text = _clean(text, one_line)
        if len(text) > limit:
            text = text[:limit - 1].rstrip() + '…' if one_line else text[:limit]
        if text:
            out[lang] = text
    return out


def _https(url):
    """Адрес установщика — только https:// без имени и пароля в адресе, без пробелов и управляющих знаков. Иначе None."""
    if not isinstance(url, str) or len(url) > 2048 or not url.isascii() or not url.startswith('https://'):
        return None
    if any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in url):
        return None
    try:
        parts = urllib.parse.urlsplit(url)
        parts.port                          # порт не число — ValueError
    except ValueError:
        return None
    if parts.scheme != 'https' or not parts.hostname or '@' in parts.netloc or parts.fragment:
        return None
    return url


def read_manifest(data, sig, point):
    """Файл обновления (точные байты latest.json) и его подпись (содержимое latest.json.sig) -> поля файла:
    {version, game, published, url, size, sha256, notes, notice}. Подпись проверяется ДО того, как файл читается.
    Не принят — Refused (sig — подпись не сошлась или не та, format — не тот формат, nokey — нечем проверять)."""
    signed.check(data, sig, point, MAX_MANIFEST)
    try:
        doc = json.loads(data.decode('utf-8'))
    except ValueError:                      # и UnicodeDecodeError
        raise Refused('format', 'not json') from None
    if not isinstance(doc, dict) or doc.get('format') != FORMAT:
        raise Refused('format', 'format')
    if type(doc.get('v')) is not int or doc['v'] != 1:
        raise Refused('format', 'v %r' % (doc.get('v'),))
    version = doc.get('version')
    key = version_key(version)
    if key is None:
        raise Refused('format', 'version')
    if doc.get('game') != '%d.%d.%d' % key[:3]:
        raise Refused('format', 'game')
    published = doc.get('published')
    if not isinstance(published, str) or not RE_DAY.fullmatch(published):
        raise Refused('format', 'published')
    inst = doc.get('installer')
    if not isinstance(inst, dict):
        raise Refused('format', 'installer')
    url = _https(inst.get('url'))
    if url is None:
        raise Refused('format', 'installer url')
    size = inst.get('size')
    if type(size) is not int or not 0 < size <= MAX_INSTALLER:
        raise Refused('format', 'installer size')
    sha = inst.get('sha256')
    if not isinstance(sha, str) or not RE_SHA.fullmatch(sha):
        raise Refused('format', 'installer sha256')
    return {'version': version, 'game': doc['game'], 'published': published, 'url': url, 'size': size,
            'sha256': sha.lower(), 'notes': _texts(doc.get('notes'), NOTES_MAX, False),
            'notice': _texts(doc.get('notice'), NOTICE_MAX, True)}


def in_lang(texts, lang):
    """Текст автора на языке страницы, а нет его — по-английски; нет и английского — None."""
    text = (texts or {}).get(lang) or (texts or {}).get('en')
    return Raw(text) if text else None


# --- сеть: WinHTTP самой Windows ---------------------------------------------------------------------------------

_WINHTTP = []
_WINHTTP_LOCK = threading.Lock()
# коды ошибок WinHTTP, которые значат «не прошла проверка защищённого соединения»
TLS_ERRORS = {12175, 12037, 12038, 12044, 12045, 12057, 12169, 12179}


def _winhttp():
    """winhttp.dll с объявленными типами аргументов."""
    with _WINHTTP_LOCK:
        if not _WINHTTP:
            from ctypes import wintypes as w
            h = ctypes.WinDLL('winhttp', use_last_error=True)
            hi = ctypes.c_void_p
            sig = {'WinHttpOpen': ([w.LPCWSTR, w.DWORD, w.LPCWSTR, w.LPCWSTR, w.DWORD], hi),
                   'WinHttpSetTimeouts': ([hi, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int], w.BOOL),
                   'WinHttpConnect': ([hi, w.LPCWSTR, w.WORD, w.DWORD], hi),
                   'WinHttpOpenRequest': ([hi, w.LPCWSTR, w.LPCWSTR, w.LPCWSTR, w.LPCWSTR, ctypes.c_void_p, w.DWORD], hi),
                   'WinHttpSetOption': ([hi, w.DWORD, ctypes.c_void_p, w.DWORD], w.BOOL),
                   'WinHttpSendRequest': ([hi, w.LPCWSTR, w.DWORD, ctypes.c_void_p, w.DWORD, w.DWORD, ctypes.c_size_t],
                                          w.BOOL),
                   'WinHttpReceiveResponse': ([hi, ctypes.c_void_p], w.BOOL),
                   'WinHttpQueryHeaders': ([hi, w.DWORD, w.LPCWSTR, ctypes.c_void_p, ctypes.POINTER(w.DWORD),
                                            ctypes.POINTER(w.DWORD)], w.BOOL),
                   'WinHttpQueryOption': ([hi, w.DWORD, ctypes.c_void_p, ctypes.POINTER(w.DWORD)], w.BOOL),
                   'WinHttpReadData': ([hi, ctypes.c_void_p, w.DWORD, ctypes.POINTER(w.DWORD)], w.BOOL),
                   'WinHttpCloseHandle': ([hi], w.BOOL)}
            for name, (args, res) in sig.items():
                f = getattr(h, name)
                f.argtypes, f.restype = args, res
            _WINHTTP.append(h)
        return _WINHTTP[0]


def _request(url, agent, limit, timeout, sink=None, progress=None, secure=True):
    """Один запрос GET через WinHTTP. Без sink — содержимое ответа (bytes); с sink — куски уходят в sink(кусок), ответ —
    сколько байтов пришло. progress(пришло, всего или None) — после каждого куска. Больше limit байтов — NetError big.
    secure=False — только для проверок на этом компьютере (http://127.0.0.1): программа сама так не ходит."""
    from ctypes import wintypes as w
    if sys.platform != 'win32':
        raise NetError('net', 'not windows')
    h = _winhttp()
    parts = urllib.parse.urlsplit(url)
    path = (parts.path or '/') + ('?' + parts.query if parts.query else '')
    handles = []

    def fail(step):
        code = ctypes.get_last_error()
        raise NetError('tls' if code in TLS_ERRORS else 'net', '%s %d' % (step, code))

    try:
        # прокси — как у Windows (WINHTTP_ACCESS_TYPE_AUTOMATIC_PROXY; до Windows 8.1 его нет — настройки WinHTTP)
        s = h.WinHttpOpen(agent, 4, None, None, 0) or h.WinHttpOpen(agent, 0, None, None, 0)
        if not s:
            fail('open')
        handles.append(s)
        ms = int(timeout * 1000)
        h.WinHttpSetTimeouts(s, ms, ms, ms, ms)
        c = h.WinHttpConnect(s, parts.hostname, parts.port or (443 if secure else 80), 0)
        if not c:
            fail('connect')
        handles.append(c)
        r = h.WinHttpOpenRequest(c, 'GET', path, None, None, None, 0x00800000 if secure else 0)   # WINHTTP_FLAG_SECURE
        if not r:
            fail('request')
        handles.append(r)
        no_cookies = w.DWORD(0x1)               # WINHTTP_OPTION_DISABLE_FEATURE: WINHTTP_DISABLE_COOKIES
        h.WinHttpSetOption(r, 63, ctypes.byref(no_cookies), 4)
        no_downgrade = w.DWORD(1)               # WINHTTP_OPTION_REDIRECT_POLICY: с https на http не переходить
        h.WinHttpSetOption(r, 88, ctypes.byref(no_downgrade), 4)
        if not h.WinHttpSendRequest(r, None, 0, None, 0, 0, 0):
            fail('send')
        if not h.WinHttpReceiveResponse(r, None):
            fail('receive')
        status, n = w.DWORD(0), w.DWORD(4)
        if not h.WinHttpQueryHeaders(r, 19 | 0x20000000, None, ctypes.byref(status), ctypes.byref(n), None):
            fail('status')                      # WINHTTP_QUERY_STATUS_CODE | WINHTTP_QUERY_FLAG_NUMBER
        if status.value != 200:
            raise NetError('http', status.value)
        if secure:
            where, n = ctypes.create_unicode_buffer(4096), w.DWORD(4096 * 2)
            if not h.WinHttpQueryOption(r, 34, where, ctypes.byref(n)) or not where.value.startswith('https://'):
                raise NetError('url', where.value[:200])        # WINHTTP_OPTION_URL — куда привели перенаправления
        total, n = w.DWORD(0), w.DWORD(4)
        known = h.WinHttpQueryHeaders(r, 5 | 0x20000000, None, ctypes.byref(total), ctypes.byref(n), None)
        total = total.value if known else None  # WINHTTP_QUERY_CONTENT_LENGTH; его может не быть
        if total is not None and total > limit:
            raise NetError('big', total)
        buf, got, done, chunks = ctypes.create_string_buffer(1 << 16), w.DWORD(0), 0, []
        while True:
            if not h.WinHttpReadData(r, buf, len(buf), ctypes.byref(got)):
                fail('read')
            if not got.value:
                break
            done += got.value
            if done > limit:
                raise NetError('big', done)
            piece = buf.raw[:got.value]
            if sink is None:
                chunks.append(piece)
            else:
                sink(piece)
            if progress is not None:
                progress(done, total)
        return b''.join(chunks) if sink is None else done
    finally:
        for x in reversed(handles):
            h.WinHttpCloseHandle(x)


def get(url, agent, limit, timeout=CHECK_TIMEOUT, sink=None, progress=None):
    """Файл по адресу https:// (через WinHTTP, _request). Другой адрес — NetError url."""
    if not isinstance(url, str) or not url.startswith('https://'):
        raise NetError('url', str(url)[:200])
    return _request(url, agent, limit, timeout, sink, progress, secure=True)


# --- установщик ---------------------------------------------------------------------------------------------------

def start_installer(path, log=None):
    """Запускает установщик отдельно от программы (он переживёт её выход) — тихо, с SWITCHES; log — куда установщик
    пишет свой журнал (/LOG=…). Не запустился — OSError."""
    args = [str(path)] + list(SWITCHES) + (['/LOG=%s' % log] if log else [])
    flags = 0x00000008 | 0x00000200             # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    try:
        # CREATE_BREAKAWAY_FROM_JOB: программу могли запустить внутри задания, которое убивает потомков вместе с ней
        return subprocess.Popen(args, cwd=str(Path(path).parent), creationflags=flags | 0x01000000, close_fds=True)
    except OSError:
        return subprocess.Popen(args, cwd=str(Path(path).parent), creationflags=flags, close_fds=True)


def hold_app_mutex():
    """Отметка «программа работает» для установщика (APP_MUTEX): держится до выхода программы. Не Windows — ничего."""
    if sys.platform != 'win32':
        return None
    from ctypes import wintypes as w
    k = ctypes.WinDLL('kernel32', use_last_error=True)
    k.CreateMutexW.argtypes, k.CreateMutexW.restype = [ctypes.c_void_p, w.BOOL, w.LPCWSTR], w.HANDLE
    return k.CreateMutexW(None, False, APP_MUTEX) or None


# --- обновление в работе ------------------------------------------------------------------------------------------

class Updater:
    """Обновление в работающей программе: проверка по расписанию (run), состояние для страниц (view), загрузка и
    запуск установщика по «Обновить» (install). Есть только у окна программы (desktop.py): сервер страниц из
    исходников о новых версиях не спрашивает.

    version — своя версия ('0.5.5.18'); folder — куда качать (<папка данных>\\update); settings_path — settings.json
    (настройка «Проверять обновления»); point — открытый ключ подписи (X‖Y). Для проверок подменяются: fetch(url,
    limit, timeout, sink=None, progress=None) — запрос (как get); launch(путь, журнал) — запуск установщика;
    quit() — закрыть программу; urgent() — игра новее программы (проверять чаще); clock; say — строка в журнал."""

    def __init__(self, version, folder, settings_path=None, point=None, fetch=None, launch=None, quit=None,
                 urgent=None, clock=time.time, say=None):
        # что ещё спросить у сайта при каждой проверке и под той же настройкой — каталог одобренных планов
        # (App.plancat_check): функции без аргументов; их неудача не влияет на проверку обновлений
        self.also = []
        self.version = version
        self.folder = Path(folder)
        self.settings_path = settings_path
        self.point = point
        self.agent = 'PoE2Runbook/%s' % version
        self.fetch = fetch or (lambda url, limit, timeout, sink=None, progress=None:
                               get(url, self.agent, limit, timeout, sink, progress))
        self.launch = launch or start_installer
        self.quit = quit or (lambda: None)
        self.urgent = urgent or (lambda: False)
        self.clock = clock
        self.say = say or (lambda text: print(text, flush=True))
        self.lock = threading.RLock()
        self.wake = threading.Event()
        self.stopped = False
        self.on = appsettings.load(settings_path).get(SETTING) is not False
        self.offer = None       # новая версия: поля read_manifest
        self.notice = {}        # объявление для всех: язык -> строка
        self.last = None        # последняя проверка: {at, code, version}
        self.job = None         # «Обновить»: {state: load | run | fail, done, total, code}
        self.process = None     # запущенный установщик
        self.changed = None     # что позвать, когда изменилось видимое (сервер — чтобы страница «Игра» узнала сразу)
        self.stamp = 0          # счёт перемен видимого: по нему страница «Игра» спрашивает /api/update заново

    # --- проверка ---

    def _changed(self):
        with self.lock:
            self.stamp += 1
        if self.changed is not None:
            try:
                self.changed()
            except Exception:
                traceback.print_exc()

    def check(self):
        """Одна проверка. True — сайт ответил (принят его файл или нет); False — не дозвались (повторить скоро)."""
        at = self.clock()
        code, version, reached = None, None, True
        try:
            if self.point is None:
                raise Refused('nokey')
            data = self.fetch(URL, MAX_MANIFEST, CHECK_TIMEOUT)
            sig = self.fetch(SIG_URL, MAX_SIG, CHECK_TIMEOUT)
            info = read_manifest(data, sig, self.point)
            rel = compare(info['version'], self.version)
            if rel < 0:
                raise Refused('older', info['version'])
        except Refused as e:
            code, version = e.code, (e.detail if e.code == 'older' else None)
            self.say('update check: refused (%s%s)' % (e.code, ', ' + str(e.detail) if e.detail else ''))
            if e.code == 'older':
                with self.lock:         # подлинный, но старый файл: новой версии нет, объявления — тоже
                    self.offer, self.notice = None, {}
        except NetError as e:
            code, reached = ('http' if e.code == 'http' else 'tls' if e.code == 'tls' else 'net'), False
            version = e.detail if e.code == 'http' else None
            self.say('update check: no answer (%s %s)' % (e.code, e.detail))
        except Exception:
            code = 'error'
            self.say('update check: error\n' + traceback.format_exc())
        else:
            code, version = ('offer' if rel > 0 else 'latest'), info['version']
            with self.lock:
                self.offer = info if rel > 0 else None
                self.notice = info['notice']
            self.say('update check: %s' % ('version %s is available' % version if rel > 0
                                          else 'up to date (%s)' % version))
        with self.lock:
            self.last = {'at': at, 'code': code, 'version': version}
        self._changed()
        return reached

    def run(self):
        """Проверки по расписанию, пока программа работает: сразу, потом раз в EVERY; не дозвались, или игра новее
        программы, а новой программы нет, — через SOON. Выключено — не спрашиваем, ждём включения (set_on)."""
        while not self.stopped:
            reached = self.check() if self.on else True
            for extra in (self.also if self.on else ()):
                try:
                    extra()
                except Exception:
                    self.say('update check: extra check failed\n' + traceback.format_exc())
            soon = not reached or (self.on and self.offer is None and self.urgent())
            self.wake.wait(SOON if soon else EVERY)
            self.wake.clear()

    def start(self):
        """Убрать недокачанное и поставленное, затем проверки — в своём потоке."""
        self.tidy()
        threading.Thread(target=self.run, daemon=True, name='update').start()

    def set_on(self, on):
        """«Проверять обновления» (окно «Настройки»): запоминается в settings.json; включили — проверка сразу."""
        if type(on) is not bool:
            return False
        if on != self.on:
            self.on = on
            try:
                appsettings.update(self.settings_path, **{SETTING: on})
            except OSError:
                pass
            if on:
                self.wake.set()
            self._changed()
        return True

    # --- «Обновить» ---

    def tidy(self):
        """Папка загрузки: недокачанное (.part) и установщики версий не новее своей (уже поставлены) — убрать.
        Занятый файл (установщик ещё работает) остаётся до следующего запуска."""
        try:
            names = list(self.folder.iterdir())
        except OSError:
            return
        for path in names:
            m = RE_SETUP.fullmatch(path.name)
            if m and (m.group(2) or compare(m.group(1), self.version) <= 0):
                try:
                    path.unlink()
                except OSError:
                    pass

    def install(self):
        """«Обновить»: скачать установщик новой версии, сверить, запустить, закрыть программу — в своём потоке.
        Новой версии нет или уже качаем — False."""
        with self.lock:
            offer = self.offer
            if offer is None or not self.on or (self.job and self.job['state'] in ('load', 'run')):
                return False
            self.job = {'state': 'load', 'done': 0, 'total': offer['size'], 'code': None}
        self._changed()
        threading.Thread(target=self._install, args=(offer,), daemon=True, name='update-install').start()
        return True

    def _fail(self, code, why):
        with self.lock:
            self.job = dict(self.job or {}, state='fail', code=code)
        self.say('update: failed (%s)' % why)
        self._changed()

    @staticmethod
    def _sha256(path):
        h = hashlib.sha256()
        with open(path, 'rb') as f:
            for piece in iter(lambda: f.read(1 << 20), b''):
                h.update(piece)
        return h.hexdigest()

    def _ready(self, final, offer):
        """Установщик этой версии уже скачан и сверен (прошлое «Обновить» не дошло до конца) — True; лежит не тот —
        убрать его."""
        try:
            if final.stat().st_size == offer['size'] and self._sha256(final) == offer['sha256']:
                return True
            final.unlink()
        except OSError:
            pass
        return False

    def _load(self, offer, part):
        """Скачать установщик в part, сверяя размер и SHA-256 с подписанным файлом. Не сошлось — Refused."""
        digest = hashlib.sha256()
        with open(part, 'wb') as f:
            def sink(piece):
                digest.update(piece)
                f.write(piece)

            def progress(done, total):
                with self.lock:
                    if self.job is not None:
                        self.job['done'] = done
            got = self.fetch(offer['url'], offer['size'], LOAD_TIMEOUT, sink=sink, progress=progress)
        if got != offer['size'] or part.stat().st_size != offer['size']:
            raise Refused('size', '%s of %d' % (got, offer['size']))
        if digest.hexdigest() != offer['sha256']:
            raise Refused('hash', digest.hexdigest())

    def _install(self, offer):
        name = SETUP_NAME % offer['version']        # имя — из проверенной версии, не из адреса
        final, part = self.folder / name, self.folder / (name + '.part')
        self.say('update: downloading %s (%d bytes)' % (offer['url'], offer['size']))
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            if not self._ready(final, offer):
                self._load(offer, part)
                os.replace(part, final)
        except (NetError, Refused, OSError, Exception) as e:
            try:
                part.unlink()               # недокачанное и не сошедшееся не остаётся
            except OSError:
                pass
            code = ('damaged' if isinstance(e, Refused) or (isinstance(e, NetError) and e.code == 'big')
                    else 'http' if isinstance(e, NetError) and e.code == 'http'
                    else 'net' if isinstance(e, NetError) else 'disk' if isinstance(e, OSError) else 'error')
            if code == 'error':
                traceback.print_exc()
            return self._fail(code, '%s: %s' % (type(e).__name__, e))
        with self.lock:
            self.job = dict(self.job, state='run', done=offer['size'])
        self._changed()
        try:
            self.process = self.launch(final, self.folder / 'install.log')     # установщик живёт сам по себе
        except OSError as e:
            return self._fail('launch', e)
        self.say('update: installer %s started, the program closes' % name)
        self.quit()

    # --- для страниц ---

    def setting(self):
        """Строка «Проверять обновления» окна «Настройки»."""
        return {'can': True, 'on': self.on}

    def brief(self):
        """Для состояния страницы «Игра»: offer — есть версия новее и её можно «Обновить» (кнопка у красной строки «нужна
        новая версия программы»); stamp — счёт перемен (сменился — страница спрашивает /api/update). Только числа и да /
        нет: состояние «Игры» переводит строки как названия."""
        with self.lock:
            busy = bool(self.job) and self.job.get('state') in ('load', 'run')
            return {'offer': bool(self.on and self.offer is not None and not busy), 'stamp': self.stamp}

    def view(self, lang):
        """Для шапки и окна «О программе» на языке lang: state — none (показывать нечего) | offer (есть версия
        новее: version, notes) | load (качается: done из total) | run (установщик запущен, программа закрывается) |
        fail (не удалось: error; кнопка «Обновить» снова); notice — объявление для всех; last — последняя проверка
        {at, text}. Выключено — ничего, кроме настройки и last."""
        with self.lock:
            offer, job, last, notice = self.offer, dict(self.job or {}), dict(self.last or {}), dict(self.notice)
        out = {'can': True, 'on': self.on, 'state': 'none', 'version': None, 'notes': None, 'notice': None,
               'done': 0, 'total': 0, 'error': None, 'last': self._last_view(last)}
        if not self.on:
            return out
        out['notice'] = in_lang(notice, lang)
        if offer is not None:
            out.update(state='offer', version=offer['version'], notes=in_lang(offer['notes'], lang))
        if job.get('state') in ('load', 'run'):
            out.update(state=job['state'], done=job.get('done', 0), total=job.get('total', 0))
        elif job.get('state') == 'fail' and offer is not None:
            out.update(state='fail', error=JOB_TEXTS.get(job.get('code'), JOB_TEXTS['error']))
        return out

    def _last_view(self, last):
        if not self.on:
            return {'at': None, 'text': tr('выключена в настройках')}
        if not last:
            return {'at': None, 'text': tr('ещё не было')}
        text = CHECK_TEXTS.get(last.get('code'), CHECK_TEXTS['error'])
        if last.get('code') in ('offer', 'older', 'http'):
            text = text % (last.get('version') or '?')
        return {'at': last.get('at'), 'text': text}
