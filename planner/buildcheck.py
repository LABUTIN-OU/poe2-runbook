# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Sergei Labutin
# Additional terms under GPL-3.0 section 7: see NOTICE.md
"""Проверка гайда целиком — раздел «Проверка билда» на вкладке «Билд» редактора плана.

Собирает в один список всё, что в плане не сходится, по тому плану, какой сейчас на странице (со всеми
несохранёнными правками): так автор видит, что не так, ещё до записи. Замечание — {kind, level, text,
detail?, tab?, goal?, step?, what?, where?}:

  kind   — о чём оно: plan — план записан не так (то, что помешает его сохранить или прочитать);
           route — шаг маршрута, который не наступит сам (зона повторяется в соседних шагах);
           hero — класс и вознесение; tree — дерево; attr — не хватает атрибута камню или вещи (attrneed);
           game — шаг цели раньше, чем игра вообще может это дать (камень нужного уровня, база ещё не падают;
           ступень восхождения), и восхождение сверх четырёх или не на испытании;
           luck — срок цели по стату на удачу: её порог берётся только случайным броском, и в среднем до него
           больше craftplan.LUCK белых баз (craftplan.odds);
           data — в данных игры нет того, что нужно для проверки;
  level  — bad: надо править; note — к сведению;
  tab    — вкладка страницы, где это правят (класс и вознесение — «Билд», узлы дерева — «Дерево», какая
           версия на каком этапе — «Этапы»); goal — цель, о которой речь (страница покажет замечание и прямо у неё); what — что
           это за цель; where — к концу какого шага или с какого этапа; step — шаг, о котором речь (у замечаний маршрута
           страница покажет замечание под самим шагом).

Чего здесь нет: забега. Проверяется план — то, что автор написал, а не то, что надето на герое сейчас
(это дело страницы маршрута: wearcheck).
"""
import attrneed
import buildstage
import core
import craftplan
import gamedata
import herostats
import i18n
from i18n import tr

MAX_SHOWN = 6       # сколько названий перечислять в одном замечании


def _list(names):
    names = list(names)
    return ', '.join('«%s»' % n for n in names[:MAX_SHOWN]) + (tr(' и ещё %d') % (len(names) - MAX_SHOWN) if len(names) > MAX_SHOWN else '')


def _step_words(g, name):
    """Шаг цели — тем словом, каким его поле названо в редакторе: умение «надеть», камень поддержки «вставить»
    (раньше своего шага их не ждут); у остального «не позже» — его ищут и раньше шага."""
    kind = (g or {}).get('kind')
    if kind == 'skill':
        return tr('надеть «%s»') % name
    if kind == 'support':
        return tr('вставить «%s»') % name
    return tr('не позже «%s»') % name


def hero_findings(plan, geo, names=None):
    """Класс и вознесение героя: назван ли класс, есть ли такие в данных дерева. names — названия классов
    и вознесений на языке страницы ({имя из данных: название})."""
    classes = (geo or {}).get('classes') or {}
    hero = plan.get('hero') or {}
    cls, asc = hero.get('class'), hero.get('ascendancy')
    own = lambda x: (names or {}).get(x) or x   # noqa: E731
    out = []
    if not cls:
        out.append({'kind': 'hero', 'level': 'note', 'tab': 'build',
                    'text': tr('Класс героя не назван — стартовые атрибуты взяты по узлу старта, от которого растёт дерево')})
    elif classes and cls not in classes:
        out.append({'kind': 'hero', 'level': 'bad', 'tab': 'build', 'text': tr('Класса героя «%s» нет в данных дерева') % cls})
    if asc and not cls:
        out.append({'kind': 'hero', 'level': 'bad', 'tab': 'build', 'text': tr('Восхождение названо, а класс героя — нет')})
    elif asc and cls in classes and asc not in [a['name'] for a in classes[cls].get('ascendancies') or []]:
        out.append({'kind': 'hero', 'level': 'bad', 'tab': 'build',
                    'text': tr('У класса «%s» нет восхождения «%s»') % (own(cls), own(asc))})
    return out


