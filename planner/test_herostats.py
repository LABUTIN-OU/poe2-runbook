# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Sergei Labutin
# Additional terms under GPL-3.0 section 7: see NOTICE.md
"""Инвентарь на статах: суммы героя с запомненных вещей и сравнение вещи с надетой.
Запуск: python -m unittest planner.test_herostats"""
import copy
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import herostats  # noqa: E402
import itemcopy  # noqa: E402
import itemstats  # noqa: E402
import test_itemstats  # noqa: E402

PLAN = {
    'slots': [{'id': 'weapon', 'name': 'Оружие', 'gear': 'Sceptre'},
              {'id': 'helmet', 'name': 'Шлем', 'gear': 'Helmet int_armour'},
              {'id': 'body', 'name': 'Нательный доспех', 'gear': 'Body Armour str_armour'},
              {'id': 'boots', 'name': 'Сапоги', 'gear': 'Boots'},
              {'id': 'belt', 'name': 'Пояс', 'gear': 'Belt'},
              {'id': 'amulet', 'name': 'Амулет', 'gear': 'Amulet'}],
    # где в памяти надетого лежит вещь слота: оружие — на линии шага, с которого носят скипетр
    'keys': {'weapon': 'weapon/after'},
    # Билд на своём шаге (как его отдаёт at_step): stats — статы этапа по важности. Здесь этап
    # со скипетром: уровень приспешников и дух ведут только на нём.
    'stats': [{'id': 'minion_level'}, {'id': 'spirit'}, {'id': 'speed'},
              {'id': 'res_fire'}, {'id': 'res_cold'}, {'id': 'life'}],
    'goals': [{'id': 'beira', 'gives': {'res_cold': 10}}, {'id': 'tattoo', 'gives': {'res_cold': 5, 'nothing': 3}},
              {'id': 'sceptre', 'slot': 'weapon', 'gear': 'Sceptre'}],
}
# тот же билд, который ведёт ещё и броню (в учебном каталоге её несут доспех, сапоги и пояс)
ARMOUR_PLAN = dict(PLAN, stats=PLAN['stats'] + [{'id': 'armour'}])
# тот же билд на раннем этапе, с луком: приспешников ещё нет
BOW_PLAN = dict(PLAN, stats=PLAN['stats'][2:], keys={'weapon': 'weapon/'},
                slots=[dict(s, gear='Bow') if s['id'] == 'weapon' else s for s in PLAN['slots']])


def text(cls, base, *lines, name='Вещь', ilvl=66, props=(), rarity='Редкий'):
    """Простая копия вещи (Ctrl+C): строки свойств без заголовков аффиксов. У белой и синей вещи имя одной
    строкой — в нём и база."""
    head = ['Класс предмета: %s' % cls, 'Редкость: %s' % rarity] + ([name, base] if rarity == 'Редкий' else [base])
    body = (['--------'] + list(props) if props else []) + ['--------', 'Уровень предмета: %d' % ilvl, '--------'] + list(lines)
    return '\n'.join(head + body) + '\n'


def boots(*lines, **kw):
    return text('Сапоги', 'Грубые поножи', *lines, **kw)


def body(*lines, armour=300, **kw):
    return text('Нательные доспехи', 'Полные латы', *lines, props=['Броня: %d' % armour], **kw)


class Base(unittest.TestCase):
    def setUp(self):
        self.cat = copy.deepcopy(test_itemstats.CAT)
        # штраф скорости базы: на вещи не написан, умножается на прибавки
        self.cat['bases']['Armours/Body/Plate']['speed'] = -5
        self.cat['stats']['stats']['speed']['base'] = 'speed'
        for sid in ('res_fire', 'res_cold'):
            self.cat['stats']['stats'][sid]['act_penalty'] = True
        self.worn = {}
        self.keys = herostats.hero_keys(PLAN)

    def item(self, txt):
        return itemcopy.identify(self.cat, itemcopy.parse(txt))

    def wear(self, slot, txt):
        self.worn[self.keys[slot]] = {'at': 1.0, 'item': self.item(txt)}

    def cmp(self, slot, txt, extra=None, ilvl=70, plan=PLAN):
        return herostats.compare(self.cat, plan, slot, herostats.hero_keys(plan)[slot], self.item(txt),
                                 self.worn, extra or {}, ilvl)


