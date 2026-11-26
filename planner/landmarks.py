# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Sergei Labutin
# Additional terms under GPL-3.0 section 7: see NOTICE.md
"""Справочник игры: что есть в зонах — боссы, задания, механики, тайники, лагеря и награды навсегда (файл
knowledge/landmarks.json). Полный: всё, что карта мира игры показывает в зонах кампании, — не только то, что нужно
какому-то плану.

Это факты игры, а не чей-то план: кто в какой зоне, что даёт, по каким строкам лога засчитывается, можно ли
пройти мимо. Они одни на всех, кто играет в эту версию игры, и после обновления игры их сверяют заново —
один раз, а не в каждом плане. Запись справочника:

  id      — имя записи; по нему на неё ссылается план и её помнит забег;
  kind    — boss (и редкий монстр карты мира — «Хижина Нараг»), quest (задание зоны: реликвия, «Канальный рычаг»,
            «Дерево Душ»), mechanic, cache (тайник зоны: сундук или клад, какие карта мира игры показывает в зоне, —
            «Опасный клад», «Виселица»), camp (лагерь: «Паромщик», «Странствующий торговец») или ascension
            (восхождение: очки Восхождения за Испытание Сехем или Испытание Хаоса); нет поля — награда;
  zone    — код зоны из лога игры, в которой это находится (пусто — ещё не сказано);
  zones   — у механики (Бездна, Ритуал, Маяк ваал…): зоны кампании, где её показывает карта мира игры. Механика
            бывает и в других местах (на картах — где угодно), поэтому одна механика может стоять на многих шагах;
            у восхождения — зоны испытаний, где его берут (метки этих испытаний на карте мира — оно и есть); по ним
            редактор предлагает его шагу;
  title   — название, как его показывает страница: «Имя (English): что даёт»;
  group   — в какую группу страницы забега запись идёт («Награды»);
  reward  — награда из лога: коды свойств игры (base_cold_damage_resistance_%), один или список; passive_points —
            очки пассивных умений. Строка лога о награде узнаётся по ним на любом языке клиента;
  gives   — что запись даёт герою навсегда: {стат: число};
  heard   — реплика в логе (или несколько) — коды строк таблицы игры, по которым запись отмечается сама;
  must    — босс, без убийства которого маршрут не продолжить;
  final   — финальный босс акта;
  options — награда с выбором: все её варианты, как их даёт игра, — [{title — что вариант даёт, словами
            клиента игры; name — как называется сам вариант (предмет, столб); reward — коды свойств этой
            награды; gives — что вариант даёт герою: {стат: число}}];
  swap    — можно ли сменить выбор позже: true — можно, false — выбор навсегда, нет поля — не известно;
  handout — где награду выдают, если не там, где босс или задание: код зоны (обычно город);
  spot    — где это в зоне: место, как его называет игра («Галерея (The Galleria)»), или пара слов;
  random  — предмет задания падает со случайного монстра зоны: true;
  monsters — с каких монстров он падает, если не с любых (к random): названия, как их пишет игра,
            [«Гигант ваал (Vaal Goliath)»] — страница говорит, кого бить;
  needs   — записи справочника, без которых эту не взять: [id] (Медальон — после обеих реликвий);
  levels  — у восхождения: младший уровень зоны, где берут каждую из четырёх ступеней (по два очка Восхождения):
            [22, 38, 60, 75] — Сехем: 1 этаж с 22, 2 этажа с 45, 3 с 60, 4 с 75; Хаос: 4 испытания с 38 (первая
            ступень; вторая — первые ступени обоих испытаний), 7 с 60, 10 с 75, Мастер испытаний с 75. Восхождение
            ставят на шаги, где его берут; какое оно по счёту, говорит порядок маршрута (core.norm_plan), а
            отмечается оно само: лог пишет каждый взятый узел Восхождения;
  early   — у восхождения: ступень, которую можно взять раньше её уровня зоны, и запись, после которой можно:
            {"3": "boss-elzarah"} — Элзара гарантированно даёт барию на третье восхождение (патч 0.3.1).

План о записи справочника говорит только своё: на каком она шаге (need), какой вариант награды берёт (opt —
номер варианта с единицы; не назван — выбор не сделан) и чем она закрывается (grantedBy). В файле маршрута
это запись без названия:
{"id": "boss-beira", "need": "clearfell"}; при сборке плана к ней подставляются факты из справочника —
дальше программа работает с целью такого же вида, как раньше. Механику и восхождение ставят на шаг ссылкой
со своим id и полем ref — id записи: {"id": "abyss-badlands", "ref": "mech-abyss", "need": "badlands"} — так одна
запись стоит на нескольких шагах (босс же — одна битва в одной зоне: на него ссылаются только его id). У награды с выбором цель называется
«запись: выбранный вариант» и даёт герою то, что даёт этот вариант; отмечается она строкой лога любого
варианта — награда взята, даже если в игре выбрали не то, что в плане.
"""
import json
from pathlib import Path
from i18n import tr

