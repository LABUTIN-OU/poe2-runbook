# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Sergei Labutin
# Additional terms under GPL-3.0 section 7: see NOTICE.md
"""План из частей: маршрут и билд — отдельными файлами.

Раньше план был одним файлом, где вперемешку лежали разные вещи. Теперь:

  маршрут (routes/…)   — порядок карт: шаги (зона, цель по времени, точки перехода, задачи, фильтр игры,
                          который включают с шага) и цели самого пути — боссы, задания карт, награды,
                          уровень героя к шагу. Часть плана, как и дерево: у каждого плана свой. Босс,
                          задание и награда — факты игры: они лежат в справочнике (knowledge/landmarks.json,
                          модуль landmarks), а в маршруте от них только ссылка — id записи и шаг, на котором
                          она стоит.
  билд (builds/…)      — герой: слоты, вещи, умения и камни, версии дерева, ресурсы и этапы
                          (stages) — шаг, с которого билд меняет направление, и что на нём меняется
                          целиком: версия дерева, база защиты, атрибуты, статы по важности.
                          К шагам маршрута билд привязывается по их id: начало этапа (from), шаги цели
                          (need — срок, use и until — с какого шага и по какой её вещь или камень в ходу).
                          Что закрыть на шаге, говорит срок цели: своих списков у шага в билде нет.

Личного блока у плана нет: фильтр по шагам — часть плана, у автора и у игроков один и тот же (кто хочет
другой, правит свой план). Оглавление прежнего вида с полем profile читается, а файл личного — нет.

plan.json — оглавление: какие файлы взять и в каком порядке идут группы целей на странице:

    {"version": 2, "route": "routes/campaign-0.5.json", "build": "builds/varashta-crossbow.json",
     "groups": ["Навыки", "Уровень", "Награды", "Ресурсы"]}

compose собирает из частей словарь того же вида, каким раньше был один файл, — дальше с ним работает
core.norm_plan, как и прежде. План одним файлом (без поля route) по-прежнему читается как есть.
"""
import json
from pathlib import Path

import landmarks as marksmod
import slotwear
from i18n import tr

PARTS = ('route', 'build')


def is_manifest(raw):
    """Оглавление плана, а не сам план: названы файлы маршрута и билда."""
    return isinstance(raw, dict) and isinstance(raw.get('route'), str) and isinstance(raw.get('build'), str)


def part_paths(plan_path, raw):
    """Файлы частей, названные в оглавлении: {часть: путь}. Пути — относительно папки оглавления
    и только внутри неё."""
    root = Path(plan_path).resolve().parent
    out = {}
    for part in PARTS:
        name = raw.get(part)
        if not isinstance(name, str) or not name.strip():
            continue
        path = (root / name).resolve()
        if root != path and root not in path.parents:
            raise ValueError(tr('файл части «%s» лежит вне папки плана: %s') % (part, name))
        out[part] = path
    return out


def read_parts(plan_path, raw):
    """Читает части плана с диска: {часть: словарь}. Нет файла или в нём не JSON — ошибка с именем части."""
    names = {'route': tr('маршрута'), 'build': tr('билда')}
    out = {}
    for part, path in part_paths(plan_path, raw).items():
        try:
            out[part] = json.loads(path.read_text(encoding='utf-8-sig'))
        except OSError:
            raise ValueError(tr('нет файла %s: %s') % (names[part], raw[part]))
        except ValueError as e:
            raise ValueError(tr('файл %s не читается (%s): %s') % (names[part], raw[part], e))
        if not isinstance(out[part], dict):
            raise ValueError(tr('файл %s — не словарь: %s') % (names[part], raw[part]))
    return out


def compose(manifest, route, build, marks=None):
    """Собирает план из частей. Возвращает (план того же вида, что раньше был одним файлом, замечания).

    Шаги — шаги маршрута по порядку, как они записаны (фильтр шага — тоже поле шага).
    Цели — сначала билда, потом маршрута: порядок групп на странице задаёт оглавление (groups),
    а не место цели в файле. Цель маршрута без своего названия — ссылка на запись справочника игры
    (marks: {id: запись}, landmarks.load): к ней подставляются факты записи. Остальные разделы — из билда
    (слоты, этапы, дерево, название).
    """
    route, build = route or {}, build or {}
    problems = []
    if build.get('routeId') and route.get('id') and build['routeId'] != route['id']:
        # сроки целей и начала этапов билда названы по шагам своего маршрута: с другим маршрутом они могут не лечь
        problems.append(tr('Билд написан для маршрута «%s», а подключён «%s»') % (build['routeId'], route['id']))
    steps = [dict(s) for s in route.get('steps') or [] if isinstance(s, dict) and s.get('id')]
    plan = {k: v for k, v in build.items() if k not in ('steps', 'goals')}
    plan['steps'] = steps
    route_goals, more = marksmod.resolve(route.get('goals'), marks)
    problems += more
    plan['goals'] = list(build.get('goals') or []) + route_goals
    if isinstance(manifest.get('groups'), list):
        plan['groupOrder'] = manifest['groups']
    # что носят в слоте, записано его периодами: слоту — все его классы, его целям — срок периода
    return slotwear.expand(plan), problems
