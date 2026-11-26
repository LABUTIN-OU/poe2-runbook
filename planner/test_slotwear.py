# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Sergei Labutin
# Additional terms under GPL-3.0 section 7: see NOTICE.md
"""Что носят в слоте: периоды (slotwear) — перевод файла старого вида, срок периода, развёрнутый план и то, как
периодами пользуются сравнение скопированного предмета и статы. Запуск: python -m unittest planner.test_slotwear"""
import copy
import os
import sys
import unittest
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import core  # noqa: E402
import gamedata  # noqa: E402
import herostats  # noqa: E402
import itemcopy  # noqa: E402
import slotstats  # noqa: E402
import slotwear  # noqa: E402

STEPS = [{'id': 'start', 'zone': 'G1_1', 'name': 'Берег'}, {'id': 'trial', 'zone': 'G1_2', 'name': 'Испытание'},
         {'id': 'after', 'zone': 'G1_4', 'name': 'После вознесения'}, {'id': 'maps', 'zone': 'G1_5', 'name': 'Карты'}]

# Билд старого вида: у слота один список классов на весь забег и своё «что носят» (gear); период угадывается по целям
# слота с одним use, его срок until повторён на каждой цели, а класс — поле gear одной из них.
OLD = {
    'slots': [
        {'id': 'weapon', 'name': 'Оружие', 'classes': ['Crossbow', 'Sceptre', 'Wand', 'Staff']},
        {'id': 'offhand', 'name': 'Вторая рука', 'classes': ['Shield', 'Focus', 'Sceptre']},
        {'id': 'helmet', 'name': 'Шлем', 'classes': ['Helmet'], 'gear': 'Helmet int_armour'},
        {'id': 'ring', 'name': 'Кольцо', 'classes': ['Ring'], 'gear': 'Ring'},
    ],
    'goals': [
        {'id': 'w-any', 'slot': 'weapon', 'title': 'любое', 'any': True, 'need': 'start', 'until': 'trial'},
        {'id': 'w-bow', 'slot': 'weapon', 'title': 'Прочный самострел (Sturdy Crossbow)', 'need': 'trial', 'until': 'trial'},
        {'id': 'w-elem', 'slot': 'weapon', 'part': 'elem', 'stat': 'weapon_elem', 'min': 1, 'title': 'любой', 'until': 'trial'},
        {'id': 'w-sc', 'slot': 'weapon', 'title': 'Гремящий скипетр (Rattling Sceptre)', 'gear': 'Sceptre', 'need': 'trial', 'use': 'after'},
        {'id': 'w-spirit', 'slot': 'weapon', 'part': 'spirit', 'stat': 'spirit', 'min': 120, 'title': 'от 120', 'use': 'after'},
        {'id': 'o-shield', 'slot': 'offhand', 'title': 'Ростовой щит (Tower Shield): жёлтый', 'gear': 'Shield str_armour', 'need': 'trial', 'use': 'after'},
        {'id': 'o-es', 'slot': 'offhand', 'part': 'es', 'stat': 'es', 'min': 270, 'title': 'от 270', 'gear': 'Focus', 'need': 'maps', 'use': 'after'},
        {'id': 'h-any', 'slot': 'helmet', 'title': 'любой', 'any': True, 'soft': True, 'need': 'start'},
        {'id': 'gold', 'kind': 'resource', 'title': '7000 золота', 'need': 'maps', 'until': 'maps'},
    ],
}
NEW_SLOTS = [
    {'id': 'weapon', 'name': 'Оружие', 'wear': [{'classes': ['Crossbow', 'Sceptre', 'Wand', 'Staff']},
                                                {'from': 'after', 'classes': ['Sceptre']}]},
    # класс, которого не назвал ни один период слота (скипетр во второй руке), действовал до первого из них
    {'id': 'offhand', 'name': 'Вторая рука', 'wear': [{'classes': ['Sceptre']},
                                                     {'from': 'after', 'classes': ['Shield', 'Focus'], 'kind': 'str_armour'}]},
    {'id': 'helmet', 'name': 'Шлем', 'wear': [{'classes': ['Helmet'], 'kind': 'int_armour'}]},
    {'id': 'ring', 'name': 'Кольцо', 'wear': [{'classes': ['Ring']}]},
]


def plan_of(build):
    return dict(build, steps=STEPS, title='проба')


