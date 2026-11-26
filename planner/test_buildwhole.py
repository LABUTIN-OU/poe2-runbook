# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Sergei Labutin
# Additional terms under GPL-3.0 section 7: see NOTICE.md
"""То, что относится к билду целиком: название, герой (класс и вознесение) и свои статы из свойств игры;
сокращения баз защиты; классы героя в данных дерева.
Запуск: python -m unittest planner.test_buildwhole"""
import copy
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import buildcheck  # noqa: E402
import buildplan  # noqa: E402
import core  # noqa: E402
import gamedata  # noqa: E402
import itemstats  # noqa: E402
import slotwear  # noqa: E402
import test_buildplan as tb  # noqa: E402
import test_itemstats  # noqa: E402
import treegeo  # noqa: E402
import wearcheck  # noqa: E402

GEO = {'classes': {
    'Witch': {'id': 'Witch', 'base': [7, 7, 15], 'start': 'witch', 'ascendancies': [{'id': 'Witch1', 'name': 'Infernalist'},
                                                                                    {'id': 'Witch3', 'name': 'Lich'},
                                                                                    {'id': 'Witch3b', 'name': 'Abyssal Lich'}]},
    'Warrior': {'id': 'Warrior', 'base': [15, 7, 7], 'start': 'marauder', 'ascendancies': [{'id': 'Warrior1', 'name': 'Titan'}]}},
    'starts': {'witch': [7, 7, 15], 'marauder': [15, 7, 7]}, 'near': {'n1': {'marauder'}}, 'kind': {}}


def catalogue():
    """Учебный каталог со строкой «от # до #» и названиями классов героя."""
    cat = tb.catalogue()
    cat['mods']['Dmg|prefix|fire'] = test_itemstats.fam('Dmg', 'prefix', ['min_fire', 'max_fire'], [(1, [[1, 2], [3, 4]], ['bow'])],
                                                        lines=['min_fire max_fire'])
    cat['lang']['ru']['stats']['min_fire max_fire'] = ['Добавляет от # до # урона от огня к атакам']
    cat['lang']['ru']['heroClasses'] = {'Witch': 'Ведьма', 'Warrior': 'Воин', 'Infernalist': 'Инферналист'}
    return cat


class StatDefsTest(unittest.TestCase):
    def setUp(self):
        self.cat = catalogue()

    def test_what_can_be_picked(self):
        lines = gamedata.affix_lines(self.cat)
        # строки аффиксов вещей; те, что меняют саму вещь и уже идут в готовый стат («+# к броне» на доспехе), — нет
        self.assertEqual(lines['life'], ('life',))
        self.assertEqual(lines['min_fire max_fire'], ('min_fire', 'max_fire'))
        self.assertNotIn('local_armour', lines)
        self.assertNotIn('local_armour_pct', lines)
        rows = buildplan.prop_choices(self.cat)
        self.assertIn({'key': 'cold', 'text': '#% к сопротивлению холоду'}, rows)
        self.assertEqual([r['text'] for r in rows], sorted((r['text'] for r in rows), key=lambda t: t.lstrip('#%+ ').lower()))
        # строка без текста в данных игры в выбор не идёт
        self.cat['mods']['Odd|suffix|odd'] = test_itemstats.fam('Odd', 'suffix', ['odd'], [(1, [[1, 2]], ['belt'])])
        self.cat.pop('_affix_lines', None)
        self.assertNotIn('odd', [r['key'] for r in buildplan.prop_choices(self.cat)])
        self.assertEqual(gamedata.line_text(self.cat, 'odd'), 'odd')

    def test_records_are_checked(self):
        good = [{'id': 'elem', 'name': ' Стихии ', 'lines': ['cold', 'fire'], 'short': ' Стих '},
                {'id': 'atk_fire', 'name': 'Огонь к атакам', 'lines': ['min_fire max_fire']}]
        self.assertEqual(gamedata.stat_defs(self.cat, good), (
            [{'id': 'elem', 'name': 'Стихии', 'short': 'Стих', 'lines': ['cold', 'fire']},
             {'id': 'atk_fire', 'name': 'Огонь к атакам', 'lines': ['min_fire max_fire']}], []))
        self.assertEqual(gamedata.stat_defs(self.cat, None), ([], []))
        bad = lambda d: gamedata.stat_defs(self.cat, [d])   # noqa: E731
        self.assertEqual(bad({'id': 'life', 'name': 'x', 'lines': ['cold']}), ([], ['свой стат «x»: id «life» уже занят готовым статом']))
        self.assertEqual(bad({'id': 'Bad Id', 'name': 'x', 'lines': ['cold']})[1], ['свой стат: id — латинские буквы, цифры, подчёркивание'])
        self.assertEqual(bad({'id': 'a', 'name': '', 'lines': ['cold']})[1], ['свой стат «a»: нужно название не длиннее 60 знаков'])
        self.assertEqual(bad({'id': 'a', 'name': 'x', 'lines': []})[1], ['свой стат «x»: строки свойств — список без повторов, от одной до 12'])
        self.assertEqual(bad({'id': 'a', 'name': 'x', 'lines': ['cold', 'cold']})[1], ['свой стат «x»: строки свойств — список без повторов, от одной до 12'])
        self.assertEqual(bad({'id': 'a', 'name': 'x', 'lines': ['local_armour']})[1],
                         ['свой стат «x»: строки свойства «local_armour» среди аффиксов предметов в данных игры нет'])
        self.assertEqual(bad({'id': 'a', 'name': 'x', 'lines': ['cold', 'min_fire max_fire']})[1],
                         ['свой стат «x»: строку «от # до #» нельзя сложить в один стат со строкой из одного числа'])
        twice = gamedata.stat_defs(self.cat, [good[0], dict(good[0])])
        self.assertEqual((len(twice[0]), twice[1]), (1, ['свой стат «Стихии»: id «elem» уже занят']))
        self.assertEqual(gamedata.stat_defs(self.cat, 'нет')[1], ['свои статы: нужен список не длиннее 60'])

    def test_own_stat_joins_the_table(self):
        before = copy.deepcopy(self.cat['stats'])
        cat, problems = gamedata.with_stats(self.cat, [{'id': 'elem', 'name': 'Стихии', 'lines': ['cold', 'fire']},
                                                       {'id': 'atk_fire', 'name': 'Огонь к атакам', 'short': 'Огонь', 'lines': ['min_fire max_fire']},
                                                       {'id': 'life', 'name': 'x', 'lines': ['cold']}])
        self.assertEqual(problems, ['свой стат «x»: id «life» уже занят готовым статом'])
        table = cat['stats']['stats']
        # свойства игры — из строк стата; процентные строки — процентный стат; «от # до #» — среднее двух чисел
        self.assertEqual(table['elem'], {'ids': ['cold', 'fire'], 'own': True, 'unit': '%'})
        self.assertEqual(table['atk_fire'], {'ids': ['min_fire', 'max_fire'], 'own': True, 'scale': 0.5})
        self.assertEqual(cat['stats']['order'][-2:], ['elem', 'atk_fire'])
        self.assertEqual(cat['lang']['ru']['statNames']['atk_fire'], ['Огонь к атакам', 'Огонь'])
        # исходный каталог не тронут; без своих статов возвращается он сам
        self.assertEqual(self.cat['stats'], before)
        self.assertNotIn('elem', self.cat['lang']['ru']['statNames'])
        self.assertIs(gamedata.with_stats(self.cat, [])[0], self.cat)
        self.assertIs(gamedata.with_stats(self.cat, None)[0], self.cat)
        # каталог без своих статов — для проверки нового их набора
        self.assertEqual(sorted(buildplan.base_of(cat)['stats']['stats']), sorted(before['stats']))
        self.assertIs(buildplan.base_of(self.cat), self.cat)

    def test_an_item_is_counted_by_an_own_stat(self):
        cat, _ = gamedata.with_stats(self.cat, [{'id': 'elem', 'name': 'Стихии', 'lines': ['cold', 'fire']}])
        p = test_itemstats.passport(test_itemstats.BODY, cat)
        # холод с руны и с суффикса и огонь с суффикса: 36 + 7 + 6; готовые статы считаются как раньше
        self.assertEqual(p['stats']['elem'], 49)
        self.assertEqual(p['stats']['res_cold'], test_itemstats.passport(test_itemstats.BODY, self.cat)['stats']['res_cold'])
        self.assertNotIn('elem', test_itemstats.passport(test_itemstats.BODY, self.cat)['stats'])
        row = [r for r in itemstats.view(cat, itemstats_item(cat))['rows'] if r['id'] == 'elem'][0]
        self.assertEqual((row['name'], row['value'], row['unit']), ('Стихии', 49, '%'))

    def test_plan_keeps_hero_and_own_stats(self):
        raw = json.loads(json.dumps(tb.PLAN))
        raw['hero'] = {'class': ' Witch ', 'ascendancy': '', 'level': 5}
        raw['statDefs'] = [{'id': 'elem', 'name': 'Стихии', 'lines': ['cold', 'fire']}, 'мусор']
        raw['stages'][0]['stats'] = list(raw['stages'][0].get('stats') or []) + ['elem']
        cat, more = gamedata.with_stats(self.cat, raw['statDefs'])
        plan, problems = core.norm_plan(raw, cat)
        self.assertEqual((problems, more), ([], ['свой стат: id — латинские буквы, цифры, подчёркивание']))
        self.assertEqual(plan['hero'], {'class': 'Witch'})
        self.assertEqual(plan['statDefs'], [{'id': 'elem', 'name': 'Стихии', 'lines': ['cold', 'fire']}])
        # без своих статов в каталоге этап со ссылкой на такой стат — замечание
        self.assertIn('стата «elem» нет', ' '.join(core.norm_plan(raw, self.cat)[1]))
        self.assertEqual(core.norm_plan({}, self.cat)[0]['hero'], {})


