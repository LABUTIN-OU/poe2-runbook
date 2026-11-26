# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Sergei Labutin
# Additional terms under GPL-3.0 section 7: see NOTICE.md
"""Разбор лога Path of Exile 2 и расчёт состояния забега по плану.

Модуль ничего не пишет и не знает про сеть: на входе строки лога, план и
отметки, на выходе готовое к показу состояние. Поэтому его проверяют тесты
без запуска сервера (test_core.py).
"""
import bisect
import re
from datetime import datetime

import buildstage
import i18n
import logtext
import slotwear
from i18n import tr

RE_TS = re.compile(r'^(\d{4})/(\d\d)/(\d\d) (\d\d):(\d\d):(\d\d) ')
RE_GEN = re.compile(r'Generating level (\d+) area "([^"]+)"(?: with seed (\d+))?')
RE_SRC = re.compile(r'\[SCENE\] Set Source \[(.*)\]\s*$')
# Уровень героя, награда, гибель и очки умений — системные строки лога на языке клиента: их шаблоны берутся из
# таблицы игры (logtext.LogText). Имя героя игра называет только в них (при входе в игру — нет); оно остаётся
# в журнале забега и на этой странице: по нему игрок узнаёт свой забег в списке.
RE_FILTER = re.compile(r'\[Item Filter\] Finished reloading (?:online )?filter (.+?)\. Result: (true|false)', re.I)
RE_HASH = re.compile(r'Hash: ([0-9a-fA-F]+)')
# Взятый или снятый узел дерева восхождения. Каждое испытание даёт два очка, поэтому первый взятый
# узел забега — первое вознесение, третий одновременно взятый — второе, пятый — третье.
RE_ASCEND = re.compile(r'Successfully (allocated|unallocated) passive skill id: (Ascendancy\w+)')
# Каждый клик по дереву пассивных умений: узел взят или снят. id узла — тот же, что в данных дерева,
# которые выкладывает GGG (поле id), имя — как в игре на языке клиента.
RE_PASSIVE = re.compile(r'Successfully (allocated|unallocated) passive skill id: ([^,\s]+)(?:, name: (.*?))?\s*$')
ASCENDANCY_NODE = 'Ascendancy'   # так начинаются id узлов восхождения: у них свои очки
ATLAS_NODE = 'Atlas'             # так начинаются id узлов дерева атласа: своё дерево и свои очки
RE_MARKUP = re.compile(r'\[(?:[^\]|]*\|)?([^\]]*)\]')
RE_TOWN = re.compile(r'town|hideout', re.I)
# Реплика в чате: «Имя: текст». Так же выглядит местный чат других игроков, поэтому событие выдаётся
# только для реплик, которых ждёт план (поле heard у цели — коды строк таблицы игры), и хранит эти коды,
# а не строку лога. Код по тексту и говорящему находит logtext.LogText на языке клиента.
RE_SAY = re.compile(r'^\S+ \S+ \d+ \w+ \[INFO Client \d+\] ([^:]+): (.*)$')

# Первая зона нового персонажа: по ней определяется начало забега.
START_ZONE = ('G1_1', 1)
# Экран входа и выбора персонажа: игра пишет его как сцену без имени — после каждого запуска и при
# каждом выходе к списку героев. Какой герой вошёл, в логе нет, но между двумя такими строками герой
# один: это сессия. По ней игрок может сказать «сейчас играю героем такого-то забега».
CHAR_SCREEN = '(unknown)'
# С этой строки игра начинает писать лог при каждом запуске. Значит, до неё игра была закрыта:
# герой вышел не позже предыдущей строки лога.
LOG_OPENING = 'LOG FILE OPENING'
# Обычное закрытие игры она пишет сама — по этой строке выход виден сразу, а не при следующем запуске
# (в логе игрока так кончается 41 закрытие из 45; остальные — вылеты, их видно только по запуску).
# Строка сверяется целиком после метки журнала: реплика в чате с такими словами начинается с имени.
RE_CLOSING = re.compile(r'\] Closing game gracefully\s*$')
# Имя картинки вещи (поле icon у цели): файл static/icons/<имя>.webp. «item-…» — рисунок именно этой вещи,
# «type-…» — силуэт типа вещи («любой самострел»). Только такие буквы: имя уходит в адрес картинки.
# картинка цели-вещи: своя (item-…), силуэт типа (type-…) или рисунок базы из данных игры (art-…)
RE_ICON_NAME = re.compile(r'(?:item|type|art)-[a-z0-9-]+')
# Редкость предмета слота, какой его подбирают, — словами игры, как их пишут фильтры предметов
ITEM_RARITIES = ('Normal', 'Magic', 'Rare')


def line_ts(line):
    """Время строки лога в секундах эпохи или None, если строка без даты."""
    m = RE_TS.match(line)
    if not m:
        return None
    y, mo, d, h, mi, s = (int(x) for x in m.groups())
    try:
        return datetime(y, mo, d, h, mi, s).timestamp()
    except ValueError:
        return None


def fmt_ts(ts):
    return datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S') if ts else None


def run_id(ts):
    return datetime.fromtimestamp(ts).strftime('%Y%m%d-%H%M%S')


def is_town(code):
    return bool(RE_TOWN.search(code or ''))


def is_endgame(code):
    """Зона после кампании: убежище, откуда ходят на карты, и сами карты. С них открыт атлас."""
    return bool(re.match(r'^(G_Endgame|Map)', code or '', re.I))


def endgame_from(steps):
    """Номер первого шага маршрута на картах — с него у героя есть атлас (факт игры: в кампании атласа нет).
    Шаг на картах — шаг с зоной после кампании (убежище, карта) или шаг по уровню зоны: так записаны этапы
    карт, у самих карт постоянных кодов нет. None — карт в маршруте нет."""
    for k, s in enumerate(steps or []):
        if isinstance(s, dict) and (is_endgame(s.get('zone')) or is_int(s.get('level'))):
            return k
    return None


def act_of(code):
    """Название акта по коду зоны: G2_10_1 -> «Акт 2», P1_3 -> «Интерлюдия 1», G_Endgame_Town -> «Карты»."""
    if is_endgame(code):
        return tr('Карты')
    m = re.match(r'^([GP])(\d+)_', code or '')
    if not m:
        return tr('Прочее')
    return (tr('Акт %s') if m.group(1) == 'G' else tr('Интерлюдия %s')) % m.group(2)


def clean_markup(text):
    """«[Resistances|холоду]» -> «холоду», «[Spirit]» -> «Spirit»."""
    return RE_MARKUP.sub(r'\1', text).strip()


class LogParser:
    """Превращает строки Client.txt в события забега.

    Зона приходит двумя строками: «Generating level N area "КОД"» и следом
    «[SCENE] Set Source [Название]». Событие зоны выдаётся на второй строке.
    Строки «Set Source» без генерации (карта мира, «Акт 1») зону не меняют.
    """

    def __init__(self, watch=(), text=None):
        # text — тексты лога на языке клиента (logtext.LogText); без них — русские строки игры, реплик нет
        self.text = text or logtext.LogText()
        # watch — коды строк реплик, которых ждёт план (AsalaA2DreadnoughtCutOffHisHead): см. heard_ids
        self.watch = watch
        self.pending = None
        self.names = {}
        self.last_code = None
        self.last_filter = None
        self.last_points_ts = None
        self.asc_nodes = set()   # взятые сейчас узлы восхождения
        self.ascensions = 0      # сколько вознесений забега уже отмечено
        self.prev_ts = None      # время предыдущей строки лога
        self.in_game = False     # герой сейчас в игре (а не на экране персонажей и не при закрытой игре)

    def _leave(self, ts):
        """Герой вышел из игры: с этого времени и до следующей зоны время забега не идёт."""
        if not self.in_game:
            return []
        self.in_game = False
        return [{'type': 'leave', 'ts': ts}]

    def ascension_state(self):
        """Счёт вознесений героя, который сейчас играет: его запоминают, чтобы вернуть вместе с героем."""
        return set(self.asc_nodes), self.ascensions

    def set_ascension_state(self, state):
        """Возвращает счёт вознесений героя, к забегу которого вернулись (None — счёт с нуля)."""
        nodes, n = state or ((), 0)
        self.asc_nodes, self.ascensions = set(nodes), n

    def feed(self, line):
        ts = line_ts(line)
        if ts is None:
            return []
        out = self._events(line, ts)
        self.prev_ts = ts
        return out

    def _events(self, line, ts):
        if LOG_OPENING in line:
            return self._leave(self.prev_ts or ts)
        if RE_CLOSING.search(line):
            return self._leave(ts)
        m = RE_GEN.search(line)
        if m:
            level, code = int(m.group(1)), m.group(2)
            self.pending = {'ts': ts, 'code': code, 'level': level, 'seed': m.group(3)}
            if (code, level) == START_ZONE:
                self.last_code = None
                self.asc_nodes, self.ascensions = set(), 0
                # прежний герой, если он ещё числится в игре, вышел не позже этого момента
                out = self._leave(ts) + [{'type': 'start', 'ts': ts}]
                if self.last_filter:
                    # Фильтр, загруженный до старта, действует и в новом забеге.
                    out.append({'type': 'filter', 'ts': ts, 'id': self.last_filter, 'ok': True, 'carried': True})
                return out
            return []
        m = RE_SRC.search(line)
        if m:
            name = m.group(1).strip()
            if name == CHAR_SCREEN:
                return self._leave(ts) + [{'type': 'session', 'ts': ts}]
            if not name or name == '(null)':
                return []
            if self.pending:
                p, self.pending = self.pending, None
                self.names[name] = (p['code'], p['level'])
                self.last_code = p['code']
                self.in_game = True
                return [{'type': 'zone', 'ts': p['ts'], 'code': p['code'], 'level': p['level'],
                         'name': name, 'seed': p['seed']}]
            known = self.names.get(name)
            if known and known[0] != self.last_code:
                self.last_code = known[0]
                self.in_game = True
                return [{'type': 'zone', 'ts': ts, 'code': known[0], 'level': known[1],
                         'name': name, 'seed': None}]
            return []
        m = RE_FILTER.search(line)
        if m:
            ok = m.group(2).lower() == 'true'
            if ok:
                self.last_filter = m.group(1)
            h = RE_HASH.search(line)
            return [{'type': 'filter', 'ts': ts, 'id': m.group(1), 'ok': ok, 'hash': h.group(1) if h else None}]
        m = RE_PASSIVE.search(line)
        if m:
            taken, pid = m.group(1) == 'allocated', m.group(2)
            # Клик по дереву: по этим событиям страница знает, какие узлы взяты, без единой отметки рукой.
            out = [{'type': 'passive', 'ts': ts, 'op': 'take' if taken else 'drop', 'id': pid,
                    'name': clean_markup(m.group(3) or '')}]
            if not pid.startswith(ASCENDANCY_NODE):
                return out
            if not taken:
                self.asc_nodes.discard(pid)
                return out
            self.asc_nodes.add(pid)
            # Перекачка узлов (сняли и взяли другие) счёт не меняет: новое вознесение — только
            # когда взятых узлов стало больше, чем дают уже отмеченные испытания.
            if len(self.asc_nodes) <= 2 * self.ascensions:
                return out
            self.ascensions += 1
            return out + [{'type': 'ascend', 'ts': ts, 'n': self.ascensions}]
        text = self.text
        m = text.level.search(line) if text.level else None
        if m:
            return [{'type': 'level', 'ts': ts, 'name': m.group('name'), 'cls': m.group('cls'),
                     'level': int(m.group('level'))}]
        for rx, one, weapon in text.points:
            m = rx.search(line)
            if not m:
                continue
            # Награда приходит двумя строками в одну секунду: «очков пассивных умений: 2» — обычные очки
            # дерева — и «2 очка пассивных умений для набора оружия» — отдельные очки набора оружия.
            # Событие points считает их порознь; награда (reward) для целей «+2 очка» — одна на пару.
            n = one or int(m.group('n'))
            out = [{'type': 'points', 'ts': ts, 'n': n, 'weapon': weapon}]
            if self.last_points_ts != ts:
                self.last_points_ts = ts
                out.append({'type': 'reward', 'ts': ts, 'text': 'очки пассивных умений: +%s' % n,
                            'keys': [logtext.POINTS]})
            return out
        # награда — после очков умений: на некоторых языках строка очков подходит и под общий шаблон награды
        m = text.reward.search(line) if text.reward else None
        if m:
            # текст — как его написала игра (для журнала), keys — коды свойств: по ним награду узнаёт цель
            said = clean_markup(m.group('text'))
            return [{'type': 'reward', 'ts': ts, 'text': said, 'keys': text.reward_keys(said)}]
        m = text.slain.search(line) if text.slain else None
        if m:
            return [{'type': 'death', 'ts': ts, 'name': m.group('name')}]
        if self._index:
            m = RE_SAY.match(line)
            if m:
                ids = text.heard(self._index, m.group(1).strip(), m.group(2))
                if ids:
                    return [{'type': 'say', 'ts': ts, 'ids': ids}]
        return []

    @property
    def watch(self):
        return self._watch

    @watch.setter
    def watch(self, ids):
        """Новый список кодов строк, которых ждёт план: указатель реплик строится заново."""
        self._watch = tuple(ids or ())
        self._index = self.text.watch(self._watch) if self._watch else {}


class Run:
    """Один забег: события из лога, отметки игрока и ручные переходы по шагам."""

    def __init__(self, rid='unknown', started=None):
        self.id = rid
        self.started = started
        self.events = []
        self.marks = []
        self.moves = []
        # Пауза игрока («Пауза» / «Продолжить» на странице): [{'ts', 'on'}] — время забега и шага в паузе стоит.
        self.hold = []
        # Надетые вещи целиком: место (слот/линия) -> {'at': когда, 'item': разобранная вещь}.
        # Запоминаются по слову игрока «надеть» (herostats.py).
        self.worn = {}
        # Статы этих вещей: место -> {стат: число}; считает программа перед сборкой состояния.
        self.gear = {}
        # Игра хоть раз написала в тексте скопированной вещи «Вы не можете использовать этот предмет»:
        # значит, клиент эту строку пишет, и её отсутствие — тоже ответ (wearcheck.py).
        self.told = False
        # Какой атрибут игрок взял в узле «Характеристика» на самом деле, когда это не то, что в плане
        # (или узла в плане нет): узел -> str / dex / int. Игра этого в лог не пишет — называет игрок,
        # на карте дерева (wearcheck.py).
        self.picks = {}
        # Умения (и камни поддержки со своим шагом «Снять»), которые игрок снял сам — кнопка «Снять» на странице: цель ->
        # когда. Игра снятие камня в лог не пишет; без отметки снятое уходит со страницы в конце шага «Снять».
        self.off = {}


def merged_length(spans, lo, hi):
    """Длина объединения отрезков (a, b), обрезанных по [lo, hi], секунды: отрезки могут перекрываться (герой вышел из
    игры, пока она стояла на паузе) — общее считается один раз."""
    total, reach = 0, lo
    for a, b in sorted((max(a, lo), min(b, hi)) for a, b in spans):
        a = max(a, reach)
        if b > a:
            total += b - a
            reach = b
    return total


def stopped_spans(timeline):
    """Отрезки, когда время забега стоит: (готовые отрезки, вне игры с, пауза с). Событие leave — герой вышел (экран
    персонажей или игра закрыта), следующая зона — вернулся. hold — слово игрока «Пауза» / «Продолжить» на странице:
    пауза снимается и сама, когда герой заходит в боевую зону (город и убежище её не снимают — там как раз разбирают
    добычу и крафтят). Незакрытые отрезки — «с» (None — их нет)."""
    spans, out, held = [], None, None
    for e in timeline:
        if e['type'] == 'leave' and out is None:
            out = e['ts']
        elif e['type'] == 'zone':
            if out is not None:
                spans.append((out, e['ts']))
                out = None
            if held is not None and not is_town(e.get('code') or ''):
                spans.append((held, e['ts']))
                held = None
        elif e['type'] == 'hold':
            if e.get('on') and held is None:
                held = e['ts']
            elif not e.get('on') and held is not None:
                spans.append((held, e['ts']))
                held = None
    return spans, out, held


def clean_time(events, started, end, hold=()):
    """Чистое время забега к моменту end, секунды: без отрезков, когда героя не было в игре и когда игра стояла на
    паузе (hold — слова игрока: [{'ts', 'on'}]).

    Тот же счёт, что у таймера на странице (stopped_spans). Нужен для списка забегов, где полный расчёт каждого забега
    был бы лишним.
    """
    t0 = started or (events[0]['ts'] if events else end)
    timeline = sorted(list(events) + [dict(h, type='hold') for h in hold], key=lambda e: e['ts'])
    spans, out, held = stopped_spans(timeline)
    spans += [(s, end) for s in (out, held) if s is not None and s < end]
    return max(0, int(end - t0 - merged_length(spans, t0, end)))


def hero_clock(events, hold, started, end):
    """Часы героя до момента end. Ответ: (его события не позже end, по порядку; функция «чистое время героя к моменту
    t» — тот же счёт, что у таймера забега: без времени вне игры и на паузе; с какого времени герой на паузе, или None)."""
    events = sorted((e for e in events if e['ts'] <= end), key=lambda e: e['ts'])
    timeline = sorted(events + [dict(h, type='hold') for h in hold if h['ts'] <= end], key=lambda e: e['ts'])
    away, out_since, held_since = stopped_spans(timeline)
    t0 = started or (timeline[0]['ts'] if timeline else end)

    def active(t):
        t = max(t, t0)
        spans = away + [(s, t) for s in (out_since, held_since) if s is not None and s < t]
        return t - t0 - merged_length(spans, t0, t)

    return events, active, held_since


def zone_visits(events, end):
    """Заходы героя по порядку: (с, по, событие зоны) — до следующей зоны, выхода из игры или момента end; выход из
    игры — (время, время, None). Второе в ответе — номер захода, который ещё идёт (герой в зоне и сейчас), или None."""
    visits, cur = [], None
    for e in events:
        if e['type'] in ('zone', 'leave'):
            if cur is not None:
                visits.append((cur['ts'], e['ts'], cur))
            cur = e if e['type'] == 'zone' else None
            if e['type'] == 'leave':
                visits.append((e['ts'], e['ts'], None))
    going = None
    if cur is not None:
        going = len(visits)
        visits.append((cur['ts'], end, cur))
    return visits, going


def map_copies(visits):
    """Карты, которые герой начинал заново. Герой вышел из игры в боевой зоне, а следующий его вход в эту зону — уже в
    НОВУЮ её копию (копию игра называет числом seed): карту пришлось проходить с начала. Так в логе виден уход с карты
    через выбор героя, когда оставаться на ней опасно: вход «в город», возврат на карту — и карта создана заново.
    Попыткой НЕ считается: выход из игры и возврат в ту же копию (вышел — продолжил); новая копия без выхода из игры
    (вернулся на карту через час, прежняя копия истекла); карты атласа — там новая копия и есть новая карта.

    visits — заходы героя (zone_visits). Ответ: (fresh, dropped). fresh — {(зона, копия)}: копии, с которых карта начата
    заново. dropped — {(зона, копия): номер}: брошенные копии по порядку, с 1 — попытки, прерванные выходом из игры."""
    fresh, dropped = set(), {}
    spot, quit_in = None, {}      # (зона, копия), где герой сейчас; зона -> копия, в которой он вышел из игры
    for _, _, z in visits:
        if z is None:
            if spot:
                quit_in[spot[0]] = spot[1]
            spot = None
            continue
        code, seed = z['code'], z.get('seed')
        if is_town(code) or is_endgame(code) or not seed:
            spot = None
            continue
        old = quit_in.pop(code, None)
        if old is not None and old != seed:
            fresh.add((code, seed))
            dropped.setdefault((code, old), len(dropped) + 1)
        spot = (code, seed)
    return fresh, dropped


def restarts(events, hold, started, end):
    """Карты, которые герой начинал заново (map_copies), — по зонам, без плана: это факт игры, а не маршрута.
    Ответ: {код зоны: {'name', 'again' — сколько раз зону начинали заново, 'lost' — чистое время в брошенных копиях}} —
    все боевые зоны кампании, где герой был; зона, которую он заново не начинал, — с нулями."""
    events, active, _ = hero_clock(events, hold, started, end)
    visits, _ = zone_visits(events, end)
    _, dropped = map_copies(visits)
    out = {}
    for a, b, z in visits:
        if z is None or is_town(z['code']) or is_endgame(z['code']):
            continue
        rec = out.setdefault(z['code'], {'name': z.get('name') or z['code'], 'again': 0, 'lost': 0})
        if (z['code'], z.get('seed')) in dropped:
            rec['lost'] += max(0, active(b) - active(a))
    for code, _ in dropped:
        out[code]['again'] += 1
    return out


