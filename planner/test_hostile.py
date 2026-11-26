# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Sergei Labutin
# Additional terms under GPL-3.0 section 7: see NOTICE.md
"""План от незнакомого автора: файл плана с враждебными значениями в каждом поле (hostile.py) либо не принимается
— понятными словами и ничего не записав, — либо принимается и программа его показывает, не падая; запись — только
внутри библиотеки планов; страницы уходят с Content-Security-Policy и меткой ответа в своих скриптах и стилях.

Сами страницы с такими планами проверяет hostile_pages.py (настоящий браузер на пробной странице).

Запуск: python -m unittest planner.test_hostile
"""
import _winapi
import json
import os
import re
import sys
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hostile  # noqa: E402
import planguard  # noqa: E402
import planlib  # noqa: E402
import server  # noqa: E402

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
CATALOG = ROOT / 'catalog' / 'data'
KNOWLEDGE = ROOT / 'knowledge'


def area(t, level, code, name):
    return ('2026/11/11 %s 1 a [DEBUG Client 1] Generating level %d area "%s" with seed 1\n' % (t, level, code)
            + '2026/11/11 %s 1 a [INFO Client 1] [SCENE] Set Source [%s]\n' % (t, name))


class Library(unittest.TestCase):
    """Временная папка: библиотека с одним своим планом (маленький план hostile.base), лог с героем."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.plans = self.root / 'plans'
        self.route, self.build, self.groups = hostile.base()
        self.plans.mkdir()
        pid = planlib.add(self.plans, hostile.bundle(self.route, self.build, self.groups), 'base.plan.json')
        man = self.plans / pid / planlib.MANIFEST
        raw = json.loads(man.read_text(encoding='utf-8'))
        raw.pop('received')                        # свой план игрока: по нему идёт герой
        planlib.write_manifest(man, raw)
        self.log = self.root / 'Client.txt'
        self.log.write_text(area('20:07:03', 1, 'G1_1', 'Берег реки') + area('20:10:55', 2, 'G1_2', 'Клирфелл'),
                            encoding='utf-8')

    def tearDown(self):
        self.tmp.cleanup()

    def start(self):
        lib = planlib.scan(self.plans)
        more = {}
        if (CATALOG / 'current.txt').is_file():
            more['catalog_dir'] = CATALOG
        if KNOWLEDGE.is_dir():
            more['knowledge_dir'] = KNOWLEDGE
        app = server.App(self.log, lib[0]['path'], self.root / 'runs', backup_dir=self.root / 'backup',
                         plans_dir=self.plans, **more)
        with app.cond:
            app.load_plan()
            app.poll_log(initial=True)
            app.use_plan(app.plan_of(app.run.id))
            app.attach_run()
        return app

    def folders(self):
        return sorted(p.name for p in self.plans.iterdir())


class RefusedTest(Library):
    def test_every_hostile_value_is_refused_in_words(self):
        """Каждое поле схемы с каждым враждебным значением — отказ ValueError со словами для игрока: без самого чужого
        значения в нём (ни разметки, ни управляющих знаков, ни длинной строки) и без падения программы."""
        cases = hostile.refused(self.route, self.build, self.groups)
        self.assertGreater(len(cases), 2000)
        fields = {path for _, path, _ in cases}
        self.assertGreater(len(fields), 100)
        for what, path, data in cases:
            with self.subTest(what=what, path=path):
                with self.assertRaises(ValueError) as e:
                    planlib.parse_bundle(data)
                msg = str(e.exception)
                self.assertTrue(msg.strip())
                self.assertLess(len(msg), 1500)
                self.assertNotIn('<x-zz', msg)
                self.assertIsNone(planguard.RE_BAD.search(msg))

    def test_refused_file_writes_nothing(self):
        app = self.start()
        before = self.folders()
        for what, path, data in hostile.refused(self.route, self.build, self.groups)[::25]:
            with self.subTest(what=what, path=path):
                res = app.import_plan({'import': data, 'file': 'x.plan.json'})
                self.assertEqual((res['ok'], res['problems'][0].startswith('план не добавлен: ')), (False, True))
                self.assertEqual(self.folders(), before)

    def test_strange_requests(self):
        app = self.start()
        good = hostile.bundle(self.route, self.build, self.groups)
        for req in ({'import': good, 'file': ['a']}, {'import': good, 'replace': ['x']}, {'import': good, 'replace': '../x'},
                    {'import': good, 'replace': 'nope'}, {'import': None}, {'import': 'x'}):
            with self.subTest(req=str(req)[:80]):
                res = app.import_plan(req)
                self.assertFalse(res['ok'])
        self.assertEqual(len(self.folders()), 1)

    def test_strict_json(self):
        for text in ('{"a": NaN}', '{"a": Infinity}', '{"a": 1, "a": 2}', '[' * 50000 + ']' * 50000):
            with self.assertRaises(planguard.Refused):
                planguard.loads(text, 'маршрут')
        self.assertEqual(planguard.loads('{"a": [1, {"b": "в"}]}', 'маршрут'), {'a': [1, {'b': 'в'}]})


class AcceptedTest(Library):
    def test_hostile_text_is_taken_and_served(self):
        """План, у которого каждое текстовое поле — разметка, кавычки, ссылки javascript: и прочее (то, что проверка
        пропускает), ложится в библиотеку и показывается: состояние «Игры», редактора, «Разбора», список планов —
        JSON без NaN, программа не падает."""
        app = self.start()
        for family, data, name, tags in hostile.text_plans(self.route, self.build, self.groups):
            with self.subTest(family=family):
                res = app.import_plan({'import': data, 'file': name})
                self.assertTrue(res['ok'], res)
                pid = res['plan']
                ok, problems = app.bind_plan(pid)
                self.assertTrue(ok, problems)
                with app.cond:
                    self.assertIsNone(app.plan_error)
                    views = [app.view_json('ru'), app.view_json('en'), app.answer(app.build_view('ru'), 'ru'),
                             json.dumps(app.review_view(), ensure_ascii=False, default=str),
                             json.dumps(app.plans_view(), ensure_ascii=False)]
                for body in views:
                    self.assertNotIn('NaN', body)
                    self.assertNotIn('Infinity', body)
                    json.loads(body)
                # присланный план — только для просмотра: правка редактора в него не пишется
                before = (self.plans / pid / 'build.json').read_bytes()
                self.assertFalse(app.save_plan(pid, {'title': 'Мой'})['ok'])
                self.assertEqual((self.plans / pid / 'build.json').read_bytes(), before)
                # файл плана уходит обратно таким же: его можно отдать другому игроку
                again = planlib.parse_bundle(planlib.bundle(self.plans, pid))
                self.assertEqual(json.loads(again[0]), json.loads(data['route']))

    def test_odd_references_do_not_hang(self):
        """Ссылки, которые редактор не дал бы записать (сам на себя, по кругу, на несуществующий шаг), — замечания
        плана, а не зависание и не падение."""
        app = self.start()
        r, b = json.loads(json.dumps(self.route)), json.loads(json.dumps(self.build))
        b['goals'][1]['for'] = 'sup-a'                    # поддержка при самой себе
        b['goals'][0]['for'] = 'sup-a'                    # умение при поддержке — по кругу
        b['goals'][0]['grantedBy'] = 'skill-a'
        r['goals'][1]['grantedBy'] = 'reward-own'
        b['tree']['phases'][0]['without'] = 'start'       # запасная версия — она же
        b['tree']['phases'][1]['without'] = 'start'
        b['slots'][0]['wear'][1]['until'] = 'beach'       # срок раньше начала
        b['stages'][1]['from'] = 'nowhere'
        r['goals'][0]['need'] = 'nowhere'
        b['goals'][3]['slot'] = 'nowhere'
        res = app.import_plan({'import': hostile.bundle(r, b, self.groups, uid='0dd'), 'file': 'odd.plan.json'})
        self.assertTrue(res['ok'], res)
        self.assertTrue(app.bind_plan(res['plan'])[0])
        with app.cond:
            json.loads(app.view_json('ru'))
            json.loads(app.answer(app.build_view('ru'), 'ru'))
            self.assertTrue(app.plan_problems)

    def test_real_plans_pass(self):
        """Настоящие планы проекта уходят файлом и принимаются обратно без замечаний."""
        plans = planlib.project_plans(ROOT)
        if not plans:
            self.skipTest('в проекте нет планов')
        for path, parts in plans:
            with self.subTest(plan=path.parent.name):
                raw = json.loads(path.read_text(encoding='utf-8-sig'))
                data = {'format': planlib.FORMAT, 'version': 1, 'uid': 'x', 'title': path.parent.name,
                        'groups': raw.get('groups') or [],
                        'route': parts['route'].read_text(encoding='utf-8-sig'),
                        'build': parts['build'].read_text(encoding='utf-8-sig')}
                planlib.parse_bundle(data)
        tpl = KNOWLEDGE / planlib.TEMPLATE
        if tpl.is_file():
            route = planguard.loads(tpl.read_text(encoding='utf-8-sig'), 'маршрут')
            self.assertEqual(planguard.problems(route, json.loads(planlib.empty_build('x', route['id'])),
                                                planlib.TEMPLATE_GROUPS), [])


class PathsTest(Library):
    def test_writes_stay_inside_the_library(self):
        outside = self.root / 'outside'
        outside.mkdir()
        for bad in (outside, self.plans, self.plans / '..' / 'outside', self.root):
            with self.assertRaises(ValueError):
                planlib.inside(self.plans, bad)
        self.assertEqual(planlib.inside(self.plans, self.plans / 'a' / 'b.json'), (self.plans / 'a' / 'b.json').resolve())
        # папка плана, которая на деле — ссылка наружу (junction): присланная новая версия в неё не пишется
        src = self.plans / self.folders()[0]
        (outside / 'evil').mkdir()
        _winapi.CreateJunction(str(outside / 'evil'), str(self.plans / 'evil'))
        try:
            for name in ('plan.json', 'route.json', 'build.json'):
                (outside / 'evil' / name).write_bytes((src / name).read_bytes())
            raw = json.loads((outside / 'evil' / 'plan.json').read_text(encoding='utf-8'))
            raw['received'] = {'file': 'x', 'at': 'y'}
            planlib.write_manifest(outside / 'evil' / 'plan.json', raw)
            before = (outside / 'evil' / 'route.json').read_bytes()
            with self.assertRaises(ValueError):
                planlib.replace(self.plans, 'evil', hostile.bundle(self.route, self.build, self.groups), 'x.plan.json',
                                backup_dir=self.root / 'backup')
            self.assertEqual((outside / 'evil' / 'route.json').read_bytes(), before)
        finally:
            os.rmdir(self.plans / 'evil')          # junction — только сама ссылка
        # имена папок — только по образцу; имена устройств Windows и пути из названия плана не выводят наружу
        for title in ('..\\..\\evil', '../../evil', 'CON', 'nul', 'aux', 'COM1', 'lpt9', '.', '..', 'C:\\x'):
            with self.subTest(title=title):
                pid = planlib.add(self.plans, dict(hostile.bundle(self.route, self.build, self.groups), title=title))
                self.assertTrue(planlib.RE_ID.fullmatch(pid))
                self.assertNotIn(pid, planlib.DEVICES)
                self.assertTrue((self.plans / pid / 'plan.json').is_file())
        self.assertEqual(sorted(p.name for p in outside.iterdir()), ['evil'])

    def test_file_name_is_clean(self):
        for name, want in (('..\\..\\a.plan.json', 'a.plan.json'), ('C:\\x\\<b>.json', '<b>.json'),
                           ('a\u202eb\x00c.json', 'abc.json'), (['x'], ''), ('Ж' * 300, 'Ж' * 120)):
            self.assertEqual(planlib._file_name(name), want)


class PagePolicyTest(unittest.TestCase):
    """Страницы уходят с политикой: скрипт и стиль — только с меткой этого ответа; метка каждый раз новая."""

    def test_pages_have_one_script_and_one_style(self):
        for name in ('index.html', 'admin.html'):
            body = (HERE / 'static' / name).read_bytes()
            self.assertEqual(len(server.RE_PAGE_TAG.findall(body)), 2, name)
            self.assertEqual(len(re.findall(rb'<script\b', body)), 1, name)
            self.assertEqual(len(re.findall(rb'<style\b', body)), 1, name)
            inline = re.findall(rb'<[a-z]+[^>]*\son[a-z]+\s*=[^>]{0,40}', body)
            self.assertEqual(inline, [], name)      # встроенных обработчиков (onerror=…) нет

    def test_policy_and_nonce(self):
        a, b = server.page_nonce(), server.page_nonce()
        self.assertNotEqual(a, b)
        self.assertRegex(a, r'^[A-Za-z0-9_-]{20,}$')
        body = server.with_nonce(b'<!doctype html>\n<style>\nx{}\n</style>\n<script>\n"<script>"\n</script>\n', a)
        self.assertEqual(body.count(('nonce="%s"' % a).encode()), 2)
        self.assertIn(b'"<script>"', body)
        policy = server.PAGE_POLICY.format(n=a)
        for part in ("default-src 'none'", "script-src 'nonce-%s'" % a, "connect-src 'self'", "img-src 'self'",
                     "base-uri 'none'", "form-action 'none'", "frame-ancestors 'none'"):
            self.assertIn(part, policy)
        self.assertNotIn('unsafe-eval', policy)
        self.assertNotIn("script-src 'nonce-%s' 'unsafe-inline'" % a, policy)

    def test_served_pages(self):
        """Настоящий ответ сервера: заголовок политики, метка в теге — та же, у второго ответа — другая; тело запроса
        с NaN и глубокой вложенностью — отказ 400, а не падение."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log = root / 'Client.txt'
            log.write_text(area('20:07:03', 1, 'G1_1', 'Берег реки'), encoding='utf-8')
            route, build, groups = hostile.base()
            plans = root / 'plans'
            plans.mkdir()
            pid = planlib.add(plans, hostile.bundle(route, build, groups))
            app = server.App(log, plans / pid / planlib.MANIFEST, root / 'runs', plans_dir=plans)
            with app.cond:
                app.load_plan()
                app.poll_log(initial=True)
                app.attach_run()
            httpd = server.ThreadingHTTPServer(('127.0.0.1', 0), server.make_handler(app, 0))
            port = httpd.server_address[1]
            httpd.RequestHandlerClass = server.make_handler(app, port)
            threading.Thread(target=httpd.serve_forever, daemon=True).start()
            try:
                seen = set()
                for path in ('/', '/admin', '/review', '/?ov=list'):
                    with urllib.request.urlopen('http://127.0.0.1:%d%s' % (port, path)) as r:
                        policy, body = r.headers['Content-Security-Policy'], r.read()
                    nonce = re.search(r"script-src 'nonce-([^']+)'", policy).group(1)
                    self.assertIn(('<script nonce="%s">' % nonce).encode(), body)
                    self.assertIn(('<style nonce="%s">' % nonce).encode(), body)
                    seen.add(nonce)
                self.assertEqual(len(seen), 4)
                for where, raw in (('mark', b'{"goal": NaN}'), ('build', b'{"a": ' + b'[' * 5000 + b']' * 5000 + b'}'),
                                   ('mark', b'[1]'), ('plans', b'{"import": {"a": Infinity}}')):
                    req = urllib.request.Request('http://127.0.0.1:%d/api/%s' % (port, where), data=raw, method='POST',
                                                 headers={'Content-Type': 'application/json'})
                    with self.assertRaises(urllib.error.HTTPError) as e:
                        urllib.request.urlopen(req)
                    self.assertEqual(e.exception.code, 400)
            finally:
                httpd.shutdown()
                httpd.server_close()


if __name__ == '__main__':
    unittest.main()
