# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Sergei Labutin
# Additional terms under GPL-3.0 section 7: see NOTICE.md
"""Хватит ли герою атрибутов на то, что билд называет: камни умений и вещи.

Требование возникает там, где автор билда что-то называет: «Морозная бомба, камень 9-го уровня к такому-то
шагу», «Ростовой щит с такого-то шага». Там о нехватке и сказано — у самого камня и у самой вещи на странице
«Билд» — и ещё раз общим списком в проверке билда (вкладка «Билд»). Этап билда об этом не знает ничего: он называет
дерево и то, какие атрибуты считать на вещах, а кто потом этим пользуется — не его дело.

Что требуется (данные игры):

  камень умения — по уровню камня (правила каталога gemAttr: требование по доле атрибута у камня). Уровень —
                  стартовый у самого умения (gemFrom) и названный у ступени «уровень N к шагу». У камней
                  поддержки требований нет; умение, которое даёт вещь, требует столько же, сколько вещь;
  вещь          — требование названной базы.

Что есть у героя на шаге — по плану, не по забегу:

  класс  — атрибуты класса, названного билдом (раздел hero); класс не назван — класса узла старта, от
           которого растёт дерево;
  дерево — версия дерева этапа, действующего на шаге, ЦЕЛИКОМ — какой она станет к концу этапа: узлы
           «Характеристика» с назначенным атрибутом, «+N к силе», «+N ко всем атрибутам», «N% повышение»;
           узел «на N% меньше требований» уменьшает само требование;
  вещи   — атрибуты, запланированные на вещах: цели по стату-атрибуту («Сила от 40» на поясе) со сроком
           не позже шага — на вещи, которая на этом шаге в ходу.

Когда проверяется: на шаге, с которого требование действует (срок цели или шаг, с которого её вещь или
камень в ходу, — что позже), и на первом шаге каждого следующего этапа, пока цель в ходу: со сменой дерева
и вещей атрибут может уйти (на картах сила с дерева уходит, а сапоги с требованием силы остались). Говорится
о первом месте, где не хватило.
"""
import math
import re

import buildplan
import buildstage
import core
import herostats
import treeplan
from i18n import tr
import i18n

ATTRS = treeplan.ATTRS
ATTR_WORDS = treeplan.ATTR_WORDS
RE_ANY = re.compile(r'\+(\d+) to any Attribute')
RE_FLAT = re.compile(r'\+(\d+) to (Strength|Dexterity|Intelligence)(?: and (Strength|Dexterity|Intelligence))?')
RE_ALL = re.compile(r'\+(\d+) to all Attributes')
RE_INC = re.compile(r'(\d+)% increased (Strength|Dexterity|Intelligence|Attributes)')
RE_EASE = re.compile(r'Equipment and Skill Gems have (\d+)% reduced Attribute Requirements')
# строки, которые меняют атрибуты или требования, но расчёту не по силам: о них страница скажет словами
RE_ODD = re.compile(r'Attribute Requirements|Requirements of|less Attributes|increased (?:Strength|Dexterity|Intelligence|Attributes)'
                    r'|Attribute Passive Skills|bonuses gained from Attributes')
RE_ENGLISH = re.compile(r'\(([^()]*)\)')


def attr_id(word):
    """Атрибут, как бы он ни был записан: «int», «Intelligence», «инт» -> 'int'. Не атрибут — None."""
    return treeplan.attr_id(word)


def english(title):
    """Английское имя из названия цели: «Гремящий скипетр (Rattling Sceptre): жёлтый» -> «Rattling Sceptre»."""
    found = RE_ENGLISH.findall(title or '')
    return (found[-1] if found else title or '').strip()


# --- что даёт дерево ---------------------------------------------------------------------------------

