# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Sergei Labutin
# Additional terms under GPL-3.0 section 7: see NOTICE.md
"""Что искать на каждом слоте: где какой стат героя вообще можно получить.

Ценность стата на вещи зависит от того, где ещё его взять. Скорость передвижения бывает только на
сапогах, уровень умений приспешников — на шлеме, амулете и скипетре, а сопротивление — почти на всём:
поэтому сапоги берут за скорость, а сопротивление добирают там, где осталось место. Эта редкость не
задаётся руками — она считается из данных игры (каталог):

  * аффиксы: какие семейства бывают на базе слота, с какого уровня предмета какая ступень;
  * собственные свойства баз этого класса (сопротивление на кольце, сила на амулете);
  * вставки в гнёзда: что руна даёт на вещи этой категории (на доспехе — сопротивление, на оружии —
    урон; у скипетра свой набор).

Сколько слотов несут стат аффиксом — мера его редкости: чем меньше, тем важнее он на каждом из них.

Запуск: python -I planner/slotstats.py [--plan plan.json] [--ilvl 70]
"""
import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import gamedata  # noqa: E402
import planfiles  # noqa: E402
import slotwear  # noqa: E402


def specs_of(raw, cat=None):
    """Слоты билда с описанием базы: [(id, название, описание)]. У слота, где вещи сменяют друг друга
    (оружие: самострел, потом скипетр), — по строке на каждую. У слота с записанными периодами (wear) —
    по строке на каждый класс каждого периода; у слота старого вида описание называет цель вещи (поле gear),
    а с какого шага вещь в ходу — её поле use."""
    out = []
    idx = slotwear.step_index(raw.get('steps'))
    for s in raw.get('slots') or []:
        if slotwear.stated(s):
            seen = set()
            for per in slotwear.periods(s, raw.get('goals') or [], idx):
                for spec in slotwear.specs(cat, per):
                    if (per['from'], spec) not in seen:
                        seen.add((per['from'], spec))
                        out.append(('%s/%s' % (s['id'], per['from'] or ''), '%s · %s' % (s.get('name') or s['id'], spec), spec))
            continue
        if s.get('gear'):
            out.append((s['id'], s.get('name') or s['id'], s['gear']))
        seen = set()
        for g in raw.get('goals') or []:
            if g.get('slot') == s['id'] and g.get('gear') and g['gear'] not in seen:
                seen.add(g['gear'])
                out.append(('%s/%s' % (s['id'], g.get('use') or ''), '%s · %s' % (s.get('name') or s['id'], g['gear']), g['gear']))
    return out


def _own(stat, ids):
    """Свойство из списка, которое идёт в стат: (свойство, меняет ли оно саму вещь) или None."""
    for i in ids:
        if i in (stat.get('ids') or ()):
            return i, False
        if i in (stat.get('local') or ()):
            return i, True
    return None


