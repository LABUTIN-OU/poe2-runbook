# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Sergei Labutin
# Additional terms under GPL-3.0 section 7: see NOTICE.md
"""Проверка слоя языка (planner/i18n.py, planner/lang/*.json).

Что проверяется:
  * у каждого текста программы есть перевод на каждом языке — и лишних переводов нет: ключи файла языка
    совпадают с ключами, которыми пользуется код (tr('…') в Python, T('…') на страницах);
  * ни один текст не остался в стороне: каждый литерал с кириллицей в коде либо обёрнут вызовом перевода,
    либо назван в planner/lang/raw.json — «это не текст программы» (разбор лога и текста предмета по языку
    клиента, служебные скрипты);
  * перевод подставляется так же, как русский текст: те же %s, %d и {0}, столько форм числа, сколько у языка;
  * название из игры на каждом языке: по-русски «Гремящий скипетр (Rattling Sceptre)», по-английски —
    «Rattling Sceptre»;
  * русский язык — язык кода: для него данные страницы не меняются вовсе.

Запуск: python -X utf8 -m unittest planner.test_lang"""
import io
import json
import re
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import i18n  # noqa: E402
import langscan  # noqa: E402
from i18n import tr  # noqa: E402

PAGES = ('index.html', 'admin.html')
# модули без текстов программы: сам слой языка и его проверка; проверочные инструменты (враждебные планы, язык страниц —
# их данные и отчёт; в программу они не входят)
SKIP = ('i18n.py', 'langscan.py', 'hostile.py', 'hostile_pages.py', 'lang_pages.py')


def modules():
    return sorted(p for p in HERE.glob('*.py') if not p.name.startswith('test_') and p.name not in SKIP)


def read(path):
    with io.open(path, encoding='utf-8-sig', newline='') as f:
        return f.read()


def code_keys():
    """Ключи перевода, которыми пользуется код: {ключ: где встречен}."""
    keys = {}
    for path in modules():
        for lit in langscan.py_literals(read(path)):
            if lit['call'] and not lit['doc']:
                keys.setdefault(lit['text'], path.name)
    for name in PAGES:
        html = read(HERE / 'static' / name)
        a, b = langscan.script_span(html)
        for key in langscan.js_keys(html, a, b):
            if langscan.CYR.search(key):
                keys.setdefault(key, name)
        for m in langscan.markup_texts(html):
            keys.setdefault(m['text'], name)
    return keys


def raw_list():
    return json.loads(read(i18n.LANG_DIR / 'raw.json'))


