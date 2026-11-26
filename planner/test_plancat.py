# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Sergei Labutin
# Additional terms under GPL-3.0 section 7: see NOTICE.md
"""Каталог одобренных планов (plancat.py): подпись каталога, сверка файла плана, «Поставить» / «Обновить» в
программе, обновление посреди прохождения, план для другой игры, враждебный каталог. Настоящей сети нет: «сайт» —
словарь адрес -> байты (Site.fetch). Подписывает openssl (из PATH или Git для Windows), проверяет Windows (bcrypt.dll).

Запуск: python -m unittest planner.test_plancat
"""
import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import desktop  # noqa: E402
import plancat  # noqa: E402
import planlib  # noqa: E402
import signed  # noqa: E402
import update  # noqa: E402
from test_planlib import CHAR_SCREEN, Lib, ROUTE, area, build, ln, text  # noqa: E402
from test_update import OPENSSL, Key  # noqa: E402

HAVE = sys.platform == 'win32' and bool(OPENSSL)
BASE = 'https://poe2.labutin.gg/plans/'


def sha(data):
    return hashlib.sha256(data).hexdigest()


class Site:
    """Подставной сайт: адрес -> байты. Нет адреса — ответ 404; больше предела — NetError big. Помнит запросы."""

    def __init__(self):
        self.files, self.asked = {}, []

    def fetch(self, url, limit, timeout):
        self.asked.append(url)
        if url not in self.files:
            raise update.NetError('http', 404)
        data = self.files[url]
        if isinstance(data, Exception):
            raise data
        if len(data) > limit:
            raise update.NetError('big', len(data))
        return data


def entry(uid, version, data, **over):
    """Запись каталога о файле плана data (байты), как её пишет инструмент одобрения."""
    e = {'uid': uid, 'version': version, 'title': {'ru': 'План %s' % uid, 'en': 'Plan %s' % uid},
         'author': {'name': 'Автор плана', 'url': 'https://example.org/author'}, 'game': '0.5.5', 'class': 'Sorceress',
         'ascendancy': 'Disciple of Varashta', 'tags': ['hc', 'ssf'], 'langs': ['ru'],
         'summary': {'ru': 'О плане', 'en': 'About the plan'}, 'changed': {'ru': 'Что нового %d' % version, 'en': 'New %d' % version},
         'published': '2026-11-%02d' % (20 + version),
         'file': {'url': '%s%s/%d.plan' % (BASE, uid, version), 'size': len(data), 'sha256': sha(data)}}
    e.update(over)
    return e


def index(*entries, **over):
    d = {'format': plancat.FORMAT, 'v': 1, 'updated': '2026-11-26', 'plans': list(entries)}
    d.update(over)
    return (json.dumps(d, ensure_ascii=False, indent=1) + '\n').encode('utf-8')


def plan_file(uid, title, steps=None, goal='bomb'):
    """Файл плана (байты, как его пишет программа): маршрут ROUTE (или со своими шагами) и билд с названием title."""
    route = dict(ROUTE, steps=steps) if steps is not None else ROUTE
    data = {'format': planlib.FORMAT, 'version': 1, 'uid': uid, 'title': title, 'groups': [],
            'route': text(route), 'build': text(build(title, goal=goal))}
    return planlib.bundle_bytes(data)


