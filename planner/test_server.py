# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Sergei Labutin
# Additional terms under GPL-3.0 section 7: see NOTICE.md
"""Проверка серверной части без сети: чтение лога, отметки, ручной шаг, сохранение.

Запуск: python -m unittest planner.test_server
"""
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import clip  # noqa: E402
import core  # noqa: E402
import gamedata  # noqa: E402
import server  # noqa: E402

LOG = '\n'.join([
    '2026/11/11 20:07:03 1 a [DEBUG Client 1] Generating level 1 area "G1_1" with seed 1',
    '2026/11/11 20:07:03 1 a [INFO Client 1] [SCENE] Set Source [Берег реки]',
    '2026/11/11 20:07:04 1 a [INFO Client 1] [Item Filter] Finished reloading online filter f1. Result: true. Hash: abc12345ff.',
    '2026/11/11 20:10:55 1 a [DEBUG Client 1] Generating level 2 area "G1_2" with seed 5',
    '2026/11/11 20:10:56 1 a [INFO Client 1] [SCENE] Set Source [Клирфелл]',
]) + '\n'



def ln(t, text):
    return '2026/11/11 %s 1 a [INFO Client 1] %s\n' % (t, text)


def area(t, level, code, name):
    return ('2026/11/11 %s 1 a [DEBUG Client 1] Generating level %d area "%s" with seed 1\n' % (t, level, code)
            + ln(t, '[SCENE] Set Source [%s]' % name))


def node(t, n):
    return ln(t, 'Successfully allocated passive skill id: AscendancySorceress3Small%d, name: Дух' % n)


CHAR_SCREEN = '[SCENE] Set Source [(unknown)]'

PLAN = {
    'slots': [{'id': 'weapon', 'name': 'Оружие'}],
    'steps': [{'id': 'riverbank', 'zone': 'G1_1', 'name': 'Берег реки', 'filter': 'f1', 'filterName': 'Первый'},
              {'id': 'clearfell', 'zone': 'G1_2', 'name': 'Клирфелл'}],
    'goals': [{'id': 'weapon-crossbow', 'slot': 'weapon', 'title': 'Арбалет', 'need': 'clearfell'},
              {'id': 'weapon-better', 'slot': 'weapon', 'title': 'Арбалет получше'}],
}


class AppTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.log = root / 'Client.txt'
        self.plan = root / 'plan.json'
        self.runs = root / 'runs'
        self.log.write_text(LOG, encoding='utf-8')
        self.plan.write_text(json.dumps(PLAN, ensure_ascii=False), encoding='utf-8')

    def tearDown(self):
        self.tmp.cleanup()

    def start(self, **more):
        app = server.App(self.log, self.plan, self.runs, **more)
        with app.cond:
            app.load_plan()
            app.poll_log(initial=True)
            app.attach_run()
        return app

    def test_log_of_another_client_language_gives_game_words(self):
        """Лог английского клиента называет зону и класс героя по-английски («Clearfell», «Sorceress»), а программа считает
        на своём языке: событие получает слово игры по-русски (из таблиц игры, по коду зоны и по слою языка), страница на
        другом языке — название из игры на своём языке. Раньше русская страница показывала «Clearfell», немецкая —
        тоже английское, а шаг плана «Клирфелл» оставался там русским."""
        self.log.write_text('\n'.join([
            '2026/11/11 20:07:03 1 a [DEBUG Client 1] Generating level 1 area "G1_1" with seed 1',
            '2026/11/11 20:07:03 1 a [INFO Client 1] [SCENE] Set Source [The Riverbank]',
            '2026/11/11 20:08:00 1 a [INFO Client 1] : Proba (Sorceress) is now level 2',
            '2026/11/11 20:10:55 1 a [DEBUG Client 1] Generating level 2 area "G1_2" with seed 5',
            '2026/11/11 20:10:56 1 a [INFO Client 1] [SCENE] Set Source [Clearfell]',
        ]) + '\n', encoding='utf-8')
        app = server.App(self.log, self.plan, self.runs)
        with app.cond:
            app.load_plan()
            app.set_client_lang('en')
            app.poll_log(initial=True)
            app.attach_run()
        langs = app.base_catalog['lang']
        v = app.view()
        self.assertEqual(v['zone']['name'], langs['ru']['areas']['G1_2'])
        self.assertEqual(app.zone_names(), {'G1_1': langs['ru']['areas']['G1_1'], 'G1_2': langs['ru']['areas']['G1_2']})
        self.assertEqual(v['hero']['cls'], langs['ru']['heroClasses']['Sorceress'])
        de = json.loads(app.view_json('de'))
        self.assertEqual(de['zone']['name'], langs['de']['areas']['G1_2'])
        self.assertEqual(de['step']['name'], langs['de']['areas']['G1_2'])          # шаг плана «Клирфелл»
        self.assertEqual(de['hero']['cls'], langs['de']['heroClasses']['Sorceress'])
        self.assertEqual(json.loads(app.view_json('en'))['hero']['cls'], 'Sorceress')

    def test_tree_nodes_on_the_russian_page_are_named_by_the_game(self):
        """Узел дерева на русской странице назван так, как его называет игра по-русски (таблицы игры, names-ru): и в
        состоянии страницы — какое бы имя ни записали план (узел, взятый на карте, — английским) и лог (клиент на другом
        языке), — и на карте (геометрия дерева получает here). Раньше там оставалось «Spell Critical Damage»."""
        app = self.start()
        ru = gamedata.names_pack(app.catalog, 'ru')
        if not ru:
            self.skipTest('каталог без русского слоя названий')
        want = ru['nodes']['spell_criticals4']
        v = {'tree': {'items': [{'id': 'spell_criticals4', 'name': 'Spell Critical Damage'}],
                      'goalNode': {'id': 'passive_keystone_chaos_inoculation', 'name': 'Узел-цель', 'goal': 'g'}},
             'atlas': {}}
        app._local_nodes(v, 'ru')
        self.assertEqual(v['tree']['items'][0]['name'], want)
        self.assertEqual(v['tree']['goalNode']['name'], 'Узел-цель')             # узел-цель — названием цели
        geo = json.loads(app.geo_file(app.tree_path, 'ru'))
        self.assertEqual(geo['here']['spell_criticals4'], want)
        self.assertNotIn('[', geo['here'].get('jewel_slot1979', ''))            # без разметки игры: «Гнездо для самоцвета»
        self.assertNotIn('here', json.loads(app.geo_file(app.tree_path, 'en')))

    def test_filter_page_is_opened_in_the_system_browser_on_request(self):
        """Во встроенном браузере отдельной вкладки нет: страницу фильтра на сайте игры по просьбе страницы открывает
        программа — в браузере системы. Адрес она собирает сама из кода фильтра."""
        app = self.start()
        opened = []
        app.opener = lambda url: opened.append(url) or True
        self.assertTrue(app.open_filter('Ab3dE6gH'))
        self.assertEqual(opened, ['https://pathofexile2.com/item-filter/Ab3dE6gH'])
        for bad in ('f1', '../evil/x', 'Ab3dE6gH?x=1', None, 7):           # не код фильтра с сайта — ничего не открыто
            self.assertFalse(app.open_filter(bad))
        self.assertEqual(len(opened), 1)
        app.opener = lambda url: False                      # браузера системы нет
        self.assertFalse(app.open_filter('Ab3dE6gH'))

        def broken(url):
            raise OSError('браузер не запустился')
        app.opener = broken
        self.assertFalse(app.open_filter('Ab3dE6gH'))

    def test_plan_stamp_follows_the_files(self):
        """Отпечаток файлов плана меняется вместе с ними: страница, открытая до чужой правки, присылает старый — её
        запись не принимают (server, POST /api/build), и правка другой вкладки не пропадает."""
        app = self.start()
        with app.cond:
            first = app.plan_stamp()
            self.assertEqual(first, app.plan_stamp())
            self.plan.write_text(json.dumps(dict(PLAN, title='другое'), ensure_ascii=False), encoding='utf-8')
            self.assertNotEqual(first, app.plan_stamp())

    def test_pause_is_kept_in_the_run_file(self):
        """«Пауза» / «Продолжить» записываются в файл забега и переживают перезапуск программы."""
        app = self.start()
        self.assertTrue(app.set_hold(True))
        self.assertTrue(app.view()['run']['held'])
        saved = json.loads(app._run_path().read_text(encoding='utf-8'))
        self.assertEqual([h['on'] for h in saved['hold']], [True])
        app.run.hold = []
        app.attach_run()
        self.assertEqual([h['on'] for h in app.run.hold], [True])
        self.assertTrue(app.set_hold(False))
        self.assertFalse(app.view()['run']['held'])

    def test_initial_scan_and_tail(self):
        app = self.start()
        v = app.view()
        self.assertEqual(v['zone']['name'], 'Клирфелл')
        self.assertEqual(v['step']['id'], 'clearfell')
        self.assertEqual(v['filter']['name'], 'Первый')
        self.assertTrue(v['log']['ok'])
        with open(self.log, 'a', encoding='utf-8') as f:
            f.write('2026/11/11 20:15:53 1 a [INFO Client 1] : Герой (Чародейка) достигает 3 уровня\n')
            f.write('2026/11/11 20:20:18 1 a [DEBUG Client 1] Generating level 15 area "G1_town" wi')
        self.assertTrue(app.poll_log())
        self.assertEqual(app.view()['hero']['level'], 3)
        self.assertEqual(app.view()['zone']['name'], 'Клирфелл')
        with open(self.log, 'a', encoding='utf-8') as f:
            f.write('th seed 1\n2026/11/11 20:20:18 1 a [INFO Client 1] [SCENE] Set Source [Лагерь Клирфелл]\n')
        self.assertTrue(app.poll_log())
        self.assertTrue(app.view()['zone']['town'])
        self.assertFalse(app.poll_log())

    def test_reading_that_fails_is_not_shown_as_reading(self):
        """Проход цикла чтения упал — страница видит это, а не «лог читается»; удался — снова чисто."""
        app = self.start()
        app.tick()
        self.assertEqual((app.view()['log']['ok'], app.view()['log']['error']), (True, None))
        poll = app.poll_log

        def broken(*a, **k):
            raise RuntimeError('диск не отвечает')

        app.poll_log = broken
        seen = app.version
        app.tick()
        app.tick()
        self.assertEqual(app.view()['log']['error'], 'RuntimeError: диск не отвечает')
        self.assertEqual(app.version, seen + 1)       # страницу будят один раз, а не каждые полсекунды
        app.poll_log = poll
        app.tick()
        self.assertEqual((app.view()['log']['error'], app.version), (None, seen + 2))
        # лог пропал — это своё состояние, не ошибка программы
        os.remove(self.log)
        app.tick()
        self.assertEqual((app.view()['log']['ok'], app.view()['log']['error']), (False, None))

    def test_page_is_told_which_pictures_exist(self):
        """Страница рисует картинку вещи, только если файл есть: список имён приходит в состоянии."""
        icons = Path(self.tmp.name) / 'icons'
        app = server.App(self.log, self.plan, self.runs, icons_dir=icons)
        with app.cond:
            app.load_plan()
            app.poll_log(initial=True)
            app.attach_run()
        self.assertEqual(app.view()['icons'], [])          # папки ещё нет
        icons.mkdir()
        (icons / 'type-helmet.webp').write_bytes(b'RIFF')
        (icons / 'item-sturdy-crossbow.webp').write_bytes(b'RIFF')
        (icons / 'notes.txt').write_text('не картинка', encoding='utf-8')
        (icons / 'Плохое имя.webp').write_bytes(b'RIFF')
        self.assertEqual(app.view()['icons'], ['item-sturdy-crossbow', 'type-helmet'])
        # новый файл замечается без перезапуска
        (icons / 'type-ring.webp').write_bytes(b'RIFF')
        self.assertEqual(app.view()['icons'], ['item-sturdy-crossbow', 'type-helmet', 'type-ring'])
        # картинки камней (их сотни — все камни игры) и баз в список не идут: страница берёт их по названию
        for name in ('skill-frost-bomb', 'sup-heft', 'art-ring01'):
            (icons / (name + '.webp')).write_bytes(b'RIFF')
        self.assertEqual(app.view()['icons'], ['item-sturdy-crossbow', 'type-helmet', 'type-ring'])

    def test_marks_and_validation(self):
        # Отметку снимает нажатие на неё же — отметка 0; отдельной отмены нет (их решение 2026-11-25), и снятие одной
        # цели не трогает соседнюю цепочку слота.
        app = self.start()
        self.assertTrue(app.mark('weapon-crossbow', 2))
        self.assertTrue(app.mark('weapon-better', 1))
        self.assertFalse(app.mark('nope', 2))
        self.assertFalse(app.mark('weapon-crossbow', 5))
        self.assertFalse(app.mark('weapon-crossbow', True))
        self.assertEqual(app.view()['slots'][0]['worn']['id'], 'weapon-crossbow')
        self.assertTrue(app.mark('weapon-crossbow', 0))
        self.assertEqual((app._status('weapon-crossbow'), app._status('weapon-better')), (0, 1))
        self.assertTrue(app.mark('weapon-better', 0))
        self.assertIsNone(app.view()['slots'][0]['worn'])
        self.assertEqual(app.run.marks[0]['zoneName'], 'Клирфелл')
        self.assertFalse(hasattr(app, 'undo_goals') or hasattr(app, 'undo_slot'))

    def test_skill_taken_off_is_kept_in_the_run(self):
        """Кнопка «Снять»: умение сняли на шаге «Снять». Игра снятие камня в лог не пишет — слово игрока хранится в забеге."""
        plan = dict(PLAN, goals=PLAN['goals'] + [
            {'id': 'skill-bomb', 'kind': 'skill', 'group': 'Навыки', 'title': 'Бомба', 'need': 'riverbank',
             'until': 'clearfell'},
            {'id': 'skill-mage', 'kind': 'skill', 'group': 'Навыки', 'title': 'Маг', 'need': 'riverbank'}])
        self.plan.write_text(json.dumps(plan, ensure_ascii=False), encoding='utf-8')
        app = self.start()
        self.assertTrue(app.mark('skill-bomb', 2))

        def row():
            return next((r for r in app.view()['holders'] if r['id'] == 'skill:skill-bomb'), None)

        self.assertTrue(row()['drop'])                    # лог кончается на Клирфелле — шаг «Снять» бомбы
        # снять так можно только то, что план снимает
        for bad in ({'goal': 'skill-mage'}, {'goal': 'weapon-crossbow'}, {'goal': 'nope'}, {'goal': 7},
                    {'goal': 'skill-bomb', 'on': 'yes'}):
            self.assertFalse(app.take_off(bad))
        self.assertTrue(app.take_off({'goal': 'skill-bomb'}))
        self.assertIsNone(row())
        saved = json.loads((self.runs / ('%s.json' % app.run.id)).read_text(encoding='utf-8'))
        self.assertEqual(list(saved['off']), ['skill-bomb'])
        # программу перезапустили: слово игрока на месте
        app = self.start()
        self.assertIsNone(row())
        # «вернуть» — нажатием на зелёную плашку «снято»
        self.assertTrue(app.take_off({'goal': 'skill-bomb', 'on': False}))
        self.assertTrue(row()['drop'])
        self.assertTrue(app.take_off({'goal': 'skill-bomb', 'on': False}))    # повтор ничего не меняет

    def test_level_is_set_from_a_list(self):
        # Уровень камня выбирают из списка: лесенка встаёт на выбранную ступень одним действием. Отметки
        # выше снимаются (иначе уровень не опустить), умение можно заодно взять или снять.
        plan = dict(PLAN, gemLevels=[0, 3, 6, 10, 14], goals=PLAN['goals'] + [
            {'id': 'skill-mage', 'kind': 'skill', 'group': 'Навыки', 'title': 'Маг', 'gemFrom': 2}])
        self.plan.write_text(json.dumps(plan, ensure_ascii=False), encoding='utf-8')
        app = self.start()
        chain = ['gem2-mage', 'gem3-mage', 'gem4-mage', 'gem5-mage']

        def level():
            row = next(r for r in app.view()['holders'] if r['id'] == 'skill:skill-mage')
            part = next(p for p in row['parts'] if p['key'] == 'level')
            return (row['base']['have'] or {}).get('id'), (part['have'] or {}).get('id')

        self.assertEqual([(x['id'], x['start']) for x in next(
            p for r in app.view()['holders'] if r['id'] == 'skill:skill-mage' for p in r['parts'])['rungs']],
            [('gem2-mage', True), ('gem3-mage', False), ('gem4-mage', False), ('gem5-mage', False)])
        # камня не было: выбрали уровень 4 — умение взято и стоит на 4
        self.assertTrue(app.set_rung({'chain': chain, 'to': 'gem4-mage', 'take': {'goal': 'skill-mage', 'status': 2}}))
        self.assertEqual(level(), ('skill-mage', 'gem4-mage'))
        # опустили до 3: отметка 4 снята
        self.assertTrue(app.set_rung({'chain': chain, 'to': 'gem3-mage'}))
        self.assertEqual((level(), app._status('gem4-mage')), (('skill-mage', 'gem3-mage'), 0))
        # стартовый уровень своей отметки не требует: снимаются все
        self.assertTrue(app.set_rung({'chain': chain, 'to': None}))
        self.assertEqual((level(), app._status('gem3-mage')), (('skill-mage', 'gem2-mage'), 0))
        # «нет» — камня больше нет
        self.assertTrue(app.set_rung({'chain': chain, 'to': 'gem5-mage'}))
        self.assertTrue(app.set_rung({'chain': chain, 'to': None, 'drop': 'skill-mage'}))
        self.assertEqual((level(), app._status('gem5-mage')), ((None, None), 0))
        # чужие и кривые запросы не проходят и ничего не меняют
        before = len(app.run.marks)
        for bad in ({'chain': chain, 'to': 'weapon-crossbow'}, {'chain': ['nope'], 'to': None}, {'chain': [], 'to': None},
                    {'chain': chain, 'to': None, 'drop': 'nope'}, {'chain': [{}], 'to': None},
                    {'chain': chain, 'to': 'gem3-mage', 'take': {'goal': 'skill-mage', 'status': 0}}):
            self.assertFalse(app.set_rung(bad))
        self.assertEqual(len(app.run.marks), before)

    def test_manual_move_and_persistence(self):
        app = self.start()
        self.assertTrue(app.move_to('riverbank'))
        self.assertFalse(app.move_to('nope'))
        self.assertTrue(app.mark('weapon-crossbow', 2))
        self.assertEqual(app.view()['step']['id'], 'riverbank')
        saved = json.loads((self.runs / '20261111-200703.json').read_text(encoding='utf-8'))
        self.assertEqual(len(saved['marks']), 1)
        self.assertEqual(len(saved['moves']), 1)
        self.assertEqual(saved['plan']['steps'][1]['id'], 'clearfell')
        again = self.start()
        self.assertEqual(again.view()['step']['id'], 'riverbank')
        self.assertEqual(again.view()['slots'][0]['worn']['id'], 'weapon-crossbow')

    def test_older_hero_played_again(self):
        # В логе нет имени вошедшего героя. Новый герой сам начинает новый забег, а к прежнему герою
        # возвращает слово игрока — и действует оно с экрана выбора персонажа, а не с момента нажатия.
        app = self.start()
        a = app.run.id
        self.assertTrue(app.mark('weapon-crossbow', 2))
        with open(self.log, 'a', encoding='utf-8') as f:
            f.write(ln('20:12:00', ': Герой (Чародейка) достигает 2 уровня')
                    + ln('20:13:00', ': Герой (Чародейка) достигает 3 уровня')
                    + node('20:14:00', 1) + node('20:14:01', 2)
                    + ln('20:30:00', CHAR_SCREEN) + area('20:31:00', 1, 'G1_1', 'Берег реки')
                    + ln('20:36:00', ': Новый (Чародейка) достигает 2 уровня'))
        self.assertTrue(app.poll_log())
        b = app.run.id
        self.assertEqual((a, b), ('20261111-200703', '20261111-203100'))
        self.assertTrue(app.mark('weapon-better', 1))
        # прежний герой снова в игре: экран персонажей, город, Клирфелл, новый уровень
        with open(self.log, 'a', encoding='utf-8') as f:
            f.write(ln('21:00:00', CHAR_SCREEN) + area('21:01:00', 15, 'G1_town', 'Лагерь Клирфелл')
                    + area('21:02:00', 2, 'G1_2', 'Клирфелл') + ln('21:03:00', ': Герой (Чародейка) достигает 4 уровня'))
        self.assertTrue(app.poll_log())
        v = app.view()
        # без слова игрока всё это легло в новый забег; страница замечает это по уровню не по порядку
        self.assertEqual((app.run.id, v['step']['id'], v['hero']['level']), (b, 'clearfell', 4))
        self.assertEqual((v['stranger']['level'], v['stranger']['after']), (4, 2))
        self.assertEqual([(r['id'], r['current'], r['level']) for r in v['runs']], [(a, False, 3), (b, True, 4)])
        # чистое время первого забега: от старта 20:07:03 до выхода к списку героев в 20:30
        self.assertEqual(v['runs'][0]['spent'], 22 * 60 + 57)
        self.assertFalse(app.switch_run('nope'))
        self.assertFalse(app.switch_run(b))
        version = app.version
        self.assertTrue(app.switch_run(a))
        self.assertGreater(app.version, version)
        v = app.view()
        self.assertEqual((app.run.id, v['hero']['level'], v['zone']['name']), (a, 4, 'Клирфелл'))
        self.assertIsNone(v['stranger'])
        self.assertEqual(v['slots'][0]['worn']['id'], 'weapon-crossbow')      # отметки своего забега на месте
        self.assertEqual([(r['id'], r['current'], r['level'], r['zone']) for r in v['runs']],
                         [(a, True, 4, 'Клирфелл'), (b, False, 2, 'Берег реки')])
        # у каждого забега имя его героя (по первой строке об уровне); оба героя живы — играть можно любым
        self.assertEqual([(r['name'], r['fate']) for r in v['runs']], [('Герой', 'alive'), ('Новый', 'alive')])
        # второй забег после переключения: его время — от старта 20:31 до экрана героев в 21:00
        self.assertEqual(v['runs'][1]['spent'], 29 * 60)
        # из журнала нового забега чужие события ушли, его отметки остались
        left = json.loads((self.runs / (b + '.json')).read_text(encoding='utf-8'))
        self.assertEqual([e['type'] for e in left['events']], ['filter', 'zone', 'level', 'leave'])
        self.assertEqual([m['goal'] for m in left['marks']], ['weapon-better'])
        # после перезапуска — то же самое, и счёт вознесений у героя свой: третий узел — второе вознесение
        again = self.start()
        self.assertEqual(again.run.id, a)
        self.assertEqual(again.view()['slots'][0]['worn']['id'], 'weapon-crossbow')
        with open(self.log, 'a', encoding='utf-8') as f:
            f.write(node('21:10:00', 3))
        self.assertTrue(again.poll_log())
        self.assertEqual([e['n'] for e in again.run.events if e['type'] == 'ascend'], [1, 2])
        # новый герой снова начинает свой забег сам; сессию, в которой он создан, другому забегу не отдать
        with open(self.log, 'a', encoding='utf-8') as f:
            f.write(ln('21:20:00', CHAR_SCREEN) + area('21:21:00', 1, 'G1_1', 'Берег реки'))
        self.assertTrue(again.poll_log())
        c = again.run.id
        self.assertEqual(c, '20261111-212100')
        self.assertFalse(again.switch_run(b))
        self.assertEqual(again.run.id, c)
        saved = json.loads((self.runs / 'switches.json').read_text(encoding='utf-8'))
        self.assertEqual([s['run'] for s in saved], [a])
        # Третий герой назван так же, как первый: значит, первого уже удалили (имя в игре занято, пока
        # герой есть). Потом третий гибнет — и чужая гибель в его забеге его не убивает.
        with open(self.log, 'a', encoding='utf-8') as f:
            f.write(ln('21:25:00', ': Герой (Чародейка) достигает 2 уровня')
                    + ln('21:26:00', ': Прохожий был повержен.'))
        self.assertTrue(again.poll_log())
        fate = lambda: [(r['id'], r['name'], r['fate']) for r in again.view()['runs']]
        self.assertEqual(fate(), [(a, 'Герой', 'gone'), (b, 'Новый', 'alive'), (c, 'Герой', 'alive')])
        with open(self.log, 'a', encoding='utf-8') as f:
            f.write(ln('21:30:00', ': Герой был повержен.') + ln('21:31:00', CHAR_SCREEN))
        self.assertTrue(again.poll_log())
        self.assertEqual(fate(), [(a, 'Герой', 'gone'), (b, 'Новый', 'alive'), (c, 'Герой', 'dead')])
        # погибшим и удалённым героем играть нельзя; живым — можно
        self.assertFalse(again.switch_run(a))
        self.assertTrue(again.switch_run(b))
        self.assertFalse(again.switch_run(c))
        # Героя, о котором лог молчит, называет ушедшим сам игрок: переключиться на него больше нельзя.
        # Текущему забегу такого не сказать; слово переживает перезапуск, и его можно взять обратно.
        self.assertTrue(again.switch_run(b) or again.run.id == b)
        self.assertFalse(again.mark_gone({'run': b, 'on': True}))                 # им сейчас играют
        self.assertFalse(again.mark_gone({'run': 'нет-такого', 'on': True}))
        with open(self.log, 'a', encoding='utf-8') as f:
            f.write(ln('21:40:00', CHAR_SCREEN) + area('21:41:00', 1, 'G1_1', 'Берег реки') + ln('21:42:00', ': Третий (Монах) достигает 2 уровня'))
        self.assertTrue(again.poll_log())
        d = again.run.id
        self.assertTrue(again.mark_gone({'run': b, 'on': True}))
        self.assertFalse(again.mark_gone({'run': b, 'on': True}))                 # уже сказано
        rows = {r['id']: r for r in again.view()['runs']}
        self.assertEqual((rows[b]['fate'], rows[b].get('byHand'), rows[d]['fate'], rows[a].get('byHand')), ('gone', True, 'alive', None))
        self.assertFalse(again.switch_run(b))
        self.assertEqual([x['run'] for x in json.loads((self.runs / 'gone.json').read_text(encoding='utf-8'))], [b])
        third = self.start()
        self.assertEqual({r['id']: r['fate'] for r in third.view()['runs']}[b], 'gone')
        self.assertTrue(third.mark_gone({'run': b, 'on': False}))
        self.assertEqual({r['id']: r['fate'] for r in third.view()['runs']}[b], 'alive')
        self.assertEqual(json.loads((self.runs / 'gone.json').read_text(encoding='utf-8')), [])

    def test_atlas_of_the_league_by_the_players_word(self):
        """Дерево атласа общее у героев одной лиги, а лигу лог не пишет: чей атлас продолжает герой, говорит
        игрок. Взятое до героя — клики того героя из того же лога, до его гибели: погибший в «Хардкоре» уходит
        в обычную лигу и кликает уже по её атласу. Вопрос — когда герой на картах, слова нет, а в логе есть атлас
        другого героя. Узлы, взятые до лога, игрок отмечает сам. Слова переживают перезапуск (runs/atlas.json)."""
        click = lambda t, nid: ln(t, 'Successfully allocated passive skill id: %s, name: %s' % (nid, nid))
        a1, b1, c1 = 'AtlasIncursionSmall1', 'AtlasIncursionNotable1', 'AtlasIncursionSmall18'   # путь от корня
        far = 'AtlasIncursionSmall10'                                                              # далеко от них
        app = self.start()
        first = app.run.id
        with open(self.log, 'a', encoding='utf-8') as f:
            f.write(ln('20:12:00', ': Первый (Чародейка) достигает 2 уровня')
                    + area('20:20:00', 65, 'G_Endgame_Town', 'Убежище') + click('20:21:00', a1) + click('20:21:05', b1)
                    + ln('20:25:00', ': Первый был повержен.') + click('20:26:00', far)      # после гибели — другая лига
                    + ln('20:30:00', CHAR_SCREEN) + area('20:31:00', 1, 'G1_1', 'Берег реки')
                    + ln('20:36:00', ': Второй (Чародейка) достигает 2 уровня'))
        self.assertTrue(app.poll_log())
        second = app.run.id
        a = app.view()['atlas']
        # в кампании не спрашивают: атласа у героя ещё нет
        self.assertEqual((a['open'], a['ask'], a['from'], a['offers']), (False, False, None, []))
        with open(self.log, 'a', encoding='utf-8') as f:
            f.write(area('20:40:00', 65, 'G_Endgame_Town', 'Убежище') + click('20:41:00', c1))
        self.assertTrue(app.poll_log())
        a = app.view()['atlas']
        # на картах, слова нет, в логе — атлас первого героя: спросить; свой клик идёт не от взятого
        self.assertEqual((a['ask'], a['from'], a['have'], [g['id'] for g in a['gaps']]), (True, None, [c1], [c1]))
        self.assertEqual([(o['run'], o['nodes'], o['on']) for o in a['offers']], [(first, 2, False)])
        self.assertFalse(app.atlas_answer({'run': second}))          # свой же забег
        self.assertFalse(app.atlas_answer({'run': 'нет-такого'}))
        self.assertTrue(app.atlas_answer({'run': first}))
        a = app.view()['atlas']
        self.assertEqual((a['ask'], a['from'], a['have'], a['before'], a['gaps']), (False, first, [a1, b1, c1], {a1: first, b1: first}, []))
        self.assertEqual([(o['run'], o['on']) for o in a['offers']], [(first, True)])
        # слово переживает перезапуск; файл забега первого героя для этого не нужен
        (self.runs / (first + '.json')).unlink()
        again = self.start()
        self.assertEqual((again.run.id, again.view()['atlas']['have']), (second, [a1, b1, c1]))
        # «новый атлас»: только свои клики — и проверка зовёт отметить взятое до лога
        self.assertTrue(again.atlas_answer({'run': ''}))
        a = again.view()['atlas']
        self.assertEqual((a['ask'], a['from'], a['have'], [g['id'] for g in a['gaps']]), (False, '', [c1], [c1]))
        self.assertFalse(again.atlas_mark({'node': 'AtlasIncursionStart_', 'on': True}))     # корень
        self.assertFalse(again.atlas_mark({'node': 'нет-такого', 'on': True}))
        self.assertFalse(again.atlas_mark({'node': b1, 'on': False}))                        # отметки нет
        self.assertTrue(again.atlas_mark({'node': b1, 'on': True}))
        self.assertFalse(again.atlas_mark({'node': b1, 'on': True}))                         # уже отмечен
        a = again.view()['atlas']
        self.assertEqual((a['have'], a['before'], a['gaps']), ([b1, c1], {b1: 'hand'}, []))
        self.assertEqual(json.loads((self.runs / 'atlas.json').read_text(encoding='utf-8')), {'from': {second: ''}, 'had': {second: [b1]}})
        self.assertTrue(again.atlas_mark({'node': b1, 'on': False}))
        self.assertEqual(again.view()['atlas']['before'], {})
        # Герой, чей атлас продолжили, видит и клики продолжившего: атлас один на двоих.
        self.assertTrue(again.atlas_answer({'run': first}))
        with open(self.log, 'a', encoding='utf-8') as f:
            f.write(ln('21:00:00', CHAR_SCREEN) + area('21:01:00', 1, 'G1_1', 'Берег реки')
                    + ln('21:02:00', ': Третий (Монах) достигает 2 уровня') + area('21:10:00', 65, 'G_Endgame_Town', 'Убежище'))
        self.assertTrue(again.poll_log())
        a = again.view()['atlas']
        # третий герой: в логе один атлас (первый и второй — один), он и предложен — по герою, кликавшему последним
        self.assertEqual((a['ask'], [(o['run'], o['nodes'], o['on']) for o in a['offers']]), (True, [(second, 3, False)]))

    def test_filter_check_and_archive(self):
        root = Path(self.tmp.name)
        fdir = root / 'OnlineFilters'
        fdir.mkdir()
        (fdir / 'f1').write_text('Hide\n\tRarity Magic\n\tClass == "Sceptres"\n\nShow\n\tRarity Magic\n',
                                 encoding='utf-8')
        ts = core.line_ts('2026/11/11 20:07:04 x')
        os.utime(fdir / 'f1', (ts, ts))
        plan = dict(PLAN, goals=PLAN['goals'] + [
            {'id': 'sc', 'group': 'Проверка', 'title': 'Скипетр',
             'probe': {'Class': 'Sceptres', 'BaseType': 'Rattling Sceptre', 'Rarity': 'Magic'}},
            {'id': 'cb', 'group': 'Проверка', 'title': 'Самострел',
             'probe': {'Class': 'Crossbows', 'BaseType': 'Makeshift Crossbow'}},
            {'id': 'plain', 'group': 'Проверка', 'title': 'Без проверки'},
            # база для карт: в зоне первого акта она не падает — фильтру нечего скрывать, проверки нет
            {'id': 'far', 'group': 'Проверка', 'title': 'Скипетр для карт',
             'probe': {'Class': 'Sceptres', 'BaseType': 'Omen Sceptre', 'Rarity': 'Magic', 'DropLevel': 65}}])
        self.plan.write_text(json.dumps(plan, ensure_ascii=False), encoding='utf-8')
        app = server.App(self.log, self.plan, self.runs, fdir, root / 'filters')
        with app.cond:
            app.load_plan()
            app.poll_log(initial=True)
            app.attach_run()
        v = app.view()
        goals = {g['id']: g for grp in v['groups'] for g in grp['goals']}
        self.assertEqual(goals['sc']['ground'], 'hide')
        self.assertEqual(goals['cb']['ground'], 'show')
        self.assertIsNone(goals['plain']['ground'])
        self.assertIsNone(goals['far']['ground'])
        self.assertNotIn('samples', v['filter'])            # своих образцов «что показывает» у программы больше нет
        ev = [e for e in app.run.events if e['type'] == 'filter'][-1]
        dst = app.archive_filter(ev)
        self.assertEqual(dst.name, 'f1_20261111-200704_abc12345.filter')
        self.assertTrue(dst.exists())
        # файл в папке игры уже переписан более поздней версией: копию под старым именем не делаем
        os.utime(fdir / 'f1', (ts + 900, ts + 900))
        self.assertIsNone(app.archive_filter(ev))

    def test_filter_loaded_before_maps_is_checked_for_maps(self):
        """Фильтр для карт загружают в убежище: его правила начинаются с уровня карт (AreaLevel >= 65), а последняя
        боевая зона — зона кампании 64-го уровня. Шаг «Выход на карты» своей боевой зоны не имеет: фильтр
        проверяется для этапа карт впереди — цель не «скрыта». В боевой зоне проверяется её уровень."""
        root = Path(self.tmp.name)
        fdir = root / 'OnlineFilters'
        fdir.mkdir()
        (fdir / 'f1').write_text('Show\n\tAreaLevel >= 65\n\tClass == "Sceptres"\n\tBaseType == "Rattling Sceptre"\n\n'
                                 'Hide\n\tClass == "Sceptres"\n', encoding='utf-8')
        plan = dict(PLAN, steps=PLAN['steps'] + [{'id': 'maps', 'zone': 'G_Endgame_Town', 'name': 'Выход на карты'},
                                                 {'id': 'maps-65', 'level': 65, 'name': 'Карты 1–5'}],
                    goals=PLAN['goals'] + [{'id': 'sc', 'group': 'Проверка', 'title': 'Скипетр', 'probe': {
                        'Class': 'Sceptres', 'BaseType': 'Rattling Sceptre', 'Rarity': 'Normal', 'DropLevel': 1}}])
        self.plan.write_text(json.dumps(plan, ensure_ascii=False), encoding='utf-8')

        def look(log):
            self.log.write_text(log, encoding='utf-8')
            app = server.App(self.log, self.plan, self.runs, fdir, root / 'filters')
            with app.cond:
                app.load_plan()
                app.poll_log(initial=True)
                app.attach_run()
            v = app.view()
            goals = {g['id']: g for grp in v['groups'] for g in grp['goals']}
            return v['step']['id'], v['filter']['level'], goals['sc']['ground']

        camp = LOG + area('21:00:00', 64, 'G1_2', 'Клирфелл')
        self.assertEqual(look(camp), ('clearfell', 64, 'hide'))
        hub = camp + area('21:10:00', 65, 'G_Endgame_Town', 'Убежище в зиккурате')
        self.assertEqual(look(hub), ('maps', 65, 'show'))
        self.assertEqual(look(hub + area('21:20:00', 67, 'MapAugury', 'Карта')), ('maps-65', 67, 'show'))

    def test_filter_sample_follows_the_goal_name(self):
        """Образец для проверки фильтра называет сама цель-предмет: её переименовали — проверяется новая база.
        От записанного образца остаются редкость и слово класса."""
        root = Path(self.tmp.name)
        fdir = root / 'OnlineFilters'
        fdir.mkdir()
        (fdir / 'f1').write_text('Hide\n\tClass == "Shields"\n\tBaseEnergyShield == 0\n\n'      # щит без энергощита скрыт
                                 'Show\n\tClass == "Shields"\n\tRarity Rare\n\tDropLevel <= 16\n\n'
                                 'Hide\n\tClass == "Shields"\n', encoding='utf-8')
        cat = gamedata.load(server.ROOT / 'catalog' / 'data')
        if not cat or not (cat.get('lang') or {}).get('ru'):
            self.skipTest('нет каталога данных игры')
        ru = cat['lang']['ru']['bases']
        hand = ['Shield', 'Focus']
        tower = gamedata.named_bases(cat, 'Ростовой щит (Tower Shield)', hand)[1]
        crest = gamedata.named_bases(cat, 'Гербовый щит (Crest Shield)', hand)[1]
        self.assertTrue(tower and crest and all('str_armour' in b['tags'] for b in tower) and all('str_int_armour' in b['tags'] for b in crest))
        late = next(b for b in sorted(crest, key=lambda b: b['level']) if b['level'] > 2 and ru.get(b['name']))
        focus = next(b for b in cat['bases'].values() if b['class'] == 'Focus' and b['level'] == 1 and ru.get(b['name'])
                     and 'runeforged' not in b['tags'])
        probe = {'Class': 'Shields', 'BaseType': 'Barricade Tower Shield', 'Rarity': 'Rare', 'DropLevel': 16}

        def ground(title, log=LOG, table=True, **more):
            goal = {k: v for k, v in dict({'id': 'shield', 'slot': 'offhand', 'title': title, 'probe': probe}, **more).items() if v is not None}
            plan = dict(PLAN, slots=PLAN['slots'] + [{'id': 'offhand', 'name': 'Вторая рука', 'wear': [{'classes': hand}]}],
                        goals=PLAN['goals'] + [goal])
            self.plan.write_text(json.dumps(plan, ensure_ascii=False), encoding='utf-8')
            self.log.write_text(log, encoding='utf-8')
            app = server.App(self.log, self.plan, self.runs, fdir, root / 'filters')
            with app.cond:
                app.load_plan()
                app.poll_log(initial=True)
                app.attach_run()
            if not table:       # каталог, собранный до таблицы классов игры
                app.base_catalog['lang']['en'].pop('classNames', None)
            self.assertFalse([x for x in app.plan_problems if 'rarity' in x])
            return app.filter_check().get('shield')

        # зона 2. Ростовой щит: здесь падает младшая база семейства, энергощита у неё нет — скрыт (по записанному
        # образцу проверки не было бы вовсе: его база падает с 16-й зоны)
        self.assertEqual(ground('Ростовой щит (Tower Shield)'), 'hide')
        # цель переименовали — образец записан прежний, а проверяется гербовый щит: энергощит есть, жёлтый — показан
        self.assertEqual(ground('Гербовый щит (Crest Shield)'), 'show')
        self.assertEqual(ground('Гербовый щит (Crest Shield): жёлтый'), 'show')
        # точная база, которая здесь ещё не падает, — проверять нечего; в своей зоне — проверяется она
        name = '%s (%s)' % (ru[late['name']], late['name'])
        self.assertIsNone(ground(name))
        deep = LOG + area('21:00:00', late['level'], 'G2_2', 'Тропа Изменницы')
        self.assertEqual(ground(name, log=deep), 'show' if late['level'] <= 16 else 'hide')
        # редкость — из записанного образца: синий гербовый щит не показан
        self.assertEqual(ground('Гербовый щит (Crest Shield)', probe=dict(probe, Rarity='Magic')), 'hide')
        # предмет другого класса (щит стал фокусом): класс называет таблица классов игры — фильтр о фокусах молчит,
        # предмет виден; без таблицы слово класса образца (о щитах) к фокусу не подходит — проверки нет
        self.assertEqual(gamedata.filter_class(cat, 'Focus'), 'Foci')
        self.assertEqual(ground('%s (%s)' % (ru[focus['name']], focus['name'])), 'show')
        self.assertIsNone(ground('%s (%s)' % (ru[focus['name']], focus['name']), table=False))
        # редкость — параметр самой цели: записанный образец ей не нужен, а его редкость она перекрывает
        self.assertEqual(ground('Гербовый щит (Crest Shield)', probe=None, rarity='Rare'), 'show')
        self.assertEqual(ground('Гербовый щит (Crest Shield)', probe=None, rarity='Magic'), 'hide')
        self.assertEqual(ground('Гербовый щит (Crest Shield)', rarity='Magic'), 'hide')
        self.assertEqual(ground('Ростовой щит (Tower Shield)', probe=None, rarity='Normal'), 'hide')
        # редкость не выбрана и образца нет — проверки нет; нет таблицы классов и образца — тоже
        self.assertIsNone(ground('Гербовый щит (Crest Shield)', probe=None))
        self.assertIsNone(ground('Гербовый щит (Crest Shield)', probe=None, rarity='Rare', table=False))
        self.assertEqual(ground('Гербовый щит (Crest Shield)', table=False), 'show')      # прежняя запись: её слово класса
        # название не из игры — образец как записан: его база с 16-й зоны, здесь не падает
        self.assertIsNone(ground('жёлтый щит'))
        self.assertEqual(ground('жёлтый щит', probe=dict(probe, DropLevel=1)), 'unsure')      # защита образца неизвестна

    def test_client_language_comes_from_game_config(self):
        # Лог английского клиента: язык назван в настройках игры, строки уровня читаются по английскому шаблону
        # игры; без строки language= язык узнаётся по самому логу.
        root = Path(self.tmp.name)
        cfg = root / 'poe2_production_Config.ini'
        cfg.write_text('[LANGUAGE]\nlanguage=en\n[UI]\nitem_filter=None\n', encoding='utf-8')
        with open(self.log, 'a', encoding='utf-8') as f:
            f.write(ln('20:40:00', ': Varra (Sorceress) is now level 9'))
        app = server.App(self.log, self.plan, self.runs, None, None, cfg)
        if not (app.base_catalog or {}).get('logs'):
            self.skipTest('в каталоге нет текстов лога')
        with app.cond:
            app.load_plan()
            app.load_config()
            app.poll_log(initial=True)
            app.attach_run()
        self.assertEqual(app.client_lang, 'en')
        self.assertEqual([e['level'] for e in app.run.events if e['type'] == 'level'], [9])
        cfg.write_text('[UI]\nitem_filter=None\n', encoding='utf-8')
        os.utime(cfg, (1, 4102444800))
        with app.cond:
            app.load_config()
        self.assertEqual(app.client_lang, 'en')
        # язык страницы, пока пользователь его не выбрал, — язык клиента игры, если на него есть перевод
        self.assertEqual(app.page_lang('auto'), 'en')
        app.client_lang = 'ru'
        self.assertEqual((app.page_lang('auto'), app.page_lang('en'), app.page_lang(None)), ('ru', 'en', 'ru'))
        app.client_lang = 'zh-Hant'                      # перевода страницы на этот язык нет — язык по умолчанию
        self.assertEqual(app.page_lang('auto'), 'en')
        app.client_lang = 'en'
        # реплики игры для поля редактора — на языке страницы
        self.assertEqual(app.speech_lines('ru')['AsalaA2DreadnoughtCutOffHisHead'], 'Сехема Асала: Дело сделано.')
        self.assertEqual(app.speech_lines('en')['AsalaA2DreadnoughtCutOffHisHead'], 'Sekhema Asala: It is done.')

    def test_tree_names_in_page_language(self):
        # карта деревьев на языке игры, кроме английского: к файлу геометрии добавлены названия узлов на этом языке (here) —
        # и по-русски тоже (в файле названия английские); по-английски — файл как есть
        app = server.App(self.log, self.plan, self.runs, None, None)
        with app.cond:
            app.load_plan()
        if not {'de', 'ru'} <= set((app.catalog or {}).get('namePacks') or ()):
            self.skipTest('в каталоге нет названий из игры на немецком и русском')
        path = Path(self.tmp.name) / 'tree.json'
        path.write_text(json.dumps({'nodes': [['fire37', 0, 0, 1, 'Volcanic Skin'], ['nope', 0, 0, 1, 'X']]}), encoding='utf-8')
        self.assertEqual(json.loads(app.geo_file(path, 'de'))['here'], {'fire37': 'Vulkanische Haut'})
        self.assertEqual(json.loads(app.geo_file(path, 'ru'))['here'], {'fire37': 'Вулканическая кожа'})
        self.assertEqual(app.geo_file(path, 'en'), path.read_bytes())

    def test_selected_filter_comes_from_game_config(self):
        root = Path(self.tmp.name)
        cfg = root / 'poe2_production_Config.ini'
        cfg.write_text('[UI]\nitem_filter_loaded_successfully=None\nitem_filter=None\n', encoding='utf-8')
        app = server.App(self.log, self.plan, self.runs, None, None, cfg)
        with app.cond:
            app.load_plan()
            self.assertTrue(app.load_config())
            app.poll_log(initial=True)
            app.attach_run()
        self.assertEqual(app.selected_filter, 'None')
        self.assertTrue(app.view()['filter']['off'])
        self.assertFalse(app.load_config())
        cfg.write_text('[UI]\nitem_filter=f1\n', encoding='utf-8')
        os.utime(cfg, (1, 4102444800))
        self.assertTrue(app.load_config())
        v = app.view()
        self.assertFalse(v['filter']['off'])
        self.assertEqual(v['filter']['name'], 'Первый')

    def test_no_filter_folder_is_fine(self):
        app = self.start()
        v = app.view()
        self.assertNotIn('samples', v['filter'])
        self.assertIsNone(v['slots'][0]['next']['ground'])

    def test_broken_plan_keeps_previous_one(self):
        app = self.start()
        self.plan.write_text('{ это не json', encoding='utf-8')
        os.utime(self.plan, (1, 4102444800))
        self.assertTrue(app.load_plan())
        self.assertIn('План не прочитан', app.plan_error)
        self.assertEqual(app.view()['step']['id'], 'clearfell')

    def copy_app(self, **more_args):
        """Программа с планом, где у доспеха есть слот, билд ведёт сопротивления, а к шагу «Клирфелл»
        на доспехе должно быть не меньше 30% сопротивления огню (цель по стату)."""
        # слотов с вещами пять: сопротивление бывает на каждом, поэтому оно обычный стат, а не редкий
        more = [{'id': s.lower(), 'name': s, 'classes': [s], 'gear': s} for s in ('Helmet', 'Gloves', 'Boots', 'Belt')]
        plan = dict(PLAN, slots=PLAN['slots'] + [{'id': 'body', 'name': 'Нательный доспех', 'classes': ['Нательные доспехи'],
                                                  'gear': 'Body Armour str_armour'}] + more,
                    stages=[{'id': 'start', 'name': 'Старт', 'stats': ['res_fire', 'res_cold', 'res_lightning', 'nope']}],
                    goals=PLAN['goals'] + [{'id': 'body-any', 'slot': 'body', 'title': 'любой', 'any': True},
                                           {'id': 'body-fire', 'slot': 'body', 'part': 'fire', 'label': 'сопротивление огню',
                                            'stat': 'res_fire', 'min': 30, 'title': 'от 30%', 'need': 'clearfell'},
                                           {'id': 'beira', 'title': 'Бейра: +10% к сопротивлению холоду',
                                            'gives': {'res_cold': 10}}])
        self.plan.write_text(json.dumps(plan, ensure_ascii=False), encoding='utf-8')
        return self.start(**more_args)

    def test_copied_item_is_shown_and_worn(self):
        """Игрок скопировал вещь в игре: страница показывает её против слота, но сама ничего не меняет.
        «Надеть» запоминает вещь и отмечает её базу в плане одним действием. Отмены нет: надел не то — копируют то, что
        надето на деле, и снова «Надеть» (их решение 2026-11-25)."""
        app = self.copy_app()
        self.assertIn('Этап «start»: стата «nope» нет в таблице статов данных игры', app.plan_problems)
        self.assertEqual([s['id'] for s in app.plan['stages'][0]['stats']], ['res_fire', 'res_cold', 'res_lightning'])
        v = app.view()
        self.assertEqual((v['copy'], v['wore'], v['clip']), (None, None, 'off'))
        # в буфере не вещь — ничего не запоминается
        self.assertFalse(app.take_copy('пароль от почты'))
        self.assertIsNone(app.copied)
        self.assertFalse(app.wear({'row': 'slot:body:'}))
        self.assertTrue(app.take_copy(ITEM, ts=100.0))
        c = app.view()['copy']
        row = c['rows'][0]
        # слот пуст: любая вещь лучше, и запомнить её можно
        self.assertEqual((c['at'], c['name'], c['pick'], row['verdict'], row['empty'], row['keep'], row['key']),
                         (100.0, 'Колючий спаситель', 'slot:body:', 'better', True, True, 'body/'))
        self.assertEqual((app._status('body-any'), app.run.worn), (0, {}))      # копия сама ничего не отметила
        self.assertFalse(app.wear({'row': 'slot:nowhere:'}))
        self.assertFalse(app.wear({'row': 7}))
        self.assertTrue(app.wear({'row': 'slot:body:'}))
        self.assertEqual((app._status('body-any'), app.run.worn['body/']['item']['name']), (2, 'Колючий спаситель'))
        v = app.view()
        self.assertIsNone(v['copy'])
        # окно страницы коротко говорит «НАДЕТО» — что и куда
        self.assertEqual((v['wore']['row'], v['wore']['name']), ('slot:body:', 'Колючий спаситель'))
        # отметка и вещь ушли в файл забега
        saved = json.loads((self.runs / (app.run.id + '.json')).read_text(encoding='utf-8'))
        self.assertEqual((saved['marks'][-1]['zoneName'], saved['worn']['body/']['item']['base']), ('Клирфелл', 'Полные латы'))
        # отмены нет: прежнего слова «вернуть» программа не знает — отметка и вещь на месте
        self.assertFalse(app.wear({'undo': True}))
        self.assertEqual((app._status('body-any'), sorted(app.run.worn)), (2, ['body/']))
        # «убрать» ничего не меняет
        self.assertTrue(app.take_copy(ITEM))
        before = len(app.run.marks)
        self.assertTrue(app.wear({'drop': True}))
        self.assertEqual((app.view()['copy'], len(app.run.marks), sorted(app.run.worn)), (None, before, ['body/']))
        # надел не то — снова «Надеть» тем, что надето на деле: слот помнит его, окно называет его
        self.assertTrue(app.take_copy(WINTER, ts=200.0) and app.wear({'row': 'slot:body:'}))
        self.assertEqual(app.run.worn['body/']['item']['name'], 'Зимний панцирь')
        self.assertTrue(app.take_copy(ITEM, ts=300.0) and app.wear({'row': 'slot:body:'}))
        self.assertEqual((app.run.worn['body/']['item']['name'], app.view()['wore']['name']), ('Колючий спаситель',) * 2)

    def test_worn_item_is_remembered_and_the_next_one_is_compared_by_stats(self):
        """«Надеть» запоминает вещь целиком. Следующая вещь для слота сравнивается с ней по статам билда.
        Память лежит в файле забега; «Надеть» другой вещи и «забыть» её правят; цель по стату отмечается по ней сама."""
        # в папке картинок лежит рисунок базы «Полные латы» (имя файла — из каталога данных игры)
        icons = Path(self.tmp.name) / 'icons'
        icons.mkdir()
        (icons / 'art-bodystr07.webp').write_bytes(b'RIFF\x04\x00\x00\x00WEBP')
        app = self.copy_app(icons_dir=icons)
        self.assertTrue(app.take_copy(ITEM, ts=100.0) and app.wear({'row': 'slot:body:'}))
        v = app.view()
        body = next(r for r in v['holders'] if r['id'] == 'slot:body:')
        self.assertEqual((body['wornKey'], body['item']['name'], body['item']['base']), ('body/', 'Колючий спаситель', 'Полные латы'))
        # надетая вещь нарисована рисунком своей базы; в общий список картинок страницы рисунки баз не идут
        self.assertEqual((body['item']['icon'], v['icons']), ('art-bodystr07', []))
        # и вещь из буфера — тоже: рисунок её базы идёт в шапку карточки сравнения
        self.assertTrue(app.take_copy(WINTER, ts=150.0))
        self.assertEqual(app.view()['copy']['icon'], 'art-bodystr07')
        os.remove(icons / 'art-bodystr07.webp')
        v = app.view()
        self.assertIsNone(next(r for r in v['holders'] if r['id'] == 'slot:body:')['item']['icon'])   # файла нет — имени нет
        self.assertIsNone(v['copy']['icon'])
        self.assertTrue(app.wear({'drop': True}))
        self.assertEqual([(ln['id'], ln['value'], ln['cls']) for ln in body['item']['lines']],
                         [('res_fire', 6, 'need'), ('res_lightning', 25, 'need')])
        # у вещи три аффикса из шести; броня билду не нужна, оба сопротивления — нужны
        self.assertEqual([(c['stat'], c['free']) for c in body['item']['bar']],
                         [('res_lightning', False), ('res_fire', False), (None, False)] + [(None, True)] * 3)
        # цель по стату: огня на доспехе 6 из 30 — не сделана, и нажатием её не отметить
        fire = next(p for p in body['parts'] if p['key'] == 'fire')
        self.assertEqual((fire['stat'], fire['have'], fire['next']['id'], fire['next']['locked']), ('res_fire', None, 'body-fire', True))
        # награда маршрута идёт в стат героя помимо вещей (её видно ниже, в сравнении: порог — от суммы героя)
        self.assertTrue(app.mark('beira', 2))
        # та же вещь — «надето»
        self.assertTrue(app.take_copy(ITEM, ts=200.0))
        self.assertEqual(app.view()['copy']['rows'][0]['verdict'], 'worn')
        # другая вещь: огня и холода больше, молнии меньше — строки идут статами билда
        self.assertTrue(app.take_copy(WINTER, ts=300.0))
        c = app.view()['copy']
        row = c['rows'][0]
        self.assertEqual((row['verdict'], row['up'], row['down'], c['pick'], row['empty']), ('better', 2, 1, 'slot:body:', False))
        self.assertEqual([(ln['id'], ln['now'], ln['new']) for ln in row['st']['lines']],
                         [('res_fire', 6, 35), ('res_cold', 0, 33), ('res_lightning', 25, 20)])
        # холод героя: 10 — награда маршрута, с новой вещью 33 + 10
        cold = next(ln for ln in row['st']['lines'] if ln['id'] == 'res_cold')
        self.assertEqual((cold['hero'], cold['heroNew']), (10, 43))
        self.assertTrue(app.wear({'row': 'slot:body:'}))
        self.assertEqual(app.run.worn['body/']['item']['name'], 'Зимний панцирь')
        body = next(r for r in app.view()['holders'] if r['id'] == 'slot:body:')
        self.assertEqual(next(p for p in body['parts'] if p['key'] == 'fire')['have']['id'], 'body-fire')   # огня 35 из 30
        # надели прежнюю снова — скопировали её и «Надеть»: в слоте снова она
        self.assertTrue(app.take_copy(ITEM, ts=350.0) and app.wear({'row': 'slot:body:'}))
        self.assertEqual(app.run.worn['body/']['item']['name'], 'Колючий спаситель')
        # память переживает перезапуск программы
        again = self.start()
        self.assertEqual(again.run.worn['body/']['item']['name'], 'Колючий спаситель')
        # «забыть»: вещь сняли, а новую не скопировали
        self.assertTrue(again.wear({'forget': 'body/'}))
        self.assertFalse(again.wear({'forget': 'body/'}))
        v = again.view()
        self.assertEqual(again.run.worn, {})
        self.assertIsNone(next(r for r in v['holders'] if r['id'] == 'slot:body:')['item'])
        # слот отмечен занятым, а что в нём надето, программа не видела: сравнить не с чем
        self.assertEqual(again._status('body-any'), 2)
        self.assertTrue(again.take_copy(WINTER, ts=400.0))
        row = again.view()['copy']['rows'][0]
        self.assertEqual((row['verdict'], row['lost'], row['keep'], row['empty']), ('unknown', True, True, False))
        self.assertTrue(again.wear({'row': 'slot:body:'}))
        self.assertEqual(again.run.worn['body/']['item']['name'], 'Зимний панцирь')

    def test_put_on_keeps_one_item_per_slot(self):
        """Слот помнит один предмет — тот, что надет (рюкзака нет). «Надеть» вытесняет прежние записи слота (и запись
        прежнего вида — место по периоду), тот же предмет в другом слоте (его переложили) и руку, которую по правилу игры
        занимает двуручное оружие (колчан при луке — нет)."""
        app = self.copy_app()
        app.plan['hands'] = {'main': 'weapon', 'off': 'offhand', 'quiver': ['Quiver']}
        staff = {'name': 'Посох', 'cls_id': 'Staff', 'tags': ['staff', 'twohand']}
        bow = {'name': 'Лук', 'cls_id': 'Bow', 'tags': ['bow', 'twohand']}
        wand = {'name': 'Жезл', 'cls_id': 'Wand', 'tags': ['wand', 'onehand']}
        shield = {'name': 'Щит', 'cls_id': 'Shield', 'tags': ['shield']}
        quiver = {'name': 'Колчан', 'cls_id': 'Quiver', 'tags': ['quiver']}
        sceptre = {'name': 'Скипетр', 'cls_id': 'Sceptre', 'tags': ['sceptre', 'onehand']}
        on = lambda **places: {k: {'item': v, 'at': 1} for k, v in places.items()}      # noqa: E731
        app.run.worn = dict(on(weapon=staff), **{'helmet/': {'item': wand, 'at': 1}})
        self.assertEqual(app.displaced('offhand/', shield), ['weapon'])
        app.run.worn = {'weapon/': {'item': staff, 'at': 1}}
        self.assertEqual(app.displaced('offhand/', shield), ['weapon/'])          # щит во вторую руку — посоха уже нет
        self.assertEqual(app.displaced('weapon/', wand), [])                      # своё место перезаписывается
        app.run.worn = {'offhand/': {'item': shield, 'at': 1}}
        self.assertEqual(app.displaced('weapon/', staff), ['offhand/'])           # посох вытесняет щит
        self.assertEqual(app.displaced('weapon/', wand), [])
        app.run.worn = {'offhand/': {'item': quiver, 'at': 1}}
        self.assertEqual(app.displaced('weapon/', bow), [])                       # лук держат вместе с колчаном
        app.run.worn = {'offhand/': {'item': sceptre, 'at': 1}, 'weapon/after': {'item': wand, 'at': 1}}
        self.assertEqual(sorted(app.displaced('weapon/', dict(sceptre, at=9))), ['offhand/', 'weapon/after'])
        # целиком: запись прежнего вида уходит
        app.run.worn = {'body/old': {'item': {'name': 'Старые латы'}, 'at': 1}}
        self.assertEqual(app.view()['wornAt'], {'body': 'body/old'})
        self.assertTrue(app.take_copy(ITEM, ts=100.0) and app.wear({'row': 'slot:body:'}))
        self.assertEqual((sorted(app.run.worn), app.view()['wornAt']), (['body/'], {'body': 'body/'}))
        # «Снять» забывает все записи слота
        app.run.worn = {'body/': {'item': {'name': 'А'}, 'at': 2}, 'body/old': {'item': {'name': 'Б'}, 'at': 1}}
        self.assertTrue(app.wear({'forget': 'body/'}))
        self.assertEqual(app.run.worn, {})

    def test_copied_waystone_gets_its_own_answer(self):
        """Путевой камень из буфера — не вещь для слота: на него страница отвечает ступенью опасности,
        а вещь, которая сейчас сравнивается со слотом, остаётся на месте. Очки свойств берутся из базы
        знаний, и она перечитывается при изменении файла."""
        folder = Path(self.tmp.name) / 'knowledge'
        folder.mkdir()
        path = folder / 'waystones.json'

        def know(pen):
            path.write_text(json.dumps({'mods': {
                'MapMonsterLifeIncrease': {'points': 0},
                'MapMonstersElementalPenetration': {'points': pen, 'why': 'пробивание'}}}), encoding='utf-8')

        know(3)
        app = self.start(knowledge_dir=folder)
        if not app.catalog or not app.catalog.get('waystones'):
            self.skipTest('каталог данных игры не собран')
        self.assertTrue(app.load_know())
        self.assertFalse(app.load_know())                    # файл не менялся — второй раз не читается
        self.assertIsNone(app.view()['way'])
        self.assertTrue(app.take_copy(ITEM, ts=100.0))
        self.assertTrue(app.take_copy(WAYSTONE, ts=200.0))
        v = app.view()
        self.assertEqual(v['copy']['at'], 100.0)             # вещь для слота осталась
        # у вещи — паспорт: её статы суммой (броня доспеха здесь — свойство самой вещи, в сумму не идёт);
        # скорость −5 — штраф базы «Полные латы», которого на самой вещи не написано
        self.assertEqual({r['id']: r['value'] for r in v['copy']['stats']['rows']},
                         {'speed': -5, 'res_fire': 6, 'res_lightning': 25})
        w = v['way']
        self.assertEqual((w['at'], w['tier'], w['area'], w['verdict'], w['score']), (200.0, 4, 68, 'fair', 3))
        self.assertEqual([(r['fam'], r['pts'], r['val']) for r in w['rows']],
                         [('MapMonstersElementalPenetration', 3, '8%'), ('MapMonsterLifeIncrease', 0, '+10%')])
        self.assertEqual(w['over'], 68 - v['hero']['level'])
        # остальным свойствам игры очки в этом файле не заданы — страница об этом скажет
        self.assertTrue(any('не заданы очки' in p for p in v['wayProblems']))
        # базу знаний поправили: ответ по тому же камню меняется без новой копии
        know(9)
        os.utime(path, (time.time() + 5, time.time() + 5))
        self.assertTrue(app.load_know())
        self.assertEqual(app.view()['way']['verdict'], 'deadly')
        # обычная вещь после камня: окно камня остаётся, вещь встаёт к своему слоту
        self.assertTrue(app.take_copy(ITEM, ts=300.0))
        v = app.view()
        self.assertEqual((v['copy']['at'], v['way']['at']), (300.0, 200.0))

    def test_comparison_leaves_the_page_by_itself(self):
        """Сравнение скопированной вещи само уходит со страницы через минуту после копии. Продлить его
        нельзя: вещь копируют в игре заново. «Надеть» и «убрать» работают как раньше."""
        app = self.copy_app()
        self.assertFalse(app.expire_copy())                      # копии нет — убирать нечего
        self.assertTrue(app.take_copy(ITEM, ts=1000.0))
        self.assertEqual(app.view()['copy']['until'], 1000.0 + server.COPY_SECONDS)
        self.assertFalse(app.expire_copy(now=1059.0))
        self.assertIsNotNone(app.view()['copy'])
        self.assertTrue(app.expire_copy(now=1060.0))
        self.assertEqual((app.view()['copy'], app.run.worn, app._status('body-any')), (None, {}, 0))   # ничего не отмечено
        self.assertFalse(app.expire_copy(now=2000.0))
        # продлить сравнение нельзя: такого слова у программы нет
        self.assertTrue(app.take_copy(ITEM, ts=3000.0))
        self.assertFalse(app.wear({'hold': True}))
        self.assertEqual(app.view()['copy']['until'], 3060.0)
        # новая копия той же или другой вещи начинает свою минуту заново
        self.assertTrue(app.take_copy(WINTER, ts=5000.0))
        self.assertEqual(app.view()['copy']['until'], 5060.0)
        self.assertTrue(app.expire_copy(now=5060.0))

    def test_clipboard_gives_only_items(self):
        """Из буфера дальше уходит только текст вещи; то, что лежало в нём до запуска, не читается."""
        class Fake:
            def __init__(self):
                self.n, self.value, self.reads = 0, 'пароль, скопированный до запуска', 0

            def seq(self):
                return self.n

            def text(self):
                self.reads += 1
                return self.value

        src, got = Fake(), []
        w = clip.Watcher(src, got.append)
        self.assertFalse(w.poll())
        self.assertEqual(src.reads, 0)                       # буфер не менялся — его не читали
        src.n, src.value = 1, 'письмо другу'
        self.assertFalse(w.poll())
        self.assertEqual((got, src.reads), ([], 1))
        src.n, src.value = 2, ITEM
        self.assertTrue(w.poll())
        self.assertFalse(w.poll())                           # та же копия второй раз не читается
        self.assertEqual((got, src.reads), ([ITEM], 2))
        src.n, src.value = 3, None                           # окно игры не активно: буфер не отдан
        self.assertFalse(w.poll())
        self.assertEqual(got, [ITEM])
        # пробный «буфер» из файла
        path = Path(self.tmp.name) / 'clip.txt'
        f = clip.FileClipboard(path)
        self.assertEqual((f.seq(), f.text()), (None, None))
        w = clip.Watcher(f, got.append)
        path.write_text(ITEM, encoding='utf-8')
        self.assertTrue(w.poll())
        self.assertEqual(len(got), 2)

    @unittest.skipUnless(sys.platform == 'win32', 'клавиши в игре — Windows')
    def test_keys_are_held_only_while_the_game_is_in_front(self):
        """«Надеть» (F2) и «Закрыть» (F3) регистрируются в системе, только пока впереди окно игры, и снимаются, когда
        впереди другое (там клавиши работают как обычно); нажатие — своё действие у каждой. Клавишу держит другая
        программа — «busy» у неё одной, повторная попытка только при следующем переходе в игру. Игра заняла клавишу (выбор
        сменился) — программа переходит на другую. Системные вызовы подменены: настоящие клавиши не регистрируются."""
        class User32:
            def __init__(self):
                self.calls, self.taken, self.queue = [], set(), []

            def RegisterHotKey(self, hwnd, kid, mods, key):
                self.calls.append(('reg', kid, mods, key))
                return key not in self.taken

            def UnregisterHotKey(self, hwnd, kid):
                self.calls.append(('unreg', kid))
                return True

            def PeekMessageW(self, ref, hwnd, lo, hi, remove):
                if not self.queue:
                    return False
                ref._obj.wParam = self.queue.pop(0)
                return True

        F2, F3, F7 = 0x71, 0x72, 0x76
        game, pressed, choice = [False], [], [clip.pick_keys()]
        k = clip.WinKeys(lambda: game[0], lambda: choice[0],
                         {'wear': lambda: pressed.append('wear'), 'close': lambda: pressed.append('close')})
        u = k.user32 = User32()
        self.assertEqual(choice[0], {'wear': F2, 'close': F3})
        k.step()
        self.assertEqual((k.state, u.calls), ({'wear': 'idle', 'close': 'idle'}, []))   # игра не впереди — клавиши свободны
        game[0] = True
        k.step()
        self.assertEqual((k.state, sorted(c[3] for c in u.calls)), ({'wear': 'on', 'close': 'on'}, [F2, F2, F3]))
        # одиночные клавиши; «Сравнить / Надеть» слушается ещё и с зажатым Alt (игрок держит его, чтобы видеть тиры)
        self.assertEqual(sorted(c[2] for c in u.calls), [clip.MOD_NOREPEAT, clip.MOD_NOREPEAT, clip.MOD_NOREPEAT | clip.MOD_ALT])
        u.queue = [clip.KEY_IDS['close'], clip.KEY_IDS['wear']]
        k.step()
        self.assertEqual(pressed, ['close', 'wear'])
        game[0] = False
        k.step()
        self.assertEqual((k.state['wear'], k.held, [c[0] for c in u.calls[-2:]]), ('idle', {}, ['unreg', 'unreg']))
        # F3 держит другая программа: «busy» только у «Закрыть», и каждые 50 мс её не перехватывают
        u.taken, game[0] = {F3}, True
        k.step()
        k.step()
        self.assertEqual((k.state, [c[3] for c in u.calls if c[0] == 'reg'].count(F3)), ({'wear': 'on', 'close': 'busy'}, 2))
        # игра заняла F2 (игрок переназначил клавиши): «Надеть» переходит на F3, «Закрыть» — на F7 (F4 программа не
        # берёт: Alt+F4 закрывает игру)
        u.taken = set()
        choice[0] = clip.pick_keys({F2})
        k.step()
        self.assertEqual((k.held, k.state), ({'wear': F3, 'close': F7}, {'wear': 'on', 'close': 'on'}))

    def test_game_keys_from_the_config_decide_which_keys_the_program_takes(self):
        """Клавиши игры — из её файла настроек: привязки обоих режимов управления, только без модификаторов. Программа
        берёт первые свободные функциональные клавиши: «Сравнить / Надеть» и «Закрыть» — по умолчанию F2 и F3,
        «Программа ↔ игра» — F7 (F4 не берётся: Alt+F4 закрывает игру; F5 оставлена программам торговли)."""
        cfg = ('[GENERAL]\nuser_input_mode=wasd\n[ACTION_KEYS]\nperformance_overlay=112\nuse_bound_skill9=113 2\n'
               'take_screenshot=119\n[WASD_ACTION_KEYS]\nmove_up=87\n[UI]\nwhatever=113\n')
        taken = clip.game_keys(cfg)
        self.assertEqual(taken, {112, 119, 87})            # Ctrl+F2 и строка не из раздела привязок не в счёт
        self.assertEqual(clip.pick_keys(taken), {'wear': 0x71, 'close': 0x72})
        self.assertEqual(clip.pick_keys(clip.game_keys(cfg + '[WASD_ACTION_KEYS]\nfoo=113\n')), {'wear': 0x72, 'close': 0x76})
        self.assertEqual(clip.pick_keys(taken, clip.ALL_KEYS), {'wear': 0x71, 'close': 0x72, 'app': 0x76})
        self.assertNotIn(0x73, clip.pick_keys(set(), ('a', 'b', 'c', 'd', 'e', 'f', 'g')).values())   # F4 — никогда
        # клавиша подробного описания предмета (с ней игра копирует тиры): из настроек игры, без модификаторов
        self.assertEqual(clip.game_key(cfg + '[ACTION_KEYS]\nshow_advanced_item_descriptions=18\n', 'show_advanced_item_descriptions'), 18)
        self.assertIsNone(clip.game_key(cfg + '[ACTION_KEYS]\nshow_advanced_item_descriptions=18 2\n', 'show_advanced_item_descriptions'))
        self.assertIsNone(clip.game_key(cfg, 'show_advanced_item_descriptions'))
        self.assertEqual((clip.key_name(0x71), clip.key_name(0x7A), clip.key_name(0x56), clip.key_name(None)),
                         ('F2', 'F11', None, None))
        # программа читает клавиши вместе с фильтром; сменились — страница узнаёт новые
        root = Path(self.tmp.name)
        path = root / 'poe2_production_Config.ini'
        path.write_text('[UI]\nitem_filter=None\n', encoding='utf-8')
        app = server.App(self.log, self.plan, self.runs, None, None, path)
        with app.cond:
            app.load_plan()
            app.load_config()
            app.poll_log(initial=True)
            app.attach_run()
        self.assertEqual(app.key_choice, {'wear': 0x71, 'close': 0x72, 'app': 0x76})
        self.assertEqual(app.copy_mod, clip.VK_MENU)                          # в настройках клавиши нет — Alt
        path.write_text('[ACTION_KEYS]\nfoo=113\nshow_advanced_item_descriptions=20\n[UI]\nitem_filter=None\n', encoding='utf-8')
        os.utime(path, (1, 4102444800))
        before = app.version
        with app.cond:
            app.load_config()
        self.assertEqual((app.key_choice, app.version > before),
                         ({'wear': 0x72, 'close': 0x76, 'app': 0x75}, True))
        self.assertEqual(app.copy_mod, 20)

    def test_own_copy_key_reads_once_and_gives_the_clipboard_back(self):
        """Своя копия по клавише: одно нажатие игрока — одна копия в игре, одно чтение буфера, и в буфере снова то, что
        лежало до нажатия. Под курсором не предмет — буфер не трогается. Окно игры не впереди — в чужое окно ничего не
        нажимается. Слежение за буфером своих перемен за новую копию не принимает. Буфер и клавиши подменены."""
        class Fake:
            def __init__(self):
                self.n, self.value, self.front, self.answer = 5, 'пароль', True, ITEM
                self.sent, self.restored, self.reads = [], [], 0

            def seq(self):
                return self.n

            def text(self):
                self.reads += 1
                return self.value

            def game_in_front(self):
                return self.front

            def snapshot(self):
                return [(13, self.value)]

            def restore(self, snap):
                self.restored.append(snap)
                self.n, self.value = self.n + 1, snap[0][1]
                return True

            def send_copy(self, mod):
                self.sent.append(mod)
                if self.answer is not None:                 # игра кладёт текст предмета под курсором в буфер
                    self.n, self.value = self.n + 1, self.answer

        src, got = Fake(), []
        w = clip.Watcher(src, got.append)
        c = clip.Copier(src, w, mod=lambda: 20, wait=0.2, pause=0.001)
        self.assertEqual(c.grab(), ITEM)
        self.assertEqual((src.sent, src.reads), ([20], 1))                    # клавиша подробного описания — из настроек
        self.assertEqual((src.value, src.restored), ('пароль', [[(13, 'пароль')]]))   # буфер — как до нажатия
        self.assertFalse(w.poll())                                            # возврат буфера — не новая копия
        self.assertEqual((src.reads, got), (1, []))
        # под курсором не предмет: игра ничего не положила — буфер не открывали и не меняли
        src.answer = None
        self.assertIsNone(c.grab())
        self.assertEqual((len(src.sent), src.reads, len(src.restored)), (2, 1, 1))
        # в буфер легло не то (чужая программа успела раньше игры): дальше не идёт, прежнее возвращается
        src.answer = 'не предмет'
        self.assertIsNone(c.grab())
        self.assertEqual((src.value, len(src.restored)), ('пароль', 2))
        # окно игры не впереди — ни клавиш, ни чтения
        src.front, src.answer = False, ITEM
        self.assertIsNone(c.grab())
        self.assertEqual((len(src.sent), src.reads), (3, 2))
        # обычное Ctrl+Alt+C самим игроком работает как раньше
        src.front, src.n, src.value = True, src.n + 1, ITEM
        self.assertTrue(w.poll())
        self.assertEqual(got, [ITEM])

    def test_one_key_compares_and_then_wears(self):
        """Одна клавиша в игре: по предмету под курсором — сравнить; по тому же предмету ещё раз — «Надеть». Новый
        предмет при открытом сравнении — новое сравнение, а не «Надеть» (предметы перебирают подряд). Второе нажатие
        сразу за первым (случайное) ничего не отмечает. Под курсором не предмет — ничего."""
        app = self.copy_app()
        self.assertFalse(app.hotkey_item(None, now=90.0))
        self.assertTrue(app.hotkey_item(ITEM, now=100.0))                     # сравнить
        self.assertEqual((app.copied['name'], app.view()['copy']['at'], app.run.worn), ('Колючий спаситель', 100.0, {}))
        self.assertFalse(app.hotkey_item(ITEM, now=100.2))                    # тут же ещё раз — случайное: не «Надеть»
        self.assertFalse(app.hotkey_item(None, now=102.0))                    # под курсором пусто — не «Надеть»
        self.assertEqual(app.run.worn, {})
        self.assertTrue(app.hotkey_item(WINTER, now=103.0))                   # другой предмет — новое сравнение
        self.assertEqual((app.copied['name'], app.run.worn), ('Зимний панцирь', {}))
        self.assertTrue(app.hotkey_item(ITEM, now=106.0))                     # вернулись к первому — снова сравнение
        self.assertEqual((app.copied['name'], app.run.worn), ('Колючий спаситель', {}))
        # тот же ещё раз через треть секунды — уже «Надеть» (было: не раньше секунды — нажимали трижды)
        self.assertTrue(app.hotkey_item(ITEM.replace('\n', '\r\n') + '\r\n', now=106.35))
        self.assertEqual((app.run.worn['body/']['item']['name'], app.copied), ('Колючий спаситель', None))
        self.assertTrue(app.hotkey_item(ITEM, now=112.0))                     # надетый предмет ещё раз — просто показать
        self.assertEqual(app.view()['copy']['rows'][0]['verdict'], 'worn')
        self.assertFalse(app.hotkey_item(ITEM, now=115.0))                    # и «Надеть» по нему — уже нечего
    @unittest.skipUnless(sys.platform == 'win32', 'клавиши в игре — Windows')
    def test_extra_keys_are_held_only_with_an_action_and_on_their_own_condition(self):
        """«Программа ↔ игра» программа держит, только если для неё есть действие, и слушает её и когда впереди окно
        самой программы — иначе из него не вернуться в игру той же клавишей. «Сравнить / Надеть» слушается и с зажатым
        Alt (игрок держит его, чтобы видеть тиры)."""
        class User32:
            def __init__(self):
                self.held, self.queue = {}, []

            def RegisterHotKey(self, hwnd, kid, mods, key):
                self.held[kid] = (key, mods & clip.MOD_ALT)
                return True

            def UnregisterHotKey(self, hwnd, kid):
                self.held.pop(kid, None)
                return True

            def PeekMessageW(self, ref, hwnd, lo, hi, remove):
                if not self.queue:
                    return False
                ref._obj.wParam = self.queue.pop(0)
                return True

        ids, game, own, pressed = clip.KEY_IDS, [False], [False], []
        press = {name: (lambda n=name: pressed.append(n)) for name in ('wear', 'close', 'app')}
        k = clip.WinKeys(lambda: game[0], lambda: clip.pick_keys(names=clip.ALL_KEYS), press,
                         {'app': lambda: game[0] or own[0]})
        u = k.user32 = User32()
        k.step()
        self.assertEqual((u.held, set(k.state.values())), ({}, {'idle'}))
        game[0] = True
        k.step()
        self.assertEqual(u.held, {ids['wear']: (0x71, 0), ids['wear'] + clip.ALT_ID: (0x71, clip.MOD_ALT),
                                  ids['close']: (0x72, 0), ids['app']: (0x76, 0)})
        u.queue = [ids['wear'], ids['app'], ids['wear'] + clip.ALT_ID]
        k.step()
        self.assertEqual(pressed, ['wear', 'app', 'wear'])
        # впереди окно программы: держится одна «Программа ↔ игра»
        game[0], own[0] = False, True
        k.step()
        self.assertEqual((u.held, k.state['app'], k.state['wear']), ({ids['app']: (0x76, 0)}, 'on', 'idle'))
        u.queue = [ids['app']]
        k.step()
        self.assertEqual(pressed, ['wear', 'app', 'wear', 'app'])
        own[0] = False
        k.step()
        self.assertEqual(u.held, {})
        # без действия клавиша не берётся вовсе: игрок её не теряет
        k = clip.WinKeys(lambda: True, lambda: clip.pick_keys(names=clip.ALL_KEYS), {'wear': print, 'close': print})
        u = k.user32 = User32()
        k.step()
        self.assertEqual((sorted(k.state), ids['app'] in u.held), (['close', 'wear'], False))
    def test_versions_of_the_program_and_of_the_game(self):
        """Версия программы — «версия игры, под которую она сделана» (из каталога данных в программе) и номер сборки.
        Какая игра у игрока, называет её лог при каждом запуске; игра новее программы — страница скажет «нужна новая
        версия программы»; исправление внутри версии (буква) или ещё не обновлённая игра — нет."""
        app = self.start()
        app.base_catalog = None                                               # каталога данных игры нет — версии нет
        self.assertEqual(app.view()['version'], {'program': None, 'made': None, 'game': None, 'newer': False})
        app.base_catalog = {'version': '0.5.5.10'}
        program = '0.5.5.%d' % server.appversion.BUILD
        self.assertEqual(app.view()['version'], {'program': program, 'made': '0.5.5', 'game': None, 'newer': False})
        with open(self.log, 'a', encoding='utf-8') as f:
            f.write(ln('21:00:00', '#Сосед: [HTTP2] User agent: PoE poe2_production/tags/9.9.9 Windows x64'))   # чат — не версия
            f.write(ln('21:00:01', '[HTTP2] User agent: PoE poe2_production/tags/0.5.5h Windows x64'))
        before = app.version
        with app.cond:
            self.assertTrue(app.poll_log())
        self.assertEqual(app.view()['version'], {'program': program, 'made': '0.5.5', 'game': '0.5.5h', 'newer': False})
        with open(self.log, 'a', encoding='utf-8') as f:
            f.write(ln('22:00:00', '[HTTP2] User agent: PoE poe2_production/tags/0.6.0 Windows x64'))
        with app.cond:
            app.poll_log()
        self.assertEqual(app.view()['version'], {'program': program, 'made': '0.5.5', 'game': '0.6.0', 'newer': True})
        app.base_catalog = {'version': '0.7.0.1'}                             # программу обновили раньше игры
        self.assertEqual((app.view()['version']['made'], app.view()['version']['newer']), ('0.7.0', False))
        # лог перечитан с начала (другой герой, другая папка игры) — версия игры находится заново
        with app.cond:
            app.replay()
        self.assertEqual(app.game_tag, '0.6.0')
        self.assertIsInstance(before, int)

    def test_keys_from_a_file_for_trial_runs(self):
        """Пробные запуски вместо клавиш следят за файлом: каждая его смена — одно нажатие, клавишу называет первое
        слово (после него пишут время, чтобы файл менялся); иначе — «Надеть»."""
        path, pressed = Path(self.tmp.name) / 'key.txt', []
        path.write_text('', encoding='utf-8')
        k = clip.FileKeys(path, {name: (lambda n=name: pressed.append(n)) for name in ('wear', 'close', 'app')})
        self.assertIsNone(k.poll())                                           # файл не менялся
        for text in ('close 1795.25', 'app 1795.5', 'wear 1796', '1797', 'copy 1798.123'):
            path.write_text(text, encoding='utf-8')
            k.poll()
        self.assertEqual(pressed, ['close', 'app', 'wear', 'wear', 'wear'])

    def test_overlay_switch_lives_in_the_settings(self):
        """«поверх игры: вкл / выкл» — настройка программы: есть только у её собственного окна (overlay.can) и помнится в
        settings.json; страница узнаёт о смене сразу."""
        app = self.start()
        self.assertEqual(app.view()['overlay'], {'can': False, 'on': True, 'list': 'fold', 'alt': 'any', 'clear': 30})
        self.assertFalse(app.set_overlay(False))                             # окон нет — выключать нечего
        app.overlay = {'can': True, 'on': True}
        app.settings_path = Path(self.tmp.name) / 'settings.json'
        before = app.version
        self.assertFalse(app.set_overlay('off'))
        self.assertTrue(app.set_overlay(False))
        self.assertEqual((app.view()['overlay'], app.version > before), ({'can': True, 'on': False}, True))
        self.assertIs(json.loads(app.settings_path.read_text(encoding='utf-8'))['overlay'], False)
        self.assertTrue(app.set_overlay(True))
        self.assertIs(json.loads(app.settings_path.read_text(encoding='utf-8'))['overlay'], True)

    def test_overlay_choices_live_in_the_settings(self):
        """Что игрок выбирает об окнах поверх игры в окне «Настройки»: список свёрнут или раскрыт, по Alt он раскрыт
        всегда или под курсором, его прозрачность. Есть только вместе с окнами поверх игры, помнится в settings.json,
        страница узнаёт о смене сразу. Значение не из возможных (и похожее на него: 1 вместо True, '30' вместо 30) не
        принимается. Своей клавиши в игре у этих настроек нет."""
        app = self.start()
        self.assertEqual(app.overlay, dict(server.overlay_from({}), can=False))
        self.assertFalse(app.set_overlay_opt('list', 'open'))                 # окон нет — менять нечего
        app.overlay = dict(server.overlay_from({}), can=True)
        app.settings_path = Path(self.tmp.name) / 'settings.json'
        before = app.version
        for name, bad in (('list', 'wide'), ('alt', 'never'), ('clear', 20), ('clear', '30'), ('clear', True), ('on', 1),
                          ('size', 100)):
            self.assertFalse(app.set_overlay_opt(name, bad), (name, bad))
        self.assertEqual(app.version, before)
        self.assertTrue(app.set_overlay_list('open'))
        self.assertTrue(app.set_overlay_opt('alt', 'over'))
        self.assertTrue(app.set_overlay_opt('clear', 0))
        self.assertEqual((app.view()['overlay'], app.version > before),
                         ({'can': True, 'on': True, 'list': 'open', 'alt': 'over', 'clear': 0}, True))
        saved = json.loads(app.settings_path.read_text(encoding='utf-8'))
        self.assertEqual((saved['overlayList'], saved['overlayAlt'], saved['overlayClear']), ('open', 'over', 0))
        seen = app.version
        self.assertTrue(app.set_overlay_opt('alt', 'over'))                   # то же самое — ничего не меняется
        self.assertEqual(app.version, seen)
        # при запуске настройки читаются из файла; чего в нём нет или что в нём не из возможного — по умолчанию
        self.assertEqual(server.overlay_from(saved), {'on': True, 'list': 'open', 'alt': 'over', 'clear': 0})
        self.assertEqual(server.overlay_from({'overlay': False, 'overlayList': 'wide', 'overlayClear': '50'}),
                         {'on': False, 'list': 'fold', 'alt': 'any', 'clear': 30})
        # окно «Настройки»: те же настройки и папка игры
        self.assertEqual(app.settings_view()['overlay'], app.view()['overlay'])
        self.assertEqual(set(app.settings_view()['game']), {'dir', 'found', 'pick'})
        # клавиш у программы три: «Список» (F6) убрана
        app.keys = clip.FileKeys(Path(self.tmp.name) / 'key.txt', {'app': print})
        self.assertEqual({k: v['key'] for k, v in app.view()['keys'].items()}, {'wear': 'F2', 'close': 'F3', 'app': 'F7'})
        self.assertFalse(hasattr(app, 'hotkey_list'))

    def test_copy_remembers_where_the_cursor_was(self):
        """Копию делают, наведя курсор на предмет: программа запоминает, где он был, — у этого места встаёт ответ поверх
        игры. Буфер без курсора (файл в проверках) — места нет: ответ встанет у курсора, когда появится."""
        class Source:
            def cursor(self):
                return (3100, 900)

        app = self.copy_app()
        self.assertIsNone(app.copy_cursor)
        app.clip_source = Source()
        self.assertTrue(app.take_copy(ITEM, ts=100.0))
        self.assertEqual(app.copy_cursor, (100.0, (3100, 900)))
        app.clip_source = clip.FileClipboard(Path(self.tmp.name) / 'clip.txt')
        self.assertTrue(app.take_copy(WINTER, ts=200.0))
        self.assertIsNone(app.copy_cursor)

    def test_close_key_tells_the_page_when_it_was_pressed(self):
        """«Закрыть» в игре: какое окно верхнее, знает только страница, — программа отдаёт время нажатия (shut)."""
        app = self.copy_app()
        self.assertIsNone(app.view()['shut'])
        self.assertTrue(app.hotkey_close())
        self.assertIsInstance(app.view()['shut'], float)

    def test_put_on_key_wears_into_the_chosen_slot(self):
        """Клавиша в игре — то же, что «Надеть» в карточке: в слот, выбранный для копии (на странице — кольцо), иначе в тот,
        что программа выбрала сама. Нечего надевать — ничего."""
        app = self.copy_app()
        self.assertFalse(app.hotkey_wear())                                   # сравнения нет
        self.assertTrue(app.take_copy(ITEM, ts=100.0))
        self.assertEqual(app.view()['keys'], None)                            # клавиш нет: программа не слушает
        app.keys = clip.FileKeys(Path(self.tmp.name) / 'key.txt', {})
        self.assertEqual(app.view()['keys'], {'wear': {'key': 'F2', 'state': 'on'}, 'close': {'key': 'F3', 'state': 'on'}})
        # «Программа ↔ игра» страница видит, только когда программа её держит; «Сравнить» — та же клавиша, что «Надеть»:
        # страница узнаёт об этом по признаку copy у клавиши
        app.keys = clip.FileKeys(Path(self.tmp.name) / 'key.txt', {'app': print})
        self.assertEqual({k: v['key'] for k, v in app.view()['keys'].items()}, {'wear': 'F2', 'close': 'F3', 'app': 'F7'})
        self.assertNotIn('copy', app.view()['keys']['wear'])
        app.key_copies = True
        self.assertIs(app.view()['keys']['wear']['copy'], True)
        app.key_copies = False
        app.keys = None
        self.assertTrue(app.wear({'choose': 'slot:nowhere:'}))
        self.assertEqual(app.view()['copy']['pick'], 'slot:body:')            # выбранной строки нет — выбор программы
        self.assertTrue(app.hotkey_wear())
        self.assertEqual((app.run.worn['body/']['item']['name'], app.copied, app._status('body-any')),
                         ('Колючий спаситель', None, 2))
        self.assertTrue(app.take_copy(ITEM, ts=200.0))
        self.assertFalse(app.hotkey_wear())                                   # та же вещь уже надета
        app.copied = None
        self.assertFalse(app.wear({'choose': 'slot:body:'}))                  # выбирать не для чего
        # кольцо: строк две, выбор страницы важнее
        ring = ('Класс предмета: Кольца\nРедкость: Редкий\nВихрь горя\nЖелезное кольцо\n--------\nУровень предмета: 20\n'
                '--------\n{ Суффикс "углей" (Уровень: 8) — Стихийный, Огонь, Сопротивление }\n+8(6-10)% к сопротивлению огню\n')
        plan = json.loads(self.plan.read_text(encoding='utf-8'))
        plan['slots'] += [{'id': 'ring1', 'name': 'Кольцо 1', 'classes': ['Ring'], 'gear': 'Ring'},
                          {'id': 'ring2', 'name': 'Кольцо 2', 'classes': ['Ring'], 'gear': 'Ring'}]
        self.plan.write_text(json.dumps(plan, ensure_ascii=False), encoding='utf-8')
        app = self.start()
        self.assertTrue(app.take_copy(ring, ts=300.0))
        rows = [r['row'] for r in app.view()['copy']['rows']]
        self.assertEqual(rows, ['slot:ring1:', 'slot:ring2:'])
        self.assertTrue(app.wear({'choose': 'slot:ring2:'}))
        self.assertEqual(app.view()['copy']['pick'], 'slot:ring2:')
        self.assertTrue(app.hotkey_wear())
        self.assertEqual(sorted(app.run.worn), ['body/', 'ring2/'])          # (доспех — от прежнего запуска того же забега)

    @unittest.skipUnless(sys.platform == 'win32', 'буфер обмена Windows')
    def test_windows_clipboard_is_reachable(self):
        """Системные вызовы на месте. Сам буфер тут не читается: только счётчик его смен и чьё окно активно."""
        c = clip.WinClipboard(game_dir=Path(self.tmp.name))
        self.assertIsInstance(c.seq(), int)
        self.assertFalse(c.game_in_front())                  # активное окно — не программа из этой папки
        self.assertIsNone(c.text())                          # значит, буфер не открывается


