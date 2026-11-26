# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Sergei Labutin
# Additional terms under GPL-3.0 section 7: see NOTICE.md
"""Правка маршрута в редакторе плана (вкладка «Маршрут»): шаги и их цели записываются в файл маршрута.

Маршрут — часть плана, как и дерево: у каждого плана он свой (файл routes/…), общим для разных планов он
не считается. Поэтому своего названия у маршрута нет: план называется в билде. В нём:

  шаги — порядок карт. У шага название, цель по времени (target: «5:30» или «1:05:00»),
         точки перехода, которые на нём активируют (touch: зона и её название), фильтр игры, который
         включают с этого шага (filter: код фильтра или «none» — выключить; filterName — его название, как
         его называет игра автора: по нему фильтр узнают игроки, у которых его ещё нет), и то, как шаг узнаётся:
         по зоне (zone — код зоны из лога игры; also — ещё зоны того же шага), по событию (event:
         восхождение) или по уровню зоны (level: этапы карт). Задач — строк текста — у шага нет: всё, что на шаге
         делают, — цели (боссы, задания, механики, восхождения из справочника, уровень героя, цели билда), их
         отмечают и они горят сроком; поле notes из файла, записанного раньше, не читается и уходит при записи;
  цели шага — то, что привязано к карте, а не к герою. Босс, задание, механика и награда — факты игры: в файле
         маршрута от них только ссылка на запись справочника (landmarks) — id и шаг (need). Механика (Бездна,
         Ритуал…) бывает на многих шагах: её ссылка — свой id и ref, id записи. Целиком в маршруте лежит лишь то, что решает автор, — уровень героя к шагу
         (reach). Поля фактов те же, что были у цели: боссы (kind boss; must — без убийства маршрут
         не продолжить, final — финальный босс акта), задания карт (kind quest), награды (reward —
         строка награды в логе) и уровень героя к шагу (reach). Босс в плане — цель: босса, мимо которого
         можно пройти без потери, в план не вносят (пометку soft «не напоминать» редактор не ставит).

Страница присылает оба списка целиком. Здесь они проверяются и вписываются в файл маршрута; остальной
текст файла не меняется (это проверяется перед записью), прежний файл сохраняется копией.
Ссылки билда на удалённый шаг (сроки целей, начало этапа) сами не чинятся — это отказ: сначала их переносят
на другой шаг.
"""
import json
import re

import buildplan
import core
import landmarks as marksmod
from i18n import tr

RE_ID = re.compile(r'[a-z0-9][a-z0-9_-]{0,63}')
RE_ZONE = re.compile(r'[A-Za-z0-9_]{1,60}')         # код зоны, как его пишет лог игры
MAX_STEPS = 400
MAX_GOALS = 600
MAX_TOUCH = 12       # точек перехода у одного шага
STEP_KEYS = ('id', 'zone', 'also', 'event', 'level', 'name', 'far', 'target', 'filter', 'filterName', 'touch')   # порядок полей шага в файле
# Код фильтра — так фильтр называет лог игры: у фильтра с сайта это короткий код, у своего — имя файла.
RE_FILTER = re.compile(r'[^\x00-\x1f"\\]{1,80}')
# заметки (note) у цели шага нет: страница её не правит (у целей билда она есть не у всех: у умения и того,
# что при нём, её тоже нет — buildplan.check_goals)
GOAL_TEXT = {'title': 200, 'group': 40, 'reward': 200}
GOAL_STEPS = ('need', 'from', 'until')
GOAL_FLAGS = ('must', 'final')      # soft («о пропущенном боссе не напоминать») страница не ставит
GOAL_KINDS = ('boss', 'quest')


