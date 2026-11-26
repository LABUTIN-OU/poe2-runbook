# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Sergei Labutin
# Additional terms under GPL-3.0 section 7: see NOTICE.md
"""Библиотека планов: несколько планов в программе, герой и его план, присланный план и копия.

Запуск: python -m unittest planner.test_planlib
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import planlib  # noqa: E402
import server  # noqa: E402

ROUTE = {
    'version': 2, 'id': 'campaign',
    'steps': [{'id': 'riverbank', 'zone': 'G1_1', 'name': 'Берег реки', 'notes': []},
              {'id': 'clearfell', 'zone': 'G1_2', 'name': 'Клирфелл', 'notes': []}],
    'goals': [{'id': 'hero-3', 'group': 'Уровень', 'title': '3 уровень героя', 'reach': 3, 'need': 'clearfell'}],
}


def build(title, cls='Sorceress', goal='bomb'):
    return {'version': 2, 'title': title, 'routeId': 'campaign', 'hero': {'class': cls},
            'slots': [{'id': 'weapon', 'name': 'Оружие', 'wear': [{'classes': ['Wand']}]}],
            'goals': [{'id': goal, 'kind': 'skill', 'group': 'Навыки', 'title': 'Бомба', 'need': 'clearfell'}]}


def text(data):
    """Файл части плана — как их пишет программа: раздел на строку, у списка — запись на строку."""
    dump = lambda x: json.dumps(x, ensure_ascii=False)     # noqa: E731
    rows = []
    for k, v in data.items():
        if isinstance(v, list) and v:
            rows.append('  %s: [\n%s\n  ]' % (dump(k), ',\n'.join('    ' + dump(x) for x in v)))
        else:
            rows.append('  %s: %s' % (dump(k), dump(v)))
    return '{\n' + ',\n'.join(rows) + '\n}\n'


def ln(t, line):
    return '2026/11/11 %s 1 a [INFO Client 1] %s\n' % (t, line)


def area(t, level, code, name):
    return ('2026/11/11 %s 1 a [DEBUG Client 1] Generating level %d area "%s" with seed 1\n' % (t, level, code)
            + ln(t, '[SCENE] Set Source [%s]' % name))


CHAR_SCREEN = '[SCENE] Set Source [(unknown)]'


class Lib(unittest.TestCase):
    """Временная папка проекта: plans/ с планами, runs/, лог."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.plans = self.root / 'plans'
        self.log = self.root / 'Client.txt'
        self.log.write_text(area('20:07:03', 1, 'G1_1', 'Берег реки') + area('20:10:55', 2, 'G1_2', 'Клирфелл'),
                            encoding='utf-8')

    def tearDown(self):
        self.tmp.cleanup()

    def plan(self, pid, title, cls='Sorceress', goal='bomb', **manifest):
        folder = self.plans / pid
        folder.mkdir(parents=True)
        (folder / 'route.json').write_text(text(ROUTE), encoding='utf-8')
        (folder / 'build.json').write_text(text(build(title, cls, goal)), encoding='utf-8')
        planlib.write_manifest(folder / 'plan.json', dict({'version': 2, 'uid': pid + 'uid', 'route': 'route.json',
                                                            'build': 'build.json'}, **manifest))
        return folder

    def start(self, **more):
        lib = planlib.scan(self.plans)
        app = server.App(self.log, lib[0]['path'], self.root / 'runs', backup_dir=self.root / 'backup',
                         plans_dir=self.plans, **more)
        with app.cond:
            app.load_plan()
            app.poll_log(initial=True)
            app.use_plan(app.plan_of(app.run.id))
            app.attach_run()
        return app

    def more_log(self, *chunks):
        with open(self.log, 'a', encoding='utf-8') as f:
            f.write(''.join(chunks))


