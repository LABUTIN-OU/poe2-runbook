# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Sergei Labutin
# Additional terms under GPL-3.0 section 7: see NOTICE.md
"""Правка билда со страницы «Билд» (/admin): то, что раньше вписывалось в файл билда руками.

На странице два блока билда и то, что относится к билду целиком.

Билд целиком: название (title), герой (раздел hero: класс и вознесение, как их называют данные дерева
GGG, — от класса зависят стартовые атрибуты) и свои статы (раздел statDefs, см. gamedata.with_stats):
стат, которого нет в готовом наборе каталога, билд собирает сам из свойств игры.

Деревья (разделы tree и atlas, см. treeplan.py): версии дерева героя и дерева атласа — своя библиотека
билда. Их создают, называют и правят на вкладке «Дерево» этой же страницы; какая версия действует, говорит
этап. Страница присылает полный набор версий каждого дерева вместе с остальными разделами.

Этапы (раздел stages файла билда, см. buildstage.py). Этап — шаг маршрута, с которого билд меняет
направление. Этапов сколько угодно; у каждого название, шаг начала (у первого шага нет — он действует
с начала забега) и то, что на нём меняется ЦЕЛИКОМ:

  * версия дерева героя и версия дерева атласа (сами версии правят на карте, здесь — какая действует);
  * база защиты — род баз из данных игры (какие вообще бывают), как и всё, что из рода следует:
    статы защиты (herostats);
  * атрибуты, которые билд берёт с вещей;
  * статы билда по порядку важности.

Этап называет только то, что меняет: остальное действует как на прежнем.

Цели (раздел goals) — то, что меняется по одному, у каждой свои шаги. Цель живёт при своём носителе:

  * камни: умение (kind skill) — его поддержки (kind support, for — умение; part — гнездо: «Приказание I»
    и сменяющее его «Приказание II» делят одно) — уровни камня к шагу (kind gem, part level);
  * вещи: вещь в слоте (slot; gear — что это за вещь) — статы на ней (slot, part, stat, min);
  * прочее: запасы и проверки без носителя.

У любой цели: что (title), к какому шагу (need), с какого шага её ищут (from), с какого и по какой шаг
её вещь или камень в ходу (use, until), заметка. Названия умений, поддержек и баз страница
берёт из данных игры — на языке игрока с английским в скобках; оттуда же стартовый уровень камня,
описание и рисунок базы.

К шагу маршрута билд ничего не дописывает: что закрыть на шаге, говорит срок самой цели (need), и программа
сама показывает на карточке шага цели с этим сроком. Что сделать в городе, пишут обычной задачей шага —
в маршруте.

Страница присылает разделы целиком. Здесь они проверяются и вписываются в файл билда; остальной текст
файла не меняется (это проверяется перед записью), прежний файл сохраняется копией.
"""
import json
import os
import re
import shutil
import time
from pathlib import Path

import buildstage
import core
import gamedata
import herostats
import slotwear
import treeplan
from i18n import tr

RE_ID = re.compile(r'[a-z0-9][a-z0-9_-]{0,39}')
MAX_NAME = 60        # длина названия этапа
MAX_STAGES = 40      # этапов в одном билде
MAX_STATS = 60       # статов в списке этапа
MIN_BASES = 10       # род баз, у которого в игре меньше стольких баз, в выбор не идёт
KEEP_BACKUPS = 20    # сколько прежних версий файла хранить
SECTIONS = ('title', 'hero', 'statDefs', 'slots', 'stages', 'goals')    # разделы файла билда, которые правит страница
PAYLOAD = SECTIONS       # страница присылает их под теми же именами
TREES = ('tree', 'atlas')    # деревья билда: их версии страница присылает теми же ключами (см. server.tree_section)
MAX_TITLE = 80       # длина названия билда
MAX_SLOTS = 40       # слотов в одном билде
SLOT_ORDER = ('id', 'name', 'wear', 'classes', 'gear')     # поля слота в привычном порядке
MAX_WEAR = 20        # периодов у одного слота
WEAR_ORDER = ('from', 'classes', 'kind', 'until')          # поля периода в привычном порядке
STAGE_KEYS = ('id', 'from', 'name') + buildstage.PARAMS     # поля этапа, которые знает страница

# --- цели: что страница правит и как -------------------------------------------------------------------
RE_GOAL_ID = re.compile(r'[a-z0-9][a-z0-9_-]{0,63}')
MAX_GOALS = 600
GOAL_TEXT = {'title': 200, 'note': 4000, 'label': 80, 'gear': 60, 'group': 40, 'part': 40}   # строки и их длина
GOAL_STEPS = ('need', 'from', 'use', 'until')      # шаги маршрута
GOAL_FLAGS = ('any', 'soft', 'key')      # пометки: в записи либо true, либо поля нет
GOAL_INTS = {'gemFrom': (1, 40), 'opens': (1, 100), 'hero': (1, 100)}
GOAL_KINDS = ('skill', 'support', 'gem', 'resource')   # виды целей билда; боссы и награды — цели маршрута
GOAL_REFS = ('for', 'grantedBy')                   # ссылки на другую цель


def _names(cat, lang):
    packs = (cat or {}).get('lang') or {}
    return (packs.get(lang) or {}).get('statNames') or (packs.get('ru') or {}).get('statNames') or {}


def kinds(cat, lang='ru'):
    """Базы защиты, какие бывают в игре, — выбор для этапа: [{id, label, short, stats, needs}]. id — род баз
    из данных игры; stats — статы защиты, которые несут его базы (они и идут в счёт); needs — атрибуты,
    которых базы требуют (справка: в счёт они идут, только если этап назвал их сам); у обоих —
    [{id, name}]; label — название выбора: статы защиты через косую черту («Броня / Энергощит»); short —
    то же общепринятыми у игроков сокращениями («AR/ES»: поле abbr таблицы статов) — подпись кнопки там,
    где названия целиком в ряд не помещаются. Порядок — по атрибутам, как в игре: сила, ловкость,
    интеллект, потом связки."""
    cache = cat.setdefault('_kinds', {}) if isinstance(cat, dict) else {}
    if lang in cache:
        return cache[lang]
    table = ((cat or {}).get('stats') or {}).get('stats') or {}
    order = ((cat or {}).get('stats') or {}).get('order') or list(table)
    names = _names(cat, lang)
    count = {}
    for b in ((cat or {}).get('bases') or {}).values():
        if b.get('props'):
            for t in b.get('tags') or ():
                if t.endswith('_armour'):
                    count[t] = count.get(t, 0) + 1
    found = {}
    for kind, n in count.items():
        stats, attrs = herostats.defence_stats(cat, kind), herostats.kind_attrs(cat, kind)
        if n >= MIN_BASES and stats:
            found[kind] = (stats, attrs)
    # У чистого рода один стат защиты и один атрибут: по ним видно, какой стат к какому атрибуту относится —
    # так статы связки встают в привычном порядке («Броня / Энергощит», а не как в таблице статов).
    home = {stats[0]: order.index(attrs[0]) for stats, attrs in found.values() if len(stats) == 1 and len(attrs) == 1}
    full = lambda ids: [{'id': s, 'name': (names.get(s) or (s, s))[0]} for s in ids]   # noqa: E731
    out = []
    for kind, (stats, attrs) in found.items():
        stats = sorted(stats, key=lambda s: home.get(s, len(order)))
        label = ' / '.join((names.get(s) or (s, s))[1] for s in stats)
        abbr = [(table.get(s) or {}).get('abbr') for s in stats]
        out.append({'id': kind, 'label': label, 'short': '/'.join(abbr) if all(abbr) else label,
                    'stats': full(stats), 'needs': full(attrs)})
    place = lambda k: (len(k['needs']), [order.index(a['id']) for a in k['needs']], k['id'])   # noqa: E731
    cache[lang] = sorted(out, key=place)
    return cache[lang]


