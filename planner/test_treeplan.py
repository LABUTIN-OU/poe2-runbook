# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Sergei Labutin
# Additional terms under GPL-3.0 section 7: see NOTICE.md
"""Правка дерева со страницы «Билд»: проверка присланных версий, запись раздела "tree" в файл плана.

Запуск: python -m unittest planner.test_treeplan
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import buildplan  # noqa: E402
import server  # noqa: E402
import treegeo  # noqa: E402
import treeplan  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

# Маленькое дерево: старт — a — b(«Характеристика») — c(значимый), a — d — c (кольцо), d — e;
# рядом чужой старт со своим узлом z.
GEO = {
    'nodes': [['start', 0, 0, 5, 'Start'], ['a', 0, -100, 0, 'Spell Damage'], ['b', -100, -200, 1, 'Attribute'],
              ['c', 0, -300, 2, 'Raw Power'], ['d', 100, -200, 0, 'Mana'], ['e', 200, -200, 0, 'Mana'],
              ['other', 900, 0, 5, 'Other Start'], ['z', 900, -100, 0, 'Axe Damage']],
    'edges': [[0, 1], [1, 2], [2, 3], [1, 4], [4, 3], [4, 5], [6, 7]],
}
TREE = {'attr': 'инт', 'phases': [
    {'id': 'start', 'name': 'До вознесения', 'nodes': [
        {'id': 'a', 'name': 'Урон чарами'}, {'id': 'b', 'name': 'Характеристика', 'kind': 'attribute'}]},
    {'id': 'maps', 'name': 'Карты', 'nodes': []}]}
# Этапы билда: они говорят, какая версия дерева с какого шага действует.
STAGES = [{'id': 'start', 'name': 'Старт', 'tree': 'start'},
          {'id': 'late', 'from': 'clearfell', 'name': 'Поздно', 'tree': 'maps'}]


def build_text(tree, eol='\n', stages=None):
    """Файл билда в том виде, в каком его пишут в проекте: раздел дерева между другими разделами;
    stages — этапы билда, раздел перед деревом."""
    head = ['{', '  "version": 2,', '  "title": "Проба",']
    if stages:
        head += buildplan.render('stages', stages)
        head[-1] += ','
    return eol.join(head + treeplan.render(tree)[:-1] + ['  },', '  "goals": [',
                    '    {"id": "g1", "title": "Цель"}', '  ]', '}', ''])


class CheckTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        path = Path(self.tmp.name) / 'tree.json'
        path.write_text(json.dumps(GEO), encoding='utf-8')
        self.geo = treeplan.load_geo(path)

    def tearDown(self):
        self.tmp.cleanup()

    def bad(self, nodes, vid='start'):
        return treeplan.check([{'id': vid, 'nodes': nodes}], TREE, self.geo)[1]

    def test_good_versions_pass(self):
        clean, problems = treeplan.check([{'id': 'start', 'nodes': [{'id': 'a'}, {'id': 'b', 'attr': 'str'}, {'id': 'c'}]},
                                          {'id': 'maps', 'nodes': []}], TREE, self.geo)
        self.assertEqual(problems, [])
        self.assertEqual(clean, {'start': [{'id': 'a'}, {'id': 'b', 'attr': 'str'}, {'id': 'c'}], 'maps': []})

    def test_what_is_refused(self):
        self.assertEqual(treeplan.check('нет', TREE, self.geo)[1], ['нет ни одной версии дерева'])
        self.assertEqual(self.bad([{'id': 'a'}], vid='nope'), ['версии «nope» в плане нет'])
        self.assertEqual(self.bad([{'id': 'a'}, {'id': 'q'}]), ['версия «start»: узла «q» нет в дереве'])
        # старт класса — не узел плана
        self.assertEqual(self.bad([{'id': 'start'}]), ['версия «start»: узла «start» нет в дереве'])
        self.assertEqual(self.bad([{'id': 'a'}, {'id': 'a'}]), ['версия «start»: узел «a» записан дважды'])
        self.assertIn('атрибут бывает только str, dex или int', self.bad([{'id': 'a'}, {'id': 'b', 'attr': 'wis'}])[0])
        self.assertIn('только у узла «Характеристика»', self.bad([{'id': 'a', 'attr': 'str'}])[0])
        # порядок, который в игре не пройти: c примыкает к b и d, а они ещё не взяты
        self.assertEqual(self.bad([{'id': 'a'}, {'id': 'c'}, {'id': 'b'}]),
                         ['версия «start»: узел «c» стоит раньше своих соседей — такой порядок в игре не пройти'])
        # первый узел должен примыкать к старту класса
        self.assertIn('узел «b» стоит раньше своих соседей', self.bad([{'id': 'b'}])[0])
        # одна плохая версия — не записывается ни одна
        clean, problems = treeplan.check([{'id': 'start', 'nodes': [{'id': 'a'}]}, {'id': 'maps', 'nodes': [{'id': 'q'}]}],
                                         TREE, self.geo)
        self.assertEqual((clean, len(problems)), ({}, 1))

    def test_any_number_of_versions_each_with_its_name(self):
        """Версий столько, сколько нужно билду, у каждой своё имя; встают в том порядке, в каком присланы.
        С какого шага версия действует, решает этап билда: версию, которую он назвал, из набора не убрать."""
        sent = [{'id': 'v3', 'name': ' К боссу ', 'nodes': [{'id': 'a'}, {'id': 'd'}]},
                {'id': 'start', 'name': 'Начало', 'nodes': [{'id': 'a'}]},
                {'id': 'v2', 'name': 'После Клирфелла', 'nodes': [{'id': 'a'}, {'id': 'b', 'attr': 'dex'}]}]
        clean, problems = treeplan.check_all(sent, {'start': ['Старт']}, self.geo)
        self.assertEqual(problems, [])
        self.assertEqual([(v['id'], v['name'], len(v['nodes'])) for v in clean],
                         [('v3', 'К боссу', 2), ('start', 'Начало', 1), ('v2', 'После Клирфелла', 2)])
        self.assertEqual(list(clean[0]), ['id', 'name', 'nodes'])

        def bad(*vs, used=None):
            return treeplan.check_all(list(vs), used or {}, self.geo)[1]

        base = {'id': 'start', 'name': 'Начало', 'nodes': []}
        self.assertEqual(bad(base, used={'maps': ['Карты', 'Босс']}),
                         ['версию «maps» убрать нельзя: она действует на этапе «Карты», «Босс» — сначала дайте этапу '
                          'другую (вкладка «Этапы»)'])
        self.assertEqual(treeplan.check_all([], {}, self.geo)[1], ['нет ни одной версии дерева'])
        self.assertIn('нужно название', bad(base, {'id': 'v2', 'name': '  ', 'nodes': []})[0])
        self.assertIn('латинские буквы', bad(base, {'id': 'Версия', 'name': 'В', 'nodes': []})[0])
        self.assertIn('прислана дважды', bad(base, dict(base, name='Копия'))[0])
        # узлы версии проверяются так же, как при правке одной версии; в замечании — её название
        self.assertEqual(bad(base, {'id': 'v2', 'name': 'К боссу', 'nodes': [{'id': 'a'}, {'id': 'c'}]}),
                         ['версия «К боссу»: узел «c» стоит раньше своих соседей — такой порядок в игре не пройти'])

    def test_full_set_replaces_the_versions_of_the_plan(self):
        tree = {'attr': 'инт', 'phases': [
            {'id': 'start', 'from': 'gone', 'name': 'До вознесения', 'note': 'своё поле', 'nodes': [{'id': 'a', 'name': 'Урон чарами'}]},
            {'id': 'old', 'name': 'Старая', 'nodes': []}]}
        versions = [{'id': 'start', 'name': 'Начало', 'nodes': [{'id': 'a'}, {'id': 'b', 'attr': 'str'}]},
                    {'id': 'v2', 'name': 'К боссу', 'nodes': [{'id': 'a'}]}]
        new = treeplan.apply_all(tree, versions, treeplan.known_names(tree), self.geo, 'str')
        # своё поле версии остаётся; прежнее поле шага (from) версия больше не хранит
        self.assertEqual(new, {'attr': 'str', 'phases': [
            {'id': 'start', 'name': 'Начало', 'note': 'своё поле',
             'nodes': [{'id': 'a', 'name': 'Урон чарами'}, {'id': 'b', 'name': 'Attribute', 'kind': 'attribute', 'attr': 'str'}]},
            {'id': 'v2', 'name': 'К боссу', 'nodes': [{'id': 'a', 'name': 'Урон чарами'}]}]})
        # поля версии идут как в файле: id, name, …, nodes
        self.assertEqual(list(new['phases'][0]), ['id', 'name', 'note', 'nodes'])
        # атрибут по умолчанию не прислан — остаётся прежним; прежнее дерево не тронуто
        self.assertEqual(treeplan.apply_all(tree, versions, {}, self.geo)['attr'], 'инт')
        self.assertEqual(len(tree['phases']), 2)
        # страница, которая присылает атрибут каждого узла явно, прежнее «по умолчанию» из раздела убирает
        self.assertNotIn('attr', treeplan.apply_all(tree, versions, {}, self.geo, drop_default=True))
        self.assertEqual(tree['attr'], 'инт')

    def test_the_old_default_attribute_is_written_to_each_node(self):
        """Атрибута «по умолчанию» у дерева больше нет. Узлы старого файла, которые на него опирались, странице
        отдаются уже с этим атрибутом; что узел — «Характеристика», говорят данные дерева, а без них — запись."""
        nodes = [{'id': 'a', 'name': 'Урон чарами'}, {'id': 'b', 'name': 'Характеристика', 'kind': 'attribute'},
                 {'id': 'c', 'kind': 'notable'}, 'мусор', {'name': 'без id'}]
        self.assertEqual(treeplan.with_default(nodes, 'инт', self.geo), [{'id': 'a'}, {'id': 'b', 'attr': 'int'}, {'id': 'c'}])
        self.assertEqual(treeplan.with_default(nodes, 'Strength'), [{'id': 'a'}, {'id': 'b', 'attr': 'str'}, {'id': 'c'}])
        # свой атрибут узла важнее; нет «по умолчанию» (или в нём не атрибут) — узел без выбора остаётся пустым
        own = [{'id': 'b', 'kind': 'attribute', 'attr': 'dex'}]
        self.assertEqual(treeplan.with_default(own, 'инт', self.geo), [{'id': 'b', 'attr': 'dex'}])
        self.assertEqual([treeplan.with_default(nodes[:2], d, self.geo) for d in (None, 'мудрость')], [[{'id': 'a'}, {'id': 'b'}]] * 2)
        self.assertEqual([treeplan.attr_id(w) for w in ('int', ' Инт ', 'Dexterity', 'сила', 'wis', None)],
                         ['int', 'int', 'dex', 'str', None, None])

    def test_records_take_names_from_the_plan_then_from_the_log(self):
        names = treeplan.known_names(TREE, {'a': 'Из лога', 'c': 'Необузданная мощь'})
        recs = treeplan.records([{'id': 'a'}, {'id': 'b', 'attr': 'dex'}, {'id': 'c'}, {'id': 'd'}], names, self.geo)
        self.assertEqual(recs, [{'id': 'a', 'name': 'Урон чарами'},                      # в плане уже названо
                                {'id': 'b', 'name': 'Характеристика', 'kind': 'attribute', 'attr': 'dex'},
                                {'id': 'c', 'name': 'Необузданная мощь', 'kind': 'notable'},  # назвал лог
                                {'id': 'd', 'name': 'Mana'}])                             # игра ещё не называла


class FileTest(unittest.TestCase):
    def test_only_the_tree_section_changes(self):
        for eol in ('\n', '\r\n'):
            text = build_text(TREE, eol)
            self.assertEqual(treeplan.splice(text, TREE), text)      # без правок текст тот же, знак в знак
            new = json.loads(json.dumps(TREE))
            new['phases'][1]['nodes'] = [{'id': 'a', 'name': 'Урон чарами'}, {'id': 'd', 'name': 'Mana'}]
            out = treeplan.splice(text, new)
            self.assertEqual(json.loads(out)['tree'], new)
            self.assertEqual({k: v for k, v in json.loads(out).items() if k != 'tree'},
                             {k: v for k, v in json.loads(text).items() if k != 'tree'})
            self.assertIn('        {"id": "d", "name": "Mana"}' + eol + '      ]}', out)
            self.assertEqual(out.count('\r\n') > 0, eol == '\r\n')

    def test_odd_layout_is_left_alone(self):
        one_line = json.dumps({'tree': TREE, 'goals': []}, ensure_ascii=False)
        with self.assertRaises(ValueError):
            treeplan.splice(one_line, TREE)

    def test_save_keeps_a_copy_of_the_old_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, backup = Path(tmp) / 'build.json', Path(tmp) / 'backup'
            path.write_bytes(build_text(TREE, '\r\n').encode('utf-8'))
            new = json.loads(json.dumps(TREE))
            new['phases'][0]['nodes'].append({'id': 'c', 'name': 'Raw Power', 'kind': 'notable'})
            treeplan.save(path, new, backup, now=1794787200)
            self.assertEqual(json.loads(path.read_text(encoding='utf-8'))['tree'], new)
            copies = list(backup.glob('build.tree-*.json'))
            self.assertEqual(len(copies), 1)
            self.assertEqual(json.loads(copies[0].read_text(encoding='utf-8'))['tree'], TREE)
            self.assertFalse((Path(tmp) / 'build.json.tmp').exists())

    def test_the_real_plan_is_written_back_exactly(self):
        """Раздел дерева настоящего плана воспроизводится знак в знак, а его версии проходят проверку
        порядка — иначе первая же правка со страницы переписала бы файл не так, как он написан."""
        import planlib
        plans, geo_path = planlib.project_plans(ROOT), ROOT / 'planner' / 'static' / 'tree.json'
        if not (plans and geo_path.exists()):
            self.skipTest('нет файлов плана или дерева')
        geo = treeplan.load_geo(geo_path)
        for path, parts in plans:
            with self.subTest(plan=path.parent.name):
                text = parts['build'].read_bytes().decode('utf-8-sig')
                if 'tree' not in json.loads(text):
                    continue        # новый план: дерева ещё нет — первая версия встанет разделом сама (splice)
                tree = json.loads(text)['tree']
                self.assertEqual(treeplan.splice(text, tree), text)
                versions = [{'id': ph['id'], 'nodes': [{'id': n['id']} for n in ph['nodes']]} for ph in tree['phases']]
                clean, problems = treeplan.check(versions, tree, geo)
                self.assertEqual(problems, [])
                names = treeplan.known_names(tree)
                for ph in tree['phases']:
                    plain = [{k: v for k, v in n.items() if k != 'attr'} for n in ph['nodes']]
                    self.assertEqual(treeplan.records(clean[ph['id']], names, geo), plain)


class GeoTest(unittest.TestCase):
    def test_node_stats_come_without_markup(self):
        data = {'nodes': {
            '1': {'id': 'es1', 'x': 0, 'y': 0, 'stats': ['12% increased maximum [EnergyShield|Energy Shield]']},
            '2': {'id': 'two', 'x': 1, 'y': 1, 'stats': ['+5 to any [Attributes|Attribute]\n[Minion|Minions] deal 10% increased Damage']},
            '3': {'id': 'AscendancyX1', 'x': 2, 'y': 2, 'ascendancyId': 'X', 'stats': ['+10 to [Strength]']},
            '4': {'id': 'empty', 'x': 3, 'y': 3, 'stats': []},
            '5': {'id': 'deco', 'x': 4, 'y': 4, 'isMastery': True, 'stats': ['не в счёт']}}}
        # узел восхождения входит: взятые героем узлы лог называет теми же id, и по строке видно, что он даёт
        self.assertEqual(treegeo.stats(data), {'es1': ['12% increased maximum Energy Shield'],
                                               'two': ['+5 to any Attribute', 'Minions deal 10% increased Damage'],
                                               'AscendancyX1': ['+10 to Strength']})

    def test_node_lines_in_the_client_language(self):
        """GGG пишет, что даёт узел, только по-английски; перевод — по таблицам статов каталога (ref общий у языков):
        форма «уменьшение» — своей формой, у числа свой знак, двойной пробел таблицы — одним. Строки, которой нет
        в таблице, перевод не выдумывает: она остаётся английской."""
        en = [{'ref': '#% increased Cast Speed', 'matchers': [{'string': '#% increased Cast Speed'},
                                                             {'string': '#% reduced Cast Speed', 'negate': True}]},
              {'ref': '# to Strength', 'matchers': [{'string': '# to Strength'}]},
              {'ref': 'Minions have #% increased Cooldown Recovery Rate',
               'matchers': [{'string': 'Minions have #% increased Cooldown Recovery Rate'}]}]
        ru = [{'ref': '#% increased Cast Speed', 'matchers': [{'string': '#% повышение скорости сотворения чар'},
                                                             {'string': '#% снижение скорости сотворения чар', 'negate': True}]},
              {'ref': '# to Strength', 'matchers': [{'string': '# к силе'}]},
              {'ref': 'Minions have #% increased Cooldown Recovery Rate',
               'matchers': [{'string': 'Приспешники имеют #%  повышение скорости перезарядки'}]}]
        what = {'n1': ['10% increased Cast Speed', '6% reduced Cast Speed'],
                'n2': ['+10 to Strength', 'Minions have 20% increased Cooldown Recovery Rate', 'Gain 5 Unknown Things']}
        out, counts = treegeo.lang_stats(what, en, ru)
        self.assertEqual(out, {'n1': ['10% повышение скорости сотворения чар', '6% снижение скорости сотворения чар'],
                               'n2': ['+10 к силе', 'Приспешники имеют 20% повышение скорости перезарядки',
                                      'Gain 5 Unknown Things']})
        self.assertEqual(counts, (4, 5))

    def test_node_lines_by_game_descriptions(self):
        """Строки узла словами игры на любом её языке — по описаниям свойств (файл игры .csd): английский вариант
        узнаётся по скелету, числа переходят в вариант языка, «уменьшение» — своей формой; у языка свои формы числа
        (одно, два–четыре, много) — по значению; свойство в две строки переводится целиком."""
        csd = ('description\r\n\t1 base_cast_speed_+%\r\n\t2\r\n'
               '\t\t1|# "{0}% increased Cast Speed"\r\n\t\t#|-1 "{0}% reduced Cast Speed" negate 1\r\n'
               '\tlang "German"\r\n\t2\r\n'
               '\t\t1|# "{0}% erhöhte Zaubergeschwindigkeit"\r\n\t\t#|-1 "{0}% verringerte Zaubergeschwindigkeit" negate 1\r\n'
               'description\r\n\t1 base_strength\r\n\t1\r\n\t\t# "{0:+d} to [Strength|Strength]"\r\n'
               '\tlang "Russian"\r\n\t3\r\n\t\t1 "{0:+d} очко силы"\r\n\t\t2|4 "{0:+d} очка силы"\r\n'
               '\t\t# "{0:+d} очков силы"\r\n'
               'description\r\n\t1 infusion_chance_%\r\n\t1\r\n\t\t# "{0}% chance to gain an\\nadditional Infusion"\r\n'
               '\tlang "German"\r\n\t1\r\n\t\t# "{0}% Chance, eine zusätzliche Infusion zu erhalten"\r\n')
        descs = treegeo.parse_descriptions(csd)
        de = treegeo.desc_translator(descs, 'de')
        self.assertEqual(de('10% increased Cast Speed'), ['10% erhöhte Zaubergeschwindigkeit'])
        self.assertEqual(de('6% reduced Cast Speed'), ['6% verringerte Zaubergeschwindigkeit'])
        self.assertEqual(de('5% chance to gain an\nadditional Infusion'), ['5% Chance, eine zusätzliche Infusion zu erhalten'])
        self.assertIsNone(de('+10 to Strength'))                    # немецкого варианта у описания нет
        ru = treegeo.desc_translator(descs, 'ru')
        self.assertEqual([ru('+1 to Strength'), ru('+3 to Strength'), ru('+10 to Strength')],
                         [['+1 очко силы'], ['+3 очка силы'], ['+10 очков силы']])
        self.assertIsNone(ru('Gain 5 Unknown Things'))
        # строки интерфейса игры: очки пассивных умений, «узел даёт умение» — с именем умения словами игры
        ui = [{'ids': ['PassiveNodeGrantsPassivePoint'], 'lang': {'en': [([], 'Grants {0} Passive Skill Point', [])],
                                                                 'de': [([], 'Gewährt {0} passiven Fertigkeitspunkt', [])]}}]
        granted = {'en': 'Grants Skill: <underline>{{{0}}}', 'de': 'Gewährt Fertigkeit: <underline>{{{0}}}'}
        de = treegeo.desc_translator(ui + descs, 'de', granted, {'Temper Weapon': 'Waffe temperieren'})
        self.assertEqual(de('Grants 1 Passive Skill Point'), ['Gewährt 1 passiven Fertigkeitspunkt'])
        self.assertEqual(de('Grants Skill: Temper Weapon'), ['Gewährt Fertigkeit: Waffe temperieren'])
        self.assertEqual(de('Grants Skill: Unknown Skill'), ['Gewährt Fertigkeit: Unknown Skill'])
        # свойство в две строки — целиком; строка, которой нет нигде, остаётся английской
        out, counts = treegeo.page_stats({'n': ['5% chance to gain an\nadditional Infusion', 'Gain 5 Unknown Things']}, de)
        self.assertEqual(out, {'n': ['5% Chance, eine zusätzliche Infusion zu erhalten', 'Gain 5 Unknown Things']})
        self.assertEqual(counts, (2, 3))
        # разметка GGG снимается и в английских строках: «Grants Skill: <underline>{…}»
        self.assertEqual(treegeo.plain('Grants Skill: <underline>{Temper Weapon}'), 'Grants Skill: Temper Weapon')

    def test_saved_game_descriptions(self):
        """На сохранённых источниках каталога: строки ключевого узла и обычные — словами игры."""
        sources = ROOT / 'catalog' / 'sources'
        try:
            base = sources / (sources / 'current.txt').read_text(encoding='utf-8').strip()
        except OSError:
            self.skipTest('нет источников каталога')
        descs = treegeo.read_descriptions(base)
        if not (base / 'dat' / 'passive_skill_stat_descriptions.csd.gz').is_file():
            self.skipTest('нет описаний свойств пассивных умений')
        ui, granted = treegeo.ui_descriptions(base)
        ru = treegeo.desc_translator(ui + descs, 'ru', granted)
        # ключевой узел: одно свойство игры в две строки
        self.assertEqual(ru('Maximum Life is 1' + chr(10) + 'Immune to Chaos Damage and Bleeding'),
                         ['Максимум здоровья равен 1', 'Иммунитет к урону хаосом и кровотечению'])
        self.assertEqual(ru('10% increased Spell Damage'), ['10% увеличение урона от чар'])
        self.assertEqual(ru('Grants 1 Passive Skill Point'), ['Дарует 1 очко пассивных умений'])
        de = treegeo.desc_translator(ui + descs, 'de', granted)
        self.assertEqual(de('Maximum Life is 1' + chr(10) + 'Immune to Chaos Damage and Bleeding'),
                         ['Maximales Leben beträgt 1', 'Immun gegen Chaosschaden und Bluten'])

    def test_saved_sources_give_russian_lines(self):
        """На сохранённых источниках каталога: какие языки есть и строка настоящего узла по-русски."""
        en, langs = treegeo.catalog_langs(ROOT / 'catalog' / 'sources')
        if en is None or 'ru' not in langs:
            self.skipTest('нет таблиц статов каталога')
        tr = treegeo.translator(treegeo.stat_rows(en), treegeo.stat_rows(langs['ru']))
        self.assertEqual(tr('10% increased Spell Damage'), '10% увеличение урона от чар')
        self.assertEqual(tr('Minions deal 10% increased Damage'), 'Приспешники имеют 10% увеличение урона')
        self.assertIsNone(tr('+5 to any Attribute'))


LOG = '\n'.join([
    '2026/11/11 20:07:03 1 a [DEBUG Client 1] Generating level 1 area "G1_1" with seed 1',
    '2026/11/11 20:07:03 1 a [INFO Client 1] [SCENE] Set Source [Берег реки]',
    '2026/11/11 20:08:00 1 a [INFO Client 1] Successfully allocated passive skill id: a, name: Урон чарами',
    '2026/11/11 20:08:10 1 a [INFO Client 1] Successfully allocated passive skill id: d, name: Мана',
]) + '\n'


START = {'id': 'start', 'name': 'До вознесения', 'nodes': [{'id': 'a'}, {'id': 'b'}]}     # первая версия как записана


class ServerTest(unittest.TestCase):
    """Сохранение версий через программу: план из частей, дерево лежит в файле билда; версии уходят вместе
    с остальными разделами билда (ключи tree и atlas запроса)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        (root / 'Client.txt').write_text(LOG, encoding='utf-8')
        (root / 'plan.json').write_text(json.dumps({'version': 2, 'route': 'route.json', 'build': 'build.json'}), encoding='utf-8')
        (root / 'route.json').write_text(json.dumps({'id': 'r', 'steps': [
            {'id': 'riverbank', 'zone': 'G1_1', 'name': 'Берег реки'}, {'id': 'clearfell', 'zone': 'G1_2', 'name': 'Клирфелл'}]},
            ensure_ascii=False), encoding='utf-8')
        self.build = root / 'build.json'
        self.build.write_bytes(build_text(TREE, '\r\n', STAGES).encode('utf-8'))
        (root / 'tree.json').write_text(json.dumps(GEO), encoding='utf-8')
        self.app = server.App(root / 'Client.txt', root / 'plan.json', root / 'runs', backup_dir=root / 'backup')
        self.app.tree_path = root / 'tree.json'
        with self.app.cond:
            self.app.load_plan()
            self.app.poll_log(initial=True)
            self.app.attach_run()
        if not self.app.catalog or not self.app.catalog.get('stats'):
            self.skipTest('каталог данных игры не собран')

    def tearDown(self):
        self.tmp.cleanup()

    def test_build_page_gets_every_version(self):
        tp = self.app.build_view()['treePlan']
        # версии: полный порядок узлов. Атрибута «по умолчанию» странице нет: у «Характеристики», которая
        # в файле опиралась на него («инт»), он записан явно
        self.assertEqual(tp['tree']['versions'], [{'id': 'start', 'name': 'До вознесения', 'nodes': [{'id': 'a'}, {'id': 'b', 'attr': 'int'}]},
                                                  {'id': 'maps', 'name': 'Карты', 'nodes': []}])
        self.assertNotIn('attr', tp['tree'])
        # названия узлов: из плана и из лога (узел «d» герой брал — игра его назвала)
        self.assertEqual(tp['tree']['names'], {'a': 'Урон чарами', 'b': 'Характеристика', 'd': 'Мана'})
        self.assertEqual(tp['atlas']['versions'], [])

    def test_route_page_only_views_the_tree(self):
        """Странице маршрута версии целиком не нужны: она показывает план текущего шага и то, что взято."""
        t = self.app.view()['tree']
        self.assertEqual((t['now'], [n['id'] for n in t['plan']], t['have']), ('start', ['a', 'b'], ['a', 'd']))
        # где герой сейчас — редактору плана, для выбора зоны шага: та же зона, что на странице забега
        self.assertEqual(self.app.now_zone()['code'], self.app.view()['zone']['code'])
        self.assertEqual([k for k in ('versions', 'names', 'attr') if k in t], [])
        # у узла «Характеристика» без своего атрибута — атрибут дерева по умолчанию
        self.assertEqual(t['plan'][1]['attr'], 'инт')

    def test_saved_version_lands_in_the_build_file(self):
        before = self.build.read_bytes().decode('utf-8')
        ok, problems = self.app.save_build({'tree': {'versions': [START, {'id': 'maps', 'name': 'Карты', 'nodes': [
            {'id': 'a'}, {'id': 'b', 'attr': 'str'}, {'id': 'd'}, {'id': 'e'}]}]}})
        self.assertEqual((ok, problems), (True, []))
        after = json.loads(self.build.read_text(encoding='utf-8'))
        self.assertEqual(after['tree']['phases'][1]['nodes'], [
            {'id': 'a', 'name': 'Урон чарами'}, {'id': 'b', 'name': 'Характеристика', 'kind': 'attribute', 'attr': 'str'},
            {'id': 'd', 'name': 'Мана'},        # название — из лога: в плане узла ещё не было
            {'id': 'e', 'name': 'Mana'}])       # игра этот узел не называла — английское из данных дерева
        self.assertEqual(after['tree']['phases'][0], json.loads(before)['tree']['phases'][0])    # другая версия цела
        self.assertEqual(after['goals'], [{'id': 'g1', 'title': 'Цель'}])
        self.assertEqual(len(list((Path(self.tmp.name) / 'backup').glob('build.build-*.json'))), 1)
        # план перечитан сразу: страница видит новую версию
        tp = self.app.build_view()['treePlan']['tree']
        self.assertEqual(tp['versions'][1]['nodes'], [{'id': 'a'}, {'id': 'b', 'attr': 'str'}, {'id': 'd'}, {'id': 'e'}])
        self.assertEqual(self.app.plan_problems, [])

    def test_saving_from_the_page_drops_the_default_and_keeps_the_meaning(self):
        """Страница записывает дерево так, как получила (у старых узлов атрибут уже явный), и с новым узлом
        «Характеристика» без выбора: поле attr у дерева из файла уходит, прежний узел остаётся с интеллектом,
        новый — пустой, и проверка гайда говорит о нём."""
        tp = self.app.build_view()['treePlan']['tree']
        ok, problems = self.app.save_build({'tree': {'versions': [
            tp['versions'][0], {'id': 'maps', 'name': 'Карты', 'nodes': [{'id': 'a'}, {'id': 'b'}]}]}})
        self.assertEqual((ok, problems), (True, []))
        tree = json.loads(self.build.read_text(encoding='utf-8'))['tree']
        self.assertNotIn('attr', tree)
        self.assertEqual([ph['nodes'][1] for ph in tree['phases']],
                         [{'id': 'b', 'name': 'Характеристика', 'kind': 'attribute', 'attr': 'int'},
                          {'id': 'b', 'name': 'Характеристика', 'kind': 'attribute'}])
        # странице маршрута: у прежнего узла — интеллект, как и было
        self.assertEqual(self.app.view()['tree']['plan'][1]['attr'], 'int')
        # страница получает то же, что записала: прежний узел с интеллектом, новый — пустой
        again = self.app.build_view()
        self.assertEqual([v['nodes'] for v in again['treePlan']['tree']['versions']],
                         [[{'id': 'a'}, {'id': 'b', 'attr': 'int'}], [{'id': 'a'}, {'id': 'b'}]])

    def test_versions_are_created_renamed_and_removed_as_a_whole_set(self):
        """Набор версий — дело билда: новая версия, прежняя переименована, лишняя убрана. Какая версия
        действует на шаге, решает этап билда — правка дерева этапов не трогает."""
        ok, problems = self.app.save_build({'tree': {'attr': 'str', 'versions': [
            {'id': 'start', 'name': 'Начало', 'nodes': [{'id': 'a'}, {'id': 'b'}]},
            {'id': 'maps', 'name': 'Карты', 'nodes': []},
            {'id': 'v2', 'name': 'К мельнику', 'nodes': [{'id': 'a'}, {'id': 'd'}]}]}})
        self.assertEqual((ok, problems), (True, []))
        data = json.loads(self.build.read_text(encoding='utf-8'))
        tree = data['tree']
        self.assertEqual((tree['attr'], [(p['id'], p['name'], len(p['nodes'])) for p in tree['phases']]),
                         ('str', [('start', 'Начало', 2), ('maps', 'Карты', 0), ('v2', 'К мельнику', 2)]))
        self.assertEqual(list(tree['phases'][2]), ['id', 'name', 'nodes'])
        self.assertEqual(data['stages'], STAGES)
        t = self.app.view()['tree']
        # герой на «Берегу реки»: действует версия первого этапа; новую версию пока не назвал никто
        self.assertEqual((t['now'], t['phase'], self.app.plan_problems), ('start', 'Начало', []))
        d = self.app.build_view()
        # (эта запись пришла «по-старому», с полем attr, — оно в файле осталось; странице оно отдано узлом)
        self.assertEqual([v['id'] for v in d['treePlan']['tree']['versions']], ['start', 'maps', 'v2'])
        self.assertEqual(d['treePlan']['tree']['versions'][0]['nodes'], [{'id': 'a'}, {'id': 'b', 'attr': 'str'}])
        self.assertEqual([(st['id'], st['tree']) for st in d['stages']], [('start', 'start'), ('late', 'maps')])     # «v2» не назвал никто
        # версию, которую назвал этап, из набора не убрать — отказ, файл цел
        before = self.build.read_bytes()
        ok, problems = self.app.save_build({'tree': {'versions': [
            {'id': 'start', 'name': 'Начало', 'nodes': []},
            {'id': 'v2', 'name': 'К мельнику', 'nodes': []}]}})
        self.assertEqual((ok, problems), (False, ['версию «maps» убрать нельзя: она действует на этапе «Поздно» — '
                                                  'сначала дайте этапу другую (вкладка «Этапы»)']))
        self.assertEqual(self.build.read_bytes(), before)
        # этап тем же запросом переведён на другую версию — прежнюю можно убрать, а новую этап называет сразу
        ok, problems = self.app.save_build({
            'tree': {'versions': [{'id': 'start', 'name': 'Начало', 'nodes': []}, {'id': 'v2', 'name': 'К мельнику', 'nodes': []}]},
            'stages': [STAGES[0], dict(STAGES[1], tree='v2')]})
        self.assertEqual((ok, problems), (True, []))
        data = json.loads(self.build.read_text(encoding='utf-8'))
        self.assertEqual(([p['id'] for p in data['tree']['phases']], data['stages']), (['start', 'v2'], [STAGES[0], dict(STAGES[1], tree='v2')]))
        # черновик, который не назвал ни один этап, убирается свободно; этапы при этом не трогаются
        ok, problems = self.app.save_build({'tree': {'versions': [
            {'id': 'start', 'name': 'Начало', 'nodes': []}, {'id': 'v2', 'name': 'К мельнику', 'nodes': []},
            {'id': 'v3', 'name': 'Черновик', 'nodes': [{'id': 'a'}]}]}})
        self.assertEqual((ok, problems), (True, []))
        ok, problems = self.app.save_build({'tree': {'versions': [
            {'id': 'start', 'name': 'Начало', 'nodes': []}, {'id': 'v2', 'name': 'К мельнику', 'nodes': []}]}})
        self.assertEqual((ok, problems), (True, []))
        data = json.loads(self.build.read_text(encoding='utf-8'))
        self.assertEqual(([p['id'] for p in data['tree']['phases']], data['stages']), (['start', 'v2'], [STAGES[0], dict(STAGES[1], tree='v2')]))
        # этап не может назвать версию, которой в присланном наборе нет
        ok, problems = self.app.save_build({'stages': [STAGES[0], dict(STAGES[1], tree='nope')]})
        self.assertEqual((ok, problems), (False, ['этап «Поздно»: версии дерева «nope» в билде нет']))

    def test_bad_version_changes_nothing(self):
        before = self.build.read_bytes()
        ok, problems = self.app.save_build({'tree': {'versions': [START, {'id': 'maps', 'name': 'Карты', 'nodes': [{'id': 'a'}, {'id': 'c'}]}]}})
        self.assertFalse(ok)
        self.assertIn('узел «c» стоит раньше своих соседей', problems[0])
        self.assertEqual(self.build.read_bytes(), before)
        self.assertFalse((Path(self.tmp.name) / 'backup').exists())
        self.assertEqual(self.app.save_build({'tree': {}}), (False, ['нет ни одной версии дерева']))
        self.assertEqual(self.app.save_build({'tree': 'не набор'}), (False, ['дерево: нужен набор версий']))
        # проверка гайда с несохранённым деревом: плохая версия — замечанием, ничего не пишется
        found = self.app.check_build({'tree': {'versions': [START, {'id': 'maps', 'name': 'Карты', 'nodes': [{'id': 'a'}, {'id': 'c'}]}]}})
        self.assertIn('узел «c» стоит раньше своих соседей', ' '.join(f['text'] for f in found if f['kind'] == 'plan'))
        self.assertEqual(self.build.read_bytes(), before)

    def test_atlas_is_saved_as_a_section_of_its_own(self):
        """Дерево атласа — второй раздел того же файла билда. Сначала его в файле нет: первая запись
        создаёт раздел сразу за деревом героя; первую версию страница тем же запросом называет в первом
        этапе билда — иначе её план нигде бы не действовал. Остальной текст не меняется."""
        (Path(self.tmp.name) / 'atlas.json').write_text(json.dumps(ATLAS_GEO, ensure_ascii=False), encoding='utf-8')
        self.app.atlas_path = Path(self.tmp.name) / 'atlas.json'
        a = self.app.view()['atlas']
        self.assertEqual((a['plan'], a['now'], self.app.build_view()['treePlan']['atlas']['versions']), ([], None, []))
        before = self.build.read_bytes().decode('utf-8')
        ok, problems = self.app.save_build({'atlas': {'attr': 'str', 'versions': [
            {'id': 'a1', 'name': 'Атлас', 'nodes': [{'id': 'AtlasBreachSmall1'}, {'id': 'AtlasGenericSmall1'},
                                                   {'id': 'AtlasGenericNotable1'}]}]},
            'stages': [dict(STAGES[0], atlas='a1'), STAGES[1]]})
        self.assertEqual((ok, problems), (True, []))
        text = self.build.read_bytes().decode('utf-8')
        after = json.loads(text)
        self.assertEqual(list(after), ['version', 'title', 'stages', 'tree', 'atlas', 'goals'])
        # первая версия атласа встала на первый этап; второй этап и версии дерева героя не тронуты
        self.assertEqual(after['stages'], [dict(STAGES[0], atlas='a1'), STAGES[1]])
        self.assertEqual(after['atlas'], {'phases': [{'id': 'a1', 'name': 'Атлас', 'nodes': [
            {'id': 'AtlasBreachSmall1', 'name': 'Объём крови улья'},                          # русское имя — из слоя ru
            {'id': 'AtlasGenericSmall1', 'name': 'Essence Chance'},                           # перевода нет — английское
            {'id': 'AtlasGenericNotable1', 'name': 'Растущая угроза', 'kind': 'notable'}]}]})
        rest = lambda d: {k: v for k, v in d.items() if k not in ('atlas', 'stages')}       # noqa: E731
        self.assertEqual(rest(after), rest(json.loads(before)))                               # дерево героя и цели целы
        self.assertEqual(text.count('\r\n'), text.count('\n'))                                # окончания строк прежние
        self.assertEqual(len(list((Path(self.tmp.name) / 'backup').glob('build.build-*.json'))), 1)   # одна запись — одна копия
        # план перечитан: страница видит версию; атрибут по умолчанию к атласу не относится
        a = self.app.view()['atlas']
        self.assertEqual((a['now'], a['phase'], [n['id'] for n in a['plan']], self.app.plan_problems),
                         ('a1', 'Атлас', ['AtlasBreachSmall1', 'AtlasGenericSmall1', 'AtlasGenericNotable1'], []))
        self.assertNotIn('attr', after['atlas'])
        self.assertEqual(after['tree']['attr'], 'инт')
        # вторая запись правит уже существующий раздел; этапы она больше не трогает: новая версия — черновик
        ok, problems = self.app.save_build({'atlas': {'versions': [
            {'id': 'a1', 'name': 'Атлас', 'nodes': [{'id': 'AtlasGenericSmall1'}]},
            {'id': 'v2', 'name': 'Дальше', 'nodes': [{'id': 'AtlasGenericSmall1'}, {'id': 'AtlasGenericNotable1'}]}]}})
        self.assertEqual((ok, problems), (True, []))
        after = json.loads(self.build.read_text(encoding='utf-8'))
        self.assertEqual([(p['id'], len(p['nodes'])) for p in after['atlas']['phases']], [('a1', 1), ('v2', 2)])
        self.assertEqual(list(after), ['version', 'title', 'stages', 'tree', 'atlas', 'goals'])
        self.assertEqual(after['stages'], [dict(STAGES[0], atlas='a1'), STAGES[1]])
        d = self.app.build_view()
        self.assertEqual([(v['id'], len(v['nodes'])) for v in d['treePlan']['atlas']['versions']], [('a1', 1), ('v2', 2)])
        self.assertEqual([st.get('atlas') for st in d['stages']], ['a1', None])
        # узел с выбором: названный вариант пишется в файл, доходит до страницы «Билд» и до страницы забега
        ok, problems = self.app.save_build({'atlas': {'versions': [
            {'id': 'a1', 'name': 'Атлас', 'nodes': [{'id': 'AtlasGenericSmall1'}, {'id': 'AtlasGenericNotable1'},
                                                    {'id': 'AtlasGenericChoice1', 'opt': 2}]},
            {'id': 'v2', 'name': 'Дальше', 'nodes': []}]}})
        self.assertEqual((ok, problems), (True, []))
        self.assertEqual(json.loads(self.build.read_text(encoding='utf-8'))['atlas']['phases'][0]['nodes'][2],
                         {'id': 'AtlasGenericChoice1', 'name': 'Знание пустыни', 'kind': 'keystone', 'opt': 2})
        self.assertEqual(self.app.build_view()['treePlan']['atlas']['versions'][0]['nodes'][2], {'id': 'AtlasGenericChoice1', 'opt': 2})
        self.assertEqual([n.get('opt') for n in self.app.view()['atlas']['plan']], [None, None, 2])
        ok, problems = self.app.save_build({'atlas': {'versions': [
            {'id': 'a1', 'name': 'Атлас', 'nodes': [{'id': 'AtlasGenericSmall1', 'opt': 1}]}, {'id': 'v2', 'name': 'Дальше', 'nodes': []}]}})
        self.assertEqual((ok, 'только у узла атласа с выбором' in problems[0]), (False, True))
        # узел чужого дерева без пути от своего корня — отказ; узел дерева героя в атлас не идёт
        self.assertIn('узел «AtlasGenericNotable1» стоит раньше своих соседей',
                      self.app.save_build({'atlas': {'versions': [{'id': 'a1', 'name': 'Атлас', 'from': None,
                                                                   'nodes': [{'id': 'AtlasGenericNotable1'}]}]}})[1][0])
        self.assertEqual(self.app.save_build({'atlas': {'versions': [{'id': 'a1', 'name': 'Атлас', 'nodes': [{'id': 'a'}]},
                                                                    {'id': 'v2', 'name': 'Дальше', 'nodes': []}]}})[1],
                         ['версия «Атлас»: узла «a» нет в дереве'])