class UpgradeTest(unittest.TestCase):
    def test_old_build_becomes_periods(self):
        new = slotwear.upgrade(OLD, STEPS)
        self.assertEqual(new['slots'], NEW_SLOTS)
        by = {g['id']: g for g in new['goals']}
        # срок, который следует из периода (он кончается, когда начинается следующий), у целей больше не записан;
        # описания базы у целей нет — класс называет период
        self.assertEqual([g['id'] for g in new['goals'] if 'gear' in g or (g.get('slot') and 'until' in g)], [])
        self.assertEqual(by['w-sc'], {'id': 'w-sc', 'slot': 'weapon', 'title': 'Гремящий скипетр (Rattling Sceptre)', 'need': 'trial', 'use': 'after'})
        self.assertEqual(by['gold'], OLD['goals'][-1])                    # цель без слота не тронута
        self.assertEqual([g['id'] for g in new['goals']], [g['id'] for g in OLD['goals']])
        # исходный билд цел, новый вид второй раз не переводится
        self.assertEqual(OLD['slots'][0]['classes'], ['Crossbow', 'Sceptre', 'Wand', 'Staff'])
        self.assertIs(slotwear.upgrade(new, STEPS), new)

    def test_a_term_that_does_not_follow_from_the_next_period_is_kept(self):
        old = copy.deepcopy(OLD)
        for g in old['goals'][:3]:
            g['until'] = 'start'                      # оружие сняли раньше, чем начался следующий период
        new = slotwear.upgrade(old, STEPS)
        self.assertEqual(new['slots'][0]['wear'][0], {'classes': ['Crossbow', 'Sceptre', 'Wand', 'Staff'], 'until': 'start'})
        self.assertEqual([g.get('until') for g in new['goals'][:3]], [None, None, None])
        # у целей периода срок разный — он остаётся у самих целей
        old['goals'][1]['until'] = 'trial'
        new = slotwear.upgrade(old, STEPS)
        self.assertEqual((new['slots'][0]['wear'][0].get('until'), [g.get('until') for g in new['goals'][:3]]),
                         (None, ['start', None, 'start']))


class PeriodTest(unittest.TestCase):
    def setUp(self):
        self.idx = slotwear.step_index(STEPS)

    def test_period_lasts_until_the_next_one(self):
        pers = slotwear.periods(NEW_SLOTS[0], [], self.idx)
        self.assertEqual([(p['from'], p['ends'], p['classes'], p['stated']) for p in pers],
                         [(None, 'trial', ['Crossbow', 'Sceptre', 'Wand', 'Staff'], True), ('after', None, ['Sceptre'], True)])
        own = dict(NEW_SLOTS[0], wear=[{'classes': ['Bow'], 'until': 'start'}, {'from': 'maps', 'classes': ['Sceptre']}])
        self.assertEqual([p['ends'] for p in slotwear.periods(own, [], self.idx)], ['start', None])
        # периоды читаются по порядку шагов, как бы ни были записаны
        back = dict(NEW_SLOTS[0], wear=list(reversed(NEW_SLOTS[0]['wear'])))
        self.assertEqual([p['from'] for p in slotwear.periods(back, [], self.idx)], [None, 'after'])
        self.assertEqual(slotwear.period_of(NEW_SLOTS[1], [], self.idx, 'after')['kind'], 'str_armour')
        self.assertIsNone(slotwear.period_of(NEW_SLOTS[1], [], self.idx, 'maps'))

    def test_old_slot_is_read_as_before(self):
        pers = slotwear.periods(OLD['slots'][1], OLD['goals'], self.idx)
        # срок старого слота говорит сама цель: без него период не кончается
        self.assertEqual([(p['from'], p['classes'], p['kind'], p['ends'], p['spec'], p['stated']) for p in pers],
                         [(None, ['Sceptre'], None, None, None, False),
                          ('after', ['Shield', 'Focus'], 'str_armour', None, 'Shield str_armour', False)])
        self.assertEqual(slotwear.classes_of(OLD['slots'][1]), ['Shield', 'Focus', 'Sceptre'])
        self.assertEqual(slotwear.classes_of(NEW_SLOTS[1]), ['Sceptre', 'Shield', 'Focus'])

    def test_specs(self):
        per = slotwear.period_of(NEW_SLOTS[1], [], self.idx, 'after')
        self.assertEqual(slotwear.specs(None, per), ['Shield str_armour', 'Focus'])
        cat = {'bases': {'a': {'class': 'Shield', 'tags': ['str_armour']}, 'b': {'class': 'Focus', 'tags': ['int_armour']}}}
        self.assertEqual(slotwear.specs(cat, per), ['Shield str_armour', 'Focus'])
        self.assertEqual(slotwear.specs(cat, dict(per, kind='int_armour')), ['Shield', 'Focus int_armour'])

    def test_problems(self):
        bad = {'id': 'w', 'name': 'Оружие', 'wear': [{'classes': ['Bow']}, {'classes': ['Wand']}, {'from': 'nowhere', 'classes': ['Bow']},
                                                      {'from': 'after', 'classes': []}, 'период']}
        goals = [{'id': 'g', 'slot': 'w', 'title': 'Лук', 'use': 'maps'}]
        self.assertEqual(slotwear.problems(bad, goals, self.idx), [
            'Слот «Оружие»: два периода с одного шага',
            'Слот «Оружие»: у периода нет шага «nowhere»',
            'Слот «Оружие»: у периода нужен хотя бы один класс предметов, без повторов',
            'Слот «Оружие»: период — запись {from, classes, kind}',
            'Цель «Лук»: у слота «Оружие» нет периода с шага «maps»'])
        self.assertEqual(slotwear.problems(NEW_SLOTS[0], slotwear.upgrade(OLD, STEPS)['goals'], self.idx), [])
        self.assertEqual(slotwear.problems(OLD['slots'][0], OLD['goals'], self.idx), [])      # слот старого вида не сверяется