def kind_label(cat, kind, lang='ru'):
    """Название базы защиты, как на странице «Билд»: «Броня», «Энергощит», «Броня / Энергощит»."""
    return next((k['label'] for k in kinds(cat, lang) if k['id'] == kind), kind)


def kind_short(cat, kind, lang='ru'):
    """Короткое название рода базы, как на кнопках этапа: «AR/ES». Рода нет в списке выбора (редкий род) —
    сокращения его статов защиты; не род вовсе — None."""
    if not kind:
        return None
    hit = next((k['short'] for k in kinds(cat, lang) if k['id'] == kind), None)
    if hit:
        return hit
    table = ((cat or {}).get('stats') or {}).get('stats') or {}
    stats = herostats.kind_stats(cat, [kind])
    return '/'.join((table.get(s) or {}).get('abbr') or s for s in stats) or None


def attributes(cat, lang='ru'):
    """Атрибуты героя из данных игры — выбор для этапа: [{id, name}]."""
    names = _names(cat, lang)
    return [{'id': a, 'name': (names.get(a) or (a, a))[0]} for a in herostats.attributes(cat)]


def hero_choices(cat, geo, lang='ru'):
    """Классы героя и их вознесения — выбор для билда: [{id, name, base, ascendancies}]. id — имя класса
    в данных дерева GGG («Sorceress»), name — как класс называет игра на языке страницы, base — атрибуты,
    с которыми класс начинает ({str, dex, int}), ascendancies — [{id — имя вознесения в данных, name, code —
    как оно зовётся в id узлов вознесения в логе игры: Sorceress3}]. geo — данные дерева (treeplan.load_geo)."""
    names = (((cat or {}).get('lang') or {}).get(lang) or {}).get('heroClasses') or {}
    out = []
    for cid, c in ((geo or {}).get('classes') or {}).items():
        out.append({'id': cid, 'name': names.get(cid) or cid, 'base': dict(zip(('str', 'dex', 'int'), c.get('base') or (0, 0, 0))),
                    'ascendancies': [{'id': a['name'], 'name': names.get(a['name']) or a['name'], 'code': a['id']}
                                     for a in c.get('ascendancies') or []]})
    return out


def prop_choices(cat, lang='ru'):
    """Свойства игры, из которых билд собирает свой стат, — строки аффиксов вещей: [{key, text}] по
    алфавиту. key — ключ строки каталога, text — строка на языке страницы («#% увеличение урона хаосом»).
    Строка, у которой в данных игры нет текста (заготовки: ловушки, рыбалка), в выбор не идёт. У двух строк
    с одним текстом (скорость атаки героя и самого оружия) та, что меняет саму вещь, помечена."""
    rows = []
    for key in gamedata.affix_lines(cat):
        text = gamedata.line_text(cat, key, lang)
        if text != key:
            rows.append({'key': key, 'text': text + (tr(' · на самом предмете') if key.startswith('local_') else '')})
    return sorted(rows, key=lambda r: r['text'].lstrip('#%+ ').lower())


def stat_parts(cat, sid, lang='ru'):
    """Из чего складывается стат — словами игры: {lines, prop, local, cap, half, base, penalty, void}.
      lines   — строки свойств, которые складываются в стат со всех вещей («#% к сопротивлению огню»);
      prop    — собственное свойство вещи, которое идёт в стат числом («Броня»), и local — строки, которые
                уже внутри этого числа («# к броне» на доспехе);
      cap     — предел, выше которого стат бесполезен; half — у строк «от # до #» в стат идёт среднее;
      base    — в стат идёт и свойство базы, которого на вещи не написано (штраф скорости доспеха);
      penalty — на стат ложится штраф за пройденные акты; void — строки узла дерева, с которыми стат
                теряет смысл.
    Строка относится к стату, если все её свойства игры входят в него."""
    s = (((cat or {}).get('stats') or {}).get('stats') or {}).get(sid) or {}
    pack = ((cat or {}).get('lang') or {}).get(lang) or {}
    texts = pack.get('stats') or {}

    def lines(ids):
        want, out = set(ids or ()), []
        for key, shapes in texts.items():
            if shapes and want.issuperset(key.split()) and shapes[0] not in out:
                out.append(shapes[0])
        return out

    prop = next((name for name, pid in (pack.get('props') or {}).items() if pid == s.get('prop')), None) if s.get('prop') else None
    out = {'lines': lines(s.get('ids'))}
    if prop:
        out['prop'], out['local'] = prop, lines(s.get('local'))
    for key, field in (('cap', 'cap'), ('void', 'void')):
        if s.get(field):
            out[key] = s[field]
    for key, on in (('half', s.get('scale') == 0.5), ('base', bool(s.get('base'))), ('penalty', bool(s.get('act_penalty')))):
        if on:
            out[key] = True
    return out


def describe_trees(build, heard=None, geo=None):
    """Деревья билда для вкладки «Дерево»: {'tree': {versions, names}, 'atlas': {versions, names}}. Версия —
    {id, name, nodes: [{id, attr?}]}: полный порядок узлов, у узла «Характеристика» — выбранный в нём
    атрибут; узел без выбора — пустой. В старом файле у дерева героя был атрибут «по умолчанию» (поле attr
    раздела): странице он не отдаётся — его значение записано каждому узлу, который на него опирался
    (treeplan.with_default; geo — данные дерева героя), так что смысл плана тот же. names — названия
    узлов, как их называет игра: из записанного плана и из лога (heard — {id узла: название})."""
    out = {}
    for key in TREES:
        sec = build.get(key) if isinstance(build.get(key), dict) else {}
        default = sec.get('attr') if key == 'tree' and isinstance(sec.get('attr'), str) else None
        vers = []
        for ph in sec.get('phases') or []:
            if isinstance(ph, dict) and ph.get('id'):
                rec = {'id': ph['id'], 'name': ph.get('name') or ph['id'],
                       'nodes': treeplan.with_default(ph.get('nodes'), default, geo if key == 'tree' else None)}
                # узлы с предметов (зачарование амулета): id и слот — когда версия их берёт
                items = [{'id': x['id'], 'slot': x.get('slot')} for x in ph.get('items') or []
                         if isinstance(x, dict) and x.get('id')]
                if items:
                    rec['items'] = items
                    if isinstance(ph.get('without'), str) and ph['without']:
                        rec['without'] = ph['without']      # запасная: пока узлов с предметов на предметах нет
                vers.append(rec)
        out[key] = {'versions': vers, 'names': treeplan.known_names(sec, heard)}
    return out


def versions(cat, plan, tree_lines, lang='ru'):
    """Версии деревьев билда — выбор для этапа: {'tree': [...], 'atlas': [...]}, запись — {id, name,
    nodes (сколько узлов)}; у версии дерева героя ещё voids — статы, которые она обнуляет: [{id, name,
    node, line}]. По ним страница показывает, почему стат на этапе не в счёт."""
    names = _names(cat, lang)
    rules = herostats.void_rules(cat)
    out = {}
    for key in ('tree', 'atlas'):
        out[key] = []
        for ph in (plan.get(key) or {}).get('phases') or []:
            rec = {'id': ph['id'], 'name': ph.get('name') or ph['id'], 'nodes': len(ph.get('nodes') or [])}
            if key == 'tree':
                gone = herostats.version_voids(rules, ph, tree_lines)
                rec['voids'] = [dict(why, id=sid, name=(names.get(sid) or (sid, sid))[0]) for sid, why in gone.items()]
            out[key].append(rec)
    return out


