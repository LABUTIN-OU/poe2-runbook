# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Sergei Labutin
# Additional terms under GPL-3.0 section 7: see NOTICE.md
"""Каталог одобренных планов: игрок берёт в программе планы, которые одобрил автор программы, — видит список, ставит
план одним нажатием, получает его новые версии. Одобряет план автор программы одной командой (release/plans.py).

Договорённость с сайтом и инструментом одобрения. Менять её нельзя: на неё опираются сайт и установленные копии.
  * Адрес в программе один — INDEX_URL, подпись рядом (SIG_URL). Файлы планов лежат по адресам из подписанного
    каталога (https://poe2.labutin.gg/plans/<uid>/<версия>.plan) — только https://.
  * index.json: {"format": "poe2-runbook-plans", "v": 1, "updated": "2026-11-26", "plans": [{"uid", "version": 3,
    "title": {"ru", "en"}, "author": {"name", "url"}, "game": "0.5.5", "class", "ascendancy", "tags", "langs",
    "summary": {"ru", "en"}, "changed": {"ru", "en"}, "published": "2026-11-26", "file": {"url", "size",
    "sha256"}}]}. Незнакомые поля пропускаются; запись без метки, версии, названия, автора или файла — тоже.
  * Подпись — та же, что у файла обновления программы, и проверяется тем же кодом (signed.py): ECDSA P-256 над
    SHA-256 от точных байтов index.json, ключ — вписанный в программу (updatekey.py). У каждого файла плана в
    подписанном каталоге стоят размер и SHA-256: скачанный файл сверяется с ними, потом проходит обычный приём плана
    (planlib.add / planlib.replace — строгая проверка planguard).
  * Имя автора плана берётся ТОЛЬКО из подписанного каталога, никогда из файла плана: так чужой план нельзя выдать
    за план известного автора. Класс и восхождение в каталоге — из самого плана (их пишет инструмент одобрения).

Что делает программа.
  * Спрашивает каталог вместе с проверкой обновлений — то же расписание и та же настройка «Проверять обновления»
    (update.Updater.also) — и когда игрок открывает «Каталог» в редакторе (не чаще FRESH). В запросе — только
    User-Agent PoE2Runbook/<версия>, как у обновлений. Файл плана качается только по «Поставить» / «Обновить».
  * Принятый каталог помнит в памяти. Что нужно надолго — версия и автор плана, поставленного из каталога, — пишется
    в оглавление плана (plan.json: catalog): автор виден в списке планов и без сети.
"""
import hashlib
import json
import re
import threading
import time
import traceback
import urllib.parse

import planlib
import signed
import update
from signed import Refused

INDEX_URL = 'https://poe2.labutin.gg/plans/index.json'
SIG_URL = INDEX_URL + '.sig'
FORMAT = 'poe2-runbook-plans'
MAX_INDEX = 1024 * 1024         # больше — не каталог
MAX_SIG = 1024
MAX_PLAN = 2 * planlib.MAX_TEXT + 65536     # файл плана: маршрут и билд целиком (тот же предел, что у файла из рук)
MAX_PLANS = 500
FRESH = 60                      # «Каталог» открыли снова раньше, чем через минуту после прошлого запроса, — не спрашиваем
TITLE_MAX, NAME_MAX, SUMMARY_MAX, CHANGED_MAX = 120, 80, 300, 600

RE_UID = re.compile(r'[0-9a-z]{1,40}')         # метка плана — как её принимает planlib.parse_bundle
RE_GAME = re.compile(r'\d{1,4}\.\d{1,4}\.\d{1,4}')
RE_DAY = re.compile(r'\d{4}-\d\d-\d\d')
RE_SHA = re.compile(r'[0-9a-fA-F]{64}')
RE_NAME = re.compile(r"[A-Za-z][A-Za-z' -]{0,39}")     # класс и восхождение — имена из данных игры («Disciple of Varashta»)
RE_TAG = re.compile(r'[a-z0-9][a-z0-9-]{0,23}')
RE_LANG = re.compile(r'[a-z]{2,3}')


