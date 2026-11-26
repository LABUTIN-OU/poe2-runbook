# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Sergei Labutin
# Additional terms under GPL-3.0 section 7: see NOTICE.md
"""Узлы дерева с предметов: зачарование амулета жидкими эмоциями (anoint.py, treegeo.anoints, слой языка каталога).

Запуск: python -m unittest planner.test_anoint
"""
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import anoint  # noqa: E402
import attrneed  # noqa: E402
import buildplan  # noqa: E402
import core  # noqa: E402
import gamedata  # noqa: E402
import itemcopy  # noqa: E402
import server  # noqa: E402
import treegeo  # noqa: E402
import treeplan  # noqa: E402
import wearcheck  # noqa: E402
from test_core import RUN_LINES, TREE  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def catalog_build():
    """catalog/build.py под отдельным именем: имя build слишком общее, чтобы класть его в sys.modules."""
    spec = importlib.util.spec_from_file_location('catalog_build', ROOT / 'catalog' / 'build.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# Копия амулета игрока (2026-11-20, русский клиент): зачарование — строкой с пометкой (enchant).
AMULET = '''Класс предмета: Амулеты
Редкость: Редкий
Жуткая защита
Амулет с перламутром
--------
Требуется: Уровень 36
--------
Уровень предмета: 46
--------
Активирует {node} (enchant)
--------
{{ Собственное свойство — Стихийный, Огонь, Холод, Молния, Сопротивление }}
+7(7-10)% к сопротивлению всем стихиям
--------
{{ Префикс "Чешуйчатый" (Уровень: 4) — Броня }}
29(27-32)% повышение брони
{{ Суффикс "печи" (Уровень: 5) — Стихийный, Огонь, Сопротивление }}
+25(21-25)% к сопротивлению огню
'''
PLAIN_AMULET = AMULET.replace('--------\nАктивирует {node} (enchant)\n', '')


class DataTest(unittest.TestCase):
    """Откуда программа знает узлы зачарования: карта дерева и слой языка каталога."""

    def test_tree_map_lists_anoints_and_leaves_the_unplaced_ones_off(self):
        data = {'nodes': {
            '1': {'id': 'start', 'x': 0, 'y': 0, 'classStartIndex': 0},
            '2': {'id': 'small', 'x': 10, 'y': 0},
            '3': {'id': 'notable', 'x': 20, 'y': 0, 'isNotable': True, 'name': 'Splintering Force',
                  'recipe': ['LiquidEnvy', 'LiquidParanoia', 'DilutedLiquidGuilt']},
            # только для зачарования: координаты есть, связей нет
            '4': {'id': 'DeliriumAnoint_Dominion', 'x': 999, 'y': 999, 'isNotable': True, 'name': 'Dominion',
                  'recipe': ['PotentLiquidContempt', 'ConcentratedLiquidSuffering', 'ConcentratedLiquidIsolation']}},
            'edges': [{'from': 1, 'to': 2}, {'from': 2, 'to': 3}], 'classes': []}
        geo = treegeo.build(data)
        self.assertEqual([n[0] for n in geo['nodes']], ['start', 'small', 'notable'])
        an = geo['anoint']
        recipe = lambda nid: [an['emotions'][i] for i in an['nodes'][nid][1]]
        self.assertEqual(an['nodes']['notable'][0], 3)
        self.assertEqual(recipe('notable'), ['LiquidEnvy', 'LiquidParanoia', 'DilutedLiquidGuilt'])
        self.assertEqual(len(an['nodes']['notable']), 2)                      # на дереве: название — в nodes
        self.assertEqual(an['nodes']['DeliriumAnoint_Dominion'][2], 'Dominion')  # места нет: название здесь

    def test_language_layer_knows_the_line_and_the_names(self):
        build = catalog_build()
        rows = [{'string': 'Активирует Разбивающая сила', 'value': 49088, 'oils': '4,3,1'},
                {'string': 'Активирует Господство', 'value': 2, 'oils': '10,8,9'},
                {'string': 'Активирует Бык', 'value': 3}]
        self.assertEqual(build.build_anoint(rows), {'line': 'Активирует {0}',
                                                    'nodes': {'49088': 'Разбивающая сила', '2': 'Господство', '3': 'Бык'}})
        self.assertEqual(build.build_anoint([]), {})
        stats = json.dumps({'ref': 'Allocates #', 'matchers': [{'string': 'Allocates Dominion', 'value': 2},
                                                              {'string': 'Allocates Bull', 'value': 3}]})
        pack = build.build_lang('', stats, {})
        self.assertEqual(pack['anoint'], {'line': 'Allocates {0}', 'nodes': {'2': 'Dominion', '3': 'Bull'}})

    def test_real_data_names_splintering_force_and_its_recipe(self):
        cat = gamedata.load(ROOT / 'catalog' / 'data')
        geo = treeplan.load_geo(ROOT / 'planner' / 'static' / 'tree.json')
        if not ((cat or {}).get('lang') or {}).get('ru', {}).get('anoint') or not geo.get('anoint'):
            self.skipTest('каталог или карта дерева без узлов зачарования')
        item = itemcopy.parse(AMULET.format(node='Разбивающая сила'))
        self.assertEqual(anoint.on_item(cat, geo, item), [{'name': 'Разбивающая сила', 'ids': ['minion_offence15']}])
        self.assertEqual(anoint.recipe(cat, geo, 'minion_offence15', 'ru'),
                         ['Жидкая зависть', 'Жидкая паранойя', 'Разбавленная жидкая вина'])
        self.assertEqual(anoint.name_of(cat, geo, 'minion_offence15', 'en', '?'), 'Splintering Force')
        # узел без места на дереве узнаётся так же; на карте его нет
        dom = anoint.on_item(cat, geo, itemcopy.parse(AMULET.format(node='Господство')))
        self.assertEqual(dom, [{'name': 'Господство', 'ids': ['DeliriumAnoint_Dominion']}])
        self.assertNotIn('DeliriumAnoint_Dominion', geo['kind'])
        # одно русское название у двух узлов: без плана узел не выбрать
        two = anoint.on_item(cat, geo, itemcopy.parse(AMULET.format(node='Несломимый')))
        self.assertEqual(len(two[0]['ids']), 2)
        self.assertIsNone(anoint.pick(two[0]['ids'], set()))
        self.assertEqual(anoint.pick(two[0]['ids'], {two[0]['ids'][1]}), two[0]['ids'][1])
        # строки без зачарования — ничего
        self.assertEqual(anoint.on_item(cat, geo, itemcopy.parse(PLAIN_AMULET)), [])


# Карта для расчёта пути: старт S; ветка S-a1-a2-N1 (N1 — значимый в конце); от a1 — «Характеристика» b1, малый b2
# и значимый N2; отдельно S-c1-M-c2-N3: значимый M в середине пути.
GEO = {'kind': {'S': 5, 'a1': 0, 'a2': 0, 'N1': 2, 'b1': 1, 'b2': 0, 'N2': 2, 'c1': 0, 'M': 2, 'c2': 0, 'N3': 2},
       'near': {}}
for a, b in [('S', 'a1'), ('a1', 'a2'), ('a2', 'N1'), ('a1', 'b1'), ('b1', 'b2'), ('b2', 'N2'),
             ('S', 'c1'), ('c1', 'M'), ('M', 'c2'), ('c2', 'N3')]:
    GEO['near'].setdefault(a, set()).add(b)
    GEO['near'].setdefault(b, set()).add(a)
ORDER = ['a1', 'a2', 'N1', 'b1', 'b2', 'N2', 'c1', 'M', 'c2', 'N3']


class SpareTest(unittest.TestCase):
    """Что из версии дерева брать очком не нужно, когда узел даёт предмет."""

    def test_end_of_branch_frees_the_node_and_the_path_only_to_it(self):
        self.assertEqual(anoint.spare(ORDER, {'N1'}, set(), GEO), {'N1': {'N1', 'a2'}})
        # путь кончается на «Характеристике»: её атрибуты план мог считать — она остаётся
        self.assertEqual(anoint.spare(ORDER, {'N2'}, set(), GEO), {'N2': {'N2', 'b2'}})

    def test_node_in_the_middle_of_the_path_keeps_its_point(self):
        self.assertEqual(anoint.spare(ORDER, {'M'}, set(), GEO), {})

    def test_taken_nodes_and_nodes_out_of_the_plan(self):
        self.assertEqual(anoint.spare(ORDER, {'N1'}, {'a2'}, GEO), {'N1': {'N1'}})     # путь уже взят
        self.assertEqual(anoint.spare(ORDER, {'N1'}, {'N1'}, GEO), {})               # взят очком — дело игрока
        self.assertEqual(anoint.spare(['a1', 'a2'], {'N1'}, set(), GEO), {})         # узла нет в версии

    def test_pick(self):
        self.assertEqual(anoint.pick(['x'], set()), 'x')
        self.assertIsNone(anoint.pick(['x', 'y'], {'x', 'y'}))
        self.assertEqual(anoint.pick(['x', 'y'], {'y'}), 'y')

    def test_row_states(self):
        """Строка блока «Дерево»: в версии и сберегает очки, держит путь, уже взят очком, не в плане, не узнать."""
        geo = {'kind': {'a': 2, 'b': 2, 'c': 2, 'd': 2}}
        tree = {'plan': [{'id': 'a'}, {'id': 'b'}, {'id': 'c'}], 'have': ['c', 'p']}
        found = [{'name': 'A', 'ids': ['a'], 'key': 'amulet/', 'amulet': True},
                 {'name': 'B', 'ids': ['b'], 'key': 'amulet/', 'amulet': True},
                 {'name': 'C', 'ids': ['c'], 'key': 'amulet/', 'amulet': True},
                 {'name': 'D', 'ids': ['d'], 'key': 'body/', 'amulet': False},
                 {'name': 'E', 'ids': ['x', 'y'], 'key': 'amulet/', 'amulet': True}]
        rows = anoint.view(found, tree, {'a': {'a', 'p', 'q'}}, None, geo, 'ru',
                           {'amulet': 'Амулет', 'body': 'Нательный доспех'})
        self.assertEqual([(r['id'], r['name'], r['state'], r.get('saves')) for r in rows],
                         [('a', 'A', 'plan', 2), ('b', 'B', 'path', None), ('c', 'C', 'took', None),
                          ('d', 'D', 'out', None), (None, 'E', 'out', None)])
        self.assertEqual([(r['slot'], r['amulet']) for r in rows[2:4]], [('Амулет', True), ('Нательный доспех', False)])


class QueueTest(unittest.TestCase):
    """Очередь дерева на странице забега: узел с предмета очком не берут."""

    def derive(self, given=None):
        plan, problems = core.norm_plan(TREE)
        self.assertEqual(problems, [])
        parser, run = core.LogParser(core.heard_ids(plan)), core.Run()
        for line in RUN_LINES:
            for ev in parser.feed(line):
                if ev['type'] == 'start':
                    run = core.Run(core.run_id(ev['ts']), ev['ts'])
                else:
                    run.events.append(ev)
        return core.derive(plan, run, 0, given=given)['tree']

    def test_without_items_nothing_changes(self):
        t = self.derive()
        self.assertEqual((t['taken'], t['total'], 'skip' in t), (0, 5, False))

    def test_node_from_an_item_leaves_the_queue_and_counts_as_taken(self):
        seen = []

        def given(order, taken, pos):
            seen.append((order, taken, pos))
            return {'notable1'}, {'notable1'}
        t = self.derive(given)
        self.assertEqual(seen[0][0], ['spells18', 'intelligence11', 'notable1', 'cold2', 'cold3'])
        self.assertEqual([n['id'] for n in t['next']], ['spells18', 'intelligence11', 'cold2', 'cold3'])
        self.assertEqual((t['taken'], t['total'], t['skip'], t['free']), (1, 5, ['notable1'], 2))

    def test_path_only_to_it_leaves_the_count(self):
        t = self.derive(lambda order, taken, pos: ({'notable1'}, {'notable1', 'cold3'}))
        self.assertEqual([n['id'] for n in t['next']], ['spells18', 'intelligence11', 'cold2'])
        self.assertEqual((t['taken'], t['total'], t['skip']), (1, 4, ['cold3', 'notable1']))


# План с амулетом и деревом: версия — путь от старта Ведьмы до «Разбивающей силы» (данные игры) или без неё.
LOG = ('2026/11/11 20:07:03 1 a [DEBUG Client 1] Generating level 1 area "G1_1" with seed 1\n'
       '2026/11/11 20:07:03 1 a [INFO Client 1] [SCENE] Set Source [Берег реки]\n')


def plan_with(nodes):
    return {'slots': [{'id': 'amulet', 'name': 'Амулет', 'classes': ['Амулеты']}],
            'steps': [{'id': 'riverbank', 'zone': 'G1_1', 'name': 'Берег реки'},
                      {'id': 'clearfell', 'zone': 'G1_2', 'name': 'Клирфелл'}],
            'goals': [{'id': 'amulet-any', 'slot': 'amulet', 'title': 'любой', 'any': True}],
            # статы этапа: без них предмет не сравнить, и «Надеть» его не запомнит
            'stages': [{'id': 'start', 'name': 'До вознесения', 'tree': 'start',
                        'stats': ['res_fire', 'res_cold', 'res_lightning']}],
            'tree': {'phases': [{'id': 'start', 'name': 'До вознесения', 'nodes': [{'id': n} for n in nodes]}]}}


class AppBase(unittest.TestCase):
    """Программа на настоящих данных игры (каталог, карта дерева) и временной папке плана и забегов."""

    def setUp(self):
        self.cat = gamedata.load(ROOT / 'catalog' / 'data')
        self.geo = treeplan.load_geo(ROOT / 'planner' / 'static' / 'tree.json')
        if not ((self.cat or {}).get('lang') or {}).get('ru', {}).get('anoint') or not self.geo.get('anoint'):
            self.skipTest('каталог или карта дерева без узлов зачарования')
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / 'Client.txt').write_text(LOG, encoding='utf-8')

    def tearDown(self):
        self.tmp.cleanup()

    def start(self, nodes):
        (self.root / 'plan.json').write_text(json.dumps(plan_with(nodes), ensure_ascii=False), encoding='utf-8')
        app = server.App(self.root / 'Client.txt', self.root / 'plan.json', self.root / 'runs')
        with app.cond:
            app.load_plan()
            app.poll_log(initial=True)
            app.attach_run()
        return app

    def path_to(self, target):
        """Узлы от ближайшего старта класса до target по карте дерева (без старта)."""
        near, kind = self.geo['near'], self.geo['kind']
        prev = {s: None for s, k in kind.items() if k == 5}
        queue = list(prev)
        while queue and target not in prev:
            x = queue.pop(0)
            for y in sorted(near.get(x) or ()):
                if y not in prev:
                    prev[y] = x
                    queue.append(y)
        path, x = [], target
        while prev[x] is not None:
            path.append(x)
            x = prev[x]
        return path[::-1]

    def wear(self, app, node):
        self.assertTrue(app.take_copy(AMULET.format(node=node)))
        self.assertTrue(app.wear({'row': 'slot:amulet:'}))

