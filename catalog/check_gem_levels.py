# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Sergei Labutin
# Additional terms under GPL-3.0 section 7: see NOTICE.md
"""Достижимы ли камни плана к своим срокам: где на маршруте падает неогранённый камень каждого уровня.

Правило игры (каталог, rules.json): неогранённый камень умения, выпавший в зоне, — самого высокого
уровня из тех, что в ней уже падают; с редких и уникальных чудовищ — как в зоне на 1–2 уровня выше.
Поэтому у каждого уровня камня на маршруте есть окно: шаги, на которых он падает. До окна камня ещё нет,
после — уже нет (падает только выше, а тому нужны уровень героя и характеристики повыше).

Проверяется: уровень камня умения к шагу (срок — поле need цели или проверка шага, где цель названа),
само умение (его можно огранить камнем не ниже его минимального уровня) и камни поддержки (годится
неогранённый камень поддержки не ниже уровня самой поддержки).

Запуск: python -I catalog/check_gem_levels.py [--plan plan.json] [--catalog catalog/data]
"""
import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'planner'))
import core  # noqa: E402
import gamedata  # noqa: E402
import planfiles  # noqa: E402

ABOVE = 2          # с редкого или уникального чудовища вещь — как из зоны на столько уровней выше
RE_GEM = re.compile(r'^gem(\d+)-')
RE_TITLE = re.compile(r'^(.*?) \(([^()]*)\)\s*$')


def load_plan(path, cat):
    raw = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    if planfiles.is_manifest(raw):
        parts = planfiles.read_parts(path, raw)
        raw, _ = planfiles.compose(raw, parts.get('route'), parts.get('build'), parts.get('profile'))
    return core.norm_plan(raw, cat)[0]


def level_at(table, area):
    """Самый высокий уровень камня, который уже падает в зоне такого уровня (table: уровень -> зона)."""
    fit = [int(lv) for lv, start in table.items() if start is not None and start <= area]
    return max(fit) if fit else None


def gem_levels_in(rules, area):
    """Уровни неогранённых камней умений, которые падают в зоне такого уровня."""
    skill = rules['uncut']['skill']
    low = {lv: start for lv, start in skill.items() if int(lv) < 15}
    high = min((start for lv, start in skill.items() if int(lv) >= 15 and start is not None), default=None)

    def one(level):
        """Что падает с чудовища такого уровня: до порога 15-го камня — один уровень, самый высокий
        из уже падающих; с порога — диапазон от 15-го и выше по таблице карт."""
        if high is not None and level >= high:
            span = (15, 15)
            for start, lo, hi in rules.get('mapGems') or []:
                if level >= start:
                    span = (lo, hi)
            return set(range(span[0], span[1] + 1))
        lv = level_at(low, level)
        return {lv} if lv else set()

    # в зоне: с обычных чудовищ — по её уровню, с редких и уникальных — как на 1–2 уровня выше;
    # диапазон карт берётся только по уровню самой зоны
    out = one(area)
    for up in range(1, ABOVE + 1):
        more = one(area + up)
        out |= more if (high is None or area + up < high) else {min(more)}
    return out


