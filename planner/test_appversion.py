# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Sergei Labutin
# Additional terms under GPL-3.0 section 7: see NOTICE.md
"""Версия программы «версия игры.номер сборки» и версия игры из её лога (appversion.py).

    python -X utf8 -m unittest planner.test_appversion
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import appversion  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


class VersionTest(unittest.TestCase):
    def test_game_version_is_three_numbers(self):
        """Версия игры — три числа: четвёртое число каталога данных и буква исправления в неё не входят. Прежняя запись
        клиента с четвёркой впереди — та же версия."""
        self.assertEqual(appversion.stem('0.5.5.10'), '0.5.5')
        self.assertEqual(appversion.stem('0.5.5h'), '0.5.5')
        self.assertEqual(appversion.stem('0.6.0'), '0.6.0')
        self.assertEqual(appversion.stem('4.5.2'), '0.5.2')
        self.assertEqual(appversion.stem(' 0.10.0b '), '0.10.0')
        for bad in (None, '', 'abc', '0.5', 'v1'):
            self.assertIsNone(appversion.stem(bad))

    def test_program_version_is_game_version_and_build_number(self):
        self.assertEqual(appversion.program('0.5.5.10', 4), '0.5.5.4')
        self.assertEqual(appversion.program('0.6.0.1', 1), '0.6.0.1')
        self.assertEqual(appversion.program('0.5.5.10'), '0.5.5.%d' % appversion.BUILD)
        self.assertIsNone(appversion.program(None))
        # версия целиком — четыре числа: столько помещается в версию файла Windows
        self.assertRegex(appversion.program('0.5.5.10'), r'^\d+\.\d+\.\d+\.\d+$')

    def test_newer_game_needs_a_newer_program(self):
        """Красным страница говорит только одно: игра новее программы. Исправление внутри версии — не новая версия;
        игра старее программы (её ещё не обновили или не запускали после обновления) — тоже нет."""
        self.assertTrue(appversion.newer('0.6.0', '0.5.5.10'))
        self.assertTrue(appversion.newer('0.5.6b', '0.5.5.10'))
        self.assertTrue(appversion.newer('0.10.0', '0.9.3.2'))                # числа, а не строки
        self.assertFalse(appversion.newer('0.5.5h', '0.5.5.10'))
        self.assertFalse(appversion.newer('0.5.5h', '0.6.0.1'))
        self.assertFalse(appversion.newer('4.5.5', '0.5.5.10'))               # прежняя запись той же версии
        self.assertFalse(appversion.newer(None, '0.5.5.10') or appversion.newer('0.6.0', None))

    def test_game_names_its_version_in_the_log(self):
        """Строка лога, которую игра пишет при каждом запуске; реплика в чате с тем же текстом — не версия."""
        line = '2026/11/25 02:35:10 123456 abc [INFO Client 4321] [HTTP2] User agent: PoE poe2_production/tags/0.5.5h Windows x64'
        self.assertEqual(appversion.game_tag(line), '0.5.5h')
        self.assertEqual(appversion.game_tag(line.replace('0.5.5h', '4.5.2').replace('poe2_production', 'poe2_other')), '4.5.2')
        chat = '2026/11/25 02:35:10 123456 abc [INFO Client 4321] #Сосед: [HTTP2] User agent: PoE poe2_production/tags/9.9.9 Windows x64'
        self.assertIsNone(appversion.game_tag(chat))
        self.assertIsNone(appversion.game_tag('2026/11/25 02:35:10 1 a [INFO Client 1] [ENGINE] Build Revision: 329201'))

    def test_build_counter_is_for_the_game_version_of_the_catalogue(self):
        """Счётчик сборок считается для версии игры GAME: каталог данных в проекте — той же версии (иначе сборщик
        остановится и попросит начать счёт с 1)."""
        current = ROOT / 'catalog' / 'data' / 'current.txt'
        if not current.is_file():
            self.skipTest('каталога данных игры рядом нет')
        self.assertEqual(appversion.stem(current.read_text(encoding='utf-8')), appversion.GAME)
        self.assertGreaterEqual(appversion.BUILD, 1)


if __name__ == '__main__':
    unittest.main()