class AppTest(AppBase):
    """Копия амулета, «Надеть» — и узел с амулета на странице забега: блок «Дерево» и карточка копии."""

    def test_node_out_of_the_plan(self):
        app = self.start(self.path_to('minion_offence15')[:-3])
        self.assertTrue(app.take_copy(AMULET.format(node='Разбивающая сила')))
        cp = app.view()['copy']
        self.assertEqual(cp['anoint'], [{'name': 'Разбивающая сила',
                                         'recipe': ['Жидкая зависть', 'Жидкая паранойя', 'Разбавленная жидкая вина']}])
        self.assertNotIn('anoint', cp['rows'][0])                  # в слоте ничего не надето — терять нечего
        self.assertTrue(app.wear({'row': 'slot:amulet:'}))
        t = app.view()['tree']
        self.assertEqual(t['anoint'], [{'id': 'minion_offence15', 'name': 'Разбивающая сила', 'slot': 'Амулет',
                                        'amulet': True, 'state': 'out', 'node': 'minion_offence15'}])
        self.assertNotIn('skip', t)
        self.assertEqual(app.view('en')['tree']['anoint'][0]['name'], 'Splintering Force')
        # другой амулет без зачарования: с надетого узел теряется — у строки слота её узел и рецепт
        self.assertTrue(app.take_copy(PLAIN_AMULET))
        cp = app.view()['copy']
        self.assertNotIn('anoint', cp)
        self.assertEqual(cp['rows'][0]['anoint'][0]['name'], 'Разбивающая сила')

    def test_node_at_the_end_of_the_plan_branch(self):
        path = self.path_to('minion_offence15')
        app = self.start(path)
        before = app.view()['tree']
        self.wear(app, 'Разбивающая сила')
        t = app.view()['tree']
        # сама «Разбивающая сила» и два малых узла пути к ней; путь кончается на «Характеристике» — она остаётся
        self.assertEqual(t['skip'], sorted(['minion_offence15', 'minion_offence20', 'minion_offence23']))
        self.assertEqual(t['anoint'][0]['state'], 'plan')
        self.assertEqual(t['anoint'][0]['saves'], 3)
        self.assertEqual((before['total'], t['total'], t['taken']), (len(path), len(path) - 2, 1))
        self.assertNotIn('minion_offence15', [n['id'] for n in t['next']])

    def test_node_without_a_place_on_the_tree(self):
        app = self.start(self.path_to('minion_offence15')[:-3])
        self.wear(app, 'Господство')
        t = app.view()['tree']
        self.assertEqual(t['anoint'], [{'id': None, 'name': 'Господство', 'slot': 'Амулет', 'amulet': True,
                                        'state': 'out', 'node': 'DeliriumAnoint_Dominion'}])