class KeysTest(unittest.TestCase):
    def test_languages_listed(self):
        """Языки берутся из файлов перевода: английский — по умолчанию и первым, русский — язык кода."""
        langs = i18n.languages()
        self.assertEqual([x['code'] for x in langs][:2], ['en', 'ru'])
        self.assertEqual({x['code']: x['name'] for x in langs}['ru'], 'Русский')
        self.assertEqual((i18n.DEFAULT, i18n.SOURCE), ('en', 'ru'))
        self.assertEqual(i18n.pick('en'), 'en')
        self.assertEqual(i18n.pick('ru'), 'ru')
        self.assertEqual(i18n.pick('xx'), 'en')            # незнакомый язык — язык по умолчанию
        self.assertEqual(i18n.pick('../ru'), 'en')         # имя файла из запроса не собирается

    def test_every_key_has_every_language(self):
        """У каждого текста программы есть перевод на каждом языке, и лишних переводов нет."""
        keys = code_keys()
        self.assertGreater(len(keys), 1000)
        for lang in i18n.languages():
            if lang['code'] == i18n.SOURCE:
                continue
            texts = i18n.table(lang['code'])['texts']
            missing = sorted(k for k in keys if k not in texts)
            extra = sorted(k for k in texts if k not in keys)
            self.assertEqual(missing, [], '%s: нет перевода (первый — из %s)' % (lang['code'], keys.get(missing[0]) if missing else ''))
            self.assertEqual(extra, [], '%s: перевод есть, а в коде такого текста нет' % lang['code'])
            self.assertFalse([k for k, v in texts.items() if not isinstance(v, str) or not v.strip()], 'пустой перевод')

    def test_source_language_has_no_table(self):
        """Русский — язык кода: его текст и есть ключ, своего словаря у него нет."""
        ru = i18n.table('ru')
        self.assertEqual((ru['texts'], ru['plan']), ({}, {}))
        self.assertEqual(i18n.page('ru')['texts'], {})

    def test_plan_words_same_in_every_language(self):
        """Слова из файлов плана («любой», название слота) переведены на каждом языке одним и тем же набором."""
        sets = {x['code']: set(i18n.table(x['code'])['plan']) for x in i18n.languages() if x['code'] != i18n.SOURCE}
        self.assertTrue(sets['en'])
        for code, words in sets.items():
            self.assertEqual(words, sets['en'], code)

    def test_nothing_left_unwrapped(self):
        """Каждый литерал с кириллицей в коде — текст программы (обёрнут) или назван в raw.json."""
        raw = raw_list()
        for path in modules():
            allowed = set(raw.get(path.name) or ())
            left = [(lit['line'], lit['text']) for lit in langscan.py_literals(read(path))
                    if not lit['doc'] and not lit['call'] and lit['text'] not in allowed]
            self.assertEqual(left, [], '%s: текст не обёрнут tr() и не назван в raw.json' % path.name)
        for name in PAGES:
            html = read(HERE / 'static' / name)
            a, b = langscan.script_span(html)
            allowed = set(raw.get(name) or ())
            left = [(html.count('\n', 0, p['start']) + 1, p['text']) for p in langscan.js_pieces(html, a, b)
                    if not p['call'] and not p['key'] and p['text'] not in allowed]
            self.assertEqual(left, [], '%s: текст не обёрнут T() и не назван в raw.json' % name)

    def test_raw_list_has_no_stale_entries(self):
        """В raw.json нет записей о тексте, которого в файле уже нет."""
        for name, texts in raw_list().items():
            path = HERE / name if name.endswith('.py') else HERE / 'static' / name
            src = read(path)
            if name.endswith('.py'):
                have = {lit['text'] for lit in langscan.py_literals(src)}
            else:
                a, b = langscan.script_span(src)
                have = {p['text'] for p in langscan.js_pieces(src, a, b)}
            self.assertEqual([t for t in texts if t not in have], [], name)

    def test_static_markup_is_translated_at_start(self):
        """Текст в неизменной разметке страницы помечен data-t: его переводит запуск страницы."""
        for name in PAGES:
            html = read(HERE / 'static' / name)
            for m in langscan.markup_texts(html):
                tag = html[html.rfind('<', 0, m['start']):m['start']]
                self.assertIn('data-t', tag, '%s: «%s»' % (name, m['text']))