def areas(cat, route, heard=None):
    """Зоны игры — выбор для шага и для точки перехода: [{code, name, own, act, level, town, waypoint}].
    name — английское название из данных игры; own — название на языке игрока, если оно известно: так зону
    называл лог игры (heard: {код: название}) или так назван шаг маршрута с этой зоной. По порядку актов
    и уровня."""
    own = dict(heard or {})
    for s in (route or {}).get('steps') or []:
        if isinstance(s, dict) and s.get('zone') and s.get('name'):
            own.setdefault(s['zone'], s['name'])
        for t in (s.get('touch') or []) if isinstance(s, dict) else []:
            if isinstance(t, dict) and t.get('zone') and t.get('name'):
                own.setdefault(t['zone'], t['name'])
    out = [{'code': code, 'name': a.get('name') or code, 'own': own.get(code), 'act': a.get('act'), 'level': a.get('level'),
            'town': bool(a.get('town')), 'waypoint': bool(a.get('waypoint'))}
           for code, a in ((cat or {}).get('areas') or {}).items()]
    return sorted(out, key=lambda a: (a['act'] or 0, a['level'] or 0, a['code']))


def describe(cat, route, heard=None):
    """Маршрут для страницы: шаги и их цели как они записаны в файле, зоны игры и события, по которым
    шаг может наступать."""
    route = route or {}
    return {
        'route': {'steps': [s for s in route.get('steps') or [] if isinstance(s, dict) and s.get('id')],
                  'goals': [g for g in route.get('goals') or [] if isinstance(g, dict) and g.get('id')]},
        'areas': areas(cat, route, heard),
        'events': list(core.STEP_EVENTS),
    }


def _text(val, limit):
    """Строка без пробелов по краям или None, если это не строка или она длиннее limit."""
    return val.strip() if isinstance(val, str) and len(val.strip()) <= limit else None


