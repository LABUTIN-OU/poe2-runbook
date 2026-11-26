# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Sergei Labutin
# Additional terms under GPL-3.0 section 7: see NOTICE.md
"""Что носят в слоте: периоды.

Слот — носитель: по ходу забега в нём носят то одно, то другое (оружие: до вознесения что выпало, после —
скипетр; вторая рука: сначала скипетр, потом щит). Меняют предметы по одному, и у каждого слота свой шаг смены —
поэтому «что носят» записано не в этапе билда, а в самом слоте, периодами (поле wear, по порядку шагов):

    {"id": "offhand", "name": "Вторая рука", "wear": [
        {"classes": ["Sceptre"]},
        {"from": "after-ascension", "classes": ["Shield", "Focus"], "kind": "str_armour"}]}

  from     — шаг, с которого период в ходу (нет поля — с начала забега). У слота не бывает двух периодов с одного шага;
  classes  — классы предметов, которые в этот период носят (из данных игры: «Sceptre», «Body Armour»);
  kind     — род базы защиты (str_armour, int_armour…); нет — как у этапа билда;
  until    — последний шаг периода. Обычно его нет: период длится, пока не начался следующий период слота,
             а последний — до конца забега.

Предметы и цели по стату слота принадлежат периоду полем use (= его from; нет поля — периоду «с начала забега»).
Срок «в ходу» и классы они берут у периода: своих until и gear у них нет.

Раньше того же самого в файле не было — период угадывался: цели слота с одним use, срок until повторён на каждой
из них, класс — поле gear одной из целей, а у слота — один список classes на весь забег и своё gear. Файл такого
вида по-прежнему читается (periods выводит периоды из целей), а upgrade переписывает его в новый.
"""


import re
from i18n import tr


def step_index(steps):
    """Шаги маршрута по порядку: {id шага: номер}."""
    return {s['id']: i for i, s in enumerate(steps or []) if isinstance(s, dict) and s.get('id')}


def spec_parts(spec):
    """Описание базы -> (класс, род или None): «Shield str_armour» -> ('Shield', 'str_armour')."""
    words = spec.rsplit(' ', 1) if isinstance(spec, str) else []
    if len(words) == 2 and words[1].islower() and '_' in words[1]:
        return words[0], words[1]
    return (spec if isinstance(spec, str) and spec else None), None


def stated(slot):
    """Записаны ли периоды у слота самим файлом (поле wear), а не выводятся из целей."""
    return isinstance(slot, dict) and isinstance(slot.get('wear'), list)


def _line(g, idx):
    return g['use'] if g.get('use') in idx else None


def _written(slot, idx):
    out, seen = [], set()
    for p in slot.get('wear') or []:
        if not isinstance(p, dict):
            continue
        start = p.get('from') if p.get('from') in idx else None
        if start in seen:
            continue                    # второй период с того же шага: о нём скажет проверка (problems)
        seen.add(start)
        classes = []
        for c in p.get('classes') if isinstance(p.get('classes'), list) else []:
            if isinstance(c, str) and c.strip() and c not in classes:
                classes.append(c)
        out.append({'from': start, 'classes': classes,
                    'kind': p['kind'] if isinstance(p.get('kind'), str) and p['kind'].strip() else None,
                    'until': p['until'] if p.get('until') in idx else None, 'spec': None})
    out.sort(key=lambda p: idx[p['from']] if p['from'] else -1)
    return out


