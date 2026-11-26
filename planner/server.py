# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Sergei Labutin
# Additional terms under GPL-3.0 section 7: see NOTICE.md
"""Локальная страница маршрута PoE2.

Читает лог игры (Client.txt), хранит отметки игрока в папке runs и отдаёт
страницу на http://127.0.0.1:<порт>/. Игру не трогает: читает её лог и текст вещи,
который игрок сам скопировал в игре (Ctrl+Alt+C) — см. clip.py; в игру ничего не посылает.

Запуск: python planner/server.py [--port 4717] [--open] [--no-clip]
"""
import argparse
import contextlib
import hashlib
import json
import os
import re
import secrets
import shutil
import sys
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import about  # noqa: E402
import anoint  # noqa: E402
import appsettings  # noqa: E402
import appversion  # noqa: E402
import attrneed  # noqa: E402
import buildplan  # noqa: E402
import buildstage  # noqa: E402
import clip  # noqa: E402
import core  # noqa: E402
import craftplan  # noqa: E402
import filtereval  # noqa: E402
import gamedata  # noqa: E402
import gamepaths  # noqa: E402
import herostats  # noqa: E402
import itemcopy  # noqa: E402
import itemstats  # noqa: E402
import landmarks  # noqa: E402
import logtext  # noqa: E402
import buildcheck  # noqa: E402
import planfiles  # noqa: E402
import planlib  # noqa: E402
import plancat  # noqa: E402
import review  # noqa: E402
import signed  # noqa: E402
import update  # noqa: E402
import routeplan  # noqa: E402
import slotwear  # noqa: E402
import treegeo  # noqa: E402
import treeplan  # noqa: E402
import waystone  # noqa: E402
import wearcheck  # noqa: E402
from i18n import tr  # noqa: E402
import i18n  # noqa: E402

# Где игра (её лог, настройки, фильтры с сайта), программа ищет сама — см. gamepaths.py: Steam на любом диске,
# клиент с сайта игры, запущенная игра. Параметры --log, --config, --filters нужны только проверкам.
# Картинки умений и вещей лежат рядом со страницей: /icons/<id цели умения или поле icon вещи>.webp
RE_ICON = re.compile(r'/icons/([a-z0-9-]+\.webp)')
# Что даёт узел на языке страницы: /treestats.<язык>.json рядом с /treestats.json (собирает planner/treegeo.py) и
# /atlasstats.<язык>.json рядом с /atlasstats.json (planner/atlasgeo.py)
RE_TREESTATS = re.compile(r'/(tree|atlas)stats\.([a-z]{2}(?:-[a-z]{2,4})?)\.json')
# Фильтры, полученные из аккаунта, игра кладёт в «Документы»\My Games\Path of Exile 2\OnlineFilters; файл
# переписывается при каждой загрузке.
# Файл фильтра из аккаунта игра начинает своей шапкой: «#Online Item Filter», затем строки «#ключ:значение» —
# name (название, как на сайте), version, realm, hash, lastUpdate… Название фильтра программа берёт отсюда: игроку
# не нужно называть фильтр самому.
FILTER_HEAD = '#Online Item Filter'
RE_FILTER_FIELD = re.compile(r'#(\w+):(.*)')


def filter_header(path):
    """Шапка файла фильтра из аккаунта: {ключ: значение}; {} — файл не такой или не читается."""
    try:
        with open(path, encoding='utf-8-sig', errors='replace') as f:
            if f.readline().strip() != FILTER_HEAD:
                return {}
            head = {}
            for _ in range(40):
                m = RE_FILTER_FIELD.fullmatch(f.readline().strip())
                if not m:
                    break
                head[m.group(1)] = m.group(2).strip()
            return head
    except OSError:
        return {}
# Настройки игры (там же, в «Документах»): строка item_filter= говорит, какой фильтр выбран (None — выключен).
# Сравнение скопированной вещи со слотом само уходит со страницы через минуту после копии: вещь к тому
# времени или надели, или выбросили. Продлить его нельзя и не нужно — проще скопировать вещь в игре ещё раз.
COPY_SECONDS = 60
# «Сравнить» и «Надеть» — одна клавиша в игре: второе нажатие по тому же предмету — «Надеть», но не раньше этого
# времени после сравнения: случайное двойное нажатие ничего не отмечает. Было 1 с — игрок успевал взглянуть на ответ и
# нажать снова раньше, нажатие пропадало молча (их слова из игры 2026-11-26: «задержка надевания F2 очень большая,
# прямо раза в 3 уменьшить нужно, сейчас по 3 раза нажимаю чтобы что-то надеть»). 0,3 с — втрое меньше, как просили:
# дрожь клавиши и случайный двойной удар обычно короче.
SAME_GUARD = 0.3
# Что игрок выбирает об окнах поверх игры (окно «Настройки» в шапке страниц): имя в App.overlay -> (ключ в settings.json,
# возможные значения, значение по умолчанию). on — окна включены; list — список шага свёрнут ('fold': строка шага и
# имена дел зоны над ней) или раскрыт всегда ('open'); alt — по клавише (Alt) список раскрыт всегда ('any') или только
# когда курсор над ним ('over'); clear — на сколько процентов список прозрачен, пока клавиша не зажата.
OVERLAY_CHOICES = {'on': ('overlay', (True, False), True), 'list': ('overlayList', ('fold', 'open'), 'fold'),
                   'alt': ('overlayAlt', ('any', 'over'), 'any'), 'clear': ('overlayClear', (0, 15, 30, 50), 30)}


def _choice(value, choices):
    """Значение — одно из возможных, того же вида: 1 не сойдёт за True, '30' — за 30."""
    return any(type(value) is type(c) and value == c for c in choices)


def overlay_from(settings):
    """Настройки окон поверх игры из файла настроек программы: чего в файле нет или что в нём не из возможного — по
    умолчанию."""
    return {name: settings.get(key) if _choice(settings.get(key), choices) else default
            for name, (key, choices, default) in OVERLAY_CHOICES.items()}


class Book:
    """Один план, каким его видит программа: файл оглавления (или план одним файлом), план в рабочем виде,
    каталог данных игры с его своими статами, замечания, отметка времени файлов. id — имя папки плана в
    библиотеке ('' — программа запущена с одним планом, без библиотеки)."""

    def __init__(self, path, pid=''):
        self.id = pid
        self.path = Path(path)
        self.plan = core.norm_plan({})[0]
        self.catalog = None
        self.problems = []
        self.error = None
        self.mtime = None
        self.parts = []          # файлы частей плана (маршрут, билд), если план собран из них


def _book_field(name):
    """Поле плана у программы — поле книги, на которую она сейчас смотрит (App.book)."""
    return property(lambda app: getattr(app.book, name), lambda app, value: setattr(app.book, name, value))


