# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Sergei Labutin
# Additional terms under GPL-3.0 section 7: see NOTICE.md
"""Путевой камень из буфера обмена: насколько он опасен.

Игрок наводит на путевой камень и копирует его (Ctrl+C или Ctrl+Alt+C). Плана для ответа не нужно:
каждое свойство камня стоит сколько-то очков опасности (база знаний knowledge/waystones.json; у свойств
с числом очки растут вместе с числом на камне), очки складываются, и сумма даёт ступень — легко, сносно,
тяжело, смертельно. Куда какой камень потратить (на босса — лёгкий, на простую карту — тяжёлый), решает
игрок. Ответ — одно слово и строки свойств, опасные сверху, у каждой её очки. Рядом — справка о тире:
не теряется ли на нём опыт и какого уровня неогранённые камни умений с него падают.

Вещь узнаётся по данным игры (каталог, часть waystones): тир — по названию базы на языке клиента,
аффикс — по строке текста, за которой стоит его семейство в игре. Строка, которой в каталоге нет
(осквернённый аффикс, зачарование Делириума, новый патч), показывается как неопознанная и никогда —
как безопасная.

Копия с камня (русский клиент, 2026-11-15):

    Класс предмета: Путевые камни
    Редкость: Редкий
    Тайный гамбит
    Путевой камень (Ур. 4)
    --------
    Доступно возрождений: 2 (augmented)
    Шанс выпадения путевого камня: +65% (augmented)
    --------
    Уровень предмета: 69
    --------
    { Префикс "Пробивающий" (Уровень: 1) }
    Урон монстров пробивает 8(6-8)% сопротивлений стихиям
    { Суффикс "шока" (Уровень: 1) }
    Область содержит участки заряженной земли — Неизменяемое значение
    --------
    Можно использовать в Машине картоходца, чтобы войти на карту. Путевые камни одноразовые.

Блок над аффиксами — сумма того, чем игра платит за каждый аффикс; сам по себе он не читается.
"""
import json
import re
from pathlib import Path
from i18n import tr

# ступени опасности по возрастанию и сумма очков, с которой каждая начинается, если база знаний молчит
LEVELS = ('easy', 'fair', 'hard', 'deadly')
LEVEL_FROM = {'fair': 2, 'hard': 5, 'deadly': 8}
# пометки в конце строки, с которыми строка — аффикс, даже если она стоит отдельной секцией
MOD_MARKS = ('desecrated', 'fractured', 'crafted')
RE_TIER = re.compile(r'\(\D*?(\d+)\)\s*$')
RE_SIGN = re.compile(r'[+\-−]#')
# Доля уровней неогранённых камней умений в зоне: нижний, средний, верхний из тех, что там падают
GEM_SHARE = (tr('чаще'), tr('реже'), tr('редко'))


def norm(shape):
    """Форма строки без знака перед числом: «-#% максимум…» и «#% максимум…» — одна строка."""
    return RE_SIGN.sub('#', shape or '').strip()


def _points_ok(spec):
    """Очки свойства записаны верно: число от нуля или список [до какого числа на камне, очки]."""
    one = lambda x: isinstance(x, (int, float)) and not isinstance(x, bool) and x >= 0   # noqa: E731
    if one(spec):
        return True
    return (isinstance(spec, list) and bool(spec)
            and all(isinstance(r, list) and len(r) == 2 and one(r[0]) and one(r[1]) for r in spec))


def points_of(spec, value):
    """Очки свойства по числу на камне. spec — число или список [до какого числа, очки] по возрастанию;
    числа на камне нет (не прочитано) — наибольшие очки: неизвестное не считается безопасным."""
    if not isinstance(spec, list):
        return spec
    if value is None:
        return max(p for _, p in spec)
    v = abs(value)
    for upto, pts in spec:
        if v <= upto:
            return pts
    return spec[-1][1]