def gem_choices(cat, lang='ru'):
    """Камни из данных игры — названия для умений и поддержек: {'skills': [...], 'supports': [...]},
    запись — {name: «Русское (English)», level: уровень камня из данных}. У умения это стартовый уровень
    камня (ниже такое умение не сделать), у поддержки — ранг камня поддержки. Только камни, у которых
    в данных есть название на языке игрока: остальные (умения восхождения) называют рукой."""
    names = (((cat or {}).get('lang') or {}).get(lang) or {}).get('gems') or {}
    found = {'skills': {}, 'supports': {}}
    for g in ((cat or {}).get('gems') or {}).values():
        own = names.get(g.get('name'))
        if not own:
            continue
        part = found['supports' if g.get('type') == 'support' else 'skills']
        title, lv = '%s (%s)' % (own, g['name']), g.get('level') or 0
        # одно название у нескольких записей игры (умение оружия и его камень): берём уровень камня
        part[title] = max(part.get(title, 0), lv)
    return {k: [{'name': t, 'level': lv} for t, lv in sorted(v.items())] for k, v in found.items()}


def gem_facts(cat, lang='ru'):
    """Справка игры об умениях для страницы «Билд»: английское имя камня умения -> {level — с какого уровня
    камня умение делают (0 — камня не делают: умение предмета или восхождения), bases — базы предметов,
    которые дают это умение сами («Русское (English)»), sockets — у умения восхождения: с какого уровня героя
    открыто 3-е, 4-е, 5-е гнездо поддержки}. Автор этого не выбирает: страница показывает."""
    if not cat:
        return {}
    names = (((cat.get('lang') or {}).get(lang) or {}).get('bases')) or {}
    givers = {}
    for b in (cat.get('bases') or {}).values():
        for key in b.get('grants') or ():
            own = names.get(b.get('name'))
            givers.setdefault(key, set()).add('%s (%s)' % (own, b['name']) if own else b.get('name'))
    out = {}
    sockets = (((cat.get('rules') or {}).get('gemSockets')) or {}).get('level') or {}
    for name, rec in gamedata.fact_index(cat)['gems'].items():
        out[name] = {'level': rec['level']}
        if rec.get('ascendancy') and sockets:
            out[name]['sockets'] = dict(sockets)
        bases = sorted(set().union(*[givers.get(k, set()) for k in rec['keys']]))
        if bases:
            out[name]['bases'] = bases
    return out


def class_bases(cat, lang='ru'):
    """Базы вещей из данных игры по классам предметов — названия для вещей слота: {класс: [{name: «Русское
    (English)», gear: описание базы («Sceptre», «Helmet int_armour»), level: с какого уровня зоны падает,
    icon: рисунок, made: вариант, который делают из базы, — только у таких}]}; внутри класса — по уровню и названию."""
    cache = cat.setdefault('_class_bases', {}) if isinstance(cat, dict) else {}
    if lang in cache:
        return cache[lang]
    names = (((cat or {}).get('lang') or {}).get(lang) or {}).get('bases') or {}
    out, seen = {}, set()
    for b in ((cat or {}).get('bases') or {}).values():
        own = names.get(b.get('name'))
        if not b.get('class') or not own or 'demigods' in (b.get('tags') or ()):
            continue
        title = '%s (%s)' % (own, b['name'])
        if (b['class'], title) in seen:
            continue
        seen.add((b['class'], title))
        kinds_ = gamedata.ARMOUR_KINDS & set(b.get('tags') or ())
        gear = '%s %s' % (b['class'], next(iter(kinds_))) if len(kinds_) == 1 else b['class']
        row = {'name': title, 'gear': gear, 'level': b.get('level') or 1, 'icon': b.get('icon')}
        if 'runeforged' in (b.get('tags') or ()):
            row['made'] = True      # вариант, который делают из базы, а не находят (gamedata.named_bases)
        out.setdefault(b['class'], []).append(row)
    for rows in out.values():
        rows.sort(key=lambda r: (r['level'], r['name']))
    cache[lang] = out
    return out


def base_choices(cat, slots, lang='ru'):
    """Базы вещей слота: {слот: [запись class_bases]} — базы тех классов, что слот назвал (classes),
    по порядку классов и уровня."""
    by_class = class_bases(cat, lang)
    out = {}
    for s in slots or []:
        rows, seen = [], set()
        for c in slotwear.classes_of(s):
            for r in by_class.get(c, ()) if isinstance(c, str) else ():
                if r['name'] not in seen:
                    seen.add(r['name'])
                    rows.append(r)
        out[s['id']] = rows
    return out


def class_kinds(cat):
    """Классы предметов, какие бывают у баз в данных игры, и роды баз каждого: {класс: {род}}. Род говорит,
    что за защита на вещи (str_armour — броня, int_armour — энергощит…); у оружия и бижутерии родов нет."""
    out = {}
    for b in ((cat or {}).get('bases') or {}).values():
        if b.get('class') and 'demigods' not in (b.get('tags') or ()):
            out.setdefault(b['class'], set()).update(gamedata.ARMOUR_KINDS & set(b.get('tags') or ()))
    return out


def item_classes(cat, lang='ru'):
    """Классы предметов из данных игры — из чего собирать слот: [{id, name, kinds}]. id — класс, как его
    называют данные игры («Crossbow», «Body Armour»). name — по-русски: как клиент пишет класс в строке
    «Класс предмета» (слой языка, classes), а где это слово не проверено — как класс называет таблица
    классов игры (classNames); нет ни того, ни другого — None. kinds — роды баз класса из тех, что страница
    умеет назвать ([{id, label}], порядок — как у баз защиты этапа)."""
    pack = ((cat or {}).get('lang') or {}).get(lang) or {}
    words = {}
    for word, cid in (pack.get('classes') or {}).items():
        words.setdefault(cid, word)
    more = pack.get('classNames') or {}
    labels = {k['id']: k['label'] for k in kinds(cat, lang)}
    out = [{'id': c, 'name': words.get(c) or more.get(c), 'kinds': [{'id': k, 'label': labels[k]} for k in labels if k in ks]}
           for c, ks in class_kinds(cat).items()]
    return sorted(out, key=lambda c: (c['name'] is None, c['name'] or c['id']))


def route_ids(route):
    """Id целей маршрута (боссы, награды, уровень героя): цели билда такой id дать нельзя."""
    return {g['id'] for g in (route or {}).get('goals') or [] if isinstance(g, dict) and g.get('id')}


def describe_goals(cat, plan, build, route=None, lang='ru'):
    """Цели билда для страницы и из чего их выбирать. build и route — файлы билда и маршрута как есть:
    цели отдаются такими, какими записаны (ступени уровня камня, которые программа достраивает сама,
    сюда не идут). taken — id целей маршрута: новой цели билда такой id дать нельзя."""
    mine = [g for g in build.get('goals') or [] if isinstance(g, dict) and g.get('id')]
    ids = {g['id'] for g in mine}
    slots = [s for s in build.get('slots') or [] if isinstance(s, dict) and s.get('id')]
    table = ((cat or {}).get('stats') or {}).get('stats') or {}
    return {
        'goals': mine,
        # слоты — как в файле: их правят на вкладке «Вещи»; классы предметов и базы по классам — из данных игры
        'slots': [dict(s) for s in slots],
        'classes': item_classes(cat, lang),
        'classBases': class_bases(cat),
        'gems': gem_choices(cat),
        # справка игры об умениях: с какого уровня камня умение делают и какие базы дают его сами
        'gemFacts': gem_facts(cat),
        # единица стата — в подпись цели по стату («от 75%»)
        'units': {sid: st['unit'] for sid, st in table.items() if st.get('unit')},
        # сколько уровней у камня — по таблице плана, а нет её — по правилу каталога (данные игры)
        'gemLevels': len(build.get('gemLevels') or ((cat or {}).get('rules') or {}).get('gemHero') or []),
        'groups': list(plan.get('groupOrder') or []),
        'taken': sorted(route_ids(route)),
    }


