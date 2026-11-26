# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Sergei Labutin
# Additional terms under GPL-3.0 section 7: see NOTICE.md
"""Этап билда: шаг маршрута, с которого билд меняет направление.

Этап — блок билда (раздел stages файла билда). Своих параметров у него два: название и шаг начала
(from; у первого этапа шага нет — он действует с начала забега). Остальное — то, что в билде меняется
ЦЕЛИКОМ и потому привязано к этапу, а не к шагу:

  tree, atlas — какая версия дерева героя и дерева атласа действует (id версии из разделов tree и atlas);
  kind        — база защиты: род баз из данных игры (str_armour — броня, int_armour — энергощит и связки);
  attrs       — какие атрибуты билд берёт с вещей (любые из тех, что есть в игре; пустой список — никаких);
  stats       — статы, которые билд ведёт, по порядку важности: [{id, cap?}].

Этап называет только то, что на нём меняется: чего он не назвал, действует как на прежнем этапе. Поэтому
совпавшая смена (на картах — и дерево, и защита) и несовпавшая (другое дерево на одного босса) — один
и тот же блок. Отрезок маршрута для целей по времени — тоже этап: от одной смены направления до другой.

То, что меняется по одному, — камни и вещи — к этапу не относится: это цели, у каждой свой шаг.

Здесь только чтение: какой этап действует на шаге и что на нём действует. Проверка раздела при чтении
плана — core.norm_plan, правка со страницы «Билд» — buildplan.
"""

PARAMS = ('tree', 'atlas', 'kind', 'attrs', 'stats')   # что этап может назвать; порядок — как в файле


def per_step(plan):
    """Для каждого шага маршрута — номер этапа, который на нём действует (в списке plan['stages']);
    None — этапов у билда нет. Этапы в плане стоят по порядку шагов, первый — с начала забега."""
    stages = plan.get('stages') or []
    steps = plan.get('steps') or []
    if not stages:
        return [None] * len(steps)
    idx = {s['id']: i for i, s in enumerate(steps)}
    start = {}
    for n, st in enumerate(stages[1:], 1):
        at = idx.get(st.get('from'))
        if at is not None:
            start[at] = n
    out, cur = [], 0
    for i in range(len(steps)):
        cur = start.get(i, cur)
        out.append(cur)
    return out


def number(plan, pos):
    """Номер этапа на шаге pos (None — забег ещё не начат: первый этап). None — этапов нет."""
    stages = plan.get('stages') or []
    if not stages:
        return None
    if pos is None:
        return 0
    by = per_step(plan)
    return by[min(pos, len(by) - 1)] if by else 0


def effective(stages, n):
    """Этап номер n со всем, что на нём действует: его название и шаг начала, а по каждому параметру —
    значение, названное им самим или ближайшим прежним этапом (None — не назвал никто). own — что этап
    назвал сам; by — какой этап назвал каждый действующий параметр ({параметр: номер этапа})."""
    st = stages[n]
    out = {'n': n, 'id': st['id'], 'name': st.get('name') or st['id'], 'from': st.get('from') if n else None,
           'own': [k for k in PARAMS if st.get(k) is not None], 'by': {}}
    for k in PARAMS:
        out[k] = None
    for m in range(n + 1):
        for k in PARAMS:
            if stages[m].get(k) is not None:
                out[k] = stages[m][k]
                out['by'][k] = m
    return out


def at(plan, pos):
    """Этап, действующий на шаге pos, — как его отдаёт effective. None — этапов у билда нет."""
    n = number(plan, pos)
    return None if n is None else effective(plan['stages'], n)


def version(plan, key, pos):
    """Версия дерева (key: 'tree' — героя, 'atlas' — атласа), действующая на шаге pos: та, которую назвал
    этап шага или ближайший прежний. None — ни один этап версии не назвал или такой версии в разделе нет."""
    st = at(plan, pos)
    if st is None or not st.get(key):
        return None
    return next((ph for ph in ((plan.get(key) or {}).get('phases') or []) if ph.get('id') == st[key]), None)


def users(plan, key):
    """Где версии дерева названы: {id версии: [название этапа, …]} — по этим этапам версия действует."""
    out = {}
    for st in plan.get('stages') or []:
        if st.get(key):
            out.setdefault(st[key], []).append(st.get('name') or st['id'])
    return out
