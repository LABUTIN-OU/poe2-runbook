# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Sergei Labutin
# Additional terms under GPL-3.0 section 7: see NOTICE.md
"""Узлы дерева героя, которые дают предметы: зачарование амулета жидкими эмоциями (Liquid Emotions).

Игра пишет такой узел строкой предмета — «Активирует Разбивающая сила» (в копии с пометкой (enchant)); лог
о зачаровании и о надевании такого предмета молчит (сверено 2026-11-20). Поэтому узел с предмета — факт
забега из памяти надетого: копия предмета и «Надеть». Узнаётся он по строке: слой языка каталога знает начало
строки и название узла по его номеру в данных игры (skill), карта дерева (tree.json, раздел anoint) — номер,
id узла, рецепт и узлы без места на дереве. Одно название бывает у двух узлов (по-русски «Несломимый» —
Unbreakable и Unbreaking): тогда узел — тот из них, что в версии дерева; иначе известно только название.

Узел с предмета очка не тратит. Узел версии в конце ветки очередь дерева брать не зовёт — и малые узлы пути,
который вёл только к нему. Узел в середине пути в очереди остаётся: ведёт ли путь от узла с предмета, в игре
не проверено, а лишнее очко безопаснее пути, который оборвётся.
"""
SMALL, START = 0, 5            # виды узлов на карте (treegeo): малый, старт класса

_CACHE = {}


def _pack(cat, geo, lang):
    """(начало строки, конец строки, {название: [id узлов]}, {id узла: название}) — на языке lang."""
    key = (id(cat), id(geo), lang)
    hit = _CACHE.get(key)
    if hit is None:
        if len(_CACHE) > 8:
            _CACHE.clear()
        nodes = ((geo or {}).get('anoint') or {}).get('nodes') or {}
        layer = ((((cat or {}).get('lang') or {}).get(lang) or {}).get('anoint')) or {}
        by_skill = {str(r[0]): nid for nid, r in nodes.items() if isinstance(r, list) and r}
        head, _, tail = (layer.get('line') or '').partition('{0}')
        ids, names = {}, {}
        for skill, text in (layer.get('nodes') or {}).items():
            nid = by_skill.get(str(skill))
            if nid and text:
                ids.setdefault(text, []).append(nid)
                names[nid] = text
        hit = _CACHE[key] = (head, tail, ids, names)
    return hit


def on_item(cat, geo, item):
    """Узлы, которые даёт предмет: [{'name': название из строки предмета, 'ids': [id узлов с таким названием]}].
    Строка, похожая на «Активирует …», но с названием, которого среди узлов зачарования нет, не берётся."""
    if not isinstance(item, dict):
        return []
    head, tail, ids, _ = _pack(cat, geo, item.get('lang') or 'en')
    if not head and not tail:
        return []
    lines = [ln for m in item.get('mods') or [] for ln in m.get('lines') or []]
    lines += [p.get('text') or '' for p in item.get('plain') or []]
    out = []
    for ln in lines:
        if not (ln.startswith(head) and ln.endswith(tail) and len(ln) > len(head) + len(tail)):
            continue
        name = ln[len(head):len(ln) - len(tail)].strip()
        if ids.get(name) and all(a['name'] != name for a in out):
            out.append({'name': name, 'ids': list(ids[name])})
    return out


def is_amulet(item):
    return isinstance(item, dict) and (item.get('cls_id') == 'Amulet' or 'amulet' in (item.get('tags') or ()))


def worn_nodes(cat, geo, worn, keys):
    """Узлы с предметов, которые герой носит (keys — их места в памяти надетого):
    [{'name', 'ids', 'key' — место, 'amulet' — предмет амулет}]."""
    out = []
    for key in keys:
        entry = (worn or {}).get(key)
        item = entry.get('item') if isinstance(entry, dict) else None
        for a in on_item(cat, geo, item):
            out.append(dict(a, key=key, amulet=is_amulet(item)))
    return out


def pick(ids, wanted):
    """Какой это узел: единственный с таким названием — он; из нескольких — тот, что в версии дерева (wanted),
    если такой один; иначе None — на карте его не отметить."""
    if len(ids) == 1:
        return ids[0]
    mine = [i for i in ids if i in wanted]
    return mine[0] if len(mine) == 1 else None


def _reach(keep, starts, near):
    """Узлы keep, до которых есть путь от старта класса по узлам keep."""
    seen = {s for s in starts if s in keep}
    stack = list(seen)
    while stack:
        for y in near.get(stack.pop()) or ():
            if y in keep and y not in seen:
                seen.add(y)
                stack.append(y)
    return seen