class PlanTest(unittest.TestCase):
    """План с периодами разворачивается: слоту — все его классы, его целям — срок периода; дальше программа
    считает как раньше, поэтому страница забега от вида файла не зависит."""

    def setUp(self):
        self.new = plan_of(slotwear.upgrade(OLD, STEPS))
        self.plan, self.problems = core.norm_plan(self.new)
        self.old, self.old_problems = core.norm_plan(plan_of(OLD))

    def test_expand(self):
        self.assertEqual((self.problems, self.old_problems), ([], []))
        by = {g['id']: g for g in self.plan['goals']}
        self.assertEqual([by[i].get('until') for i in ('w-any', 'w-bow', 'w-elem', 'w-sc', 'o-shield', 'h-any', 'gold')],
                         ['trial', 'trial', 'trial', None, None, None, 'maps'])
        self.assertEqual([s['classes'] for s in self.plan['slots']],
                         [['Crossbow', 'Sceptre', 'Wand', 'Staff'], ['Sceptre', 'Shield', 'Focus'], ['Helmet'], ['Ring']])
        again = slotwear.expand(slotwear.expand(self.new))
        self.assertEqual(again, slotwear.expand(self.new))
        self.assertIs(slotwear.expand(plan_of(OLD))['slots'], OLD['slots'])     # старый вид не трогается
        # цель слота без своего периода — замечание к плану
        broken = copy.deepcopy(self.new)
        broken['goals'].append({'id': 'x', 'slot': 'ring', 'title': 'Кольцо позже', 'use': 'maps'})
        self.assertEqual(core.norm_plan(broken)[1], ['Цель «Кольцо позже»: у слота «Кольцо» нет периода с шага «maps»'])

    def test_run_page_is_the_same_for_both_shapes(self):
        def state(plan, zones):
            run = core.Run('r', 100)
            run.events = [{'type': 'zone', 'ts': 100 + 600 * i, 'code': code, 'level': i + 1, 'name': code, 'seed': 1}
                          for i, code in enumerate(zones)]
            v = core.derive(plan, run, 100 + 600 * len(zones))
            return {k: v[k] for k in ('holders', 'stash', 'slots', 'overdue', 'retired', 'cards')}

        for zones in (['G1_1'], ['G1_1', 'G1_2'], ['G1_1', 'G1_2', 'G1_4'], ['G1_1', 'G1_2', 'G1_4', 'G1_5']):
            self.assertEqual(state(self.plan, zones), state(self.old, zones), zones)

    def test_copied_item_goes_to_a_slot_of_any_period(self):
        # слот принимает класс любого своего периода: надеть вещь можно и раньше её периода по плану (рюкзака нет)
        self.assertEqual([s['classes'] for s in self.plan['slots'][:2]],
                         [['Crossbow', 'Sceptre', 'Wand', 'Staff'], ['Sceptre', 'Shield', 'Focus']])
        shield = {'name': 'Щит', 'cls_id': 'Shield', 'cls': 'Щиты', 'base': 'Ростовой щит', 'base_en': 'Tower Shield', 'tags': ['shield']}
        run = core.Run('r', 100)
        run.events = [{'type': 'zone', 'ts': 100, 'code': 'G1_1', 'level': 1, 'name': 'G1_1', 'seed': 1}]
        v = core.derive(self.plan, run, 200)
        self.assertEqual([r['slot'] for r in itemcopy.compare(self.plan, v, shield)['rows']], ['offhand'])

    def test_build_at_a_step(self):
        lines = herostats.slot_lines(self.plan)
        self.assertEqual(lines['weapon'], [(-1, None, 'Crossbow'), (2, 'after', 'Sceptre')])
        self.assertEqual(lines['offhand'], [(-1, None, 'Sceptre'), (2, 'after', 'Shield str_armour')])
        self.assertEqual(herostats.slot_lines(self.old)['offhand'], [(-1, None, None), (2, 'after', 'Shield str_armour')])
        spec = lambda plan, pos: [(sid, s) for sid, _, s in herostats.specs(herostats.at_step(None, plan, pos))]   # noqa: E731
        # в период носят предметы нескольких классов — у слота по описанию базы на каждый
        self.assertEqual(spec(self.plan, 0), [('weapon', 'Crossbow'), ('weapon', 'Sceptre'), ('weapon', 'Wand'), ('weapon', 'Staff'),
                                             ('offhand', 'Sceptre'), ('helmet', 'Helmet int_armour'), ('ring', 'Ring')])
        self.assertEqual(spec(self.plan, 2), [('weapon', 'Sceptre'), ('offhand', 'Shield str_armour'), ('offhand', 'Focus'),
                                             ('helmet', 'Helmet int_armour'), ('ring', 'Ring')])
        # старый вид: одно описание на слот, как раньше
        self.assertEqual(spec(self.old, 2), [('weapon', 'Sceptre'), ('offhand', 'Shield str_armour'),
                                            ('helmet', 'Helmet int_armour'), ('ring', 'Ring')])
        # слот помнит один предмет: место в памяти надетого у него одно на любом шаге
        keys = herostats.at_step(None, self.plan, 2)['keys']
        self.assertEqual((keys['weapon'], keys['offhand'], keys['helmet']), ('weapon/', 'offhand/', 'helmet/'))

    def test_stat_sources_of_several_classes_add_up(self):
        cat = gamedata.load(Path(HERE).parent / 'catalog' / 'data')
        if not cat or not cat.get('stats') or not cat.get('bases'):
            self.skipTest('каталог данных игры не собран')
        one = lambda *specs: slotstats.carriers(cat, [('offhand', 'Вторая рука', s) for s in specs])    # noqa: E731
        where = lambda table: {sid for sid, slots in table.items() if slotstats.is_source(slots.get('offhand'))}    # noqa: E731
        shield, focus, both = where(one('Shield str_armour')), where(one('Focus')), where(one('Shield str_armour', 'Focus'))
        self.assertTrue(shield and focus and shield != focus)
        self.assertEqual(both, shield | focus)


