# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Sergei Labutin
# Additional terms under GPL-3.0 section 7: see NOTICE.md
"""Инвентарь на статах: что надето, что это даёт герою суммой и чем вещь из буфера лучше надетой.

Вещи подбирают под итоговые статы героя, а не под аффиксы: сопротивление холоду с суффикса, с руны и
со встроенного свойства кольца — одно и то же сопротивление. Поэтому всё считается по паспортам вещей
(itemstats): сколько каждого стата даёт надетая вещь, сколько — новая, и что от этого станет с героем.

Какие статы билду нужны, говорит он сам (раздел stats билда, по порядку важности). Чего стоит стат
на этой вещи, считается из данных игры:

  * редкий — сами его несут не больше трёх слотов билда (аффиксом, свойством базы или её встроенным
    свойством), и этот слот — один из них: скорость на сапогах, уровень умений приспешников на шлеме,
    амулете и скипетре. Больше его взять негде, поэтому такие статы решают первыми, по одному,
    в порядке билда: разница в редком стате перевешивает всё, что ниже;
  * с порогом (сопротивления, предел 75%) — считается только то, что доводит героя до порога; что сверх
    порога, не стоит ничего;
  * остальные — рост: чем больше, тем лучше.

Мера разницы — доля лучшего аффикса этого стата, какой сейчас бывает на таком слоте (на вещи уровня
самой дальней зоны забега). Номера тиров тут ни при чём: у разных аффиксов разное число ступеней
и открываются они на разных уровнях предмета, поэтому сравнивается число на вещи с лучшим числом,
какое сейчас вообще может выпасть. У стата, который вещь несёт своим свойством (броня доспеха, дух
скипетра), мера — доля этого стата у героя со всех вещей. Обычные статы складываются в общий счёт;
разница меньше одной восьмой аффикса (TIE) разницей не считается.

Вещи разной редкости (белая, синяя, жёлтая) — защита базы попроще не перевешивает вложенного в вещь побогаче:
броня, уклонение и энергощит базы — то, за что её берут под крафт. Если при одной защите баз вещь побогаче
заметно лучше, ответ её; у белой рядом сказано «как база — лучше» (compare: even, basis).

Что герой получает не с вещей, известно пока частично: штраф сопротивлений стихиям за пройденные акты
и награды маршрута (поле gives цели). Дерево и остальное — отдельный шаг.

Надетое программа помнит сама: «надеть» сохраняет вещь целиком в файле забега.
"""
import re

import buildstage
import gamedata
import itemstats
import slotstats
import slotwear
from i18n import tr

SCARCE_MAX = 3      # стат, который наверняка несут не больше стольких слотов билда, — редкий
TIE = 0.12          # разница меньше одной восьмой лучшего аффикса — не разница
NEAR = 0.25         # вещи «почти равны»: счёт меньше четверти лучшего аффикса — тогда решает база по плану
AFFIXES = {'rare': 6, 'magic': 2}      # сколько аффиксов вмещает вещь (префиксы и суффиксы вместе)
# Сколько в вещь вложено сверх базы — по её редкости: у белой аффиксов нет, у синей один-два, у жёлтой до шести.
# Уникальной здесь нет: её свойства — не вложение, а сама вещь.
INVESTED = {'normal': 0, 'magic': 1, 'rare': 2}

RE_ACT = re.compile(r'^G(\d+)_')
RE_INTERLUDE = re.compile(r'^P\d+_')
RE_MAPS = re.compile(r'^(G_Endgame|Map)', re.I)


def worn_key(slot, line=None):
    """Имя места в памяти надетого: «слот/». Слот помнит один предмет — тот, что на герое надет; периоды слота (line
    — шаг, с которого в нём что-то носят по плану) места не меняют: рюкзака нет. Записи прежнего вида («слот/шаг»)
    читает slotwear.settle."""
    return '%s/' % slot


def signature(item):
    """По чему узнать ту же самую вещь: имя, база, уровень и все её строки."""
    return [item.get('name'), item.get('base'), item.get('ilvl'),
            [list(m.get('lines') or ()) for m in item.get('mods') or []],
            [p.get('text') for p in item.get('plain') or []]]


def res_penalty(events):
    """Штраф к сопротивлениям стихиям по самому дальнему месту забега, числом процентов (хаоса не
    касается). Акт 2 — 10, акт 3 — 20, акт 4 — 30; в интерлюдиях по уровню зоны: 54–59 — 40, 60–64 — 50;
    с 65-го и на картах — 60. Игра считает штраф по зоне, где герой стоит; вещи подбирают под самое
    дальнее место, поэтому берётся оно."""
    act, inter, maps = 1, 0, False
    for e in events or []:
        if e.get('type') != 'zone':
            continue
        code = e.get('code') or ''
        m = RE_ACT.match(code)
        if m:
            act = max(act, int(m.group(1)))
        elif RE_INTERLUDE.match(code):
            inter = max(inter, e.get('level') or 1)
        elif RE_MAPS.match(code):
            maps = True
    if maps or inter >= 65:
        return 60
    if inter >= 60:
        return 50
    if inter >= 54:
        return 40
    if inter:
        return 30
    return min(30, 10 * (act - 1))


def rest(cat, gained, events):
    """Что герой получает не с вещей — то, что уже умеем считать: награды маршрута (gained — стат ->
    сумма по сделанным целям с полем gives, её считает core.derive: награду отмечает лог) и штраф актов
    у статов с пометкой act_penalty. Возвращает {стат: число}."""
    table = ((cat or {}).get('stats') or {}).get('stats') or {}
    out = {sid: v for sid, v in (gained or {}).items()
           if sid in table and isinstance(v, (int, float)) and not isinstance(v, bool)}
    pen = res_penalty(events)
    for sid, s in table.items():
        if s.get('act_penalty') and pen:
            out[sid] = out.get(sid, 0) - pen
    return out


def gear(cat, worn):
    """Статы каждой запомненной вещи: место -> {стат: число}. По ним сами отмечаются цели по стату
    (core.derive). Без каталога паспорта нет — тогда такие цели отмечают рукой."""
    out = {}
    for key, entry in (worn or {}).items():
        p = itemstats.passport(cat, entry.get('item'))
        if p is not None:
            out[key] = p['stats']
    return out


# --- билд на шаге маршрута: этап -----------------------------------------------------------------------
# Что ценно на вещи, меняется по ходу забега вместе с направлением билда: до вознесения — урон оружия,
# после — приспешники; кампанию идут на броне, на картах переходят на энергощит, и броня с силой уже
# ни к чему. Всё это — параметры этапа билда (buildstage): статы по важности, база защиты (род баз, как
# кнопки «Armour / AR/EV / Evasion / EV/ES / Energy Shield / AR/ES» в фильтре) и атрибуты. Этап называет
# только то, что меняет; остальное действует как на прежнем. Из названного выводится само:
#   * статы защиты — то, что базы этого рода несут своим свойством (данные игры);
#   * стат, который дерево этапа обнуляет (здоровье при «Иммунитете к хаосу»), из счёта уходит —
#     правило в таблице статов каталога (void), узлы — из версии дерева, действующей на шаге.
# Атрибуты из базы НЕ выводятся: сила при броне — случай одного билда, у другого она нужна ради урона
# или не нужна вовсе. Их этап называет сам (attrs) — любые из тех, что в игре есть.