def load_knowledge(path, cat=None):
    """База знаний об опасности свойств камня и замечания к ней: (словарь или None, [строки]).

    В файле: mods — семейство -> points (очки опасности: число или список [до какого числа на камне,
    очки]), off — черта героя, при которой свойство не действует, why — почему; levels — с какой суммы
    очков начинается ступень (fair, hard, deadly); traits — черты героя: узел дерева, по которому черта
    узнаётся, и её название. Свойство, которого нет в данных игры, и свойство игры без очков —
    замечания: после патча список не должен молча разойтись с игрой.
    """
    try:
        raw = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    except OSError:
        return None, [tr('Путевые камни: нет файла базы знаний %s') % path]
    except ValueError as e:
        return None, [tr('Путевые камни: база знаний не прочитана: %s') % e]
    mods = raw.get('mods') if isinstance(raw, dict) else None
    if not isinstance(mods, dict):
        return None, [tr('Путевые камни: в базе знаний нет списка mods')]
    problems, clean = [], {}
    traits = {k: {'node': t['node'], 'name': t.get('name') or k}
              for k, t in (raw.get('traits') if isinstance(raw.get('traits'), dict) else {}).items()
              if isinstance(t, dict) and isinstance(t.get('node'), str)}
    for fam, k in mods.items():
        if not isinstance(k, dict) or not _points_ok(k.get('points')):
            problems.append(tr('Путевые камни: у свойства %s нет очков опасности (points)') % fam)
            continue
        if k.get('off') is not None and k['off'] not in traits:
            problems.append(tr('Путевые камни: у свойства %s названа черта «%s», которой нет в traits') % (fam, k['off']))
            continue
        clean[fam] = {'points': k['points'], 'off': k.get('off'), 'why': k['why'] if isinstance(k.get('why'), str) else ''}
    known = ((cat or {}).get('waystones') or {}).get('mods') or {}
    if known:
        problems += [tr('Путевые камни: свойства %s нет в данных игры') % f for f in clean if f not in known]
        problems += [tr('Путевые камни: свойству %s не заданы очки опасности') % f for f in known if f not in clean]
    given = raw.get('levels') if isinstance(raw.get('levels'), dict) else {}
    levels = {k: given[k] if isinstance(given.get(k), (int, float)) and not isinstance(given.get(k), bool) else v
              for k, v in LEVEL_FROM.items()}
    if not levels['fair'] <= levels['hard'] <= levels['deadly']:
        problems.append(tr('Путевые камни: ступени (levels) должны идти по возрастанию: fair, hard, deadly'))
        levels = dict(LEVEL_FROM)
    return {'mods': clean, 'levels': levels, 'traits': traits}, problems


def hero_traits(know, taken):
    """Черты героя, от которых зависят очки свойств: те, чей узел дерева герой взял. taken — id взятых узлов."""
    taken = set(taken or ())
    return {k for k, t in ((know or {}).get('traits') or {}).items() if t['node'] in taken}


def tier_of(cat, item):
    """Тир путевого камня по названию базы на языке клиента; None — это не путевой камень."""
    tiers = ((cat or {}).get('waystones') or {}).get('tiers') or {}
    pack = ((cat or {}).get('lang') or {}).get(item.get('lang')) or {}
    names = pack.get('bases') or {}
    text = ' '.join(x for x in (item.get('name'), item.get('base')) if x).lower()
    best = None
    for n, t in tiers.items():
        local = (names.get(t['name']) or '').lower()
        if local and local in text and (best is None or len(local) > best[1]):
            best = (n, len(local))
    if best:
        return int(best[0])
    # названия в слое языка нет: класс предмета говорит «путевой камень», тир — число в скобках
    if (pack.get('classes') or {}).get(item.get('cls')) == 'Map':
        m = RE_TIER.search(item.get('base') or '')
        if m and m.group(1) in tiers:
            return int(m.group(1))
    return None


def index(cat, lang):
    """Строка аффикса (форма без чисел и знаков) -> (семейство, номер строки в нём)."""
    texts = ((cat.get('lang') or {}).get(lang) or {}).get('stats') or {}
    out = {}
    for fam, f in ((cat.get('waystones') or {}).get('mods') or {}).items():
        for i, key in enumerate(f.get('lines') or []):
            for sh in texts.get(key) or []:
                out.setdefault(norm(sh), (fam, i))
    return out