def web_url(url):
    """Адрес страницы автора: только http:// или https:// — без имени и пароля, пробелов и управляющих знаков; иначе
    None (автор показывается без ссылки)."""
    if not isinstance(url, str) or len(url) > 2048 or not url.isascii():
        return None
    if any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in url):
        return None
    try:
        parts = urllib.parse.urlsplit(url)
        parts.port                          # порт не число — ValueError
    except ValueError:
        return None
    if parts.scheme not in ('http', 'https') or not parts.hostname or '@' in parts.netloc:
        return None
    return url


def _line(value, limit):
    """Одна строка простого текста из каталога (без управляющих знаков и смены направления письма); не строка — ''."""
    if not isinstance(value, str):
        return ''
    text = update._clean(value, True)
    return text[:limit - 1].rstrip() + '…' if len(text) > limit else text


def _entry(p):
    """Запись каталога как её понимает программа или None (без метки, версии, названия, автора или файла)."""
    if not isinstance(p, dict):
        return None
    uid, version = p.get('uid'), p.get('version')
    if not isinstance(uid, str) or not RE_UID.fullmatch(uid):
        return None
    if type(version) is not int or not 0 < version <= 1000000:
        return None
    title = update._texts(p.get('title'), TITLE_MAX, True)
    who = p.get('author') if isinstance(p.get('author'), dict) else {}
    name = _line(who.get('name'), NAME_MAX)
    f = p.get('file') if isinstance(p.get('file'), dict) else {}
    url, size, sha = update._https(f.get('url')), f.get('size'), f.get('sha256')
    if not title or not name or url is None or type(size) is not int or not 0 < size <= MAX_PLAN \
            or not isinstance(sha, str) or not RE_SHA.fullmatch(sha):
        return None
    author = {'name': name}
    if web_url(who.get('url')):
        author['url'] = who['url']
    one = lambda v, rx: v if isinstance(v, str) and rx.fullmatch(v) else ''      # noqa: E731
    words = lambda v, rx, n: [x for x in v if isinstance(x, str) and rx.fullmatch(x)][:n] if isinstance(v, list) else []   # noqa: E731
    return {'uid': uid, 'version': version, 'title': title, 'author': author,
            'game': one(p.get('game'), RE_GAME), 'cls': one(p.get('class'), RE_NAME), 'asc': one(p.get('ascendancy'), RE_NAME),
            'tags': words(p.get('tags'), RE_TAG, 12), 'langs': words(p.get('langs'), RE_LANG, 12),
            'summary': update._texts(p.get('summary'), SUMMARY_MAX, True),
            'changed': update._texts(p.get('changed'), CHANGED_MAX, True),
            'published': one(p.get('published'), RE_DAY), 'url': url, 'size': size, 'sha256': sha.lower()}


def _no_constant(name):
    raise ValueError(name)


def read_index(data, sig, point):
    """Каталог (точные байты index.json) и его подпись (содержимое index.json.sig) -> {updated, plans: [записи]}.
    Подпись проверяется ДО того, как файл читается (signed.check). Не принят — Refused: sig, format, nokey."""
    signed.check(data, sig, point, MAX_INDEX)
    try:
        doc = json.loads(data.decode('utf-8'), parse_constant=_no_constant)
    except (ValueError, RecursionError):        # и UnicodeDecodeError
        raise Refused('format', 'not json') from None
    if not isinstance(doc, dict) or doc.get('format') != FORMAT:
        raise Refused('format', 'format')
    if type(doc.get('v')) is not int or doc['v'] != 1:
        raise Refused('format', 'v %r' % (doc.get('v'),))
    if not isinstance(doc.get('plans'), list):
        raise Refused('format', 'plans')
    plans, seen = [], set()
    for p in doc['plans'][:MAX_PLANS]:
        e = _entry(p)
        if e is not None and e['uid'] not in seen:          # метка повторилась — в счёт первая запись
            seen.add(e['uid'])
            plans.append(e)
    updated = doc.get('updated') if isinstance(doc.get('updated'), str) and RE_DAY.fullmatch(doc['updated']) else ''
    return {'updated': updated, 'plans': plans}


def in_lang(texts, lang):
    """Текст каталога на языке страницы, иначе английский, иначе русский, иначе любой; нет — ''."""
    texts = texts or {}
    return texts.get(lang) or texts.get('en') or texts.get('ru') or next(iter(texts.values()), '')


