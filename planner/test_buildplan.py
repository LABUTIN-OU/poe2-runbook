# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Sergei Labutin
# Additional terms under GPL-3.0 section 7: see NOTICE.md
"""Правка билда со страницы «Билд»: выбор из данных игры, проверка присланных этапов, запись раздела в файл.
Запуск: python -m unittest planner.test_buildplan"""
import copy
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import buildplan  # noqa: E402
import test_itemstats  # noqa: E402

# Билд с двумя этапами (план в рабочем виде, как после core.norm_plan): первый называет всё, второй —
# только то, что меняет: дерево и базу защиты с атрибутами. Статы на втором те же, что на первом.
PLAN = {
    'title': 'Учебный билд',
    'steps': [{'id': 'start', 'zone': 'G1_1', 'name': 'Берег'}, {'id': 'mid', 'zone': 'G2_1', 'name': 'Середина'},
              {'id': 'maps', 'zone': 'G_Endgame_Town', 'name': 'Карты'}],
    'stages': [{'id': 'armour', 'name': 'Кампания', 'note': 'своё поле', 'tree': 'early', 'kind': 'str_armour', 'attrs': ['str'],
                'stats': [{'id': 'minion_level'}, {'id': 'res_cold', 'cap': 80}, {'id': 'life'}]},
               {'id': 'es', 'from': 'maps', 'name': 'Карты', 'tree': 'late', 'kind': 'int_armour', 'attrs': []}],
    'tree': {'phases': [{'id': 'early', 'name': 'Кампания', 'nodes': [{'id': 'n1', 'name': 'Узел'}]},
                        {'id': 'late', 'name': 'Карты', 'nodes': [{'id': 'ci', 'name': 'Иммунитет к хаосу'}]}]},
    'atlas': {'phases': [{'id': 'a1', 'name': 'Атлас', 'nodes': []}]},
}
LINES = {'ci': ['Maximum Life is 1']}

FILE = '''{
  "version": 2,
  "title": "Учебный билд",
  "stages": [
    {"id": "armour", "name": "Кампания", "stats": ["minion_level", {"id": "res_cold", "cap": 80}, "life"]},
    {"id": "es", "from": "maps", "name": "Карты", "kind": "int_armour"}
  ],
  "tree": {
    "phases": []
  },
  "goals": [
    {"id": "a", "title": "Цель"}
  ]
}
'''


def catalogue():
    """Учебный каталог, в котором родов баз хватает на выбор: по дюжине силовых баз и баз на интеллект."""
    cat = copy.deepcopy(test_itemstats.CAT)
    for i in range(12):
        cat['bases']['Extra/Str%d' % i] = {'name': 'Plate %d' % i, 'class': 'Body Armour', 'level': i, 'req': {'level': i, 'str': 10},
                                           'tags': ['str_armour', 'body_armour', 'armour', 'default'], 'props': {'armour': 100 + i}}
        cat['bases']['Extra/Int%d' % i] = {'name': 'Robe %d' % i, 'class': 'Body Armour', 'level': i, 'req': {'level': i, 'int': 10},
                                           'tags': ['int_armour', 'body_armour', 'armour', 'default'], 'props': {'energy_shield': 30 + i}}
        cat['bases']['Extra/Mix%d' % i] = {'name': 'Mail %d' % i, 'class': 'Body Armour', 'level': i,
                                           'req': {'level': i, 'str': 6, 'int': 6}, 'tags': ['str_int_armour', 'body_armour', 'armour', 'default'],
                                           'props': {'armour': 60 + i, 'energy_shield': 20 + i}}
    cat['stats']['stats']['int'] = {'ids': ['int'], 'local': []}
    cat['stats']['order'].append('int')
    cat['stats']['stats']['life']['void'] = ['Maximum Life is 1']
    cat['lang']['ru']['statNames']['int'] = ['Интеллект', 'Интеллект']
    return cat