def check_steps(raw, route, problems, filters=None):
    """Проверяет присланные шаги маршрута и возвращает записи для файла. Поле, которое у прежней записи
    шага было таким же, проходит как есть. У изменённого и нового шага поля встают в привычном порядке.
    filters — фильтры, которые сейчас есть в игре: {код: название} (server.filter_names). Новым фильтром шага
    можно назвать только такой; фильтр шага, которого на этой машине нет, но он был записан, не мешает
    записать остальное. Название фильтра (filterName) пишет программа — из игры, а игра не знает фильтра —
    прежнее: страница его не правит."""
    if not isinstance(raw, list) or not raw or len(raw) > MAX_STEPS:
        problems.append(tr('шаги маршрута: нужен непустой список не длиннее %d') % MAX_STEPS)
        return []
    old = {s['id']: s for s in (route or {}).get('steps') or [] if isinstance(s, dict) and s.get('id')}
    out, ids = [], set()
    for s in raw:
        if not (isinstance(s, dict) and isinstance(s.get('id'), str) and RE_ID.fullmatch(s['id'])):
            problems.append(tr('шаг: id — латинские буквы, цифры, дефис'))
            continue
        sid = s['id']
        if sid in ids:
            problems.append(tr('шаг «%s» прислан дважды') % sid)
            continue
        ids.add(sid)
        was, rec = old.get(sid) or {}, {'id': sid}
        name = s.get('name').strip() if isinstance(s.get('name'), str) else ''
        where = tr('шаг «%s»') % (name or sid)
        for key, val in s.items():
            if key in ('id', 'notes'):
                # задачи шага (notes) больше не пишутся: страница прежнего вида их присылает — их просто нет
                continue
            if key in was and was[key] == val:
                rec[key] = val
            elif key == 'name':
                if not name or len(name) > 80:
                    problems.append(tr('шаг «%s»: нужно название не длиннее 80 знаков') % sid)
                else:
                    rec[key] = name
            elif key == 'zone':
                if val in (None, ''):
                    continue
                if not (isinstance(val, str) and RE_ZONE.fullmatch(val.strip())):
                    problems.append(tr('%s: зона — её код из лога игры (G1_2)') % where)
                else:
                    rec[key] = val.strip()
            elif key == 'also':
                codes = [x.strip() for x in val if isinstance(x, str) and x.strip()] if isinstance(val, list) else None
                if codes is None or any(not RE_ZONE.fullmatch(x) for x in codes):
                    problems.append(tr('%s: ещё зоны шага — список кодов зон') % where)
                elif codes:
                    rec[key] = codes
            elif key == 'event':
                if val in (None, ''):
                    continue
                if val not in core.STEP_EVENTS:
                    problems.append(tr('%s: событие бывает только %s') % (where, ', '.join(core.STEP_EVENTS)))
                else:
                    rec[key] = val
            elif key == 'level':
                if val in (None, ''):
                    continue
                if not core.is_int(val) or not 1 <= val <= 100:
                    problems.append(tr('%s: уровень зоны — целое от 1 до 100') % where)
                else:
                    rec[key] = val
            elif key == 'far':
                if val not in (True, False, None):
                    problems.append(tr('%s: пометка «дальняя веха» — да или нет') % where)
                elif val:
                    rec[key] = True
            elif key == 'filter':
                # какой фильтр игры включают с этого шага: код фильтра или «none» — выключить; пусто — как раньше
                if val in (None, ''):
                    continue
                if isinstance(val, str) and RE_FILTER.fullmatch(val) and (val == core.NO_FILTER or val in (filters or {})):
                    rec[key] = val
                else:
                    problems.append(tr('%s: фильтра «%s» нет в игре') % (where, val))
            elif key == 'filterName':
                continue                    # название фильтра пишет программа (ниже), не страница
            elif key == 'target':
                # цель по времени на шаг; пустая в запись не идёт
                if val in (None, ''):
                    continue
                if not isinstance(val, str) or core.parse_clock(val) is None:
                    problems.append(tr('%s: цель по времени — вида 5:30 или 1:05:00') % where)
                else:
                    rec[key] = val.strip()
            elif key == 'touch':
                ok = isinstance(val, list) and len(val) <= MAX_TOUCH and all(
                    isinstance(t, dict) and set(t) <= {'zone', 'name'} and isinstance(t.get('zone') or '', str)
                    and _text(t.get('name') or '', 80) is not None for t in val)
                if not ok or any((t.get('zone') or '').strip() and not RE_ZONE.fullmatch(t['zone'].strip()) for t in val):
                    problems.append(tr('%s: точки перехода — список зон (до %d), каждая — её код из лога игры') % (where, MAX_TOUCH))
                    continue
                # название у точки своё только в старых файлах: точку называет её зона (core.derive)
                touch = [dict({'zone': t['zone'].strip()}, **({'name': t['name'].strip()} if (t.get('name') or '').strip() else {}))
                         for t in val if (t.get('zone') or '').strip()]
                if touch:
                    rec[key] = touch
            else:
                problems.append(tr('%s: поле «%s» со страницы не правится') % (where, key))
        if 'name' not in rec and not any(p.startswith(tr('шаг «%s»: нужно название') % sid) for p in problems):
            problems.append(tr('шаг «%s»: нужно название не длиннее 80 знаков') % sid)
        # название фильтра шага — из игры: так его увидят игроки, у которых этого фильтра ещё нет; игра его
        # не знает (фильтра нет на этой машине) — остаётся прежнее, записанное у того же фильтра
        rec.pop('filterName', None)
        fid = rec.get('filter')
        if fid and fid != core.NO_FILTER:
            name = (filters or {}).get(fid) or (was.get('filterName') if was.get('filter') == fid else None)
            if isinstance(name, str) and name.strip():
                rec['filterName'] = name.strip()[:120]
        if len([k for k in ('zone', 'event', 'level') if k in rec]) != 1:
            problems.append(tr('%s: шаг узнаётся по одному из трёх — зона, событие или уровень зоны') % where)
        if 'also' in rec and 'zone' not in rec:
            problems.append(tr('%s: «ещё зоны» бывают только у шага с зоной') % where)
        if rec != was or list(rec) != list(was):
            rec = dict([(k, rec[k]) for k in STEP_KEYS if k in rec] + [(k, v) for k, v in rec.items() if k not in STEP_KEYS])
        out.append(rec)
    return out