@unittest.skipUnless(HAVE, 'нужны Windows (bcrypt.dll) и openssl')
class IndexTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.key = Key(Path(cls.tmp.name))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_signature_right_foreign_changed(self):
        data = index(entry('aaa111', 1, b'x' * 10))
        got = plancat.read_index(data, self.key.sign(data), self.key.point)
        self.assertEqual([(e['uid'], e['version']) for e in got['plans']], [('aaa111', 1)])
        (Path(self.tmp.name) / 'foreign').mkdir(exist_ok=True)
        foreign = Key(Path(self.tmp.name) / 'foreign')
        with self.assertRaises(plancat.Refused) as cm:            # подписан чужим ключом
            plancat.read_index(data, foreign.sign(data), self.key.point)
        self.assertEqual(cm.exception.code, 'sig')
        changed = data.replace(b'"version": 1', b'"version": 2')  # файл изменён после подписи
        with self.assertRaises(plancat.Refused) as cm:
            plancat.read_index(changed, self.key.sign(data), self.key.point)
        self.assertEqual(cm.exception.code, 'sig')
        for sig in (b'', b'not base64!', b'AAAA'):
            with self.assertRaises(plancat.Refused) as cm:
                plancat.read_index(data, sig, self.key.point)
            self.assertEqual(cm.exception.code, 'sig')
        with self.assertRaises(plancat.Refused) as cm:            # ключа в сборке нет — проверять нечем
            plancat.read_index(data, self.key.sign(data), None)
        self.assertEqual(cm.exception.code, 'nokey')
        # подпись проверяется тем же кодом, что у обновления программы
        self.assertIs(update.Refused, signed.Refused)
        self.assertIs(update.verify, signed.verify)

    def test_wrong_documents_are_refused(self):
        for doc in (b'not json', b'[]', index(format='other'), index(v=2), index(v=True), index(plans={})):
            with self.assertRaises(plancat.Refused) as cm:
                plancat.read_index(doc, self.key.sign(doc), self.key.point)
            self.assertEqual(cm.exception.code, 'format', doc[:40])

    def test_unknown_fields_skipped_and_bad_records_dropped(self):
        good = entry('aaa111', 3, b'x' * 10, extra={'any': 'thing'})
        bad = [entry('BAD', 1, b'x'), entry('bbb222', 0, b'x'), entry('ccc333', True, b'x'), entry('ddd444', 1, b'x', title={}),
               entry('eee555', 1, b'x', author={'url': 'https://x.org'}),
               entry('fff666', 1, b'x', file={'url': 'http://example.org/a.plan', 'size': 1, 'sha256': 'a' * 64}),
               entry('ggg777', 1, b'x', file={'url': BASE + 'g/1.plan', 'size': 0, 'sha256': 'a' * 64}),
               entry('hhh888', 1, b'x', file={'url': BASE + 'h/1.plan', 'size': 5, 'sha256': 'xyz'}), 'not a record']
        dup = entry('aaa111', 9, b'y')
        data = index(good, *bad, dup, extra=[1, 2])
        got = plancat.read_index(data, self.key.sign(data), self.key.point)
        self.assertEqual([(e['uid'], e['version']) for e in got['plans']], [('aaa111', 3)])     # повтор метки — первая
        e = got['plans'][0]
        self.assertEqual((e['cls'], e['asc'], e['game'], e['tags'], e['published']),
                         ('Sorceress', 'Disciple of Varashta', '0.5.5', ['hc', 'ssf'], '2026-11-23'))
        self.assertNotIn('extra', e)

    def test_hostile_texts_stay_text_and_links_only_http(self):
        """Разметка в названии, имени автора и «что изменилось» остаётся текстом (страница выводит её как текст);
        управляющие знаки и смена направления письма убраны; ссылка автора — только http(s)."""
        hostile = '<img src=x onerror=alert(1)>«План»\u202e\u0007'
        e1 = entry('aaa111', 1, b'x', title={'ru': hostile, 'en': '<script>alert(1)</script>'},
                   author={'name': '<b>Автор</b>\u2066', 'url': 'javascript:alert(1)'},
                   changed={'ru': '"><svg onload=alert(1)>'}, summary={'ru': 'a\nb\tc'})
        e2 = entry('bbb222', 1, b'x', author={'name': 'Другой', 'url': 'http://example.org/me'})
        e3 = entry('ccc333', 1, b'x', author={'name': 'Третий', 'url': 'https://user:pw@example.org/'},
                   game='<0.5.5>', ascendancy='<b>', **{'class': 'x"y'})
        data = index(e1, e2, e3)
        got = {e['uid']: e for e in plancat.read_index(data, self.key.sign(data), self.key.point)['plans']}
        a = got['aaa111']
        self.assertEqual(a['title']['ru'], '<img src=x onerror=alert(1)>«План»')
        self.assertEqual(a['author'], {'name': '<b>Автор</b>'})             # javascript: — не ссылка
        self.assertEqual((a['changed']['ru'], a['summary']['ru']), ('"><svg onload=alert(1)>', 'a b c'))
        self.assertEqual(got['bbb222']['author']['url'], 'http://example.org/me')
        self.assertNotIn('url', got['ccc333']['author'])                    # имя и пароль в адресе — не ссылка
        self.assertEqual((got['ccc333']['game'], got['ccc333']['asc'], got['ccc333']['cls']), ('', '', ''))
        for url in ('javascript:alert(1)', 'data:text/html,x', 'file:///c:/x', 'ftp://x.org', ' https://x.org', 'https://',
                    'https://x.org/a b', 'https://x.org:abc/', 'vbscript:x', 'https://ок.рф'):
            self.assertIsNone(plancat.web_url(url), url)
        self.assertEqual(plancat.web_url('https://poe2.labutin.gg/a?b=c#d'), 'https://poe2.labutin.gg/a?b=c#d')


