# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Sergei Labutin
# Additional terms under GPL-3.0 section 7: see NOTICE.md
"""Приём чужого плана: файл плана от незнакомого автора (открытый из файла, взятый из каталога) попадает в
библиотеку, только если каждое его поле — того вида, который программа сама пишет.

Файл плана (planlib.FORMAT) несёт тексты маршрута и билда. Редактор пишет в них только проверенное
(routeplan.check, buildplan.check), а файл с чужой машины мог написать кто угодно и чем угодно. Здесь — та же
граница для него, без знания игры (есть ли такая зона, такой стат — скажет проверка плана, это не опасно):

  * JSON строгий: без NaN и Infinity (страница их не прочтёт — JSON.parse падает), без повтора ключа в одной
    записи, не глубже MAX_DEPTH уровней (глубокая вложенность роняет разбор);
  * у каждой записи — только известные программе поля, у каждого поля — свой вид: строка не длиннее своего
    предела и без управляющих и невидимых знаков (смена направления письма, одиночные суррогаты — их не
    записать в UTF-8 и не отдать странице), число в своих пределах, пометка — да или нет;
  * id — по образцу из латиницы, цифр, «_» и «-»: ни разделителей пути, ни точек, ни имён служебных свойств
    объектов JavaScript (__proto__, constructor…), которыми страница хранит записи по id; id не повторяются;
  * записей не больше, чем принимает редактор (шагов, целей, слотов…).

Проверка не правит план и не дописывает в него ничего: нашлось не так — отказ со словами для игрока (что и где,
без самого чужого текста). Прошло — план ложится в библиотеку как прислан.
"""
import json
import math
import re

from i18n import tr

MAX_DEPTH = 12          # уровней вложенности в части плана (у настоящего плана их шесть)
MAX_SAY = 6             # замечаний в отказе: остальные — числом

# знаки, которых в тексте плана быть не может: управляющие (перевод строки и табуляция — только в заметке),
# смена направления письма, разделители строк Юникода, BOM, не-знаки, одиночные суррогаты, невидимые теги
RE_BAD = re.compile('[\x00-\x08\x0b-\x1f\x7f-\x9f؜‎‏ -‮⁦-⁩﻿￹-￻'
                    '￾￿\ud800-\udfff\U000e0000-\U000e007f]')
RE_BAD_LINE = re.compile('[\t\n]')

# имена свойств объекта JavaScript: запись с таким id на странице подменила бы служебное свойство
JS_NAMES = frozenset(('__proto__', 'constructor', 'prototype', 'toString', 'toLocaleString', 'valueOf',
                      'hasOwnProperty', 'isPrototypeOf', 'propertyIsEnumerable', '__defineGetter__',
                      '__defineSetter__', '__lookupGetter__', '__lookupSetter__'))

RE_KEY = re.compile(r'[A-Za-z][A-Za-z0-9_]{0,39}')      # имя поля, которое можно назвать в замечании


class Refused(ValueError):
    """План не принят: args[0] — слова для игрока."""


def _no_constant(name):
    raise Refused(name)


def _pairs(pairs):
    seen = set()
    for k, _ in pairs:
        if k in seen:
            raise Refused('dup')
        seen.add(k)
    return dict(pairs)


def loads(text, part):
    """Строгий разбор текста части плана (part — её название для игрока: «маршрут», «билд»). Не JSON — ValueError
    с причиной; JSON, но с NaN / Infinity, повтором ключа или слишком глубокий — Refused."""
    try:
        obj = json.loads(text, parse_constant=_no_constant, object_pairs_hook=_pairs)
    except Refused as e:
        if e.args[0] == 'dup':
            raise Refused(tr('часть «%s» файла плана: в одной записи ключ записан дважды') % part)
        raise Refused(tr('часть «%s» файла плана: вместо числа — %s') % (part, e.args[0]))
    except RecursionError:
        raise Refused(tr('часть «%s» файла плана вложена глубже %d уровней') % (part, MAX_DEPTH))
    if _depth(obj) > MAX_DEPTH:
        raise Refused(tr('часть «%s» файла плана вложена глубже %d уровней') % (part, MAX_DEPTH))
    return obj


def _depth(x):
    """Глубина вложенности без рекурсии (на глубоком файле рекурсия сама бы упала)."""
    top, stack = 0, [(x, 1)]
    while stack:
        x, d = stack.pop()
        top = max(top, d)
        if d > MAX_DEPTH:
            return d
        if isinstance(x, dict):
            stack.extend((v, d + 1) for v in x.values())
        elif isinstance(x, list):
            stack.extend((v, d + 1) for v in x)
    return top