def itemstats_item(cat):
    import itemcopy
    return itemcopy.identify(cat, itemcopy.parse(test_itemstats.BODY))


class RouteStepsTest(unittest.TestCase):
    """Зона может стоять в нескольких шагах; проверка называет шаг, который из-за этого не наступит сам."""

    STEPS = [{'id': 'yard', 'zone': 'G1_7', 'name': 'Кладбище'},
             {'id': 'vault', 'zone': 'G1_8', 'name': 'Мавзолей'},
             {'id': 'tomb', 'zone': 'G1_9', 'name': 'Гробница', 'also': ['G1_7']},
             {'id': 'boss', 'zone': 'G1_7', 'name': 'Лакланн'},
             {'id': 'hunt', 'zone': 'G1_11', 'name': 'Угодья'}]

    def found(self, steps):
        return [(f['level'], f['step'], f['text']) for f in buildcheck.route_findings({'steps': steps})]

    def test_step_that_cannot_start(self):
        # зона шага стоит у шага перед ним в «ещё зоны»: с него в неё и входят — программа останется на нём
        self.assertEqual(self.found(self.STEPS), [(
            'bad', 'boss', 'Шаг сам не наступит: его зона стоит в «ещё зоны» шага «Гробница» перед ним — программа останется '
                           'на том шаге. Уберите её оттуда')])
        # два шага подряд с одной зоной — то же
        twice = [self.STEPS[0], dict(self.STEPS[3])]
        self.assertEqual(self.found(twice), [
            ('bad', 'boss', 'Шаг сам не наступит: у него та же зона, что у шага «Кладбище» перед ним, — программа останется '
                            'на том шаге')])

    def test_revisit_far_ahead_is_fine(self):
        # шаг повторного захода наступает только следующим: заход в его зону с дальнего шага шаг не меняет —
        # прыжка мимо шагов между ними нет, и «ещё зоны» ради этого не нужны: замечаний нет
        steps = [dict(s) for s in self.STEPS]
        del steps[2]['also']
        self.assertEqual(self.found(steps), [])
        self.assertEqual(self.found([{'id': 'a', 'zone': 'G1_4'}, {'id': 'b', 'zone': 'G1_5'}, {'id': 'c', 'zone': 'G1_4'}]), [])
        far = [{'id': 'a', 'zone': 'Z1', 'name': 'А'}, {'id': 'b', 'zone': 'Z2', 'name': 'Б'}, {'id': 'e', 'event': 'ascend', 'name': 'В'},
               {'id': 'c', 'zone': 'Z3', 'name': 'Г'}, {'id': 'd', 'zone': 'Z1', 'name': 'Д'}]
        self.assertEqual(self.found(far), [])

    def test_point_is_named_by_its_zone(self):
        plan, _ = core.norm_plan({'steps': [{'id': 'a', 'zone': 'G1_1', 'name': 'Берег',
                                             'touch': [{'zone': 'G1_2'}, {'zone': 'G1_3', 'name': 'Своё'}, {'zone': 'G1_4'}]}],
                                  'goals': []})
        view = core.derive(plan, core.Run(), 0, zone_names={'G1_2': 'Клирфелл', 'G1_3': 'Другое'})
        # название зоны — из лога и данных игры; название из старого файла стоит, пока лог зону не назвал; зону
        # не знают — её код
        self.assertEqual([t['name'] for t in view['cards'][0]['touch']], ['Клирфелл', 'Своё', 'G1_4'])


