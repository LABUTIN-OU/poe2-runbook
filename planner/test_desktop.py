# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Sergei Labutin
# Additional terms under GPL-3.0 section 7: see NOTICE.md
"""Журнал программы (desktop.py): журналы прежних запусков не стираются, в начале каждой строки — день и время.

    python -X utf8 -m unittest planner.test_desktop
"""
import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import desktop  # noqa: E402

STAMP = r'\d\d-\d\d \d\d:\d\d:\d\d  '


def run_once(data, *lines):
    """Один «запуск программы»: журнал открыт, в него написали строки, программа закрыта."""
    log = desktop.open_log(data)
    for line in lines:
        print(line, file=log)
    log.flush()
    log.file.close()


class LogTest(unittest.TestCase):
    def test_earlier_logs_are_kept(self):
        """Новый запуск не стирает журнал прежнего: тот становится program.1.log, более ранние сдвигаются; хранится
        LOGS_KEPT прежних, самый старый уходит."""
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            for n in range(1, desktop.LOGS_KEPT + 3):
                run_once(data, 'run %d' % n)
            last = desktop.LOGS_KEPT + 2
            self.assertIn('run %d' % last, (data / 'program.log').read_text(encoding='utf-8'))
            for back in range(1, desktop.LOGS_KEPT + 1):
                text = (data / ('program.%d.log' % back)).read_text(encoding='utf-8')
                self.assertIn('run %d' % (last - back), text)
            names = sorted(p.name for p in data.iterdir())
            self.assertEqual(len(names), desktop.LOGS_KEPT + 1, names)

    def test_first_start_in_an_empty_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            run_once(data, 'first')
            self.assertEqual([p.name for p in data.iterdir()], ['program.log'])

    def test_every_line_starts_with_day_and_time(self):
        """Время — в начале каждой строки, и одно на строку, даже когда строку пишут кусками (print пишет текст и
        перевод строки отдельно, отчёт об ошибке — много строк одним куском). Пустая строка остаётся пустой."""
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            log = desktop.open_log(data)
            print('one', file=log)
            log.write('two ')
            log.write('halves\n')
            log.write('Traceback:\n  File "x.py", line 1\nValueError: мимо\n')
            log.write('\n')
            log.write('')
            print('после пустой', file=log)
            log.flush()
            log.file.close()
            lines = (data / 'program.log').read_text(encoding='utf-8').split('\n')
            self.assertEqual(lines.pop(), '')
            want = ['one', 'two halves', 'Traceback:', '  File "x.py", line 1', 'ValueError: мимо', None, 'после пустой']
            self.assertEqual(len(lines), len(want), lines)
            for line, text in zip(lines, want):
                if text is None:
                    self.assertEqual(line, '')
                else:
                    self.assertTrue(re.fullmatch(STAMP + re.escape(text), line), line)

    def test_log_takes_what_the_server_does_with_a_stream(self):
        """Сервер при старте просит у потока вывода кодировку UTF-8 (reconfigure) и готов к тому, что такого умения
        нет; print(..., flush=True) и номер файла журналу нужны."""
        with tempfile.TemporaryDirectory() as tmp:
            log = desktop.open_log(Path(tmp))
            self.assertFalse(hasattr(log, 'reconfigure'))
            self.assertEqual(log.encoding.lower().replace('-', ''), 'utf8')
            print('строка', file=log, flush=True)
            self.assertIsInstance(log.fileno(), int)
            self.assertFalse(log.isatty())
            log.file.close()


if __name__ == '__main__':
    unittest.main()