class LibraryFilesTest(Lib):
    def test_ids_from_titles(self):
        self.assertEqual([planlib.slug(t) for t in ('HC SSF · DoV', 'Ведьма на хаосе', '', '!!!')],
                         ['hc-ssf-dov', 'vedma-na-khaose', 'plan', 'plan'])
        self.plan('hc-ssf-dov', 'HC SSF · DoV')
        self.assertEqual(planlib.free_id(self.plans, 'HC SSF · DoV'), 'hc-ssf-dov-2')
        # id плана — только имя папки внутри библиотеки: выйти из неё нельзя
        self.assertIsNone(planlib.manifest_path(self.plans, '../runs'))
        self.assertIsNone(planlib.manifest_path(self.plans, 'A'))

    def test_old_single_plan_moves_into_the_library(self):
        """Прежний plan.json с частями в routes/ и builds/ переезжает в plans/<id>/: те же тексты, метка, порядок групп."""
        (self.root / 'routes').mkdir()
        (self.root / 'builds').mkdir()
        route_text, build_text = text(ROUTE), text(build('HC SSF · DoV'))
        (self.root / 'routes' / 'campaign.json').write_text(route_text, encoding='utf-8')
        (self.root / 'builds' / 'hero.json').write_text(build_text, encoding='utf-8')
        (self.root / 'plan.json').write_text(json.dumps({'version': 2, 'route': 'routes/campaign.json', 'build': 'builds/hero.json',
                                                         'groups': ['Навыки', 'Уровень']}, ensure_ascii=False), encoding='utf-8')
        pid = planlib.adopt(self.root / 'plan.json', self.plans)
        self.assertEqual(pid, 'hc-ssf-dov')
        folder = self.plans / pid
        self.assertEqual(((folder / 'route.json').read_text(encoding='utf-8'), (folder / 'build.json').read_text(encoding='utf-8')),
                         (route_text, build_text))
        m = json.loads((folder / 'plan.json').read_text(encoding='utf-8'))
        self.assertEqual((m['route'], m['build'], m['groups'], len(m['uid'])), ('route.json', 'build.json', ['Навыки', 'Уровень'], 12))
        # прежнего нет: ни оглавления, ни опустевших папок частей
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ['Client.txt', 'plans'])
        self.assertEqual([r['id'] for r in planlib.scan(self.plans)], ['hc-ssf-dov'])

    def test_copy_is_a_new_plan_of_its_own(self):
        self.plan('dov', 'HC SSF · DoV', received={'file': 'dov.plan.json', 'at': '2026-11-22 10:00:00'})
        pid = planlib.copy(self.plans, 'dov', 'Мой DoV')
        self.assertEqual(pid, 'moy-dov')
        info = planlib.summary(next(r for r in planlib.scan(self.plans) if r['id'] == pid))
        # своё название, своя метка, «копия плана …», и она уже не присланная
        self.assertEqual((info['title'], info['from'], 'received' in info), ('Мой DoV', {'uid': 'dovuid', 'title': 'HC SSF · DoV', 'take': 'all'}, False))
        self.assertNotEqual(info['uid'], 'dovuid')
        # маршрут — тот же текст; в билде изменилось только название
        self.assertEqual((self.plans / pid / 'route.json').read_text(encoding='utf-8'), text(ROUTE))
        self.assertEqual(json.loads((self.plans / pid / 'build.json').read_text(encoding='utf-8')), build('Мой DoV'))
        # без названия — «… · копия»
        pid = planlib.copy(self.plans, 'dov')
        self.assertEqual((pid, planlib.summary(next(r for r in planlib.scan(self.plans) if r['id'] == pid))['title']),
                         ('hc-ssf-dov-kopiya', 'HC SSF · DoV · копия'))

    def test_plan_file_goes_to_another_library_as_it_is(self):
        self.plan('dov', 'HC SSF · DoV', groups=['Навыки'])
        data = json.loads(json.dumps(planlib.bundle(self.plans, 'dov'), ensure_ascii=False))     # как через файл
        self.assertEqual((data['format'], data['version'], data['uid'], data['title']), (planlib.FORMAT, 1, 'dovuid', 'HC SSF · DoV'))
        other = self.root / 'other'
        pid = planlib.add(other, data, 'C:\\Users\\x\\Downloads\\dov.plan.json', now=0)
        self.assertEqual(pid, 'hc-ssf-dov')
        # части — те же тексты, что у автора; пометка «прислан» с именем файла без папки
        for name in ('route.json', 'build.json'):
            self.assertEqual((other / pid / name).read_text(encoding='utf-8'), (self.plans / 'dov' / name).read_text(encoding='utf-8'))
        info = planlib.summary(planlib.scan(other)[0])
        self.assertEqual((info['uid'], info['received']['file'], planlib.scan(other)[0]['manifest']['groups']),
                         ('dovuid', 'dov.plan.json', ['Навыки']))
        self.assertEqual(planlib.same(other, data)['id'], pid)

    def test_what_is_not_a_plan_file_is_refused(self):
        self.plan('dov', 'HC SSF · DoV')
        good = planlib.bundle(self.plans, 'dov')
        for bad, why in (({'format': 'x'}, 'это не файл плана'),
                         (dict(good, version=2), 'файл плана новее программы: обновите программу'),
                         (dict(good, build=''), 'в файле плана нет части «билд»'),
                         (dict(good, route='[1]'), 'часть «маршрут» файла плана записана не так')):
            with self.assertRaises(ValueError) as e:
                planlib.add(self.root / 'other', bad)
            self.assertEqual(str(e.exception), why)
        with self.assertRaises(ValueError) as e:
            planlib.parse_bundle(dict(good, build='{ не json'))
        self.assertTrue(str(e.exception).startswith('часть «билд» файла плана не читается'))
        self.assertFalse((self.root / 'other').exists())

    def test_new_version_of_a_received_plan_replaces_it(self):
        self.plan('dov', 'HC SSF · DoV', received={'file': 'a.plan.json', 'at': '2026-11-22 10:00:00'})
        data = dict(planlib.bundle(self.plans, 'dov'), build=text(build('HC SSF · DoV v2')))
        planlib.replace(self.plans, 'dov', data, 'b.plan.json', now=0, backup_dir=self.root / 'backup')
        info = planlib.summary(planlib.scan(self.plans)[0])
        self.assertEqual((info['id'], info['uid'], info['title'], info['received']['file']), ('dov', 'dovuid', 'HC SSF · DoV v2', 'b.plan.json'))
        self.assertEqual(len(list((self.root / 'backup').iterdir())), 2)        # прежние маршрут и билд
        # свой план присланным файлом не заменяется
        self.plan('mine', 'Мой')
        with self.assertRaises(ValueError):
            planlib.replace(self.plans, 'mine', data)

    def test_removed_plan_goes_to_the_trash_folder(self):
        self.plan('dov', 'HC SSF · DoV')
        dest = planlib.remove(self.plans, 'dov', self.root / 'backup' / 'removed', now=0)
        self.assertTrue((dest / 'plan.json').is_file())
        self.assertEqual(planlib.scan(self.plans), [])