class GameFactsTest(unittest.TestCase):
    """Справка игры о названных в плане вещах берётся из данных игры, а не из полей плана."""

    def setUp(self):
        self.cat = {
            'gems': {
                'SkillGemFrostBomb': {'name': 'Frost Bomb', 'type': 'active', 'level': 3},
                'SkillGemWarriorWeaponSkill': {'name': 'Skeletal Warrior', 'type': 'active', 'level': 0},
                'SupportGemBidding': {'name': 'Bidding I', 'type': 'support', 'level': 2},
            },
            'bases': {
                'Sceptres/One': {'name': 'Rattling Sceptre', 'class': 'Sceptre', 'level': 1, 'grants': ['SkillGemWarriorWeaponSkill']},
                'Crossbows/Two': {'name': 'Sturdy Crossbow', 'class': 'Crossbow', 'level': 10},
            },
            'rules': {'gemHero': [0, 3, 6, 10]},
            'lang': {'ru': {'bases': {'Rattling Sceptre': 'Гремящий скипетр'}}},
        }
        self.raw = {
            'slots': [{'id': 'weapon', 'classes': ['Crossbow', 'Sceptre']}],
            'goals': [
                {'id': 'bow', 'slot': 'weapon', 'title': 'Прочный самострел (Sturdy Crossbow)', 'opens': 99},
                {'id': 'sceptre', 'slot': 'weapon', 'title': 'Гремящий скипетр (Rattling Sceptre)', 'opens': 5},
                {'id': 'any', 'slot': 'weapon', 'title': 'любой', 'opens': 7},
                {'id': 'stat', 'slot': 'weapon', 'part': 'spirit', 'title': 'от 120'},
                {'id': 'skill-bomb', 'kind': 'skill', 'title': 'Морозная бомба (Frost Bomb)', 'gemFrom': 1},
                {'id': 'skill-warrior', 'kind': 'skill', 'title': 'Приспешник скелет-воин (Skeletal Warrior)'},
                {'id': 'skill-own', 'kind': 'skill', 'title': 'Призрак: Подвижник (Spectre: Zealot)', 'gemFrom': 7},
                {'id': 'support', 'kind': 'support', 'for': 'skill-bomb', 'title': 'Приказание I (Bidding I)'},
            ],
        }

    def test_name_from_the_game(self):
        self.assertEqual(gamedata.english('Морозная бомба (Frost Bomb)'), 'Frost Bomb')
        self.assertEqual(gamedata.english('Frost Bomb'), 'Frost Bomb')
        # название с припиской — не название из игры: остаётся как есть
        self.assertEqual(gamedata.english('Ростовой щит (Tower Shield): жёлтый'), 'Ростовой щит (Tower Shield): жёлтый')
        self.assertEqual(gamedata.english(None), '')

    def test_facts_come_from_the_game(self):
        before = copy.deepcopy(self.raw)
        out = gamedata.with_facts(self.cat, self.raw)
        got = {g['id']: g for g in out['goals']}
        # умение из данных игры: стартовый уровень камня — из игры, что бы ни вписал автор
        self.assertEqual(got['skill-bomb']['gemFrom'], 3)
        # умение, которое даёт база предмета: цель плана с такой базой; камня у него нет — уровня тоже
        self.assertEqual((got['skill-warrior'].get('grantedBy'), got['skill-warrior'].get('gemFrom')), ('sceptre', None))
        # умение, которого игра не знает, — как записал автор
        self.assertEqual((got['skill-own']['gemFrom'], got['skill-own'].get('grantedBy')), (7, None))
        # база из данных игры: уровень зоны — из игры; с первого уровня — не пишется; не база — как записано
        self.assertEqual((got['bow']['opens'], got['sceptre'].get('opens'), got['any']['opens']), (10, None, 7))
        self.assertEqual((got['stat'], got['support']), (self.raw['goals'][3], self.raw['goals'][7]))
        # таблица «уровень героя для уровня камня» — из правил каталога, если в плане её нет
        self.assertEqual(out['gemLevels'], [0, 3, 6, 10])
        self.assertEqual(gamedata.with_facts(self.cat, dict(self.raw, gemLevels=[0, 2]))['gemLevels'], [0, 2])
        # исходный план не меняется; без каталога и без целей — тот же план
        self.assertEqual(self.raw, before)
        self.assertIs(gamedata.with_facts(None, self.raw), self.raw)
        self.assertEqual(gamedata.with_facts(self.cat, {'title': 'x'}), {'title': 'x'})

    def test_page_gets_the_facts_about_skills(self):
        self.assertEqual(buildplan.gem_facts(self.cat), {
            'Frost Bomb': {'level': 3},
            'Skeletal Warrior': {'level': 0, 'bases': ['Гремящий скипетр (Rattling Sceptre)']}})
        self.assertEqual(buildplan.gem_facts(None), {})

    def test_spirit_and_sockets_come_from_the_game(self):
        """Резерв духа умения и условие гнезда камня поддержки — из данных игры; гнездо — по порядку камней в плане."""
        cat = copy.deepcopy(self.cat)
        cat['gems'].update({
            'SkillGemSkeletalReaver': {'name': 'Skeletal Reaver', 'type': 'active', 'level': 3, 'spirit': [90, 65, 50, 41]},
            'SkillGemAscendancySummonSandDjinn': {'name': 'Kelari, the Tainted Sands', 'type': 'active', 'level': 0,
                                                  'ascendancy': True},
        })
        cat['rules']['gemSockets'] = {'level': {'3': 36, '4': 64, '5': 90},
                                      'orbs': {'3': "Lesser Jeweller's Orb", '4': "Greater Jeweller's Orb",
                                               '5': "Perfect Jeweller's Orb"}}
        cat['lang']['ru']['bases']["Greater Jeweller's Orb"] = 'Большая сфера златокузнеца'
        sup = lambda gid, skill, part: {'id': gid, 'kind': 'support', 'for': skill, 'part': part, 'title': gid}
        raw = {'slots': [], 'goals': [
            {'id': 'skill-reaver', 'kind': 'skill', 'title': 'Скелет-разоритель (Skeletal Reaver)'},
            {'id': 'skill-kelari', 'kind': 'skill', 'title': 'Келари (Kelari)'},
            sup('r1', 'skill-reaver', 'a'), sup('r2', 'skill-reaver', 'b'), sup('r1b', 'skill-reaver', 'a'),
            sup('r3', 'skill-reaver', 'c'), sup('r4', 'skill-reaver', 'd'),
            sup('k1', 'skill-kelari', 'a'), sup('k2', 'skill-kelari', 'b'), sup('k3', 'skill-kelari', 'c'),
            {'id': 'gem5-reaver', 'kind': 'gem', 'part': 'level', 'for': 'skill-reaver', 'title': '5'},
        ]}
        got = {g['id']: g for g in gamedata.with_facts(cat, raw)['goals']}
        # дух — по уровням камня; у умения восхождения его нет, а камень узнан по короткому имени
        self.assertEqual((got['skill-reaver']['spirit'], got['skill-kelari'].get('spirit')), ([90, 65, 50, 41], None))
        # замена (та же часть) стоит в том же гнезде; с 3-го гнезда — условие игры: у камня умения сфера…
        self.assertEqual([got[x].get('socket') for x in ('r1', 'r2', 'r1b', 'k1', 'k2')], [None] * 5)
        self.assertEqual(got['r3']['socket'], {'n': 3, 'orb': "Lesser Jeweller's Orb"})
        self.assertEqual(got['r4']['socket'], {'n': 4, 'orb': "Большая сфера златокузнеца (Greater Jeweller's Orb)"})
        # …у умения восхождения — уровень героя; уровень камня — не гнездо
        self.assertEqual(got['k3']['socket'], {'n': 3, 'hero': 36})
        self.assertNotIn('socket', got['gem5-reaver'])
        # страница «Билд»: гнёзда умения восхождения (дух зависит от уровня камня — в справке его нет)
        facts = buildplan.gem_facts(cat)
        self.assertEqual((facts['Kelari']['sockets'], facts['Kelari']['level'], 'spirit' in facts['Skeletal Reaver']),
                         ({'3': 36, '4': 64, '5': 90}, 0, False))