def stage(plan, pos):
    """Этап билда на шаге маршрута pos (номер шага; None — забег ещё не начат) со всем, что на нём
    действует, — см. buildstage.effective. None — этапов у билда нет."""
    return buildstage.at(plan, pos)


def _kind_share(cat, kind, field):
    """Что есть почти у всех баз рода в поле field (props — свои свойства, req — требования). Порог —
    девять баз из десяти: в данных игры попадаются одиночные странные базы (силовая с уклонением вместо
    брони)."""
    count, total = {}, 0
    for b in ((cat or {}).get('bases') or {}).values():
        if kind in (b.get('tags') or ()) and b.get('props'):
            total += 1
            for p in b.get(field) or ():
                count[p] = count.get(p, 0) + 1
    return {p for p, n in count.items() if n * 10 >= total * 9}


def defence_stats(cat, kind):
    """Статы, которыми держит удар база такого рода, — то, что её базы несут своим свойством: силовые —
    броню, на интеллект — энергощит, смешанные — и то и другое. В порядке каталога."""
    table = ((cat or {}).get('stats') or {}).get('stats') or {}
    props = _kind_share(cat, kind, 'props')
    order = ((cat or {}).get('stats') or {}).get('order') or list(table)
    return [sid for sid in order if sid in table and table[sid].get('prop') in props]


def kind_attrs(cat, kind):
    """Атрибуты, которых требуют базы такого рода: без них такую вещь не надеть (силовые — сила, на
    интеллект — интеллект, смешанные — оба). В порядке каталога. В счёт сами они не идут — по ним
    роды баз стоят в привычном порядке и подписаны (buildplan.kinds)."""
    table = ((cat or {}).get('stats') or {}).get('stats') or {}
    need = _kind_share(cat, kind, 'req')
    order = ((cat or {}).get('stats') or {}).get('order') or list(table)
    return [sid for sid in order if sid in table and sid in need]


def attributes(cat):
    """Атрибуты героя, какие есть в игре, — статы, которых базы требуют, чтобы их надеть (сила,
    ловкость, интеллект). Из данных игры, в порядке каталога."""
    table = ((cat or {}).get('stats') or {}).get('stats') or {}
    need = {k for b in ((cat or {}).get('bases') or {}).values() for k in (b.get('req') or ())}
    order = ((cat or {}).get('stats') or {}).get('order') or list(table)
    return [sid for sid in order if sid in table and sid in need]


def voided(cat, plan, pos, tree_lines):
    """Статы, которые на шаге pos потеряли смысл из-за узла в дереве этапа: {стат: {node, line}}.
    Правило — в таблице статов (void: строки узла, с которыми стат бесполезен: «Maximum Life is 1»);
    узлы — из версии дерева героя, действующей на шаге: билд идёт к ней, и вещи подбирают под неё
    заранее, не дожидаясь, пока узел взят. tree_lines — что даёт каждый узел дерева (treestats.json)."""
    return version_voids(void_rules(cat), buildstage.version(plan, 'tree', pos), tree_lines)


def void_rules(cat):
    """Правила «стат бесполезен»: {стат: строки узла дерева, с которыми он теряет смысл}."""
    table = ((cat or {}).get('stats') or {}).get('stats') or {}
    return {sid: set(s['void']) for sid, s in table.items() if s.get('void')}


def version_voids(rules, phase, tree_lines):
    """Что обнуляет одна версия дерева (phase — запись версии с узлами): {стат: {node, line}}."""
    if not rules or not tree_lines or not phase:
        return {}
    out = {}
    for n in phase.get('nodes') or []:
        lines = tree_lines.get(n.get('id'))
        lines = lines.get('text') if isinstance(lines, dict) else lines
        for sid, texts in rules.items():
            hit = next((ln for ln in lines or () if ln in texts), None)
            if hit and sid not in out:
                out[sid] = {'node': n.get('name') or n['id'], 'line': hit}
    return out


def _with_kind(cat, spec, kind):
    """Описание базы слота с родом этапа защиты: «Gloves» → «Gloves int_armour». Род, названный в самом
    описании («Helmet int_armour»), остаётся; класс, у которого такого рода нет (пояс), — как был."""
    cls, own = gamedata.spec_parts(spec)
    if own or not cls or not kind:
        return spec
    if any(b['class'] == cls and kind in b['tags'] for b in cat['bases'].values()):
        return '%s %s' % (cls, kind)
    return spec


def slot_lines(plan):
    """Периоды слотов: {слот: [(номер шага, id шага или None, описание базы или None)]} по порядку шагов.
    Период — то, что в слоте носят с одного шага (нет шага — с начала забега, номер −1). Вещи меняют по одной,
    поэтому периоды у каждого слота свои (slotwear). Описание базы — первое из описаний периода («Sceptre»,
    «Shield str_armour»); у слота старого вида — поле gear цели периода: сначала цели-базы, потом любой; нет
    ни у одной — None (тогда действует описание самого слота)."""
    idx = {s['id']: i for i, s in enumerate(plan.get('steps') or [])}
    out = {}
    for s in plan.get('slots') or []:
        rows = [(idx[p['from']] if p['from'] else -1, p['from'],
                 (slotwear.specs(None, p) or [None])[0] if p['stated'] else p['spec'])
                for p in slotwear.periods(s, plan.get('goals') or [], idx)]
        if rows:
            out[s['id']] = rows
    return out


def line_at(lines, pos):
    """Линия слота, которая в ходу на шаге pos: (id шага или None, описание базы или None). lines — линии
    одного слота из slot_lines; у слота без целей линий нет — (None, None)."""
    cur = (None, None)
    for at, ln, gear in lines or ():
        if at <= (pos or 0):
            cur = (ln, gear)
    return cur