def step_spans(plan, events, hold, started, pos_log, end):
    """Чем герой был занят: его чистое время до момента end, разложенное по шагам плана и по месту. Один счёт на всю
    программу: по нему идёт время шага на странице «Игра» и собран режим «Разбор» (review.py).

    Время идёт шагу, которым герой ЗАНЯТ, а не шагу, который открыт на странице: кнопка «Шаг пройден», нажатая до прихода
    на новую карту, время не переносит. Шаг сменяется, когда герой пришёл в зону другого шага работать — задержался там
    дольше порога (touchSeconds плана, TOUCH_SECONDS). Короче порога шаг сменит только зона СЛЕДУЮЩЕГО шага, не записанная
    у текущего точкой перехода, и только если герой пошёл из неё дальше (короткий шаг: пройти карту насквозь), а не
    вернулся — в зону своего шага или сюда же после города. Остальное короткое — «заглянул»: открыл точку перехода, взял
    вход, прошёл мимо. Заход, который ещё идёт, считается приходом и раньше порога, если страница уже на этом шаге (игрок
    сам нажал «Шаг пройден»; обычный переход на следующую карту): кончится он коротким — станет «заглянул». Время делится
    по месту (kind):
      zone — зоны шага (его зона и «ещё зоны»);    peek — короткий заход на другую карту;
      town — город и убежище;                       off  — зоны, которых в маршруте нет (Бездна и т. п.).
    Так город после карты остаётся у шага этой карты, даже если по дороге герой заглянул на следующую за точкой перехода.
    Шаг без своей зоны («После восхождения») и шаг-город — работа в городе: пока такой шаг текущий на странице, герой
    занят им, и город идёт ему как zone. Время вне игры и на паузе не идёт никому. Сумма по кускам — чистое время героя.

    events, hold — события и паузы забега (в счёт идут те, что не позже end); pos_log — когда какой шаг становился текущим
    на странице ([время, номер шага]): им выбирается шаг, когда зона значится у нескольких шагов (Грельвуд и «Грельвуд ·
    дерево»), и узнаётся шаг без своей зоны.

    Карту, начатую заново (map_copies), куски отмечают сами: 'again' — первый кусок новой копии карты, 'drop' — кусок в
    брошенной копии (её номер), 'quit' — последний кусок брошенной копии: здесь попытка прервана. Попытка считается
    шагу, которым герой был занят, когда вышел из игры, — один раз, даже если копия карты досталась двум шагам.

    Ответ: {'pieces': куски по порядку — {'a', 'b' — время с и по, 'step' — номер шага, 'kind', 'name' — зона, 'dur' —
    чистые секунды}, кусок вида 'leave' — метка «вышел из игры»; 'active': функция — чистое время к моменту t; 'busy':
    шаг, которым герой занят в конце (None — времени ещё нет); 'recheck': когда разложение изменится само, без новых
    строк лога (идущий короткий заход дотянет до порога), или None}.
    """
    steps = plan['steps']
    dwell = plan.get('touchSeconds') or TOUCH_SECONDS
    events, active, held_since = hero_clock(events, hold, started, end)

    def clean(a, b):
        return max(0, active(b) - active(a))

    out = {'pieces': [], 'active': active, 'busy': None, 'recheck': None}
    if not steps:
        return out
    step_towns = {s['zone'] for s in steps if s.get('zone') and is_town(s['zone'])}
    main, touch = {}, {}      # зона -> шаги, у которых она своя (зона и «ещё зоны») / точка перехода
    for i, s in enumerate(steps):
        for z in [s.get('zone')] + list(s.get('also') or []):
            if z:
                main.setdefault(z, []).append(i)
        for t in s.get('touch') or []:
            if isinstance(t, dict) and t.get('zone'):
                touch.setdefault(t['zone'], []).append(i)

    def stage(i):
        """Этап карт: шаг по уровню зоны — его зоны в плане не названы, это любые карты."""
        return is_int(steps[i].get('level'))

    def whole(i):
        """Шаг без своей боевой зоны: по событию или шаг-город — его работа идёт в городе."""
        return not stage(i) and (not steps[i].get('zone') or steps[i]['zone'] in step_towns)

    def next_zoned(i):
        """Следующий по маршруту шаг со своей боевой зоной (шаги по событию и шаги-города между ними не в счёт)."""
        return next((k for k in range(i + 1, len(steps))
                     if steps[k].get('zone') and steps[k]['zone'] not in step_towns), None)

    pos_log = [(ts, p) for ts, p in pos_log if isinstance(p, int) and not isinstance(p, bool) and 0 <= p < len(steps)]
    log_ts = [ts for ts, _ in pos_log]

    def page_step(t):
        k = bisect.bisect_right(log_ts, t) - 1
        return pos_log[k][1] if k >= 0 else None

    def nearest(cands, p):
        """Шаг с этой зоной, ближайший к текущему: сам текущий, иначе ближайший позади, иначе впереди."""
        if p is None:
            return cands[0]
        if p in cands:
            return p
        back = [k for k in cands if k < p]
        return back[-1] if back else cands[0]

    # Заходы: (с, по, зона) — до следующей зоны, выхода из игры или момента end; выход из игры — (время, время, None);
    # going — заход, который ещё идёт (герой в зоне и сейчас): его номер
    visits, going = zone_visits(events, end)
    fresh, dropped = map_copies(visits)      # карты, начатые заново, и брошенные их копии

    # Что было после захода: заходил ли герой в город и в какую боевую зону пришёл следом (None — больше никуда).
    # По этому короткий заход отличается от короткого шага: заглянул и вернулся — или пошёл дальше.
    after, field = {}, [(k, v[2]['code']) for k, v in enumerate(visits) if v[2] is not None]
    for n, (k, code) in enumerate(field):
        stop, nxt = False, None
        for _, c in field[n + 1:]:
            if is_town(c):
                stop = True
            else:
                nxt = c
                break
        after[k] = (stop, nxt)

    doing = None       # шаг, которым герой занят
    cuts = sorted(set(log_ts))
    for k, (a, b, z) in enumerate(visits):
        if z is None:
            if doing is not None:
                out['pieces'].append({'a': a, 'b': a, 'step': doing, 'kind': 'leave', 'name': None, 'dur': 0})
            continue
        code, town = z['code'], is_town(z['code'])
        stay = clean(a, b)      # сколько длился заход целиком: по нему видно, задержался герой или заглянул
        # заход режется там, где на странице сменился шаг: шаг без своей зоны («После восхождения») начинается в городе
        lo, hi = bisect.bisect_right(cuts, a), bisect.bisect_left(cuts, b)
        edges = [a] + cuts[lo:hi] + [b]
        for x, y in zip(edges, edges[1:]):
            p = page_step(x)
            here = doing if doing is not None else p if p is not None else 0
            if p is not None and whole(p) and town:
                owner, kind = p, 'zone'           # шаг по событию и шаг-город: город — его работа
                doing = p
            elif town:
                owner, kind = here, 'town'
            elif doing is not None and doing in main.get(code, ()):
                owner, kind = doing, 'zone'       # зона шага, которым герой занят
            elif code in main:
                cand = nearest(main[code], p if p is not None else doing)
                stop, nxt = after[k]
                if doing is None or stay >= dwell:
                    peek = False                  # задержался
                elif k == going and cand == p:
                    peek = False                  # заход ещё идёт, а страница уже на этом шаге: герой пришёл
                elif doing in touch.get(code, ()) or cand != next_zoned(doing):
                    peek = True                   # точка перехода своего шага; шаг позади или через шаг — как у страницы
                else:
                    # следующий шаг, а пробыл мало: заглянул, если вернулся в зону своего шага или пришёл сюда же
                    # после города; пошёл отсюда дальше — это и был шаг (короткий)
                    peek = (nxt is not None and doing in main.get(nxt, ())) or (nxt == code and stop)
                if peek:
                    owner, kind = here, 'peek'
                    if k == going and held_since is None:
                        # заход ещё идёт: дотянет до порога — станет приходом, и его время уйдёт другому шагу
                        out['recheck'] = end + (dwell - stay)
                else:
                    owner, kind = cand, 'zone'    # пришёл работать: задержался или пошёл отсюда дальше по маршруту
                    doing = cand
            elif p is not None and stage(p):
                owner, kind = p, 'zone'           # этап карт: любая карта
                doing = p
            elif stay < dwell and here in touch.get(code, ()):
                owner, kind = here, 'peek'        # точка перехода этого шага в зоне, которой у маршрута нет
            else:
                owner, kind = here, 'off'         # зоны нет в маршруте
            d = clean(x, y)
            if d < 1 and y - x < 1 and k != going:
                continue               # зона мелькнула в логе (вход и сразу следующая): в счёт не идёт
            piece = {'a': x, 'b': y, 'step': owner, 'kind': kind, 'name': z.get('name') or code, 'dur': d}
            copy = (code, z.get('seed'))
            if copy in dropped:
                piece['drop'] = dropped[copy]
            if copy in fresh:
                piece['again'] = True          # метка — на первом куске новой копии
                fresh.discard(copy)
            out['pieces'].append(piece)
    # последний кусок каждой брошенной копии: на нём попытка прервана
    for piece in {p['drop']: p for p in out['pieces'] if p.get('drop')}.values():
        piece['quit'] = True
    out['busy'] = next((p['step'] for p in reversed(out['pieces']) if p['kind'] != 'leave'), None)
    return out


# События, по которым наступает шаг без своей зоны: первое вознесение и следующие за ним
# (второе — после испытания Хаоса). Шаг с таким полем event наступает сам, по строке лога.
STEP_EVENTS = ('ascend', 'ascend2', 'ascend3', 'ascend4')
# Восхождений в игре четыре: каждая ступень испытания даёт два очка Восхождения (так их зовёт клиент), всего восемь.
ASCENSIONS = 4
# Как восхождение называет страница — по его номеру; номер считает norm_plan по порядку маршрута.
ASC_TITLES = (tr('Первое восхождение'), tr('Второе восхождение'), tr('Третье восхождение'), tr('Четвёртое восхождение'))
# То же — словами о событии шага («наступит сам, когда герой возьмёт второе восхождение»).
ASC_WORDS = (tr('первое восхождение'), tr('второе восхождение'), tr('третье восхождение'), tr('четвёртое восхождение'))


def ascension_title(k):
    """Название восхождения номер k: «Третье восхождение»; сверх четырёх — так и сказано."""
    return ASC_TITLES[k - 1] if 1 <= k <= len(ASC_TITLES) else tr('Восхождение сверх четырёх')


def ascend_event(n):
    """Имя события для вознесения номер n: 1 -> ascend, 2 -> ascend2."""
    return 'ascend' if n == 1 else 'ascend%d' % n


def heard_of(g):
    """Реплики, по которым цель отмечается сама (поле heard): коды строк таблицы игры — один или список,
    хватит любой. Код один на всех языках клиента («AsalaA2DreadnoughtCutOffHisHead» — «Дело сделано.»).

    Список нужен, когда победа звучит по-разному: Белый Яма то сдаётся сам («Ай! Хорошо, хорошо»),
    то о его поражении объявляет Навали («Свершилось!»); у босса бывает несколько предсмертных фраз.
    """
    h = g.get('heard')
    items = [h] if isinstance(h, str) else h if isinstance(h, list) else []
    return [x.strip() for x in items if isinstance(x, str) and x.strip()]


def reward_of(g):
    """Награда цели из лога (поле reward): коды свойств игры (base_cold_damage_resistance_%) — один или список,
    хватит любого; logtext.POINTS — очки пассивных умений. Строка лога о награде узнаётся по кодам на любом
    языке клиента (logtext.LogText.reward_keys)."""
    want = g.get('reward')
    items = [want] if isinstance(want, str) else want if isinstance(want, list) else []
    return [x.strip() for x in items if isinstance(x, str) and x.strip()]


def heard_ids(plan):
    """Коды строк реплик, которых ждёт план (поле heard у целей): только их парсер лога ищет в чате."""
    return tuple(sorted({p for g in plan.get('goals') or [] for p in heard_of(g)}))


def parse_clock(x):
    """Время из плана в секундах: «5:30» -> 330, «1:05:00» -> 3900, число — уже секунды. Иначе None."""
    if isinstance(x, int) and not isinstance(x, bool):
        return x if x > 0 else None
    if not isinstance(x, str) or not re.fullmatch(r'\d+(:[0-5]\d){1,2}', x.strip()):
        return None
    n = 0
    for part in x.strip().split(':'):
        n = n * 60 + int(part)
    return n or None


# Какая доля цели шага должна пройти, чтобы страница предупредила: времени осталось мало.
TIME_WARN = 0.8


def is_int(x):
    return isinstance(x, int) and not isinstance(x, bool)


# число в названии цели по стату: его знак и знак процента — вид, в котором показывают число стата на предмете
RE_AMOUNT = re.compile(r'(\+?)\d+(?:[.,]\d+)?(\s?%)?')


def amount_like(title, value):
    """Число стата на предмете в том же виде, в каком цель называет нужное: «от +3» — «+1», «от 75%» — «60%»,
    «от 120» — «95». Стата на предмете нет — пустая строка."""
    if not value:
        return ''
    value = round(value, 1)
    m = RE_AMOUNT.search(str(title or ''))
    sign, unit = (m.group(1), m.group(2) or '') if m else ('', '')
    return '%s%s%s' % (sign, int(value) if value == int(value) else value, unit)


def gem_ladders(goals, table, problems):
    """Достраивает лесенки уровня камня.

    У умения с полем gemFrom (стартовый уровень камня: ниже такое умение не сделать) уровни идут
    от стартового до последнего в таблице gemLevels — в ней уровень героя, с которого камень такого
    уровня можно носить. Каждый уровень в плане не пишут: недостающие ступени появляются здесь.
    Записанные в плане уровни (цели со сроком: «к такому-то шагу — 8») остаются как есть и встают
    на своё место по порядку. Стартовый уровень даёт само умение: взяли камень — уровень уже есть.
    """
    skills = {g['id']: g for g in goals if g.get('kind') == 'skill' and g.get('gemFrom') is not None}
    for sid, s in list(skills.items()):
        if not table:
            problems.append(tr('Умение «%s»: нет таблицы gemLevels') % sid)
        elif not is_int(s['gemFrom']) or not 1 <= s['gemFrom'] <= len(table):
            problems.append(tr('Умение «%s»: стартовый уровень камня вне таблицы gemLevels') % sid)
        else:
            continue
        del skills[sid]
    if not skills:
        return goals

    def level_of(g):
        """Уровень камня, если цель — записанная в плане ступень лесенки одного из этих умений."""
        if g.get('part') == 'level' and g.get('for') in skills and str(g.get('title')).isdigit():
            return int(g['title'])
        return None

    written = {}
    for g in goals:
        n = level_of(g)
        if n is not None:
            written.setdefault(g['for'], {})[n] = dict(g)
    out = []
    for g in goals:
        if level_of(g) is not None:
            continue
        out.append(g)
        if g['id'] not in skills:
            continue
        mine, first = written.get(g['id'], {}), g['gemFrom']
        for n in sorted(set(mine) | set(range(first, len(table) + 1))):
            rung = mine.get(n)
            if rung is None:
                tail = g['id'][6:] if g['id'].startswith('skill-') else g['id']
                rung = {'id': 'gem%d-%s' % (n, tail), 'kind': 'gem', 'part': 'level', 'title': str(n), 'for': g['id']}
                rung.update({k: g[k] for k in ('use', 'until', 'group') if g.get(k)})
            if n < first or n > len(table):
                problems.append(tr('Цель «%s»: уровня камня %d у умения «%s» не бывает') % (rung['id'], n, g['id']))
            else:
                if table[n - 1] > 1:
                    rung.setdefault('hero', table[n - 1])
                if n == first:
                    rung.setdefault('grantedBy', g['id'])
            out.append(rung)
    return out


def skill_steps(goals, step_ids):
    """Шаги умения и его частей — от шага самого умения, а не от технических полей.

    Автор называет у умения два шага: «Надеть» (need) — на этом шаге умение берут и начинают использовать, к концу
    шага оно должно быть у героя, — и «Снять» (until): на нём умение снимают, после него оно не нужно. Начало использования —
    тот же шаг need: раньше план умения не ждёт (игрок может и опередить — отметит раньше). Поэтому прежнее поле
    use у умения не читается, как и from (с какого шага искать) и hero (с какого уровня героя): гнездо и уровень
    камня программа знает из данных игры. Камни поддержки и уровни камня живут при умении: начинают с ним, а
    снимают их вместе с ним (своё until у части остаётся, если оно записано). Камень поддержки план ждёт с его
    собственного шага (derive). Исходные записи не меняются: изменённая цель — новая запись."""
    skills = {g['id']: g for g in goals if g.get('kind') == 'skill'}
    out = []
    for g in goals:
        sk = g if g.get('kind') == 'skill' else skills.get(g.get('for'))
        if sk is None:
            out.append(g)
            continue
        own = {k: v for k, v in g.items() if k not in ('use', 'from') and (k != 'hero' or g.get('kind') == 'gem')}
        if sk.get('need') in step_ids:
            own['use'] = sk['need']
        if g is not sk and not own.get('until') and sk.get('until'):
            own['until'] = sk['until']
        out.append(own)
    return out


def norm_stages(raw, plan, catalog, problems):
    """Этапы билда (раздел stages) в рабочем виде: по порядку шагов маршрута, первый — с начала забега.

    Этап — шаг, с которого билд меняет направление (from; у первого шага нет), его название и то, что
    на нём меняется целиком (см. buildstage.py): tree и atlas — id версии дерева, kind — род баз защиты
    из данных игры, attrs — атрибуты, stats — статы билда по важности (id стата из таблицы каталога;
    cap — свой порог вместо порога каталога). Чего этап не назвал, действует как на прежнем. Параметр,
    записанный с ошибкой, отбрасывается (с замечанием), сам этап остаётся. plan — уже с шагами и деревьями.
    """
    for key, what in (('stats', tr('статы')), ('defence', tr('база защиты'))):
        if raw.get(key) is not None:
            problems.append(tr('Раздел %s больше не читается: %s — параметр этапа билда (stages)') % (key, what))
    stat_table = ((catalog or {}).get('stats') or {}).get('stats')
    kinds = {t for b in ((catalog or {}).get('bases') or {}).values() for t in b.get('tags') or () if t.endswith('_armour')}
    step_at = {s['id']: i for i, s in enumerate(plan['steps'])}
    versions = {key: {ph['id'] for ph in plan[key]['phases']} for key in ('tree', 'atlas')}
    out, ids, starts = [], set(), set()
    for st in raw.get('stages') if isinstance(raw.get('stages'), list) else []:
        if not (isinstance(st, dict) and isinstance(st.get('id'), str) and st['id'].strip()):
            problems.append(tr('Этапы билда: у записи нет id'))
            continue
        sid = st['id']
        if sid in ids:
            problems.append(tr('Этап «%s» записан дважды') % sid)
            continue
        start = st.get('from')
        if out and start not in step_at:
            problems.append(tr('Этап «%s»: нет шага «%s» (from)') % (sid, start))
            continue
        if not out and start is not None:
            problems.append(tr('Этап «%s»: первый этап действует с самого начала — шаг начала (from) ему не нужен') % sid)
        if out and start in starts:
            problems.append(tr('Этап «%s»: с шага «%s» уже начинается другой этап') % (sid, start))
            continue
        rec = {k: v for k, v in st.items() if k != 'from'}
        if out:
            rec['from'] = start
            starts.add(start)
        for key, label in (('tree', tr('дерева')), ('atlas', tr('атласа'))):
            if rec.get(key) is not None and rec[key] not in versions[key]:
                problems.append(tr('Этап «%s»: версии %s «%s» в билде нет') % (sid, label, rec[key]))
                del rec[key]
        kind = rec.get('kind')
        if kind is not None and (not (isinstance(kind, str) and kind.strip()) or (kinds and kind not in kinds)):
            problems.append(tr('Этап «%s»: kind — род баз из данных игры (str_armour, int_armour, …)') % sid)
            del rec['kind']
        attrs = rec.get('attrs')
        if attrs is not None and not (isinstance(attrs, list) and all(
                isinstance(a, str) and (stat_table is None or a in stat_table) for a in attrs)):
            problems.append(tr('Этап «%s»: attrs — список атрибутов из данных игры (str, dex, int)') % sid)
            del rec['attrs']
        if rec.get('stats') is not None:
            stats = []
            for s in rec['stats'] if isinstance(rec['stats'], list) else [None]:
                s = {'id': s} if isinstance(s, str) else s
                if not (isinstance(s, dict) and isinstance(s.get('id'), str) and s['id'].strip()):
                    problems.append(tr('Этап «%s»: stats — список статов (id из таблицы статов данных игры)') % sid)
                elif stat_table is not None and s['id'] not in stat_table:
                    problems.append(tr('Этап «%s»: стата «%s» нет в таблице статов данных игры') % (sid, s['id']))
                elif any(x['id'] == s['id'] for x in stats):
                    problems.append(tr('Этап «%s»: стат «%s» записан дважды') % (sid, s['id']))
                else:
                    stats.append(s)
            rec['stats'] = stats
        ids.add(sid)
        out.append(rec)
    # по порядку шагов: первый (без шага) остаётся первым
    return out[:1] + sorted(out[1:], key=lambda st: step_at[st['from']])