class PlanFileTest(unittest.TestCase):
    def test_file_must_match_the_catalogue(self):
        data = plan_file('aaa111', 'План')
        e = plancat._entry(entry('aaa111', 1, data))
        self.assertEqual(plancat.read_plan(data, e)['uid'], 'aaa111')
        cases = {'size': data + b' ', 'hash': data.replace(b'"version": 1', b'"version": 2')}
        for code, body in cases.items():
            with self.assertRaises(plancat.Refused) as cm:
                plancat.read_plan(body, e)
            self.assertEqual(cm.exception.code, code)
        other = plan_file('bbb222', 'План')                               # файл другого плана — под чужой записью
        with self.assertRaises(plancat.Refused) as cm:
            plancat.read_plan(other, plancat._entry(entry('aaa111', 1, other)))
        self.assertEqual(cm.exception.code, 'uid')
        junk = b'{"format": "x"}'
        with self.assertRaises(plancat.Refused) as cm:
            plancat.read_plan(junk, plancat._entry(entry('aaa111', 1, junk)))
        self.assertEqual(cm.exception.code, 'format')

    def test_bundle_bytes_are_the_same_for_the_same_plan(self):
        """Файл плана одного и того же плана — всегда те же байты: по ним каталог узнаёт свою версию в библиотеке."""
        with tempfile.TemporaryDirectory() as tmp:
            data = json.loads(plan_file('aaa111', 'План').decode('utf-8'))
            pid = planlib.add(Path(tmp), data, 'x.plan.json')
            self.assertEqual(planlib.bundle_bytes(planlib.bundle(Path(tmp), pid)), plan_file('aaa111', 'План'))
            self.assertEqual(planlib.bundle_sha(Path(tmp), pid), sha(plan_file('aaa111', 'План')))
            self.assertIsNone(planlib.bundle_sha(Path(tmp), 'nope'))

    def test_offline_server_does_not_reach_the_network(self):
        """Сервер с --offline (проверки страниц): каталог не спрашивается — «нет связи», наружу ничего не уходит."""
        import server
        self.assertTrue(server.options(['--offline']).offline)
        self.assertFalse(server.options([]).offline)
        cat = plancat.Catalog(b'x' * 64, fetch=plancat.offline, say=lambda t: None)
        self.assertFalse(cat.check())
        self.assertEqual((cat.last['code'], cat.data), ('net', None))

    def test_one_address_in_the_program(self):
        """В коде каталога записан ОДИН адрес — каталог на poe2.labutin.gg; адреса файлов — только в подписанном каталоге."""
        import ast
        tree = ast.parse((HERE / 'plancat.py').read_text(encoding='utf-8'))
        docs = {id(n.body[0].value) for n in ast.walk(tree)
                if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef)) and n.body
                and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
        found = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)
                 and id(n) not in docs and n.value.partition('://')[2]}
        self.assertEqual(found, {plancat.INDEX_URL})
        self.assertEqual(plancat.SIG_URL, plancat.INDEX_URL + '.sig')


