# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Sergei Labutin
# Additional terms under GPL-3.0 section 7: see NOTICE.md
"""Враждебные планы — для проверки, что план от незнакомого автора не выполнит код в окне программы, не сломает
страницу и ничего не запишет мимо библиотеки планов.

Поля плана генератор берёт из той же схемы, по которой план принимается (planguard): каждое поле, которое знает
проверка, получает по очереди враждебные значения. Два вида наборов:

  * TEXT — то, что проверка пропускает: разметка с обработчиком, закрытие атрибута и тега, ссылки javascript:
    и data:, кавычки и обратные апострофы, сущности, комментарии, текст до самого предела поля. Такой план
    ложится в библиотеку; страницы обязаны показать его текстом. Каждая вставка, если её выполнят, ставит
    отметку window.__hit = <номер> (по номеру видно поле), а разметка оставляет на странице элемент
    с атрибутом data-zz или тег x-zz — их ищет проверка страниц (hostile_pages.py).
  * REFUSED — то, что проверка обязана отвергнуть понятными словами: длинные строки, управляющие знаки и смена
    направления письма, пути с ..\\ и / в id, имена служебных свойств JavaScript, огромные числа, NaN, глубокая
    вложенность, повтор id и ключа, неизвестные поля, не те типы, лишние записи.

base() — план, в котором заполнено каждое поле схемы (свой маленький, на нём идут тесты); enrich(route, build) —
дописывает такие записи в настоящий план (на нём идёт проверка страниц: на нём видны все её части).
"""
import copy
import json
import re

import planguard
import planlib

MARK = 'data-zz'            # атрибут вставленной разметки: найден на странице — разметка легла разметкой
HIT = '__hit={t}'           # отметка выполненного кода (в обработчике разметки — глобальная переменная окна)

# Наборы, которые проверка пропускает: (длинный вид, короткий вид для полей до 20–40 знаков). {t} — номер поля.
TEXT = {
    'img': ('<img data-zz src=x onerror=__hit={t}>', '<x-zz>{t}</x-zz>'),
    'dquote': ('"><svg data-zz onload=__hit={t}>', '"><x-zz>{t}'),
    'squote': ("'><svg data-zz onload=__hit={t}>", "'><x-zz>{t}"),
    'script': ('</script><script data-zz>__hit={t}</script>', '<x-zz>{t}</x-zz>'),
    'attr': ('" data-zz onmouseover=__hit={t} x="', '" data-zz x="{t}'),
    'sattr': ("' data-zz onfocus=__hit={t} autofocus x='", "' data-zz x='{t}"),
    'jsurl': ('javascript:__hit={t}', 'javascript:{t}'),
    'dataurl': ('data:text/html,<svg data-zz onload=parent.__hit={t}>', 'data:,{t}<x-zz>'),
    'template': ('${__hit={t}}`;__hit={t};//`+(__hit={t})+\'', '${__hit={t}}`'),
    'entity': ('&lt;svg data-zz onload=__hit={t}&gt;&#60;x-zz&#62;{t}', '&lt;x-zz&gt;{t}'),
    'close': ('</style></textarea></title></select><svg data-zz onload=__hit={t}>', '</style><x-zz>{t}'),
    'comment': ('<!-- {t} <x-zz> ]]> --!>', '<!--{t}'),
    'quotes': ('\'"`\\\\</ \\" \\\' ${{x}} {t} %s %d {{0}}', '\'"`\\{t}'),
    'longest': (None, None),       # текст ровно до предела поля
}

# Значения, которые проверка обязана отвергнуть.
CTRL = ['x\x00y', 'x\x07y', 'x\x1b[31my', 'x\x7fy', 'x\x85y', 'x\u202ey', 'x\u2066y', 'x\u200fy', 'x\u2028y',
        'x\ufeffy', 'x\ud800y', 'x\U000e0041y', 'x\uffffy']
PATHS = ['..\\..\\evil', '../../evil', '/etc/passwd', 'C:\\Windows\\x', 'a/b', 'a\\b', '.', '..', 'A:',
         '\\\\host\\share']
