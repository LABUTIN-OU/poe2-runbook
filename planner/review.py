# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Sergei Labutin
# Additional terms under GPL-3.0 section 7: see NOTICE.md
"""Разбор времени героя (режим «Разбор»): куда ушло чистое время — по тому, чем герой был занят на самом деле.

Чем герой был занят, считает core.step_spans — один счёт на всю программу: по нему же идёт время шага на странице
«Игра». Время привязано к шагу, которым герой занят, а не к кнопке «Шаг пройден»: нажали кнопку раньше, чем дошли до
новой карты, — остаток прежней карты и город после неё остаются у её шага. Короткий заход на другую карту (открыть
точку перехода, взять вход) шаг не меняет. Время шага делится по месту: зоны шага, город и убежище, зоны вне маршрута.
Время вне игры и на паузе не считается нигде. Сумма по шагам равна чистому времени героя.

Здесь из этого счёта собирается таблица героя: шаги по порядку маршрута, у каждого — лента заходов с метками (вышел из
игры, карта начата заново, страницу перевели на другой шаг, гибель). Время героя кончается его гибелью.

Карта, начатая заново (core.map_copies): герой вышел из игры на карте и вернулся уже в новую её копию — так уходят с
карты через выбор героя, когда оставаться опасно. Время в брошенных копиях — время прерванных попыток: оно остаётся в
зонах шага (или вне маршрута) и показано в них отдельной частью.
"""
import core

# Виды записей в ленте шага; странице уходит номер вида (KINDS.index): слова о нём — её дело
KINDS = ('zone', 'peek', 'town', 'off', 'leave', 'button', 'death', 'again')


def end_of(run):
    """Когда кончилось время героя: его гибель (в лиге «Хардкор» она окончательна; что лог писал после неё — уже не
    эта игра) или последняя строка лога. Гибель — своя: имя совпало с именем героя или имени ещё нет."""
    name = next((e.get('name') for e in run.events if e['type'] == 'level' and e.get('name')), None)
    for e in run.events:
        if e['type'] == 'death' and (not name or not e.get('name') or e['name'] == name):
            return e['ts'], True
    return (max(e['ts'] for e in run.events) if run.events else run.started), False