def at_step(cat, plan, pos, tree_lines=None):
    """Билд, каким он действует на шаге маршрута pos — всё, что о нём нужно знать сравнению вещей:

      stats — статы этапа по важности; к ним добавлены статы базы защиты этапа и атрибуты, которые этап
              назвал (attrs); статы, обнулённые деревом этапа, убраны;
      slots — слоты с описанием базы того, что в слоте в ходу на этом шаге (поле gear цели его линии:
              до вознесения в оружии самострел, после — скипетр; нет — описание самого слота); слотам
              без названного рода базы дан род этапа;
      keys  — где в памяти надетого лежит вещь каждого слота: {слот: место} (одно место на слот — worn_key);
      floors — пороги автора: цели по стату у слота («дух скипетра от 120») — {место: [{stat, min, goal}]}.
              Порогом служит цель периода, который на этом шаге в ходу: цель будущего периода (use впереди) ещё
              не служит, цель, чей срок годности (until) позади, — уже.

    Этапов у билда нет — статов нет. Без каталога данных игры вывести из базы защиты нечего: остаются
    список статов этапа, слоты и места."""
    st = stage(plan, pos)
    stats = list((st or {}).get('stats') or [])
    lines = slot_lines(plan)
    idx = {s['id']: i for i, s in enumerate(plan.get('steps') or [])}
    slots, keys = [], {}
    for s in plan.get('slots') or []:
        ln, gear = line_at(lines.get(s['id']), pos)
        keys[s['id']] = worn_key(s['id'], ln)
        # Период слота записан в плане — у слота столько описаний базы, сколько классов носят в этот период
        # (specs): стат на слоте бывает, если бывает хотя бы на одном из них. gear — первое из них.
        per = slotwear.period_of(s, plan.get('goals') or [], idx, ln) if slotwear.stated(s) and lines.get(s['id']) else None
        if per and per['from'] == ln and (not ln or idx[ln] <= (pos or 0)):
            every = slotwear.specs(cat, per)
            slots.append(dict(s, gear=every[0], specs=every) if every else s)
        else:
            slots.append(dict(s, gear=gear) if gear else s)
    if cat and cat.get('bases') and st is not None:
        gone = voided(cat, plan, pos, tree_lines)
        stats = [s for s in stats if s['id'] not in gone]
        kind = st.get('kind')
        known = attributes(cat)
        for sid in (defence_stats(cat, kind) if kind else []) + [a for a in st.get('attrs') or [] if a in known]:
            if sid not in gone and not any(x['id'] == sid for x in stats):
                stats.append({'id': sid})
        if kind:
            slots = [dict(s, gear=_with_kind(cat, s['gear'], kind),
                          **({'specs': [_with_kind(cat, x, kind) for x in s['specs']]} if s.get('specs') else {}))
                     if s.get('gear') else s for s in slots]
    floors = {}
    for g in plan.get('goals') or []:
        if (not isinstance(g, dict) or not g.get('slot') or not g.get('stat') or isinstance(g.get('min'), bool)
                or not isinstance(g.get('min'), (int, float))):
            continue
        if g.get('until') in idx and (pos or 0) > idx[g['until']]:
            continue
        if g.get('use') in idx and (pos or 0) < idx[g['use']]:
            continue
        floors.setdefault(worn_key(g['slot']), []).append({'stat': g['stat'], 'min': g['min'], 'goal': g.get('id')})
    return dict(plan, stats=stats, slots=slots, keys=keys, floors=floors)


# --- билд: какие статы нужны и где их берут ---------------------------------------------------------

def wanted(plan):
    """Статы, которые билд ведёт на своём шаге, по важности. plan — билд на шаге (at_step)."""
    return list(plan.get('stats') or [])


def hero_keys(plan):
    """Слот -> место в памяти надетого. plan — билд на шаге (at_step): места он уже назвал; у билда
    «как есть» вещь каждого слота лежит в месте с пустой линией."""
    keys = plan.get('keys') or {}
    return {s['id']: keys.get(s['id']) or worn_key(s['id']) for s in plan.get('slots') or []}


def specs(plan):
    """Слоты героя с описанием базы: [(слот, название, описание)]. plan — билд на шаге (at_step). У слота,
    в период которого носят предметы нескольких классов, — по строке на класс."""
    return [(s['id'], s.get('name') or s['id'], spec) for s in plan.get('slots') or [] if s.get('gear')
            for spec in (s.get('specs') or [s['gear']])]


def carriers(cat, plan):
    """Где какой стат бывает на слотах героя (slotstats.carriers); считается один раз на набор слотов."""
    sp = specs(plan)
    key = tuple((a, c) for a, _, c in sp)
    cache = cat.setdefault('_carriers', {})
    if key not in cache:
        if len(cache) > 8:
            cache.clear()
        cache[key] = slotstats.carriers(cat, sp)
    return cache[key]


def source_slots(table, sid):
    """Слоты, которые несут стат сами: аффиксом, свойством базы или её встроенным свойством."""
    return [slot for slot, f in (table.get(sid) or {}).items() if slotstats.is_source(f)]


def sure_slots(table, sid):
    """Слоты, которые несут стат наверняка: он бывает на предмете любого класса, который в слоте носят
    (slotstats.is_sure). Оружие, где принимается любой из четырёх классов, а стат бывает только на скипетре, —
    не из них."""
    return [slot for slot, f in (table.get(sid) or {}).items() if slotstats.is_sure(f)]


def is_scarce(table, sid):
    """Редкий ли стат у билда: хоть один слот может нести его сам, а несущих наверняка — не больше трёх."""
    return bool(source_slots(table, sid)) and len(sure_slots(table, sid)) <= SCARCE_MAX


def is_rare(table, sid, slot):
    """Редкий ли стат на этом слоте: слот может нести его сам, и у билда стат редкий (is_scarce)."""
    return slot in source_slots(table, sid) and is_scarce(table, sid)


def may_carry(table, sid, slot, cls):
    """Бывает ли стат на предмете этого класса в этом слоте: слот несёт его на любом классе, который в нём носят,
    либо класс предмета — из тех, на которых слот его несёт (slotstats.carriers: every, on). Класс не известен —
    считается, что бывает."""
    f = (table.get(sid) or {}).get(slot)
    return slotstats.is_source(f) and (f.get('every', True) or cls is None or cls in (f.get('on') or ()))


def class_word(cat, cls, lang='ru'):
    """Как класс предмета называет клиент игры («Скипетры»), иначе таблица классов игры, иначе как в данных."""
    pack = ((cat or {}).get('lang') or {}).get(lang) or {}
    return (next((w for w, cid in (pack.get('classes') or {}).items() if cid == cls), None)
            or (pack.get('classNames') or {}).get(cls) or cls)