class NamedBaseTest(unittest.TestCase):
    """Что о предмете цели говорит её название: базу из данных игры — точную или любую из семейства; от неё
    рисунок цели и то, каким предмет лежит на земле (образец для проверки фильтра)."""

    def setUp(self):
        base = lambda name, cls, level, icon, tags=(), **props: {       # noqa: E731
            'name': name, 'class': cls, 'level': level, 'icon': icon, 'tags': list(tags), 'props': props or None}
        self.cat = {
            'bases': {
                't1': base('Splintered Tower Shield', 'Shield', 1, 'art-tower01', ['str_armour', 'armour'], armour=18),
                't4': base('Barricade Tower Shield', 'Shield', 16, 'art-tower04', ['str_armour', 'armour'], armour=62),
                't5': base('Effigial Tower Shield', 'Shield', 21, 'art-tower05', ['str_armour', 'armour'], armour=76),
                't4r': base('Runemastered Barricade Tower Shield', 'Shield', 18, 'art-tower04', ['str_armour', 'armour', 'runeforged'], armour=94),
                'tg': base('Golden Tower Shield', 'Shield', 1, 'art-tower09', ['armour', 'demigods']),
                'c1': base('Blazon Crest Shield', 'Shield', 1, 'art-crest01', ['str_int_armour', 'armour'], armour=10, energy_shield=6),
                'c3': base('Emblem Crest Shield', 'Shield', 16, 'art-crest03', ['str_int_armour', 'armour'], armour=34, energy_shield=12),
                'f1': base('Twig Focus', 'Focus', 1, 'art-focus01', ['int_armour', 'armour'], energy_shield=12),
                's1': base('Rattling Sceptre', 'Sceptre', 1, 'art-sceptre01', ['sceptre']),
                'x1': base('Tower Shield Charm', 'Charm', 1, 'art-charm01'),
            },
            'lang': {'ru': {'bases': {
                'Splintered Tower Shield': 'Обшарпанный ростовой щит', 'Barricade Tower Shield': 'Баррикадный ростовой щит',
                'Effigial Tower Shield': 'Тотемный ростовой щит', 'Runemastered Barricade Tower Shield': 'Рунномастерский баррикадный ростовой щит',
                'Golden Tower Shield': 'Золотой ростовой щит', 'Blazon Crest Shield': 'Гербовый щит',
                'Emblem Crest Shield': 'Гербовый щит с эмблемой', 'Twig Focus': 'Фокус из прутьев',
                'Rattling Sceptre': 'Гремящий скипетр', 'Tower Shield Charm': 'Оберег «Ростовой щит»'}}},
            'areas': {'Z1': {'level': 1}, 'Z16': {'level': 16}, 'Town': {'level': 40, 'town': True}, 'Z22': {'level': 22}},
        }
        self.hand = ['Shield', 'Focus']

    def names(self, title, classes=None):
        exact, recs = gamedata.named_bases(self.cat, title, classes)
        return exact, sorted(b['name'] for b in recs)

    def test_which_bases_a_name_means(self):
        # название читается так же, как при узнавании скопированного предмета
        for title in ('Ростовой щит (Tower Shield)', 'Ростовой щит (Tower Shield): жёлтый', 'Гербовый щит', 'любой', '', None):
            self.assertEqual(gamedata.title_names(title), slotwear._names(title))
        # точное название — сама база; приписка автора делу не мешает
        self.assertEqual(self.names('Гремящий скипетр (Rattling Sceptre)'), (True, ['Rattling Sceptre']))
        self.assertEqual(self.names('Гербовый щит с эмблемой (Emblem Crest Shield): жёлтый', self.hand), (True, ['Emblem Crest Shield']))
        # общее название — все базы, в чьём названии оно есть; вариант, который делают (runeforged), и база наград
        # (demigods) — не находки; базы чужих классов — не в счёт
        self.assertEqual(self.names('Ростовой щит (Tower Shield)', self.hand),
                         (False, ['Barricade Tower Shield', 'Effigial Tower Shield', 'Splintered Tower Shield']))
        self.assertEqual(self.names('Гербовый щит (Crest Shield)', self.hand), (False, ['Blazon Crest Shield', 'Emblem Crest Shield']))
        self.assertIn('Tower Shield Charm', self.names('Ростовой щит (Tower Shield)')[1])
        # есть только варианты — тогда они
        only = dict(self.cat, bases={k: v for k, v in self.cat['bases'].items() if k == 't4r'})
        self.assertEqual([b['name'] for b in gamedata.named_bases(only, 'Ростовой щит', self.hand)[1]], ['Runemastered Barricade Tower Shield'])
        # чего игра не знает — пусто: «любой», своё название, слишком короткое слово, пустой каталог
        for title in ('любой', 'жёлтый щит', 'щи', '', None):
            self.assertEqual(self.names(title, self.hand), (False, []))
        self.assertEqual(gamedata.named_bases(None, 'Ростовой щит'), (False, []))
        # классы слота — по его периодам; у слота старого вида — его список
        self.assertEqual(gamedata.slot_classes({'wear': [{'classes': ['Sceptre']}, {'from': 'a', 'classes': ['Shield', 'Sceptre']}]}),
                         ['Sceptre', 'Shield'])
        self.assertEqual((gamedata.slot_classes({'classes': ['Belt']}), gamedata.slot_classes(None)), (['Belt'], []))

    def test_which_base_drops_at_a_zone_level(self):
        tower = gamedata.named_bases(self.cat, 'Ростовой щит (Tower Shield)', self.hand)[1]
        at = lambda level: (gamedata.base_at(tower, level) or {}).get('name')      # noqa: E731
        self.assertEqual([at(1), at(15), at(16), at(20), at(21), at(80)],
                         ['Splintered Tower Shield', 'Splintered Tower Shield', 'Barricade Tower Shield', 'Barricade Tower Shield',
                          'Effigial Tower Shield', 'Effigial Tower Shield'])
        # уровень не назван — младшая; ни одна ещё не падает — ничего
        self.assertEqual((gamedata.base_at(tower)['name'], gamedata.base_at(tower[1:], 0), gamedata.base_at([])), ('Splintered Tower Shield', None, None))

    def test_picture_follows_the_name(self):
        raw = {
            'steps': [{'id': 'a', 'zone': 'Z1'}, {'id': 'b', 'zone': 'Z16'}, {'id': 'town', 'zone': 'Town'}, {'id': 'event'}, {'id': 'c', 'zone': 'Z22'}],
            'slots': [{'id': 'offhand', 'wear': [{'classes': ['Sceptre']}, {'from': 'b', 'classes': ['Shield', 'Focus']}]}],
            'goals': [
                {'id': 'exact', 'slot': 'offhand', 'title': 'Гремящий скипетр (Rattling Sceptre)', 'icon': 'item-old'},
                {'id': 'early', 'slot': 'offhand', 'title': 'Ростовой щит (Tower Shield)', 'icon': 'type-tower-shield', 'need': 'a'},
                {'id': 'mid', 'slot': 'offhand', 'title': 'Ростовой щит (Tower Shield)', 'use': 'event'},
                {'id': 'late', 'slot': 'offhand', 'title': 'Гербовый щит (Crest Shield): жёлтый', 'icon': 'type-tower-shield', 'need': 'c', 'use': 'a'},
                {'id': 'free', 'slot': 'offhand', 'title': 'Ростовой щит (Tower Shield)'},
                {'id': 'own', 'slot': 'offhand', 'title': 'жёлтый щит', 'icon': 'type-tower-shield'},
                {'id': 'any', 'slot': 'offhand', 'title': 'любой', 'any': True},
                {'id': 'stat', 'slot': 'offhand', 'part': 'es', 'title': 'от 270', 'icon': 'type-x'},
                {'id': 'other', 'title': 'Ростовой щит (Tower Shield)'},
            ]}
        before = copy.deepcopy(raw)
        got = {g['id']: g.get('icon') for g in gamedata.with_facts(self.cat, raw)['goals']}
        self.assertEqual(got, {
            'exact': 'art-sceptre01',          # точная база: её рисунок, что бы ни было записано
            'early': 'art-tower01',            # общее название: база, что падает к шагу срока (зона 1)
            'mid': 'art-tower04',              # к шагу без зоны герой видел зону 16; город в счёт не идёт
            'late': 'art-crest03',             # срок важнее шага «в ходу»; переименованная цель — рисунок нового названия
            'free': 'art-tower01',             # шаг не назван — младшая база
            'own': 'type-tower-shield',        # название не из игры — рисунок как записан
            'any': None, 'stat': 'type-x', 'other': None})
        self.assertEqual(raw, before)

    def test_what_lies_on_the_ground(self):
        goal = lambda title, **more: dict({'id': 'g', 'slot': 'offhand', 'title': title}, **more)       # noqa: E731
        on = lambda g, level: (lambda known, b: (known, b and b['name']))(*gamedata.ground_base(self.cat, g, self.hand, level))   # noqa: E731
        # общее название: старшая из баз, что здесь падают; точное: сама база — когда уже падает
        self.assertEqual([on(goal('Ростовой щит (Tower Shield)'), n) for n in (2, 16, 30)],
                         [(True, 'Splintered Tower Shield'), (True, 'Barricade Tower Shield'), (True, 'Effigial Tower Shield')])
        self.assertEqual([on(goal('Гербовый щит с эмблемой (Emblem Crest Shield)'), n) for n in (15, 16)],
                         [(True, None), (True, 'Emblem Crest Shield')])
        # названия игра не знает; цель по стату; «любой»; цель не предмет слота — образец остаётся как записан
        for g in (goal('жёлтый щит'), goal('от 270', part='es'), goal('любой', any=True), {'id': 'x', 'title': 'Ростовой щит'}):
            self.assertEqual(on(g, 30), (False, None))
        # защита базы для условий фильтра: у доспеха с числами — они, чего нет — ноль; иначе пусто
        b = self.cat['bases']
        self.assertEqual(gamedata.base_defences(b['c3']), {'BaseArmour': 34, 'BaseEvasion': 0, 'BaseEnergyShield': 12})
        self.assertEqual(gamedata.base_defences(b['t4']), {'BaseArmour': 62, 'BaseEvasion': 0, 'BaseEnergyShield': 0})
        self.assertEqual((gamedata.base_defences(b['s1']), gamedata.base_defences(b['tg'])), ({}, {}))
        # класс, каким его пишут фильтры, — из таблицы классов игры в каталоге; нет таблицы или класса — ничего
        named = dict(self.cat, lang=dict(self.cat['lang'], en={'classNames': {'Shield': 'Shields', 'Focus': 'Foci'}}))
        self.assertEqual([gamedata.filter_class(named, c) for c in ('Shield', 'Focus', 'Sceptre', None)], ['Shields', 'Foci', None, None])
        self.assertEqual((gamedata.filter_class(self.cat, 'Shield'), gamedata.filter_class(None, 'Shield')), (None, None))

    def test_editor_counts_the_same_bases(self):
        """Редактор считает базы общего названия сам — по тем же правилам: вариант, который делают из базы, у него
        помечен (made), базы наград в выдаче нет вовсе."""
        rows = {r['name']: r for r in buildplan.class_bases(self.cat)['Shield']}
        self.assertEqual(sorted(n for n, r in rows.items() if r.get('made')), ['Рунномастерский баррикадный ростовой щит (Runemastered Barricade Tower Shield)'])
        self.assertNotIn('Золотой ростовой щит (Golden Tower Shield)', rows)
        self.assertNotIn('made', rows['Баррикадный ростовой щит (Barricade Tower Shield)'])
        family = [n for n, r in rows.items() if 'ростовой щит' in n.split(' (')[0].lower() and not r.get('made')]
        self.assertEqual(sorted(x.split(' (')[1].rstrip(')') for x in family),
                         sorted(b['name'] for b in gamedata.named_bases(self.cat, 'Ростовой щит (Tower Shield)', ['Shield'])[1]))




