# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Sergei Labutin
# Additional terms under GPL-3.0 section 7: see NOTICE.md
"""Проверка разбора вещи из буфера обмена и её сравнения со слотом.
Запуск: python -m unittest planner.test_itemcopy"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import core  # noqa: E402
import itemcopy  # noqa: E402

DAY = '2026/11/15'

# Настоящая копия из русского клиента (Ctrl+Alt+C), 2026-11-15: по ней сверен формат и нумерация тиров.
REAL = '''Класс предмета: Нательные доспехи
Редкость: Редкий
Колючий спаситель
Полные латы
--------
Броня: 358 (augmented)
--------
Требуется: Уровень 36, 54 Сила
--------
Гнезда: S S
--------
Уровень предмета: 47
--------
+36% к сопротивлению холоду (rune)
--------
{ Префикс "Массивный" (Уровень: 7) — Здоровье }
+95(85-99) к максимуму здоровья
{ Префикс "Омаровый" (Уровень: 5) — Здоровье, Броня }
17(14-20)% повышение брони
+12(11-19) к максимуму здоровья
{ Префикс "Шипованный" (Уровень: 10) — Броня }
+36(28-56) к броне
{ Суффикс "грозовой тучи" (Уровень: 5) — Стихийный, Молния, Сопротивление }
+25(21-25)% к сопротивлению молнии
{ Суффикс "силача" (Уровень: 8) — Характеристика }
+5(5-8) к силе
{ Суффикс "углей" (Уровень: 8) — Стихийный, Огонь, Сопротивление }
+6(6-10)% к сопротивлению огню
'''


def item_text(cls, name, base=None, mods=(), rarity='Редкий', ilvl=30, extra=()):
    """Текст расширенной копии. mods — (заголовок без скобок, строка[, строка])."""
    head = ['Класс предмета: ' + cls, 'Редкость: ' + rarity, name] + ([base] if base else [])
    secs = [head, ['Уровень предмета: %d' % ilvl]] + [list(x) for x in extra]
    if mods:
        secs.append([ln for m in mods for ln in ['{ %s }' % m[0]] + list(m[1:])])
    return '\n--------\n'.join('\n'.join(s) for s in secs) + '\n'


PLAN = {
    'title': 'копия',
    'slots': [{'id': 'weapon', 'name': 'Оружие', 'classes': ['Самострелы', 'Скипетры']},
              {'id': 'body', 'name': 'Нательный доспех', 'classes': ['Нательные доспехи']},
              {'id': 'belt', 'name': 'Пояс', 'classes': ['Пояса']},
              {'id': 'ring1', 'name': 'Кольцо 1', 'classes': ['Кольца']},
              {'id': 'ring2', 'name': 'Кольцо 2', 'classes': ['Кольца']}],
    'steps': [{'id': 'riverbank', 'zone': 'G1_1', 'name': 'Берег реки'},
              {'id': 'trial', 'zone': 'G1_2', 'name': 'Испытание'},
              {'id': 'after', 'zone': 'G1_4', 'name': 'После вознесения'}],
    # В оружии вещи сменяют друг друга: самострелы в ходу по испытание (until), скипетр — с шага «После
    # вознесения» (use). Что это за вещь, говорит её цель (gear): по классу строка слота узнаёт свои вещи.
    'goals': [
        {'id': 'bow-1', 'slot': 'weapon', 'until': 'trial', 'gear': 'Самострелы', 'title': 'Самодельный самострел (Makeshift Crossbow)'},
        {'id': 'bow-2', 'slot': 'weapon', 'until': 'trial', 'title': 'Прочный самострел (Sturdy Crossbow)'},
        {'id': 'bow-3', 'slot': 'weapon', 'until': 'trial', 'title': 'Лакированный самострел (Varnished Crossbow)'},
        {'id': 'sceptre', 'slot': 'weapon', 'use': 'after', 'gear': 'Скипетры', 'title': 'Гремящий скипетр (Rattling Sceptre)'},
        {'id': 'body-any', 'slot': 'body', 'title': 'любой', 'any': True, 'soft': True},
        {'id': 'belt-any', 'slot': 'belt', 'title': 'любой', 'any': True, 'soft': True},
        {'id': 'belt-plate', 'slot': 'belt', 'title': 'Ремень из пластин (Plate Belt)'},
        {'id': 'ring1-any', 'slot': 'ring1', 'title': 'любое', 'any': True, 'soft': True},
        {'id': 'ring2-any', 'slot': 'ring2', 'title': 'любое', 'any': True, 'soft': True},
    ],
}

START = ['%s 20:07:03 1000 abcd [DEBUG Client 1] Generating level 1 area "G1_1" with seed 1' % DAY,
         '%s 20:07:03 1000 abcd [INFO Client 1] [SCENE] Set Source [Берег реки]' % DAY]
LATER = START + ['%s 21:00:00 1000 abcd [DEBUG Client 1] Generating level 4 area "G1_4" with seed 1' % DAY,
                 '%s 21:00:00 1000 abcd [INFO Client 1] [SCENE] Set Source [После вознесения]' % DAY]


def state(marks=(), lines=START, plan=PLAN):
    """План и состояние забега с такими отметками — как их видит страница."""
    plan, problems = core.norm_plan(plan)
    assert problems == [], problems
    parser = core.LogParser(core.heard_ids(plan))
    run = core.Run()
    for line in lines:
        for ev in parser.feed(line):
            if ev['type'] == 'start':
                run = core.Run(core.run_id(ev['ts']), ev['ts'])
            else:
                run.events.append(ev)
    for i, (goal, status) in enumerate(marks):
        run.marks.append({'ts': 5000 + i, 'goal': goal, 'status': status})
    return plan, core.derive(plan, run, 0)


def cmp(text, marks=(), lines=START, plan=PLAN):
    plan, view = state(marks, lines, plan)
    return itemcopy.compare(plan, view, itemcopy.parse(text))


# Копии из русского клиента (Ctrl+Alt+C), 2026-11-20: пояс с ремесленным суффиксом и скипетр с очернённым префиксом.
CRAFTED_BELT = '''Класс предмета: Пояса
Редкость: Редкий
Орлиная ловушка
Ремень из пластин
--------
Требуется: Уровень 37
--------
Уровень предмета: 55
--------
{ Собственное свойство — Броня }
+144(140-180) к броне
{ Собственное свойство — Оберег }
Имеет 2(1-2) ячейки для оберегов
--------
{ Префикс "Массивный" (Уровень: 4) — Здоровье }
+98(85-99) к максимуму здоровья
{ Префикс "Лазурный" (Уровень: 5) — Мана }
+63(55-64) к максимуму маны
{ Префикс "Пластинчатый" (Уровень: 6) — Броня }
+134(108-140) к броне
{ Суффикс "шквала" (Уровень: 7) — Стихийный, Молния, Сопротивление }
+14(11-15)% к сопротивлению молнии
{ Суффикс "выздоровления" (Уровень: 3) — Здоровье }
Регенерация 15.8(13.1-18) здоровья в секунду
{ Ремесленное Суффикс "саламандры" (Уровень: 7) — Стихийный, Огонь, Сопротивление }
+13(11-15)% к сопротивлению огню
'''

DESECRATED_SCEPTRE = '''Класс предмета: Скипетры
Редкость: Редкий
Кровавая песнь
Гремящий скипетр
--------
Дух: 128 (augmented)
--------
Требуется: Уровень 20
--------
Гнезда: S
--------
Уровень предмета: 33
--------
Дарует умение: Приспешник скелет-воин 9 уровня
--------
{ Префикс "Болезненный" (Уровень: 8) — Урон, Физический, Атака }
Союзники в вашем присутствии наносят от 2(2-3) до 5(4-6) дополнительного физического урона атаками
{ Префикс "Охлаждающий" (Уровень: 8) — Урон, Стихийный, Холод, Атака }
Союзники в вашем присутствии наносят от 4(3-4) до 5(5-8) дополнительного урона от холода атаками
{ Очернённое Префикс "Баронский" (Уровень: 7) }
28(27-32)% увеличение духа
{ Суффикс "деспота" (Уровень: 3) — Приспешник, Камень }
+2 к уровню всех камней умений приспешников
{ Суффикс "вспыльчивости" (Уровень: 6) — Урон, Критический }
10(10-14)% увеличение дополнительного критического урона союзников в вашем присутствии
{ Суффикс "сноровки" (Уровень: 3) — Чародейский, Скорость }
Союзники в вашем присутствии имеют 12(9-12)% повышение скорости сотворения чар
'''


class ParseTest(unittest.TestCase):
    def test_real_copy_from_the_russian_client(self):
        item = itemcopy.parse(REAL)
        self.assertEqual((item['cls'], item['rarity'], item['name'], item['base'], item['ilvl']),
                         ('Нательные доспехи', 'rare', 'Колючий спаситель', 'Полные латы', 47))
        self.assertTrue(item['advanced'] and item['identified'] and not item['corrupted'])
        self.assertEqual([(m['kind'], m['gen'], m['name'], m['tier']) for m in item['mods']], [
            ('rune', None, None, None),
            ('explicit', 'prefix', 'Массивный', 7), ('explicit', 'prefix', 'Омаровый', 5),
            ('explicit', 'prefix', 'Шипованный', 10), ('explicit', 'suffix', 'грозовой тучи', 5),
            ('explicit', 'suffix', 'силача', 8), ('explicit', 'suffix', 'углей', 8)])
        life, hybrid = item['mods'][1], item['mods'][2]
        # форма свойства — его текст с # вместо чисел, без диапазона тира
        self.assertEqual((life['shapes'], life['values'], life['ranges'], life['tags']),
                         (['+# к максимуму здоровья'], [[95.0]], [[(85.0, 99.0)]], ['Здоровье']))
        # гибрид — один заголовок, две строки
        self.assertEqual(hybrid['shapes'], ['#% повышение брони', '+# к максимуму здоровья'])
        self.assertEqual(hybrid['tags'], ['Здоровье', 'Броня'])
        self.assertEqual(item['mods'][0]['lines'], ['+36% к сопротивлению холоду'])
        # броня, требования и гнёзда — не свойства
        self.assertEqual(item['loose'], 3)

    def test_only_an_item_is_read(self):
        """В буфере может лежать что угодно: всё, что не начинается как вещь, не разбирается."""
        for text in ('пароль от почты', '', None, 42, 'Редкость: Редкий\nКласс предмета: Кольца',
                     'Класс предмета: Кольца\n' + 'x' * 30000):
            self.assertFalse(itemcopy.is_item(text))
            self.assertIsNone(itemcopy.parse(text))
        self.assertTrue(itemcopy.is_item('\r\n  Класс предмета: Кольца\r\nРедкость: Обычный\r\nЖелезное кольцо'))

    def test_plain_copy_has_no_tiers(self):
        plain = ('Класс предмета: Кольца\nРедкость: Редкий\nВихрь горя\nЖелезное кольцо\n--------\n'
                 'Уровень предмета: 12\n--------\nДобавляет от 1 до 4 физического урона к атакам (implicit)\n'
                 '--------\n+107 к максимуму здоровья\n+25% к сопротивлению молнии\n')
        item = itemcopy.parse(plain)
        self.assertFalse(item['advanced'])
        self.assertEqual([m['kind'] for m in item['mods']], ['implicit'])
        self.assertEqual(item['loose'], 2)

    def test_names_of_magic_normal_and_unusable_items(self):
        magic = itemcopy.parse(item_text('Самострелы', 'Гудящий Прочный самострел скорости', rarity='Волшебный'))
        self.assertEqual((magic['rarity'], magic['name'], magic['base']),
                         ('magic', 'Гудящий Прочный самострел скорости', 'Гудящий Прочный самострел скорости'))
        # вещь не по требованиям: строка об этом встаёт в шапку, а имя и база уезжают в следующую секцию
        text = ('Класс предмета: Шлемы\nРедкость: Редкий\n'
                'Вы не можете использовать этот предмет, его параметры не будут учтены\n--------\n'
                'Венец бури\nШапка мудреца\n--------\nУровень предмета: 30\n')
        item = itemcopy.parse(text)
        self.assertEqual((item['name'], item['base'], item['ilvl']), ('Венец бури', 'Шапка мудреца', 30))

    def test_unidentified_and_english_client(self):
        raw = itemcopy.parse('Класс предмета: Кольца\nРедкость: Редкий\nЖелезное кольцо\n--------\n'
                             'Уровень предмета: 40\n--------\nНеопознано\n')
        self.assertFalse(raw['identified'])
        en = itemcopy.parse('Item Class: Rings\nRarity: Rare\nGale Whorl\nIron Ring\n--------\nItem Level: 40\n'
                            '--------\n{ Prefix Modifier "Hale" (Tier: 8) — Life }\n+15(10-19) to maximum Life\n')
        self.assertEqual((en['cls'], en['rarity'], en['ilvl']), ('Rings', 'rare', 40))
        self.assertEqual([(m['kind'], m['gen'], m['name'], m['tier'], m['shapes']) for m in en['mods']],
                         [('explicit', 'prefix', 'Hale', 8, ['+# to maximum Life'])])

    def test_crafted_desecrated_and_fractured_marks_are_kept(self):
        """Аффикс от сущности, очернённый и расколотый — для сравнения всё тот же аффикс (kind — explicit), но пометка
        хранится у свойства (how): её читает помощник крафта. У обычного аффикса поля нет, и предмет, запомненный до
        пометок, узнаётся по-прежнему."""
        text = ('Класс предмета: Скипетры|Редкость: Редкий|Кровавая песнь|Гремящий скипетр|--------|Уровень предмета: 55|--------|'
                '{ Очернённый префикс "Маркиза" (Уровень: 5) — Дух }|28(27-32)% увеличение духа|'
                '{ Префикс "Сущности" — Урон }|Союзники в вашем присутствии наносят увеличенный на 80(75-89)% урон (crafted)|'
                '{ Суффикс "Надзирателя" (Уровень: 2) — Приспешник }|+3 к уровню всех умений приспешников (fractured)|'
                '{ Суффикс "Льда" (Уровень: 4) — Холод }|+20(16-20)% к сопротивлению холоду|').replace('|', chr(10))
        item = itemcopy.parse(text)
        self.assertEqual([(m['kind'], m['gen'], m.get('how')) for m in item['mods']],
                         [('explicit', 'prefix', 'desecrated'), ('explicit', 'prefix', 'crafted'),
                          ('explicit', 'suffix', 'fractured'), ('explicit', 'suffix', None)])
        self.assertNotIn('how', item['mods'][3])
        old = itemcopy.parse(text)
        for m in old['mods']:
            m.pop('how', None)                       # так предмет был запомнен до пометок
        self.assertTrue(itemcopy.same_item(dict(item, at=1), dict(old, at=2)))
        self.assertFalse(itemcopy.same_item(item, dict(old, ilvl=56)))

    def test_crafted_and_desecrated_affixes_of_the_russian_client(self):
        """Настоящие копии: пометка стоит словом в начале заголовка аффикса — «Ремесленное Суффикс …», «Очернённое
        Префикс …» (у очернённого нет и списка меток после тире); в конце строки свойства пометки нет."""
        belt = itemcopy.parse(CRAFTED_BELT)
        self.assertEqual((belt['base'], belt['rarity'], belt['ilvl'], belt['advanced']), ('Ремень из пластин', 'rare', 55, True))
        self.assertEqual([(m['kind'], m['gen'], m['name'], m['tier'], m.get('how')) for m in belt['mods']], [
            ('implicit', None, None, None, None), ('implicit', None, None, None, None),
            ('explicit', 'prefix', 'Массивный', 4, None), ('explicit', 'prefix', 'Лазурный', 5, None),
            ('explicit', 'prefix', 'Пластинчатый', 6, None), ('explicit', 'suffix', 'шквала', 7, None),
            ('explicit', 'suffix', 'выздоровления', 3, None), ('explicit', 'suffix', 'саламандры', 7, 'crafted')])
        self.assertEqual((belt['mods'][-1]['lines'], belt['mods'][-1]['tags'], belt['mods'][-1]['ranges']),
                         (['+13(11-15)% к сопротивлению огню'], ['Стихийный', 'Огонь', 'Сопротивление'], [[(11.0, 15.0)]]))
        sceptre = itemcopy.parse(DESECRATED_SCEPTRE)
        self.assertEqual([(m['gen'], m['name'], m['tier'], m.get('how')) for m in sceptre['mods']], [
            ('prefix', 'Болезненный', 8, None), ('prefix', 'Охлаждающий', 8, None), ('prefix', 'Баронский', 7, 'desecrated'),
            ('suffix', 'деспота', 3, None), ('suffix', 'вспыльчивости', 6, None), ('suffix', 'сноровки', 3, None)])
        dark = sceptre['mods'][2]
        self.assertEqual((dark['kind'], dark['tags'], dark['lines'], dark['ranges']),
                         ('explicit', [], ['28(27-32)% увеличение духа'], [[(27.0, 32.0)]]))
        # свойство с одним числом идёт в копии без диапазона
        self.assertEqual((sceptre['mods'][3]['lines'], sceptre['mods'][3]['values'], sceptre['mods'][3]['ranges']),
                         (['+2 к уровню всех камней умений приспешников'], [[2.0]], [[]]))

    def test_shape_of_a_line(self):
        for line, shape, values in (
                ('Добавляет от 2(1-2) до 22(20-24) урона от молнии', 'Добавляет от # до # урона от молнии', [2, 22]),
                ('10% повышение скорости передвижения', '#% повышение скорости передвижения', [10]),
                ('+1 к уровню всех камней умений приспешников', '+# к уровню всех камней умений приспешников', [1]),
                ('6.5(6-6.9)% физического урона от атак похищается в виде здоровья (desecrated)',
                 '#% физического урона от атак похищается в виде здоровья', [6.5])):
            s = itemcopy.stat_line(line)
            self.assertEqual((s['shape'], s['values']), (shape, values))


class CompareTest(unittest.TestCase):
    """Куда идёт вещь из буфера и что «надеть» отметит в плане. Чем она лучше надетой, решают статы
    (test_herostats)."""

    def test_item_finds_its_slot(self):
        c = cmp(REAL)
        self.assertEqual((c['name'], c['base'], c['rarity'], c['ilvl'], c['pick'], c['note']),
                         ('Колючий спаситель', 'Полные латы', 'rare', 47, 'slot:body:', None))
        row = c['rows'][0]
        self.assertEqual((row['row'], row['slot'], row['slotName'], row['line'], row['held']),
                         ('slot:body:', 'body', 'Нательный доспех', None, False))
        self.assertNotIn('stash', row)
        # база плана — «любой доспех»: о базе сказать нечего, «надеть» отметит слот занятым
        self.assertEqual((row['base']['named'], row['base']['to'], row['base']['delta']), (False, 'body-any', 0))
        self.assertEqual(itemcopy.wear_marks(c, 'slot:body:'), [('body-any', 2)])
        self.assertIsNone(itemcopy.wear_marks(c, 'slot:nowhere:'))
        # слот уже отмечен занятым
        self.assertTrue(cmp(REAL, [('body-any', 2)])['rows'][0]['held'])

    def test_ring_has_two_slots(self):
        ring = item_text('Кольца', 'Вихрь горя', 'Железное кольцо', [
            ('Префикс "Здоровый" (Уровень: 6) — Здоровье', '+75(70-84) к максимуму здоровья')])
        c = cmp(ring, [('ring1-any', 2)])
        self.assertEqual([(r['row'], r['held']) for r in c['rows']], [('slot:ring1:', True), ('slot:ring2:', False)])

    def test_weapon_in_use_and_the_one_worn_later(self):
        bow = item_text('Самострелы', 'Гудящий Прочный самострел', rarity='Волшебный', mods=[
            ('Префикс "Гудящий" (Уровень: 8) — Урон, Стихийный, Молния, Атака',
             'Добавляет от 1 до 30(27-33) урона от молнии')])
        c = cmp(bow, [('bow-1', 2)])
        self.assertEqual([(r['row'], r['line']) for r in c['rows']], [('slot:weapon:', None)])
        # база — в имени волшебной вещи; самострел получше надетого
        b = c['rows'][0]['base']
        self.assertEqual((b['named'], b['now'], b['new'], b['to'], b['delta']),
                         (True, 'Самодельный самострел (Makeshift Crossbow)', 'Прочный самострел (Sturdy Crossbow)', 'bow-2', 1))
        # «надеть» ставит вещь на её базу и снимает отметки баз получше
        self.assertEqual(itemcopy.wear_marks(c, 'slot:weapon:'), [('bow-3', 0), ('bow-2', 2)])
        self.assertEqual(cmp(bow, [('bow-3', 2)])['rows'][0]['base']['delta'], -1)
        # Скипетр до вознесения (по плану его носят после): рюкзака нет — его можно надеть в оружие и сейчас; цели плана
        # он сейчас не отвечает, отмечать нечего (сделана будет цель скипетра, когда её период настанет)
        sceptre = item_text('Скипетры', 'Гром душ', 'Гремящий скипетр', [
            ('Префикс "Вельможеский" (Уровень: 3) — Дух', '22(20-26)% увеличение духа')])
        c = cmp(sceptre, [('bow-1', 2)])
        self.assertEqual([(r['row'], r['line']) for r in c['rows']], [('slot:weapon:', None)])
        self.assertEqual((c['rows'][0]['base']['to'], itemcopy.wear_marks(c, 'slot:weapon:')), (None, []))
        # с шага, на котором скипетр входит в ход, он отвечает цели периода
        c = cmp(sceptre, [('bow-1', 2)], LATER)
        self.assertEqual([(r['row'], r['line']) for r in c['rows']], [('slot:weapon:', 'after')])
        self.assertEqual(itemcopy.wear_marks(c, 'slot:weapon:'), [('sceptre', 2)])
        # самострел после вознесения план не называет, но надеть его можно всегда: в оружии самострелы носят
        c = cmp(bow, [('bow-1', 2)], LATER)
        self.assertEqual(([(r['row'], r['base']['to']) for r in c['rows']], c['pick'], c['note']),
                         ([('slot:weapon:', None)], 'slot:weapon:', None))

    def test_named_base_against_any_base(self):
        belt = item_text('Пояса', 'Узы', 'Ремень из пластин')
        b = cmp(belt, [('belt-any', 2)])['rows'][0]['base']
        self.assertEqual((b['to'], b['delta'], b['named']), ('belt-plate', 1, True))
        # другой пояс вместо ремня из пластин: база хуже, отметка ремня снимется
        c = cmp(item_text('Пояса', 'Узы', 'Кожаный пояс'), [('belt-plate', 2)])
        self.assertEqual((c['rows'][0]['base']['to'], c['rows'][0]['base']['delta']), ('belt-any', -1))
        self.assertEqual(itemcopy.wear_marks(c, 'slot:belt:'), [('belt-plate', 0), ('belt-any', 2)])
        # в пустом слоте о базе сравнивать не с чем
        self.assertEqual(cmp(belt)['rows'][0]['base']['delta'], 0)
        # самострел, которого в плане нет: отметить нечего
        odd = cmp(item_text('Самострелы', 'Имя', 'Осадный самострел'))
        self.assertEqual((odd['rows'][0]['base']['to'], itemcopy.wear_marks(odd, 'slot:weapon:')), (None, []))

    def test_what_has_no_slot(self):
        c = cmp(item_text('Посохи', 'Имя', 'Дубовый посох'))
        self.assertEqual((c['rows'], c['note']), ([], 'класс «Посохи» не из плана'))
        raw = cmp('Класс предмета: Кольца\nРедкость: Редкий\nЖелезное кольцо\n--------\nНеопознано\n')
        self.assertEqual((raw['note'], len(raw['rows'])), ('предмет не опознан', 2))
        self.assertIsNone(itemcopy.compare(PLAN, {}, None))

    def test_plan_fields_are_checked(self):
        bad = dict(PLAN, slots=PLAN['slots'][:-1] + [{'id': 'ring2', 'name': 'Кольцо 2', 'classes': 'Кольца'}])
        self.assertEqual(core.norm_plan(bad)[1], ['Слот «ring2»: classes — список классов предметов, как их пишет игра'])


# --- каталог данных игры: вещь из буфера на идентификаторах игры ------------------------------------

def fam(kind, gen, stat, fmt, tiers_, lines=None):
    """Семейство аффиксов, как в каталоге: tiers_ — (уровень предмета, от, до, метки баз)."""
    stats = stat.split()
    return {'type': kind, 'gen': gen, 'stats': stats, 'lines': lines if lines is not None else [stat], 'fmt': [fmt],
            'mods': [{'id': '%s%d' % (kind, i + 1), 'name': kind, 'level': lv,
                      'vals': [[lo, hi]] * len(stats), 'on': [[t, 1] for t in on] + [['default', 0]]}
                     for i, (lv, lo, hi, on) in enumerate(tiers_)]}


ARM, RING = ['body_armour'], ['ring']
CAT = {
    'version': 'test', 'areas': {},
    'bases': {'Body/Plate': {'name': 'Full Plate', 'class': 'Body Armour', 'level': 33, 'req': {},
                             'tags': ['str_armour', 'body_armour', 'armour', 'default']},
              'Belts/Plate': {'name': 'Plate Belt', 'class': 'Belt', 'level': 25, 'req': {}, 'tags': ['belt', 'default']},
              'Rings/Iron': {'name': 'Iron Ring', 'class': 'Ring', 'level': 1, 'req': {}, 'tags': ['ring', 'default']}},
    'mods': {
        'IncreasedLife|prefix|life': fam('IncreasedLife', 'prefix', 'life', '+#', [
            (1, 10, 19, ARM + RING), (6, 20, 29, ARM + RING), (80, 200, 214, ARM)]),
        'FireResistance|suffix|fire': fam('FireResistance', 'suffix', 'fire', '+#%', [
            (1, 6, 10, ARM + RING), (12, 11, 15, ARM + RING), (24, 16, 20, ARM + RING)]),
        'ColdResistance|suffix|cold': fam('ColdResistance', 'suffix', 'cold', '+#%', [
            (1, 6, 10, ARM + RING), (14, 11, 15, ARM + RING), (26, 16, 20, ARM + RING)]),
        'Armour|prefix|local_armour': fam('Armour', 'prefix', 'local_armour', '+#', [(1, 16, 27, ['str_armour'])]),
        'Armour|prefix|global_armour': fam('Armour', 'prefix', 'global_armour', '+#', [(1, 12, 22, ['belt'])]),
        'ArmourLife|prefix|armour_pct life': fam('ArmourLife', 'prefix', 'armour_pct life', '#%', [
            (8, 6, 13, ['str_armour'])], lines=['armour_pct', 'life']),
        'Fire|prefix|min_fire max_fire': fam('Fire', 'prefix', 'min_fire max_fire', '#', [
            (1, 1, 4, RING), (8, 5, 9, RING)], lines=['min_fire max_fire']),
    },
    'lang': {
        'ru': {'classes': {'Кольца': 'Ring'},
               'bases': {'Full Plate': 'Полные латы', 'Plate Belt': 'Ремень из пластин', 'Iron Ring': 'Железное кольцо'},
               'stats': {'life': ['# к максимуму здоровья'], 'fire': ['#% к сопротивлению огню'],
                         'cold': ['#% к сопротивлению холоду'], 'local_armour': ['# к броне'],
                         'global_armour': ['# к броне'], 'armour_pct': ['#% повышение брони']}},
        'en': {'bases': {'Full Plate': 'Full Plate', 'Plate Belt': 'Plate Belt', 'Iron Ring': 'Iron Ring'},
               'stats': {'life': ['# to maximum Life'], 'fire': ['#% to Fire Resistance'],
                         'cold': ['#% to Cold Resistance'], 'local_armour': ['# to Armour'],
                         'global_armour': ['# to Armour'], 'armour_pct': ['#% increased Armour']}},
    },
}
# план, который называет классы вещей идентификаторами игры
BY_ID = {
    'title': 'каталог',
    'slots': [{'id': 'body', 'name': 'Нательный доспех', 'classes': ['Body Armour'], 'gear': 'Body Armour str_armour'},
              {'id': 'belt', 'name': 'Пояс', 'classes': ['Belt'], 'gear': 'Belt'},
              {'id': 'ring1', 'name': 'Кольцо 1', 'classes': ['Ring'], 'gear': 'Ring'}],
    'steps': [{'id': 'riverbank', 'zone': 'G1_1', 'name': 'Берег реки'}, {'id': 'next', 'zone': 'G1_2', 'name': 'Дальше'}],
    'goals': [{'id': 'body-any', 'slot': 'body', 'title': 'любой', 'any': True, 'soft': True},
              {'id': 'belt-any', 'slot': 'belt', 'title': 'любой', 'any': True, 'soft': True},
              {'id': 'ring1-any', 'slot': 'ring1', 'title': 'любое', 'any': True, 'soft': True}],
}


def cat_cmp(text):
    plan, view = state(plan=BY_ID)
    return itemcopy.compare(plan, view, itemcopy.identify(CAT, itemcopy.parse(text)))


class CatalogTest(unittest.TestCase):
    def test_item_is_recognised_by_game_ids(self):
        ru = item_text('Нательные доспехи', 'Колючий спаситель', 'Полные латы', [
            ('Префикс "Массивный" (Уровень: 2) — Здоровье', '+25(20-29) к максимуму здоровья'),
            ('Префикс "Омаровый" (Уровень: 1) — Здоровье, Броня', '9(6-13)% повышение брони',
             '+12(6-13) к максимуму здоровья'),
            ('Префикс "Шипованный" (Уровень: 1) — Броня', '+20(16-27) к броне'),
            ('Суффикс "углей" (Уровень: 3) — Сопротивление', '+6(6-10)% к сопротивлению огню'),
            ('Суффикс "тюленя" (Уровень: 2) — Сопротивление', '+12(11-15)% к сопротивлению холоду')])
        item = itemcopy.identify(CAT, itemcopy.parse(ru))
        self.assertEqual((item['lang'], item['cls_id'], item['tags'][:2]), ('ru', 'Body Armour', ['str_armour', 'body_armour']))
        self.assertEqual([m['fam'] for m in item['mods']], [
            'IncreasedLife|prefix|life', 'ArmourLife|prefix|armour_pct life', 'Armour|prefix|local_armour',
            'FireResistance|suffix|fire', 'ColdResistance|suffix|cold'])
        # слот находится по классу базы — идентификатору игры, а не по слову клиента
        self.assertEqual([r['row'] for r in cat_cmp(ru)['rows']], ['slot:body:'])
        # та же вещь из английского клиента узнаётся так же: план от языка не зависит
        en = ('Item Class: Body Armours\nRarity: Rare\nThorn Saviour\nFull Plate\n--------\nItem Level: 47\n--------\n'
              '{ Prefix Modifier "Healthy" (Tier: 2) — Life }\n+25(20-29) to maximum Life\n'
              '{ Prefix Modifier "Lacquered" (Tier: 1) — Armour }\n+20(16-27) to Armour\n'
              '{ Suffix Modifier "of Embers" (Tier: 3) — Resistance }\n+6(6-10)% to Fire Resistance\n'
              '{ Suffix Modifier "of the Seal" (Tier: 2) — Resistance }\n+12(11-15)% to Cold Resistance\n')
        other = itemcopy.identify(CAT, itemcopy.parse(en))
        self.assertEqual((other['lang'], other['cls_id'], [m['fam'] for m in other['mods']]),
                         ('en', 'Body Armour', ['IncreasedLife|prefix|life', 'Armour|prefix|local_armour',
                                                'FireResistance|suffix|fire', 'ColdResistance|suffix|cold']))
        self.assertEqual([r['row'] for r in cat_cmp(en)['rows']], ['slot:body:'])
        # «к броне» на поясе — другое свойство игры, чем на доспехе: вещь находит своё по своей базе
        belt = itemcopy.identify(CAT, itemcopy.parse(item_text('Пояса', 'Узы', 'Ремень из пластин', [
            ('Префикс "Лакированный" (Уровень: 1) — Броня', '+15(12-22) к броне')])))
        self.assertEqual((belt['cls_id'], belt['mods'][0]['fam']), ('Belt', 'Armour|prefix|global_armour'))
        # волшебная вещь: база — внутри имени
        magic = itemcopy.identify(CAT, itemcopy.parse(
            item_text('Кольца', 'Крепкое Железное кольцо углей', rarity='Волшебный')))
        self.assertEqual(magic['cls_id'], 'Ring')
        # названия базы нет в данных игры: слот находится по строке «Класс предмета» (слова слоя языка)
        new = cat_cmp(item_text('Кольца', 'Имя', 'Кольцо грёз', [
            ('Префикс "Крепкий" (Уровень: 2) — Здоровье', '+15(10-19) к максимуму здоровья')]))
        self.assertEqual([r['row'] for r in new['rows']], ['slot:ring1:'])
        # нет ни базы, ни такого класса — так и сказано
        odd = cat_cmp(item_text('Жезлы', 'Имя', 'Жезл грёз'))
        self.assertEqual((odd['rows'], odd['note']), ([], 'база «Жезл грёз» не найдена в данных игры'))

    @unittest.skipUnless(os.path.isfile(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'catalog',
                                                     'data', 'current.txt')), 'нет собранного каталога')
    def test_real_item_on_the_real_catalogue(self):
        """Настоящая вещь из игры на настоящем каталоге: семейства и тиры те же, что видел игрок."""
        import gamedata
        cat = gamedata.load(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'catalog', 'data'))
        item = itemcopy.identify(cat, itemcopy.parse(REAL))
        self.assertEqual((item['cls_id'], 'str_armour' in item['tags'], 'body_armour' in item['tags']),
                         ('Body Armour', True, True))
        self.assertEqual([(m['fam'].split('|')[0] if m['fam'] else None, m['tier']) for m in item['mods'] if m['kind'] == 'explicit'], [
            ('IncreasedLife', 7), ('LocalIncreasedArmourAndLife', 5), ('LocalPhysicalDamageReductionRating', 10),
            ('LightningResistance', 5), ('Strength', 8), ('FireResistance', 8)])
        tiers = {t['tier']: t for t in gamedata.tiers(cat['mods'][item['mods'][1]['fam']], item['tags'])}
        self.assertEqual(tiers[7]['vals'], [[85, 99]])


class ClientLanguageTest(unittest.TestCase):
    """Копия предмета на любом из языков игры: подписи, классы, базы и строки свойств — из таблиц игры в каталоге."""

    @classmethod
    def setUpClass(cls):
        import gamedata
        cls.cat = gamedata.load(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'catalog', 'data'))
        if not cls.cat or 'ja' not in cls.cat['lang']:
            raise unittest.SkipTest('в каталоге нет языков клиента')
        itemcopy.use_catalog(cls.cat)

    @classmethod
    def tearDownClass(cls):
        itemcopy.use_catalog(None)          # прочим проверкам — встроенные подписи

    def copy_in(self, lang, mods):
        """Полные латы с аффиксами mods [(gen, тир, ключ строки, число)] — копией клиента на языке lang."""
        pack, c = self.cat['lang'][lang], self.cat['lang'][lang]['copy']
        cls_word = next(w for w, cid in pack['classes'].items() if cid == 'Body Armour')
        rare = next(w for w, k in c['rarities'].items() if k == 'rare')
        out = ['%s: %s' % (c['class'], cls_word), '%s: %s' % (c['rarity'], rare), 'Name', pack['bases']['Full Plate'],
               '--------', '%s: %d' % (c['ilvl'], 47), '--------']
        for gen, tier, key, value in mods:
            head = c['prefix' if gen == 'prefix' else 'suffix'].replace('{0}', 'X')
            out.append('{ %s %s }' % (head, c['tier'].replace('{0}', str(tier))))
            out.append(pack['stats'][key][0].replace('#', str(value), 1))
        return '\n'.join(out)

    def test_same_item_in_every_language(self):
        mods = [('prefix', 2, 'base_maximum_life', 25), ('suffix', 3, 'base_fire_damage_resistance_%', 6)]
        want = None
        for lang in ('ru', 'en', 'de', 'fr', 'ja', 'ko', 'th', 'zh-Hant', 'es', 'pt'):
            item = itemcopy.identify(self.cat, itemcopy.parse(self.copy_in(lang, mods)))
            got = (item['lang'], item['cls_id'], item['base_en'], [(m['gen'], m['tier'], m['fam']) for m in item['mods']])
            want = want or ('', 'Body Armour', 'Full Plate', got[3])
            self.assertEqual(got[1:], want[1:], lang)
            self.assertEqual(got[0], lang)
            self.assertTrue(all(f for _, _, f in got[3]), lang)

    def unique_in(self, lang):
        """«Ремень Мегинорда» (Meginord's Girdle) копией клиента на языке lang (Ctrl+Alt+C): собственные свойства базы,
        свойства уникального и строки описания. Имя — как его пишет клиент этого языка (тайский — по-английски)."""
        pack, c = self.cat['lang'][lang], self.cat['lang'][lang]['copy']
        cls_word = next(w for w, cid in pack['classes'].items() if cid == 'Belt')
        unique = next(w for w, k in c['rarities'].items() if k == 'unique')
        name = next((w for w, en in (pack.get('uniques') or {}).items() if en == "Meginord's Girdle"), "Meginord's Girdle")
        line = lambda key, value: pack['stats'][key][0].replace('#', value, 1)
        return '\n'.join(['%s: %s' % (c['class'], cls_word), '%s: %s' % (c['rarity'], unique), name,
                          pack['bases']['Rawhide Belt'], '--------', '%s: %d' % (c['ilvl'], 11), '--------',
                          '{ %s }' % c['implicit'], line('flask_life_to_recover_+%', '20(20-30)'),
                          '{ %s }' % c['implicit'], line('local_charm_slots', '1(1-3)'), '--------',
                          '{ %s }' % c['uniqueMod'], line('additional_strength', '+43(40-50)'),
                          '{ %s }' % c['uniqueMod'], line('base_cold_damage_resistance_%', '+11(10-15)'),
                          '{ %s }' % c['uniqueMod'], line('flask_charges_gained_+%', '100'),
                          '{ %s }' % c['uniqueMod'], line('flask_charges_used_+%', '50'),
                          '--------', 'Kaom', 'Meginord'])

    def test_unique_item_in_every_language(self):
        """Уникальный предмет на любом языке клиента: его свойства — свойства уникального (не аффиксы и не «прочее»),
        они идут в статы героя; по имени он находится в каталоге — у него своя картинка, а не рисунок базы."""
        import gamedata
        import itemstats
        for lang in ('ru', 'en', 'de', 'fr', 'ja', 'ko', 'th', 'zh-Hant', 'es', 'pt'):
            item = itemcopy.identify(self.cat, itemcopy.parse(self.unique_in(lang)))
            self.assertEqual((item['rarity'], item['cls_id'], item['base_en']), ('unique', 'Belt', 'Rawhide Belt'), lang)
            self.assertEqual([m['kind'] for m in item['mods']], ['implicit'] * 2 + ['unique'] * 4, lang)
            self.assertEqual(gamedata.find_unique(self.cat, lang, item['name'], item['base_en'])[0], "Meginord's Girdle", lang)
            self.assertEqual(gamedata.item_icon(self.cat, item), 'uniq-meginordsgirdle', lang)
            p = itemstats.passport(self.cat, item)
            self.assertEqual((p['stats'].get('str'), p['stats'].get('res_cold')), (43, 11), lang)
            self.assertEqual({x['src'] for x in p['parts']['str'] + p['parts']['res_cold']}, {'unique'}, lang)

    def test_unique_name_shared_by_two_uniques(self):
        """Одно имя у двух уникальных на языке клиента (по-немецки «Atziris Verachtung»): выбирает база; не выбрала —
        уникальный не назван (картинкой остаётся рисунок базы, а не чужого предмета)."""
        import gamedata
        layer = self.cat['lang']['de'].get('uniques') or {}
        shared = next(((local, ens) for local, ens in layer.items() if isinstance(ens, list)), None)
        if shared is None:
            self.skipTest('в каталоге нет общих имён')
        local, ens = shared
        base = self.cat['uniques'][ens[1]]['bases'][0]
        self.assertEqual(gamedata.find_unique(self.cat, 'de', local, base)[0], ens[1])
        self.assertIsNone(gamedata.find_unique(self.cat, 'de', local, None))
        item = {'rarity': 'unique', 'lang': 'de', 'name': local, 'base_en': 'Rawhide Belt'}
        self.assertEqual(gamedata.item_icon(self.cat, item), gamedata.base_icon(self.cat, item))

    def test_affix_headers_of_other_languages(self):
        # японские кавычки «」», французские «ёлочки» и пробел перед двоеточием, тайское «ремесленное» после имени
        ja = itemcopy._mod_head('プレフィックスモッド「健康」 (ティア: 4) — ライフ', itemcopy.copy_lang('アイテムクラス: 指輪'))
        self.assertEqual((ja['gen'], ja['name'], ja['tier']), ('prefix', '健康', 4))
        fr = itemcopy._mod_head('Préfixe : « Sain » (Palier : 2) — Vie', itemcopy.copy_lang("Classe d'objet : Bagues"))
        self.assertEqual((fr['gen'], fr['name'], fr['tier']), ('prefix', 'Sain', 2))
        th = itemcopy.copy_lang('ชนิดไอเทม: แหวน')
        crafted = itemcopy._mod_head('ม็อดซัฟฟิกซ์ "X" ที่ถูกคราฟท์ (อันดับ: 1)', th)
        self.assertEqual((crafted['gen'], crafted.get('how'), crafted['tier']), ('suffix', 'crafted', 1))

    def test_requirements_with_a_wide_colon(self):
        import itemstats
        pack = self.cat['lang']['zh-Hant']
        words = pack['words']
        plain = [itemcopy.stat_line('%s：%s 36，54 %s' % (words['requires'], words['level'][0], words['str'][0]))]
        props, req, sockets = itemstats._props(pack, plain)
        self.assertEqual(req, {'level': 36, 'str': 54})


if __name__ == '__main__':
    unittest.main()