def tree_gives(nodes, lines, default=None):
    """Что даёт версия дерева. nodes — её узлы ([{id, name?, attr?}]), lines — строки узлов из данных GGG
    ({id: [строка]}), default — атрибут по умолчанию для узлов «Характеристика». Возвращает:
      flat — {атрибут: сколько прибавлено числом};
      inc  — {атрибут: на сколько процентов повышен};
      ease — на сколько процентов снижены требования вещей и камней;
      free — сколько узлов «Характеристика» без выбранного атрибута (ничего не дали);
      odd  — [(узел, строка)]: строки об атрибутах и требованиях, которых расчёт не понимает."""
    flat, inc = {a: 0 for a in ATTRS}, {a: 0 for a in ATTRS}
    ease, free, odd = 0, 0, []
    for n in nodes or []:
        for ln in (lines or {}).get(n.get('id')) or []:
            m = RE_ANY.fullmatch(ln)
            if m:
                a = attr_id(n.get('attr')) or attr_id(default)
                if a:
                    flat[a] += int(m.group(1))
                else:
                    free += 1
                continue
            m = RE_FLAT.fullmatch(ln)
            if m:
                for word in (m.group(2), m.group(3)):
                    if word:
                        flat[attr_id(word)] += int(m.group(1))
                continue
            m = RE_ALL.fullmatch(ln)
            if m:
                for a in flat:
                    flat[a] += int(m.group(1))
                continue
            m = RE_INC.fullmatch(ln)
            if m:
                for a in ([attr_id(m.group(2))] if attr_id(m.group(2)) else list(inc)):
                    inc[a] += int(m.group(1))
                continue
            m = RE_EASE.fullmatch(ln)
            if m:
                ease += int(m.group(1))
                continue
            if RE_ODD.search(ln):
                odd.append((n.get('name') or n.get('id'), ln))
    return {'flat': flat, 'inc': inc, 'ease': ease, 'free': free, 'odd': odd}


def class_start(nodes, geo):
    """Узел старта класса, от которого растёт версия дерева: старт, с которым соседствует её узел (версия
    идёт от старта). None — версия пуста или в данных дерева стартов нет."""
    starts, near = (geo or {}).get('starts') or {}, (geo or {}).get('near') or {}
    for n in nodes or []:
        for s in sorted(near.get(n.get('id')) or ()):
            if s in starts:
                return s
    return None


def class_base(plan, geo, nodes=None):
    """Атрибуты класса героя: ({атрибут: число}, откуда они). Откуда: 'hero' — класс назван билдом (раздел
    hero) и есть в данных дерева; 'tree' — билд класса не назвал, взят класс узла старта, от которого растёт
    версия дерева (nodes — её узлы); None — узнать не из чего, атрибуты класса — нули."""
    classes = (geo or {}).get('classes') or {}
    cls = (plan.get('hero') or {}).get('class')
    if cls in classes:
        return dict(zip(ATTRS, classes[cls]['base'])), 'hero'
    base = ((geo or {}).get('starts') or {}).get(class_start(nodes, geo))
    if base:
        return dict(zip(ATTRS, base)), 'tree'
    return {a: 0 for a in ATTRS}, None


# --- что требуется -----------------------------------------------------------------------------------

def gem_weights(cat, title):
    """Доли атрибутов в требованиях камня умения по названию цели («Русское (English)»): {атрибут: доля}.
    {} — у умения требований нет; None — такого камня в данных игры нет. Имя камня с местом для слова
    («Spectre: {0}») подходит к любому такому названию."""
    name, found = english(title), None
    for g in ((cat or {}).get('gems') or {}).values():
        if g.get('type') == 'support':
            continue
        own = g.get('name') or ''
        same = own == name or ('{0}' in own and re.fullmatch(re.escape(own).replace(r'\{0\}', '.+'), name))
        if same:
            found = found or {}
            for a, share in (g.get('req') or {}).items():
                found[a] = max(found.get(a, 0), share)
    return found


def gem_need(rules, weights, level):
    """Требования камня умения такого уровня: {атрибут: число}. None — для такой доли атрибута таблицы нет.
    Выше последнего уровня таблицы требования не растут."""
    table, out = rules.get('gemAttr') or {}, {}
    for a, share in (weights or {}).items():
        row = table.get(str(share))
        if not row or level < 1:
            return None
        out[a] = row[min(level, len(row)) - 1]
    return out