class ShapeTest(unittest.TestCase):
    def test_translation_takes_the_same_values(self):
        """Перевод подставляет то же, что русский текст: %s и %d — в том же порядке, {0} — тот же набор."""
        for lang in i18n.languages():
            if lang['code'] == i18n.SOURCE:
                continue
            for key, text in i18n.table(lang['code'])['texts'].items():
                if '|' in i18n.bare(key) and '%' not in key and '{' not in key:
                    continue
                want, got = i18n.shape(i18n.bare(key)), i18n.shape(text)
                if not want[0] and '%%' not in key:
                    # у текста нет подстановок вида %s: знак процента в переводе — просто текст («12% des …»)
                    got = ([], got[1])
                self.assertEqual(got, want, '%s: %r -> %r' % (lang['code'], key, text))

    def test_plural_forms(self):
        """Ключ с формами числа: в коде три русские формы, в переводе — столько, сколько у правила языка."""
        keys = [k for k in code_keys() if '|' in i18n.bare(k)]
        self.assertTrue(keys)
        for key in keys:
            self.assertEqual(len(i18n.bare(key).split('|')), 3, key)
        for lang in i18n.languages():
            tab = i18n.table(lang['code'])
            self.assertIn(tab.get('plural'), i18n.PLURALS, lang['code'])
            if lang['code'] == i18n.SOURCE:
                continue
            for key in keys:
                self.assertEqual(len(tab['texts'][key].split('|')), i18n.PLURALS[tab['plural']][0], '%s: %r' % (lang['code'], key))

    def test_plural_rules(self):
        ru = lambda n: str(i18n.plural(n, 'шаг|шага|шагов'))      # noqa: E731
        self.assertEqual([ru(n) for n in (1, 2, 5, 11, 21, 22, 25, 111)],
                         ['шаг', 'шага', 'шагов', 'шагов', 'шаг', 'шага', 'шагов', 'шагов'])
        en = lambda n: i18n.to(i18n.plural(n, 'шаг|шага|шагов'), 'en')      # noqa: E731
        self.assertEqual([en(n) for n in (0, 1, 2, 11, 21)], ['steps', 'step', 'steps', 'steps', 'steps'])

    def test_pages_know_the_same_plural_rules(self):
        """Правила числа в коде страниц — те же, что у программы."""
        for name in PAGES:
            html = read(HERE / 'static' / name)
            block = html[html.index('const PLURALS = {'):html.index('// Форма слова для числа')]
            self.assertEqual(set(re.findall(r'^  (\w+):', block, re.M)), set(i18n.PLURALS), name)

    def test_translations_are_safe_in_markup(self):
        """Перевод вставляется в разметку и в подсказки (title="…"): знаков разметки в нём нет."""
        for lang in i18n.languages():
            tab = i18n.table(lang['code'])
            for key, text in list(tab['texts'].items()) + list(tab['plan'].items()):
                self.assertFalse(set('<>"') & set(text) - set(i18n.bare(key)), '%s: %r -> %r' % (lang['code'], key, text))

    def test_patterns_compile(self):
        for lang in i18n.languages():
            tab = i18n.table(lang['code'])
            for rx, tmpl in tab.get('patterns') or []:
                groups = re.compile(rx).groups
                self.assertEqual(sorted(set(i18n._FIELD.findall(tmpl))), [str(n) for n in range(groups)], '%s: %s' % (lang['code'], rx))


