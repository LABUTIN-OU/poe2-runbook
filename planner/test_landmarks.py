# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Sergei Labutin
# Additional terms under GPL-3.0 section 7: see NOTICE.md
"""Справочник игры: боссы, задания и награды по зонам; план ссылается на его записи и говорит только своё.
Запуск: python -m unittest planner.test_landmarks"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import landmarks  # noqa: E402
import planfiles  # noqa: E402
import routeplan  # noqa: E402
import test_routeplan  # noqa: E402

# Файл справочника в том виде, в каком его пишет программа: запись — одна строка.
MARKS = '''{
  "version": 1,
  "game": "0.5.5.9",
  "landmarks": [
    {"id": "boss-miller", "kind": "boss", "zone": "G1_1", "title": "Раздувшийся мельник (The Bloated Miller)", "must": true},
    {"id": "boss-beira", "kind": "boss", "zone": "G1_2", "title": "Бейра (Beira): +10% к холоду", "group": "Награды", "reward": "base_cold_damage_resistance_%", "gives": {"res_cold": 10}, "heard": ["CarrionCroneRotten2", "UnaNewAfterSinging"]},
    {"id": "points-una", "zone": "G1_2", "title": "Хижина Уны (Una's Hut): +2 очка", "group": "Награды", "reward": "passive_points"}
  ]
}
'''
# Тот же учебный маршрут, но боссы в нём — ссылки на справочник
ROUTE = test_routeplan.ROUTE.replace(
    '{"id": "boss-miller", "kind": "boss", "must": true, "title": "Раздувшийся мельник (The Bloated Miller)", "need": "riverbank"}',
    '{"id": "boss-miller", "need": "riverbank"}').replace(
    '{"id": "boss-beira", "kind": "boss", "group": "Награды", "title": "Бейра (Beira): +10% к холоду", "reward": "base_cold_damage_resistance_%", '
    '"gives": {"res_cold": 10}, "heard": ["CarrionCroneRotten2", "UnaNewAfterSinging"], "need": "clearfell"}',
    '{"id": "boss-beira", "need": "clearfell", "from": "riverbank"}')


def marks():
    return {r['id']: r for r in json.loads(MARKS)['landmarks']}


# Награда с выбором: в справочнике — все варианты; какой брать, говорит план
CHOICE = {'id': 'tattoo-una', 'zone': 'G1_2', 'title': "Испытание Уны (Una's Test)", 'group': 'Награды', 'swap': False, 'options': [
    {'title': '+5 к ловкости', 'name': 'Татуировка ловкости (Dexterity Tattoo)', 'reward': 'additional_dexterity', 'gives': {'dex': 5}},
    {'title': '+5% к сопротивлению молнии', 'name': 'Татуировка молнии (Lightning Tattoo)', 'reward': 'base_lightning_damage_resistance_%',
     'gives': {'res_lightning': 5}}]}


def with_choice():
    return dict(marks(), **{'tattoo-una': CHOICE})


class FileTest(unittest.TestCase):
    def load(self, text):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'landmarks.json'
            path.write_text(text, encoding='utf-8')
            return landmarks.load(path)

    def test_reference_is_read_in_file_order(self):
        got, game, problems = self.load(MARKS)
        self.assertEqual((list(got), game, problems), (['boss-miller', 'boss-beira', 'points-una'], '0.5.5.9', []))
        self.assertEqual(got['boss-beira']['gives'], {'res_cold': 10})
        # файла нет — справочник пуст, и это не ошибка
        self.assertEqual(landmarks.load(Path(HERE) / 'no-such-file.json'), ({}, None, []))

    def test_what_is_wrong_in_the_file_is_said(self):
        self.assertEqual(self.load('{ не json')[0], {})
        self.assertIn('Справочник игры не читается', self.load('{ не json')[2][0])
        self.assertEqual(self.load('{"things": []}')[2], ['Справочник игры записан не так: нужен список landmarks'])
        bad = json.loads(MARKS)
        bad['landmarks'] += [{'id': 'boss-miller', 'title': 'Дубль'}, {'id': 'no-name'}, {'title': 'Без id'},
                             {'id': 'odd', 'kind': 'skill', 'title': 'Не тот вид'}]
        got, _, problems = self.load(json.dumps(bad, ensure_ascii=False))
        self.assertEqual(list(got), ['boss-miller', 'boss-beira', 'points-una'])
        self.assertEqual(problems, ['Справочник игры: запись «boss-miller» стоит дважды', 'Справочник игры: у записи «no-name» нет названия',
                                    'Справочник игры: запись без id',
                                    'Справочник игры: запись «odd» — босс (boss), задание (quest), механика (mechanic), тайник (cache), лагерь (camp), восхождение (ascension) или награда (без kind)'])

    def test_an_ascension_has_its_levels(self):
        """Восхождение — одна запись справочника: зоны испытаний и младший уровень зоны каждой ступени (levels). Ставят его
        ссылкой ref, как механику, — на нескольких шагах; в цель плана идут вид, уровни и зоны (по зонам проверка видит,
        на испытании ли шаг). Уровни ступеней — только у восхождения, и у него всегда."""
        rec = {'id': 'ascendancy', 'kind': 'ascension', 'zones': ['G2_13', 'G3_10'], 'title': 'Восхождение (Ascendancy)',
               'group': 'Восхождение', 'levels': [22, 38, 60, 75]}
        good = json.loads(MARKS)
        good['landmarks'].append(rec)
        got, _, problems = self.load(json.dumps(good, ensure_ascii=False))
        self.assertEqual((problems, got['ascendancy']['levels']), ([], [22, 38, 60, 75]))
        goals, problems = landmarks.resolve([{'id': 'ascendancy-chaos', 'ref': 'ascendancy', 'need': 'chaos'},
                                             {'id': 'ascendancy-trial', 'ref': 'ascendancy', 'need': 'trial'}], got)
        self.assertEqual((problems, [g['need'] for g in goals]), ([], ['chaos', 'trial']))
        self.assertEqual(goals[0], dict(rec, id='ascendancy-chaos', need='chaos'))
        for rec in ({'id': 'a5', 'kind': 'ascension', 'title': 'Не по порядку', 'levels': [60, 22]},
                    {'id': 'a0', 'kind': 'ascension', 'title': 'Без уровней'},
                    {'id': 'b1', 'kind': 'boss', 'title': 'Босс с уровнями', 'levels': [22]}):
            bad = json.loads(MARKS)
            bad['landmarks'].append(rec)
            got, _, problems = self.load(json.dumps(bad, ensure_ascii=False))
            self.assertNotIn(rec['id'], got)
            self.assertEqual(len(problems), 1, rec['id'])

    def test_where_and_after_what_are_facts_of_the_record(self):
        """Где выдают награду, где это в зоне, падает ли случайно, что нужно раньше — факты игры в записи. Записанное
        не так и ожидание записи, которой нет, — замечание; запись остаётся без этого."""
        good = json.loads(MARKS)
        good['landmarks'][2].update(handout='G1_town', spot='у колодца', needs=['boss-beira'])
        good['landmarks'][1].update(random=True)
        got, _, problems = self.load(json.dumps(good, ensure_ascii=False))
        self.assertEqual((problems, got['points-una']['needs'], got['boss-beira']['random']), ([], ['boss-beira'], True))
        bad = json.loads(MARKS)
        bad['landmarks'][0]['random'] = 'да'
        bad['landmarks'][2]['needs'] = ['boss-beira', 'boss-nobody', 'points-una']
        got, _, problems = self.load(json.dumps(bad, ensure_ascii=False))
        self.assertEqual(problems, ['Справочник игры: у записи «boss-miller» поле random записано не так',
                                    'Справочник игры: запись «points-una» ждёт записей, которых нет: boss-nobody, points-una'])
        self.assertEqual((list(got), got['points-una']['needs']), (['boss-beira', 'points-una'], ['boss-beira']))
        # в цели плана — что нужно раньше, с названиями записей
        goal = landmarks.resolve([{'id': 'points-una', 'need': 'clearfell'}], {r['id']: r for r in good['landmarks']})[0][0]
        self.assertEqual((goal['handout'], goal['spot'], goal['needs']),
                         ('G1_town', 'у колодца', [{'id': 'boss-beira', 'title': 'Бейра (Beira): +10% к холоду'}]))

    def test_which_monsters_drop_a_quest_item_is_a_fact_of_the_record(self):
        """С каких монстров падает предмет задания — список названий, как их пишет игра; в цель плана он идёт как
        есть. Не список, пустой список или пустое название — замечание, запись не читается."""
        good = json.loads(MARKS)
        good['landmarks'][1].update(random=True, monsters=['Гигант ваал (Vaal Goliath)'])
        got, _, problems = self.load(json.dumps(good, ensure_ascii=False))
        self.assertEqual((problems, got['boss-beira']['monsters']), ([], ['Гигант ваал (Vaal Goliath)']))
        goal = landmarks.resolve([{'id': 'boss-beira', 'need': 'clearfell'}], got)[0][0]
        self.assertEqual((goal['random'], goal['monsters']), (True, ['Гигант ваал (Vaal Goliath)']))
        for wrong in ('Гигант ваал (Vaal Goliath)', [], ['  ']):
            bad = json.loads(MARKS)
            bad['landmarks'][1]['monsters'] = wrong
            got, _, problems = self.load(json.dumps(bad, ensure_ascii=False))
            self.assertEqual(problems, ['Справочник игры: у записи «boss-beira» поле monsters записано не так'])
            self.assertNotIn('boss-beira', got)

    def test_a_goal_splits_into_a_fact_and_a_link_and_comes_back_whole(self):
        old = [g for g in test_routeplan.route()['goals'] if 'reach' not in g]
        table, links = {}, []
        for g in old:
            ref, link = landmarks.split(dict(g, until='maps'), 'G1_2')
            table[g['id']] = ref
            links.append(link)
        # в записи — факты игры и зона, в ссылке — только то, что сказал план
        self.assertEqual(table['boss-miller'], {'id': 'boss-miller', 'kind': 'boss', 'zone': 'G1_2',
                                                'title': 'Раздувшийся мельник (The Bloated Miller)', 'must': True})
        self.assertEqual(links[0], {'id': 'boss-miller', 'need': 'riverbank', 'until': 'maps'})
        back, problems = landmarks.resolve(links, table)
        self.assertEqual((problems, back), ([], [dict(g, until='maps') for g in old]))
        # файл справочника: запись — одна строка; читается обратно таким же
        text = landmarks.render(table, '0.5.5.9')
        self.assertIn('    {"id": "boss-miller", "kind": "boss", "zone": "G1_2", "title": "Раздувшийся мельник (The Bloated Miller)", "must": true},\n', text)
        self.assertEqual(self.load(text), (table, '0.5.5.9', []))


class ResolveTest(unittest.TestCase):
    def test_links_become_goals_of_the_usual_kind(self):
        goals = json.loads(ROUTE)['goals']
        got, problems = landmarks.resolve(goals, marks())
        self.assertEqual(problems, [])
        # цель самого плана (уровень героя) — как записана; ссылка — факты записи плюс сказанное планом; зоны в цели нет
        self.assertEqual(got[0], {'id': 'hero-7', 'group': 'Уровень', 'title': '7 уровень героя', 'reach': 7, 'need': 'clearfell'})
        self.assertEqual(got[1], {'id': 'boss-miller', 'kind': 'boss', 'title': 'Раздувшийся мельник (The Bloated Miller)', 'must': True, 'need': 'riverbank'})
        self.assertEqual((got[2]['title'], got[2]['gives'], got[2]['need'], got[2]['from'], 'zone' in got[2]),
                         ('Бейра (Beira): +10% к холоду', {'res_cold': 10}, 'clearfell', 'riverbank', False))
        # план, собранный из ссылок, — тот же, что из маршрута, где факты записаны прямо в целях
        old = test_routeplan.route()['goals']
        self.assertEqual([dict(g) for g in got[:2]], old[:2])
        self.assertEqual({k: v for k, v in got[2].items() if k != 'from'}, old[2])

    def test_a_link_to_nothing_is_said_and_dropped(self):
        got, problems = landmarks.resolve([{'id': 'boss-nobody', 'need': 'riverbank'}, {'id': 'boss-own', 'kind': 'boss', 'title': 'Свой', 'need': 'riverbank'}], marks())
        self.assertEqual(problems, ['Маршрут: записи «boss-nobody» нет в справочнике игры'])
        self.assertEqual([g['id'] for g in got], ['boss-own'])          # цель со своим названием — не ссылка
        # без справочника цели с названиями живут как раньше
        self.assertEqual(landmarks.resolve(test_routeplan.route()['goals'], None), (test_routeplan.route()['goals'], []))

    def test_plan_is_composed_with_the_reference(self):
        raw, notes = planfiles.compose({'route': 'r', 'build': 'b'}, json.loads(ROUTE), json.loads(test_routeplan.BUILD), marks())
        self.assertEqual(notes, [])
        self.assertEqual([(g['id'], g.get('title')) for g in raw['goals']], [
            ('sceptre', 'Гремящий скипетр (Rattling Sceptre)'), ('hero-7', '7 уровень героя'),
            ('boss-miller', 'Раздувшийся мельник (The Bloated Miller)'), ('boss-beira', 'Бейра (Beira): +10% к холоду')])


class ChoiceTest(unittest.TestCase):
    def test_the_plan_says_which_option_it_takes(self):
        got, problems = landmarks.resolve([{'id': 'tattoo-una', 'need': 'clearfell', 'opt': 2, 'from': 'riverbank'}], with_choice())
        self.assertEqual(problems, [])
        # цель называется по выбранному варианту и даёт герою то, что даёт он; отмечается строкой лога любого варианта
        self.assertEqual(got, [{'id': 'tattoo-una', 'title': "Испытание Уны (Una's Test): +5% к сопротивлению молнии", 'group': 'Награды',
                                'need': 'clearfell', 'from': 'riverbank', 'reward': ['additional_dexterity', 'base_lightning_damage_resistance_%'],
                                'gives': {'res_lightning': 5}}])
        self.assertEqual(landmarks.picked(CHOICE, {'opt': 1})['title'], '+5 к ловкости')
        self.assertIsNone(landmarks.picked(CHOICE, {}))
        self.assertIsNone(landmarks.picked(marks()['boss-miller'], {'opt': 1}))

    def test_an_unmade_choice_is_not_made_by_the_program(self):
        got, problems = landmarks.resolve([{'id': 'tattoo-una', 'need': 'clearfell'}], with_choice())
        self.assertEqual(problems, [])
        self.assertEqual((got[0]['title'], got[0]['unpicked'], 'gives' in got[0], got[0]['reward']),
                         ("Испытание Уны (Una's Test): вариант не выбран", True, False, ['additional_dexterity', 'base_lightning_damage_resistance_%']))
        # назван вариант, которого нет, — сказано, и выбор считается несделанным
        got, problems = landmarks.resolve([{'id': 'tattoo-una', 'need': 'clearfell', 'opt': 5}], with_choice())
        self.assertEqual((problems, got[0]['unpicked']), (["Маршрут: у «Испытание Уны (Una's Test)» назван вариант 5, а их 2"], True))
        # и это стоит в проверке гайда как несделанное — со ссылкой на запись и её шаг
        import buildcheck
        plan = {'steps': [{'id': 'clearfell', 'name': 'Клирфелл'}], 'goals': landmarks.resolve([{'id': 'tattoo-una', 'need': 'clearfell'}], with_choice())[0]}
        found = [f for f in buildcheck.run({}, plan, {}, None) if f['kind'] == 'choice']
        self.assertEqual(found, [{'kind': 'choice', 'level': 'bad', 'tab': 'route', 'goal': 'tattoo-una', 'what': "Испытание Уны (Una's Test)",
                                  'text': 'У награды с выбором не назван вариант', 'where': 'шаг «Клирфелл»'}])

    def test_the_choice_is_checked_when_the_route_is_saved(self):
        def check(link):
            problems = []
            out = routeplan.check_goals([link], {'goals': []}, {'clearfell'}, set(), problems, marks=with_choice())
            return out, problems

        self.assertEqual(check({'id': 'tattoo-una', 'need': 'clearfell', 'opt': 1}), ([{'id': 'tattoo-una', 'need': 'clearfell', 'opt': 1}], []))
        self.assertEqual(check({'id': 'tattoo-una', 'need': 'clearfell', 'opt': ''}), ([{'id': 'tattoo-una', 'need': 'clearfell'}], []))
        self.assertEqual(check({'id': 'tattoo-una', 'need': 'clearfell', 'opt': 3})[1],
                         ["цель шага «Испытание Уны (Una's Test)»: вариант — номер от 1 до 2"])
        self.assertEqual(check({'id': 'boss-miller', 'need': 'clearfell', 'opt': 1})[1],
                         ['цель шага «Раздувшийся мельник (The Bloated Miller)»: выбирать вариант не из чего'])
        # сами варианты — факт игры: в плане их не правят
        self.assertEqual(check({'id': 'tattoo-una', 'need': 'clearfell', 'options': []})[1],
                         ["цель шага «Испытание Уны (Una's Test)»: поле «options» — факт игры из справочника, в плане он не правится"])

    def test_options_written_wrong_are_said(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'landmarks.json'
            bad = json.loads(MARKS)
            bad['landmarks'] += [dict(CHOICE, id='one', options=CHOICE['options'][:1]), dict(CHOICE, id='blank', options=[{'title': ' '}, {'title': 'б'}]), CHOICE]
            path.write_text(json.dumps(bad, ensure_ascii=False), encoding='utf-8')
            got, _, problems = landmarks.load(path)
        self.assertEqual(list(got), ['boss-miller', 'boss-beira', 'points-una', 'tattoo-una'])
        self.assertEqual(problems, ['Справочник игры: у записи «one» варианты записаны не так — нужно хотя бы два, у каждого название',
                                    'Справочник игры: у записи «blank» варианты записаны не так — нужно хотя бы два, у каждого название'])


# Механика — одна запись на механику игры; zones — где её показывает карта мира кампании
ABYSS = {'id': 'mech-abyss', 'kind': 'mechanic', 'zones': ['G1_2', 'G2_5_1'], 'title': 'Бездна (Abyss)', 'group': 'Механики'}


def with_mechanic():
    return dict(marks(), **{'mech-abyss': ABYSS})


class MechanicTest(unittest.TestCase):
    def test_a_mechanic_is_a_record_with_the_zones_where_the_game_shows_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'landmarks.json'
            raw = json.loads(MARKS)
            raw['landmarks'] += [ABYSS, dict(ABYSS, id='mech-bad', zones='G1_2'), dict(ABYSS, id='mech-empty', zones=[])]
            path.write_text(json.dumps(raw, ensure_ascii=False), encoding='utf-8')
            got, _, problems = landmarks.load(path)
        self.assertEqual(got['mech-abyss'], ABYSS)
        self.assertEqual(problems, ['Справочник игры: у записи «mech-bad» поле zones записано не так',
                                    'Справочник игры: у записи «mech-empty» поле zones записано не так'])

    def test_one_mechanic_stands_on_several_steps_by_ref(self):
        links = [{'id': 'abyss-clearfell', 'ref': 'mech-abyss', 'need': 'clearfell'},
                 {'id': 'abyss-maps', 'ref': 'mech-abyss', 'need': 'maps'},
                 {'id': 'mech-abyss', 'need': 'riverbank'}]
        got, problems = landmarks.resolve(links, with_mechanic())
        self.assertEqual(problems, [])
        # у каждой ссылки — своя цель со своим id; зон и ref в цели нет: зоны нужны редактору, ref — только файлу
        self.assertEqual(got, [
            {'id': 'abyss-clearfell', 'kind': 'mechanic', 'title': 'Бездна (Abyss)', 'group': 'Механики', 'need': 'clearfell'},
            {'id': 'abyss-maps', 'kind': 'mechanic', 'title': 'Бездна (Abyss)', 'group': 'Механики', 'need': 'maps'},
            {'id': 'mech-abyss', 'kind': 'mechanic', 'title': 'Бездна (Abyss)', 'group': 'Механики', 'need': 'riverbank'}])
        self.assertTrue(landmarks.is_ref(links[0], with_mechanic()))
        self.assertEqual(landmarks.ref_id(links[0]), 'mech-abyss')

    def test_only_a_mechanic_is_placed_by_ref(self):
        # босс — одна битва в одной зоне: на него ссылаются его id, по ref его на второй шаг не поставить
        got, problems = landmarks.resolve([{'id': 'miller-again', 'ref': 'boss-miller', 'need': 'clearfell'},
                                           {'id': 'abyss-x', 'ref': 'mech-nothing', 'need': 'clearfell'}], with_mechanic())
        self.assertEqual(got, [])
        self.assertEqual(problems, ['Маршрут: цель «miller-again» ссылается на «boss-miller» полем ref — так ставят только механику и восхождение',
                                    'Маршрут: записи «mech-nothing» нет в справочнике игры'])

    def test_a_mechanic_link_is_saved_with_its_ref(self):
        def check(goals):
            problems = []
            return routeplan.check_goals(goals, json.loads(ROUTE), {'riverbank', 'clearfell', 'maps'}, set(), problems,
                                         marks=with_mechanic()), problems

        links = [{'id': 'abyss-clearfell', 'ref': 'mech-abyss', 'need': 'clearfell'},
                 {'id': 'abyss-maps', 'ref': 'mech-abyss', 'need': 'maps'}]
        out, problems = check(links)
        self.assertEqual((problems, out, [list(g) for g in out]), ([], links, [['id', 'ref', 'need']] * 2))
        self.assertEqual(check([{'id': 'abyss-x', 'ref': 'boss-miller', 'need': 'clearfell'}])[1],
                         ['цель шага «Раздувшийся мельник (The Bloated Miller)»: ссылка ref — id механики или восхождения из справочника игры'])
        self.assertEqual(check([{'id': 'abyss-x', 'ref': 'mech-nothing', 'need': 'clearfell'}])[1],
                         ['цель шага «abyss-x»: ссылка ref — id механики или восхождения из справочника игры',
                          'цель шага «abyss-x»: такой записи нет в справочнике игры'])
        # факт игры (зоны, название) на ссылке не правится
        self.assertEqual(check([{'id': 'abyss-x', 'ref': 'mech-abyss', 'need': 'clearfell', 'zones': ['G1_1']}])[1],
                         ['цель шага «Бездна (Abyss)»: поле «zones» — факт игры из справочника, в плане он не правится'])
        self.assertEqual(check([{'id': 'abyss-x', 'ref': 'mech-abyss'}])[1], ['цель шага «Бездна (Abyss)»: не назван её шаг'])

    def test_a_mechanic_link_is_one_line_in_the_route_file(self):
        r = json.loads(ROUTE)
        r['goals'].append({'id': 'abyss-clearfell', 'ref': 'mech-abyss', 'need': 'clearfell'})
        out = routeplan.render(ROUTE, {'steps': r['steps'], 'goals': r['goals']})
        self.assertIn('    {"id": "abyss-clearfell", "ref": "mech-abyss", "need": "clearfell"}\n  ]\n', out)
        raw, notes = planfiles.compose({'route': 'r', 'build': 'b'}, json.loads(out), json.loads(test_routeplan.BUILD), with_mechanic())
        self.assertEqual(notes, [])
        self.assertEqual([(g['id'], g.get('kind'), g.get('title')) for g in raw['goals']][-1],
                         ('abyss-clearfell', 'mechanic', 'Бездна (Abyss)'))


class CheckTest(unittest.TestCase):
    def check(self, goals):
        problems = []
        return routeplan.check_goals(goals, json.loads(ROUTE), {'riverbank', 'clearfell', 'after', 'maps'}, set(), problems, marks=marks()), problems

    def test_a_record_of_the_reference_has_no_note_in_the_plan(self):
        """О записи справочника план говорит шаг; ни заметки, ни подсказки у целей шага нет."""
        self.assertEqual(self.check([{'id': 'boss-miller', 'need': 'clearfell', 'note': 'тактика'}])[1],
                         ['цель шага «Раздувшийся мельник (The Bloated Miller)»: поле «note» со страницы не правится'])
        self.assertEqual(self.check([{'id': 'boss-miller', 'need': 'clearfell', 'hint': 'у моста'}])[1],
                         ['цель шага «Раздувшийся мельник (The Bloated Miller)»: поле «hint» со страницы не правится'])

    def test_links_pass_and_only_the_plans_own_words_are_edited(self):
        goals = json.loads(ROUTE)['goals']
        out, problems = self.check(goals)
        self.assertEqual((problems, out, [list(g) for g in out]), ([], goals, [list(g) for g in goals]))
        goals[1].update({'need': 'clearfell', 'from': 'riverbank'})
        goals.append({'id': 'points-una', 'need': 'clearfell'})
        out, problems = self.check(goals)
        self.assertEqual(problems, [])
        self.assertEqual((out[1], out[3]), ({'id': 'boss-miller', 'need': 'clearfell', 'from': 'riverbank'},
                                           {'id': 'points-una', 'need': 'clearfell'}))
        # «о пропущенном боссе не напоминать» (soft) страница не ставит: босс в плане — цель
        self.assertEqual(self.check([{'id': 'boss-miller', 'need': 'clearfell', 'soft': True}])[1],
                         ['цель шага «Раздувшийся мельник (The Bloated Miller)»: поле «soft» со страницы не правится'])

    def test_facts_of_the_game_are_not_edited_in_the_plan(self):
        def bad(rec):
            return self.check(json.loads(ROUTE)['goals'] + [rec])[1]

        self.assertEqual(bad({'id': 'points-una', 'need': 'clearfell', 'reward': 'другая строка'}),
                         ["цель шага «Хижина Уны (Una's Hut): +2 очка»: поле «reward» — факт игры из справочника, в плане он не правится"])
        self.assertEqual(bad({'id': 'points-una', 'need': 'clearfell', 'must': True}),
                         ["цель шага «Хижина Уны (Una's Hut): +2 очка»: поле «must» — факт игры из справочника, в плане он не правится"])
        self.assertEqual(bad({'id': 'points-una'}), ["цель шага «Хижина Уны (Una's Hut): +2 очка»: не назван её шаг"])
        self.assertEqual(bad({'id': 'boss-nobody', 'need': 'clearfell'}), ['цель шага «boss-nobody»: такой записи нет в справочнике игры'])
        # цель со своим названием — цель самого плана: проверяется как раньше
        self.assertEqual(bad({'id': 'hero-9', 'title': '9 уровень героя', 'reach': 9, 'need': 'clearfell'}), [])

    def test_a_link_is_one_line_in_the_route_file(self):
        r = json.loads(ROUTE)
        self.assertEqual(routeplan.render(ROUTE, {'steps': r['steps'], 'goals': r['goals']}), ROUTE)          # знак в знак
        r['goals'].append({'id': 'points-una', 'need': 'clearfell'})
        out = routeplan.render(ROUTE, {'steps': r['steps'], 'goals': r['goals']})
        self.assertIn('    {"id": "boss-beira", "need": "clearfell", "from": "riverbank"},\n    {"id": "points-una", "need": "clearfell"}\n  ]\n', out)


class ServerTest(unittest.TestCase):
    """Справочник через программу: план из трёх частей, каталог настоящий, справочник — свой, во временной папке."""

    def setUp(self):
        import server
        import test_treeplan
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        (root / 'Client.txt').write_text(test_treeplan.LOG, encoding='utf-8')
        (root / 'plan.json').write_text(json.dumps({'version': 2, 'route': 'route.json', 'build': 'build.json'}), encoding='utf-8')
        self.route, self.marks = root / 'route.json', root / 'knowledge' / 'landmarks.json'
        self.route.write_bytes(ROUTE.replace('\n', '\r\n').encode('utf-8'))
        (root / 'build.json').write_bytes(test_routeplan.BUILD.replace('\n', '\r\n').encode('utf-8'))
        self.marks.parent.mkdir()
        # справочник пробы составлен для той версии данных игры, что стоит в каталоге: с другой версией программа
        # просит его сверить (это проверяет последний тест)
        import gamedata
        cat = gamedata.load(server.ROOT / 'catalog' / 'data')
        self.MARKS = MARKS.replace('"game": "0.5.5.9"', '"game": %s' % json.dumps(cat['version'])) if cat else MARKS
        self.marks.write_text(self.MARKS, encoding='utf-8')
        self.app = server.App(root / 'Client.txt', root / 'plan.json', root / 'runs', knowledge_dir=root / 'knowledge', backup_dir=root / 'backup')
        with self.app.cond:
            self.app.load_plan()
            self.app.poll_log(initial=True)
            self.app.attach_run()

    def tearDown(self):
        self.tmp.cleanup()

    def test_plan_reads_the_facts_from_the_reference(self):
        if not self.app.catalog or not self.app.catalog.get('stats'):
            self.skipTest('каталог данных игры не собран')
        self.assertEqual(self.app.plan_problems, [])
        view = self.app.view()
        self.assertEqual([(b['id'], b['title'], b['must']) for b in view['bosses']],
                         [('boss-miller', 'Раздувшийся мельник (The Bloated Miller)', True), ('boss-beira', 'Бейра (Beira): +10% к холоду', False)])
        # редактор плана получает справочник (что предлагать шагу) и маршрут как он записан — ссылками
        d = self.app.build_view()
        self.assertEqual(([r['id'] for r in d['landmarks']], d['landmarks'][1]['zone']), (['boss-miller', 'boss-beira', 'points-una'], 'G1_2'))
        self.assertEqual(d['route']['goals'][1:], [{'id': 'boss-miller', 'need': 'riverbank'}, {'id': 'boss-beira', 'need': 'clearfell', 'from': 'riverbank'}])
        # запись справочника берут на шаг: в файле маршрута — одна строка со ссылкой
        r = d['route']
        ok, problems = self.app.save_build({'route': {'steps': r['steps'], 'goals': r['goals'] + [{'id': 'points-una', 'need': 'clearfell'}]}})
        self.assertEqual((ok, problems), (True, []))
        self.assertIn('    {"id": "points-una", "need": "clearfell"}\r\n  ]', self.route.read_bytes().decode('utf-8'))
        self.assertEqual(next(g for g in self.app.plan['goals'] if g['id'] == 'points-una')['title'], "Хижина Уны (Una's Hut): +2 очка")
        # факт игры в плане не правится — отказ, файл цел
        saved = self.route.read_bytes()
        d = self.app.build_view()
        goals = [dict(g, must=True) if g['id'] == 'points-una' else g for g in d['route']['goals']]
        ok, problems = self.app.save_build({'route': {'steps': d['route']['steps'], 'goals': goals}})
        self.assertEqual((ok, self.route.read_bytes() == saved), (False, True))
        self.assertIn('в плане он не правится', problems[0])

    def test_reference_is_reread_and_its_troubles_are_shown(self):
        if not self.app.catalog or not self.app.catalog.get('stats'):
            self.skipTest('каталог данных игры не собран')
        # справочник поправили — план перечитан без перезапуска
        self.marks.write_text(self.MARKS.replace('Раздувшийся мельник', 'Толстый мельник'), encoding='utf-8')
        os.utime(self.marks, (4102444800, 4102444800))
        with self.app.cond:
            self.assertTrue(self.app.load_plan())
        self.assertEqual(self.app.view()['bosses'][0]['title'], 'Толстый мельник (The Bloated Miller)')
        # записи, на которую ссылается маршрут, в справочнике не стало — об этом сказано, цели нет
        self.marks.write_text(self.MARKS.replace('    {"id": "boss-miller", "kind": "boss", "zone": "G1_1", "title": "Раздувшийся мельник (The Bloated Miller)", "must": true},\n', ''),
                              encoding='utf-8')
        os.utime(self.marks, (4102444801, 4102444801))
        with self.app.cond:
            self.assertTrue(self.app.load_plan())
        self.assertIn('Маршрут: записи «boss-miller» нет в справочнике игры', self.app.plan_problems)
        self.assertEqual([b['id'] for b in self.app.view()['bosses']], ['boss-beira'])
        # справочник составлен для другой версии игры — после обновления игры его сверяют заново
        self.marks.write_text(MARKS.replace('"game": "0.5.5.9"', '"game": "0.4.0"'), encoding='utf-8')
        os.utime(self.marks, (4102444802, 4102444802))
        with self.app.cond:
            self.assertTrue(self.app.load_plan())
        version = self.app.base_catalog['version']
        self.assertEqual('Справочник игры составлен для версии 0.4.0, а данные игры — версии %s: сверьте его' % version in self.app.plan_problems,
                         version != '0.4.0')


if __name__ == '__main__':
    unittest.main()
