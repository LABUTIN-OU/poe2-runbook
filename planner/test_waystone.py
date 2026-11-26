# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Sergei Labutin
# Additional terms under GPL-3.0 section 7: see NOTICE.md
"""Путевой камень из буфера: разбор копии и ответ — ступень опасности по сумме очков свойств.
Запуск: python -m unittest planner.test_waystone"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import gamedata  # noqa: E402
import itemcopy  # noqa: E402
import waystone  # noqa: E402

# Маленький каталог того же вида, что собирает catalog/build.py
CAT = {
    'waystones': {
        'tiers': {'1': {'name': 'Waystone (Tier 1)', 'area': 65, 'band': 'map_key_low'},
                  '4': {'name': 'Waystone (Tier 4)', 'area': 68, 'band': 'map_key_low'},
                  '10': {'name': 'Waystone (Tier 10)', 'area': 74, 'band': 'map_key_medium'}},
        'mods': {
            'MapPen': {'gen': 'prefix', 'stats': ['pen'], 'lines': ['pen'], 'fmt': ['#%']},
            'MapLife': {'gen': 'prefix', 'stats': ['life'], 'lines': ['life'], 'fmt': ['#%']},
            'MapFire': {'gen': 'prefix', 'stats': ['fire'], 'lines': ['fire'], 'fmt': ['#%']},
            'MapCold': {'gen': 'prefix', 'stats': ['cold'], 'lines': ['cold'], 'fmt': ['#%']},
            'MapCrit': {'gen': 'prefix', 'stats': ['crit', 'multi'], 'lines': ['crit', 'multi'], 'fmt': ['#%', '+#%']},
            'MapMaxRes': {'gen': 'suffix', 'stats': ['maxres'], 'lines': ['maxres'], 'fmt': ['#%']},
            'MapShock': {'gen': 'suffix', 'stats': ['shock'], 'lines': ['shock'], 'fmt': ['#']},
            'MapNew': {'gen': 'suffix', 'stats': ['new'], 'lines': ['new'], 'fmt': ['#']},
        }},
    'lang': {'ru': {
        'bases': {'Waystone (Tier 1)': 'Путевой камень (Ур. 1)', 'Waystone (Tier 4)': 'Путевой камень (Ур. 4)',
                  'Waystone (Tier 10)': 'Путевой камень (Ур. 10)', 'Full Plate': 'Полные латы'},
        'classes': {'Путевые камни': 'Map'},
        'stats': {'pen': ['Урон монстров пробивает #% сопротивлений стихиям'],
                  'life': ['На #% больше здоровья монстров', 'На #% меньше здоровья монстров'],
                  'fire': ['Монстры наносят #% от их урона в виде дополнительного урона от огня'],
                  'cold': ['Монстры наносят #% от их урона в виде дополнительного урона от холода'],
                  'crit': ['Монстры имеют #% повышение шанса критического удара'],
                  'multi': ['#% к бонусу критического урона монстров'],
                  'maxres': ['#% максимум сопротивлений игроков'],
                  'shock': ['Область содержит участки заряженной земли'],
                  'new': ['Область полна новинок']},
        'wayMods': {'MapPen': ['Пробивание сопротивлений', '#%'], 'MapLife': ['Здоровье монстров', '+#%'],
                    'MapCrit': ['Шанс критического удара монстров', '+#%'], 'MapMaxRes': ['Макс. сопротивления', '−#%'],
                    'MapShock': ['Заряженная земля', '']},
    }},
}
KNOW = {'levels': {'fair': 2, 'hard': 5, 'deadly': 8},
        'traits': {'ci': {'node': 'keystone_ci', 'name': 'Иммунитет к хаосу'}},
        'mods': {
            'MapPen': {'points': [[8, 3], [11, 4], [99, 6]], 'off': None, 'why': 'пробивание'},
            'MapLife': {'points': 0, 'off': None, 'why': ''},
            'MapFire': {'points': 1, 'off': None, 'why': ''},
            # в этом маленьком каталоге «холод» играет роль свойства, которое снимает черта героя
            'MapCold': {'points': [[9, 2], [99, 5]], 'off': 'ci', 'why': 'по энергощиту бьёт вдвое'},
            'MapCrit': {'points': [[180, 3], [999, 4]], 'off': None, 'why': 'криты'},
            'MapMaxRes': {'points': [[3, 1], [6, 2], [99, 4]], 'off': None, 'why': ''},
            'MapShock': {'points': 2, 'off': None, 'why': ''},
        }}

HEAD = 'Класс предмета: Путевые камни\nРедкость: %s\n%s\n--------\n' \
       'Доступно возрождений: 2 (augmented)\nРедкость предметов: +16%% (augmented)\n--------\n' \
       'Уровень предмета: 69\n--------\n'
TAIL = '--------\nМожно использовать в Машине картоходца, чтобы войти на карту. Путевые камни одноразовые.\n'


def stone(lines, name='Тайный гамбит\nПутевой камень (Ур. 4)', rarity='Редкий'):
    return HEAD % (rarity, name) + '\n'.join(lines) + '\n' + TAIL


def judged(text, hero=69, know=KNOW, cat=CAT, traits=()):
    return waystone.judge(cat, know, waystone.read(cat, itemcopy.parse(text)), hero, traits)


class ReadTest(unittest.TestCase):
    def test_copy_with_headers(self):
        s = waystone.read(CAT, itemcopy.parse(stone([
            '{ Префикс "Стойкий" (Уровень: 1) }', 'На 10(10-14)% больше здоровья монстров',
            '{ Префикс "Пробивающий" (Уровень: 1) }', 'Урон монстров пробивает 8(6-8)% сопротивлений стихиям',
            '{ Суффикс "шока" (Уровень: 1) }', 'Область содержит участки заряженной земли — Неизменяемое значение'])))
        self.assertEqual((s['tier'], s['area'], s['band'], s['name']), (4, 68, 'map_key_low', 'Тайный гамбит'))
        self.assertEqual([(m['fam'], m['value']) for m in s['mods']],
                         [('MapLife', 10.0), ('MapPen', 8.0), ('MapShock', None)])
        self.assertFalse(s['blind'] or s['dark'])

    def test_plain_copy_reads_the_same(self):
        """Простая копия (Ctrl+C): строки без заголовков; блок платы сверху и подсказка снизу — не аффиксы."""
        s = waystone.read(CAT, itemcopy.parse(stone([
            'На 10% больше здоровья монстров', 'Урон монстров пробивает 8% сопротивлений стихиям',
            '-4% максимум сопротивлений игроков', 'Область содержит участки заряженной земли'])))
        self.assertEqual([(m['fam'], m['value']) for m in s['mods']],
                         [('MapLife', 10.0), ('MapPen', 8.0), ('MapMaxRes', 4.0), ('MapShock', None)])

    def test_two_lines_of_one_affix_are_one_row(self):
        for lines in (['{ Префикс "Разрушительный" (Уровень: 1) }', 'Монстры имеют 95(80-120)% повышение шанса критического удара',
                       '+13(11-15)% к бонусу критического урона монстров'],
                      ['+13% к бонусу критического урона монстров', 'Монстры имеют 95% повышение шанса критического удара']):
            s = waystone.read(CAT, itemcopy.parse(stone(lines)))
            # число строки — шанс крита, в каком бы порядке строки ни пришли
            self.assertEqual([(m['fam'], m['value']) for m in s['mods']], [('MapCrit', 95.0)])

    def test_tier_and_what_is_not_a_waystone(self):
        ten = waystone.read(CAT, itemcopy.parse(stone([], name='Путевой камень (Ур. 10)', rarity='Обычный')))
        self.assertEqual((ten['tier'], ten['area'], ten['mods'], ten['dark']), (10, 74, [], False))
        # волшебный камень: база стоит внутри имени
        magic = waystone.read(CAT, itemcopy.parse(stone(['На 12% больше здоровья монстров'],
                                                        name='Стойкий Путевой камень (Ур. 1)', rarity='Волшебный')))
        self.assertEqual((magic['tier'], [m['fam'] for m in magic['mods']]), (1, ['MapLife']))
        # названия базы в слое языка нет — тир берётся из скобок, раз класс говорит «путевой камень»
        cat = dict(CAT, lang={'ru': dict(CAT['lang']['ru'], bases={})})
        self.assertEqual(waystone.read(cat, itemcopy.parse(stone([])))['tier'], 4)
        armour = 'Класс предмета: Нательные доспехи\nРедкость: Редкий\nКолючий спаситель\nПолные латы\n--------\n' \
                 'Уровень предмета: 47\n'
        self.assertIsNone(waystone.read(CAT, itemcopy.parse(armour)))
        self.assertIsNone(waystone.read(None, itemcopy.parse(stone([]))))


LIFE = 'На 10% больше здоровья монстров'
PEN = 'Урон монстров пробивает %d%% сопротивлений стихиям'
MAXRES = '-%d%% максимум сопротивлений игроков'
SHOCK = 'Область содержит участки заряженной земли'
CRIT = 'Монстры имеют 95% повышение шанса критического удара'
FIRE = 'Монстры наносят 7% от их урона в виде дополнительного урона от огня'
COLD = 'Монстры наносят %d%% от их урона в виде дополнительного урона от холода'


class JudgeTest(unittest.TestCase):
    def test_points_add_up_to_a_level(self):
        """Каждое свойство стоит очков; сумма — ступень: до 2 легко, с 2 сносно, с 5 тяжело, с 8 смертельно."""
        level = lambda *lines: (lambda v: (v['verdict'], v['score']))(judged(stone(list(lines))))   # noqa: E731
        self.assertEqual(level(LIFE), ('easy', 0))
        self.assertEqual(judged(stone([], name='Путевой камень (Ур. 4)', rarity='Обычный'))['verdict'], 'easy')
        self.assertEqual(level(LIFE, FIRE), ('easy', 1))
        # одно небольшое «−5% максимума сопротивлений» при пустом остальном — не повод не идти
        self.assertEqual(level(MAXRES % 5), ('fair', 2))
        self.assertEqual(level(PEN % 8, SHOCK), ('hard', 5))
        self.assertEqual(level(PEN % 8, SHOCK, FIRE, LIFE), ('hard', 6))
        # четыре средних свойства вместе — смерть, хотя ни одно из них само не смертельно
        self.assertEqual(level(PEN % 8, SHOCK, CRIT, MAXRES % 4), ('deadly', 10))
        # одно свойство само смертельной суммы не набирает, но тяжёлым камень делает
        self.assertEqual(level(PEN % 14), ('hard', 6))

    def test_points_grow_with_the_number_on_the_stone(self):
        pts = lambda line: judged(stone([line]))['rows'][0]['pts']   # noqa: E731
        self.assertEqual([pts(PEN % n) for n in (6, 8, 9, 11, 12, 16)], [3, 3, 4, 4, 6, 6])
        self.assertEqual([pts(MAXRES % n) for n in (3, 4, 6, 7, 10)], [1, 2, 2, 4, 4])
        self.assertEqual((waystone.points_of(2, None), waystone.points_of([[9, 2], [99, 5]], 7), waystone.points_of([[9, 2], [99, 5]], -12)),
                         (2, 2, 5))
        # числа на камне не прочитано — наибольшие очки свойства; число больше таблицы — её последняя строка
        self.assertEqual((waystone.points_of([[9, 2], [99, 5]], None), waystone.points_of([[9, 2], [20, 5]], 300)), (5, 5))

    def test_rows_go_most_dangerous_first(self):
        v = judged(stone([LIFE, MAXRES % 4, PEN % 12, SHOCK]))
        # подпись короткая, число — со знаком из слоя языка; размер очков — для цвета строки
        self.assertEqual([(r['fam'], r['pts'], r['cls'], r['label'], r['val']) for r in v['rows']], [
            ('MapPen', 6, 'p3', 'Пробивание сопротивлений', '12%'), ('MapMaxRes', 2, 'p1', 'Макс. сопротивления', '−4%'),
            ('MapShock', 2, 'p1', 'Заряженная земля', ''), ('MapLife', 0, 'p0', 'Здоровье монстров', '+10%')])
        self.assertEqual((v['verdict'], v['score'], v['tier'], v['area'], v['hero'], v['over']), ('deadly', 10, 4, 68, 69, 0))
        self.assertEqual(judged(stone([CRIT]))['rows'][0]['cls'], 'p2')

    def test_what_the_hero_has_switches_a_property_off(self):
        """Черта героя (взятый узел дерева) снимает свойство: после «Иммунитета к хаосу» урон хаосом не страшен."""
        self.assertEqual(waystone.hero_traits(KNOW, ['spells18', 'keystone_ci']), {'ci'})
        self.assertEqual(waystone.hero_traits(KNOW, ['spells18']), set())
        self.assertEqual(waystone.hero_traits(KNOW, None), set())
        before = judged(stone([COLD % 12, LIFE]))
        self.assertEqual((before['verdict'], before['score'], before['rows'][0]['off']), ('hard', 5, None))
        after = judged(stone([COLD % 12, LIFE]), traits={'ci'})
        self.assertEqual((after['verdict'], after['score']), ('easy', 0))
        self.assertEqual([(r['fam'], r['pts'], r['cls'], r['off']) for r in after['rows']],
                         [('MapCold', 0, 'p0', 'Иммунитет к хаосу'), ('MapLife', 0, 'p0', None)])
        self.assertIn('не действует', after['rows'][0]['why'])

    def test_unknown_is_never_safe(self):
        # строка, которой нет в данных игры, среди свойств: решить нельзя
        v = judged(stone([LIFE, 'Монстры одержимы']))
        self.assertEqual(v['verdict'], 'unknown')
        self.assertEqual([(r['cls'], r['label']) for r in v['rows']], [('unknown', 'Монстры одержимы'), ('p0', 'Здоровье монстров')])
        # смертельная сумма уже прочитанного сильнее неопознанного; несмертельная — нет
        self.assertEqual(judged(stone(['Монстры одержимы', PEN % 12, CRIT]))['verdict'], 'deadly')
        self.assertEqual(judged(stone(['Монстры одержимы', PEN % 12]))['verdict'], 'unknown')
        # свойство есть в данных игры, а очков в базе знаний ему нет — тоже «решить нельзя»
        self.assertEqual(judged(stone(['Область полна новинок']))['rows'][0]['cls'], 'unknown')
        # неопознанный в игре камень и редкий камень без единой прочитанной строки
        blind = judged(HEAD % ('Редкий', 'Путевой камень (Ур. 4)') + 'Неопознано\n' + TAIL)
        self.assertEqual((blind['verdict'], blind['rows']), ('unknown', []))
        self.assertIn('скрыты', blind['note'])
        dark = judged(HEAD % ('Редкий', 'Тайный гамбит\nПутевой камень (Ур. 4)') + TAIL)
        self.assertEqual((dark['verdict'], dark['note']), ('unknown', 'свойства не прочитаны'))
        # осквернённый аффикс отдельной секцией в простой копии
        v = judged(stone([LIFE, '--------', 'Монстры одержимы (desecrated)']))
        self.assertEqual(v['verdict'], 'unknown')

    def test_tier_above_the_hero(self):
        v = judged(stone(['На 16% больше здоровья монстров'], name='Путевой камень (Ур. 10)', rarity='Волшебный'), hero=69)
        self.assertEqual((v['area'], v['over'], v['verdict']), (74, 5, 'easy'))    # ступень по свойствам не меняется
        self.assertEqual(judged(stone([]), hero=68)['over'], 0)
        self.assertEqual(judged(stone([]), hero=None)['over'], 0)                  # уровень героя неизвестен

    def test_tier_and_experience(self):
        """Опыт идёт целиком, пока зона отличается от героя не больше чем на 3 + уровень // 16. Камень ниже
        этой полосы — штраф (с какого тира его нет); последний камень без штрафа — с какого уровня героя
        штраф дойдёт и до него."""
        ten = lambda hero: judged(stone([], name='Путевой камень (Ур. 10)', rarity='Обычный'), hero=hero)['xp']   # noqa: E731
        four = lambda hero: judged(stone([]), hero=hero)['xp']                                                   # noqa: E731
        self.assertIsNone(four(69))                               # герой 69: без штрафа зоны 62–76
        self.assertEqual(four(82), {'state': 'low', 'from': 10})  # герой 82: без штрафа с зоны 74 — это камень 10
        # камень 10 — последний без штрафа; с 83-го штраф и на нём (камня 11 в этом маленьком каталоге нет)
        self.assertEqual(ten(82), {'state': 'edge', 'at': 83, 'from': None})
        # герой 75: без штрафа зоны с 68 — камень 4 последний; с 76-го без штрафа с зоны 69 (здесь такого камня нет)
        self.assertEqual(four(75), {'state': 'edge', 'at': 76, 'from': None})
        self.assertIsNone(ten(81))                                # ещё есть запас в один тир
        self.assertEqual(ten(60), {'state': 'high'})              # зона выше полосы — опыт тоже режется
        self.assertEqual(four(95), {'state': 'low', 'from': None})   # герой перерос все камни: тира без штрафа нет
        self.assertIsNone(four(None))
        self.assertEqual([waystone.xp_band(n) for n in (1, 15, 16, 60, 81, 96)], [3, 3, 4, 6, 8, 9])

    def test_gem_levels_of_the_stone(self):
        """Какого уровня неогранённые камни умений падают в зоне камня — по правилам каталога."""
        cat = dict(CAT, rules={'mapGems': [[62, 15, 15], [70, 15, 17], [74, 16, 18]],
                               'gemHero': [0, 3, 6, 10, 14, 18, 22, 26, 31, 36, 41, 46, 52, 58, 64, 66, 72, 78],
                               'gemAttr': {'100': [4, 9, 14, 21, 28, 35, 41, 48, 57, 65, 74, 82, 92, 103, 113, 116, 126]}})
        self.assertEqual(judged(stone([]), cat=cat)['gems'], [15])                       # камень 4: зона 68
        ten = judged(stone([], name='Путевой камень (Ур. 10)', rarity='Обычный'), cat=cat)
        self.assertEqual(ten['gems'], [16, 17, 18])
        # что нужно герою для камня такого уровня: уровень героя и интеллект (чего в правилах нет — пусто)
        self.assertEqual(ten['gemNeed'], {16: [66, 116], 17: [72, 126], 18: [78, None]})
        self.assertEqual((judged(stone([]))['gems'], judged(stone([]))['gemNeed']), (None, {}))   # правил в каталоге нет
        self.assertIsNone(waystone.gem_levels(cat, 60))


class KnowledgeTest(unittest.TestCase):
    def test_file_is_checked_against_the_game(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'waystones.json'
            self.assertEqual(waystone.load_knowledge(path)[0], None)
            path.write_text('{', encoding='utf-8')
            self.assertIn('не прочитана', waystone.load_knowledge(path)[1][0])
            path.write_text(json.dumps({
                'levels': {'about': 'x', 'fair': 3, 'hard': 6},
                'traits': {'about': 'x', 'ci': {'node': 'keystone_ci', 'name': 'Иммунитет'}},
                'mods': {
                    'MapPen': {'points': [[8, 3], [99, 6]], 'why': 'w'}, 'MapLife': {'points': 'много'},
                    'MapFire': {'points': [[8]]}, 'MapCold': {'points': 2, 'off': 'ci'},
                    'MapShock': {'points': 2, 'off': 'wings'}, 'MapGone': {'points': 0}}}), encoding='utf-8')
            know, problems = waystone.load_knowledge(path, CAT)
            self.assertEqual(know['mods'], {'MapPen': {'points': [[8, 3], [99, 6]], 'off': None, 'why': 'w'},
                                            'MapCold': {'points': 2, 'off': 'ci', 'why': ''},
                                            'MapGone': {'points': 0, 'off': None, 'why': ''}})
            # ступени: что названо — из файла, остальное — как в программе
            self.assertEqual(know['levels'], {'fair': 3, 'hard': 6, 'deadly': 8})
            self.assertEqual(know['traits'], {'ci': {'node': 'keystone_ci', 'name': 'Иммунитет'}})
            text = '\n'.join(problems)
            self.assertIn('у свойства MapLife нет очков опасности', text)
            self.assertIn('у свойства MapFire нет очков опасности', text)
            self.assertIn('у свойства MapShock названа черта «wings»', text)
            self.assertIn('свойства MapGone нет в данных игры', text)
            self.assertIn('свойству MapCrit не заданы очки опасности', text)
            # ступени не по возрастанию — замечание, считаем по ступеням программы
            path.write_text(json.dumps({'levels': {'fair': 9}, 'mods': {}}), encoding='utf-8')
            know, problems = waystone.load_knowledge(path)
            self.assertEqual((know['levels'], problems), ({'fair': 2, 'hard': 5, 'deadly': 8},
                                                          ['Путевые камни: ступени (levels) должны идти по возрастанию: fair, hard, deadly']))

    def test_real_files(self):
        """Настоящие каталог и база знаний: у каждого аффикса игры есть класс и подпись, а камень игрока
        (копия из русского клиента от 2026-11-15) читается целиком."""
        root = Path(HERE).parent
        cat = gamedata.load(root / 'catalog' / 'data')
        if not cat or not cat.get('waystones'):
            self.skipTest('каталог данных игры не собран')
        know, problems = waystone.load_knowledge(root / 'knowledge' / 'waystones.json', cat)
        self.assertEqual(problems, [])
        self.assertEqual(set(cat['lang']['ru']['wayMods']), set(cat['waystones']['mods']))
        text = stone(['{ Префикс "Ударяющий" (Уровень: 1) }',
                      'Монстры имеют 54(50-60)% увеличение накопления шкалы оглушения',
                      '{ Префикс "Стойкий" (Уровень: 1) }', 'На 10(10-14)% больше здоровья монстров',
                      '{ Префикс "Пробивающий" (Уровень: 1) }', 'Урон монстров пробивает 8(6-8)% сопротивлений стихиям',
                      '{ Суффикс "шока" (Уровень: 1) }',
                      'Область содержит участки заряженной земли — Неизменяемое значение'])
        v = waystone.judge(cat, know, waystone.read(cat, itemcopy.parse(text)), 69)
        self.assertEqual((v['tier'], v['area'], v['over'], v['verdict'], v['score']), (4, 68, 0, 'hard', 7))
        self.assertEqual([(r['fam'], r['pts'], r['label'], r['val']) for r in v['rows']], [
            ('MapMonstersElementalPenetration', 3, 'Пробивание сопротивлений', '8%'),
            ('MapMonsterStunBuildup', 2, 'Накопление оглушения', '+54%'),
            ('MapSpreadShockedGround', 2, 'Заряженная земля', ''),
            ('MapMonsterLifeIncrease', 0, 'Здоровье монстров', '+10%')])
        # камень 4 — зона 68: с неё падают камни умений 15 уровня; герою 69 опыт идёт целиком
        self.assertEqual((v['gems'], v['xp']), ([15], None))
        # черта героя узнаётся по узлу настоящего дерева, и свойства, которые она снимает, в базе названы
        self.assertEqual(waystone.hero_traits(know, ['passive_keystone_chaos_inoculation']), {'ci'})
        self.assertEqual(sorted(f for f, k in know['mods'].items() if k['off'] == 'ci'),
                         ['MapMonsterBleeding', 'MapMonsterDamageAsChaos', 'MapMonsterPoisoning'])
        tree = root / 'planner' / 'static' / 'tree.json'
        if tree.exists():
            ids = {n[0] for n in json.loads(tree.read_text(encoding='utf-8'))['nodes']}
            self.assertTrue(all(t['node'] in ids for t in know['traits'].values()))
        # каждая строка каждого аффикса на русском находит своё семейство
        idx = waystone.index(cat, 'ru')
        for fam, f in cat['waystones']['mods'].items():
            for key in f['lines']:
                for shape in cat['lang']['ru']['stats'][key]:
                    self.assertEqual(idx[waystone.norm(shape)][0], fam)


if __name__ == '__main__':
    unittest.main()