class HeroTest(unittest.TestCase):
    def test_classes_come_from_the_tree_data(self):
        data = {'classes': [
            {'name': 'Marauder', 'base_str': 15, 'base_dex': 7, 'base_int': 7, 'ascendancies': []},
            {'name': 'Witch', 'base_str': 7, 'base_dex': 7, 'base_int': 15,
             'ascendancies': [{'id': 'Witch1', 'name': 'Infernalist'}, {'id': 'Witch2', 'name': None}]},
            {'name': 'Warrior', 'base_str': 15, 'base_dex': 7, 'base_int': 7, 'ascendancies': [{'id': 'Warrior1', 'name': 'Titan'}]}],
            'nodes': {'1': {'id': 'marauder1', 'x': 0, 'y': 0, 'classStartIndex': [0, 2], 'name': 'MARAUDER'},
                      '2': {'id': 'witch1', 'x': 5, 'y': 5, 'classStartIndex': [1], 'name': 'WITCH'},
                      '3': {'id': 'n', 'x': 1, 'y': 1, 'name': 'Life'}},
            'edges': [{'from': '1', 'to': '3'}]}
        geo = treegeo.build(data)
        # класс без вознесений (в игре за него не играют) и вознесение без имени (заготовка) не идут
        self.assertEqual(geo['classes'], [
            {'id': 'Witch', 'base': [7, 7, 15], 'start': 'witch1', 'ascendancies': [{'id': 'Witch1', 'name': 'Infernalist'}]},
            {'id': 'Warrior', 'base': [15, 7, 7], 'start': 'marauder1', 'ascendancies': [{'id': 'Warrior1', 'name': 'Titan'}]}])
        self.assertEqual(geo['starts'], {'marauder1': [15, 7, 7], 'witch1': [7, 7, 15]})

    def test_choices_for_the_page(self):
        got = buildplan.hero_choices(catalogue(), GEO)
        self.assertEqual(got[0], {'id': 'Witch', 'name': 'Ведьма', 'base': {'str': 7, 'dex': 7, 'int': 15}, 'ascendancies': [
            {'id': 'Infernalist', 'name': 'Инферналист', 'code': 'Witch1'}, {'id': 'Lich', 'name': 'Lich', 'code': 'Witch3'},
            {'id': 'Abyssal Lich', 'name': 'Abyssal Lich', 'code': 'Witch3b'}]})
        self.assertEqual(buildplan.hero_choices(catalogue(), None), [])

    def test_hero_is_checked(self):
        def hero(raw, geo=GEO):
            problems = []
            return buildplan.check_hero(raw, geo, problems), problems
        self.assertEqual(hero({'class': 'Witch', 'ascendancy': 'Lich'}), ({'class': 'Witch', 'ascendancy': 'Lich'}, []))
        self.assertEqual(hero({'class': 'Witch', 'ascendancy': ''}), ({'class': 'Witch'}, []))            # без вознесения — можно
        self.assertEqual(hero({}), ({}, []))                                                              # и вовсе не назван
        self.assertEqual(hero({'class': 'Nobody'})[1], ['герой: класса «Nobody» нет в данных дерева'])
        self.assertEqual(hero({'class': 'Witch', 'ascendancy': 'Titan'})[1], ['герой: у класса «Witch» нет восхождения «Titan»'])
        self.assertEqual(hero({'ascendancy': 'Titan'})[1], ['герой: восхождение названо, а класс — нет'])
        self.assertEqual(hero({'class': 'Witch', 'level': 3})[1], ['герой: у героя есть класс (class) и восхождение (ascendancy)'])
        self.assertEqual(hero({'class': 5})[1], ['герой: класс и восхождение — названия из данных дерева'])
        self.assertEqual(hero({'class': 'Witch'}, None)[1], ['герой: нет данных дерева (planner/static/tree.json) — выбрать класс не из чего'])

    def test_defence_buttons_get_short_names(self):
        cat = catalogue()
        # без сокращений в таблице статов подпись — название целиком
        self.assertEqual([k['short'] for k in buildplan.kinds(cat)], ['Броня', 'Энергощит', 'Броня / Энергощит'])
        cat = catalogue()
        cat['stats']['stats']['armour']['abbr'], cat['stats']['stats']['es']['abbr'] = 'AR', 'ES'
        self.assertEqual([(k['short'], k['label']) for k in buildplan.kinds(cat)],
                         [('AR', 'Броня'), ('ES', 'Энергощит'), ('AR/ES', 'Броня / Энергощит')])

    def test_class_named_by_the_build_gives_the_hero_attributes(self):
        take = [{'type': 'passive', 'op': 'take', 'id': 'n1'}]
        # дерево растёт от старта воина; билд называет ведьму — её атрибуты и идут в счёт
        self.assertEqual(wearcheck.tree_state({}, GEO, take)['base'], {'str': 15, 'dex': 7, 'int': 7})
        self.assertEqual(wearcheck.tree_state({}, GEO, take, cls='Witch')['base'], {'str': 7, 'dex': 7, 'int': 15})
        self.assertEqual(wearcheck.tree_state({}, GEO, [], cls='Witch')['notes'], [])


