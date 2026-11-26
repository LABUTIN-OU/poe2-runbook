# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Sergei Labutin
# Additional terms under GPL-3.0 section 7: see NOTICE.md
"""Хватит ли герою уровня и атрибутов, чтобы надеть вещь из буфера, и не перестанет ли после замены
работать что-то из надетого.

Откуда атрибуты героя. Билд строится на конкретного героя с конкретным деревом, и в дереве каждому узлу
«Характеристика» назначен атрибут. Какой атрибут игрок взял в таком узле на самом деле, игра в лог не
пишет, поэтому счёт идёт по плану:

  узел взят и есть в версии дерева текущего этапа — считается тем атрибутом, что ему назначил план
      (свой у узла или атрибут дерева по умолчанию);
  узел взят, а в версии его нет (расхождение с планом) — не считается вовсе;
  игрок сам назвал, что взял в узле (выбор на карте дерева во время игры, хранится в забеге), — считается
      так, как он назвал, в плане узел или нет.

К этому прибавляются атрибуты класса (класс называет билд; не назвал — класс узла старта дерева), узлы с названным атрибутом («+10 к силе»,
восхождение тоже) и свойства запомненных надетых вещей; «N% повышение атрибута» из дерева применяется
к сумме. Самоцвет в гнезде дерева программа не видит — он не считается.

Сверка с игрой. Всё, что на герое надето, и камни умений отмеченного уровня работают — значит, атрибута
у героя не меньше, чем они требуют. Если по счёту выходит меньше, счёт неверен (в узлах взято не то, что
в плане): об этом сказано отдельно, а в ответах по этому атрибуту число заменяется на «не меньше того,
что требует надетое».

Ответы:

  no    — надеть нельзя: уровень героя ниже, атрибута не хватает или игра сама написала в тексте вещи
          «Вы не можете использовать этот предмет»;
  drop  — после замены перестанет работать надетая вещь или камень умения: новая вещь даёт атрибута
          меньше, чем снятая;
  check — может не хватить: числа названы, решает окно героя в игре (так бывает, когда счёт не сошёлся
          с надетым или дело в собственном бонусе вещи);
  ok    — хватает (страница молчит).

Собственный бонус вещи в счёт её же требования здесь не идёт: правило игры на этот счёт не проверено,
берётся осторожный вариант — и об этом сказано словами, когда дело решает именно он.
"""
import attrneed
import buildplan
import core
import itemstats
import treegeo
from i18n import tr

ATTRS = ('str', 'dex', 'int')
WORST = ('no', 'drop', 'check', 'ok')      # от худшего ответа к лучшему


def _total(flat, inc):
    """Атрибут героя по сумме числом и проценту повышения от дерева (округление вниз — осторожное)."""
    return flat * (100 + inc) // 100