class ItemsCheckTest(unittest.TestCase):
    """Узлы, которые версия дерева берёт с предметов (поле items версии): проверка и запись."""

    def setUp(self):
        self.geo = treeplan.load_geo(ROOT / 'planner' / 'static' / 'tree.json')
        if not self.geo.get('anoint'):
            self.skipTest('карта дерева без узлов зачарования')
        self.path = AppBase.path_to(self, 'minion_offence15')[:-3]

    def check(self, items, slots=('amulet',), path=None):
        v = {'id': 'start', 'name': 'Старт', 'nodes': [{'id': n} for n in (path or self.path)]}
        if items is not None:
            v['items'] = items
        return treeplan.check_all([v], {}, self.geo, set(slots))

    def test_good_item_and_its_absence(self):
        out, problems = self.check([{'id': 'minion_offence15', 'slot': 'amulet'}])
        self.assertEqual((problems, out[0]['items']), ([], [{'id': 'minion_offence15', 'slot': 'amulet'}]))
        out, problems = self.check(None)
        self.assertEqual((problems, 'items' in out[0]), ([], False))       # страница поля не прислала

    def test_bad_items(self):
        bad = lambda items: self.check(items)[1]
        self.assertIn('зачарованием не берут', bad([{'id': 'minion_offence20', 'slot': 'amulet'}])[0])   # малый узел
        full = AppBase.path_to(self, 'minion_offence15')
        self.assertIn('и в пути версии', self.check([{'id': 'minion_offence15', 'slot': 'amulet'}], path=full)[1][0])
        self.assertIn('записан дважды', bad([{'id': 'minion_offence15', 'slot': 'amulet'}] * 2)[0])
        self.assertIn('нет слота', bad([{'id': 'minion_offence15', 'slot': 'ring1'}])[0])
        self.assertIn('один узел', bad([{'id': 'minion_offence15', 'slot': 'amulet'},
                                        {'id': 'DeliriumAnoint_Dominion', 'slot': 'amulet'}])[0])

    def test_written_with_names_and_kept_when_not_sent(self):
        tree = {'phases': [{'id': 'start', 'name': 'Старт', 'items': [{'id': 'old', 'name': 'Прежний', 'slot': 'amulet'}],
                            'nodes': []}]}
        names = {'minion_offence15': 'Разбивающая сила'}
        sent = [{'id': 'start', 'name': 'Старт', 'nodes': [], 'items': [{'id': 'minion_offence15', 'slot': 'amulet'}]}]
        ph = treeplan.apply_all(tree, sent, names, self.geo)['phases'][0]
        self.assertEqual((list(ph), ph['items']), (['id', 'name', 'items', 'nodes'],
                                                   [{'id': 'minion_offence15', 'name': 'Разбивающая сила', 'slot': 'amulet'}]))
        kept = treeplan.apply_all(tree, [{'id': 'start', 'name': 'Старт', 'nodes': []}], names, self.geo)['phases'][0]
        self.assertEqual(kept['items'], tree['phases'][0]['items'])        # страница поля не знает — прежние целы
        gone = treeplan.apply_all(tree, [dict(sent[0], items=[])], names, self.geo)['phases'][0]
        self.assertNotIn('items', gone)                                     # прислала пустой список — узлов нет