FACT_KEYS = ('kind', 'zone', 'zones', 'title', 'group', 'reward', 'gives', 'heard', 'must', 'final', 'options', 'swap',
             'handout', 'spot', 'random', 'monsters', 'needs', 'levels', 'early')   # порядок полей записи в файле
# что о записи говорит план; note и soft редактор не ставит — в файле, записанном раньше, они читаются как есть;
# ref — на какую запись ссылается цель со своим id (механика на нескольких шагах)
PLAN_KEYS = ('ref', 'need', 'opt', 'from', 'until', 'note', 'soft', 'grantedBy')
CHECKS = (('handout', lambda v: isinstance(v, str) and bool(v.strip())),          # поле записи и какое значение годится
          ('spot', lambda v: isinstance(v, str) and bool(v.strip())),
          ('random', lambda v: v is True),
          ('monsters', lambda v: isinstance(v, list) and bool(v) and all(isinstance(x, str) and x.strip() for x in v)),
          ('needs', lambda v: isinstance(v, list) and bool(v) and all(isinstance(x, str) and x for x in v)),
          ('zones', lambda v: isinstance(v, list) and bool(v) and all(isinstance(x, str) and x.strip() for x in v)),
          ('levels', lambda v: isinstance(v, list) and bool(v) and all(isinstance(x, int) and not isinstance(x, bool) and x > 0
                                                                       for x in v) and v == sorted(v)),
          ('early', lambda v: isinstance(v, dict) and bool(v) and all(isinstance(k, str) and k.isdigit()
                                                                      and isinstance(x, str) and x for k, x in v.items())))
KINDS = ('boss', 'quest', 'mechanic', 'cache', 'camp', 'ascension')
MECHANIC = 'mechanic'
# виды записей, на которые ссылаются с нескольких шагов (поле ref ссылки): механика — где её проходят, восхождение — где
# берут очки Восхождения
MULTI = (MECHANIC, 'ascension')


def load(path):
    """Справочник из файла: ({id: запись} в порядке файла, версия игры, для которой он составлен, замечания).
    Файла нет — справочник пуст, и это не ошибка: план может обходиться без него."""
    try:
        raw = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    except FileNotFoundError:
        return {}, None, []
    except (OSError, ValueError) as e:
        return {}, None, [tr('Справочник игры не читается (%s): %s') % (Path(path).name, e)]
    if not isinstance(raw, dict) or not isinstance(raw.get('landmarks'), list):
        return {}, None, [tr('Справочник игры записан не так: нужен список landmarks')]
    out, problems = {}, []
    for rec in raw['landmarks']:
        if not (isinstance(rec, dict) and isinstance(rec.get('id'), str) and rec['id']):
            problems.append(tr('Справочник игры: запись без id'))
            continue
        if rec['id'] in out:
            problems.append(tr('Справочник игры: запись «%s» стоит дважды') % rec['id'])
            continue
        if not (isinstance(rec.get('title'), str) and rec['title'].strip()):
            problems.append(tr('Справочник игры: у записи «%s» нет названия') % rec['id'])
            continue
        if rec.get('kind') is not None and rec['kind'] not in KINDS:
            problems.append(tr('Справочник игры: запись «%s» — босс (boss), задание (quest), механика (mechanic), тайник (cache), лагерь (camp), восхождение (ascension) или награда (без kind)') % rec['id'])
            continue
        opts = rec.get('options')
        if opts is not None and not (isinstance(opts, list) and len(opts) > 1 and all(
                isinstance(o, dict) and isinstance(o.get('title'), str) and o['title'].strip() for o in opts)):
            problems.append(tr('Справочник игры: у записи «%s» варианты записаны не так — нужно хотя бы два, у каждого название') % rec['id'])
            continue
        bad = next((k for k, ok in CHECKS if k in rec and not ok(rec[k])), None)
        if bad:
            problems.append(tr('Справочник игры: у записи «%s» поле %s записано не так') % (rec['id'], bad))
            continue
        if (rec.get('kind') == 'ascension') != ('levels' in rec):
            # уровни ступеней — только у восхождения, и у него они есть всегда: по ним проверка плана судит, не рано ли
            problems.append(tr('Справочник игры: уровни ступеней (levels) бывают только у восхождения (ascension), и у него они есть всегда — «%s»') % rec['id'])
            continue
        out[rec['id']] = rec
    for rid, rec in out.items():
        lost = [n for n in rec.get('needs') or () if n not in out or n == rid]
        if lost:
            problems.append(tr('Справочник игры: запись «%s» ждёт записей, которых нет: %s') % (rid, ', '.join(lost)))
            out[rid] = dict(rec, needs=[n for n in rec['needs'] if n not in lost])
    game = raw.get('game') if isinstance(raw.get('game'), str) else None
    return out, game, problems


def ref_id(goal):
    """Id записи справочника, на которую ссылается цель маршрута: поле ref, а без него — её собственный id."""
    return goal.get('ref') if isinstance(goal.get('ref'), str) else goal.get('id')


