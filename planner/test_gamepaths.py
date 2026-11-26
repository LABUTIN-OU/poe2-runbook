# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Sergei Labutin
# Additional terms under GPL-3.0 section 7: see NOTICE.md
"""Проверка поиска игры (planner/gamepaths.py) и смены папки игры у программы (App.set_game, /api/game).

Реестр и окна Windows подменены: папки игры — во временной папке.
Запуск: python -X utf8 -m unittest planner.test_gamepaths"""
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import appsettings  # noqa: E402
import gamepaths  # noqa: E402

UNINST = r'SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall'


class FakeRegistry:
    """Реестр словарём: {(root, key): {name: value}}."""

    def __init__(self, keys):
        self.keys = keys

    def value(self, root, key, name):
        return self.keys.get((root, key), {}).get(name)

    def subkeys(self, root, key):
        pre = key + '\\'
        return sorted({k[len(pre):].split('\\')[0] for r, k in self.keys if r == root and k.startswith(pre)})


def make_game(folder, log='Client.txt', text='', age=0):
    """Папка игры с логом; age — на сколько секунд лог старше «сейчас»."""
    path = Path(folder) / 'logs' / log
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')
    t = time.time() - age
    os.utime(path, (t, t))
    return Path(folder)


class FindTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.env = {'ProgramFiles(x86)': str(self.tmp / 'pf86'), 'ProgramFiles': str(self.tmp / 'pf')}

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def steam(self, libraries, manifest=None):
        """Steam в tmp/steam с файлом библиотек; libraries — пути других библиотек."""
        steam = self.tmp / 'steam'
        (steam / 'steamapps').mkdir(parents=True, exist_ok=True)
        body = '"libraryfolders"\n{\n\t"0"\n\t{\n\t\t"path"\t\t"%s"\n\t\t"apps"\n\t\t{\n\t\t\t"2694490"\t\t"123456"\n\t\t}\n\t}\n' % (
            str(steam).replace('\\', '\\\\'))
        for n, lib in enumerate(libraries, 1):
            body += '\t"%d"\n\t{\n\t\t"path"\t\t"%s"\n\t}\n' % (n, str(lib).replace('\\', '\\\\'))
        (steam / 'steamapps' / 'libraryfolders.vdf').write_text(body + '}\n', encoding='utf-8')
        if manifest:
            lib, name = manifest
            (Path(lib) / 'steamapps').mkdir(parents=True, exist_ok=True)
            (Path(lib) / 'steamapps' / 'appmanifest_2694490.acf').write_text(
                '"AppState"\n{\n\t"appid"\t\t"2694490"\n\t"installdir"\t\t"%s"\n}\n' % name, encoding='utf-8')
        return {('HKCU', r'Software\Valve\Steam'): {'SteamPath': str(steam).replace('\\', '/')}}

    def test_steam_library_on_another_disk(self):
        lib = self.tmp / 'D' / 'SteamLibrary'
        game = make_game(lib / 'steamapps' / 'common' / 'Path of Exile 2')
        reg = FakeRegistry(self.steam([lib]))
        self.assertEqual(gamepaths.find(reg=reg, env=self.env), (game, game / 'logs' / 'Client.txt'))

    def test_steam_folder_from_the_manifest(self):
        lib = self.tmp / 'E' / 'Games'
        game = make_game(lib / 'steamapps' / 'common' / 'PoE2 Custom')
        reg = FakeRegistry(self.steam([lib], manifest=(lib, 'PoE2 Custom')))
        self.assertEqual(gamepaths.find(reg=reg, env=self.env)[0], game)

    def test_old_library_file(self):
        """Старый вид libraryfolders.vdf: «"1" "D:\\\\SteamLibrary"» — путь прямо у номера."""
        lib = self.tmp / 'old'
        game = make_game(lib / 'steamapps' / 'common' / 'Path of Exile 2')
        steam = self.tmp / 'steam2'
        (steam / 'steamapps').mkdir(parents=True)
        (steam / 'steamapps' / 'libraryfolders.vdf').write_text(
            '"LibraryFolders"\n{\n\t"TimeNextStatsReport"\t\t"1"\n\t"1"\t\t"%s"\n}\n' % str(lib).replace('\\', '\\\\'),
            encoding='utf-8')
        reg = FakeRegistry({('HKLM', r'SOFTWARE\WOW6432Node\Valve\Steam'): {'InstallPath': str(steam)}})
        self.assertEqual(gamepaths.find(reg=reg, env=self.env)[0], game)

    def test_standalone_client_in_its_default_folder(self):
        game = make_game(self.tmp / 'pf86' / 'Grinding Gear Games' / 'Path of Exile 2')
        self.assertEqual(gamepaths.find(reg=FakeRegistry({}), env=self.env)[0], game)

    def test_standalone_client_in_a_folder_of_its_own(self):
        """Клиент с сайта, поставленный в свою папку: её называет запись установщика."""
        game = make_game(self.tmp / 'Games' / 'PoE2')
        reg = FakeRegistry({('HKLM', UNINST + r'\{GGG-1}'): {'DisplayName': 'Path of Exile 2',
                                                               'InstallLocation': str(game) + '\\'}})
        self.assertEqual(gamepaths.find(reg=reg, env=self.env)[0], Path(str(game) + '\\'))

    def test_installer_record_without_a_folder_gives_the_icon_folder(self):
        game = make_game(self.tmp / 'G' / 'Path of Exile 2')
        reg = FakeRegistry({('HKCU', r'Software\Microsoft\Windows\CurrentVersion\Uninstall\x'): {
            'DisplayName': 'Path of Exile 2', 'DisplayIcon': '"%s",0' % (game / 'PathOfExile.exe')}})
        self.assertEqual(gamepaths.find(reg=reg, env=self.env)[0], game)

    def test_first_game_is_not_the_second(self):
        """Запись «Path of Exile» (первая игра) — не наша игра."""
        poe1 = make_game(self.tmp / 'poe1')
        reg = FakeRegistry({('HKLM', UNINST + r'\poe1'): {'DisplayName': 'Path of Exile', 'InstallLocation': str(poe1)}})
        self.assertEqual(gamepaths.find(reg=reg, env=self.env), (None, None))

    def test_two_clients_newest_log_wins(self):
        """Стоят и Steam, и клиент с сайта: берётся тот, чей лог писался последним."""
        lib = self.tmp / 'lib'
        steam_game = make_game(lib / 'steamapps' / 'common' / 'Path of Exile 2', age=3600)
        site_game = make_game(self.tmp / 'pf86' / 'Grinding Gear Games' / 'Path of Exile 2', age=60)
        reg = FakeRegistry(self.steam([lib]))
        self.assertEqual(gamepaths.find(reg=reg, env=self.env)[0], site_game)
        os.utime(steam_game / 'logs' / 'Client.txt', None)
        self.assertEqual(gamepaths.find(reg=reg, env=self.env)[0], steam_game)

    def test_running_game_then_remembered_folder(self):
        lib = self.tmp / 'lib'
        make_game(lib / 'steamapps' / 'common' / 'Path of Exile 2')
        saved = make_game(self.tmp / 'saved', age=999)
        running = make_game(self.tmp / 'running', age=9999)
        reg = FakeRegistry(self.steam([lib]))
        self.assertEqual(gamepaths.find(saved, running, reg, self.env)[0], running)
        self.assertEqual(gamepaths.find(saved, None, reg, self.env)[0], saved)
        # запомненная папка без лога (игру удалили) — ищем дальше
        shutil.rmtree(saved)
        self.assertEqual(gamepaths.find(saved, None, reg, self.env)[0], lib / 'steamapps' / 'common' / 'Path of Exile 2')

    def test_folder_without_a_log_is_not_a_game(self):
        (self.tmp / 'pf86' / 'Grinding Gear Games' / 'Path of Exile 2').mkdir(parents=True)
        self.assertEqual(gamepaths.find(reg=FakeRegistry({}), env=self.env), (None, None))

    def test_kakao_log_name(self):
        game = make_game(self.tmp / 'kakao' / 'Path of Exile 2', log='KakaoClient.txt')
        self.assertEqual(gamepaths.log_in(game), game / 'logs' / 'KakaoClient.txt')

    def test_what_the_player_may_pick(self):
        game = make_game(self.tmp / 'GGG' / 'Path of Exile 2')
        for picked in (game, game / 'logs', game / 'logs' / 'Client.txt', self.tmp / 'GGG'):
            self.assertEqual(gamepaths.game_at(picked), game, picked)
        self.assertIsNone(gamepaths.game_at(self.tmp))
        self.assertIsNone(gamepaths.game_at(None))

    def test_game_config_name(self):
        docs = self.tmp / 'docs'
        docs.mkdir()
        self.assertEqual(gamepaths.config_in(docs), docs / gamepaths.CONFIG)      # ещё не создан — обычное имя
        (docs / 'poe2_kakao_Config.ini').write_text('x', encoding='utf-8')
        self.assertEqual(gamepaths.config_in(docs), docs / 'poe2_kakao_Config.ini')
        (docs / gamepaths.CONFIG).write_text('x', encoding='utf-8')
        self.assertEqual(gamepaths.config_in(docs), docs / gamepaths.CONFIG)

    def test_settings_keep_other_values(self):
        path = self.tmp / 'data' / 'settings.json'
        appsettings.update(path, gameDir='D:\\PoE2')
        appsettings.update(path, window={'w': 1200, 'h': 800})
        self.assertEqual(appsettings.load(path), {'gameDir': 'D:\\PoE2', 'window': {'w': 1200, 'h': 800}})
        appsettings.update(None, gameDir='x')         # без файла — ничего
        path.write_text('{broken', encoding='utf-8')
        self.assertEqual(appsettings.load(path), {})