def tree_findings(plan, tree_lines, geo):
    """Дерево героя: растёт ли каждая версия, названная этапом, от старта класса билда; узлы
    «Характеристика» без назначенного атрибута; узлы, которые расчёт атрибутов не понимает; версии,
    которые не назвал ни один этап; этап без дерева."""
    classes = (geo or {}).get('classes') or {}
    cls = (plan.get('hero') or {}).get('class')
    want = (classes.get(cls) or {}).get('start')
    phases = (plan.get('tree') or {}).get('phases') or []
    used = set(buildstage.users(plan, 'tree'))
    # запасная версия (without) действует вместо той, что назвал этап, пока узла с амулета нет — она тоже в ходу
    by_id = {ph.get('id'): ph for ph in phases}
    for vid in list(used):
        seen = set()
        while vid in by_id and vid not in seen and isinstance(by_id[vid].get('without'), str):
            seen.add(vid)
            vid = by_id[vid]['without']
            used.add(vid)
    default = (plan.get('tree') or {}).get('attr')
    out = []
    stages = plan.get('stages') or []
    if stages and phases and not stages[0].get('tree'):
        out.append({'kind': 'tree', 'level': 'bad', 'tab': 'stages',
                    'text': tr('Этап «%s» не назвал версию дерева — до первого этапа с деревом атрибуты считаются без него')
                            % (stages[0].get('name') or stages[0]['id'])})
    for ph in phases:
        name = ph.get('name') or ph['id']
        if ph['id'] not in used:
            out.append({'kind': 'tree', 'level': 'note', 'tab': 'stages',
                        'text': tr('Версию дерева «%s» не назвал ни один этап — она нигде не действует') % name})
            continue
        nodes = ph.get('nodes') or []
        start = attrneed.class_start(nodes, geo)
        if want and nodes and start != want:
            out.append({'kind': 'tree', 'level': 'bad', 'tab': 'tree',
                        'text': tr('Дерево «%s» растёт не от старта класса героя') % name if start
                                else tr('Дерево «%s»: не найден узел у старта класса — растёт ли оно от старта, не видно') % name})
        gives = attrneed.tree_gives(nodes, tree_lines, default)
        if gives['free']:
            out.append({'kind': 'tree', 'level': 'bad', 'tab': 'tree',
                        'text': tr('Дерево «%s»: узлов «Характеристика» без назначенного атрибута — %d; в счёт атрибутов они не идут')
                                % (name, gives['free'])})
        for node, line in gives['odd']:
            out.append({'kind': 'tree', 'level': 'note', 'tab': 'tree',
                        'text': tr('Дерево «%s»: узел «%s» в счёте атрибутов не учтён') % (name, node), 'detail': line})
    for ph in (plan.get('atlas') or {}).get('phases') or []:
        if ph['id'] not in buildstage.users(plan, 'atlas'):
            out.append({'kind': 'tree', 'level': 'note', 'tab': 'stages',
                        'text': tr('Версию атласа «%s» не назвал ни один этап — она нигде не действует') % (ph.get('name') or ph['id'])})
    # Атлас есть только на картах (факт игры): версию атласа называет этап, который начинается на картах.
    steps = plan.get('steps') or []
    end_at = core.endgame_from(steps)
    at = {s.get('id'): k for k, s in enumerate(steps) if isinstance(s, dict)}
    for n, st in enumerate(stages):
        start = at.get(st.get('from')) if n else 0
        if st.get('atlas') and start is not None and (end_at is None or start < end_at):
            out.append({'kind': 'tree', 'level': 'bad', 'tab': 'stages',
                        'text': tr('Этап «%s» начинается до карт, а атлас есть только на картах — версию атласа называет этап, '
                                   'который начинается на картах') % (st.get('name') or st['id'])})
    return out