JS = ['__proto__', 'constructor', 'toString', 'valueOf', 'hasOwnProperty']
WRONG = {'text': [123, 1.5, True, None, [], {}, ['x']],
         'pattern': [123, True, None, [], {'a': 1}],
         'int': ['5', 5.5, True, None, 10 ** 30, -(10 ** 30), [], float('inf')],
         'num': ['5', True, None, 10 ** 30, float('inf'), float('-inf'), []],
         'flag': ['true', 1, 0, None, []],
         'one_of': ['x', 1, None],
         'items': ['x', 1, {}, None],
         'record': ['x', 1, [], None],
         'mapping': ['x', 1, [], None]}


# --- поля по схеме ----------------------------------------------------------------------------------------

def _pick(value, check):
    """Вид из either, которому значение соответствует сейчас (строка — первый, список — второй…)."""
    for k in check.kinds:
        found = []
        k(value, '', found)
        if not found:
            return k
    return check.kinds[0]


def leaves(value, check, path='', parent=None, key=None, outer=None):
    """Каждое поле value по схеме check: (путь, словарь или список, ключ, вид поля, either или None). Вид — text,
    pattern, int, num, flag, one_of; у записи, списка и словаря — их поля. Последнее — вид «одно из» (строка или
    список строк), через который поле найдено: значение, подходящее ему, — не враждебное."""
    kind = getattr(check, 'kind', None)
    if kind == 'either':
        yield from leaves(value, _pick(value, check), path, parent, key, outer or check)
    elif kind == 'record' and isinstance(value, dict):
        for k, v in value.items():
            if k in check.fields:
                yield from leaves(v, check.fields[k], '%s.%s' % (path, k) if path else k, value, k)
    elif kind == 'items' and isinstance(value, list):
        for i, v in enumerate(value):
            yield from leaves(v, check.item, '%s[%d]' % (path, i), value, i)
    elif kind == 'mapping' and isinstance(value, dict):
        for k, v in list(value.items()):
            yield from leaves(v, check.value, '%s.%s' % (path, k), value, k)
    elif kind is not None and parent is not None:
        yield path, parent, key, check, outer


def shapes(value, check, path='', outer=None):
    """Записи и списки по схеме (для неизвестных полей, повторов, лишних записей): (путь, значение, вид, either
    или None — как у leaves)."""
    kind = getattr(check, 'kind', None)
    if kind == 'either':
        yield from shapes(value, _pick(value, check), path, outer or check)
    elif kind == 'record' and isinstance(value, dict):
        yield path, value, check, outer
        for k, v in value.items():
            if k in check.fields:
                yield from shapes(v, check.fields[k], '%s.%s' % (path, k) if path else k)
    elif kind == 'items' and isinstance(value, list):
        yield path, value, check, outer
        for i, v in enumerate(value):
            yield from shapes(v, check.item, '%s[%d]' % (path, i))
    elif kind == 'mapping' and isinstance(value, dict):
        yield path, value, check, outer


def general(path):
    """Путь без номеров записей: steps[*].touch[*].zone — одно поле схемы."""
    return re.sub(r'\[\d+\]', '[*]', path)


# --- свой маленький план, в котором заполнено каждое поле схемы -------------------------------------------