def norm_plan(raw, catalog=None):
    """Приводит план к рабочему виду и возвращает список замечаний к нему.
    catalog — каталог данных игры (gamedata.load): по нему сверяются статы билда."""
    raw = raw if isinstance(raw, dict) else {}
    # Что носят в слоте по ходу забега, записано его периодами (wear): из них слоту — все его классы, его
    # целям — срок периода (slotwear). Слот старого вида (classes у слота, until и gear у целей) идёт как есть.
    raw = slotwear.expand(raw)
    filters = raw.get('filters') if isinstance(raw.get('filters'), dict) else {}
    raw_goals = raw.get('goals') or []
    plan = {
        'title': str(raw.get('title') or ''),
        'slots': [s for s in (raw.get('slots') or []) if isinstance(s, dict) and s.get('id')],
        'steps': [s for s in (raw.get('steps') or []) if isinstance(s, dict) and s.get('id')],
        'goals': [g for g in raw_goals if isinstance(g, dict) and g.get('id')],
        'filters': {k: v for k, v in filters.items() if isinstance(v, dict)},
        'touchSeconds': raw.get('touchSeconds') if isinstance(raw.get('touchSeconds'), (int, float)) else None,
        # Доля цели шага, после которой страница предупреждает, что времени мало (обычно 0.8).
        'timeWarn': raw.get('timeWarn') if isinstance(raw.get('timeWarn'), float) and 0 < raw['timeWarn'] < 1 else None,
        # Уровень героя, с которого камень умения N-го уровня можно носить (N — место в списке, с 1).
        'gemLevels': [x for x in (raw.get('gemLevels') or []) if is_int(x)],
        # В каком порядке идут группы целей на странице (см. derive).
        'groupOrder': [str(x) for x in (raw.get('groupOrder') or []) if isinstance(x, str) and x.strip()],
        # Герой билда: класс и вознесение, как их называют данные дерева GGG («Sorceress», «Disciple of
        # Varashta»). От класса зависят стартовые атрибуты; вознесения у билда может и не быть.
        'hero': {k: v.strip() for k, v in (raw.get('hero') if isinstance(raw.get('hero'), dict) else {}).items()
                 if k in ('class', 'ascendancy') and isinstance(v, str) and v.strip()},
        # Свои статы билда (gamedata.with_stats): проверяет и добавляет в таблицу статов тот, кто читает
        # план, — сюда они идут как записаны, для страницы «Билд».
        'statDefs': [d for d in raw.get('statDefs') if isinstance(d, dict) and d.get('id')]
        if isinstance(raw.get('statDefs'), list) else [],
    }
    problems = []
    # Комплектов в плане больше нет: вещи и камни меняют по одному, поэтому срок — у каждой цели свой
    # (use — с какого шага её вещь носят или камень вставлен, until — по какой шаг), а что это за вещь,
    # говорит поле gear цели.
    if raw.get('kits'):
        problems.append(tr('Раздел kits больше не читается: с какого шага и по какой предмет или камень в ходу, '
                        'говорит сама цель (use, until), что это за предмет — её поле gear'))
    if any(g.get('kit') is not None for g in plan['goals']):
        problems.append(tr('Поле kit у целей больше не читается (%d): срок у каждой цели свой — use и until')
                        % sum(1 for g in plan['goals'] if g.get('kit') is not None))
    # Какие вещи идут в слот, говорит его поле classes — как в строке «Класс предмета».
    for owner in plan['slots']:
        cl = owner.get('classes')
        if cl is not None and not (isinstance(cl, list) and all(isinstance(c, str) and c.strip() for c in cl)):
            problems.append(tr('Слот «%s»: classes — список классов предметов, как их пишет игра') % owner['id'])
        # периоды слота: с какого шага какие классы предметов в нём носят; цель слота стоит в одном из них
        problems += slotwear.problems(owner, plan['goals'], slotwear.step_index(plan['steps']))
    # какой слот — основная рука и какой вторая (по данным игры): двуручное оружие вторую руку закрывает
    plan['hands'] = slotwear.hands(plan['slots'], catalog)
    stat_table = ((catalog or {}).get('stats') or {}).get('stats')
    # Цель по стату: «к этому шагу на вещи слота стата не меньше min» (скипетр с уровнем умений
    # приспешников к вознесению). Она живёт частью своего слота (part) и отмечается сама — по вещи,
    # которую игрок запомнил надетой (см. derive).
    for g in plan['goals']:
        if g.get('stat') is None:
            continue
        if not (g.get('slot') and g.get('part')):
            problems.append(tr('Цель «%s»: цели по стату нужны слот (slot) и имя части (part)') % g['id'])
        elif not isinstance(g.get('min'), (int, float)) or isinstance(g.get('min'), bool):
            problems.append(tr('Цель «%s»: min — число, меньше которого стата быть не должно') % g['id'])
        elif stat_table is not None and g['stat'] not in stat_table:
            problems.append(tr('Цель «%s»: стата «%s» нет в таблице статов данных игры') % (g['id'], g['stat']))
    # Дерево пассивных умений: версии — дерево целиком, каким оно должно быть на своём отрезке забега.
    # У версии название и полный порядок узлов от старта класса: id узла — как в логе игры и в данных
    # дерева GGG, name — как в игре, kind — notable / attribute / socket / keystone (у обычного малого
    # узла поля нет), attr — какой атрибут брать в узле «Характеристика». С какого шага версия действует,
    # говорит не она сама, а этап билда, который её назвал (раздел stages).
    def tree_phases(section, label):
        phases = []
        for ph in section.get('phases') or []:
            if not (isinstance(ph, dict) and ph.get('id')):
                continue
            if ph.get('from') is not None:
                problems.append(tr('%s, версия «%s»: поле from больше не читается — с какого шага версия '
                                'действует, говорит этап билда (stages)') % (label, ph['id']))
            nodes, seen = [], set()
            for n in ph.get('nodes') or []:
                if not (isinstance(n, dict) and n.get('id')):
                    continue
                if n['id'] in seen:
                    problems.append(tr('%s, версия «%s»: узел «%s» записан дважды') % (label, ph['id'], n['id']))
                    continue
                seen.add(n['id'])
                nodes.append(n)
            phases.append(dict(ph, nodes=nodes))
        return phases

    tree = raw.get('tree') if isinstance(raw.get('tree'), dict) else {}
    # attr у всего дерева — атрибут по умолчанию для узлов «Характеристика» («инт»); у отдельного узла
    # своё поле attr важнее.
    plan['tree'] = {'attr': tree['attr'] if isinstance(tree.get('attr'), str) and tree['attr'].strip() else None,
                    'phases': tree_phases(tree, tr('Дерево'))}
    # Дерево атласа записано так же, разделом atlas: версии с шагом начала и порядком узлов. В атласе
    # деревьев несколько (основное и по механикам), у каждого свои очки; порядок версии — общий для всех.
    atlas = raw.get('atlas') if isinstance(raw.get('atlas'), dict) else {}
    plan['atlas'] = {'phases': tree_phases(atlas, tr('Атлас'))}
    plan['goals'] = skill_steps(plan['goals'], {s['id'] for s in plan['steps']})
    plan['goals'] = gem_ladders(plan['goals'], plan['gemLevels'], problems)
    # Восхождение (запись справочника вида ascension) автор ставит на шаги, где берёт очки Восхождения, — Испытание Сехем
    # или Испытание Хаоса, какое выберет. Какое оно по счёту, говорит порядок маршрута: номер (ascend) и название
    # («Третье восхождение») считает программа. Сверх четырёх номер тоже ставится — такое восхождение не отметится
    # никогда, о нём говорит проверка плана (buildcheck).
    at = {s['id']: i for i, s in enumerate(plan['steps'])}
    asc = sorted((g for g in plan['goals'] if g.get('kind') == 'ascension'), key=lambda g: at.get(g.get('need'), len(at)))
    nth = {id(g): k for k, g in enumerate(asc, 1)}
    plan['goals'] = [dict(g, ascend=nth[id(g)], title=ascension_title(nth[id(g)])) if id(g) in nth else g
                     for g in plan['goals']]
    slot_ids = {s['id'] for s in plan['slots']}
    step_ids, goal_ids = set(), set()
    for x in plan['slots'] + plan['goals']:
        if x.get('doneOn') not in (None, 'find', 'equip'):
            problems.append(tr('«%s»: doneOn бывает только find или equip') % x['id'])
    for s in plan['steps']:
        if s['id'] in step_ids:
            problems.append(tr('Шаг «%s» записан дважды') % s['id'])
        step_ids.add(s['id'])
        # фильтры плана — фильтры игры (программа берёт их из папки фильтров игры); inGame: False — фильтра в игре
        # нет: на этой машине на него ещё не подписаны или его удалили из аккаунта. Папки фильтров игры не видно —
        # не известно и это
        frec = (plan['filters'].get(s['filter']) or {}) if s.get('filter') else {}
        if s.get('filter') and s['filter'] != NO_FILTER and frec.get('inGame') is False:
            problems.append(tr('Шаг «%s»: фильтра «%s» нет в игре') % (s.get('name') or s['id'], frec.get('name') or s['filter']))
        if s.get('kit') is not None:
            problems.append(tr('Шаг «%s»: поле kit больше не читается — срок у каждой цели свой (use, until)') % s['id'])
        if s.get('event') not in (None,) + STEP_EVENTS:
            problems.append(tr('Шаг «%s»: событие бывает только %s') % (s['id'], ', '.join(STEP_EVENTS)))
        # Этап карт: у шага нет своей зоны (у карт нет постоянных кодов), он наступает с первой
        # боевой зоной не ниже такого уровня, которой в плане нет.
        if s.get('level') is not None and (not is_int(s['level']) or s.get('zone') or s.get('event')):
            problems.append(tr('Шаг «%s»: level — целое число, и у такого шага нет ни зоны, ни события') % s['id'])
        # Цель по времени на шаг: «5:30» или «1:05:00». Отрезок маршрута, на который цели шагов
        # складываются, — этап билда: от одной смены направления до другой («До вознесения», «До карт»).
        if s.get('target') is not None and parse_clock(s['target']) is None:
            problems.append(tr('Шаг «%s»: target — время вида 5:30 или 1:05:00') % s['id'])
        if s.get('stretch') is not None:
            problems.append(tr('Шаг «%s»: поле stretch больше не читается — отрезок задаёт этап билда (stages)') % s['id'])
    plan['stages'] = norm_stages(raw, plan, catalog, problems)
    for g in plan['goals']:
        if g['id'] in goal_ids:
            problems.append(tr('Цель «%s» записана дважды') % g['id'])
        goal_ids.add(g['id'])
        if g.get('slot') and g['slot'] not in slot_ids:
            problems.append(tr('Цель «%s»: нет слота «%s»') % (g['id'], g['slot']))
        # Шаги цели: need — срок, from — с какого шага её ищут; use — с какого шага её вещь носят: до него цель
        # только собирают в запас (у умения и его частей use — шаг умения, его считает skill_steps); until —
        # последний шаг, на котором она в ходу.
        for key in ('need', 'from', 'use', 'until'):
            if g.get(key) and g[key] not in step_ids:
                problems.append(tr('Цель «%s»: нет шага «%s»') % (g['id'], g[key]))
        # gear — что это за вещь: описание базы, как у слота («Sceptre», «Shield str_armour»)
        if g.get('gear') is not None and not (isinstance(g['gear'], str) and g['gear'].strip() and g.get('slot')):
            problems.append(tr('Цель «%s»: gear — описание базы предмета слота («Sceptre», «Shield str_armour»)') % g['id'])
        if g.get('kind') == 'boss' and not g.get('need'):
            # босс живёт на своей карте: без шага его негде показать
            problems.append(tr('Босс «%s»: не указан шаг (need)') % g['id'])
        if g.get('icon') is not None and not (isinstance(g['icon'], str) and RE_ICON_NAME.fullmatch(g['icon'])):
            problems.append(tr('Цель «%s»: icon — имя картинки вида item-…, type-… или art-…') % g['id'])
        # rarity — какой редкости предмет слота подбирают: по ней проверяется фильтр
        if g.get('rarity') is not None and not (g['rarity'] in ITEM_RARITIES and g.get('slot') and not g.get('part')):
            problems.append(tr('Цель «%s»: rarity — редкость предмета слота: Normal, Magic или Rare') % g['id'])
    node_owner = {}
    for g in plan['goals']:
        # grantedBy — вещь, которая даёт это умение: цель закроется сама, когда вещь наденут
        if g.get('grantedBy') and g['grantedBy'] not in goal_ids:
            problems.append(tr('Цель «%s»: нет цели «%s» (grantedBy)') % (g['id'], g['grantedBy']))
        # node — узел дерева героя или атласа, взять который и есть эта цель («Иммунитет к хаосу» —
        # при 6–7 тысячах энергощита). Узел берут не по очереди очков, а когда выполнено условие цели:
        # строка дерева показывает его отдельно, а цель закрывается сама, когда лог покажет узел взятым.
        if g.get('node') is not None:
            if not (isinstance(g['node'], str) and g['node'].strip()):
                problems.append(tr('Цель «%s»: node — id узла дерева, как в логе игры') % g['id'])
            elif g['node'] in node_owner:
                problems.append(tr('Цели «%s» и «%s» привязаны к одному узлу дерева') % (node_owner[g['node']], g['id']))
            else:
                node_owner[g['node']] = g['id']
    return plan, problems


# Перекачка дерева на смене этапа — цель шага, которую программа выводит сама (respec_plan): в плане её нет.
RESPEC = 'respec'
# Вид цели вне слотов (поле kind в плане) — как он подписан на странице.
KIND_NAMES = {'skill': tr('умение'), 'support': tr('камень поддержки'), 'gem': tr('уровень камня'), 'resource': tr('ресурс'),
              'boss': tr('босс'), 'quest': tr('задание'), 'mechanic': tr('механика'), 'cache': tr('тайник'),
              'camp': tr('лагерь'), 'ascension': tr('восхождение'), RESPEC: tr('дерево')}
# Цели, привязанные к своей карте: раньше шага их не взять, а пропущенные называют карту, куда
# вернуться. Босс, задание карты (реликвия), механика (Бездна, Ритуал — на карте шага или на картах
# этапа), тайник зоны («Опасный клад»), лагерь («Паромщик») и награда из лога (поле reward).
PLACE_KINDS = ('boss', 'quest', 'mechanic', 'cache', 'camp')
# На сколько уровней вещь может быть выше зоны, где упала: с обычного чудовища — уровень зоны,
# с волшебного +1, с редкого, уникального и босса +2.
DROP_ABOVE = 2
# Путевой камень уровня N открывает зону уровня 64 + N (данные игры, каталог: waystones.tiers — T1…T16 = 65…80). На
# картах игрок говорит уровнем путевого камня («T13»), а не уровнем зоны («77»): так программа и пишет.
MAP_ZONES = range(65, 81)


def zone_word(level):
    """Уровень зоны словами игрока: на картах — уровень путевого камня («T13»), в кампании — «зона 52»."""
    return 'T%d' % (level - 64) if level in MAP_ZONES else tr('зона %d') % level


def from_zone(level):
    """«С какой зоны» словами игрока: на картах — «с T13», в кампании — «с зоны 52»."""
    return tr('с T%d') % (level - 64) if level in MAP_ZONES else tr('с зоны %d') % level

MARK_TEXT_SLOT = {0: tr('отметка снята'), 1: tr('в рюкзаке'), 2: tr('надето')}
MARK_TEXT_PART = {0: tr('отметка снята'), 1: tr('есть'), 2: tr('есть')}
MARK_TEXT_OTHER = {0: tr('отметка снята'), 1: tr('найдено'), 2: tr('взято')}
MARK_TEXT_BOSS = {0: tr('отметка снята'), 1: tr('готово'), 2: tr('готово')}


def current_filter_and_level(run):
    """Какой фильтр загружен последним и уровень последней боевой зоны."""
    fid, level = None, 1
    for e in run.events:
        if e['type'] == 'filter' and e.get('ok', True):
            fid = e['id']
        elif e['type'] == 'zone' and not is_town(e['code']):
            level = e['level']
    return fid, level


def ground_level(steps, pos, cur, cur_field, zone_levels=None):
    """Уровень зоны, для которой проверяется фильтр: что он сделает с предметом на земле.

    В боевой зоне — её уровень. В городе — уровень последней боевой зоны: в неё и возвращаются. Но с шага без
    своей боевой зоны (шаг-город «Выход на карты», шаг по событию «После вознесения») возвращаться некуда: из
    города герой пойдёт на ближайший шаг впереди, у которого уровень есть, — проверка идёт не ниже его уровня.
    Иначе фильтр для карт (правила с AreaLevel >= 65), загруженный в убежище, «скрывал» бы цель по последней
    зоне кампании 64-го уровня, куда с ним уже не пойдут.
    Уровень шага-этапа называет план (level); уровень шага-зоны — данные игры (zone_levels: код -> уровень).
    В данных у зоны стоит младший уровень: у зон, чей уровень растёт с порядком прохождения, настоящий выше —
    поэтому «не ниже», а не «ровно».

    steps — шаги плана, pos — номер текущего шага (None — шага ещё нет), cur — последняя зона (и город тоже),
    cur_field — последняя боевая зона."""
    level = cur_field['level'] if cur_field else 1
    if pos is None or cur is None or not is_town(cur['code']):
        return level
    here = steps[pos]
    if is_int(here.get('level')) or (here.get('zone') and not is_town(here['zone'])):
        return level        # этап карт или шаг боевой зоны: из города возвращаются туда же
    for s in steps[pos + 1:]:
        if is_int(s.get('level')):
            return max(level, s['level'])
        if s.get('zone') and not is_town(s['zone']):
            return max(level, (zone_levels or {}).get(s['zone']) or 0)
    return level


def atlas_fold(own, league=None):
    """Атлас, каким его видит герой. Дерево атласа — общее у всех героев одной лиги учётной записи: новый
    герой той же лиги получает его открытым. Лог об этом молчит, он пишет только клики, поэтому взятое
    складывается из трёх частей:
      own — свои события «узел атласа взят / снят» (passive) — лог этого забега;
      league['clicks'] — такие же события героев той же лиги ({ts, op, id, name, run}); какие герои из той же
        лиги, говорит игрок — лига в лог не пишется;
      league['marks'] — узлы, которые игрок отметил взятыми до лога (лог начат позже, чем взяты узлы).
    Клики идут по времени: герои одной лиги могут играть и вперемешку. Отметки — раньше всех кликов.

    Проверка — правило игры: узел атласа берут только рядом со взятым или с корнем дерева. Клик не рядом со
    взятым значит, что в атласе есть взятое, которого программа не знает. league['near'] (соседи узла)
    и league['roots'] (корни) — данные атласа; без них проверки нет.

    Возвращает {'taken': {id: имя} в порядке взятия, 'src': {id: None — свой клик, id забега — клик того
    героя, 'hand' — отметка игрока}, 'gaps': [{id, name, run}] — клики не рядом со взятым, по времени}."""
    league = league or {}
    near, roots = league.get('near'), set(league.get('roots') or ())
    names = league.get('names') or {}
    taken, src, gaps = {}, {}, []
    for m in league.get('marks') or []:
        if isinstance(m, str) and m not in taken:
            taken[m] = names.get(m) or m
            src[m] = 'hand'
    seq = [(e['ts'], e, None) for e in own] + [(e['ts'], e, e.get('run')) for e in league.get('clicks') or []]
    seq.sort(key=lambda x: x[0])
    for _ts, e, rid in seq:
        nid = e['id']
        if e['op'] != 'take':
            taken.pop(nid, None)
            src.pop(nid, None)
            continue
        if nid in taken:
            # взятое кликом лога вместо отметки: отметка была лишней — узел берут только невзятым
            if src.get(nid) == 'hand':
                src[nid] = rid
            continue
        if near is not None and nid in near and not (near[nid] & roots) and not any(x in taken for x in near[nid]):
            gaps.append({'id': nid, 'name': e.get('name') or names.get(nid) or nid, 'run': rid})
        taken[nid] = e.get('name') or names.get(nid) or nid
        src[nid] = rid
    return {'taken': taken, 'src': src, 'gaps': gaps}