class CompareTest(Base):
    def test_scarce_stat_decides_over_everything_below(self):
        """Скорость бывает только на сапогах: меньше скорости — хуже, сколько бы ни было остального."""
        self.wear('boots', boots('30% повышение скорости передвижения'))
        st = self.cmp('boots', boots('10% повышение скорости передвижения', '+35% к сопротивлению холоду',
                                     '+99 к максимуму здоровья'))
        self.assertEqual((st['verdict'], st['up'], st['down']), ('worse', 2, 1))
        first = st['lines'][0]
        self.assertEqual((first['id'], first['cls'], first['now'], first['new'], first.get('decides')),
                         ('speed', 'scarce', 30, 10, True))
        self.assertEqual([ln['cls'] for ln in st['lines'][1:]], ['need', 'grow'])
        # та же скорость — решает остальное; строка редкого стата остаётся: видно, что главное то же
        st = self.cmp('boots', boots('30% повышение скорости передвижения', '+35% к сопротивлению холоду'))
        self.assertEqual((st['verdict'], [(ln['id'], ln['delta']) for ln in st['lines']]),
                         ('better', [('speed', 0), ('res_cold', 1)]))

    def test_scarce_follows_the_build_order_and_its_stage(self):
        """Редких статов на вещи два — решает тот, что в билде выше. На другом этапе их не ведут вовсе."""
        self.wear('amulet', text('Амулеты', 'Солнечный амулет', '+1 к уровню всех камней умений приспешников',
                                 '+33 к духу'))
        new = text('Амулеты', 'Солнечный амулет', '+2 к уровню всех камней умений приспешников')
        st = self.cmp('amulet', new)
        self.assertEqual(st['verdict'], 'better')
        self.assertEqual([(ln['id'], ln['cls'], ln['delta'], bool(ln.get('decides'))) for ln in st['lines']],
                         [('minion_level', 'scarce', 1, True), ('spirit', 'scarce', -1, False)])
        st = self.cmp('amulet', new, plan=BOW_PLAN)
        self.assertEqual((st['verdict'], st['lines']), ('same', []))

    def test_common_stats_add_up_in_affixes(self):
        """Обычные статы складываются: каждый — долей лучшего аффикса на таком слоте (холод 35, здоровье 99)."""
        self.wear('boots', boots('+35% к сопротивлению холоду'))
        st = self.cmp('boots', boots('+20% к сопротивлению холоду', '+99 к максимуму здоровья'))
        self.assertEqual([(ln['id'], ln['d']) for ln in st['lines']], [('res_cold', -0.43), ('life', 1.0)])
        self.assertEqual((st['verdict'], st['score']), ('better', 0.57))
        # мелочь — не разница: строка есть, но помечена мелкой и в счёт «хуже» не идёт
        st = self.cmp('boots', boots('+33% к сопротивлению холоду'))
        self.assertEqual((st['verdict'], st['down'], st['lines'][0]['delta'], st['lines'][0]['minor']), ('same', 0, -1, True))
        # одинаковый стат билда строкой не показан — он назван в same
        st = self.cmp('boots', boots('+35% к сопротивлению холоду', '+50 к максимуму здоровья'))
        self.assertEqual(([ln['id'] for ln in st['lines']], st['same']), (['life'], ['res_cold']))

    def test_over_the_cap_counts_for_nothing(self):
        """Сопротивление сверх порога ничего не стоит: считается только то, что доводит героя до 75."""
        self.wear('boots', boots('+35% к сопротивлению холоду'))
        self.wear('belt', text('Пояса', 'Сыромятный пояс', '+35% к сопротивлению холоду'))
        new = boots('+10% к сопротивлению холоду')
        # герой и так сверх порога (вещи 70 + прочее 40): потеря холода ничего не меняет
        st = self.cmp('boots', new, extra={'res_cold': 40})
        cold = st['lines'][0]
        self.assertEqual((cold['id'], cold['cls'], cold['d'], cold['hero'], cold['heroNew']), ('res_cold', 'over', 0, 110, 85))
        self.assertEqual((st['verdict'], st['down']), ('same', 0))
        # без запаса та же вещь хуже: герой уходит с 70 на 45
        st = self.cmp('boots', new)
        cold = st['lines'][0]
        self.assertEqual((cold['cls'], cold['hero'], cold['heroNew'], cold['d'], st['verdict']), ('need', 70, 45, -0.71, 'worse'))
        # сейчас сверх порога, после замены ниже: считается всё, что ниже порога (с 80 на 55 — как 20 из 35)
        st = self.cmp('boots', new, extra={'res_cold': 10})
        cold = st['lines'][0]
        self.assertEqual((cold['cls'], cold['hero'], cold['heroNew'], cold['d'], st['verdict']), ('need', 80, 55, -0.57, 'worse'))
        # сколько не хватает до порога, столько и считается: с 60 до 75, хотя на вещи +35
        st = self.cmp('amulet', text('Амулеты', 'Солнечный амулет', '+35% к сопротивлению холоду'), extra={'res_cold': -10})
        cold = st['lines'][-1]
        self.assertEqual((cold['hero'], cold['heroNew'], cold['d']), (60, 95, round(15 / 35.0, 2)))

    def test_items_own_property_is_measured_in_best_affixes_too(self):
        """Броня доспеха — свойство самой вещи. Мера та же, что у остальных статов, — лучший аффикс: сколько
        прибавит броне лучший один аффикс, меняющий саму вещь, на такой базе, — но не меньше всей базы: целая
        база защиты стоит не больше одного аффикса. На картах так выходит само (процент защиты +100% и больше),
        а у полных лат учебного каталога лучший аффикс — «+56 к броне» при базе 270, как в начале кампании."""
        full = self.item(body(armour=400))
        strong = copy.deepcopy(self.cat)        # тот же каталог с базой покрепче (мера запоминается в каталоге)
        strong['bases']['Armours/Body/Plate']['props']['armour'] = 400
        # и с процентом защиты, как на картах, больше всей базы
        maps = copy.deepcopy(self.cat)
        maps['mods']['ArmourLife|prefix|local_armour_pct life']['mods'][0]['vals'][0] = [140, 150]
        self.assertEqual(herostats.item_base(self.cat, full)['name'], 'Full Plate')
        # числом — до 56; процентом — 20% от 270 брони базы = 54; сама база — 270: она и мера
        self.assertEqual(herostats.own_unit(self.cat, 'armour', [full], 70), 270)
        # мера — по большей из сравниваемых вещей: база покрепче — 400
        self.assertEqual(herostats.own_unit(strong, 'armour', [full], 70), 400)
        self.assertEqual(herostats.own_unit(self.cat, 'armour', [self.item(boots()), full], 70), 270)
        # процент защиты больше всей базы: 150% от 270 = 405 — мера он
        self.assertEqual(herostats.own_unit(maps, 'armour', [full], 70), 405)
        # не свойство вещи (здоровье), нет таких аффиксов в данных (энергощит учебного каталога), нет базы — меры нет
        hat = self.item(text('Шлемы', 'Шапка мудреца', props=['Энергетический щит: 100']))
        self.assertEqual([herostats.own_unit(self.cat, sid, [x], 70) for sid, x in (('life', full), ('es', hat), ('armour', hat))],
                         [None, None, None])
        self.wear('body', body('+6% к сопротивлению огню', armour=400))
        st = self.cmp('body', body('+6% к сопротивлению огню', armour=300), plan=ARMOUR_PLAN)
        arm = next(ln for ln in st['lines'] if ln['id'] == 'armour')
        # сто брони — больше трети всей брони лат: заметная разница, а не «четверть брони героя»
        self.assertEqual((arm['cls'], arm['now'], arm['new'], arm['d'], st['verdict']), ('scarce', 400, 300, -0.37, 'worse'))
        st = self.cmp('body', body('+6% к сопротивлению огню', armour=396), plan=ARMOUR_PLAN)
        self.assertEqual(st['verdict'], 'same')            # 4 из 270 — не разница
        # билд броню не ведёт — её и не сравнивают
        st = self.cmp('body', body('+6% к сопротивлению огню', armour=300))
        self.assertEqual((st['verdict'], st['lines']), ('same', []))
        # данных об аффиксах свойства нет — мерой остаётся доля этого стата у героя со всех вещей
        es_plan = dict(PLAN, stats=PLAN['stats'] + [{'id': 'es'}])
        self.wear('helmet', text('Шлемы', 'Шапка мудреца', props=['Энергетический щит: 100']))
        st = self.cmp('helmet', text('Шлемы', 'Шапка мудреца', props=['Энергетический щит: 80']), plan=es_plan)
        self.assertEqual([(ln['id'], ln['d']) for ln in st['lines']], [('es', -0.2)])

    def test_nearly_equal_items_are_settled_by_the_base_the_plan_wants(self):
        """Слот ждёт базу определённого рода (шлем на энергощит). Когда вещи по статам почти равны — ни один
        редкий стат не решил, счёт меньше четверти лучшего аффикса, — лучше та, чья база ближе к плану."""
        self.cat['bases']['Armours/Helmets/Great'] = {'name': 'Rusted Greathelm', 'class': 'Helmet', 'level': 1, 'req': {},
                                                      'tags': ['str_armour', 'helmet', 'armour', 'default'], 'props': {'armour': 60}}
        self.cat['lang']['ru']['bases']['Rusted Greathelm'] = 'Ржавый шлем'
        iron = lambda *lines: text('Шлемы', 'Ржавый шлем', *lines, props=['Броня: 60'])                    # noqa: E731
        hat = lambda *lines: text('Шлемы', 'Шапка мудреца', *lines, props=['Энергетический щит: 40'])       # noqa: E731
        self.assertEqual([herostats.kind_of(self.cat, self.item(t)['tags']) for t in (iron(), hat(), boots())],
                         ['str_armour', 'int_armour', 'str_armour'])
        fit = lambda want, t: herostats.base_fit(self.cat, want, self.item(t)['tags'])                      # noqa: E731
        self.assertEqual([fit('int_armour', hat()), fit('int_armour', iron()), fit('str_armour', iron())], [1.0, 0.0, 1.0])
        # надет силовой шлем, новый — на энергощит, как ждёт план; холод почти тот же (20 и 19)
        self.wear('helmet', iron('+20% к сопротивлению холоду'))
        st = self.cmp('helmet', hat('+19% к сопротивлению холоду'))
        kind = st['lines'][0]
        self.assertEqual((st['verdict'], kind['id'], kind['cls'], kind['want'], kind['now'], kind['new'], kind['delta'], kind['decides']),
                         ('better', 'kind', 'kind', 'int_armour', 'str_armour', 'int_armour', 1, True))
        self.assertEqual((st['up'], st['down'], round(st['score'], 2)), (1, 0, -0.03))
        # статы заметно хуже — база по плану не спасает: её строка есть, но тихая
        st = self.cmp('helmet', hat('+6% к сопротивлению холоду'))
        self.assertEqual((st['verdict'], st['lines'][0]['id'], st['lines'][0]['decides'], st['lines'][0]['minor'], st['up']),
                         ('worse', 'kind', False, True, 0))
        # редкий стат решает раньше базы: уровень умений приспешников на шлеме
        st = self.cmp('helmet', hat('+19% к сопротивлению холоду', '+1 к уровню всех камней умений приспешников'))
        self.assertEqual((st['verdict'], [(ln['id'], bool(ln.get('decides'))) for ln in st['lines'][:2]]),
                         ('better', [('kind', False), ('minion_level', True)]))
        # наоборот: надета вещь по плану, новая — не того рода и не лучше: менять незачем
        self.worn.clear()
        self.wear('helmet', hat('+19% к сопротивлению холоду'))
        st = self.cmp('helmet', iron('+20% к сопротивлению холоду'))
        self.assertEqual((st['verdict'], st['lines'][0]['delta'], st['lines'][0]['decides']), ('worse', -1, True))
        # базы одного рода — строки нет; у слота без рода в описании (сапоги этого плана) — тоже
        st = self.cmp('helmet', hat('+20% к сопротивлению холоду'))
        self.assertEqual((st['verdict'], [ln['id'] for ln in st['lines']]), ('same', ['res_cold']))
        self.wear('boots', boots('+20% к сопротивлению холоду'))
        self.assertNotIn('kind', [ln['id'] for ln in self.cmp('boots', boots('+19% к сопротивлению холоду'))['lines']])

    def test_a_plainer_items_base_defence_does_not_outweigh_affixes(self):
        """Белая (синяя) вещь против жёлтой: броня, уклонение и энергощит её базы — то, за что базу берут под
        крафт, — не перевешивают того, что вложено в жёлтую. Вещи сравниваются ещё раз — новая с защитой базы
        надетой; жёлтая по остальному заметно лучше — она и лучше, а у белой сказано: «как база — лучше»."""
        self.cat['bases']['Armours/Body/Mail'] = {'name': 'Chainmail', 'class': 'Body Armour', 'level': 1, 'req': {},
                                                  'tags': ['str_armour', 'body_armour', 'armour', 'default'], 'props': {'armour': 120}}
        self.cat['lang']['ru']['bases']['Chainmail'] = 'Кольчуга'
        mail = lambda *lines, rarity='Редкий': text('Нательные доспехи', 'Кольчуга', *lines, props=['Броня: 120'], rarity=rarity)   # noqa: E731
        plate = lambda *lines, rarity='Обычный', armour=270: body(*lines, armour=armour, rarity=rarity)                            # noqa: E731
        self.wear('body', mail('+10% к сопротивлению холоду', '+19 к максимуму здоровья'))
        st = self.cmp('body', plate(), plan=ARMOUR_PLAN)
        arm = next(ln for ln in st['lines'] if ln['id'] == 'armour')
        # белые латы на 150 брони крепче — больше половины всей брони лат; броня у этого билда редкая и решила бы
        # первой, хотя холод, здоровье и штраф скорости лат (−5%) — за кольчугу
        self.assertEqual((arm['cls'], arm['now'], arm['new'], arm['d'], st['score']), ('scarce', 120, 270, 0.56, -0.65))
        # при одной защите баз жёлтая лучше: ответ — её, белая хороша как база; броня ответа не решала — не обведена
        self.assertEqual((st['verdict'], st['even'], st['byEven'], st['basis'], arm.get('decides')),
                         ('worse', {'verdict': 'worse', 'score': -0.48, 'by': None}, True, 'better', None))
        # наоборот: надеты белые латы, скопирована жёлтая кольчуга — она лучше; о базе ни слова
        self.worn.clear()
        self.wear('body', plate())
        st = self.cmp('body', mail('+10% к сопротивлению холоду', '+19 к максимуму здоровья'), plan=ARMOUR_PLAN)
        self.assertEqual((st['verdict'], st['even']['verdict'], st['byEven'], st['basis']), ('better', 'better', True, None))
        # у жёлтой ничего полезного билду (сила билд не ведёт): белые латы честно лучше — крепче, а больше разницы нет
        self.worn.clear()
        self.wear('body', mail('+8 к силе'))
        st = self.cmp('body', plate(), plan=ARMOUR_PLAN)
        self.assertEqual((st['verdict'], st['even']['verdict'], st['byEven'], st['basis']), ('better', 'same', False, None))
        # вещи одной редкости — как раньше: жёлтые латы крепче жёлтой кольчуги, и это решает
        self.worn.clear()
        self.wear('body', mail('+10% к сопротивлению холоду', '+19 к максимуму здоровья'))
        st = self.cmp('body', plate('+8 к силе', rarity='Редкий'), plan=ARMOUR_PLAN)
        self.assertEqual((st['verdict'], st['even'], st['byEven'], st['basis'], st['lines'][0]['decides']),
                         ('better', None, False, None, True))
        # синие латы с прибавкой брони: прибавка — вложение, она остаётся и на базе кольчуги (120 + 40)
        self.worn.clear()
        self.wear('body', mail('+8 к силе'))
        new = self.item(plate('+40 к броне', rarity='Волшебный', armour=310))
        old_p, new_p = (itemstats.bare(itemstats.passport(self.cat, x)) for x in (self.worn['body/']['item'], new))
        # штраф скорости — тоже свойство базы: у кольчуги его нет, и латы на её базе его не несут
        self.assertEqual(herostats.on_base(self.cat, self.worn['body/']['item'], old_p, new, new_p)['stats'], {'armour': 160})
        self.assertEqual(new_p['stats'], {'armour': 310, 'speed': -5})

    def test_defence_of_an_implicit_is_the_base_too_the_rest_counts(self):
        """Встроенная броня пояса — та же защита базы: белый пояс с ней не лучше жёлтого с холодом и здоровьем.
        Встроенное сопротивление — обычный стат: белый амулет с холодом лучше синего с горсткой здоровья. Редкий
        стат решает раньше всего, как и прежде: синие сапоги со скоростью лучше жёлтых без неё."""
        self.cat['bases']['Belts/Plate'] = {'name': 'Plate Belt', 'class': 'Belt', 'tags': ['belt', 'default'], 'level': 1,
                                            'req': {}, 'implicits': ['BeltArmour']}
        self.cat['bases']['Amulets/Lapis'] = {'name': 'Lapis Amulet', 'class': 'Amulet', 'tags': ['amulet', 'default'], 'level': 1,
                                              'req': {}, 'implicits': ['AmuletCold']}
        self.cat['implicits'].update({'BeltArmour': {'stats': ['armour'], 'vals': [[140, 180]], 'lines': ['armour']},
                                      'AmuletCold': {'stats': ['cold'], 'vals': [[20, 30]], 'lines': ['cold']}})
        self.cat['lang']['ru']['bases'].update({'Plate Belt': 'Ремень из пластин', 'Lapis Amulet': 'Амулет с лазуритом',
                                                'Crimson Amulet': 'Багровый амулет'})
        self.wear('belt', text('Пояса', 'Сыромятный пояс', '+10% к сопротивлению холоду', '+19 к максимуму здоровья'))
        st = self.cmp('belt', text('Пояса', 'Ремень из пластин', '+160 к броне (implicit)', rarity='Обычный'), plan=ARMOUR_PLAN)
        arm = st['lines'][0]
        # броня пояса у этого билда редкая: 160 встроенной брони решили бы первыми — а это защита базы
        self.assertEqual((arm['id'], arm['cls'], arm['new'], st['verdict'], st['byEven'], st['basis']),
                         ('armour', 'scarce', 160, 'worse', True, 'better'))
        # белый пояс той же базы, что надетый, — хуже, и как база не лучше: о базе ни слова
        st = self.cmp('belt', text('Пояса', 'Сыромятный пояс', rarity='Обычный'), plan=ARMOUR_PLAN)
        self.assertEqual((st['verdict'], st['basis']), ('worse', None))
        self.wear('amulet', text('Амулеты', 'Багровый амулет', '+15 к максимуму здоровья', rarity='Волшебный'))
        st = self.cmp('amulet', text('Амулеты', 'Амулет с лазуритом', '+25% к сопротивлению холоду (implicit)', rarity='Обычный'))
        self.assertEqual((st['verdict'], st['score'], st['even']['verdict'], st['byEven'], st['basis']), ('better', 0.56, 'better', False, None))
        self.wear('boots', boots('+20% к сопротивлению холоду', '+19 к максимуму здоровья'))
        st = self.cmp('boots', boots('10% повышение скорости передвижения', rarity='Волшебный'))
        self.assertEqual((st['verdict'], st['lines'][0]['id'], st['lines'][0]['decides'], st['byEven']), ('better', 'speed', True, False))

    def test_a_threshold_of_the_plan_decides_like_a_rare_stat(self):
        """Цель плана «дух скипетра от 120» — порог автора. Берёт его только одна из вещей — решает он, на месте
        своего стата в порядке билда, как редкий стат: разница в три духа — мелочь, а цель есть и её не станет."""
        def sceptre(spirit, *lines):
            return text('Скипетры', 'Гремящий скипетр', *lines, props=['Дух: %d' % spirit])
        floors = dict(PLAN, floors={'weapon/after': [{'stat': 'spirit', 'min': 120, 'goal': 'sceptre-spirit'}]})
        row = lambda st: [(ln['id'], ln['cls'], ln.get('floor'), bool(ln.get('decides'))) for ln in st['lines']]  # noqa: E731
        self.wear('weapon', sceptre(121))
        new = sceptre(118, '+35% к сопротивлению холоду')
        # без порога дух — мелочь, решает холод
        st = self.cmp('weapon', new)
        self.assertEqual((st['verdict'], row(st)), ('better', [('spirit', 'scarce', None, False), ('res_cold', 'need', None, False)]))
        # с порогом новая вещь цель теряет: хуже, решил дух, а остальное лучше
        st = self.cmp('weapon', new, plan=floors)
        self.assertEqual((st['verdict'], row(st), st['score']),
                         ('worse', [('spirit', 'floor', 120, True), ('res_cold', 'need', None, False)], 1.0))
        self.assertEqual((st['up'], st['down']), (1, 1))
        # наоборот — новая вещь цель берёт: лучше
        self.worn = {}
        self.wear('weapon', new)
        self.assertEqual(self.cmp('weapon', sceptre(121), plan=floors)['verdict'], 'better')
        # обе вещи порог берут — счёт как всегда
        self.worn = {}
        self.wear('weapon', sceptre(125))
        st = self.cmp('weapon', new.replace('Дух: 118', 'Дух: 121'), plan=floors)
        self.assertEqual((st['verdict'], row(st)[0]), ('better', ('spirit', 'scarce', None, False)))
        # редкий стат выше в билде решает раньше порога
        self.worn = {}
        self.wear('weapon', sceptre(118, '+1 к уровню всех камней умений приспешников'))
        st = self.cmp('weapon', sceptre(121), plan=floors)
        self.assertEqual((st['verdict'], row(st)), ('worse', [('minion_level', 'scarce', None, True), ('spirit', 'floor', 120, False)]))
        # стат, которого этап не ведёт, но порог у него есть, — тоже строка и тоже решает
        self.worn = {}
        self.wear('weapon', sceptre(121))
        st = self.cmp('weapon', new, plan=dict(floors, stats=[s for s in PLAN['stats'] if s['id'] != 'spirit']))
        self.assertEqual((st['verdict'], row(st)[0]), ('worse', ('spirit', 'floor', 120, True)))
        # порог у вещи другого места (лука на линии с самого начала) скипетру не порог
        st = self.cmp('weapon', new, plan=dict(PLAN, floors={'weapon/': [{'stat': 'spirit', 'min': 120, 'goal': 'x'}]}))
        self.assertEqual(st['verdict'], 'better')

    def test_the_same_item_is_the_worn_one(self):
        txt = boots('30% повышение скорости передвижения', '+20% к сопротивлению холоду')
        self.wear('boots', txt)
        st = self.cmp('boots', txt)
        self.assertEqual((st['verdict'], st['worn']), ('worn', {'name': 'Вещь', 'base': 'Грубые поножи'}))
        # пустой слот: сравнивать не с чем, все числа — прибавка
        st = self.cmp('helmet', text('Шлемы', 'Шапка мудреца', '+1 к уровню всех камней умений приспешников'))
        self.assertEqual((st['worn'], st['verdict'], st['lines'][0]['now'], st['lines'][0]['new']), (None, 'better', 0, 1))

    def test_items_are_compared_without_what_is_socketed(self):
        """Руны в новую вещь ещё не вставлены, и ответ нужен до того, как их потратят: вещи сравниваются
        сами по себе, без вставок. Что дают вставки, отдано отдельно; ответ «как есть» — только когда
        он другой."""
        self.wear('boots', boots('+20% к сопротивлению холоду', '+36% к сопротивлению холоду (rune)'))
        st = self.cmp('boots', boots('+30% к сопротивлению холоду'))
        # с рунами надетой было бы «хуже» (56 против 30), вещь против вещи — «лучше» (20 против 30)
        cold = st['lines'][0]
        self.assertEqual((st['verdict'], cold['now'], cold['new'], cold['hero'], cold['heroNew'], cold['noRunes']),
                         ('better', 20, 30, 20, 30, True))
        self.assertEqual(st['runes'], {'now': [{'id': 'res_cold', 'short': 'Холод', 'value': 36, 'unit': '%'}], 'new': [],
                                       'sockets': [0, 0], 'verdict': 'worse'})
        # ответ с рунами и без один и тот же — о рунах говорить незачем: они названы, но ответа не меняют
        st = self.cmp('boots', boots('+10% к сопротивлению холоду'))
        self.assertEqual((st['verdict'], st['runes']['verdict'], st['runes']['now'][0]['value']), ('worse', None, 36))
        # руны на других вещах героя остаются на месте: они идут в порог сопротивления
        self.wear('belt', text('Пояса', 'Сыромятный пояс', '+35% к сопротивлению холоду'))
        st = self.cmp('boots', boots('+30% к сопротивлению холоду'), extra={'res_cold': 25})
        cold = st['lines'][0]
        self.assertEqual((cold['hero'], cold['heroNew'], cold['cls']), (80, 90, 'over'))
        # вставок нет ни там, ни там — раздела о них нет
        self.worn.clear()
        self.wear('boots', boots('+20% к сопротивлению холоду'))
        self.assertIsNone(self.cmp('boots', boots('+30% к сопротивлению холоду'))['runes'])
        # руны в новой вещи тоже не в счёт: она лучше не рунами, а собой
        st = self.cmp('boots', boots('+20% к сопротивлению холоду', '+18% к сопротивлению холоду (rune)'))
        self.assertEqual((st['verdict'], st['lines'], st['same'], st['runes']['new'][0]['value'], st['runes']['verdict']),
                         ('same', [], ['res_cold'], 18, 'better'))

    def test_a_rune_inside_the_items_own_number_is_taken_out(self):
        """Руна «% брони» сидит внутри числа «Броня: 400»: без неё вещь слабее, чем написано."""
        self.wear('body', body('20% повышение брони (rune)', armour=400))
        st = self.cmp('body', body(armour=390), plan=ARMOUR_PLAN)
        arm = st['lines'][0]
        # 400 с руной 20% — это 333 без неё: новая вещь на 390 лучше, хотя число на ней меньше
        self.assertEqual((arm['id'], arm['now'], arm['new'], st['verdict']), ('armour', 333, 390, 'better'))
        # «как есть», с руной, надетая крепче на 10 брони — 10 из 270 брони базы, не разница: ответ другой — «так же»
        self.assertEqual((st['runes']['now'], st['runes']['verdict']),
                         ([{'id': 'armour', 'short': 'Броня', 'value': 67, 'unit': ''}], 'same'))
        # надетую вещь программа узнаёт и с рунами: это она и есть
        st = self.cmp('body', body('20% повышение брони (rune)', armour=400), plan=ARMOUR_PLAN)
        self.assertEqual((st['verdict'], st['runes']['verdict']), ('worn', None))

    def test_nothing_to_compare_without_stats(self):
        self.assertIsNone(herostats.compare(self.cat, dict(PLAN, stats=[]), 'boots', 'boots/',
                                            self.item(boots('+20% к сопротивлению холоду')), {}, {}))
        self.assertIsNone(herostats.compare(None, PLAN, 'boots', 'boots/', self.item(boots()), {}, {}))