def main():
    ap = argparse.ArgumentParser(description='Достижимы ли камни плана к своим срокам')
    ap.add_argument('--plan', default=str(HERE.parent / 'plan.json'))
    ap.add_argument('--catalog', default=str(HERE / 'data'))
    ap.add_argument('--run', help='журнал сыгранного забега (runs/<id>.json): уровни зон берутся из него')
    args = ap.parse_args()
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding='utf-8', errors='replace')
        except (AttributeError, ValueError):
            pass
    cat = gamedata.load(args.catalog)
    rules = cat['rules']
    plan = load_plan(args.plan, cat)
    steps = plan['steps']
    name = lambda i: '«%s»' % (steps[i].get('name') or steps[i]['id'])
    # Уровень зоны каждого шага. В данных игры у зоны одно число, но в игре уровни островов 4 акта, конца
    # 2 акта и интерлюдий растут по ходу прохождения (третья интерлюдия — 62–64, а не 54–56). Поэтому
    # настоящие уровни берём из журнала сыгранного забега (--run): лог пишет, с каким уровнем зона создана.
    # Чего в журнале нет — из каталога; у шага карт — его порог; шаг-событие — как прошлый.
    real = {}
    if args.run:
        journal = json.loads(Path(args.run).read_text(encoding='utf-8'))
        for e in journal.get('events') or []:
            if e.get('type') == 'zone' and e.get('level'):
                real.setdefault(e['code'], set()).add(e['level'])
    area, spans, prev = [], [], 1
    for s in steps:
        seen = sorted(real.get(s.get('zone')) or [])
        lv = (seen[0] if seen else None) or (cat['areas'].get(s.get('zone')) or {}).get('level') or s.get('level') or prev
        area.append(lv)
        spans.append(seen or [lv])           # зону проходят и повторно, уже с уровнем повыше
        prev = lv
    # в городе и мирной деревне чудовищ нет — камни там не падают
    peaceful = [bool((cat['areas'].get(s.get('zone')) or {}).get('town')) for s in steps]
    drops = [set() if calm else set().union(*[gem_levels_in(rules, lv) for lv in span])
             for span, calm in zip(spans, peaceful)]
    if args.run:
        print('Уровни зон — из журнала %s; отличаются от данных игры на %d шагах\n' % (
            Path(args.run).stem, sum(1 for s, span in zip(steps, spans)
                                     if span != [(cat['areas'].get(s.get('zone')) or {}).get('level')] and s.get('zone'))))
    first, last = {}, {}
    for i, levels in enumerate(drops):
        for lv in levels:
            first.setdefault(lv, i)
            last[lv] = i
    hero_req = rules.get('gemHero') or []
    attr = (rules.get('gemAttr') or {}).get('100') or []
    print('Окна на маршруте: где падает неогранённый камень умения каждого уровня')
    for lv in range(1, 21):
        if lv in first:
            zones = sorted({area[i] for i in range(len(steps)) if lv in drops[i]})
            print('  ур. %-2d зоны %s–%s | шаги %s … %s | герой с %s, интеллект %s' % (
                lv, zones[0], zones[-1], name(first[lv]), name(last[lv]),
                hero_req[lv - 1] if lv <= len(hero_req) else '?', attr[lv - 1] if lv <= len(attr) else '?'))
        else:
            print('  ур. %-2d на этом маршруте не падает (начинает падать с зоны %s)' % (lv, rules['uncut']['skill'].get(str(lv))))
    # --- сроки плана ---
    step_idx = {s['id']: i for i, s in enumerate(steps)}
    gated = {}
    for i, s in enumerate(steps):
        for gate in core.step_gates(s):
            for gid in gate.get('goals') or []:
                gated.setdefault(gid, i)
    goal_by_id = {g['id']: g for g in plan['goals']}
    notes, checked = [], 0
    reach = [max(area[:i + 1]) for i in range(len(steps))]
    for g in plan['goals']:
        m = RE_GEM.match(g['id'])
        if not (m and g.get('part') == 'level'):
            continue
        d = step_idx.get(g.get('need'), gated.get(g['id']))
        if d is None:
            continue                       # срока нет — проверять нечего
        checked += 1
        lv = int(m.group(1))
        skill = (goal_by_id.get(g.get('for')) or {}).get('title', g.get('for'))
        what = 'камень %d для «%s» к шагу %s (зона %d)' % (lv, RE_TITLE.sub(r'\1', skill), name(d), area[d])
        if lv not in first:
            notes.append('НЕДОСТИЖИМО: %s — такой камень на маршруте не падает' % what)
        elif d < first[lv]:
            notes.append('РАНО: %s — такой камень падает только с шага %s (зона %d)' % (what, name(first[lv]), area[first[lv]]))
        elif d > last[lv]:
            # что падает на шаге срока вместо нужного: камень повыше со своими требованиями
            now = min(drops[d]) if drops[d] else None
            more = '' if now is None else ' — там падает уже %d-й (герой с %s, интеллект %s)' % (
                now, hero_req[now - 1] if now <= len(hero_req) else '?', attr[now - 1] if now <= len(attr) else '?')
            notes.append('ПОЗДНО: %s%s; %d-й падает только до шага %s (зона %d)' % (
                what, more, lv, name(last[lv]), area[last[lv]]))
        if lv <= len(hero_req) and hero_req[lv - 1] > reach[d] + 1:
            notes.append('РАНО ПО УРОВНЮ: %s — камню нужен герой %d уровня' % (what, hero_req[lv - 1]))
    by_name = {}
    for gem in cat['gems'].values():
        by_name.setdefault(gem['name'], gem)
    support = rules['uncut']['support']
    sup_first = {}                          # уровень неогранённого камня поддержки -> первый шаг, где он падает
    for i, lv_area in enumerate(area):
        top = level_at(support, lv_area + ABOVE) or 0
        for lv in range(1, top + 1):
            sup_first.setdefault(lv, i)
    table, unknown = [], []
    for g in plan['goals']:
        if g.get('kind') not in ('skill', 'support'):
            continue
        d = step_idx.get(g.get('need'), gated.get(g['id']))
        t = RE_TITLE.match(g.get('title') or '')
        gem = by_name.get(t.group(2)) if t else None
        if g['kind'] == 'support' and not gem:
            unknown.append(g.get('title') or g['id'])
        if d is None or not gem or not gem.get('level'):
            continue
        checked += 1
        if g['kind'] == 'skill':
            best = max((lv for i in range(d + 1) for lv in drops[i]), default=0)
        else:
            # камень поддержки годится на любую поддержку не выше своего уровня — важен только потолок
            best = max((level_at(support, area[i] + ABOVE) or 0 for i in range(d + 1)), default=0)
            f = sup_first.get(gem['level'])
            table.append((t.group(1), gem['level'], name(d), area[d], name(f) if f is not None else '—',
                          area[f] if f is not None else None, d - f if f is not None else None))
        if best < gem['level']:
            notes.append('РАНО: %s «%s» к шагу %s — нужен неогранённый камень %d уровня, а к этому шагу падает не выше %d' % (
                'умение' if g['kind'] == 'skill' else 'поддержка', t.group(1), name(d), gem['level'], best))
    print('\nКамни поддержки: неогранённый камень уровня N падает с зоны ' +
          ', '.join('%s: %s' % (lv, support[lv]) for lv in sorted(support, key=int)) +
          ' (годится на любую поддержку не выше своего уровня)')
    for title, lv, dn, da, fn, fa, gap in table:
        print('  %-28s ур. %d | срок %s (зона %d) | падает с шага %s (зона %s) | запас %s' % (
            title[:28], lv, dn, da, fn, fa, ('%d шаг.' % gap) if gap is not None else '—'))
    if unknown:
        print('  не найдены в каталоге по имени: %s' % ', '.join(sorted(set(unknown))))
    print('\nПроверено целей со сроком: %d | замечаний: %d' % (checked, len(notes)))
    for n in notes:
        print('  ' + n)
    return 0


if __name__ == '__main__':
    sys.exit(main())