def describe(cat, plan, tree_lines, lang='ru', build=None, route=None, geo=None, heard=None):
    """Всё, что нужно странице «Билд»: шаги маршрута (к чему привязывать этап и цель), из чего выбирать —
    версии деревьев билда, базы защиты, атрибуты и статы из данных игры — и сами этапы: у каждого то,
    что он назвал сам (не названное — None: действует как на прежнем этапе). build и route — файлы билда
    и маршрута как есть (план из частей): тогда страница получает и цели билда с выбором для них
    (describe_goals), а с ними то, что относится к билду целиком: название, героя (hero; из чего выбирать —
    heroes, по данным дерева geo) и свои статы (statDefs; из чего их собирать — props). cat — каталог
    уже со своими статами билда (gamedata.with_stats): в catalog они помечены own."""
    table = ((cat or {}).get('stats') or {}).get('stats') or {}
    order = ((cat or {}).get('stats') or {}).get('order') or list(table)
    names = _names(cat, lang)
    steps, act = [], None
    # end — шаг на картах (с первого такого шага у героя есть атлас): атлас называет только этап, начатый на картах
    end_at = core.endgame_from(plan.get('steps'))
    for k, s in enumerate(plan.get('steps') or []):
        act = core.act_of(s['zone']) if s.get('zone') else (act or core.act_of(None))
        steps.append({'id': s['id'], 'name': s.get('name') or s['id'], 'act': act, 'end': end_at is not None and k >= end_at})
    stages = []
    for n, st in enumerate(plan.get('stages') or []):
        rec = {'id': st['id'], 'name': st.get('name') or st['id'], 'from': (st.get('from') or None) if n else None}
        for k in buildstage.PARAMS:
            rec[k] = st.get(k)
        if rec['attrs'] is not None:
            rec['attrs'] = list(rec['attrs'])
        if rec['stats'] is not None:
            rec['stats'] = [s['id'] for s in rec['stats']]
        stages.append(rec)
    return {
        'title': plan.get('title') or '',
        'steps': steps,
        'kinds': kinds(cat, lang),
        'attrs': attributes(cat, lang),
        # статы для выбора; у каждого — из чего он складывается (parts): страница показывает это подсказкой
        'catalog': [dict({'id': sid, 'name': (names.get(sid) or (sid, sid))[0], 'parts': stat_parts(cat, sid, lang)},
                         **({'own': True} if table[sid].get('own') else {}))
                    for sid in order if sid in table],
        'trees': versions(cat, plan, tree_lines, lang),
        'stages': stages,
        **(describe_goals(cat, plan, build, route, lang) if isinstance(build, dict) else {}),
        **(describe_whole(cat, build, geo, lang) if isinstance(build, dict) else {}),
        **({'treePlan': describe_trees(build, heard, geo)} if isinstance(build, dict) else {}),
    }


def describe_whole(cat, build, geo, lang='ru'):
    """То, что относится к билду целиком, — как записано в файле билда: название (buildTitle), герой
    (hero: {class?, ascendancy?}) и свои статы (statDefs), — и из чего выбирать: heroes — классы
    и вознесения, props — свойства игры для своего стата."""
    hero = build.get('hero') if isinstance(build.get('hero'), dict) else {}
    return {
        'buildTitle': build.get('title') if isinstance(build.get('title'), str) else '',
        'hero': {k: hero[k] for k in ('class', 'ascendancy') if isinstance(hero.get(k), str) and hero[k]},
        'heroes': hero_choices(cat, geo, lang),
        'statDefs': [dict(d) for d in build.get('statDefs') or [] if isinstance(d, dict)] if isinstance(build.get('statDefs'), list) else [],
        'props': prop_choices(cat, lang),
    }


def check(payload, plan, cat, build=None, route=None, verify=None, geo=None):
    """Проверяет присланные разделы билда — название (title), героя (hero), свои статы (statDefs), слоты
    (slots), этапы (stages), цели (goals), любые из них. Возвращает ({раздел: записи
    для файла}, замечания); при любом замечании записей нет. build и route — файлы билда и маршрута как
    есть (нужны целям: прежние записи и чужие id); verify — проверка плана целиком: функция от новых
    разделов, которая собирает план с ними и возвращает новые замечания к нему; geo — данные дерева
    (классы героя). cat — каталог со своими статами билда, какими они станут после этой же правки."""
    if not isinstance(payload, dict) or not any(k in payload for k in PAYLOAD):
        return {}, [tr('нечего записывать: нет ни одного раздела билда')]
    out, problems = {}, []
    if 'stages' in payload:
        out.update(check_stages(payload['stages'], plan, cat, problems))
    whole = [k for k in ('title', 'hero', 'statDefs') if k in payload]
    if whole and not isinstance(build, dict):
        problems.append(tr('название, герой и свои статы правятся только у плана из частей (маршрут, билд, личное)'))
    else:
        if 'title' in payload:
            title = payload['title'].strip() if isinstance(payload['title'], str) else None
            if not title or len(title) > MAX_TITLE:
                problems.append(tr('название билда — текст не длиннее %d знаков') % MAX_TITLE)
            else:
                out['title'] = title
        if 'hero' in payload:
            out['hero'] = check_hero(payload['hero'], geo, problems)
        if 'statDefs' in payload:
            out['statDefs'], found = gamedata.stat_defs(base_of(cat), payload['statDefs'])
            problems.extend(found)
    if any(k in payload for k in ('slots', 'goals')) and not isinstance(build, dict):
        problems.append(tr('%s правятся только у плана из частей (маршрут, билд, личное)') % (
            tr('слоты и цели') if 'slots' in payload else tr('цели')))
    else:
        if 'slots' in payload:
            # цели, какими они будут после этой же правки: слот с целями убрать нельзя
            goals = payload['goals'] if isinstance(payload.get('goals'), list) else None
            out['slots'] = check_slots(payload['slots'], build, cat, problems, goals, plan.get('steps'))
            build = dict(build, slots=out['slots'])       # цели сверяются уже с новыми слотами
        if 'goals' in payload:
            out['goals'] = check_goals(payload['goals'], build, plan, cat, problems, route_ids(route))
    # всё вместе ещё раз глазами сборки плана: уровень камня из таблицы и прочее
    if not problems and verify is not None:
        problems.extend(verify(out))
    return ({} if problems else out), problems


def base_of(cat):
    """Каталог без своих статов билда: таблица статов — только готовые. По нему проверяется новый набор
    своих статов: id своего стата не должен совпасть с готовым, а совпасть с прежним своим — может."""
    table = ((cat or {}).get('stats') or {}).get('stats') or {}
    if not any(s.get('own') for s in table.values()):
        return cat
    keep = {sid: s for sid, s in table.items() if not s.get('own')}
    out = {k: v for k, v in cat.items() if k not in ('_stat_index', '_carriers', '_kinds', '_affix_lines')}
    out['stats'] = dict(cat['stats'], stats=keep, order=[s for s in cat['stats'].get('order') or [] if s in keep])
    return out