class TextTest(unittest.TestCase):
    def test_text_is_a_russian_string(self):
        """Текст программы в расчётах — обычная русская строка: сравнения, ключи, JSON не меняются."""
        t = tr('с шага «%s»') % 'Клирфелл'
        self.assertEqual(t, 'с шага «Клирфелл»')
        self.assertEqual({t: 1}['с шага «Клирфелл»'], 1)
        self.assertEqual(json.dumps({'a': t}, ensure_ascii=False), '{"a": "с шага «Клирфелл»"}')
        self.assertEqual(tr('цель##время'), 'цель')                  # пометка в текст не входит
        self.assertIsInstance(t, str)

    def test_render_keeps_source_language_untouched(self):
        """Для русского состояние страницы отдаётся как есть — тот же объект, без единой перемены."""
        data = {'a': [tr('позже'), {'b': tr('Акт %s') % 2}], 'c': 'Гремящий скипетр (Rattling Sceptre)'}
        self.assertIs(i18n.render(data, 'ru'), data)

    def test_text_in_another_language(self):
        self.assertEqual(i18n.to(tr('с шага «%s»') % 'X', 'en'), 'from step “X”')
        self.assertEqual(i18n.to(tr('позже') + ' · ' + tr('с %d уровня') % 14, 'en'), 'later · from level 14')
        self.assertEqual(i18n.to(tr('Шаг «%s»: фильтра «%s» нет в игре') % ('a', 'b'), 'en'), 'Step “a”: the filter “b” is not in the game')
        self.assertEqual(i18n.to(i18n.join(', ', [tr('город'), tr('зона %d') % 3]), 'en'), 'town, zone 3')
        self.assertEqual(i18n.to(tr('цель##время'), 'en'), 'target')
        self.assertEqual(i18n.to(tr('цель'), 'en'), 'goal')
        # текст без перевода остаётся русским, а не теряется
        self.assertEqual(i18n.to(tr('такого ключа в переводе нет'), 'en'), 'такого ключа в переводе нет')
        self.assertEqual(i18n.to('обычная строка', 'en'), 'обычная строка')

    def test_missing_translation_falls_back_to_english(self):
        """Текст добавили в код, а на какой-то язык ещё не перевели: на этом языке он выходит по-английски (понятнее
        русского) — и в тексте программы, и в словаре страницы."""
        import shutil
        import tempfile
        keep = i18n.LANG_DIR
        with tempfile.TemporaryDirectory() as d:
            shutil.copy(keep / 'en.json', d)
            (Path(d) / 'xx.json').write_text(json.dumps({'lang': 'xx', 'name': 'X', 'plural': 'none', 'quotes': '',
                                                         'locale': 'xx', 'texts': {'позже': 'later-x'}}), encoding='utf-8')
            i18n.LANG_DIR = Path(d)
            try:
                self.assertEqual(i18n.to(tr('позже'), 'xx'), 'later-x')                       # свой перевод
                self.assertEqual(i18n.to(tr('с %d уровня') % 14, 'xx'), 'from level 14')       # нет своего — английский
                self.assertEqual(i18n.to(i18n.plural(3, 'шаг|шага|шагов'), 'xx'), 'steps')     # и число по-английски
                words = i18n.page('xx')['texts']
                self.assertEqual((words['позже'], words['с %d уровня']), ('later-x', 'from level %d'))
                self.assertEqual(i18n.Names('xx').of('любой'), 'any')                         # слово из файла плана
            finally:
                i18n.LANG_DIR = keep
                i18n._tables.pop('xx', None)

    def test_filter_names_are_not_translated(self):
        """Название фильтра дал его автор на сайте: совпади оно со словом программы («Карты»), оно не переводится —
        ни в тексте программы, ни на странице, где переводятся названия из плана."""
        names = i18n.Names('en')
        self.assertEqual(names.of('Карты'), 'Maps')                          # слово программы переводится…
        self.assertEqual(i18n.to(tr('Фильтр: %s') % i18n.Raw('Карты'), 'en', names), 'Filter: Карты')   # …а название фильтра — нет
        out = i18n.render({'filter': {'name': i18n.Raw('Карты'), 'other': 'Карты'}}, 'en', names, plain=True)
        self.assertEqual(out, {'filter': {'name': 'Карты', 'other': 'Maps'}})
        self.assertIs(type(out['filter']['name']), str)

    def test_render_for_the_editor_keeps_plan_records(self):
        """Редактору плана тексты программы отдаются на его языке, а записи плана — как в файлах."""
        names = i18n.Names('en')
        data = {'findings': [{'text': tr('Этап «%s» записан дважды') % 'start'}],
                'goals': [{'title': 'Гремящий скипетр (Rattling Sceptre)', 'note': 'любой'}]}
        out = i18n.render(data, 'en', names)
        self.assertEqual(out['findings'][0]['text'], 'Stage “start” is written twice')
        self.assertEqual(out['goals'], data['goals'])