class FileTest(unittest.TestCase):
    def test_one_line_sections(self):
        text = tb.GOALS_BUILD
        hero = {'class': 'Witch', 'ascendancy': 'Lich'}
        out = buildplan.splice_value(text, 'hero', hero)
        # раздела не было — встал одной строкой перед слотами; остальной текст не изменился
        self.assertEqual(out, text.replace('  "slots": [', '  "hero": {"class": "Witch", "ascendancy": "Lich"},\n  "slots": [', 1))
        self.assertEqual(list(json.loads(out))[:4], ['version', 'title', 'hero', 'slots'])
        again = buildplan.splice_value(out, 'hero', {'class': 'Warrior'})
        self.assertEqual(again, text.replace('  "slots": [', '  "hero": {"class": "Warrior"},\n  "slots": [', 1))
        self.assertEqual(buildplan.splice_value(out, 'hero', hero), out)                       # то же значение — знак в знак
        self.assertEqual(buildplan.splice_value(text, 'title', 'Другой билд'), text.replace('"title": "Учебный билд"', '"title": "Другой билд"', 1))
        crlf = text.replace('\n', '\r\n')
        self.assertEqual(buildplan.splice_value(crlf, 'hero', hero).replace('\r\n', '\n'), out)
        # раздел, записанный не в одну строку, со страницы не правится
        odd = text.replace('  "slots": [', '  "hero": {\n    "class": "Witch"\n  },\n  "slots": [', 1)
        with self.assertRaises(ValueError):
            buildplan.splice_value(odd, 'hero', hero)

    def test_whole_build_sections_are_written(self):
        defs = [{'id': 'elem', 'name': 'Стихии', 'lines': ['cold', 'fire']}]
        out = buildplan.render_sections(tb.GOALS_BUILD, {'title': 'Новый', 'hero': {'class': 'Witch'}, 'statDefs': defs})
        got = json.loads(out)
        self.assertEqual((got['title'], got['hero'], got['statDefs']), ('Новый', {'class': 'Witch'}, defs))
        self.assertIn('  "statDefs": [\n    {"id": "elem", "name": "Стихии", "lines": ["cold", "fire"]}\n  ]', out)
        want = json.loads(tb.GOALS_BUILD)
        self.assertEqual({k: v for k, v in got.items() if k not in ('title', 'hero', 'statDefs')},
                         {k: v for k, v in want.items() if k != 'title'})
        self.assertEqual(buildplan.render_sections(out, {'title': 'Новый', 'hero': {'class': 'Witch'}, 'statDefs': defs}), out)

    def test_page_sends_them_with_the_rest(self):
        build, plan, cat = tb.goals_state()
        cat['lang']['ru']['stats'].setdefault('cold', ['#% к сопротивлению холоду'])
        defs = [{'id': 'elem', 'name': 'Стихии', 'lines': ['cold', 'fire']}]
        merged, _ = gamedata.with_stats(cat, defs)
        stages = [{'id': 'start', 'name': 'Кампания', 'stats': ['res_cold', 'life', 'elem']}]
        sec, problems = buildplan.check({'title': ' Новый ', 'hero': {'class': 'Witch', 'ascendancy': 'Lich'}, 'statDefs': defs, 'stages': stages},
                                        plan, merged, build=build, route=tb.GOALS_ROUTE, geo=GEO)
        self.assertEqual(problems, [])
        self.assertEqual((sec['title'], sec['hero'], sec['statDefs']), ('Новый', {'class': 'Witch', 'ascendancy': 'Lich'}, defs))
        self.assertEqual(sec['stages'][0]['stats'], ['res_cold', 'life', 'elem'])
        # без своего стата в каталоге этап на него сослаться не может
        self.assertEqual(buildplan.check({'stages': stages}, plan, cat, build=build)[1], ['этап «Кампания»: стата «elem» нет в данных игры'])
        bad = buildplan.check({'title': '', 'hero': {'class': 'Nobody'}, 'statDefs': [{'id': 'life', 'name': 'x', 'lines': ['cold']}]},
                              plan, cat, build=build, geo=GEO)
        self.assertEqual(bad, ({}, ['название билда — текст не длиннее 80 знаков', 'герой: класса «Nobody» нет в данных дерева',
                                    'свой стат «x»: id «life» уже занят готовым статом']))
        # что отдаётся странице: как записано в файле и из чего выбирать
        d = buildplan.describe(merged, dict(plan, hero={'class': 'Witch'}), {}, build=dict(build, hero={'class': 'Witch'}, statDefs=defs),
                               route=tb.GOALS_ROUTE, geo=GEO)
        self.assertEqual((d['buildTitle'], d['hero'], d['statDefs']), ('Учебный билд', {'class': 'Witch'}, defs))
        self.assertEqual([c['id'] for c in d['heroes']], ['Witch', 'Warrior'])
        cat_ = {c['id']: c for c in d['catalog']}
        self.assertEqual((cat_['elem']['name'], cat_['elem'].get('own'), cat_['life'].get('own')), ('Стихии', True, None))
        self.assertEqual(cat_['elem']['parts']['lines'], ['#% к сопротивлению холоду', '#% к сопротивлению огню'])
        self.assertIn('cold', [r['key'] for r in d['props']])


