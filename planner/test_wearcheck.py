# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Sergei Labutin
# Additional terms under GPL-3.0 section 7: see NOTICE.md
"""Хватит ли герою уровня и атрибутов надеть вещь из буфера и не перестанет ли работать надетое.
Запуск: python -m unittest planner.test_wearcheck"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import itemcopy  # noqa: E402
import itemstats  # noqa: E402
import test_itemstats  # noqa: E402
import treegeo  # noqa: E402
import wearcheck  # noqa: E402

NAMES = {'str': 'сила', 'dex': 'ловкость', 'int': 'интеллект'}
# что дают узлы дерева и где они стоят: s — старт класса, g1…g4 — «Характеристика», j — гнездо самоцвета
LINES = {'n1': ['+10 to Strength'], 'g1': ['+5 to any Attribute'], 'g2': ['+5 to any Attribute'], 'g3': ['+5 to any Attribute'],
         'g4': ['+5 to any Attribute'], 'n2': ['10% increased Intelligence'], 'AscendancyX1': ['+6 to all Attributes'],
         'k1': ['Attribute Requirements of Gems can be satisified by your highest Attribute']}
GEO = {'near': {'n1': {'s', 'g1'}}, 'starts': {'s': [7, 7, 15]},
       'kind': {'n1': treegeo.SMALL, 'g1': treegeo.ATTRIBUTE, 'j': treegeo.SOCKET, 'k1': treegeo.KEYSTONE}}
# версия дерева этапа: узлу g1 назначена сила, g2 — атрибут дерева по умолчанию; g3 и g4 в плане нет
VERSION = {'id': 'v', 'nodes': [{'id': 'n1'}, {'id': 'g1', 'kind': 'attribute', 'attr': 'str'}, {'id': 'g2', 'kind': 'attribute'}]}


def take(*ids):
    return [{'type': 'passive', 'op': 'take', 'id': i} for i in ids]


def tree(**more):
    """Дерево героя для проверок счёта: класс 7 / 7 / 15, от узлов — сила 15 и интеллект 5, без повышений."""
    out = {'base': {'str': 7, 'dex': 7, 'int': 15}, 'flat': {'str': 15, 'dex': 0, 'int': 5}, 'inc': {'str': 0, 'dex': 0, 'int': 0},
           'ease': 0, 'nodes': {'str': 3, 'dex': 0, 'int': 1}, 'unset': [], 'notes': []}
    out.update(more)
    return out


class TreeTest(unittest.TestCase):
    def test_taken_nodes_come_from_the_log(self):
        events = take('n1', 'g1', 'AtlasNode1', 'AscendancyX1', 'g2') + [{'type': 'passive', 'op': 'drop', 'id': 'g2'}] + take('n1') + \
            [{'type': 'zone', 'code': 'G1_1'}]
        # атлас не в счёт; снятый узел снят; повторный клик по взятому — не второй узел
        self.assertEqual(wearcheck.taken(events), (['n1', 'g1'], ['AscendancyX1']))

    def test_attribute_nodes_count_as_the_plan_assigns_them(self):
        events = take('n1', 'g1', 'g2', 'g3', 'AscendancyX1')
        got = wearcheck.tree_state(LINES, GEO, events, VERSION, 'инт')
        # g1 — сила (так в плане), g2 — интеллект (атрибут дерева по умолчанию), g3 в плане нет — не считается;
        # узел восхождения и узел «+10 к силе» считаются как есть; класс — по старту, с которым соседствует дерево
        self.assertEqual(got, {'base': {'str': 7, 'dex': 7, 'int': 15}, 'flat': {'str': 21, 'dex': 6, 'int': 11},
                               'inc': {'str': 0, 'dex': 0, 'int': 0}, 'ease': 0, 'nodes': {'str': 1, 'dex': 0, 'int': 1},
                               'unset': ['g3'], 'notes': []})
        # игрок назвал сам: узел вне плана считается; назначенное планом заменяется его словом
        got = wearcheck.tree_state(LINES, GEO, events, VERSION, 'инт', {'g3': 'dex', 'g1': 'int'})
        self.assertEqual((got['flat'], got['nodes'], got['unset']), ({'str': 16, 'dex': 11, 'int': 16}, {'str': 0, 'dex': 1, 'int': 2}, []))
        # плана дерева нет вовсе — узлы «Характеристика» не считаются, пока игрок их не назовёт
        got = wearcheck.tree_state(LINES, GEO, events)
        self.assertEqual((got['flat'], got['unset']), ({'str': 16, 'dex': 6, 'int': 6}, ['g1', 'g2', 'g3']))
        # у дерева нет атрибута по умолчанию — узел плана без своего атрибута тоже не посчитан
        self.assertEqual(wearcheck.tree_state(LINES, GEO, events, VERSION)['unset'], ['g2', 'g3'])

    def test_what_is_not_counted_is_said(self):
        self.assertEqual(wearcheck.tree_state(LINES, GEO, take('n1', 'j'))['notes'], ['самоцвет в гнезде дерева не учтён'])
        self.assertEqual(wearcheck.tree_state(LINES, GEO, take('n1', 'k1'))['notes'],
                         ['узел дерева не учтён: Attribute Requirements of Gems can be satisified by your highest Attribute'])
        got = wearcheck.tree_state(LINES, GEO, take('g2'))
        self.assertEqual((got['notes'], got['base']), (['класс героя не назван ни логом, ни билдом и по дереву не найден — его атрибуты не посчитаны'],
                                                      {'str': 0, 'dex': 0, 'int': 0}))

    def test_the_class_is_the_one_played_not_the_one_of_the_build(self):
        """Билд написан для одного класса, а играют другим: атрибуты класса — того, кем играют (по логу)."""
        geo = dict(GEO, classes={'Witch': {'base': [7, 7, 15]}, 'Warrior': {'base': [15, 7, 7]}})
        state = lambda **more: wearcheck.hero_state(test_itemstats.CAT, {'hero': {'class': 'Witch'}}, {}, [], {}, {}, LINES, geo, **more)   # noqa: E731
        self.assertEqual(state(cls='Warrior')['tree']['base'], {'str': 15, 'dex': 7, 'int': 7})
        # лог героя ещё не назвал — до тех пор класс тот, что в билде
        self.assertEqual(state()['tree']['base'], {'str': 7, 'dex': 7, 'int': 15})
        self.assertEqual(wearcheck.tree_state(LINES, GEO, take('n1', 'n2'))['inc'], {'str': 0, 'dex': 0, 'int': 10})


class BoundsTest(unittest.TestCase):
    def test_attributes_are_numbers_by_the_plan(self):
        gear = {'amulet/': {'str': 12}, 'ring1/': {'int': 8}}
        b = wearcheck.bounds(tree(), gear, {'str': (30, 'Сапоги')})
        # сила 7 + 15 + 12, интеллект 15 + 5 + 8: числа, а не границы
        self.assertEqual({a: (x['value'], x['lo'], x['hi']) for a, x in b['attrs'].items()},
                         {'str': (34, 34, 34), 'dex': (7, 7, 7), 'int': (28, 28, 28)})
        self.assertEqual((b['conflict'], b['notes']), ({}, []))
        # повышение от дерева применяется к сумме
        b = wearcheck.bounds(tree(inc={'str': 0, 'dex': 0, 'int': 10}), gear, {})
        self.assertEqual((b['attrs']['int']['value'], b['attrs']['int']['lo_flat']), (30, 28))

    def test_count_below_what_is_worn_is_a_conflict(self):
        gear = {'amulet/': {'str': 12}}
        # надетые сапоги требуют 40, а по счёту 34: в узлах взято не то, что в плане. Считать ответы дальше
        # можно только от «не меньше 40»
        b = wearcheck.bounds(tree(), gear, {'str': (40, 'Сапоги'), 'int': (20, 'Камень')})
        self.assertEqual(b['conflict'], {'str': (40, 'Сапоги')})
        self.assertEqual({a: (x['value'], x['lo'], x['hi']) for a, x in b['attrs'].items()},
                         {'str': (34, 40, None), 'dex': (7, 7, 7), 'int': (20, 20, 20)})
        # что не посчитано, сказано словами
        b = wearcheck.bounds(tree(unset=['g3', 'g4'], notes=['самоцвет в гнезде дерева не учтён']), gear, {}, blind=['Кольцо 1', 'Пояс'])
        self.assertEqual(b['notes'], ['самоцвет в гнезде дерева не учтён',
                                      'узлов «Характеристика» вне плана без названного атрибута: 2 — не посчитаны',
                                      'надетое не запомнено и не посчитано: Кольцо 1, Пояс'])


class JudgeTest(unittest.TestCase):
    def setUp(self):
        # сила 34, ловкость 7, интеллект 28
        self.b = wearcheck.bounds(tree(), {'amulet/': {'str': 12}, 'ring1/': {'int': 8}}, {'str': (30, 'Стальные поножи')})
        self.boots = ('Стальные поножи', {'str': 30})

    def judge(self, need, own=None, old=None, others=None, **more):
        return wearcheck.judge(self.b, need, own or {}, old or {}, [self.boots] if others is None else others, names=NAMES, **more)

    def test_own_requirements(self):
        self.assertEqual(self.judge({'level': 12, 'str': 34}), {'state': 'ok', 'lines': []})
        self.assertEqual(self.judge({'level': 12, 'str': 36}), {'state': 'no', 'lines': ['сила: нужно 36, у героя 34']})
        self.assertEqual(self.judge({'level': 20, 'int': 20}, hero_level=18), {'state': 'no', 'lines': ['с 20 уровня героя (сейчас 18)']})
        self.assertEqual(self.judge({'level': 20, 'dex': 13, 'str': 36}, hero_level=30),
                         {'state': 'no', 'lines': ['сила: нужно 36, у героя 34', 'ловкость: нужно 13, у героя 7']})
        # собственный бонус вещи в счёт её требования не идёт — но сказано, когда дело только в нём
        self.assertEqual(self.judge({'str': 40}, own={'str': 10}),
                         {'state': 'check', 'lines': ['сила: нужно 40 — хватит только с её собственным бонусом +10']})
        self.assertEqual(self.judge({'str': 50}, own={'str': 10}), {'state': 'no', 'lines': ['сила: нужно 50, у героя 44']})

    def test_what_stops_working_after_the_swap(self):
        # новая вещь даёт столько же или больше — надетому ничего не грозит
        self.assertEqual(self.judge({}, own={'str': 12}, old={'str': 12}), {'state': 'ok', 'lines': []})
        self.assertEqual(self.judge({}, own={'str': 20}, old={'str': 12}), {'state': 'ok', 'lines': []})
        # отнимает 12 силы: останется 22, сапогам нужно 30
        self.assertEqual(self.judge({}, old={'str': 12}),
                         {'state': 'drop', 'lines': ['перестанет работать «Стальные поножи»: сила 30, останется 22']})
        self.assertEqual(self.judge({}, own={'str': 6}, old={'str': 12})['lines'], ['перестанет работать «Стальные поножи»: сила 30, останется 28'])
        self.assertEqual(self.judge({}, own={'str': 8}, old={'str': 12}), {'state': 'ok', 'lines': []})
        # спрашивают у самого требовательного; кому атрибут не нужен, тот не в счёт
        self.assertEqual(self.judge({}, old={'str': 12}, others=[('Щит', {'str': 19}), ('Кольцо', {})]), {'state': 'ok', 'lines': []})
        self.assertEqual(self.judge({}, old={'int': 8}, others=[('Камень · 4 ур.', {'int': 21}), ('Тиара', {'int': 16})]),
                         {'state': 'drop', 'lines': ['перестанет работать «Камень · 4 ур.»: интеллект 21, останется 20']})

    def test_when_the_count_disagrees_with_what_is_worn(self):
        # по счёту сила 34, а надетое требует 40: дальше известно только «не меньше 40»
        self.b = wearcheck.bounds(tree(), {'amulet/': {'str': 12}}, {'str': (40, 'Сапоги')})
        self.boots = ('Сапоги', {'str': 40})
        self.assertEqual(self.judge({'str': 36}), {'state': 'ok', 'lines': []})
        self.assertEqual(self.judge({'str': 86}), {'state': 'check', 'lines': ['сила: нужно 86, у героя от 40']})
        self.assertEqual(self.judge({}, old={'str': 12}), {'state': 'check', 'lines': ['сила после замены от 28: «Сапоги» требует 40']})

    def test_the_game_itself_knows_best(self):
        # игра написала, что вещью пользоваться нельзя: это ответ, даже когда причина не видна
        self.assertEqual(self.judge({'str': 30}, unusable=True), {'state': 'no', 'lines': ['игра пишет: этим предметом пользоваться нельзя']})
        self.assertEqual(self.judge({'str': 36}, unusable=True), {'state': 'no', 'lines': ['сила: нужно 36, у героя 34']})
        # клиент такую строку пишет, а у этой вещи её нет — значит, надеть можно: о её требованиях молчим,
        # но о том, что после замены перестанет работать, — нет
        self.assertEqual(self.judge({'level': 90, 'str': 36}, hero_level=18, told=True), {'state': 'ok', 'lines': []})
        self.assertEqual(self.judge({'str': 36}, old={'str': 12}, told=True)['lines'],
                         ['перестанет работать «Стальные поножи»: сила 30, останется 22'])


class TextTest(unittest.TestCase):
    def test_requirements_and_the_cannot_use_line_are_read_from_the_item(self):
        cat = test_itemstats.CAT
        body = test_itemstats.BODY.replace('Требуется: Уровень 36, 54 Сила', 'Требуется: Уровень 54, 40 (augmented) Сила, 40 (augmented) Инт')
        self.assertEqual(test_itemstats.passport(body)['req'], {'level': 54, 'str': 40, 'int': 40})
        self.assertEqual(test_itemstats.passport(test_itemstats.BODY)['req'], {'level': 36, 'str': 54})
        text = ('Класс предмета: Шлемы\nРедкость: Редкий\nВы не можете использовать этот предмет, его параметры не будут учтены\n'
                '--------\nВенец бури\nШапка мудреца\n--------\nТребуется: Уровень 30, 48 Ловк\n--------\nУровень предмета: 30\n')
        item = itemcopy.identify(cat, itemcopy.parse(text))
        self.assertEqual((item.get('unusable'), item['base'], itemstats.passport(cat, item)['req']), (True, 'Шапка мудреца', {'level': 30, 'dex': 48}))
        self.assertNotIn('unusable', itemcopy.parse(test_itemstats.BODY))


LOG = ''.join('2026/11/11 %s 1 a [%s Client 1] %s\n' % row for row in (
    ('20:07:03', 'DEBUG', 'Generating level 1 area "G1_1" with seed 1'),
    ('20:07:03', 'INFO', '[SCENE] Set Source [Берег реки]'),
    ('20:08:00', 'INFO', 'Successfully allocated passive skill id: spells18, name: Урон чарами'),
    ('20:08:10', 'INFO', 'Successfully allocated passive skill id: intelligence11, name: Характеристика'),
    ('20:08:20', 'INFO', 'Successfully allocated passive skill id: intelligence12, name: Характеристика'),
))
# В плане дерева один узел «Характеристика» из двух взятых, и ему назначена сила.
BUILD = {'title': 'Учебный билд',
         'slots': [{'id': 'amulet', 'name': 'Амулет', 'classes': ['Amulet'], 'gear': 'Amulet'},
                   {'id': 'boots', 'name': 'Сапоги', 'classes': ['Boots'], 'gear': 'Boots'}],
         'stages': [{'id': 'start', 'name': 'Начало', 'tree': 'v1', 'stats': ['life', 'str']}],
         'tree': {'attr': 'int', 'phases': [{'id': 'v1', 'name': 'Дерево', 'nodes': [
             {'id': 'spells18', 'name': 'Урон чарами'}, {'id': 'intelligence11', 'name': 'Характеристика', 'kind': 'attribute', 'attr': 'str'}]}]},
         'goals': [{'id': 'amulet-any', 'slot': 'amulet', 'any': True, 'title': 'любой', 'need': 'riverbank'},
                   {'id': 'boots-any', 'slot': 'boots', 'any': True, 'title': 'любые', 'need': 'riverbank'}]}
ROUTE = {'id': 'r', 'steps': [{'id': 'riverbank', 'zone': 'G1_1', 'name': 'Берег реки'}]}


def item(cls, base, req, *lines, head=None):
    """Текст вещи, как его копирует русский клиент: редкая вещь с требованиями и строками свойств."""
    return ('Класс предмета: %s\nРедкость: Редкий\n%sЗнак бури\n%s\n--------\nТребуется: %s\n--------\nУровень предмета: 30\n--------\n%s\n'
            % (cls, (head + '\n--------\n') if head else '', base, req, '\n'.join(lines)))


AMBER = item('Амулеты', 'Амулет с янтарём', 'Уровень 1', '+12 к силе (implicit)')
AZURE = item('Амулеты', 'Лазурный амулет', 'Уровень 1', '+25 к максимуму маны (implicit)')
GREAVES = item('Сапоги', 'Стальные рифлёные поножи', 'Уровень 1, 21 Сила', '{ Префикс "Массивный" (Уровень: 7) — Здоровье }', '+40(30-49) к максимуму здоровья')
HEAVY = item('Сапоги', 'Стальные рифлёные поножи', 'Уровень 1, 40 Сила', '{ Префикс "Массивный" (Уровень: 7) — Здоровье }', '+60(50-69) к максимуму здоровья')
LOCKED = item('Сапоги', 'Стальные рифлёные поножи', 'Уровень 45, 25 Сила', '{ Префикс "Массивный" (Уровень: 7) — Здоровье }', '+60(50-69) к максимуму здоровья',
              head='Вы не можете использовать этот предмет, его параметры не будут учтены')


class ServerTest(unittest.TestCase):
    """Ответ доходит до карточки скопированной вещи: настоящие каталог и дерево, герой из учебного лога —
    класс 7 / 7 / 15 и два узла «Характеристика», из которых в плане один (сила)."""

    def setUp(self):
        import server
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        (root / 'Client.txt').write_text(LOG, encoding='utf-8')
        (root / 'plan.json').write_text(json.dumps({'version': 2, 'route': 'route.json', 'build': 'build.json'}), encoding='utf-8')
        (root / 'route.json').write_text(json.dumps(ROUTE, ensure_ascii=False), encoding='utf-8')
        (root / 'build.json').write_text(json.dumps(BUILD, ensure_ascii=False), encoding='utf-8')
        self.root = root
        self.app = server.App(root / 'Client.txt', root / 'plan.json', root / 'runs', backup_dir=root / 'backup')
        with self.app.cond:
            self.app.load_plan()
            self.app.poll_log(initial=True)
            self.app.attach_run()

    def tearDown(self):
        self.tmp.cleanup()

    def wear(self, text, row):
        self.assertTrue(self.app.take_copy(text))
        self.assertTrue(self.app.wear({'row': row}))

    def answer(self, text):
        self.assertTrue(self.app.take_copy(text))
        rows = self.app.view()['copy']['rows']
        self.assertEqual(len(rows), 1)
        return rows[0].get('wear')

    def hero(self):
        h = self.app.view()['heroAttrs']
        return {a['id']: a for a in h['attrs']}, h

    def test_hero_attributes_follow_the_plan_and_the_players_choice(self):
        app = self.app
        if not app.catalog or not app.catalog.get('stats') or not app.tree_geo('tree'):
            self.skipTest('каталог данных игры или дерево не собраны')
        self.assertEqual(app.plan_problems, [])
        by, h = self.hero()
        # узел из плана — сила; второй узел в плане не значится — не считается
        self.assertEqual(([(a, by[a]['value'], by[a]['nodes']) for a in ('str', 'dex', 'int')], h['unset'], h['picks'], h['notes']),
                         ([('str', 12, 1), ('dex', 7, 0), ('int', 15, 0)], ['intelligence12'], {},
                          ['узлов «Характеристика» вне плана без названного атрибута: 1 — не посчитаны']))
        self.assertEqual(self.answer(GREAVES)['lines'], ['сила: нужно 21, у героя 12'])
        # игрок назвал, что взял во втором узле: теперь он считается; выбор лежит в забеге
        self.assertTrue(app.pick({'node': 'intelligence12', 'attr': 'str'}))
        by, h = self.hero()
        self.assertEqual((by['str']['value'], by['str']['nodes'], h['unset'], h['picks'], h['notes']), (17, 2, [], {'intelligence12': 'str'}, []))
        saved = json.loads((self.root / 'runs' / ('%s.json' % app.run.id)).read_text(encoding='utf-8'))
        self.assertEqual(saved['picks'], {'intelligence12': 'str'})
        # не узел «Характеристика» и не атрибут — отказ
        self.assertFalse(app.pick({'node': 'spells18', 'attr': 'str'}))
        self.assertFalse(app.pick({'node': 'intelligence12', 'attr': 'мана'}))
        # амулет с силой: 29 — сапоги надеваются; амулет без силы потом их выключит
        self.wear(AMBER, 'slot:amulet:')
        w = self.answer(GREAVES)
        self.assertEqual((w['state'], w['lines'], w['hero']['str']), ('ok', [], {'lo': 29, 'hi': 29}))
        self.assertEqual(self.answer(HEAVY)['lines'], ['сила: нужно 40, у героя 29'])
        self.wear(GREAVES, 'slot:boots:')
        w = self.answer(AZURE)
        self.assertEqual((w['state'], w['lines']), ('drop', ['перестанет работать «Стальные рифлёные поножи»: сила 21, останется 17']))
        self.assertIsNone(self.answer(GREAVES))                      # надетую вещь не спрашивают
        # выбор игрока важнее плана: узел плана назван интеллектом, второй — снова «как в плане» (то есть никак).
        # По счёту силы 19, а надетые сапоги требуют 21 — счёт неверен, и это сказано
        self.assertTrue(app.pick({'node': 'intelligence11', 'attr': 'int'}))
        self.assertTrue(app.pick({'node': 'intelligence12', 'attr': None}))
        by, h = self.hero()
        self.assertEqual((by['str']['value'], by['str']['need'], by['str']['by'], by['str']['low'], by['int']['value'], h['picks']),
                         (19, 21, 'Стальные рифлёные поножи', True, 20, {'intelligence11': 'int'}))
        w = self.answer(HEAVY)
        self.assertEqual((w['state'], w['lines'], w['hero']['str']), ('check', ['сила: нужно 40, у героя от 21'], {'lo': 21, 'hi': None}))
        self.assertIn('сила по счёту 19, а «Стальные рифлёные поножи» требует 21 — в узлах взято не то, что в плане', w['notes'])
        # память забега читается обратно
        app.run.picks = {}
        app.attach_run()
        self.assertEqual(app.run.picks, {'intelligence11': 'int'})

    def test_the_games_own_line_is_learned(self):
        app = self.app
        if not app.catalog or not app.catalog.get('stats') or not app.tree_geo('tree'):
            self.skipTest('каталог данных игры или дерево не собраны')
        # игра сама написала «нельзя»: ответ есть, и забег запомнил, что клиент такую строку пишет
        self.assertFalse(app.run.told)
        w = self.answer(LOCKED)
        self.assertEqual((w['state'], w['lines']), ('no', ['с 45 уровня героя (сейчас 1)', 'сила: нужно 25, у героя 12']))
        self.assertTrue(app.run.told)
        saved = json.loads((self.root / 'runs' / ('%s.json' % app.run.id)).read_text(encoding='utf-8'))
        self.assertIs(saved['cannotLine'], True)
        # теперь молчание игры — тоже ответ: вещь без этой строки надеть можно, о её требованиях молчим
        w = self.answer(HEAVY)
        self.assertEqual((w['state'], w['lines']), ('ok', []))
        app.run.told = False
        app.attach_run()
        self.assertTrue(app.run.told)


if __name__ == '__main__':
    unittest.main()