class ChoiceTest(unittest.TestCase):
    def test_defence_bases_come_from_game_data(self):
        """Выбор базы защиты — роды баз из данных игры: что несут и чего требуют. Рода, у которого баз
        почти нет, в выборе нет; статы связки названы в порядке атрибутов."""
        cat = catalogue()
        kinds = buildplan.kinds(cat)
        self.assertEqual([(k['id'], k['label'], [a['id'] for a in k['needs']]) for k in kinds],
                         [('str_armour', 'Броня', ['str']), ('int_armour', 'Энергощит', ['int']),
                          ('str_int_armour', 'Броня / Энергощит', ['str', 'int'])])
        self.assertEqual(kinds[0]['stats'], [{'id': 'armour', 'name': 'Броня'}])
        self.assertEqual(buildplan.kinds(copy.deepcopy(test_itemstats.CAT)), [])       # в маленьком каталоге баз по одной
        # название рода базы («Шлемы · Энергощит» в карточке крафта); неизвестный род называется как есть
        self.assertEqual([buildplan.kind_label(cat, k) for k in ('int_armour', 'str_int_armour', 'nope')],
                         ['Энергощит', 'Броня / Энергощит', 'nope'])
        # атрибуты — отдельный выбор этапа: те, что в игре вообще есть (чего требуют базы)
        self.assertEqual(buildplan.attributes(cat), [{'id': 'str', 'name': 'Сила'}, {'id': 'int', 'name': 'Интеллект'}])

    def test_page_gets_everything_it_edits(self):
        d = buildplan.describe(catalogue(), PLAN, LINES)
        self.assertEqual((d['title'], [(s['id'], s['act']) for s in d['steps']]),
                         ('Учебный билд', [('start', 'Акт 1'), ('mid', 'Акт 2'), ('maps', 'Карты')]))
        # шаг на картах: с него у героя есть атлас — версию атласа называет только этап, начатый на картах
        self.assertEqual([s['end'] for s in d['steps']], [False, False, True])
        # этап отдаётся тем, что назвал сам: не названное — None (действует как на прежнем); статы — их id
        self.assertEqual(d['stages'], [
            {'id': 'armour', 'name': 'Кампания', 'from': None, 'tree': 'early', 'atlas': None, 'kind': 'str_armour',
             'attrs': ['str'], 'stats': ['minion_level', 'res_cold', 'life']},
            {'id': 'es', 'name': 'Карты', 'from': 'maps', 'tree': 'late', 'atlas': None, 'kind': 'int_armour',
             'attrs': [], 'stats': None}])
        self.assertEqual([a['id'] for a in d['attrs']], ['str', 'int'])
        self.assertIn(('life', 'Здоровье'), [(c['id'], c['name']) for c in d['catalog']])
        # у стата — из чего он складывается: строки свойств словами игры; у стата с собственным свойством вещи —
        # его название и строки, которые уже внутри этого числа
        parts = {c['id']: c['parts'] for c in d['catalog']}
        self.assertEqual(parts['life'], {'lines': ['# к максимуму здоровья'], 'void': ['Maximum Life is 1']})
        self.assertEqual((parts['armour']['prop'], parts['armour']['local']), ('Броня', ['# к броне', '#% повышение брони']))
        self.assertEqual(parts['res_cold']['cap'], 75)
        # версии деревьев билда — выбор для этапа; у версии дерева героя — какой стат она обнуляет,
        # чтобы страница сказала, почему он не в счёт
        self.assertEqual(d['trees'], {
            'tree': [{'id': 'early', 'name': 'Кампания', 'nodes': 1, 'voids': []},
                     {'id': 'late', 'name': 'Карты', 'nodes': 1, 'voids': [
                         {'id': 'life', 'name': 'Здоровье', 'node': 'Иммунитет к хаосу', 'line': 'Maximum Life is 1'}]}],
            'atlas': [{'id': 'a1', 'name': 'Атлас', 'nodes': 0}]})


class CheckTest(unittest.TestCase):
    def setUp(self):
        self.cat = catalogue()

    def test_stages_are_checked_and_keep_their_other_fields(self):
        good = {'stages': [
            {'id': 'es', 'from': 'mid', 'name': ' Щит ', 'tree': 'late', 'atlas': 'a1', 'kind': 'str_int_armour', 'attrs': ['int', 'str'],
             'stats': None},
            {'id': 'armour', 'name': 'Кампания', 'from': None, 'tree': None, 'atlas': None, 'kind': None, 'attrs': None,
             'stats': ['life', 'res_cold', 'speed']},
            {'id': 's3', 'from': 'maps', 'name': 'Карты', 'tree': None, 'atlas': None, 'kind': None, 'attrs': [], 'stats': []}]}
        out, problems = buildplan.check(good, PLAN, self.cat)
        self.assertEqual(problems, [])
        self.assertEqual(out, {'stages': [
            # этапы — по порядку шагов; у прежнего этапа осталось его прочее поле; то, что страница
            # не назвала (дерево, база, атрибуты), из прежней записи не возвращается; порядок статов —
            # как прислан (это важность), прочие поля прежней записи стата (cap) остались
            {'id': 'armour', 'name': 'Кампания', 'stats': ['life', {'id': 'res_cold', 'cap': 80}, 'speed'], 'note': 'своё поле'},
            # атрибуты — в порядке игры
            {'id': 'es', 'from': 'mid', 'name': 'Щит', 'tree': 'late', 'atlas': 'a1', 'kind': 'str_int_armour', 'attrs': ['str', 'int']},
            # пустые списки — тоже выбор этапа: «никаких атрибутов», «ни одного стата»
            {'id': 's3', 'from': 'maps', 'name': 'Карты', 'attrs': [], 'stats': []}]})

    def test_what_is_refused(self):
        bad = lambda payload: buildplan.check(payload, PLAN, self.cat)       # noqa: E731
        self.assertEqual(bad({}), ({}, ['нечего записывать: нет ни одного раздела билда']))
        self.assertEqual(bad({'stages': 'все'}), ({}, ['этапы: нужен список']))
        self.assertEqual(bad({'stages': []}), ({}, ['нужен хотя бы один этап — тот, что действует с самого начала']))
        stage = lambda **kw: dict({'id': 'a', 'name': 'Этап'}, **kw)     # noqa: E731
        one = lambda **kw: bad({'stages': [stage(**kw)]})[1]             # noqa: E731
        self.assertEqual(one(id='Плохой id'), ['этап: id — латинские буквы, цифры, дефис'])
        self.assertEqual(one(name='  '), ['этап «a»: нужно название не длиннее 60 знаков'])
        self.assertEqual(one(kind='dex_armour'), ['этап «Этап»: такой базы защиты в данных игры нет'])
        self.assertEqual(one(attrs=['life']), ['этап «Этап»: атрибуты — только те, что есть в игре'])
        self.assertEqual(one(tree='nope', atlas='late'),
                         ['этап «Этап»: версии дерева «nope» в билде нет', 'этап «Этап»: версии атласа «late» в билде нет'])
        self.assertEqual(one(stats=['nope', 'life', 'life']),
                         ['этап «Этап»: стата «nope» нет в данных игры', 'этап «Этап»: стат «life» записан дважды'])
        self.assertEqual(one(stats='life'), ['этап «Этап»: статы — список не длиннее 60'])
        self.assertEqual(bad({'stages': [stage(), stage(id='b', **{'from': 'nowhere'})]})[1], ['этап «Этап»: шага «nowhere» в маршруте нет'])
        self.assertEqual(bad({'stages': [stage(), stage(id='b')]})[1],
                         ['с самого начала действует только один этап — остальным нужен шаг начала'])
        self.assertEqual(bad({'stages': [stage(), stage(id='b', **{'from': 'mid'}), stage(id='c', **{'from': 'mid'})]})[1],
                         ['этап «Этап»: с шага «mid» уже начинается другой этап'])
        self.assertEqual(one(**{'from': 'mid'}), ['нет этапа, который действует с самого начала'])
        self.assertEqual(bad({'stages': [stage(), stage()]})[1], ['этап «a» прислан дважды'])