def read(cat, item):
    """Путевой камень из разобранной копии (itemcopy.parse); None — вещь не путевой камень.

    mods — аффиксы по порядку: fam — семейство в игре (None — строка не опознана), text — строка как
    в игре, value — её первое число. blind — камень не опознан в игре, аффиксы скрыты. dark — аффиксы
    должны быть (камень волшебный или редкий), но ни одной их строки прочесть не удалось.
    """
    if not cat or not item:
        return None
    tier = tier_of(cat, item)
    if tier is None:
        return None
    t = cat['waystones']['tiers'][str(tier)]
    idx = index(cat, item.get('lang'))
    rows, by_fam = [], {}

    def add(fam, no, text, values):
        value = values[0] if values else None
        if fam is None:
            rows.append({'fam': None, 'text': text, 'value': value})
        elif fam in by_fam:
            # вторая строка того же аффикса (шанс крита и бонус крита): число берём с первой строки семейства
            if no == 0:
                by_fam[fam].update(text=text, value=value)
        else:
            by_fam[fam] = {'fam': fam, 'text': text, 'value': value, 'first': no == 0}
            rows.append(by_fam[fam])

    # копия с заголовками (Ctrl+Alt+C): каждый аффикс — свой блок строк
    for m in item.get('mods') or []:
        hits = [(idx.get(norm(sh)), text, vals) for sh, text, vals in zip(m['shapes'], m['lines'], m['values'])]
        known = [h for h in hits if h[0]]
        if known:
            for (fam, no), text, vals in known:
                add(fam, no, text, vals)
        elif m['lines']:
            add(None, 0, ' / '.join(m['lines']), (m['values'] or [[]])[0])
    # простая копия (Ctrl+C): аффиксы — строки одной секции. Секция, где опознана хоть одна строка, —
    # секция аффиксов, и всё остальное в ней — тоже аффиксы, только неизвестные. Секции без опознанных
    # строк — не аффиксы (блок платы над ними, подсказка внизу); но строка с пометкой особого аффикса
    # (осквернённый, расколотый) — аффикс, где бы она ни стояла.
    plain = item.get('plain') or []
    mod_secs = {p['sec'] for p in plain if norm(p['shape']) in idx}
    for p in plain:
        if p['sec'] in mod_secs or p.get('mark') in MOD_MARKS:
            fam, no = idx.get(norm(p['shape'])) or (None, 0)
            add(fam, no, p['text'], p['values'])
    for r in rows:
        r.pop('first', None)
    blind = not item.get('identified', True)
    dark = not blind and not rows and item.get('rarity') in ('magic', 'rare')
    return {'tier': tier, 'area': t['area'], 'band': t['band'], 'name': item.get('name'),
            'lang': item.get('lang'), 'mods': rows, 'blind': blind, 'dark': dark}


def _num(x):
    return '%g' % x


def xp_band(level):
    """На сколько уровней зона может отличаться от героя без штрафа к опыту: 3 и ещё 1 за каждые 16 уровней."""
    return 3 + level // 16


def xp_note(cat, area, hero_level):
    """Что тир камня значит для опыта героя: None — опыт идёт целиком и запас есть.

    low — зона ниже полосы без штрафа: опыт режется; from — с какого тира штрафа нет (None — такого тира
    уже не бывает: герой перерос все камни). edge — камень последний без штрафа: at — уровень героя,
    с которого штраф появится и на нём, from — с какого тира его тогда не будет. high — зона выше полосы
    (опыт тоже режется).
    Штраф — только к получаемому опыту: меньше нуля он не уходит, на добычу и очки атласа не влияет."""
    if not hero_level:
        return None
    tiers = ((cat or {}).get('waystones') or {}).get('tiers') or {}
    by_area = {t['area']: int(n) for n, t in tiers.items()}
    lowest = hero_level - xp_band(hero_level)
    if area < lowest:
        return {'state': 'low', 'from': by_area.get(lowest)}
    if area > hero_level + xp_band(hero_level):
        return {'state': 'high'}
    if area == lowest:
        at = hero_level + 1
        while at - xp_band(at) <= area and at < 100:
            at += 1
        if at - xp_band(at) > area:
            return {'state': 'edge', 'at': at, 'from': by_area.get(at - xp_band(at))}
    return None


def gem_levels(cat, area):
    """Какого уровня неогранённые камни умений падают в зоне такого уровня: [уровни по убыванию частоты]
    (правила каталога, раздел mapGems: с какого уровня зоны — от и до какого уровня). None — данных нет."""
    row = None
    for start, lo, hi in ((cat or {}).get('rules') or {}).get('mapGems') or []:
        if area >= start:
            row = (lo, hi)
    return list(range(row[0], row[1] + 1)) if row else None