def base():
    """(маршрут, билд, группы) — каждое поле схемы planguard заполнено верным значением; план собирается
    программой (шаги, цели, слоты, этапы и версии дерева ссылаются друг на друга)."""
    route = {
        'version': 1, 'id': 'campaign-0.5',
        'steps': [
            {'id': 'beach', 'zone': 'G1_1', 'name': 'Берег реки', 'target': '5:30', 'filter': 'none',
             'touch': [{'zone': 'G1_1', 'name': 'Берег'}]},
            {'id': 'clearfell', 'zone': 'G1_2', 'also': ['G1_3'], 'name': 'Клирфелл', 'far': True, 'target': '1:05:00',
             'filter': 'TrialAa1', 'filterName': 'Фильтр 1', 'touch': [{'zone': 'G1_2'}]},
            {'id': 'trial', 'event': 'ascend', 'name': 'После восхождения', 'notes': ['старая задача']},
            {'id': 'maps', 'level': 65, 'name': 'Карты'},
        ],
        'goals': [
            {'id': 'boss-own', 'kind': 'boss', 'title': 'Свой босс', 'group': 'Боссы', 'need': 'clearfell', 'from': 'beach',
             'until': 'trial', 'must': True, 'final': True, 'heard': ['LineA', 'LineB'], 'note': 'заметка\nвторая строка'},
            {'id': 'reward-own', 'title': 'Своя награда', 'group': 'Награды', 'reward': 'base_maximum_life',
             'gives': {'life': 20, 'res_fire': 10.5}, 'need': 'clearfell', 'soft': True, 'grantedBy': 'skill-a'},
            {'id': 'lvl-10', 'title': '10 уровень героя', 'reach': 10, 'need': 'clearfell', 'heard': 'LineC'},
            {'id': 'mech-1', 'ref': 'mech-abyss', 'need': 'beach', 'opt': 1},
        ],
    }
    build = {
        'version': 2, 'title': 'План проверки', 'routeId': 'campaign-0.5',
        'hero': {'class': 'Sorceress', 'ascendancy': 'Disciple of Varashta'},
        'statDefs': [{'id': 'own_stat', 'name': 'Свой стат', 'short': 'СС', 'lines': ['spell_skill_gem_level_+']}],
        'slots': [
            {'id': 'weapon', 'name': 'Оружие', 'wear': [{'classes': ['Wands'], 'kind': 'int_armour'},
                                                     {'from': 'clearfell', 'until': 'maps', 'classes': ['Sceptres']}]},
            {'id': 'old', 'name': 'Старый слот', 'classes': ['Rings'], 'gear': 'Ring', 'doneOn': 'equip'},
        ],
        'stages': [
            {'id': 'start', 'name': 'Начало', 'tree': 'start', 'atlas': 'a1', 'kind': 'int_armour', 'attrs': ['int'],
             'stats': ['life', {'id': 'res_fire', 'cap': 75}, 'own_stat']},
            {'id': 'later', 'from': 'trial', 'name': 'После восхождения'},
        ],
        'goals': [
            {'id': 'skill-a', 'kind': 'skill', 'title': 'Умение (Skill)', 'group': 'Навыки', 'need': 'beach', 'use': 'beach',
             'until': 'maps', 'gemFrom': 2, 'icon': 'art-wand01', 'node': 'spells18'},
            {'id': 'sup-a', 'kind': 'support', 'title': 'Поддержка (Support)', 'for': 'skill-a', 'part': 'Гнездо I',
             'need': 'clearfell', 'opens': 3, 'any': True},
            {'id': 'gem5-a', 'kind': 'gem', 'part': 'level', 'title': '5', 'for': 'skill-a', 'need': 'clearfell', 'hero': 5},
            {'id': 'wand', 'slot': 'weapon', 'title': 'Жезл', 'label': 'Оружие', 'gear': 'Wand', 'rarity': 'Magic',
             'need': 'beach', 'key': True, 'note': 'заметка', 'probe': {'Class': 'Wands', 'BaseType': 'Withered Wand',
                                                                        'Rarity': 'Magic', 'DropLevel': 1}},
            {'id': 'wand-stat', 'slot': 'weapon', 'part': 'Жезл', 'stat': 'own_stat', 'min': 2.5, 'title': 'Уровень умений',
             'need': 'clearfell'},
            {'id': 'gold', 'kind': 'resource', 'title': 'Золото', 'group': 'Ресурсы', 'need': 'maps', 'soft': True,
             'heard': 'LineD', 'doneOn': 'find'},
        ],
        'tree': {'attr': 'int', 'phases': [
            {'id': 'start', 'name': 'Старт', 'nodes': [{'id': 'spells18', 'name': 'Чары', 'kind': 'notable'},
                                                      {'id': 'attr1', 'name': 'Характеристика', 'kind': 'attribute', 'attr': 'int'}],
             'items': [{'id': 'amulet_node', 'name': 'Узел с амулета', 'slot': 'old'}], 'without': 'plain'},
            {'id': 'plain', 'name': 'Без амулета', 'nodes': [{'id': 'spells18', 'name': 'Чары'}]},
        ]},
        'atlas': {'phases': [{'id': 'a1', 'name': 'Атлас', 'nodes': [{'id': 'AtlasGenericSmall71', 'name': 'Узел', 'opt': 1}]}]},
        'gemLevels': [1, 3, 5],
    }
    return route, build, ['Навыки', 'Боссы', 'Награды', 'Ресурсы']