def build_file(path_nodes, items=None):
    """Файл билда с амулетом, этапом со статами и версией дерева — в том виде, какой правит программа."""
    tree = {'phases': [dict({'id': 'start', 'name': 'Старт'}, **({'items': items} if items else {}),
                            nodes=[{'id': n, 'name': n} for n in path_nodes])]}
    head = ['{', '  "version": 2,', '  "title": "Проба",',
            '  "slots": [{"id": "amulet", "name": "Амулет", "wear": [{"classes": ["Amulet"]}]}],']
    stages = buildplan.render('stages', [{'id': 'start', 'name': 'Старт', 'tree': 'start',
                                           'stats': ['res_fire', 'res_cold', 'res_lightning']}])
    stages[-1] += ','
    return '\n'.join(head + stages + treeplan.render(tree)[:-1] + [
        '  },', '  "goals": [', '    {"id": "amulet-any", "slot": "amulet", "title": "любой", "any": true}', '  ]', '}', ''])


class PlanItemsTest(AppBase):
    """Узел с амулета в плане: редактор пишет его в версию, страница забега говорит «по плану» или «на амулет»."""

    def start2(self, items=None):
        root = self.root
        (root / 'plan.json').write_text(json.dumps({'version': 2, 'route': 'route.json', 'build': 'build.json'}), encoding='utf-8')
        (root / 'route.json').write_text(json.dumps({'id': 'r', 'steps': plan_with([])['steps']}, ensure_ascii=False),
                                         encoding='utf-8')
        (root / 'build.json').write_text(build_file(self.path_to('minion_offence15')[:-3], items), encoding='utf-8')
        app = server.App(root / 'Client.txt', root / 'plan.json', root / 'runs', backup_dir=root / 'backup')
        with app.cond:
            app.load_plan()
            app.poll_log(initial=True)
            app.attach_run()
        return app

    def test_editor_writes_the_node_and_the_run_page_follows_it(self):
        app = self.start2()
        an = app.build_view()['anoint']
        self.assertEqual(an['slots'], ['amulet'])
        row = next(r for r in an['nodes'] if r[0] == 'minion_offence15')
        self.assertEqual((row[1], row[2], [an['emotions'][i] for i in row[3]], row[4]),
                         ('Разбивающая сила', 'Splintering Force', ['Жидкая зависть', 'Жидкая паранойя', 'Разбавленная жидкая вина'], 0))
        self.assertEqual(next(r for r in an['nodes'] if r[0] == 'DeliriumAnoint_Dominion')[4], 1)
        # редактор прислал версию с узлом с амулета: он в файле — с названием и слотом
        vers = app.build_view()['treePlan']['tree']['versions']
        sent = [dict(vers[0], items=[{'id': 'minion_offence15', 'slot': 'amulet'}])]
        self.assertEqual(app.save_build({'tree': {'versions': sent}}), (True, []))
        saved = json.loads((self.root / 'build.json').read_text(encoding='utf-8'))
        self.assertEqual(saved['tree']['phases'][0]['items'], [{'id': 'minion_offence15', 'name': 'Разбивающая сила', 'slot': 'amulet'}])
        self.assertEqual(app.build_view()['treePlan']['tree']['versions'][0]['items'], [{'id': 'minion_offence15', 'slot': 'amulet'}])
        # на амулете узла ещё нет: «на амулет» и чем зачаровать
        t = app.view()['tree']
        self.assertEqual(t['anoint'], [{'id': 'minion_offence15', 'name': 'Разбивающая сила', 'slot': 'Амулет', 'amulet': True,
                                        'state': 'todo', 'recipe': ['Жидкая зависть', 'Жидкая паранойя', 'Разбавленная жидкая вина']}])
        # надел амулет с этим узлом: «по плану»; очередь и счёт дерева прежние — в пути версии узла нет
        before = (t['taken'], t['total'], [n['id'] for n in t['next']])
        self.wear(app, 'Разбивающая сила')
        t = app.view()['tree']
        self.assertEqual([(r['id'], r['state']) for r in t['anoint']], [('minion_offence15', 'item')])
        self.assertEqual((t['taken'], t['total'], [n['id'] for n in t['next']]), before)
        # другой узел на амулете: свой — «не в плане», плановый — снова «на амулет»
        self.wear(app, 'Господство')
        self.assertEqual([(r['name'], r['state']) for r in app.view()['tree']['anoint']],
                         [('Господство', 'out'), ('Разбивающая сила', 'todo')])

    def test_editor_check_refuses_a_node_on_the_path(self):
        app = self.start2()
        vers = app.build_view()['treePlan']['tree']['versions']
        full = [{'id': n} for n in self.path_to('minion_offence15')]
        ok, problems = app.save_build({'tree': {'versions': [dict(vers[0], nodes=full,
                                                                  items=[{'id': 'minion_offence15', 'slot': 'amulet'}])]}})
        self.assertFalse(ok)
        self.assertIn('и в пути версии, и с предмета', problems[0])