class FileTest(unittest.TestCase):
    def test_only_the_section_changes_in_the_file(self):
        stages = [{'id': 'armour', 'name': 'Кампания', 'kind': 'str_armour', 'stats': ['life', {'id': 'res_cold', 'cap': 80}]}]
        out = buildplan.splice(FILE, 'stages', stages)
        self.assertEqual(json.loads(out)['stages'], stages)
        self.assertIn('  "stages": [\n    {"id": "armour", "name": "Кампания", "kind": "str_armour", '
                      '"stats": ["life", {"id": "res_cold", "cap": 80}]}\n  ],\n  "tree": {', out)
        # раздела ещё нет — встаёт перед деревом; пустой раздел пишется одной строкой и правится дальше
        bare = FILE[:FILE.index('  "stages": [')] + FILE[FILE.index('  "tree": {'):]
        self.assertNotIn('stages', json.loads(bare))
        added = buildplan.splice(bare, 'stages', stages)
        self.assertEqual(added, out)
        self.assertEqual(list(json.loads(added)), ['version', 'title', 'stages', 'tree', 'goals'])
        empty = buildplan.splice(out, 'stages', [])
        self.assertIn('  "stages": [],\n  "tree": {', empty)
        self.assertEqual(buildplan.splice(empty, 'stages', stages), out)
        # переводы строк файла сохраняются
        crlf = buildplan.splice(FILE.replace('\n', '\r\n'), 'stages', stages)
        self.assertEqual(crlf.replace('\r\n', '\n'), out)
        self.assertNotIn('\n', crlf.replace('\r\n', ''))
        # раздел записан непривычно (в одну строку с записями) — файл не трогаем
        odd = bare.replace('  "tree": {', '  "stages": [{"id": "a"}], "stages2": [\n  ],\n  "tree": {')
        with self.assertRaises(ValueError):
            buildplan.splice(odd, 'stages', stages)

    def test_save_keeps_a_copy_of_the_old_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'build.json'
            path.write_text(FILE, encoding='utf-8', newline='')
            buildplan.save(path, {'stages': [{'id': 'a', 'name': 'Этап', 'kind': 'str_armour'}]}, Path(tmp) / 'backup', now=0)
            data = json.loads(path.read_text(encoding='utf-8'))
            self.assertEqual((data['stages'], data['goals']),
                             ([{'id': 'a', 'name': 'Этап', 'kind': 'str_armour'}], [{'id': 'a', 'title': 'Цель'}]))
            copies = list((Path(tmp) / 'backup').glob('build.build-*.json'))
            self.assertEqual((len(copies), copies[0].read_text(encoding='utf-8')), (1, FILE))


BUILD = '''{
  "version": 2,
  "title": "Учебный билд",
  "slots": [
    {"id": "body", "name": "Доспех", "gear": "Body Armour"}
  ],
  "stages": [
    {"id": "start", "name": "Кампания", "tree": "early", "stats": ["res_cold", "life"]}
  ],
  "tree": {
    "phases": [
      {"id": "early", "name": "Кампания", "nodes": [
        {"id": "n1", "name": "Узел"}
      ]},
      {"id": "late", "name": "Карты", "nodes": [
        {"id": "ci", "name": "Иммунитет к хаосу"}
      ]}
    ]
  },
  "goals": []
}
'''