def gem_needs(cat, levels):
    """Что нужно герою, чтобы пользоваться камнем умения такого уровня: {уровень камня: [уровень героя,
    интеллект для камня целиком на интеллекте]} — из правил каталога (gemHero, gemAttr)."""
    rules = (cat or {}).get('rules') or {}
    hero, attr = rules.get('gemHero') or [], (rules.get('gemAttr') or {}).get('100') or []
    return {n: [hero[n - 1] if 0 < n <= len(hero) else None, attr[n - 1] if 0 < n <= len(attr) else None]
            for n in levels or []}


def judge(cat, know, stone, hero_level=None, traits=(), lang=None):
    """Ответ по камню для страницы.

    verdict — ступень опасности: easy (легко), fair (сносно), hard (тяжело), deadly (смертельно) — по
    сумме очков свойств (score); unknown — решить нельзя: есть неопознанная строка или свойства скрыты
    (смертельная сумма уже прочитанных свойств сильнее неопознанного). rows — свойства, опасные сверху:
    pts — очки, cls — их размер для страницы (p0 — не опасно … p3 — тяжёлое, unknown — не опознано),
    label и val — короткая подпись и число, off — свойство не действует на героя (название его черты),
    why — почему. traits — черты героя (hero_traits). over — на сколько уровень зоны карты выше уровня
    героя (0 — не выше). xp — что тир значит для опыта (xp_note), gems — уровни камней умений в зоне.
    """
    packs = (cat or {}).get('lang') or {}
    labels = ((packs.get(lang) or {}).get('wayMods') or (packs.get(stone.get('lang')) or {}).get('wayMods')
              or (packs.get('ru') or {}).get('wayMods') or {})
    kmods = (know or {}).get('mods') or {}
    names = (know or {}).get('traits') or {}
    rows = []
    for m in stone['mods']:
        k = kmods.get(m['fam']) if m['fam'] else None
        label, tpl = labels.get(m['fam']) or (m['text'], '')
        row = {'fam': m['fam'], 'label': label, 'text': m['text'],
               'val': tpl.replace('#', _num(m['value'])) if tpl and m['value'] is not None else ''}
        if not k:
            row.update(pts=0, cls='unknown', off=None,
                       why=tr('свойство не опознано: прочитать самому') if not m['fam'] else tr('свойству не заданы очки опасности'))
        elif k['off'] in traits:
            # у героя есть то, от чего свойство не действует (после «Иммунитета к хаосу» — урон хаосом)
            name = names[k['off']]['name']
            row.update(pts=0, cls='p0', off=name, why=tr('не действует: у героя %s') % name)
        else:
            pts = points_of(k['points'], m['value'])
            row.update(pts=pts, cls='p0' if pts <= 0 else 'p1' if pts <= 2 else 'p2' if pts <= 4 else 'p3',
                       off=None, why=k['why'])
        rows.append(row)
    score = sum(r['pts'] for r in rows)
    levels = (know or {}).get('levels') or LEVEL_FROM
    verdict = next(lv for lv in reversed(LEVELS) if lv == 'easy' or score >= levels[lv])
    note = None
    if stone.get('blind'):
        verdict, note = 'unknown', tr('камень не опознан: свойства скрыты')
    elif stone.get('dark'):
        verdict, note = 'unknown', tr('свойства не прочитаны')
    elif verdict != 'deadly' and any(r['cls'] == 'unknown' for r in rows):
        verdict = 'unknown'
    # опасные сверху, неопознанные — выше всех; внутри равных — как на камне (сортировка устойчива)
    rows.sort(key=lambda r: -(99 if r['cls'] == 'unknown' else r['pts']))
    over = max(0, stone['area'] - hero_level) if hero_level else 0
    gems = gem_levels(cat, stone['area'])
    return {'at': stone.get('at'), 'name': stone.get('name'), 'tier': stone['tier'], 'area': stone['area'],
            'hero': hero_level or None, 'over': over, 'verdict': verdict, 'score': score, 'rows': rows,
            'note': note, 'xp': xp_note(cat, stone['area'], hero_level), 'gems': gems,
            'gemNeed': gem_needs(cat, gems)}