class WithoutTest(unittest.TestCase):
    """Запасная версия (without): действует, пока узлов, которые версия берёт с амулета, на амулете нет."""

    def setUp(self):
        self.geo = treeplan.load_geo(ROOT / 'planner' / 'static' / 'tree.json')
        if not self.geo.get('anoint'):
            self.skipTest('карта дерева без узлов зачарования')
        self.path = AppBase.path_to(self, 'minion_offence15')[:-3]

    def check(self, *versions):
        return treeplan.check_all(list(versions), {}, self.geo, {'amulet'})

    def version(self, vid, items=(), without=None):
        v = {'id': vid, 'name': vid.upper(), 'nodes': [{'id': n} for n in self.path], 'items': list(items)}
        if without is not None:
            v['without'] = without
        return v

    def test_good_and_bad_stand_ins(self):
        dom = [{'id': 'DeliriumAnoint_Dominion', 'slot': 'amulet'}]
        out, problems = self.check(self.version('a'), self.version('b', dom, 'a'))
        self.assertEqual((problems, out[1]['without'], 'without' in out[0]), ([], 'a', False))
        self.assertEqual(self.check(self.version('a'), self.version('b', dom, ''))[0][1].get('without'), None)   # пусто — нет
        self.assertIn('запасной версии', self.check(self.version('b', dom, 'nope'))[1][0])
        self.assertIn('запасной версии', self.check(self.version('b', dom, 'b'))[1][0])
        self.assertIn('только версии с узлами с амулета', self.check(self.version('a'), self.version('b', (), 'a'))[1][0])
        self.assertIn('по кругу', self.check(self.version('a', dom, 'b'), self.version('b', dom, 'a'))[1][0])

    def test_written_kept_and_removed(self):
        tree = {'phases': [{'id': 'a', 'name': 'A', 'nodes': []},
                           {'id': 'b', 'name': 'B', 'items': [{'id': 'x', 'name': 'X', 'slot': 'amulet'}], 'without': 'a', 'nodes': []}]}
        a = {'id': 'a', 'name': 'A', 'nodes': []}
        b = {'id': 'b', 'name': 'B', 'nodes': [], 'items': [{'id': 'x', 'slot': 'amulet'}]}
        new = treeplan.apply_all(tree, [a, dict(b, without='a')], {'x': 'X'}, self.geo)['phases'][1]
        self.assertEqual((list(new), new['without']), (['id', 'name', 'items', 'without', 'nodes'], 'a'))
        self.assertEqual(treeplan.apply_all(tree, [a, {'id': 'b', 'name': 'B', 'nodes': []}], {}, self.geo)['phases'][1]['without'], 'a')
        self.assertNotIn('without', treeplan.apply_all(tree, [a, dict(b, without='')], {'x': 'X'}, self.geo)['phases'][1])

    def test_waiting_picks_the_stand_in_until_the_node_is_worn(self):
        plan = {'tree': {'phases': [{'id': 'a', 'nodes': []},
                                    {'id': 'b', 'items': [{'id': 'x'}], 'without': 'a', 'nodes': []},
                                    {'id': 'c', 'items': [{'id': 'y'}], 'without': 'b', 'nodes': []}]}}
        ph = {p['id']: p for p in plan['tree']['phases']}
        pick = lambda v, have: tuple((p or {}).get('id') for p in core.waiting(plan, ph[v], have))
        self.assertEqual(pick('b', set()), ('a', 'b'))           # узла нет — запасная; ждёт «b»
        self.assertEqual(pick('b', {'x'}), ('b', None))          # надет — своя
        self.assertEqual(pick('c', set()), ('a', 'c'))           # по цепочке: ни y, ни x
        self.assertEqual(pick('c', {'x'}), ('b', 'c'))
        self.assertEqual(pick('b', None), ('b', None))           # что надето, не известно — как есть
        self.assertEqual(pick('a', set()), ('a', None))          # у версии нет узлов с амулета