def spare(order, had, taken, geo):
    """Что из версии дерева брать очком больше не нужно из-за узлов с предметов: {узел с предмета: {он сам и малые
    узлы пути, который вёл только к нему}}. order — id узлов версии, had — узлы с предметов, taken — взятые очком.
    Узел, без которого путь к другим узлам версии обрывается, сюда не идёт: очко на него план тратит."""
    near = (geo or {}).get('near') or {}
    kind = (geo or {}).get('kind') or {}
    want = set(order)
    starts = {i for i, k in kind.items() if k == START}
    keep = want | starts
    out, cut = {}, set()
    for a in sorted(had):
        if a not in want or a in taken:
            continue
        rest = keep - cut - {a}
        if not (want - cut - {a}) <= _reach(rest, starts, near):
            continue
        mine = {a}
        cut.add(a)
        edge = set(near.get(a) or ()) & keep
        changed = True
        while changed:
            changed = False
            for x in sorted(edge - cut):
                if x not in want or x in taken or kind.get(x) != SMALL:
                    continue
                if len(set(near.get(x) or ()) & (keep - cut)) <= 1:
                    mine.add(x)
                    cut.add(x)
                    edge |= set(near.get(x) or ()) & keep
                    changed = True
        out[a] = mine
    return out


def emotion_names(cat, geo, lang):
    """Эмоции карты дерева (id GGG, «LiquidEnvy») названиями предметов на языке lang («Жидкая зависть»).
    Название ищется среди баз каталога: id — то же английское название без пробелов."""
    bases = (((cat or {}).get('lang') or {}).get(lang) or {}).get('bases') or {}
    english = {en.replace(' ', ''): en for en in bases}
    out = []
    for e in ((geo or {}).get('anoint') or {}).get('emotions') or []:
        en = english.get(e)
        out.append(bases.get(en) or en or e)
    return out


def emotion_drops(cat, geo):
    """С какого уровня зоны падает каждая эмоция карты дерева (каталог: emotions — английское название -> уровень)
    — список по номерам эмоций; эмоция, которой каталог не знает, — 1."""
    by = {en.replace(' ', ''): lv for en, lv in ((cat or {}).get('emotions') or {}).items()}
    return [by.get(e) or 1 for e in ((geo or {}).get('anoint') or {}).get('emotions') or []]


def available_from(cat, geo, nid):
    """С какого уровня зоны падают все три эмоции рецепта узла (самая поздняя из них); узла нет — None."""
    row = (((geo or {}).get('anoint') or {}).get('nodes') or {}).get(nid)
    if not isinstance(row, list) or len(row) < 2:
        return None
    drops = emotion_drops(cat, geo)
    return max((drops[i] for i in row[1] if isinstance(i, int) and 0 <= i < len(drops)), default=None)


def recipe(cat, geo, nid, lang):
    """Чем узел зачаровать: три эмоции по порядку, названиями на языке lang; узла нет — []."""
    row = (((geo or {}).get('anoint') or {}).get('nodes') or {}).get(nid)
    if not isinstance(row, list) or len(row) < 2:
        return []
    names = emotion_names(cat, geo, lang)
    return [names[i] for i in row[1] if isinstance(i, int) and 0 <= i < len(names)]


def name_of(cat, geo, nid, lang, fallback):
    """Название узла на языке lang (слой языка каталога), иначе — как его написал предмет."""
    return _pack(cat, geo, lang)[3].get(nid) or fallback


def describe(cat, geo, item, lang):
    """Узлы предмета для карточки копии: [{'name', 'recipe'}] — на языке lang."""
    out = []
    for a in on_item(cat, geo, item):
        nid = a['ids'][0] if len(a['ids']) == 1 else None
        out.append({'name': name_of(cat, geo, nid, lang, a['name']) if nid else a['name'],
                    'recipe': recipe(cat, geo, nid, lang) if nid else []})
    return out


def amulet_slots(cat, plan):
    """Слоты билда, в которых носят амулет (класс игры Amulet; в старых файлах — словом клиента «Амулеты»)."""
    words = (((cat or {}).get('lang') or {}).get('ru') or {}).get('classes') or {}
    return {s['id'] for s in (plan or {}).get('slots') or [] if isinstance(s, dict) and s.get('id')
            and any(c == 'Amulet' or words.get(c) == 'Amulet' for c in s.get('classes') or ())}