def check_goals(raw, route, steps, taken, problems, stats=None, marks=None):
    """Проверяет присланные цели шага и возвращает записи для файла. steps — id шагов нового маршрута;
    taken — id целей билда: цели шага такой id дать нельзя; stats — статы героя из данных игры (их id):
    по ним сверяется, что награда даёт герою; marks — справочник игры ({id: запись}): цель без своего
    названия — ссылка на его запись (по ref, без него — по своему id), и план говорит о ней только своё (шаг,
    вариант награды) — факты игры в плане не правятся. Ссылка по ref бывает только на механику. Поле, которое у прежней записи цели было таким же, проходит как есть;
    остальное — только поля, которые страница правит."""
    if not isinstance(raw, list) or len(raw) > MAX_GOALS:
        problems.append(tr('цели шага: нужен список не длиннее %d') % MAX_GOALS)
        return []
    old = {g['id']: g for g in (route or {}).get('goals') or [] if isinstance(g, dict) and g.get('id')}
    out, ids = [], set()
    for g in raw:
        if not (isinstance(g, dict) and isinstance(g.get('id'), str) and RE_ID.fullmatch(g['id'])):
            problems.append(tr('цель шага: id — латинские буквы, цифры, дефис'))
            continue
        gid = g['id']
        if gid in ids or gid in taken:
            problems.append(tr('цель шага «%s»: такой id уже есть%s') % (gid, tr(' у цели билда') if gid in taken else ''))
            continue
        ids.add(gid)
        was, rec = old.get(gid) or {}, {}
        # ссылка на запись справочника игры: по полю ref (механика на нескольких шагах), без него — по своему id
        key = g['ref'] if 'title' not in g and isinstance(g.get('ref'), str) else gid
        ref = (marks or {}).get(key) if 'title' not in g else None
        name = g.get('title').strip() if isinstance(g.get('title'), str) else (ref or {}).get('title') or ''
        where = tr('цель шага «%s»') % (name or gid)
        for field, val in g.items():
            if field == 'id' or (field in was and was[field] == val):
                rec[field] = val
            elif field == 'ref':
                # на какую запись справочника ссылается цель со своим id: так ставят механику и восхождение
                if ref is None or ref.get('kind') not in marksmod.MULTI:
                    problems.append(tr('%s: ссылка ref — id механики или восхождения из справочника игры') % where)
                else:
                    rec[field] = val
            elif ref is not None and field not in marksmod.PLAN_KEYS:
                problems.append((tr('%s: поле «%s» — факт игры из справочника, в плане он не правится')
                                 if field in marksmod.FACT_KEYS else tr('%s: поле «%s» со страницы не правится')) % (where, field))
            elif field == 'opt':
                # какой вариант награды с выбором берёт план: номер с единицы; пусто — выбор не сделан
                if val in (None, ''):
                    continue
                n = len((ref or {}).get('options') or [])
                if not n:
                    problems.append(tr('%s: выбирать вариант не из чего') % where)
                elif not core.is_int(val) or not 1 <= val <= n:
                    problems.append(tr('%s: вариант — номер от 1 до %d') % (where, n))
                else:
                    rec[field] = val
            elif field in GOAL_TEXT:
                if val is None:
                    continue
                text = _text(val, GOAL_TEXT[field])
                if text is None:
                    problems.append(tr('%s: поле %s — текст не длиннее %d знаков') % (where, field, GOAL_TEXT[field]))
                elif text:
                    rec[field] = text
            elif field in GOAL_STEPS:
                if val in (None, ''):
                    continue
                if val not in steps:
                    problems.append(tr('%s: шага «%s» в маршруте нет') % (where, val))
                else:
                    rec[field] = val
            elif field in GOAL_FLAGS:
                if val not in (True, False, None):
                    problems.append(tr('%s: пометка %s — да или нет') % (where, field))
                elif val:
                    rec[field] = True
            elif field == 'reach':
                if val in (None, ''):
                    continue
                if not core.is_int(val) or not 1 <= val <= 100:
                    problems.append(tr('%s: уровень героя — целое от 1 до 100') % where)
                else:
                    rec[field] = val
            elif field == 'kind':
                if val in (None, ''):
                    continue
                if val not in GOAL_KINDS:
                    problems.append(tr('%s: цель шага — босс, задание или награда') % where)
                else:
                    rec[field] = val
            elif field == 'heard':
                # реплика в логе, по которой цель отмечается сама; несколько — когда победа звучит по-разному
                lines = [val] if isinstance(val, str) else val if isinstance(val, list) else None
                if lines is None or any(_text(x, 200) is None for x in lines):
                    problems.append(tr('%s: реплики — строки не длиннее 200 знаков') % where)
                    continue
                lines = [x.strip() for x in lines if x.strip()]
                if lines:
                    rec[field] = lines[0] if len(lines) == 1 else lines
            elif field == 'gives':
                # что цель даёт герою навсегда (награда задания, книга): {стат: число} — идёт в статы героя
                if val in (None, '', {}):
                    continue
                if not (isinstance(val, dict) and all(
                        isinstance(k, str) and (stats is None or k in stats) and isinstance(n, (int, float))
                        and not isinstance(n, bool) and n for k, n in val.items())):
                    problems.append(tr('%s: «даёт герою» — статы из данных игры, у каждого число') % where)
                else:
                    rec[field] = dict(val)
            elif field == 'grantedBy':
                if val in (None, ''):
                    continue
                if not isinstance(val, str):
                    problems.append(tr('%s: «чем дано» — id цели') % where)
                else:
                    rec[field] = val                # есть ли такая цель, скажет сборка плана целиком
            else:
                problems.append(tr('%s: поле «%s» со страницы не правится') % (where, field))
        if ref is None and not rec.get('title'):
            problems.append(tr('цель шага «%s»: нужно название') % gid if 'title' in g or marks is None
                            else tr('цель шага «%s»: такой записи нет в справочнике игры') % gid)
        elif not rec.get('need'):
            problems.append(tr('%s: не назван её шаг') % where)
        out.append(rec)
    return out