def route_findings(plan):
    """Маршрут: шаги с зоной, которая в маршруте уже была. Программа ведёт шаги по зонам (core.derive): вход
    в зону ищет ближайший шаг ВПЕРЕДИ с такой зоной, поэтому одна зона может стоять в нескольких шагах. Зона
    текущего шага — его собственная или из «ещё зоны» — шаг не меняет, а шаг повторного захода (его зона уже была
    раньше) наступает только следующим: заход в его зону с дальнего шага — ради прежней цели, а не прыжок вперёд.
    Поэтому остаётся одно замечание — надо править: зона шага значится у шага прямо перед ним — с него в эту зону
    и входят, а программа останется на нём: шаг сам не наступит. Стоит у этого шага.
    Замечание называет шаг (step — его id): страница ставит замечание и под самим шагом. В порядке шагов."""
    steps = [s for s in plan.get('steps') or [] if isinstance(s, dict) and s.get('id')]
    name = lambda s: s.get('name') or s['id']                                   # noqa: E731
    zones = lambda s: [s.get('zone')] + list(s.get('also') or [])                # noqa: E731
    out = []
    for k, s in enumerate(steps):
        z = s.get('zone')
        if not z:
            continue
        if k and z in zones(steps[k - 1]):
            prev = steps[k - 1]
            text = (tr('Шаг сам не наступит: у него та же зона, что у шага «%s» перед ним, — программа останется на том шаге')
                    if prev.get('zone') == z else
                    tr('Шаг сам не наступит: его зона стоит в «ещё зоны» шага «%s» перед ним — программа останется на том '
                    'шаге. Уберите её оттуда')) % name(prev)
            out.append({'kind': 'route', 'level': 'bad', 'tab': 'route', 'step': s['id'], 'what': name(s), 'text': text})
    return out


def step_reach(cat, steps, zones=None):
    """Старший уровень боевой зоны, какой герой видел к концу каждого шага: список по шагам из пар (уровень — None,
    пока ни одной; подтверждён ли он). Уровень зоны — какой видели забеги (zones: код зоны -> младший из виденных
    уровней): у зон, чей уровень растёт с порядком прохождения (ветки второго акта, острова четвёртого, интерлюдии),
    он выше, чем в данных игры. Зона, где забеги не бывали, — по данным игры: это младший уровень зоны, настоящий
    бывает выше; с такой зоны уровень к шагу уже не подтверждён. Уровень шага карт (level) — уровень путевого
    камня. Зоны шага — его зона и «ещё зоны»; города не в счёт: их уровень в данных игры выше окрестных зон."""
    areas, top, sure, out = (cat or {}).get('areas') or {}, None, True, []
    for s in steps:
        for code in [s.get('zone')] + list(s.get('also') or []):
            a = areas.get(code) if isinstance(code, str) else None
            if isinstance(a, dict) and a.get('town'):
                continue
            seen = (zones or {}).get(code) if isinstance(code, str) else None
            lv = seen if core.is_int(seen) else (a or {}).get('level')
            if not (core.is_int(lv) and lv > 0):
                continue
            sure = sure and core.is_int(seen)
            top = max(top or 0, lv)
        if core.is_int(s.get('level')):
            top = max(top or 0, s['level'])
        out.append((top, sure))
    return out