def _guessed(slot, goals, idx):
    """Периоды слота, записанного по-старому: цели слота с одним use — один период; его классы называют поля
    gear целей (сначала предметы, потом цели по стату), нет ни у одной — описание самого слота (gear), нет
    и его — все классы слота. Класс слота, которого не назвал ни один период, действовал до первого из них."""
    mine = [g for g in goals if isinstance(g, dict) and g.get('slot') == slot.get('id')]
    lines = []
    for g in mine:
        if _line(g, idx) not in lines:
            lines.append(_line(g, idx))
    lines.sort(key=lambda ln: idx[ln] if ln else -1)
    own = slot.get('gear') if isinstance(slot.get('gear'), str) and slot['gear'].strip() else None
    every = [c for c in slot.get('classes') if isinstance(c, str) and c.strip()] if isinstance(slot.get('classes'), list) else []
    out = []
    for ln in lines:
        gs = [g for g in mine if _line(g, idx) == ln]
        named = [g['gear'] for part in (False, True) for g in gs
                 if bool(g.get('part')) == part and isinstance(g.get('gear'), str) and g['gear'].strip()]
        spec = named[0] if named else None
        classes = []
        for s in named:
            if spec_parts(s)[0] not in classes:
                classes.append(spec_parts(s)[0])
        kind = spec_parts(spec)[1] if spec else None
        if not classes and own:
            classes, kind = [spec_parts(own)[0]], spec_parts(own)[1]
        elif not classes:
            classes = list(every)
        untils = {g.get('until') for g in gs}
        until = untils.pop() if len(untils) == 1 else None      # срок у целей периода разный — он остаётся у них самих
        out.append({'from': ln, 'classes': classes, 'kind': kind, 'until': until if until in idx else None, 'spec': spec})
    if not out:
        if own:
            out.append({'from': None, 'classes': [spec_parts(own)[0]], 'kind': spec_parts(own)[1], 'until': None, 'spec': None})
        elif every:
            out.append({'from': None, 'classes': list(every), 'kind': None, 'until': None, 'spec': None})
    elif out[0]['from'] is not None:
        used = {c for p in out for c in p['classes']}
        left = [c for c in every if c not in used]
        if left:
            out.insert(0, {'from': None, 'classes': left, 'kind': None, 'until': None, 'spec': None})
    return out


def periods(slot, goals, idx):
    """Периоды слота по порядку шагов: [{from, classes, kind, until, ends, stated, spec}].

    from — id шага или None (с начала забега); until — срок, записанный явно; ends — последний шаг периода, как
    он действует: записанный срок, а у слота с записанными периодами — ещё и шаг перед началом следующего
    периода (None — до конца забега). stated — периоды записаны в файле (wear), а не выведены из целей.
    spec — у выведенного периода: описание базы, как его называла цель («Shield str_armour»), или None."""
    idx = idx if isinstance(idx, dict) else step_index(idx)
    own = stated(slot)
    out = _written(slot, idx) if own else _guessed(slot, goals or [], idx)
    order = sorted(idx, key=idx.get)
    for k, p in enumerate(out):
        nxt = out[k + 1]['from'] if k + 1 < len(out) else None
        p['stated'] = own
        p['ends'] = p['until'] or (order[idx[nxt] - 1] if own and nxt and idx[nxt] > 0 else None)
    return out


def period_of(slot, goals, idx, line):
    """Период слота, который начинается с шага line (None — с начала забега), или None."""
    return next((p for p in periods(slot, goals, idx) if p['from'] == line), None)


def classes_of(slot):
    """Все классы предметов, какие слот носит за забег, без повторов: у записанных периодов — их классы,
    у слота старого вида — его собственный список."""
    if not stated(slot):
        cl = slot.get('classes') if isinstance(slot, dict) else None
        return [c for c in cl if isinstance(c, str)] if isinstance(cl, list) else []
    out = []
    for p in slot['wear']:
        for c in p.get('classes') if isinstance(p, dict) and isinstance(p.get('classes'), list) else []:
            if isinstance(c, str) and c.strip() and c not in out:
                out.append(c)
    return out


def specs(cat, period):
    """Описания баз периода — по одному на класс: «Shield str_armour», «Focus». Род периода приписан классу,
    у которого базы такого рода бывают (у фокуса брони нет — он остаётся «Focus»); без каталога — первому."""
    out = []
    for k, cls in enumerate(period.get('classes') or []):
        kind = period.get('kind')
        if kind and cat and cat.get('bases'):
            fits = any(b.get('class') == cls and kind in (b.get('tags') or ()) for b in cat['bases'].values())
        else:
            fits = bool(kind) and k == 0
        out.append('%s %s' % (cls, kind) if fits else cls)
    return out


OFF_HAND = ('shield', 'focus', 'quiver')      # метки баз, которые держат только во второй руке