class ServerTest(unittest.TestCase):
    """Страница «Билд» через программу: план из частей, этапы лежат в файле билда; каталог — настоящий."""

    def setUp(self):
        import server
        import test_treeplan
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        (root / 'Client.txt').write_text(test_treeplan.LOG, encoding='utf-8')
        (root / 'plan.json').write_text(json.dumps({'version': 2, 'route': 'route.json', 'build': 'build.json'}), encoding='utf-8')
        (root / 'route.json').write_text(json.dumps({'id': 'r', 'steps': [
            {'id': 'riverbank', 'zone': 'G1_1', 'name': 'Берег реки'}, {'id': 'clearfell', 'zone': 'G1_2', 'name': 'Клирфелл'},
            {'id': 'maps', 'zone': 'G_Endgame_Town', 'name': 'Выход на карты'}]}, ensure_ascii=False), encoding='utf-8')
        self.build = root / 'build.json'
        self.build.write_bytes(BUILD.replace('\n', '\r\n').encode('utf-8'))
        (root / 'treestats.json').write_text(json.dumps(LINES), encoding='utf-8')
        self.app = server.App(root / 'Client.txt', root / 'plan.json', root / 'runs', backup_dir=root / 'backup')
        self.app.treestats_path = root / 'treestats.json'
        with self.app.cond:
            self.app.load_plan()
            self.app.poll_log(initial=True)
            self.app.attach_run()

    def tearDown(self):
        self.tmp.cleanup()

    def test_admin_reads_and_writes_the_build(self):
        if not self.app.catalog or not self.app.catalog.get('stats'):
            self.skipTest('каталог данных игры не собран')
        d = self.app.build_view()
        self.assertEqual((d['stages'], [s['id'] for s in d['steps']], d['problems']),
                         ([{'id': 'start', 'name': 'Кампания', 'from': None, 'tree': 'early', 'atlas': None, 'kind': None,
                            'attrs': None, 'stats': ['res_cold', 'life']}], ['riverbank', 'clearfell', 'maps'], []))
        # шесть баз защиты из данных игры — те же, что кнопки фильтра
        self.assertEqual([k['id'] for k in d['kinds']],
                         ['str_armour', 'dex_armour', 'int_armour', 'str_dex_armour', 'str_int_armour', 'dex_int_armour'])
        self.assertEqual(d['trees']['tree'][1]['voids'][0]['id'], 'life')
        before = self.build.read_bytes()
        ok, problems = self.app.save_build({'stages': [
            {'id': 'es', 'from': 'maps', 'name': 'Карты', 'tree': 'late', 'kind': 'int_armour', 'attrs': []},
            {'id': 'start', 'name': 'Кампания', 'tree': 'early', 'kind': 'str_armour', 'attrs': ['str'], 'stats': ['life', 'res_cold']}]})
        self.assertEqual((ok, problems), (True, []))
        text = self.build.read_bytes().decode('utf-8')
        data = json.loads(text)
        self.assertEqual((data['stages'], data['tree'], list(data)), ([
            {'id': 'start', 'name': 'Кампания', 'tree': 'early', 'kind': 'str_armour', 'attrs': ['str'], 'stats': ['life', 'res_cold']},
            {'id': 'es', 'from': 'maps', 'name': 'Карты', 'tree': 'late', 'kind': 'int_armour', 'attrs': []}],
            json.loads(BUILD)['tree'], ['version', 'title', 'slots', 'stages', 'tree', 'goals']))
        self.assertNotIn('\n', text.replace('\r\n', ''))                       # переводы строк файла сохранены
        self.assertEqual(len(list((Path(self.tmp.name) / 'backup').glob('build.build-*.json'))), 1)
        # план перечитан: этапы действуют, страница их видит
        self.assertEqual(([s['id'] for s in self.app.plan['stages']], self.app.build_view()['stages'][1]['from'], self.app.plan_problems),
                         (['start', 'es'], 'maps', []))
        # билд на шаге: до карт — броня и сила с первого этапа, на картах — энергощит, а здоровье дерево обнулило
        import herostats
        ids = lambda pos: [s['id'] for s in herostats.at_step(self.app.catalog, self.app.plan, pos, self.app.tree_lines())['stats']]  # noqa: E731
        self.assertEqual((ids(0), ids(2)), (['life', 'res_cold', 'armour', 'str'], ['res_cold', 'es']))
        # отказ ничего не пишет
        saved = self.build.read_bytes()
        ok, problems = self.app.save_build({'stages': [{'id': 'x', 'name': 'Этап', 'kind': 'nope'}]})
        self.assertEqual((ok, problems, self.build.read_bytes() == saved, before == saved),
                         (False, ['этап «Этап»: такой базы защиты в данных игры нет'], True, False))


# --- цели билда ---------------------------------------------------------------------------------------
# Файл билда с целями всех носителей: вещи слота (одна — в две строки, с probe), умение с поддержкой
# и уровнем камня, запас. Две цели стоят в проверках шагов.
GOALS_BUILD = '''{
  "version": 2,
  "title": "Учебный билд",
  "slots": [
    {"id": "weapon", "name": "Оружие", "classes": ["Sceptre"]},
    {"id": "body", "name": "Доспех", "classes": ["Body Armour"], "gear": "Body Armour"}
  ],
  "stages": [
    {"id": "start", "name": "Кампания", "stats": ["res_cold", "life"]}
  ],
  "gemLevels": [0, 3, 6, 10, 14],
  "goals": [
    {"id": "sceptre", "use": "clearfell", "slot": "weapon", "gear": "Sceptre", "title": "Гремящий скипетр (Rattling Sceptre)", "key": true, "need": "riverbank",
     "probe": {"Class": "Sceptres", "BaseType": "Rattling Sceptre"}},
    {"id": "sceptre-spirit", "use": "clearfell", "slot": "weapon", "part": "spirit", "stat": "spirit", "min": 120, "title": "от 120", "need": "clearfell"},
    {"id": "skill-bomb", "kind": "skill", "group": "Навыки", "title": "Морозная бомба (Frost Bomb)", "gemFrom": 1, "need": "riverbank"},
    {"id": "support-area", "kind": "support", "group": "Навыки", "title": "Увеличенная область I (Magnified Area I)", "for": "skill-bomb", "need": "clearfell"},
    {"id": "gem3-bomb", "kind": "gem", "group": "Навыки", "part": "level", "title": "3", "for": "skill-bomb", "need": "clearfell"},
    {"id": "gold", "kind": "resource", "group": "Ресурсы", "title": "7000 золота", "heard": "SinA4_Wild_ThirdPieceAfterConvo", "need": "maps"}
  ]
}
'''
GOALS_ROUTE = {'id': 'r', 'steps': [
    {'id': 'riverbank', 'zone': 'G1_1', 'name': 'Берег реки'}, {'id': 'clearfell', 'zone': 'G1_2', 'name': 'Клирфелл'},
    {'id': 'maps', 'zone': 'G_Endgame_Town', 'name': 'Выход на карты'}],
    'goals': [{'id': 'hero-7', 'group': 'Уровень', 'title': '7 уровень героя', 'reach': 7, 'need': 'clearfell'}]}