NO_FILTER = 'none'   # в плане: на этом шаге фильтр должен быть выключен
# Фильтр с сайта игры называется коротким кодом (у фильтров Path of Exile 2 — восемь букв и цифр); у такого есть
# своя страница на сайте: на ней игрок подписывается на фильтр (Follow), и игра сама его скачивает. Публичный
# фильтр эта страница показывает и без входа на сайт. Свой фильтр-файл игрока называется именем файла — страницы
# у него нет.
RE_SITE_FILTER = re.compile(r'[A-Za-z0-9]{8}')
FILTER_PAGE = 'https://pathofexile2.com/item-filter/%s'
TOUCH_SECONDS = 40   # заход короче этого считается активацией точки, а не переходом на шаг
TREE_QUEUE = 40      # сколько ближайших узлов дерева отдавать странице (при перекачке их берут подряд)


def waiting(plan, phase, have):
    """Какая версия дерева действует на деле. Версия этапа (phase) — если узлы, которые она берёт с предметов (items),
    на надетых предметах есть (have — id узлов с надетых предметов; None — не известно, тогда как есть); иначе — её
    запасная версия (without), по цепочке запасных. Возвращает (действующая версия, версия этапа, которая ждёт своих
    узлов с предметов, — или None)."""
    if not phase or have is None:
        return phase, None
    versions = {ph['id']: ph for ph in plan['tree']['phases'] if isinstance(ph, dict) and ph.get('id')}
    target, seen = None, set()
    while (phase.get('items') and phase.get('without') in versions and phase['id'] not in seen
           and not all(x.get('id') in have for x in phase['items'] if isinstance(x, dict))):
        seen.add(phase['id'])
        target = target or phase
        phase = versions[phase['without']]
    return phase, target


def respec_plan(plan, step_idx):
    """Перекачки дерева героя, которых требует план. Этап, с которого действует другая версия дерева, чем до него,
    начинается с перекачки, если в прежней версии есть узлы, которых в новой нет: лишнее снимают и берут узлы новой.
    Автор это не пишет — это следует из этапов. [{'stage': номер этапа, 'name': его название, 'step': номер шага, с
    которого он действует, 'allow': узлы, которые можно оставить, — новой версии и её запасных (without: пока узла
    с амулета нет, действует запасная), 'done': когда лог показал, что лишних узлов не осталось (None — ещё нет)}]."""
    stages = plan.get('stages') or []
    phases = {ph['id']: ph for ph in (plan.get('tree') or {}).get('phases') or [] if isinstance(ph, dict) and ph.get('id')}

    def allow(vid):
        out, seen = set(), set()
        while vid in phases and vid not in seen:
            seen.add(vid)
            out.update(n['id'] for n in phases[vid].get('nodes') or [] if isinstance(n, dict) and n.get('id'))
            vid = phases[vid].get('without')
        return out

    out, prev = [], None
    for n in range(len(stages)):
        vid = buildstage.effective(stages, n).get('tree')
        f = step_idx.get(stages[n].get('from')) if n else None
        if f is not None and vid != prev and vid in phases and prev in phases and allow(prev) - allow(vid):
            out.append({'stage': n, 'name': stages[n].get('name') or stages[n]['id'], 'step': f,
                        'allow': allow(vid), 'done': None})
        prev = vid or prev
    return out


