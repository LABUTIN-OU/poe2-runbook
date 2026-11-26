# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Sergei Labutin
# Additional terms under GPL-3.0 section 7: see NOTICE.md
"""Сверка каталога с планом: те же ли тиры даёт каталог, что записаны в plan.json руками.

Строка аффикса в плане задана словами («префикс · здоровье») и текстом свойства на русском. Здесь она
переводится в идентификаторы игры: текст -> id свойства (слой языка) -> семейство аффикса (каталог) ->
ступени на базе этого слота. Ступени сравниваются с ручными: число тиров, числа каждого тира и уровень
предмета, с которого тир бывает. Совпало — значит, такую строку можно больше не писать руками.

Запуск: python catalog/check_plan.py [--sources ПАПКА] [--plan plan.json]
"""
import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build  # noqa: E402

RE_NUM = re.compile(r'\d+(?:[.,]\d+)?')
# На какой базе проверять строки слота: имя базы или (класс, метка) — «любая такая».
SLOT_BASE = {
    ('weapon', 'crossbow'): 'Sturdy Crossbow', ('weapon', 'djinn'): 'Rattling Sceptre',
    ('offhand', 'djinn'): 'Barricade Tower Shield', ('body', None): 'Full Plate', ('belt', None): 'Plate Belt',
    ('helmet', None): ('Helmet', 'int_armour'), ('gloves', None): ('Gloves', 'str_armour'),
    ('boots', None): ('Boots', 'str_armour'), ('amulet', None): ('Amulet', 'amulet'),
    ('ring1', None): ('Ring', 'ring'), ('ring2', None): ('Ring', 'ring'),
}


def title_range(title):
    nums = [float(n.replace(',', '.')) for n in RE_NUM.findall(title or '')]
    if not nums:
        return None
    return (nums[0], nums[1]) if len(nums) > 1 else (nums[0], nums[0])


def base_tags(cat, want):
    if isinstance(want, str):
        return next((b['tags'] for b in cat['bases'].values() if b['name'] == want), None)
    cls, tag = want
    pure = {'str_armour', 'dex_armour', 'int_armour', 'str_dex_armour', 'str_int_armour', 'dex_int_armour'}
    for b in cat['bases'].values():
        if b['class'] == cls and tag in b['tags'] and len(pure & set(b['tags'])) <= 1:
            return b['tags']
    return None


def main():
    ap = argparse.ArgumentParser(description='Сверка каталога с планом')
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
    ru = cat['lang']['ru']
    print('каталог: версия %s, зон %d, баз %d, семейств %d' % (cat['version'], len(cat['areas']), len(cat['bases']), len(cat['mods'])))
    codes = {c for s in plan['steps'] for c in [s.get('zone')] + list(s.get('also') or []) if c}
    print('зоны плана в каталоге: %d из %d' % (sum(1 for c in codes if c in cat['areas']), len(codes)))
    named = [g['title'].split(' (')[1].split(')')[0] for g in plan['goals']
             if g.get('slot') and not g.get('part') and ' (' in (g.get('title') or '')]
    known = {b['name'] for b in cat['bases'].values()}
    # в плане «Ростовой щит (Tower Shield)» — род баз, а не одна база: ищем и как часть имени
    print('базы плана в каталоге: %d из %d%s' % (
        sum(1 for n in named if n in known or any(n in k for k in known)), len(named),
        ' | русские названия: ' + ', '.join('%s = %s' % (n, ru['bases'].get(n, '?')) for n in named if n in known)))

    rows = {}
    for g in plan['goals']:
        if g.get('slot') and g.get('part'):
            rows.setdefault((g['slot'], g.get('kit'), g['part']), []).append(g)
    ok = bad = 0
    for (slot, kit, part), chain in rows.items():
        label = next((g['label'] for g in chain if g.get('label')), '')
        gen = 'prefix' if label.startswith('префикс') else 'suffix'
        tags = base_tags(cat, SLOT_BASE.get((slot, kit)))
        head = '%-8s %-8s %-36s' % (slot, part, label)
        if tags is None:
            print(head, '— нет базы для проверки')
            bad += 1
            continue
        # семейство строки: аффикс из одной строки текста, и эта строка по-русски — одна из записанных в плане
        want = {build.shape(text) for text in plan.get('affixes', {}).get(label, [])}
        fams = [(k, f) for k, f in cat['mods'].items()
                if f['gen'] == gen and f['lines'] and len(f['lines']) == 1
                and want & set(ru['stats'].get(f['lines'][0], [])) and build.tiers(f, tags)]
        if not fams:
            print(head, '— семейство не найдено')
            bad += 1
            continue
        notes = []
        for key, fam in fams:
            ladder = {t['tier']: t for t in build.tiers(fam, tags)}
            diff = []
            if len(ladder) != len(chain):
                diff.append('тиров %d, в плане %d' % (len(ladder), len(chain)))
            for g in chain:
                t = ladder.get(g.get('tier'))
                if t is None:
                    continue
                want = title_range(g.get('title'))
                got = tuple(float(x) for x in t['vals'][0]) if len(t['vals']) == 1 else None
                if want and got and want != got:
                    diff.append('T%d числа %g–%g, в плане %s' % (g['tier'], got[0], got[1], g.get('title')))
                if (g.get('opens') or 1) != (t['level'] or 1):
                    diff.append('T%d с уровня %s, в плане %s' % (g['tier'], t['level'], g.get('opens') or 1))
            notes.append((fam['type'], diff))
        if all(not d for _, d in notes):
            ok += 1
            print(head, 'совпало:', ', '.join('%s' % t for t, _ in notes), '· тиров', len(chain))
        else:
            bad += 1
            print(head, 'РАСХОЖДЕНИЯ:')
            for t, d in notes:
                print('      %s: %s' % (t, '; '.join(d[:4]) + (' … ещё %d' % (len(d) - 4) if len(d) > 4 else '') if d else 'совпало'))
    print('строк аффиксов: %d | совпало полностью: %d | с расхождениями: %d' % (ok + bad, ok, bad))
    return 0


if __name__ == '__main__':
    sys.exit(main())