def goals_state():
    """Файл билда как есть, план в рабочем виде и каталог — то, с чем работает проверка целей."""
    import core
    import planfiles
    build = json.loads(GOALS_BUILD)
    cat = catalogue()
    cat['stats']['stats'].setdefault('spirit', {'ids': ['spirit'], 'local': []})
    composed, _ = planfiles.compose({'route': 'r', 'build': 'b'}, GOALS_ROUTE, build)
    plan, problems = core.norm_plan(composed, cat)
    assert problems == [], problems
    return build, plan, cat


class GoalChoiceTest(unittest.TestCase):
    def test_names_come_from_game_data(self):
        """Названия умений, поддержек и баз страница берёт из данных игры: на языке игрока с английским
        в скобках. Оттуда же стартовый уровень камня, описание базы, уровень зоны и рисунок."""
        cat = catalogue()
        cat['gems'] = {'A': {'name': 'Frost Bomb', 'type': 'active', 'level': 1}, 'A2': {'name': 'Frost Bomb', 'type': 'active', 'level': 0},
                       'B': {'name': 'Magnified Area I', 'type': 'support', 'level': 1},
                       'C': {'name': 'Kelari, the Tainted Sands', 'type': 'active', 'level': 0},
                       'D': {'name': 'Skeletal Cleric', 'type': 'spirit', 'level': 13}}
        cat['lang']['ru']['gems'] = {'Frost Bomb': 'Морозная бомба', 'Magnified Area I': 'Увеличенная область I',
                                     'Skeletal Cleric': 'Скелет-клерик'}
        # камень без названия на языке игрока (умение восхождения) в выбор не идёт: его называют рукой
        self.assertEqual(buildplan.gem_choices(cat), {
            'skills': [{'name': 'Морозная бомба (Frost Bomb)', 'level': 1}, {'name': 'Скелет-клерик (Skeletal Cleric)', 'level': 13}],
            'supports': [{'name': 'Увеличенная область I (Magnified Area I)', 'level': 1}]})
        cat['lang']['ru']['bases'].update({'Plate 3': 'Латы 3', 'Robe 2': 'Мантия 2', 'Mail 1': 'Кольчуга 1'})
        cat['bases']['Extra/Int2']['icon'] = 'art-robe02'
        rows = buildplan.base_choices(cat, [{'id': 'body', 'classes': ['Body Armour']}, {'id': 'ring', 'classes': ['Ring']}])
        # база со связкой родов называет связку; по порядку уровня
        self.assertEqual([r for r in rows['body'] if r['name'].split(' (')[0] in ('Латы 3', 'Мантия 2', 'Кольчуга 1')], [
            {'name': 'Кольчуга 1 (Mail 1)', 'gear': 'Body Armour str_int_armour', 'level': 1, 'icon': None},
            {'name': 'Мантия 2 (Robe 2)', 'gear': 'Body Armour int_armour', 'level': 2, 'icon': 'art-robe02'},
            {'name': 'Латы 3 (Plate 3)', 'gear': 'Body Armour str_armour', 'level': 3, 'icon': None}])
        self.assertEqual(rows['ring'], [])

    def test_page_gets_the_goals_as_they_are_written(self):
        build, plan, cat = goals_state()
        d = buildplan.describe(cat, plan, {}, build=build, route=GOALS_ROUTE)
        # цели — как в файле: ступени уровня камня, которые программа достраивает сама, сюда не идут
        self.assertEqual([g['id'] for g in d['goals']], ['sceptre', 'sceptre-spirit', 'skill-bomb', 'support-area', 'gem3-bomb', 'gold'])
        self.assertEqual(d['goals'][0]['probe'], {'Class': 'Sceptres', 'BaseType': 'Rattling Sceptre'})
        self.assertEqual(([(s['id'], s['name']) for s in d['slots']], d['taken'], d['gemLevels']),
                         ([('weapon', 'Оружие'), ('body', 'Доспех')], ['hero-7'], 5))
        # своих списков у шагов билд не ведёт: что закрыть на шаге, говорит срок цели
        self.assertEqual([k for k in ('adds', 'gates', 'routeGoals', 'names') if k in d], [])
        # у плана одним файлом (без частей) целей на странице нет
        self.assertNotIn('goals', buildplan.describe(cat, plan, {}))