# Билд с двумя этапами: сначала броня (и сила — так решил этот билд), с шага «карты» — энергощит без
# атрибутов и другое дерево. Этап называет только то, что меняет: статы на картах те же, что раньше.
# Род базы у доспеха и сапог в слотах не назван — его даёт этап. Дерево на картах берёт узел, который
# оставляет героя с 1 здоровья.
STAGED = dict({k: v for k, v in PLAN.items() if k != 'stats'}, steps=[{'id': 'start'}, {'id': 'maps'}],
              slots=[dict(s, gear='Body Armour') if s['id'] == 'body' else s for s in PLAN['slots']],
              stages=[{'id': 'armour', 'name': 'Кампания', 'tree': 'early', 'kind': 'str_armour', 'attrs': ['str'],
                       'stats': [dict(x) for x in PLAN['stats']]},
                      {'id': 'es', 'from': 'maps', 'name': 'Карты', 'tree': 'late', 'kind': 'int_armour', 'attrs': []}],
              tree={'phases': [{'id': 'early', 'name': 'Кампания', 'nodes': [{'id': 'life1', 'name': 'Здоровье'}]},
                               {'id': 'late', 'name': 'Карты', 'nodes': [
                                   {'id': 'life1', 'name': 'Здоровье'}, {'id': 'ci', 'name': 'Иммунитет к хаосу'}]}]})
