# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Sergei Labutin
# Additional terms under GPL-3.0 section 7: see NOTICE.md
"""Хватит ли герою атрибутов на камни и вещи, которые называет билд: требование — у цели, герой — по плану
(класс, дерево этапа, атрибуты на вещах); и проверка гайда целиком (buildcheck).
Запуск: python -m unittest planner.test_attrneed"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import attrneed  # noqa: E402
import buildcheck  # noqa: E402
import core  # noqa: E402
import test_buildplan as tb  # noqa: E402

# Маршрут из пяти шагов (третий — город), билд из двух этапов: силовая база, потом энергощит.
RAW = {
    'title': 'Учебный билд',
    'slots': [{'id': 'weapon', 'name': 'Оружие', 'classes': ['Bow', 'Sceptre']},
              {'id': 'body', 'name': 'Доспех', 'classes': ['Body Armour'], 'gear': 'Body Armour'},
              {'id': 'helmet', 'name': 'Шлем', 'classes': ['Helmet'], 'gear': 'Helmet int_armour'},
              {'id': 'belt', 'name': 'Пояс', 'classes': ['Belt'], 'gear': 'Belt'}],
    'steps': [{'id': 'a', 'zone': 'G1_1', 'name': 'Берег'}, {'id': 'b', 'zone': 'G1_2', 'name': 'Лес'},
              {'id': 'town', 'zone': 'G1_town', 'name': 'Город'}, {'id': 'c', 'zone': 'G2_1', 'name': 'Пустыня'},
              {'id': 'maps', 'level': 65, 'name': 'Карты'}],
    'gemLevels': [0, 3, 6, 10, 14, 18],
    'stages': [{'id': 'start', 'name': 'Начало', 'tree': 'early', 'kind': 'str_armour', 'attrs': ['str']},
               {'id': 'late', 'from': 'c', 'name': 'Конец', 'tree': 'late', 'kind': 'int_armour'}],
    'tree': {'attr': 'инт', 'phases': [
        {'id': 'early', 'name': 'Раннее', 'nodes': [{'id': 'n1'}, {'id': 'a1', 'kind': 'attribute', 'attr': 'str'},
                                                    {'id': 'a2', 'kind': 'attribute'}, {'id': 'n2'}]},
        {'id': 'late', 'name': 'Позднее', 'nodes': [{'id': 'n1'}, {'id': 'a1', 'kind': 'attribute'}, {'id': 'a2', 'kind': 'attribute'},
                                                    {'id': 'a3', 'kind': 'attribute', 'attr': 'dex'}, {'id': 'n3'}, {'id': 'n4'},
                                                    {'id': 'k1', 'name': 'Ключ', 'kind': 'keystone'}]}]},
    'goals': [
        {'id': 'bow', 'slot': 'weapon', 'gear': 'Bow', 'title': 'Короткий лук (Short Bow)', 'need': 'a', 'until': 'b'},
        {'id': 'bow-dex', 'slot': 'weapon', 'part': 'dex', 'stat': 'dex', 'min': 5, 'title': 'от 5', 'need': 'a', 'until': 'b'},
        {'id': 'sceptre', 'slot': 'weapon', 'use': 'c', 'gear': 'Sceptre', 'title': 'Гремящий скипетр (Rattling Sceptre)', 'need': 'b'},
        {'id': 'body-any', 'slot': 'body', 'any': True, 'title': 'любой', 'need': 'a'},
        {'id': 'belt-str', 'slot': 'belt', 'part': 'str', 'stat': 'str', 'min': 10, 'title': 'от 10', 'need': 'b'},
        {'id': 'belt-str-2', 'slot': 'belt', 'part': 'str', 'stat': 'str', 'min': 25, 'title': 'от 25', 'need': 'c'},
        {'id': 'belt-dex', 'slot': 'belt', 'part': 'dex', 'stat': 'dex', 'min': 7, 'title': 'от 7'},
        {'id': 'skill-bomb', 'kind': 'skill', 'title': 'Морозная бомба (Frost Bomb)', 'gemFrom': 1, 'need': 'a'},
        {'id': 'gem5-bomb', 'kind': 'gem', 'part': 'level', 'title': '5', 'for': 'skill-bomb', 'need': 'c'},
        {'id': 'skill-gas', 'kind': 'skill', 'title': 'Газовая граната (Gas Grenade)', 'gemFrom': 1, 'need': 'a', 'until': 'b'},
        {'id': 'skill-spectre', 'kind': 'skill', 'title': 'Призрак: Подвижник (Spectre: Zealot)', 'gemFrom': 3, 'use': 'c', 'need': 'c'},
        {'id': 'skill-given', 'kind': 'skill', 'title': 'Призрак: Воин (Spectre: Warrior)', 'gemFrom': 6, 'use': 'c', 'need': 'c',
         'grantedBy': 'sceptre'},
        {'id': 'skill-kelari', 'kind': 'skill', 'title': 'Келари (Kelari)', 'use': 'c', 'need': 'c'},
        {'id': 'skill-odd', 'kind': 'skill', 'title': 'Чудной (Weird)', 'gemFrom': 2, 'use': 'c', 'need': 'c'},
        {'id': 'hero-12', 'reach': 12, 'title': '12 уровень героя', 'need': 'b'},
    ],
}
# что дают узлы дерева — строки из данных GGG
LINES = {'n1': ['+10 to Strength'], 'a1': ['+5 to any Attribute'], 'a2': ['+5 to any Attribute'], 'a3': ['+5 to any Attribute'],
         'n2': ['+2 to all Attributes', '12% increased Armour'], 'n3': ['+12 to Strength and Intelligence'],
         'n4': ['10% increased Intelligence', 'Equipment and Skill Gems have 10% reduced Attribute Requirements'],
         'k1': ['Attribute Requirements of Gems can be satisified by your highest Attribute', 'Gain Accuracy Rating equal to your Intelligence']}
# дерево: узел n1 стоит у старта «witch»; у этого старта два класса с одними атрибутами, у другого старта — воин
GEO = {'near': {'n1': {'witch', 'a1'}, 'a1': {'n1', 'a2'}}, 'starts': {'witch': [7, 7, 15], 'marauder': [15, 7, 7]},
       'classes': {'Witch': {'id': 'Witch', 'base': [7, 7, 15], 'start': 'witch', 'ascendancies': [{'id': 'Witch1', 'name': 'Infernalist'}]},
                   'Sorceress': {'id': 'Sorceress', 'base': [7, 7, 15], 'start': 'witch',
                                 'ascendancies': [{'id': 'Sorceress1', 'name': 'Stormweaver'}]},
                   'Warrior': {'id': 'Warrior', 'base': [15, 7, 7], 'start': 'marauder', 'ascendancies': [{'id': 'Warrior1', 'name': 'Titan'}]}}}


def catalogue():
    """Каталог проверок билда и то, чего в нём для атрибутов не хватает: требования баз, камни с долями
    атрибутов, таблицы требований камня, ловкость в таблице статов."""
    cat = tb.catalogue()
    cat['stats']['stats']['dex'] = {'ids': ['dex'], 'local': []}
    cat['stats']['order'].append('dex')
    cat['lang']['ru']['statNames']['dex'] = ['Ловкость', 'Ловкость']
    cat['lang']['ru']['heroClasses'] = {'Witch': 'Ведьма', 'Warrior': 'Воин', 'Titan': 'Титан', 'Infernalist': 'Инферналист'}
    cat['bases']['Armours/Body/Plate']['req'] = {'level': 33, 'str': 54}
    cat['bases']['Armours/Helmets/Hat']['req'] = {'level': 20, 'int': 30}
    cat['bases']['Weapons/Short'] = {'name': 'Short Bow', 'class': 'Bow', 'level': 4, 'req': {'level': 4, 'str': 5, 'dex': 11},
                                     'tags': ['bow', 'weapon', 'default']}
    cat['gems'] = {'A': {'name': 'Frost Bomb', 'type': 'active', 'req': {'int': 100}},
                   'B': {'name': 'Gas Grenade', 'type': 'active', 'req': {'str': 50, 'dex': 50}},
                   'C': {'name': 'Spectre: {0}', 'type': 'active', 'req': {'int': 100}},
                   'D': {'name': 'Purity of Fire', 'type': 'spirit', 'req': {'int': 75, 'str': 25}},
                   'E': {'name': 'Weird', 'type': 'active', 'req': {'dex': 60, 'int': 40}},
                   'S': {'name': 'Frost Bomb', 'type': 'support', 'req': {'str': 100}},
                   'K': {'name': "Kelari's Judgment", 'type': 'active', 'req': {}}}
    cat['rules'] = {'gemHero': [0, 3, 6, 10, 14, 18],
                    'gemAttr': {'100': [4, 9, 14, 21, 28, 60], '50': [4, 7, 9, 13, 17, 20], '75': [4, 8, 12, 17, 22, 28], '25': [4, 5, 7, 9, 11, 13]}}
    cat['areas'] = {'G1_1': {'level': 2, 'town': False}, 'G1_2': {'level': 10, 'town': False}, 'G1_town': {'level': 15, 'town': True},
                    'G2_1': {'level': 20, 'town': False}}
    return cat


def state(change=None):
    """Каталог и план в рабочем виде. change — что поправить в записи плана перед сборкой."""
    cat = catalogue()
    raw = json.loads(json.dumps(RAW))
    if change:
        change(raw)
    plan, problems = core.norm_plan(raw, cat)
    assert problems == [], problems
    return cat, plan


class TreeTest(unittest.TestCase):
    def test_what_a_tree_version_gives(self):
        nodes = RAW['tree']['phases'][1]['nodes']
        got = attrneed.tree_gives(nodes, LINES, 'инт')
        # «Характеристика» — выбранный атрибут или атрибут дерева по умолчанию; «повышение» и «снижение
        # требований» — процентами; строка, которой расчёт не понимает, отдана как есть; чужое («меткость
        # равна интеллекту») не замечено вовсе
        self.assertEqual(got, {'flat': {'str': 22, 'dex': 5, 'int': 22}, 'inc': {'str': 0, 'dex': 0, 'int': 10}, 'ease': 10, 'free': 0,
                               'odd': [('Ключ', 'Attribute Requirements of Gems can be satisified by your highest Attribute')]})
        # без атрибута по умолчанию узел «Характеристика» без выбора ничего не даёт — и это сказано
        got = attrneed.tree_gives(RAW['tree']['phases'][0]['nodes'], LINES)
        self.assertEqual((got['flat'], got['free']), ({'str': 17, 'dex': 2, 'int': 2}, 1))
        got = attrneed.tree_gives([{'id': 'x'}, {'id': 'y'}], {'x': ['8% increased Attributes'], 'y': ['+3 to all Attributes']})
        self.assertEqual((got['inc'], got['flat']), ({'str': 8, 'dex': 8, 'int': 8}, {'str': 3, 'dex': 3, 'int': 3}))
        self.assertEqual([attrneed.attr_id(w) for w in ('инт', 'Intelligence', 'str', 'ловк', 'мана', None)],
                         ['int', 'int', 'str', 'dex', None, None])

    def test_class_is_named_by_the_build_or_told_by_the_tree(self):
        nodes = RAW['tree']['phases'][0]['nodes']
        self.assertEqual(attrneed.class_start(nodes, GEO), 'witch')
        self.assertIsNone(attrneed.class_start([{'id': 'a2'}], GEO))
        self.assertIsNone(attrneed.class_start([{'id': 'n1'}], {}))
        # класс назвал билд — его атрибуты, от какого бы старта ни росло дерево
        self.assertEqual(attrneed.class_base({'hero': {'class': 'Warrior'}}, GEO, nodes), ({'str': 15, 'dex': 7, 'int': 7}, 'hero'))
        # не назвал (или назвал то, чего в данных нет) — класс узла старта, от которого растёт дерево
        self.assertEqual(attrneed.class_base({}, GEO, nodes), ({'str': 7, 'dex': 7, 'int': 15}, 'tree'))
        self.assertEqual(attrneed.class_base({'hero': {'class': 'Nobody'}}, GEO, nodes)[1], 'tree')
        # узнать не из чего — нули, и это видно
        self.assertEqual(attrneed.class_base({}, GEO, [{'id': 'a2'}]), ({'str': 0, 'dex': 0, 'int': 0}, None))


class NeedTest(unittest.TestCase):
    def setUp(self):
        self.cat, self.plan = state()

    def test_gem_requirements_come_from_the_tables(self):
        rules = self.cat['rules']
        self.assertEqual(attrneed.gem_weights(self.cat, 'Морозная бомба (Frost Bomb)'), {'int': 100})        # поддержка с тем же именем не в счёт
        self.assertEqual(attrneed.gem_weights(self.cat, 'Призрак: Подвижник (Spectre: Zealot)'), {'int': 100})
        self.assertEqual(attrneed.gem_weights(self.cat, "Суд Келари (Kelari's Judgment)"), {})
        self.assertIsNone(attrneed.gem_weights(self.cat, 'Келари (Kelari)'))
        self.assertEqual(attrneed.gem_need(rules, {'int': 100}, 4), {'int': 21})
        self.assertEqual(attrneed.gem_need(rules, {'int': 75, 'str': 25}, 2), {'int': 8, 'str': 5})
        self.assertEqual(attrneed.gem_need(rules, {'str': 50, 'dex': 50}, 40), {'str': 20, 'dex': 20})       # выше таблицы не растёт
        self.assertIsNone(attrneed.gem_need(rules, {'dex': 60, 'int': 40}, 2))                              # такой доли в таблицах нет
        self.assertEqual(attrneed.gem_need(rules, {}, 5), {})

    def test_base_requirements(self):
        self.assertEqual(attrneed.base_need(self.cat, 'Короткий лук (Short Bow)', ['Bow']), {'str': 5, 'dex': 11})
        self.assertEqual(attrneed.base_need(self.cat, 'Гремящий скипетр (Rattling Sceptre): жёлтый', ['Sceptre']), {})
        self.assertIsNone(attrneed.base_need(self.cat, 'Ростовой щит (Tower Shield)', ['Shield']))
        self.assertIsNone(attrneed.base_need(self.cat, 'Короткий лук (Short Bow)', ['Sceptre']))               # не из классов слота

    def test_a_requirement_arises_where_the_build_names_a_thing(self):
        rows, unknown = attrneed.sources(self.cat, self.plan)
        self.assertEqual([(r['goal'], r['tab'], r['what'], r['at'], r['until'], r['need']) for r in rows], [
            # умение: стартовый уровень камня — с шага, к которому умение нужно, пока оно в ходу
            ('skill-bomb', 'gems', 'Морозная бомба (Frost Bomb) · камень 1 ур.', 0, 4, {'int': 4}),
            ('skill-gas', 'gems', 'Газовая граната (Gas Grenade) · камень 1 ур.', 0, 1, {'str': 4, 'dex': 4}),
            ('skill-spectre', 'gems', 'Призрак: Подвижник (Spectre: Zealot) · камень 3 ур.', 3, 4, {'int': 14}),
            # вещь: требование названной базы; скипетр ничего не требует, «любой» доспех — не названная база
            ('bow', 'items', 'Короткий лук (Short Bow)', 0, 1, {'str': 5, 'dex': 11}),
            # ступень «уровень 5 к шагу» — записана автором; ступени, достроенные программой (без срока), не в счёт
            ('gem5-bomb', 'gems', 'Морозная бомба (Frost Bomb) · камень 5 ур.', 3, 4, {'int': 28})])
        # умение, которое даёт вещь, и умение без камня (вознесение) молчат; камень, которого данные не знают, назван
        self.assertEqual(unknown, [{'goal': 'skill-odd', 'tab': 'gems', 'what': 'Чудной (Weird)'}])

    def test_attributes_planned_on_gear(self):
        import herostats
        idx = {s['id']: i for i, s in enumerate(self.plan['steps'])}
        lines = herostats.slot_lines(self.plan)
        at = lambda pos: attrneed.gear_plan(self.plan, idx, lines, pos)   # noqa: E731
        # к первому шагу: ловкость на луке; сила на поясе — к следующему шагу (пока не в счёт), ловкость на поясе без срока
        self.assertEqual(at(0), ({'str': 0, 'dex': 5, 'int': 0}, {'str': 2, 'dex': 1, 'int': 0}))
        self.assertEqual(at(1), ({'str': 10, 'dex': 5, 'int': 0}, {'str': 1, 'dex': 1, 'int': 0}))
        # лук сменён скипетром — его ловкости нет; у ступеней одной части в счёт идёт наибольшая
        self.assertEqual(at(3), ({'str': 25, 'dex': 0, 'int': 0}, {'str': 0, 'dex': 1, 'int': 0}))

    def test_the_hero_by_the_plan(self):
        h = attrneed.hero_at(self.plan, LINES, GEO, 0)
        self.assertEqual({k: h[k] for k in ('stage', 'version', 'base', 'classFrom', 'tree', 'gear', 'inc', 'ease', 'total')},
                         {'stage': 'Начало', 'version': 'Раннее', 'base': {'str': 7, 'dex': 7, 'int': 15}, 'classFrom': 'tree',
                          'tree': {'str': 17, 'dex': 2, 'int': 7}, 'gear': {'str': 0, 'dex': 5, 'int': 0},
                          'inc': {'str': 0, 'dex': 0, 'int': 0}, 'ease': 0, 'total': {'str': 24, 'dex': 14, 'int': 22}})
        # на этапе «Конец» — другое дерево: повышение интеллекта применяется к сумме, округление вниз
        h = attrneed.hero_at(self.plan, LINES, GEO, 3)
        self.assertEqual((h['stage'], h['version'], h['tree'], h['gear'], h['inc']['int'], h['ease'], h['total']),
                         ('Конец', 'Позднее', {'str': 22, 'dex': 5, 'int': 22}, {'str': 25, 'dex': 0, 'int': 0}, 10, 10,
                          {'str': 54, 'dex': 12, 'int': 40}))
        # класс назван билдом — его атрибуты
        h = attrneed.hero_at(dict(self.plan, hero={'class': 'Warrior'}), LINES, GEO, 0)
        self.assertEqual((h['base'], h['classFrom'], h['total']['str']), ({'str': 15, 'dex': 7, 'int': 7}, 'hero', 32))


class VersionsTest(unittest.TestCase):
    def test_what_the_hero_has_with_each_tree_version_without_gear(self):
        """Вкладке «Дерево»: атрибуты героя с версией дерева целиком, без вещей — класс и всё, что дерево даёт:
        узлы «Характеристика» по выбранному атрибуту, «+10 к силе», «+2 ко всем», проценты повышения."""
        _, plan = state()
        got = attrneed.versions_attrs(plan, LINES, GEO)
        self.assertEqual(sorted(got), ['early', 'late'])
        self.assertEqual(got['early'], {'base': {'str': 7, 'dex': 7, 'int': 15}, 'classFrom': 'tree',
                                        'tree': {'str': 17, 'dex': 2, 'int': 7}, 'inc': {'str': 0, 'dex': 0, 'int': 0}, 'ease': 0,
                                        'total': {'str': 24, 'dex': 9, 'int': 22}, 'free': 0, 'odd': []})
        late = got['late']
        # повышение интеллекта применено к сумме класса и дерева; строка, которой расчёт не понял, названа
        self.assertEqual((late['tree'], late['inc']['int'], late['ease'], late['total']),
                         ({'str': 22, 'dex': 5, 'int': 22}, 10, 10, {'str': 29, 'dex': 12, 'int': 40}))
        self.assertEqual(late['odd'], [['Ключ', 'Attribute Requirements of Gems can be satisified by your highest Attribute']])
        # тот же счёт, что у героя на шаге, только без вещей
        h = attrneed.hero_at(plan, LINES, GEO, 0)
        self.assertEqual(got['early']['total'], {a: h['total'][a] - h['gear'][a] for a in attrneed.ATTRS})
        # класс назван билдом — его атрибуты; атрибут по умолчанию другой — «Характеристики» без выбора считаются им
        warrior = attrneed.versions_attrs(dict(plan, hero={'class': 'Warrior'}), LINES, GEO)['early']
        self.assertEqual((warrior['classFrom'], warrior['total']), ('hero', {'str': 32, 'dex': 9, 'int': 14}))
        dex = attrneed.versions_attrs(dict(plan, tree=dict(plan['tree'], attr='dex')), LINES, GEO)['early']
        self.assertEqual(dex['tree'], {'str': 17, 'dex': 7, 'int': 2})
        # у дерева без атрибута «по умолчанию» (так пишет страница) узел без выбора пуст: в счёт не идёт, и он назван
        bare = attrneed.versions_attrs(dict(plan, tree=dict(plan['tree'], attr=None)), LINES, GEO)['early']
        self.assertEqual((bare['tree'], bare['free']), ({'str': 17, 'dex': 2, 'int': 2}, 1))
        # ни класса, ни старта у дерева — счёт идёт от нуля, и об этом сказано; без дерева считать нечего
        lost = attrneed.versions_attrs(plan, LINES, {})['early']
        self.assertEqual((lost['classFrom'], lost['total']), (None, {'str': 17, 'dex': 2, 'int': 7}))
        self.assertEqual(attrneed.versions_attrs({k: v for k, v in plan.items() if k != 'tree'}, LINES, GEO), {})


class CheckTest(unittest.TestCase):
    def test_enough_means_silence(self):
        cat, plan = state()
        found, unknown = attrneed.check(cat, plan, LINES, GEO)
        self.assertEqual(found, [])
        self.assertEqual([u['what'] for u in unknown], ['Чудной (Weird)'])

    def test_a_shortage_is_told_at_the_goal(self):
        def more(raw):
            # камень 6-го уровня к шагу «Пустыня» и латы с требованием силы к шагу «Лес»
            raw['goals'].append({'id': 'gem6-bomb', 'kind': 'gem', 'part': 'level', 'title': '6', 'for': 'skill-bomb', 'need': 'c'})
            raw['goals'].append({'id': 'plate', 'slot': 'body', 'title': 'Латы (Full Plate)', 'need': 'b'})
        cat, plan = state(more)
        found, _ = attrneed.check(cat, plan, LINES, GEO)
        self.assertEqual([(f['goal'], f['tab'], f['step'], f['later'], f['attr'], f['need'], f['have'], f['short']) for f in found], [
            ('plate', 'items', 'b', None, 'str', 54, 34, 20),
            ('gem6-bomb', 'gems', 'c', None, 'int', 54, 40, 14)])
        # одной строкой — что и сколько; отдельно — из чего сложилось «есть»: сила на поясе «от 10» к этому шагу
        # в счёт идёт, а ступень «от 25» со сроком позже — нет, и это сказано
        self.assertEqual((found[0]['what'], found[0]['text'], found[0]['detail'], found[0]['stepName']),
                         ('Латы (Full Plate)', 'Сила: нужно 54, есть 34 — не хватает 20',
                          'класс 7 + дерево «Раннее» 17 + предметы по плану 10 '
                          '(целей по атрибуту на предметах без срока или со сроком позже шага: 1 — не в счёт)', 'Лес'))
        # дерево снижает требования на 10% (60 → 54) и повышает интеллект на 10%: (15 + 22) × 1,1 = 40
        self.assertEqual((found[1]['what'], found[1]['text'], found[1]['detail']),
                         ('Морозная бомба (Frost Bomb) · камень 6 ур.', 'Интеллект: нужно 54, есть 40 — не хватает 14',
                          'класс 15 + дерево «Позднее» 22 + предметы по плану 0 · повышение 10% · требования снижены на 10% (было 60)'))

    def test_a_goal_without_a_deadline_does_not_count_and_this_is_said(self):
        def more(raw):
            raw['goals'].append({'id': 'bow2', 'slot': 'weapon', 'title': 'Короткий лук (Short Bow)', 'need': 'a', 'until': 'b'})
            raw['goals'] = [g for g in raw['goals'] if g['id'] != 'bow-dex']
        cat, plan = state(more)
        found, _ = attrneed.check(cat, plan, LINES, GEO)
        self.assertEqual({f['goal'] for f in found}, {'bow', 'bow2'})
        self.assertEqual(found[0]['text'], 'Ловкость: нужно 11, есть 9 — не хватает 2')
        self.assertEqual(found[0]['detail'], 'класс 7 + дерево «Раннее» 2 + предметы по плану 0 '
                                             '(целей по атрибуту на предметах без срока или со сроком позже шага: 1 — не в счёт)')

    def test_a_later_stage_may_take_the_attribute_away(self):
        def more(raw):
            # латы носят до конца, а силу на поясе — только до смены этапа: с этапом «Конец» дерево то же по силе,
            # но пояс снят
            raw['goals'].append({'id': 'plate', 'slot': 'body', 'title': 'Латы (Full Plate)', 'need': 'c'})
            for g in raw['goals']:
                if g['id'] == 'belt-str-2':
                    g['min'] = 30
            raw['steps'].append({'id': 'end', 'zone': 'G3_1', 'name': 'Конец пути'})
            raw['stages'].append({'id': 'last', 'from': 'end', 'name': 'Финал', 'tree': 'early'})
        cat, plan = state(more)
        plate = lambda p: [(f['step'], f['later'], f['need'], f['have']) for f in attrneed.check(cat, p, LINES, GEO)[0]   # noqa: E731
                           if f['goal'] == 'plate']
        # к своему шагу хватает (7 + 22 + 30 = 59 при требовании 54 со снижением 10% — 49); с этапа «Финал» дерево
        # другое: 7 + 17 + 30 = 54 — всё ещё хватает
        self.assertEqual(plate(plan), [])

        def worse(raw):
            more(raw)
            for g in raw['goals']:
                if g['id'] == 'belt-str-2':
                    g['until'] = 'maps'
        cat, plan = state(worse)
        # пояс с силой «от 30» сняли перед последним этапом: остаётся «от 10» — 7 + 17 + 10 = 34
        self.assertEqual(plate(plan), [('end', 'Финал', 54, 34)])
        # камню 5-го уровня на том же этапе не хватает интеллекта раннего дерева — тоже «с этапа»
        found = [f for f in attrneed.check(cat, plan, LINES, GEO)[0] if f['goal'] == 'gem5-bomb']
        self.assertEqual([(f['step'], f['later'], f['text']) for f in found], [('end', 'Финал', 'Интеллект: нужно 28, есть 22 — не хватает 6')])

    def test_plan_without_steps_or_stages_is_not_a_crash(self):
        cat, plan = state()
        self.assertEqual(attrneed.check(cat, dict(plan, steps=[]), LINES, GEO), ([], []))
        found, _ = attrneed.check(cat, dict(plan, stages=[]), LINES, GEO)
        self.assertTrue(all(f['detail'].startswith('класс 0 + дерево не названо') for f in found))


class GuideTest(unittest.TestCase):
    """Проверка гайда целиком: план, герой, дерево, атрибуты, данные."""

    def test_everything_goes_into_one_list(self):
        cat, plan = state()
        found = buildcheck.run(cat, plan, LINES, GEO, ['Цель «x» записана дважды'])
        self.assertEqual([(f['kind'], f['level'], f.get('tab'), f['text']) for f in found], [
            ('plan', 'bad', None, 'Цель «x» записана дважды'),
            ('hero', 'note', 'build', 'Класс героя не назван — стартовые атрибуты взяты по узлу старта, от которого растёт дерево'),
            ('tree', 'note', 'tree', 'Дерево «Позднее»: узел «Ключ» в счёте атрибутов не учтён'),
            ('data', 'note', 'gems', 'Нет данных о требованиях камней: «Чудной (Weird)» — их атрибуты не проверены')])

    def test_hero_and_tree_are_checked_against_game_data(self):
        cat, plan = state()
        text = lambda p: [f['text'] for f in buildcheck.hero_findings(p, GEO, cat['lang']['ru']['heroClasses'])]   # noqa: E731
        self.assertEqual(text(dict(plan, hero={'class': 'Witch', 'ascendancy': 'Infernalist'})), [])
        self.assertEqual(text(dict(plan, hero={'class': 'Witch'})), [])                       # без вознесения — можно
        self.assertEqual(text(dict(plan, hero={'class': 'Nobody'})), ['Класса героя «Nobody» нет в данных дерева'])
        self.assertEqual(text(dict(plan, hero={'class': 'Witch', 'ascendancy': 'Titan'})), ['У класса «Ведьма» нет восхождения «Титан»'])
        self.assertEqual(text(dict(plan, hero={'ascendancy': 'Titan'}))[-1], 'Восхождение названо, а класс героя — нет')
        # дерево растёт от старта другого класса; версия, которую не назвал ни один этап; узлы без атрибута
        tree = lambda p: [(f['level'], f['text']) for f in buildcheck.tree_findings(p, LINES, GEO)]   # noqa: E731
        self.assertIn(('bad', 'Дерево «Раннее» растёт не от старта класса героя'), tree(dict(plan, hero={'class': 'Warrior'})))
        self.assertNotIn(('bad', 'Дерево «Раннее» растёт не от старта класса героя'), tree(dict(plan, hero={'class': 'Sorceress'})))
        idle = dict(plan, stages=[dict(plan['stages'][0]), dict(plan['stages'][1], tree=None)])
        self.assertIn(('note', 'Версию дерева «Позднее» не назвал ни один этап — она нигде не действует'), tree(idle))
        bare = dict(plan, tree=dict(plan['tree'], attr=None))
        self.assertIn(('bad', 'Дерево «Раннее»: узлов «Характеристика» без назначенного атрибута — 1; в счёт атрибутов они не идут'), tree(bare))
        first = dict(plan, stages=[dict(plan['stages'][0], tree=None), plan['stages'][1]])
        self.assertEqual(tree(first)[0], ('bad', 'Этап «Начало» не назвал версию дерева — до первого этапа с деревом атрибуты считаются без него'))
        # атлас есть только на картах: этап, начатый до карт, версию атласа не называет; этап на картах — называет
        late = ('bad', 'Этап «%s» начинается до карт, а атлас есть только на картах — версию атласа называет этап, '
                       'который начинается на картах')
        atl = dict(plan, atlas={'phases': [{'id': 'a1', 'name': 'Атлас', 'nodes': []}]},
                   stages=[dict(plan['stages'][0], atlas='a1'), plan['stages'][1]])
        self.assertIn((late[0], late[1] % 'Начало'), tree(atl))
        # шаг «maps» маршрута — по уровню зоны (этап карт)
        maps = dict(atl, stages=[plan['stages'][0], plan['stages'][1], {'id': 'm', 'from': 'maps', 'name': 'Карты', 'atlas': 'a1'}])
        self.assertEqual([f for f in tree(maps) if 'атлас' in f[1]], [])
        # маршрут без карт — атласа нет нигде, даже у последнего этапа
        bare = dict(atl, steps=plan['steps'][:-1], stages=[plan['stages'][0], dict(plan['stages'][1], atlas='a1')])
        self.assertIn((late[0], late[1] % (plan['stages'][1].get('name') or plan['stages'][1]['id'])), tree(bare))

    def test_shortage_says_where(self):
        def more(raw):
            raw['goals'].append({'id': 'gem6-bomb', 'kind': 'gem', 'part': 'level', 'title': '6', 'for': 'skill-bomb', 'need': 'c'})
        cat, plan = state(more)
        f = [x for x in buildcheck.run(cat, plan, LINES, GEO) if x['kind'] == 'attr'][0]
        self.assertEqual((f['level'], f['goal'], f['tab'], f['where']), ('bad', 'gem6-bomb', 'gems', 'не позже «Пустыня»'))

    def test_step_earlier_than_the_game_gives_it(self):
        """Шаг цели раньше, чем игра вообще может это дать: неогранённый камень нужного уровня или база ещё не падают.
        Камень и вещь с редкого чудовища — на два уровня выше зоны; камень уровня выше нужного тоже годится; город не в
        счёт; у шага карт своей зоны нет — его уровень. Уровень зоны, каким его видели забеги, важнее данных игры."""
        cat = {'areas': {'Z1': {'level': 1}, 'Z2': {'level': 10}, 'T': {'level': 50, 'town': True}, 'Z3': {'level': 30}},
               'rules': {'uncut': {'skill': {'1': 1, '9': 32, '12': 70}, 'support': {'1': 1, '3': 33}, 'spirit': {'4': 11}}},
               'gems': {'a': {'name': 'Reaver', 'type': 'active', 'level': 9},
                        's': {'name': 'Muster', 'type': 'support', 'level': 3},
                        'h': {'name': 'Herald', 'type': 'spirit', 'level': 4}}}
        steps = [{'id': 'a', 'zone': 'Z1', 'name': 'Начало'}, {'id': 't', 'zone': 'T', 'name': 'Город'},
                 {'id': 'b', 'zone': 'Z2', 'name': 'Середина'}, {'id': 'c', 'zone': 'Z3', 'name': 'Конец'},
                 {'id': 'm', 'level': 65, 'name': 'Карты'}]
        goals = [{'id': 'sk', 'kind': 'skill', 'title': 'Разоритель (Reaver)', 'gemFrom': 9, 'need': 'b'},
                 {'id': 'mu', 'kind': 'support', 'for': 'sk', 'title': 'Сборище (Muster)', 'need': 'c'},
                 {'id': 'lv', 'kind': 'gem', 'part': 'level', 'for': 'sk', 'title': '12', 'need': 'c'},
                 {'id': 'he', 'kind': 'skill', 'title': 'Вестник (Herald)', 'gemFrom': 4, 'need': 'b'},
                 {'id': 'it', 'kind': 'skill', 'title': 'Разоритель (Reaver)', 'gemFrom': 9, 'grantedBy': 'sh', 'need': 'a'},
                 {'id': 'sh', 'slot': 'off', 'title': 'Щит (Shield)', 'opens': 40, 'need': 'c'}]
        plan = {'steps': steps, 'goals': goals}
        got = lambda zones=None: [(f['goal'], f['tab'], f['what'], f['where'], f['text'])   # noqa: E731
                                  for f in buildcheck.game_findings(cat, plan, zones)]
        self.assertEqual(got(), [
            ('sk', 'gems', 'Разоритель (Reaver)', 'надеть «Середина»',
             'Так рано не получить: неогранённый камень умения 9 уровня падает только с шага «Конец»'),
            ('mu', 'gems', 'Сборище (Muster) → Разоритель (Reaver)', 'вставить «Конец»',
             'Так рано не получить: неогранённый камень поддержки 3 уровня падает только с шага «Карты»'),
            ('lv', 'gems', 'уровень камня 12 → Разоритель (Reaver)', 'не позже «Конец»',
             'Не получить: неогранённый камень умения 12 уровня не падает ни на одном шаге маршрута'),
            ('sh', 'items', 'Щит (Shield)', 'не позже «Конец»', 'Так рано не получить: эта база падает только с шага «Карты»')])
        # забеги видели «Конец» 36-го уровня (порядок прохождения поднял его): поддержке 3 уровня этого хватает, базе — нет
        self.assertEqual([x[0] for x in got({'Z3': 36})], ['sk', 'lv', 'sh'])
        # то же — в общем списке проверки, видом game
        self.assertEqual([f['goal'] for f in buildcheck.run(cat, plan, {}, None, zones={'Z3': 36}) if f['kind'] == 'game'],
                         ['sk', 'lv', 'sh'])
        # Уровень зоны из данных игры — младший: пока забеги в зонах до шага цели не были, замечание только к сведению
        # (настоящий уровень бывает выше). Забеги видели все зоны — надо править.
        level = lambda zones: [(f['goal'], f['level'], bool(f.get('detail'))) for f in buildcheck.game_findings(cat, plan, zones)]   # noqa: E731
        self.assertEqual(level(None), [('sk', 'note', True), ('mu', 'note', True), ('lv', 'note', True), ('sh', 'note', True)])
        self.assertEqual(level({'Z1': 1, 'Z2': 10, 'Z3': 30}),
                         [('sk', 'bad', False), ('mu', 'bad', False), ('lv', 'bad', False), ('sh', 'bad', False)])
        self.assertEqual(level({'Z1': 1, 'Z2': 10}), [('sk', 'bad', False), ('mu', 'note', True), ('lv', 'note', True), ('sh', 'note', True)])

    def test_ascensions_follow_the_game_rules(self):
        """Восхождения по правилам игры: номер считает программа по маршруту; ступень N дают испытания не младше её
        уровня зоны — маршрут к шагу должен до него дойти; восхождений четыре; берут его на испытании или на картах;
        шаг по событию «N-е восхождение» стоит после N-го восхождения плана."""
        import core
        cat = {'areas': {'T2': {'level': 22}, 'Z3': {'level': 38}, 'C3': {'level': 38}, 'Z5': {'level': 55}, 'Z6': {'level': 62}}}
        asc = {'kind': 'ascension', 'title': 'Восхождение (Ascendancy)', 'levels': [22, 38, 60, 75], 'zones': ['T2', 'C3']}
        steps = [{'id': 'trial', 'zone': 'T2', 'name': 'Сехем'}, {'id': 'after', 'event': 'ascend', 'name': 'После'},
                 {'id': 'chaos', 'zone': 'C3', 'name': 'Хаос'}, {'id': 'after2', 'event': 'ascend2', 'name': 'После Хаоса'},
                 {'id': 'mid', 'zone': 'Z5', 'name': 'Середина'}, {'id': 'trial3', 'zone': 'T2', 'name': 'Сехем, третье'},
                 {'id': 'late', 'zone': 'Z6', 'name': 'Конец'}, {'id': 'maps', 'level': 75, 'name': 'Карты 11–14'}]
        goals = [dict(asc, id='a1', need='trial'), dict(asc, id='a2', need='chaos'), dict(asc, id='a3', need='trial3'),
                 dict(asc, id='a4', need='maps')]
        seen = {'T2': 22, 'C3': 38, 'Z5': 55, 'Z6': 62}

        def got(goals, zones=seen):
            plan, _ = core.norm_plan({'steps': steps, 'goals': goals})
            return [(f.get('goal') or f.get('step'), f['level'], f['text']) for f in buildcheck.ascension_findings(cat, plan, zones)]

        # третье — на Сехем, когда маршрут дошёл только до 55: ступень 3 дают испытания от 60
        self.assertEqual(got(goals), [('a3', 'bad', 'Так рано не взять: эту ступень дают испытания от 60 уровня зоны, а маршрут '
                                                     'к этому шагу доходит до зоны 55')])
        # третье — на шаге после зоны 62: нет замечаний
        ok = [dict(asc, id='a1', need='trial'), dict(asc, id='a2', need='chaos'), dict(asc, id='a3', need='late'),
              dict(asc, id='a4', need='maps')]
        self.assertEqual(got(ok), [('a3', 'note', 'Восхождение берут на Испытании Сехем или Испытании Хаоса — в зонах '
                                                  'этого шага испытания нет')])
        # пятое — лишнее; без второго шаг «После Хаоса» сам не наступит
        five = ok + [dict(asc, id='a5', need='maps')]
        self.assertIn(('a5', 'bad', 'Восхождений в игре четыре: это уже 5-е — лишнее'), got(five))
        self.assertIn(('after2', 'bad', 'Шаг наступит сам, когда герой возьмёт второе восхождение, а восхождений до него в плане: 1'),
                      got([g for g in ok if g['id'] != 'a2']))
        # уровень зоны только по данным игры (забеги там не были) — к сведению
        self.assertEqual([x[1] for x in got(goals, zones=None)], ['note'])
        # Элзара гарантированно даёт барию на третье: её запись в плане раньше шага — третье можно и до зон 60
        gift = [dict(g, early={'3': 'boss-elzarah'}) for g in goals] + [{'id': 'boss-elzarah', 'kind': 'boss', 'need': 'mid',
                                                                         'title': 'Элзара'}]
        self.assertEqual(got(gift), [])
        late_gift = [dict(g, early={'3': 'boss-elzarah'}) for g in goals] + [{'id': 'boss-elzarah', 'kind': 'boss', 'need': 'late',
                                                                              'title': 'Элзара'}]
        self.assertEqual([x[0] for x in got(late_gift)], ['a3'])

    def test_the_real_plan_is_checked(self):
        """Настоящий план проверяется без ошибок: замечания — словари с текстом, цели в них есть в плане."""
        import gamedata
        import planfiles
        import treeplan
        import planlib
        root = Path(HERE).parent
        base = gamedata.load(root / 'catalog' / 'data')
        plans = planlib.project_plans(root)
        if not base or not plans:
            self.skipTest('нет плана или каталога данных игры')
        lines = json.loads((Path(HERE) / 'static' / 'treestats.json').read_text(encoding='utf-8'))
        geo = treeplan.load_geo(Path(HERE) / 'static' / 'tree.json')
        self.assertEqual(sorted(len(v) for v in geo['starts'].values()), [3] * 6)          # шесть стартов, у каждого три атрибута
        self.assertEqual(sorted(geo['classes']), ['Druid', 'Huntress', 'Mercenary', 'Monk', 'Ranger', 'Sorceress', 'Warrior', 'Witch'])
        # каждый план библиотеки (plans/<id>/) — и прежний единственный plan.json, если он ещё есть
        for path, _ in plans:
            with self.subTest(plan=path.parent.name):
                raw = json.loads(path.read_text(encoding='utf-8-sig'))
                parts = planfiles.read_parts(path, raw)
                composed, _ = planfiles.compose(raw, parts['route'], parts['build'])
                cat, _ = gamedata.with_stats(base, composed.get('statDefs'))
                plan, _ = core.norm_plan(composed, cat)
                found = buildcheck.run(cat, plan, lines, geo)
                ids = {g['id'] for g in plan['goals']}
                for f in found:
                    self.assertTrue(f['text'] and f['kind'] in ('route', 'hero', 'tree', 'attr', 'game', 'luck', 'data') and f['level'] in ('bad', 'note'), f)
                    self.assertTrue(f.get('goal') is None or f['goal'] in ids, f)
                # у героя по плану на каждом шаге есть класс: назван билдом или найден по дереву
                # у нового плана может не быть ни класса, ни дерева — тогда и знать его неоткуда
                named = bool((plan.get('hero') or {}).get('class')) or bool((plan.get('tree') or {}).get('phases'))
                for pos in range(len(plan['steps'])):
                    self.assertIn(attrneed.hero_at(plan, lines, geo, pos)['classFrom'], ('hero', 'tree') if named else ('hero', 'tree', None))

class ServerTest(unittest.TestCase):
    """Проверка доходит до страницы «Билд»: по записанному плану и по плану с правками страницы."""

    def setUp(self):
        import server
        import test_treeplan
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        (root / 'Client.txt').write_text(test_treeplan.LOG, encoding='utf-8')
        (root / 'plan.json').write_text(json.dumps({'version': 2, 'route': 'route.json', 'build': 'build.json'}), encoding='utf-8')
        (root / 'route.json').write_text(json.dumps(tb.GOALS_ROUTE, ensure_ascii=False), encoding='utf-8')
        (root / 'build.json').write_text(tb.GOALS_BUILD, encoding='utf-8')
        self.build = root / 'build.json'
        self.app = server.App(root / 'Client.txt', root / 'plan.json', root / 'runs', backup_dir=root / 'backup')
        with self.app.cond:
            self.app.load_plan()
            self.app.poll_log(initial=True)
            self.app.attach_run()

    def tearDown(self):
        self.tmp.cleanup()

    def test_page_gets_the_findings(self):
        if not self.app.catalog or not self.app.catalog.get('stats'):
            self.skipTest('каталог данных игры не собран')
        view = self.app.build_view()
        self.assertNotIn('needs', view)                       # подсказки у этапа больше нет
        kinds = [f['kind'] for f in view['findings']]
        self.assertIn('hero', kinds)                          # класс героя в учебном билде не назван
        # то же самое отвечает запрос проверки без правок
        self.assertEqual(self.app.check_build({}), view['findings'])
        # вместе с замечаниями страница получает, какие статы на каком этапе редкие: {этап: {стат: [слоты]}}
        self.assertEqual(sorted(view['rare']), sorted(st['id'] for st in self.app.plan['stages']))
        slots = {s['name'] for s in self.app.plan['slots']}
        for per in view['rare'].values():
            for sid, where in per.items():
                self.assertIn(sid, self.app.catalog['stats']['stats'])
                self.assertTrue(where and len(where) <= 3 and set(where) <= slots, (sid, where))
        # и атрибуты героя с каждой версией дерева (без вещей) — для вкладки «Дерево»
        self.assertEqual(sorted(view['treeAttrs']), sorted(ph['id'] for ph in self.app.plan['tree']['phases']))
        for per in view['treeAttrs'].values():
            self.assertEqual(sorted(per['total']), ['dex', 'int', 'str'])
        self.assertEqual(self.app.check_page({}), {'findings': view['findings'], 'rare': view['rare'], 'treeAttrs': view['treeAttrs']})
        # правка страницы, ещё не записанная: назван класс — замечания о герое нет; файл не тронут
        before = self.build.read_bytes()
        found = self.app.check_build({'hero': {'class': 'Sorceress'}})
        self.assertNotIn('hero', [f['kind'] for f in found])
        self.assertEqual(self.build.read_bytes(), before)
        # цель с требованием, которого герою не хватит: замечание — у этой цели, и до правки его не было
        goals = json.loads(tb.GOALS_BUILD)['goals']
        skill = next(g for g in goals if g.get('kind') == 'skill')
        new = 'gem20-' + skill['id'][6:]
        goals.append({'id': new, 'kind': 'gem', 'part': 'level', 'title': '20', 'for': skill['id'],
                      'need': self.app.plan['steps'][0]['id']})
        self.assertNotIn(new, [f.get('goal') for f in view['findings']])
        found = [f for f in self.app.check_build({'goals': goals}) if f['kind'] == 'attr']
        self.assertIn((new, 'gems', 'int'), [(f['goal'], f['tab'], f['attr']) for f in found])
        # то, из чего план не собрать, не роняет проверку — становится замечанием
        self.assertEqual([f['kind'] for f in self.app.check_build({'goals': 'не список'})], ['plan'])
        self.assertEqual(sorted(self.app.check_page({'goals': 'не список'})), ['findings'])
        # правка слота меняет ответ: в доспехе теперь носят скипетр — статы доспеха слот больше не несёт
        cut = [dict(s, wear=[{'classes': ['Sceptre']}]) if s['id'] == 'body' else s for s in view['slots']]
        after = self.app.check_page({'slots': cut})['rare']
        self.assertNotEqual(after, view['rare'])
        self.assertEqual(self.build.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