def carriers(cat, specs, ilvl=None):
    """Где какой стат можно получить: стат -> слот -> {affix, prop, implicit, rune, base}.

    affix — семейства аффиксов, что бывают на базе слота: gen, hybrid (в аффиксе есть и другое
    свойство), local (меняет саму вещь), steps — ступени [уровень предмета, от, до] от слабой к
    сильной, now — сколько из них бывает на вещи уровня ilvl. prop — стат, который база несёт своим
    свойством (броня силовых перчаток): [уровень базы, число] по базам слота. implicit — базы этого
    класса с таким встроенным свойством. rune — вставки, которые дают стат на вещи этой категории.
    base — что даёт сама база молча (штраф скорости нательного доспеха и щита): числа, какие бывают.
    Род базы в описании слота не назван — считается любой род.
    every — у слота несколько описаний базы (в период носят предметы нескольких классов), и стат слот несёт сам
    на любом из них: такой слот несёт стат наверняка; иначе — только если наденут предмет подходящего класса.
    on — классы предметов слота, на которых он несёт стат сам.
    """
    table = (cat.get('stats') or {}).get('stats') or {}
    out = {sid: {} for sid in table}
    described, carried = {}, {}      # слот -> сколько у него описаний базы; (стат, слот) -> классы, где стат несут сами
    for slot_id, _, spec in specs:
        cls, want = gamedata.spec_parts(spec)
        # Род базы в плане не назван («Gloves») — годится любой: тогда берём всё, что бывает хоть на одном
        # роде (броня — на силовых перчатках, энергощит — на перчатках на интеллект).
        sets = gamedata.tag_sets(cat, spec)
        if not sets:
            continue
        described[slot_id] = described.get(slot_id, 0) + 1
        tags = sorted({t for ts in sets for t in ts})
        mine = [b for b in cat['bases'].values() if b['class'] == cls and (want is None or want in b['tags'])]
        for sid, stat in table.items():
            found = {'affix': [], 'implicit': [], 'rune': [], 'base': [], 'prop': []}
            if stat.get('base'):
                # свойство самой базы, которого на вещи не написано: штраф скорости доспеха и щита
                found['base'] = sorted({b[stat['base']] for b in mine if b.get(stat['base'])})
            if stat.get('prop'):
                # стат, который база несёт своим свойством (броня силовых перчаток): [уровень базы, число]
                found['prop'] = sorted([b.get('level') or 0, b['props'][stat['prop']]] for b in mine
                                       if (b.get('props') or {}).get(stat['prop']))
            for fam in cat['mods'].values():
                own = _own(stat, fam['stats'])
                if not own or not fam.get('lines'):
                    continue
                tiers = max((gamedata.tiers(fam, ts) for ts in sets), key=len)
                if not tiers:
                    continue
                j = fam['stats'].index(own[0])
                found['affix'].append({
                    'gen': fam['gen'], 'type': fam['type'], 'hybrid': len(fam['lines']) > 1, 'local': own[1],
                    'steps': [[m['level'] or 0] + list(m['vals'][j]) for m in tiers],
                    'now': sum(1 for m in tiers if ilvl is None or (m['level'] or 0) <= ilvl)})
            for base in mine:
                for mid in base.get('implicits') or ():
                    imp = (cat.get('implicits') or {}).get(mid)
                    own = _own(stat, imp['stats']) if imp else None
                    if own and not own[1]:
                        found['implicit'].append({'base': base['name'], 'level': base.get('level') or 0,
                                                  'vals': imp['vals'][imp['stats'].index(own[0])]})
            for aid, a in (cat.get('augments') or {}).items():
                for category, body in a['on'].items():
                    own = _own(stat, body['stats'])
                    if own and body.get('vals') and gamedata.augment_fits(category, cls, tags):
                        # plain — обычная руна: одна на целый род вещей (любой доспех, любое оружие);
                        # особые руны и ядра душ привязаны к одному классу вещи (только шлем, только сапоги)
                        found['rune'].append({'id': aid, 'name': a.get('name'), 'type': a.get('type'),
                                              'level': a.get('level') or 0, 'local': own[1],
                                              'plain': a.get('type') == 'Rune' and category in gamedata.AUGMENT_BROAD,
                                              'val': body['vals'][body['stats'].index(own[0])]})
            if is_source(found):
                carried.setdefault((sid, slot_id), []).append(cls)
            if any(found.values()):
                have = out[sid].get(slot_id)
                if have is None:
                    out[sid][slot_id] = found
                else:
                    # у слота несколько описаний базы (в период носят предметы разных классов): стат бывает
                    # на слоте, если бывает хоть на одном из них, — источники складываются
                    have['affix'] += found['affix']
                    have['implicit'] += found['implicit']
                    have['rune'] += [r for r in found['rune'] if not any(x['id'] == r['id'] and x['val'] == r['val'] for x in have['rune'])]
                    have['base'] = sorted(set(have['base']) | set(found['base']))
                    have['prop'] = sorted(have['prop'] + [x for x in found['prop'] if x not in have['prop']])
    for sid, slots in out.items():
        for slot_id, found in slots.items():
            on = carried.get((sid, slot_id), [])
            found['every'], found['on'] = len(on) == described.get(slot_id, 0), sorted(set(on))
    return out


def is_source(found):
    """Несёт ли слот стат сам: аффиксом, свойством базы (броня силовых перчаток) или её встроенным
    свойством (сопротивление на кольце). Руны не в счёт: гнёзда — отдельный запас, и руна стихии
    годится в любой доспех."""
    return bool(found and (found['affix'] or found['prop'] or found['implicit']))


def is_sure(found):
    """Несёт ли слот стат наверняка: сам (is_source) и на предмете любого класса, который в нём носят. Слот, где
    стат бывает лишь на части классов (в оружии принимается любой из четырёх, а уровень умений приспешников бывает
    только на скипетре), источником может стать, но в счёт редкости стата не идёт."""
    return is_source(found) and found.get('every', True)