# Маленький атлас: два дерева со своими корнями. Основное: корень — малый — значимый — узел с выбором;
# Разлом: корень — малый.
ATLAS_GEO = {
    'tree': 'Atlas',
    'trees': [{'id': 'AtlasGenericStart', 'key': 'Atlas', 'name': 'Атлас'}, {'id': 'AtlasBreachStart', 'key': 'Breach', 'name': 'Разлом'}],
    'nodes': [['AtlasGenericStart', 0, 0, 5, '', 0], ['AtlasGenericSmall1', 0, -100, 0, 'Essence Chance', 0],
              ['AtlasGenericNotable1', 0, -200, 2, 'Rising Danger', 0],
              ['AtlasBreachStart', 900, 0, 5, '', 1], ['AtlasBreachSmall1', 900, -100, 0, 'Hiveblood Quantity', 1],
              ['AtlasGenericChoice1', 0, -300, 3, 'Desert Lore', 0]],
    'edges': [[0, 1], [1, 2], [3, 4], [2, 5]],
    'ru': {'Rising Danger': 'Растущая угроза', 'Hiveblood Quantity': 'Объём крови улья', 'Desert Lore': 'Знание пустыни'},
}


class ForestTest(unittest.TestCase):
    """Атлас — несколько деревьев в одном файле: узел примыкает к взятому раньше или к корню своего дерева."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        path = Path(self.tmp.name) / 'atlas.json'
        path.write_text(json.dumps(ATLAS_GEO, ensure_ascii=False), encoding='utf-8')
        self.geo = treeplan.load_geo(path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_any_root_starts_a_branch(self):
        self.assertTrue(self.geo['forest'])
        self.assertEqual(self.geo['name']['AtlasBreachSmall1'], 'Объём крови улья')
        ok = [{'id': 'a1', 'name': 'Атлас', 'from': None,
               'nodes': [{'id': 'AtlasGenericSmall1'}, {'id': 'AtlasBreachSmall1'}, {'id': 'AtlasGenericNotable1'}]}]
        versions, problems = treeplan.check_all(ok, {}, self.geo)
        self.assertEqual((problems, [n['id'] for n in versions[0]['nodes']]),
                         ([], ['AtlasGenericSmall1', 'AtlasBreachSmall1', 'AtlasGenericNotable1']))
        # корень — не узел плана; у узла атласа атрибута не бывает
        bad = lambda nodes: treeplan.check_all([dict(ok[0], nodes=nodes)], {}, self.geo)[1]   # noqa: E731
        self.assertEqual(bad([{'id': 'AtlasBreachStart'}]), ['версия «Атлас»: узла «AtlasBreachStart» нет в дереве'])
        self.assertIn('только у узла «Характеристика»', bad([{'id': 'AtlasGenericSmall1', 'attr': 'int'}])[0])

    def test_a_choice_node_keeps_the_number_of_the_picked_option(self):
        """У узла атласа с выбором план называет вариант — номер с единицы (поле opt). Номер бывает только у
        такого узла и не больше числа его вариантов, когда оно известно; у дерева героя вариантов нет."""
        path = [{'id': 'AtlasGenericSmall1'}, {'id': 'AtlasGenericNotable1'}]
        ok = lambda nodes, geo: treeplan.check_all([{'id': 'a1', 'name': 'Атлас', 'nodes': nodes}], {}, geo)   # noqa: E731
        got, problems = ok(path + [{'id': 'AtlasGenericChoice1', 'opt': 2}], self.geo)
        self.assertEqual((got[0]['nodes'][2], problems), ({'id': 'AtlasGenericChoice1', 'opt': 2}, []))
        self.assertEqual(treeplan.records(got[0]['nodes'], {}, self.geo)[2],
                         {'id': 'AtlasGenericChoice1', 'name': 'Знание пустыни', 'kind': 'keystone', 'opt': 2})
        # узел без названного варианта — как раньше
        self.assertEqual(ok(path + [{'id': 'AtlasGenericChoice1'}], self.geo)[0][0]['nodes'][2], {'id': 'AtlasGenericChoice1'})
        for bad in (path[:1] + [{'id': 'AtlasGenericNotable1', 'opt': 1}], path + [{'id': 'AtlasGenericChoice1', 'opt': 0}],
                    path + [{'id': 'AtlasGenericChoice1', 'opt': '2'}], path + [{'id': 'AtlasGenericChoice1', 'opt': True}]):
            self.assertIn('только у узла атласа с выбором', ok(bad, self.geo)[1][0])
        # число вариантов узла известно — больше него нельзя
        counted = dict(self.geo, opts={'AtlasGenericChoice1': 3})
        self.assertEqual(ok(path + [{'id': 'AtlasGenericChoice1', 'opt': 3}], counted)[1], [])
        self.assertIn('номер с единицы до 3', ok(path + [{'id': 'AtlasGenericChoice1', 'opt': 4}], counted)[1][0])
        # странице узлы отдаются с номером варианта; мусор вместо номера отброшен
        self.assertEqual(treeplan.with_default([{'id': 'AtlasGenericChoice1', 'kind': 'keystone', 'opt': 2}, {'id': 'x', 'opt': 'два'}], None),
                         [{'id': 'AtlasGenericChoice1', 'opt': 2}, {'id': 'x'}])

    def test_one_tree_still_needs_its_first_node_at_the_start(self):
        # у дерева героя правило прежнее: к старту класса примыкает только первый узел версии
        path = Path(self.tmp.name) / 'tree.json'
        path.write_text(json.dumps(GEO), encoding='utf-8')
        geo = treeplan.load_geo(path)
        self.assertFalse(geo['forest'])
        problems = treeplan.check([{'id': 'start', 'nodes': [{'id': 'a'}, {'id': 'z'}]}], TREE, geo)[1]
        self.assertEqual(problems, ['версия «start»: узел «z» стоит раньше своих соседей — такой порядок в игре не пройти'])

    def test_new_section_goes_after_the_tree_or_to_the_end(self):
        atlas = {'phases': [{'id': 'a1', 'name': 'Атлас', 'nodes': [{'id': 'AtlasGenericSmall1', 'name': 'Essence Chance'}]}]}
        for eol in ('\n', '\r\n'):
            text = build_text(TREE, eol)
            out = treeplan.splice(text, atlas, 'atlas')
            self.assertEqual(list(json.loads(out)), ['version', 'title', 'tree', 'atlas', 'goals'])
            self.assertEqual(json.loads(out)['atlas'], atlas)
            self.assertEqual(treeplan.splice(out, atlas, 'atlas'), out)              # повторная запись — знак в знак
            self.assertEqual(treeplan.splice(out, TREE), out)                        # дерево героя рядом не задето
            self.assertIn('  },' + eol + '  "atlas": {' + eol + '    "phases": [', out)
            # дерево — последний раздел файла: ему достаётся запятая, атлас встаёт после него
            last = eol.join(['{', '  "title": "Проба",'] + treeplan.render(TREE) + ['}', ''])
            out = treeplan.splice(last, atlas, 'atlas')
            self.assertEqual((list(json.loads(out)), json.loads(out)['tree']), (['title', 'tree', 'atlas'], TREE))
            # дерева героя в файле нет вовсе: раздел атласа встаёт последним
            bare = eol.join(['{', '  "title": "Проба",', '  "goals": [', '    {"id": "g1"}', '  ]', '}', ''])
            out = treeplan.splice(bare, atlas, 'atlas')
            self.assertEqual((list(json.loads(out)), json.loads(out)['goals']), (['title', 'goals', 'atlas'], [{'id': 'g1'}]))
            self.assertTrue(out.endswith('  }' + eol + '}' + eol))
        with self.assertRaises(ValueError):
            treeplan.splice(json.dumps({'atlas': atlas, 'goals': []}), atlas, 'atlas')   # раздел есть, но записан в строку

    def test_the_real_atlas_data_reads(self):
        """Настоящий файл атласа: семь деревьев, у узлов русские названия, порядок героя из лога проходит проверку."""
        path = ROOT / 'planner' / 'static' / 'atlas.json'
        if not path.exists():
            self.skipTest('нет файла атласа')
        geo = treeplan.load_geo(path)
        raw = json.loads(path.read_text(encoding='utf-8'))
        self.assertEqual([t['name'] for t in raw['trees']], ['Атлас', 'Ритуал', 'Разлом', 'Делириум', 'Бездна', 'Храм', 'Экспедиция'])
        self.assertEqual(sum(1 for n in raw['nodes'] if n[3] == 5), 7)
        self.assertEqual(geo['name']['AtlasDeliriumNotable17'], 'Тебе меня больше не напугать!')
        # так брал узлы герой: основное дерево, потом Разлом, потом Делириум
        taken = ['AtlasGenericSmall71', 'AtlasEssenceNotable2', 'AtlasGenericSmall17', 'AtlasEssenceNotable7', 'AtlasEssenceNotable11',
                 'AtlasBreachSmall16', 'AtlasBreachNotable16', 'AtlasDeliriumSmall8', 'AtlasDeliriumNotable5']
        versions, problems = treeplan.check_all([{'id': 'a1', 'name': 'Атлас', 'nodes': [{'id': i} for i in taken]}], {}, geo)
        self.assertEqual(problems, [])


class AtlasGeoTest(unittest.TestCase):
    def test_orbits_become_coordinates_and_arcs(self):
        """Узел стоит на орбите своей группы; связь с номером орбиты — дуга этого радиуса, знак говорит,
        с какой стороны её центр. «Мастерство» (картинка в центре группы) в карту не идёт."""
        import atlasgeo
        p = lambda h, i, **kw: dict({'hash': h, 'id': i, 'name': '', 'stat_text': []}, **kw)   # noqa: E731
        data = {
            'orbit_radii': [0, 100, 200], 'skills_per_orbit': [1, 4, 8], 'roots': [1, 5],
            'passives': {'1': p(1, 'AtlasGenericStart', is_atlas_root=True),
                         '2': p(2, 'AtlasGenericSmall1', name='Essence Chance', stat_text=['10% increased chance of [Essence|Essences]']),
                         '3': p(3, 'AtlasGenericNotable1', name='Rising Danger', is_notable=True),
                         '4': p(4, 'AtlasGenericMastery1', is_icon_only=True),
                         '5': p(5, 'AtlasBreachStart', is_atlas_root=True),
                         '6': p(6, 'AtlasBreachKey1', name='Breeding Program', is_keystone=True, atlas_subtree={'id': 'Breach'})},
            'groups': [
                {'x': 0, 'y': 0, 'passives': [
                    {'hash': 1, 'radius': 0, 'position_clockwise': 0, 'connections': [2], 'splines': [0]},
                    {'hash': 2, 'radius': 1, 'position_clockwise': 0, 'connections': [3], 'splines': [1]},   # (0, -100)
                    {'hash': 3, 'radius': 1, 'position_clockwise': 1, 'connections': [], 'splines': []},     # (100, 0)
                    {'hash': 4, 'radius': 0, 'position_clockwise': 0, 'connections': [], 'splines': []}]},
                {'x': 1000, 'y': 0, 'passives': [
                    {'hash': 5, 'radius': 0, 'position_clockwise': 0, 'connections': [6], 'splines': [2147483647]},
                    {'hash': 6, 'radius': 2, 'position_clockwise': 4, 'connections': [], 'splines': []}]}]}       # (1000, 200)
        names = {'trees': {'AtlasBreachStart': 'Разлом'}, 'names': {'Rising Danger': 'Растущая угроза', 'Essence Chance': 'Essence Chance'}}
        geo = atlasgeo.build(data, names)
        self.assertEqual(geo['trees'], [{'id': 'AtlasGenericStart', 'key': 'Atlas', 'name': 'Atlas'},
                                        {'id': 'AtlasBreachStart', 'key': 'Breach', 'name': 'Разлом'}])
        at = {n[0]: n for n in geo['nodes']}
        self.assertEqual(sorted(at), ['AtlasBreachKey1', 'AtlasBreachStart', 'AtlasGenericNotable1', 'AtlasGenericSmall1', 'AtlasGenericStart'])
        self.assertEqual((at['AtlasGenericSmall1'][1:], at['AtlasGenericNotable1'][1:], at['AtlasBreachKey1'][1:]),
                         ([0, -100, 0, 'Essence Chance', 0], [100, 0, 2, 'Rising Danger', 0], [1000, 200, 3, 'Breeding Program', 1]))
        self.assertEqual((at['AtlasGenericStart'][3], at['AtlasBreachStart'][5]), (5, 1))
        ids = [n[0] for n in geo['nodes']]
        edges = {(ids[e[0]], ids[e[1]]): e[2:] for e in geo['edges']}
        self.assertEqual(len(edges), 3)
        # дуга радиуса 100 между (0, −100) и (100, 0), путь идёт вправо-вниз: при знаке «плюс» центр слева
        # от пути (на экране — выше и правее), при «минусе» — справа (здесь это центр группы)
        arc = edges.get(('AtlasGenericSmall1', 'AtlasGenericNotable1')) or edges.get(('AtlasGenericNotable1', 'AtlasGenericSmall1'))
        self.assertEqual(arc, [100, -100])
        self.assertEqual([len(v) for k, v in edges.items() if 'Start' in k[0] or 'Start' in k[1]], [0, 0])   # остальные — прямые
        other = atlasgeo.arc_centre((0, -100), (100, 0), 100, -1)
        self.assertEqual((round(other[0], 6), round(other[1], 6)), (0.0, 0.0))
        self.assertEqual(geo['ru'], {'Rising Danger': 'Растущая угроза'})                                    # только настоящие переводы
        # текста и условий словами клиента нет — английский текст выгрузки, условий ни у кого
        self.assertEqual(atlasgeo.stats(data), {'AtlasGenericSmall1': {'text': ['10% increased chance of Essences']}})
        self.assertEqual((geo['conds'], [len(n) for n in geo['nodes']]), ([], [6] * 5))

    def test_conditions_are_exact_or_absent_never_guessed(self):
        """Условия узла — словами клиента из atlas-ru.json. Название носит один узел — условия из списка
        точные. Малый узел с повторяющимся названием стоит в разных разделах дерева: его условия берутся
        только если они названы для него самого; иначе в основном дереве данных нет (null), а в дереве
        механики, где все перечисленные такие узлы без условий, — условий нет."""
        import atlasgeo
        p = lambda h, i, name, **kw: dict({'hash': h, 'id': i, 'name': name, 'stat_text': []}, **kw)   # noqa: E731
        node = lambda h, at, to=(): {'hash': h, 'radius': 0, 'position_clockwise': 0, 'connections': list(to),   # noqa: E731
                                     'splines': [0] * len(to), 'at': at}
        chain = [(1, [2]), (2, [3]), (3, [4]), (4, [5]), (5, [6]), (6, [7]), (7, []), (8, [9]), (9, [10]), (10, [])]
        data = {
            'orbit_radii': [0], 'skills_per_orbit': [1], 'roots': [1, 8],
            'passives': {
                '1': p(1, 'AtlasGenericStart', '', is_atlas_root=True),
                '2': p(2, 'AtlasGenericSmall1', 'Essence Chance', stat_text=['40% increased chance of [Essence|Essences]']),
                '3': p(3, 'AtlasEssence4', 'Essence Chance', stat_text=['40% increased chance of [Essence|Essences]']),
                '4': p(4, 'AtlasEssence7', 'Essence Chance', stat_text=['40% increased chance of [Essence|Essences]']),
                '5': p(5, 'AtlasEssenceKey1', 'Essence Dowsing', is_keystone=True,
                       stat_text=['100% increased chance to find certain [Essence|Essence] types']),
                '6': p(6, 'AtlasRitualNotable1', 'Mysterious Rites', is_notable=True,
                       stat_text=["[ContainsRitual|Rituals] have a 8% chance to be the Queen's Ritual\nThe Queen's Ritual has 10 additional [Omen|Omens]"]),
                '7': p(7, 'AtlasBreachNotable1', 'Flesh Flower', is_notable=True,
                       stat_text=['Killing Vruun will allow you to return his Head\nto unlock the Grasping Orchid']),
                '8': p(8, 'AtlasBreachStart', '', is_atlas_root=True),
                '9': p(9, 'AtlasBreachSmall1', 'Hiveblood Quantity', atlas_subtree={'id': 'Breach'}),
                '10': p(10, 'AtlasBreachSmall2', 'Hiveblood Quantity', atlas_subtree={'id': 'Breach'})},
            'groups': [{'x': 100 * h, 'y': 0, 'passives': [{k: v for k, v in node(h, 0, to).items() if k != 'at'}]} for h, to in chain]}
        gate = ['Действует на области 70+ уровня', 'Требует завершения Восточных или Западных ворот']
        names = {'names': {}, 'nodes': {
            # в списке у повторяющегося названия стоят условия одного из узлов — к остальным они не относятся
            'Essence Chance': {'when': ['Действует на области 75+ уровня', 'Требует завершения Горящего монолита'], 'count': 3,
                               'text': ['40% увеличение шанса появления Сущностей'], 'ids': {'AtlasGenericSmall1': [], 'AtlasEssence4': gate}},
            'Essence Dowsing': {'when': [], 'count': 1, 'text': [
                '100% увеличение шанса нахождения Сущностей определенного типа',
                'Большая сущность тела', 'map essence type chance +% [20]', 'Большая сущность разума', 'map essence type chance +% [20]']},
            'Mysterious Rites': {'when': ['Требует победы над верховным боссом Ритуала'], 'count': 1,
                                 'text': ['Ритуалы с 8% шансом могут оказаться Ритуалами Царицы']},
            'Flesh Flower': {'when': [], 'count': 1, 'text': ['Убийство Рууна позволит вернуть его голову к Древу зарождения']},
            'Hiveblood Quantity': {'when': [], 'count': 2, 'text': ['5% увеличение количества находимой крови улья'], 'ids': {'AtlasBreachSmall1': []}}}}
        geo = atlasgeo.build(data, names)
        when = {n[0]: (None if len(n) > 6 and n[6] is None else [geo['conds'][i] for i in (n[6] if len(n) > 6 else [])]) for n in geo['nodes']}
        self.assertEqual(when['AtlasGenericSmall1'], [])              # назван на странице своего названия: условий нет
        self.assertEqual(when['AtlasEssence4'], gate)                 # назван: свои условия
        self.assertIsNone(when['AtlasEssence7'])                      # не назван, основное дерево: данных нет
        self.assertEqual(when['AtlasRitualNotable1'], ['Требует победы над верховным боссом Ритуала'])
        self.assertEqual((when['AtlasBreachSmall1'], when['AtlasBreachSmall2']), ([], []))   # дерево механики: малые без условий
        self.assertEqual(sorted(geo['conds']), sorted(gate + ['Требует победы над верховным боссом Ритуала']))
        text = atlasgeo.stats(data, names)
        # узел с выбором: его строка и варианты; повторённая у каждого варианта служебная строка убрана
        self.assertEqual(text['AtlasEssenceKey1'], {'text': ['100% увеличение шанса нахождения Сущностей определенного типа'],
                                                    'opts': ['Большая сущность тела', 'Большая сущность разума']})
        self.assertEqual(text['AtlasEssence7'], {'text': ['40% увеличение шанса появления Сущностей']})
        # карточка короче выгрузки: строки, которых в ней нет, дописаны по-английски…
        self.assertEqual(text['AtlasRitualNotable1'], {'text': ['Ритуалы с 8% шансом могут оказаться Ритуалами Царицы',
                                                                "The Queen's Ritual has 10 additional Omens"]})
        # …а перенос одной английской фразы на вторую строку потерей не считается
        self.assertEqual(text['AtlasBreachNotable1'], {'text': ['Убийство Рууна позволит вернуть его голову к Древу зарождения']})


LIST_RU = '''
<div class="tab-pane"><div class="row">
<div class="col"><div class="d-flex border-top rounded"><div class="flex-shrink-0">
  <div class="passive-icon-container passive-icon-type__atlas_keystone "><div class="passive-icon-frame"></div>
  <a href="/ru/Essence_Dowsing"><img loading="lazy" src="x.webp"></a></div></div>
 <div class="flex-grow-1 ms-2"><div><a class="PassiveSkills" data-hover="h" href="Essence_Dowsing">Сущностное лозоходство</a></div>
 <div class="separator"></div>
 <div class="implicitMod"><span class="mod-value">100</span>% увеличение шанса нахождения <a class="KeywordPopups" href="Essence">Сущностей</a> определенного типа</div>
 <div class="separator"></div>
 <div class="explicitMod"><ul><li>Большая сущность тела</li><li>Большая сущность разума<br>map x +% [20]</li></ul></div></div></div></div>
<div class="col"><div class="d-flex border-top rounded"><div class="flex-shrink-0">
  <div class="passive-icon-container passive-icon-type__atlas_basic "><a href="/ru/Essence_Chance"><img src="y.webp"></a></div></div>
 <div class="flex-grow-1 ms-2"><div><a class="PassiveSkills" href="Essence_Chance">Шанс появления Сущностей</a></div>
 <div class="property">Действует на области<span style="color:red"> <span class="colourDefault">75</span>+ уровня</span></div>
 <div class="property"><span class="colourDefault">Требует завершения Горящего монолита</span></div>
 <div class="property">SubTree: Breach</div><div class="property">Количество: 9</div>
 <div class="implicitMod"><span class="mod-value">40</span>% увеличение шанса появления Сущностей</div></div></div></div>
</div></div>
<div class="footer"><a class="PassiveSkills" href="Elsewhere">Чужая ссылка</a><div class="property">не карточка</div></div>
'''
LIST_EN = LIST_RU.replace('Сущностное лозоходство', 'Essence Dowsing').replace('Шанс появления Сущностей', 'Essence Chance')
NAME_PAGE = '''
<div class="card"><div class="property">Количество: 9</div><div class="implicitMod">40% увеличение шанса появления Сущностей</div>
 <table><tr><td>ID</td><td>AtlasGenericSmall17</td></tr><tr><td>Icon</td><td></td></tr><tr><td>Tags</td><td>isUsed: true</td></tr></table></div>
<div class="card"><div class="property">Действует на области<span> <span>70</span>+ уровня</span></div>
 <div class="property">Требует завершения Восточных или Западных ворот</div><div class="property">Количество: 9</div>
 <table><tr><td>ID</td><td>AtlasEssence4_</td></tr></table></div>
'''


class AtlasLangTest(unittest.TestCase):
    """Тексты атласа на языке страницы — словами игры: строки узла — описанием свойства атласа, варианты выбора (они
    известны только по-русски, из карточек poe2db) — тем же описанием с русского, условия и названия деревьев —
    строками интерфейса игры."""

    def test_ui_template(self):
        import atlasgeo
        self.assertEqual(atlasgeo.ui_template('Applies to <rgb(219,217,206)>{{Level {0}+}} Areas'), 'Applies to Level {0}+ Areas')
        self.assertEqual(atlasgeo.ui_template('Действует на области <rgb(219,217,206)>{{{0}+ уровня}}'),
                         'Действует на области {0}+ уровня')

    def test_texts_in_page_languages(self):
        import atlasgeo
        csd = ('description\r\n\t1 dummy_display_expedition_explosive_bonus_selector\r\n\t1\r\n'
               '\t\t# "Improve [ContainsExpedition|Explosives]"\r\n'
               '\tlang "German"\r\n\t1\r\n\t\t# "Verbessert Sprengstoff"\r\n'
               '\tlang "Russian"\r\n\t1\r\n\t\t# "Улучшает взрывчатку"\r\n'
               'description\r\n\t1 dummy_display_expedition_explosive_wait\r\n\t1\r\n'
               '\t\t# "Explosives only wait for {0}% of Monsters"\r\n'
               '\tlang "German"\r\n\t1\r\n\t\t# "Sprengstoff wartet nur auf {0}% der Monster"\r\n'
               '\tlang "Russian"\r\n\t1\r\n\t\t# "Заряды ждут только {0}% монстров"\r\n'
               'description\r\n\t1 dummy_display_abyss_faction_amanamu\r\n\t1\r\n\t\t# "Amanamu"\r\n'
               '\tlang "Russian"\r\n\t1\r\n\t\t# "Аманаму"\r\n')
        descs = treegeo.parse_descriptions(csd)
        data = {'passives': {'1': {'id': 'K1', 'name': 'Strategic Advantage', 'is_keystone': True,
                                   'stat_text': ['Improve [ContainsExpedition|Explosives]']}}}
        names = {'nodes': {'Strategic Advantage': {'text': ['Улучшает взрывчатку', 'Заряды ждут только 50% монстров', 'Аманаму']}}}
        de, counts = atlasgeo.lang_texts(data, names, 'de', treegeo.desc_translator(descs, 'de'),
                                         treegeo.desc_translator(descs, 'de', source='ru'))
        # у имени фракции немецкой строки нет — игра пишет его по-английски
        self.assertEqual(de, {'K1': {'text': ['Verbessert Sprengstoff'],
                                     'opts': ['Sprengstoff wartet nur auf 50% der Monster', 'Amanamu']}})
        self.assertEqual(counts, [1, 1, 2, 2])
        en, _ = atlasgeo.lang_texts(data, names, 'en', None, treegeo.desc_translator(descs, 'en', source='ru'))
        self.assertEqual(en['K1'], {'text': ['Improve Explosives'], 'opts': ['Explosives only wait for 50% of Monsters', 'Amanamu']})
        ru, _ = atlasgeo.lang_texts(data, names, 'ru', treegeo.desc_translator(descs, 'ru'), None)
        self.assertEqual(ru['K1'], {'text': ['Улучшает взрывчатку'], 'opts': ['Заряды ждут только 50% монстров', 'Аманаму']})

    def test_tree_names(self):
        import atlasgeo
        ui = {'columns': {'Id': ['A', 'B'], 'Text': {'en': ['Breach', 'Atlas'], 'ru': ['Разлом', 'Атлас'],
                                                    'ja': ['ブリーチ', 'アトラス']}}}
        trees = [{'id': 'r1', 'key': 'Breach', 'name': 'Разлом'}, {'id': 'r2', 'key': 'Ritual', 'name': 'Ритуал'}]
        names = atlasgeo.tree_names(trees, ui)
        self.assertEqual((names['ja'], names['en'], names['de']), (['ブリーチ', 'Ritual'], ['Breach', 'Ritual'], ['Breach', 'Ritual']))
        self.assertNotIn('ru', names)                     # по-русски — названия карточек, как были

    def test_saved_atlas_descriptions(self):
        """На сохранённых источниках каталога: строка ключевого узла и условие — словами игры."""
        import atlasgeo
        sources = ROOT / 'catalog' / 'sources'
        try:
            base = sources / (sources / 'current.txt').read_text(encoding='utf-8').strip()
        except OSError:
            self.skipTest('нет источников каталога')
        descs, conds, ui = atlasgeo.read_texts(base)
        if not descs:
            self.skipTest('нет описаний свойств атласа')
        de = treegeo.desc_translator(descs, 'de')
        self.assertEqual(de('Improve Explosives used within Expeditions and Grand Expeditions'),
                         ['Verbessert Sprengstoff, der bei Expeditionen und Großen Expeditionen benutzt wird'])
        en = treegeo.desc_translator(conds, 'en', source='ru')
        self.assertEqual(en('Требует активации большого зеркала'), ['Requires activating a Grand Mirror'])
        self.assertEqual(en('Действует на области 70+ уровня'), ['Applies to Level 70+ Areas'])


class AtlasNamesTest(unittest.TestCase):
    """Разбор страниц открытой базы: карточки узлов в списке и узлы на странице одного названия."""

    def setUp(self):
        sys.path.insert(0, str(ROOT / 'catalog'))
        import fetch_atlas_names
        self.fan = fetch_atlas_names

    def test_cards_give_name_kind_conditions_and_text(self):
        cards = self.fan.cards(LIST_RU)
        self.assertEqual([(c['href'], c['name'], c['kind']) for c in cards],
                         [('Essence_Dowsing', 'Сущностное лозоходство', 'keystone'), ('Essence_Chance', 'Шанс появления Сущностей', 'basic')])
        # пункты списка и переносы — отдельные строки; ссылки и числа внутри строки остаются её текстом
        self.assertEqual(cards[0]['text'], ['100% увеличение шанса нахождения Сущностей определенного типа',
                                            'Большая сущность тела', 'Большая сущность разума', 'map x +% [20]'])
        self.assertEqual(cards[1]['props'], ['Действует на области 75+ уровня', 'Требует завершения Горящего монолита',
                                             'SubTree: Breach', 'Количество: 9'])

    def test_two_languages_pair_by_page_address(self):
        names, nodes, hrefs = self.fan.pair(LIST_EN, LIST_RU)
        self.assertEqual(names, {'Essence Dowsing': 'Сущностное лозоходство', 'Essence Chance': 'Шанс появления Сущностей'})
        self.assertEqual(hrefs['Essence Chance'], 'Essence_Chance')
        # в условия идут только «Действует…» и «Требует…»; служебные строки — нет; «Количество» — отдельным полем
        self.assertEqual(nodes['Essence Chance'], {'when': ['Действует на области 75+ уровня', 'Требует завершения Горящего монолита'],
                                                   'text': ['40% увеличение шанса появления Сущностей'], 'count': 9})
        self.assertEqual((nodes['Essence Dowsing']['when'], nodes['Essence Dowsing']['count']), ([], 1))
        with self.assertRaises(ValueError):
            self.fan.pair(LIST_EN, LIST_RU.replace('href="Essence_Chance"', 'href="Other_Node"'))   # страницы разошлись

    def test_name_page_lists_each_node_with_its_own_conditions(self):
        self.assertEqual(self.fan.variants(NAME_PAGE), {
            'AtlasGenericSmall17': [],
            'AtlasEssence4_': ['Действует на области 70+ уровня', 'Требует завершения Восточных или Западных ворот']})


if __name__ == '__main__':
    unittest.main()