@unittest.skipUnless(HAVE, 'нужны Windows (bcrypt.dll) и openssl')
class CatalogCheckTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.key = Key(Path(self.tmp.name))
        self.site = Site()
        self.now = [1000.0]
        self.cat = plancat.Catalog(self.key.point, fetch=self.site.fetch, clock=lambda: self.now[0], say=lambda t: None)

    def tearDown(self):
        self.tmp.cleanup()

    def publish(self, data, sig=None):
        self.site.files[plancat.INDEX_URL] = data
        self.site.files[plancat.SIG_URL] = self.key.sign(data) if sig is None else sig

    def test_check_keeps_the_last_good_catalogue(self):
        good = index(entry('aaa111', 1, b'x'))
        self.publish(good)
        self.assertTrue(self.cat.check())
        self.assertEqual((self.cat.last['code'], self.cat.got, len(self.cat.data['plans'])), ('ok', 1000.0, 1))
        self.assertEqual(self.site.asked, [plancat.INDEX_URL, plancat.SIG_URL])     # только каталог и подпись
        # «Каталог» открыли снова через полминуты — не спрашиваем; через минуту — спрашиваем
        self.now[0] += 30
        self.assertTrue(self.cat.check(plancat.FRESH))
        self.assertEqual(len(self.site.asked), 2)
        self.now[0] += 31
        # подпись не сошлась — каталог не принят, прежний остаётся
        self.publish(index(entry('bbb222', 1, b'x')), sig=self.key.sign(good))
        self.assertTrue(self.cat.check(plancat.FRESH))
        self.assertEqual((self.cat.last['code'], [e['uid'] for e in self.cat.data['plans']]), ('sig', ['aaa111']))
        # сайт не ответил — не дозвались (повторить скоро), каталог прежний
        self.site.files[plancat.INDEX_URL] = update.NetError('net', 'connect 12029')
        self.assertFalse(self.cat.check())
        self.assertEqual((self.cat.last['code'], self.cat.got), ('net', 1000.0))
        # каталога на сайте ещё нет (404)
        del self.site.files[plancat.INDEX_URL]
        self.assertFalse(self.cat.check())
        self.assertEqual((self.cat.last['code'], self.cat.last['detail']), ('http', 404))

    def test_no_key_no_request(self):
        cat = plancat.Catalog(None, fetch=self.site.fetch, say=lambda t: None)
        self.assertTrue(cat.check())
        self.assertEqual((cat.last['code'], self.site.asked), ('nokey', []))

    def test_plan_file_is_checked_before_use(self):
        data = plan_file('aaa111', 'План')
        e = plancat._entry(entry('aaa111', 1, data))
        self.site.files[e['url']] = data + b'tail'                      # файл больше, чем говорит каталог
        with self.assertRaises(plancat.Refused):
            self.cat.load(e)
        self.site.files[e['url']] = data
        self.assertEqual(self.cat.load(e)['uid'], 'aaa111')


