# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Sergei Labutin
# Additional terms under GPL-3.0 section 7: see NOTICE.md
"""Слоты билда со страницы «Билд» (вкладка «Вещи»): классы предметов из данных игры, проверка присланных
слотов, запись раздела в файл. Запуск: python -m unittest planner.test_slots"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import buildplan  # noqa: E402
import slotwear  # noqa: E402
import test_buildplan as tb  # noqa: E402

BOOTS = {'id': 'boots', 'name': 'Сапоги', 'classes': ['Boots'], 'gear': 'Boots str_armour'}


def state():
    """Файл билда, план и каталог из проверок целей; в слое языка — слова двух видов: как клиент пишет
    класс предмета (classes) и как его называет таблица классов игры (classNames)."""
    build, plan, cat = tb.goals_state()
    cat['lang']['ru']['classes'] = {'Скипетры': 'Sceptre', 'Сапоги': 'Boots'}
    cat['lang']['ru']['classNames'] = {'Bow': 'Луки', 'Boots': 'Обувь'}
    return build, plan, cat


class ChoiceTest(unittest.TestCase):
    def test_item_classes_come_from_game_data(self):
        build, plan, cat = state()
        full = [{'id': 'str_armour', 'label': 'Броня'}, {'id': 'int_armour', 'label': 'Энергощит'},
                {'id': 'str_int_armour', 'label': 'Броня / Энергощит'}]
        # слово клиента важнее названия из таблицы классов (сапоги — «Сапоги», не «Обувь»); названные — первыми
        self.assertEqual(buildplan.item_classes(cat), [
            {'id': 'Bow', 'name': 'Луки', 'kinds': []},
            {'id': 'Boots', 'name': 'Сапоги', 'kinds': full[:1]},
            {'id': 'Sceptre', 'name': 'Скипетры', 'kinds': []},
            {'id': 'Amulet', 'name': None, 'kinds': []},
            {'id': 'Belt', 'name': None, 'kinds': []},
            {'id': 'Body Armour', 'name': None, 'kinds': full},
            {'id': 'Helmet', 'name': None, 'kinds': full[1:2]}])
        d = buildplan.describe(cat, plan, {}, build=build, route=tb.GOALS_ROUTE)
        # слоты — как в файле; базы вещей — по классам: страница сама собирает их для слота
        self.assertEqual(d['slots'], json.loads(tb.GOALS_BUILD)['slots'])
        self.assertEqual([c['id'] for c in d['classes']], ['Bow', 'Boots', 'Sceptre', 'Amulet', 'Belt', 'Body Armour', 'Helmet'])
        self.assertEqual(d['classBases']['Sceptre'], [{'name': 'Гремящий скипетр (Rattling Sceptre)', 'gear': 'Sceptre', 'level': 1, 'icon': None}])
        self.assertNotIn('bases', d)


class CheckTest(unittest.TestCase):
    def setUp(self):
        self.build, self.plan, self.cat = state()

    def check(self, raw, goals=None):
        problems = []
        return buildplan.check_slots(raw, self.build, self.cat, problems, goals), problems

    def slots(self):
        return json.loads(tb.GOALS_BUILD)['slots']

    def test_untouched_slots_pass_and_edits_are_cleaned(self):
        out, problems = self.check(self.slots())
        self.assertEqual((problems, out, [list(s) for s in out]), ([], self.slots(), [list(s) for s in self.slots()]))
        raw = self.slots()
        raw[0]['name'] = '  Основное оружие '
        raw[0]['classes'] = ['Sceptre', 'Bow']
        raw[1]['gear'] = ''                                                    # «что носят» стёрли — поля нет
        raw.insert(1, {'gear': 'Boots str_armour', 'classes': ['Boots'], 'name': 'Сапоги', 'id': 'boots'})
        out, problems = self.check(raw)
        self.assertEqual(problems, [])
        self.assertEqual(out, [{'id': 'weapon', 'name': 'Основное оружие', 'classes': ['Sceptre', 'Bow']}, BOOTS,
                               {'id': 'body', 'name': 'Доспех', 'classes': ['Body Armour']}])
        self.assertEqual(list(out[1]), ['id', 'name', 'classes', 'gear'])      # новая запись — в привычном порядке полей
        # род базы — из тех, что у класса бывают; класс без рода — «как у этапа»
        raw = self.slots()
        raw[1]['gear'] = 'Body Armour str_int_armour'
        self.assertEqual(self.check(raw), ([raw[0], dict(raw[1])], []))

    def test_fields_the_page_does_not_edit_survive(self):
        self.build['slots'][0]['doneOn'] = 'find'
        raw = [dict(self.build['slots'][0], name='Оружие 2'), self.build['slots'][1]]
        out, problems = self.check(raw)
        self.assertEqual((problems, out[0]), ([], {'id': 'weapon', 'name': 'Оружие 2', 'classes': ['Sceptre'], 'doneOn': 'find'}))
        raw[0]['doneOn'] = 'equip'
        self.assertEqual(self.check(raw)[1], ['слот «Оружие 2»: поле «doneOn» со страницы не правится'])

    def test_what_is_refused(self):
        def bad(i, **kw):
            raw = self.slots()
            raw[i].update(kw)
            return self.check(raw)[1]

        self.assertEqual(self.check({})[1], ['слоты: нужен список не длиннее 40'])
        self.assertEqual(bad(0, id='Оружие'), ['слот: id — латинские буквы, цифры, дефис',
                                               'слот «Оружие» не убрать: в нём есть цели (2), первая — «Гремящий скипетр (Rattling Sceptre)»; сначала уберите их'])
        self.assertEqual(bad(1, id='weapon'), ['слот «weapon»: такой id уже есть'])
        self.assertEqual(bad(0, name=' '), ['слот «weapon»: нужно название'])
        self.assertEqual(bad(0, name='х' * 61), ['слот «%s»: название — текст не длиннее 60 знаков' % ('х' * 61), 'слот «weapon»: нужно название'])
        self.assertEqual(bad(0, classes=[]), ['слот «Оружие»: классы предметов — список без повторов, хотя бы один класс'])
        self.assertEqual(bad(0, classes=['Sceptre', 'Sceptre']), ['слот «Оружие»: классы предметов — список без повторов, хотя бы один класс'])
        self.assertEqual(bad(0, classes=['Sceptre', 'Wand']), ['слот «Оружие»: класса предметов «Wand» нет в данных игры'])
        self.assertEqual(bad(1, gear='Helmet'), ['слот «Доспех»: в слоте носят «Helmet», а такого класса у слота нет'])
        self.assertEqual(bad(1, gear='Body Armour dex_armour'), ['слот «Доспех»: у класса «Body Armour» нет баз рода «dex_armour»'])
        self.assertEqual(bad(1, gear=['Body Armour']), ['слот «Доспех»: что носят в слоте — класс предмета и, если нужно, род базы'])
        self.assertEqual(self.check(self.slots() + [{'id': 'ring', 'name': 'Кольцо'}])[1], ['слот «Кольцо»: нужен хотя бы один период — что в слоте носят'])
        # класс, который называет вещь слота, из слота не убрать
        self.assertEqual(bad(0, classes=['Bow']), ['слот «Оружие»: класс «Sceptre» не убрать — его называет предмет «Гремящий скипетр (Rattling Sceptre)»'])

    def test_periods_of_a_slot_are_checked(self):
        """Слот нового вида: что в нём носят, записано периодами (wear). Шаг начала — из маршрута и один на период,
        классы — из данных игры, род базы — из тех, что у этих классов бывают; периоды встают по порядку шагов."""
        steps = tb.GOALS_ROUTE['steps']
        build = slotwear.upgrade(self.build, steps)

        def check(wear, goals=None):
            problems = []
            raw = [dict(build['slots'][0], wear=wear), build['slots'][1]]
            return buildplan.check_slots(raw, build, self.cat, problems, goals, steps), problems

        self.assertEqual(build['slots'], [{'id': 'weapon', 'name': 'Оружие', 'wear': [{'from': 'clearfell', 'classes': ['Sceptre']}]},
                                          {'id': 'body', 'name': 'Доспех', 'wear': [{'classes': ['Body Armour']}]}])
        out, problems = check(build['slots'][0]['wear'])
        self.assertEqual((problems, out), ([], build['slots']))
        # второй период с самого начала встаёт первым; пустые поля в запись не идут
        out, problems = check([{'from': 'clearfell', 'classes': ['Sceptre'], 'kind': ''}, {'from': '', 'classes': ['Bow', 'Sceptre'], 'until': None}])
        self.assertEqual((problems, out[0]['wear']), ([], [{'classes': ['Bow', 'Sceptre']}, {'from': 'clearfell', 'classes': ['Sceptre']}]))
        out, problems = check([{'classes': ['Boots'], 'kind': 'str_armour'}, {'from': 'clearfell', 'classes': ['Sceptre'], 'until': 'maps'}])
        self.assertEqual((problems, out[0]['wear']), ([], [{'classes': ['Boots'], 'kind': 'str_armour'},
                                                         {'from': 'clearfell', 'classes': ['Sceptre'], 'until': 'maps'}]))
        self.assertEqual(check([])[1], ['слот «Оружие»: периоды — список, хотя бы один и не больше 20'])
        self.assertEqual(check([{'from': 'nowhere', 'classes': ['Sceptre']}])[1], ['слот «Оружие»: шага «nowhere» в маршруте нет'])
        self.assertEqual(check([{'from': 'clearfell', 'classes': ['Sceptre']}, {'from': 'clearfell', 'classes': ['Bow']}])[1],
                         ['слот «Оружие»: два периода начинаются с одного шага'])
        self.assertEqual(check([{'from': 'clearfell', 'classes': []}])[1], ['слот «Оружие»: у периода нужен хотя бы один класс предметов, без повторов'])
        self.assertEqual(check([{'from': 'clearfell', 'classes': ['Sceptre', 'Wand']}])[1], ['слот «Оружие»: класса предметов «Wand» нет в данных игры'])
        self.assertEqual(check([{'from': 'clearfell', 'classes': ['Sceptre'], 'kind': 'str_armour'}])[1],
                         ['слот «Оружие»: у классов периода нет баз рода «str_armour»'])
        self.assertEqual(check([{'from': 'maps', 'classes': ['Sceptre'], 'until': 'clearfell'}])[1][:1],
                         ['слот «Оружие»: срок периода — шаг маршрута не раньше его начала'])
        self.assertEqual(check([{'from': 'clearfell', 'classes': ['Sceptre'], 'spec': 'x'}])[1],
                         ['слот «Оружие»: у периода есть шаг начала (from), классы (classes), род базы (kind) и срок (until)'])
        # период, в котором стоит предмет слота, убрать нельзя; предмет убран этой же правкой — можно
        gone = check([{'classes': ['Sceptre']}])[1]
        self.assertEqual(gone, ['слот «Оружие»: у предмета «Гремящий скипетр (Rattling Sceptre)» нет периода (с шага «Клирфелл») — '
                                'сначала уберите или перенесите его'])
        rest = [g for g in build['goals'] if g.get('slot') != 'weapon']
        self.assertEqual(check([{'classes': ['Sceptre']}], rest)[1], [])
        # цель слота стоит в одном из его периодов — это сверяется и когда присланы одни цели
        goals = build['goals'] + [{'id': 'bow', 'slot': 'weapon', 'title': 'любое', 'any': True}]
        sec, problems = buildplan.check({'goals': goals}, self.plan, self.cat, build=build, route=tb.GOALS_ROUTE)
        self.assertEqual((sec, problems), ({}, ['цель «любое»: у слота нет периода с самого начала']))

    def test_slot_with_goals_cannot_be_removed(self):
        body = self.slots()[1:]
        self.assertEqual(self.check(body), (body, [
            'слот «Оружие» не убрать: в нём есть цели (2), первая — «Гремящий скипетр (Rattling Sceptre)»; сначала уберите их']))
        # цели слота убраны этой же правкой — слот уходит
        rest = [g for g in self.build['goals'] if g.get('slot') != 'weapon']
        self.assertEqual(self.check(body, rest), (body, []))
        self.assertEqual(self.check(self.slots()[:1]), (self.slots()[:1], []))   # слот без целей уходит сразу

    def test_slots_and_goals_of_one_request_are_checked_together(self):
        goals = self.build['goals'] + [{'id': 'boots-any', 'slot': 'boots', 'title': 'Любые сапоги', 'any': True, 'need': 'maps'}]
        sec, problems = buildplan.check({'goals': goals}, self.plan, self.cat, build=self.build, route=tb.GOALS_ROUTE)
        self.assertEqual((sec, problems), ({}, ['цель «Любые сапоги»: слота «boots» в билде нет']))
        sec, problems = buildplan.check({'slots': self.slots() + [BOOTS], 'goals': goals}, self.plan, self.cat,
                                        build=self.build, route=tb.GOALS_ROUTE)
        self.assertEqual((problems, sec['slots'][-1], sec['goals'][-1]['slot']), ([], BOOTS, 'boots'))
        # слот убран, а цель в нём осталась — отказ, и сказано почему
        sec, problems = buildplan.check({'slots': self.slots(), 'goals': goals}, self.plan, self.cat, build=self.build, route=tb.GOALS_ROUTE)
        self.assertEqual((sec, problems), ({}, ['цель «Любые сапоги»: слота «boots» в билде нет']))
        # у плана одним файлом слотов на странице нет
        self.assertEqual(buildplan.check({'slots': []}, self.plan, self.cat),
                         ({}, ['слоты и цели правятся только у плана из частей (маршрут, билд, личное)']))


class FileTest(unittest.TestCase):
    def test_only_the_slots_section_is_rewritten(self):
        slots = json.loads(tb.GOALS_BUILD)['slots']
        self.assertEqual(buildplan.render_sections(tb.GOALS_BUILD, {'slots': slots}), tb.GOALS_BUILD)   # знак в знак
        new = [dict(slots[0], name='Основное оружие'), BOOTS, slots[1]]
        out = buildplan.render_sections(tb.GOALS_BUILD, {'slots': new})
        self.assertIn('  "slots": [\n    {"id": "weapon", "name": "Основное оружие", "classes": ["Sceptre"]},\n'
                      '    {"id": "boots", "name": "Сапоги", "classes": ["Boots"], "gear": "Boots str_armour"},\n'
                      '    {"id": "body", "name": "Доспех", "classes": ["Body Armour"], "gear": "Body Armour"}\n  ],\n  "stages": [\n', out)
        before, after = json.loads(tb.GOALS_BUILD), json.loads(out)
        self.assertEqual((after['slots'], list(after), {k: v for k, v in after.items() if k != 'slots'}),
                         (new, list(before), {k: v for k, v in before.items() if k != 'slots'}))
        self.assertEqual(buildplan.render_sections(tb.GOALS_BUILD.replace('\n', '\r\n'), {'slots': new}).replace('\r\n', '\n'), out)

    def test_the_real_build_is_written_back_exactly(self):
        """Слоты настоящего билда проходят проверку нетронутыми и пишутся знак в знак — иначе первая же
        правка со страницы переписала бы раздел не так, как он написан."""
        import gamedata
        import planlib
        root = Path(HERE).parent
        plans, cat = planlib.project_plans(root), gamedata.load(root / 'catalog' / 'data')
        if not plans or not cat:
            self.skipTest('нет файла билда или каталога данных игры')
        for path, parts in plans:
            with self.subTest(plan=path.parent.name):
                text = parts['build'].read_bytes().decode('utf-8-sig')
                build, problems = json.loads(text), []
                route = json.loads(parts['route'].read_text(encoding='utf-8-sig'))
                slots = buildplan.check_slots(build['slots'], build, cat, problems, None, route['steps'])
                self.assertEqual((problems, slots), ([], build['slots']))
                self.assertEqual(buildplan.render_sections(text, {'slots': slots}), text)
                # у каждого класса, который носят в слоте, в данных игры есть русское название
                names = {c['id']: c['name'] for c in buildplan.item_classes(cat)}
                self.assertEqual([c for s in slots for c in slotwear.classes_of(s) if not names.get(c)], [])


class ServerTest(unittest.TestCase):
    """Слоты через программу: план из частей, каталог настоящий."""

    def setUp(self):
        import server
        import test_treeplan
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        (root / 'Client.txt').write_text(test_treeplan.LOG, encoding='utf-8')
        (root / 'plan.json').write_text(json.dumps({'version': 2, 'route': 'route.json', 'build': 'build.json'}), encoding='utf-8')
        (root / 'route.json').write_text(json.dumps(tb.GOALS_ROUTE, ensure_ascii=False), encoding='utf-8')
        self.build = root / 'build.json'
        self.build.write_bytes(tb.GOALS_BUILD.replace('\n', '\r\n').encode('utf-8'))
        self.app = server.App(root / 'Client.txt', root / 'plan.json', root / 'runs', backup_dir=root / 'backup')
        with self.app.cond:
            self.app.load_plan()
            self.app.poll_log(initial=True)
            self.app.attach_run()

    def tearDown(self):
        self.tmp.cleanup()

    def test_slots_are_read_edited_and_written(self):
        if not self.app.catalog or not self.app.catalog.get('stats'):
            self.skipTest('каталог данных игры не собран')
        d = self.app.build_view()
        # файл старого вида (classes и gear у слота, gear у цели) страница получает уже с периодами слотов
        self.assertEqual((d['problems'], d['slots']), ([], [
            {'id': 'weapon', 'name': 'Оружие', 'wear': [{'from': 'clearfell', 'classes': ['Sceptre']}]},
            {'id': 'body', 'name': 'Доспех', 'wear': [{'classes': ['Body Armour']}]}]))
        self.assertNotIn('gear', next(g for g in d['goals'] if g['id'] == 'sceptre'))
        names = {c['id']: c['name'] for c in d['classes']}
        self.assertEqual((names['Sceptre'], names['Boots'], names['Bow']), ('Скипетры', 'Сапоги', 'Луки'))
        self.assertIn({'name': 'Гремящий скипетр (Rattling Sceptre)', 'gear': 'Sceptre', 'level': 1, 'icon': 'art-sceptre01'}, d['classBases']['Sceptre'])
        # слот переименован, в его период добавлен второй класс; добавлен новый слот — и сразу с целью в нём
        slots = d['slots']
        slots[0]['name'] = 'Основное оружие'
        slots[0]['wear'][0]['classes'].append('Crossbow')
        slots.append({'id': 'boots', 'name': 'Сапоги', 'wear': [{'classes': ['Boots'], 'kind': 'str_armour'}]})
        goals = d['goals'] + [{'id': 'boots-any', 'slot': 'boots', 'title': 'Любые сапоги', 'any': True, 'need': 'maps'}]
        ok, problems = self.app.save_build({'slots': slots, 'goals': goals})
        self.assertEqual((ok, problems), (True, []))
        text = self.build.read_bytes().decode('utf-8')
        self.assertIn('    {"id": "weapon", "name": "Основное оружие", "wear": [{"from": "clearfell", "classes": ["Sceptre", "Crossbow"]}]},\r\n', text)
        self.assertIn('    {"id": "boots", "name": "Сапоги", "wear": [{"classes": ["Boots"], "kind": "str_armour"}]}\r\n  ],\r\n', text)
        self.assertNotIn('\n', text.replace('\r\n', ''))
        # старого вида в файле не осталось: у слотов нет classes и gear, у целей слотов нет gear
        data = json.loads(text)
        self.assertEqual([s['id'] for s in data['slots'] if 'classes' in s or 'gear' in s] + [g['id'] for g in data['goals'] if 'gear' in g], [])
        self.assertEqual(([s['id'] for s in self.app.plan['slots']], self.app.plan_problems), (['weapon', 'body', 'boots'], []))
        self.assertEqual(sorted(x.name.split('-')[0] for x in (Path(self.tmp.name) / 'backup').iterdir()), ['build.build'])
        # страница маршрута видит новый слот; вещь класса нового слота находит в нём место
        view = self.app.view()
        self.assertEqual([s['id'] for s in view['slots']], ['weapon', 'body', 'boots'])
        # слот с целями не убрать — файл цел; без целей — убирается, порядок слотов меняется
        saved = self.build.read_bytes()
        d = self.app.build_view()
        ok, problems = self.app.save_build({'slots': [s for s in d['slots'] if s['id'] != 'boots']})
        self.assertEqual((ok, problems, self.build.read_bytes() == saved), (
            False, ['слот «Сапоги» не убрать: в нём есть цели (1), первая — «Любые сапоги»; сначала уберите их'], True))
        ok, problems = self.app.save_build({'slots': [d['slots'][2], d['slots'][0]], 'goals': [g for g in d['goals'] if g.get('slot') != 'body']})
        self.assertEqual((ok, problems), (True, []))
        self.assertEqual([s['id'] for s in self.app.plan['slots']], ['boots', 'weapon'])


if __name__ == '__main__':
    unittest.main()