def split(plan, run, pos_log, now=None):
    """Разбор времени героя по шагам плана.

    pos_log — когда какой шаг становился текущим на странице ([время, номер шага], core.derive, поле posLog).
    now — до какого времени считать живого героя (без него — до последней строки лога).

    Ответ: {'end', 'dead', 'clean', 'total': {zone, town, off, all}, 'steps': [по порядку маршрута, только шаги со
    временем]}. Шаг: {'i', 'id', 'name', 'act' — группа таблицы, 'target', 'zone', 'town', 'off', 'all',
    'at' — чистое время, когда герой занялся шагом, 'leaves' — сколько раз вышли из игры, 'cut' — сколько шаг длился,
    когда время героя кончилось (гибель, конец лога: этот шаг не пройден; у остальных None), 'maps' — шаг на картах,
    'again' — сколько попыток на шаге прервано (карту начинали заново), 'lostZone', 'lostOff' — время в брошенных
    копиях: часть zone и часть off,
    'parts': [{'t' — чистое время от старта, 'kind', 'name', 'dur', 'drop' — заход в брошенную копию}]} — лента шага по
    порядку. Виды в ленте (KINDS): zone, town, off — где шло время; peek — короткий заход на другую карту (его время —
    в zone); leave — вышли из игры; again — карта начата заново (перед первым заходом в новую копию); button —
    страницу перевели на другой шаг (name — на какой); death — гибель.
    """
    steps = plan['steps']
    end, dead = end_of(run)
    if not dead and now is not None:
        end = max(end or now, now)
    if end is None or not steps:
        return {'end': end, 'dead': dead, 'clean': 0, 'total': {'zone': 0, 'town': 0, 'off': 0, 'all': 0}, 'steps': []}
    spans = core.step_spans(plan, run.events, run.hold, run.started, pos_log, end)
    active = spans['active']
    rows = {}

    def row(i):
        if i not in rows:
            s = steps[i]
            rows[i] = {'i': i, 'id': s['id'], 'name': s.get('name') or s['id'], 'target': core.parse_clock(s.get('target')),
                       'zone': 0, 'town': 0, 'off': 0, 'at': None, 'leaves': 0, 'cut': None, 'parts': [],
                       'lostZone': 0, 'lostOff': 0, 'again': 0}
        return rows[i]

    for p in spans['pieces']:
        r, kind, x = row(p['step']), p['kind'], p['a']
        if kind == 'leave':
            r['leaves'] += 1
            r['parts'].append({'t': int(active(x)), 'ts': x, 'kind': 'leave', 'name': None, 'dur': 0})
            continue
        if r['at'] is None and kind == 'zone':
            r['at'] = int(active(x))
        r['zone' if kind == 'peek' else kind] += p['dur']
        drop = p.get('drop')
        if drop:
            r['lostOff' if kind == 'off' else 'lostZone'] += p['dur']
        if p.get('quit'):
            r['again'] += 1       # попытка прервана на этом шаге: им герой был занят, когда вышел из игры
        if p.get('again'):
            # карта начата заново: метка встаёт перед первым заходом в новую копию
            r['parts'].append({'t': int(active(x)), 'ts': x, 'kind': 'again', 'name': p['name'], 'dur': 0})
        last = r['parts'][-1] if r['parts'] else None
        if last and last['kind'] == kind and last['name'] == p['name'] and last.get('_to') == x and last.get('drop') == bool(drop):
            last['dur'] += p['dur']     # тот же заход, разрезанный сменой шага на странице, или та же зона подряд
            last['_to'] = p['b']
        else:
            r['parts'].append({'t': int(active(x)), 'ts': x, 'kind': kind, 'name': p['name'], 'dur': p['dur'], '_to': p['b'],
                               'drop': bool(drop)})

    # Перевод страницы на другой шаг и конец времени героя — метки в ленте шага, которому шло время в тот момент
    # (вне игры — последнему)
    def owner_at(t):
        best = None
        for r in rows.values():
            for part in r['parts']:
                if part['kind'] not in ('leave', 'again') and part['ts'] <= t and (best is None or part['ts'] >= best[0]):
                    best = (part['ts'], r)
        return best[1] if best else None

    names = {s['id']: s.get('name') or s['id'] for s in steps}
    for m in run.moves:
        if m['ts'] <= end and m.get('step') in names:
            r = owner_at(m['ts'])
            if r is not None and r['id'] != m['step']:       # перевод на этот же шаг в его ленте ничего не говорит
                r['parts'].append({'t': int(active(m['ts'])), 'ts': m['ts'], 'kind': 'button', 'name': names[m['step']],
                                   'dur': 0})
    # Шаг, которым герой был занят, когда его время кончилось, не пройден: его время с целью не сравнить
    r = owner_at(end)
    if r is not None:
        r['cut'] = int(round(r['zone'] + r['town'] + r['off']))
        if dead:
            r['parts'].append({'t': int(active(end)), 'ts': end + 0.5, 'kind': 'death', 'name': None, 'dur': 0})

    # Группа таблицы — акт по порядку маршрута: шаг-возврат в зону прошлого акта (третье испытание Сехем среди шагов
    # интерлюдии) остаётся в группе, где он стоит, а не открывает прошлый акт второй раз.
    acts = []
    for s in steps:
        acts.append(core.act_of(s['zone']) if s.get('zone') else (acts[-1] if acts else core.act_of(None)))
    maps_from = core.endgame_from(steps)
    seen, group = [], None
    out = []
    for i in sorted(rows):
        r = rows[i]
        if acts[i] != group and acts[i] not in seen:
            group = acts[i]
            seen.append(group)
        r['act'] = group
        r['maps'] = maps_from is not None and i >= maps_from
        r['parts'].sort(key=lambda x: x['ts'])
        for part in r['parts']:
            part.pop('_to', None)
            part.pop('ts', None)
            part['dur'] = int(round(part['dur']))
        for k in ('zone', 'town', 'off', 'lostZone', 'lostOff'):
            r[k] = int(round(r[k]))
        r['all'] = r['zone'] + r['town'] + r['off']
        out.append(r)
    total = {k: sum(r[k] for r in out) for k in ('zone', 'town', 'off', 'all')}
    return {'end': end, 'dead': dead, 'clean': int(active(end)), 'total': total, 'steps': out}


def page(res):
    """Разбор для страницы — короткими ключами: у героя на картах лента длинная, а строк в таблице под сотню.
    {'clean', 'dead', 'end', 'maps' — герой дошёл до карт, 'total': {z, t, o}, 'steps': [{'i', 'id', 'n' — название,
    'a' — акт, 'g' — цель шага в секундах или None, 'z', 't', 'o' — секунды в зонах шага, в городе, вне маршрута,
    'q' — сколько раз карту начинали заново, 'qz', 'qo' — секунды в брошенных копиях (часть z и часть o),
    'l' — выходов из игры, 'c' — cut, 'at', 'p': [[t, номер вида (KINDS), название, секунды]; у захода в брошенную
    копию пятым стоит 1]}]}."""
    steps = [{'i': r['i'], 'id': r['id'], 'n': r['name'], 'a': r['act'], 'g': r['target'], 'z': r['zone'], 't': r['town'],
              'o': r['off'], 'q': r['again'], 'qz': r['lostZone'], 'qo': r['lostOff'],
              'l': r['leaves'], 'c': r['cut'], 'at': r['at'],
              'p': [[p['t'], KINDS.index(p['kind']), p['name'], p['dur']] + ([1] if p.get('drop') else [])
                    for p in r['parts']]} for r in res['steps']]
    t = res['total']
    return {'clean': res['clean'], 'dead': res['dead'], 'end': res['end'], 'maps': any(r['maps'] for r in res['steps']),
            'total': {'z': t['zone'], 't': t['town'], 'o': t['off']}, 'steps': steps}