@unittest.skipUnless(HAVE, 'нужны Windows (bcrypt.dll) и openssl')
class ProgramTest(Lib):
    """Каталог в программе: раздел «Каталог» редактора, «Поставить», «Обновить», запись в библиотеке."""

    def setUp(self):
        super().setUp()
        self.key = Key(self.root)
        self.site = Site()
        self.plan('dov', 'HC SSF · DoV')

    def catalog(self, *entries):
        data = index(*entries)
        self.site.files[plancat.INDEX_URL] = data
        self.site.files[plancat.SIG_URL] = self.key.sign(data)

    def offer(self, uid, version, body, **over):
        self.site.files['%s%s/%d.plan' % (BASE, uid, version)] = body
        return entry(uid, version, body, **over)

    def start(self, **more):
        app = super().start(**more)
        app.plancat = plancat.Catalog(self.key.point, fetch=self.site.fetch, say=lambda t: None)
        return app

    def rows(self, app, lang='ru'):
        return {r['uid']: r for r in app.plancat_view(lang)['list']}

    def test_install_update_and_states(self):
        v1 = plan_file('witch01', 'Ведьма')
        self.catalog(self.offer('witch01', 1, v1))
        app = self.start()
        self.assertEqual(app.plancat_view('ru')['list'], [])                  # каталог ещё не спрашивали
        self.assertTrue(app.plancat_check())
        row = self.rows(app)['witch01']
        self.assertEqual((row['state'], row['have'], row['plan'], row['title'], row['author']['name']),
                         ('new', None, None, 'План witch01', 'Автор плана'))
        self.assertEqual((row['cls'], row['asc'], row['game'], row['other']), ('Чародейка', 'Ученица Варашты', '0.5.5', False))
        self.assertEqual(self.rows(app, 'de')['witch01']['cls'], 'Zauberin')    # названия из данных игры на языке страницы
        # «Поставить»: план в библиотеке — полученный (только для просмотра), с версией и автором из каталога
        res = app.plancat_get('witch01')
        self.assertEqual((res['ok'], res['plan'], res['title'], res['version'], res['fresh']), (True, 'vedma', 'Ведьма', 1, True))
        lib = {p['id']: p for p in app.library()}
        self.assertEqual((lib['vedma']['uid'], lib['vedma']['catalog']['version'], lib['vedma']['catalog']['author']),
                         ('witch01', 1, {'name': 'Автор плана', 'url': 'https://example.org/author'}))
        self.assertEqual(lib['vedma']['received']['file'], '')
        self.assertEqual(planlib.bundle_bytes(planlib.bundle(self.plans, 'vedma')), v1)     # тот же план, байт в байт
        self.assertFalse(app.save_plan('vedma', {'title': 'Моя'})['ok'])                    # только для просмотра
        self.assertEqual(self.rows(app)['witch01']['state'], 'have')
        self.assertEqual(app.plancat_get('witch01'), {'ok': False, 'problems': ['этот план уже поставлен — та же версия']})
        # автор виден там, где план выбирают (имя — только из каталога)
        row = next(p for p in app.plans_view()['list'] if p['id'] == 'vedma')
        self.assertEqual((row['catalog']['author']['name'], 'newer' in row), ('Автор плана', False))
        # новая версия в каталоге: у плана «есть новая версия», в каталоге — «Обновить» и что изменилось
        v2 = plan_file('witch01', 'Ведьма 2')
        self.catalog(self.offer('witch01', 2, v2))
        app.plancat_check()
        row = self.rows(app)['witch01']
        self.assertEqual((row['state'], row['have'], row['changed']), ('update', 1, 'Что нового 2'))
        self.assertEqual(next(p for p in app.plans_view()['list'] if p['id'] == 'vedma')['newer'], 2)
        res = app.plancat_get('witch01')
        self.assertEqual((res['ok'], res['plan'], res['version'], res['fresh']), (True, 'vedma', 2, False))
        lib = {p['id']: p for p in app.library()}
        self.assertEqual((sorted(lib), lib['vedma']['title'], lib['vedma']['catalog']['version']),
                         (['dov', 'vedma'], 'Ведьма 2', 2))
        self.assertTrue(list((self.root / 'backup' / 'plans' / 'vedma').iterdir()))        # прежняя версия — в копиях
        # в каталоге версия старее поставленной — не ставится
        self.catalog(self.offer('witch01', 1, v1))
        app.plancat_check()
        self.assertEqual((self.rows(app)['witch01']['state'], self.rows(app)['witch01']['have']), ('older', 2))
        self.assertEqual(app.plancat_get('witch01')['problems'], ['в каталоге версия старее поставленной — не ставится'])
        self.assertEqual({p['id']: p for p in app.library()}['vedma']['catalog']['version'], 2)

    def test_setting_decides_the_automatic_request(self):
        """Список планов в редакторе спрашивает каталог сам, только пока «Проверять обновления» включено; «Спросить
        каталог» спрашивает всегда."""
        self.catalog(self.offer('witch01', 1, plan_file('witch01', 'Ведьма')))
        app = self.start()
        settings = self.root / 'settings.json'
        app.settings_path = settings
        self.assertTrue(app.net_allowed())                                 # настроек нет — можно
        settings.write_text(json.dumps({update.SETTING: False}), encoding='utf-8')
        self.assertFalse(app.net_allowed())
        self.assertFalse(app.plancat_refresh())                            # открыли список — запроса нет
        self.assertEqual((self.site.asked, app.plancat_view('ru')['auto']), ([], False))
        self.assertTrue(app.plancat_refresh(ask=True))                     # «Спросить каталог»
        self.assertEqual(self.site.asked, [plancat.INDEX_URL, plancat.SIG_URL])
        self.assertEqual(list(self.rows(app)), ['witch01'])
        settings.write_text(json.dumps({update.SETTING: True}), encoding='utf-8')
        self.assertTrue(app.plancat_refresh())                             # включено: спрашивает, но не чаще минуты
        self.assertEqual(len(self.site.asked), 2)
        # у окна программы решает её проверка обновлений (Updater.on)
        app.updater = type('Up', (), {'on': False})()
        self.assertFalse(app.net_allowed())
        app.updater.on = True
        self.assertTrue(app.net_allowed())

    def test_own_plan_with_the_same_tag_is_not_touched(self):
        """Свой план с той же меткой (у автора плана) каталог не меняет: «ваш план», «Обновить» нет."""
        body = plan_file('dovuid', 'HC SSF · DoV 2')
        self.catalog(self.offer('dovuid', 5, body))
        app = self.start()
        app.plancat_check()
        self.assertEqual(self.rows(app)['dovuid']['state'], 'own')
        before = (self.plans / 'dov' / 'build.json').read_bytes()
        self.assertEqual(app.plancat_get('dovuid')['problems'], ['в библиотеке ваш план с этой меткой — каталог его не меняет'])
        self.assertEqual((self.plans / 'dov' / 'build.json').read_bytes(), before)
        self.assertNotIn('newer', app.plans_view()['list'][0])

    def test_file_that_does_not_match_is_refused(self):
        body = plan_file('witch01', 'Ведьма')
        e = self.offer('witch01', 1, body)
        self.catalog(e)
        app = self.start()
        app.plancat_check()
        for bad in (body + b' ', body.replace('Ведьма'.encode('utf-8'), 'Ведьмы'.encode('utf-8'))):
            self.site.files[e['file']['url']] = bad
            self.assertEqual(app.plancat_get('witch01'),
                             {'ok': False, 'problems': ['файл плана не сошёлся с каталогом — план не поставлен']})
        self.site.files[e['file']['url']] = update.NetError('net', 'x')
        self.assertEqual(app.plancat_get('witch01')['problems'], ['файл плана не скачан: нет связи с сайтом программы'])
        self.assertEqual([p['id'] for p in app.library()], ['dov'])
        self.assertEqual(app.plancat_get('nope')['problems'], ['этого плана нет в каталоге'])

    def test_plan_for_another_game_is_shown_and_marked(self):
        body = plan_file('witch01', 'Ведьма')
        self.catalog(self.offer('witch01', 1, body, game='0.4.0'))
        app = self.start()
        app.plancat_check()
        row = self.rows(app)['witch01']
        self.assertEqual((row['game'], row['other'], row['state']), ('0.4.0', True, 'new'))
        self.assertTrue(app.plancat_get('witch01')['ok'])

    def test_hostile_catalogue_reaches_the_page_as_text(self):
        body = plan_file('witch01', 'Ведьма')
        self.catalog(self.offer('witch01', 1, body, title={'ru': '<img src=x onerror=alert(1)>'},
                                author={'name': '<script>alert(1)</script>', 'url': 'javascript:alert(1)'},
                                changed={'ru': '"><b>x</b>'}, summary={'ru': '<i>о</i>'}))
        app = self.start()
        app.plancat_check()
        row = self.rows(app)['witch01']
        self.assertEqual((row['title'], row['author'], row['summary']),
                         ('<img src=x onerror=alert(1)>', {'name': '<script>alert(1)</script>'}, '<i>о</i>'))
        # страница автора — только адрес из каталога и только http(s): у этого автора её нет
        opened = []
        app.opener = lambda url: opened.append(url) or True
        self.assertFalse(app.open_author('witch01'))
        self.assertTrue(app.plancat_get('witch01')['ok'])
        self.assertEqual({p['id']: p for p in app.library()}['vedma']['catalog']['author'], {'name': '<script>alert(1)</script>'})
        self.catalog(self.offer('witch01', 1, body))
        app.plancat_check()
        self.assertTrue(app.open_author('witch01'))
        self.assertEqual(opened, ['https://example.org/author'])

    def test_plan_that_came_with_the_program(self):
        """План, пришедший с программой, — полученный; совпал байт в байт с версией каталога — запоминает её и автора;
        не совпал — «Обновить»."""
        data = Path(self.tmp.name) / 'data'
        added = desktop.seed_plans(data, self.plans)
        self.assertEqual(added, ['hc-ssf-dov'])
        lib = planlib.scan(data / 'plans')
        self.assertEqual(lib[0]['manifest']['received']['by'], 'program')
        self.assertEqual(desktop.seed_plans(data, self.plans), [])          # библиотека не пуста — ничего не кладём
        body = planlib.bundle_bytes(planlib.bundle(self.plans, 'dov'))
        self.catalog(self.offer('dovuid', 3, body))
        self.plans = data / 'plans'
        app = self.start()
        self.assertTrue(app.plancat_check())
        row = self.rows(app)['dovuid']
        self.assertEqual((row['state'], row['have'], row['plan']), ('have', 3, 'hc-ssf-dov'))
        rec = {p['id']: p for p in app.library()}['hc-ssf-dov']
        self.assertEqual((rec['catalog']['version'], rec['catalog']['author']['name']), (3, 'Автор плана'))
        # в каталоге другой файл той же версии плана — его не знаем: «Обновить»
        manifest = self.plans / 'hc-ssf-dov' / 'plan.json'
        m = json.loads(manifest.read_text(encoding='utf-8'))
        del m['catalog']
        planlib.write_manifest(manifest, m)
        self.catalog(self.offer('dovuid', 4, plan_file('dovuid', 'HC SSF · DoV')))
        app.plancat_check()
        self.assertEqual(self.rows(app)['dovuid']['state'], 'update')