class AttributesTest(unittest.TestCase):
    def test_node_from_an_item_gives_its_attributes(self):
        lines = {'n1': ['+10 to Strength'], 'n2': ['+8 to Intelligence']}
        events = [{'type': 'passive', 'op': 'take', 'id': 'n2', 'ts': 1}]
        self.assertEqual(wearcheck.tree_state(lines, {}, events)['flat'], {'str': 0, 'dex': 0, 'int': 8})
        self.assertEqual(wearcheck.tree_state(lines, {}, events, extra=['n1', 'n2'])['flat'], {'str': 10, 'dex': 0, 'int': 8})
        self.assertEqual(attrneed.with_items({'items': [{'id': 'n1', 'slot': 'amulet'}]}), [{'id': 'n1'}])


def build_two(path_nodes):
    """Файл билда с двумя версиями: «Старт» и «Старт с Господством» (Господство с амулета; пока его нет — «Старт»)."""
    tree = {'phases': [{'id': 'start', 'name': 'Старт', 'nodes': [{'id': n, 'name': n} for n in path_nodes]},
                       {'id': 'dom', 'name': 'Старт с Господством',
                        'items': [{'id': 'DeliriumAnoint_Dominion', 'name': 'Господство', 'slot': 'amulet'}], 'without': 'start',
                        'nodes': [{'id': n, 'name': n} for n in path_nodes[:-1]]}]}
    head = ['{', '  "version": 2,', '  "title": "Проба",',
            '  "slots": [{"id": "amulet", "name": "Амулет", "wear": [{"classes": ["Amulet"]}]}],']
    stages = buildplan.render('stages', [{'id': 'start', 'name': 'Старт', 'tree': 'dom',
                                           'stats': ['res_fire', 'res_cold', 'res_lightning']}])
    stages[-1] += ','
    return '\n'.join(head + stages + treeplan.render(tree)[:-1] + [
        '  },', '  "goals": [', '    {"id": "amulet-any", "slot": "amulet", "title": "любой", "any": true}', '  ]', '}', ''])