TREE_LINES = {'life1': ['8% increased maximum Life'], 'ci': {'text': ['Maximum Life is 1', 'Immune to Chaos Damage']}}


class StageTest(Base):
    def setUp(self):
        super().setUp()
        # базы требуют атрибут своего рода; здоровье теряет смысл с узлом «Maximum Life is 1»
        self.cat['bases']['Armours/Body/Plate']['req'] = {'level': 33, 'str': 54}
        self.cat['bases']['Armours/Helmets/Hat']['req'] = {'level': 20, 'int': 30}
        self.cat['stats']['stats']['int'] = {'ids': ['int'], 'local': []}
        self.cat['stats']['order'].append('int')
        self.cat['stats']['stats']['life']['void'] = ['Maximum Life is 1']

    def test_stage_says_what_the_build_tracks_now(self):
        """Этап билда говорит статы по важности, род баз защиты и атрибуты. Из рода по данным игры берутся
        статы защиты (силовые базы несут броню, базы на интеллект — энергощит); слоту без названного рода
        базы даётся род этапа. Атрибуты из рода НЕ берутся: в счёт идут только названные этапом — любые,
        какие есть в игре. Чего этап не назвал, действует как на прежнем."""
        self.assertEqual([herostats.stage(STAGED, pos)['id'] for pos in (None, 0, 1)], ['armour', 'armour', 'es'])
        self.assertEqual([(herostats.defence_stats(self.cat, k), herostats.kind_attrs(self.cat, k)) for k in ('str_armour', 'int_armour')],
                         [(['armour'], ['str']), (['es'], ['int'])])
        self.assertEqual(herostats.attributes(self.cat), ['str', 'int'])      # чего в учебном каталоге требуют базы
        ids = lambda plan: [s['id'] for s in herostats.wanted(plan)]             # noqa: E731
        common = ['minion_level', 'spirit', 'speed', 'res_fire', 'res_cold']
        early, late = herostats.at_step(self.cat, STAGED, 0), herostats.at_step(self.cat, STAGED, 1)
        # энергощит требует интеллект, но этап его не назвал — в счёт он не идёт
        self.assertEqual((ids(early), ids(late)), (common + ['life', 'armour', 'str'], common + ['life', 'es']))
        # а сила при энергощите — пожалуйста: билду виднее, зачем она ему
        synergy = dict(STAGED, stages=[STAGED['stages'][0], dict(STAGED['stages'][1], attrs=['str', 'int', 'nope'])])
        self.assertEqual(ids(herostats.at_step(self.cat, synergy, 1)), common + ['life', 'es', 'str', 'int'])
        # этап, который назвал только статы: база и атрибуты остаются прежними; порядок — его
        own = dict(STAGED, stages=[STAGED['stages'][0], {'id': 'es', 'from': 'maps', 'stats': [{'id': 'armour'}, {'id': 'speed'}]}])
        self.assertEqual(ids(herostats.at_step(self.cat, own, 1)), ['armour', 'speed', 'str'])
        # без каталога данных игры вывести из базы нечего — остаётся список этапа
        self.assertEqual(ids(herostats.at_step(None, STAGED, 1)), common + ['life'])
        gear = lambda plan: {slot: spec for slot, _, spec in herostats.specs(plan)}   # noqa: E731
        # род этапа получают слоты, где он не назван и где такие базы бывают; шлем назван сам, у пояса родов нет
        self.assertEqual([gear(early)[s] for s in ('body', 'boots', 'helmet', 'belt')],
                         ['Body Armour str_armour', 'Boots str_armour', 'Helmet int_armour', 'Belt'])
        # в учебном каталоге нет ни доспеха, ни сапог на интеллект — описание остаётся без рода
        self.assertEqual([gear(late)[s] for s in ('body', 'boots', 'helmet')], ['Body Armour', 'Boots', 'Helmet int_armour'])
        # у билда без этапов статов нет; сам билд этапом не портится
        self.assertEqual(herostats.at_step(self.cat, dict(STAGED, stages=[]), 1)['stats'], [])
        self.assertEqual([s['id'] for s in STAGED['stages'][0]['stats']], common + ['life'])

    def test_stat_the_tree_makes_pointless_is_not_tracked(self):
        """Здоровье не ведут с того шага, с которого действует версия дерева с узлом «Maximum Life is 1»:
        вещи подбирают под неё заранее, не дожидаясь, пока узел взят. Правило — в таблице статов."""
        self.assertEqual(herostats.voided(self.cat, STAGED, 0, TREE_LINES), {})
        self.assertEqual(herostats.voided(self.cat, STAGED, 1, TREE_LINES),
                         {'life': {'node': 'Иммунитет к хаосу', 'line': 'Maximum Life is 1'}})
        ids = lambda pos: [s['id'] for s in herostats.wanted(herostats.at_step(self.cat, STAGED, pos, TREE_LINES))]  # noqa: E731
        self.assertEqual((ids(0)[-3:], ids(1)[-2:]), (['life', 'armour', 'str'], ['res_cold', 'es']))
        # без строк дерева (файла нет) или без правила в таблице стат остаётся
        self.assertEqual(herostats.voided(self.cat, STAGED, 1, None), {})
        del self.cat['stats']['stats']['life']['void']
        self.assertEqual(herostats.voided(self.cat, STAGED, 1, TREE_LINES), {})

    def test_which_stats_decide_first_on_each_stage(self):
        """Странице «Билд»: какие статы на этапе редкие — их несут сами не больше трёх слотов; на таком слоте
        они решают сравнение по порядку списка этапа, остальные статы складываются. Считается по всей
        таблице статов (и про стат, которого в списке этапа нет); слоты — названиями, в порядке билда."""
        rare = herostats.stage_rare(self.cat, STAGED, TREE_LINES)
        early = {'minion_level': ['Оружие', 'Шлем', 'Амулет'], 'spirit': ['Оружие', 'Нательный доспех', 'Амулет'],
                 'speed': ['Сапоги'], 'armour': ['Нательный доспех', 'Сапоги', 'Пояс'], 'es': ['Шлем']}
        self.assertEqual(rare, {'armour': early, 'es': early})
        # сопротивления и здоровье несут пять слотов — складываются; атрибуты в учебном каталоге не несёт никто
        self.assertFalse({'res_fire', 'res_cold', 'life', 'str', 'int'} & set(early))
        # что редкий стат и правда решает первым: сапоги со скоростью лучше сапог с сопротивлением и здоровьем
        self.wear('boots', boots('+30% к сопротивлению огню', '+60 к максимуму здоровья'))
        fast = self.cmp('boots', boots('30% повышение скорости передвижения'), plan=herostats.at_step(self.cat, STAGED, 0, TREE_LINES))
        self.assertEqual((fast['verdict'], [ln['id'] for ln in fast['lines'] if ln.get('decides')]), ('better', ['speed']))
        # с шага «карты» в оружии лук: уровень приспешников и дух остаются на двух слотах
        bow = [{'id': 'bow', 'slot': 'weapon', 'use': 'maps', 'gear': 'Bow'}]
        late = herostats.stage_rare(self.cat, dict(STAGED, goals=STAGED['goals'] + bow), TREE_LINES)
        self.assertEqual((late['armour'], late['es']['minion_level'], late['es']['spirit']),
                         (early, ['Шлем', 'Амулет'], ['Нательный доспех', 'Амулет']))
        # та же смена посреди этапа: стат назван редким на всех слотах, где он редкий хотя бы на части этапа
        one = dict(STAGED, stages=STAGED['stages'][:1], goals=STAGED['goals'] + bow)
        self.assertEqual(herostats.stage_rare(self.cat, one, TREE_LINES), {'armour': early})
        # у маршрута без шагов действует первый этап; без каталога и без этапов считать нечего
        self.assertEqual(herostats.stage_rare(self.cat, dict(STAGED, steps=[]), TREE_LINES), {'armour': early})

    def test_a_slot_counts_when_it_carries_the_stat_for_sure(self):
        """В счёт редкости идёт слот, который несёт стат наверняка — на предмете любого класса, который в нём
        носят. Оружие, где принимают и скипетр, и лук, уровень приспешников несёт, только если наденут скипетр."""
        at = herostats.at_step(self.cat, STAGED, 0, TREE_LINES)
        hand = {'id': 'offhand', 'name': 'Вторая рука', 'gear': 'Sceptre'}
        plan = lambda specs: dict(at, slots=[dict(s, specs=specs) if s['id'] == 'weapon' else s for s in at['slots']] + [hand])   # noqa: E731
        # скипетр в обеих руках, шлем, амулет — четыре слота несут стат наверняка: он не редкий
        four = herostats.carriers(self.cat, plan(['Sceptre']))
        self.assertEqual((herostats.source_slots(four, 'minion_level'), herostats.sure_slots(four, 'minion_level')),
                         (['weapon', 'helmet', 'amulet', 'offhand'], ['weapon', 'helmet', 'amulet', 'offhand']))
        self.assertEqual((herostats.is_scarce(four, 'minion_level'), herostats.is_rare(four, 'minion_level', 'offhand')), (False, False))
        # в оружии принимают скипетр или лук: слот стат несёт не наверняка — в счёт идут три, стат редкий;
        # на самом оружии он тоже редкий: скипетр, скопированный для него, сравнивается так же
        some = herostats.carriers(self.cat, plan(['Sceptre', 'Bow']))
        self.assertEqual((herostats.source_slots(some, 'minion_level'), herostats.sure_slots(some, 'minion_level')),
                         (['weapon', 'helmet', 'amulet', 'offhand'], ['helmet', 'amulet', 'offhand']))
        self.assertEqual([herostats.is_rare(some, 'minion_level', s) for s in ('weapon', 'offhand', 'helmet', 'boots')],
                         [True, True, True, False])
        self.assertEqual((some['minion_level']['weapon']['every'], some['minion_level']['offhand']['every']), (False, True))
        self.assertEqual((some['minion_level']['weapon']['on'], four['minion_level']['weapon']['on']), (['Sceptre'], ['Sceptre']))
        # как такой слот назван на странице «Этапы»: с классом, на котором стат бывает (слово клиента игры)
        self.cat['lang'] = {'ru': {'classes': {'Скипетры': 'Sceptre'}, 'classNames': {'Bow': 'Луки'}}}
        self.assertEqual([herostats.class_word(self.cat, c) for c in ('Sceptre', 'Bow', 'Wand')], ['Скипетры', 'Луки', 'Wand'])
        wide = dict(STAGED, stages=STAGED['stages'][:1], slots=[
            dict(s, wear=[{'classes': ['Sceptre', 'Bow']}]) if s['id'] == 'weapon' else s for s in STAGED['slots']] + [hand])
        self.assertEqual(herostats.stage_rare(self.cat, wide, TREE_LINES)['armour']['minion_level'],
                         ['Оружие (скипетры)', 'Шлем', 'Амулет', 'Вторая рука'])
        # редкий стат, которого на предмете нет, ищут на слоте, только если он бывает на предмете такого класса
        self.assertEqual([herostats.may_carry(some, 'minion_level', 'weapon', c) for c in ('Sceptre', 'Bow', None)], [True, False, True])
        self.assertEqual([herostats.may_carry(some, 'minion_level', s, 'Bow') for s in ('offhand', 'helmet', 'boots')], [True, True, False])
        # карточка слота говорит «нет» редкого стата, только когда он бывает на предмете надетого класса: с луком
        # в оружии таких строк нет, с простым скипетром — уровень приспешников и дух
        staged = plan(['Sceptre', 'Bow'])
        key = herostats.hero_keys(staged)['weapon']
        missing = lambda item: [ln['id'] for ln in herostats.slot_item(                                 # noqa: E731
            self.cat, staged, 'weapon', key, {key: {'item': item}}, {})['lines'] if ln['missing']]
        sceptre = self.item(text('Скипетры', 'Гремящий скипетр'))
        self.assertEqual(missing(dict(sceptre, cls_id='Bow')), [])
        self.assertEqual(missing(sceptre), ['minion_level', 'spirit'])
        self.assertEqual((herostats.stage_rare(None, STAGED), herostats.stage_rare(self.cat, dict(STAGED, stages=[]))), ({}, {}))

    def test_the_same_item_is_judged_by_the_stage(self):
        """Доспех с бронёй и здоровьем против доспеха без них: на этапе брони новая вещь хуже, на этапе
        энергощита броня и здоровье в сравнение уже не идут."""
        self.wear('body', body('+50 к максимуму здоровья', armour=400))
        new = body(armour=300)
        early = self.cmp('body', new, plan=herostats.at_step(self.cat, STAGED, 0, TREE_LINES))
        self.assertEqual((early['verdict'], sorted(ln['id'] for ln in early['lines'])), ('worse', ['armour', 'life']))
        late = self.cmp('body', new, plan=herostats.at_step(self.cat, STAGED, 1, TREE_LINES))
        self.assertEqual((late['verdict'], late['lines']), ('same', []))