class HandsTest(unittest.TestCase):
    """Двуручное оружие закрывает вторую руку — правило игры: какой слот какая рука, программа выводит из данных
    игры о классах слотов, а что надето — из памяти надетого."""
    CAT = {'bases': {
        'bow': {'class': 'Bow', 'tags': ['bow', 'twohand', 'weapon']}, 'staff': {'class': 'Staff', 'tags': ['staff', 'twohand']},
        'wand': {'class': 'Wand', 'tags': ['wand', 'onehand']}, 'sceptre': {'class': 'Sceptre', 'tags': ['sceptre', 'onehand']},
        'shield': {'class': 'Shield', 'tags': ['shield', 'armour']}, 'focus': {'class': 'Focus', 'tags': ['focus', 'armour']},
        'quiver': {'class': 'Quiver', 'tags': ['quiver']}, 'helmet': {'class': 'Helmet', 'tags': ['helmet', 'armour']}}}
    SLOTS = [{'id': 'weapon', 'name': 'Оружие', 'wear': [{'classes': ['Wand', 'Staff', 'Sceptre']}, {'from': 'after', 'classes': ['Sceptre']}]},
             {'id': 'offhand', 'name': 'Вторая рука', 'wear': [{'classes': ['Sceptre']}, {'from': 'after', 'classes': ['Shield']}]},
             {'id': 'helmet', 'name': 'Шлем', 'wear': [{'classes': ['Helmet']}]}]

    def test_which_slot_is_which_hand(self):
        self.assertEqual(slotwear.hands(self.SLOTS, self.CAT), {'main': 'weapon', 'off': 'offhand', 'quiver': ['Quiver']})
        self.assertEqual(slotwear.hands(self.SLOTS, None), {})
        # двуручного в плане нет — закрывать нечем; слот старого вида читается так же
        one = [dict(self.SLOTS[0], wear=[{'classes': ['Wand']}])] + self.SLOTS[1:]
        self.assertEqual(slotwear.hands(one, self.CAT), {})
        old = [{'id': 'weapon', 'classes': ['Staff']}, {'id': 'offhand', 'classes': ['Focus']}]
        self.assertEqual(slotwear.hands(old, self.CAT)['off'], 'offhand')

    def test_shut(self):
        pair = slotwear.hands(self.SLOTS, self.CAT)
        self.assertTrue(slotwear.shut(pair, {'tags': ['staff', 'twohand']}, ['Sceptre']))
        self.assertFalse(slotwear.shut(pair, {'tags': ['wand', 'onehand']}, ['Sceptre']))
        self.assertFalse(slotwear.shut(pair, None, ['Sceptre']))
        self.assertFalse(slotwear.shut({}, {'tags': ['twohand']}))
        # колчан при луке держат вместе с луком
        self.assertTrue(slotwear.shut(pair, {'tags': ['bow', 'twohand']}, ['Shield']))
        self.assertFalse(slotwear.shut(pair, {'tags': ['bow', 'twohand']}, ['Quiver']))

    def test_goals_of_the_shut_hand_do_not_burn(self):
        goals = [{'id': 'w', 'slot': 'weapon', 'title': 'любое', 'any': True, 'need': 'start'},
                 {'id': 'o', 'slot': 'offhand', 'title': 'любой', 'any': True, 'need': 'start'},
                 {'id': 'o-shield', 'slot': 'offhand', 'title': 'Щит', 'need': 'trial', 'use': 'after'}]
        plan, problems = core.norm_plan({'title': 'проба', 'steps': STEPS, 'slots': self.SLOTS, 'goals': goals}, self.CAT)
        self.assertEqual((problems, plan['hands']['off']), ([], 'offhand'))

        def off(worn, zones=('G1_1', 'G1_2')):
            run = core.Run('r', 100)
            run.events = [{'type': 'zone', 'ts': 100 + 600 * i, 'code': code, 'level': i + 1, 'name': code, 'seed': 1}
                          for i, code in enumerate(zones)]
            run.worn = worn
            v = core.derive(plan, run, 100 + 600 * len(zones))
            row = next(r for r in v['holders'] if r.get('slot') == 'offhand')
            lad = row['base']
            return (row['state'], (lad['next'] or {}).get('urgency'), (lad['later'] or {}).get('since'), 'o' in [g['id'] for g in v['overdue']])

        # срок «любого» во второй руке прошёл: без двуручного оружия он горит опозданием
        self.assertEqual(off({}), ('overdue', 'overdue', None, True))
        self.assertEqual(off({'weapon/': {'item': {'tags': ['wand', 'onehand']}}})[:2], ('overdue', 'overdue'))
        # в основной руке посох: вторая закрыта — её цель «позже», срок не горит
        self.assertEqual(off({'weapon/': {'item': {'tags': ['staff', 'twohand']}}}), ('early', None, 'пока оружие двуручное', False))
        # после вознесения посох по плану уже не носят, но он всё ещё в руке (память — то, что надето): рука закрыта, пока
        # игрок не отметит другое оружие
        self.assertEqual(off({'weapon/': {'item': {'tags': ['staff', 'twohand']}}}, ('G1_1', 'G1_2', 'G1_4'))[:2], ('early', None))
        self.assertEqual(off({'weapon/': {'item': {'tags': ['wand', 'onehand']}}}, ('G1_1', 'G1_2', 'G1_4'))[1], 'overdue')