ITEM = '''Класс предмета: Нательные доспехи
Редкость: Редкий
Колючий спаситель
Полные латы
--------
Уровень предмета: 47
--------
{ Префикс "Шипованный" (Уровень: 10) — Броня }
+36(28-56) к броне
{ Суффикс "грозовой тучи" (Уровень: 5) — Стихийный, Молния, Сопротивление }
+25(21-25)% к сопротивлению молнии
{ Суффикс "углей" (Уровень: 8) — Стихийный, Огонь, Сопротивление }
+6(6-10)% к сопротивлению огню
'''


WINTER = '''Класс предмета: Нательные доспехи
Редкость: Редкий
Зимний панцирь
Полные латы
--------
Уровень предмета: 47
--------
{ Суффикс "айсберга" (Уровень: 4) — Стихийный, Холод, Сопротивление }
+33(31-35)% к сопротивлению холоду
{ Суффикс "грозовой тучи" (Уровень: 6) — Стихийный, Молния, Сопротивление }
+20(16-20)% к сопротивлению молнии
{ Суффикс "вулкана" (Уровень: 4) — Стихийный, Огонь, Сопротивление }
+35(31-35)% к сопротивлению огню
'''


WAYSTONE = '''Класс предмета: Путевые камни
Редкость: Редкий
Тайный гамбит
Путевой камень (Ур. 4)
--------
Доступно возрождений: 3 (augmented)
Редкость предметов: +16% (augmented)
Редкость монстров: +23% (augmented)
Шанс выпадения путевого камня: +35% (augmented)
--------
Уровень предмета: 69
--------
{ Префикс "Стойкий" (Уровень: 1) }
На 10(10-14)% больше здоровья монстров
{ Префикс "Пробивающий" (Уровень: 1) }
Урон монстров пробивает 8(6-8)% сопротивлений стихиям
--------
Можно использовать в Машине картоходца, чтобы войти на карту. Путевые камни одноразовые.
'''


if __name__ == '__main__':
    unittest.main()