class StandInRunTest(AppBase):
    """Страница забега: пока Господства на амулете нет — дерево «Старт» и строка «на амулет … потом дерево …»;
    надел амулет с Господством — дерево само переходит на «Старт с Господством»."""

    def test_tree_switches_with_the_amulet(self):
        root = self.root
        (root / 'plan.json').write_text(json.dumps({'version': 2, 'route': 'route.json', 'build': 'build.json'}), encoding='utf-8')
        (root / 'route.json').write_text(json.dumps({'id': 'r', 'steps': plan_with([])['steps']}, ensure_ascii=False), encoding='utf-8')
        (root / 'build.json').write_text(build_two(self.path_to('minion_offence15')[:-3]), encoding='utf-8')
        app = server.App(root / 'Client.txt', root / 'plan.json', root / 'runs', backup_dir=root / 'backup')
        with app.cond:
            app.load_plan()
            app.poll_log(initial=True)
            app.attach_run()
        t = app.view()['tree']
        self.assertEqual((t['now'], t['phase'], t['target']['id']), ('start', 'Старт', 'dom'))
        self.assertEqual([(r['name'], r['state'], r.get('then')) for r in t['anoint']],
                         [('Господство', 'todo', 'Старт с Господством')])
        self.wear(app, 'Господство')
        t = app.view()['tree']
        self.assertEqual((t['now'], 'target' in t), ('dom', False))
        self.assertEqual([(r['name'], r['state']) for r in t['anoint']], [('Господство', 'item')])
        # на вкладке «Дерево» редактора: запасная версия и узел атласа для густых эмоций
        vers = app.build_view()['treePlan']['tree']['versions']
        self.assertEqual([(v['id'], v.get('without')) for v in vers], [('start', None), ('dom', 'start')])
        an = app.build_view()['anoint']
        self.assertEqual([an['emotions'][i] for i in an['potent']],
                         ['Густое жидкое презрение', 'Густая жидкая свирепость', 'Густая жидкая меланхолия'])
        self.assertEqual((an['potentAtlas'] or {}).get('id'), anoint.POTENT_ATLAS)