def _flat_for(total, inc):
    """Сколько атрибута числом нужно, чтобы с повышением вышло не меньше total."""
    return -(-total * 100 // (100 + inc))


def taken(events):
    """Узлы дерева героя, взятые сейчас, по событиям лога: (основное дерево, восхождение). Узлы атласа
    не в счёт; повторный клик по взятому узлу — назначение набору оружия, узел уже есть."""
    main, asc = {}, {}
    for e in events or []:
        if e.get('type') != 'passive':
            continue
        pid = e.get('id') or ''
        if pid.startswith(core.ATLAS_NODE):
            continue
        box = asc if pid.startswith(core.ASCENDANCY_NODE) else main
        if e.get('op') == 'take':
            box.setdefault(pid, True)
        else:
            box.pop(pid, None)
    return list(main), list(asc)


def tree_state(lines, geo, events, version=None, default=None, picks=None, cls=None, extra=()):
    """Что дерево героя даёт сейчас. version — версия дерева текущего этапа ({nodes: [{id, attr?}]}),
    default — атрибут дерева по умолчанию, picks — {узел: атрибут}, что игрок назвал сам, cls — класс героя
    именем из данных дерева (нет — берётся класс узла старта, от которого растут взятые узлы).
    Возвращает: base — атрибуты класса; flat — прибавки числом (узлы с названным атрибутом и узлы
    «Характеристика» по плану и по выбору игрока); inc — проценты повышения; ease — процент снижения
    требований; nodes — сколько узлов «Характеристика» посчитано за каждым атрибутом; unset — взятые узлы
    «Характеристика», которые не посчитаны (в версии их нет, игрок их не назвал); notes — что не учтено."""
    main, asc = taken(events)
    planned = {n.get('id'): n for n in (version or {}).get('nodes') or []}
    named, unset, count = [], [], {a: 0 for a in ATTRS}
    for i in main + asc:
        generic = any(attrneed.RE_ANY.fullmatch(ln) for ln in (lines or {}).get(i) or [])
        attr = attrneed.attr_id((picks or {}).get(i)) or (
            attrneed.attr_id(planned[i].get('attr')) or attrneed.attr_id(default) if i in planned else None)
        named.append({'id': i, 'attr': attr} if attr else {'id': i})
        if generic and attr:
            count[attr] += 1
        elif generic:
            unset.append(i)
    # узлы с надетых предметов (зачарование амулета; extra — их id): дают то же, что взятые очком
    named += [{'id': i} for i in extra or () if i not in main and i not in asc]
    gives = attrneed.tree_gives(named, lines)
    base, src = attrneed.class_base({'hero': {'class': cls}}, geo, [{'id': i} for i in main])
    kinds = (geo or {}).get('kind') or {}
    notes = []
    if src is None:
        notes.append(tr('класс героя не назван ни логом, ни билдом и по дереву не найден — его атрибуты не посчитаны'))
    if any(kinds.get(i) == treegeo.SOCKET for i in main):
        notes.append(tr('самоцвет в гнезде дерева не учтён'))
    for node, line in gives['odd']:
        notes.append(tr('узел дерева не учтён: %s') % line)
    return {'base': base, 'flat': gives['flat'], 'inc': gives['inc'], 'ease': gives['ease'], 'nodes': count,
            'unset': unset, 'notes': notes}


def bounds(tree, gear, proof, blind=()):
    """Атрибуты героя по счёту и сверка с тем, что уже работает. tree — tree_state, gear — {место: {атрибут:
    число}} с запомненных надетых вещей, proof — {атрибут: (число, что этого требует)}: столько у героя
    наверняка есть; blind — названия слотов, где вещь надета, а программа её не видела.
    Возвращает {'attrs': {атрибут: {inc, value, lo_flat, hi_flat, lo, hi}}, 'conflict': {атрибут: (число,
    что его требует)}, 'notes'}: value — атрибут по счёту; lo и hi — с чем считать ответ: обычно это то же
    число, а когда счёт меньше доказанного — «не меньше доказанного» без верхней границы (hi None)."""
    notes = list(tree['notes'])
    if tree['unset']:
        notes.append(tr('узлов «Характеристика» вне плана без названного атрибута: %d — не посчитаны') % len(tree['unset']))
    if blind:
        notes.append(tr('надетое не запомнено и не посчитано: %s') % ', '.join(blind))
    out, conflict = {}, {}
    for a in ATTRS:
        inc = tree['inc'][a]
        flat = tree['base'][a] + tree['flat'][a] + sum((s or {}).get(a, 0) for s in gear.values())
        value = _total(flat, inc)
        need, by = (proof or {}).get(a) or (0, None)
        if value < need:
            conflict[a] = (need, by)
            lo, hi = _flat_for(need, inc), None
        else:
            lo = hi = flat
        out[a] = {'inc': inc, 'value': value, 'lo_flat': lo, 'hi_flat': hi, 'lo': _total(lo, inc), 'hi': None if hi is None else _total(hi, inc)}
    return {'attrs': out, 'conflict': conflict, 'notes': notes}


def gem_proofs(cat, plan, view, ease=0):
    """Камни умений, которые у героя в ходу, и чего они требуют: [(название, {атрибут: число})]. Умение —
    то, что отмечено взятым; уровень камня — отмеченная ступень (нет отметок — стартовый уровень)."""
    rules = (cat or {}).get('rules') or {}
    by_id = {g['id']: g for g in plan.get('goals') or []}
    out = []
    for r in (view or {}).get('holders') or []:
        have = (r.get('base') or {}).get('have')
        if r.get('slot') or not have:
            continue
        weights = attrneed.gem_weights(cat, have.get('title'))
        if not weights:
            continue
        first = (by_id.get(have.get('id')) or {}).get('gemFrom')
        level = first if core.is_int(first) else 0
        for p in r.get('parts') or []:
            h = p.get('have') or {}
            if h.get('part') == 'level' and str(h.get('title')).isdigit():
                level = max(level, int(h['title']))
        need = attrneed.gem_need(rules, weights, level) if level else None
        if need:
            out.append((tr('%s · камень %d ур.') % (have.get('title'), level),
                        {a: -(-n * (100 - min(ease, 100)) // 100) for a, n in need.items()}))
    return out


def _span(lo, hi):
    return tr('от %d') % lo if hi is None else '%d' % lo if lo == hi else '%d–%d' % (lo, hi)


def judge(b, need, own, old, others, hero_level=None, unusable=False, names=None, told=False):
    """Ответ по вещи. b — атрибуты героя (bounds); need — требования вещи ({'level', 'str', …}); own —
    атрибуты, которые она сама даёт; old — атрибуты, которые даёт вещь, которую она сменит; others —
    [(название, {атрибут: требование})]: что остаётся надетым, и камни умений; hero_level — уровень героя;
    unusable — игра сама написала, что вещью пользоваться нельзя; names — как назвать атрибут; told —
    клиент такую строку пишет (её уже видели): раз у этой вещи её нет, надеть вещь можно, и о её
    собственных требованиях гадать незачем.
    Возвращает {'state': no | drop | check | ok, 'lines': [что сказать]}."""
    names = names or {}
    said = []               # (ответ, строка)
    level = need.get('level') or 0
    fits = told and not unusable        # игра промолчала, а молчать она не стала бы
    if hero_level and level > hero_level and not fits:
        said.append(('no', tr('с %d уровня героя (сейчас %d)') % (level, hero_level)))
    for a in ATTRS:
        x, word = b['attrs'][a], names.get(a) or a
        was, got = (old or {}).get(a, 0), (own or {}).get(a, 0)

        def rng(delta):
            """Атрибут после замены: delta — что прибавилось числом. (от, до); до None — сверху не знаем."""
            return (_total(x['lo_flat'] + delta, x['inc']),
                    None if x['hi_flat'] is None else _total(x['hi_flat'] + delta, x['inc']))

        bare, full = rng(-was), rng(got - was)      # без бонуса самой вещи и с ним
        sure = full[0] == full[1]                   # счёт сошёлся с надетым: число, а не граница
        r = 0 if fits else need.get(a) or 0
        if r:
            if full[1] is not None and full[1] < r:
                said.append(('no', tr('%s: нужно %d, у героя %s%d') % (word, r, '' if sure else tr('не больше '), full[1])))
            elif bare[0] < r:
                if got and full[0] >= r:
                    said.append(('check', tr('%s: нужно %d — хватит только с её собственным бонусом +%d') % (word, r, got)))
                else:
                    said.append(('check', tr('%s: нужно %d, у героя %s') % (word, r, _span(*bare))))
        if was > got:
            # вещь даёт атрибута меньше, чем снятая: хватит ли остатка тому, что остаётся работать —
            # спрашиваем у самого требовательного
            name, q = max(((n, q.get(a) or 0) for n, q in others), key=lambda t: t[1], default=(None, 0))
            if q and full[0] < q:
                if full[1] is not None and full[1] < q:
                    said.append(('drop', tr('перестанет работать «%s»: %s %d, останется %s%d') % (
                        name, word, q, '' if sure else tr('не больше '), full[1])))
                else:
                    said.append(('check', tr('%s после замены %s: «%s» требует %d') % (word, _span(*full), name, q)))
    if unusable and not any(s == 'no' for s, _ in said):
        said.insert(0, ('no', tr('игра пишет: этим предметом пользоваться нельзя')))
    said.sort(key=lambda t: WORST.index(t[0]))
    return {'state': said[0][0] if said else 'ok', 'lines': [text for _, text in said]}


def hero_state(cat, plan, view, events, worn, places, lines, geo, version=None, default=None, picks=None, blind=(), lang='ru',
               cls=None, extra=()):
    """Всё о герое, что нужно ответу по вещи. places — {слот: место} того, что герой носит на текущем шаге
    (herostats.hero_keys), worn — память надетого забега ({место: {item}}), view — состояние забега
    (уровень героя, умения с уровнями камней), events — события лога (узлы дерева), lines и geo — данные
    дерева, version и default — версия дерева текущего этапа и атрибут дерева по умолчанию, picks — что
    игрок назвал сам, blind — слоты с незапомненной надетой вещью, cls — класс героя, каким его показал лог
    (именем из данных дерева): герой забега — тот, кем играют, а не тот, кого назвал билд; класс из билда
    берётся, только пока лог героя не назвал (до второго уровня)."""
    mine = []               # (место, название, требования, что даёт)
    for place in sorted(set(places.values())):
        entry = (worn or {}).get(place) or {}
        p = itemstats.passport(cat, entry.get('item'))
        if p is not None:
            it = entry['item']
            mine.append((place, it.get('base') or it.get('name') or place,
                         {a: n for a, n in p['req'].items() if a in ATTRS and n},
                         {a: p['stats'].get(a, 0) for a in ATTRS}))
    tree = tree_state(lines, geo, events, version, default, picks, cls or (plan.get('hero') or {}).get('class'), extra)
    gems = gem_proofs(cat, plan, view, tree['ease'])
    proof = {}
    for name, req in [(m[1], m[2]) for m in mine] + gems:
        for a, n in req.items():
            if n > proof.get(a, (0, None))[0]:
                proof[a] = (n, name)
    return {'mine': mine, 'gems': gems, 'tree': tree, 'proof': proof,
            'b': bounds(tree, {m[0]: m[3] for m in mine}, proof, blind),
            'names': {a['id']: a['name'] for a in buildplan.attributes(cat, lang)},
            'level': ((view or {}).get('hero') or {}).get('level'), 'picks': dict(picks or {})}


def hero_view(state):
    """Атрибуты героя для страницы: attrs — по атрибуту {id, name, value — по счёту, need и by — сколько
    требует надетое или камень и что именно, low — счёт меньше этого (в узлах взято не то, что в плане),
    nodes — сколько узлов «Характеристика» посчитано за атрибутом}; unset — взятые узлы «Характеристика»
    без атрибута; picks — что игрок назвал сам; notes — что не учтено."""
    b, tree = state['b'], state['tree']
    attrs = []
    for a in ATTRS:
        need, by = state['proof'].get(a) or (0, None)
        attrs.append({'id': a, 'name': state['names'].get(a) or a, 'value': b['attrs'][a]['value'], 'need': need, 'by': by,
                      'low': a in b['conflict'], 'nodes': tree['nodes'][a]})
    return {'attrs': attrs, 'unset': list(tree['unset']), 'picks': state['picks'], 'notes': b['notes']}


def describe(cat, state, key, item, told=False):
    """Ответ по вещи из буфера для слота, чья память надетого — место key. state — hero_state; told —
    клиент пишет в тексте вещи, что ею пользоваться нельзя (такую строку уже видели). None — вещь не
    опознана или нет таблицы статов. В ответе, кроме state и lines, — hero ({атрибут: {lo, hi}}: с чем
    считался ответ) и notes (что не учтено)."""
    new = itemstats.passport(cat, item)
    if new is None:
        return None
    mine, b = state['mine'], state['b']
    out = judge(b, new['req'], {a: new['stats'].get(a, 0) for a in ATTRS},
                next((m[3] for m in mine if m[0] == key), {}),
                [(m[1], m[2]) for m in mine if m[0] != key] + state['gems'],
                state['level'], bool(item.get('unusable')), {a: n.lower() for a, n in state['names'].items()}, told)
    out['hero'] = {a: {'lo': x['lo'], 'hi': x['hi']} for a, x in b['attrs'].items()}
    out['notes'] = b['notes'] + [tr('%s по счёту %d, а «%s» требует %d — в узлах взято не то, что в плане') % (
        (state['names'].get(a) or a).lower(), b['attrs'][a]['value'], by, need) for a, (need, by) in b['conflict'].items()]
    return out
