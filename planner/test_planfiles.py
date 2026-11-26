# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Sergei Labutin
# Additional terms under GPL-3.0 section 7: see NOTICE.md
"""Проверка плана из частей: маршрут и билд. Запуск: python -m unittest planner.test_planfiles"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import core  # noqa: E402
import planfiles  # noqa: E402
import server  # noqa: E402

ROUTE = {
    'version': 2, 'id': 'campaign',
    'steps': [{'id': 'riverbank', 'zone': 'G1_1', 'name': 'Берег реки', 'target': '11:00', 'filter': 'f1', 'filterName': 'Первый',
               'notes': []},
              {'id': 'clearfell', 'zone': 'G1_2', 'name': 'Клирфелл', 'target': '5:30', 'notes': ['Точка'], 'touch': ['G1_town']}],
    'goals': [{'id': 'boss-miller', 'kind': 'boss', 'title': 'Мельник', 'must': True, 'need': 'riverbank'},
              {'id': 'hero-3', 'group': 'Уровень', 'title': '3 уровень героя', 'reach': 3, 'need': 'clearfell'}],
}
BUILD = {
    'version': 2, 'title': 'Герой', 'routeId': 'campaign',
    'slots': [{'id': 'weapon', 'name': 'Оружие'}],
    'goals': [{'id': 'bow', 'slot': 'weapon', 'title': 'Самострел', 'need': 'clearfell'},
              {'id': 'bomb', 'kind': 'skill', 'group': 'Навыки', 'title': 'Бомба', 'need': 'clearfell'},
              {'id': 'gold', 'kind': 'resource', 'group': 'Ресурсы', 'title': 'Золото', 'need': 'clearfell'}],
}
MANIFEST = {'version': 2, 'route': 'routes/campaign.json', 'build': 'builds/hero.json', 'groups': ['Уровень', 'Ресурсы', 'Навыки']}
LOG = '\n'.join([
    '2026/11/11 20:07:03 1 a [DEBUG Client 1] Generating level 1 area "G1_1" with seed 1',
    '2026/11/11 20:07:03 1 a [INFO Client 1] [SCENE] Set Source [Берег реки]',
    '2026/11/11 20:10:55 1 a [DEBUG Client 1] Generating level 2 area "G1_2" with seed 5',
    '2026/11/11 20:10:56 1 a [INFO Client 1] [SCENE] Set Source [Клирфелл]',
]) + '\n'


class ComposeTest(unittest.TestCase):
    def test_plan_from_two_parts(self):
        raw, notes = planfiles.compose(MANIFEST, ROUTE, BUILD)
        self.assertEqual(notes, [])
        # шаги — шаги маршрута как они записаны: фильтр шага и его название — поля самого шага
        self.assertEqual([s['id'] for s in raw['steps']], ['riverbank', 'clearfell'])
        self.assertEqual(raw['steps'][0], ROUTE['steps'][0])
        self.assertEqual((raw['steps'][1]['target'], raw['steps'][1]['touch']), ('5:30', ['G1_town']))
        # цели — билда, потом маршрута; разделы — из билда; фильтров с названиями здесь нет — их даёт игра (сервер)
        self.assertEqual([g['id'] for g in raw['goals']], ['bow', 'bomb', 'gold', 'boss-miller', 'hero-3'])
        self.assertEqual((raw['title'], 'filters' in raw, raw['slots'][0]['id']), ('Герой', False, 'weapon'))
        self.assertEqual(raw['groupOrder'], ['Уровень', 'Ресурсы', 'Навыки'])
        plan, problems = core.norm_plan(raw)
        self.assertEqual(problems, [])
        # части не меняются оттого, что из них собрали план
        raw['steps'][0]['name'] = 'другое'
        self.assertEqual(ROUTE['steps'][0]['name'], 'Берег реки')

    def test_group_order_comes_from_the_table_of_contents(self):
        """Порядок групп на странице задан в оглавлении, а не местом цели в файле."""
        raw, _ = planfiles.compose(MANIFEST, ROUTE, BUILD)
        plan, _ = core.norm_plan(raw)
        view = core.derive(plan, core.Run(), 0)
        self.assertEqual([g['name'] for g in view['groups']], ['Уровень', 'Ресурсы', 'Навыки'])
        # без оглавления — как раньше: по первой цели каждой группы; не названная группа встаёт следом
        raw, _ = planfiles.compose({}, ROUTE, BUILD)
        self.assertEqual([g['name'] for g in core.derive(core.norm_plan(raw)[0], core.Run(), 0)['groups']],
                         ['Навыки', 'Ресурсы', 'Уровень'])
        raw, _ = planfiles.compose({'groups': ['Уровень', 'Пустая']}, ROUTE, BUILD)
        self.assertEqual([g['name'] for g in core.derive(core.norm_plan(raw)[0], core.Run(), 0)['groups']],
                         ['Уровень', 'Навыки', 'Ресурсы'])

    def test_what_does_not_fit_is_said(self):
        # раздел steps в файле билда, записанном раньше (проверки шага), не читается вовсе
        build = dict(BUILD, routeId='other', steps={'nowhere': {'gate': {'title': 'Перед боссом', 'goals': ['bow']}}})
        raw, notes = planfiles.compose(MANIFEST, ROUTE, build)
        self.assertEqual(notes, ['Билд написан для маршрута «other», а подключён «campaign»'])
        self.assertEqual(['gate' in s for s in raw['steps']], [False, False])
        self.assertTrue(planfiles.is_manifest(MANIFEST))
        self.assertFalse(planfiles.is_manifest({'steps': [], 'goals': []}))
        self.assertFalse(planfiles.is_manifest({'route': 'r.json'}))


class FilesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / 'Client.txt').write_text(LOG, encoding='utf-8')
        self.write('plan.json', MANIFEST)
        self.write('routes/campaign.json', ROUTE)
        self.write('builds/hero.json', BUILD)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, data, when=None):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(data if isinstance(data, str) else json.dumps(data, ensure_ascii=False), encoding='utf-8')
        if when:
            os.utime(path, (when, when))
        return path

    def start(self):
        app = server.App(self.root / 'Client.txt', self.root / 'plan.json', self.root / 'runs')
        with app.cond:
            app.load_plan()
            app.poll_log(initial=True)
            app.attach_run()
        return app

    def test_server_reads_the_parts_and_notices_changes(self):
        app = self.start()
        v = app.view()
        self.assertEqual((v['planError'], v['planProblems'], v['planTitle'], v['step']['id']), (None, [], 'Герой', 'clearfell'))
        self.assertEqual([c['target'] for c in v['cards']], [660, 330])     # цель по времени — из шага маршрута
        self.assertFalse(app.load_plan())                       # ничего не менялось
        # правка билда подхватывается без перезапуска — как раньше правка единственного файла
        self.write('builds/hero.json', dict(BUILD, title='Другой герой'), when=4102444800)
        self.assertTrue(app.load_plan())
        self.assertEqual(app.view()['planTitle'], 'Другой герой')
        # то же с маршрутом; название фильтра шага, когда игра его не знает, — то, что шаг записал
        self.assertEqual(app.plan['filters']['f1']['name'], 'Первый')
        renamed = [dict(ROUTE['steps'][0], filterName='Другое имя')] + ROUTE['steps'][1:]
        self.write('routes/campaign.json', dict(ROUTE, steps=renamed), when=4102444801)
        self.assertTrue(app.load_plan())
        self.assertEqual(app.plan['filters']['f1']['name'], 'Другое имя')
        self.write('routes/campaign.json', dict(ROUTE, steps=ROUTE['steps'][:1]), when=4102444802)
        self.assertTrue(app.load_plan())
        self.assertEqual(app.view()['planProblems'][0], 'Цель «bow»: нет шага «clearfell»')

    def test_old_table_of_contents_with_the_personal_part(self):
        """Оглавление прежнего вида называет личное: файл личного не читается, а план говорит, что строку пора убрать."""
        self.write('plan.json', dict(MANIFEST, profile='profiles/main.json'))
        self.write('profiles/main.json', {'version': 2, 'steps': {'riverbank': {'filter': 'other'}}})
        app = self.start()
        self.assertEqual(app.plan_problems, ['Личное больше не читается: фильтр — поле шага маршрута. Уберите из plan.json строку «profile»'])
        self.assertEqual(app.plan['steps'][0]['filter'], 'f1')

    def test_broken_part_keeps_the_previous_plan(self):
        app = self.start()
        self.write('builds/hero.json', '{ это не json', when=4102444800)
        self.assertTrue(app.load_plan())
        self.assertIn('файл билда не читается', app.plan_error)
        self.assertEqual(app.view()['planTitle'], 'Герой')        # показан прежний план
        (self.root / 'builds' / 'hero.json').unlink()
        self.assertTrue(app.load_plan())
        self.assertIn('нет файла билда: builds/hero.json', app.plan_error)
        # файл вернулся — план снова читается
        self.write('builds/hero.json', BUILD, when=4102444900)
        self.assertTrue(app.load_plan())
        self.assertIsNone(app.plan_error)
        # часть вне папки плана не читается
        self.write('plan.json', dict(MANIFEST, build='../hero.json'), when=4102444901)
        self.assertTrue(app.load_plan())
        self.assertIn('лежит вне папки плана', app.plan_error)

    def test_single_file_plan_still_works(self):
        raw, _ = planfiles.compose(MANIFEST, ROUTE, BUILD)
        self.write('plan.json', raw, when=4102444800)
        app = self.start()
        self.assertEqual((app.plan_error, app.view()['planTitle'], app._plan_parts), (None, 'Герой', []))


if __name__ == '__main__':
    unittest.main()