def stage_rare(cat, plan, tree_lines=None, lang='ru'):
    """Какие статы на каком этапе редкие — для страницы «Билд»: {id этапа: {стат: [названия слотов]}}.

    Редкий стат (is_rare) на своих слотах решает сравнение вещей первым — по порядку списка этапа;
    остальные статы складываются в общий счёт, и порядок среди них ничего не меняет (compare). Страница
    показывает список этапа так, как им пользуется сравнение, — двумя группами. Названы все редкие статы
    таблицы, а не только те, что в списке этапа: про стат, который в список только что добавили, страница
    знает сразу. Слоты — по всем шагам этапа: вещь в слоте по ходу этапа сменяется (самострел → скипетр),
    и стат, редкий хотя бы на части этапа, назван редким на всех таких слотах; порядок слотов — как
    у билда. Слот, который несёт стат не наверняка (в нём носят предметы нескольких классов, а стат бывает не
    на всех), назван с этими классами: «Оружие (скипетры)» — в счёт редкости он не идёт (is_scarce).
    Этап, на который не приходится ни одного шага, пропущен. Нет каталога или этапов — {}."""
    stages = plan.get('stages') or []
    table = ((cat or {}).get('stats') or {}).get('stats')
    if not stages or not table or not cat.get('bases'):
        return {}
    by = buildstage.per_step(plan)
    # шаги, с которых в каком-нибудь слоте носят другую вещь: набор слотов меняется только на них
    turns = {at for lines in slot_lines(plan).values() for at, _, _ in lines if at > 0}
    names = [(s['id'], s.get('name') or s['id']) for s in plan.get('slots') or []]
    out = {}
    for n, st in enumerate(stages):
        # у маршрута без шагов действует только первый этап — как до начала забега
        mine = [i for i, m in enumerate(by) if m == n] if by else ([None] if n == 0 else [])
        if not mine:
            continue
        found, part = {}, {}       # стат -> слоты; (стат, слот) -> классы, на которых он бывает, если не на всех
        for pos in mine[:1] + [i for i in mine[1:] if i in turns]:
            where = carriers(cat, at_step(cat, plan, pos, tree_lines))
            for sid in table:
                if is_scarce(where, sid):
                    slots = source_slots(where, sid)
                    found.setdefault(sid, set()).update(slots)
                    for slot in slots:
                        if not where[sid][slot].get('every', True):
                            part.setdefault((sid, slot), set()).update(where[sid][slot].get('on') or ())
        said = lambda sid, slot, name: name if (sid, slot) not in part else '%s (%s)' % (     # noqa: E731
            name, ', '.join(sorted(class_word(cat, c, lang).lower() for c in part[(sid, slot)])))
        out[st['id']] = {sid: list(dict.fromkeys(said(sid, slot, name) for slot, name in names if slot in slots))
                         for sid, slots in found.items()}
    return out


def unit_of(table, sid, slot, ilvl=None, own=False):
    """Лучший аффикс стата, какой бывает на этом слоте на вещи уровня ilvl (верх его диапазона): мера
    «одного аффикса». Свойства, меняющие саму вещь, не в счёт — их мера другая (см. compare). Слот стат
    аффиксом не несёт (холод с руны на щите, штраф скорости доспеха) — мера с того слота, где аффикс
    крупнее всего; own — только свой слот: чужая мера не годится как «лучшее, что тут бывает».
    None — меры нет."""
    def best(found):
        top = 0
        for a in (found or {}).get('affix') or []:
            if a['local'] or not a['steps']:
                continue
            ok = [st for st in a['steps'] if ilvl is None or st[0] <= ilvl] or a['steps'][:1]
            top = max(top, ok[-1][2] or 0)
        return top
    slots = table.get(sid) or {}
    mine = best(slots.get(slot))
    return mine or (None if own else max([best(f) for f in slots.values()] or [0]) or None)


# --- свойство самой вещи и её база -------------------------------------------------------------------

def item_base(cat, item):
    """Запись базы вещи в каталоге — по английскому имени базы и классу (их знает itemcopy.identify).
    У нескольких записей с одним именем (в данных игры такое бывает) — та, чьи метки совпали с метками
    вещи. None — базы нет."""
    name, cls = (item or {}).get('base_en'), (item or {}).get('cls_id')
    if not name or not cat:
        return None
    cache = cat.setdefault('_base_by_name', {})
    if (name, cls) not in cache:
        cache[(name, cls)] = [b for b in (cat.get('bases') or {}).values()
                              if b.get('name') == name and (cls is None or b.get('class') == cls)]
    found = cache[(name, cls)]
    return next((b for b in found if b.get('tags') == item.get('tags')), found[0] if found else None)


def own_unit(cat, sid, items, ilvl=None):
    """Мера «одного аффикса» для стата, который вещь несёт своим свойством (броня доспеха, энергощит
    тиары, дух скипетра): сколько прибавит свойству лучший ОДИН аффикс, меняющий саму вещь, на базе этой
    вещи — числом (верх ступени, какая бывает на вещи уровня ilvl) или процентом от свойства базы, что
    больше. items — вещи, которые сравнивают (надетая и новая): берётся большая мера, обе измерены одной
    линейкой. Так свойство вещи стоит в одном ряду с остальными статами: «+90 энергощита» на тиаре — это
    примерно один лучший аффикс, как «+35% к сопротивлению». None — меры нет: у баз нет такого свойства
    или данные игры не называют таких аффиксов; тогда сравнение меряет долей от суммы героя.

    У брони, уклонения и энергощита (guard_stats) мера не меньше всей базы: целая база стоит не больше одного
    лучшего аффикса. Так на картах и выходит само (с 65-го уровня предмета лучший процент защиты +100% и
    больше), а в кампании проценты слабые (+26…55%), и база нательного доспеха без этого стоила бы 2–4 аффикса —
    больше, чем три аффикса сопротивлений вместе."""
    st = (((cat or {}).get('stats') or {}).get('stats') or {}).get(sid) or {}
    prop, local = st.get('prop'), set(st.get('local') or ())
    if not prop or not local:
        return None
    cache = cat.setdefault('_own_units', {})
    best = 0
    for it in items:
        base = item_base(cat, it)
        value = ((base or {}).get('props') or {}).get(prop)
        if not value:
            continue
        key = (sid, base['name'], base.get('class'), tuple(base.get('tags') or ()), ilvl)
        if key not in cache:
            top = 0
            for fam in (cat.get('mods') or {}).values():
                for j, gid in enumerate(fam.get('stats') or ()):
                    if gid not in local:
                        continue
                    tiers = gamedata.tiers(fam, base.get('tags') or [])
                    ok = [t for t in tiers if ilvl is None or (t.get('level') or 0) <= ilvl] or tiers[:1]
                    if not ok:
                        continue
                    hi = ok[-1]['vals'][j][1] or 0
                    line = next((k for k in fam.get('lines') or () if gid in k.split()), gid)
                    top = max(top, hi * value / 100.0 if gamedata.is_percent(cat, line) else hi)
            cache[key] = max(top, value) if top and sid in guard_stats(cat) else top
        best = max(best, cache[key])
    return best or None


def guard_stats(cat):
    """Статы защиты, которые несут базы снаряжения своим числом, — броня, уклонение, энергощит: всё, что
    defence_stats находит у какого-нибудь рода баз. Из данных игры."""
    if '_guard' not in cat:
        kinds = {t for b in (cat.get('bases') or {}).values() for t in b.get('tags') or () if t.endswith('_armour')}
        cat['_guard'] = {sid for k in kinds for sid in defence_stats(cat, k)}
    return cat['_guard']