class App:
    """Состояние программы. Все обращения идут под замком self.cond.

    Планов может быть несколько (библиотека plans/, planlib). Каждый герой идёт по своему плану (runs/plans.json):
    программа держит книгу плана героя текущего забега (active) — по ней разбирается лог и собирается страница
    «Игра». Редактор может открыть и другой план: на время его запроса программа смотрит на книгу того плана
    (editing). Поля plan, catalog, plan_problems… — поля книги, на которую программа смотрит сейчас (book)."""

    plan = _book_field('plan')
    catalog = _book_field('catalog')
    plan_problems = _book_field('problems')
    plan_error = _book_field('error')
    _plan_mtime = _book_field('mtime')
    _plan_parts = _book_field('parts')
    plan_path = property(lambda app: app.book.path, lambda app, value: setattr(app.book, 'path', Path(value)))

    def __init__(self, log_path, plan_path, runs_dir, filters_dir=None, archive_dir=None, config_path=None,
                 icons_dir=None, catalog_dir=None, knowledge_dir=None, backup_dir=None, plans_dir=None):
        # Библиотека планов (plans/): нет её — программа работает с одним планом plan_path, как раньше.
        # plan_path при библиотеке — оглавление плана, с которого начать (пока лог не назвал героя).
        self.plans_dir = Path(plans_dir) if plans_dir else None
        start = Path(plan_path)
        self.book = self.active = Book(start, start.parent.name if self.plans_dir else '')
        self.books = {self.book.id: self.book} if self.plans_dir else {}
        self._lib = (None, [])        # список планов библиотеки: (отметка папок, сводки planlib.summary)
        self.run_plans = {}           # забег -> {'plan': id плана, 'at': когда сказано, 'ask'?: спросить у нового героя}
        # Каталог данных игры (catalog/data): по нему план разворачивает строки аффиксов в ступени, а вещь
        # из буфера находит свою строку. Нет каталога — план с такими строками сообщит об этом сам.
        # base_catalog — каталог как он лежит на диске; catalog — он же со своими статами билда, который
        # сейчас прочитан (gamedata.with_stats): им пользуется всё, что считает статы.
        self.base_catalog = gamedata.load(catalog_dir if catalog_dir else ROOT / 'catalog' / 'data')
        self.catalog = self.base_catalog
        # подписи копии предмета на всех языках клиента — из таблицы строк игры в каталоге
        itemcopy.use_catalog(self.base_catalog)
        # Зоны с собственным уровнем (узлы механик, арены боссов): этап карт они не открывают
        self.own_level = gamedata.own_level(self.catalog)
        # Уровни боевых зон по данным игры: фильтр в городе проверяется для шага впереди (core.ground_level)
        self.zone_levels = gamedata.zone_levels(self.catalog)
        # Картинки умений и вещей; какие из них есть, страница узнаёт из состояния (поле icons)
        self.icons_dir = Path(icons_dir) if icons_dir else HERE / 'static' / 'icons'
        self.tree_path = HERE / 'static' / 'tree.json'   # геометрия дерева для карты (см. treegeo.py)
        self.treestats_path = HERE / 'static' / 'treestats.json'   # что даёт каждый узел — для правки дерева
        # то же для дерева атласа (см. atlasgeo.py): карта и правка у двух деревьев общие
        self.atlas_path = HERE / 'static' / 'atlas.json'
        self.atlasstats_path = HERE / 'static' / 'atlasstats.json'
        self._geo = {}                # данные деревьев для проверки правок: 'tree' / 'atlas' -> (время файла, данные)
        self._tree_lines = (None, {})  # что даёт каждый узел дерева героя: (время файла, данные)
        # Куда складывать прежние версии файла плана перед правкой со страницы (у плана библиотеки — своя папка
        # внутри: части разных планов называются одинаково) и убранные из библиотеки планы
        self.backup_dir = Path(backup_dir) if backup_dir else (
            self.plans_dir.parent / 'backup' if self.plans_dir else Path(plan_path).resolve().parent / 'backup')
        self.config_path = Path(config_path) if config_path else None
        self.selected_filter = None   # что выбрано в настройках игры; None — настройки не прочитаны
        self._config_mtime = None
        # Язык клиента игры (строка language= настроек) и что игра пишет в лог на этом языке: шаблоны
        # системных строк и реплики по кодам строк (logtext.LogText). Пока настройки не прочитаны — русские строки.
        self.client_lang = None
        self.log_text = logtext.LogText()
        self._speech = {}             # реплики игры для редактора: язык страницы -> {код: «Имя: текст»}
        self._stats = {}              # тексты свойств для поля награды редактора: язык страницы -> {коды: текст}
        self._pending_at = None       # когда короткий заход превратится в смену шага
        self.opener = webbrowser.open  # чем открыть страницу в браузере системы (в проверках — подмена)
        # Вещь, которую игрок скопировал в игре (Ctrl+Alt+C): разобранный текст, живёт только в памяти.
        self.copied = None
        self.copy_until = None        # когда сравнение с этой вещью само уйдёт со страницы
        self.wore = None              # последний «надеть»: строка, время, имя — окно страницы коротко говорит «НАДЕТО»
        self.copy_pick = None         # (время копии, строка): слот, выбранный для неё на странице (кольцо 1 или 2)
        self.clip = 'off'             # чтение буфера: 'on', 'off' или текст ошибки
        self.keys = None              # клавиши страницы в игре — «Надеть» и «Закрыть» (clip.WinKeys): их state — на странице
        # какие клавиши держать: первые функциональные, которых игра не занимает (по её настройкам, load_config):
        # «Сравнить / Надеть», «Закрыть» и «Программа ↔ игра»
        self.key_choice = clip.pick_keys(names=clip.ALL_KEYS)
        self.key_copies = False       # клавиша «Надеть» ещё и сравнивает: сама копирует предмет под курсором (serve)
        self.copied_raw = None        # текст предмета в окне сравнения: тот же предмет под курсором ещё раз — «Надеть»
        self.copy_mod = clip.VK_MENU  # клавиша «подробное описание предмета» в игре: с ней «Сравнить» копирует тиры
        self.copy_cursor = None       # где был курсор, когда пришла копия: окно поверх игры встаёт рядом с предметом
        # Окна поверх игры (overlay.py; есть только у окна программы, desktop.py): can — программа их умеет, on — игрок
        # их не выключил (настройка overlay в settings.json). window_toggle — «Программа ↔ игра»: окно программы вперёд
        # или назад в игру; window_front — впереди ли окно программы (клавиша слушается и в нём).
        # Остальное в overlay — выбор игрока (OVERLAY_CHOICES): list, alt, clear.
        self.overlay = dict(overlay_from({}), can=False)
        self.window_toggle = None
        self.window_front = None
        # Обновление программы (update.Updater): есть только у окна программы (desktop.py) — сервер из исходников о новых
        # версиях не спрашивает. Его состояние — /api/update (шапка всех страниц) и поле update состояния «Игры».
        self.updater = None
        # Каталог одобренных планов (plancat.py): спрашивается вместе с проверкой обновлений (окно программы:
        # update.Updater.also) и когда игрок открывает «Каталог» в редакторе; файл плана — только по «Поставить» /
        # «Обновить». Ключ подписи — тот же, что у обновлений; нет его — каталог не спрашивается.
        self.plancat = plancat.Catalog(signed.embedded_key(), 'PoE2Runbook/%s' % (
            appversion.program((self.base_catalog or {}).get('version')) or '%s.%d' % (appversion.GAME, appversion.BUILD)))
        self._plancat_jobs = {}       # uid плана, который сейчас качается («Поставить» / «Обновить») -> 'load'
        self._shas = {}               # SHA-256 файла плана библиотеки (planlib.bundle_sha): id -> (отметка файлов, sha)
        self.shut_at = None           # когда нажата «Закрыть» в игре: страница убирает своё верхнее окно
        # Путевой камень, скопированный в игре: страница отвечает «идти / без босса / не идти». Плана для
        # ответа не нужно: класс опасности каждого аффикса лежит в базе знаний (knowledge/waystones.json),
        # файл перечитывается при изменении.
        self.way = None
        self.know_path = Path(knowledge_dir if knowledge_dir else ROOT / 'knowledge') / 'waystones.json'
        # Справочник игры: боссы, задания и награды по зонам (knowledge/landmarks.json). План ссылается на его
        # записи; файл перечитывается вместе с планом.
        self.marks_path = self.know_path.with_name('landmarks.json')
        # Шаблон кампании (knowledge/campaign.json): маршрут из того, что задаёт игра, — основа «Нового плана»
        self.template_path = self.know_path.with_name(planlib.TEMPLATE)
        self.marks = {}               # {id: запись}
        self.marks_game = None        # версия игры, для которой справочник составлен
        self.know = None
        self.know_problems = []
        self._know_mtime = False      # False — файл ещё не читали (None — читали, файла нет)
        self._names = {}              # названия плана на языке страницы: язык -> (признак, i18n.Names)
        self._geo_lang = {}           # файлы геометрии деревьев с названиями узлов на языке страницы (geo_file)
        self._words = (None, {}, {})  # слова игры на языке программы для событий лога (game_words): каталог, зоны, классы
        self.cond = threading.Condition()
        self.version = 0
        # Лог игры; None — игра не найдена (страница так и говорит). Папка игры, если её нашла или узнала программа:
        # по ней буфер и клавиша «Надеть» узнают окно игры. follow — как спросить Windows, из какой папки запущена
        # игра (None — не спрашивать: лог назван параметром); picker — окно выбора папки (есть только у окна
        # программы, desktop.py); settings_path — где программа помнит папку игры.
        self.log_path = Path(log_path) if log_path else None
        self.game_dir = None
        self.follow = None
        self.picker = None
        self.settings_path = None
        self.clip_source = None
        self.game_problem = None     # игрок указал папку, в которой игры нет: страница говорит это вместо статуса
        self._follow_at = 0.0
        self.plan_path = Path(plan_path)
        self.runs_dir = Path(runs_dir)
        self.filters_dir = Path(filters_dir) if filters_dir else None
        self.archive_dir = Path(archive_dir) if archive_dir else None
        self._fcache_key = None
        self._fcache = None
        self._fnames = (False, {})    # фильтры игры с названиями: (отметка файлов, {id: {name, inGame}}); False — ещё не читали
        self.parser = core.LogParser()
        self.run = core.Run()
        # Все забеги из лога по порядку (id -> Run); текущий — self.run. Забег начинает новый герой,
        # а вернуться к прежнему герою можно только словом игрока: в логе нет имени вошедшего.
        self.runs = {}
        self.session_ts = None   # когда в последний раз был экран выбора персонажа
        self.claims = {}         # время такого экрана -> id забега, который с него продолжается
        self._asc = {}           # счёт вознесений героя каждого забега
        self._sums = {}          # короткие сведения о забегах для списка на странице
        self._reviews = {}       # разборы времени героев (review_of): (забег, план) -> (признак свежести, разбор)
        self._run_times = {}     # нажатия «Шаг пройден» и паузы героев из их файлов: забег -> (время файла, списки)
        self._again = None       # где карты начинали заново, по всем героям (restarts_view): (признак свежести, данные)
        self.gone = set()        # забеги, о героях которых игрок сказал: его больше нет (погиб, удалён)
        # Атлас общий у героев одной лиги, а лигу лог не пишет: её называет игрок. atlas_links — забег ->
        # забег героя, чей атлас продолжает его герой, или '' — атлас новый; atlas_had — забег -> узлы,
        # которые игрок отметил взятыми до лога (runs/atlas.json)
        self.atlas_links, self.atlas_had = {}, {}
        self._aclicks = {}       # клики забегов по атласу до гибели героя: id -> (число событий, клики)
        self.load_claims()
        self.load_gone()
        self.load_atlas_words()
        self.load_run_plans()
        self.log_ok = False
        self.loop_error = None   # что сломалось в цикле чтения: пока он падает, «лог читается» было бы неправдой
        self.last_log_ts = None
        self.game_tag = None     # версия игры у игрока, как её называет лог при каждом запуске игры («0.5.5h»)
        self._pos = 0
        self._buf = b''

    # --- план -------------------------------------------------------------

    def _plan_stamp(self):
        """Время изменения файла плана, файлов его частей (маршрут, билд, личное), справочника игры и фильтров
        игры (их названия входят в план): изменился любой — план перечитывается. Файлу, которого пока нет на
        диске, соответствует None."""
        stamp = [self.plan_path.stat().st_mtime]
        for path in list(self._plan_parts) + [self.marks_path]:
            try:
                stamp.append(path.stat().st_mtime)
            except OSError:
                stamp.append(None)
        stamp.append(self._filters_stamp())
        return tuple(stamp)

    def _filters_stamp(self):
        """Файлы фильтров игры и их время: новый фильтр из аккаунта, удалённый или переименованный на сайте
        меняет отметку. None — папку фильтров игры не прочесть (не названа, нет игры на этой машине)."""
        try:
            return tuple(sorted((p.name, p.stat().st_mtime) for p in self.filters_dir.iterdir() if p.is_file()))
        except (OSError, AttributeError):
            return None

    def filter_names(self):
        """Фильтры игры с названиями: {id: {name, inGame}}. Фильтр игры — файл в её папке фильтров (имя файла —
        id фильтра, как его называет лог); название — из шапки файла, которую пишет сама игра (filter_header), поэтому
        игроку называть фильтры не нужно ('' — шапки нет). inGame: True — файл в папке, фильтр можно выбрать в игре;
        False — его там уже нет (удалён из аккаунта): такой называется по своей копии в архиве версий, если она есть,
        — чтобы прежние забеги и план называли его словами, а не кодом. Сначала названные фильтры игры по названию,
        потом без названия, потом прежние."""
        stamp = self._filters_stamp()
        if self._fnames[0] is not False and stamp == self._fnames[0]:
            return self._fnames[1]
        found = {name: {'name': filter_header(self.filters_dir / name).get('name', ''), 'inGame': True}
                 for name, _ in stamp or ()}
        gone = {}
        try:
            for path in sorted(self.archive_dir.glob('*_*_*.filter')):    # имя копии: <id>_<время>_<хеш>.filter
                fid = path.name.rsplit('_', 2)[0]
                head = filter_header(path)
                if fid not in found and head.get('name'):
                    gone[fid] = {'name': head['name'], 'inGame': False}      # последняя по времени копия — последней
        except (OSError, AttributeError):
            pass
        order = lambda kv: (not kv[1]['name'], (kv[1]['name'] or kv[0]).lower())   # noqa: E731
        names = dict(sorted(found.items(), key=order))
        names.update(sorted(gone.items(), key=order))
        self._fnames = (stamp, names)
        return names

    def plan_filters(self, raw):
        """Фильтры плана — фильтры игры (filter_names) и фильтры, названные шагами маршрута. Название фильтра
        в игре — из шапки его файла. Фильтра в игре нет (у игрока плана он ещё не подписан, у автора удалён из
        аккаунта) — название, которое шаг записал из игры автора (filterName), а нет его — с копии в архиве
        версий; inGame у такого — False, если папку фильтров игры видно, — иначе фильтр шага назывался бы кодом."""
        own = {}
        for s in raw.get('steps') or []:
            fid = s.get('filter') if isinstance(s, dict) else None
            if isinstance(fid, str) and fid and fid != core.NO_FILTER:
                name = s.get('filterName') if isinstance(s.get('filterName'), str) else ''
                if name or fid not in own:
                    own[fid] = name or own.get(fid) or ''
        names = self.filter_names()
        seen = self._fnames[0] is not None                      # папку фильтров игры видно
        out = {}
        for fid, rec in names.items():
            name = (rec['name'] or own.get(fid) or '') if rec['inGame'] else (own.get(fid) or rec['name'])
            out[fid] = dict(rec, name=name)
        for fid, name in own.items():
            if fid not in out:
                out[fid] = dict({'name': name}, **({'inGame': False} if seen else {}))
        return out

    def load_plan(self):
        """Перечитывает план, если изменился его файл или файл любой его части. Битый файл не ломает
        работу: показан прежний план и сказано, что не так."""
        try:
            stamp = self._plan_stamp()
        except OSError:
            changed = self.plan_error is None
            self.plan_error = tr('Файл плана не найден: %s') % self.plan_path
            return changed
        if stamp == self._plan_mtime:
            return False
        try:
            raw = json.loads(self.plan_path.read_text(encoding='utf-8-sig'))
            notes = []
            if planfiles.is_manifest(raw):
                # план из частей: plan.json — оглавление, сами маршрут и билд лежат в своих файлах
                self._plan_parts = list(planfiles.part_paths(self.plan_path, raw).values())
                parts = planfiles.read_parts(self.plan_path, raw)
                # справочник игры: на его записи (боссы, задания, награды) ссылаются цели маршрута
                self.marks, self.marks_game, notes = landmarks.load(self.marks_path)
                version = (self.base_catalog or {}).get('version')
                if self.marks and self.marks_game and version and self.marks_game != version:
                    notes.append(tr('Справочник игры составлен для версии %s, а данные игры — версии %s: сверьте его')
                                 % (self.marks_game, version))
                if raw.get('profile'):
                    # личного у плана больше нет: фильтр по шагам — поле шага маршрута
                    notes.append(tr('Личное больше не читается: фильтр — поле шага маршрута. Уберите из %s строку «profile»')
                                 % self.plan_path.name)
                raw, more = planfiles.compose(raw, parts.get('route'), parts.get('build'), self.marks)
                notes += more
            else:
                self._plan_parts = []
            # фильтры с названиями — из самой игры (шапка файла фильтра): план говорит, какой фильтр с какого шага
            if isinstance(raw, dict):
                raw = dict(raw, filters=self.plan_filters(raw))
            # свои статы билда встают в таблицу статов каталога — до проверки плана: этапы и цели на них ссылаются
            cat, more = gamedata.with_stats(self.base_catalog, raw.get('statDefs') if isinstance(raw, dict) else None)
            # справка игры о названных в плане вещах (уровень камня умения, уровень зоны базы, какая база даёт
            # умение) — из данных игры: автор её не пишет
            raw = gamedata.with_facts(self.base_catalog, raw)
            self.plan, problems = core.norm_plan(raw, cat)
            self.catalog = cat
            self.plan_problems = notes + more + problems
            self.plan_error = None
            # Реплики, которых ждёт план: новая фраза ловится в строках лога с этого момента,
            # а в уже прочитанных — после перезапуска программы (лог читается заново). Лог разбирается
            # по плану героя: план, открытый только в редакторе, реплик не задаёт.
            if self.book is self.active:
                self.parser.watch = core.heard_ids(self.plan)
            # Реплика плана — код строки таблицы игры: код, которого в данных игры нет (опечатка, старый план с
            # фразой вместо кода, строку убрали патчем), не услышится никогда — об этом говорит проверка плана.
            say = self.log_text.say or (gamedata.log_pack(self.base_catalog, 'en') or {}).get('say') or {}
            lost = [x for x in core.heard_ids(self.plan) if say and x not in say]
            if lost:
                self.plan_problems.append(tr('Реплик с такими кодами нет в данных игры: %s') % ', '.join(lost))
            # Награда плана — коды свойств игры (их же находит строка награды лога на любом языке клиента):
            # кода нет в описаниях свойств игры — награда не узнается никогда.
            stats = self.log_text.stat or (gamedata.log_pack(self.base_catalog, 'en') or {}).get('stat') or {}
            odd = sorted({k for g in self.plan.get('goals') or [] for k in core.reward_of(g)
                          if stats and k != logtext.POINTS and k not in stats})
            if odd:
                self.plan_problems.append(tr('Наград с такими кодами нет в данных игры: %s') % ', '.join(odd))
        except (ValueError, OSError) as e:
            self.plan_error = tr('План не прочитан, показан прежний: %s') % e
        except Exception as e:   # noqa: BLE001 — план не того вида, что ждёт программа: страница живёт, о плане сказано
            self.plan_error = tr('План не прочитан, показан прежний: %s') % type(e).__name__
            i18n.say('plan %s: %r' % (self.plan_path, e), flush=True)
        # отметка времени — уже с учётом частей, названных в только что прочитанном оглавлении
        try:
            self._plan_mtime = self._plan_stamp()
        except OSError:
            self._plan_mtime = None
        return True

    # --- библиотека планов --------------------------------------------------

    def library(self):
        """Планы библиотеки: [{id, title, cls, uid, received?, from?}] (planlib.summary) по id; без библиотеки — []."""
        if not self.plans_dir:
            return []
        stamp = planlib.stamp(self.plans_dir)
        if stamp != self._lib[0]:
            self._lib = (stamp, [planlib.summary(rec) for rec in planlib.scan(self.plans_dir)])
        return self._lib[1]

    def default_plan(self):
        """План, по которому идёт герой, о котором слова нет и чей предшественник неизвестен: первый в библиотеке."""
        lib = self.library()
        return lib[0]['id'] if lib else self.active.id

    def book_for(self, pid):
        """Книга плана pid (прочитанная, с отметкой времени файлов); None — такого плана в библиотеке нет.
        Без библиотеки — книга единственного плана."""
        if not self.plans_dir:
            return self.active
        path = planlib.manifest_path(self.plans_dir, pid)
        if path is None or not path.is_file():
            return None
        book = self.books.get(pid)
        if book is None:
            book = self.books[pid] = Book(path, pid)
            book.catalog = self.base_catalog
        saved, self.book = self.book, book
        try:
            self.load_plan()
        finally:
            self.book = saved
        return book

    @contextlib.contextmanager
    def editing(self, pid):
        """Запрос редактора о плане pid: пока он идёт, программа смотрит на книгу этого плана — всё, что
        редактор спрашивает и записывает, относится к нему, а не к плану героя. pid пустой — план героя.
        Нет такого плана — KeyError."""
        book = self.book_for(pid) if pid and self.plans_dir else self.active
        if book is None:
            raise KeyError(pid)
        saved, self.book = self.book, book
        try:
            yield book
        finally:
            self.book = saved

    def use_plan(self, pid):
        """Герой текущего забега идёт по плану pid: его книга становится действующей — по ней разбирается лог
        и собирается страница «Игра». Плана нет — первый в библиотеке. True — план сменился."""
        if not self.plans_dir:
            return False
        book = self.book_for(pid) or self.book_for(self.default_plan())
        if book is None or book is self.active:
            return False
        self.active = self.book = book
        self.parser.watch = core.heard_ids(self.plan)
        return True

    def plan_of(self, rid, ids=None):
        """id плана, по которому идёт герой забега rid: что сказал игрок или что получил новый герой. О забеге
        слова нет или его плана в библиотеке больше нет — первый план библиотеки. ids — id планов библиотеки,
        если уже собраны (для списка героев: библиотека читается один раз). Забега нет (rid пустой: лог ещё
        не начинал забег) — план, который игрок выбрал для первого героя (запись с пустым run)."""
        if ids is None:
            ids = [p['id'] for p in self.library()]
        rec = self.run_plans.get(rid if rid in self.runs else '')
        if rec and rec['plan'] in ids:
            return rec['plan']
        return ids[0] if ids else self.active.id

    def _run_plans_path(self):
        return self.runs_dir / 'plans.json'

    def load_run_plans(self):
        """Читает, по какому плану идёт каждый герой (runs/plans.json): это факт забегов, а не плана."""
        self.run_plans = {}
        try:
            saved = json.loads(self._run_plans_path().read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return
        for c in saved if isinstance(saved, list) else []:
            if isinstance(c, dict) and isinstance(c.get('run'), str) and isinstance(c.get('plan'), str):
                rec = {'plan': c['plan'], 'at': c['at'] if isinstance(c.get('at'), str) else None}
                if c.get('ask') is True:
                    rec['ask'] = True
                self.run_plans[c['run']] = rec

    def save_run_plans(self):
        try:
            self.runs_dir.mkdir(parents=True, exist_ok=True)
            data = [dict({'run': rid}, **rec) for rid, rec in sorted(self.run_plans.items())]
            tmp = self._run_plans_path().with_suffix('.tmp')
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')
            os.replace(tmp, self._run_plans_path())
            return True
        except OSError as e:
            i18n.say(tr('Не удалось записать план героя: %s') % e, flush=True)
            return False

    def give_plan(self, rid, prev):
        """Новый герой (забег rid) идёт по плану героя, которым играли до него (prev — id того забега). Если планов
        больше одного, страница спросит, так ли это (ask): ответ — выбор плана в шапке. Первый герой (забегов до
        него не было) берёт план, который игрок выбрал заранее, и не спрашивает; не выбирал — спросит."""
        if not self.plans_dir or rid in self.run_plans:
            return
        rec = {'plan': self.plan_of(prev), 'at': planlib.stamp_text()}
        chosen = prev not in self.runs and '' in self.run_plans
        if len(self.library()) > 1 and not chosen:
            rec['ask'] = True
        self.run_plans[rid] = rec
        self.save_run_plans()

    def bind_plan(self, pid):
        """Игрок выбрал план (строка списка планов, «Новый план»): текущий герой идёт по плану pid, и обе страницы —
        «Игра» и «Редактор» — о нём (новый герой — это ответ на вопрос «по какому плану?»). Героя ещё нет (лог
        не начинал забег) — по плану pid пойдёт первый герой. Отметки забега остаются в его файле: цели с теми же
        id (копия плана) остаются отмеченными, остальные вернутся, если герой вернётся к прежнему плану.
        Возвращает (получилось, замечания)."""
        if not self.plans_dir:
            return False, [tr('библиотеки планов нет: программа запущена с одним планом')]
        if not any(p['id'] == pid for p in self.library()):
            return False, [tr('плана «%s» нет') % pid]
        key = self.run.id if self.run.id in self.runs else ''
        before = self.run_plans.get(key)
        self.run_plans[key] = {'plan': pid, 'at': planlib.stamp_text()}
        if not self.save_run_plans():
            if before is None:
                self.run_plans.pop(key, None)
            else:
                self.run_plans[key] = before
            return False, [tr('план героя не записан')]
        self.use_plan(pid)
        if key:
            self.save_run()           # снимок плана в файле забега — уже нового
        self._bump()
        return True, []

    def in_game(self):
        """Герой текущего забега сейчас в игре: лог не сказал, что он вышел (экран персонажей, игра закрыта). Тогда
        смена плана переспрашивает: шаг, цели и фильтр шага станут по другому плану прямо в игре."""
        return self.run.id in self.runs and self.parser.in_game

    def plans_view(self, rows=None):
        """Планы для шапки обеих страниц: {library — есть ли библиотека, list — планы (planlib.summary) с heroes —
        сколько живых героев идёт по плану, current — выбранный план: по нему идёт текущий герой, его играет «Игра»
        и правит «Редактор», ask — новый герой ещё не сказал, по какому плану идёт, inGame — герой сейчас в игре:
        смена плана переспросит}. rows — забеги (run_list), если уже посчитаны."""
        # класс героя плана — словом клиента («Чародейка»): страница на другом языке переводит его, как класс из лога
        words = ((((self.base_catalog or {}).get('lang') or {}).get(i18n.SOURCE) or {}).get('heroClasses') or {})
        if not self.plans_dir:
            hero = (self.active.plan.get('hero') or {}) if isinstance(self.active.plan.get('hero'), dict) else {}
            return {'library': False, 'current': '', 'ask': False, 'inGame': False,
                    'list': [{'id': '', 'title': i18n.Raw(self.active.plan.get('title') or ''), 'cls': hero.get('class'),
                              'clsName': words.get(hero.get('class'), hero.get('class')), 'heroes': 1}]}
        rows = self.run_list() if rows is None else rows
        lib = self.library()
        ids = [p['id'] for p in lib]
        alive = {}
        for r in rows:
            if r['current'] or r['fate'] == 'alive':
                pid = self.plan_of(r['id'], ids)
                alive[pid] = alive.get(pid, 0) + 1
        rec = self.run_plans.get(self.run.id) or {}
        # в каталоге планов версия новее той, что у игрока: newer — её номер (редактор показывает «есть новая версия»)
        newer = {}
        with self.plancat.lock:
            entries = list((self.plancat.data or {}).get('plans') or ())
        for e in entries:
            p = next((x for x in lib if x.get('uid') == e['uid']), None)
            if p is not None and self.plancat_state(e, p)[0] == 'update':
                newer[p['id']] = e['version']
        return {'library': True, 'current': self.active.id, 'ask': bool(rec.get('ask')) and len(lib) > 1,
                'inGame': self.in_game(),
                'template': self.template_path.is_file(),          # есть шаблон кампании — основа «Нового плана»
                'list': [self._plan_row(p, heroes=alive.get(p['id'], 0), clsName=words.get(p['cls'], p['cls']),
                                        **({'newer': newer[p['id']]} if p['id'] in newer else {})) for p in lib]}

    @staticmethod
    def _plan_row(p, **more):
        """Строка плана для страницы: название плана, название того, с чего сделана копия, имя присланного файла и имя
        автора из каталога — слова людей, их не переводят (план «Ведьма · проба» на английской странице не становится
        «Witch · проба»)."""
        row = dict(p, title=i18n.Raw(p['title']), **more)
        if isinstance(p.get('from'), dict):
            row['from'] = dict(p['from'], title=i18n.Raw(p['from'].get('title') or ''))
        if isinstance(p.get('received'), dict):
            row['received'] = dict(p['received'], file=i18n.Raw(p['received'].get('file') or ''))
        if isinstance(p.get('catalog'), dict):
            row['catalog'] = dict(p['catalog'], author=dict(p['catalog']['author'], name=i18n.Raw(p['catalog']['author']['name'])))
        return row

    def copy_plan(self, src, title=None):
        """Копия плана src (новый план на базе готового): (id копии или None, замечания)."""
        if not self.plans_dir:
            return None, [tr('библиотеки планов нет: программа запущена с одним планом')]
        try:
            pid = planlib.copy(self.plans_dir, src, title)
        except (OSError, ValueError) as e:
            return None, [tr('копия не сделана: %s') % e]
        self._bump()
        return pid, []

    def import_plan(self, req):
        """Присланный файл плана — в библиотеку. req: {import — файл плана (planlib.FORMAT), file — его имя,
        replace — id присланного плана, который он обновляет, separate — добавить отдельным планом, даже если
        такой уже есть}. Ответ: {ok, plan, title} или {ok: false, same: план с той же меткой} (страница
        спрашивает, заменить ли его) или {ok: false, problems}."""
        if not self.plans_dir:
            return {'ok': False, 'problems': [tr('библиотеки планов нет: программа запущена с одним планом')]}
        data = req.get('import')
        if not (req.get('file') is None or isinstance(req.get('file'), str)) or not (
                req.get('replace') in (None, '', False) or isinstance(req.get('replace'), str)):
            return {'ok': False, 'problems': [tr('план не добавлен: %s') % tr('это не файл плана')]}
        try:
            planlib.parse_bundle(data)
            if req.get('replace'):
                pid = str(req['replace'])
                if planlib.manifest_path(self.plans_dir, pid) is None:
                    raise ValueError(tr('плана «%s» нет') % '?')
                planlib.replace(self.plans_dir, pid, data, req.get('file'), backup_dir=self.backup_dir / 'plans' / pid)
                fresh = False
            else:
                uid = None
                same = planlib.same(self.plans_dir, data)
                if same and not req.get('separate'):
                    if same.get('received'):
                        return {'ok': False, 'same': same}
                    uid = planlib.new_uid()      # свой же план вернулся файлом: отдельным планом, со своей меткой
                elif same:
                    uid = planlib.new_uid()
                pid = planlib.add(self.plans_dir, data, req.get('file'), uid=uid)
                fresh = True
        except (OSError, ValueError, TypeError) as e:
            return {'ok': False, 'problems': [tr('план не добавлен: %s') % e]}
        book = self.book_for(pid)
        if book is None or book.error:
            why = book.error if book is not None else tr('план не читается')
            if fresh:
                shutil.rmtree(self.plans_dir / pid, ignore_errors=True)
                self.books.pop(pid, None)
            return {'ok': False, 'problems': [tr('план не добавлен: %s') % why]}
        if book is self.active:
            self.load_plan()
        self._bump()
        return {'ok': True, 'plan': pid, 'title': book.plan.get('title') or pid}

    def remove_plan(self, pid):
        """Убирает план из библиотеки (папка — в backup/removed). Нельзя убрать последний план и план, по которому
        идёт живой герой. Возвращает (получилось, замечания)."""
        if not self.plans_dir:
            return False, [tr('библиотеки планов нет: программа запущена с одним планом')]
        lib = self.library()
        if not any(p['id'] == pid for p in lib):
            return False, [tr('плана «%s» нет') % pid]
        if len(lib) < 2:
            return False, [tr('это единственный план: убрать его нельзя')]
        users = [r.get('name') or core.fmt_ts(r['started']) for r in self.run_list()
                 if (r['current'] or r['fate'] == 'alive') and self.plan_of(r['id']) == pid]
        if users:
            return False, [tr('по этому плану идёт герой: %s — сначала дайте ему другой план или скажите «Нет героя»')
                           % ', '.join(users)]
        try:
            planlib.remove(self.plans_dir, pid, self.backup_dir / 'removed')
        except (OSError, ValueError) as e:
            return False, [tr('план не убран: %s') % e]
        self.books.pop(pid, None)
        if self.active.id == pid:
            # убран выбранный план (его герой погиб или его нет): выбран план, который теперь числится за героем
            self.use_plan(self.plan_of(self.run.id))
        self._bump()
        return True, []

    def plan_file(self, pid):
        """Файл плана pid для обмена (planlib.bundle) и имя файла; без библиотеки — единственный план."""
        if not self.plans_dir:
            raise ValueError(tr('библиотеки планов нет: программа запущена с одним планом'))
        data = planlib.bundle(self.plans_dir, pid)
        return data, '%s.plan.json' % pid

    def save_plan_file(self, pid):
        """Файл плана pid — в папку export рядом с библиотекой: для браузера, который файлы не скачивает (встроенный
        браузер приложения Claude). Ответ: {ok, path} или {ok: false, problems}."""
        try:
            data, name = self.plan_file(pid)
            folder = self.plans_dir.parent / 'export'
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / name
            tmp = path.with_name(name + '.tmp')
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')
            os.replace(tmp, path)
        except (OSError, ValueError) as e:
            return {'ok': False, 'problems': [tr('файл плана не записан: %s') % e]}
        return {'ok': True, 'path': i18n.Raw(str(path))}

    # --- каталог одобренных планов (plancat.py) --------------------------------

    def _bundle_sha(self, pid):
        """SHA-256 файла плана pid для обмена (planlib.bundle_sha) — пересчитывается, когда меняются его файлы."""
        mark = dict(planlib.stamp(self.plans_dir)).get(pid)
        if pid not in self._shas or self._shas[pid][0] != mark:
            self._shas[pid] = (mark, planlib.bundle_sha(self.plans_dir, pid))
        return self._shas[pid][1]

    def plancat_state(self, e, p):
        """Что запись каталога e значит для плана библиотеки p с той же меткой (None — такого плана нет): (state, have).
        state: new — плана у игрока нет («Поставить»); update — в каталоге версия новее («Обновить»); have — поставлен,
        та же версия; older — в каталоге версия старее поставленной (не ставится); own — у игрока СВОЙ план с этой
        меткой (его правит он сам — каталог его не меняет). have — версия у игрока (None — не известна). Полученный
        план без записи каталога (пришёл файлом или с программой) — та же версия, если его файл плана байт в байт как
        файл каталога."""
        if p is None:
            return 'new', None
        if not p.get('received'):
            return 'own', None
        have = (p.get('catalog') or {}).get('version')
        if have is None:
            return ('have', e['version']) if self._bundle_sha(p['id']) == e['sha256'] else ('update', None)
        return ('update' if e['version'] > have else 'have' if e['version'] == have else 'older'), have

    @staticmethod
    def plancat_record(e):
        """Запись каталога для оглавления плана (planlib catalog): версия и автор — из подписанного каталога."""
        rec = {'version': e['version'], 'author': dict(e['author']), 'at': planlib.stamp_text()}
        if e.get('published'):
            rec['published'] = e['published']
        return rec

    def plancat_sync(self):
        """Полученный план, который каталог узнал (та же метка, файл плана байт в байт как файл каталога), запоминает
        версию и автора из каталога (оглавление, planlib.set_catalog): автор виден в списке планов и без сети. Свои
        планы не трогаются. True — что-то записано."""
        if not self.plans_dir:
            return False
        with self.plancat.lock:
            entries = list((self.plancat.data or {}).get('plans') or ())
        done = False
        for e in entries:
            p = next((x for x in self.library() if x.get('uid') == e['uid']), None)
            if p is None or not p.get('received') or p.get('catalog') or self.plancat_state(e, p)[0] != 'have':
                continue
            try:
                planlib.set_catalog(self.plans_dir, p['id'], self.plancat_record(e))
                done = True
            except (OSError, ValueError) as x:
                i18n.say('plan catalogue: %s not marked: %s' % (p['id'], x), flush=True)
        return done

    def net_allowed(self):
        """Может ли программа сама спрашивать свой сайт — настройка «Проверять обновления»: у окна программы — как её
        поставил игрок (update.Updater.on), у сервера из исходников — по файлу настроек (settings.json: updates); нет
        его — да."""
        if self.updater is not None:
            return bool(self.updater.on)
        return appsettings.load(self.settings_path).get(update.SETTING) is not False

    def plancat_refresh(self, ask=False):
        """«Каталог» редактора. Открыли список планов — каталог спрашивается, только если программе можно спрашивать
        сайт самой (net_allowed), и не чаще plancat.FRESH; ask — игрок нажал «Спросить каталог»: спрашивается сразу и
        при выключенной настройке. True — запрос был (или прошлый был только что)."""
        if not ask and not self.net_allowed():
            return False
        self.plancat_check(5 if ask else plancat.FRESH)
        return True

    def plancat_check(self, fresh=None):
        """Спросить каталог планов (сеть — без замка программы) и запомнить у планов библиотеки, что из него узнано
        (plancat_sync). Зовут проверка обновлений по расписанию (update.Updater.also) и раздел «Каталог» редактора
        (fresh — не чаще). True — сайт ответил."""
        reached = self.plancat.check(fresh)
        with self.cond:
            if self.plancat_sync():
                self._bump()
        return reached

    # что ответил последний запрос каталога — строкой раздела «Каталог»
    PLANCAT_TEXTS = {
        'ok': tr('каталог получен'),
        'none': tr('в каталоге пока нет планов'),
        'net': tr('нет связи с сайтом программы'),
        'http': tr('сайт программы ответил ошибкой %s'),
        'tls': tr('защищённое соединение с сайтом программы не установлено'),
        'sig': tr('подпись не сошлась — файл не принят'),
        'format': tr('каталог не того вида — не принят'),
        'nokey': tr('в этой сборке нет ключа подписи — проверять нечем'),
        'error': tr('ошибка программы — подробности в журнале программы'),
    }
    # почему план из каталога не ставится
    PLANCAT_NO = {
        'have': tr('этот план уже поставлен — та же версия'),
        'older': tr('в каталоге версия старее поставленной — не ставится'),
        'own': tr('в библиотеке ваш план с этой меткой — каталог его не меняет'),
    }

    def plancat_view(self, lang):
        """Раздел «Каталог» редактора на языке lang: {can — в сборке есть ключ подписи (без него каталог не
        спрашивается), auto — программа спрашивает каталог сама (настройка «Проверять обновления» не выключена; иначе —
        только кнопкой «Спросить каталог»), library, busy — запрос идёт, game — версия игры программы, got — когда принят каталог, last —
        что ответил последний запрос {at, code, text}, list — планы каталога}. Строка плана: uid, version, title,
        author {name, url?}, cls / asc (названия из данных игры на языке страницы), game, other — для другой версии
        игры, published, summary, changed, state (plancat_state), have, plan — id в библиотеке, job — качается. Порядок:
        что обновить, что поставить, что уже стоит; внутри — новые раньше. Слова каталога не переводятся."""
        cat = self.plancat
        with cat.lock:
            data, got, busy = cat.data, cat.got, cat.busy
            last = dict(cat.last) if cat.last else None
        made = appversion.stem((self.base_catalog or {}).get('version'))
        names = ((((self.base_catalog or {}).get('lang') or {}).get(lang) or {}).get('heroClasses') or {})
        raw = lambda t: i18n.Raw(t or '')       # noqa: E731 — слова автора каталога: не переводятся
        lib = self.library()
        rows = []
        for e in (data or {}).get('plans') or ():
            p = next((x for x in lib if x.get('uid') == e['uid']), None)
            state, have = self.plancat_state(e, p) if self.plans_dir else ('new', None)
            author = {'name': raw(e['author']['name'])}
            if e['author'].get('url'):
                author['url'] = e['author']['url']
            rows.append({'uid': e['uid'], 'version': e['version'], 'title': raw(plancat.in_lang(e['title'], lang)),
                         'author': author, 'cls': raw(names.get(e['cls'], e['cls'])), 'asc': raw(names.get(e['asc'], e['asc'])),
                         'game': e['game'], 'other': bool(e['game'] and made and e['game'] != made),
                         'published': e['published'], 'summary': raw(plancat.in_lang(e['summary'], lang)),
                         'changed': raw(plancat.in_lang(e['changed'], lang)), 'state': state, 'have': have,
                         'plan': p['id'] if p else None, 'job': e['uid'] in self._plancat_jobs})
        rank = {'update': 0, 'new': 1}
        rows.sort(key=lambda r: (rank.get(r['state'], 2), -int((r['published'] or '0').replace('-', '')), str(r['title']).lower()))
        if last is not None:
            code = 'none' if last['code'] == 'http' and str(last['detail']) == '404' else last['code']
            text = self.PLANCAT_TEXTS.get(code, self.PLANCAT_TEXTS['error'])
            last = {'at': last['at'], 'code': code, 'text': text % last['detail'] if code == 'http' else text}
        return {'can': cat.point is not None, 'auto': self.net_allowed(), 'library': bool(self.plans_dir), 'busy': busy,
                'game': made or '', 'got': got, 'last': last, 'list': rows}

    def plancat_get(self, uid):
        """«Поставить» / «Обновить»: файл плана из каталога (скачан и сверен с подписанным каталогом — plancat.load) —
        в библиотеку обычным приёмом плана: новый план (planlib.add) или новая версия плана, который у игрока уже есть
        (planlib.replace: папка, id и метка остаются — герой идёт дальше по новой версии, его отметки — в его файле).
        Запоминаются версия и автор из каталога. Сеть — без замка программы. Ответ: {ok, plan, title, version, fresh}
        или {ok: false, problems}."""
        no = lambda text: {'ok': False, 'problems': [text]}        # noqa: E731
        if not self.plans_dir:
            return no(tr('библиотеки планов нет: программа запущена с одним планом'))
        with self.cond:
            e = self.plancat.entry(uid) if isinstance(uid, str) else None
            if e is None:
                return no(tr('этого плана нет в каталоге'))
            state = self.plancat_state(e, next((x for x in self.library() if x.get('uid') == uid), None))[0]
            if state not in ('new', 'update'):
                return no(self.PLANCAT_NO[state])
            if uid in self._plancat_jobs:
                return no(tr('этот план уже качается'))
            self._plancat_jobs[uid] = 'load'
        try:
            try:
                data = self.plancat.load(e)
            except plancat.Refused as x:
                i18n.say('plan catalogue: %s refused (%s %s)' % (uid, x.code, x.detail), flush=True)
                return no(tr('файл плана не сошёлся с каталогом — план не поставлен'))
            except update.NetError as x:
                i18n.say('plan catalogue: %s not loaded (%s %s)' % (uid, x.code, x.detail), flush=True)
                return no(tr('файл плана не скачан: %s') % (self.PLANCAT_TEXTS['http'] % x.detail if x.code == 'http'
                                                             else self.PLANCAT_TEXTS['tls'] if x.code == 'tls'
                                                             else self.PLANCAT_TEXTS['net']))
            with self.cond:
                p = next((x for x in self.library() if x.get('uid') == uid), None)
                state = self.plancat_state(e, p)[0]         # пока файл качался, библиотека могла измениться
                if state not in ('new', 'update'):
                    return no(self.PLANCAT_NO[state])
                record, old = self.plancat_record(e), None
                try:
                    if p is None:
                        pid = planlib.add(self.plans_dir, data, '', uid=uid, extra={'catalog': record})
                    else:
                        pid = p['id']
                        rec = next(r for r in planlib.scan(self.plans_dir) if r['id'] == pid)
                        old = (planlib.bundle(self.plans_dir, pid),
                               {k: rec['manifest'][k] for k in ('received', 'catalog') if k in rec['manifest']})
                        planlib.replace(self.plans_dir, pid, data, '', backup_dir=self.backup_dir / 'plans' / pid,
                                        extra={'catalog': record})
                except (OSError, ValueError, TypeError, StopIteration) as x:
                    return no(tr('план не поставлен: %s') % x)
                book = self.book_for(pid)
                if book is None or book.error:
                    why = book.error if book is not None else tr('план не читается')
                    if old is None:
                        shutil.rmtree(self.plans_dir / pid, ignore_errors=True)
                        self.books.pop(pid, None)
                    else:
                        # новая версия не читается — прежняя на место, как была (та же запись каталога)
                        planlib.replace(self.plans_dir, pid, old[0], '', backup_dir=self.backup_dir / 'plans' / pid,
                                        extra=old[1])
                        self.book_for(pid)
                    return no(tr('план не поставлен: %s') % why)
                if book is self.active:
                    self.load_plan()
                    if self.run.id in self.runs:
                        self.save_run()           # снимок плана в файле героя — уже новой версии
                self._bump()
                return {'ok': True, 'plan': pid, 'title': i18n.Raw(book.plan.get('title') or pid), 'version': e['version'],
                        'fresh': old is None}
        finally:
            with self.cond:
                self._plancat_jobs.pop(uid, None)

    def open_author(self, uid):
        """Страница автора плана из каталога — в браузере системы (окно «Каталог» во встроенном браузере приложения
        Claude). Адрес — только из подписанного каталога и только http(s); адрес от страницы не принимается."""
        e = self.plancat.entry(uid) if isinstance(uid, str) else None
        url = plancat.web_url((e or {}).get('author', {}).get('url'))
        if not url:
            return False
        try:
            return bool(self.opener(url))
        except Exception as x:   # noqa: BLE001 — браузер системы не открылся: странице говорим «не удалось»
            i18n.say('author page not opened: %s' % x, flush=True)
            return False

    # --- правка дерева ----------------------------------------------------

    def tree_geo(self, kind='tree'):
        """Данные дерева (kind: 'tree' — героя, 'atlas' — атласа) для проверки правок: виды узлов, соседи.
        Перечитываются, если файл изменился."""
        path = self.atlas_path if kind == 'atlas' else self.tree_path
        try:
            mtime = path.stat().st_mtime
            if self._geo.get(kind, (None, None))[0] != mtime:
                geo = treeplan.load_geo(path)
                if kind == 'atlas':
                    geo['opts'] = self.atlas_options()
                self._geo[kind] = (mtime, geo)
        except (OSError, ValueError, KeyError, IndexError):
            self._geo.pop(kind, None)
        return self._geo.get(kind, (None, None))[1]

    def atlas_options(self):
        """Сколько вариантов у каждого узла атласа с выбором: {id узла: число} — из текстов узлов
        (atlasstats.json). По ним проверяется номер выбранного варианта; файла нет — проверяется только,
        что это номер."""
        try:
            data = json.loads(self.atlasstats_path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return {}
        return {nid: len(v['opts']) for nid, v in data.items() if isinstance(v, dict) and v.get('opts')}

    def tree_lines(self):
        """Что даёт каждый узел дерева героя (treestats.json, строки из данных GGG): по ним видно, какой
        стат обнуляет дерево этапа («Maximum Life is 1»). Перечитывается, если файл изменился."""
        try:
            mtime = self.treestats_path.stat().st_mtime
            if self._tree_lines[0] != mtime:
                self._tree_lines = (mtime, json.loads(self.treestats_path.read_text(encoding='utf-8')))
        except (OSError, ValueError):
            self._tree_lines = (None, {})
        return self._tree_lines[1]

    # --- правка билда (страница /admin) ------------------------------------

    def build_view(self, lang=i18n.SOURCE):
        """Данные для страницы «Билд»: разделы билда, которые на ней правят, и из чего выбирать."""
        if not self.catalog or not self.catalog.get('stats'):
            return {'error': tr('нет каталога данных игры (catalog/data) — править билд не из чего')}
        parts = self.plan_parts() or {}
        geo = self.tree_geo('tree')
        view = buildplan.describe(self.catalog, self.plan, self.tree_lines(), lang, build=parts.get('build'),
                                  route=parts.get('route'),
                                  geo=geo, heard=self.heard_names())
        # отпечаток файлов, какими их прочла страница: запись она присылает с ним (см. plan_stamp)
        view['stamp'] = self.plan_stamp()
        # из чего выбирать узел с амулета в версии дерева: узлы зачарования и их рецепты (anoint.py) и слоты амулета
        view['anoint'] = dict(anoint.choices(self.catalog, geo, lang), slots=sorted(anoint.amulet_slots(self.catalog, self.plan)),
                              potentAtlas=anoint.potent_atlas(self.tree_geo('atlas'), lang))
        if parts.get('route') is not None:
            view.update(routeplan.describe(self.catalog, parts['route'], self.zone_names()))
            view['landmarks'] = landmarks.describe(self.marks)      # справочник игры: что предлагать шагу
            # из чего выбирать фильтр шага: фильтры игры с названиями из самих файлов (filter_names)
            view['gameFilters'] = [dict(rec, id=fid) for fid, rec in self.filter_names().items()]
        # проверка гайда по записанному плану (раздел «Проверка билда» и замечания у камней и вещей); пока
        # на странице есть несохранённые правки, она спрашивает проверку сама (/api/check)
        try:
            view['findings'] = buildcheck.run(self.catalog, self.plan, self.tree_lines(), geo, self.plan_problems, lang,
                                              zones=self.zones_seen())
        except (KeyError, TypeError, ValueError, AttributeError) as e:
            i18n.say(tr('Проверка гайда не посчитана: %s') % e, flush=True)
        # какие статы на каком этапе редкие: список этапа страница показывает так, как им пользуется
        # сравнение вещей (редкие решают по порядку, остальные складываются)
        try:
            view['rare'] = herostats.stage_rare(self.catalog, self.plan, self.tree_lines(), lang)
        except (KeyError, TypeError, ValueError, AttributeError, IndexError) as e:
            i18n.say(tr('Редкие статы этапов не посчитаны: %s') % e, flush=True)
        # атрибуты героя с каждой версией дерева, без вещей: их показывает вкладка «Дерево»
        try:
            view['treeAttrs'] = attrneed.versions_attrs(self.plan, self.tree_lines(), geo)
        except (KeyError, TypeError, ValueError, AttributeError, IndexError) as e:
            i18n.say(tr('Атрибуты версий дерева не посчитаны: %s') % e, flush=True)
        # класс героя по логу предлагается назвать в билде, только если этот герой и идёт по этому плану
        view['heroSeen'] = self.hero_seen() if self.book is self.active else {}
        # какой план правится (planId — папка в библиотеке, '' — программа с одним планом), что о нём известно
        # (присланный, чья копия) и планы с героями — для списка в шапке
        # (список в шапке показывают, а не правят: его слова — на языке страницы, как на «Игре»)
        shown = lambda x: i18n.render(x, lang, self.names(lang), plain=True)   # noqa: E731
        rows = self.run_list()
        view['planId'] = self.book.id
        view['planInfo'] = shown(next((self._plan_row(p) for p in self.library() if p['id'] == self.book.id), {}))
        view['plans'] = shown(self.plans_view(rows))
        view['runs'] = shown(rows)
        # Редактор показывает названия сам (пары «Русское (English)» из плана и списков выбора, зоны). Зона в плане
        # названа словами игры на языке программы (ru — из таблиц игры; этим словом редактор и называет новый шаг), лог
        # героя называл её так же (own: App.game_words), а зону, которую лог не называл, план — названием шага; на другом
        # языке игры к ним — название зоны на этом языке (here) и названия из игры на этом языке (gameNames).
        packs = (self.catalog or {}).get('lang') or {}
        ru = (packs.get(i18n.SOURCE) or {}).get('areas') or {}
        there = ((packs.get(lang) or {}).get('areas') or {}) if lang not in ('en', i18n.SOURCE) else {}
        for a in view.get('areas') or ():
            if ru.get(a.get('code')):
                a['ru'] = ru[a['code']]
            if there.get(a.get('code')):
                a['here'] = there[a['code']]
        if lang not in ('en', i18n.SOURCE):
            view['gameNames'] = self.names(lang).game_names(view)
        return dict(view, problems=list(self.plan_problems), error=self.plan_error)

    def zones_seen(self):
        """Уровни боевых зон, какими их видели забеги (лог): код зоны -> младший из виденных уровней. У зон, чей
        уровень растёт с порядком прохождения (ветки второго акта, острова четвёртого, интерлюдии), он выше, чем в
        данных игры: по нему проверка билда судит, что к шагу уже может выпасть (buildcheck.step_reach). Младший —
        потому что в зону возвращаются и позже, уже старше (испытание Сехем ради следующего вознесения)."""
        seen = {}
        for run in list(self.runs.values()) + [self.run]:
            for e in run.events:
                if e.get('type') == 'zone' and isinstance(e.get('code'), str) and core.is_int(e.get('level')):
                    seen[e['code']] = min(seen.get(e['code'], e['level']), e['level'])
        return seen

    def heard_names(self):
        """Названия узлов деревьев, как их называл лог игры (в любом из забегов): {id узла: название}. У узла,
        которого герой ни разу не брал, остаётся название из данных дерева."""
        heard = {}
        for run in list(self.runs.values()) + [self.run]:
            for e in run.events:
                if e.get('type') == 'passive' and e.get('name'):
                    heard[e['id']] = e['name']
        return heard

    def tree_section(self, kind, raw, build, users):
        """Раздел дерева (kind: 'tree' — героя, 'atlas' — атласа) для файла билда из того, что прислала страница
        «Билд»: {versions: полный набор версий [{id, name, nodes}]}. Атрибут каждого узла «Характеристика»
        страница присылает явно, поэтому прежний атрибут дерева «по умолчанию» из раздела уходит; страница,
        открытая до этой перемены, ещё присылает его полем attr — тогда раздел пишется по-старому.
        users — {id версии: [названия этапов, которые её назвали]}: такую версию убрать нельзя.
        Возвращает (раздел или None, замечания)."""
        geo = self.tree_geo(kind)
        if geo is None:
            return None, [tr('нет данных дерева (planner/static/%s.json)') % kind]
        if not isinstance(raw, dict):
            return None, [tr('%s: нужен набор версий') % (tr('атлас') if kind == 'atlas' else tr('дерево'))]
        tree = build.get(kind) if isinstance((build or {}).get(kind), dict) else {}
        # узлы с предметов (зачарование амулета) привязаны к слотам билда
        slots = {s['id'] for s in (build or {}).get('slots') or [] if isinstance(s, dict) and isinstance(s.get('id'), str)}
        versions, problems = treeplan.check_all(raw.get('versions'), users, geo, slots if kind == 'tree' else None)
        if problems:
            return None, problems
        names = treeplan.known_names(tree, self.heard_names())
        for v in versions:
            for x in v.get('items') or []:
                names.setdefault(x['id'], anoint.name_of(self.catalog, geo, x['id'], i18n.SOURCE, x['id']))
        old_page = kind == 'tree' and isinstance(raw.get('attr'), str)
        return treeplan.apply_all(tree, versions, names, geo, raw.get('attr') if old_page else None,
                                  drop_default=kind == 'tree' and not old_page), []

    def tree_users(self, kind, req):
        """Где версии дерева названы после этой правки: {id версии: [названия этапов]} — по этапам, присланным
        тем же запросом, а если этапы не присланы — по записанному плану."""
        if isinstance(req.get('stages'), list):
            return buildstage.users({'stages': [st for st in req['stages'] if isinstance(st, dict) and st.get('id')]}, kind)
        return buildstage.users(self.plan, kind)

    def hero_seen(self):
        """Класс и вознесение героя текущего забега, как их показывает лог: {class?, ascendancy?} — именами
        из данных дерева. Класс — по слову из строки уровня («Чародейка»), вознесение — по id взятых узлов
        вознесения (AscendancySorceress3…) или по тому же слову («Ученица Варашты»). Страница «Билд»
        предлагает назвать героя билда так же."""
        classes = (self.tree_geo('tree') or {}).get('classes') or {}
        words = {}
        for pack in ((self.catalog or {}).get('lang') or {}).values():
            for en, own in (pack.get('heroClasses') or {}).items():
                words[own] = en
        by_code = {a['id']: (cid, a['name']) for cid, c in classes.items() for a in c.get('ascendancies') or []}
        by_name = {name: cid for cid, name in by_code.values()}
        out = {}
        for e in self.run.events:
            if e.get('type') == 'level' and e.get('cls'):
                word = words.get(e['cls'], e['cls'])
                if word in classes:
                    out = {'class': word}
                elif word in by_name:
                    out = {'class': by_name[word], 'ascendancy': word}
            elif e.get('type') == 'passive' and e.get('op') == 'take' and str(e.get('id')).startswith(core.ASCENDANCY_NODE):
                code = max((c for c in by_code if e['id'].startswith(core.ASCENDANCY_NODE + c)), key=len, default=None)
                if code:
                    out = {'class': by_code[code][0], 'ascendancy': by_code[code][1]}
        return out

    def hero_words(self, hero):
        """Класс и вознесение героя словами клиента — для шапки страницы забега: (класс, вознесение).
        hero — герой из состояния забега (core.derive): cls и asc — слова лога, ascNode — последний взятый узел
        вознесения. Лог зовёт героя одним словом: до вознесения это класс («Чародейка»), после — вознесение
        («Ученица Варашты»), и новое слово приходит только со следующим уровнем. Поэтому вознесение,
        которого строка об уровне ещё не назвала, берётся по узлу (AscendancySorceress3…): чьё оно, знают
        данные дерева, а как его зовёт клиент — словарь каталога. Плана билда здесь нет: только лог."""
        cls, asc, node = hero.get('cls'), hero.get('asc'), hero.get('ascNode')
        classes = (self.tree_geo('tree') or {}).get('classes') or {}
        by_code = {a['id']: (cid, a['name']) for cid, c in classes.items() for a in c.get('ascendancies') or []}
        base_of = {name: cid for cid, name in by_code.values()}
        # словарь языка клиента — тот, что знает слово из лога: имя из данных дерева -> слово клиента
        own = next((pack['heroClasses'] for pack in ((self.catalog or {}).get('lang') or {}).values()
                    if cls and cls in (pack.get('heroClasses') or {}).values()), {})
        name_of = {word: name for name, word in own.items()}
        if cls and not asc and name_of.get(cls, cls) in base_of:
            # лог начался уже после вознесения: первое же слово — вознесение, класс — тот, чьё оно
            cls, asc = own.get(base_of[name_of.get(cls, cls)], base_of[name_of.get(cls, cls)]), cls
        if not asc and node:
            code = max((c for c in by_code if str(node).startswith(core.ASCENDANCY_NODE + c)), key=len, default=None)
            if code:
                asc = own.get(by_code[code][1], by_code[code][1])
                cls = cls or own.get(by_code[code][0], by_code[code][0])
        return cls, asc

    def open_filter(self, fid):
        """Открывает страницу фильтра на сайте игры в браузере системы — по нажатию «страница фильтра» там, где
        страница сама отдельную вкладку открыть не может: встроенный браузер открывает такие ссылки в той же
        вкладке, и страница программы сменилась бы сайтом. На сайте игрок подписывается на фильтр (Follow), а
        вошёл он на сайт в своём браузере. Адрес собирается здесь из кода фильтра — адреса от страницы программа
        не принимает."""
        if not (isinstance(fid, str) and core.RE_SITE_FILTER.fullmatch(fid)):
            return False
        try:
            return bool(self.opener(core.FILTER_PAGE % fid))
        except Exception as e:   # noqa: BLE001 — браузер системы не открылся: странице говорим «не удалось»
            i18n.say(tr('Страница фильтра не открыта: %s') % e, flush=True)
            return False

    def open_site(self):
        """Открывает официальный сайт программы (about.SITE) в браузере системы — по нажатию на адрес в окне «О программе»
        там, где страница сама отдельную вкладку открыть не может (как open_filter). Адрес — только свой."""
        try:
            return bool(self.opener(about.SITE))
        except Exception as e:   # noqa: BLE001 — браузер системы не открылся: странице говорим «не удалось»
            i18n.say('official site not opened: %s' % e, flush=True)
            return False

    def about_view(self):
        """Что показывает окно «О программе»: версия программы и игры, под которую она сделана, автор, официальный адрес,
        какие тексты лицензий лежат в папке программы, сторонние компоненты сборки (about.view)."""
        made = (self.base_catalog or {}).get('version')
        return about.view(appversion.program(made), appversion.stem(made))

    def now_zone(self):
        """Зона, где герой текущего забега сейчас: {code, name — как зону назвал лог} или {}, если забег
        ещё не начат. Редактор плана предлагает её первой, когда шагу маршрута выбирают зону."""
        for e in reversed(self.run.events):
            if e.get('type') == 'zone' and e.get('code'):
                return {'code': e['code'], 'name': e.get('name') or ''}
        return {}

    def zone_names(self):
        """Названия зон, как их называл лог игры (в любом из забегов): {код зоны: название}. По ним страница
        подписывает зону на языке игрока: в данных игры названия зон только английские."""
        names = {}
        for run in list(self.runs.values()) + [self.run]:
            for e in run.events:
                if e.get('type') == 'zone' and e.get('name') and e.get('code'):
                    names.setdefault(e['code'], e['name'])
        return names

    def point_names(self):
        """Названия зон для точек перехода: как зону называл лог игры (в любом из забегов), а не называл — как она
        названа в слое языка каталога (русские названия из таблиц игры: новичок, у которого лога ещё нет, видит
        «Грельвуд», а не «The Grelwood»; страница на другом языке переводит их, как названия из лога), а нет и там —
        английским названием данных игры."""
        names = {code: a['name'] for code, a in ((self.base_catalog or {}).get('areas') or {}).items()
                 if isinstance(a, dict) and a.get('name')}
        own = (((self.base_catalog or {}).get('lang') or {}).get(i18n.SOURCE) or {}).get('areas') or {}
        names.update({code: name for code, name in own.items() if isinstance(name, str) and name})
        names.update(self.zone_names())
        return names

    def plan_stamp(self):
        """Отпечаток файлов плана, который сейчас правят (оглавление и его части), какими они лежат на диске. Страница
        редактора получает его вместе с планом и присылает при записи: не совпал — файлы изменились после того, как
        страница их прочла (запись из другой вкладки, правка программой), и такая запись затёрла бы те правки целиком.
        None — файлы не читаются."""
        h = hashlib.sha1()
        try:
            raw = json.loads(self.plan_path.read_text(encoding='utf-8-sig'))
            paths = [self.plan_path] + (list(planfiles.part_paths(self.plan_path, raw).values())
                                        if planfiles.is_manifest(raw) else [])
            for p in paths:
                h.update(Path(p).read_bytes())
        except (OSError, ValueError, TypeError):
            return None
        return h.hexdigest()[:16]

    def plan_parts(self):
        """Части плана как они лежат в файлах: {'manifest', 'route', 'build'}. None — план одним
        файлом (без частей) или части не читаются: тогда цели билда со страницы не правятся."""
        try:
            raw = json.loads(self.plan_path.read_text(encoding='utf-8-sig'))
            if not planfiles.is_manifest(raw):
                return None
            parts = dict(planfiles.read_parts(self.plan_path, raw), manifest=raw)
            # Файл билда старого вида (classes и gear у слота, until и gear у его целей) страница получает уже
            # в новом — с периодами слотов (slotwear); oldWear — на диске он ещё старый: при записи слотов или
            # целей переписываются оба раздела.
            new = slotwear.upgrade(parts.get('build'), (parts.get('route') or {}).get('steps'))
            if new is not parts.get('build'):
                parts['build'], parts['oldWear'] = new, True
            return parts
        except (OSError, ValueError):
            return None

    def compose_with(self, parts, sections):
        """План, каким он станет с такими разделами билда (название, герой, свои статы, слоты, этапы, цели)
        и таким маршрутом (route): (план в рабочем виде, каталог с его своими статами, замечания сборки)."""
        build, route = parts['build'], parts.get('route')
        for key in buildplan.SECTIONS + buildplan.TREES:
            if key in sections:
                build = dict(build, **{key: sections[key]})
        if 'route' in sections:
            route = dict(route or {}, **sections['route'])
        composed, notes = planfiles.compose(parts['manifest'], route, build, self.marks)
        composed = dict(composed, filters=self.plan_filters(composed))     # названия фильтров — из игры (load_plan)
        cat, more = gamedata.with_stats(self.base_catalog, composed.get('statDefs'))
        composed = gamedata.with_facts(self.base_catalog, composed)
        plan, problems = core.norm_plan(composed, cat)
        return plan, cat, notes + more + problems

    def plan_with(self, parts, sections):
        """Замечания к плану, каким он станет с такими разделами (compose_with), — только новые: тех, что
        у плана уже есть, страница не добавила."""
        return [p for p in self.compose_with(parts, sections)[2] if p not in self.plan_problems]

    def check_build(self, req, lang=i18n.SOURCE):
        """Замечания проверки гайда к плану, каким он станет с присланными разделами (check_page)."""
        return self.check_page(req, lang)['findings']

    def check_page(self, req, lang=i18n.SOURCE):
        """Проверка гайда для страницы «Билд»: {findings — замечания (buildcheck) к плану, каким он станет
        с присланными разделами; rare — какие статы на каком этапе такого плана редкие
        (herostats.stage_rare); treeAttrs — атрибуты героя с каждой версией дерева такого плана
        (attrneed.versions_attrs); обоих нет, если план не собрался}. Разделы — те же, что при записи, но ничего
        не пишется и не проверяется построчно: план собирается так же, как из файлов, и всё, что в нём
        не сходится, уходит в замечания."""
        geo, lines = self.tree_geo('tree'), self.tree_lines()
        parts = self.plan_parts()
        keys = buildplan.PAYLOAD + buildplan.TREES + ('route',)
        if not parts or not isinstance(req, dict) or not any(k in req for k in keys):
            return {'findings': buildcheck.run(self.catalog, self.plan, lines, geo, self.plan_problems, lang, zones=self.zones_seen()),
                    'rare': herostats.stage_rare(self.catalog, self.plan, lines, lang),
                    'treeAttrs': attrneed.versions_attrs(self.plan, lines, geo)}
        sections = {k: req[k] for k in keys if k in req}
        more = []
        try:
            # деревья приходят набором версий: в раздел файла их превращает та же проверка, что и при записи;
            # не прошло — дерево остаётся прежним, а почему, сказано замечанием
            for kind in buildplan.TREES:
                if kind in sections:
                    new, found = self.tree_section(kind, sections.pop(kind), parts['build'], self.tree_users(kind, req))
                    more += found
                    if new is not None:
                        sections[kind] = new
            for key, kind in (('goals', list), ('route', dict)):
                if key in sections and not isinstance(sections[key], kind):
                    raise ValueError(tr('раздел %s прислан не так') % key)
            if 'route' in sections and not isinstance(sections['route'].get('steps'), list):
                raise ValueError(tr('у маршрута нет шагов'))
            plan, cat, problems = self.compose_with(parts, sections)
            return {'findings': buildcheck.run(cat, plan, lines, geo, more + problems, lang, zones=self.zones_seen()),
                    'rare': herostats.stage_rare(cat, plan, lines, lang),
                    'treeAttrs': attrneed.versions_attrs(plan, lines, geo)}
        except (KeyError, TypeError, ValueError, AttributeError, IndexError) as e:
            return {'findings': [{'kind': 'plan', 'level': 'bad', 'text': tr('план с такими правками не собирается: %s') % e}]}

    def save_build(self, req):
        """Правка плана со страницы «Билд»: присланные разделы билда (название, герой, свои статы, слоты,
        этапы, цели) целиком
        записываются в файл билда, маршрут (route: шаги — с фильтром шага — и их цели) — в файл маршрута.
        Возвращает (получилось, замечания). Ничего не записано, если хоть что-то не прошло проверку: тексты
        всех файлов готовятся заранее, пишутся в конце."""
        if not self.catalog or not self.catalog.get('stats'):
            return False, [tr('нет каталога данных игры')]
        if isinstance(req, dict) and 'profile' in req:
            # страница прежнего вида (открыта до обновления программы): личного больше нет
            return False, [tr('личное больше не правится: фильтр — поле шага маршрута. Обновите страницу редактора')]
        if not isinstance(req, dict) or not any(k in req for k in buildplan.PAYLOAD + buildplan.TREES + ('route',)):
            return False, [tr('нечего записывать: нет ни одного раздела плана')]
        parts = self.plan_parts()
        sections, problems = {}, []
        # Деревья (версии дерева героя и атласа) — первыми: этапы, присланные тем же запросом, могут называть
        # версию, которая только что создана.
        trees = {}
        for kind in buildplan.TREES:
            if kind not in req:
                continue
            if not parts:
                problems.append(tr('деревья правятся только у плана из частей (маршрут, билд)'))
                break
            new, found = self.tree_section(kind, req[kind], parts['build'], self.tree_users(kind, req))
            problems += found
            if new is not None:
                trees[kind] = new
        # свои статы билда, какими они станут после этой правки: этапы, цели и награды маршрута сверяются с ними
        cat = gamedata.with_stats(self.base_catalog, req['statDefs'])[0] if 'statDefs' in req else self.catalog
        ids = lambda goals: {g.get('id') for g in goals or [] if isinstance(g, dict)}   # noqa: E731
        if 'route' in req:
            if not parts:
                problems.append(tr('маршрут правится только у плана из частей (маршрут, билд)'))
            else:
                # id целей шага и целей билда не должны совпасть: берём те цели билда, что придут этим же запросом
                taken = ids(req['goals']) if isinstance(req.get('goals'), list) else ids(parts['build'].get('goals'))
                # фильтр шага выбирают из фильтров игры: их названия шаг записывает себе (routeplan.check_steps)
                filters = {fid: rec['name'] for fid, rec in self.filter_names().items() if rec['inGame']}
                sections['route'] = routeplan.check(req['route'], parts.get('route'), taken, problems,
                                                    stats=set((cat.get('stats') or {}).get('stats') or {}), marks=self.marks,
                                                    filters=filters)
        if any(k in req for k in buildplan.PAYLOAD):
            route, plan = (parts or {}).get('route'), self.plan
            for kind, sec in trees.items():
                plan = dict(plan, **{kind: dict(plan.get(kind) or {}, phases=sec['phases'])})
            if 'route' in sections and sections['route']:
                # маршрут пришёл этим же запросом: разделы билда сверяются уже с его шагами и их целями
                route = dict(route or {}, **sections['route'])
                plan = dict(plan, steps=sections['route']['steps'])
            sec, found = buildplan.check({k: req[k] for k in buildplan.PAYLOAD if k in req}, plan, cat,
                                         build=(parts or {}).get('build'), route=route, geo=self.tree_geo('tree'))
            sections.update(sec)
            problems += found
        if not problems and parts:
            problems += self.plan_with(parts, dict(sections, **trees))
        if problems:
            return False, problems
        try:
            writes = []                 # (файл, новый текст, метка порядка байтов, вид копии)
            mine = {k: v for k, v in sections.items() if k != 'route'}
            if parts and parts.get('oldWear') and ('slots' in mine or 'goals' in mine):
                # файл старого вида: слоты и цели переписываются вместе — период слота и срок его целей
                # не расходятся (раздел, которого страница не прислала, берётся переведённым в новый вид)
                mine.setdefault('slots', parts['build']['slots'])
                mine.setdefault('goals', parts['build']['goals'])
            paths = planfiles.part_paths(self.plan_path, parts['manifest']) if parts else {}
            if mine or trees:
                path = self.tree_file()
                text, bom = buildplan.read_text(path)
                new = buildplan.render_sections(text, mine)
                for kind, sec in trees.items():
                    new = treeplan.splice(new, sec, kind)
                if new != text:             # страница присылает разделы целиком: файл, где ничего не изменилось, не трогаем
                    writes.append((path, new, bom, 'build'))
            if 'route' in sections:
                text, bom = buildplan.read_text(paths['route'])
                new = routeplan.render(text, sections['route'])
                if new != text:
                    writes.append((paths['route'], new, bom, 'route'))
            for path, text, bom, tag in writes:
                buildplan.write_text(path, text, bom, self.book_backup(), tag)
        except (OSError, ValueError, AttributeError, TypeError, KeyError) as e:
            return False, [tr('план не записан: %s') % e]
        if self.load_plan():
            self._bump()
        return True, []

    def save_plan(self, pid, req):
        """Правка редактора — в план pid ('' — план героя). Правится только свой план: присланный — только для
        просмотра (он остаётся, каким его прислали, и новая версия от автора ложится поверх); чтобы его менять,
        делают свой план на его основе («Новый план»). Ответ: {ok, problems, plan — id плана}."""
        with self.editing(pid) as book:
            target = book.id
            info = next((p for p in self.library() if p['id'] == book.id), {})
        if info.get('received'):
            return {'ok': False, 'plan': target,
                    'problems': [tr('присланный план только для просмотра — чтобы его менять, сделайте свой план на его основе')]}
        with self.editing(target):
            ok, problems = self.save_build(req)
        return {'ok': ok, 'problems': problems, 'plan': target}

    def new_plan(self, req):
        """«Новый план» — единственный способ завести свой план. req: {title — название, base — 'template' (шаблон
        кампании) или id плана библиотеки, take — 'all' (план целиком) или 'route' (только маршрут, билд пустой)}.
        У шаблона берётся только маршрут. Ответ: {ok, plan} или {ok: false, problems}."""
        if not self.plans_dir:
            return {'ok': False, 'problems': [tr('библиотеки планов нет: программа запущена с одним планом')]}
        title = req.get('title').strip()[:120] if isinstance(req.get('title'), str) else ''
        base, take = req.get('base'), req.get('take')
        if not title:
            return {'ok': False, 'problems': [tr('у нового плана нет названия')]}
        if take not in ('all', 'route'):
            return {'ok': False, 'problems': [tr('непонятно, что взять: план целиком или только маршрут')]}
        try:
            if base == 'template':
                text = self.template_path.read_bytes().decode('utf-8-sig')
                route_id = json.loads(text).get('id') or 'campaign'
                pid = planlib.create(self.plans_dir, title, text, planlib.empty_build(title, route_id),
                                     planlib.TEMPLATE_GROUPS, {'template': 'campaign'})
            else:
                rec = next((r for r in planlib.scan(self.plans_dir) if r['id'] == base), None)
                if rec is None:
                    return {'ok': False, 'problems': [tr('плана «%s» нет') % base]}
                if take == 'all':
                    pid = planlib.copy(self.plans_dir, base, title)
                else:
                    info = planlib.summary(rec)
                    paths = planfiles.part_paths(rec['path'], rec['manifest'])
                    text = buildplan.read_text(paths['route'])[0]
                    route_id = json.loads(text).get('id') or 'campaign'
                    groups = rec['manifest'].get('groups') if isinstance(rec['manifest'].get('groups'), list) else None
                    pid = planlib.create(self.plans_dir, title, planlib.route_only(text), planlib.empty_build(title, route_id),
                                         groups, {'uid': info['uid'] or '', 'title': info['title'], 'take': 'route'})
        except (OSError, ValueError, KeyError) as e:
            return {'ok': False, 'problems': [tr('план не создан: %s') % e]}
        book = self.book_for(pid)
        if book is None or book.error:
            shutil.rmtree(self.plans_dir / pid, ignore_errors=True)
            self.books.pop(pid, None)
            return {'ok': False, 'problems': [tr('план не создан: %s') % (book.error if book else tr('план не читается'))]}
        # новый план — сразу выбранный: по нему идёт текущий герой, его играет «Игра» и правит «Редактор»
        ok, problems = self.bind_plan(pid)
        self._bump()
        return {'ok': True, 'plan': pid, 'problems': problems}

    def book_backup(self):
        """Куда класть прежние версии файлов плана, который сейчас правится: у плана библиотеки — своя папка
        (backup/plans/<id>): части разных планов называются одинаково (route.json, build.json)."""
        return self.backup_dir / 'plans' / self.book.id if self.plans_dir else self.backup_dir

    def tree_file(self):
        """Файл, в котором записано дерево плана: билд (план из частей) или сам файл плана."""
        raw = json.loads(self.plan_path.read_text(encoding='utf-8-sig'))
        if planfiles.is_manifest(raw):
            return planfiles.part_paths(self.plan_path, raw).get('build')
        return self.plan_path

    # --- база знаний ------------------------------------------------------

    def load_know(self):
        """Перечитывает базу знаний о путевых камнях, если её файл изменился. Нет каталога данных игры —
        нет и аффиксов камней: тогда файл не читается и замечаний о нём нет."""
        if not self.catalog or not self.catalog.get('waystones'):
            return False
        try:
            stamp = self.know_path.stat().st_mtime
        except OSError:
            stamp = None
        if stamp == self._know_mtime:
            return False
        self._know_mtime = stamp
        self.know, self.know_problems = waystone.load_knowledge(self.know_path, self.catalog)
        return True

    # --- настройки игры ---------------------------------------------------

    def load_config(self):
        """Читает из настроек игры выбранный фильтр, язык клиента и клавиши, которые игра держит за собой (клавиши
        страницы в игре берутся из свободных). Возвращает True, если фильтр или язык изменились."""
        if not self.config_path:
            return False
        try:
            mtime = self.config_path.stat().st_mtime
            if mtime == self._config_mtime:
                return False
            self._config_mtime = mtime
            value, lang = None, None
            with open(self.config_path, encoding='utf-8-sig', errors='replace') as f:
                text = f.read()
            for line in text.splitlines():
                if line.startswith('item_filter='):
                    value = line.split('=', 1)[1].strip()
                elif line.startswith('language='):
                    lang = line.split('=', 1)[1].strip()
        except OSError:
            return False
        keys = clip.pick_keys(clip.game_keys(text), clip.ALL_KEYS)
        if keys != self.key_choice:
            self.key_choice = keys
            self._bump()
        self.copy_mod = clip.game_key(text, 'show_advanced_item_descriptions') or clip.VK_MENU
        changed = value != self.selected_filter
        self.selected_filter = value
        return self.set_client_lang(lang) or changed

    def set_client_lang(self, code):
        """Язык клиента из настроек игры: лог дальше читается его строками. Код, которого нет среди языков
        каталога (или настройки его не называют), узнаётся по самому логу — по системным строкам. Язык сменился,
        когда лог уже прочитан, — лог перечитывается заново. Возвращает True, если язык сменился."""
        langs = (self.base_catalog or {}).get('logs') or []
        lang = logtext.CONFIG_LANGS.get((code or '').strip().lower())
        if lang not in langs:
            lang = self.detect_client_lang() or lang
        if lang == self.client_lang:
            return False
        self.client_lang = lang
        self.log_text = logtext.LogText(gamedata.log_pack(self.base_catalog, lang), lang or 'ru')
        if self._pos:
            self.replay()
        else:
            self.parser = core.LogParser(core.heard_ids(self.plan) if self.plan else (), self.log_text)
        return True

    def detect_client_lang(self):
        """Язык клиента по последним строкам лога (уровень героя, награда, гибель, очки умений); не узнан — None."""
        if not self.log_path:
            return None
        try:
            with open(self.log_path, 'rb') as f:
                f.seek(max(0, os.path.getsize(self.log_path) - 3_000_000))
                lines = f.read().decode('utf-8', 'replace').splitlines()
        except OSError:
            return None
        return logtext.detect(lines, gamedata.log_msgs(self.base_catalog))

    def stat_lines(self, lang):
        """Тексты свойств игры для поля «Награда в логе» редактора на языке страницы: {коды свойств: текст с «#»
        на месте чисел}; плюс очки пассивных умений (logtext.POINTS). Языка в каталоге нет — английские."""
        if lang not in self._stats:
            pack = gamedata.log_pack(self.base_catalog, lang) or gamedata.log_pack(self.base_catalog, 'en') or {}
            out = {logtext.POINTS: tr('очки пассивных умений')} if pack else {}
            for key, temps in (pack.get('stat') or {}).items():
                if temps:
                    out[key] = logtext.stat_text(temps[0])
            self._stats[lang] = {k: i18n.to(v, lang) if k == logtext.POINTS else v for k, v in out.items()}
        return self._stats[lang]

    def speech_lines(self, lang):
        """Реплики игры для редактора на языке страницы: {код строки: «Имя: текст»}. Языка в каталоге нет —
        английские; каталога нет — пусто."""
        if lang not in self._speech:
            pack = gamedata.log_pack(self.base_catalog, lang) or gamedata.log_pack(self.base_catalog, 'en') or {}
            t = logtext.LogText(pack, lang)
            out = {}
            for lid, row in (pack.get('say') or {}).items():
                who = sorted(t.speakers(lid))
                out[lid] = ('%s: %s' % (who[0], logtext.clean(row[0])) if who else logtext.clean(row[0]))
            self._speech[lang] = out
        return self._speech[lang]

    # --- лог --------------------------------------------------------------

    def poll_log(self, initial=False):
        """Дочитывает новые строки лога. Возвращает True, если что-то изменилось."""
        try:
            if not self.log_path:
                raise FileNotFoundError('no game')
            size = os.path.getsize(self.log_path)
        except OSError:
            changed = self.log_ok
            self.log_ok = False
            return changed
        changed = not self.log_ok
        self.log_ok = True
        if size < self._pos:
            # Файл лога начат заново (его удалили): читаем сначала, а забег в памяти остаётся как есть.
            self._pos, self._buf = 0, b''
            self.game_tag = None
            self.parser = core.LogParser(core.heard_ids(self.plan), self.log_text)
        if size == self._pos:
            return changed
        with open(self.log_path, 'rb') as f:
            f.seek(self._pos)
            data = f.read(size - self._pos)
        self._pos += len(data)
        lines = (self._buf + data).split(b'\n')
        self._buf = lines.pop()
        for raw in lines:
            line = raw.decode('utf-8', 'replace').rstrip('\r')
            ts = core.line_ts(line)
            if ts is not None and ts != self.last_log_ts:
                self.last_log_ts = ts
                changed = True
            tag = appversion.game_tag(line)
            if tag and tag != self.game_tag:
                self.game_tag = tag       # игра назвала свою версию: так она делает при каждом запуске
                changed = True
            for ev in self.parser.feed(line):
                self._apply(ev, initial)
        return changed

    def replay(self):
        """Собирает забеги заново, перечитав лог с начала — так же, как при запуске.

        Нужно после слова игрока «сейчас играю этим героем»: события текущей сессии переходят
        в выбранный забег, а самый надёжный способ их переложить — тот же разбор, что и при запуске.
        """
        self._pos, self._buf = 0, b''
        self.game_tag = None
        self.parser = core.LogParser(core.heard_ids(self.plan), self.log_text)
        self.run = core.Run()
        self.runs, self._asc, self._sums, self.session_ts = {}, {}, {}, None
        self._aclicks = {}
        self._reviews = {}       # разборы считались по событиям прежнего прочтения лога
        self._again = None
        self.poll_log(initial=True)
        self.use_plan(self.plan_of(self.run.id))
        self.attach_run()

    # --- где игра -------------------------------------------------------------

    def set_game(self, game_dir, log):
        """Игра в другой папке (её запустили оттуда или её указал игрок): лог читается этот — с начала, забеги
        собираются заново, как при запуске; буфер и клавиша «Надеть» узнают окно игры по этой папке; папку
        программа запоминает."""
        self.game_dir, self.log_path = Path(game_dir), Path(log)
        self.game_problem = None
        self.log_ok, self.last_log_ts = False, None
        src = self.clip_source
        if src is not None and hasattr(src, 'game_dir'):
            src.game_dir = os.path.normcase(os.path.abspath(str(game_dir)))
            src._front = None
        self.replay()
        try:
            appsettings.update(self.settings_path, gameDir=str(self.game_dir))
        except OSError:
            pass
        i18n.say(tr('Лог игры: %s (%s)') % (self.log_path, tr('читается') if self.log_ok else tr('НЕ НАЙДЕН')), flush=True)
        self._bump()

    def choose_game(self, path):
        """Папка, которую игрок указал в окне выбора: сама папка игры, её logs или папка, где лежит папка игры.
        Ответ — {ok, problems}; игры там нет — страница говорит это строкой состояния, пока игру не найдут."""
        game = gamepaths.game_at(path)
        if not game:
            self.game_problem = tr('в этой папке нет лога игры: %s') % i18n.Raw(str(path))
            self._bump()
            return {'ok': False, 'problems': [self.game_problem]}
        self.set_game(game, gamepaths.log_in(game))
        return {'ok': True, 'problems': []}

    def follow_game(self):
        """Игра запущена не из той папки, чей лог читается (второй клиент, игра нашлась только теперь), — лог
        берётся её. Windows спрашивается не чаще раза в две секунды. Возвращает True, если лог сменился."""
        if not self.follow:
            return False
        now = time.monotonic()
        if now < self._follow_at:
            return False
        self._follow_at = now + 2.0
        running = self.follow()
        if not running or gamepaths.same(running, self.game_dir):
            return False
        log = gamepaths.log_in(running)
        if not log:
            return False
        self.set_game(running, log)
        return True

    def _session(self, ts, initial):
        """Экран выбора персонажа: дальше может играть другой герой.

        Сам лог героя не называет, поэтому без слова игрока сессия продолжает тот же забег. Если игрок
        сказал про эту сессию «играю героем забега X» (claims), с этого места события идут в X.
        """
        self.session_ts = ts
        self._asc[self.run.id] = self.parser.ascension_state()
        target = self.runs.get(self.claims.get(ts))
        if target is None or target is self.run:
            return
        self.run = target
        self.use_plan(self.plan_of(target.id))      # у того героя может быть свой план: лог дальше — по нему
        self.parser.set_ascension_state(self._asc.get(target.id))
        # Фильтр в игре общий для всех героев: загруженный при другом герое действует и здесь.
        loaded = [e['id'] for e in target.events if e['type'] == 'filter' and e.get('ok', True)]
        last = self.parser.last_filter
        if last and (not loaded or loaded[-1] != last):
            target.events.append({'type': 'filter', 'ts': ts, 'id': last, 'ok': True, 'carried': True})
        if not initial:
            self.attach_run()

    def _apply(self, ev, initial):
        if ev['type'] == 'start':
            prev = self.run.id
            self.run = core.Run(core.run_id(ev['ts']), ev['ts'])
            self.runs[self.run.id] = self.run
            # новый герой идёт по плану героя, которым играли до него (или по тому, что сказал игрок)
            self.give_plan(self.run.id, prev)
            self.use_plan(self.plan_of(self.run.id))
            if not initial:
                self.attach_run()
                i18n.say(tr('Новый герой: %s') % core.fmt_ts(ev['ts']), flush=True)
            return
        if ev['type'] == 'session':
            self._session(ev['ts'], initial)
            return
        self.game_words(ev)
        self.run.events.append(ev)
        if not initial:
            self.save_run()
            if ev['type'] == 'filter':
                self.archive_filter(ev)

    def game_words(self, ev):
        """Слова клиента в событии лога — словами игры на языке программы (i18n.SOURCE): название зоны — по её коду,
        класс и Восхождение героя — по слою языка каталога, который знает это слово. Лог пишет их на языке клиента
        игрока, а программа считает на своём языке и переводит на выходе: зона, которую английский клиент назвал
        «Clearfell», на русской странице — «Клирфелл», на немецкой — названием из немецких таблиц игры. Чего данные
        игры не знают (зона новее каталога), остаётся словом лога."""
        cat = self.base_catalog or {}
        if self._words[0] is not cat:
            packs = cat.get('lang') or {}
            src = packs.get(i18n.SOURCE) or {}
            classes = {}
            for pack in packs.values():
                for en, word in (pack.get('heroClasses') or {}).items():
                    if isinstance(word, str) and word:
                        classes.setdefault(word, (src.get('heroClasses') or {}).get(en) or en)
            self._words = (cat, dict(src.get('areas') or {}), classes)
        _, areas, classes = self._words
        if ev.get('type') == 'zone' and areas.get(ev.get('code')):
            ev['name'] = areas[ev['code']]
        elif ev.get('type') == 'level' and ev.get('cls') in classes:
            ev['cls'] = classes[ev['cls']]

    # --- файл фильтра -----------------------------------------------------

    def archive_filter(self, ev):
        """Сохраняет копию только что загруженной версии фильтра, чтобы версии можно было сравнить.

        Игра переписывает файл в момент загрузки, поэтому копия берётся, только если время
        файла совпадает со временем загрузки из лога.
        """
        if not (self.filters_dir and self.archive_dir and ev.get('ok', True) and ev.get('hash')):
            return None
        src = self.filters_dir / ev['id']
        try:
            if abs(src.stat().st_mtime - ev['ts']) > 120:
                return None
            # Та же версия (тот же хеш) уже сохранена — второй копии не нужно.
            if self.archive_dir.is_dir():
                same = sorted(self.archive_dir.glob('%s_*_%s.filter' % (ev['id'], ev['hash'][:8])))
                if same:
                    return same[0]
            name = '%s_%s_%s.filter' % (ev['id'], core.run_id(ev['ts']), ev['hash'][:8])
            dst = self.archive_dir / name
            self.archive_dir.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(src.read_bytes())
            return dst
        except OSError as e:
            i18n.say(tr('Не удалось сохранить версию фильтра: %s') % e, flush=True)
            return None

    def _filter_blocks(self, fid):
        """Разобранный файл текущего фильтра; перечитывается, когда файл изменился."""
        if not (self.filters_dir and fid):
            return None
        path = self.filters_dir / fid
        try:
            key = (str(path), path.stat().st_mtime)
            if key != self._fcache_key:
                self._fcache = filtereval.parse(path)
                self._fcache_key = key
            return self._fcache
        except OSError:
            return None

    def filter_check(self, level=None):
        """Что текущий фильтр сделает с целями плана в зоне такого уровня: {id цели: show / hide / unsure}. Уровень
        называет сборка состояния (core.ground_level: в городе на шаге без боевой зоны — шаг впереди); без него —
        уровень последней боевой зоны."""
        fid, last = core.current_filter_and_level(self.run)
        if level is None:
            level = last
        if self.selected_filter is not None:
            fid = None if self.selected_filter in ('None', '') else self.selected_filter
        blocks = self._filter_blocks(fid)
        if not blocks:
            return {}
        ground = {}
        slots = {s.get('id'): s for s in self.plan.get('slots') or [] if isinstance(s, dict)}
        for g in self.plan['goals']:
            item = self._ground_item(g, level, slots)
            if item is not None:
                ground[g['id']] = filtereval.state(filtereval.verdict(blocks, item))
        return ground

    def _ground_item(self, g, level, slots):
        """Предмет цели, каким он лежал бы на земле в зоне такого уровня, — образец для проверки фильтра. None —
        проверять нечего: предмет здесь не падает (иначе фильтр прокачки, который белое скрывает, «скрывал» бы белые
        базы для карт с первого акта) или о нём сказано не всё.
        Предмет слота, название которого игра знает: базу называет сама цель (gamedata.ground_base) — точное
        название даёт эту базу, общее («Ростовой щит») — ту из баз, что падает на этом уровне; уровень базы и её
        защита — из данных игры; класс — как его называет таблица классов игры (gamedata.filter_class); редкость —
        параметр цели (rarity): не выбрана — проверки нет.
        Прежняя запись образца (probe) читается там, где параметра нет: у цели по стату и у названия не из игры
        («жёлтый щит») — целиком; у предмета без выбранной редкости — её редкость."""
        cat = self.base_catalog
        p = g.get('probe') if isinstance(g.get('probe'), dict) and g['probe'].get('Class') else None
        known, base = gamedata.ground_base(cat, g, gamedata.slot_classes(slots.get(g.get('slot'))), level) if cat else (False, None)
        if not known:
            if not p or (isinstance(p.get('DropLevel'), (int, float)) and level < p['DropLevel']):
                return None
            return filtereval.gear(p['Class'], p.get('Rarity', 'Magic'), level, p.get('BaseType'), DropLevel=p.get('DropLevel'))
        rarity = g.get('rarity') or (p.get('Rarity', 'Magic') if p else None)
        if base is None or rarity not in filtereval.RANK:
            return None
        word = gamedata.filter_class(cat, base.get('class'))
        if not word and p:
            # каталог собран до таблицы классов: слово класса — из прежней записи образца, если она о том же классе
            was = gamedata.fact_index(cat)['bases'].get(p.get('BaseType')) or []
            if not was or any(x.get('class') == base.get('class') for x in was):
                word = p['Class']
        if not word:
            return None
        return filtereval.gear(word, rarity, level, base['name'], DropLevel=base.get('level') or 1,
                               **gamedata.base_defences(base))

    # --- файл забега ------------------------------------------------------

    def _run_path(self, run=None):
        return self.runs_dir / ('%s.json' % (run or self.run).id)

    def attach_run(self, run=None):
        """Подхватывает отметки забега (без указания — текущего), если они уже были сохранены."""
        run = run or self.run
        try:
            saved = json.loads(self._run_path(run).read_text(encoding='utf-8'))
            marks = saved.get('marks') or []
            moves = saved.get('moves') or []
            run.marks = [m for m in marks if isinstance(m, dict) and 'goal' in m and m.get('status') in (0, 1, 2)]
            run.moves = [m for m in moves if isinstance(m, dict) and 'step' in m and 'ts' in m]
            hold = saved.get('hold') or []
            run.hold = [h for h in hold if isinstance(h, dict) and isinstance(h.get('ts'), (int, float))
                        and not isinstance(h.get('ts'), bool) and isinstance(h.get('on'), bool)]
            worn = saved.get('worn')
            run.worn = {k: e for k, e in (worn if isinstance(worn, dict) else {}).items()
                        if isinstance(k, str) and isinstance(e, dict) and isinstance(e.get('item'), dict)
                        and isinstance(e['item'].get('mods'), list)}
            run.told = saved.get('cannotLine') is True
            picks = saved.get('picks')
            run.picks = {k: a for k, a in (picks if isinstance(picks, dict) else {}).items()
                         if isinstance(k, str) and a in wearcheck.ATTRS}
            off = saved.get('off')
            run.off = {k: t for k, t in (off if isinstance(off, dict) else {}).items()
                       if isinstance(k, str) and isinstance(t, (int, float)) and not isinstance(t, bool)}
        except (OSError, ValueError, AttributeError):
            run.marks, run.moves, run.worn, run.told, run.picks, run.off = [], [], {}, False, {}, {}
            run.hold = []
        self.save_run(run)

    def save_run(self, run=None):
        run = run or self.run
        # план этого героя: у текущего — действующий, у другого (покинутый при смене героя) — его собственный
        book = self.active if run is self.run or not self.plans_dir else (self.book_for(self.plan_of(run.id)) or self.active)
        try:
            self.runs_dir.mkdir(parents=True, exist_ok=True)
            data = {
                'id': run.id,
                'started': run.started,
                'startedText': core.fmt_ts(run.started),
                'events': run.events,
                'marks': run.marks,
                'moves': run.moves,
                # пауза игрока: «Пауза» / «Продолжить» на странице — [{'ts', 'on'}]
                'hold': run.hold,
                # Надетые вещи целиком — как их скопировал и подтвердил «надеть» игрок (herostats.py).
                'worn': run.worn,
                # клиент пишет в тексте вещи, что герой не может ею пользоваться: такую строку уже видели
                'cannotLine': run.told,
                # что игрок взял в узлах «Характеристика» не по плану: узел -> атрибут
                'picks': run.picks,
                # умения, которые игрок снял сам (кнопка «Снять» на шаге «Снять»): цель -> когда
                'off': getattr(run, 'off', None) or {},
                # План героя на момент сохранения: при разборе видно, по какому плану и с какой его версией шёл
                # забег (planId — папка плана в библиотеке; '' — программа работала с одним планом).
                'planId': book.id,
                'plan': book.plan,
            }
            tmp = self._run_path(run).with_suffix('.tmp')
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')
            os.replace(tmp, self._run_path(run))
        except OSError as e:
            i18n.say(tr('Не удалось сохранить данные героя: %s') % e, flush=True)

    # --- несколько забегов ------------------------------------------------

    def _claims_path(self):
        return self.runs_dir / 'switches.json'

    def load_claims(self):
        """Читает слова игрока «с этого входа в игру идёт забег X» — они переживают перезапуск."""
        self.claims = {}
        try:
            saved = json.loads(self._claims_path().read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return
        for c in saved if isinstance(saved, list) else []:
            if not isinstance(c, dict) or not isinstance(c.get('run'), str):
                continue
            ts = c.get('ts')
            if isinstance(ts, (int, float)) and not isinstance(ts, bool):
                self.claims[float(ts)] = c['run']

    def save_claims(self):
        try:
            self.runs_dir.mkdir(parents=True, exist_ok=True)
            data = [{'ts': ts, 'at': core.fmt_ts(ts), 'run': rid} for ts, rid in sorted(self.claims.items())]
            tmp = self._claims_path().with_suffix('.tmp')
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')
            os.replace(tmp, self._claims_path())
            return True
        except OSError as e:
            i18n.say(tr('Не удалось записать смену героя: %s') % e, flush=True)
            return False

    def _gone_path(self):
        return self.runs_dir / 'gone.json'

    def load_gone(self):
        """Читает слова игрока «героя этого забега больше нет» — они переживают перезапуск."""
        self.gone = set()
        try:
            saved = json.loads(self._gone_path().read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return
        for c in saved if isinstance(saved, list) else []:
            if isinstance(c, dict) and isinstance(c.get('run'), str):
                self.gone.add(c['run'])

    def mark_gone(self, req):
        """Игрок говорит о герое забега: его больше нет ({'run': id, 'on': true}) — или: он есть (on: false).
        Лог об удалённом герое молчит, а о гибели говорит не всегда (герой погиб, когда программа лог
        не читала). Текущему забегу такое сказать нельзя: им сейчас играют."""
        rid, on = str(req.get('run')), bool(req.get('on'))
        if rid not in self.runs or (on and rid == self.run.id) or on == (rid in self.gone):
            return False
        before = set(self.gone)
        (self.gone.add if on else self.gone.discard)(rid)
        try:
            self.runs_dir.mkdir(parents=True, exist_ok=True)
            data = [{'run': r, 'started': core.fmt_ts(self.runs[r].started) if r in self.runs else None} for r in sorted(self.gone)]
            tmp = self._gone_path().with_suffix('.tmp')
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')
            os.replace(tmp, self._gone_path())
        except OSError as e:
            i18n.say(tr('Не удалось записать пометку героя: %s') % e, flush=True)
            self.gone = before
            return False
        self._bump()
        return True

    # --- атлас лиги -------------------------------------------------------
    # Дерево атласа — общее у всех героев одной лиги учётной записи: новый герой получает его открытым.
    # Лог пишет только клики и лигу не называет, поэтому чей атлас продолжает герой, говорит игрок — одним
    # словом на героя. Взятое до героя — клики тех героев из того же лога. Узлы, взятые до начала лога,
    # игрок отмечает на карте сам.

    def _atlas_words_path(self):
        return self.runs_dir / 'atlas.json'

    def load_atlas_words(self):
        """Читает слова игрока об атласах — они переживают перезапуск."""
        self.atlas_links, self.atlas_had = {}, {}
        try:
            saved = json.loads(self._atlas_words_path().read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return
        if not isinstance(saved, dict):
            return
        links, had = saved.get('from'), saved.get('had')
        for rid, src in (links if isinstance(links, dict) else {}).items():
            if isinstance(rid, str) and isinstance(src, str) and src != rid:
                self.atlas_links[rid] = src
        for rid, nodes in (had if isinstance(had, dict) else {}).items():
            if isinstance(rid, str) and isinstance(nodes, list):
                nodes = list(dict.fromkeys(n for n in nodes if isinstance(n, str)))
                if nodes:
                    self.atlas_had[rid] = nodes

    def save_atlas_words(self):
        try:
            self.runs_dir.mkdir(parents=True, exist_ok=True)
            data = {
                # забег -> забег героя, чей атлас продолжает его герой (та же лига), или '' — атлас новый
                'from': dict(sorted(self.atlas_links.items())),
                # забег -> узлы атласа, которые игрок отметил взятыми до лога
                'had': {rid: nodes for rid, nodes in sorted(self.atlas_had.items()) if nodes},
            }
            tmp = self._atlas_words_path().with_suffix('.tmp')
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')
            os.replace(tmp, self._atlas_words_path())
            return True
        except OSError as e:
            i18n.say(tr('Не удалось записать слово об атласе: %s') % e, flush=True)
            return False

    @staticmethod
    def _atlas_group(rid, links):
        """Забеги с тем же атласом, что у забега rid: связанные словом игрока в любую сторону. Герой, чей атлас
        продолжили, тоже видит клики продолжившего: атлас один на двоих, они могут играть и вперемешку."""
        near = {}
        for a, b in links.items():
            if b and a != b:
                near.setdefault(a, set()).add(b)
                near.setdefault(b, set()).add(a)
        seen, todo = {rid}, [rid]
        while todo:
            for x in near.get(todo.pop(), ()):
                if x not in seen:
                    seen.add(x)
                    todo.append(x)
        return seen

    def _atlas_clicks(self, run):
        """Клики забега по атласу — до гибели его героя: погибший в «Хардкоре» уходит в обычную лигу, и дальше
        его клики — по её атласу (список забегов так же считает гибель окончательной, run_list)."""
        got = self._aclicks.get(run.id)
        if got and got[0] == len(run.events):
            return got[1]
        name, out = None, []
        for e in run.events:
            if e['type'] == 'level':
                name = name or e.get('name')
            elif e['type'] == 'death' and (not name or not e.get('name') or e['name'] == name):
                break
            elif e['type'] == 'passive' and str(e.get('id', '')).startswith(core.ATLAS_NODE):
                out.append(dict(e, run=run.id))
        self._aclicks[run.id] = (len(run.events), out)
        return out

    def atlas_league(self):
        """Что было в атласе до героя текущего забега (core.atlas_fold): клики героев того же атласа и отметки
        игрока — со всех забегов этого атласа; данные атласа — для проверки «взят не рядом со взятым»."""
        group = self._atlas_group(self.run.id, self.atlas_links)
        geo = self.tree_geo('atlas')
        return {
            'clicks': [c for rid in sorted(group) if rid != self.run.id and rid in self.runs
                       for c in self._atlas_clicks(self.runs[rid])],
            'marks': [n for rid in sorted(group) for n in self.atlas_had.get(rid, [])],
            'near': geo['near'] if geo else None,
            'roots': {i for i, k in geo['kind'].items() if k == treegeo.START} if geo else (),
            'names': geo['name'] if geo else {},
        }

    def atlas_offers(self):
        """Чей атлас может продолжать герой текущего забега: по одному на атлас, у которого в логе есть клики
        (забеги, связанные словом игрока, — один атлас), свежие первыми. run — забег героя, кликавшего
        последним; nodes — сколько узлов взято; on — его продолжает герой сейчас."""
        links = {a: b for a, b in self.atlas_links.items() if a != self.run.id}
        mine = self._atlas_group(self.run.id, links)
        now = self._atlas_group(self.run.id, self.atlas_links)
        seen, out = set(mine), []
        for rid in self.runs:
            if rid in seen:
                continue
            group = self._atlas_group(rid, links)
            seen |= group
            clicks = [c for r in sorted(group) if r in self.runs for c in self._atlas_clicks(self.runs[r])]
            if not clicks:
                continue
            fold = core.atlas_fold([], {'clicks': clicks, 'marks': [n for r in sorted(group) for n in self.atlas_had.get(r, [])]})
            last = max(clicks, key=lambda c: c['ts'])
            out.append({'run': last['run'], 'nodes': len(fold['taken']), 'last': last['ts'], 'on': bool(group & now)})
        out.sort(key=lambda o: -o['last'])
        return out

    def atlas_answer(self, req):
        """Игрок говорит, чей атлас у героя текущего забега: {'run': id} — тот же, что у героя забега id (та же
        лига), или {'run': ''} — атлас новый."""
        rid = req.get('run')
        if not (rid == '' or (isinstance(rid, str) and rid in self.runs and rid != self.run.id)):
            return False
        before = dict(self.atlas_links)
        self.atlas_links[self.run.id] = rid
        if not self.save_atlas_words():
            self.atlas_links = before
            return False
        self._bump()
        return True

    def atlas_mark(self, req):
        """Игрок отмечает узел атласа взятым до лога ({'node': id, 'on': true}) — или снимает отметку (on: false;
        снимается у всех забегов того же атласа). Отметка — слово игрока, не лог: страница рисует её иначе."""
        geo = self.tree_geo('atlas')
        node, on = req.get('node'), bool(req.get('on'))
        if not geo or not isinstance(node, str) or geo['kind'].get(node) in (None, treegeo.START):
            return False
        before = {rid: list(nodes) for rid, nodes in self.atlas_had.items()}
        if on:
            group = self._atlas_group(self.run.id, self.atlas_links)
            if any(node in self.atlas_had.get(rid, []) for rid in group):
                return False
            self.atlas_had.setdefault(self.run.id, []).append(node)
        else:
            hit = [rid for rid in self._atlas_group(self.run.id, self.atlas_links) if node in self.atlas_had.get(rid, [])]
            if not hit:
                return False
            for rid in hit:
                self.atlas_had[rid] = [n for n in self.atlas_had[rid] if n != node]
        if not self.save_atlas_words():
            self.atlas_had = before
            return False
        self._bump()
        return True

    def switch_run(self, rid):
        """Игрок говорит: сейчас играю героем забега rid.

        Действует с последнего экрана выбора персонажа, а не с момента нажатия: всё, что герой успел
        сделать после входа, переходит в его забег и уходит из того, куда попало по ошибке. Новый герой
        (первая зона на 1 уровне) по-прежнему начинает свой забег сам.
        """
        if rid not in self.runs or rid == self.run.id or self.session_ts is None:
            return False
        if next(r['fate'] for r in self.run_list() if r['id'] == rid) != 'alive':
            return False        # погибшим или удалённым героем играть нельзя
        left = self.run.id
        before = dict(self.claims)
        self.claims[self.session_ts] = rid
        if not self.save_claims():
            self.claims = before
            return False
        self.replay()
        if self.run.id != rid:
            # В этой сессии создан новый герой — она его, а не выбранного забега: слово не принято.
            self.claims = before
            self.save_claims()
            self.replay()
            self._bump()
            return False
        # Журнал покинутого забега тоже переписывается: чужие события из него ушли, отметки остались.
        if left in self.runs:
            self.attach_run(self.runs[left])
        i18n.say(tr('Снова тот же герой: %s') % core.fmt_ts(self.run.started), flush=True)
        self._bump()
        return True

    def run_list(self):
        """Забеги из лога для списка на странице: чей, когда начат, докуда дошёл и можно ли им играть.

        Играть нельзя погибшим героем (в лиге «Хардкор» гибель окончательна) и удалённым: имя героя
        в игре занято, пока герой есть, поэтому забег, чьё имя носит более новый забег, — герой,
        которого уже удалили. О герое, про которого лог ничего такого не сказал, это говорит игрок
        (mark_gone): у такого забега byHand — пометку можно снять.
        """
        out = []
        for run in self.runs.values():
            n = len(run.events)
            got = self._sums.get(run.id)
            if not got or got[0] != n:
                zone = cls = name = None
                level, deaths = 1, []
                for e in run.events:
                    if e['type'] == 'zone':
                        zone = e['name']
                    elif e['type'] == 'level':
                        # имя — по первой строке об уровне: если этим забегом по ошибке «поиграл»
                        # другой герой (забыли переключить), его имя забегу не достанется
                        level, cls, name = e['level'], e['cls'], name or e.get('name')
                    elif e['type'] == 'death':
                        deaths.append(e)
                # гибель считается, если это гибель героя забега (имя совпало или ещё неизвестно)
                died = [d for d in deaths if not name or not d.get('name') or d['name'] == name]
                last = run.events[-1]['ts'] if run.events else run.started
                # имя героя дал игрок: на странице на другом языке оно не переводится, даже если совпало со словом игры
                got = (n, {'id': run.id, 'started': run.started, 'name': i18n.Raw(name) if name else name, 'level': level, 'cls': cls,
                           'zone': zone, 'last': last, 'died': died[-1]['ts'] if died else None,
                           # сколько забег занял чистого времени — по нему сравнивают забеги между собой: у погибшего —
                           # до гибели (что лог писал после неё — уже не эта игра); паузы героя, которым сейчас не
                           # играют, — из его файла (review_run). Так же время героя считает «Разбор».
                           'spent': core.clean_time(run.events, run.started, died[0]['ts'] if died else last,
                                                    (self.review_run(run.id) or run).hold)})
                self._sums[run.id] = got
            row = dict(got[1], current=run is self.run)
            if row['current'] and not row['died']:
                # текущий забег ещё идёт: его время — на сейчас
                row['spent'] = core.clean_time(run.events, run.started, time.time(), run.hold)
            out.append(row)
        newest = {}
        for row in out:
            if row['name']:
                newest[row['name']] = row['id']
        ids = [p['id'] for p in self.library()] if self.plans_dir else []
        for row in out:
            said = row['id'] in self.gone and not row['current']
            row['fate'] = ('dead' if row['died'] else
                           'gone' if said or (row['name'] and newest[row['name']] != row['id']) else 'alive')
            if said and not row['died']:
                row['byHand'] = True
            if self.plans_dir:
                # по какому плану идёт герой; '' — его план из библиотеки убран (так бывает только у погибших)
                rec = self.run_plans.get(row['id'])
                row['plan'] = '' if rec and rec['plan'] not in ids else self.plan_of(row['id'], ids)
        return out

    # --- разбор времени героя (режим «Разбор») ----------------------------
    # Куда ушло время героя — по шагам его плана и по месту: зоны шага, город, вне маршрута (review.py). Разбирать
    # можно любого героя из лога, и погибшего: его события — в логе, а нажатия «Шаг пройден» и паузы — в его файле.
    # Это только чтение: героя, которым играют, план и файлы забегов разбор не меняет.

    def review_run(self, rid):
        """Забег героя rid для разбора (None — такого нет): события — из лога, как у всей программы; нажатия «Шаг
        пройден» и паузы героя, которым сейчас не играют, — из его файла (в памяти они только у текущего). Файла нет
        (герой играл, когда программа не работала) — нажатий и пауз у него нет."""
        run = self.runs.get(rid)
        if run is None or run is self.run:
            return run
        path = self._run_path(run)
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return run
        hit = self._run_times.get(rid)
        if not hit or hit[0] != mtime:
            def timed(x):
                return isinstance(x, dict) and isinstance(x.get('ts'), (int, float)) and not isinstance(x.get('ts'), bool)
            moves, hold = run.moves, run.hold
            try:
                saved = json.loads(path.read_text(encoding='utf-8'))
                moves = [m for m in saved.get('moves') or [] if timed(m) and 'step' in m]
                hold = [h for h in saved.get('hold') or [] if timed(h) and isinstance(h.get('on'), bool)]
            except (OSError, ValueError, AttributeError):
                pass
            hit = self._run_times[rid] = (mtime, (moves, hold))
        copy = core.Run(run.id, run.started)
        copy.events, (copy.moves, copy.hold) = run.events, hit[1]
        return copy

    def review_of(self, rid, book):
        """Разбор времени героя rid по плану книги book — для страницы (review.page) и кто он: id, name, cls, asc
        (словами клиента), level, started, fate — 'dead' (погиб), 'now' (им играют) или 'left' (им больше не играют).
        None — такого героя нет. Считается заново, когда у героя прибавилось событий, нажатий или пауз либо изменился
        план; у героя, которым играют, — каждый раз: его время идёт."""
        run = self.review_run(rid)
        if run is None:
            return None
        end, dead = review.end_of(run)
        current = self.runs.get(rid) is self.run
        live = current and not dead
        stamp = (len(run.events), len(run.moves), len(run.hold), repr(book.mtime))
        hit = self._reviews.get((rid, book.id))
        if hit and hit[0] == stamp and not live:
            return hit[1]
        now = time.time() if live else end
        v = core.derive(book.plan, run, now or 0, own_level=self.own_level, zone_levels=self.zone_levels)
        data = review.page(review.split(book.plan, run, v['posLog'], now if live else None))
        hero = v['hero']
        cls, asc = self.hero_words(hero)
        data.update({'id': rid, 'name': i18n.Raw(hero['name']) if hero.get('name') else None, 'cls': cls, 'asc': asc,
                     'level': hero.get('level'), 'started': run.started,
                     'fate': 'dead' if dead else 'now' if current else 'left'})
        if not live:
            self._reviews[(rid, book.id)] = (stamp, data)
        return data

    @staticmethod
    def review_pick(rows, hero=None, last=None, since=None):
        """Чей разбор показать (id забега; None — героев нет). rows — герои (run_list). Герой назван (его выбрали в
        списке; страница обновляет того, кого уже показывает) — он. Иначе — герой, которым играют: разбор открывают
        посмотреть на свою игру, и не только после гибели. Страница говорит, кого показывала в прошлый раз (last) и
        когда (since): пока с тех пор никто не играл, остаётся прежний — выбранного в списке героя не сбивает уход на
        другую страницу и обратно. Героя, которым играют, нет — тот, кем играли последним."""
        ids = {r['id'] for r in rows}
        if hero in ids:
            return hero
        played = max((r.get('last') or 0 for r in rows), default=0)
        if last in ids and since is not None and played <= since:
            return last
        cur = next((r['id'] for r in rows if r.get('current')), None)
        return cur or (max(rows, key=lambda r: r.get('last') or r.get('started') or 0)['id'] if rows else None)

    def restarts_view(self):
        """Где карты начинали заново — по всем героям лога (core.restarts): {'heroes' — сколько героев в счёте,
        'rows': [{'n' — зона, 'came' — сколько героев в ней было, 'who' — сколько из них начинали её заново, 'q' —
        сколько раз, 'lost' — секунд в брошенных копиях}]} — только зоны, которые начинали заново; сначала те, где
        ушло больше времени. Время героя кончается его гибелью; паузы героя, которым не играют, — из его файла.
        Считается заново, когда у героев прибавилось событий."""
        stamp = (len(self.runs), sum(len(r.events) for r in self.runs.values()))
        if self._again and self._again[0] == stamp:
            return self._again[1]
        zones, heroes = {}, 0
        for rid in list(self.runs):
            run = self.review_run(rid)
            end = review.end_of(run)[0]
            if not end:
                continue
            heroes += 1
            for code, rec in core.restarts(run.events, run.hold, run.started, end).items():
                z = zones.setdefault(code, {'n': rec['name'], 'came': 0, 'who': 0, 'q': 0, 'lost': 0})
                z['came'] += 1
                z['who'] += 1 if rec['again'] else 0
                z['q'] += rec['again']
                z['lost'] += rec['lost']
        rows = sorted((dict(z, lost=int(round(z['lost']))) for z in zones.values() if z['q']),
                      key=lambda z: (-z['lost'], -z['q'], z['n']))
        data = {'heroes': heroes, 'rows': rows}
        self._again = (stamp, data)
        return data

    def review_view(self, hero=None, base=None, last=None, since=None):
        """Данные режима «Разбор»: {'plans', 'runs' — планы и герои для шапки и списка героев (как у /api/plans);
        'pick' — чей разбор показан (review_pick); 'plan': {id, title} — по какому плану он посчитан: план этого героя
        из библиотеки, как он есть сейчас; 'hero' — разбор (review_of); 'base' — разбор героя base по ТОМУ ЖЕ плану
        (иначе шаги двух героев не сопоставить), у него ownPlan — название его собственного плана, если тот другой;
        'again' — где карты начинали заново, по всем героям (restarts_view);
        'error' — расчёт не удался (тогда hero — None)}."""
        rows = self.run_list()
        out = {'plans': self.plans_view(rows), 'runs': rows, 'pick': self.review_pick(rows, hero, last, since),
               'plan': None, 'hero': None, 'base': None, 'again': None, 'error': None}
        rid = out['pick']
        if rid is None:
            return out
        try:
            book = (self.book_for(self.plan_of(rid)) if self.plans_dir else None) or self.active
            out['plan'] = {'id': book.id, 'title': i18n.Raw(book.plan.get('title') or '')}
            out['hero'] = self.review_of(rid, book)
            other = self.review_of(base, book) if base and base != rid else None
            if other is not None:
                own = self.plan_of(base) if self.plans_dir else book.id
                if own != book.id:
                    title = next((p['title'] for p in self.library() if p['id'] == own), '')
                    other = dict(other, ownPlan=i18n.Raw(title))
                out['base'] = other
            out['again'] = self.restarts_view()
        except Exception as e:   # noqa: BLE001 — странный лог давнего героя не должен ронять страницу
            out['hero'] = out['base'] = None
            out['error'] = '%s: %s' % (type(e).__name__, e)
        return out

    # --- отметки ----------------------------------------------------------

    def _context(self):
        zones = [e for e in self.run.events if e['type'] == 'zone']
        levels = [e for e in self.run.events if e['type'] == 'level']
        cur = zones[-1] if zones else None
        return {
            'zone': cur['code'] if cur else None,
            'zoneName': cur['name'] if cur else None,
            'heroLevel': levels[-1]['level'] if levels else 1,
        }

    def _status(self, goal_id):
        st = 0
        for m in self.run.marks:
            if m['goal'] == goal_id:
                st = m['status']
        return st

    def _put(self, goal_id, status):
        """Дописывает отметку в журнал, если она что-то меняет. Не сохраняет и не оповещает."""
        if self._status(goal_id) == status:
            return False
        rec = {'ts': time.time(), 'goal': goal_id, 'status': status}
        rec.update(self._context())
        self.run.marks.append(rec)
        return True

    def mark(self, goal_id, status):
        if status not in (0, 1, 2) or isinstance(status, bool):
            return False
        if goal_id not in {g['id'] for g in self.plan['goals']}:
            return False
        if self._put(goal_id, status):
            self.save_run()
            self._bump()
        return True

    def set_rung(self, req):
        """Ставит лесенку на выбранную ступень одним действием — выбор уровня камня из списка.

        chain — ступени лесенки по порядку, to — ступень, которая теперь есть (None — ни одной:
        остаётся стартовый уровень). Отметки выше неё снимаются, иначе уровень не опустить: побеждает
        самая высокая отметка. take — заодно отметить само умение (камня не было), drop — снять его.
        """
        ids = {g['id'] for g in self.plan['goals']}
        chain, to = req.get('chain'), req.get('to')
        take, drop = req.get('take'), req.get('drop')
        def known(x):
            return isinstance(x, str) and x in ids

        if not isinstance(chain, list) or not chain or len(chain) > 64 or not all(known(c) for c in chain):
            return False
        if to is not None and not (isinstance(to, str) and to in chain):
            return False
        if take is not None and not (isinstance(take, dict) and known(take.get('goal'))
                                     and take.get('status') in (1, 2) and not isinstance(take.get('status'), bool)):
            return False
        if drop is not None and not known(drop):
            return False
        changed = False
        if take:
            changed = self._put(take['goal'], take['status']) or changed
        for gid in (chain[chain.index(to) + 1:] if to is not None else chain):
            changed = self._put(gid, 0) or changed
        if to is not None:
            changed = self._put(to, 2) or changed
        if drop:
            changed = self._put(drop, 0) or changed
        if changed:
            self.save_run()
            self._bump()
        return True

    # --- вещь из буфера обмена --------------------------------------------

    def take_copy(self, text, ts=None):
        """Игрок скопировал вещь в игре: запоминаем её (только в памяти) и показываем против слота.
        Сама копия ничего не отмечает: где вещь лежит, из текста не узнать."""
        item = itemcopy.parse(text)
        if item is None:
            return False
        itemcopy.identify(self.catalog, item)     # база и семейства аффиксов — по каталогу данных игры
        item['at'] = ts if ts is not None else time.time()
        # где курсор: копию делают, наведя его на предмет, — рядом с этим местом встанет окно поверх игры
        src = self.clip_source
        self.copy_cursor = (item['at'], src.cursor()) if src is not None and hasattr(src, 'cursor') else None
        # Путевой камень — не вещь для слота: на него страница отвечает своим окном «идти / не идти»,
        # а вещь, которая сейчас сравнивается со слотом, остаётся на месте.
        stone = waystone.read(self.catalog, item)
        if stone is not None:
            stone['at'] = item['at']
            self.way = stone
            self._bump()
            return True
        self.copied = item
        self.copied_raw = _plain(text)
        if item.get('unusable') and not self.run.told:
            # игра сама написала, что вещью пользоваться нельзя: с этого забега её молчание — тоже ответ
            self.run.told = True
            self.save_run()
        # Сравнение само уходит со страницы: вещь посмотрели и бросили — оно больше не должно отвлекать.
        self.copy_until = item['at'] + COPY_SECONDS
        self._bump()
        return True

    def pick(self, req):
        """Игрок назвал, какой атрибут взят у его героя в узле «Характеристика»: {node, attr} — str, dex
        или int; пустой attr — снова как в плане. Запоминается в забеге."""
        geo = self.tree_geo('tree')
        node, attr = req.get('node'), req.get('attr')
        if not geo or not isinstance(node, str) or geo['kind'].get(node) != treegeo.ATTRIBUTE:
            return False
        if attr in wearcheck.ATTRS:
            self.run.picks[node] = attr
        elif attr in (None, ''):
            self.run.picks.pop(node, None)
        else:
            return False
        self.save_run()
        self._bump()
        return True

    def take_off(self, req):
        """Игрок снял умение — кнопка «Снять» на странице: {goal, on}; on: false — отметку убрать. Снять так можно только то,
        что план снимает: умение или камень поддержки с шагом «Снять». Игра снятие камня в лог не пишет."""
        gid, on = req.get('goal'), req.get('on', True)
        g = next((x for x in self.plan['goals'] if x['id'] == gid), None) if isinstance(gid, str) else None
        if (g is None or not isinstance(on, bool) or g.get('slot') or g.get('kind') not in ('skill', 'support')
                or not g.get('until')):
            return False
        if on == (gid in self.run.off):
            return True
        if on:
            self.run.off[gid] = time.time()
        else:
            del self.run.off[gid]
        self.save_run()
        self._bump()
        return True

    def expire_copy(self, now=None):
        """Убирает сравнение со скопированной вещью, когда его время вышло. Возвращает, убрано ли."""
        if self.copied is None or self.copy_until is None or (now or time.time()) < self.copy_until:
            return False
        self.copied = None
        return True

    def wear(self, req):
        """Слово игрока о скопированной вещи.

        row — «надеть»: отметки этой строки слота встают по вещи, а сама вещь запоминается целиком как надетая
        в этом слоте — с ней будут сравнивать следующие. Слот помнит один предмет: прежняя запись слота уходит, тот же
        предмет, запомненный в другом слоте, — тоже (его переложили), а двуручное оружие и вторая рука друг друга
        вытесняют, как в игре. Сравнение считается заново здесь, страница присылает только имя строки.
        drop — убрать вещь со страницы, ничего не отмечая.
        forget — забыть вещь, запомненную в этом слоте (место «слот/»): её снимают, а новую не надевают.
        Отмены у «надеть» нет: надел не то — копируют то, что надето на деле, и снова «надеть» (их решение 2026-11-25).
        """
        if req.get('drop'):
            if self.copied is not None:
                self.copied = None
                self._bump()
            return True
        if req.get('choose') is not None:
            # слот, выбранный для копии на странице (кольцо 2): в него «Надеть» и клавиша в игре
            if self.copied is None:
                return False
            self.copy_pick = (self.copied.get('at'), str(req['choose']))
            self._bump()
            return True
        if req.get('forget') is not None:
            # все записи слота: и «слот/», и прежнего вида — «слот/шаг» (slotwear.settle)
            sid = str(req['forget']).split('/', 1)[0]
            gone = [spot for spot in self.run.worn if spot.split('/', 1)[0] == sid]
            if not gone:
                return False
            for spot in gone:
                del self.run.worn[spot]
            self.save_run()
            self._bump()
            return True
        row = req.get('row')
        if not isinstance(row, str) or self.copied is None:
            return False
        cmp_view = self.view().get('copy')
        cmp_row = next((x for x in (cmp_view or {}).get('rows') or [] if x['row'] == row), None)
        if cmp_row is None:
            return False
        keep = cmp_row.get('key') if cmp_row.get('keep') else None
        puts = itemcopy.wear_marks(cmp_view, row) or []
        if not puts and not keep:
            return False       # ни запомнить вещь (нет каталога), ни отметить её базу в плане
        known = {g['id'] for g in self.plan['goals']}
        if any(gid not in known for gid, _ in puts):
            return False
        changed = False
        for gid, st in puts:
            changed = self._put(gid, st) or changed
        if keep:
            for spot in self.displaced(keep, self.copied):
                del self.run.worn[spot]
            self.run.worn[keep] = {'at': time.time(), 'item': self.copied}
            changed = True
        self.wore = {'run': self.run.id, 'row': row, 'at': time.time(), 'name': self.copied.get('name')} if changed else None
        self.copied = None
        if changed:
            self.save_run()
        self._bump()
        return True

    def set_overlay_opt(self, name, value):
        """Игрок выбрал настройку окон поверх игры (окно «Настройки» в шапке страниц; имена и значения —
        OVERLAY_CHOICES). Запоминается в настройках программы; окна прячет и показывает overlay.py (он читает
        self.overlay), список рисует его страница — она узнаёт о смене сразу. Окон поверх игры нет — менять нечего."""
        key, choices, _ = OVERLAY_CHOICES.get(name, (None, (), None))
        if key is None or not _choice(value, choices) or not self.overlay.get('can'):
            return False
        if value != self.overlay.get(name):
            self.overlay[name] = value
            try:
                appsettings.update(self.settings_path, **{key: value})
            except OSError:
                pass
            self._bump()
        return True

    def set_overlay(self, on):
        """Окна поверх игры включены или выключены."""
        return self.set_overlay_opt('on', on)

    def set_overlay_list(self, mode):
        """Список шага поверх игры: 'fold' — свёрнут, 'open' — раскрыт всегда."""
        return self.set_overlay_opt('list', mode)

    def settings_view(self):
        """Что показывает окно «Настройки»: окна поверх игры (can — они есть только у окна программы) и папка игры
        (found — лог игры в ней найден; pick — указать папку можно: окно выбора есть только у окна программы)."""
        return {'overlay': dict(self.overlay),
                'game': {'dir': str(self.game_dir or ''), 'found': bool(self.log_path), 'pick': bool(self.picker)},
                'about': {'name': about.NAME, 'author': about.AUTHOR, 'year': about.YEAR},     # первая строка окна
                # «Проверять обновления»: строка есть только у окна программы (can) — сервер из исходников не спрашивает
                'update': self.updater.setting() if self.updater else {'can': False}}

    def hotkey_close(self):
        """Клавиша «Закрыть» в игре: страница убирает своё верхнее окно (сравнение, путевой камень, очки дерева) — какое из
        них верхнее, знает только страница, поэтому программа лишь говорит ей время нажатия (поле shut)."""
        self.shut_at = time.time()
        self._bump()
        return True

    def hotkey_wear(self):
        """Клавиша «Надеть» в игре — то же, что «Надеть» в окне сравнения: в слот, выбранный для копии (на странице — у колец;
        иначе тот, что программа выбрала сама). Сравнения нет, предмет уже надет или запомнить его нечем — ничего."""
        if self.copied is None:
            return False
        cp = self.view().get('copy') or {}
        row = next((r for r in cp.get('rows') or [] if r['row'] == cp.get('pick')), None)
        if row is None or row.get('verdict') == 'worn' or not (row.get('keep') or (row.get('base') or {}).get('to')):
            return False
        return self.wear({'row': row['row']})

    def hotkey_item(self, text, now=None):
        """Клавиша «Сравнить / Надеть» в игре: text — предмет, который программа скопировала под курсором (None — под
        курсором не предмет). Новый предмет — сравнить, даже когда окно сравнения открыто (так предметы перебирают
        подряд). Тот же предмет, что в окне сравнения, — «Надеть»; раньше SAME_GUARD секунд после сравнения — ничего
        (случайное двойное нажатие). Под курсором не предмет — ничего: молчание игры за «Надеть» не принимается."""
        if not text:
            return False
        now = time.time() if now is None else now
        if self.copied is None or self.copied_raw != _plain(text):
            return self.take_copy(text, ts=now)
        if now - self.copied['at'] < SAME_GUARD:
            return False
        return self.hotkey_wear()

    def displaced(self, keep, item):
        """Записи памяти надетого, которые «надеть» предмета item в место keep («слот/») вытесняет — так память остаётся
        тем, что на герое на деле: прежние записи того же слота другого вида (место по периоду, slotwear.settle); тот же
        предмет, запомненный в другом слоте (его переложили — скипетр из второй руки в оружие); и руку, которую вещь
        занимает по правилу игры: двуручное оружие — вторую руку, вещь во второй руке — двуручное в основной (колчан при
        луке лук не вытесняет). Сама keep сюда не входит: её «надеть» перезаписывает."""
        sid = keep.split('/', 1)[0]
        pair = self.plan.get('hands') or {}
        classes = lambda it: [c for c in ((it or {}).get('cls_id'), (it or {}).get('cls')) if c]    # noqa: E731
        out = []
        for spot, entry in self.run.worn.items():
            if spot == keep:
                continue
            other, had = spot.split('/', 1)[0], (entry or {}).get('item')
            if other == sid or itemcopy.same_item(had, item):
                out.append(spot)
            elif pair and sid == pair.get('main') and other == pair.get('off') and slotwear.shut(pair, item, classes(had)):
                out.append(spot)
            elif pair and sid == pair.get('off') and other == pair.get('main') and slotwear.shut(pair, had, classes(item)):
                out.append(spot)
        return out

    def set_hold(self, on):
        """«Пауза» / «Продолжить» на странице: время забега и шага стоит, пока игрок не продолжит или не зайдёт в боевую
        зону (core.stopped_spans). То же слово дважды ничего не меняет."""
        self.run.hold.append({'ts': time.time(), 'on': bool(on)})
        self.save_run()
        self._bump()
        return True

    def move_to(self, step_id):
        """Ручная поправка: сделать шаг текущим, если страница ошиблась с позицией."""
        if step_id not in {s['id'] for s in self.plan['steps']}:
            return False
        self.run.moves.append({'ts': time.time(), 'step': step_id})
        self.save_run()
        self._bump()
        return True

    # --- выдача -----------------------------------------------------------

    def _bump(self):
        # Замок повторно входимый, поэтому вызов безопасен и под уже взятым замком.
        with self.cond:
            self.version += 1
            self.cond.notify_all()

    def icon_names(self):
        """Имена картинок, которые лежат в папке (без «.webp»). Страница рисует картинку вещи, только
        если файл есть: запроса за несуществующей картинкой и пустого места на плитке не бывает.
        Папку читаем каждый раз: в ней несколько десятков файлов, а время изменения папки — плохой
        признак (файл, добавленный в тот же миг, что и прошлое чтение, остался бы незамеченным)."""
        try:
            names = [e.name[:-len('.webp')] for e in os.scandir(self.icons_dir)
                     if e.is_file() and RE_ICON.fullmatch('/icons/' + e.name)]
        except OSError:
            return []
        return sorted(names)

    def _given(self):
        """Узлы дерева с надетых предметов (зачарование амулета, anoint.py) для сборки состояния: объект-функция
        (id узлов версии, взятые очком, шаг) -> (что есть с предметов, что брать очком не нужно), у которого
        on_items(шаг) — id узлов с надетых предметов (по ним выбирается версия дерева: core.waiting), и словарь,
        куда он кладёт найденное (rows — узлы с предметов, spare — что они сберегают): по нему после сборки
        строятся строки блока «Дерево». Что надето, зависит от шага (периоды слотов), а шаг знает только сборка."""
        found = {}
        geo = self.tree_geo('tree')
        if not self.catalog or not geo or not geo.get('anoint'):
            return None, found
        app = self

        class Given:
            def rows(self, pos):
                if found.get('pos', -1) != pos or 'rows' not in found:
                    # что надето в каждом слоте на этом шаге (одна запись на слот: slotwear.settle)
                    found.update(pos=pos, rows=anoint.worn_nodes(app.catalog, geo, app.run.worn,
                                                                 slotwear.settle(app.plan, app.run.worn, pos).values()))
                return found['rows']

            def on_items(self, pos):
                try:
                    return {i for a in self.rows(pos) for i in a['ids']}
                except (KeyError, TypeError, ValueError, AttributeError, IndexError) as e:
                    i18n.say(tr('Узлы дерева с предметов не посчитаны: %s') % e, flush=True)
                    return set()

            def __call__(self, order, taken, pos):
                try:
                    had = {anoint.pick(a['ids'], set(order)) for a in self.rows(pos)} - {None}
                    spare = anoint.spare(order, had, taken, geo)
                except (KeyError, TypeError, ValueError, AttributeError, IndexError) as e:
                    i18n.say(tr('Узлы дерева с предметов не посчитаны: %s') % e, flush=True)
                    return set(), set()
                found['spare'] = spare
                return had, set().union(*spare.values())
        return Given(), found

    def _tree_now(self, v, pos):
        """Версия дерева, которая действует на деле (её назвала сборка состояния: tree.now — с учётом запасной версии,
        пока узла с амулета нет); без неё — версия этапа."""
        now = (v.get('tree') or {}).get('now')
        return (next((ph for ph in self.plan['tree']['phases'] if ph.get('id') == now), None) if now
                else None) or buildstage.version(self.plan, 'tree', pos)

    def _stats_view(self, v, icons=(), lang=i18n.SOURCE):
        """Инвентарь на статах (herostats.py): вещь каждого слота (что на ней работает на билд) и ответ
        на вещь из буфера — чем она лучше надетой.
        icons — имена картинок, которые лежат в папке."""
        # Что надето: в каждом слоте один предмет (core: wornAt — где он в памяти; запись прежнего вида читается так же)
        cat = self.catalog
        worn = {herostats.worn_key(sid): self.run.worn[spot] for sid, spot in (v.get('wornAt') or {}).items()
                if spot in self.run.worn}
        # Билд, каким он действует на текущем шаге: этап билда (до вознесения — урон оружия, после —
        # приспешники; броня в кампании, энергощит на картах) решает, какие статы идут в карточку слота
        # и в сравнение вещей и какого рода базы у слотов.
        pos, lines = v.get('pos'), self.tree_lines()
        plan = herostats.at_step(cat, self.plan, pos, lines)
        extra = herostats.rest(cat, v.get('gained'), self.run.events)
        # уровень вещей, какие сейчас падают: самая высокая зона забега
        ilvl = max([e.get('level') or 0 for e in self.run.events if e['type'] == 'zone'] or [0]) or None
        # строка слота меряется билдом текущего шага: рюкзака нет, вещи на потом не меряют
        plan_of = lambda row: plan      # noqa: E731

        hero_level = (v.get('hero') or {}).get('level')
        # настоящие уровни зон забега (у интерлюдий уровень зависит от порядка): где падают базы нужного уровня
        zone_levels = {e['code']: e['level'] for e in self.run.events if e['type'] == 'zone' and e.get('level')}
        for r in itemcopy.slot_rows(v):
            at = plan_of(r)
            r['wornKey'] = herostats.hero_keys(at).get(r['slot'])
            r['item'] = herostats.slot_item(cat, at, r['slot'], r['wornKey'], worn, extra, ilvl, lang)
            # картинка вещи (у уникального — своя, иначе базы) — только если её файл есть: за несуществующей страница
            # не пойдёт; нет своего рисунка уникального — рисунок базы
            if r['item']:
                r['item']['icon'] = gamedata.item_icon(cat, (worn.get(r['wornKey']) or {}).get('item'), icons)
            # Блок «Как сделать»: карточка рецепта надетого предмета (ничего не надето — белой базы в лучшем окне
            # уровня) и где искать базу (craftplan.slot_card). Сказать нечего (у слота нет редкого стата, нет весов) —
            # блока нет.
            try:
                r['howto'] = craftplan.slot_card(cat, at, r, (worn.get(r['wornKey']) or {}).get('item'), hero_level, ilvl,
                                                 zone_levels, self.plan.get('steps') or (), lang)
            except (KeyError, TypeError, ValueError, AttributeError, IndexError) as e:
                r['howto'] = None
                i18n.say(tr('Путь крафта не посчитан: %s') % e, flush=True)
        # Слоты, где вещь отмечена надетой, а программа её не видела: атрибуты с вещей героя известны не все.
        # Пустой слот (ничего не отмечено и не запомнено) сюда не идёт — в нём просто ничего нет.
        blind = [r['kind'] for r in v.get('holders') or []
                 if r.get('slot') and not r.get('item') and (r.get('base') or {}).get('have')]
        # Атрибуты героя — по плану дерева (узел в версии этапа считается назначенным ему атрибутом, узел вне
        # плана не считается, выбор игрока важнее плана) — и сверка с тем, что на герое уже работает.
        # Класс героя — тот, которым играют (по логу), а не названный билдом.
        state = None
        try:
            state = wearcheck.hero_state(cat, self.plan, v, self.run.events, worn, herostats.hero_keys(plan), lines,
                                         self.tree_geo('tree'), self._tree_now(v, pos),
                                         (self.plan.get('tree') or {}).get('attr'), self.run.picks,
                                         blind, lang=lang, cls=self.hero_seen().get('class'),
                                         # узлы дерева с надетых предметов (зачарование амулета) — в атрибуты героя
                                         extra=[a['node'] for a in (v.get('tree') or {}).get('anoint') or [] if a.get('node')])
            v['heroAttrs'] = wearcheck.hero_view(state)
        except (KeyError, TypeError, ValueError, AttributeError) as e:
            i18n.say(tr('Атрибуты героя не посчитаны: %s') % e, flush=True)
        cp = v.get('copy')
        if not cp or not cp.get('rows') or not self.copied:
            return
        seen = self.copied.get('identified', True)
        for row in cp['rows']:
            at = plan_of(row)
            key = herostats.hero_keys(at).get(row['slot'])
            st = (herostats.compare(cat, at, row['slot'], key, self.copied, worn, extra, ilvl,
                                    lang=lang, base=row.get('base')) if seen else None)
            known = key in worn
            row['key'] = key
            row['keep'] = st is not None       # вещь можно запомнить надетой в этом слоте
            # В слоте ничего нет: ни запомненной вещи, ни отметки базы. Тогда любая вещь лучше пустого места.
            row['empty'] = not known and not row.get('held')
            if st is None or not (known or row['empty']):
                # Сравнить не с чем: вещь не опознана, нет данных игры, либо слот отмечен занятым, а что
                # в нём надето, программа не видела (lost) — надетую вещь нужно скопировать и запомнить.
                row['verdict'] = 'unknown'
                row['lost'] = st is not None
                continue
            # строка «база по плану»: роды баз — короткими названиями, как на кнопках этапа («AR/ES»)
            for ln in st['lines']:
                if ln.get('cls') == 'kind':
                    for k in ('want', 'now', 'new'):
                        ln[k + 'Name'] = buildplan.kind_short(cat, ln.get(k), lang)
            row['st'] = st
            row['verdict'] = st['verdict'] if known else 'better'
            row['up'], row['down'] = st['up'], st['down']
        # Хватит ли герою уровня и атрибутов надеть вещь и не перестанет ли после замены работать что-то
        # из надетого. Надетая уже надета — у неё вопроса нет.
        for row in cp['rows']:
            if not seen or state is None or row.get('verdict') == 'worn':
                continue
            try:
                row['wear'] = wearcheck.describe(cat, state, row['key'], self.copied, told=self.run.told)
            except (KeyError, TypeError, ValueError, AttributeError) as e:
                i18n.say(tr('Требования предмета не сверены: %s') % e, flush=True)
        # Помощник крафта: карточка рецепта предмета и где искать базу для слота. Форму предмета задают статы этапа,
        # на котором предмет строки носят, и цели слота; шансы — веса свойств из каталога (craftplan).
        level = (v.get('hero') or {}).get('level')
        for row in cp['rows']:
            try:
                row['craft'] = (craftplan.for_row(cat, plan_of(row), v, row, self.copied, level, lang, ilvl, zone_levels,
                                                  self.plan.get('steps') or ()) if seen else None)
            except (KeyError, TypeError, ValueError, AttributeError, IndexError) as e:
                row['craft'] = None
                i18n.say(tr('Крафт не посчитан: %s') % e, flush=True)
        # Узел дерева на предмете (зачарование амулета): ответ по статам его не считает — страница говорит о нём
        # строкой: что на копии, что теряется с надетого и чем его зачаровать заново (anoint.py)
        geo = self.tree_geo('tree')
        on_copy = anoint.describe(cat, geo, self.copied, lang)
        if on_copy:
            cp['anoint'] = on_copy
        for row in cp['rows']:
            had = anoint.describe(cat, geo, (worn.get(row.get('key')) or {}).get('item'), lang)
            if had:
                row['anoint'] = had
        # Куда вещь пойдёт по умолчанию: слот, где она уже надета; иначе — где она лучше всего. При равном ответе —
        # строка, где план называет именно эту базу (скипетр — во вторую руку, а не в оружие, где годится любое).
        order = {'worn': 0, 'better': 1, 'same': 2, 'worse': 3, 'unknown': 4}
        cp['pick'] = min(cp['rows'], key=lambda r: (order.get(r['verdict'], 5), not (r.get('base') or {}).get('byName'),
                                                    -(r['st']['score'] if r.get('st') else 0)))['row']
        # Предмет уже надет в слоте, где план его сейчас не ждёт, а в другом слоте план называет именно его (скипетр после
        # вознесения: надет во второй руке, а ждут его в оружии) — по умолчанию строка того слота: туда его перекладывают.
        here = next((r for r in cp['rows'] if r['verdict'] == 'worn'), None)
        if here is not None and not (here.get('base') or {}).get('to'):
            there = next((r for r in cp['rows'] if r is not here and (r.get('base') or {}).get('byName')), None)
            if there is not None:
                cp['pick'] = there['row']
        # Слот, выбранный для этой копии на странице (кольцо 2 вместо кольца 1), важнее: в него «Надеть» и клавиша в игре.
        chosen = self.copy_pick[1] if self.copy_pick and self.copy_pick[0] == self.copied.get('at') else None
        if any(r['row'] == chosen for r in cp['rows']):
            cp['pick'] = chosen

    def view(self, lang=i18n.SOURCE):
        # Фильтр проверяется для зоны, уровень которой называет сама сборка состояния: шаг знает только она.
        check = {}

        def ground(level):
            check['ground'] = self.filter_check(level)
            return check['ground']
        # Статы запомненных вещей — до сборки состояния: по ним сами отмечаются цели по стату.
        self.run.gear = herostats.gear(self.catalog, self.run.worn)
        given, found = self._given()
        v = core.derive(self.plan, self.run, time.time(), ground, self.selected_filter, self.own_level,
                        zone_names=self.point_names(), zone_levels=self.zone_levels, atlas_league=self.atlas_league(),
                        given=given)
        if v.get('tree') is not None and (found.get('rows') or v['tree'].get('items') or v['tree'].get('target')):
            slots = {s['id']: s.get('name') or s['id'] for s in self.plan.get('slots') or []}
            v['tree']['anoint'] = anoint.view(found.get('rows') or [], v['tree'], found.get('spare') or {}, self.catalog,
                                              self.tree_geo('tree'), lang, slots, anoint.amulet_slots(self.catalog, self.plan))
        # Чей атлас продолжает герой: слово игрока (from: id забега, '' — новый, None — слова нет) и из чего
        # выбирать (offers). Вопрос (ask) — когда герой на картах, слова о его атласе нет (ни своего, ни героя,
        # который продолжил его атлас), а в логе есть клики по атласу других героев.
        a = v['atlas']
        a['from'] = self.atlas_links.get(self.run.id)
        a['offers'] = self.atlas_offers() if a['open'] or a['from'] is not None else []
        told = a['from'] is not None or any(b == self.run.id for b in self.atlas_links.values())
        a['ask'] = bool(a['open'] and not told and a['offers'])
        # Заход, который станет сменой шага, если игрок останется: к этому времени страницу обновим сами.
        # То же после кнопки «сменить шаг» во время захода: по истечении порога время шага уточняется.
        self._pending_at = v.get('recheckAt') or (v['pending']['at'] if v['pending'] else None)
        # герой в шапке — словами клиента и только по логу
        v['hero']['cls'], v['hero']['asc'] = self.hero_words(v['hero'])
        # error — проход цикла чтения падает: страница говорит это вместо «лог читается»
        # found — игра найдена (иначе страница просит её запустить); pick — у окна программы есть выбор папки игры;
        # problem — указанная игроком папка не та
        v['log'] = {'ok': self.log_ok, 'lastTs': self.last_log_ts, 'path': str(self.log_path or ''),
                    'error': self.loop_error, 'found': bool(self.log_path), 'pick': bool(self.picker),
                    'problem': self.game_problem}
        # Версии. program — программа: «версия игры, под которую она сделана» и номер сборки («0.5.5.4»); made — та
        # версия игры тремя числами; game — какая игра у игрока (её называет лог игры при каждом запуске; None — лог
        # её ещё не назвал); newer — игра новее программы: страница говорит «нужна новая версия программы».
        made = (self.base_catalog or {}).get('version')
        v['version'] = {'program': appversion.program(made), 'made': appversion.stem(made), 'game': self.game_tag,
                        'newer': appversion.newer(self.game_tag, made)}
        # обновление программы: есть ли новая версия (тогда у красной строки «нужна новая версия программы» — кнопка
        # «Обновить») и счёт перемен (шапка спрашивает /api/update заново); None — программа о новых версиях не
        # спрашивает (сервер из исходников)
        v['update'] = self.updater.brief() if self.updater else None
        v['planError'] = self.plan_error
        v['planProblems'] = self.plan_problems
        v['wayProblems'] = self.know_problems     # база знаний о путевых камнях разошлась с данными игры
        v['runs'] = self.run_list()
        # планы для шапки: какие есть, по какому идёт герой, спросить ли нового героя о плане
        v['plans'] = self.plans_view(v['runs'])
        # название плана — слова автора: на странице на другом языке оно остаётся как записано
        v['planTitle'] = i18n.Raw(v.get('planTitle') or '')
        # Картинки баз снаряжения и уникальных предметов (art-…, uniq-…, их сотни) страница по имени не ищет: программа
        # сама кладёт имя в вещь слота, когда файл есть. Картинки умений и камней поддержки (skill-…, sup-…: все камни
        # игры, тоже сотни) страница берёт по названию из плана и списка не спрашивает. В список идут остальные —
        # рисунки предметов плана и силуэты типов.
        icons = self.icon_names()
        have = set(icons)
        v['icons'] = [n for n in icons if not n.startswith(('art-', 'uniq-', 'skill-', 'sup-'))]
        # Скопированная в игре вещь против своего слота; после «надеть» — что надето (wore: окно коротко говорит «НАДЕТО»).
        v['copy'] =itemcopy.compare(self.plan, v, self.copied) if self.copied else None
        if v['copy'] is not None:
            # паспорт вещи: всё, что на ней есть, суммой по статам героя (аффиксы, гибриды, руны, свойства)
            v['copy']['stats'] = itemstats.view(self.catalog, self.copied, lang)
            # рисунок вещи (у уникального — свой, иначе базы) — в шапку её карточки; как и у надетой, только если файл
            # рисунка есть
            v['copy']['icon'] = gamedata.item_icon(self.catalog, self.copied, have)
            v['copy']['until'] = self.copy_until      # когда сравнение само уйдёт со страницы
        self._stats_view(v, have, lang)
        w = self.wore
        v['wore'] = ({'row': w['row'], 'at': w['at'], 'name': w['name']}
                     if w and w['run'] == self.run.id else None)
        v['clip'] = self.clip
        # Клавиши страницы в игре: какая клавиша («F2») и её состояние — 'idle' / 'on' — слушается (пока игра впереди),
        # 'busy' — клавишу держит другая программа; None — клавиш нет (буфер не читается, не Windows). shut — когда
        # нажата «Закрыть»: страница убирает своё верхнее окно.
        v['keys'] = ({name: {'key': clip.key_name(self.key_choice.get(name)), 'state': self.keys.state.get(name, 'idle')}
                      for name in clip.KEY_IDS if name in self.keys.state} if self.keys is not None else None)
        if v['keys'] and 'wear' in v['keys'] and self.key_copies:
            v['keys']['wear']['copy'] = True      # эта же клавиша сравнивает: по предмету под курсором
        v['shut'] = self.shut_at
        # окна поверх игры: умеет ли их программа (только её собственное окно) и включены ли они
        v['overlay'] = dict(self.overlay)
        # Скопированный путевой камень: ответ считается заново при каждой выдаче — уровень героя растёт,
        # база знаний правится, герой берёт узлы дерева, от которых часть свойств перестаёт действовать.
        v['way'] = (waystone.judge(self.catalog, self.know, self.way, (v.get('hero') or {}).get('level'),
                                   waystone.hero_traits(self.know, (v.get('tree') or {}).get('have')), lang)
                    if self.way else None)
        self._local_nodes(v, lang)
        return v

    # --- язык страницы ----------------------------------------------------

    def geo_file(self, path, lang):
        """Файл геометрии дерева (tree.json, atlas.json) для страницы на языке lang. На языке игры, кроме английского,
        к нему добавлены названия узлов на этом языке (here: id узла -> название; данные игры, names-<язык>) — и
        по-русски тоже: в файле названия английские; по-английски — файл как есть. Собранное помнится, пока не
        изменился файл."""
        body = path.read_bytes()
        nodes = ((gamedata.names_pack(self.catalog, lang) or {}).get('nodes') or {}) if lang != 'en' else {}
        if not nodes:
            return body
        key = (str(path), lang, len(body), path.stat().st_mtime)
        hit = self._geo_lang.get(key)
        if hit is None:
            geo = json.loads(body.decode('utf-8'))
            geo['here'] = {n[0]: nodes[n[0]] for n in geo.get('nodes') or () if isinstance(n, list) and n and n[0] in nodes}
            hit = json.dumps(geo, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
            self._geo_lang = {k: v for k, v in self._geo_lang.items() if k[:2] != key[:2]}
            self._geo_lang[key] = hit
        return hit

    def page_lang(self, given):
        """Язык страницы по параметру запроса lang. Назван язык — он, если на него есть перевод (иначе язык по
        умолчанию); 'auto' — пользователь язык не выбирал: язык клиента игры, если на него есть перевод, иначе язык по
        умолчанию; параметра нет — страница, открытая до появления языков: язык кода."""
        if given is None:
            return i18n.SOURCE
        return i18n.pick((self.client_lang or '') if given == 'auto' else given)

    def names(self, lang):
        """Как показать на языке lang названия из плана (i18n.Names): слова программы, попавшие в план, пары
        «Русское (English)», названия зон из лога. Для языка кода — None: названия идут как записаны.
        Собирается заново, когда меняется каталог (перечитан план), файл перевода или лог назвал новую зону."""
        if lang == i18n.SOURCE:
            return None
        zones = self.zone_names()
        stamp = (id(self.catalog), len(zones), id(i18n.table(lang)))
        hit = self._names.get(lang)
        if not hit or hit[0] != stamp:
            # тексты свойств игры (варианты наград, строки наград): описания свойств из файлов игры — русские и этого языка
            stats = tuple((gamedata.log_pack(self.catalog, code) or {}).get('stat') or {} for code in (i18n.SOURCE, lang))
            hit = self._names[lang] = (stamp, i18n.Names(lang, self.catalog, zones, gamedata.names_pack(self.catalog, lang),
                                                         stats))
        return hit[1]

    def _local_nodes(self, v, lang):
        """Названия узлов деревьев в состоянии страницы — на языке lang, названиями игры по id узла. План и лог
        называют узел по-своему: план — как его записал автор (узел, взятый на карте, — английским названием из
        данных дерева), лог — словами клиента игрока. Английское название узла знают данные дерева (tree.json,
        atlas.json), название на другом языке игры, русском тоже, — её таблицы (names-<язык>).
        Узел-цель («Иммунитет к хаосу») назван своей целью и идёт как название из плана."""
        if lang == 'en':
            local = {}
        else:
            pack = gamedata.names_pack(self.catalog, lang)
            if pack is None and lang == i18n.SOURCE:
                return          # каталог без русского слоя названий: узлы — как их назвали план и лог
            local = (pack or {}).get('nodes') or {}
        for kind in ('tree', 'atlas'):
            names = (self.tree_geo(kind) or {}).get('en') or {}

            def walk(x):
                if isinstance(x, dict):
                    if isinstance(x.get('name'), str) and x.get('id') in names and not x.get('goal'):
                        # чего нет в таблицах этого языка: на другом языке — английским, по-русски — как записано
                        other = x['name'] if lang == i18n.SOURCE else names[x['id']]
                        x['name'] = core.clean_markup(local.get(x['id']) or other) or x['name']
                    for val in x.values():
                        walk(val)
                elif isinstance(x, list):
                    for val in x:
                        walk(val)

            if names:
                walk(v.get(kind))

    def view_json(self, lang):
        """Состояние страницы забега на языке lang строкой JSON. Для языка кода — ровно то, что собрал расчёт."""
        return json.dumps(i18n.render(self.view(lang), lang, self.names(lang), plain=True), ensure_ascii=False)

    def answer(self, data, lang):
        """Ответ редактору плана на языке lang строкой JSON: тексты программы переведены, записи плана — как
        в файлах (редактор их правит и присылает обратно)."""
        return json.dumps(i18n.render(data, lang, self.names(lang)), ensure_ascii=False)

    def tick(self):
        """Один проход цикла чтения. Ошибка цикл не останавливает, но и не прячется: пока проход падает,
        страница вместо «лог читается» говорит, что чтение сломано (log.error в состоянии) — иначе зелёный
        индикатор горел бы и над программой, которая ничего не читает."""
        try:
            with self.cond:
                changed = self.follow_game()
                changed = self.poll_log() or changed
                changed = self.load_plan() or changed
                changed = self.load_know() or changed
                changed = self.load_config() or changed
                if self._pending_at and time.time() >= self._pending_at:
                    self._pending_at = None
                    changed = True
                changed = self.expire_copy() or changed
                if self.loop_error:
                    self.loop_error, changed = None, True     # проход снова удался
                if changed:
                    self._bump()
        except Exception as e:  # цикл не должен умирать из-за одной ошибки
            text = '%s: %s' % (type(e).__name__, e)
            if text != self.loop_error:
                i18n.say(tr('Ошибка в цикле чтения: %r') % e, flush=True)
                self.loop_error = text
                self._bump()

    def loop(self):
        while True:
            time.sleep(0.5)
            self.tick()


# Content-Security-Policy страниц программы — вторая стена после esc на самих страницах: если текст чужого плана
# где-то всё же ляжет на страницу разметкой, браузер не выполнит из него ничего. Скрипт и стиль страницы — только
# те, что пришли с ней (метка nonce — новая на каждый ответ, сервер ставит её в теги <script> и <style> страницы);
# встроенные обработчики (onerror=…), eval, чужие скрипты и стили не выполняются. Атрибут style в разметке
# страниц нужен (ширины, цвета) — он разрешён. Картинки — только с самого сервера, запросы — только к нему
# (/api/…, поток событий). Окно программы (pywebview) вставляет свой мост через WebView2 — политика его не касается.
PAGE_POLICY = ("default-src 'none'; script-src 'nonce-{n}'; style-src 'nonce-{n}'; style-src-attr 'unsafe-inline'; "
               "img-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
RE_PAGE_TAG = re.compile(rb'(?m)^<(script|style)>')


def page_nonce():
    return secrets.token_urlsafe(18)


def with_nonce(body, nonce):
    """Текст страницы с меткой ответа в её тегах <script> и <style> (они стоят в начале своей строки)."""
    return RE_PAGE_TAG.sub(lambda m: b'<%s nonce="%s">' % (m.group(1), nonce.encode('ascii')), body)


def no_constant(name):
    """NaN и Infinity в теле запроса — не JSON: страница таких чисел не шлёт."""
    raise ValueError(name)


def make_handler(app, port):
    allowed_hosts = {'127.0.0.1:%d' % port, 'localhost:%d' % port}
    allowed_origins = {'http://' + h for h in allowed_hosts}

    class Handler(BaseHTTPRequestHandler):
        server_version = 'PoE2Planner/0.1'

        def log_message(self, fmt, *args):
            pass

        def _send(self, code, body, ctype, cache=False):
            data = body if isinstance(body, bytes) else body.encode('utf-8')
            self.send_response(code)
            self.send_header('Content-Type', ctype)
            self.send_header('Content-Length', str(len(data)))
            # картинки умений не меняются — их браузер держит у себя; всё остальное всегда свежее
            self.send_header('Cache-Control', 'max-age=86400' if cache else 'no-store')
            self.end_headers()
            self.wfile.write(data)

        def _page(self, body):
            """Страница программы: с политикой (PAGE_POLICY) и меткой этого ответа в её скриптах и стилях."""
            nonce = page_nonce()
            data = with_nonce(body, nonce)
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Security-Policy', PAGE_POLICY.format(n=nonce))
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.end_headers()
            self.wfile.write(data)

        def _local_only(self):
            """Страница доступна только с этого компьютера и только самой себе."""
            if self.headers.get('Host') not in allowed_hosts:
                return False
            origin = self.headers.get('Origin')
            return origin is None or origin in allowed_origins

        def _lang(self):
            """Язык запроса — параметр lang адреса. Сервер языка не помнит: его называет страница в каждом
            обращении, поэтому вкладки на разных языках друг другу не мешают. Запрос без lang — от страницы,
            открытой до появления языков: ей отвечают как раньше, по-русски."""
            given = urllib.parse.parse_qs(self.path.partition('?')[2]).get('lang')
            return app.page_lang(given[0] if given else None)

        def _plan(self):
            """План, о котором спрашивает редактор, — параметр plan адреса (id папки плана); нет — план героя."""
            given = urllib.parse.parse_qs(self.path.partition('?')[2]).get('plan')
            return given[0] if given else ''

        def _no_plan(self, lang):
            body = app.answer({'ok': False, 'error': tr('плана «%s» нет в библиотеке') % self._plan(),
                               'problems': [tr('плана «%s» нет в библиотеке') % self._plan()]}, lang)
            return self._send(404, body, 'application/json; charset=utf-8')

        def do_GET(self):
            if not self._local_only():
                return self._send(403, 'forbidden', 'text/plain; charset=utf-8')
            path = self.path.split('?', 1)[0]
            if path in ('/', '/index.html', '/admin', '/review'):
                # '/admin' — страница «Билд»: правка разделов билда, которые не видны на карте дерева;
                # '/review' — режим «Разбор»: та же страница, что «Игра» (шапка у них общая), какой режим
                # показать, она узнаёт по своему адресу
                try:
                    body = (HERE / 'static' / ('admin.html' if path == '/admin' else 'index.html')).read_bytes()
                except OSError:
                    return self._send(500, tr('Нет файла страницы'), 'text/plain; charset=utf-8')
                return self._page(body)
            lang = self._lang()
            if path == '/api/lang':
                # тексты страницы на языке lang и список языков для переключателя
                return self._send(200, json.dumps(i18n.page(lang), ensure_ascii=False), 'application/json; charset=utf-8')
            if path == '/api/settings':
                # настройки программы — для окна «Настройки» в шапке (оно одно на всех страницах)
                with app.cond:
                    body = json.dumps(app.settings_view(), ensure_ascii=False)
                return self._send(200, body, 'application/json; charset=utf-8')
            if path == '/api/update':
                # обновление программы — для шапки всех страниц: есть ли версия новее, как идёт «Обновить», объявление
                # для всех, когда была последняя проверка и что ответила (окно «О программе»)
                upd = app.updater
                body = json.dumps(i18n.render(upd.view(lang) if upd else {'can': False}, lang), ensure_ascii=False)
                return self._send(200, body, 'application/json; charset=utf-8')
            if path == '/api/about':
                # окно «О программе» (в окне «Настройки»): чья программа, версия, лицензия, сторонние компоненты
                with app.cond:
                    body = json.dumps(app.about_view(), ensure_ascii=False)
                return self._send(200, body, 'application/json; charset=utf-8')
            if path == '/api/legal':
                # текст LICENSE / NOTICE.md / THIRD-PARTY.md из папки программы — окно «О программе» показывает его в себе
                given = urllib.parse.parse_qs(self.path.partition('?')[2]).get('file')
                text = about.legal_text(given[0] if given else '')
                if text is None:
                    return self._send(404, 'not found', 'text/plain; charset=utf-8')
                return self._send(200, text, 'text/plain; charset=utf-8')
            if path == '/api/build':
                # данные редактора о плане ?plan=… (нет — о плане героя)
                with app.cond:
                    try:
                        with app.editing(self._plan()):
                            body = app.answer(app.build_view(lang), lang)
                    except KeyError:
                        return self._no_plan(lang)
                return self._send(200, body, 'application/json; charset=utf-8')
            if path == '/api/stats':
                # тексты свойств игры для поля «Награда в логе» редактора: коды свойств -> текст на языке страницы
                with app.cond:
                    body = json.dumps(app.stat_lines(lang), ensure_ascii=False)
                return self._send(200, body, 'application/json; charset=utf-8')
            if path == '/api/speech':
                # реплики игры для поля «Реплики в логе» редактора: код строки -> «Имя: текст» на языке страницы
                with app.cond:
                    body = json.dumps(app.speech_lines(lang), ensure_ascii=False)
                return self._send(200, body, 'application/json; charset=utf-8')
            if path == '/api/plans':
                # планы библиотеки и герои — для списка в шапке редактора (страница «Игра» получает их в состоянии)
                with app.cond:
                    rows = app.run_list()
                    # список показывают, а не правят: слова — на языке страницы, как в состоянии «Игры»
                    body = json.dumps(i18n.render({'plans': app.plans_view(rows), 'runs': rows}, lang, app.names(lang), plain=True),
                                      ensure_ascii=False)
                return self._send(200, body, 'application/json; charset=utf-8')
            if path == '/api/plancat':
                # раздел «Каталог» редактора: что в каталоге одобренных планов и что из этого уже стоит (сеть — нет:
                # спросить каталог заново — POST {refresh})
                with app.cond:
                    body = json.dumps(i18n.render(app.plancat_view(lang), lang, app.names(lang), plain=True), ensure_ascii=False)
                return self._send(200, body, 'application/json; charset=utf-8')
            if path == '/api/plan-file':
                # файл плана для обмена: его отдают другому игроку, тот добавляет его в свою библиотеку
                with app.cond:
                    try:
                        data, name = app.plan_file(self._plan())
                    except (OSError, ValueError) as e:
                        return self._send(404, str(e), 'text/plain; charset=utf-8')
                body = json.dumps(data, ensure_ascii=False, indent=1).encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Content-Disposition', 'attachment; filename="%s"' % name)
                self.send_header('Content-Length', str(len(body)))
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                self.wfile.write(body)
                return None
            if path == '/api/zone':
                # где герой сейчас — редактору плана, для выбора зоны шага
                with app.cond:
                    body = json.dumps(app.now_zone(), ensure_ascii=False)
                return self._send(200, body, 'application/json; charset=utf-8')
            icon = RE_ICON.fullmatch(path)
            if icon:
                # Картинка умения или вещи: файл из папки static/icons (у умения имя — id цели, у вещи —
                # поле icon цели). Имя проверено шаблоном, поэтому выйти за пределы папки запросом нельзя.
                try:
                    body = (app.icons_dir / icon.group(1)).read_bytes()
                except OSError:
                    return self._send(404, 'not found', 'text/plain; charset=utf-8')
                return self._send(200, body, 'image/webp', cache=True)
            if path == '/tree.json':
                # Геометрия дерева пассивных умений для карты: её собирает planner/treegeo.py из данных,
                # которые выкладывает GGG. Нет файла — у страницы просто нет карты, строка «Дерево» работает.
                try:
                    body = app.geo_file(app.tree_path, lang)
                except (OSError, ValueError):
                    return self._send(404, 'not found', 'text/plain; charset=utf-8')
                return self._send(200, body, 'application/json; charset=utf-8')
            if path == '/treestats.json':
                # Что даёт каждый узел дерева (строки из данных GGG) — нужно только при правке дерева:
                # страница берёт файл, когда правку открывают. Собирает его тоже planner/treegeo.py.
                try:
                    body = app.treestats_path.read_bytes()
                except OSError:
                    return self._send(404, 'not found', 'text/plain; charset=utf-8')
                return self._send(200, body, 'application/json; charset=utf-8')
            lang_stats = RE_TREESTATS.fullmatch(path)
            if lang_stats:
                # Те же строки на языке страницы (treestats.de.json, atlasstats.de.json) — словами игры: их собирают
                # planner/treegeo.py и planner/atlasgeo.py из описаний свойств в файлах игры. Страницы берут файл своего
                # языка; нет файла — общий. Имя проверено шаблоном: выйти за папку запросом нельзя.
                try:
                    body = app.treestats_path.with_name('%sstats.%s.json' % lang_stats.groups()).read_bytes()
                except OSError:
                    return self._send(404, 'not found', 'text/plain; charset=utf-8')
                return self._send(200, body, 'application/json; charset=utf-8')
            if path in ('/atlas.json', '/atlasstats.json'):
                # То же для дерева атласа: геометрия для карты и что даёт каждый узел. Оба файла собирает
                # planner/atlasgeo.py из выгрузки таблиц игры. Нет файла — у страницы нет карты атласа.
                try:
                    body = (app.geo_file(app.atlas_path, lang) if path == '/atlas.json' else app.atlasstats_path.read_bytes())
                except (OSError, ValueError):
                    return self._send(404, 'not found', 'text/plain; charset=utf-8')
                return self._send(200, body, 'application/json; charset=utf-8')
            if path == '/api/review':
                # режим «Разбор»: куда ушло время героя ?hero=… и, для сравнения, героя ?base=… по тому же плану.
                # Герой не назван — кого показать, решает программа (App.review_pick): героя, которым играют;
                # last и since — кого страница показывала в прошлый раз и когда
                q = urllib.parse.parse_qs(self.path.partition('?')[2])
                arg = {k: (q.get(k) or [None])[0] for k in ('hero', 'base', 'last', 'since')}
                try:
                    since = float(arg['since']) if arg['since'] else None
                except ValueError:
                    since = None
                with app.cond:
                    data = app.review_view(arg['hero'], arg['base'], arg['last'], since)
                    body = json.dumps(i18n.render(data, lang, app.names(lang), plain=True), ensure_ascii=False)
                return self._send(200, body, 'application/json; charset=utf-8')
            if path == '/api/view':
                with app.cond:
                    body = app.view_json(lang)
                return self._send(200, body, 'application/json; charset=utf-8')
            if path == '/api/events':
                return self._events(lang)
            return self._send(404, 'not found', 'text/plain; charset=utf-8')

        def _events(self, lang=i18n.SOURCE):
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            last = -1
            try:
                while True:
                    with app.cond:
                        if app.version == last:
                            app.cond.wait(timeout=15)
                        ver = app.version
                        payload = app.view_json(lang) if ver != last else None
                    if payload is None:
                        self.wfile.write(b': ping\n\n')
                    else:
                        self.wfile.write(('data: ' + payload + '\n\n').encode('utf-8'))
                        last = ver
                    self.wfile.flush()
            except OSError:
                pass

        def do_POST(self):
            if not self._local_only():
                return self._send(403, 'forbidden', 'text/plain; charset=utf-8')
            path, lang = self.path.split('?', 1)[0], self._lang()
            if path not in ('/api/mark', '/api/build', '/api/check', '/api/open', '/api/plans', '/api/game', '/api/update',
                            '/api/plancat'):
                return self._send(404, 'not found', 'text/plain; charset=utf-8')
            try:
                n = int(self.headers.get('Content-Length') or 0)
                # отметка — короткая; версии дерева — три списка по сотне узлов; разделы билда — этапы
                # и цели с заметками (сотня записей); присланный файл плана — маршрут и билд целиком
                if not 0 < n <= {'/api/mark': 4096, '/api/open': 256, '/api/game': 256, '/api/update': 256, '/api/plancat': 256,
                                 '/api/plans': 2 * planlib.MAX_TEXT + 65536}.get(path, 262144):
                    raise ValueError('bad length')
                req = json.loads(self.rfile.read(n).decode('utf-8'), parse_constant=no_constant)
                if not isinstance(req, dict):
                    raise ValueError('bad body')
            except (ValueError, OSError, RecursionError):
                return self._send(400, '{"ok": false}', 'application/json')
            if path == '/api/game':
                # «указать папку игры»: окно выбора папки открывает сама программа (оно есть только у окна программы),
                # путь от страницы не принимается. Пока окно выбора открыто, замок не держим — страница живёт.
                picker = app.picker
                if not (req.get('pick') is True and picker):
                    return self._send(400, '{"ok": false}', 'application/json')
                try:
                    folder = picker()
                except Exception as e:       # окно выбора не открылось — это не повод ронять ответ
                    folder = None
                    i18n.say('folder dialog: %r' % (e,), flush=True)
                if not folder:
                    return self._send(200, json.dumps({'ok': False, 'cancelled': True}), 'application/json')
                with app.cond:
                    body = app.answer(app.choose_game(folder), lang)
                return self._send(200, body, 'application/json; charset=utf-8')
            if path == '/api/update':
                # «Обновить» (go) — скачать, сверить и запустить установщик новой версии; «Проверять обновления» (on) —
                # настройка окна «Настройки». Адрес и файл берёт сама программа: от страницы — только «да» и «вкл/выкл».
                upd = app.updater
                if upd is None:
                    ok = False
                elif req.get('go') is True:
                    ok = upd.install()
                elif 'on' in req:
                    ok = upd.set_on(req['on'])
                else:
                    ok = False
                return self._send(200 if ok else 400, json.dumps({'ok': bool(ok)}), 'application/json')
            if path == '/api/plancat':
                # «Каталог» редактора: открыли список планов (refresh — каталог спрашивается, только пока включено
                # «Проверять обновления», и не чаще plancat.FRESH), нажали «Спросить каталог» (ask — сразу) или поставить
                # план из него (get — метка плана). Сеть — без замка программы: страницы живут, пока идёт запрос.
                if req.get('refresh') is True or req.get('ask') is True:
                    app.plancat_refresh(ask=req.get('ask') is True)
                    with app.cond:
                        res = dict(app.plancat_view(lang), ok=True)
                elif isinstance(req.get('get'), str):
                    res = app.plancat_get(req['get'])
                else:
                    res = {'ok': False, 'problems': [tr('непонятно, что сделать с планом')]}
                with app.cond:
                    body = json.dumps(i18n.render(res, lang, app.names(lang), plain=True), ensure_ascii=False)
                return self._send(200 if res['ok'] else 400, body, 'application/json; charset=utf-8')
            if path == '/api/open':
                # страница просит открыть в браузере системы страницу фильтра на сайте игры (App.open_filter), официальный
                # сайт программы (App.open_site) или страницу автора плана из каталога (App.open_author): адрес собирает
                # программа — адрес от страницы не принимается
                ok = app.open_filter(req.get('id')) if req.get('page') == 'filter' else \
                    app.open_site() if req.get('page') == 'site' else \
                    app.open_author(req.get('uid')) if req.get('page') == 'author' else False
                return self._send(200 if ok else 400, json.dumps({'ok': bool(ok)}), 'application/json')
            if path == '/api/check':
                # проверка гайда: те же разделы, что при записи, но ничего не пишется — только замечания
                # и то, что страница показывает по плану «как сейчас на ней» (редкие статы этапов)
                with app.cond:
                    try:
                        with app.editing(self._plan()):
                            body = app.answer(app.check_page(req, lang), lang)
                    except KeyError:
                        return self._no_plan(lang)
                return self._send(200, body, 'application/json; charset=utf-8')
            if path == '/api/build':
                # правка плана на странице /admin (?plan=… — какого): разделы целиком; в ответе — что не так, если
                # не записано, и в какой план записано (присланный план сам не правится — правки ложатся в копию)
                with app.cond:
                    try:
                        # страница прочла план до того, как его файлы изменились (запись из другой вкладки, правка
                        # программой): её запись затёрла бы те правки — отказ, страницу обновляют
                        with app.editing(self._plan()):
                            now = app.plan_stamp()
                        if req.get('stamp') != now:
                            res = {'ok': False, 'problems': [tr('План изменился после того, как эта страница его открыла '
                                                               '(запись из другой вкладки или программой): обновите '
                                                               'страницу — несохранённые правки этой вкладки пропадут')]}
                        else:
                            res = app.save_plan(self._plan(), {k: v for k, v in req.items() if k != 'stamp'})
                    except KeyError:
                        return self._no_plan(lang)
                    body = app.answer(res, lang)
                return self._send(200 if res['ok'] else 400, body, 'application/json; charset=utf-8')
            if path == '/api/plans':
                # библиотека планов из шапки: герою — план (use), копия плана (copy), файл плана в библиотеку
                # (import), убрать план (remove), файл плана — в папку export (save)
                with app.cond:
                    if isinstance(req.get('use'), str):
                        ok, problems = app.bind_plan(req['use'])
                        res = {'ok': ok, 'problems': problems}
                    elif isinstance(req.get('create'), dict):
                        res = app.new_plan(req['create'])
                    elif isinstance(req.get('copy'), str):
                        pid, problems = app.copy_plan(req['copy'], req.get('title') if isinstance(req.get('title'), str) else None)
                        res = {'ok': pid is not None, 'plan': pid, 'problems': problems}
                    elif isinstance(req.get('import'), dict):
                        res = app.import_plan(req)
                    elif isinstance(req.get('remove'), str):
                        ok, problems = app.remove_plan(req['remove'])
                        res = {'ok': ok, 'problems': problems}
                    elif isinstance(req.get('save'), str):
                        res = app.save_plan_file(req['save'])
                    else:
                        res = {'ok': False, 'problems': [tr('непонятно, что сделать с планом')]}
                    body = app.answer(res, lang)
                return self._send(200 if res['ok'] or res.get('same') else 400, body, 'application/json; charset=utf-8')
            with app.cond:
                if isinstance(req.get('set'), dict):
                    ok = app.set_rung(req['set'])
                elif isinstance(req.get('pick'), dict):
                    # какой атрибут взят в узле «Характеристика» у героя — выбор на карте дерева
                    ok = app.pick(req['pick'])
                elif isinstance(req.get('off'), dict):
                    # «Снять»: умение снимают на шаге, где план его снимает (или отметку убрали)
                    ok = app.take_off(req['off'])
                elif isinstance(req.get('atlasFrom'), dict):
                    # чей атлас продолжает герой: тот же, что у героя другого забега, или новый
                    ok = app.atlas_answer(req['atlasFrom'])
                elif isinstance(req.get('atlasHad'), dict):
                    # узел атласа взят до лога — отметка игрока на карте атласа (или снять её)
                    ok = app.atlas_mark(req['atlasHad'])
                elif isinstance(req.get('wear'), dict):
                    # скопированная вещь: «надеть», выбрать ей слот, убрать со страницы или забыть надетую («Снять»)
                    ok = app.wear(req['wear'])
                elif 'moveTo' in req:
                    ok = app.move_to(str(req['moveTo']))
                elif any(c[0] in req for c in OVERLAY_CHOICES.values()):
                    # окна поверх игры: выбор игрока в окне «Настройки» — включены ли, вид списка, прозрачность
                    name = next(n for n, c in OVERLAY_CHOICES.items() if c[0] in req)
                    ok = app.set_overlay_opt(name, req[OVERLAY_CHOICES[name][0]])
                elif 'hold' in req:
                    # «Пауза» / «Продолжить»: время забега и шага стоит
                    ok = app.set_hold(req['hold'] is True)
                elif isinstance(req.get('gone'), dict):
                    # «героя этого забега больше нет» — или «он есть»
                    ok = app.mark_gone(req['gone'])
                elif 'run' in req:
                    # «сейчас играю героем этого забега»
                    ok = app.switch_run(str(req['run']))
                else:
                    ok = app.mark(str(req.get('goal')), req.get('status'))
            return self._send(200 if ok else 400, json.dumps({'ok': ok}), 'application/json')

    return Handler


def _plain(text):
    """Текст предмета для сравнения «тот же ли это предмет»: без пробелов по краям строк и разницы в концах строк."""
    return '\n'.join(line.rstrip() for line in str(text or '').replace('\r\n', '\n').strip().split('\n'))


def options(argv=None):
    """Параметры запуска. Где игра, программа находит сама; --log, --config и --filters — для проверок."""
    ap = argparse.ArgumentParser(description='Страница маршрута PoE2')
    ap.add_argument('--port', type=int, default=4717)
    ap.add_argument('--log', default=os.environ.get('POE2_LOG'), help='путь к Client.txt')
    ap.add_argument('--plan', help='работать с одним этим планом (оглавление plan.json), без библиотеки планов')
    ap.add_argument('--plans', default=str(ROOT / 'plans'), help='папка библиотеки планов: в ней у каждого плана своя папка')
    ap.add_argument('--runs', default=str(ROOT / 'runs'))
    ap.add_argument('--filters', help='папка OnlineFilters игры')
    ap.add_argument('--archive', default=str(ROOT / 'filters'), help='куда складывать версии фильтра')
    ap.add_argument('--config', help='файл настроек игры')
    ap.add_argument('--settings', help='файл, где программа помнит папку игры')
    ap.add_argument('--open', action='store_true', help='открыть страницу в браузере')
    ap.add_argument('--catalog', default=str(ROOT / 'catalog' / 'data'), help='папка каталога данных игры')
    ap.add_argument('--knowledge', default=str(ROOT / 'knowledge'), help='папка базы знаний (опасность аффиксов путевых камней)')
    ap.add_argument('--no-clip', action='store_true', help='не читать буфер обмена (копии предметов из игры)')
    ap.add_argument('--clip-file', help='для проверок: брать «буфер» из этого файла; настоящий буфер не трогается')
    ap.add_argument('--hotkey-file', help='для проверок: каждая смена этого файла — нажатие клавиши в игре '
                                          '(слово close в файле — «Закрыть», иначе — «Надеть»)')
    ap.add_argument('--lang', help='язык сообщений в этом окне: ru, en… (страницы выбирают язык сами)')
    ap.add_argument('--offline', action='store_true', help='для проверок: в сеть не ходить (каталог планов не спрашивается)')
    return ap.parse_args(argv)


def prepare(argv=None):
    """Всё, что до ответов страницам: параметры, где игра, план, лог, порт. Возвращает (app, httpd, url, args);
    порт занят — None. Окно программы (desktop.py) зовёт это и serve() само — со своими папками данных."""
    args = options(argv)

    # Русский текст в окне консоли и в журнале запуска не должен превращаться в кракозябры.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding='utf-8', errors='replace')
        except (AttributeError, ValueError):
            pass

    if args.lang:
        i18n.CONSOLE[0] = i18n.pick(args.lang)
    plans_dir, plan_path = None, args.plan
    if not plan_path:
        # Библиотека планов. Прежний единственный план (plan.json рядом с папкой библиотеки) переезжает в неё
        # при первом запуске — своей папкой, с теми же маршрутом и билдом.
        plans_dir = Path(args.plans)
        old = plans_dir.parent / 'plan.json'
        if not planlib.scan(plans_dir) and old.is_file():
            try:
                pid = planlib.adopt(old, plans_dir)
                i18n.say(tr('План переехал в библиотеку планов: %s') % (plans_dir / pid), flush=True)
            except (OSError, ValueError) as e:
                i18n.say(tr('План не перенесён в библиотеку: %s') % e, flush=True)
        lib = planlib.scan(plans_dir)
        plan_path = lib[0]['path'] if lib else plans_dir / 'plan' / planlib.MANIFEST
    # Где игра (gamepaths.py). Лог назван параметром (проверки, пробный сервер) — читается он, и за запущенной игрой
    # программа не следит; иначе — запущенная игра, запомненная папка, Steam, клиент с сайта.
    wins, game_dir, log = None, None, args.log
    if log:
        game_dir = Path(log).resolve().parent.parent
    else:
        wins = gamepaths.windows()
        running = wins.running_game() if wins else None
        game_dir, log = gamepaths.find(appsettings.load(args.settings).get('gameDir'), running, gamepaths.registry())
    docs = gamepaths.game_docs()
    app = App(log, plan_path, args.runs, args.filters or docs / 'OnlineFilters', args.archive,
              args.config or gamepaths.config_in(docs), catalog_dir=args.catalog, knowledge_dir=args.knowledge,
              plans_dir=plans_dir)
    app.game_dir, app.settings_path = game_dir, args.settings
    if args.offline:
        app.plancat.fetch = plancat.offline         # проверки страниц: наружу ничего не уходит
    if wins:
        app.follow = wins.running_game
        if game_dir:
            try:
                appsettings.update(args.settings, gameDir=str(game_dir))
            except OSError:
                pass
    with app.cond:
        app.load_plan()
        app.load_know()
        app.load_config()
        app.poll_log(initial=True)
        app.use_plan(app.plan_of(app.run.id))       # план героя, которым играют сейчас
        app.attach_run()
        # Версия, которая загружена сейчас, тоже попадает в архив.
        loads = [e for e in app.run.events if e['type'] == 'filter' and e.get('ok', True) and e.get('hash')]
        if loads:
            app.archive_filter(loads[-1])

    try:
        httpd = ThreadingHTTPServer(('127.0.0.1', args.port), make_handler(app, args.port))
    except OSError as e:
        i18n.say(tr('Порт %d занят: возможно, программа уже запущена. (%s)') % (args.port, e), flush=True)
        return None

    url = 'http://127.0.0.1:%d/' % args.port
    i18n.say(tr('Страница маршрута: %s') % url, flush=True)
    i18n.say(tr('Лог игры: %s (%s)') % (app.log_path or '—', tr('читается') if app.log_ok else tr('НЕ НАЙДЕН')), flush=True)
    i18n.say(tr('План: %s%s') % (app.plan_path, ' — ' + app.plan_error if app.plan_error else ''), flush=True)
    i18n.say(tr('Каталог данных игры: %s') % (tr('версия ') + app.catalog['version'] if app.catalog else tr('не найден')), flush=True)
    i18n.say(tr('Путевые камни: %s') % (tr('опасность задана %d аффиксам%s') % (
        len(app.know['mods']), tr(', замечаний: %d') % len(app.know_problems) if app.know_problems else '')
        if app.know else tr('база знаний не прочитана')), flush=True)
    i18n.say(tr('Герой: %s, событий: %d, отметок: %d') % (app.run.id, len(app.run.events), len(app.run.marks)), flush=True)
    return app, httpd, url, args


def serve(app, httpd, url, args):
    """Буфер обмена, клавиша «Надеть», цикл чтения лога — и ответы страницам, пока программу не закроют."""
    # Вещь, скопированная в игре (Ctrl+Alt+C): буфер читается только при активном окне игры — программе
    # из папки игры (там лежит logs\Client.txt). Игра не найдена — окно игры узнаётся по заголовку; нашлась
    # позже — App.set_game скажет буферу её папку. Подробности и оговорки — в clip.py.
    source = None
    if args.clip_file:
        source = clip.FileClipboard(args.clip_file)
    elif not args.no_clip:
        try:
            source = clip.WinClipboard(game_dir=app.game_dir)
        except OSError as e:
            app.clip = tr('Буфер обмена не читается: %s') % e
    app.clip_source = source
    watcher = None
    if source is not None:
        def on_item(text):
            with app.cond:
                app.take_copy(text)
        app.clip = 'on'
        watcher = clip.Watcher(source, on_item)
        threading.Thread(target=watcher.run, daemon=True).start()
    if args.clip_file:
        i18n.say(tr('Буфер обмена: вместо него читаю файл %s') % args.clip_file, flush=True)
    elif app.clip == 'on':
        i18n.say(tr('Буфер обмена: читаю копии предметов (Ctrl+Alt+C), только когда активно окно игры'), flush=True)
    else:
        i18n.say(tr('Буфер обмена не читается%s') % ('' if app.clip == 'off' else ': ' + app.clip), flush=True)

    # Клавиши страницы в игре — «Надеть» и «Закрыть» (по умолчанию F2 и F3: первые две функциональные, которых игра не
    # занимает): слушаются, только пока впереди окно игры — то же, что и для буфера. В игру ничего не посылается. Без
    # буфера (копий нет) и вне Windows их нет.
    # «Сравнить» — та же клавиша, что «Надеть»: программа сама нажимает в игре копию предмета под курсором (одна копия
    # на одно нажатие игрока) и возвращает в буфер то, что в нём лежало (clip.Copier); что это нажатие значит, решает
    # App.hotkey_item. Только с настоящим буфером: без него (буфер — файл в проверках) клавиша — только «Надеть».
    copier = (clip.Copier(source, watcher, lambda: app.copy_mod)
              if isinstance(source, clip.WinClipboard) and watcher is not None else None)
    app.key_copies = copier is not None

    def on_wear():
        text = copier.grab() if copier is not None else None
        with app.cond:
            if copier is not None:
                app.hotkey_item(text)
            else:
                app.hotkey_wear()

    def on_close():
        with app.cond:
            app.hotkey_close()
    press = {'wear': on_wear, 'close': on_close}
    fronts = {}
    # «Программа ↔ игра»: есть только у окна программы (desktop.py); слушается и когда впереди само окно программы
    if app.window_toggle is not None:
        press['app'] = app.window_toggle
        if isinstance(source, clip.WinClipboard):
            fronts['app'] = lambda: source.game_in_front() or bool(app.window_front and app.window_front())
    if args.hotkey_file:
        app.keys = clip.FileKeys(args.hotkey_file, press)
        i18n.say(tr('Клавиши в игре: вместо них слежу за файлом %s') % args.hotkey_file, flush=True)
    elif isinstance(source, clip.WinClipboard):
        try:
            app.keys = clip.WinKeys(source.game_in_front, lambda: app.key_choice, press, fronts)
            i18n.say(tr('Клавиши в игре: %s — «Надеть», %s — «Закрыть»; только когда активно окно игры') % (
                clip.key_name(app.key_choice.get('wear')) or '—', clip.key_name(app.key_choice.get('close')) or '—'),
                flush=True)
            if copier is not None:
                i18n.say(tr('Клавиша «Сравнить»: %s — программа сама копирует предмет под курсором и возвращает буфер обмена') % (
                    clip.key_name(app.key_choice.get('wear')) or '—'), flush=True)
        except OSError as e:
            i18n.say(tr('Клавиши в игре не работают: %s') % e, flush=True)
    if app.keys is not None:
        threading.Thread(target=app.keys.run, daemon=True).start()

    threading.Thread(target=app.loop, daemon=True).start()
    if args.open:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    httpd.serve_forever()


def main(argv=None):
    ready = prepare(argv)
    if ready is None:
        return 1
    try:
        serve(*ready)
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == '__main__':
    sys.exit(main())