def hands(slots, cat):
    """Какой слот — основная рука и какой — вторая, по данным игры о классах, которые в них носят:
    {'main': id, 'off': id, 'quiver': [классы колчанов]}. Основная — слот, где бывает двуручное оружие (у всех баз
    класса метка twohand); вторая — другой слот, где носят то, что держат только во второй руке (щит, баклер,
    фокус, колчан). Пусто — данных игры нет или слоты так не различить (двуручного в плане нет вовсе)."""
    two, off, quiver = set(), set(), set()
    by = {}
    for b in ((cat or {}).get('bases') or {}).values():
        if b.get('class'):
            by.setdefault(b['class'], []).append(set(b.get('tags') or ()))
    for cls, sets in by.items():
        if all('twohand' in t for t in sets):
            two.add(cls)
        if all(t & set(OFF_HAND) for t in sets):
            off.add(cls)
        if all('quiver' in t for t in sets):
            quiver.add(cls)
    main = [s['id'] for s in slots or [] if set(classes_of(s)) & two]
    other = [s['id'] for s in slots or [] if s['id'] not in main and set(classes_of(s)) & off]
    if len(main) != 1 or len(other) != 1:
        return {}
    return {'main': main[0], 'off': other[0], 'quiver': sorted(quiver)}


def shut(pair, item, off_classes=()):
    """Закрыта ли вторая рука: в основной запомнен надетым двуручный предмет (метка twohand). pair — hands();
    item — предмет основной руки из памяти надетого; off_classes — что сейчас носят во второй руке: колчан при
    луке держат вместе с луком, такую руку лук не закрывает."""
    tags = set((item or {}).get('tags') or ())
    if not pair or 'twohand' not in tags:
        return False
    return not ('bow' in tags and set(off_classes or ()) & set(pair.get('quiver') or ()))


def _names(title):
    """Название цели вида «Русское (English): приписка» -> (русское строчными, английское); у названия не из игры
    английского нет."""
    t = title if isinstance(title, str) else ''
    m = re.match(r'^[^()]*\(([^()]*)\)', t)
    return t.split(' (', 1)[0].split(':', 1)[0].strip().lower(), (m.group(1).strip() if m else '')


def fits(goal, item):
    """Отвечает ли предмет цели-предмету: «любому» — любой, названному — тот, чья база так называется или одинакова
    с названной по данным игры (twins цели — gamedata.with_facts)."""
    if goal.get('any'):
        return True
    ru, en = _names(goal.get('title'))
    return bool((ru and ru in (item.get('base') or '').lower()) or (en and en == item.get('base_en'))
                or (item.get('base_en') and item['base_en'] in (goal.get('twins') or ())))


def same_base(a, b):
    """Называют ли две цели-предмета одну базу: одним названием или базами, одинаковыми по данным игры (twins)."""
    na, nb = _names(a.get('title')), _names(b.get('title'))
    return bool(na[0]) and (na == nb or (nb[1] and nb[1] in (a.get('twins') or ()))
                            or (na[1] and na[1] in (b.get('twins') or ())))


def _moves(plan):
    """Периоды, в которые что-то может перейти: [(номер шага начала, слот, период, его цели-предметы)] по порядку
    шагов, и функция «период слота в ходу на шаге»."""
    idx = step_index(plan.get('steps'))
    goals = [g for g in plan.get('goals') or [] if isinstance(g, dict)]
    slots = [s for s in plan.get('slots') or [] if isinstance(s, dict) and s.get('id')]
    pers = {s['id']: periods(s, goals, idx) for s in slots}
    at = lambda p: idx[p['from']] if p['from'] else -1          # noqa: E731

    def in_use(sid, n):
        live = [p for p in pers[sid] if at(p) <= n]
        return live[-1] if live else None

    targets = []
    for k, s in enumerate(slots):
        for per in pers[s['id']]:
            wanted = [g for g in goals if g.get('slot') == s['id'] and not g.get('part') and _line(g, idx) == per['from']]
            if per['from'] and wanted:
                targets.append((at(per), k, s['id'], per, wanted))
    targets.sort(key=lambda x: x[:2])
    return [(a, sid, per, wanted) for a, _, sid, per, wanted in targets], [s['id'] for s in slots], in_use, goals, idx