def on_base(cat, under, under_p, item, p):
    """Паспорт вещи item с защитой базы вещи under: броня, уклонение, энергощит (guard_stats) — числом самой
    вещи и встроенным свойством — и штраф скорости базы — от under, всё остальное — от item, как есть. Так
    видно, чем вещи разнятся помимо своих баз: аффиксами и прочими встроенными свойствами (сопротивления
    кольца, здоровье амулета).

    under_p и p — паспорта вещей без вставок (itemstats.bare). Число самой вещи («Броня: 160») считается как
    у игры: (база under + числа аффиксов item) × (1 + проценты аффиксов item) × (1 + качество under) — прибавки,
    вложенные в item, остаются его. Базы under нет в каталоге — её базой считается всё её число."""
    table = ((cat or {}).get('stats') or {}).get('stats') or {}
    guard = guard_stats(cat)

    def of_base(sid, part):
        return part['src'] == 'base' or (sid in guard and part['src'] in ('property', 'implicit'))
    parts = {}
    for sid, ps in (p.get('parts') or {}).items():
        for part in ps:
            if not of_base(sid, part):
                parts.setdefault(sid, []).append(part)
    for sid, ps in (under_p.get('parts') or {}).items():
        for part in ps:
            if of_base(sid, part) and part['src'] != 'property':
                parts.setdefault(sid, []).append(part)
    base = item_base(cat, under)
    quality = 1 + (under_p.get('props') or {}).get('quality', 0) / 100.0
    for sid in guard:
        prop = (table.get(sid) or {}).get('prop')
        own = [x['v'] for x in (under_p.get('parts') or {}).get(sid) or () if x['src'] == 'property']
        theirs = [x for x in (p.get('parts') or {}).get(sid) or () if x['src'] == 'property']
        if not prop or not (own or theirs):
            continue
        loc = (p.get('local') or {}).get(sid) or {}
        if base:
            v = (((base.get('props') or {}).get(prop) or 0) + loc.get('flat', 0)) * (1 + loc.get('pct', 0) / 100.0) * quality
        else:
            v = (sum(own) + loc.get('flat', 0)) * (1 + loc.get('pct', 0) / 100.0)
        if v:
            parts.setdefault(sid, []).append({'v': _num(v), 'src': 'property', 'text': None})
    return {'stats': {sid: _num(sum(x['v'] for x in ps)) for sid, ps in parts.items()}, 'parts': parts,
            'props': under_p.get('props') or {}, 'local': {}}


def base_only(cat, item, p):
    """Паспорт одной базы вещи — какой эта вещь была бы белой: встроенные свойства, штраф базы и число самой
    вещи по данным игры (без прибавок аффиксов и качества). Базы нет в каталоге — её числом считается всё число
    вещи. p — паспорт вещи без вставок (itemstats.bare)."""
    table = ((cat or {}).get('stats') or {}).get('stats') or {}
    base = item_base(cat, item)
    parts = {}
    for sid, ps in (p.get('parts') or {}).items():
        for part in ps:
            if part['src'] in ('implicit', 'base') or (part['src'] == 'property' and not base):
                parts.setdefault(sid, []).append(part)
            elif part['src'] == 'property':
                v = ((base.get('props') or {}).get((table.get(sid) or {}).get('prop')))
                if v:
                    parts.setdefault(sid, []).append({'v': v, 'src': 'property', 'text': None})
    return {'stats': {sid: _num(sum(x['v'] for x in ps)) for sid, ps in parts.items()}, 'parts': parts,
            'props': p.get('props') or {}, 'local': {}}


def kind_stats(cat, tags):
    """Статы защиты, которые несёт база с такими метками, — по её роду (метка вида «int_armour»,
    «str_int_armour»): [] — рода нет (кольцо, оружие)."""
    cache = cat.setdefault('_kind_stats', {})
    out = []
    for t in tags or ():
        if not (isinstance(t, str) and t.endswith('_armour')):
            continue
        if t not in cache:
            cache[t] = defence_stats(cat, t)
        out += [s for s in cache[t] if s not in out]
    return out


def kind_of(cat, tags):
    """Род базы вещи — её метка, по которой базы несут защиту («str_int_armour»). None — рода нет."""
    return next((t for t in tags or () if kind_stats(cat, [t])), None)


def base_fit(cat, want, tags):
    """Насколько база вещи отвечает роду, который план ждёт в слоте (want): доля общих статов защиты
    среди всех статов защиты обоих родов. Тот же набор — 1; AR/ES при цели ES — 0.5; AR при цели ES — 0."""
    a, b = set(kind_stats(cat, [want])), set(kind_stats(cat, tags))
    return len(a & b) / float(len(a | b)) if a | b else 1.0


# --- суммы героя ------------------------------------------------------------------------------------

EMPTY = {'stats': {}, 'parts': {}}


def passport_sums(passports):
    """Суммы статов по паспортам вещей. Штраф базы (скорость у доспеха и щита) умножается на прибавки,
    а не складывается: (1 − 5%) × (1 + 30%) − 1 = 23,5%."""
    sums, base = {}, {}
    for p in passports:
        for sid, parts in p['parts'].items():
            for part in parts:
                bucket = base if part['src'] == 'base' else sums
                bucket[sid] = bucket.get(sid, 0) + part['v']
    for sid, pen in base.items():
        sums[sid] = round(((1 + pen / 100.0) * (1 + sums.get(sid, 0) / 100.0) - 1) * 100, 1)
    return sums


def gear_sums(cat, items):
    """Суммы статов со всех вещей — как они есть, со вставками в гнёздах."""
    return passport_sums([itemstats.passport(cat, it) or EMPTY for it in items])


def _num(x):
    x = round(x, 1)
    return int(x) if x == int(x) else x


def _names(cat, lang):
    packs = cat.get('lang') or {}
    return (packs.get(lang) or {}).get('statNames') or (packs.get('ru') or {}).get('statNames') or {}


def _own(st, *passports):
    """Несёт ли вещь стат своим свойством («Броня: 358»): тогда аффикс меняет вещь, а не героя."""
    sid = st['_id']
    return bool(st.get('prop')) and any(p['src'] == 'property' for ps in passports for p in ps['parts'].get(sid) or [])


# --- вещь в слоте: что на ней работает на билд -------------------------------------------------------