class GoalCheckTest(unittest.TestCase):
    def setUp(self):
        self.build, self.plan, self.cat = goals_state()
        self.goals = json.loads(GOALS_BUILD)['goals']

    def check(self, goals, verify=None):
        return buildplan.check({'goals': goals}, self.plan, self.cat, build=self.build, route=GOALS_ROUTE, verify=verify)

    def test_untouched_goals_pass_as_they_are(self):
        out, problems = self.check(self.goals)
        self.assertEqual((problems, out), ([], {'goals': json.loads(GOALS_BUILD)['goals']}))
        self.assertEqual([list(g) for g in out['goals']], [list(g) for g in self.goals])      # порядок полей прежний

    def test_edits_are_cleaned_and_new_goals_join(self):
        g = self.goals
        g[0].update(title='  Стоический скипетр (Stoic Sceptre) ', label='', key=False, opens=16, icon='art-sceptre02')
        g[3].update(need='maps', until='maps', hero=64)
        g[5].update(note='  заметка  ')
        g.insert(4, {'id': 'support-heft-bomb', 'kind': 'support', 'group': 'Навыки', 'title': 'Тяжесть (Heft)', 'for': 'skill-bomb',
                     'label': None, 'from': '', 'need': 'maps'})
        g.append({'id': 'gem4-bomb', 'kind': 'gem', 'group': 'Навыки', 'part': 'level', 'title': '4', 'for': 'skill-bomb', 'need': 'maps'})
        g.append({'id': 'body-life', 'slot': 'body', 'part': 'life', 'stat': 'life', 'min': 80, 'title': 'от 80', 'soft': True})
        out, problems = self.check(g)
        self.assertEqual(problems, [])
        by = {x['id']: x for x in out['goals']}
        # пустая строка и снятая пометка в запись не идут; строки без пробелов по краям; probe цел
        self.assertEqual(by['sceptre'], {'id': 'sceptre', 'use': 'clearfell', 'slot': 'weapon', 'gear': 'Sceptre',
                                         'title': 'Стоический скипетр (Stoic Sceptre)', 'need': 'riverbank',
                                         'probe': {'Class': 'Sceptres', 'BaseType': 'Rattling Sceptre'}, 'opens': 16, 'icon': 'art-sceptre02'})
        self.assertEqual((by['support-area']['until'], by['support-area']['hero'], by['gold']['note']), ('maps', 64, 'заметка'))
        self.assertEqual(by['support-heft-bomb'], {'id': 'support-heft-bomb', 'kind': 'support', 'group': 'Навыки', 'title': 'Тяжесть (Heft)',
                                                   'for': 'skill-bomb', 'need': 'maps'})
        self.assertEqual([x['id'] for x in out['goals']],
                         ['sceptre', 'sceptre-spirit', 'skill-bomb', 'support-area', 'support-heft-bomb', 'gem3-bomb', 'gold', 'gem4-bomb', 'body-life'])

    def test_a_skill_and_what_lives_with_it_have_no_note(self):
        """Заметки у умения, камня поддержки и уровня камня нет, подсказки — ни у одной цели. Прежняя заметка из файла,
        записанного раньше, проходит как есть; новая или изменённая — нет. У остальных целей заметка есть."""
        def notes(i, text):
            g = [dict(x) for x in self.goals]
            g[i]['note'] = text
            return self.check(g)[1]

        refused = 'цель «%s»: заметки у умения, камня поддержки и уровня камня нет'
        self.assertEqual(notes(2, 'тактика'), [refused % 'Морозная бомба (Frost Bomb)'])
        self.assertEqual(notes(3, 'тактика'), [refused % 'Увеличенная область I (Magnified Area I)'])
        self.assertEqual(notes(4, 'тактика'), [refused % '3'])
        self.assertEqual((notes(1, 'рецепт'), notes(5, 'рецепт')), ([], []))      # стат предмета и запас
        g = [dict(x) for x in self.goals]
        g[1]['hint'] = 'белый скипетр'
        self.assertEqual(self.check(g)[1], ['цель «%s»: поле «hint» со страницы не правится' % (g[1].get('title') or g[1]['id'])])
        # прежняя заметка у камня поддержки: тем же текстом проходит, другим — нет
        self.build['goals'][3]['note'] = 'старая'
        self.assertEqual((notes(3, 'старая'), notes(3, 'новая')),
                         ([], [refused % 'Увеличенная область I (Magnified Area I)']))

    def test_what_is_refused(self):
        def bad(**kw):
            return self.check(self.goals[:-1] + [dict(self.goals[-1], **kw)])[1]

        self.assertEqual(self.check('все')[1], ['цели: нужен список не длиннее 600'])
        self.assertEqual(bad(id='Плохой id'), ['цель: id — латинские буквы, цифры, дефис'])
        self.assertEqual(bad(id='sceptre'), ['цель «sceptre»: такой id уже есть'])
        self.assertEqual(bad(id='hero-7'), ['цель «hero-7»: такой id уже есть у цели маршрута'])
        self.assertEqual(bad(title='  '), ['цель «gold»: нужно название'])
        self.assertEqual(bad(need='nowhere'), ['цель «7000 золота»: шага «nowhere» в маршруте нет'])
        self.assertEqual(bad(hero=0), ['цель «7000 золота»: поле hero — целое от 1 до 100'])
        self.assertEqual(bad(key='да'), ['цель «7000 золота»: пометка key — да или нет'])
        self.assertEqual(bad(kind='boss'), ['цель «7000 золота»: такого вида цели у билда нет'])
        self.assertEqual(bad(slot='tail'), ['цель «7000 золота»: слота «tail» в билде нет'])
        # редкость — параметр предмета слота, словом игры
        self.assertEqual(bad(rarity='Rare'), ['цель «7000 золота»: редкость бывает только у предмета слота'])
        self.assertEqual(bad(rarity='жёлтый'), ['цель «7000 золота»: редкость — Normal, Magic или Rare'])
        item = [dict(g, rarity='Magic') if g['id'] == 'sceptre' else g for g in self.goals]
        out, problems = self.check(item)
        self.assertEqual((problems, out['goals'][0]['rarity']), ([], 'Magic'))
        # снятый выбор в запись не идёт
        out, problems = self.check([dict(g, rarity=None) if g['id'] == 'sceptre' else g for g in self.goals])
        self.assertEqual((problems, 'rarity' in out['goals'][0]), ([], False))
        stat = [dict(g, rarity='Rare') if g['id'] == 'sceptre-spirit' else g for g in self.goals]
        self.assertEqual(self.check(stat)[1], ['цель «%s»: редкость бывает только у предмета слота' % self.goals[1]['title']])
        self.assertEqual(bad(icon='../secret'), ['цель «7000 золота»: рисунок назван не так'])
        self.assertEqual(bad(grantedBy='nope'), ['цель «7000 золота»: нет цели «nope» (grantedBy)'])
        # поле, которого страница не правит, новым значением не проходит; прежним — проходит (heard у золота)
        self.assertEqual(bad(heard='Другая реплика'), ['цель «7000 золота»: поле «heard» со страницы не правится'])
        self.assertEqual(bad(reward='дух'), ['цель «7000 золота»: поле «reward» со страницы не правится'])
        self.assertEqual(bad(stat='life'), ['цель «7000 золота»: цели по стату нужны слот, стат и число «от»'])
        self.assertEqual(bad(stat='nope'), ['цель «7000 золота»: стата «nope» нет в данных игры'])
        # поддержка и уровень камня живут при умении; новая ступень уровня носит id, который дала бы программа
        self.assertEqual(bad(kind='support'), ['цель «7000 золота»: камень поддержки и уровень камня живут при умении'])
        new = {'id': 'level-4', 'kind': 'gem', 'part': 'level', 'title': '4', 'for': 'skill-bomb'}
        self.assertEqual(self.check(self.goals + [new])[1], ['цель «4»: уровень камня — число, а id ступени — gem<уровень>-<умение>'])
        self.assertEqual(self.check(self.goals + [dict(new, id='gem4-bomb')])[1], [])
        # цель удалённого умения осталась без него
        self.assertEqual(self.check([g for g in self.goals if g['id'] != 'skill-bomb'])[1], [
            'цель «Увеличенная область I (Magnified Area I)»: нет цели «skill-bomb» (for)',
            'цель «Увеличенная область I (Magnified Area I)»: камень поддержки и уровень камня живут при умении',
            'цель «3»: нет цели «skill-bomb» (for)', 'цель «3»: камень поддержки и уровень камня живут при умении'])
        # замечания к плану целиком (их считает программа) тоже отказ; при прочих замечаниях до них не доходит
        self.assertEqual(self.check(self.goals, verify=lambda sections: ['Цели «a» и «b» привязаны к одному узлу дерева']),
                         ({}, ['Цели «a» и «b» привязаны к одному узлу дерева']))
        self.assertEqual(buildplan.check({'goals': self.goals}, self.plan, self.cat),
                         ({}, ['цели правятся только у плана из частей (маршрут, билд, личное)']))