def base_need(cat, title, classes):
    """Требования названной базы вещи: {атрибут: число} (у нескольких баз с одним названием — наибольшее).
    None — базы с таким названием среди классов слота в данных игры нет."""
    name, out = english(title), None
    for b in ((cat or {}).get('bases') or {}).values():
        if b.get('name') == name and (not classes or b.get('class') in classes) and 'demigods' not in (b.get('tags') or ()):
            out = out or {}
            for a, n in (b.get('req') or {}).items():
                if a != 'level' and n:
                    out[a] = max(out.get(a, 0), n)
    return out


def _span(g, idx):
    """Шаги, на которых требование цели действует: (первый, последний). Первый — срок цели (need) или шаг,
    с которого её вещь или камень в ходу (use), — что позже; не названо ни то, ни другое — начало забега.
    Последний — шаг until; не назван — конец маршрута."""
    first = max(idx.get(g.get('need'), 0) if g.get('need') else 0, idx.get(g.get('use'), 0) if g.get('use') else 0)
    last = idx.get(g.get('until'), len(idx) - 1) if g.get('until') else len(idx) - 1
    return first, last


def sources(cat, plan):
    """Что в плане требует атрибутов: (строки, чего не знаем). Строка — {goal — id цели, tab — вкладка
    страницы «Билд» (gems / items), what — что это, at и until — номера шагов, на которых требование
    действует, need — {атрибут: число}}. «Не знаем» — [{goal, tab, what}]: камни умений с уровнем,
    которых в данных игры нет."""
    steps = plan.get('steps') or []
    idx = {s['id']: i for i, s in enumerate(steps)}
    rules = (cat or {}).get('rules') or {}
    goals = plan.get('goals') or []
    by_id = {g['id']: g for g in goals}
    slots = {s['id']: s for s in plan.get('slots') or []}
    rows, unknown, weights = [], [], {}
    if not steps:
        return rows, unknown

    def put(g, tab, what, need):
        at, until = _span(g, idx)
        if need and at <= until:
            rows.append({'goal': g['id'], 'tab': tab, 'what': what, 'at': at, 'until': until, 'need': need})

    for g in goals:
        if g.get('kind') != 'skill':
            continue
        # умение, которое даёт вещь (скипетр — приспешника), камнем не вставляют: требует вещь, а не оно
        if (by_id.get(g.get('grantedBy')) or {}).get('slot'):
            continue
        title = g.get('title') or g['id']
        w = gem_weights(cat, title)
        if w is None:
            # умение без уровня камня и без камня в данных игры — не камень вовсе (умение восхождения):
            # требований у него нет. Камень с уровнем, которого данные не знают, — «не знаем».
            if g.get('gemFrom') is not None:
                unknown.append({'goal': g['id'], 'tab': 'gems', 'what': title})
            continue
        if not w:
            continue
        weights[g['id']] = w
        if core.is_int(g.get('gemFrom')):
            need = gem_need(rules, w, g['gemFrom'])
            if need is None:
                unknown.append({'goal': g['id'], 'tab': 'gems', 'what': title})
            else:
                put(g, 'gems', tr('%s · камень %d ур.') % (title, g['gemFrom']), need)
    for g in goals:
        if g.get('kind') == 'gem' and g.get('part') == 'level' and g.get('for') in weights:
            # ступень «уровень N к шагу»: без срока её достроила программа — это не требование автора
            if not (g.get('need') in idx and str(g.get('title')).isdigit()):
                continue
            need = gem_need(rules, weights[g['for']], int(g['title']))
            if need is not None:
                put(g, 'gems', tr('%s · камень %s ур.') % (by_id[g['for']].get('title') or g['for'], g['title']), need)
        elif g.get('slot') in slots and not g.get('part') and not g.get('any') and g.get('kind') is None:
            need = base_need(cat, g.get('title'), slots[g['slot']].get('classes'))
            if need:
                put(g, 'items', g.get('title') or g['id'], need)
    return rows, unknown


# --- что есть у героя по плану -------------------------------------------------------------------------