class HeroPlanTest(Lib):
    def setUp(self):
        super().setUp()
        self.plan('dov', 'HC SSF · DoV')
        self.plan('witch', 'Ведьма', cls='Witch', goal='chaos')

    def test_every_hero_has_its_plan(self):
        app = self.start()
        a = app.run.id
        # первый герой без слова игрока — по первому плану библиотеки; планов два — его спрашивают, так ли это
        self.assertEqual((app.plan_of(a), app.view()['planTitle']), ('dov', 'HC SSF · DoV'))
        v = app.view()
        self.assertTrue(v['plans']['ask'])
        self.assertEqual([(p['id'], p['title'], p['cls'], p['heroes']) for p in v['plans']['list']],
                         [('dov', 'HC SSF · DoV', 'Sorceress', 1), ('witch', 'Ведьма', 'Witch', 0)])
        self.assertEqual((v['plans']['current'], v['runs'][0]['plan']), ('dov', 'dov'))
        # игрок говорит: этот герой идёт по «Ведьме» — страница и разбор лога идут по ней
        self.assertEqual(app.bind_plan('witch'), (True, []))
        v = app.view()
        self.assertEqual((v['planTitle'], v['plans']['current'], v['plans']['ask']), ('Ведьма', 'witch', False))
        self.assertEqual(json.loads((app.runs_dir / ('%s.json' % a)).read_text(encoding='utf-8'))['planId'], 'witch')
        self.assertEqual(app.bind_plan('nope')[0], False)
        # новый герой идёт по плану героя, которым играли до него, — и его спрашивают, так ли это
        self.more_log(ln('20:30:00', CHAR_SCREEN), area('20:31:00', 1, 'G1_1', 'Берег реки'))
        with app.cond:
            app.poll_log()
        b = app.run.id
        self.assertNotEqual(a, b)
        v = app.view()
        self.assertEqual((v['planTitle'], v['plans']['current'], v['plans']['ask']), ('Ведьма', 'witch', True))
        self.assertEqual(app.bind_plan('dov'), (True, []))
        v = app.view()
        self.assertEqual((v['planTitle'], v['plans']['ask']), ('HC SSF · DoV', False))
        saved = json.loads((app.runs_dir / 'plans.json').read_text(encoding='utf-8'))
        self.assertEqual([(r['run'], r['plan'], 'ask' in r) for r in saved], [(a, 'witch', False), (b, 'dov', False)])
        # прежний герой снова в игре: с ним возвращается и его план
        self.more_log(ln('21:00:00', CHAR_SCREEN), area('21:02:00', 2, 'G1_2', 'Клирфелл'))
        with app.cond:
            app.poll_log()
            self.assertTrue(app.switch_run(a))
        self.assertEqual((app.run.id, app.view()['planTitle']), (a, 'Ведьма'))
        # после перезапуска — то же самое: слова о планах лежат в runs/plans.json
        again = self.start()
        self.assertEqual({r['id']: r['plan'] for r in again.view()['runs']}, {a: 'witch', b: 'dov'})

    def test_plan_chosen_before_the_first_hero(self):
        """Героя ещё нет (лог не начинал забег): выбранный план — план первого героя; его не спрашивают, так ли это.
        Следующего нового героя спрашивают, как всегда."""
        self.log.write_text('', encoding='utf-8')
        app = self.start()
        self.assertEqual((app.run.id in app.runs, app.view()['plans']['current']), (False, 'dov'))
        self.assertEqual(app.bind_plan('witch'), (True, []))
        v = app.view()
        self.assertEqual((v['plans']['current'], v['planTitle'], v['plans']['inGame']), ('witch', 'Ведьма', False))
        saved = json.loads((app.runs_dir / 'plans.json').read_text(encoding='utf-8'))
        self.assertEqual([(r['run'], r['plan']) for r in saved], [('', 'witch')])
        # после перезапуска выбор тот же
        self.assertEqual(self.start().view()['plans']['current'], 'witch')
        # первый герой — по выбранному плану, без вопроса
        self.more_log(area('20:07:03', 1, 'G1_1', 'Берег реки'))
        with app.cond:
            app.poll_log()
        v = app.view()
        self.assertEqual((app.run.id in app.runs, v['plans']['current'], v['plans']['ask']), (True, 'witch', False))
        # следующий новый герой — по плану прежнего, но его спрашивают
        self.more_log(ln('20:30:00', CHAR_SCREEN), area('20:31:00', 1, 'G1_1', 'Берег реки'))
        with app.cond:
            app.poll_log()
        v = app.view()
        self.assertEqual((v['plans']['current'], v['plans']['ask']), ('witch', True))

    def test_hero_in_game(self):
        """Герой в игре — пока лог не сказал, что он вышел (экран персонажей): тогда смена плана на странице переспрашивает."""
        app = self.start()
        self.assertTrue(app.view()['plans']['inGame'])
        self.more_log(ln('20:20:00', CHAR_SCREEN))
        with app.cond:
            app.poll_log()
        self.assertFalse(app.view()['plans']['inGame'])
        self.more_log(area('20:21:00', 2, 'G1_2', 'Клирфелл'))
        with app.cond:
            app.poll_log()
        self.assertTrue(app.view()['plans']['inGame'])
        # выбор плана из шапки — и в игре: страница сама спрашивает, программа просто делает
        self.assertEqual(app.bind_plan('witch'), (True, []))
        self.assertEqual(app.view()['plans']['current'], 'witch')

    def test_one_plan_asks_nothing(self):
        app = self.start()
        app.remove_plan('witch')
        self.more_log(ln('20:30:00', CHAR_SCREEN), area('20:31:00', 1, 'G1_1', 'Берег реки'))
        with app.cond:
            app.poll_log()
        self.assertFalse(app.view()['plans']['ask'])

    def test_the_editor_edits_any_plan_without_touching_the_hero(self):
        app = self.start()
        mine = (self.plans / 'dov' / 'build.json').read_text(encoding='utf-8')
        with app.editing('witch'):
            d = app.build_view()
        self.assertEqual((d['planId'], d['buildTitle'], d['plans']['current'], d['heroSeen']), ('witch', 'Ведьма', 'dov', {}))
        with app.editing(''):
            self.assertEqual(app.build_view()['planId'], 'dov')
        res = app.save_plan('witch', {'title': 'Ведьма 2'})
        self.assertEqual((res['ok'], res['plan'], res.get('copied')), (True, 'witch', None))
        self.assertEqual(json.loads((self.plans / 'witch' / 'build.json').read_text(encoding='utf-8'))['title'], 'Ведьма 2')
        # план героя не тронут, программа снова смотрит на него
        self.assertEqual(((self.plans / 'dov' / 'build.json').read_text(encoding='utf-8'), app.book is app.active, app.view()['planTitle']),
                         (mine, True, 'HC SSF · DoV'))
        self.assertEqual([p['title'] for p in app.view()['plans']['list']], ['HC SSF · DoV', 'Ведьма 2'])
        # прежняя версия правленого плана — в его собственной папке копий
        self.assertEqual([p.name.split('-')[0] for p in (self.root / 'backup' / 'plans' / 'witch').iterdir()], ['build.build'])
        with self.assertRaises(KeyError):
            with app.editing('nope'):
                pass

    def test_received_plan_is_only_viewed(self):
        app = self.start()
        data = planlib.bundle(self.plans, 'witch')
        # свой же план вернулся файлом — отдельным планом, со своей меткой
        res = app.import_plan({'import': data, 'file': 'witch.plan.json'})
        self.assertEqual((res['ok'], res['plan'], res['title']), (True, 'vedma', 'Ведьма'))
        got = {p['id']: p for p in app.library()}
        self.assertNotEqual(got['vedma']['uid'], got['witch']['uid'])
        self.assertEqual(got['vedma']['received']['file'], 'witch.plan.json')
        # он же ещё раз — программа спрашивает: заменить или добавить отдельно
        again = app.import_plan({'import': dict(data, uid=got['vedma']['uid']), 'file': 'witch.plan.json'})
        self.assertEqual((again['ok'], again['same']['id']), (False, 'vedma'))
        self.assertTrue(app.import_plan({'import': dict(data, uid=got['vedma']['uid']), 'file': 'x.plan.json', 'replace': 'vedma'})['ok'])
        self.assertEqual(app.import_plan({'import': dict(data, uid=got['vedma']['uid']), 'separate': True})['plan'], 'vedma-2')
        # присланный план только для просмотра: правка не записывается, файл не тронут
        before = (self.plans / 'vedma' / 'build.json').read_text(encoding='utf-8')
        res = app.save_plan('vedma', {'title': 'Моя ведьма'})
        self.assertEqual((res['ok'], res['plan'], res['problems']),
                         (False, 'vedma', ['присланный план только для просмотра — чтобы его менять, сделайте свой план на его основе']))
        self.assertEqual((self.plans / 'vedma' / 'build.json').read_text(encoding='utf-8'), before)
        # свой план на его основе — «Новый план», план целиком: копия, уже своя и сразу выбранная (герой идёт по ней)
        res = app.new_plan({'title': 'Моя ведьма', 'base': 'vedma', 'take': 'all'})
        self.assertEqual(res, {'ok': True, 'plan': 'moya-vedma', 'problems': []})
        self.assertEqual((app.view()['plans']['current'], app.plan_of(app.run.id)), ('moya-vedma', 'moya-vedma'))
        mine = {p['id']: p for p in app.library()}['moya-vedma']
        self.assertEqual((mine['title'], mine['from']['take'], 'received' in mine), ('Моя ведьма', 'all', False))
        self.assertTrue(app.save_plan('moya-vedma', {'hero': {'class': 'Witch'}})['ok'])
        self.assertEqual(sorted(p['id'] for p in app.library()), ['dov', 'moya-vedma', 'vedma', 'vedma-2', 'witch'])
        # файл плана — в папку export рядом с библиотекой (браузер, который не скачивает файлы)
        res = app.save_plan_file('moya-vedma')
        self.assertEqual(json.loads(Path(res['path']).read_text(encoding='utf-8'))['format'], planlib.FORMAT)
        self.assertEqual(Path(res['path']), self.root / 'export' / 'moya-vedma.plan.json')
        # не файл плана — понятный отказ
        self.assertEqual(app.import_plan({'import': {'format': 'x'}}), {'ok': False, 'problems': ['план не добавлен: это не файл плана']})

    def test_new_plan_from_the_template_or_a_route(self):
        """«Новый план»: из шаблона кампании или из маршрута плана — билд пустой и правится со страницы как любой."""
        know = self.root / 'knowledge'
        know.mkdir()
        tpl = dict(ROUTE, goals=[])
        (know / 'campaign.json').write_text(text(tpl), encoding='utf-8')
        app = self.start(knowledge_dir=know)
        self.assertTrue(app.view()['plans']['template'])
        self.assertEqual(app.new_plan({'title': 'С нуля', 'base': 'template', 'take': 'route'}), {'ok': True, 'plan': 's-nulya', 'problems': []})
        self.assertEqual(app.view()['plans']['current'], 's-nulya')          # новый план сразу выбран
        folder = self.plans / 's-nulya'
        self.assertEqual((folder / 'route.json').read_text(encoding='utf-8'), text(tpl))
        self.assertEqual(json.loads((folder / 'build.json').read_text(encoding='utf-8')),
                         {'version': 2, 'title': 'С нуля', 'routeId': 'campaign', 'hero': {}, 'slots': [], 'stages': [], 'goals': []})
        info = {p['id']: p for p in app.library()}['s-nulya']
        self.assertEqual((info['from'], 'received' in info), ({'template': 'campaign'}, False))
        self.assertEqual(planlib.scan(self.plans)[[r['id'] for r in planlib.scan(self.plans)].index('s-nulya')]['manifest']['groups'],
                         planlib.TEMPLATE_GROUPS)
        # пустой билд правится со страницы как любой: название, герой, этап, слот, цель
        for body in ({'title': 'С нуля 2'}, {'hero': {'class': 'Witch'}}, {'stages': [{'id': 'start', 'name': 'Начало'}]},
                     {'slots': [{'id': 'helmet', 'name': 'Шлем', 'wear': [{'classes': ['Helmet']}]}]},
                     {'goals': [{'id': 'fireball', 'kind': 'skill', 'group': 'Навыки', 'title': 'Огненный шар', 'need': 'clearfell'}]}):
            self.assertEqual(app.save_plan('s-nulya', body)['ok'], True, body)
        self.assertEqual(json.loads((folder / 'build.json').read_text(encoding='utf-8'))['goals'][0]['id'], 'fireball')
        # только маршрут плана: маршрут — тот же текст, билд пустой, на основе — чьего маршрута
        self.assertEqual(app.new_plan({'title': 'Свой маршрут', 'base': 'dov', 'take': 'route'}),
                         {'ok': True, 'plan': 'svoy-marshrut', 'problems': []})
        self.assertEqual((self.plans / 'svoy-marshrut' / 'route.json').read_text(encoding='utf-8'), text(ROUTE))
        self.assertEqual(json.loads((self.plans / 'svoy-marshrut' / 'build.json').read_text(encoding='utf-8'))['goals'], [])
        self.assertEqual({p['id']: p for p in app.library()}['svoy-marshrut']['from'], {'uid': 'dovuid', 'title': 'HC SSF · DoV', 'take': 'route'})
        # что не так — понятный отказ, плана нет
        for req, why in (({'title': '', 'base': 'dov', 'take': 'all'}, 'у нового плана нет названия'),
                         ({'title': 'x', 'base': 'dov', 'take': 'half'}, 'непонятно, что взять: план целиком или только маршрут'),
                         ({'title': 'x', 'base': 'nope', 'take': 'all'}, 'плана «nope» нет')):
            self.assertEqual(app.new_plan(req), {'ok': False, 'problems': [why]})
        self.assertEqual(len(app.library()), 4)

    def test_route_only_drops_links_to_the_old_build(self):
        """Маршрут без билда: «даёт цель билда» (grantedBy) у цели шага уходит, остальное — знак в знак."""
        t = text(dict(ROUTE, goals=ROUTE['goals'] + [{'id': 'boss-x', 'need': 'clearfell', 'grantedBy': 'bomb'}]))
        out = planlib.route_only(t)
        self.assertEqual(json.loads(out), dict(ROUTE, goals=ROUTE['goals'] + [{'id': 'boss-x', 'need': 'clearfell'}]))
        self.assertEqual(out.split('"goals"')[0], t.split('"goals"')[0])
        self.assertEqual(planlib.route_only(text(ROUTE)), text(ROUTE))

    def test_the_real_template_makes_a_clean_plan(self):
        """Шаблон, который идёт с программой: маршрут проходит проверку, план с пустым билдом собирается без замечаний."""
        import core
        import landmarks
        import planfiles
        import routeplan
        path = Path(server.ROOT) / 'knowledge' / planlib.TEMPLATE
        if not path.is_file():
            self.skipTest('нет шаблона кампании')
        text_ = path.read_bytes().decode('utf-8')
        route = json.loads(text_)
        marks, _, bad = landmarks.load(path.with_name('landmarks.json'))
        problems = []
        clean = routeplan.check({'steps': route['steps'], 'goals': route['goals']}, route, (), problems, marks=marks)
        self.assertEqual((bad, problems), ([], []))
        self.assertEqual(routeplan.render(text_, clean), text_)
        # только то, что задаёт игра: ни времени, ни фильтров, ни задач; цели — ссылки на справочник без выбора автора
        # (вариант награды не выбран, уровней героя нет)
        self.assertFalse([s for s in route['steps'] if set(s) & {'target', 'filter', 'filterName'} or s.get('notes')])
        self.assertTrue(route['goals'] and all(set(g) <= {'id', 'need', 'ref'} for g in route['goals']))
        # план новичка: всё, что карта мира показывает в зонах кампании, — на шаге своей зоны; механика — на каждом шаге
        # зоны, где её показывает карта мира
        zones = {}
        for s in route['steps']:
            for z in ([s['zone']] if s.get('zone') else []) + (s.get('also') or []):
                zones.setdefault(z, s['id'])
        placed = {g['id'] for g in route['goals'] if 'ref' not in g}
        self.assertEqual([r['id'] for r in marks.values() if r.get('zone') in zones and r['id'] not in placed], [])
        spots = {(g['ref'], g['need']) for g in route['goals'] if 'ref' in g}
        self.assertEqual([(r['id'], z) for r in marks.values() for z in r.get('zones') or []
                          if z in zones and (r['id'], zones[z]) not in spots], [])
        # восхождений в игре четыре — и в плане новичка четыре: на испытаниях и на картах
        self.assertEqual(len([g for g in route['goals'] if (marks.get(g.get('ref')) or {}).get('kind') == 'ascension']), 4)
        raw, notes = planfiles.compose({'version': 2}, route, json.loads(planlib.empty_build('x', route['id'])), marks)
        plan, more = core.norm_plan(raw)
        self.assertEqual((notes, more), ([], []))

    def test_plan_of_a_living_hero_stays(self):
        app = self.start()
        ok, problems = app.remove_plan('dov')
        self.assertFalse(ok)
        self.assertTrue(problems[0].startswith('по этому плану идёт герой'))
        self.assertEqual(app.remove_plan('witch'), (True, []))
        self.assertEqual([p['id'] for p in app.library()], ['dov'])
        self.assertEqual(app.remove_plan('dov'), (False, ['это единственный план: убрать его нельзя']))
        self.assertTrue(any((self.root / 'backup' / 'removed').iterdir()))
        # копия плана — новый план в библиотеке
        self.assertEqual(app.copy_plan('dov', 'Второй'), ('vtoroy', []))
        self.assertEqual(app.copy_plan('nope')[0], None)