class GoalFileTest(unittest.TestCase):
    def test_untouched_goal_keeps_its_text(self):
        goals = json.loads(GOALS_BUILD)['goals']
        self.assertEqual(buildplan.splice_goals(GOALS_BUILD, goals), GOALS_BUILD)        # ничего не менялось — знак в знак
        goals[1]['min'] = 150
        goals.insert(4, {'id': 'support-heft-bomb', 'kind': 'support', 'title': 'Тяжесть (Heft)', 'for': 'skill-bomb'})
        del goals[-1]
        out = buildplan.splice_goals(GOALS_BUILD, goals)
        self.assertEqual(json.loads(out)['goals'], goals)
        # цель в две строки (probe на своей) не тронута; изменённая и новая — одной строкой; последняя — без запятой
        self.assertIn('"need": "riverbank",\n     "probe": {"Class": "Sceptres", "BaseType": "Rattling Sceptre"}},\n'
                      '    {"id": "sceptre-spirit", "use": "clearfell", "slot": "weapon", "part": "spirit", "stat": "spirit", "min": 150, ', out)
        self.assertIn('    {"id": "support-heft-bomb", "kind": "support", "title": "Тяжесть (Heft)", "for": "skill-bomb"},\n', out)
        self.assertTrue(out.endswith('"for": "skill-bomb", "need": "clearfell"}\n  ]\n}\n'))
        # тот же набор полей в другом порядке — уже правка: запись пишется заново
        moved = json.loads(GOALS_BUILD)['goals']
        moved[2] = {'id': 'skill-bomb', 'title': moved[2]['title'], 'kind': 'skill', 'group': 'Навыки', 'gemFrom': 1, 'need': 'riverbank'}
        self.assertIn('{"id": "skill-bomb", "title": "Морозная бомба (Frost Bomb)", "kind": "skill"', buildplan.splice_goals(GOALS_BUILD, moved))
        # переводы строк файла сохраняются; пустой список — раздел без записей
        crlf = buildplan.splice_goals(GOALS_BUILD.replace('\n', '\r\n'), goals)
        self.assertEqual(crlf.replace('\r\n', '\n'), out)
        self.assertIn('  "goals": [\n  ]\n}', buildplan.splice_goals(GOALS_BUILD, []))
        with self.assertRaises(ValueError):
            buildplan.splice_goals(GOALS_BUILD.replace('  "goals": [\n', '  "goals": [ \n'), goals)

    def test_the_real_build_is_written_back_exactly(self):
        """Раздел целей настоящего билда воспроизводится знак в знак — иначе первая же правка со страницы
        переписала бы файл не так, как он написан. Раздела проверок шагов (steps) в нём нет: что закрыть
        на шаге, говорят сроки самих целей."""
        import planlib
        plans = planlib.project_plans(Path(HERE).parent)
        if not plans:
            self.skipTest('нет файла билда')
        for path, parts in plans:
            with self.subTest(plan=path.parent.name):
                text = parts['build'].read_bytes().decode('utf-8-sig')
                data = json.loads(text)
                self.assertNotIn('steps', data)
                self.assertEqual(buildplan.splice_goals(text, data['goals']), text)