def check_hero(raw, geo, problems):
    """Проверяет героя билда и возвращает запись для файла: {class?, ascendancy?} — имена из данных дерева
    GGG. Класс — один из тех, за которые в игре можно играть; вознесение — одно из вознесений этого класса;
    вознесения у билда может не быть (билд без вознесения или до него), класса — тоже (ещё не назван)."""
    classes = (geo or {}).get('classes') or {}
    if not isinstance(raw, dict) or set(raw) - {'class', 'ascendancy'}:
        problems.append(tr('герой: у героя есть класс (class) и восхождение (ascendancy)'))
        return {}
    cls, asc = raw.get('class') or None, raw.get('ascendancy') or None
    if not all(x is None or isinstance(x, str) for x in (cls, asc)):
        problems.append(tr('герой: класс и восхождение — названия из данных дерева'))
        return {}
    if not classes and (cls or asc):
        problems.append(tr('герой: нет данных дерева (planner/static/tree.json) — выбрать класс не из чего'))
        return {}
    out = {}
    if cls:
        if cls not in classes:
            problems.append(tr('герой: класса «%s» нет в данных дерева') % cls)
            return {}
        out['class'] = cls
    if asc:
        if not cls:
            problems.append(tr('герой: восхождение названо, а класс — нет'))
        elif asc not in [a['name'] for a in classes[cls].get('ascendancies') or []]:
            problems.append(tr('герой: у класса «%s» нет восхождения «%s»') % (cls, asc))
        else:
            out['ascendancy'] = asc
    return out


def check_wear(val, idx, known, where, problems):
    """Проверяет присланные периоды слота и возвращает записи для файла по порядку шагов (None — есть замечания).
    Период — что носят в слоте с шага from (нет — с начала забега): classes — классы предметов из данных игры,
    kind — род базы (нет — как у этапа), until — последний шаг (обычно его нет: период длится до следующего)."""
    if not isinstance(val, list) or not val or len(val) > MAX_WEAR:
        problems.append(tr('%s: периоды — список, хотя бы один и не больше %d') % (where, MAX_WEAR))
        return None
    out, starts, bad = [], set(), len(problems)
    for p in val:
        if not isinstance(p, dict) or set(p) - set(WEAR_ORDER):
            problems.append(tr('%s: у периода есть шаг начала (from), классы (classes), род базы (kind) и срок (until)') % where)
            continue
        start = p.get('from') or None
        if start is not None and start not in idx:
            problems.append(tr('%s: шага «%s» в маршруте нет') % (where, start))
            continue
        if start in starts:
            problems.append(tr('%s: два периода начинаются с одного шага') % where)
            continue
        starts.add(start)
        cl = p.get('classes')
        if not (isinstance(cl, list) and cl and all(isinstance(c, str) for c in cl) and len(set(cl)) == len(cl)):
            problems.append(tr('%s: у периода нужен хотя бы один класс предметов, без повторов') % where)
            continue
        if any(c not in known for c in cl):
            problems.append(tr('%s: класса предметов «%s» нет в данных игры') % (where, next(c for c in cl if c not in known)))
            continue
        rec = dict([('from', start)] if start else [], classes=list(cl))
        kind = p.get('kind') or None
        if kind is not None:
            if not isinstance(kind, str) or not any(kind in known[c] for c in cl):
                problems.append(tr('%s: у классов периода нет баз рода «%s»') % (where, kind))
                continue
            rec['kind'] = kind
        until = p.get('until') or None
        if until is not None:
            if until not in idx or (start and idx[until] < idx[start]):
                problems.append(tr('%s: срок периода — шаг маршрута не раньше его начала') % where)
                continue
            rec['until'] = until
        out.append(rec)
    if len(problems) > bad:
        return None
    return sorted(out, key=lambda r: idx[r['from']] if r.get('from') else -1)


def check_slots(raw, build, cat, problems, goals=None, steps=None):
    """Проверяет присланные слоты и возвращает записи для файла (при замечаниях — что успело набраться).
    Слот — носитель вещей билда: id, название (name) и что в нём носят по ходу забега — периоды (wear,
    slotwear): с какого шага какие классы предметов и какой род базы. Слот старого вида называл это иначе —
    classes (классы на весь забег) и gear («Ring», «Helmet int_armour»); такая запись по-прежнему проходит.
    Поле, которое у прежней записи слота было таким же, проходит как есть (doneOn и прочее, чего страница
    не правит). goals — цели билда, какими они станут после этой же правки (None — как в файле): слот,
    в котором есть цели, убрать нельзя; период, в котором стоит предмет слота, — тоже. steps — шаги маршрута."""
    if not isinstance(raw, list) or len(raw) > MAX_SLOTS:
        problems.append(tr('слоты: нужен список не длиннее %d') % MAX_SLOTS)
        return []
    old = {s['id']: s for s in build.get('slots') or [] if isinstance(s, dict) and s.get('id')}
    known = class_kinds(cat)
    idx = slotwear.step_index(steps)
    step_name = {s['id']: s.get('name') or s['id'] for s in steps or [] if isinstance(s, dict) and s.get('id')}
    out, ids = [], set()
    for s in raw:
        if not (isinstance(s, dict) and isinstance(s.get('id'), str) and RE_ID.fullmatch(s['id'])):
            problems.append(tr('слот: id — латинские буквы, цифры, дефис'))
            continue
        sid = s['id']
        if sid in ids:
            problems.append(tr('слот «%s»: такой id уже есть') % sid)
            continue
        ids.add(sid)
        was, rec = old.get(sid) or {}, {}
        where = tr('слот «%s»') % ((s['name'].strip() if isinstance(s.get('name'), str) else '') or sid)
        for key, val in s.items():
            if key == 'id' or (key in was and was[key] == val):
                rec[key] = val
            elif key == 'name':
                if not isinstance(val, str) or len(val.strip()) > MAX_NAME:
                    problems.append(tr('%s: название — текст не длиннее %d знаков') % (where, MAX_NAME))
                elif val.strip():
                    rec[key] = val.strip()
            elif key == 'classes':
                if not (isinstance(val, list) and val and all(isinstance(c, str) for c in val) and len(set(val)) == len(val)):
                    problems.append(tr('%s: классы предметов — список без повторов, хотя бы один класс') % where)
                elif any(c not in known for c in val):
                    problems.append(tr('%s: класса предметов «%s» нет в данных игры') % (where, next(c for c in val if c not in known)))
                else:
                    rec[key] = list(val)
            elif key == 'wear':
                wear = check_wear(val, idx, known, where, problems)
                if wear is not None:
                    rec[key] = wear
            elif key == 'gear':
                if val in (None, ''):
                    continue
                if not isinstance(val, str):
                    problems.append(tr('%s: что носят в слоте — класс предмета и, если нужно, род базы') % where)
                else:
                    rec[key] = val.strip()        # класс и род сверяются ниже: с классами слота
            else:
                problems.append(tr('%s: поле «%s» со страницы не правится') % (where, key))
        if not rec.get('name'):
            problems.append(tr('слот «%s»: нужно название') % sid)
        if 'classes' not in rec and 'wear' not in rec and not was:
            problems.append(tr('%s: нужен хотя бы один период — что в слоте носят') % where)
        # что носят в слоте: класс — один из классов слота, род — из тех, что у баз класса бывают
        if rec.get('gear') and not (was.get('gear') == rec['gear'] and was.get('classes') == rec.get('classes')):
            cls, kind = gamedata.spec_parts(rec['gear'])
            if cls not in (rec.get('classes') or ()):
                problems.append(tr('%s: в слоте носят «%s», а такого класса у слота нет') % (where, cls))
            elif kind and kind not in known.get(cls, ()):
                problems.append(tr('%s: у класса «%s» нет баз рода «%s»') % (where, cls, kind))
        if rec != was:
            # изменённая и новая запись — в привычном порядке полей; нетронутая остаётся как записана
            rec = dict([(k, rec[k]) for k in SLOT_ORDER if k in rec] + [(k, v) for k, v in rec.items() if k not in SLOT_ORDER])
        out.append(rec)
    # цели слотов: какими они будут после этой правки
    mine = {}
    for g in (build.get('goals') or []) if goals is None else goals:
        if isinstance(g, dict) and isinstance(g.get('slot'), str):
            mine.setdefault(g['slot'], []).append(g)
    title = lambda g: g.get('title') if isinstance(g.get('title'), str) and g['title'].strip() else g.get('id')   # noqa: E731
    for sid, was in old.items():
        if sid not in ids and mine.get(sid):
            problems.append(tr('слот «%s» не убрать: в нём есть цели (%d), первая — «%s»; сначала уберите их') % (
                was.get('name') or sid, len(mine[sid]), title(mine[sid][0])))
    for rec in out:
        # предмет слота стоит в одном из его периодов: период, в котором есть предметы, убрать нельзя
        if slotwear.stated(rec):
            starts = {p.get('from') for p in rec['wear']}
            for g in mine.get(rec['id'], ()):
                line = g.get('use') if g.get('use') in idx else None
                if line not in starts:
                    problems.append(tr('слот «%s»: у предмета «%s» нет периода (%s) — сначала уберите или перенесите его') % (
                        rec.get('name') or rec['id'], title(g), tr('с шага «%s»') % step_name.get(line, line) if line else tr('с самого начала')))
                    break
            continue
        was = old.get(rec['id']) or {}
        if rec.get('classes') == was.get('classes') or not isinstance(rec.get('classes'), list):
            continue
        for g in mine.get(rec['id'], ()):
            cls = gamedata.spec_parts(g.get('gear'))[0]
            if cls and cls not in rec['classes']:
                problems.append(tr('слот «%s»: класс «%s» не убрать — его называет предмет «%s»') % (rec.get('name') or rec['id'], cls, title(g)))
                break
    return out