@unittest.skipUnless(HAVE, 'нужны Windows (bcrypt.dll) и openssl')
class MidRunTest(Lib):
    """Герой посреди прохождения: план обновился из каталога — герой продолжает с того же шага, факты прохождения (в
    его файле) остаются; шаг героя в новой версии переименован или удалён."""

    STEPS = [{'id': 'riverbank', 'zone': 'G1_1', 'name': 'Берег реки', 'notes': []},
             {'id': 'clearfell', 'zone': 'G1_2', 'name': 'Клирфелл', 'notes': []},
             {'id': 'grelwood', 'zone': 'G1_3', 'name': 'Грельвуд', 'notes': []}]

    def setUp(self):
        super().setUp()
        self.key = Key(self.root)
        self.site = Site()

    def publish(self, version, steps):
        body = plan_file('witch01', 'Ведьма', steps=steps)
        url = '%s%s/%d.plan' % (BASE, 'witch01', version)
        self.site.files[url] = body
        data = index(entry('witch01', version, body))
        self.site.files[plancat.INDEX_URL] = data
        self.site.files[plancat.SIG_URL] = self.key.sign(data)

    def test_update_in_the_middle_of_a_run(self):
        self.publish(1, self.STEPS)
        cat = plancat.Catalog(self.key.point, fetch=self.site.fetch, say=lambda t: None)
        # план из каталога — в библиотеке; герой идёт по нему: Берег реки → Клирфелл
        self.plans.mkdir()
        cat.check()
        pid = planlib.add(self.plans, cat.load(cat.entry('witch01')), '', uid='witch01',
                          extra={'catalog': {'version': 1, 'author': {'name': 'Автор плана'}}})
        app = self.start()
        app.plancat = cat
        hero = app.run.id
        self.assertEqual((app.view()['step']['id'], app.plan_of(hero)), ('clearfell', pid))
        with app.cond:
            self.assertTrue(app.mark('hero-3', 1))                      # факт прохождения — в файле героя
        run_file = app.runs_dir / ('%s.json' % hero)
        marks = json.loads(run_file.read_text(encoding='utf-8'))['marks']
        self.assertEqual([(m['goal'], m['status']) for m in marks], [('hero-3', 1)])

        # версия 2: шаг героя переименован — герой на нём же, отметка на месте
        steps = [dict(s, name='Клирфелл, лагерь') if s['id'] == 'clearfell' else s for s in self.STEPS]
        self.publish(2, steps)
        app.plancat_check()
        res = app.plancat_get('witch01')
        self.assertEqual((res['ok'], res['plan'], res['fresh']), (True, pid, False))
        v = app.view()
        self.assertEqual((v['step']['id'], v['step']['name'], app.plan_of(hero)), ('clearfell', 'Клирфелл, лагерь', pid))
        saved = json.loads(run_file.read_text(encoding='utf-8'))
        self.assertEqual([(m['goal'], m['status']) for m in saved['marks']], [('hero-3', 1)])
        self.assertEqual([s['name'] for s in saved['plan']['steps']][1], 'Клирфелл, лагерь')     # снимок плана — новый
        goal = next(g for g in v['goals'] if g['id'] == 'hero-3') if 'goals' in v else None
        if goal is not None:
            self.assertEqual(goal.get('status'), 1)

        # версия 3: шага героя больше нет — герой на последнем шаге, который узнаёт лог, отметка на месте; следующая
        # зона маршрута — следующий шаг
        self.publish(3, [s for s in self.STEPS if s['id'] != 'clearfell'])
        app.plancat_check()
        self.assertTrue(app.plancat_get('witch01')['ok'])
        self.assertEqual(app.view()['step']['id'], 'riverbank')
        saved = json.loads(run_file.read_text(encoding='utf-8'))
        self.assertEqual([(m['goal'], m['status']) for m in saved['marks']], [('hero-3', 1)])
        self.more_log(area('20:40:00', 3, 'G1_3', 'Грельвуд'))
        with app.cond:
            app.poll_log()
        self.assertEqual(app.view()['step']['id'], 'grelwood')
        # перезапуск программы — то же
        again = self.start()
        self.assertEqual((again.view()['step']['id'], again.plan_of(hero)), ('grelwood', pid))