class NamesTest(unittest.TestCase):
    CAT = {'lang': {'ru': {'bases': {'Rattling Sceptre': 'Гремящий скипетр'}, 'gems': {'Frost Bomb': 'Морозная бомба'},
                           'heroClasses': {'Sorceress': 'Чародейка'}, 'classes': {'Сапоги': 'Boots'},
                           'statNames': {'spirit': ['Дух', 'Дух']}},
                    'en': {'bases': {'Rattling Sceptre': 'Rattling Sceptre'}, 'statNames': {'spirit': ['Spirit', 'Spirit']}}},
           'areas': {'G1_2': {'name': 'Clearfell'}}}

    def test_game_name_format(self):
        """Название из игры: по-русски — с английским в скобках, по-английски — только английское."""
        self.assertEqual(i18n.game_name('Гремящий скипетр', 'Rattling Sceptre', 'ru'), 'Гремящий скипетр (Rattling Sceptre)')
        self.assertEqual(i18n.game_name('Гремящий скипетр', 'Rattling Sceptre', 'en'), 'Rattling Sceptre')
        self.assertEqual(i18n.game_name(None, 'Kelari', 'ru'), 'Kelari')            # русского названия в данных нет
        self.assertEqual(i18n.game_name('Rattling Sceptre', 'Rattling Sceptre', 'ru'), 'Rattling Sceptre')

    def test_plan_names_in_english(self):
        n = i18n.Names('en', self.CAT, {'G1_2': 'Клирфелл'})
        for ru, en in (
                ('Гремящий скипетр (Rattling Sceptre)', 'Rattling Sceptre'),
                ('Ростовой щит (Tower Shield): жёлтый', 'Tower Shield: жёлтый'),                 # своё уточнение автора остаётся
                ('Призрак: Заряженный подвижник (Spectre: Powered Zealot)', 'Spectre: Powered Zealot'),
                ('Дрейвен, претор Вечных (Draven, the Eternal Praetor)', 'Draven, the Eternal Praetor'),
                ('Акулий плавник (Shark Fin) → Каймана (Kaimana)', 'Shark Fin → Kaimana'),
                ('Балбала Изменница (Balbala, the Traitor): Бария Балбалы (Balbala\'s Barya)', 'Balbala, the Traitor: Balbala\'s Barya'),
                ('уровень камня: 3 → Инфекция (Contagion)', 'gem level: 3 → Contagion'),
                ('Неогранённый камень умения 11–12 (Uncut Skill Gem)', 'Неогранённый камень умения 11–12 (Uncut Skill Gem)'),
                ('Бейра из Гнилой стаи (Beira of the Rotten Pack): +10% к сопротивлению холоду', 'Beira of the Rotten Pack: +10% Cold Resistance'),
                ('любой', 'any'), ('Оружие', 'Weapon'), ('вторая рука', 'off hand'), ('кольцо 1', 'ring 1'),
                ('от 120', 'from 120'), ('от +2', 'from +2'), ('от 75%', 'from 75%'), ('7 уровень героя', 'Hero level 7'),
                ('Клирфелл', 'Clearfell'), ('Клирфелл · зона 2', 'Clearfell · zone 2'), ('Чародейка', 'Sorceress'),
                ('Гремящий скипетр', 'Rattling Sceptre'), ('Сапоги', 'Boots'), ('Дух', 'Spirit'), ('Оружие, Шлем', 'Weapon, Helmet'),
                ('Забрать второй камень умения', 'Забрать второй камень умения'),                 # текст автора — как записан
                ('Rattling Sceptre', 'Rattling Sceptre')):
            self.assertEqual(n.of(ru), en)

    def test_plan_names_in_another_game_language(self):
        """На другом языке игры название из плана — названием игры на этом языке: пара — «Местное (English)»,
        русское без пары — местным без пары; чего игра на этом языке не знает — английским."""
        cat = {'lang': dict(self.CAT['lang'], de={
            'bases': {'Rattling Sceptre': 'Rasselndes Zepter'}, 'gems': {'Frost Bomb': 'Frostbombe'},
            'heroClasses': {'Sorceress': 'Zauberin'}, 'classes': {'Zepter': 'Sceptre'},
            'statNames': {'spirit': ['Wille', 'Wille']}, 'areas': {'G1_2': 'Lichtfall'}}),
            'areas': self.CAT['areas']}
        cat['lang']['ru'] = dict(cat['lang']['ru'], classes={'Скипетры': 'Sceptre'})
        pack = {'names': {'Draven, the Eternal Praetor': 'Draven, der Ewige Prätor', 'Spectre': 'Gespenst',
                          'Powered Zealot': 'Angetriebener Zelot'}, 'nodes': {}}
        n = i18n.Names('de', cat, {'G1_2': 'Клирфелл'}, pack)
        for ru, de in (
                ('Гремящий скипетр (Rattling Sceptre)', 'Rasselndes Zepter (Rattling Sceptre)'),
                ('Дрейвен, претор Вечных (Draven, the Eternal Praetor)', 'Draven, der Ewige Prätor (Draven, the Eternal Praetor)'),
                ('Призрак: Заряженный подвижник (Spectre: Powered Zealot)', 'Gespenst: Angetriebener Zelot (Spectre: Powered Zealot)'),
                ('Кира (Kira)', 'Kira'),                                          # игра на этом языке его не знает
                ('Гремящий скипетр', 'Rasselndes Zepter'), ('Чародейка', 'Zauberin'), ('Скипетры', 'Zepter'),
                ('Клирфелл', 'Lichtfall'), ('Дух', 'Wille'),
                ('Забрать второй камень умения', 'Забрать второй камень умения')):
            self.assertEqual(n.of(ru), de)
        # редактор показывает пары сам: ему — названия на языке страницы тех пар, что есть в его данных
        view = {'goals': [{'title': 'Морозная бомба (Frost Bomb)'}, {'title': 'Кира (Kira)'}], 'x': 'Дух'}
        self.assertEqual(n.game_names(view), {'Frost Bomb': 'Frostbombe'})
        self.assertEqual(i18n.Names('en', cat, None, pack).game_names(view), {})

    def test_zone_named_by_a_client_of_another_language(self):
        """Лог нерусского клиента называет зону по-своему, а план — словами игры по-русски: шаг плана «Клирфелл» всё равно
        показывается на языке страницы. Раньше название из лога вытесняло русское — и шаг оставался русским."""
        cat = {'lang': {'ru': {'areas': {'G1_2': 'Клирфелл'}}, 'en': {}, 'de': {'areas': {'G1_2': 'Lichtfall'}}},
               'areas': {'G1_2': {'name': 'Clearfell'}}}
        for client in ({'G1_2': 'Clearfell'}, {'G1_2': 'Lichtfall'}, {'G1_2': 'Клирфелл'}, None):
            self.assertEqual(i18n.Names('en', cat, client).of('Клирфелл'), 'Clearfell', client)
            self.assertEqual(i18n.Names('de', cat, client).of('Клирфелл'), 'Lichtfall', client)
            self.assertEqual(i18n.Names('de', cat, client).of('Клирфелл · дерево'), 'Lichtfall · Baum', client)

    def test_author_note_whole_or_as_written(self):
        """Заметка автора переводится только целиком — если её перевод есть среди слов плана в файле языка; нет перевода —
        как записана, и названия внутри неё по одному не переводятся (заметка чужого плана — на языке своего автора)."""
        names = i18n.Names('en')
        word = next(k for k in i18n.table('en')['plan'] if ' ' in k)
        view = {'goal': {'note': word, 'other': {'note': 'Сфера превращения (Orb of Transmutation) на белую базу'}}}
        out = i18n.render(view, 'en', names, plain=True)
        self.assertEqual(out['goal']['note'], i18n.table('en')['plan'][word])
        self.assertEqual(out['goal']['other']['note'], 'Сфера превращения (Orb of Transmutation) на белую базу')

    def test_game_stat_line_in_page_language(self):
        """Текст свойства игры (вариант награды, строка аффикса в заметке) — словами игры на языке страницы: по описанию
        свойства из файлов игры; знак, разброс «61–73» и порядок мест шаблона сохраняются."""
        ru = {'charm_duration_+%': ['{0}% увеличение длительности эффекта оберега', '{0}% уменьшение длительности эффекта оберега'],
              'local_energy_shield': ['{0:+d} к максимуму энергетического щита'],
              'two': ['{0}% урона и {1} к силе']}
        de = {'charm_duration_+%': ['{0}% verlängerte Phiolen-Wirkdauer', '{0}% verkürzte Phiolen-Wirkdauer'],
              'local_energy_shield': ['{0:+d} zu maximalem Energieschild'],
              'two': ['{1} zu Stärke und {0}% Schaden']}
        n = i18n.Names('de', stats=(ru, de))
        self.assertEqual(n.stat('30% увеличение длительности эффекта оберега'), '30% verlängerte Phiolen-Wirkdauer')
        self.assertEqual(n.stat('30% уменьшение длительности эффекта оберега'), '30% verkürzte Phiolen-Wirkdauer')
        self.assertEqual(n.stat('+61–73 к максимуму энергетического щита'), '+61–73 zu maximalem Energieschild')
        self.assertEqual(n.stat('15% урона и 7 к силе'), '7 zu Stärke und 15% Schaden')
        self.assertIsNone(n.stat('урон без числа'))
        self.assertEqual(n.of('Медальон: 30% увеличение длительности эффекта оберега'), 'Медальон: 30% verlängerte Phiolen-Wirkdauer')

    def test_skill_name_made_by_a_game_template(self):
        """Название умения, которое игра собирает по шаблону («Spectre: {0}»), — шаблоном языка страницы и названием
        монстра на этом языке."""
        cat = {'lang': {'ru': {}, 'de': {'gems': {'Spectre: {0}': 'Schemen: {0}'}}}, 'areas': {}}
        pack = {'names': {'Powered Zealot': 'Angetriebener Eiferer'}, 'nodes': {}}
        n = i18n.Names('de', cat, None, pack)
        self.assertEqual(n.of('Призрак: Заряженный подвижник (Spectre: Powered Zealot)'),
                         'Schemen: Angetriebener Eiferer (Spectre: Powered Zealot)')

    def test_composite_name_in_quotes(self):
        """Составное название в кавычках («вместо «Карты · Атлас»») — по частям, как вне кавычек."""
        self.assertEqual(i18n.Names('en').of('вместо «Карты · Атлас»'), 'вместо «Maps · Atlas»')

    def test_names_inside_program_text(self):
        """Название, подставленное в текст программы, показывается по тому же правилу."""
        n = i18n.Names('en', self.CAT, {'G1_2': 'Клирфелл'})
        self.assertEqual(i18n.to(tr('с шага «%s»') % 'Клирфелл', 'en', n), 'from step “Clearfell”')
        self.assertEqual(i18n.to(tr('Награда: %s') % 'Гремящий скипетр (Rattling Sceptre)', 'en', n), 'Reward: Rattling Sceptre')
        self.assertEqual(i18n.to(tr('слот «%s»') % 'Вторая рука', 'en', n), 'slot “Off hand”')

    def test_run_page_state_in_english(self):
        """Состояние страницы забега: тексты программы и названия — по-английски, тексты автора и коды — как были."""
        n = i18n.Names('en', self.CAT, {'G1_2': 'Клирфелл'})
        view = {'step': {'id': 'clearfell', 'name': 'Клирфелл', 'act': tr('Акт %s') % '1',
                         'goals': [{'id': 'g', 'title': 'Морозная бомба (Frost Bomb)', 'kind': tr('умение'), 'note': 'взять сразу',
                                    'since': tr('с %d уровня') % 10, 'attr': 'инт',
                                    'fact': i18n.join(' · ', [tr('награду выдают в городе: %s') % 'Клирфелл',
                                                              tr('сначала: %s') % i18n.join(', ', ['Морозная бомба (Frost Bomb)'])])}]},
                'history': [{'text': '%s · %s' % ('Клирфелл', tr('зона %d') % 2)}]}
        out = i18n.render(view, 'en', n, plain=True)
        self.assertEqual(out['step']['name'], 'Clearfell')
        self.assertEqual(out['step']['act'], 'Act 1')
        self.assertEqual(out['step']['goals'][0], {'id': 'g', 'title': 'Frost Bomb', 'kind': 'skill', 'note': 'взять сразу',
                                                   'since': 'from level 10', 'attr': 'инт',
                                                   'fact': 'reward given in town: Clearfell · first: Frost Bomb'})
        # текст программы, вставленный в обычную строку, узнаётся по своему шаблону
        self.assertEqual(out['history'][0]['text'], 'Clearfell · zone 2')
        self.assertEqual(view['step']['name'], 'Клирфелл')          # сами данные расчёта не тронуты


if __name__ == '__main__':
    unittest.main()