def check_goals(raw, build, plan, cat, problems, taken=()):
    """Проверяет присланные цели билда и возвращает записи для файла (при замечаниях — что успело
    набраться). Поле, которое у прежней записи цели было таким же, проходит как есть: страница правит
    не всё, что в цели бывает (probe, heard, node…). Остальное — только поля, которые страница
    правит, и только верного вида. Пустая строка и снятая пометка в запись не идут."""
    if not isinstance(raw, list) or len(raw) > MAX_GOALS:
        problems.append(tr('цели: нужен список не длиннее %d') % MAX_GOALS)
        return []
    old = {g['id']: g for g in build.get('goals') or [] if isinstance(g, dict) and g.get('id')}
    taken = set(taken)
    steps = {s['id'] for s in plan.get('steps') or []}
    slots = {s['id'] for s in build.get('slots') or [] if isinstance(s, dict)}
    table = ((cat or {}).get('stats') or {}).get('stats') or {}
    out, ids = [], set()
    for g in raw:
        if not (isinstance(g, dict) and isinstance(g.get('id'), str) and RE_GOAL_ID.fullmatch(g['id'])):
            problems.append(tr('цель: id — латинские буквы, цифры, дефис'))
            continue
        gid = g['id']
        if gid in ids or gid in taken:
            problems.append(tr('цель «%s»: такой id уже есть%s') % (gid, tr(' у цели маршрута') if gid in taken else ''))
            continue
        ids.add(gid)
        was, rec = old.get(gid) or {}, {}
        name = g.get('title').strip() if isinstance(g.get('title'), str) else ''
        for key, val in g.items():
            if key == 'id' or (key in was and was[key] == val):
                rec[key] = val
            elif key in GOAL_TEXT:
                if val is None:
                    continue
                text = val.strip() if isinstance(val, str) else None
                if text is None or len(text) > GOAL_TEXT[key]:
                    problems.append(tr('цель «%s»: поле %s — текст не длиннее %d знаков') % (name or gid, key, GOAL_TEXT[key]))
                elif text:
                    rec[key] = text
            elif key in GOAL_STEPS:
                if val in (None, ''):
                    continue
                if val not in steps:
                    problems.append(tr('цель «%s»: шага «%s» в маршруте нет') % (name or gid, val))
                else:
                    rec[key] = val
            elif key in GOAL_FLAGS:
                if val not in (True, False, None):
                    problems.append(tr('цель «%s»: пометка %s — да или нет') % (name or gid, key))
                elif val:
                    rec[key] = True
            elif key in GOAL_INTS:
                lo, hi = GOAL_INTS[key]
                if val in (None, ''):
                    continue
                if not core.is_int(val) or not lo <= val <= hi:
                    problems.append(tr('цель «%s»: поле %s — целое от %d до %d') % (name or gid, key, lo, hi))
                else:
                    rec[key] = val
            elif key == 'min':
                if isinstance(val, bool) or not isinstance(val, (int, float)) or val < 0:
                    problems.append(tr('цель «%s»: «от» — число, меньше которого стата быть не должно') % (name or gid))
                else:
                    rec[key] = val
            elif key == 'stat':
                if val not in table:
                    problems.append(tr('цель «%s»: стата «%s» нет в данных игры') % (name or gid, val))
                else:
                    rec[key] = val
            elif key == 'slot':
                if val not in slots:
                    problems.append(tr('цель «%s»: слота «%s» в билде нет') % (name or gid, val))
                else:
                    rec[key] = val
            elif key == 'kind':
                if val not in GOAL_KINDS:
                    problems.append(tr('цель «%s»: такого вида цели у билда нет') % (name or gid))
                else:
                    rec[key] = val
            elif key == 'rarity':
                if val in (None, ''):
                    continue
                if val not in core.ITEM_RARITIES:
                    problems.append(tr('цель «%s»: редкость — Normal, Magic или Rare') % (name or gid))
                else:
                    rec[key] = val
            elif key == 'icon':
                if val in (None, ''):
                    continue
                if not (isinstance(val, str) and core.RE_ICON_NAME.fullmatch(val)):
                    problems.append(tr('цель «%s»: рисунок назван не так') % (name or gid))
                else:
                    rec[key] = val
            elif key in GOAL_REFS:
                if val in (None, ''):
                    continue
                rec[key] = val            # есть ли такая цель, видно после сбора всего списка
            else:
                problems.append(tr('цель «%s»: поле «%s» со страницы не правится') % (name or gid, key))
        if not rec.get('title'):
            problems.append(tr('цель «%s»: нужно название') % gid)
        out.append(rec)
    by_id = {g['id']: g for g in out}
    for g in out:
        name = g.get('title') or g['id']
        for key in GOAL_REFS:
            if g.get(key) and g[key] not in by_id and g[key] not in taken:
                problems.append(tr('цель «%s»: нет цели «%s» (%s)') % (name, g[key], key))
        if g.get('kind') in ('support', 'gem') and (by_id.get(g.get('for')) or {}).get('kind') != 'skill':
            problems.append(tr('цель «%s»: камень поддержки и уровень камня живут при умении') % name)
        # Заметки у умения и у того, что при нём, нет: на странице забега заметку
        # показывало только наведение мыши. Прежняя, из файла, записанного раньше, проходит как есть.
        of_skill = g.get('kind') == 'skill' or (by_id.get(g.get('for')) or {}).get('kind') == 'skill'
        if of_skill and g.get('note') and g['note'] != (old.get(g['id']) or {}).get('note'):
            problems.append(tr('цель «%s»: заметки у умения, камня поддержки и уровня камня нет') % name)
        if g.get('kind') == 'gem' and g.get('part') == 'level' and g['id'] not in old:
            # ступень уровня камня носит тот же id, что программа даёт ей сама: отметки ступени не теряются
            tail = g['for'][6:] if str(g.get('for')).startswith('skill-') else g.get('for')
            if not str(g.get('title')).isdigit() or g['id'] != 'gem%s-%s' % (g['title'], tail):
                problems.append(tr('цель «%s»: уровень камня — число, а id ступени — gem<уровень>-<умение>') % name)
        if g.get('stat') and not (g.get('slot') and g.get('part') and 'min' in g):
            problems.append(tr('цель «%s»: цели по стату нужны слот, стат и число «от»') % name)
        if g.get('rarity') and not (g.get('slot') and not g.get('part')):
            problems.append(tr('цель «%s»: редкость бывает только у предмета слота') % name)
    # предмет и стат слота стоят в одном из периодов слота (use = шаг начала периода)
    wears = {s['id']: {p.get('from') for p in s['wear'] if isinstance(p, dict)}
             for s in build.get('slots') or [] if isinstance(s, dict) and slotwear.stated(s)}
    step_name = {s['id']: s.get('name') or s['id'] for s in plan.get('steps') or []}
    for g in out:
        if g.get('slot') in wears and (g.get('use') or None) not in wears[g['slot']]:
            problems.append(tr('цель «%s»: у слота нет периода %s') % (
                g.get('title') or g['id'], tr('с шага «%s»') % step_name.get(g['use'], g['use']) if g.get('use') else tr('с самого начала')))
    return out