def derive(plan, run, now, ground=None, selected=None, own_level=(), zone_names=None, zone_levels=None,
           atlas_league=None, given=None):
    """Собирает всё, что показывает страница, из плана, событий и отметок.

    ground — необязательный словарь «цель -> show/hide/unsure»: покажет ли текущий
    фильтр такую вещь на земле (считает сервер по файлу фильтра). Или функция от уровня зоны, которая такой
    словарь отдаёт: для какой зоны проверять, знает только сборка (ground_level) — ей известен шаг.
    zone_levels — уровни боевых зон по данным игры (gamedata.zone_levels): для шага-зоны впереди.
    selected — что выбрано в настройках игры: имя фильтра или 'None', если он выключен.
    Выключение фильтра в лог не попадает, поэтому настройка важнее лога.
    own_level — коды зон с собственным постоянным уровнем (gamedata.own_level): узлы механик и арены
    боссов. Этап карт они не открывают — его открывает только карта, чей уровень задал путевой камень.
    atlas_league — что было в атласе до героя и данные атласа для проверки (см. atlas_fold); без него атлас —
    только клики самого героя.
    """
    ground = ground if callable(ground) else (ground or {})
    steps, goals, slots, filters = plan['steps'], plan['goals'], plan['slots'], plan['filters']
    step_idx = {s['id']: i for i, s in enumerate(steps)}
    goal_by_id = {g['id']: g for g in goals}
    goal_order = {g['id']: i for i, g in enumerate(goals)}
    slot_name = {s['id']: s.get('name') or s['id'] for s in slots}
    slot_by_id = {s['id']: s for s in slots}
    # Акт каждого шага — по коду зоны. Шаг по событию своей зоны не имеет и стоит в акте предыдущего.
    # По акту шаги идут в полном маршруте, а цели на странице сворачиваются в списки:
    # «Награды · Акт 2 · 5 из 6».
    acts = []
    for s in steps:
        acts.append(act_of(s['zone']) if s.get('zone') else (acts[-1] if acts else act_of(None)))

    def found_is_done(g):
        """Запас на потом (скипетр до вознесения): цель закрыта находкой, надевать не нужно.

        Задаётся полем doneOn: "find" у слота или у самой цели (цель важнее слота).
        """
        own = g.get('doneOn')
        if own:
            return own == 'find'
        return (slot_by_id.get(g.get('slot')) or {}).get('doneOn') == 'find'

    def zones_of(i):
        """Зоны шага: основная и те, куда заглядывают, не уходя с шага."""
        return [steps[i].get('zone')] + list(steps[i].get('also') or [])

    # Точку перехода называет её зона — так, как зону писал лог этого забега (язык игрока). Пока лог её не
    # называл: название, оставшееся у точки в старом файле плана (страница его больше не пишет), потом — как зону
    # знают другие забеги и данные игры (zone_names; в данных игры названия зон только английские), потом код.
    heard_zones = {e['code']: e['name'] for e in run.events if e.get('type') == 'zone' and e.get('name')}

    def point_name(t):
        return heard_zones.get(t.get('zone')) or t.get('name') or (zone_names or {}).get(t.get('zone')) or t.get('zone')

    known_zones = set()
    for i in range(len(steps)):
        known_zones.update(zones_of(i))
    # Город шагом не бывает — кроме того, который план сам назвал шагом («Выход на карты» — убежище,
    # откуда ходят на карты). Боевой зоной он от этого не становится.
    step_towns = {s['zone'] for s in steps if s.get('zone') and is_town(s['zone'])}

    # --- проход по времени: где мы на маршруте -----------------------------
    # Шаги идут строго по порядку плана. Вход в зону ищет ближайший шаг впереди
    # с этой зоной, поэтому одна зона может встречаться в маршруте дважды.
    timeline = sorted(list(run.events) + [dict(m, type='move') for m in run.moves]
                      + [dict(h, type='hold') for h in run.hold], key=lambda e: e['ts'])
    pos = None           # номер текущего шага плана
    seen_steps = set()   # шаги, которые уже были текущими
    level_pos = {}       # уровень героя -> шаг, на котором он получен (-1: до первого шага)
    cur = cur_field = None
    hero_level, cls, first_cls = 1, None, None
    hero_name = None     # имя героя — из первой строки об уровне: события другого героя забег не переименуют
    asc_node = None      # последний взятый узел вознесения: по нему вознесение видно раньше нового уровня
    stranger = None      # уровень, который не продолжает этот забег: похоже, играет другой герой
    cur_filter = cur_hash = filter_since = None
    filter_failed = None   # фильтр, последняя загрузка которого не удалась (ошибка в самом фильтре)

    def touch_codes(i):
        """Зоны, куда на шаге i заглядывают только ради активации точки перехода."""
        return {t.get('zone') for t in (steps[i].get('touch') or []) if isinstance(t, dict)}

    # Шаги повторного захода: их зона уже была зоной или «ещё зоной» шага раньше по маршруту
    revisits, seen_zones = set(), set()
    for k, s in enumerate(steps):
        if s.get('zone') and s['zone'] in seen_zones:
            revisits.add(k)
        seen_zones.update(z for z in [s.get('zone')] + list(s.get('also') or []) if z)

    # Короткий заход шаг не меняет. Если зона значится на текущем шаге как точка для
    # активации или вход в неё перепрыгивает через шаги, шаг сменится, только когда
    # игрок пробыл в зоне дольше порога — в игре: время, когда героя в игре нет, в порог
    # не идёт (left_at ниже). Обычный переход на следующий шаг — сразу; но пока
    # в его зоне не пробыли порог, он предварительный (peek ниже): вернулись в зону шага,
    # с которого ушли, — заглянули, а не перешли, и шаг возвращается.
    dwell = plan.get('touchSeconds') or TOUCH_SECONDS
    zone_events = [e for e in timeline if e['type'] == 'zone']
    # Когда заход в зону кончился: вошли в следующую зону или вышли из игры (событие leave: экран персонажей,
    # игру закрыли, запуск после вылета) — что раньше. Пока героя в игре нет, он не в зоне: иначе отсчёт
    # порога шёл бы при закрытой игре и шаг менялся бы сам. Вернулся на ту же карту — заход новый (игра
    # пишет зону заново), и порог ему считается с начала.
    left_at, inside = {}, None
    for e in timeline:
        if e['type'] in ('zone', 'leave'):
            if inside is not None:
                left_at[id(inside)] = e['ts']
            inside = e if e['type'] == 'zone' else None
    pending = None       # заход, который ещё может стать сменой шага
    # Когда состояние изменится само, без новых строк лога: у идущего захода истечёт порог. Нужно и после
    # кнопки «сменить шаг»: ожидания уже нет, но по истечении порога шаг считается начатым со входа
    # на карту, а не с нажатия, — программа должна пересчитать время в этот момент.
    recheck = None
    tree_taken = {}      # дерево: взятые сейчас узлы (id -> имя), в порядке взятия; без узлов восхождения
    atlas_taken = {}     # дерево атласа: взятые сейчас узлы (id -> имя), в порядке взятия
    atlas_clicks = []    # его же клики героя по атласу — для атласа лиги (atlas_fold)
    atlas_open = False   # герой уже дошёл до карт: с этого времени у него есть атлас
    tree_points = 0      # дерево: очки из наград («+2 очка»); очки набора оружия не в счёт
    gain_at = None       # дерево: когда герой последний раз получил очки — новый уровень или награда «+N очков»
    rewards = []         # награды из лога: (коды свойств, шаг, на котором получена, последняя боевая зона)
    said = []            # реплики, которых ждал план: (коды строк, боевая зона, где их сказали)
    pos_log = []         # (время, шаг): когда какой шаг становился текущим
    ascended = None      # время восхождения, если оно уже было
    asc_count = 0        # сколько восхождений у героя по логу (испытание — два очка Восхождения: их считают взятые узлы)
    # Перекачка дерева на смене этапа (respec_plan): сделана, когда лог показал — взятых узлов вне новой версии не
    # осталось, хоть раз с шага начала этапа. Потом герой может отойти от плана, но перекачка была.
    respecs = respec_plan(plan, step_idx)
    tree_moves = 0       # сколько раз менялся набор взятых узлов дерева героя
    respec_seen = None   # (шаг, tree_moves), при которых перекачка уже проверена
    anchor = None        # боевая зона, где мы были, когда наступил шаг без своей зоны
    # Предварительный переход на следующий шаг: (шаг, с которого ушли; шаг, на который перешли; был ли он до
    # того хоть раз текущим; его запись в pos_log). Есть, пока в зонах нового шага ни разу не пробыли порог.
    peek = None

    def respec_check(ts):
        """Перекачка этапа, который действует на текущем шаге: лишних узлов не осталось — сделана (когда — ts)."""
        nonlocal respec_seen
        if not respecs or pos is None or (pos, tree_moves) == respec_seen:
            return
        respec_seen = (pos, tree_moves)
        r = next((r for r in reversed(respecs) if r['step'] <= pos), None)
        if r is not None and r['done'] is None and all(x in r['allow'] for x in tree_taken):
            r['done'] = ts

    last_ts = None
    for e in timeline:
        # состояние после прошлого события (у части веток ниже свой continue)
        respec_check(last_ts)
        last_ts = e['ts']
        t = e['type']
        fire = None      # событие, по которому наступает шаг без зоны («после восхождения»)
        if t == 'zone':
            cur = e
            pending = recheck = None
            atlas_open = atlas_open or is_endgame(e['code'])
            town = is_town(e['code'])
            if town:
                if e['code'] not in step_towns:
                    continue
            else:
                cur_field = e
            if peek is not None and e['code'] not in zones_of(pos) and e['code'] in zones_of(peek[0]):
                # Заглянули и вернулись: в зоне следующего шага пробыли меньше порога и пришли обратно в зону
                # шага, с которого ушли (город между ними не в счёт). Перехода не было — шаг прежний, будто
                # его и не меняли: время шага не рвётся, оставленный шаг снова не «позади».
                pos = peek[0]
                if not peek[2]:
                    seen_steps.discard(peek[1])
                if pos_log and pos_log[-1] == peek[3]:
                    pos_log.pop()
                peek = None
                continue
            if pos is not None and e['code'] in zones_of(pos):
                if peek is not None:
                    left = left_at.get(id(e))
                    if left is None or left - e['ts'] >= dwell:
                        peek = None      # в зоне нового шага задержались: переход состоялся
                continue
            start = 0 if pos is None else pos + 1
            # Шаг повторного захода (его зона уже была у шага раньше: третье испытание Сехем, Лакланн на Кладбище)
            # наступает только как следующий: заход в эту зону с дальнего шага — ради прежней цели (ещё одна попытка
            # испытания, путь через кладбище), а не прыжок вперёд мимо всех шагов между ними.
            j = next((k for k in range(start, len(steps))
                      if steps[k].get('zone') == e['code'] and (k == start or k not in revisits)), None)
            jumped_back = False
            if j is None and pos is not None:
                # Шаг, который проскочили, ни разу в него не зайдя (заглянули в соседнюю
                # зону раньше времени): возвращаемся к нему.
                j = next((k for k in range(pos - 1, -1, -1)
                          if k not in seen_steps and steps[k].get('zone') == e['code']), None)
                jumped_back = j is not None
            by_level = False
            if j is None and not town and e['code'] not in known_zones and e['code'] not in own_level:
                # Этап карт: зона, которой в плане нет, открывает самый дальний шаг впереди, чей уровень
                # она уже набрала («Карты 6–10» — с первой зоны 70-го уровня). Назад этапы не идут.
                # Зона с собственным уровнем не в счёт: заход в «Увядшую иву» (всегда 79) — не карта 15.
                ahead = [k for k in range(start, len(steps))
                         if is_int(steps[k].get('level')) and e['level'] >= steps[k]['level']]
                if ahead:
                    j, by_level = ahead[-1], True
            if j is None:
                continue
            if pos is not None and not jumped_back and (e['code'] in touch_codes(pos) or j > pos + 1):
                end = left_at.get(id(e))
                if end is not None:
                    stayed = end - e['ts']
                else:
                    # последний заход ещё идёт (герой в игре: после выхода заход уже кончен); без часов
                    # (now раньше события) считаем, что остались
                    stayed = now - e['ts'] if now >= e['ts'] else dwell
                if stayed < dwell:
                    if end is None:
                        # id — шаг, которым заход станет: страница сразу показывает его карточку и кнопку
                        # «сменить шаг сейчас» с отсчётом, не дожидаясь порога
                        pending = {'id': steps[j]['id'], 'name': e['name'], 'at': e['ts'] + dwell}
                        recheck = e['ts'] + dwell
                    continue
            was, seen_before = pos, j in seen_steps
            pos = j
            seen_steps.add(j)
            pos_log.append((e['ts'], j))
            # Шаг впереди наступил по входу в его зону, а в зоне пробыли меньше порога: это мог быть и заход
            # «заглянуть» — переход пока предварительный (вернутся в зону прежнего шага — его не было).
            left = left_at.get(id(e))
            peek = ((was, j, seen_before, pos_log[-1]) if was is not None and j > was and not by_level
                    and left is not None and left - e['ts'] < dwell else None)
            if town or by_level:
                anchor = cur_field   # как у шага по событию: на шаге, пока не ушли в другую боевую зону
        elif t == 'level':
            if stranger is None and run.started and e['level'] != hero_level + 1:
                # Уровни одного героя идут подряд. Скачок значит, что в забег попали события другого
                # героя: им снова стали играть, а странице про это не сказали (блок «Забеги»).
                stranger = {'level': e['level'], 'after': hero_level, 'ts': e['ts']}
            if e['level'] > hero_level:
                gain_at = e['ts']    # новый уровень — новое очко дерева
            hero_level, cls = e['level'], e['cls']
            first_cls = first_cls or cls
            hero_name = hero_name or e.get('name')
            level_pos[e['level']] = -1 if pos is None else pos
            if cls != first_cls:
                # Запасной признак восхождения: в строке об уровне сменился класс.
                fire = 'ascend'
                asc_count = max(asc_count, 1)
        elif t == 'ascend':
            fire = ascend_event(e.get('n', 1))
            asc_count = max(asc_count, e.get('n', 1))
        elif t == 'reward':
            rewards.append((set(e.get('keys') or ()), pos, cur_field['code'] if cur_field else None))
        elif t == 'passive':
            if e['id'].startswith(ATLAS_NODE):
                # Узел дерева атласа: игра пишет его той же строкой, что и узел героя. В дерево героя он
                # не входит — ни в счёт взятого, ни в свободные очки, ни в «лишнее после перекачки».
                atlas_clicks.append(e)
                if e['op'] == 'take':
                    atlas_taken.setdefault(e['id'], e.get('name') or e['id'])
                else:
                    atlas_taken.pop(e['id'], None)
            elif not e['id'].startswith(ASCENDANCY_NODE):
                if e['op'] == 'take':
                    # повторный клик по взятому узлу — назначение набору оружия: узел уже в дереве
                    tree_taken.setdefault(e['id'], e.get('name') or e['id'])
                else:
                    tree_taken.pop(e['id'], None)
                tree_moves += 1
            elif e['op'] == 'take':
                asc_node = e['id']
        elif t == 'points':
            if not e.get('weapon'):
                tree_points += e['n']
                gain_at = e['ts']
        elif t == 'say':
            said.append((set(e.get('ids') or ()), cur_field['code'] if cur_field else None))
        elif t == 'filter':
            filter_failed = None if e.get('ok', True) else e['id']
            if e.get('ok', True):
                # Версия фильтра считается новой, если сменился он сам или его содержимое (хеш).
                if e['id'] != cur_filter or (e.get('hash') and e.get('hash') != cur_hash):
                    filter_since = e['ts']
                cur_filter, cur_hash = e['id'], e.get('hash') or cur_hash
        elif t == 'move':
            if e.get('step') in step_idx:
                pos = step_idx[e['step']]
                seen_steps.add(pos)
                pos_log.append((e['ts'], pos))
                anchor = cur_field
                # шаг выбрали рукой (в том числе кнопкой «сменить шаг» во время захода) — ждать нечего
                pending = peek = None
        if fire and (fire != 'ascend' or ascended is None):
            if fire == 'ascend':
                ascended = e['ts']
            j = next((k for k in range(0 if pos is None else pos + 1, len(steps))
                      if steps[k].get('event') == fire), None)
            if j is not None:
                pos, pending, anchor, peek = j, None, cur_field, None
                seen_steps.add(j)
                pos_log.append((e['ts'], j))
    respec_check(last_ts)

    # --- дерево пассивных умений ---------------------------------------------
    # План дерева — версии: дерево целиком, каким оно должно быть на своём отрезке забега; у версии
    # полный порядок узлов от старта класса. Какая версия действует на шаге, говорит этап билда
    # (buildstage). Что взято, известно из лога. Очередь — узлы версии, которых ещё нет, по порядку;
    # лишние — взятые узлы, которых в версии нет (после смены версии их снимают). Свободные очки: уровень
    # героя минус один, плюс очки из наград, минус взятые узлы. Очки набора оружия сюда не входят, поэтому
    # узел, взятый за них, свободных очков не прибавляет и не отнимает ниже нуля.
    def node_name(n):
        """Название узла из плана. Данные игры пишут часть названий с разметкой ссылок («[Jewel] Socket»):
        на странице она не нужна."""
        return clean_markup(str(n.get('name') or '')) or n['id']

    # Узел, взять который — отдельная цель со своим условием (поле node у цели): в очередь «что брать»
    # он не идёт, сколько бы очков ни было свободно. Страница показывает его отдельно — названием цели,
    # пока лог не покажет узел взятым.
    node_goals = {}
    for g in goals:
        if isinstance(g.get('node'), str) and g['node'].strip():
            node_goals.setdefault(g['node'], g)

    def held_nodes(order, taken):
        return [{'id': n['id'], 'name': g.get('title') or node_name(n), 'kind': n.get('kind') or 'small',
                 'goal': g['id']}
                for n in order if n['id'] not in taken for g in [node_goals.get(n['id'])] if g]

    tree_view = None
    if plan['tree']['phases']:
        # версия, названная этапом текущего шага; ни один этап версии не назвал — плана дерева на шаге нет
        phase = buildstage.version(plan, 'tree', pos)
        # Версия берёт узлы с предметов (items), а на надетых предметах их нет: действует её запасная версия
        # (without) — до тех пор, пока предмет с узлом не надет. Что надето, знает сервер: given.on_items(шаг) —
        # id узлов с надетых предметов. target — версия этапа, которая ждёт своих узлов.
        phase, target = waiting(plan, phase, given.on_items(pos) if hasattr(given, 'on_items') else None)
        order = phase['nodes'] if phase else []
        wanted = {n['id'] for n in order}
        # Узлы с надетых предметов (зачарование амулета): given(id узлов версии, взятые, шаг) -> (что есть
        # с предметов, что брать очком не нужно — такой узел в конце ветки и путь только к нему). Считает
        # сервер: ему известны память надетого и карта дерева (anoint.py). Путь, ставший ненужным, из счёта
        # узлов этапа выходит; узел с предмета считается взятым.
        had, skip = given([n['id'] for n in order], set(tree_taken), pos) if given and order else (set(), set())
        gone = {i for i in skip if i not in had and i not in tree_taken}
        held = held_nodes(order, set(tree_taken) | set(had))
        queue = [n for n in order if n['id'] not in tree_taken and n['id'] not in node_goals and n['id'] not in skip]
        attr_default = plan['tree'].get('attr')

        def node_view(n):
            kind = n.get('kind') or 'small'
            return {'id': n['id'], 'name': node_name(n), 'kind': kind,
                    # какой атрибут выбрать в узле «Характеристика»: свой у узла или общий для дерева
                    'attr': n.get('attr') or (attr_default if kind == 'attribute' else None)}

        tree_view = {
            'phase': (phase.get('name') or phase['id']) if phase else None,
            'total': len(order) - len(gone), 'taken': len(order) - len(gone) - len(queue) - len(held),
            'free': max(0, max(0, hero_level - 1) + tree_points - len(tree_taken)),
            # когда герой последний раз получил очки (новый уровень, награда «+N очков»): от этого времени страница
            # полминуты показывает окно — сколько очков свободно и какие узлы плана взять за них. Возврат очка
            # за снятый узел — не получение: времени не меняет
            'gainAt': gain_at,
            # узлы этапа, которые ждут условия своей цели: их берут не по очереди
            'held': held,
            # сколько взятых узлов в этот этап не входит: после перекачки их снимают
            'extra': sum(1 for i in tree_taken if i not in wanted),
            'next': [node_view(n) for n in queue[:TREE_QUEUE]],
            'more': max(0, len(queue) - TREE_QUEUE),
            # для карты: весь порядок этапа и всё, что взято сейчас (в том числе лишнее)
            'plan': [node_view(n) for n in order],
            'have': list(tree_taken),
            # какая версия дерева действует сейчас (None — на этом шаге плана нет). Сами версии правят
            # на странице «Билд» — сюда они целиком не идут
            'now': phase['id'] if phase else None,
        }
        if skip:
            # узлы версии, которые брать очком не нужно из-за узлов с предметов: очередь страницы их пропускает
            tree_view['skip'] = sorted(skip)
        if phase and phase.get('items'):
            # узлы, которые версия берёт с предметов (зачарование амулета): их даёт предмет, а не очко
            tree_view['items'] = [{'id': x['id'], 'name': x.get('name') or x['id'], 'slot': x.get('slot')}
                                  for x in phase['items'] if isinstance(x, dict) and x.get('id')]
        if target:
            # версия этапа ждёт узлов с предметов — пока действует запасная (phase); надет предмет с узлом — дерево
            # переходит на неё само
            tree_view['target'] = {'id': target['id'], 'name': target.get('name') or target['id'],
                                   'items': [{'id': x['id'], 'name': x.get('name') or x['id'], 'slot': x.get('slot')}
                                             for x in target['items'] if isinstance(x, dict) and x.get('id')]}

    # --- дерево атласа -------------------------------------------------------
    # Записано в плане так же, как дерево героя: версии с порядком узлов. Отличия: деревьев в атласе
    # несколько, у каждого свои очки (сколько их свободно, игра в лог не пишет), и перекачки нет —
    # взятый узел вне плана ничего не требует. Очередь по деревьям страница собирает сама: какому
    # дереву принадлежит узел, знает файл геометрии атласа. Плана ещё нет — раздел всё равно отдаётся:
    # что герой взял в атласе, видно и без плана.
    # Атлас общий у героев одной лиги: взятое — его клики, клики героев той же лиги и отметки игрока
    # (atlas_fold). Взятое до героя тоже взято: его не зовут брать, и цель-узел (node) им закрыта.
    a_open = atlas_open or bool(atlas_taken)
    a_fold = atlas_fold(atlas_clicks, atlas_league)
    atlas_taken, a_src = a_fold['taken'], a_fold['src']
    a_phase = buildstage.version(plan, 'atlas', pos)
    a_order = a_phase['nodes'] if a_phase else []
    a_wanted = {n['id'] for n in a_order}
    # Опоздание. Сколько очков атласа получено, лог не пишет, поэтому темп задаёт этап: версия атласа этапа —
    # то, что должно быть взято к его концу. Узел из версии прошлых этапов (если та версия другая), который план
    # ждёт и сейчас, а он не взят, — опаздывает. Узел, который ждёт условия своей цели, — нет: срок у цели свой.
    a_due = set()
    stage_now = buildstage.number(plan, pos) if a_phase else None
    for m in range(stage_now or 0):
        vid = buildstage.effective(plan['stages'], m).get('atlas')
        if vid and vid != a_phase['id']:
            past = next((ph for ph in plan['atlas']['phases'] if ph.get('id') == vid), None)
            a_due.update(n['id'] for n in (past or {}).get('nodes') or [])
    a_late = [n['id'] for n in a_order if n['id'] in a_due and n['id'] not in atlas_taken and n['id'] not in node_goals]
    atlas_view = {
        'open': a_open,
        'phase': (a_phase.get('name') or a_phase['id']) if a_phase else None,
        'total': len(a_order), 'taken': sum(1 for n in a_order if n['id'] in atlas_taken),
        # из взятого по плану: сколько взял сам герой и сколько отметил игрок; остальное взято до героя
        'own': sum(1 for n in a_order if n['id'] in atlas_taken and a_src.get(n['id']) is None),
        'hand': sum(1 for n in a_order if a_src.get(n['id']) == 'hand'),
        'extra': sum(1 for i in atlas_taken if i not in a_wanted),
        # opt — какой вариант взять в узле с выбором (номер с единицы), если план его называет
        'plan': [dict({'id': n['id'], 'name': node_name(n), 'kind': n.get('kind') or 'small', 'attr': None},
                      **({'opt': n['opt']} if is_int(n.get('opt')) and n['opt'] > 0 else {}))
                 for n in a_order],
        'have': list(atlas_taken),
        # откуда взятое не этим героем: id узла -> id забега героя, который его взял, или 'hand' — отметка игрока
        'before': {i: s for i, s in a_src.items() if s is not None},
        # клики не рядом со взятым — в атласе есть взятое, которого программа не знает
        'gaps': a_fold['gaps'],
        # узлы, которые ждут условия своей цели, — как у дерева героя
        'held': held_nodes(a_order, atlas_taken),
        # узлы, которые опаздывают: были в версии атласа прошлых этапов и до сих пор не взяты (id, по порядку плана)
        'late': a_late,
        'now': a_phase['id'] if a_phase else None,
    }

    # --- время забега: идёт, только пока герой в игре и игра не на паузе -----
    # Отрезки, когда время стоит, — stopped_spans: вне игры и пауза игрока. Чистое время — от старта без них.
    # Простой с открытой игрой без паузы в него входит.
    away, out_since, held_since = stopped_spans(timeline)
    t0 = run.started or (timeline[0]['ts'] if timeline else now)
    # «сейчас» для расчётов: не раньше последней строки лога (в проверках часы могут стоять на нуле)
    t_end = max(now, timeline[-1]['ts']) if timeline else now

    def active(t):
        """Чистое время забега к моменту t, секунды."""
        t = max(t, t0)
        spans = away + [(s, t) for s in (out_since, held_since) if s is not None and s < t]
        return t - t0 - merged_length(spans, t0, t)

    # Шаги: на какой минуте чистого времени герой занялся шагом и сколько на нём провёл всего. Время идёт шагу,
    # которым герой занят (step_spans), — тот же счёт, что в «Разборе»: кнопка «Шаг пройден», нажатая до прихода
    # на новую карту, время не переносит. busy — шаг, которому время идёт сейчас: он может быть не шагом страницы.
    spans = step_spans(plan, run.events, run.hold, run.started, pos_log, t_end)
    step_at, step_took = {}, {}
    # Где шло время шага: town — в городе, off — в зонах вне маршрута, остальное — зоны шага (как в «Разборе»).
    # step_again — сколько попыток прервано на шаге (карту начинали заново, map_copies), step_lost — время шага в
    # брошенных копиях.
    step_town, step_off, step_again, step_lost = {}, {}, {}, {}
    place = None      # где герой сейчас: вид последнего куска
    for piece in spans['pieces']:
        if piece['kind'] != 'leave':
            i, place = piece['step'], piece['kind']
            step_took[i] = step_took.get(i, 0) + piece['dur']
            if place == 'zone':
                step_at.setdefault(i, active(piece['a']))
            elif place == 'town':
                step_town[i] = step_town.get(i, 0) + piece['dur']
            elif place == 'off':
                step_off[i] = step_off.get(i, 0) + piece['dur']
            if piece.get('drop'):
                step_lost[i] = step_lost.get(i, 0) + piece['dur']
            if piece.get('quit'):
                step_again[i] = step_again.get(i, 0) + 1
    busy = spans['busy']

    def away_of(i):
        """Сколько времени шага прошло не в его зонах: в городе и в зонах вне маршрута."""
        return step_town.get(i, 0) + step_off.get(i, 0)
    # идущий короткий заход дотянет до порога — время шагов разложится иначе: к этому моменту состояние пересчитают
    if spans['recheck'] is not None and (recheck is None or spans['recheck'] < recheck):
        recheck = spans['recheck']

    filter_off = False
    if selected is not None:
        if selected in ('None', ''):
            filter_off, cur_filter, filter_since = True, None, None
        elif selected != cur_filter:
            cur_filter, filter_since = selected, None

    on_step = (pos is not None and cur_field is not None
               and (cur_field['code'] in zones_of(pos) or cur_field['code'] in touch_codes(pos)))
    if pos is not None and (not steps[pos].get('zone') or steps[pos]['zone'] in step_towns):
        # Шаг по событию своей зоны не имеет, а шаг-город боевой зоной не бывает: мы на нём, пока
        # не ушли в другую боевую зону.
        on_step = cur_field is anchor
    # Ушли в зону, которой в плане нет вовсе: всё записанное осталось позади.
    beyond = (pos is not None and cur_field is not None and not on_step
              and cur_field['code'] not in known_zones)
    if pos is not None and is_int(steps[pos].get('level')):
        # Этап карт длится, пока не откроется следующий: любая карта — «на шаге», позади он не бывает.
        on_step = cur_field is not None and cur_field['code'] not in known_zones
        beyond = False

    # Фильтр проверяется для зоны, где герой сейчас; в городе на шаге без своей боевой зоны — для шага впереди
    # (ground_level). Саму проверку делает сервер: ground — готовый словарь или функция от уровня зоны.
    look = ground_level(steps, pos, cur, cur_field, zone_levels)
    if callable(ground):
        ground = ground(look) or {}

    def past(i):
        return pos is not None and (pos > i or (pos == i and beyond))

    def step_state(i):
        if pos is None or i > pos:
            return 'ahead'
        return 'behind' if past(i) else 'current'

    # --- цели по времени ------------------------------------------------------
    # У шага цель записана в плане (target). У акта и у отрезка маршрута цель — сумма целей их шагов.
    # Отрезок — этап билда: от одной смены направления до другой («До вознесения», «До карт»).
    targets = [parse_clock(s.get('target')) for s in steps]
    stage_of = buildstage.per_step(plan)      # номер этапа билда на каждом шаге (None — этапов нет)

    def group_time(member):
        """Время группы шагов: потрачено (чистое), цель, сколько план отводил на уже пройденные шаги.

        По этим числам страница сама считает отставание — в том числе между строками лога: пока
        текущий шаг укладывается в свою цель, отставание группы не растёт, дальше растёт с каждой секундой.
        """
        idx = [i for i in range(len(steps)) if member(i)]
        before = [i for i in idx if pos is not None and i < pos]
        return {'spent': int(sum(step_took.get(i, 0) for i in idx)),
                # из него — не в зонах шагов: в городе и вне маршрута
                'away': int(sum(away_of(i) for i in idx)),
                # время сейчас идёт шагу этой группы (страница досчитывает его сама между строками лога)
                'live': busy is None or member(busy),
                'target': sum(targets[i] or 0 for i in idx) or None,
                'passed': sum(targets[i] or 0 for i in before),
                'steps': len(idx), 'done': sum(1 for i in idx if past(i)),
                'state': 'ahead' if pos is None or idx[0] > pos else
                         'behind' if all(past(i) for i in idx) else 'current'}

    act_names = []
    for a in acts:
        if a not in act_names:
            act_names.append(a)
    time_view = None
    if pos is not None:
        cur_stage = stage_of[pos]
        time_view = {
            'warn': plan.get('timeWarn') or TIME_WARN,
            # live — время идёт шагу страницы; иначе оно стоит, а busy называет шаг, которому идёт (герой ещё
            # не дошёл до карты шага, на который страницу перевели кнопкой, или вернулся на прежнюю)
            'step': {'spent': int(step_took.get(pos, 0)), 'away': int(away_of(pos)), 'target': targets[pos],
                     'live': busy is None or busy == pos,
                     'busy': None if busy is None or busy == pos else steps[busy].get('name') or steps[busy]['id']},
            # герой сейчас не в зонах шага (в городе или вне маршрута): набегающие секунды идут и в away
            'out': place in ('town', 'off'),
            'act': dict(group_time(lambda i: acts[i] == acts[pos]), name=acts[pos]),
            'stretch': (dict(group_time(lambda i: stage_of[i] == cur_stage),
                             name=plan['stages'][cur_stage].get('name') or plan['stages'][cur_stage]['id'])
                        if cur_stage is not None else None),
        }

    def reached_pos(level):
        """Шаг, на котором герой получил этот уровень (или выше)."""
        cands = [(lv, p) for lv, p in level_pos.items() if lv >= level]
        return min(cands)[1] if cands else -1

    status = {}
    for m in run.marks:
        status[m['goal']] = m['status']
    # Статы вещей, которые игрок запомнил надетыми: место (слот/линия) -> {стат: число}. Их считает
    # программа по памяти надетого (herostats.gear); по ним отмечаются цели по стату.
    gear = getattr(run, 'gear', None) or {}

    # --- срок цели -----------------------------------------------------------
    # Вещи и камни меняют по одному, поэтому срок по шагам маршрута — у каждой цели свой:
    #   use   — шаг, с которого её вещь носят (камень вставлен). До него вещь слота — «позже», а камень только
    #           собирают в запас: нашёл — и достаточно. Нет поля — в ходу с начала забега;
    #   until — последний шаг, на котором она в ходу: дальше цель снята (самострел после вознесения).
    # Цели одного слота (или умения) с одним и тем же use — одна линия: то, что в слоте носят с этого шага.
    p_now = 0 if pos is None else pos
    # Умение (камень поддержки со своим шагом «Снять») игрок снял сам — кнопка «Снять» на шаге, где план его снимает:
    # цель -> когда. Лог игры этого не пишет. Снятое уходит со страницы сразу, а не в конце шага.
    off = {gid: ts for gid, ts in (getattr(run, 'off', None) or {}).items() if gid in goal_by_id}

    def line_of(g):
        """Линия цели: шаг, с которого её вещь в ходу (id шага), None — с начала забега."""
        return g['use'] if g.get('use') in step_idx else None

    def taken_off(g):
        """Снято игроком: сама цель или умение, при котором она живёт, — с шага «Снять» и дальше. (Отметку, поставленную
        на шаге, который страница приняла за текущий по ошибке, шаг раньше не трогает.)"""
        for x in (g, goal_by_id.get(g.get('for')) if not g.get('slot') else None):
            if x is not None and x['id'] in off and x.get('until') in step_idx and p_now >= step_idx[x['until']]:
                return True
        return False

    def use_phase(g):
        """future — вещь цели ещё не в ходу (собирают в запас), past — уже снята, now — в ходу."""
        if g.get('use') in step_idx and p_now < step_idx[g['use']]:
            return 'future'
        if g.get('until') in step_idx and p_now > step_idx[g['until']]:
            return 'past'
        return 'past' if off and taken_off(g) else 'now'

    # Что на шаге снимают: умения, чей шаг «Снять» — этот, и камни поддержки, у которых свой шаг «Снять» раньше, чем
    # у их умения (иначе их снимают вместе с умением). Камень умения стоит в своём гнезде, а не вместо другого:
    # новое умение старое не вытесняет, поэтому снятие — отдельное действие, и страница называет его на этом шаге.
    drops_at = {}
    for g in goals:
        u = step_idx.get(g.get('until'))
        if u is None or g.get('slot'):
            continue
        if g.get('kind') == 'skill':
            drops_at.setdefault(u, []).append(g)
        elif g.get('kind') == 'support' and g.get('for') in goal_by_id:
            su = step_idx.get(goal_by_id[g['for']].get('until'))
            if su is None or u < su:
                drops_at.setdefault(u, []).append(g)
    drop_step = {g['id']: u for u, gs in drops_at.items() for g in gs}

    def ending_of(g):
        """Шаг «Снять» цели, не привязанной к слоту: её собственный, а нет его — шаг «Снять» её умения (камень поддержки
        и уровень камня снимают вместе с умением). None — цель не снимают."""
        if g.get('slot'):
            return None
        u = step_idx.get(g.get('until'))
        if u is None and g.get('for') in goal_by_id:
            u = step_idx.get(goal_by_id[g['for']].get('until'))
        return u

    # линии по порядку шагов: с какого шага что-то входит в ход
    line_order = sorted({line_of(g) for g in goals} - {None}, key=step_idx.get)
    # шаги, после которых что-то снимают, — тоже по порядку
    until_order = sorted({g['until'] for g in goals if g.get('until') in step_idx}, key=step_idx.get)

    # Что надето на самом деле: в каждом слоте один предмет — тот, что игрок последним отметил «Надеть» (slotwear.settle;
    # запись прежнего вида, место слота по периоду, читается так же). Периоды слота говорят только, что план в нём
    # ждёт: надетое от них не зависит, рюкзака нет. worn_at — {слот: место записи в памяти}, worn_now — {слот: запись}.
    # Двуручное оружие закрывает вторую руку — правило игры: пока в основной руке запомнен надетым двуручный
    # предмет (метка twohand у его базы), во вторую надеть нечего. Её цели тогда не ищут и срок их не горит.
    # links — план: {цель позднего периода: цель, которую носят перед ним} — одна и та же вещь, названная дважды
    # (скипетр во второй руке, потом в оружии; slotwear).
    worn_mem = getattr(run, 'worn', None) or {}
    worn_at = slotwear.settle(plan, worn_mem, p_now)
    worn_now = {sid: worn_mem[spot] for sid, spot in worn_at.items()}
    links = slotwear.linked(plan)
    # цели одного и того же предмета, названного в нескольких периодах: {цель: все цели этого предмета}
    same = {}
    for a, b in links.items():
        grp = same.get(a, {a}) | same.get(b, {b})
        for x in grp:
            same[x] = grp
    shut = None          # слот второй руки, закрытый двуручным оружием
    pair = plan.get('hands') or {}
    if pair and pair['main'] in slot_by_id and pair['off'] in slot_by_id:
        def in_use(slot):
            # период слота, который в ходу сейчас
            live = [p for p in slotwear.periods(slot_by_id[slot], goals, step_idx)
                    if not p['from'] or step_idx[p['from']] <= p_now]
            return live[-1] if live else None
        other = in_use(pair['off'])
        item = (worn_now.get(pair['main']) or {}).get('item')
        if slotwear.shut(pair, item, other['classes'] if other else ()):
            shut = pair['off']

    def mark_of(g):
        """Отметка цели игроком. У вещи слота «в рюкзаке» (статус 1, оставшийся от прежних забегов) не в счёт: рюкзака
        нет — вещь либо надета, либо нет (кроме слота, где «нашёл» и есть цель: doneOn)."""
        st = status.get(g['id'], 0)
        return 0 if st == 1 and g.get('slot') and not found_is_done(g) else st

    def worn_fits(g):
        """Цель-предмет слота (база) закрыта тем, что надето: её период в ходу, и предмет, который игрок запомнил
        надетым в слоте, ей отвечает (названной — по базе, «любой» — любой; slotwear.fits)."""
        if not g.get('slot') or g.get('part') or g['slot'] == shut or use_phase(g) != 'now':
            return False
        item = (worn_now.get(g['slot']) or {}).get('item')
        return bool(item) and slotwear.fits(g, item)

    # --- носители и их части -------------------------------------------------
    # Носитель — слот предмета или умение. В слоте лежит база (самострел, скипетр) и живут
    # части — аффиксы; у умения части — камни поддержки и уровень камня. У части есть уровни
    # (тир аффикса, уровень камня): это лесенка целей с общим ключом part.
    # Лесенка — цели одного носителя, одной линии и одной части по порядку плана. Найденная
    # или надетая более поздняя ступень закрывает ранние, но только в своей лесенке: найденный
    # в запас скипетр не закрывает самострелы, суффикс не закрывает префикс.
    def chain_key(g):
        if g.get('slot'):
            return ('slot', g['slot'], line_of(g), g.get('part'))
        if g.get('for') in goal_by_id and g.get('part'):
            return ('skill', g['for'], line_of(g), g['part'])
        return None

    chains = {}
    for g in goals:
        ck = chain_key(g)
        if ck:
            chains.setdefault(ck, []).append(g)

    def part_label(g):
        """Как часть названа на странице: «префикс · дух», «уровень камня», «поддержка»."""
        if g.get('label'):
            return g['label']
        ck = chain_key(g)
        named = next((x['label'] for x in chains.get(ck, []) if x.get('label')), None) if ck else None
        return named or KIND_NAMES.get(g.get('kind'))

    def base_title(slot, line):
        """Что лежит в слоте на линии line (для подписей к его частям): надетое, иначе найденное, иначе
        первая цель."""
        base = [g for g in goals if g.get('slot') == slot and not g.get('part') and line_of(g) == line]
        pick = base[0] if base else None
        for want in (1, 2):
            got = [g for g in base if status.get(g['id'], 0) == want]
            pick = got[-1] if got else pick
        # у слота «надеть что угодно» названия вещи нет — называем сам слот
        if pick is None or pick.get('any'):
            return slot_name.get(slot, slot).lower()
        return pick.get('title')

    closed = set()
    for chain in chains.values():
        for i, g in enumerate(chain):
            for later in chain[i + 1:]:
                st = 2 if worn_fits(later) else mark_of(later)
                if st == 2 or (st == 1 and later.get('closeOn', 'find') != 'equip'):
                    closed.add(g['id'])
                    break

    # Самая высокая боевая зона забега: с неё считается, что вещь уже может выпасть (поле opens —
    # уровень предмета, с которого бывает база или тир аффикса). Вещь с редкого чудовища или босса
    # на два уровня выше зоны (в зоне 53 упало кольцо 55 уровня с T1 здоровья, который бывает с 54-го),
    # поэтому потолок — уровень зоны плюс DROP_ABOVE.
    top_zone = max([z['level'] for z in zone_events if not is_town(z['code'])] or [1])
    drop_level = top_zone + DROP_ABOVE

    # Каждая награда из лога закрывает одну цель-награду. Сначала ищем цель той карты, где награду
    # взяли (последняя боевая зона: книгу часто читают уже в городе) — так отмечается и босс,
    # к которому вернулись позже, и тот, кого убили раньше своего шага. Если такой нет — ту, чей шаг
    # ближе всего к месту получения и не позже него: две цели «+2 очка» на соседних шагах
    # не путаются, даже если награду забрали, уже перейдя на следующий шаг.
    reward_done = set()
    for got, at, code in rewards:
        cands = []
        for g in goals:
            # коды свойств, которые даёт награда (на любом языке клиента одни и те же); у награды с выбором
            # их несколько — свои у каждого варианта
            keys = reward_of(g)
            if not keys or g['id'] in reward_done or not got & set(keys):
                continue
            cands.append((step_idx.get(g.get('need'), -1), goal_order[g['id']], g['id']))
        here = [c for c in cands if c[0] >= 0 and code is not None and code in zones_of(c[0])]
        if here:
            reward_done.add(min(here)[2])
            continue
        behind = [c for c in cands if c[0] <= (-1 if at is None else at)]
        if behind:
            # самый поздний шаг, а среди целей одного шага — первая по плану
            reward_done.add(max(behind, key=lambda c: (c[0], -c[1]))[2])

    # Реплика из лога (поле heard у цели): прозвучала — значит, сделано. Так отмечается смерть босса,
    # после которой кто-то всегда говорит одно и то же («Сехема Асала: Дело сделано»). Засчитывается
    # только на своей карте. Если реплику в игре поменяют, обязательного босса закроет сам маршрут.
    heard_done = set()
    for g in goals:
        want = heard_of(g)      # реплик может быть несколько — хватит любой
        if not want:
            continue
        i = step_idx.get(g.get('need'))
        # Босс, задание карты и награда засчитываются только на своей карте. Цель без привязки к карте
        # (собрать три части оружия к такому-то шагу) — где бы реплика ни прозвучала.
        bound = g.get('kind') in PLACE_KINDS or bool(g.get('reward'))
        if any(ids & set(want) and (not bound or i is None or code in zones_of(i)) for ids, code in said):
            heard_done.add(g['id'])

    def is_given(g, depth=0):
        """Цель пришла вместе с другой (поле grantedBy): умение — с вещью, стартовый уровень камня — с умением."""
        src = goal_by_id.get(g.get('grantedBy'))
        if src is None or depth > 3:
            return False
        # (предмет, названный в двух периодах, — один: надет в любом из них — отмечен или запомнен надетым)
        group = same.get(src['id'], (src['id'],))
        st = 2 if any(worn_fits(goal_by_id[x]) for x in group) else max(mark_of(goal_by_id[x]) for x in group)
        # вещь должна быть надета; у умения «в рюкзаке» не бывает: в запасе оно отмечено как найденное
        return st == 2 or (st == 1 and src.get('kind') == 'skill') or is_given(src, depth + 1)

    views_memo = {}

    building = set()     # цели, вид которых сейчас строится: запись справочника ждёт другую (needs)

    def gview(g):
        """Вид цели для страницы. Считается один раз: план большой, а одну цель показывают в нескольких местах."""
        v = views_memo.get(g['id'])
        if v is None:
            building.add(g['id'])
            try:
                v = views_memo[g['id']] = build_view(g)
            finally:
                building.discard(g['id'])
        return v

    def have_goal(gid):
        """Цель плана уже есть: сделана, закрыта или лежит в рюкзаке. Цели в плане нет или её вид ещё
        строится (записи ждут друг друга по кругу) — не известно, и она считается невзятой."""
        other = goal_by_id.get(gid)
        if other is None or gid in building:
            return False
        return gview(other)['urgency'] in ('done', 'closed', 'found')

    def spirit_now(g):
        """Резерв духа умения, которое ещё не взято, — на уровне камня, который герой может носить сейчас (по таблице
        gemLevels плана, не ниже стартового уровня камня): столько духа нужно, чтобы взять умение сейчас. Не
        умение или камень дух не резервирует — None."""
        costs = g.get('spirit') if g.get('kind') == 'skill' else None
        if not (isinstance(costs, list) and costs and all(is_int(c) for c in costs)):
            return None
        level = max([n for n, need in enumerate(plan.get('gemLevels') or (), 1) if is_int(need) and need <= hero_level] or [1])
        if is_int(g.get('gemFrom')):
            level = max(level, g['gemFrom'])
        return costs[min(level, len(costs)) - 1]

    def goal_fact(g, urg):
        """Строка под названием цели — то, что знает программа, а не автор плана: факты справочника игры (где
        это в зоне, падает ли случайно, где выдают награду, что взять раньше — пока не взято) и что не даёт
        закрыть цель, срок которой подошёл или прошёл (уровень героя, уровень зон, гнездо умения, резерв духа) —
        пока мешает. Гнездо по уровню героя — пока уровня нет; сферу и дух программа проверить не может: они
        названы, пока цель опаздывает. Нечего сказать — None."""
        parts = []
        if g.get('spot'):
            parts.append(tr('где: %s') % g['spot'])
        if g.get('random'):
            # с каких монстров падает (справочник: monsters) — бить их, а не всех подряд
            who = [m for m in g.get('monsters') or () if isinstance(m, str) and m.strip()]
            parts.append(tr('падает случайно — бить: %s') % i18n.join(', ', who) if who else tr('падает случайно — бить всех'))
        if g.get('handout'):
            town = point_name({'zone': g['handout']})
            parts.append((tr('награду выдают в городе: %s') if is_town(g['handout']) else tr('награду выдают: %s')) % town)
        missing = [n.get('title') or n.get('id') for n in g.get('needs') or ()
                   if isinstance(n, dict) and n.get('id') and not have_goal(n['id'])]
        if missing:
            parts.append(tr('сначала: %s') % i18n.join(', ', missing))
        if urg in ('due', 'overdue'):
            if is_int(g.get('hero')) and hero_level < g['hero']:
                parts.append(tr('с %d уровня') % g['hero'])
            elif is_int(g.get('opens')) and drop_level < g['opens']:
                parts.append(from_zone(max(1, g['opens'] - DROP_ABOVE)))
            sock = g.get('socket') if isinstance(g.get('socket'), dict) and is_int(g['socket'].get('n')) else None
            if sock and is_int(sock.get('hero')):
                if hero_level < sock['hero']:
                    parts.append(tr('%d-е гнездо — с %d уровня') % (sock['n'], sock['hero']))
            elif sock and sock.get('orb'):
                parts.append(tr('%d-е гнездо — %s') % (sock['n'], sock['orb']))
            cost = spirit_now(g)
            if cost:
                parts.append(tr('нужно %d духа') % cost)
        return i18n.join(' · ', parts) if parts else None

    def build_view(g):
        st = mark_of(g)
        need_i = step_idx.get(g.get('need'))
        hl = g.get('heroLevel')
        reach = g.get('reach')
        reward = g.get('reward')
        boss = g.get('kind') == 'boss'
        # Босс, задание карты и награда привязаны к своей карте: раньше шага их не взять, а после
        # него невзятое — «пропущено», и по шагу видно, на какую карту вернуться.
        place = bool(g.get('kind') in PLACE_KINDS or reward) and need_i is not None
        # Награду (очки, дух, сопротивление) показывает лог — такая цель отмечается сама.
        # Так же сама отмечается цель, чью реплику (heard) лог уже слышал, и цель-узел (node), когда
        # лог показал её узел дерева взятым.
        logged = ((bool(reward) and g['id'] in reward_done) or g['id'] in heard_done
                  or (g.get('node') is not None and (g['node'] in tree_taken or g['node'] in atlas_taken)))
        # Восхождение (справочник, поле ascend) и перекачка дерева (respec_plan) тоже отмечаются сами — по узлам в логе.
        asc = g['ascend'] if is_int(g.get('ascend')) else None
        respec = g.get(RESPEC)
        if reach:
            # Цель «достичь уровня героя» отмечается сама по логу.
            st = 2 if hero_level >= reach else 0
        elif asc:
            st = 2 if asc_count >= asc else 0
        elif respec is not None:
            st = 2 if respec['done'] is not None else 0
        elif logged:
            st = 2
        # Цель по стату отмечается сама — по вещи, которую игрок запомнил надетой в её слоте: стата
        # на вещи не меньше min — сделана, меньше — нет. Вещь в слоте не запомнена — как отмечено рукой.
        # Меряется только цель периода, который в ходу: цель будущего периода ждёт своего шага («позже»).
        on_item = None
        if g.get('stat') and g.get('slot') and isinstance(g.get('min'), (int, float)) and use_phase(g) == 'now':
            on_item = gear.get(worn_at.get(g['slot']) or '%s/' % g['slot'])
            if on_item is not None:
                st = 2 if on_item.get(g['stat'], 0) >= g['min'] else 0
        # Цель-предмет слота (база) закрывается тем, что надето (worn_fits) — сделано, и отмечать рукой нечего. Рюкзака
        # нет: отметка «в рюкзаке», оставшаяся от прежних забегов, ничего не значит (mark_of). heldIn — такая вещь надета
        # в другом слоте (скипетр ещё во второй руке, а план с этого шага ждёт его в оружии): откуда её переложить.
        held_in, by_worn = None, False
        if g.get('slot') and not g.get('part') and st != 2:
            if worn_fits(g):
                st, by_worn = 2, True
            elif use_phase(g) == 'now' and g['slot'] != shut and not g.get('any'):
                held_in = next((slot_name.get(sid, sid) for sid, e in worn_now.items()
                                if sid not in (g['slot'], shut) and slotwear.fits(g, e.get('item') or {})), None)
        # Обязательного босса пропустить нельзя: раз шаг позади, значит, он убит.
        walked = bool(boss and g.get('must') and need_i is not None and past(need_i) and st != 2)
        if walked:
            st = 2
        # Умение, которое даёт сама вещь (скелет-воин у Гремящего скипетра): надели вещь — умение
        # есть. Цель заводят, чтобы камни поддержки такого умения жили при нём, как у всех.
        # Так же стартовый уровень камня приходит вместе с умением: «нет уровня» не бывает.
        given = bool(st != 2 and is_given(g))
        if given:
            st = 2
        # Как цель должна отмечаться и как отметилась на деле — у босса это его свойства в списке боссов:
        # по реплике в логе, по строке награды, вместе с другой целью, при переходе на следующий шаг
        # (только обязательный босс) или рукой. Ждали реплику или награду, а закрылось иначе —
        # нестыковка: её видно в списке, и по ней правят план к следующему забегу.
        expect = ('phrase' if heard_of(g) else 'reward' if reward else 'goal' if g.get('grantedBy')
                  else 'pass' if boss and g.get('must') else 'hand')
        if g['id'] in heard_done:
            closed_by = 'phrase'
        elif reward and g['id'] in reward_done:
            closed_by = 'reward'
        elif status.get(g['id'], 0) == 2:
            closed_by = 'hand'
        elif walked:
            closed_by = 'pass'
        elif given:
            closed_by = 'goal'
        else:
            closed_by = None
        mismatch = None
        if closed_by and closed_by != expect:
            mismatch = {'phrase': tr('реплика не прозвучала'), 'reward': tr('награды в логе не было')}.get(expect)
        trigger = False
        since = None   # с какого момента цель начнут искать, если ещё рано
        late_from = None   # шаг, на котором был срок цели (для счёта, на сколько шагов она опаздывает)
        line = line_of(g)
        phase = use_phase(g)
        from_i = step_idx.get(g.get('from'))
        until_i = step_idx.get(g.get('until'))
        if phase == 'future' and (from_i is None or (g.get('slot') and from_i < step_idx[line])):
            # Камни, которые вставят позже, заранее не собирают: они появятся на своём шаге. Вещь будущего периода
            # слота — тоже «позже» до шага, с которого её носят: рюкзака нет, надетое раньше закроет её на этом шаге.
            from_i = step_idx[line]
        if (place or asc or respec is not None) and from_i is None:
            # раньше своего шага не ждут: восхождение — на испытании, перекачка — на смене этапа
            from_i = need_i
        if g.get('kind') == 'support' and not g.get('slot') and need_i is not None and (from_i is None or from_i < need_i):
            # Камень поддержки вставляют на его шаге: раньше план его не ждёт (игрок может и опередить — отметит раньше).
            from_i = need_i
        # То, что ещё не в ходу, собирают в запас: нашёл — и достаточно (камень умения на потом). У вещей слота запаса
        # нет: вещь либо надета, либо нет.
        find = (phase == 'future' and not g.get('slot')) or found_is_done(g)
        if st == 2 or (st == 1 and find):
            urg = 'done'
        elif g['id'] in closed:
            urg = 'closed'
        elif respec is not None and pos is not None and any(need_i < q['step'] <= p_now for q in respecs):
            # следующий этап уже начался со своей перекачкой: эта больше не нужна
            urg = 'expired'
        elif (phase == 'past' or (until_i is not None and p_now > until_i)
              or (boss and g.get('soft') and need_i is not None and past(need_i))
              or (p_now is not None and ending_of(g) == p_now and (need_i is None or need_i < p_now))):
            # Срок годности вышел: цель снята молча, красным она уже не горит.
            # Так же уходит необязательный босс без награды, когда его карта позади.
            # И умение, которого у героя нет, на его шаге «Снять»: снимать нечего, надевать незачем (если надеть его план
            # просил раньше; умение на один шаг — «Надеть» и «Снять» на одном — на нём ещё нужно).
            urg = 'expired'
        elif st == 1:
            # Найдено и лежит в рюкзаке: искать больше не надо, осталось надеть.
            urg = 'found'
        elif from_i is not None and p_now < from_i:
            # Умение и камень поддержки ждут с их собственного шага — его страница называет и так («позже · к концу «…»»);
            # иначе — с какого шага цель ищут (у босса и награды — шаг их карты).
            urg = 'early'
            since = (None if from_i == need_i and not place
                     else tr('с шага «%s»') % (steps[from_i].get('name') or steps[from_i]['id']))
        elif hl and hero_level < hl:
            urg, since = 'early', tr('с %d уровня') % hl
        elif hl:
            # Цель с условием по уровню: «пора» с момента, когда уровень получен.
            deadline = max(-1 if need_i is None else need_i, reached_pos(hl))
            urg = 'overdue' if deadline >= 0 and past(deadline) else 'due'
            trigger = urg == 'due'
            late_from = deadline
        else:
            ss = step_state(need_i) if need_i is not None else 'ahead'
            urg = {'ahead': 'seek', 'current': 'due', 'behind': 'overdue'}[ss]
            late_from = need_i
            if urg == 'seek' and g.get('opens') and drop_level < g['opens']:
                # Физически ещё не может выпасть: уровень зон не дорос.
                urg, since = 'early', from_zone(max(1, g['opens'] - DROP_ABOVE))
            elif urg == 'seek' and is_int(g.get('hero')) and hero_level < g['hero']:
                # Ещё не надеть: камень такого уровня требует уровень героя выше. Срока это не даёт
                # и не снимает — цель со сроком горит, даже когда уровня не хватает.
                urg, since = 'early', tr('с %d уровня') % g['hero']
        if shut is not None and g.get('slot') == shut and phase == 'now' and urg in ('seek', 'due', 'overdue'):
            # вторая рука закрыта двуручным оружием: цель не ищут, срок её не горит
            urg, since, trigger = 'early', tr('пока оружие двуручное'), False
        if urg == 'overdue' and g.get('soft'):
            urg = 'due'
        # На сколько шагов цель опаздывает: срок был на шаге late_from, а забег уже дальше. Два шага —
        # ещё не беда, сорок — уже повод искать именно эту вещь; по числу это видно на плитке слота.
        late = max(1, p_now - late_from) if urg == 'overdue' and late_from is not None and late_from >= 0 else 0
        fact = goal_fact(g, urg)
        if respec is not None and urg in ('due', 'overdue'):
            # сколько узлов снять, по логу: столько взятых узлов в новой версии нет
            cut = sum(1 for x in tree_taken if x not in respec['allow'])
            fact = tr('снять %d %s') % (cut, i18n.plural(cut, 'узел|узла|узлов'))
        # Что это за цель: слот предмета, умение, камень поддержки, уровень камня, награда…
        if g.get('slot'):
            kind = slot_name.get(g['slot'], g['slot']).lower()
        elif reach:
            kind = tr('уровень героя')
        elif reward and not boss:
            kind = tr('награда')
        else:
            kind = KIND_NAMES.get(g.get('kind'))
        title = g.get('title') or g['id']
        # Сколько есть сейчас — у цели, где нужное задано числом: по разнице видно, срочно ли (их замечание
        # 2026-11-25: нужный уровень камня был виден, а какой у камня сейчас, приходилось помнить). Уровень героя —
        # из лога; стат — с предмета, запомненного в слоте, в том же виде, что и нужное; уровень камня ставит
        # лесенка умения, ниже (ему нужны все её ступени). Строка: пустая — сейчас ничего нет (стата на предмете,
        # камня умения); None — цель не о числе или программа не знает (предмет слота не запомнен).
        now = None
        if reach:
            now = str(hero_level)
        elif on_item is not None:
            now = amount_like(title, on_item.get(g['stat'], 0))
        # Камень поддержки называет умение, в которое его ставят: «Залповый огонь → Взрывная граната».
        target = goal_by_id.get(g.get('for')) if g.get('for') else None
        target_title = (target.get('title') or target['id']) if target else None
        level = title
        # Ступень части называет свою часть: «дух скипетра: от 120», «уровень камня: 6 → умение».
        label = part_label(g) if g.get('part') else None
        full = '%s: %s' % (label, level) if label else title
        if target_title:
            full = '%s → %s' % (full, target_title)
        return {
            'id': g['id'], 'title': title, 'slot': g.get('slot'),
            'for': g.get('for') if target else None,
            'fullTitle': full,
            'part': g.get('part'), 'label': label, 'level': level,
            # цель живёт в строке своего носителя: слот, умение или часть умения
            'holder': bool(g.get('slot') or g.get('kind') == 'skill' or target),
            # что лежит в слоте, к которому относится часть (для подписей в предупреждениях)
            'holderName': base_title(g['slot'], line) if g.get('slot') and g.get('part') else None,
            'needIdx': need_i, 'order': goal_order.get(g['id'], -1),
            # акт шага, к которому цель нужна (None — цель без шага)
            'act': acts[need_i] if need_i is not None else None,
            'group': g.get('group'), 'status': st, 'urgency': urg, 'trigger': trigger, 'find': find,
            'late': late,
            # line — шаг, с которого вещь цели в ходу (None — с начала); untilStep — шаг, после которого снята
            'line': line, 'untilStep': g['until'] if until_i is not None else None,
            'phase': phase, 'since': since, 'kind': kind, 'opens': g.get('opens'),
            'key': bool(g.get('key')), 'any': bool(g.get('any')), 'soft': bool(g.get('soft')),
            # картинка вещи на плитке слота (имя файла без расширения); с ошибкой в имени — никакой
            'icon': g['icon'] if isinstance(g.get('icon'), str) and RE_ICON_NAME.fullmatch(g['icon']) else None,
            'note': g.get('note'), 'source': g.get('source'), 'heroLevel': hl,
            # auto — цель умеет отмечаться сама по логу; locked — отметку уже поставил лог или сам
            # маршрут, нажатием её не снять. Награду, которой в логе ещё нет, можно отметить и рукой.
            'auto': bool(reach or asc or respec is not None or reward or g.get('heard') or g.get('stat') or g.get('node')),
            'locked': bool(reach or asc or respec is not None or logged or walked or given or on_item is not None or by_worn),
            # цель по стату: какой стат и сколько его нужно на вещи слота
            'stat': g.get('stat'), 'min': g.get('min') if g.get('stat') else None,
            'boss': boss, 'must': bool(boss and g.get('must')), 'place': place,
            # свойства босса: финальный босс акта; как должен отмечаться, как отметился, нестыковка
            'final': bool(boss and g.get('final')),
            'expect': expect, 'closedBy': closed_by, 'mismatch': mismatch,
            'reach': reach, 'now': now, 'fact': fact, 'ground': ground.get(g['id']),
            # такой предмет сейчас надет в другом слоте (название слота): план ждёт его здесь — переложить
            'heldIn': held_in,
            'ways': list(g.get('ways') or []),
            'needName': steps[need_i].get('name') if need_i is not None else None,
        }

    live = ('seek', 'due', 'overdue')

    def ladder(chain):
        """Лесенка целей: что уже есть, что лежит в рюкзаке, что искать сейчас и что будет позже."""
        views = [gview(g) for g in chain]
        have = bag = None
        for v in views:
            if v['urgency'] == 'done':      # надето; в запасе — найдено
                have = v
            elif v['urgency'] == 'found':
                bag = v                     # найдено, но ещё не надето
        # Актуальная ступень — лучшая из тех, что уже бывают (окно открыто): с ней сравнивают то, что есть.
        # Разрыв — на сколько ступеней надетое отстаёт от актуального; по нему видно, где просадка.
        open_now = [i for i, v in enumerate(views) if v['urgency'] not in ('early', 'expired')]
        top_i = open_now[-1] if open_now else None
        have_i = max((i for i, v in enumerate(views) if v['urgency'] == 'done'), default=-1)
        # Искать сейчас — только то, что уже можно найти; остальное уходит в «позже».
        nxt_i = next((i for i, v in enumerate(views) if v['status'] == 0 and v['urgency'] in live), None)
        nxt = views[nxt_i] if nxt_i is not None else None
        if nxt is not None:
            # Срок ступени повыше — срок и для ступеней под ней: «6-й уровень камня к шагу 21» значит, что
            # с первым уже опаздывают, хотя у второго своего срока нет. Ближайшая ступень берёт срочность
            # самой запущенной из тех, до которых ещё не дошли; aim — чего план уже требует (самая высокая
            # из них со сроком). В списке опозданий по-прежнему стоит сама ступень со сроком.
            pressing = [v for v in views[nxt_i:] if v['status'] == 0 and v['urgency'] in ('due', 'overdue')]
            if pressing:
                worst = max(pressing, key=lambda v: (v['urgency'] == 'overdue', v['late']))
                nxt = dict(nxt, urgency=worst['urgency'], late=worst['late'], soft=worst['soft'],
                           needIdx=worst['needIdx'], needName=worst['needName'], act=worst['act'],
                           aim=pressing[-1]['level'])
        # План части — чего она потребует дальше и к какому шагу: по нему видно, что можно сделать
        # с опережением, если камень или вещь уже есть. Срок подошёл или прошёл — то, чего план уже
        # требует, со срочностью самой запущенной ступени; иначе ближайшая ступень со сроком впереди.
        plan_v = None
        if nxt is not None and nxt.get('aim'):
            top = pressing[-1]
            plan_v = dict(top, urgency=nxt['urgency'], late=nxt['late'], soft=nxt['soft'])
        else:
            plan_v = next((v for v in views[have_i + 1:] if v['status'] == 0 and v['needIdx'] is not None
                           and v['urgency'] in ('seek', 'early')), None)
        if plan_v is not None:
            # fullTitle, fact, note — для строки цели по стату в карточке слота: она называет ступень,
            # которую план требует сейчас, и что ей мешает
            plan_v = {k: plan_v[k] for k in ('id', 'title', 'level', 'urgency', 'late', 'soft', 'needName', 'act',
                                             'fullTitle', 'fact', 'note')}
        return {
            'have': have, 'bag': bag,
            'top': views[top_i] if top_i is not None else None,
            'gap': max(top_i - have_i, 0) if top_i is not None else 0,
            # То же долей своей лесенки: надета ступень haveN из topN, которые уже бывают («0 из 2»,
            # «4 из 7»). Так сравнимы короткая лесенка и длинная: −2 из двух — пусто, −2 из семи — терпимо.
            'haveN': have_i + 1, 'topN': top_i + 1 if top_i is not None else 0,
            'next': nxt, 'plan': plan_v,
            'later': next((v for v in views if v['urgency'] == 'early'), None),
            'alive': any(v['urgency'] != 'expired' for v in views),
            'chain': [g['id'] for g in chain],
        }

    def rungs_of(chain):
        """Ступени лесенки для списка на странице: уровень камня выбирают из него.

        open — ступень уже бывает в игре: камень такого уровня герой уже может носить (уровень героя по таблице
        gemLevels), как бы далеко ни был шаг, на котором её ждёт план. Умение берут и раньше плана, и камень у него
        бывает выше стартового — игрок отмечает тот уровень, какой у него есть (их заметка 2026-11-24). Список идёт
        до последней такой ступени. start — ступень приходит вместе с другой целью (стартовый уровень камня — с
        умением) и своей отметки не требует.
        """
        out = []
        for g in chain:
            v = gview(g)
            wearable = not (is_int(g.get('hero')) and hero_level < g['hero'])
            out.append({'id': g['id'], 'title': v['title'],
                        'open': v['urgency'] != 'expired' and wearable, 'start': bool(g.get('grantedBy'))})
        return out

    def tile_view(s, chain, line=None, stash=False):
        """Плитка слота — лесенка его баз (без частей)."""
        lad = ladder(chain)
        return {
            'id': s['id'], 'name': slot_name[s['id']], 'line': line, 'stash': stash,
            'worn': lad['have'], 'bag': lad['bag'], 'next': lad['next'], 'later': lad['later'],
            'hasGoals': lad['alive'], 'chain': lad['chain'],
        }

    def base_goals(slot, future=None):
        """Базы слота: то, что план ждёт в нём в периоде, который в ходу (что надето на деле — память надетого),
        либо линии future — то, что будут носить с её шага."""
        if future:
            return chains.get(('slot', slot, future, None), [])
        return [g for g in goals if g.get('slot') == slot and not g.get('part') and use_phase(g) == 'now']

    def slot_line(slot):
        """Линия слота, которая в ходу сейчас: последняя из начавшихся (None — та, что с начала забега)."""
        started = [ln for ln in line_order if step_idx[ln] <= p_now
                   and any(g.get('slot') == slot and line_of(g) == ln for g in goals)]
        return started[-1] if started else None

    severity = {'overdue': 3, 'due': 2, 'seek': 1}

    def holder_row(rid, kind, base, parts, **extra):
        """Строка носителя: его база и части, каждая — лесенка. state — самое срочное из того, что ищут.
        У умения части — уровень камня и камни поддержки; у слота — цели по стату (вещь со статом
        не меньше заданного к такому-то шагу). Что на вещи слота надето и чего оно стоит, считается
        не здесь, а по памяти надетого (herostats.py)."""
        ladders = ([base] if base else []) + parts
        wanted = [lad['next'] for lad in ladders if lad['next']]
        if wanted:
            state = max((v['urgency'] for v in wanted), key=severity.get)
            if state == 'due' and all(v['soft'] for v in wanted if v['urgency'] == 'due'):
                state = 'seek'   # «надеть что угодно» — мягкая цель, жёлтым не горит
        elif any(lad['bag'] for lad in ladders):
            state = 'found'
        elif any(lad['have'] for lad in ladders):
            state = 'done'
        else:
            state = 'early' if any(lad['later'] for lad in ladders) else 'idle'
        # На сколько шагов опаздывает самая запущенная из целей носителя, которые ищут сейчас.
        late = max([v['late'] for v in wanted if v['urgency'] == 'overdue'] or [0])
        # План носителя — его действия на маршруте по порядку шагов: когда взять, когда поднять уровень,
        # когда какой камень вставить или сменить (у слота — когда какая база и какой тир). В него идут
        # цели со сроком; where говорит, чего действие касается: само умение, уровень камня, гнездо N.
        timeline, socket = [], 0
        for li, lad in enumerate(ladders):
            is_base = base is not None and lad is base
            if is_base:
                where = kind
            elif extra.get('slot') or lad.get('key') == 'level':
                where = lad.get('label') or kind
            else:
                socket += 1
                where = tr('гнездо %d') % socket
            for gid in lad['chain']:
                v = gview(goal_by_id[gid])
                if v['needIdx'] is not None:
                    timeline.append(dict({k: v[k] for k in ('id', 'title', 'needIdx', 'needName', 'act',
                                                            'urgency', 'late', 'soft', 'place')},
                                         # lane — дорожка в таблице плана: части носителя по порядку, база первой
                                         where=where, lane=li, isBase=is_base))
                u = drop_step.get(gid)
                if u is not None:
                    # шаг «Снять» — своей ячейкой в той же дорожке: на нём камень снимают (drop)
                    urg = ('done' if taken_off(goal_by_id[gid]) else 'due' if u == p_now
                           else 'seek' if u > p_now else 'expired')
                    timeline.append({'id': gid, 'title': v['title'], 'needIdx': u,
                                     'needName': steps[u].get('name') or steps[u]['id'], 'act': acts[u],
                                     'urgency': urg, 'late': 0, 'soft': False, 'place': False,
                                     'where': where, 'lane': li, 'isBase': is_base, 'drop': True})
        timeline.sort(key=lambda t: (t['needIdx'], goal_order[t['id']]))
        row = {'id': rid, 'kind': kind, 'base': base, 'parts': parts, 'state': state,
               'late': late, 'timeline': timeline,
               'chain': [i for lad in ladders for i in lad['chain']],
               # слот, где цель одна — «надеть что угодно»: на странице он занимает одну плашку
               'simple': bool(base) and not parts and all(goal_by_id[i].get('any') for i in base['chain'])}
        row.update(extra)
        return row

    def slot_row(s, future=None):
        base = base_goals(s['id'], future)
        parts = []
        for ck, chain in chains.items():
            if ck[0] != 'slot' or ck[1] != s['id'] or ck[3] is None:
                continue
            # Часть слота — цель по стату («на скипетре уровень умений приспешников от +1 к вознесению»).
            # Она живёт на своей вещи: в строке слота — только части того, что в ходу сейчас. Цель снятой
            # вещи уходит вместе с ней в «Снято»: «урон стихий» самострела не должен оставаться в оружии,
            # когда носят скипетр.
            if (ck[2] == future) if future else all(use_phase(g) == 'now' for g in chain):
                lad = ladder(chain)
                if lad['alive']:
                    parts.append(dict(lad, key=ck[3], label=part_label(chain[0]), stat=chain[0].get('stat')))
        base_lad = ladder(base) if base else None
        if base_lad and not base_lad['alive']:
            base_lad = None
        # Строка у слота есть всегда — и когда в периоде, который в ходу, план от него ничего не ждёт (вторая рука до
        # своего периода): надеть в него можно всегда, надетое в нём видно, и с ним сравнивают скопированное.
        # line — линия строки: у запаса — та, что наденут; у обычной строки — та, что в слоте в ходу сейчас
        return holder_row('slot:%s:%s' % (s['id'], future or ''), slot_name[s['id']].lower(), base_lad, parts,
                          slot=s['id'], line=future or slot_line(s['id']), stash=bool(future))

    def skill_row(g, stash=False):
        kids = [c for c in goals if c.get('for') == g['id'] and c is not g]
        # что из умения снимают на этом шаге — оно в ходу до конца шага, кнопка «Снять» убирает его сразу
        drop_now = set() if stash else {x['id'] for x in drops_at.get(p_now, []) if gview(x)['status'] == 2 or taken_off(x)}
        parts, seen = [], set()
        for c in kids:
            ck = chain_key(c)
            chain = chains[ck] if ck else [c]          # камень поддержки без лесенки — сам себе часть
            if id(chain[0]) in seen:
                continue
            seen.add(id(chain[0]))
            lad = ladder(chain)
            # камень поддержки со своим шагом «Снять», уже снятый, гнездо не занимает
            if lad['alive'] and any(use_phase(x) != 'past' for x in chain):
                if c.get('part') == 'level':
                    # Уровень камня на странице выбирают из списка, поэтому лесенка отдаёт свои ступени.
                    lad['rungs'] = rungs_of(chain)
                parts.append(dict(lad, key=c.get('part') or c['id'], label=part_label(c),
                                  # у поддержки лесенки нет: её название и есть содержимое части
                                  single=not c.get('part'),
                                  # камень, который снимают на этом шаге, — он стоит (вставлен)
                                  drop=next((x['id'] for x in chain if x['id'] in drop_now
                                             and gview(x)['status'] == 2), None)))
        # drop — умение снимают на этом шаге (и оно ещё не снято: снятое здесь не показывается)
        return holder_row('skill:%s' % g['id'], KIND_NAMES['skill'], ladder([g]), parts,
                          slot=None, line=line_of(g) if stash else None, stash=stash, drop=g['id'] in drop_now)

    def is_skill(g):
        return not g.get('slot') and g.get('kind') == 'skill'

    # «Сейчас» у ступеней уровня камня — уровень камня, который у героя на деле: самая высокая сделанная ступень
    # лесенки умения (камня ещё нет — пусто). Ставится до того, как лесенки начнут раздавать копии ступеней.
    for ck, chain in chains.items():
        if ck[0] == 'skill' and ck[3] == 'level':
            rungs = [gview(g) for g in chain]
            got = [v['title'] for v in rungs if v['urgency'] == 'done']
            for v in rungs:
                v['now'] = str(got[-1]) if got else ''

    # Плитки слотов показывают то, что план ждёт в них сейчас. Рюкзака (запаса вещей на смену) нет: вещь будущего
    # периода — цель «позже» на своём шаге. Запас — только умения, которые придут позже (после вознесения), по шагам.
    slot_views = [tile_view(s, base_goals(s['id'])) for s in slots]
    holders = [r for r in (slot_row(s) for s in slots) if r]
    stash_views = []
    for ln in line_order:
        if step_idx[ln] <= p_now:
            continue
        rows = [skill_row(g, True) for g in goals if is_skill(g) and line_of(g) == ln]
        if rows:
            first = steps[step_idx[ln]]
            stash_views.append({'line': ln, 'from': first.get('name') or first['id'], 'rows': rows})

    # Цели вне слотов (навыки, уровни, очки, ресурсы) идут по ходу забега: по шагу, к которому
    # нужны. Камень поддержки с полем for стоит не отдельно, а при своём умении.
    def by_route(v):
        return (v['needIdx'] if v['needIdx'] is not None else len(steps), v['order'])

    # Снятые цели (их срок вышел) из текущего состояния уходят.
    # Босс без группы — часть маршрута (обязательный или необязательный без награды): он виден
    # в карточке своего шага, а в состоянии забега остаются только боссы с наградой.
    plain = [v for v in (gview(g) for g in goals
                         if not g.get('slot') and not (g.get('kind') == 'boss' and not g.get('group')))
             if v['phase'] != 'past' and v['urgency'] != 'expired']
    plain_by_id = {v['id']: v for v in plain}
    for v in plain:
        v['children'] = []
    # Порядок групп («Навыки», «Уровень», «Награды», «Ресурсы») — как они записаны в плане (groupOrder);
    # не названная там группа встаёт следом, по первой своей цели. Раньше порядок следовал только из
    # порядка целей в файле; у плана, собранного из маршрута и билда, такого общего порядка нет.
    groups, tops = [{'name': name, 'goals': []} for name in plan.get('groupOrder') or []], []
    for v in plain:
        parent = plain_by_id.get(v['for']) if v['for'] else None
        if parent is not None and parent is not v and parent['group'] == v['group']:
            parent['children'].append(v)
            continue
        tops.append(v)
        name = v['group'] or tr('Прочее')
        if not any(x['name'] == name for x in groups):
            groups.append({'name': name, 'goals': []})
    for v in plain:
        v['children'].sort(key=by_route)
    for v in sorted(tops, key=by_route):
        next(x for x in groups if x['name'] == (v['group'] or tr('Прочее')))['goals'].append(v)
    groups = [grp for grp in groups if grp['goals']]

    # Умения — тоже носители: камень умения и его части (поддержки, уровень камня). Идут в порядке
    # плана, а не по шагу, к которому нужны: встроенное умение (Келари, Ружан) стоит наверху, даже
    # если его берут позже камней, и строки не прыгают, когда умение появляется.
    for g in goals:
        if is_skill(g) and use_phase(g) == 'now' and gview(g)['urgency'] != 'expired':
            holders.append(skill_row(g))
    # Контрольные точки шагов (уровень героя, награды, ресурсы) — всё, что не живёт в носителях.
    checks = [dict(grp, goals=[v for v in grp['goals'] if not v['holder']]) for grp in groups]
    checks = [grp for grp in checks if grp['goals']]

    def fname(fid):
        """Название фильтра: «без фильтра» — словом программы; название фильтра — как его назвал автор на сайте
        (переводить его не на что), нет названия — код."""
        if fid == NO_FILTER:
            return tr('без фильтра')
        return i18n.Raw((filters.get(fid) or {}).get('name') or fid)

    def missing(fid):
        """Фильтра нет в игре: на этой машине на него ещё не подписаны (или его удалили из аккаунта). Не видно папки
        фильтров игры — не известно и это."""
        return bool(fid) and fid != NO_FILTER and (filters.get(fid) or {}).get('inGame') is False

    def filter_ok(want):
        """Совпадает ли то, что сейчас в игре, с тем, что нужно по плану."""
        return filter_off if want == NO_FILTER else (not filter_off and cur_filter == want)

    def expected_at(i):
        """Фильтр, который по плану должен быть включён на шаге i: последний назначенный к этому шагу."""
        for k in range(i, -1, -1):
            if steps[k].get('filter'):
                return steps[k]['filter']
        return None

    entered = {z['code'] for z in timeline if z['type'] == 'zone'}

    def worn_names(slot_lines):
        """Названия вещей по списку (слот, линия): что в этом слоте на этой линии лежит."""
        return [base_title(sid, ln) for sid, ln in slot_lines]

    def starts_at(i):
        """Вещи слотов, чей период начинается с шага i (названия): что с этого шага носят по плану. Пусто — ничего."""
        ln = steps[i]['id']
        if i == 0 or ln not in line_order:
            return []
        return worn_names([(s['id'], ln) for s in slots if ('slot', s['id'], ln, None) in chains])

    # Боссы шага: цели вида boss, привязанные к нему полем need, по порядку плана.
    # Остальные цели шага — всё, чей срок (need) — этот шаг: что закрыть на шаге, говорит сама цель, отдельных
    # списков («проверок») у шага нет. Босс стоит особняком: он проверка билда и игрока, а не пункт сборов.
    # «Любая вещь в слоте» (any) сюда не идёт: это состояние инвентаря — пустой слот виден на его плитке.
    bosses_at, due_at = {}, {}
    for g in goals:
        if g.get('need') in step_idx and not g.get('any'):
            (bosses_at if g.get('kind') == 'boss' else due_at).setdefault(step_idx[g['need']], []).append(g)
    # Перекачка дерева — первая цель шага, с которого этап действует: её делают сразу, в городе.
    respec_goals = [{'id': '%s:%d' % (RESPEC, r['stage']), 'title': tr('Перекачать дерево'), 'kind': RESPEC,
                     'need': steps[r['step']]['id'], RESPEC: r} for r in respecs]
    for g in respec_goals:
        due_at.setdefault(step_idx[g['need']], []).insert(0, g)

    def drop_view(g):
        """Что снимают на шаге: умение или камень поддержки со своим шагом «Снять». have — оно в ходу (умение взято,
        камень вставлен): снимать есть что; done — игрок уже нажал «Снять» (камень поддержки — и когда сняли умение)."""
        v = gview(g)
        # skill — умение, иначе камень поддержки: строка «Дальше» считает их по отдельности
        return {'id': g['id'], 'title': v['fullTitle'], 'kind': v['kind'], 'skill': g.get('kind') == 'skill',
                'have': v['status'] == 2, 'done': taken_off(g)}

    def card(i):
        """Карточка шага: задачи, точки, боссы, цели шага, фильтр. Годится и для просмотра чужого шага."""
        s = steps[i]
        # Шаг с пометкой far — дальняя веха: между ним и предыдущим есть ещё не записанные зоны.
        after = steps[i + 1] if i + 1 < len(steps) else None
        want = expected_at(i)
        return {
            'id': s['id'], 'name': s.get('name') or s['id'], 'state': step_state(i),
            'act': acts[i],
            # чистое время забега, когда герой занялся шагом, и сколько на нём провёл (секунды); None — шагом
            # не занимался. busy — время сейчас идёт этому шагу
            'at': int(step_at[i]) if i in step_at else None,
            'took': int(step_took[i]) if i in step_took else None,
            'busy': i == busy,
            # из этого времени — в городе и в зонах вне маршрута (остальное — зоны шага); сколько попыток на шаге
            # прервано (карту начинали заново: вышли из игры и вернулись в новую копию) и сколько времени в них ушло
            'townTime': int(step_town.get(i, 0)), 'offTime': int(step_off.get(i, 0)),
            'again': step_again.get(i, 0), 'lost': int(step_lost.get(i, 0)),
            # этап билда, к которому относится шаг (номер; None — этапов нет): по нему плитка отрезка собирает свои шаги
            'stage': stage_of[i],
            'target': targets[i],
            # шаг наступает не по входу в зону, а по событию из лога
            'event': s.get('event'),
            # что на этом шаге снимают: умения и камни поддержки, чей шаг «Снять» — этот
            # на текущем и пройденных шагах — только то, что есть у героя (или уже снято): снимать не взятое нечего
            'drop': [d for d in (drop_view(g) for g in drops_at.get(i, []))
                     if d['have'] or d['done'] or p_now is None or i > p_now],
            # Точки перехода, которые на этом шаге нужно активировать: заход в зону виден в логе.
            'touch': [{'name': point_name(t), 'done': t.get('zone') in entered}
                      for t in (s.get('touch') or []) if isinstance(t, dict)],
            # Боссы этой карты: обязательные закрываются сами, когда шаг позади; необязательные
            # с наградой после шага горят как пропущенные; без награды — снимаются молча.
            'bosses': [gview(g) for g in bosses_at.get(i, [])],
            # какой фильтр нужен на этом шаге, загружен ли он, здесь ли его включают и есть ли он в игре вообще
            'filter': {'id': want, 'name': fname(want), 'none': want == NO_FILTER, 'loaded': filter_ok(want),
                       'switch': bool(s.get('filter')) and s['filter'] != expected_at(i - 1),
                       'missing': missing(want)} if want else None,
            'next': after.get('name') if after and not after.get('far') else None,
            # цели шага: всё, что нужно закрыть на нём (срок цели — этот шаг), кроме боссов
            'goals': [gview(g) for g in due_at.get(i, [])],
        }

    cards = [card(i) for i in range(len(steps))]
    # Текущий шаг — копия своей карточки. Что дальше, страница берёт из следующей карточки (кнопка «Дальше: …»).
    step_view = dict(cards[pos]) if pos is not None else None

    all_views = [gview(g) for g in goals]
    # Что цели маршрута дали герою помимо вещей (поле gives: награда прибавляет стат — «+10% к сопротивлению
    # холоду»): сумма по сделанным целям. Награду отмечает лог, поэтому считать нужно здесь, по итогу цели,
    # а не по отметкам игрока.
    gained = {}
    for g, gv in zip(goals, all_views):
        if isinstance(g.get('gives'), dict) and gv['status'] == 2:
            for sid, n in g['gives'].items():
                if isinstance(n, (int, float)) and not isinstance(n, bool):
                    gained[sid] = gained.get(sid, 0) + n
    # опаздывает и перекачка дерева, если шаг её этапа позади, а лишнее не снято
    overdue = [v for v in all_views + [gview(g) for g in respec_goals] if v['urgency'] == 'overdue']
    # Пропущено на пройденных картах (босс с наградой, задание карты, награда): к ним можно
    # вернуться, поэтому они идут отдельно от «опаздываю» и называют свою карту.
    missed = [v for v in overdue if v['place']]
    # Туда же — точки перехода пройденных карт, в зону которых так и не зашли: до карты без точки
    # потом идти пешком. Такая запись гаснет сама, как только лог покажет вход в зону точки.
    for i, s in enumerate(steps):
        if not past(i):
            continue
        for t in (s.get('touch') or []):
            if isinstance(t, dict) and t.get('zone') and t['zone'] not in entered:
                title = tr('Точка: %s') % point_name(t)
                missed.append({
                    'id': 'touch:%s:%s' % (s['id'], t['zone']), 'touch': True, 'title': title, 'fullTitle': title,
                    'kind': tr('точка'), 'urgency': 'overdue', 'status': 0, 'place': True, 'auto': True, 'locked': True,
                    'needIdx': i, 'order': -1, 'needName': s.get('name') or s['id'],
                    'slot': None, 'soft': False, 'boss': False, 'find': False, 'reach': None,
                    'holderName': None, 'fact': None, 'note': None, 'ground': None,
                })
    missed.sort(key=by_route)
    ready = [v for v in all_views if v['trigger']]

    def worth_review(v):
        """Для разбора забега: ступень части без срока, которую не отмечали, целью не была."""
        return not v['part'] or v['needIdx'] is not None or bool(status.get(v['id'], 0))

    # Снятое целиком, по шагу, после которого сняли: что взяли, а что так и нет — для разбора забега.
    # Сюда идёт только то, что было в ходу: вещи слотов, умения и их части; цель без носителя (ресурс
    # со сроком годности) снимается молча.
    def dropped(u):
        return [v for v in all_views if v['untilStep'] == u and v['holder']]

    retired = [{'id': u, 'name': steps[step_idx[u]].get('name') or u,
                'goals': sorted((v for v in dropped(u) if worth_review(v)), key=by_route)}
               for u in until_order if p_now > step_idx[u] and dropped(u)]
    # --- фильтр -------------------------------------------------------------
    expected = expected_at(pos) if pos is not None else None
    filter_view = {
        'id': cur_filter, 'name': fname(cur_filter) if cur_filter else None, 'since': filter_since,
        'off': filter_off,
        # уровень зоны, для которой фильтр проверен (ground_level): страница называет его рядом с ответами
        'level': look,
        'expected': expected, 'expectedName': fname(expected) if expected else None,
        # нужного фильтра нет в игре: игрок плана на него ещё не подписан — страница даёт ссылку на его страницу
        'expectedMissing': missing(expected),
        'expectedPage': bool(expected) and bool(RE_SITE_FILTER.fullmatch(expected)),
        'match': filter_ok(expected) if (expected and (cur_filter or filter_off)) else None,
        # последняя загрузка фильтра не удалась: в фильтре ошибка, игра его не прочитала
        'failed': fname(filter_failed) if filter_failed else None,
    }

    # --- журнал -------------------------------------------------------------
    history = []
    prev_cls, last_seed, last_filter, last_hash = None, {}, None, {}
    field_code = None     # последняя боевая зона: по ней реплика засчитывается боссу своей карты
    said_for = set()      # цели, уже названные в журнале по реплике: вторая реплика о том же не повторяется
    for e in timeline:
        t = e['type']
        if t == 'zone':
            if not is_town(e['code']):
                field_code = e['code']
            tail = tr('город') if is_town(e['code']) else zone_word(e['level'])
            seed = e.get('seed')
            if seed and not is_town(e['code']):
                if e['code'] in last_seed and last_seed[e['code']] != seed:
                    tail += tr(' · новая копия')
                last_seed[e['code']] = seed
            history.append({'ts': e['ts'], 'kind': 'zone', 'text': '%s · %s' % (e['name'], tail)})
        elif t == 'level':
            text = tr('Уровень героя %d') % e['level']
            if prev_cls and e['cls'] != prev_cls:
                text += tr(' · теперь %s') % e['cls']
            prev_cls = e['cls']
            history.append({'ts': e['ts'], 'kind': 'level', 'text': text})
        elif t == 'reward':
            history.append({'ts': e['ts'], 'kind': 'reward', 'text': tr('Награда: %s') % e['text']})
        elif t == 'death':
            history.append({'ts': e['ts'], 'kind': 'death', 'text': tr('Смерть персонажа')})
        elif t == 'ascend':
            n = e.get('n', 1)
            history.append({'ts': e['ts'], 'kind': 'reward',
                            'text': tr('Восхождение получено') if n == 1 else tr('Восхождение получено: %d-е') % n})
        elif t == 'say':
            # Одну реплику могут ждать несколько целей (Скрытный подбирает часть оружия: и сама часть,
            # и босс этой карты) — в журнал идёт каждая, кому она засчитана; босс — только своей карты.
            for who in goals:
                if not set(e.get('ids') or ()) & set(heard_of(who)) or who['id'] in said_for:
                    continue
                i = step_idx.get(who.get('need'))
                bound = who.get('kind') in PLACE_KINDS or bool(who.get('reward'))
                if bound and i is not None and field_code not in zones_of(i):
                    continue
                said_for.add(who['id'])
                history.append({'ts': e['ts'], 'kind': 'reward', 'text': '%s: %s' % (
                    tr('Босс убит') if who.get('kind') == 'boss' else tr('По логу'), who.get('title') or who['id'])})
        elif t == 'filter':
            if not e.get('ok', True):
                history.append({'ts': e['ts'], 'kind': 'death', 'text': tr('Фильтр не загрузился: %s') % fname(e['id'])})
            else:
                h = e.get('hash')
                changed = bool(h) and e['id'] in last_hash and last_hash[e['id']] != h
                if changed:
                    history.append({'ts': e['ts'], 'kind': 'filter',
                                    'text': tr('Фильтр обновлён, новая версия: %s') % fname(e['id'])})
                elif e['id'] != last_filter and not e.get('carried'):
                    history.append({'ts': e['ts'], 'kind': 'filter', 'text': tr('Фильтр: %s') % fname(e['id'])})
                last_filter = e['id']
                if h:
                    last_hash[e['id']] = h
        elif t == 'move':
            if e.get('step') in step_idx:
                history.append({'ts': e['ts'], 'kind': 'mark',
                                'text': tr('Шаг выбран вручную: %s') % steps[step_idx[e['step']]].get('name')})
    for m in run.marks:
        g = goal_by_id.get(m['goal'])
        if g and g.get('slot') and g.get('part'):
            # часть слота (цель по стату): её не надевают, она либо есть на вещи, либо нет
            text = '%s: %s: %s — %s' % (slot_name.get(g['slot'], g['slot']), part_label(g), gview(g)['level'],
                                       MARK_TEXT_PART[m['status']])
        elif g and g.get('slot') and g.get('any'):
            # слот, где вещь может быть какой угодно: названия у неё нет — «Сапоги — надето»
            text = '%s — %s' % (slot_name.get(g['slot'], g['slot']), MARK_TEXT_SLOT[m['status']])
        elif g and g.get('slot'):
            text = '%s: %s — %s' % (slot_name.get(g['slot'], g['slot']), g.get('title'), MARK_TEXT_SLOT[m['status']])
        elif g and g.get('kind') == 'boss':
            text = tr('Босс: %s — %s') % (g.get('title'), MARK_TEXT_BOSS[m['status']])
        elif g and g.get('kind') == 'mechanic':
            # механику не «берут»: её проходят — как босса
            text = tr('Механика: %s — %s') % (g.get('title'), MARK_TEXT_BOSS[m['status']])
        elif g and g.get('for') in goal_by_id:
            # часть умения называет и умение, и себя: «Скелет-снайпер: уровень камня: 6 — есть»
            owner = goal_by_id[g['for']].get('title')
            what = '%s: %s' % (part_label(g), g.get('title')) if g.get('part') else g.get('title')
            text = '%s: %s — %s' % (owner, what, MARK_TEXT_PART[m['status']] if g.get('part') else
                                    MARK_TEXT_OTHER[m['status']])
        else:
            text = '%s — %s' % (g.get('title') if g else m['goal'], MARK_TEXT_OTHER[m['status']])
        history.append({'ts': m['ts'], 'kind': 'mark', 'text': text})
    # Кнопка «Снять»: умение (камень поддержки со своим шагом «Снять») игрок снял сам — когда нажал.
    for gid, ts in off.items():
        g = goal_by_id[gid]
        owner = goal_by_id.get(g.get('for')) if g.get('kind') != 'skill' else None
        what = '%s: %s' % (owner.get('title'), g.get('title')) if owner else g.get('title')
        history.append({'ts': ts, 'kind': 'mark', 'text': tr('%s — снято') % what})
    # Смена вещей по шагам и то, что из снятого так и не взяли: пригодится при разборе забега.
    started, ended = set(), set()
    for ts, p in pos_log:
        for u in until_order:
            if p > step_idx[u] and u not in ended:
                ended.add(u)
                if not dropped(u):
                    continue
                gone = worn_names(sorted({(v['slot'], v['line']) for v in dropped(u) if v['slot']},
                                         key=lambda x: ([s['id'] for s in slots].index(x[0]), x[1] or '')))
                # умения названы своими именами; то, что игрок снял сам (кнопка «Снять»), уже стоит в журнале своей строкой
                gone += [v['fullTitle'] for v in dropped(u) if v['id'] in drop_step and v['status'] == 2
                         and v['id'] not in off]
                left = [v['fullTitle'] for v in dropped(u) if v['urgency'] == 'expired' and worth_review(v)]
                if not gone and not left:
                    continue
                history.append({'ts': ts, 'kind': 'filter', 'text': tr('Снято: %s%s') % (
                    ', '.join(gone) or tr('камни'), tr(' · не взято: ') + ', '.join(left) if left else '')})
        for ln in line_order:
            if step_idx[ln] <= p and ln not in started:
                started.add(ln)
                names = starts_at(step_idx[ln])
                if names:
                    history.append({'ts': ts, 'kind': 'filter', 'text': tr('С этого шага в ходу: %s') % ', '.join(names)})
    for r in respecs:
        if r['done'] is not None:
            history.append({'ts': r['done'], 'kind': 'mark', 'text': tr('Дерево перекачано: этап «%s»') % r['name']})
    history.sort(key=lambda x: x['ts'])

    return {
        'now': now,
        'planTitle': plan['title'],
        # active — чистое время забега к моменту now (без времени вне игры и на паузе); paused — время стоит (героя
        # в игре нет или пауза); held — пауза игрока
        'run': {'id': run.id, 'started': run.started, 'active': int(active(t_end)),
                'paused': out_since is not None or held_since is not None, 'held': held_since is not None},
        # время текущего шага, акта и отрезка против целей плана; по актам — для свёрнутого маршрута
        'time': time_view,
        'acts': [dict(group_time(lambda i, a=a: acts[i] == a), name=a) for a in act_names],
        # Герой — только то, что сказал лог. Имя и класс — из строк об уровне (до второго уровня лог героя
        # не называет). Лог зовёт героя одним словом: до вознесения это класс (cls), после — вознесение
        # (asc), и новое слово приходит лишь со следующим уровнем; до тех пор о вознесении говорит взятый
        # узел вознесения (ascNode) — чьё оно, программа узнаёт по данным дерева. Плана билда здесь нет.
        'hero': {'level': hero_level, 'name': hero_name, 'cls': first_cls,
                 'asc': cls if cls and first_cls and cls != first_cls else None, 'ascNode': asc_node,
                 'ascended': ascended is not None or bool(cls and first_cls and cls != first_cls)},
        'stranger': stranger,
        'zone': {'code': cur['code'], 'name': cur['name'], 'level': cur['level'],
                 'since': cur['ts'], 'town': is_town(cur['code'])} if cur else None,
        'fieldZone': cur_field['name'] if cur_field else None,
        # Запас по опыту: зона, чей уровень отличается от уровня героя не больше чем на 3 + уровень // 16,
        # даёт опыт без штрафа (в обе стороны). На картах по нему видно, до какого путевого камня выгодно
        # подниматься: уровень зоны карты — 64 + уровень камня. zone — последняя боевая зона.
        'xp': {'band': 3 + hero_level // 16, 'lo': max(1, hero_level - 3 - hero_level // 16),
               'hi': hero_level + 3 + hero_level // 16,
               'zone': cur_field['level'] if cur_field else None,
               'out': bool(cur_field) and abs(cur_field['level'] - hero_level) > 3 + hero_level // 16},
        'pos': pos,
        # когда какой шаг становился текущим на странице: [время, номер шага] по порядку — для разбора времени героя
        # (review.py): им выбирается шаг, когда зона значится у нескольких шагов, и узнаётся шаг без своей зоны
        'posLog': [[ts, p] for ts, p in pos_log],
        'pending': pending,
        # слот второй руки, закрытый двуручным оружием (id или None), и где в памяти надетого лежит предмет каждого
        # слота ({слот: место}; slotwear.settle) — по ним программа считает статы героя и сравнивает вещи
        'shut': shut,
        'wornAt': worn_at,
        # когда пересчитать состояние без новых строк лога (порог идущего захода), или None
        'recheckAt': recheck,
        # дерево пассивных умений: свободные очки и очередь узлов по плану (None — плана дерева нет)
        'tree': tree_view,
        # дерево атласа: что взято (из лога, по порядку) — плана для него пока нет
        'atlas': atlas_view,
        'onStep': on_step,
        'beyond': beyond,
        # акт текущего шага: его список целей на странице раскрыт, остальные свёрнуты
        'act': acts[p_now] if steps else None,
        'step': step_view,
        'cards': cards,
        'route': [{'id': s['id'], 'name': s.get('name') or s['id'], 'state': step_state(i),
                   'far': bool(s.get('far'))}
                  for i, s in enumerate(steps)],
        'slots': slot_views,
        # запас: умения, которые войдут в ход позже, — по шагам, с которых их возьмут
        'stash': stash_views,
        'retired': retired,
        # носители с частями (слоты и умения) и контрольные точки шагов
        'holders': holders,
        'checks': checks,
        'groups': groups,
        # что сделанные цели маршрута дали герою помимо вещей: стат -> сумма (см. herostats.rest)
        'gained': gained,
        # все боссы плана по порядку маршрута, со свойствами: список «Боссы» на странице
        'bosses': sorted((gview(g) for g in goals if g.get('kind') == 'boss'), key=by_route),
        'overdue': overdue,
        # пропущенное на пройденных картах: боссы с наградой и награды, к которым можно вернуться
        'missed': missed,
        'ready': ready,
        'filter': filter_view,
        'history': history[-14:][::-1],
    }