def game_findings(cat, plan, zones=None):
    """Цели, чей шаг раньше, чем игра вообще может это дать: неогранённый камень нужного уровня (умения, духа,
    поддержки, уровня камня) или база предмета падают только в зонах старше, чем герой видит к концу шага. Такой
    срок не выполнить без вины игрока: страница забега горела бы опозданием. Камень и вещь с редкого чудовища
    бывают на два уровня выше зоны (core.DROP_ABOVE); камень уровня выше нужного тоже годится (из него делают и
    младший). Умение, которое даёт предмет, приходит с ним — его камня не ищут. Уровни зон — step_reach."""
    steps = [s for s in plan.get('steps') or [] if isinstance(s, dict) and s.get('id')]
    uncut = ((cat or {}).get('rules') or {}).get('uncut') or {}
    if not steps or not uncut:
        return []
    reach = step_reach(cat, steps, zones)
    at = {s['id']: k for k, s in enumerate(steps)}
    name = lambda k: steps[k].get('name') or steps[k]['id']   # noqa: E731
    gems = {}
    for g in ((cat or {}).get('gems') or {}).values():
        if isinstance(g, dict) and g.get('name') and core.is_int(g.get('level')) and g['level'] >= 1:
            gems.setdefault((g['name'], g.get('type') == 'support'), g)
    goals = {g['id']: g for g in plan.get('goals') or [] if isinstance(g, dict) and g.get('id')}

    def first(zone):
        """Первый шаг, к концу которого то, что падает с зоны такого уровня, уже могло выпасть (None — ни на каком)."""
        return next((k for k, (top, _) in enumerate(reach) if top is not None and top + core.DROP_ABOVE >= zone), None)

    def gem_zone(table, level):
        """Младший уровень зоны, где падает неогранённый камень такого уровня или выше."""
        zones_up = [z for lv, z in (table or {}).items() if str(lv).isdigit() and int(lv) >= level and core.is_int(z)]
        return min(zones_up) if zones_up else None

    def skill_table(sk):
        gem = gems.get((gamedata.english(sk.get('title')), False)) or {}
        return ('spirit', tr('неогранённый камень духа %d уровня')) if gem.get('type') == 'spirit' \
            else ('skill', tr('неогранённый камень умения %d уровня'))

    out = []
    for g in goals.values():
        need = at.get(g.get('need'))
        if need is None:
            continue
        sk = goals.get(g.get('for')) if g.get('for') else None
        what, zone = None, None
        if g.get('kind') == 'skill' and core.is_int(g.get('gemFrom')) and not g.get('grantedBy'):
            key, words = skill_table(g)
            what, zone = words % g['gemFrom'], gem_zone(uncut.get(key), g['gemFrom'])
        elif g.get('kind') == 'support' and sk is not None:
            gem = gems.get((gamedata.english(g.get('title')), True))
            if gem:
                what, zone = tr('неогранённый камень поддержки %d уровня') % gem['level'], gem_zone(uncut.get('support'), gem['level'])
        elif g.get('part') == 'level' and sk is not None and str(g.get('title')).isdigit() and not sk.get('grantedBy'):
            key, words = skill_table(sk)
            what, zone = words % int(g['title']), gem_zone(uncut.get(key), int(g['title']))
        elif g.get('slot') and not g.get('part') and core.is_int(g.get('opens')) and g['opens'] > 1:
            what, zone = tr('эта база'), g['opens']
        if what is None or zone is None:
            continue
        k = first(zone)
        if k is not None and k <= need:
            continue
        # подпись — из частей: на странице каждая на языке страницы (слово программы, число, название умения из плана)
        title = str(g.get('title') or g['id'])
        if g.get('part') == 'level':
            title = i18n.join(' ', [tr('уровень камня'), title])
        if sk is not None:
            title = i18n.join(' → ', [title, sk.get('title') or sk['id']])
        text = (tr('Так рано не получить: %s падает только с шага «%s»') % (what, name(k)) if k is not None
                else tr('Не получить: %s не падает ни на одном шаге маршрута') % what)
        found = {'kind': 'game', 'level': 'bad', 'tab': 'items' if g.get('slot') else 'gems', 'goal': g['id'],
                 'what': title, 'where': _step_words(g, name(need)), 'text': text}
        if not reach[need][1]:
            # уровень зон к этому шагу — только по данным игры (младший): настоящий может быть выше — к сведению
            found.update(level='note', detail=tr('уровень зон — по данным игры: герои здесь ещё не были, настоящий бывает выше'))
        out.append(found)
    return out