# --- виды полей -------------------------------------------------------------------------------------------
# Вид — функция (значение, место, замечания) -> None; замечание дописывается в список. Место — путь в части
# плана: steps[4].touch[0].zone.

def _say(out, place, text, *args):
    out.append((place, text, args))


def _kind(check, kind, **props):
    """Вид поля описывает себя (kind, предел, вложенные виды): по описанию идёт генератор враждебных планов
    (hostile.py) — так он кладёт значения в каждое поле, которое знает проверка."""
    check.kind = kind
    check.__dict__.update(props)
    return check


def text(limit, lines=False):
    """Строка не длиннее limit знаков без управляющих и невидимых знаков; lines — можно перевод строки и табуляцию
    (заметка)."""
    def check(v, place, out):
        if not isinstance(v, str):
            return _say(out, place, 'type')
        if len(v) > limit:
            return _say(out, place, 'long', limit)
        if RE_BAD.search(v) or (not lines and RE_BAD_LINE.search(v)):
            return _say(out, place, 'chars')
    return _kind(check, 'text', limit=limit, lines=lines)


def pattern(regex, limit=None):
    """Строка по образцу (id, код зоны, стата): без разделителей пути и прочего; не имя свойства JavaScript."""
    rx = re.compile(regex)

    def check(v, place, out):
        if not isinstance(v, str) or not rx.fullmatch(v) or v in JS_NAMES:
            return _say(out, place, 'type')
    return _kind(check, 'pattern', regex=regex)


def integer(lo, hi):
    def check(v, place, out):
        if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
            return _say(out, place, 'type')
    return _kind(check, 'int', lo=lo, hi=hi)


def number(lo, hi):
    def check(v, place, out):
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not lo <= v <= hi:
            return _say(out, place, 'type')
    return _kind(check, 'num', lo=lo, hi=hi)


def flag(v, place, out):
    if not isinstance(v, bool):
        _say(out, place, 'type')


flag.kind = 'flag'


def one_of(*values):
    def check(v, place, out):
        if not isinstance(v, str) or v not in values:
            return _say(out, place, 'type')
    return _kind(check, 'one_of', values=values)


def either(*kinds):
    """Подходит любой из видов (строка или список строк…)."""
    def check(v, place, out):
        for kind in kinds:
            found = []
            kind(v, place, found)
            if not found:
                return None
        return _say(out, place, 'type')
    return _kind(check, 'either', kinds=kinds)


def items(kind, limit, unique=None):
    """Список не длиннее limit; unique — поле записи (или '' — сам элемент), которое не повторяется."""
    def check(v, place, out):
        if not isinstance(v, list):
            return _say(out, place, 'type')
        if len(v) > limit:
            return _say(out, place, 'many', limit)
        seen = set()
        for i, x in enumerate(v):
            at = '%s[%d]' % (place, i)
            kind(x, at, out)
            if unique is not None:
                key = x if unique == '' else (x.get(unique) if isinstance(x, dict) else None)
                if isinstance(key, str):
                    if key in seen:
                        _say(out, at, 'dup')
                    seen.add(key)
    return _kind(check, 'items', item=kind, limit=limit, unique=unique)


def mapping(key, value, limit):
    """Словарь {ключ по образцу: значение вида value} не больше limit пар."""
    def check(v, place, out):
        if not isinstance(v, dict):
            return _say(out, place, 'type')
        if len(v) > limit:
            return _say(out, place, 'many', limit)
        for k, x in v.items():
            at = '%s.%s' % (place, k if RE_KEY.fullmatch(k) else '?')
            key(k, at, out)
            value(x, at, out)
    return _kind(check, 'mapping', key=key, value=value, limit=limit)


def record(fields, need=()):
    """Запись-словарь: только поля fields ({имя: вид}), поля need — обязательны."""
    def check(v, place, out):
        if not isinstance(v, dict):
            return _say(out, place, 'type')
        for k in need:
            if k not in v:
                _say(out, '%s.%s' % (place, k), 'need')
        for k, x in v.items():
            at = '%s.%s' % (place, k) if place else k
            if k not in fields:
                if not RE_KEY.fullmatch(k):
                    at = '%s.?' % place if place else '?'
                _say(out, at, 'unknown')
                continue
            fields[k](x, at, out)
    return _kind(check, 'record', fields=fields, need=need)