def is_ref(goal, marks):
    """Цель маршрута — ссылка на запись справочника: своего названия у неё нет, а запись есть (по ref или по id)."""
    return isinstance(goal, dict) and 'title' not in goal and ref_id(goal) in (marks or {})


def picked(ref, link):
    """Вариант награды с выбором, который берёт план: запись варианта или None (выбор не сделан или назван
    вариант, которого нет)."""
    opts, n = (ref or {}).get('options') or [], (link or {}).get('opt')
    return opts[n - 1] if isinstance(n, int) and not isinstance(n, bool) and 1 <= n <= len(opts) else None


def resolve(goals, marks):
    """Цели маршрута, в которых ссылки на справочник заменены целями обычного вида: факты записи плюс то,
    что о ней сказал план (зона записи в цель не идёт — она нужна только редактору). У награды с выбором
    цель называется по выбранному варианту и даёт герою то, что даёт он; пока выбор не сделан, она помечена
    unpicked. Ссылка со своим id и полем ref (механика на нескольких шагах) даёт цель со своим id. Возвращает
    (цели, замечания). Ссылка на запись, которой в справочнике нет, в план не попадает — об этом сказано; так же —
    ссылка по ref не на механику."""
    out, problems = [], []
    for g in goals or []:
        if not isinstance(g, dict) or 'title' in g or 'reach' in g or not g.get('id'):
            out.append(g)                       # цель самого плана (уровень героя) — как записана
            continue
        ref = (marks or {}).get(ref_id(g))
        if ref is None:
            problems.append(tr('Маршрут: записи «%s» нет в справочнике игры') % ref_id(g))
            continue
        if 'ref' in g and ref.get('kind') not in MULTI:
            # на несколько шагов ставят механику и восхождение; босс, задание и награда — одно место в игре: ссылка — их id
            problems.append(tr('Маршрут: цель «%s» ссылается на «%s» полем ref — так ставят только механику и восхождение') % (g['id'], ref_id(g)))
            continue
        # у восхождения зоны — испытания, где его берут: по ним проверка плана видит, на испытании ли его шаг
        goal = {k: v for k, v in ref.items()
                if k not in ('zone', 'options', 'swap') and (k != 'zones' or ref.get('kind') == 'ascension')}
        if ref.get('needs'):
            # что нужно раньше — с названиями: страница называет их, даже когда этих записей в плане нет
            goal['needs'] = [{'id': n, 'title': marks[n]['title']} for n in ref['needs'] if n in marks]
        goal.update({k: v for k, v in g.items() if k not in ('opt', 'ref')})
        opts = ref.get('options')
        if opts:
            # награду выдаёт строка лога любого варианта: она взята, даже если в игре выбрали не то, что в плане
            as_list = lambda v: [v] if isinstance(v, str) else list(v) if isinstance(v, list) else []
            words = as_list(ref.get('reward')) + [k for o in opts for k in as_list(o.get('reward'))]
            if words:
                goal['reward'] = list(dict.fromkeys(words))
            chosen = picked(ref, g)
            if chosen is None:
                goal['title'] = tr('%s: вариант не выбран') % ref['title']
                goal['unpicked'] = True
                if g.get('opt') is not None:
                    problems.append(tr('Маршрут: у «%s» назван вариант %s, а их %d') % (ref['title'], g['opt'], len(opts)))
            else:
                goal['title'] = '%s: %s' % (ref['title'], chosen['title'])
                if chosen.get('gives'):
                    goal['gives'] = dict(chosen['gives'])
        out.append(goal)
    return out, problems


def split(goal, zone=None):
    """Цель маршрута прежнего вида (с фактами внутри) — на запись справочника и то, что остаётся плану:
    (запись, ссылка). zone — зона, в которой это находится."""
    ref = {'id': goal['id']}
    facts = dict(goal, zone=zone) if zone else dict(goal)
    for k in FACT_KEYS:
        if k in facts:
            ref[k] = facts[k]
    link = {'id': goal['id']}
    for k in list(PLAN_KEYS) + [k for k in goal if k not in FACT_KEYS and k not in PLAN_KEYS and k != 'id']:
        if k in goal:
            link[k] = goal[k]
    return ref, link


def render(marks, game=None, eol='\n'):
    """Текст файла справочника: запись — одна строка."""
    rows = ['    ' + json.dumps(rec, ensure_ascii=False) for rec in marks.values()]
    head = ['{', '  "version": 1,'] + (['  "game": %s,' % json.dumps(game, ensure_ascii=False)] if game else [])
    body = ['  "landmarks": ['] + [r + (',' if i < len(rows) - 1 else '') for i, r in enumerate(rows)] + ['  ]', '}', '']
    return eol.join(head + body)


def describe(marks):
    """Справочник для страницы редактора плана: записи как в файле; по зоне записи видно, какие из них
    предлагать шагу первыми."""
    return [dict(rec) for rec in (marks or {}).values()]