def gear_plan(plan, idx, lines, pos):
    """Атрибуты, запланированные на вещах к шагу pos: ({атрибут: сумма}, {атрибут: сколько целей не в счёт}).
    В счёт идут цели по стату-атрибуту (slot, part, stat, min) со сроком не позже шага — на вещи, которая
    на этом шаге в слоте в ходу (её линия, см. herostats.slot_lines) и ещё не снята (until); у ступеней
    одной части берётся наибольшая. Цель без срока или со сроком позже шага в счёт не идёт: будет ли она
    к этому шагу, план не говорит, — такие сосчитаны отдельно, чтобы о них можно было сказать."""
    best, late = {}, {a: 0 for a in ATTRS}
    for g in plan.get('goals') or []:
        a = attr_id(g.get('stat'))
        if not a or not g.get('slot') or not g.get('part') or isinstance(g.get('min'), bool) \
                or not isinstance(g.get('min'), (int, float)):
            continue
        if g.get('until') in idx and idx[g['until']] < pos:
            continue
        line = g['use'] if g.get('use') in idx else None
        if herostats.line_at(lines.get(g['slot']), pos)[0] != line:
            continue
        due = idx.get(g.get('need'))
        if due is None or due > pos:
            late[a] += 1
            continue
        key = (g['slot'], g['part'], a)
        best[key] = max(best.get(key, 0), g['min'])
    out = {a: 0 for a in ATTRS}
    for (_, _, a), n in best.items():
        out[a] += n
    return out, late