def check_stages(raw, plan, cat, problems):
    """Проверяет присланный раздел этапов. Возвращает {'stages': записи для файла} — или пусто, если
    есть замечания (они дописываются в problems). У прежнего этапа (с тем же id) сохраняются поля,
    которых страница не правит; у его стата — прочие поля записи (cap)."""
    found = []
    rows = _stages(raw, plan, cat, found)
    problems.extend(found)
    return {} if found else {'stages': rows}


def _stages(raw, plan, cat, problems):
    if not isinstance(raw, list):
        problems.append(tr('этапы: нужен список'))
        return []
    if not raw:
        problems.append(tr('нужен хотя бы один этап — тот, что действует с самого начала'))
        return []
    if len(raw) > MAX_STAGES:
        problems.append(tr('этапов больше %d') % MAX_STAGES)
        return []
    table = ((cat or {}).get('stats') or {}).get('stats') or {}
    old = {st['id']: st for st in plan.get('stages') or []}
    known = {k['id'] for k in kinds(cat)}
    attrs_all = herostats.attributes(cat)
    order = {s['id']: i for i, s in enumerate(plan.get('steps') or [])}
    have = {key: {ph['id'] for ph in (plan.get(key) or {}).get('phases') or []} for key in ('tree', 'atlas')}
    rows, ids, starts = [], set(), set()
    for st in raw:
        if not (isinstance(st, dict) and isinstance(st.get('id'), str) and RE_ID.fullmatch(st['id'])):
            problems.append(tr('этап: id — латинские буквы, цифры, дефис'))
            continue
        sid = st['id']
        name = st.get('name').strip() if isinstance(st.get('name'), str) else ''
        start = st.get('from') or None
        if sid in ids:
            problems.append(tr('этап «%s» прислан дважды') % sid)
            continue
        if not name or len(name) > MAX_NAME:
            problems.append(tr('этап «%s»: нужно название не длиннее %d знаков') % (sid, MAX_NAME))
            continue
        if start is not None and start not in order:
            problems.append(tr('этап «%s»: шага «%s» в маршруте нет') % (name, start))
            continue
        if start in starts:
            problems.append(tr('этап «%s»: с шага «%s» уже начинается другой этап') % (name, start) if start
                            else tr('с самого начала действует только один этап — остальным нужен шаг начала'))
            continue
        ids.add(sid)
        starts.add(start)
        rec = {'id': sid}
        if start is not None:
            rec['from'] = start
        rec['name'] = name
        for key, what in (('tree', tr('дерева')), ('atlas', tr('атласа'))):
            if st.get(key) is not None:
                if st[key] not in have[key]:
                    problems.append(tr('этап «%s»: версии %s «%s» в билде нет') % (name, what, st[key]))
                else:
                    rec[key] = st[key]
        if st.get('kind') is not None:
            if st['kind'] not in known:
                problems.append(tr('этап «%s»: такой базы защиты в данных игры нет') % name)
            else:
                rec['kind'] = st['kind']
        if st.get('attrs') is not None:
            if not isinstance(st['attrs'], list) or any(a not in attrs_all for a in st['attrs']):
                problems.append(tr('этап «%s»: атрибуты — только те, что есть в игре') % name)
            else:
                # в порядке каталога; пустой список — «никаких», это тоже выбор этапа
                rec['attrs'] = [a for a in attrs_all if a in st['attrs']]
        if st.get('stats') is not None:
            was = {s['id']: s for s in (old.get(sid) or {}).get('stats') or []}
            stats, seen = [], set()
            if not isinstance(st['stats'], list) or len(st['stats']) > MAX_STATS:
                problems.append(tr('этап «%s»: статы — список не длиннее %d') % (name, MAX_STATS))
            else:
                for x in st['stats']:
                    x = x.get('id') if isinstance(x, dict) else x
                    if x not in table:
                        problems.append(tr('этап «%s»: стата «%s» нет в данных игры') % (name, x))
                    elif x in seen:
                        problems.append(tr('этап «%s»: стат «%s» записан дважды') % (name, x))
                    else:
                        seen.add(x)
                        # запись стата — просто id; у прежней записи с прочими полями (cap) они остаются
                        extra = {k: v for k, v in (was.get(x) or {}).items() if k != 'id'}
                        stats.append(dict({'id': x}, **extra) if extra else x)
                rec['stats'] = stats
        rec.update({k: v for k, v in (old.get(sid) or {}).items() if k not in STAGE_KEYS})
        rows.append(rec)
    if not problems and None not in starts:
        problems.append(tr('нет этапа, который действует с самого начала'))
    if problems:
        return []
    rows.sort(key=lambda r: -1 if r.get('from') is None else order[r['from']])
    return rows


def _dumps(x):
    return json.dumps(x, ensure_ascii=False)


def render(key, items):
    """Текст раздела-списка в том виде, в каком он лежит в файле билда: запись — одна строка."""
    if not items:
        return ['  %s: []' % _dumps(key)]
    return (['  %s: [' % _dumps(key)] +
            ['    %s%s' % (_dumps(x), ',' if i < len(items) - 1 else '') for i, x in enumerate(items)] + ['  ]'])