def settle(plan, worn, pos):
    """Где в памяти надетого лежит предмет каждого слота: {слот: место}. Слот помнит один предмет — тот, что на герое
    надет (место «слот/»: herostats.worn_key); периоды слота говорят только, что в нём ждёт план.

    Запись прежнего вида — место слота по периоду («weapon/after-ascension»: предмет, отмеченный надетым после смены
    периода, или положенный в рюкзак до неё) — читается так: период уже начался (pos — номер текущего шага) — предмет
    был надет; ещё нет — он лежал в рюкзаке и надетым не считается. Из надетых записей слота берётся последняя по
    времени отметки (at). Слоты, которых в плане нет, не называются."""
    idx = step_index(plan.get('steps'))
    slots = {s['id'] for s in plan.get('slots') or [] if isinstance(s, dict) and s.get('id')}
    best = {}
    for spot, entry in (worn or {}).items():
        if not isinstance(spot, str) or '/' not in spot or not isinstance(entry, dict) or not entry.get('item'):
            continue
        sid, line = spot.split('/', 1)
        if sid not in slots or (line and line in idx and pos is not None and idx[line] > pos):
            continue
        rank = (entry.get('at') or 0, not line)
        if sid not in best or rank >= best[sid][0]:
            best[sid] = (rank, spot)
    return {sid: spot for sid, (_, spot) in best.items()}


def linked(plan):
    """То же по плану, пока предмета ещё нет: {цель-предмет позднего периода: цель-предмет, которую носят перед
    ним}. Цели называют одну базу (база из игры, не «любой»; одинаковые по данным — одна, same_base), и слот ранней
    цели к шагу поздней её отпускает: это тот же слот или в нём с этого шага период другой. Такой предмет дважды не
    ищут — он один."""
    targets, slots, in_use, goals, idx = _moves(plan)
    out = {}
    for start, sid, per, wanted in targets:
        for g in wanted:
            name = _names(g.get('title'))
            if g.get('any') or not name[0] or g['id'] in out:
                continue
            for src in [sid] + [s for s in slots if s != sid]:
                held = in_use(src, start - 1)
                if held is None or held is per:
                    continue
                # класс предмета — из тех, что носят в обоих периодах; чужой слот его отпускает, если с этого
                # шага таких классов в нём уже не носят
                common = set(held['classes']) & set(per['classes'])
                later = in_use(src, start)
                if not common or (src != sid and later is not None and common & set(later['classes'])):
                    continue
                same = [x for x in goals if x.get('slot') == src and not x.get('part') and not x.get('any')
                        and _line(x, idx) == held['from'] and same_base(x, g)]
                if same:
                    out[g['id']] = same[-1]['id']
                    break
    return out


def expand(raw):
    """План, в котором у слота с записанными периодами есть то, что из них следует и чем пользуется остальная
    программа: у слота — classes (все классы его периодов), у его целей — until (последний шаг периода).
    Слот старого вида и его цели не меняются. Исходный план не трогается; повторный вызов ничего не меняет."""
    if not isinstance(raw, dict) or not isinstance(raw.get('slots'), list):
        return raw
    if not any(stated(s) for s in raw['slots']):
        return raw
    idx = step_index(raw.get('steps'))
    goals = raw.get('goals') if isinstance(raw.get('goals'), list) else []
    slots, ends = [], {}
    for s in raw['slots']:
        if stated(s) and s.get('id'):
            pers = periods(s, goals, idx)
            s = dict(s, classes=classes_of(s))
            s.pop('gear', None)
            for p in pers:
                ends[(s['id'], p['from'])] = p['ends']
        slots.append(s)
    out = []
    for g in goals:
        key = (g.get('slot'), _line(g, idx)) if isinstance(g, dict) and g.get('slot') else None
        if key in ends:
            g = {k: v for k, v in g.items() if k != 'gear'}
            if ends[key] and not g.get('until'):
                g['until'] = ends[key]
        out.append(g)
    return dict(raw, slots=slots, goals=out)