# --- образцы ------------------------------------------------------------------------------------------------
STEP_ID = r'[a-z0-9][a-z0-9_-]{0,63}'          # шаг маршрута, цель (routeplan.RE_ID, buildplan.RE_GOAL_ID)
SHORT_ID = r'[a-z0-9][a-z0-9_-]{0,39}'         # слот, этап, версия дерева (buildplan.RE_ID, treeplan.RE_ID)
ROUTE_ID = r'[A-Za-z0-9][A-Za-z0-9._-]{0,63}'  # id маршрута: «campaign-0.5»
ZONE = r'[A-Za-z0-9_]{1,60}'                   # код зоны из лога игры (routeplan.RE_ZONE)
STAT = r'[a-z0-9_]{1,64}'                      # стат: из таблицы статов или свой (gamedata.RE_STAT_ID)
LINE = r'[a-z0-9_+%-]{1,160}'                  # строка свойства игры (ключ строки аффикса)
NODE = r'[A-Za-z0-9_]{1,80}'                   # узел дерева, как его называют данные GGG и лог
ICON = r'(?:item|type|art)-[a-z0-9-]{1,80}'    # картинка цели (core.RE_ICON_NAME)
WORD = r'[a-z][a-z0-9_]{0,39}'                 # вид цели, род базы, атрибут, событие шага (ascend2)
# код фильтра, как его пишет лог игры: у фильтра с сайта — короткий код, у своего — имя файла (routeplan.RE_FILTER);
# без разметки и без того, чего в имени файла Windows быть не может (разделители пути, двоеточие…), не из одних точек
FILTER = r'(?!\.+$)[^\x00-\x1f"\\<>&/:*?|]{1,80}'

step_ref = pattern(STEP_ID)
goal_ref = pattern(STEP_ID)

# --- маршрут ----------------------------------------------------------------------------------------------
TOUCH = record({'zone': pattern(ZONE), 'name': text(80)}, need=('zone',))
STEP = record({
    'id': pattern(STEP_ID), 'zone': pattern(ZONE), 'also': items(pattern(ZONE), 12), 'event': pattern(WORD),
    'level': integer(1, 100), 'name': text(80), 'far': flag, 'target': text(12), 'filter': pattern(FILTER),
    'filterName': text(120), 'touch': items(TOUCH, 12),
    'notes': either(text(400), items(text(400), 40)),      # задачи шага прежнего вида: программа их не читает
}, need=('id',))
HEARD = either(text(200), items(text(200), 20))
ROUTE_GOAL = record({
    'id': pattern(STEP_ID), 'ref': pattern(STEP_ID), 'need': step_ref, 'from': step_ref, 'until': step_ref,
    'title': text(200), 'group': text(40), 'reward': text(200), 'note': text(4000, lines=True),
    'must': flag, 'final': flag, 'soft': flag, 'reach': integer(1, 100), 'opt': integer(1, 50),
    'kind': pattern(WORD), 'heard': HEARD, 'gives': mapping(pattern(STAT), number(-1e6, 1e6), 40),
    'grantedBy': goal_ref,
}, need=('id',))
ROUTE = record({
    'version': integer(1, 99), 'id': pattern(ROUTE_ID), 'title': text(120),
    'steps': items(STEP, 400, unique='id'), 'goals': items(ROUTE_GOAL, 600, unique='id'),
}, need=('steps',))

# --- билд -------------------------------------------------------------------------------------------------
HERO = record({'class': text(60), 'ascendancy': text(60)})
STAT_DEF = record({'id': pattern(STAT), 'name': text(60), 'short': text(20), 'lines': items(pattern(LINE), 12)},
                  need=('id',))
WEAR = record({'from': step_ref, 'until': step_ref, 'classes': items(text(60), 40), 'kind': pattern(WORD)})
SLOT = record({'id': pattern(SHORT_ID), 'name': text(60), 'wear': items(WEAR, 20), 'classes': items(text(60), 40),
               'gear': text(60), 'doneOn': one_of('find', 'equip')}, need=('id',))
STAGE_STAT = either(pattern(STAT), record({'id': pattern(STAT), 'cap': number(0, 1e6)}, need=('id',)))
STAGE = record({'id': pattern(SHORT_ID), 'from': step_ref, 'name': text(60), 'tree': pattern(SHORT_ID),
                'atlas': pattern(SHORT_ID), 'kind': pattern(WORD), 'attrs': items(pattern(WORD), 6),
                'stats': items(STAGE_STAT, 60)}, need=('id',))
