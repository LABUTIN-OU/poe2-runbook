# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Sergei Labutin
# Additional terms under GPL-3.0 section 7: see NOTICE.md
"""Сверка камней каталога с планом: умения и камни поддержки, записанные в plan.json руками.

Для каждой цели вида «Русское имя (English Name)» ищется камень каталога по английскому имени и
сравнивается: тот ли это род (умение или поддержка), то же ли русское имя даёт слой языка и тот ли
минимальный уровень камня (gemFrom в плане — level в каталоге).

Запуск: python -I catalog/check_gems.py [--sources ПАПКА] [--plan plan.json]
"""
import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build  # noqa: E402

RE_TITLE = re.compile(r'^(.*?) \(([^()]*)\)\s*$')


def main():
    ap = argparse.ArgumentParser(description='Сверка камней каталога с планом')
    ap.add_argument('--sources')
    ap.add_argument('--plan', default=str(HERE.parent / 'plan.json'))
    args = ap.parse_args()
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding='utf-8', errors='replace')
        except (AttributeError, ValueError):
            pass
    cat = build.build(build.current(args.sources) if args.sources else None, ('ru',))
    plan = json.loads(Path(args.plan).read_text(encoding='utf-8-sig'))
    by_name = {}
    for gid, g in cat['gems'].items():
        by_name.setdefault(g['name'], (gid, g))
    ru = cat['lang']['ru']['gems']
    types = {}
    for g in cat['gems'].values():
        types[g['type']] = types.get(g['type'], 0) + 1
    print('камней в каталоге: %d %s | русских имён: %d' % (len(cat['gems']), types, len(ru)))
    goals = [g for g in plan['goals'] if g.get('kind') in ('skill', 'support')]
    ok, notes = 0, []
    seen = set()
    for g in goals:
        m = RE_TITLE.match(g.get('title') or '')
        if not m:
            notes.append('%s: в названии нет английского имени' % g['id'])
            continue
        name_ru, name_en = m.group(1), m.group(2)
        if (g['kind'], name_en) in seen:
            continue
        seen.add((g['kind'], name_en))
        hit = by_name.get(name_en)
        if not hit:
            notes.append('%-8s %s (%s): камня с таким именем нет' % (g['kind'], name_ru, name_en))
            continue
        gid, gem = hit
        diff = []
        want = 'active' if g['kind'] == 'skill' else 'support'
        if gem['type'] != want:
            diff.append('в каталоге это %s' % gem['type'])
        if ru.get(name_en) != name_ru:
            diff.append('по-русски «%s»' % ru.get(name_en))
        if g.get('gemFrom') is not None and gem['level'] != g['gemFrom']:
            diff.append('уровень камня с %s, в плане %s' % (gem['level'], g['gemFrom']))
        if diff:
            notes.append('%-8s %s (%s) = %s: %s' % (g['kind'], name_ru, name_en, gid, '; '.join(diff)))
        else:
            ok += 1
    print('умений и поддержек в плане (разных): %d | совпали полностью: %d' % (len(seen), ok))
    for n in notes:
        print('   ' + n)
    return 0


if __name__ == '__main__':
    sys.exit(main())