def problems(slot, goals, idx, known=None):
    """Замечания к записанным периодам слота. known — классы предметов из данных игры: {класс: роды баз}
    (None — данных нет, классы не сверяются)."""
    out, name = [], slot.get('name') or slot.get('id')
    if not stated(slot):
        return out
    starts = []
    for p in slot['wear']:
        if not isinstance(p, dict):
            out.append(tr('Слот «%s»: период — запись {from, classes, kind}') % name)
            continue
        start = p.get('from')
        if start is not None and start not in idx:
            out.append(tr('Слот «%s»: у периода нет шага «%s»') % (name, start))
            continue
        if start in starts:
            out.append(tr('Слот «%s»: два периода с одного шага') % name)
        starts.append(start)
        cl = p.get('classes')
        if not (isinstance(cl, list) and cl and all(isinstance(c, str) and c.strip() for c in cl) and len(set(cl)) == len(cl)):
            out.append(tr('Слот «%s»: у периода нужен хотя бы один класс предметов, без повторов') % name)
        elif known is not None:
            bad = next((c for c in cl if c not in known), None)
            if bad:
                out.append(tr('Слот «%s»: класса предметов «%s» нет в данных игры') % (name, bad))
            elif p.get('kind') and not any(p['kind'] in known[c] for c in cl):
                out.append(tr('Слот «%s»: у классов периода нет баз рода «%s»') % (name, p['kind']))
        if p.get('kind') is not None and not (isinstance(p['kind'], str) and p['kind'].strip()):
            out.append(tr('Слот «%s»: род базы периода — слово из данных игры (str_armour, int_armour…)') % name)
        if p.get('until') is not None and p['until'] not in idx:
            out.append(tr('Слот «%s»: у периода нет шага «%s»') % (name, p['until']))
        elif p.get('until') and start and idx[p['until']] < idx[start]:
            out.append(tr('Слот «%s»: период кончается раньше, чем начинается') % name)
    for g in goals or []:
        if isinstance(g, dict) and g.get('slot') == slot.get('id') and _line(g, idx) not in starts:
            out.append(tr('Цель «%s»: у слота «%s» нет периода %s') % (
                g.get('title') or g.get('id'), name, tr('с шага «%s»') % g['use'] if _line(g, idx) else tr('с самого начала')))
    return out


def upgrade(build, steps):
    """Файл билда старого вида — в новом: у каждого слота периоды (wear) вместо classes и gear, у целей слотов
    нет gear, а until остаётся только там, где он не следует из периода. Файл нового вида возвращается как есть.
    steps — шаги маршрута (порядок периодов и срок «до следующего периода» считаются по ним)."""
    if not isinstance(build, dict) or not isinstance(build.get('slots'), list):
        return build
    slots_in = [s for s in build['slots'] if isinstance(s, dict) and s.get('id')]
    goals = build.get('goals') if isinstance(build.get('goals'), list) else []
    mine = {s['id'] for s in slots_in}
    if all(stated(s) for s in slots_in) and not any(isinstance(g, dict) and g.get('slot') in mine and 'gear' in g for g in goals):
        return build
    idx = step_index(steps)
    order = sorted(idx, key=idx.get)
    slots, ends = [], {}
    for s in build['slots']:
        if not (isinstance(s, dict) and s.get('id')):
            slots.append(s)
            continue
        pers = periods(s, goals, idx)
        if not stated(s):
            wear = []
            for k, p in enumerate(pers):
                nxt = pers[k + 1]['from'] if k + 1 < len(pers) else None
                derived = order[idx[nxt] - 1] if nxt and idx[nxt] > 0 else None
                rec = dict([('from', p['from'])] if p['from'] else [], classes=list(p['classes']))
                if p['kind']:
                    rec['kind'] = p['kind']
                if p['until'] and p['until'] != derived:
                    rec['until'] = p['until']
                wear.append(rec)
                ends[(s['id'], p['from'])] = p['until'] or derived
            s = dict([(k, v) for k, v in s.items() if k not in ('classes', 'gear')], wear=wear)
        else:
            for p in pers:
                ends[(s['id'], p['from'])] = p['ends']
        slots.append(s)
    out = []
    for g in goals:
        key = (g.get('slot'), _line(g, idx)) if isinstance(g, dict) and g.get('slot') else None
        if key in ends:
            g = {k: v for k, v in g.items() if k != 'gear'}
            if g.get('until') and g['until'] == ends[key]:
                del g['until']
        out.append(g)
    return dict(build, slots=slots, goals=out)
