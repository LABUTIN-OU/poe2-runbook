# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Sergei Labutin
# Additional terms under GPL-3.0 section 7: see NOTICE.md
"""Правка маршрута со страницы: проверка присланных шагов и целей шага, запись в файл маршрута.
Запуск: python -m unittest planner.test_routeplan"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import routeplan  # noqa: E402

# Файл маршрута в том виде, в каком его пишут в проекте: шаги — обычной раскладкой, цель шага — одна строка.
ROUTE = '''{
  "version": 2,
  "id": "r",
  "steps": [
    {
      "id": "riverbank",
      "zone": "G1_1",
      "name": "Берег реки"
    },
    {
      "id": "clearfell",
      "zone": "G1_2",
      "also": [
        "G1_3"
      ],
      "name": "Клирфелл",
      "touch": [
        {
          "zone": "G1_4",
          "name": "Грельвуд"
        }
      ]
    },
    {
      "id": "after",
      "event": "ascend",
      "name": "После вознесения"
    },
    {
      "id": "maps",
      "level": 65,
      "name": "Карты 1–5"
    }
  ],
  "goals": [
    {"id": "hero-7", "group": "Уровень", "title": "7 уровень героя", "reach": 7, "need": "clearfell"},
    {"id": "boss-miller", "kind": "boss", "must": true, "title": "Раздувшийся мельник (The Bloated Miller)", "need": "riverbank"},
    {"id": "boss-beira", "kind": "boss", "group": "Награды", "title": "Бейра (Beira): +10% к холоду", "reward": "base_cold_damage_resistance_%", "gives": {"res_cold": 10}, "heard": ["CarrionCroneRotten2", "UnaNewAfterSinging"], "need": "clearfell"}
  ]
}
'''
CAT = {'areas': {'G1_1': {'name': 'The Riverbank', 'act': 1, 'level': 1, 'town': False, 'waypoint': False},
                 'G1_town': {'name': 'Clearfell Encampment', 'act': 1, 'level': 15, 'town': True, 'waypoint': True},
                 'G1_2': {'name': 'Clearfell', 'act': 1, 'level': 2, 'town': False, 'waypoint': True},
                 'G2_1': {'name': 'Vastiri Outskirts', 'act': 2, 'level': 16, 'town': False, 'waypoint': True}}}


def route():
    return json.loads(ROUTE)


class DescribeTest(unittest.TestCase):
    def test_page_gets_the_route_and_the_zones_to_pick(self):
        d = routeplan.describe(CAT, route(), {'G1_town': 'Лагерь Клирфелл', 'G1_2': 'Клирфелл из лога'})
        # своего названия у маршрута нет: странице идут шаги и их цели
        self.assertEqual((sorted(d['route']), [s['id'] for s in d['route']['steps']], [g['id'] for g in d['route']['goals']]),
                         (['goals', 'steps'], ['riverbank', 'clearfell', 'after', 'maps'], ['hero-7', 'boss-miller', 'boss-beira']))
        self.assertEqual(d['events'], ['ascend', 'ascend2', 'ascend3', 'ascend4'])
        # зоны — по порядку актов и уровня; название на языке игрока — из лога, иначе по шагу маршрута с этой
        # зоной; у зоны, где герой не был и которой в маршруте нет, его нет
        self.assertEqual([(a['code'], a['name'], a['own'], a['waypoint']) for a in d['areas']], [
            ('G1_1', 'The Riverbank', 'Берег реки', False), ('G1_2', 'Clearfell', 'Клирфелл из лога', True),
            ('G1_town', 'Clearfell Encampment', 'Лагерь Клирфелл', True), ('G2_1', 'Vastiri Outskirts', None, True)])


class StepCheckTest(unittest.TestCase):
    def check(self, steps):
        problems = []
        return routeplan.check_steps(steps, route(), problems), problems

    def test_untouched_steps_pass_and_edits_are_cleaned(self):
        steps = route()['steps']
        out, problems = self.check(steps)
        self.assertEqual((problems, out, [list(s) for s in out]), ([], route()['steps'], [list(s) for s in route()['steps']]))
        steps[0].update(name='  Берег  ', notes=['  Убить мельника ', ' '], touch=[{'zone': ' G1_2 ', 'name': ''}, {'zone': '', 'name': 'пусто'}])
        steps[1].update(also=[], touch=[], notes=['Зачистить, все сундуки'])
        steps.insert(2, {'id': 'vastiri', 'name': 'Окраины Вастири', 'notes': [], 'zone': 'G2_1', 'far': True})
        out, problems = self.check(steps)
        self.assertEqual(problems, [])
        # строки без пробелов по краям, пустые не пишутся; точка без названия называется кодом зоны;
        # у изменённого и нового шага поля в привычном порядке. Задач (notes) у шага нет: страница прежнего вида их
        # присылает — в запись они не идут, и отказа нет
        self.assertEqual(out[0], {'id': 'riverbank', 'zone': 'G1_1', 'name': 'Берег', 'touch': [{'zone': 'G1_2'}]})
        self.assertEqual(list(out[0]), ['id', 'zone', 'name', 'touch'])
        self.assertEqual(out[1], {'id': 'clearfell', 'zone': 'G1_2', 'name': 'Клирфелл'})
        self.assertEqual((out[2], list(out[2])), ({'id': 'vastiri', 'zone': 'G2_1', 'name': 'Окраины Вастири', 'far': True},
                                                 ['id', 'zone', 'name', 'far']))

    def test_what_is_refused(self):
        def bad(**kw):
            steps = route()['steps']
            steps[0] = dict(steps[0], **kw)
            return self.check(steps)[1]

        self.assertEqual(self.check([])[1], ['шаги маршрута: нужен непустой список не длиннее 400'])
        self.assertEqual(bad(id='Берег'), ['шаг: id — латинские буквы, цифры, дефис'])
        self.assertEqual(bad(id='clearfell'), ['шаг «clearfell» прислан дважды'])
        self.assertEqual(bad(name=' '), ['шаг «riverbank»: нужно название не длиннее 80 знаков'])
        self.assertEqual(bad(zone='G1 1'), ['шаг «Берег реки»: зона — её код из лога игры (G1_2)',
                                            'шаг «Берег реки»: шаг узнаётся по одному из трёх — зона, событие или уровень зоны'])
        self.assertEqual(bad(event='boss'), ['шаг «Берег реки»: событие бывает только ascend, ascend2, ascend3, ascend4',
                                             ])
        self.assertEqual(bad(event='ascend'), ['шаг «Берег реки»: шаг узнаётся по одному из трёх — зона, событие или уровень зоны'])
        self.assertEqual(bad(zone='', level=65), [])
        self.assertEqual(bad(zone=''), ['шаг «Берег реки»: шаг узнаётся по одному из трёх — зона, событие или уровень зоны'])
        self.assertEqual(bad(level=0), ['шаг «Берег реки»: уровень зоны — целое от 1 до 100'])
        self.assertEqual(bad(notes='убить'), [])          # задач у шага нет: что прислано, не читается
        self.assertEqual(bad(touch=[{'zone': 'G1_2', 'name': 'x', 'at': 1}]), ['шаг «Берег реки»: точки перехода — список зон (до 12), каждая — её код из лога игры'])
        self.assertEqual(bad(zone='', event='ascend', also=['G1_3']), ['шаг «Берег реки»: «ещё зоны» бывают только у шага с зоной'])
        self.assertEqual(bad(target='5 минут'), ['шаг «Берег реки»: цель по времени — вида 5:30 или 1:05:00'])
        self.assertEqual(bad(target='5:75'), ['шаг «Берег реки»: цель по времени — вида 5:30 или 1:05:00'])
        self.assertEqual(bad(kit='djinn'), ['шаг «Берег реки»: поле «kit» со страницы не правится'])

    def test_time_target_is_a_field_of_the_step(self):
        steps = route()['steps']
        steps[0]['target'] = ' 11:00 '
        steps[1]['target'] = '1:05:00'
        steps[2]['target'] = ''                    # пустая цель в запись не идёт
        out, problems = self.check(steps)
        self.assertEqual(problems, [])
        self.assertEqual((out[0]['target'], out[1]['target'], 'target' in out[2]), ('11:00', '1:05:00', False))
        # в записи шага цель стоит за названием, перед точками перехода
        self.assertEqual(list(out[0]), ['id', 'zone', 'name', 'target'])
        self.assertEqual(list(out[1]), ['id', 'zone', 'also', 'name', 'target', 'touch'])
        # записанная цель, которую не трогали, проходит как есть; стёртая уходит из записи
        was = dict(route(), steps=out)
        problems = []
        again = routeplan.check_steps([dict(s) for s in out], was, problems)
        self.assertEqual((problems, again, [list(s) for s in again]), ([], out, [list(s) for s in out]))
        cleared = routeplan.check_steps([dict(out[0], target='')] + [dict(s) for s in out[1:]], was, problems)
        self.assertEqual((problems, 'target' in cleared[0], cleared[1]['target']), ([], False, '1:05:00'))


class GoalCheckTest(unittest.TestCase):
    def check(self, goals, taken=()):
        problems = []
        return routeplan.check_goals(goals, route(), {'riverbank', 'clearfell', 'after', 'maps'}, set(taken), problems), problems

    def test_untouched_goals_pass_and_edits_are_cleaned(self):
        goals = route()['goals']
        out, problems = self.check(goals)
        self.assertEqual((problems, out, [list(g) for g in out]), ([], route()['goals'], [list(g) for g in route()['goals']]))
        goals[1].update(must=False, final=True, heard=' ClearfellGuardMillerDeathRandom ', group='')
        goals[2].update(heard=['CarrionCroneRotten2', '  '], need='riverbank')
        goals.append({'id': 'points-una', 'group': 'Награды', 'title': ' Хижина Уны (Una\'s Hut): +2 очка ', 'reward': 'passive_points', 'need': 'clearfell'})
        out, problems = self.check(goals)
        self.assertEqual(problems, [])
        # снятая пометка и пустая строка в запись не идут; одна реплика — строкой, несколько — списком;
        # поле, которого страница не правит (gives), на месте
        self.assertEqual(out[1], {'id': 'boss-miller', 'kind': 'boss', 'title': 'Раздувшийся мельник (The Bloated Miller)', 'need': 'riverbank',
                                  'final': True, 'heard': 'ClearfellGuardMillerDeathRandom'})
        self.assertEqual((out[2]['heard'], out[2]['need'], out[2]['gives']), ('CarrionCroneRotten2', 'riverbank', {'res_cold': 10}))
        self.assertEqual(out[3], {'id': 'points-una', 'group': 'Награды', 'title': "Хижина Уны (Una's Hut): +2 очка", 'reward': 'passive_points', 'need': 'clearfell'})

    def test_what_is_refused(self):
        def bad(**kw):
            goals = route()['goals']
            goals[1] = dict(goals[1], **kw)
            return self.check(goals, taken={'skill-bomb'})[1]

        self.assertEqual(self.check('все')[1], ['цели шага: нужен список не длиннее 600'])
        self.assertEqual(bad(id='Босс'), ['цель шага: id — латинские буквы, цифры, дефис'])
        self.assertEqual(bad(id='hero-7'), ['цель шага «hero-7»: такой id уже есть'])
        self.assertEqual(bad(id='skill-bomb'), ['цель шага «skill-bomb»: такой id уже есть у цели билда'])
        self.assertEqual(bad(title=''), ['цель шага «boss-miller»: нужно название'])
        self.assertEqual(bad(need='nowhere'), ['цель шага «Раздувшийся мельник (The Bloated Miller)»: шага «nowhere» в маршруте нет',
                                               'цель шага «Раздувшийся мельник (The Bloated Miller)»: не назван её шаг'])
        self.assertEqual(bad(kind='skill'), ['цель шага «Раздувшийся мельник (The Bloated Miller)»: цель шага — босс, задание или награда'])
        self.assertEqual(bad(reach=0), ['цель шага «Раздувшийся мельник (The Bloated Miller)»: уровень героя — целое от 1 до 100'])
        self.assertEqual(bad(must='да'), ['цель шага «Раздувшийся мельник (The Bloated Miller)»: пометка must — да или нет'])
        self.assertEqual(bad(heard=7), ['цель шага «Раздувшийся мельник (The Bloated Miller)»: реплики — строки не длиннее 200 знаков'])
        self.assertEqual(bad(probe={'Class': 'Boots'}), ['цель шага «Раздувшийся мельник (The Bloated Miller)»: поле «probe» со страницы не правится'])
        # ни заметки, ни подсказки у цели шага нет: со страницы их не записать
        self.assertEqual(bad(note='тактика'), ['цель шага «Раздувшийся мельник (The Bloated Miller)»: поле «note» со страницы не правится'])
        self.assertEqual(bad(hint='у моста'), ['цель шага «Раздувшийся мельник (The Bloated Miller)»: поле «hint» со страницы не правится'])
        problems = []
        self.assertEqual((routeplan.check({'steps': []}, route(), (), problems), problems), ({}, ['маршрут: нужны шаги и их цели']))


class FileTest(unittest.TestCase):
    def test_only_what_changed_is_rewritten(self):
        r = route()
        self.assertEqual(routeplan.render(ROUTE, {'steps': r['steps'], 'goals': r['goals']}), ROUTE)      # знак в знак
        r['steps'][0]['target'] = '11:00'
        r['steps'].insert(2, {'id': 'vastiri', 'zone': 'G2_1', 'name': 'Окраины Вастири'})
        r['goals'][0]['need'] = 'vastiri'
        out = routeplan.render(ROUTE, {'steps': r['steps'], 'goals': r['goals']})
        self.assertEqual((json.loads(out), list(json.loads(out))), (r, ['version', 'id', 'steps', 'goals']))
        self.assertIn('      "name": "Берег реки",\n      "target": "11:00"\n    },\n', out)
        self.assertIn('    {\n      "id": "vastiri",\n      "zone": "G2_1",\n      "name": "Окраины Вастири"\n    },\n', out)
        # цель шага, которая не менялась, осталась своей строкой; изменённая переписана
        self.assertIn('    {"id": "boss-miller", "kind": "boss", "must": true, "title": "Раздувшийся мельник (The Bloated Miller)", "need": "riverbank"},\n', out)
        self.assertIn('    {"id": "hero-7", "group": "Уровень", "title": "7 уровень героя", "reach": 7, "need": "vastiri"},\n', out)
        self.assertEqual(routeplan.render(ROUTE.replace('\n', '\r\n'), {'steps': r['steps'], 'goals': r['goals']}).replace('\r\n', '\n'), out)
        with self.assertRaises(ValueError):
            routeplan.splice_steps(ROUTE.replace('  "steps": [', '  "steps":  ['), r['steps'])

    def test_removed_steps_are_named(self):
        self.assertEqual(routeplan.gone_steps(route(), [{'id': 'riverbank'}, {'id': 'new'}]), {'clearfell', 'after', 'maps'})

    def test_step_filter_comes_from_the_game(self):
        """Фильтр шага — поле шага маршрута: выбрать можно фильтр, который есть в игре; его название шаг записывает
        из игры (filterName), а не со страницы. Записанный раньше фильтр, которого в игре нет, проходит как есть."""
        old = {'steps': [{'id': 'a', 'zone': 'G1_1', 'name': 'А', 'filter': 'Old0ne11', 'filterName': 'Прежний'}]}
        game = {'Ab3dE6gH': 'Сайт', 'Cd4eF7hI': 'Другой'}
        problems = []
        out = routeplan.check_steps([
            {'id': 'a', 'zone': 'G1_1', 'name': 'А', 'filter': 'Old0ne11', 'filterName': 'Прежний'},
            {'id': 'b', 'zone': 'G1_2', 'name': 'Б', 'filter': 'Ab3dE6gH', 'filterName': 'как угодно', 'target': '5:00'},
            {'id': 'c', 'zone': 'G1_3', 'name': 'В', 'filter': 'none', 'filterName': 'лишнее'},
            {'id': 'd', 'zone': 'G1_4', 'name': 'Г', 'filter': ''},
        ], old, problems, game)
        self.assertEqual(problems, [])
        self.assertEqual(out[0], old['steps'][0])                              # фильтра нет в игре — записанное остаётся
        self.assertEqual(out[1], {'id': 'b', 'zone': 'G1_2', 'name': 'Б', 'target': '5:00', 'filter': 'Ab3dE6gH',
                                  'filterName': 'Сайт'})
        self.assertEqual(list(out[1]), ['id', 'zone', 'name', 'target', 'filter', 'filterName'])
        self.assertEqual((out[2]['filter'], 'filterName' in out[2], 'filter' in out[3]), ('none', False, False))
        # новый фильтр, которого в игре нет, не выбрать; фильтр в игре переименовали — название шага следом
        problems = []
        routeplan.check_steps([{'id': 'a', 'zone': 'G1_1', 'name': 'А', 'filter': 'Zz9yY8xX'}], old, problems, game)
        self.assertEqual(problems, ['шаг «А»: фильтра «Zz9yY8xX» нет в игре'])
        out = routeplan.check_steps([dict(old['steps'][0])], old, [], {'Old0ne11': 'Новое имя'})
        self.assertEqual(out[0]['filterName'], 'Новое имя')

    def test_the_real_route_is_written_back_exactly(self):
        """Шаги и цели шага настоящего маршрута воспроизводятся знак в знак — иначе первая же правка
        со страницы переписала бы файл не так, как он написан."""
        import planlib
        plans = planlib.project_plans(Path(HERE).parent)
        if not plans:
            self.skipTest('нет файла маршрута')
        # боссы, задания и награды в маршруте — ссылки на справочник игры: проверка сверяет их с ним
        import landmarks
        marks, _, bad = landmarks.load(Path(HERE).parent / 'knowledge' / 'landmarks.json')
        self.assertEqual(bad, [])
        for path, parts in plans:
            with self.subTest(plan=path.parent.name):
                text = parts['route'].read_bytes().decode('utf-8-sig')
                data = json.loads(text)
                problems = []
                clean = routeplan.check({'steps': data['steps'], 'goals': data['goals']}, data, (), problems, marks=marks)
                self.assertEqual(problems, [])
                self.assertEqual(routeplan.render(text, clean), text)
                # и каждая ссылка маршрута находит свою запись
                self.assertEqual(landmarks.resolve(data['goals'], marks)[1], [])


BUILD = '''{
  "version": 2,
  "title": "Учебный билд",
  "slots": [
    {"id": "weapon", "name": "Оружие", "classes": ["Sceptre"]}
  ],
  "stages": [
    {"id": "start", "name": "Кампания", "stats": ["life"]}
  ],
  "goals": [
    {"id": "sceptre", "slot": "weapon", "title": "Гремящий скипетр (Rattling Sceptre)", "need": "clearfell"}
  ]
}
'''


class ServerTest(unittest.TestCase):
    """Маршрут через программу: план из трёх частей, каталог настоящий."""

    def setUp(self):
        import server
        import test_treeplan
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        (root / 'Client.txt').write_text(test_treeplan.LOG, encoding='utf-8')
        (root / 'plan.json').write_text(json.dumps({'version': 2, 'route': 'route.json', 'build': 'build.json'}), encoding='utf-8')
        self.route, self.build = root / 'route.json', root / 'build.json'
        self.route.write_bytes(ROUTE.replace('\n', '\r\n').encode('utf-8'))
        self.build.write_bytes(BUILD.replace('\n', '\r\n').encode('utf-8'))
        self.app = server.App(root / 'Client.txt', root / 'plan.json', root / 'runs', backup_dir=root / 'backup')
        with self.app.cond:
            self.app.load_plan()
            self.app.poll_log(initial=True)
            self.app.attach_run()

    def tearDown(self):
        self.tmp.cleanup()

    def test_route_is_read_edited_and_written(self):
        if not self.app.catalog or not self.app.catalog.get('stats'):
            self.skipTest('каталог данных игры не собран')
        self.assertEqual(self.app.plan_problems, [])
        d = self.app.build_view()
        self.assertEqual(([s['id'] for s in d['route']['steps']], len(d['route']['goals']), d['problems']),
                         (['riverbank', 'clearfell', 'after', 'maps'], 3, []))
        # лог учебного забега называл «Берег реки»: зона подписана на языке игрока
        self.assertEqual(next(a['own'] for a in d['areas'] if a['code'] == 'G1_1'), 'Берег реки')
        r = d['route']
        r['steps'][0]['notes'] = ['Убить мельника']                          # страница прежнего вида: задача не пишется
        r['steps'][0]['target'] = '11:00'                                     # цель по времени — поле самого шага
        r['steps'].insert(1, {'id': 'grelwood', 'zone': 'G1_4', 'name': 'Грельвуд'})
        r['goals'].append({'id': 'boss-druid', 'kind': 'boss', 'title': 'Сгнивший друид (The Rotten Druid)', 'need': 'grelwood'})
        r['steps'] = [s for s in r['steps'] if s['id'] != 'maps']             # шаг убран
        r['steps'][-1]['filter'] = 'none'                                     # с шага фильтр выключают: поле самого шага
        ok, problems = self.app.save_build({'route': {'steps': r['steps'], 'goals': r['goals']}})
        self.assertEqual((ok, problems), (True, []))
        text = self.route.read_bytes().decode('utf-8')
        data = json.loads(text)
        self.assertEqual(([s['id'] for s in data['steps']], 'notes' in data['steps'][0], data['goals'][-1]['id']),
                         (['riverbank', 'grelwood', 'clearfell', 'after'], False, 'boss-druid'))
        self.assertNotIn('\n', text.replace('\r\n', ''))                       # переводы строк файла сохранены
        self.assertEqual((data['steps'][0]['target'], list(data['steps'][0])), ('11:00', ['id', 'zone', 'name', 'target']))
        self.assertIn('      "name": "Берег реки",\r\n      "target": "11:00"\r\n    },', text)
        self.assertEqual(data['steps'][-1]['filter'], 'none')
        self.assertEqual(json.loads(self.build.read_text(encoding='utf-8')), json.loads(BUILD))       # билд не тронут
        backups = sorted(p.name.split('-')[0] for p in (Path(self.tmp.name) / 'backup').iterdir())
        self.assertEqual(backups, ['route.route'])
        # план перечитан: страница маршрута видит новый шаг с боссом
        view = self.app.view()
        self.assertEqual(self.app.plan_problems, [])
        self.assertEqual(([c['id'] for c in view['cards']], [b['id'] for b in view['cards'][1]['bosses']], 'notes' in view['cards'][0]),
                         (['riverbank', 'grelwood', 'clearfell', 'after'], ['boss-druid'], False))
        self.assertEqual([c['target'] for c in view['cards']], [660, None, None, None])      # страница забега видит цель шага
        # на шаг ссылается билд (срок цели, проверка шага): убрать его нельзя — отказ, файлы целы
        saved = self.route.read_bytes()
        d = self.app.build_view()
        ok, problems = self.app.save_build({'route': {'steps': [s for s in d['route']['steps'] if s['id'] != 'clearfell'],
                                                      'goals': [g for g in d['route']['goals'] if g.get('need') != 'clearfell']}})
        self.assertFalse(ok)
        self.assertIn('Цель «sceptre»: нет шага «clearfell»', problems)
        self.assertEqual(self.route.read_bytes(), saved)
        # маршрут и билд можно прислать вместе: цель билда получает срок на только что добавленном шаге
        goals = d['goals']
        goals[0]['need'] = 'vastiri'
        steps = d['route']['steps'] + [{'id': 'vastiri', 'zone': 'G2_1', 'name': 'Окраины Вастири', 'notes': []}]
        ok, problems = self.app.save_build({'route': {'steps': steps, 'goals': d['route']['goals']}, 'goals': goals})
        self.assertEqual((ok, problems), (True, []))
        self.assertEqual(({g['id']: g['need'] for g in self.app.plan['goals'] if g['id'] == 'sceptre'}, self.app.plan_problems),
                         ({'sceptre': 'vastiri'}, []))
        # цель шага не может взять id цели билда
        d = self.app.build_view()
        ok, problems = self.app.save_build({'route': {'steps': d['route']['steps'],
                                                      'goals': d['route']['goals'] + [{'id': 'sceptre', 'title': 'Чужой id', 'need': 'riverbank'}]}})
        self.assertEqual((ok, problems), (False, ['цель шага «sceptre»: такой id уже есть у цели билда']))
        self.assertEqual(self.app.save_build({}), (False, ['нечего записывать: нет ни одного раздела плана']))


def filter_file(name, version='0.5.5h'):
    """Файл фильтра из аккаунта, как его кладёт игра: шапка, потом правила."""
    return ('#Online Item Filter\n#name:%s\n#version:%s\n#realm:poe2\n#errors:\n#hash:0123456789abcdef\n'
            '#filterVersion:0.10.4a\n#filterType:Normal\n#lastUpdate:2026-11-20T04:29:29Z\n#monthTimeStamp:1523\n'
            '#=====\n# NeverSink\nShow\n    Rarity Unique\n' % (name, version))


class FilterServerTest(unittest.TestCase):
    """Фильтр шага через программу: план из двух частей, папка фильтров игры — своя."""

    def setUp(self):
        import server
        import test_treeplan
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        (root / 'Client.txt').write_text(test_treeplan.LOG, encoding='utf-8')
        (root / 'plan.json').write_text(json.dumps({'version': 2, 'route': 'route.json', 'build': 'build.json'}), encoding='utf-8')
        self.route, self.build = root / 'route.json', root / 'build.json'
        # с шага «Карты» включают фильтр с сайта; название шаг записал из игры автора
        text = ROUTE.replace('      "name": "Карты 1–5"\n', '      "name": "Карты 1–5",\n      "filter": "abc12345",\n      "filterName": "Строгий"\n')
        self.route.write_bytes(text.replace('\n', '\r\n').encode('utf-8'))
        self.build.write_bytes(BUILD.replace('\n', '\r\n').encode('utf-8'))
        # папка фильтров игры: два фильтра из аккаунта и чужой файл без шапки
        self.games = root / 'OnlineFilters'
        self.games.mkdir()
        (self.games / 'abc12345').write_text(filter_file('Strict Campaign'), encoding='utf-8')
        (self.games / 'xyz78901').write_text(filter_file('Maps ES'), encoding='utf-8')
        (self.games / 'junk').write_text('Show\n', encoding='utf-8')
        # архив версий: удалённый из аккаунта фильтр знают по его копии
        self.archive = root / 'archive'
        self.archive.mkdir()
        (self.archive / 'gone1234_20261101-000000_abcdef12.filter').write_text(filter_file('Old One'), encoding='utf-8')
        self.app = server.App(root / 'Client.txt', root / 'plan.json', root / 'runs', filters_dir=self.games,
                              archive_dir=self.archive, backup_dir=root / 'backup')
        with self.app.cond:
            self.app.load_plan()
            self.app.poll_log(initial=True)
            self.app.attach_run()

    def tearDown(self):
        self.tmp.cleanup()

    def test_filter_names_come_from_the_game(self):
        """Название фильтра — из шапки файла, которую пишет игра; удалённый из аккаунта — по копии в архиве; фильтра
        шага нет в игре — по названию, которое записал шаг."""
        import server
        self.assertEqual(server.filter_header(self.games / 'abc12345')['name'], 'Strict Campaign')
        self.assertEqual(server.filter_header(self.games / 'junk'), {})
        self.assertEqual(server.filter_header(self.games / 'nope'), {})
        # файл без шапки — тоже фильтр игры (id — имя файла), только без названия
        self.assertEqual(self.app.filter_names(), {'xyz78901': {'name': 'Maps ES', 'inGame': True},
                                                   'abc12345': {'name': 'Strict Campaign', 'inGame': True},
                                                   'junk': {'name': '', 'inGame': True},
                                                   'gone1234': {'name': 'Old One', 'inGame': False}})
        # в игре — по названию, без названия — после, потом прежние
        self.assertEqual(list(self.app.filter_names()), ['xyz78901', 'abc12345', 'junk', 'gone1234'])
        # фильтр в игре называет игра, а не шаг
        self.assertEqual(self.app.plan['filters']['abc12345'], {'name': 'Strict Campaign', 'inGame': True})
        self.assertEqual(self.app.plan_problems, [])
        # фильтр переименовали на сайте, и игра его скачала заново: план перечитывается и называет его по-новому
        (self.games / 'abc12345').write_text(filter_file('Strict Campaign 2'), encoding='utf-8')
        os.utime(self.games / 'abc12345', (1, 1))
        with self.app.cond:
            self.assertTrue(self.app.load_plan())
        self.assertEqual(self.app.plan['filters']['abc12345']['name'], 'Strict Campaign 2')
        # фильтра шага в игре нет (игрок плана не подписан): название — записанное шагом, и замечание к плану словами
        (self.games / 'abc12345').unlink()
        with self.app.cond:
            self.app.load_plan()
        self.assertEqual(self.app.plan['filters']['abc12345'], {'name': 'Строгий', 'inGame': False})
        self.assertEqual(self.app.plan_problems, ['Шаг «Карты 1–5»: фильтра «Строгий» нет в игре'])
        v = self.app.view()
        self.assertEqual([c['filter']['missing'] for c in v['cards'] if c['id'] == 'maps'], [True])

    def test_step_filter_is_picked_and_written(self):
        if not self.app.catalog or not self.app.catalog.get('stats'):
            self.skipTest('каталог данных игры не собран')
        d = self.app.build_view()
        self.assertNotIn('profile', d)
        self.assertEqual(d['gameFilters'], [{'id': 'xyz78901', 'name': 'Maps ES', 'inGame': True},
                                            {'id': 'abc12345', 'name': 'Strict Campaign', 'inGame': True},
                                            {'id': 'junk', 'name': '', 'inGame': True},
                                            {'id': 'gone1234', 'name': 'Old One', 'inGame': False}])
        r = d['route']
        clear = next(s for s in r['steps'] if s['id'] == 'clearfell')
        clear['filter'] = 'xyz78901'
        clear['filterName'] = 'со страницы'                                 # название пишет программа, а не страница
        ok, problems = self.app.save_build({'route': {'steps': r['steps'], 'goals': r['goals']}})
        self.assertEqual((ok, problems), (True, []))
        text = self.route.read_bytes().decode('utf-8')
        data = json.loads(text)
        clear = next(s for s in data['steps'] if s['id'] == 'clearfell')
        self.assertEqual((clear['filter'], clear['filterName']), ('xyz78901', 'Maps ES'))
        self.assertEqual(list(clear), ['id', 'zone', 'also', 'name', 'filter', 'filterName', 'touch'])
        # шаг, которого правка не коснулась, записан как был, но с названием фильтра из игры
        maps = next(s for s in data['steps'] if s['id'] == 'maps')
        self.assertEqual((maps['filter'], maps['filterName']), ('abc12345', 'Strict Campaign'))
        self.assertNotIn('\n', text.replace('\r\n', ''))                       # переводы строк файла сохранены
        self.assertEqual(self.app.plan['filters']['xyz78901']['name'], 'Maps ES')
        # фильтр, которого в игре нет (удалённый тоже), выбрать нельзя; файл цел
        saved = self.route.read_bytes()
        d = self.app.build_view()
        r = d['route']
        next(s for s in r['steps'] if s['id'] == 'after')['filter'] = 'gone1234'
        ok, problems = self.app.save_build({'route': {'steps': r['steps'], 'goals': r['goals']}})
        self.assertEqual((ok, problems, self.route.read_bytes() == saved), (False, ['шаг «После вознесения»: фильтра «gone1234» нет в игре'], True))
        # страница прежнего вида присылает личное — отказ со словами, что делать
        ok, problems = self.app.save_build({'profile': {'steps': {}}})
        self.assertEqual((ok, problems), (False, ['личное больше не правится: фильтр — поле шага маршрута. Обновите страницу редактора']))


if __name__ == '__main__':
    unittest.main()
