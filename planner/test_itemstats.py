# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Sergei Labutin
# Additional terms under GPL-3.0 section 7: see NOTICE.md
"""Паспорт вещи (сумма по статам героя) и таблица «что искать на слоте».
Запуск: python -m unittest planner.test_itemstats"""
import os
import sys
import unittest
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import gamedata  # noqa: E402
import itemcopy  # noqa: E402
import itemstats  # noqa: E402
import slotstats  # noqa: E402


def fam(kind, gen, stats, tiers, lines=None):
    """Семейство аффикса: tiers — [(уровень предмета, [[от, до] на свойство], метки баз)]."""
    return {'type': kind, 'gen': gen, 'stats': stats, 'lines': lines or [' '.join(stats)] if len(stats) == 1 else lines or stats,
            'fmt': ['#'] * len(stats),
            'mods': [{'id': '%s%d' % (kind, i), 'level': lv, 'vals': vals, 'on': [[t, 1] for t in on] + [['default', 0]]}
                     for i, (lv, vals, on) in enumerate(tiers)]}


# Маленький каталог того же вида, что собирает catalog/build.py
CAT = {
    'bases': {
        'Armours/Body/Plate': {'name': 'Full Plate', 'class': 'Body Armour', 'tags': ['str_armour', 'body_armour', 'armour', 'default'],
                               'level': 33, 'req': {}, 'props': {'armour': 270}},
        'Armours/Helmets/Hat': {'name': 'Sage Hat', 'class': 'Helmet', 'tags': ['int_armour', 'helmet', 'armour', 'default'],
                                'level': 20, 'req': {}, 'props': {'energy_shield': 40}},
        'Armours/Boots/B': {'name': 'Rough Greaves', 'class': 'Boots', 'tags': ['str_armour', 'boots', 'armour', 'default'], 'level': 1, 'req': {}},
        'Belts/B': {'name': 'Rawhide Belt', 'class': 'Belt', 'tags': ['belt', 'default'], 'level': 1, 'req': {}},
        'Amulets/Solar': {'name': 'Solar Amulet', 'class': 'Amulet', 'tags': ['amulet', 'default'], 'level': 1, 'req': {},
                          'implicits': ['AmuletSpirit']},
        'Amulets/Plain': {'name': 'Crimson Amulet', 'class': 'Amulet', 'tags': ['amulet', 'default'], 'level': 1, 'req': {}},
        'Sceptres/S': {'name': 'Rattling Sceptre', 'class': 'Sceptre', 'tags': ['sceptre', 'onehand', 'default'], 'level': 1, 'req': {}},
        'Weapons/Bow': {'name': 'Crude Bow', 'class': 'Bow', 'tags': ['bow', 'weapon', 'default'], 'level': 1, 'req': {}},
    },
    'mods': {
        'Life|prefix|life': fam('Life', 'prefix', ['life'], [(1, [[10, 19]], ['armour', 'amulet', 'belt']),
                                                             (46, [[85, 99]], ['armour', 'amulet', 'belt'])]),
        'ArmourLife|prefix|local_armour_pct life': fam('ArmourLife', 'prefix', ['local_armour_pct', 'life'],
                                                       [(8, [[14, 20], [11, 19]], ['str_armour'])], ['local_armour_pct', 'life']),
        'Armour|prefix|local_armour': fam('Armour', 'prefix', ['local_armour'], [(1, [[28, 56]], ['str_armour'])]),
        'Armour|prefix|armour': fam('Armour', 'prefix', ['armour'], [(1, [[12, 22]], ['belt'])]),
        'Cold|suffix|cold': fam('Cold', 'suffix', ['cold'], [(1, [[6, 10]], ['armour', 'amulet', 'belt']),
                                                           (60, [[31, 35]], ['armour', 'amulet', 'belt'])]),
        'Fire|suffix|fire': fam('Fire', 'suffix', ['fire'], [(1, [[6, 10]], ['armour', 'amulet', 'belt'])]),
        'AllRes|suffix|allres': fam('AllRes', 'suffix', ['allres'], [(20, [[3, 5]], ['amulet'])]),
        'Speed|prefix|speed': fam('Speed', 'prefix', ['speed'], [(1, [[10, 10]], ['boots']), (65, [[30, 30]], ['boots']),
                                                              (82, [[35, 35]], ['boots'])]),
        'Minion|suffix|minion': fam('Minion', 'suffix', ['minion'], [(5, [[1, 1]], ['helmet', 'amulet', 'sceptre']),
                                                                  (41, [[2, 2]], ['helmet', 'amulet', 'sceptre']),
                                                                  (75, [[3, 3]], ['amulet', 'sceptre'])]),
        'Spirit|prefix|spirit': fam('Spirit', 'prefix', ['spirit'], [(16, [[30, 33]], ['body_armour', 'amulet'])]),
        'SpiritPct|prefix|local_spirit_pct': fam('SpiritPct', 'prefix', ['local_spirit_pct'], [(1, [[30, 40]], ['sceptre'])]),
    },
    'implicits': {'AmuletSpirit': {'stats': ['spirit_eq'], 'vals': [[10, 15]], 'lines': ['spirit_eq']}},
    'augments': {
        'RuneCold': {'name': 'Glacial Rune', 'type': 'Rune', 'level': 15, 'on': {
            'Armour': {'stats': ['cold'], 'vals': [14], 'lines': ['cold']},
            'Martial Weapon': {'stats': ['wcold_min', 'wcold_max'], 'vals': [6, 10], 'lines': None}}},
        'RuneColdGreater': {'name': 'Greater Glacial Rune', 'type': 'Rune', 'level': 30, 'on': {
            'Armour': {'stats': ['cold'], 'vals': [18], 'lines': ['cold']}}},
        'RuneStr': {'name': 'Adept Rune', 'type': 'Rune', 'level': 15, 'on': {'All': {'stats': ['str'], 'vals': [9], 'lines': ['str']}}},
        'CoreBoots': {'name': 'Soul Core', 'type': 'SoulCore', 'level': 60, 'on': {
            'Boots': {'stats': ['speed'], 'vals': [5], 'lines': ['speed']}}},
    },
    'stats': {
        'order': ['minion_level', 'spirit', 'speed', 'res_fire', 'res_cold', 'life', 'armour', 'es', 'str'],
        'stats': {
            'minion_level': {'ids': ['minion'], 'local': []},
            'spirit': {'ids': ['spirit', 'spirit_eq'], 'local': ['local_spirit_pct'], 'prop': 'spirit'},
            'speed': {'ids': ['speed'], 'local': [], 'unit': '%'},
            'res_fire': {'ids': ['fire', 'allres'], 'local': [], 'unit': '%', 'cap': 75},
            'res_cold': {'ids': ['cold', 'allres'], 'local': [], 'unit': '%', 'cap': 75},
            'life': {'ids': ['life'], 'local': []},
            'armour': {'ids': ['armour'], 'local': ['local_armour', 'local_armour_pct'], 'prop': 'armour'},
            'es': {'ids': ['es'], 'local': ['local_es'], 'prop': 'energy_shield'},
            'str': {'ids': ['str'], 'local': []},
        }},
    'lang': {'ru': {
        'bases': {'Full Plate': 'Полные латы', 'Sage Hat': 'Шапка мудреца', 'Rattling Sceptre': 'Гремящий скипетр',
                  'Rough Greaves': 'Грубые поножи', 'Solar Amulet': 'Солнечный амулет', 'Rawhide Belt': 'Сыромятный пояс'},
        'classes': {},
        'stats': {'life': ['# к максимуму здоровья'], 'local_armour': ['# к броне'], 'armour': ['# к броне'],
                  'local_armour_pct': ['#% повышение брони'], 'cold': ['#% к сопротивлению холоду'],
                  'fire': ['#% к сопротивлению огню'], 'allres': ['#% к сопротивлению всем стихиям'],
                  'speed': ['#% повышение скорости передвижения', '#% снижение скорости передвижения'],
                  'minion': ['# к уровню всех камней умений приспешников'], 'spirit': ['# к духу'], 'spirit_eq': ['# к духу'],
                  'local_spirit_pct': ['#% увеличение духа'], 'es': ['# к максимуму энергетического щита'],
                  'local_es': ['# к максимуму энергетического щита'], 'str': ['# к силе']},
        'less': {'speed': ['#% снижение скорости передвижения']},
        'statNames': {'minion_level': ['Уровень умений приспешников', 'Приспешники'], 'spirit': ['Дух', 'Дух'],
                      'speed': ['Скорость передвижения', 'Скорость'], 'res_fire': ['Сопротивление огню', 'Огонь'],
                      'res_cold': ['Сопротивление холоду', 'Холод'], 'life': ['Здоровье', 'Здоровье'],
                      'armour': ['Броня', 'Броня'], 'es': ['Энергетический щит', 'Энергощит'], 'str': ['Сила', 'Сила']},
        'props': {'Броня': 'armour', 'Энергетический щит': 'energy_shield', 'Дух': 'spirit'},
        'words': {'sockets': 'Гнезда', 'requires': 'Требуется', 'level': ['Уровень'], 'str': ['Сила'],
                  'dex': ['Ловкость', 'Ловк'], 'int': ['Интеллект', 'Инт']},
    }},
}