@unittest.skipUnless(sys.platform == 'win32', 'Windows only')
class ThisComputerTest(unittest.TestCase):
    def test_documents_is_a_real_folder(self):
        self.assertTrue(gamepaths.documents().is_dir())

    def test_registry_reads(self):
        reg = gamepaths.registry()
        self.assertIsNotNone(reg.value('HKLM', r'SOFTWARE\Microsoft\Windows NT\CurrentVersion', 'ProductName'))
        self.assertTrue(reg.subkeys('HKLM', r'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall'))

    def test_no_window_titled_like_the_game_is_ours(self):
        """Окно с заголовком игры, но чужой программы, — не игра (проверка на настоящих окнах без игры)."""
        wins = gamepaths.windows()
        found = wins.running_game()
        self.assertTrue(found is None or os.path.basename(str(found)) != '')


class SwitchTest(unittest.TestCase):
    """Программа переходит на лог другой папки игры: запущена игра из неё или папку указал игрок."""

    LOG_A = ('2026/11/24 10:00:00 1 2 [INFO Client 1] : Проба (Ведьма) достигает 2 уровня\n')
    LOG_B = ('2026/11/24 11:00:00 1 2 [INFO Client 1] : Другой (Наёмник) достигает 2 уровня\n'
             '2026/11/24 11:01:00 1 2 [INFO Client 1] : Другой (Наёмник) достигает 3 уровня\n')

    def setUp(self):
        import server
        self.server = server
        self.tmp = Path(tempfile.mkdtemp())
        self.a = make_game(self.tmp / 'steam' / 'Path of Exile 2', text=self.LOG_A)
        self.b = make_game(self.tmp / 'site' / 'Path of Exile 2', text=self.LOG_B)
        root = HERE.parent
        plans = self.tmp / 'plans'
        shutil.copytree(root / 'plans', plans)
        lib = server.planlib.scan(plans)
        self.app = server.App(self.a / 'logs' / 'Client.txt', lib[0]['path'], self.tmp / 'runs',
                              config_path=self.tmp / 'none.ini', catalog_dir=root / 'catalog' / 'data',
                              knowledge_dir=root / 'knowledge', plans_dir=plans)
        self.app.settings_path = self.tmp / 'settings.json'
        self.app.game_dir = self.a
        with self.app.cond:
            self.app.load_plan()
            self.app.poll_log(initial=True)
            self.app.attach_run()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_follow_the_running_game(self):
        self.assertEqual([e.get('level') for e in self.app.run.events if e['type'] == 'level'][-1], 2)
        self.app.follow = lambda: self.b
        with self.app.cond:
            self.assertTrue(self.app.follow_game())
        self.assertEqual(self.app.log_path, self.b / 'logs' / 'Client.txt')
        self.assertEqual(self.app.game_dir, self.b)
        self.assertTrue(self.app.log_ok)
        self.assertEqual([e.get('level') for e in self.app.run.events if e['type'] == 'level'][-1], 3)
        self.assertEqual(appsettings.load(self.app.settings_path), {'gameDir': str(self.b)})
        # та же игра — ничего не меняется; Windows спрашивается не чаще раза в две секунды
        with self.app.cond:
            self.assertFalse(self.app.follow_game())

    def test_player_picks_a_folder(self):
        with self.app.cond:
            res = self.app.choose_game(self.tmp)            # в этой папке игры нет
        self.assertFalse(res['ok'])
        self.assertIn(str(self.tmp), str(self.app.game_problem))
        with self.app.cond:
            res = self.app.choose_game(self.b / 'logs')      # папка logs — тоже годится
        self.assertTrue(res['ok'])
        self.assertIsNone(self.app.game_problem)
        self.assertEqual(self.app.game_dir, self.b)

    def test_no_game_at_all(self):
        app = self.server.App(None, self.app.plan_path, self.tmp / 'runs2', catalog_dir=HERE.parent / 'catalog' / 'data',
                              knowledge_dir=HERE.parent / 'knowledge', plans_dir=self.tmp / 'plans')
        with app.cond:
            self.assertFalse(app.poll_log(initial=True))
            self.assertIsNone(app.detect_client_lang())
        self.assertFalse(app.log_ok)

    def test_pick_through_the_page(self):
        """POST /api/game {pick: true}: окно выбора открывает программа (здесь — подмена), путь от страницы не берётся."""
        httpd = self.server.ThreadingHTTPServer(('127.0.0.1', 0), self.server.make_handler(self.app, 0))
        port = httpd.server_address[1]
        httpd.RequestHandlerClass = self.server.make_handler(self.app, port)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        try:
            def post(body):
                req = urllib.request.Request('http://127.0.0.1:%d/api/game' % port, data=json.dumps(body).encode(),
                                             headers={'Content-Type': 'application/json'}, method='POST')
                try:
                    with urllib.request.urlopen(req) as r:
                        return r.status, json.loads(r.read())
                except urllib.error.HTTPError as e:
                    return e.code, None
            self.assertEqual(post({'pick': True})[0], 400)          # у программы нет окна выбора (не окно программы)
            self.assertEqual(post({'dir': str(self.b)})[0], 400)    # путь от страницы не принимается
            self.app.picker = lambda: None                            # игрок закрыл окно выбора
            self.assertEqual(post({'pick': True}), (200, {'ok': False, 'cancelled': True}))
            self.app.picker = lambda: str(self.b)
            code, res = post({'pick': True})
            self.assertEqual((code, res['ok']), (200, True))
            self.assertEqual(self.app.game_dir, self.b)
        finally:
            httpd.shutdown()
            httpd.server_close()


if __name__ == '__main__':
    unittest.main()