class AvailableFromTest(unittest.TestCase):
    """Когда узел с амулета станет доступен: с какого уровня зоны падают все эмоции его рецепта."""

    def test_catalogue_part(self):
        items = {'Metadata/Items/Currency/DistilledEmotion10': {'name': 'Concentrated Liquid Isolation', 'drop_level': 77},
                 'Metadata/Items/Currency/EndgameDistilledEmotion3': {'name': 'Potent Liquid Contempt', 'drop_level': 65},
                 'Metadata/Items/Currency/DistilledEmotion5': {'name': 'Liquid Envy', 'drop_level': 1},
                 'Metadata/Items/Currency/CurrencyRerollRemnant': {'name': 'Liquid Verisium', 'drop_level': 1}}
        self.assertEqual(catalog_build().build_emotions(items),
                         {'Concentrated Liquid Isolation': 77, 'Potent Liquid Contempt': 65, 'Liquid Envy': 1})

    def test_real_recipes(self):
        cat = gamedata.load(ROOT / 'catalog' / 'data')
        geo = treeplan.load_geo(ROOT / 'planner' / 'static' / 'tree.json')
        if not (cat or {}).get('emotions') or not geo.get('anoint'):
            self.skipTest('в каталоге нет уровней эмоций или карта дерева без узлов зачарования')
        # Господство: густое презрение (65), концентрированные страдание (73) и отчуждение (77)
        self.assertEqual(anoint.available_from(cat, geo, 'DeliriumAnoint_Dominion'), 77)
        self.assertEqual(anoint.available_from(cat, geo, 'minion_offence15'), 1)       # три простые эмоции
        self.assertIsNone(anoint.available_from(cat, geo, 'нет такого'))
        tree = {'plan': [], 'have': [], 'items': [{'id': 'DeliriumAnoint_Dominion', 'slot': 'amulet'},
                                                  {'id': 'minion_offence15', 'slot': 'amulet'}]}
        rows = anoint.view([], tree, {}, cat, geo, 'ru', {'amulet': 'Амулет'}, {'amulet'})
        self.assertEqual([(r['name'], r.get('from')) for r in rows], [('Господство', 77), ('Разбивающая сила', None)])


class PlayerWordsTest(unittest.TestCase):
    """На картах игрок говорит уровнем путевого камня, а не уровнем зоны: зона 77 — это T13."""

    def test_zone_level_in_the_players_words(self):
        self.assertEqual([core.zone_word(x) for x in (52, 64, 65, 77, 80, 81)],
                         ['зона 52', 'зона 64', 'T1', 'T13', 'T16', 'зона 81'])
        self.assertEqual([core.from_zone(x) for x in (52, 77)], ['с зоны 52', 'с T13'])


if __name__ == '__main__':
    unittest.main()