def scarcity(table):
    """Стат -> сколько слотов несут его наверняка (is_sure). Меньше — редче."""
    return {sid: sum(1 for f in slots.values() if is_sure(f)) for sid, slots in table.items()}


def best_step(entry):
    """Лучшая ступень семейства, что бывает на вещи нужного уровня: [уровень, от, до] или None."""
    return entry['steps'][entry['now'] - 1] if entry['now'] else None


def _span(lo, hi):
    return gamedata.num(lo) if lo == hi else '%s–%s' % (gamedata.num(lo), gamedata.num(hi))


def report(cat, raw, ilvl, lang='ru'):
    """Таблица для чтения глазами: по слотам, от редкого стата к частому."""
    specs = specs_of(raw, cat)
    table = carriers(cat, specs, ilvl)
    rare = scarcity(table)
    pack = (cat.get('lang') or {}).get(lang) or {}
    names = pack.get('statNames') or {}
    title = lambda sid: (names.get(sid) or [sid])[0]
    # база — как в клиенте игрока, с английским именем в скобках
    local = lambda en: '%s (%s)' % (pack['bases'][en], en) if (pack.get('bases') or {}).get(en) else en
    lines = ['Где какой стат бывает (аффиксом или свойством базы), уровень предмета %s:' % ilvl]
    for sid in sorted(table, key=lambda s: (rare[s] or 99, s)):
        slots = [name for slot_id, name, _ in specs if is_source(table[sid].get(slot_id))]
        lines.append('  %2d  %-28s %s' % (rare[sid], title(sid), '; '.join(slots) or '— нигде'))
    for slot_id, name, spec in specs:
        lines.append('\n%s  [%s]' % (name.upper(), spec))
        mine = sorted((sid for sid in table if slot_id in table[sid]), key=lambda s: (rare[s] or 99, s))
        for sid in mine:
            f = table[sid][slot_id]
            bits = []
            for a in sorted(f['affix'], key=lambda a: (a['hybrid'], a['gen'])):
                step = best_step(a)
                ladder = ', '.join('%s с ур. %d' % (_span(lo, hi), lv) for lv, lo, hi in a['steps'][-3:])
                bits.append('%s%s%s: сейчас %s (ступени: %s)' % (
                    'префикс' if a['gen'] == 'prefix' else 'суффикс', ' гибрид' if a['hybrid'] else '',
                    ' самого предмета' if a['local'] else '', _span(step[1], step[2]) if step else 'нет', ladder))
            if f['implicit']:
                top = max(f['implicit'], key=lambda i: i['vals'][1] or 0)
                bits.append('собственное: до %s — %s, баз %d' % (_span(*top['vals']), local(top['base']), len(f['implicit'])))
            plain = sorted({(r['val'], r['level']) for r in f['rune'] if r['plain']})
            if plain:
                bits.append('руна: %s' % ', '.join('%s с ур. героя %d' % (gamedata.num(v), lv) for v, lv in plain))
            if f.get('base'):
                bits.append('база сама: %s' % ' / '.join(gamedata.num(v) for v in f['base']))
            if f.get('prop'):
                top = [v for lv, v in f['prop'] if ilvl is None or lv <= ilvl] or [f['prop'][0][1]]
                bits.append('свойство базы: до %s' % gamedata.num(max(top)))
            if bits:
                lines.append('  %-28s [слотов: %d]  %s' % (title(sid), rare[sid], ' | '.join(bits)))
    return '\n'.join(lines)


def main():
    ap = argparse.ArgumentParser(description='Что искать на каждом слоте')
    ap.add_argument('--plan', default=str(HERE.parent / 'plan.json'))
    ap.add_argument('--catalog', default=str(HERE.parent / 'catalog' / 'data'))
    ap.add_argument('--ilvl', type=int, default=70, help='уровень предмета, для которого считать ступени')
    args = ap.parse_args()
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding='utf-8', errors='replace')
        except (AttributeError, ValueError):
            pass
    cat = gamedata.load(args.catalog)
    if not cat or not cat.get('stats'):
        print('Каталог данных игры не найден или собран старой версией')
        return 1
    raw = json.loads(Path(args.plan).read_text(encoding='utf-8-sig'))
    if planfiles.is_manifest(raw):
        parts = planfiles.read_parts(args.plan, raw)
        raw, _ = planfiles.compose(raw, parts.get('route'), parts.get('build'))
    print(report(cat, raw, args.ilvl))
    return 0


if __name__ == '__main__':
    sys.exit(main())
