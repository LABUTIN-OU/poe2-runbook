# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Sergei Labutin
# Additional terms under GPL-3.0 section 7: see NOTICE.md
"""Прогон предметов через фильтр PoE2: покажет он предмет или спрячет.

Блоки фильтра идут сверху вниз, решает первый подошедший (блок с Continue только
меняет вид). Условия, которые нельзя решить без данных о базе предмета, считаются
неизвестными: тогда ответ помечается как неуверенный.
"""
import re
from i18n import tr

STYLE = re.compile(r'^(Set|Play|Minimap|Custom|Disable|Enable)')
ABSENT = object()
RANK = {'Normal': 0, 'Magic': 1, 'Rare': 2, 'Unique': 3}
OPS = ('==', '<=', '>=', '!=', '=', '<', '>', '!')
NUMERIC = {'ItemLevel', 'AreaLevel', 'DropLevel', 'Sockets', 'Quality', 'StackSize', 'Width', 'Height', 'GemLevel',
           'WaystoneTier', 'UnidentifiedItemTier', 'BaseArmour', 'BaseEvasion', 'BaseEnergyShield'}
BOOLS = {'Corrupted', 'Mirrored', 'Identified', 'AnyEnchantment'}


def parse(path):
    """Читает файл фильтра в список блоков. Закомментированные блоки пропускаются."""
    blocks, cur = [], None
    with open(path, encoding='utf-8-sig', errors='replace') as f:
        for n, raw in enumerate(f, 1):
            line = raw.rstrip('\r\n')
            s = line.strip()
            m = re.match(r'^(Show|Hide|Minimal)\b(.*)', line)
            if m:
                cur = {'action': m.group(1), 'tag': m.group(2).strip(), 'conds': [], 'cont': False, 'line': n}
                blocks.append(cur)
                continue
            if not s:
                cur = None
                continue
            if cur is None or s.startswith('#'):
                continue
            if s == 'Continue':
                cur['cont'] = True
            elif not STYLE.match(s):
                cur['conds'].append(s)
    return blocks


def _num_cmp(op, a, b):
    return {'=': a == b, '==': a == b, '!=': a != b, '!': a != b,
            '<': a < b, '<=': a <= b, '>': a > b, '>=': a >= b}[op]


def cond(c, item):
    """True / False / None (неизвестно)."""
    toks = [t.strip('"') if t.startswith('"') else t for t in re.findall(r'"[^"]*"|\S+', c)]
    name, rest = toks[0], toks[1:]
    op = rest.pop(0) if rest and rest[0] in OPS else '='
    if name == 'Rarity':
        mine = RANK[item['Rarity']]
        if op in ('=', '=='):
            return any(RANK.get(v) == mine for v in rest)
        return _num_cmp(op, mine, RANK[rest[0]])
    if name in ('Class', 'BaseType'):
        val = item.get(name)
        if val is None:
            return None
        hit = any((v == val) if op == '==' else (v in val) for v in rest)
        return (not hit) if op in ('!=', '!') else hit
    if name in NUMERIC:
        val = item.get(name)
        if val is ABSENT:
            return False
        if val is None:
            return None
        try:
            return _num_cmp(op, val, int(rest[0]))
        except (ValueError, IndexError):
            return None
    if name in BOOLS:
        val = item.get(name)
        if val is None:
            return None
        return val == (rest[0] == 'True')
    if name == 'HasExplicitMod':
        return False
    # Редкие признаки (TwiceCorrupted, AlwaysShow и подобные) у обычной находки не выставлены.
    if rest == ['True']:
        return False
    if rest == ['False']:
        return True
    return None


def verdict(blocks, item):
    """Решение фильтра по предмету: {'action': 'Show'|'Hide'|None, 'line', 'sure'}."""
    doubts = []
    for b in blocks:
        res = [cond(c, item) for c in b['conds']]
        if any(r is False for r in res):
            continue
        if any(r is None for r in res):
            if not b['cont']:
                doubts.append(b['action'])
            continue
        if b['cont']:
            continue
        return {'action': b['action'], 'line': b['line'], 'sure': all(d == b['action'] for d in doubts)}
    return {'action': None, 'line': None, 'sure': not doubts}


def gear(cls, rarity, area, base=None, **kw):
    """Обычная неопознанная находка: без гнёзд, качества и порчи."""
    it = dict(Class=cls, BaseType=base, Rarity=rarity, AreaLevel=area, ItemLevel=area, DropLevel=None,
              Sockets=0, Quality=0, Corrupted=False, Mirrored=False,
              Identified=(rarity == 'Normal'), StackSize=ABSENT, GemLevel=ABSENT, WaystoneTier=ABSENT,
              UnidentifiedItemTier=(ABSENT if rarity == 'Normal' else None), Width=None, Height=None,
              AnyEnchantment=False, BaseArmour=None, BaseEvasion=None, BaseEnergyShield=None)
    it.update({k: v for k, v in kw.items() if v is not None})
    return it


def currency(base, area, stack=1):
    return dict(Class='Stackable Currency', BaseType=base, Rarity='Normal', AreaLevel=area, ItemLevel=area,
                DropLevel=1, Sockets=ABSENT, Quality=ABSENT, Corrupted=False, Mirrored=False, Identified=True,
                StackSize=stack, GemLevel=ABSENT, WaystoneTier=ABSENT, UnidentifiedItemTier=ABSENT,
                Width=1, Height=1, AnyEnchantment=False, BaseArmour=ABSENT, BaseEvasion=ABSENT,
                BaseEnergyShield=ABSENT)


def state(v):
    """'show' / 'hide' / 'unsure' из результата verdict()."""
    if not v['sure']:
        return 'unsure'
    return 'hide' if v['action'] == 'Hide' else 'show'


def diff(old_blocks, new_blocks):
    """Блоки, которые есть только в одной из двух версий фильтра."""
    def key(b):
        return (b['action'], b['tag'], tuple(b['conds']), b['cont'])
    old_keys = {key(b) for b in old_blocks}
    new_keys = {key(b) for b in new_blocks}
    return ([b for b in old_blocks if key(b) not in new_keys],
            [b for b in new_blocks if key(b) not in old_keys])