def totals(base, flat, inc, gear=None):
    """Итог по каждому атрибуту: класс + прибавки дерева числом + вещи, всё вместе повышено на процент
    дерева; округление вниз."""
    return {a: int((base[a] + flat[a] + (gear or {}).get(a, 0)) * (100 + inc[a]) // 100) for a in ATTRS}


def with_items(version):
    """Узлы, которые версия дерева берёт с предметов (зачарование амулета, поле items), — записями узлов для
    tree_gives: что они дают, считается так же, как у взятых очком."""
    return [{'id': x['id']} for x in (version or {}).get('items') or [] if isinstance(x, dict) and x.get('id')]


def versions_attrs(plan, tree_lines, geo):
    """Атрибуты героя с каждой версией дерева героя, БЕЗ вещей — для вкладки «Дерево» страницы «Билд»:
    {id версии: {base — атрибуты класса, classFrom — откуда они (class_base: 'hero', 'tree' или None —
    класс узнать не из чего), tree — что дерево прибавляет числом (узлы «Характеристика» по выбранному
    атрибуту, «+N к силе», «+N ко всем атрибутам»), inc — проценты повышения, ease — процент снижения
    требований, total — итог (тот же счёт, что у hero_at, только без вещей), free — сколько узлов
    «Характеристика» без атрибута, odd — [[узел, строка]]: чего расчёт не понял}}. Версия считается
    целиком — какой она станет, когда все её узлы взяты."""
    tree = plan.get('tree') or {}
    out = {}
    for ph in tree.get('phases') or []:
        nodes = ph.get('nodes') or []
        # узлы, которые версия берёт с амулета (items), дают то же, что взятые очком
        gives = tree_gives(nodes + with_items(ph), tree_lines, tree.get('attr'))
        base, src = class_base(plan, geo, nodes)
        out[ph['id']] = {'base': base, 'classFrom': src, 'tree': gives['flat'], 'inc': gives['inc'], 'ease': gives['ease'],
                         'total': totals(base, gives['flat'], gives['inc']), 'free': gives['free'],
                         'odd': [list(x) for x in gives['odd']]}
    return out


def hero_at(plan, tree_lines, geo, pos, lines=None, idx=None):
    """Герой по плану на шаге pos: {stage — название этапа, version — название версии дерева (None — этап
    дерева не назвал), base — атрибуты класса, classFrom — откуда они (class_base), tree — прибавки дерева
    числом, gear — запланировано на вещах, gearLate — сколько целей по атрибуту на вещах в счёт не пошло
    (нет срока или он позже шага), inc — проценты повышения, ease — процент снижения требований,
    total — итог по каждому атрибуту, free и odd — чего расчёт в дереве не учёл (tree_gives)}."""
    idx = idx if idx is not None else {s['id']: i for i, s in enumerate(plan.get('steps') or [])}
    lines = lines if lines is not None else herostats.slot_lines(plan)
    st = buildstage.at(plan, pos)
    ph = buildstage.version(plan, 'tree', pos) or {}
    nodes = ph.get('nodes') or []
    gives = tree_gives(nodes + with_items(ph), tree_lines, (plan.get('tree') or {}).get('attr'))
    base, src = class_base(plan, geo, nodes)
    gear, late = gear_plan(plan, idx, lines, pos)
    total = totals(base, gives['flat'], gives['inc'], gear)
    return {'stage': (st or {}).get('name'), 'version': (ph.get('name') or ph.get('id')) if ph else None,
            'base': base, 'classFrom': src, 'tree': gives['flat'], 'gear': gear, 'gearLate': late, 'inc': gives['inc'],
            'ease': gives['ease'], 'total': total, 'free': gives['free'], 'odd': gives['odd']}


def _num(x):
    return int(x) if x == int(x) else x


def check(cat, plan, tree_lines, geo, lang='ru'):
    """Нехватка атрибутов по целям билда: (замечания, чего не знаем). Замечание — одно на цель и атрибут,
    о первом шаге, где не хватило: {kind 'attr', goal, tab, what, step — id шага, stepName, later — название
    этапа, если не хватило не сразу, а с его началом (иначе None), attr, attrName, need, have, short, text —
    одной строкой («Интеллект: нужно 92, есть 60 — не хватает 32»), detail — из чего сложилось «есть»}."""
    steps = plan.get('steps') or []
    idx = {s['id']: i for i, s in enumerate(steps)}
    rows, unknown = sources(cat, plan)
    names = {a['id']: a['name'] for a in buildplan.attributes(cat, lang)}
    lines = herostats.slot_lines(plan)
    by_step = buildstage.per_step(plan)
    starts = sorted({i for i in range(1, len(steps)) if by_step[i] != by_step[i - 1]})   # первые шаги этапов
    memo, out = {}, []

    def hero(pos):
        if pos not in memo:
            memo[pos] = hero_at(plan, tree_lines, geo, pos, lines, idx)
        return memo[pos]

    for r in rows:
        points = [r['at']] + [p for p in starts if r['at'] < p <= r['until']]
        for a in ATTRS:
            if not r['need'].get(a):
                continue
            for k, pos in enumerate(points):
                h = hero(pos)
                need = int(math.ceil(r['need'][a] * (100 - min(h['ease'], 100)) / 100.0))
                have = h['total'][a]
                if have >= need:
                    continue
                name = names.get(a) or a
                parts = [tr('класс %d') % h['base'][a],
                         tr('дерево «%s» %d') % (h['version'], h['tree'][a]) if h['version'] else tr('дерево не названо'),
                         tr('предметы по плану %s') % _num(h['gear'][a])]
                detail = i18n.join(' + ', parts)
                if h['gearLate'][a]:
                    detail += tr(' (целей по атрибуту на предметах без срока или со сроком позже шага: %d — не в счёт)') % h['gearLate'][a]
                if h['inc'][a]:
                    detail += tr(' · повышение %d%%') % h['inc'][a]
                if h['ease']:
                    detail += tr(' · требования снижены на %d%% (было %d)') % (h['ease'], r['need'][a])
                out.append({'kind': 'attr', 'goal': r['goal'], 'tab': r['tab'], 'what': r['what'],
                            'step': steps[pos]['id'], 'stepName': steps[pos].get('name') or steps[pos]['id'],
                            'later': h['stage'] if k else None, 'attr': a, 'attrName': name,
                            'need': need, 'have': have, 'short': need - have,
                            'text': tr('%s: нужно %d, есть %d — не хватает %d') % (name, need, have, need - have),
                            'detail': detail})
                break
    out.sort(key=lambda f: (idx[f['step']], f['what']))
    return out, unknown