class HeroTest(Base):
    def test_totals_from_remembered_items(self):
        """Суммы статов со всех надетых вещей — от них сравнение считает героя у порога."""
        self.wear('body', body('+6% к сопротивлению огню', '+95 к максимуму здоровья', armour=358))
        self.wear('boots', boots('30% повышение скорости передвижения', '+20% к сопротивлению холоду'))
        self.wear('amulet', text('Амулеты', 'Солнечный амулет', '+2 к уровню всех камней умений приспешников'))
        sums = herostats.gear_sums(self.cat, [e['item'] for e in self.worn.values()])
        self.assertEqual([sums.get(sid) for sid in ('res_fire', 'res_cold', 'life', 'armour', 'minion_level')], [6, 20, 95, 358, 2])
        # штраф базы умножается на прибавки: (1 − 5%) × (1 + 30%) − 1
        self.assertEqual(sums['speed'], 23.5)

    def test_what_comes_not_from_gear(self):
        """Помимо вещей пока считаются награды маршрута и штраф актов."""
        zone = lambda code, level: {'type': 'zone', 'code': code, 'level': level}
        pen = [herostats.res_penalty([zone(c, lv)]) for c, lv in
               (('G1_1', 1), ('G2_3', 20), ('G3_5', 40), ('G4_2', 50), ('P1_3', 55), ('P2_1', 61), ('P3_2', 65),
                ('Map_X', 66), ('G_Endgame_Town', 65))]
        self.assertEqual(pen, [0, 10, 20, 30, 40, 50, 60, 60, 60])
        # считается самое дальнее место забега, а не то, где герой стоит
        self.assertEqual(herostats.res_penalty([zone('G3_1', 35), zone('G1_town', 15)]), 20)
        # холод: +10 награды −20 штрафа
        self.assertEqual(herostats.rest(self.cat, {'res_cold': 10}, [zone('G3_1', 35)]), {'res_cold': -10, 'res_fire': -20})
        # чужой стат и не число — не в счёт
        self.assertEqual(herostats.rest(self.cat, {'res_cold': 15, 'nothing': 3, 'life': True}, []), {'res_cold': 15})
        self.assertEqual(herostats.rest(None, None, []), {})

    def test_places_of_the_memory(self):
        # Место в памяти надетого — слот: он помнит один предмет, тот, что надет (рюкзака нет). Описание базы слота
        # на шаге (at_step) меняется по периодам: до шага «after» в оружии лук, с него — скипетр.
        plan = dict(PLAN, steps=[{'id': 'start'}, {'id': 'trial'}, {'id': 'after'}],
                    slots=[{'id': 'weapon', 'name': 'Оружие'}] + PLAN['slots'][1:],
                    goals=[{'id': 'bow', 'slot': 'weapon', 'until': 'trial', 'gear': 'Bow'},
                           {'id': 'sceptre-spirit', 'slot': 'weapon', 'use': 'after', 'part': 'spirit', 'gear': 'Wand'},
                           {'id': 'sceptre', 'slot': 'weapon', 'use': 'after', 'gear': 'Sceptre'}])
        self.assertEqual(herostats.slot_lines(plan)['weapon'], [(-1, None, 'Bow'), (2, 'after', 'Sceptre')])
        early, late = herostats.at_step(self.cat, plan, 1), herostats.at_step(self.cat, plan, 2)
        self.assertEqual((early['keys']['weapon'], late['keys']['weapon'], late['keys']['boots']),
                         ('weapon/', 'weapon/', 'boots/'))
        gear = lambda p: dict((sid, spec) for sid, _, spec in herostats.specs(p))     # noqa: E731
        self.assertEqual((gear(early)['weapon'], gear(late)['weapon'], gear(late)['boots']), ('Bow', 'Sceptre', 'Boots'))
        self.assertEqual((herostats.hero_keys(early)['weapon'], herostats.hero_keys(late)['weapon']), ('weapon/', 'weapon/'))
        # пороги автора — по месту слота; порогом служит цель периода, который в ходу: будущего — ещё нет, цель, чей срок
        # годности позади, — уже нет
        plan['goals'] += [{'id': 'bow-dmg', 'slot': 'weapon', 'until': 'trial', 'stat': 'res_cold', 'min': 10},
                          {'id': 'spirit-120', 'slot': 'weapon', 'use': 'after', 'stat': 'spirit', 'min': 120},
                          {'id': 'boots-speed', 'slot': 'boots', 'stat': 'speed', 'min': 25},
                          {'id': 'odd', 'slot': 'boots', 'stat': 'speed', 'min': True}]
        self.assertEqual(herostats.at_step(self.cat, plan, 1)['floors'], {
            'weapon/': [{'stat': 'res_cold', 'min': 10, 'goal': 'bow-dmg'}],
            'boots/': [{'stat': 'speed', 'min': 25, 'goal': 'boots-speed'}]})
        self.assertEqual(herostats.at_step(self.cat, plan, 2)['floors'], {
            'weapon/': [{'stat': 'spirit', 'min': 120, 'goal': 'spirit-120'}],
            'boots/': [{'stat': 'speed', 'min': 25, 'goal': 'boots-speed'}]})
        # билд «как есть» мест не называет: вещь слота лежит в месте с пустой линией
        self.assertEqual(herostats.hero_keys({'slots': [{'id': 'boots'}]}), {'boots': 'boots/'})
        # статы запомненных вещей по местам: по ним сами отмечаются цели по стату
        self.wear('boots', boots('30% повышение скорости передвижения', '+20% к сопротивлению холоду'))
        self.assertEqual(herostats.gear(self.cat, self.worn), {'boots/': {'speed': 30, 'res_cold': 20}})
        self.assertEqual(herostats.gear(None, self.worn), {})