def read_plan(data, entry):
    """Скачанный файл плана (байты) -> словарь файла плана. Сверяется с подписанным каталогом: размер, SHA-256 и метка
    плана внутри файла. Не сошлось — Refused (size, hash, format, uid). Сам план проверяет обычный приём (planlib)."""
    if not isinstance(data, bytes) or len(data) != entry['size']:
        raise Refused('size', '%s of %d' % (len(data) if isinstance(data, bytes) else None, entry['size']))
    if hashlib.sha256(data).hexdigest() != entry['sha256']:
        raise Refused('hash')
    try:
        doc = json.loads(data.decode('utf-8'), parse_constant=_no_constant)
    except (ValueError, RecursionError):
        raise Refused('format', 'not json') from None
    if not isinstance(doc, dict) or doc.get('format') != planlib.FORMAT:
        raise Refused('format', 'not a plan')
    if doc.get('uid') != entry['uid']:
        raise Refused('uid', str(doc.get('uid'))[:40])
    return doc


def offline(url, limit, timeout):
    """Запрос, который в сеть не ходит (сервер с --offline: проверки страниц): «нет связи»."""
    raise update.NetError('net', 'offline')


class Catalog:
    """Каталог в работающей программе: последний принятый (data) и как прошёл последний запрос (last).

    point — открытый ключ подписи (X‖Y; None — в сборке нет ключа: в сеть не ходим); agent — User-Agent запроса. Для
    проверок подменяются: fetch(url, limit, timeout) — запрос (как update.get, без sink); clock; say — строка в журнал."""

    def __init__(self, point, agent='PoE2Runbook', fetch=None, clock=time.time, say=None):
        self.point = point
        self.agent = agent
        self.fetch = fetch or (lambda url, limit, timeout: update.get(url, self.agent, limit, timeout))
        self.clock = clock
        self.say = say or (lambda text: print(text, flush=True))
        self.ask = threading.Lock()         # один запрос каталога за раз
        self.lock = threading.RLock()
        self.data = None                    # принятый каталог: {updated, plans}
        self.got = None                     # когда он принят
        self.last = None                    # последний запрос: {at, code, detail}
        self.busy = False

    def entry(self, uid):
        with self.lock:
            return next((e for e in (self.data or {}).get('plans') or () if e['uid'] == uid), None)

    def check(self, fresh=None):
        """Спросить каталог. fresh — секунды: прошлый запрос был недавно — не спрашивать. True — сайт ответил (каталог
        принят или нет); False — не дозвались."""
        with self.ask:
            at = self.clock()
            with self.lock:
                if fresh is not None and self.last is not None and 0 <= at - self.last['at'] < fresh:
                    return True
                self.busy = True
            code, detail, reached = 'ok', '', True
            try:
                if self.point is None:
                    raise Refused('nokey')
                data = self.fetch(INDEX_URL, MAX_INDEX, update.CHECK_TIMEOUT)
                sig = self.fetch(SIG_URL, MAX_SIG, update.CHECK_TIMEOUT)
                doc = read_index(data, sig, self.point)
            except Refused as e:
                code, detail = e.code, e.detail
                self.say('plan catalogue: refused (%s%s)' % (e.code, ', ' + str(e.detail) if e.detail else ''))
            except update.NetError as e:
                code, reached = ('http' if e.code == 'http' else 'tls' if e.code == 'tls' else 'net'), False
                detail = e.detail if e.code == 'http' else ''
                self.say('plan catalogue: no answer (%s %s)' % (e.code, e.detail))
            except Exception:
                code = 'error'
                self.say('plan catalogue: error\n' + traceback.format_exc())
            else:
                with self.lock:
                    self.data, self.got = doc, at
                self.say('plan catalogue: %d plan(s), updated %s' % (len(doc['plans']), doc['updated'] or '?'))
            with self.lock:
                self.last = {'at': at, 'code': code, 'detail': detail}
                self.busy = False
            return reached

    def load(self, entry):
        """Файл плана записи каталога: скачан (только https, не больше его размера) и сверен (read_plan). Не скачан —
        update.NetError; не сошёлся — Refused."""
        try:
            data = self.fetch(entry['url'], entry['size'], update.LOAD_TIMEOUT)
        except update.NetError as e:
            if e.code == 'big':
                raise Refused('size', 'big') from None
            raise
        return read_plan(data, entry)