def enrich(route, build):
    """Настоящий план (маршрут и билд, разобранные) с записями, у которых заполнены поля, которых в нём нет: каждое
    поле схемы встречается хотя бы раз — значит, каждое попадёт под враждебное значение. Шаги и цели плана
    остаются; новые цели стоят на его первом шаге."""
    route, build = copy.deepcopy(route), copy.deepcopy(build)
    r0, b0, _ = base()
    steps = [s['id'] for s in route.get('steps') or []]
    first = steps[0] if steps else 'beach'
    last = steps[-1] if steps else 'beach'
    have = {s['id'] for s in route.get('steps') or []}
    for s in r0['steps']:
        if s['id'] not in have:
            route.setdefault('steps', []).append(dict(s, id='zz-' + s['id']))
    fix = {'beach': first, 'clearfell': first, 'trial': last, 'maps': last}
    def moved(rec, keys):
        return {k: (fix.get(v, v) if k in keys else v) for k, v in rec.items()}
    for g in r0['goals']:
        route.setdefault('goals', []).append(moved(dict(g, id='zz-' + g['id']), ('need', 'from', 'until')))
    slots = {s['id'] for s in build.get('slots') or []}
    for s in b0['slots']:
        if s['id'] not in slots:
            rec = dict(s, id='zz-' + s['id'])
            if 'wear' in rec:
                rec['wear'] = [moved(p, ('from', 'until')) for p in rec['wear']]
                rec['wear'][1]['from'] = steps[1] if len(steps) > 1 else first
            build.setdefault('slots', []).append(rec)
    for g in b0['goals']:
        rec = moved(dict(g, id='zz-' + g['id']), ('need', 'from', 'use', 'until'))
        for k in ('for', 'slot'):
            if k in rec:
                rec[k] = 'zz-' + rec[k]
        if rec.get('stat') == 'own_stat':
            rec['stat'] = 'life'
        build.setdefault('goals', []).append(rec)
    for g in route['goals']:
        if g.get('grantedBy') == 'skill-a':
            g['grantedBy'] = 'zz-skill-a'
    defs = build.setdefault('statDefs', [])
    if not any(d.get('id') == 'own_stat' for d in defs):
        defs.append(dict(b0['statDefs'][0], id='zz_own_stat'))
    for key in ('tree', 'atlas'):
        sec = build.setdefault(key, {'phases': []})
        sec.setdefault('phases', [])
        if key == 'tree':
            sec.setdefault('attr', 'int')
        for ph in b0[key]['phases']:
            rec = dict(ph, id='zz-' + ph['id'])
            if 'without' in rec:
                rec['without'] = 'zz-' + rec['without']
            if 'items' in rec:
                rec['items'] = [dict(x, slot='zz-old') for x in rec['items']]
            sec['phases'].append(rec)
    build.setdefault('hero', {}).setdefault('class', 'Sorceress')
    build['hero'].setdefault('ascendancy', 'Disciple of Varashta')
    stages = build.setdefault('stages', [])
    if stages:
        st = stages[0]
        st.setdefault('kind', 'int_armour')
        st.setdefault('attrs', ['int'])
        st.setdefault('stats', [])
        if not any(isinstance(x, dict) for x in st['stats']):
            st['stats'].append({'id': 'res_cold', 'cap': 75})
    else:
        stages.extend(b0['stages'])
    build.setdefault('gemLevels', [1, 3, 5])
    return route, build


# --- враждебные варианты ----------------------------------------------------------------------------------

def payload(family, tag, limit):
    """Значение набора family с номером tag, не длиннее limit знаков."""
    if family == 'longest':
        head = 'Ш%d ' % tag
        return (head + 'Ш' * limit)[:limit]
    long, short = TEXT[family]
    for form in (long, short):
        text = form.replace('{t}', str(tag))
        if len(text) <= limit:
            return text
    return str(tag)[:limit]


def hostile_text(route, build, groups, family, start=1):
    """Копия плана, в которой КАЖДОЕ текстовое поле — значение набора family со своим номером. Возвращает (маршрут,
    билд, группы, {номер: путь поля}). Номера идут с start (у разных планов — разные)."""
    route, build, groups = copy.deepcopy(route), copy.deepcopy(build), list(groups)
    tags, n = {}, start
    for part, value, check in (('route', route, planguard.ROUTE), ('build', build, planguard.BUILD)):
        for path, parent, key, kind, _ in list(leaves(value, check)):
            if kind.kind == 'text':
                parent[key] = payload(family, n, kind.limit)
                tags[n] = '%s:%s' % (part, path)
                n += 1
    for i in range(len(groups)):
        groups[i] = payload(family, n, 40)
        tags[n] = 'groups[%d]' % i
        n += 1
    return route, build, groups, tags