ADVANCED = '''Класс предмета: Сапоги
Редкость: Редкий
Быстрый шаг
Грубые поножи
--------
Уровень предмета: 66
--------
{ Префикс "Гепарда" (Уровень: 2) — Скорость }
30% повышение скорости передвижения
{ Префикс "Массивный" (Уровень: 7) — Здоровье }
+50(46-99) к максимуму здоровья
{ Суффикс "инея" (Уровень: 8) — Стихийный, Холод, Сопротивление }
+7(6-10)% к сопротивлению холоду
{ Суффикс "силача" (Уровень: 8) — Характеристика }
+5(5-8) к силе
'''


class SlotItemTest(Base):
    def test_what_the_worn_item_gives_the_build(self):
        """Вещь слота для плитки и карточки: её статы билда против лучшего, что сейчас бывает, и её
        аффиксы отрезками — сколько из них работает на билд."""
        self.assertIsNone(herostats.slot_item(self.cat, PLAN, 'boots', 'boots/', self.worn, {}))
        self.cat['bases']['Armours/Boots/B']['icon'] = 'art-bootsstr1'      # картинка базы, как в каталоге
        self.wear('boots', ADVANCED)
        it = herostats.slot_item(self.cat, PLAN, 'boots', 'boots/', self.worn, {'res_cold': 10}, 70)
        self.assertEqual((it['name'], it['base'], it['icon']), ('Быстрый шаг', 'Грубые поножи', 'art-bootsstr1'))
        self.assertEqual([(ln['id'], ln['cls'], ln['value'], ln['top'], ln['q']) for ln in it['lines']],
                         [('speed', 'scarce', 30, 30, 1.0), ('res_cold', 'need', 7, 35, 0.2), ('life', 'grow', 50, 99, 0.51)])
        self.assertEqual((it['lines'][1]['hero'], it['lines'][1]['cap']), (17, 75))
        # четыре аффикса из шести: редкий первым, дальше по силе; сила билду не нужна; два места свободны
        self.assertEqual([(c['stat'], c['q'], c['rare'], c['free']) for c in it['bar']],
                         [('speed', 1.0, True, False), ('life', 0.51, False, False), ('res_cold', 0.2, False, False),
                          (None, 0, False, False), (None, 0, False, True), (None, 0, False, True)])
        # редкого стата слота на вещи нет — строка есть и помечена
        self.wear('amulet', text('Амулеты', 'Солнечный амулет', '+33 к духу'))
        am = herostats.slot_item(self.cat, PLAN, 'amulet', 'amulet/', self.worn, {})
        self.assertEqual([(ln['id'], ln['value'], ln['missing']) for ln in am['lines']],
                         [('minion_level', 0, True), ('spirit', 33, False)])
        # у простой копии аффиксов не видно — отрезков нет
        self.assertIsNone(am['bar'])

    def test_cap_held_by_this_item_is_not_surplus(self):
        """Стат с порогом «сверх» только тогда, когда без этой вещи герой всё равно у порога. Порог держит она — строка
        нужная и говорит, сколько станет без неё (их проверка 2026-11-24)."""
        self.wear('boots', boots('+35% к сопротивлению холоду'))
        self.wear('belt', text('Пояса', 'Сыромятный пояс', '+35% к сопротивлению холоду'))

        def cold(extra):
            it = herostats.slot_item(self.cat, PLAN, 'boots', 'boots/', self.worn, extra)
            return next(ln for ln in it['lines'] if ln['id'] == 'res_cold')
        # вещи 70 + прочее 10: у героя 80, без сапог было бы 45
        self.assertEqual((cold({'res_cold': 10})['cls'], cold({'res_cold': 10})['hero'], cold({'res_cold': 10})['without']),
                         ('need', 80, 45))
        # прочего 40: без сапог герой всё равно 75 — их холод сверх порога целиком
        self.assertEqual((cold({'res_cold': 40})['cls'], cold({'res_cold': 40})['hero']), ('over', 110))
        self.assertNotIn('without', cold({'res_cold': 40}))
        # ниже порога нужно всё — подписи нет
        self.assertEqual((cold({})['cls'], cold({})['hero']), ('need', 70))
        self.assertNotIn('without', cold({}))


if __name__ == '__main__':
    unittest.main()