class BuildCheckTest(Lib):
    def test_bundled_plan_against_the_catalogue(self):
        """Сборка говорит, узнает ли план из комплекта себя в каталоге: та же версия, более старая или ни одна —
        тогда игроки этой сборки увидят «есть новая версия»."""
        import importlib.util          # своим именем: у каталога данных игры тоже есть модуль build
        spec = importlib.util.spec_from_file_location('packaging_build', HERE.parent / 'packaging' / 'build.py')
        build = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(build)
        self.plan('dov', 'HC SSF · DoV')
        site = self.root / 'site' / 'plans'
        (site / 'dovuid').mkdir(parents=True)
        self.assertIsNone(build.catalog_check(self.root, 'dov'))                   # каталога нет
        mine = planlib.bundle_bytes(planlib.bundle(self.plans, 'dov'))
        (site / 'dovuid' / '1.plan').write_bytes(mine)
        other = plan_file('dovuid', 'HC SSF · DoV 2')
        (site / 'dovuid' / '2.plan').write_bytes(other)
        (site / 'index.json').write_bytes(index(entry('dovuid', 1, mine)))
        self.assertEqual(build.catalog_check(self.root, 'dov'), '== plan dov = catalogue version 1')
        (site / 'index.json').write_bytes(index(entry('dovuid', 2, other)))
        self.assertIn('= catalogue version 1 (the catalogue has 2', build.catalog_check(self.root, 'dov'))
        (site / 'dovuid' / '1.plan').write_bytes(other)
        self.assertIn('WARNING: plan dov matches no approved version', build.catalog_check(self.root, 'dov'))
        (site / 'index.json').write_bytes(index(entry('other1', 1, other)))
        self.assertIsNone(build.catalog_check(self.root, 'dov'))                   # плана в каталоге нет


class UpdaterAlsoTest(unittest.TestCase):
    def test_catalogue_is_asked_with_the_update_check_and_obeys_the_setting(self):
        """Каталог спрашивается тем же расписанием, что обновления, и только пока «Проверять обновления» включено."""
        with tempfile.TemporaryDirectory() as tmp:
            for on in (True, False):
                calls = []
                settings = Path(tmp) / ('s%d.json' % on)
                settings.write_text(json.dumps({update.SETTING: on}), encoding='utf-8')
                up = update.Updater('0.5.5.21', Path(tmp) / 'u', settings, None, fetch=lambda *a, **k: b'',
                                    say=lambda t: None)
                up.also.append(lambda: calls.append(1))
                up.also.append(lambda: 1 / 0)                     # неудача каталога не ломает проверку обновлений
                up.wake.wait = lambda timeout=None: setattr(up, 'stopped', True)
                up.run()
                self.assertEqual(calls, [1] if on else [])


if __name__ == '__main__':
    unittest.main()