def ascension_findings(cat, plan, zones=None):
    """Восхождения плана — по правилам игры. Какое восхождение по счёту, программа считает сама по порядку маршрута
    (core.norm_plan), поэтому «третье раньше второго» не бывает. Проверяется остальное. Восхождений в игре четыре. Ступень
    N дают испытания не младше её уровня зоны (levels записи справочника: Сехем 1–4 этажа, Хаос 4–10 испытаний и Мастер
    испытаний): маршрут к шагу восхождения должен до такого уровня дойти (step_reach) — бария и ультиматум падают с
    уровнем зоны; ступень, на которую игра даёт гарантированную барию (early записи: Элзара — третья), можно и раньше,
    если её запись в плане до шага восхождения. Берут восхождение на испытании (зоны записи) или на картах (шаг по уровню
    зоны) — где-то ещё к сведению.
    Шаг, который наступает по событию «N-е восхождение», стоит после N-го восхождения плана — иначе сам не наступит."""
    steps = [s for s in plan.get('steps') or [] if isinstance(s, dict) and s.get('id')]
    at = {s['id']: k for k, s in enumerate(steps)}
    name = lambda k: steps[k].get('name') or steps[k]['id']   # noqa: E731
    asc = sorted((g for g in plan.get('goals') or [] if isinstance(g, dict) and g.get('kind') == 'ascension'
                  and g.get('need') in at), key=lambda g: (at[g['need']], g.get('ascend') or 0))
    reach = step_reach(cat, steps, zones) if asc else []
    out = []
    for g in asc:
        k, i = g.get('ascend'), at[g['need']]
        if not core.is_int(k):
            continue
        base = {'kind': 'game', 'tab': 'route', 'goal': g['id'], 'what': str(g.get('title') or g['id']),
                'where': tr('шаг «%s»') % name(i)}
        if k > core.ASCENSIONS:
            out.append(dict(base, level='bad', text=tr('Восхождений в игре четыре: это уже %d-е — лишнее') % k))
            continue
        levels = g.get('levels') or []
        lv = levels[k - 1] if k <= len(levels) and core.is_int(levels[k - 1]) else None
        # ступень раньше её уровня: гарантированная бария (Элзара — на третье), если запись в плане раньше этого шага
        gift = (g.get('early') or {}).get(str(k)) if isinstance(g.get('early'), dict) else None
        if gift and any(x.get('id') == gift and at.get(x.get('need'), len(steps)) <= i for x in plan.get('goals') or []
                        if isinstance(x, dict)):
            lv = None
        top, sure = reach[i]
        if lv and (top is None or top < lv):
            found = dict(base, level='bad', text=tr('Так рано не взять: эту ступень дают испытания от %d уровня зоны, а маршрут '
                                                    'к этому шагу доходит до зоны %d') % (lv, top or 0))
            if not sure:
                found.update(level='note', detail=tr('уровень зон — по данным игры: герои здесь ещё не были, настоящий бывает выше'))
            out.append(found)
        s = steps[i]
        trials = set(g.get('zones') or ())
        if trials and not core.is_int(s.get('level')) and not trials & set([s.get('zone')] + list(s.get('also') or [])):
            out.append(dict(base, level='note', text=tr('Восхождение берут на Испытании Сехем или Испытании Хаоса — в зонах '
                                                        'этого шага испытания нет')))
    for i, s in enumerate(steps):
        if s.get('event') in core.STEP_EVENTS:
            n = core.STEP_EVENTS.index(s['event']) + 1
            have = sum(1 for g in asc if at[g['need']] < i)
            if have < n:
                out.append({'kind': 'route', 'level': 'bad', 'tab': 'route', 'step': s['id'], 'what': name(i),
                            'text': tr('Шаг наступит сам, когда герой возьмёт %s, а восхождений до него в плане: %d')
                            % (core.ASC_WORDS[n - 1], have)})
    return out