class GoalServerTest(unittest.TestCase):
    """Цели через программу: план из частей, каталог настоящий."""

    def setUp(self):
        import server
        import test_treeplan
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        (root / 'Client.txt').write_text(test_treeplan.LOG, encoding='utf-8')
        (root / 'plan.json').write_text(json.dumps({'version': 2, 'route': 'route.json', 'build': 'build.json'}), encoding='utf-8')
        (root / 'route.json').write_text(json.dumps(GOALS_ROUTE, ensure_ascii=False), encoding='utf-8')
        self.build = root / 'build.json'
        self.build.write_bytes(GOALS_BUILD.replace('\n', '\r\n').encode('utf-8'))
        self.app = server.App(root / 'Client.txt', root / 'plan.json', root / 'runs', backup_dir=root / 'backup')
        with self.app.cond:
            self.app.load_plan()
            self.app.poll_log(initial=True)
            self.app.attach_run()

    def tearDown(self):
        self.tmp.cleanup()

    def test_goals_are_read_edited_and_written(self):
        if not self.app.catalog or not self.app.catalog.get('stats'):
            self.skipTest('каталог данных игры не собран')
        d = self.app.build_view()
        self.assertEqual((d['problems'], len(d['goals']), d['taken']), ([], 6, ['hero-7']))
        self.assertIn({'name': 'Гремящий скипетр (Rattling Sceptre)', 'gear': 'Sceptre', 'level': 1, 'icon': 'art-sceptre01'}, d['classBases']['Sceptre'])
        self.assertIn({'name': 'Морозная бомба (Frost Bomb)', 'level': 1}, d['gems']['skills'])
        goals = d['goals']
        goals[3]['need'] = 'maps'                                           # срок поддержки перенесён
        goals.insert(5, {'id': 'gem4-bomb', 'kind': 'gem', 'group': 'Навыки', 'part': 'level', 'title': '4', 'for': 'skill-bomb', 'need': 'maps'})
        goals = [g for g in goals if g['id'] != 'sceptre']                  # вещь убрана
        goals = [g for g in goals if g['id'] != 'sceptre-spirit']
        before = self.build.read_bytes().decode('utf-8')
        ok, problems = self.app.save_build({'goals': goals})
        self.assertEqual((ok, problems), (True, []))
        text = self.build.read_bytes().decode('utf-8')
        data = json.loads(text)
        self.assertEqual([g['id'] for g in data['goals']], ['skill-bomb', 'support-area', 'gem3-bomb', 'gem4-bomb', 'gold'])
        self.assertEqual(data['goals'][1]['need'], 'maps')
        # файл был старого вида: вместе с целями в новый вид переписаны и слоты — у слота периоды (wear)
        was = json.loads(before)
        self.assertEqual({k: v for k, v in data.items() if k not in ('goals', 'slots')}, {k: v for k, v in was.items() if k not in ('goals', 'slots')})
        self.assertEqual(data['slots'], [{'id': 'weapon', 'name': 'Оружие', 'wear': [{'from': 'clearfell', 'classes': ['Sceptre']}]},
                                         {'id': 'body', 'name': 'Доспех', 'wear': [{'classes': ['Body Armour']}]}])
        self.assertNotIn('\n', text.replace('\r\n', ''))                       # переводы строк файла сохранены
        self.assertEqual(len(list((Path(self.tmp.name) / 'backup').glob('build.build-*.json'))), 1)
        # план перечитан: страница маршрута видит новый срок и новую ступень уровня
        view = self.app.view()
        self.assertEqual(self.app.plan_problems, [])
        self.assertEqual({g['id']: g['need'] for g in self.app.plan['goals'] if g['id'] in ('support-area', 'gem4-bomb')},
                         {'support-area': 'maps', 'gem4-bomb': 'maps'})
        # цели шага страница забега берёт по сроку целей: обе стоят на шаге «Выход на карты»
        self.assertTrue({'support-area', 'gem4-bomb'} <= {g['id'] for g in view['cards'][2]['goals']})
        self.assertNotIn('gates', view['cards'][0])
        # этапы и цели можно прислать вместе
        ok, problems = self.app.save_build({'stages': self.app.build_view()['stages'], 'goals': self.app.build_view()['goals']})
        self.assertEqual((ok, problems), (True, []))
        # поле, которого страница не правит, — отказ, файл цел
        saved = self.build.read_bytes()
        bad = self.app.build_view()['goals'] + [{'id': 'x', 'title': 'Узел', 'node': 'n1'}]
        ok, problems = self.app.save_build({'goals': bad})
        self.assertEqual((ok, problems, self.build.read_bytes() == saved), (False, ['цель «Узел»: поле «node» со страницы не правится'], True))
        # замечание к плану целиком (его видит только сборка плана) — тоже отказ: такого уровня камня в таблице нет
        # (умение названо не по данным игры: камню из данных игры стартовый уровень даёт сама игра)
        ok, problems = self.app.save_build({'goals': [dict(g, title='Своё умение', gemFrom=9) if g['id'] == 'skill-bomb' else g
                                                      for g in self.app.build_view()['goals']]})
        # (лесенки уровня у такого умения нет, поэтому следом идут замечания о его ступенях)
        self.assertEqual((ok, problems[0], self.build.read_bytes() == saved),
                         (False, 'Умение «skill-bomb»: стартовый уровень камня вне таблицы gemLevels', True))


if __name__ == '__main__':
    unittest.main()