def bundle(route, build, groups, title='План проверки', uid='0a0b0c0d0e0f'):
    """Файл плана (planlib.FORMAT) из частей: тексты маршрута и билда — как их пишет программа."""
    return {'format': planlib.FORMAT, 'version': 1, 'uid': uid, 'title': title, 'groups': groups,
            'route': json.dumps(route, ensure_ascii=False, indent=2),
            'build': json.dumps(build, ensure_ascii=False, indent=2)}


def text_plans(route, build, groups):
    """Пропускаемые варианты: [(набор, файл плана, имя файла, {номер: поле})] — по плану на набор TEXT, номера
    полей у всех разные. Название плана и имя файла — тоже враждебные."""
    out, start = [], 1
    for family in TEXT:
        r, b, g, tags = hostile_text(route, build, groups, family, start)
        start += len(tags) + 3
        title_tag, file_tag = start - 2, start - 1
        tags[title_tag], tags[file_tag] = 'title', 'file'
        data = bundle(r, b, g, title=payload(family, title_tag, 120), uid='zz%s' % family[:8].lower())
        out.append((family, data, payload(family, file_tag, 100) + '.plan.json', tags))
    return out


def refused(route, build, groups):
    """Варианты, которые проверка обязана отвергнуть: [(что, путь, файл плана или текст частей)]. По одному
    изменению на вариант; поле схемы (путь без номеров записей) — один раз."""
    out, seen = [], set()

    def add(what, path, r, b, g=None, **outer):
        data = bundle(r, b, groups if g is None else g)
        data.update(outer)
        out.append((what, path, data))

    for part, check in (('route', planguard.ROUTE), ('build', planguard.BUILD)):
        value = route if part == 'route' else build
        for path, parent, key, kind, either in list(leaves(value, check)):
            g = (part, general(path), kind.kind)
            if g in seen:
                continue
            seen.add(g)
            bad = list(WRONG.get(kind.kind, []))
            if kind.kind == 'text':
                bad += ['Ж' * (kind.limit + 1)] + CTRL + ([] if kind.lines else ['x\ny', 'x\ty', 'x\ry'])
            elif kind.kind == 'pattern':
                bad += PATHS + JS + ['a' * 200, '<x-zz>', '"x"', 'x\x00']
            if either is not None:
                bad = [v for v in bad if _fails(either, v)]
            for v in bad:
                r, b = copy.deepcopy(route), copy.deepcopy(build)
                target = r if part == 'route' else b
                _put(target, check, path, v)
                add('%s=%r' % (kind.kind, v)[:60], '%s:%s' % (part, path), r, b)
        # записи и списки: неизвестное поле, не тот тип, лишние записи, повтор id
        for path, value_, kind, either in list(shapes(value, check)):
            g = (part, general(path), kind.kind, 'shape')
            if g in seen:
                continue
            seen.add(g)
            r, b = copy.deepcopy(route), copy.deepcopy(build)
            target = r if part == 'route' else b
            if kind.kind == 'record':
                for k, v in (('zzUnknown', 1), ('<x-zz>', 'x'), ('__proto__', {'polluted': True})):
                    r2, b2 = copy.deepcopy(r), copy.deepcopy(b)
                    t2 = r2 if part == 'route' else b2
                    _get(t2, check, path)[k] = v
                    add('unknown=%s' % k, '%s:%s' % (part, path), r2, b2)
                for v in WRONG['record']:
                    if path and (either is None or _fails(either, v)):
                        r2, b2 = copy.deepcopy(r), copy.deepcopy(b)
                        _put(r2 if part == 'route' else b2, check, path, v)
                        add('record=%r' % (v,), '%s:%s' % (part, path), r2, b2)
            elif kind.kind == 'items':
                items = _get(target, check, path)
                if items:
                    _put(target, check, path, items + [copy.deepcopy(items[-1]) for _ in range(kind.limit + 1 - len(items))])
                    add('many>%d' % kind.limit, '%s:%s' % (part, path), r, b)
                    if kind.unique is not None and len(items) >= 1:
                        r2, b2 = copy.deepcopy(route), copy.deepcopy(build)
                        t2 = r2 if part == 'route' else b2
                        lst = _get(t2, check, path)
                        lst.append(copy.deepcopy(lst[0]))
                        add('dup', '%s:%s' % (part, path), r2, b2)
                for v in WRONG['items']:
                    if either is not None and not _fails(either, v):
                        continue
                    r2, b2 = copy.deepcopy(route), copy.deepcopy(build)
                    _put(r2 if part == 'route' else b2, check, path, v)
                    add('items=%r' % (v,), '%s:%s' % (part, path), r2, b2)
            elif kind.kind == 'mapping':
                r2, b2 = copy.deepcopy(route), copy.deepcopy(build)
                m = _get(r2 if part == 'route' else b2, check, path)
                for i in range(kind.limit + 1):
                    m['k%d' % i] = 1
                add('many>%d' % kind.limit, '%s:%s' % (part, path), r2, b2)
                r2, b2 = copy.deepcopy(route), copy.deepcopy(build)
                m = _get(r2 if part == 'route' else b2, check, path)
                m['__proto__'] = 1
                add('key=__proto__', '%s:%s' % (part, path), r2, b2)
    # цель маршрута и цель билда с одним id
    r, b = copy.deepcopy(route), copy.deepcopy(build)
    b['goals'].append(dict(b['goals'][0], id=r['goals'][0]['id']))
    add('dup route/build goal', 'build:goals', r, b)
    # глубокая вложенность в поле, которое ждёт текст
    r, b = copy.deepcopy(route), copy.deepcopy(build)
    deep = 'x'
    for _ in range(planguard.MAX_DEPTH + 2):
        deep = [deep]
    r['steps'][0]['name'] = deep
    add('deep', 'route:steps[0].name', r, b)
    # части файла не по правилам JSON: NaN, Infinity, повтор ключа, очень глубокая вложенность, огромное число
    text_r = json.dumps(route, ensure_ascii=False)
    for what, t in (('NaN', text_r.replace('"version": 1', '"version": NaN', 1)),
                    ('Infinity', text_r.replace('"version": 1', '"version": Infinity', 1)),
                    ('-Infinity', text_r.replace('"version": 1', '"version": -Infinity', 1)),
                    ('dupkey', text_r.replace('"version": 1', '"version": 1, "version": 1', 1)),
                    ('deep100k', '{"steps": ' + '[' * 100000 + ']' * 100000 + '}'),
                    ('bigint', text_r.replace('"version": 1', '"version": 1' + '0' * 5000, 1)),
                    ('1e999', text_r.replace('"version": 1', '"version": 1e999', 1)),
                    ('not json', '{"steps": [}'), ('list', '[]'), ('empty', ' ')):
        data = bundle(route, build, groups)
        data['route'] = t
        out.append((what, 'route', data))
    # файл плана целиком: не тот формат, версия, части, название, группы
    good = bundle(route, build, groups)
    outer = [('format', {'format': 'x'}), ('format', {'format': None}), ('version', {'version': 2}),
             ('version', {'version': '1'}), ('version', {'version': True}), ('version', {'version': None}),
             ('route', {'route': None}), ('route', {'route': 5}), ('route', {'route': 'x' * (planlib.MAX_TEXT + 1)}),
             ('build', {'build': []}), ('title', {'title': 5}), ('title', {'title': 'x\u202ey'}),
             ('title', {'title': 'Ж' * 201}), ('groups', {'groups': 'x'}), ('groups', {'groups': [1]}),
             ('groups', {'groups': ['x'] * 2}), ('groups', {'groups': ['g%d' % i for i in range(41)]}),
             ('groups', {'groups': ['Ж' * 41]}), ('groups', {'groups': ['x\x00']})]
    for what, change in outer:
        out.append(('outer ' + what, 'bundle', dict(good, **change)))
    out.append(('not a dict', 'bundle', ['format']))
    return out


def _fails(check, value):
    found = []
    check(value, '', found)
    return bool(found)


def _steps_of(path):
    return re.findall(r'\.?([A-Za-z_][A-Za-z0-9_+%-]*)|\[(\d+)\]', path)


def _get(root, check, path):
    """Значение по пути (steps[3].touch[0]) — словарь или список внутри root."""
    cur = root
    for name, idx in _steps_of(path):
        cur = cur[int(idx)] if idx else cur[name]
    return cur


def _put(root, check, path, value):
    parts = _steps_of(path)
    cur = root
    for name, idx in parts[:-1]:
        cur = cur[int(idx)] if idx else cur[name]
    name, idx = parts[-1]
    if idx:
        cur[int(idx)] = value
    else:
        cur[name] = value