BODY = '''Класс предмета: Нательные доспехи
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
{ Суффикс "инея" (Уровень: 8) — Стихийный, Холод, Сопротивление }
+7(6-10)% к сопротивлению холоду
{ Суффикс "углей" (Уровень: 8) — Стихийный, Огонь, Сопротивление }
+6(6-10)% к сопротивлению огню
'''


def passport(text, cat=CAT):
    return itemstats.passport(cat, itemcopy.identify(cat, itemcopy.parse(text)))


class PassportTest(unittest.TestCase):
    def test_every_source_adds_up(self):
        """Стат складывается со всей вещи: чистый аффикс, гибрид, руна, свойство самой вещи."""
        p = passport(BODY)
        self.assertEqual(p['stats'], {'res_cold': 43, 'life': 107, 'res_fire': 6, 'armour': 358})
        self.assertEqual([(x['v'], x['src']) for x in p['parts']['life']], [(95, 'prefix'), (12, 'prefix')])
        self.assertEqual([(x['v'], x['src']) for x in p['parts']['res_cold']], [(36, 'rune'), (7, 'suffix')])
        # броня — число из свойств вещи; строки «+36 к броне» и «17% повышение брони» уже внутри него
        self.assertEqual([(x['v'], x['src']) for x in p['parts']['armour']], [(358, 'property')])
        self.assertEqual((p['props'], p['req'], p['sockets'], p['runes']), ({'armour': 358}, {'level': 36, 'str': 54}, 2, 1))
        self.assertEqual((p['affixes'], p['other']), ({'prefix': 3, 'suffix': 2}, 0))

    def test_bare_item_is_the_item_without_what_is_socketed(self):
        """Вещь без вставок в гнёздах: строки рун из паспорта уходят, собственные свойства остаются.
        Руна, которая меняет саму вещь, сидит внутри числа из свойств — её вклад снимается счётом:
        (база + числа) × (1 + проценты) × (1 + качество), проценты аффиксов и рун складываются."""
        p = passport(BODY)
        b = itemstats.bare(p)
        self.assertEqual(b['stats'], {'res_cold': 7, 'life': 107, 'res_fire': 6, 'armour': 358})
        self.assertEqual((itemstats.inserts(p), p['stats']['res_cold']), ({'res_cold': 36}, 43))    # сам паспорт не тронут
        self.assertEqual(p['local']['armour'], {'pct': 17, 'flat': 36, 'rune_pct': 0, 'rune_flat': 0})
        # руна «16% брони» рядом с аффиксом «17% брони»: 358 = ядро × 1,33 → без руны ядро × 1,17 = 315
        iron = BODY.replace('+36% к сопротивлению холоду (rune)', '16% повышение брони (rune)')
        p = passport(iron)
        self.assertEqual((p['local']['armour']['rune_pct'], itemstats.bare(p)['stats']['armour'], itemstats.inserts(p)),
                         (16, 315, {'armour': 43}))
        # качество — отдельный множитель: на долю руны оно не влияет
        cat = dict(CAT, lang={'ru': dict(CAT['lang']['ru'], props=dict(CAT['lang']['ru']['props'], **{'Качество': 'quality'}))})
        fine = iron.replace('Броня: 358 (augmented)', 'Качество: +20% (augmented)\nБроня: 358 (augmented)')
        self.assertEqual(itemstats.bare(passport(fine, cat))['stats']['armour'], 315)
        # руна с числом («+30 к броне») складывается с базой — до процентов и качества
        flat = fine.replace('16% повышение брони (rune)', '+30 к броне (rune)')
        p = passport(flat, cat)
        self.assertEqual((p['local']['armour']['rune_flat'], itemstats.bare(p)['stats']['armour']), (30, 316))
        # вставок нет — вещь та же самая
        clean = BODY.replace('+36% к сопротивлению холоду (rune)\n--------\n', '')
        self.assertEqual((itemstats.bare(passport(clean))['stats'], itemstats.inserts(passport(clean))),
                         (passport(clean)['stats'], {}))
        self.assertEqual((itemstats.bare(None), itemstats.inserts(None)), (None, {}))

    def test_unique_modifiers_count_and_are_named(self):
        """Свойства уникального предмета идут в статы героя и названы своим источником — «уникальное свойство». Запись
        надетого, сделанная, когда они читались «прочим» (other), считается так же; это тот же предмет, что и новая копия."""
        text = ('Класс предмета: Пояса\nРедкость: Уникальный\nРемень Мегинорда\nСыромятный пояс\n--------\n'
                'Уровень предмета: 11\n--------\n{ Уникальное свойство — Характеристика }\n+43(40-50) к силе\n'
                '{ Уникальное свойство — Стихийный, Холод, Сопротивление }\n+11(10-15)% к сопротивлению холоду\n'
                '{ Уникальное свойство }\n100% увеличение количества получаемых зарядов флакона\n')
        item = itemcopy.identify(CAT, itemcopy.parse(text))
        self.assertEqual([m['kind'] for m in item['mods']], ['unique'] * 3)
        p = itemstats.passport(CAT, item)
        self.assertEqual((p['stats'], p['other']), ({'str': 43, 'res_cold': 11}, 1))
        self.assertEqual({x['src'] for ps in p['parts'].values() for x in ps}, {'unique'})
        old = dict(item, mods=[dict(m, kind='other') for m in item['mods']])
        self.assertEqual(itemstats.passport(CAT, old)['parts'], p['parts'])
        self.assertTrue(itemcopy.same_item(old, dict(item, at=5)))
        self.assertFalse(itemcopy.same_item(old, dict(item, name='Другой')))
        # запись из файла забега (после JSON диапазоны чисел — списки, а не кортежи) — тот же предмет
        import json
        self.assertTrue(itemcopy.same_item(json.loads(json.dumps(item)), item))

    def test_same_text_on_a_belt_is_the_heros_armour(self):
        belt = 'Класс предмета: Пояса\nРедкость: Волшебный\nСыромятный пояс стойкости\n--------\nУровень предмета: 20\n' \
               '--------\n{ Префикс "Лакированный" (Уровень: 1) — Броня }\n+15(12-22) к броне\n'
        self.assertEqual(passport(belt)['stats'], {'armour': 15})

    def test_one_line_for_several_stats_and_minus(self):
        amulet = 'Класс предмета: Амулеты\nРедкость: Редкий\nЗнак бури\nСолнечный амулет\n--------\nУровень предмета: 30\n' \
                 '--------\n{ Собственное свойство }\n+12(10-15) к духу (implicit)\n--------\n' \
                 '{ Суффикс "радуги" (Уровень: 2) — Стихийный, Сопротивление }\n+4(3-5)% к сопротивлению всем стихиям\n' \
                 '{ Суффикс "угря" (Уровень: 1) }\nРегенерация 2(1-3) здоровья в секунду\n'
        p = passport(amulet)
        # «ко всем стихиям» идёт в каждое сопротивление; собственное свойство считается наравне с аффиксом
        self.assertEqual(p['stats'], {'spirit': 12, 'res_fire': 4, 'res_cold': 4})
        self.assertEqual(p['parts']['spirit'][0]['src'], 'implicit')
        self.assertEqual(p['other'], 1)                       # строка, которая ни в один стат не идёт
        boots = 'Класс предмета: Сапоги\nРедкость: Волшебный\nТяжёлые Грубые поножи\n--------\nУровень предмета: 5\n--------\n' \
                '{ Префикс "Тяжёлый" (Уровень: 1) }\n5(4-6)% снижение скорости передвижения\n'
        self.assertEqual(passport(boots)['stats'], {'speed': -5})

    def test_plain_copy_and_local_lines(self):
        """Простая копия (Ctrl+C): строки без заголовков уже сложены игрой. Строка, что меняет саму вещь
        (энергощит шлема), в сумму не идёт: она внутри числа из свойств."""
        hat = 'Класс предмета: Шлемы\nРедкость: Редкий\nВенец бури\nШапка мудреца\n--------\n' \
              'Энергетический щит: 58 (augmented)\n--------\nУровень предмета: 33\n--------\n' \
              '+24 к максимуму энергетического щита\n+18% к сопротивлению огню\n'
        p = passport(hat)
        self.assertEqual(p['stats'], {'res_fire': 18, 'es': 58})
        sceptre = 'Класс предмета: Скипетры\nРедкость: Редкий\nГром душ\nГремящий скипетр\n--------\nДух: 100\n--------\n' \
                  'Уровень предмета: 60\n--------\n{ Префикс "Королевский" (Уровень: 4) — Дух }\n47(45-50)% увеличение духа\n' \
                  '{ Суффикс "деспота" (Уровень: 3) — Приспешник, Камень }\n+2 к уровню всех камней умений приспешников\n'
        self.assertEqual(passport(sceptre)['stats'], {'minion_level': 2, 'spirit': 100})

    def test_view_for_the_page(self):
        v = itemstats.view(CAT, itemcopy.identify(CAT, itemcopy.parse(BODY)))
        self.assertEqual([(r['id'], r['short'], r['value'], r['unit']) for r in v['rows']],
                         [('res_fire', 'Огонь', 6, '%'), ('res_cold', 'Холод', 43, '%'), ('life', 'Здоровье', 107, ''),
                          ('armour', 'Броня', 358, '')])
        self.assertEqual((v['req'], v['sockets']), ({'level': 36, 'str': 54}, 2))
        self.assertIsNone(itemstats.passport(None, itemcopy.parse(BODY)))
        self.assertIsNone(itemstats.passport({'lang': {}}, itemcopy.parse(BODY)))     # каталог без таблицы статов

    def test_real_catalogue(self):
        """Настоящий каталог: копия доспеха игрока (2026-11-15) складывается по статам целиком."""
        cat = gamedata.load(Path(HERE).parent / 'catalog' / 'data')
        if not cat or not cat.get('stats'):
            self.skipTest('каталог данных игры не собран')
        self.assertEqual(cat['stats']['missing'], [])
        real = BODY.replace('{ Суффикс "инея" (Уровень: 8) — Стихийный, Холод, Сопротивление }\n+7(6-10)% к сопротивлению холоду',
                            '{ Суффикс "грозовой тучи" (Уровень: 5) — Стихийный, Молния, Сопротивление }\n'
                            '+25(21-25)% к сопротивлению молнии\n{ Суффикс "силача" (Уровень: 8) — Характеристика }\n+5(5-8) к силе')
        p = passport(real, cat)
        # скорость −5 — штраф базы «Полные латы»: на вещи он не написан, берётся из данных игры
        self.assertEqual(p['stats'], {'res_cold': 36, 'life': 107, 'res_lightning': 25, 'str': 5, 'res_fire': 6,
                                      'armour': 358, 'speed': -5})
        self.assertEqual([(x['v'], x['src']) for x in p['parts']['speed']], [(-5, 'base')])
        self.assertEqual(set(cat['lang']['ru']['statNames']), set(cat['stats']['stats']))