class WornTest(unittest.TestCase):
    """Слот помнит один предмет — тот, что на герое надет (рюкзака нет): периоды слота говорят, что в нём ждёт план, а
    цель периода закрывается надетым предметом, когда период настал. Ничего нового не хранится — это выводится из плана
    и памяти надетого."""
    SLOTS = [
        {'id': 'weapon', 'name': 'Оружие', 'wear': [{'classes': ['Wand', 'Staff', 'Sceptre']}, {'from': 'after', 'classes': ['Sceptre']}]},
        {'id': 'offhand', 'name': 'Вторая рука', 'wear': [{'classes': ['Sceptre']}, {'from': 'after', 'classes': ['Shield']}]}]
    GOALS = [
        {'id': 'w-any', 'slot': 'weapon', 'title': 'любое', 'any': True, 'need': 'start'},
        {'id': 'w-sc', 'slot': 'weapon', 'title': 'Гремящий скипетр (Rattling Sceptre)', 'need': 'trial', 'use': 'after'},
        {'id': 'w-spirit', 'slot': 'weapon', 'part': 'spirit', 'stat': 'spirit', 'min': 100, 'title': 'от 100', 'need': 'trial', 'use': 'after'},
        {'id': 'o-sc', 'slot': 'offhand', 'title': 'Гремящий скипетр (Rattling Sceptre)', 'need': 'trial'},
        {'id': 'o-shield', 'slot': 'offhand', 'title': 'Ростовой щит (Tower Shield): жёлтый', 'need': 'trial', 'use': 'after'}]
    SCEPTRE = {'name': 'Гремящий скипетр', 'cls_id': 'Sceptre', 'cls': 'Скипетры', 'base': 'Гремящий скипетр',
               'base_en': 'Rattling Sceptre', 'tags': ['sceptre', 'onehand']}
    STOIC = dict(SCEPTRE, name='Скипетр стоика', base='Скипетр стоика', base_en='Stoic Sceptre')
    SHIELD = {'name': 'Ростовой щит', 'cls_id': 'Shield', 'cls': 'Щиты', 'base': 'Ростовой щит', 'base_en': 'Tower Shield',
              'tags': ['shield', 'armour']}
    STAFF = {'name': 'Пепельный посох', 'cls_id': 'Staff', 'cls': 'Посохи', 'base': 'Пепельный посох', 'base_en': 'Ashen Staff',
             'tags': ['staff', 'twohand']}
    WAND = {'name': 'Увядший жезл', 'cls_id': 'Wand', 'cls': 'Жезлы', 'base': 'Увядший жезл', 'base_en': 'Withered Wand',
            'tags': ['wand', 'onehand']}
    BEFORE, AFTER = ('G1_1', 'G1_2'), ('G1_1', 'G1_2', 'G1_4')

    def setUp(self):
        self.raw = {'title': 'проба', 'steps': STEPS, 'slots': self.SLOTS, 'goals': self.GOALS}
        self.plan, problems = core.norm_plan(self.raw, HandsTest.CAT)
        self.assertEqual(problems, [])

    def test_memory_holds_one_item_per_slot(self):
        settle = lambda worn, pos: slotwear.settle(self.plan, worn, pos)     # noqa: E731
        item = lambda it, at: {'item': it, 'at': at}                         # noqa: E731
        self.assertEqual(settle({'offhand/': item(self.SCEPTRE, 1)}, 0), {'offhand': 'offhand/'})
        # Запись прежнего вида — место по периоду. До периода это рюкзак: надетым не считается; с его шага — надето,
        # и из надетых записей слота действует последняя по времени.
        old = {'weapon/': item(self.WAND, 1), 'weapon/after': item(self.SCEPTRE, 2)}
        self.assertEqual((settle(old, 1), settle(old, 2)), ({'weapon': 'weapon/'}, {'weapon': 'weapon/after'}))
        self.assertEqual(settle(dict(old, **{'weapon/': item(self.WAND, 3)}), 2), {'weapon': 'weapon/'})
        # слота нет в плане, записи без предмета — не в счёт
        self.assertEqual(settle({'boots/': item(self.WAND, 1), 'weapon/': {'at': 5}}, 0), {})
        # место в памяти у слота одно — на любом шаге
        self.assertEqual(herostats.at_step(None, self.plan, 2)['keys'], {'weapon': 'weapon/', 'offhand': 'offhand/'})
        # по плану: цель оружия после вознесения — тот же предмет, что цель второй руки до него
        self.assertEqual(slotwear.linked(self.plan), {'w-sc': 'o-sc'})
        self.assertEqual(slotwear.fits(self.GOALS[4], {'base': 'Какой-то Ростовой щит', 'base_en': 'Tower Shield'}), True)

    def made_run(self, worn, zones=BEFORE, gear=None, status=None):
        run = core.Run('r', 100)
        run.events = [{'type': 'zone', 'ts': 100 + 600 * i, 'code': code, 'level': i + 1, 'name': code, 'seed': 1}
                      for i, code in enumerate(zones)]
        run.worn = {k: {'item': v, 'at': 50 + n} for n, (k, v) in enumerate(worn.items())}
        run.gear = gear or {}
        run.marks = [{'goal': gid, 'status': st, 'ts': 150} for gid, st in (status or {}).items()]
        return run

    def state(self, worn, zones=BEFORE, gear=None, status=None, plan=None):
        return core.derive(plan or self.plan, self.made_run(worn, zones, gear, status), 100 + 600 * len(zones))

    @staticmethod
    def goal(v, gid):
        for row in v['holders']:
            for lad in [row['base']] + row['parts']:
                for g in (lad['have'], lad['next'], lad['later']) if lad else ():
                    if g and g['id'] == gid:
                        return g
        return next(g for c in v['cards'] for g in c['goals'] if g['id'] == gid)

    def test_run_page(self):
        goal, off = self.goal, (lambda v: next(r for r in v['holders'] if r['slot'] == 'offhand')['base'])   # noqa: E731
        # предмета нет: вещь, которую носят после вознесения, — «позже» до своего шага; скипетр второй руки ищут
        v = self.state({})
        self.assertEqual((goal(v, 'w-sc')['urgency'], goal(v, 'w-sc')['since'], goal(v, 'o-sc')['urgency']),
                         ('early', 'с шага «После вознесения»', 'due'))
        self.assertNotIn('carried', v)
        self.assertEqual(v['wornAt'], {})
        # скипетр надет во второй руке: её цель закрыта надетым (отмечать рукой нечего); оружию он — ещё «позже»
        v = self.state({'offhand/': self.SCEPTRE}, gear={'offhand/': {'spirit': 120}})
        self.assertEqual((goal(v, 'o-sc')['urgency'], goal(v, 'o-sc')['locked']), ('done', True))
        self.assertEqual((goal(v, 'w-sc')['urgency'], goal(v, 'w-spirit')['urgency']), ('early', 'early'))
        self.assertEqual(v['stash'], [])
        # Шаг смены: в памяти скипетр по-прежнему во второй руке — так и есть, пока игрок его не переложил. Цель оружия
        # горит и говорит, где скипетр сейчас; во второй руке ждут щит, прежняя цель ушла со своим периодом.
        v = self.state({'offhand/': self.SCEPTRE}, self.AFTER)
        self.assertEqual((goal(v, 'w-sc')['urgency'], goal(v, 'w-sc')['heldIn']), ('overdue', 'Вторая рука'))
        self.assertEqual((off(v)['have'], off(v)['next']['id'], off(v)['next']['urgency']), (None, 'o-shield', 'overdue'))
        self.assertTrue(all('move' not in c and 'wear' not in c for c in v['cards']))
        # игрок переложил: скипетр в оружии — цель закрыта им, стат меряется по нему; щит надет — закрыт и он
        v = self.state({'weapon/': self.SCEPTRE, 'offhand/': self.SHIELD}, self.AFTER, gear={'weapon/': {'spirit': 120}})
        self.assertEqual([(goal(v, x)['urgency'], goal(v, x)['heldIn']) for x in ('w-sc', 'w-spirit', 'o-shield')],
                         [('done', None), ('done', None), ('done', None)])
        # Щит надет раньше вознесения (по плану его носят после): статы героя его считают, цель щита — «позже» и на своём
        # шаге закрыта им без отметки; прежняя цель второй руки (скипетр) щитом не закрывается.
        v = self.state({'offhand/': self.SHIELD})
        self.assertEqual((goal(v, 'o-sc')['urgency'], goal(v, 'o-shield')['urgency']), ('due', 'early'))
        self.assertEqual(v['wornAt'], {'offhand': 'offhand/'})
        self.assertEqual(goal(self.state({'offhand/': self.SHIELD}, self.AFTER), 'o-shield')['urgency'], 'done')
        # другая база той же вещи цели не отвечает: скипетр стоика — не Гремящий
        self.assertEqual(goal(self.state({'weapon/': self.STOIC}, self.AFTER), 'w-sc')['urgency'], 'overdue')
        # «любому» отвечает любой предмет
        anyone = core.norm_plan(dict(self.raw, goals=[dict(g, title='любой', any=True) if g['id'] == 'w-sc' else g
                                                       for g in self.GOALS]), HandsTest.CAT)[0]
        self.assertEqual(goal(self.state({'weapon/': self.STOIC}, self.AFTER, plan=anyone), 'w-sc')['urgency'], 'done')
        # отметка «в рюкзаке» прежних забегов (статус 1) ничего не значит
        self.assertEqual(goal(self.state({}, self.AFTER, status={'w-sc': 1}), 'w-sc')['urgency'], 'overdue')
        # посох в руке — двуручный: вторая рука закрыта, её цель не горит, а скипетр в ней надетым не считается
        v = self.state({'weapon/': self.STAFF, 'offhand/': self.SCEPTRE})
        self.assertEqual((v['shut'], goal(v, 'o-sc')['urgency'], goal(v, 'o-sc')['since']), ('offhand', 'early', 'пока оружие двуручное'))

    def test_skill_of_the_item(self):
        """Умение, которое даёт предмет: предмет, названный в двух периодах, один — надет во второй руке (отмечен или
        запомнен), и умение, записанное за целью оружия, уже есть."""
        raw = dict(self.raw, goals=self.GOALS + [{'id': 'warrior', 'kind': 'skill', 'title': 'Скелет-воин', 'grantedBy': 'w-sc',
                                                  'use': 'after', 'need': 'after'}])
        plan, problems = core.norm_plan(raw, HandsTest.CAT)
        self.assertEqual(problems, [])

        def skill(status, worn=None):
            v = core.derive(plan, self.made_run(worn or {}, status=status), 1300)
            return next(g for row in v['holders'] + [r for st in v['stash'] for r in st['rows']]
                        for lad in [row['base']] + row['parts'] if lad
                        for g in (lad['have'], lad['bag'], lad['next'], lad['later']) if g and g['id'] == 'warrior')['urgency']

        self.assertEqual((skill({}), skill({'o-sc': 1}), skill({'o-sc': 2}), skill({'w-sc': 2}), skill({}, {'offhand/': self.SCEPTRE})),
                         ('early', 'early', 'done', 'done', 'done'))

    def test_copied_item(self):
        rows = lambda v, item: [(r['slot'], r['line']) for r in itemcopy.compare(self.plan, v, item)['rows']]   # noqa: E731
        # жезл в руке: скопированный скипетр можно надеть в оружие или во вторую руку
        v = self.state({'weapon/': self.WAND})
        self.assertEqual(rows(v, self.SCEPTRE), [('weapon', None), ('offhand', None)])
        # во второй руке план называет именно эту базу, в оружии годится любое
        self.assertEqual([r['base']['byName'] for r in itemcopy.compare(self.plan, v, self.SCEPTRE)['rows']], [False, True])
        self.assertTrue(itemcopy.same_item(dict(self.SCEPTRE, at=1), dict(self.SCEPTRE, at=2)))
        self.assertFalse(itemcopy.same_item(self.SCEPTRE, self.STOIC))
        # щит до вознесения: в плане его носят после, но надеть его можно и сейчас — строка второй руки
        self.assertEqual(rows(v, self.SHIELD), [('offhand', None)])
        # посох двуручный и вторая рука закрыта, но надеть щит можно: это значит, что посох сняли (сервер забудет его)
        v = self.state({'weapon/': self.STAFF})
        self.assertEqual((v['shut'], rows(v, self.SHIELD)), ('offhand', [('offhand', None)]))


if __name__ == '__main__':
    unittest.main()