def affix_bar(cat, table, want, where, slot, item, ilvl=None):
    """Аффиксы вещи отрезками — сколько из них работает на билд. Отрезок: q — насколько аффикс силён
    (число на вещи к лучшему, какое сейчас бывает у этого аффикса на такой базе; 0 — аффикс билду не
    нужен), rare — он несёт редкий для слота стат, free — место под аффикс свободно. Сначала редкие,
    потом по силе, потом бесполезные, в конце свободные. None — у вещи не видно аффиксов (простая
    копия, уникальная вещь)."""
    room = AFFIXES.get(item.get('rarity'))
    if not item.get('advanced') or room is None:
        return None
    by_game = {}
    for w in want:
        for gid in (table[w['id']].get('ids') or []) + (table[w['id']].get('local') or []):
            by_game.setdefault(gid, w['id'])
    idx = itemstats.line_index(cat, item.get('lang'))
    tags = item.get('tags') or []
    cells = []
    for m in item.get('mods') or []:
        if m.get('kind') != 'explicit':
            continue
        fam = (cat.get('mods') or {}).get(m.get('fam')) if m.get('fam') else None
        cell = {'q': 0, 'rare': False, 'free': False, 'stat': None}
        if fam:
            tiers = gamedata.tiers(fam, tags)
            now = [t for t in tiers if ilvl is None or (t['level'] or 0) <= ilvl] or tiers[:1]
            rolled = {}
            for shape, values in zip(m['shapes'], m['values']):
                key = next((k for k, _ in idx.get(itemstats.norm(shape)) or () if k in fam['lines']), None)
                for n, gid in enumerate(key.split() if key else ()):
                    if n < len(values):
                        rolled[gid] = values[n]
            for j, gid in enumerate(fam['stats']):
                sid = by_game.get(gid)
                if sid is None or gid not in rolled or not now:
                    continue
                top = now[-1]['vals'][j][1]
                q = min(1.0, rolled[gid] / float(top)) if top else 1.0
                if q > cell['q']:
                    cell.update(q=round(q, 2), stat=sid, rare=is_rare(where, sid, slot))
        cells.append(cell)
    cells.sort(key=lambda c: (not c['rare'], -c['q']))
    cells += [{'q': 0, 'rare': False, 'free': True, 'stat': None}] * max(0, room - len(cells))
    return cells


def slot_item(cat, plan, slot, key, worn, extra, ilvl=None, lang='ru'):
    """Вещь, запомненная в слоте, для его плитки и карточки. None — в слоте ничего не запомнено.

    name, base, at, icon — что за вещь, когда запомнена и её картинка (у уникального своя); lines — её статы билда (и редкие статы слота,
    которых на ней нет: missing): value — число на вещи, top — лучший аффикс, какой сейчас бывает,
    q — доля от него (не больше 1), cls — scarce / need / over / grow, у стата с порогом hero и cap (over — без
    этой вещи герой всё равно у порога; порог держит она — without: сколько у героя станет без неё);
    bar — её аффиксы отрезками (affix_bar); stats — паспорт вещи целиком (itemstats.view).
    """
    entry = (worn or {}).get(key)
    if not entry:
        return None
    item = entry['item']
    out = {'name': item.get('name'), 'base': item.get('base'), 'at': entry.get('at'), 'lines': [], 'bar': None,
           'stats': itemstats.view(cat, item, lang),
           # картинка вещи (у уникального — своя, иначе базы): имя файла в папке картинок (есть ли сам файл,
           # проверяет программа)
           'icon': gamedata.item_icon(cat, item)}
    table = ((cat or {}).get('stats') or {}).get('stats')
    want = [w for w in wanted(plan) if table and w['id'] in table]
    p = itemstats.passport(cat, item)
    if not want or p is None:
        return out
    keys = hero_keys(plan)
    sums = gear_sums(cat, [worn[k]['item'] for k in keys.values() if k in worn])
    where = carriers(cat, plan)
    names = _names(cat, lang)
    rare, common = [], []
    for w in want:
        sid = w['id']
        st = dict(table[sid], _id=sid)
        v = p['stats'].get(sid, 0)
        scarce = is_rare(where, sid, slot)
        # редкий стат, которого на предмете нет, ищут на этом слоте, только если он бывает на предмете такого
        # класса: на жезле в оружии уровня умений приспешников не бывает — строки «нет» у него быть не должно
        if not (v or (scarce and may_carry(where, sid, slot, item.get('cls_id')))):
            continue
        cap = w.get('cap', st.get('cap'))
        top = None if _own(st, p) else unit_of(where, sid, slot, ilvl, own=True)
        ln = {'id': sid, 'value': _num(v), 'unit': st.get('unit') or '', 'cap': cap, 'top': top,
              'q': round(min(1.0, v / float(top)), 2) if top and v > 0 else None, 'missing': scarce and not v}
        ln['name'], ln['short'] = names.get(sid) or (sid, sid)
        over = False
        if cap is not None:
            total = sums.get(sid, 0) + extra.get(sid, 0)
            ln['hero'] = _num(total)
            # Сверх порога число вещи, только если без неё герой у порога остаётся. Герой выше порога, а без неё
            # ниже — порог держит она: строка нужная, и сказано, сколько станет без неё (их проверка 2026-11-24:
            # «сейчас больше 75 — значит, не важно» было неверно).
            rest = total - v
            over = rest >= cap
            if total >= cap > rest:
                ln['without'] = _num(rest)
        ln['cls'] = 'scarce' if scarce else 'over' if over else 'need' if cap is not None else 'grow'
        (rare if scarce else common).append(ln)
    out['lines'] = rare + common
    out['bar'] = affix_bar(cat, table, want, where, slot, item, ilvl)
    return out


# --- вещь из буфера против надетой -----------------------------------------------------------------