def check(raw, route, taken, problems, stats=None, marks=None, filters=None):
    """Проверяет присланный маршрут ({steps, goals}) и возвращает его в виде для файла. marks — справочник
    игры (см. check_goals); filters — фильтры игры (см. check_steps). Замечания дописываются в problems.
    Названия у маршрута нет: то, что прислала страница прежнего вида, не берётся."""
    if not isinstance(raw, dict) or 'steps' not in raw or 'goals' not in raw:
        problems.append(tr('маршрут: нужны шаги и их цели'))
        return {}
    steps = check_steps(raw['steps'], route, problems, filters)
    goals = check_goals(raw['goals'], route, {s['id'] for s in steps}, set(taken or ()), problems, stats, marks)
    return {'steps': steps, 'goals': goals}


def gone_steps(route, steps):
    """Id шагов, которых в новом списке нет."""
    return {s['id'] for s in (route or {}).get('steps') or [] if isinstance(s, dict) and s.get('id')} - {s['id'] for s in steps}


def splice_steps(text, steps):
    """Текст файла маршрута с новым списком шагов. Раздел лежит в файле обычной раскладкой с отступом в два
    пробела: так он и пишется, и раздел, в котором ничего не менялось, остаётся знак в знак. Всё остальное
    остаётся как было — иначе ValueError."""
    eol = '\r\n' if '\r\n' in text else '\n'
    lines = text.split(eol)
    before = json.loads(text)
    starts = [i for i, ln in enumerate(lines) if ln == '  "steps": [']
    if len(starts) != 1 or not isinstance(before.get('steps'), list):
        raise ValueError(tr('раздел шагов маршрута записан непривычно — править его со страницы нельзя'))
    s = starts[0]
    e = next((i for i in range(s + 1, len(lines)) if lines[i] in ('  ],', '  ]')), None)
    if e is None:
        raise ValueError(tr('у раздела шагов маршрута не найден конец'))
    body = json.dumps(steps, ensure_ascii=False, indent=2).split('\n')
    new = ['  "steps": ' + body[0]] + ['  ' + ln for ln in body[1:]]
    if lines[e].endswith(','):
        new[-1] += ','
    out = eol.join(lines[:s] + new + lines[e + 1:])
    after = json.loads(out)
    rest = lambda d: {k: v for k, v in d.items() if k != 'steps'}   # noqa: E731
    same_order = [list(x) for x in after.get('steps') or []] == [list(x) for x in steps]
    if after.get('steps') != steps or not same_order or rest(before) != rest(after) or list(before) != list(after):
        raise ValueError(tr('после правки изменилось бы что-то ещё — файл не тронут'))
    return out


def render(text, route):
    """Текст файла маршрута с новыми шагами и их целями (после check). Запись цели, которая не менялась,
    остаётся в файле знак в знак (buildplan.splice_goals: цель — одна строка)."""
    return buildplan.splice_goals(splice_steps(text, route['steps']), route['goals'])