NODE_REC = record({'id': pattern(NODE), 'name': text(120), 'kind': pattern(WORD), 'attr': text(20),
                   'opt': integer(1, 50)}, need=('id',))
NODE_ITEM = record({'id': pattern(NODE), 'name': text(120), 'slot': pattern(SHORT_ID)}, need=('id',))
VERSION = record({'id': pattern(SHORT_ID), 'name': text(60), 'nodes': items(NODE_REC, 700, unique='id'),
                  'items': items(NODE_ITEM, 8, unique='id'), 'without': pattern(SHORT_ID), 'from': step_ref},
                 need=('id',))
TREE = record({'attr': text(20), 'phases': items(VERSION, 40, unique='id')})
PROBE = mapping(pattern(r'[A-Za-z]{1,40}'), either(text(100), integer(0, 1000)), 16)
BUILD_GOAL = record({
    'id': pattern(STEP_ID), 'title': text(200), 'note': text(4000, lines=True), 'label': text(80), 'gear': text(60),
    'group': text(40), 'part': text(40), 'need': step_ref, 'from': step_ref, 'use': step_ref, 'until': step_ref,
    'any': flag, 'soft': flag, 'key': flag, 'gemFrom': integer(1, 40), 'opens': integer(1, 100),
    'hero': integer(1, 100), 'min': number(0, 1e6), 'stat': pattern(STAT), 'slot': pattern(SHORT_ID),
    'kind': pattern(WORD), 'rarity': one_of('Normal', 'Magic', 'Rare'), 'icon': pattern(ICON), 'for': goal_ref,
    'grantedBy': goal_ref, 'probe': PROBE, 'heard': HEARD, 'node': pattern(NODE), 'doneOn': one_of('find', 'equip'),
}, need=('id',))
BUILD = record({
    'version': integer(1, 99), 'title': text(80), 'routeId': pattern(ROUTE_ID), 'hero': HERO,
    'statDefs': items(STAT_DEF, 60, unique='id'), 'slots': items(SLOT, 40, unique='id'),
    'stages': items(STAGE, 40, unique='id'), 'goals': items(BUILD_GOAL, 600, unique='id'),
    'tree': TREE, 'atlas': TREE, 'gemLevels': items(integer(1, 100), 40),
})
GROUPS = items(text(40), 40, unique='')


# --- проверка ---------------------------------------------------------------------------------------------
def word(kind, args=()):
    """Слова замечания вида kind (type, long, chars, many, dup, unknown, need) для игрока."""
    word = {'type': tr('записано не так'), 'long': tr('текст длиннее %d знаков'),
            'chars': tr('в тексте управляющие или невидимые знаки'), 'many': tr('записей больше %d'),
            'dup': tr('такой id уже есть'), 'unknown': tr('такого поля программа не знает'),
            'need': tr('нет обязательного поля')}[kind]
    return word % args if args else word


def problems(route, build, groups=None):
    """Замечания к частям присланного плана (уже разобранным loads): [строка для игрока]. Пусто — план годится."""
    found = []
    for part, kind, value in ((tr('маршрут'), ROUTE, route), (tr('билд'), BUILD, build)):
        out = []
        kind(value, '', out)
        found += [tr('часть «%s» файла плана, %s: %s') % (part, place or '—', word(k, args)) for place, k, args in out]
    if groups is not None:
        out = []
        GROUPS(groups, 'groups', out)
        found += [tr('файл плана, %s: %s') % (place, word(k, args)) for place, k, args in out]
    if found:
        return found
    # id цели маршрута и цели билда не совпадают: страница и программа держат цели по id одним списком (вид частей
    # уже проверен: цели — записи с id-строкой)
    ids = {g['id'] for g in route.get('goals') or []}
    for i, g in enumerate(build.get('goals') or []):
        if g['id'] in ids:
            found.append(tr('часть «%s» файла плана, %s: %s') % (tr('билд'), 'goals[%d]' % i, word('dup', ())))
    return found


def verdict(found):
    """Отказ одной строкой: первые замечания и сколько ещё."""
    head = '; '.join(found[:MAX_SAY])
    return head if len(found) <= MAX_SAY else tr('%s (и ещё замечаний: %d)') % (head, len(found) - MAX_SAY)