def compare(cat, plan, slot, key, item, worn, extra, ilvl=None, lang='ru', base=None):
    """Вещь из буфера против той, что запомнена в слоте, — по статам билда. Чистая функция.

    plan — билд на шаге, где вещь носят (at_step); slot и key — слот и его место в памяти надетого;
    worn — память надетого; extra — что известно помимо вещей; base — что план говорит о базе вещи
    (itemcopy.compare: now, new, delta): у слота с названными базами (самострелы по именам) база
    получше решает первой, раньше любого стата. None — сравнить нельзя (нет каталога или билд не
    назвал статы).

    Сравниваются сами вещи, БЕЗ вставок в гнёздах (руны, сердцевины душ), но с собственными свойствами
    баз: руны в новую вещь ещё только предстоит вставить, и ответ нужен до того, как их потратят. Что
    дают вставки, отдано отдельно (runes) — вместе с ответом «как есть», если он другой.

    Как решается ответ. (1) База из плана, названная по имени, и редкие статы слота — по порядку: первая
    заметная разница решает. Стат, у которого план ставит этой вещи порог (цель «дух скипетра от 120», at_step:
    floors), а берёт его только одна из двух вещей, решает так же, на своём месте в порядке билда, — порогом,
    а не мерой разницы: 123 против 100 при пороге 120 — это цель плана, которая есть и которой не станет. (2) Остальные статы складываются в общий счёт, каждый — долей лучшего
    аффикса; свойство самой вещи (броня доспеха, энергощит тиары) — той же меркой (own_unit).
    (3) Вещи почти равны — ничто не решило, счёт меньше NEAR — и базы у них разного рода: лучше та, чья
    база ближе к роду, который план ждёт в слоте (строка kind: want — род по плану, now и new — роды
    баз надетой и новой вещи, decides — она и решила). (4) Вещи разной редкости, и вещь побогаче не
    выиграла: тот же расчёт ещё раз, новая вещь — с защитой базы надетой (on_base); выиграла в нём вещь
    побогаче — ответ её (byEven), строки первого расчёта ничего не решали.

    Возвращает verdict (better / worse / same / worn — это и есть надетая вещь), lines — строки статов,
    которые на вещах разные (и редких, если они есть): сначала база, потом редкие, потом обычные,
    в порядке билда; now и new — числа на надетой и на новой вещи, d — разница в долях лучшего
    аффикса (с учётом порога), cls — base / scarce / floor / need / grow / over (сверх порога и до, и после;
    floor — порог автора берёт только одна из вещей, floor — сам этот порог),
    hero и heroNew — стат героя до и после (у стата с порогом; noRunes — без вставок этого слота, когда
    они этот стат дают), cap, minor — разница мелкая (меньше TIE), decides — эта строка решила ответ.
    score — общий счёт обычных статов; up и down — сколько строк заметно лучше и хуже; same — статы
    билда, одинаковые на обеих вещах. runes — None, если вставок нет ни на одной из двух вещей; иначе
    now и new — что они дают надетой и новой вещи ([{id, short, value, unit}]), sockets — гнёзд
    у надетой и у новой, verdict — ответ с тем, что вставлено сейчас, если он не такой, как без вставок.
    even — у вещей разной редкости ответ при одной защите баз ({verdict, score, by — стат, который в нём
    решил}), иначе None; byEven — он и дал ответ; basis — «better», когда новая вещь проще надетой и
    проиграла только потому, что защита её базы в зачёт не пошла: её стоит оставить под крафт.
    """
    table = ((cat or {}).get('stats') or {}).get('stats')
    want = wanted(plan)
    new = itemstats.passport(cat, item)
    if not table or not want or new is None:
        return None
    entry = (worn or {}).get(key)
    old = (itemstats.passport(cat, entry['item']) if entry else None) or EMPTY
    keys = hero_keys(plan)
    # остальные вещи героя — как есть: их вставки на месте и в порог сопротивлений идут
    others = [itemstats.passport(cat, worn[k]['item']) or EMPTY
              for s, k in keys.items() if k in (worn or {}) and s != slot]
    where = carriers(cat, plan)
    names = _names(cat, lang)
    # пороги автора у вещи этого места: стат -> [min] (at_step: floors)
    floors = {}
    for f in (plan.get('floors') or {}).get(key) or ():
        floors.setdefault(f['stat'], []).append(f['min'])
    gives_old, gives_new = itemstats.inserts(old), itemstats.inserts(new)
    pair = [it for it in ((entry or {}).get('item'), item) if it]
    own_units = {}

    def own_measure(sid):
        """Мера свойства самой вещи — одна на оба расчёта (без вставок и «как есть»)."""
        if sid not in own_units:
            own_units[sid] = own_unit(cat, sid, pair, ilvl)
        return own_units[sid]

    # База по плану: род базы, который слот ждёт на этом шаге (описание слота: «Helmet int_armour»), и
    # насколько ему отвечают базы надетой и новой вещи. Строка есть, только когда они отвечают по-разному.
    spec = next((s.get('gear') for s in plan.get('slots') or [] if s['id'] == slot), None)
    planned = gamedata.spec_parts(spec)[1] if spec else None
    kind = None
    if planned and entry:
        fit_old, fit_new = base_fit(cat, planned, entry['item'].get('tags')), base_fit(cat, planned, item.get('tags'))
        if fit_old != fit_new:
            kind = {'id': 'kind', 'name': tr('База по плану'), 'short': tr('База'), 'unit': '', 'cap': None, 'cls': 'kind',
                    'want': planned, 'now': kind_of(cat, entry['item'].get('tags')), 'new': kind_of(cat, item.get('tags')),
                    'delta': 1 if fit_new > fit_old else -1, 'd': 0}

    def settle(verdict, lines, score):
        """Вещи почти равны (ни база по имени, ни редкий стат не решили, счёт меньше NEAR), а базы у них
        разного рода — решает база по плану: (ответ, решила ли она)."""
        if kind and not any(ln.get('decides') for ln in lines) and abs(score) < NEAR:
            return ('better' if kind['delta'] > 0 else 'worse'), True
        return verdict, False

    # Вещи разной редкости (белая, синяя, жёлтая): защита базы вещи попроще не перевешивает вложенное в другую.
    # Броня, уклонение и энергощит базы — то, за что базу берут под крафт; пока в неё не вложены аффиксы, лучше
    # вещи с аффиксами она не считается. Поэтому, когда вещь побогаче по обычному ответу не выиграла, вещи
    # сравниваются ещё раз тем же порядком (база по имени, редкие статы, счёт) — новая с защитой базы надетой
    # (on_base), всё остальное как есть. Выиграла вещь побогаче, когда защита баз одна, — ответ её. Иначе — как
    # у вещей одной редкости: белый амулет с перламутром (все сопротивления) честно лучше синего с одной силой,
    # белое кольцо с сапфиром — жёлтого, у которого полезно билду только встроенное, синие сапоги со скоростью —
    # жёлтых без неё.
    ranks = (INVESTED.get((entry or {}).get('item', {}).get('rarity')), INVESTED.get(item.get('rarity')))
    mixed = entry is not None and None not in ranks and ranks[0] != ranks[1]
    rich = ('better' if ranks[1] > ranks[0] else 'worse') if mixed else None    # ответ, когда выигрывает вещь побогаче
    even = None         # ответ при одной защите баз (вещи разной редкости) — считается ниже, когда judge уже есть

    def decide(old, new, stripped):
        """Ответ по паспортам надетой и новой вещи: (verdict, lines, score, same, how) — how: 'kind' — решила
        база по плану, 'even' — решил ответ при одной защите баз, None — строки."""
        verdict, lines, score, same = judge(old, new, stripped)
        verdict, by_kind = settle(verdict, lines, score)
        if even is not None and verdict != rich and even['verdict'] == rich:
            return rich, lines, score, same, 'even'
        return verdict, lines, score, same, 'kind' if by_kind else None

    def judge(old, new, stripped):
        """Ответ по паспортам надетой и новой вещи: (verdict, lines, score, same)."""
        sums_now = passport_sums(others + ([old] if entry else []))
        sums_new = passport_sums(others + [new])
        first, rare, common, same = [], [], [], []
        if base and base.get('delta'):
            first.append({'id': 'base', 'name': tr('База'), 'short': tr('База'), 'unit': '', 'cap': None, 'cls': 'base',
                          'now': base.get('now'), 'new': base.get('new'), 'delta': base['delta'], 'd': base['delta'],
                          'minor': False})
        for w in want + [{'id': sid} for sid in floors if not any(x['id'] == sid for x in want)]:
            sid = w['id']
            if sid not in table:
                continue
            st = dict(table[sid], _id=sid)
            a, b = old['stats'].get(sid, 0), new['stats'].get(sid, 0)
            scarce = is_rare(where, sid, slot)
            # порог автора, который берёт только одна из вещей (из нескольких таких — самый высокий)
            crossed = max((m for m in floors.get(sid, ()) if (a >= m) != (b >= m)), default=None)
            # Строка нужна, когда стат на вещах разный. Одинаковый обычный стат решению не помогает (он
            # остаётся в паспорте вещи); одинаковый редкий показываем: видно, что главное то же самое.
            if a == b and not (scarce and a):
                if a:
                    same.append(sid)
                continue
            cap = w.get('cap', st.get('cap'))
            ln = {'id': sid, 'now': _num(a), 'new': _num(b), 'unit': st.get('unit') or '', 'cap': cap}
            ln['name'], ln['short'] = names.get(sid) or (sid, sid)
            useful = b - a
            over = False
            if cap is not None:
                ha = sums_now.get(sid, 0) + extra.get(sid, 0)
                hb = sums_new.get(sid, 0) + extra.get(sid, 0)
                ln['hero'], ln['heroNew'] = _num(ha), _num(hb)
                # числа героя — без вставок этого слота: с тем, что видно в окне героя, они не сойдутся
                ln['noRunes'] = bool(stripped and (gives_old.get(sid) or gives_new.get(sid)))
                useful = min(hb, cap) - min(ha, cap)
                over = ha >= cap and hb >= cap
            # Мера: доля лучшего аффикса стата на таком слоте. У свойства самой вещи (броня доспеха, дух
            # скипетра) аффикс меняет вещь, а не героя, — мера та же по смыслу: сколько прибавит свойству
            # лучший один аффикс на такой базе (own_unit). Данных о таких аффиксах нет — доля этого стата
            # у героя со всех вещей.
            unit = own_measure(sid) if _own(st, old, new) else unit_of(where, sid, slot, ilvl)
            big = unit or max(abs(sums_now.get(sid, 0)), abs(sums_new.get(sid, 0)), abs(a), abs(b))
            ln['d'] = round(useful / big, 2) if big else 0
            ln['delta'] = (useful > 0) - (useful < 0)
            ln['minor'] = bool(ln['delta']) and abs(ln['d']) < TIE      # разница есть, но мелкая: на странице не горит
            ln['cls'] = 'scarce' if scarce else 'over' if over else 'need' if cap is not None else 'grow'
            if crossed is not None:
                # Порог автора берёт только одна из вещей: строка встаёт к редким на месте своего стата и решает,
                # как они, — но не мерой разницы, а самим порогом («дух скипетра от 120»: 123 против 100).
                ln.update(floor=_num(crossed), delta=1 if b > a else -1, minor=False, cls='floor')
            (rare if scarce or crossed is not None else common).append(ln)
        lines = first + rare + common       # внутри каждой группы — порядок билда
        verdict, score = None, 0.0
        for ln in lines:
            if ln['cls'] == 'floor' or (ln['cls'] in ('base', 'scarce') and abs(ln['d']) >= TIE):
                if verdict is None:
                    verdict = 'better' if (ln['delta'] if ln['cls'] == 'floor' else ln['d']) > 0 else 'worse'
                    ln['decides'] = True
            else:
                score += ln['d']     # мелкая разница редкого стата идёт в общий счёт
        if verdict is None:
            verdict = 'better' if score >= TIE else 'worse' if score <= -TIE else 'same'
        return verdict, lines, score, same

    bare_old, bare_new = itemstats.bare(old), itemstats.bare(new)
    if mixed:
        # новая вещь с защитой базы надетой против надетой, без вставок: ответ, счёт и стат, который решил
        v, ls, s, _ = judge(bare_old, on_base(cat, entry['item'], bare_old, item, bare_new), True)
        even = {'verdict': v, 'score': round(s, 2), 'by': next((ln['id'] for ln in ls if ln.get('decides')), None)}
    verdict, lines, score, same, how = decide(bare_old, bare_new, True)
    by_kind = how == 'kind'
    if how == 'even':
        # ответ дал второй расчёт: строки первого его не решали (броня базы, которая «решила» бы, — как раз то,
        # что в зачёт не пошло), обводить их нечего
        for ln in lines:
            ln.pop('decides', None)
    # Как база: новая вещь проще надетой, надеть её сейчас не стоит, а база у неё лучше — её стоит оставить под
    # крафт. Сравниваются одни базы — какими были бы обе вещи белыми (base_only), с базой по имени из плана и, когда
    # базы почти равны, с родом, который план ждёт в слоте. Сказано рядом с ответом, только когда «лучше».
    basis = None
    if rich == 'worse' and verdict != 'better':
        bv, bl, bs, _ = judge(base_only(cat, entry['item'], bare_old), base_only(cat, item, bare_new), True)
        basis = 'better' if settle(bv, bl, bs)[0] == 'better' else None
    if kind:
        # строка базы по плану — сразу за базой, названной по имени; пока она ничего не решила, она тихая
        at = sum(1 for ln in lines if ln['cls'] == 'base')
        lines = lines[:at] + [dict(kind, decides=by_kind, minor=not by_kind)] + lines[at:]
    runes = None
    if gives_old or gives_new:
        order = (cat.get('stats') or {}).get('order') or list(table)

        def rows(gives):
            return [{'id': sid, 'short': (names.get(sid) or (sid, sid))[1], 'value': _num(gives[sid]),
                     'unit': table[sid].get('unit') or ''} for sid in order if gives.get(sid) and sid in table]
        as_is = decide(old, new, False)[0]
        runes = {'now': rows(gives_old), 'new': rows(gives_new),
                 'sockets': [old.get('sockets') or 0, new.get('sockets') or 0],
                 # с тем, что вставлено сейчас, ответ другой — только тогда о вставках и стоит говорить
                 'verdict': as_is if as_is != verdict else None}
    if entry and signature(entry['item']) == signature(item):
        verdict = 'worn'
        if runes:
            runes['verdict'] = None
    return {'verdict': verdict, 'lines': lines, 'score': round(score, 2),
            # статы билда, которые на обеих вещах одинаковы: строкой не показаны
            'same': same,
            # сколько строк заметно лучше и хуже (мелкие разницы не в счёт)
            'up': sum(1 for ln in lines if ln['delta'] > 0 and not ln['minor']),
            'down': sum(1 for ln in lines if ln['delta'] < 0 and not ln['minor']),
            'runes': runes,
            # вещи разной редкости: ответ при одной защите баз (новая с защитой базы надетой) и решил ли он; как
            # база — «better», когда новая проще надетой, надеть её не стоит, а база у неё лучше
            'even': even, 'byEven': how == 'even' and verdict != 'worn',
            'basis': basis if verdict != 'worn' else None,
            'worn': {'name': entry['item'].get('name'), 'base': entry['item'].get('base')} if entry else None}