class ServerTest(unittest.TestCase):
    """Название, герой и свои статы через программу: план из частей, каталог настоящий."""

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

    def test_hero_title_and_own_stats_are_saved(self):
        if not self.app.catalog or not self.app.catalog.get('stats') or not (self.app.tree_geo('tree') or {}).get('classes'):
            self.skipTest('каталог данных игры или данные дерева не собраны')
        d = self.app.build_view()
        self.assertEqual((d['buildTitle'], d['hero'], d['statDefs'], d['problems']), ('Учебный билд', {}, [], []))
        self.assertIn('Sorceress', [c['id'] for c in d['heroes']])
        self.assertEqual([k['short'] for k in d['kinds']][:3], ['AR', 'EV', 'ES'])
        # то же короткое название — у рода базы в строке сравнения вещей («база по плану»)
        self.assertEqual([buildplan.kind_short(self.app.catalog, k) for k in ('str_int_armour', 'int_armour', None, 'ring')],
                         ['AR/ES', 'ES', None, None])
        prop = next(r for r in d['props'] if r['key'] == 'chaos_damage_+%')
        self.assertEqual(prop['text'], '#% увеличение урона хаосом')
        # герой, название, свой стат — и сразу этап и цель, которые на этот стат ссылаются
        defs = [{'id': 'chaos_dmg', 'name': 'Урон хаосом', 'lines': ['chaos_damage_+%']}]
        stages = [{'id': 'start', 'name': 'Кампания', 'stats': ['res_cold', 'life', 'chaos_dmg']}]
        goals = d['goals'] + [{'id': 'weapon-chaos-dmg-40', 'use': 'clearfell', 'slot': 'weapon', 'part': 'chaos_dmg', 'stat': 'chaos_dmg',
                               'min': 40, 'title': 'от 40%', 'need': 'maps'}]
        ok, problems = self.app.save_build({'title': 'Хаос', 'hero': {'class': 'Witch', 'ascendancy': 'Lich'}, 'statDefs': defs,
                                            'stages': stages, 'goals': goals})
        self.assertEqual((ok, problems), (True, []))
        text = self.build.read_bytes().decode('utf-8')
        self.assertIn('  "title": "Хаос",\r\n  "hero": {"class": "Witch", "ascendancy": "Lich"},\r\n  "slots": [\r\n', text)
        self.assertIn('    {"id": "chaos_dmg", "name": "Урон хаосом", "lines": ["chaos_damage_+%"]}\r\n', text)
        # план перечитан: герой назван, свой стат — в таблице статов, им считают вещи
        self.assertEqual((self.app.plan['hero'], self.app.plan_problems), ({'class': 'Witch', 'ascendancy': 'Lich'}, []))
        self.assertEqual(self.app.catalog['stats']['stats']['chaos_dmg'], {'ids': ['chaos_damage_+%'], 'own': True, 'unit': '%'})
        self.assertNotIn('chaos_dmg', self.app.base_catalog['stats']['stats'])
        d = self.app.build_view()
        self.assertEqual((d['buildTitle'], d['hero'], d['statDefs']), ('Хаос', {'class': 'Witch', 'ascendancy': 'Lich'}, defs))
        own = next(c for c in d['catalog'] if c['id'] == 'chaos_dmg')
        self.assertEqual((own['name'], own['own'], own['parts']['lines']), ('Урон хаосом', True, ['#% увеличение урона хаосом']))
        # готовый стат состоит из нескольких свойств игры — это видно странице
        fire = next(c for c in d['catalog'] if c['id'] == 'res_fire')['parts']
        self.assertIn('#% к сопротивлению всем стихиям', fire['lines'])
        self.assertEqual((fire['cap'], fire['penalty']), (75, True))
        self.assertEqual(d['units']['chaos_dmg'], '%')
        self.assertNotIn('hero', [f['kind'] for f in d['findings']])
        # стат, на который ссылаются этап и цель, не убрать: файл не тронут
        ok, problems = self.app.save_build({'statDefs': []})
        self.assertFalse(ok)
        self.assertIn('chaos_dmg', ' '.join(problems))
        self.assertEqual(self.build.read_bytes().decode('utf-8'), text)
        # переименовать — можно; то же, что в файле, файл не меняет
        ok, _ = self.app.save_build({'statDefs': [dict(defs[0], name='Хаос, урон')]})
        self.assertTrue(ok)
        self.assertEqual(self.app.catalog['lang']['ru']['statNames']['chaos_dmg'], ['Хаос, урон', 'Хаос, урон'])
        ok, problems = self.app.save_build({'hero': {'class': 'Witch', 'ascendancy': 'Titan'}})
        self.assertEqual((ok, problems), (False, ['герой: у класса «Witch» нет восхождения «Titan»']))

    def test_hero_of_the_run_is_read_from_the_log(self):
        if not (self.app.tree_geo('tree') or {}).get('classes'):
            self.skipTest('данные дерева не собраны')
        self.assertEqual(self.app.hero_seen(), {})
        self.app.run.events.append({'type': 'level', 'ts': 1, 'name': 'Имя', 'cls': 'Чародейка', 'level': 2})
        self.assertEqual(self.app.hero_seen(), {'class': 'Sorceress'})
        # вознесение — по id взятого узла вознесения: слово в логе может быть на любом языке
        self.app.run.events.append({'type': 'passive', 'ts': 2, 'op': 'take', 'id': 'AscendancySorceress3Small2'})
        self.assertEqual(self.app.hero_seen(), {'class': 'Sorceress', 'ascendancy': 'Disciple of Varashta'})
        self.app.run.events = [{'type': 'level', 'ts': 3, 'name': 'Имя', 'cls': 'Ученица Варашты', 'level': 40}]
        self.assertEqual(self.app.hero_seen(), {'class': 'Sorceress', 'ascendancy': 'Disciple of Varashta'})
        self.app.run.events = [{'type': 'passive', 'ts': 4, 'op': 'take', 'id': 'AscendancyWitch3bNotable1'}]
        self.assertEqual(self.app.hero_seen(), {'class': 'Witch', 'ascendancy': 'Abyssal Lich'})
        self.app.run.events = [{'type': 'level', 'ts': 5, 'name': 'Имя', 'cls': 'Неведомый', 'level': 1}]
        self.assertEqual(self.app.hero_seen(), {})

    def test_header_names_the_hero_in_the_words_of_the_client(self):
        if not (self.app.tree_geo('tree') or {}).get('classes'):
            self.skipTest('данные дерева не собраны')
        words = lambda cls, asc=None, node=None: self.app.hero_words({'cls': cls, 'asc': asc, 'ascNode': node})   # noqa: E731
        self.assertEqual(words('Чародейка'), ('Чародейка', None))
        # вознесение взято, а новый уровень ещё не пришёл: чьё оно, видно по узлу — словом клиента
        self.assertEqual(words('Чародейка', node='AscendancySorceress3Small2'), ('Чародейка', 'Ученица Варашты'))
        # слово лога важнее узла
        self.assertEqual(words('Чародейка', 'Ученица Варашты', 'AscendancySorceress3Small2'), ('Чародейка', 'Ученица Варашты'))
        # лог начался уже после вознесения: первое слово — вознесение, класс — тот, чьё оно
        self.assertEqual(words('Ученица Варашты'), ('Чародейка', 'Ученица Варашты'))
        # слова, которого словарь не знает, никто не переводит и не выдумывает; без слов нет и героя
        self.assertEqual(words('Неведомый'), ('Неведомый', None))
        self.assertEqual(words(None), (None, None))
        # в состояние страницы идут эти же слова — и имя героя из лога
        self.app.run.events = [{'type': 'level', 'ts': 3, 'name': 'Имя', 'cls': 'Чародейка', 'level': 2},
                               {'type': 'passive', 'ts': 4, 'op': 'take', 'id': 'AscendancySorceress3Small2', 'name': 'Дух'}]
        hero = self.app.view()['hero']
        self.assertEqual((hero['name'], hero['cls'], hero['asc'], hero['level']), ('Имя', 'Чародейка', 'Ученица Варашты', 2))