SPECS = [('helmet', 'Шлем', 'Helmet int_armour'), ('body', 'Нательный доспех', 'Body Armour str_armour'),
         ('boots', 'Сапоги', 'Boots'), ('belt', 'Пояс', 'Belt'), ('amulet', 'Амулет', 'Amulet'),
         ('weapon', 'Оружие', 'Sceptre'), ('bow', 'Лук', 'Bow')]


class SlotsTest(unittest.TestCase):
    def test_where_a_stat_can_come_from(self):
        t = slotstats.carriers(CAT, SPECS, 70)
        rare = slotstats.scarcity(t)
        # скорость — только сапоги; уровень приспешников — три слота; сопротивление холоду — пять
        self.assertEqual((rare['speed'], rare['minion_level'], rare['res_cold'], rare['spirit']), (1, 3, 5, 3))
        self.assertEqual(sorted(s for s, f in t['minion_level'].items() if f['affix']), ['amulet', 'helmet', 'weapon'])
        boots = t['speed']['boots']['affix'][0]
        # ступени — с какого уровня предмета; на вещи 70 уровня бывают первые две
        self.assertEqual((boots['steps'], boots['now'], slotstats.best_step(boots)),
                         ([[1, 10, 10], [65, 30, 30], [82, 35, 35]], 2, [65, 30, 30]))
        # на шлеме уровень приспешников кончается на +2, на амулете и скипетре есть +3 — но с 75 уровня
        self.assertEqual(len(t['minion_level']['helmet']['affix'][0]['steps']), 2)
        self.assertEqual(slotstats.best_step(t['minion_level']['amulet']['affix'][0]), [41, 2, 2])
        # здоровье на доспехе — и чистым аффиксом, и гибридом
        self.assertEqual(sorted((a['type'], a['hybrid']) for a in t['life']['body']['affix']), [('ArmourLife', True), ('Life', False)])
        # дух скипетра — свойство самой вещи; у амулета есть база с духом в собственном свойстве
        self.assertTrue(t['spirit']['weapon']['affix'][0]['local'])
        self.assertEqual(t['spirit']['amulet']['implicit'], [{'base': 'Solar Amulet', 'level': 1, 'vals': [10, 15]}])

    def test_runes_depend_on_the_item(self):
        """Руна холода даёт сопротивление только в доспехах; на оружии она — урон, в скипетре — ничего."""
        t = slotstats.carriers(CAT, SPECS, 70)
        runes = {slot: sorted((r['val'], r['level']) for r in f['rune'] if r['plain']) for slot, f in t['res_cold'].items()}
        self.assertEqual(runes['helmet'], [(14, 15), (18, 30)])
        self.assertEqual(runes['body'], [(14, 15), (18, 30)])
        self.assertEqual((runes['belt'], runes['amulet']), ([], []))          # украшения гнёзд не имеют
        self.assertNotIn('weapon', t['res_cold'])
        self.assertNotIn('bow', t['res_cold'])
        # руна характеристики — «во всё снаряжение»: и в скипетр, и в лук, но не в пояс
        self.assertEqual(sorted(s for s, f in t['str'].items() if f['rune']), ['body', 'boots', 'bow', 'helmet', 'weapon'])
        # ядро души привязано к сапогам: это вставка, но не обычная руна
        self.assertEqual([(r['type'], r['plain']) for r in t['speed']['boots']['rune']], [('SoulCore', False)])
        self.assertTrue(gamedata.augment_fits('Armour', 'Shield', ['shield', 'armour']))
        self.assertTrue(gamedata.augment_fits('Sceptre', 'Sceptre', ['sceptre']))
        self.assertFalse(gamedata.augment_fits('Martial Weapon', 'Sceptre', ['sceptre', 'onehand']))
        self.assertFalse(gamedata.augment_fits('All', 'Ring', ['ring']))

    def test_report_reads(self):
        raw = {'slots': [{'id': 'helmet', 'name': 'Шлем', 'gear': 'Helmet int_armour'}, {'id': 'weapon', 'name': 'Оружие'}],
               'goals': [{'id': 'sceptre', 'slot': 'weapon', 'use': 'after', 'gear': 'Sceptre'},
                         {'id': 'sceptre-2', 'slot': 'weapon', 'use': 'after', 'gear': 'Sceptre'}]}
        # у слота, где вещи сменяют друг друга, — по строке на вещь: её называет цель (gear), шаг — её use
        self.assertEqual(slotstats.specs_of(raw), [('helmet', 'Шлем', 'Helmet int_armour'),
                                                   ('weapon/after', 'Оружие · Sceptre', 'Sceptre')])
        text = slotstats.report(CAT, raw, 70)
        self.assertIn('Уровень умений приспешников', text)
        self.assertIn('2 с ур. 41', text)


if __name__ == '__main__':
    unittest.main()