def choices(cat, geo, lang):
    """Из чего выбирать узел с амулета в версии дерева (страница «Билд»): {emotions: [названия эмоций на языке
    lang], potent: [номера густых эмоций], nodes: [[id, название, английское название, [номера эмоций рецепта],
    1 — места на дереве нет]]}, по названию."""
    an = (geo or {}).get('anoint') or {}
    names, en = _pack(cat, geo, lang)[3], _pack(cat, geo, 'en')[3]
    rows = []
    for nid, row in (an.get('nodes') or {}).items():
        english = en.get(nid) or (row[2] if len(row) > 2 else nid)
        rows.append([nid, names.get(nid) or english, english, row[1], 1 if len(row) > 2 else 0])
    rows.sort(key=lambda r: r[1].lower())
    # густые эмоции (Potent): редкие, их нет в цепочке улучшения на верстаке — id GGG начинается с Potent
    potent = [i for i, e in enumerate(an.get('emotions') or []) if str(e).startswith('Potent')]
    return {'emotions': emotion_names(cat, geo, lang), 'potent': potent, 'drops': emotion_drops(cat, geo), 'nodes': rows}


# Узел атласа, с которым густые эмоции падают с уникальных монстров в тумане Делириума («Тебе меня больше не напугать!»,
# You can't scare me anymore!; данные атласа 0.5, AtlasDeliriumNotable17)
POTENT_ATLAS = 'AtlasDeliriumNotable17'


def potent_atlas(geo, lang):
    """Тот узел атласа: {id, name} — название из карты атласа на языке lang; в данных атласа его нет — None."""
    name = ((geo or {}).get('name' if lang == 'ru' else 'en') or {}).get(POTENT_ATLAS)
    return {'id': POTENT_ATLAS, 'name': name} if name else None


def view(found, tree, skip, cat, geo, lang, slot_names=None, amulets=()):
    """Строки блока «Дерево» об узлах с предметов. found — worn_nodes, tree — дерево в состоянии страницы
    (core.derive; items — узлы, которые версия берёт с предметов), skip — spare. Строка: id (узел на карте;
    None — места нет или узел не узнать), name, slot, amulet и state: item — по плану и уже на предмете;
    todo — по плану, на предмете ещё нет (recipe — чем зачаровать); out — нет в плане дерева; plan — в пути
    версии, очко не нужно (saves — сколько очков сберегает); path — в пути, но путь идёт через него (очко
    нужно); took — уже взят очком."""
    order = [n['id'] for n in tree.get('plan') or []]
    wanted, taken = set(order), set(tree.get('have') or ())
    items = {x['id']: x for x in tree.get('items') or [] if isinstance(x, dict) and x.get('id')}
    # версия этапа ждёт своих узлов с предметов (пока действует запасная): её узлы — тоже по плану; у недостающего
    # строка говорит, на какую версию дерево перейдёт, когда узел будет на предмете (then)
    target = tree.get('target') or {}
    then = {}
    for x in target.get('items') or []:
        if isinstance(x, dict) and x.get('id') and x['id'] not in items:
            items[x['id']] = x
            then[x['id']] = target.get('name')
    kinds = (geo or {}).get('kind') or {}
    out, got = [], set()
    for a in found:
        nid = pick(a['ids'], wanted | set(items))
        got.add(nid)
        state = ('took' if nid in taken else 'item' if nid in items else 'out' if nid not in wanted
                 else 'plan' if nid in skip else 'path') if nid else 'out'
        row = {'id': nid if nid in kinds else None,
               'name': name_of(cat, geo, nid, lang, a['name']) if nid else a['name'],
               'slot': (slot_names or {}).get(a['key'].split('/')[0]) or a['key'], 'amulet': a['amulet'],
               'state': state}
        if nid and state != 'took':
            row['node'] = nid       # узел на надетом предмете: его атрибуты идут герою (у взятого очком — уже идут)
        if state == 'plan':
            row['saves'] = len([i for i in skip[nid] if i not in taken])
        out.append(row)
    for nid, x in items.items():
        if nid in got or nid in taken:
            continue
        row = {'id': nid if nid in kinds else None, 'name': name_of(cat, geo, nid, lang, x.get('name') or nid),
               'slot': (slot_names or {}).get(x.get('slot')) or x.get('slot'), 'amulet': x.get('slot') in amulets,
               'state': 'todo', 'recipe': recipe(cat, geo, nid, lang)}
        if then.get(nid):
            row['then'] = then[nid]
        lv = available_from(cat, geo, nid)
        if lv and lv > 1:
            row['from'] = lv        # раньше этого уровня зоны эмоций рецепта не найти — зачаровать нечем
        out.append(row)
    return out