class TwinBaseTest(unittest.TestCase):
    """Базы, одинаковые по данным игры («Тиара небес» и «Тиара волшебника»: ур. 65, энергощит 90, интеллект 91), для
    плана — одна база: названа одна, узнаётся и другая — копия, переход в следующий период, тот же предмет в двух."""

    def setUp(self):
        tiara = lambda name, level=65, **more: dict({       # noqa: E731
            'name': name, 'class': 'Helmet', 'level': level, 'tags': ['int_armour', 'helmet', 'armour', 'default'],
            'req': {'level': level, 'int': 91}, 'props': {'energy_shield': 90}, 'art': 'Art/' + name, 'icon': 'art-' + name}, **more)
        self.cat = {
            'bases': {
                'h/sky': tiara('Skycrown Tiara'), 'h/magus': tiara('Magus Tiara'),
                'h/dnt': tiara('[DNT] Placeholder Tiara'),                       # такой же, но клиент её не знает
                'h/rune': tiara('Runeforged Magus Tiara', tags=['int_armour', 'helmet', 'armour', 'default', 'runeforged']),
                'h/jade': tiara('Jade Tiara', 50),
            },
            'lang': {'ru': {'bases': {'Skycrown Tiara': 'Тиара небес', 'Magus Tiara': 'Тиара волшебника',
                                      'Runeforged Magus Tiara': 'Руннокованая тиара волшебника', 'Jade Tiara': 'Нефритовая тиара'}}},
        }

    def test_which_bases_are_one(self):
        self.assertEqual(gamedata.twins(self.cat, 'Skycrown Tiara'), ['Magus Tiara'])
        self.assertEqual(gamedata.twins(self.cat, 'Magus Tiara'), ['Skycrown Tiara'])
        # другой уровень, сделанный из базы вариант, база без названия в клиенте, нет слоя языка — не одна
        for name in ('Jade Tiara', 'Runeforged Magus Tiara', '[DNT] Placeholder Tiara', 'Nothing', None):
            self.assertEqual(gamedata.twins(self.cat, name), [])
        self.assertEqual(gamedata.twins({'bases': self.cat['bases']}, 'Skycrown Tiara'), [])
        self.assertEqual(gamedata.twins(None, 'Skycrown Tiara'), [])

    def test_the_plan_knows_the_twin(self):
        raw = {'slots': [{'id': 'helmet', 'wear': [{'classes': ['Helmet'], 'kind': 'int_armour'}]}],
               'goals': [{'id': 'sky', 'slot': 'helmet', 'title': 'Тиара небес (Skycrown Tiara)'},
                         {'id': 'jade', 'slot': 'helmet', 'title': 'Нефритовая тиара (Jade Tiara)', 'twins': ['old']},
                         {'id': 'es', 'slot': 'helmet', 'part': 'es', 'stat': 'es', 'min': 300, 'title': 'от 300'}]}
        got = {g['id']: g for g in gamedata.with_facts(self.cat, raw)['goals']}
        # справка игры у цели: какие базы ей одинаковы; у базы без таковых поля нет (старое снимается), у части — нет
        self.assertEqual((got['sky'].get('twins'), 'twins' in got['jade'], 'twins' in got['es']), (['Magus Tiara'], False, False))
        magus = {'base': 'Тиара волшебника', 'base_en': 'Magus Tiara'}
        jade = {'base': 'Нефритовая тиара', 'base_en': 'Jade Tiara'}
        # копия «Тиары волшебника» отвечает цели «Тиара небес»; другая база — нет
        self.assertTrue(slotwear.fits(got['sky'], magus))
        self.assertFalse(slotwear.fits(got['sky'], jade))
        self.assertFalse(slotwear.fits(dict(got['sky'], twins=[]), magus))
        # цели, названные одинаковыми базами, — одна база (тот же предмет в двух периодах), в обе стороны
        twin = {'title': 'Тиара волшебника (Magus Tiara)', 'twins': ['Skycrown Tiara']}
        self.assertTrue(slotwear.same_base(got['sky'], twin) and slotwear.same_base(twin, got['sky']))
        self.assertTrue(slotwear.same_base(got['sky'], {'title': 'Тиара небес (Skycrown Tiara)'}))
        self.assertFalse(slotwear.same_base(got['sky'], got['jade']))


if __name__ == '__main__':
    unittest.main()