class SinglePlanTest(unittest.TestCase):
    """Программа с одним планом (--plan): библиотеки нет, а шапка всё равно знает план и его героя."""

    def test_no_library(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'Client.txt').write_text(area('20:07:03', 1, 'G1_1', 'Берег реки'), encoding='utf-8')
            (root / 'route.json').write_text(text(ROUTE), encoding='utf-8')
            (root / 'build.json').write_text(text(build('Один')), encoding='utf-8')
            (root / 'plan.json').write_text(json.dumps({'version': 2, 'route': 'route.json', 'build': 'build.json'}), encoding='utf-8')
            app = server.App(root / 'Client.txt', root / 'plan.json', root / 'runs')
            with app.cond:
                app.load_plan()
                app.poll_log(initial=True)
                app.attach_run()
            v = app.view()
            self.assertEqual((v['planTitle'], v['plans']['library'], [p['title'] for p in v['plans']['list']]), ('Один', False, ['Один']))
            self.assertFalse(app.bind_plan('x')[0])
            self.assertFalse(app.import_plan({'import': {}})['ok'])
            self.assertEqual(app.save_plan('', {'title': 'Один 2'})['ok'], True)
            self.assertFalse((root / 'runs' / 'plans.json').exists())


if __name__ == '__main__':
    unittest.main()
