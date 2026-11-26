# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Sergei Labutin
# Additional terms under GPL-3.0 section 7: see NOTICE.md
"""Проверка фильтра PoE2 из командной строки.

  python planner/filter_check.py <файл фильтра>                  — сколько в нём блоков
  python planner/filter_check.py --diff <старый> <новый>          — чем отличаются две версии

Что фильтр делает с целями плана, показывает страница «Игра» (server.filter_check): своих образцов «типовых находок»
у программы больше нет — они были зашиты под один билд.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import filtereval  # noqa: E402

def show_block(b):
    print('  строка %d  %s %s%s' % (b['line'], b['action'], b['tag'][:90], '  [Continue]' if b['cont'] else ''))
    for c in b['conds']:
        print('      ' + (c if len(c) < 200 else c[:200] + ' ...'))


def main(argv):
    if len(argv) >= 4 and argv[1] == '--diff':
        gone, added = filtereval.diff(filtereval.parse(argv[2]), filtereval.parse(argv[3]))
        print('Только в старой версии: %d' % len(gone))
        for b in gone:
            show_block(b)
        print('Только в новой версии: %d' % len(added))
        for b in added:
            show_block(b)
        return 0
    if len(argv) < 2:
        print(__doc__)
        return 1
    blocks = filtereval.parse(argv[1])
    print('%s: блоков %d' % (os.path.basename(argv[1]), len(blocks)))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