def luck_findings(cat, plan, lang='ru'):
    """Сроки на удачу: цель по стату со сроком, чей порог на предмете слота берётся только случайным броском
    (craftplan.odds: ловля на белой базе в лучшем окне уровня), а в среднем до него больше craftplan.LUCK белых баз.
    Срок программа не меняет и менять не предлагает — это решение автора; замечание называет цену числами. Стоит
    у цели (goal) и в общей проверке. Порог про сумму на предмете («дух от 120»), порог, который наверняка даёт
    сущность, и цель без срока — не сюда."""
    if not (cat or {}).get('craft'):
        return []
    steps = plan.get('steps') or []
    idx = {s['id']: i for i, s in enumerate(steps)}
    names = herostats._names(cat, lang)
    ats, out = {}, []
    for g in plan.get('goals') or []:
        if (not isinstance(g, dict) or not g.get('slot') or not g.get('stat') or g.get('need') not in idx
                or isinstance(g.get('min'), bool) or not isinstance(g.get('min'), (int, float))):
            continue
        pos = idx[g['need']]
        if pos not in ats:
            ats[pos] = herostats.at_step(cat, plan, pos)
        res = craftplan.odds(cat, ats[pos], g)
        if not res or res['bases'] <= craftplan.LUCK:
            continue
        text, detail = craftplan.luck_text(cat, res, lang)
        label = g.get('label') or (names.get(g['stat']) or [g['stat']])[0].lower()
        out.append({'kind': 'luck', 'level': 'bad', 'tab': 'items', 'goal': g['id'],
                    'what': i18n.join(' ', [x for x in (label, g.get('title')) if x]),
                    'where': _step_words(g, steps[pos].get('name') or steps[pos]['id']),
                    'text': text, 'detail': detail})
    return out


def run(cat, plan, tree_lines, geo, problems=(), lang='ru', zones=None):
    """Все замечания к плану списком — в порядке: план, выбор, герой, дерево, атрибуты, игра, сроки на удачу, данные. problems — то,
    что сказала сборка плана (core.norm_plan и остальные): строки. zones — уровни зон, какими их видели забеги
    (step_reach): код зоны -> уровень."""
    names = (((cat or {}).get('lang') or {}).get(lang) or {}).get('heroClasses') or {}
    out = [{'kind': 'plan', 'level': 'bad', 'text': p} for p in problems]
    # награда с выбором, у которой автор ещё не назвал вариант: выбор за него никто не делает — это несделанное
    steps = {s['id']: s.get('name') or s['id'] for s in plan.get('steps') or []}
    for g in plan.get('goals') or []:
        if g.get('unpicked'):
            out.append({'kind': 'choice', 'level': 'bad', 'tab': 'route', 'goal': g['id'],
                        'what': str(g.get('title') or g['id']).rsplit(': ', 1)[0], 'text': tr('У награды с выбором не назван вариант'),
                        'where': tr('шаг «%s»') % steps.get(g.get('need'), g.get('need'))})
    out += route_findings(plan)
    out += hero_findings(plan, geo, names)
    out += tree_findings(plan, tree_lines, geo)
    short, unknown = attrneed.check(cat, plan, tree_lines, geo, lang)
    by_id = {g['id']: g for g in plan.get('goals') or [] if isinstance(g, dict) and g.get('id')}
    for f in short:
        f['level'] = 'bad'
        f['where'] = (tr('с этапа «%s»') % f['later']) if f.get('later') else _step_words(by_id.get(f['goal']), f['stepName'])
    out += short
    out += game_findings(cat, plan, zones)
    out += ascension_findings(cat, plan, zones)
    out += luck_findings(cat, plan, lang)
    if unknown:
        out.append({'kind': 'data', 'level': 'note', 'tab': 'gems',
                    'text': tr('Нет данных о требованиях камней: %s — их атрибуты не проверены') % _list(u['what'] for u in unknown)})
    return out