def splice(text, key, items):
    """Текст файла билда с новым разделом-списком key. Всё остальное остаётся как было — иначе
    ValueError. Раздела ещё нет — он встаёт перед разделом дерева, а если нет и его, то последним."""
    eol = '\r\n' if '\r\n' in text else '\n'
    lines = text.split(eol)
    head = '  %s: [' % _dumps(key)
    starts = [i for i, ln in enumerate(lines) if ln.startswith(head)]
    before = json.loads(text)
    if len(starts) > 1 or (not starts and key in before) or (starts and key not in before):
        raise ValueError(tr('раздел «%s» записан непривычно — править его со страницы нельзя') % key)
    new = render(key, items)
    if starts:
        s = starts[0]
        # раздел в одну строку («"stages": []») кончается там же, где начался
        e = s if lines[s].rstrip(',').endswith(']') else next(
            (i for i in range(s + 1, len(lines)) if lines[i] in ('  ],', '  ]')), None)
        if e is None:
            raise ValueError(tr('у раздела «%s» не найден конец') % key)
        if lines[e].endswith(','):
            new[-1] += ','
        out = eol.join(lines[:s] + new + lines[e + 1:])
    else:
        tree = [i for i, ln in enumerate(lines) if ln == '  "tree": {']
        if len(tree) == 1:
            new[-1] += ','
            out = eol.join(lines[:tree[0]] + new + lines[tree[0]:])
        else:
            ends = [i for i, ln in enumerate(lines) if ln == '}']
            e = (ends[-1] if ends else 0) - 1
            while e >= 0 and not lines[e].strip():
                e -= 1
            if not ends or e < 0:
                raise ValueError(tr('файл билда записан непривычно — добавить в него раздел «%s» нельзя') % key)
            lines[e] += ','
            out = eol.join(lines[:e + 1] + new + lines[e + 1:])
    after = json.loads(out)
    rest = lambda d: {k: v for k, v in d.items() if k != key}   # noqa: E731
    order = list(before) == list(after) if key in before else [k for k in after if k != key] == list(before)
    if after.get(key) != items or rest(before) != rest(after) or not order:
        raise ValueError(tr('после правки изменилось бы что-то ещё — файл не тронут'))
    return out


def splice_value(text, key, value):
    """Текст файла билда с новым значением раздела в одну строку (название билда, герой): «  "hero": {…},».
    Раздела ещё нет — он встаёт перед слотами. Всё остальное остаётся как было — иначе ValueError."""
    eol = '\r\n' if '\r\n' in text else '\n'
    lines = text.split(eol)
    head = '  %s: ' % _dumps(key)
    at = [i for i, ln in enumerate(lines) if ln.startswith(head)]
    before = json.loads(text)
    if len(at) > 1 or (not at and key in before) or (at and key not in before):
        raise ValueError(tr('раздел «%s» записан непривычно — править его со страницы нельзя') % key)
    new = head + _dumps(value)
    if at:
        # раздел должен умещаться в своей строке: иначе это не тот раздел, что пишет страница
        try:
            whole = json.loads('{' + lines[at[0]].strip().rstrip(',') + '}')
        except ValueError:
            whole = None
        if whole != {key: before[key]}:
            raise ValueError(tr('раздел «%s» записан не в одну строку — править его со страницы нельзя') % key)
        lines[at[0]] = new + (',' if lines[at[0]].rstrip().endswith(',') else '')
    else:
        slots = [i for i, ln in enumerate(lines) if ln.startswith('  "slots": [')]
        if len(slots) != 1:
            raise ValueError(tr('файл билда записан непривычно — добавить в него раздел «%s» нельзя') % key)
        lines.insert(slots[0], new + ',')
    out = eol.join(lines)
    after = json.loads(out)
    rest = lambda d: {k: v for k, v in d.items() if k != key}   # noqa: E731
    order = list(before) == list(after) if key in before else [k for k in after if k != key] == list(before)
    if after.get(key) != value or rest(before) != rest(after) or not order:
        raise ValueError(tr('после правки изменилось бы что-то ещё — файл не тронут'))
    return out


def _goal_chunks(lines, s, e):
    """Записи раздела целей как они лежат в файле: {id: (строки записи без запятой в конце, запись)}.
    Запись начинается строкой «    {"id": …» и может занимать несколько строк (probe — на своей)."""
    chunks, cur = [], None
    for ln in lines[s + 1:e]:
        if ln.startswith('    {'):
            cur = [ln]
            chunks.append(cur)
        elif cur is not None and ln.strip():
            cur.append(ln)
        elif ln.strip():
            raise ValueError(tr('раздел «goals» записан непривычно — править его со страницы нельзя'))
    out = {}
    for ch in chunks:
        ch[-1] = ch[-1][:-1] if ch[-1].endswith(',') else ch[-1]
        rec = json.loads('\n'.join(ch))
        out[rec.get('id')] = (ch, rec)
    return out


def splice_goals(text, goals):
    """Текст файла билда с новым разделом целей. Запись цели, которая не изменилась (те же поля в том же
    порядке), остаётся в файле знак в знак — как была написана; изменённая и новая пишутся одной строкой.
    Всё остальное остаётся как было — иначе ValueError."""
    eol = '\r\n' if '\r\n' in text else '\n'
    lines = text.split(eol)
    starts = [i for i, ln in enumerate(lines) if ln == '  "goals": [']
    before = json.loads(text)
    if len(starts) != 1 or 'goals' not in before:
        raise ValueError(tr('раздел «goals» записан непривычно — править его со страницы нельзя'))
    s = starts[0]
    e = next((i for i in range(s + 1, len(lines)) if lines[i] in ('  ],', '  ]')), None)
    if e is None:
        raise ValueError(tr('у раздела «goals» не найден конец'))
    old = _goal_chunks(lines, s, e)
    body = []
    for n, g in enumerate(goals):
        was = old.get(g['id'])
        ch = list(was[0]) if was and was[1] == g and list(was[1]) == list(g) else ['    ' + _dumps(g)]
        if n < len(goals) - 1:
            ch[-1] += ','
        body += ch
    out = eol.join(lines[:s + 1] + body + lines[e:])
    after = json.loads(out)
    rest = lambda d: {k: v for k, v in d.items() if k != 'goals'}   # noqa: E731
    same_order = [list(g) for g in after.get('goals') or []] == [list(g) for g in goals]
    if after.get('goals') != goals or not same_order or rest(before) != rest(after) or list(before) != list(after):
        raise ValueError(tr('после правки изменилось бы что-то ещё — файл не тронут'))
    return out


def render_sections(text, sections):
    """Текст файла билда с новыми разделами ({раздел: записи}). Не сошлось хоть в одном — ValueError."""
    out = text
    for key in ('title', 'hero'):
        if key in sections:
            out = splice_value(out, key, sections[key])
    if 'statDefs' in sections:
        out = splice(out, 'statDefs', sections['statDefs'])
    if 'slots' in sections:
        out = splice(out, 'slots', sections['slots'])
    if 'stages' in sections:
        out = splice(out, 'stages', sections['stages'])
    if 'goals' in sections:
        out = splice_goals(out, sections['goals'])
    return out


def read_text(path):
    """Текст файла плана и была ли в начале метка порядка байтов: (текст, метка)."""
    raw = Path(path).read_bytes()
    return raw.decode('utf-8-sig'), raw.startswith(b'\xef\xbb\xbf')


def write_text(path, text, bom=False, backup_dir=None, tag='build', now=None):
    """Записывает файл плана целиком. Прежний файл перед этим копируется в backup_dir под именем
    <файл>.<tag>-<время>; копий одного вида хранится KEEP_BACKUPS."""
    path = Path(path)
    if backup_dir:
        backup_dir = Path(backup_dir)
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime('%Y%m%d-%H%M%S', time.localtime(now))
        shutil.copy2(path, backup_dir / ('%s.%s-%s%s' % (path.stem, tag, stamp, path.suffix)))
        old = sorted(backup_dir.glob('%s.%s-*%s' % (path.stem, tag, path.suffix)))
        for extra in old[:-KEEP_BACKUPS]:
            try:
                extra.unlink()
            except OSError:
                pass
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_bytes((b'\xef\xbb\xbf' if bom else b'') + text.encode('utf-8'))
    os.replace(tmp, path)


def save(path, sections, backup_dir=None, now=None):
    """Записывает разделы ({раздел: записи}) в файл билда. Прежний файл перед этим копируется
    в backup_dir. Не сошлось хоть в одном разделе — файл не тронут."""
    text, bom = read_text(path)
    out = render_sections(text, sections)
    write_text(path, out, bom, backup_dir, 'build', now)
    return out
