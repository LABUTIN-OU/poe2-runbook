# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Sergei Labutin
# Additional terms under GPL-3.0 section 7: see NOTICE.md
"""Паспорт вещи: всё, что на ней есть, суммой по статам героя.

Билду нужны не аффиксы, а итог: сколько здоровья, сопротивления холоду, духа даёт вещь целиком. Один
и тот же стат приходит с вещи разными путями — чистым аффиксом, гибридом («броня и здоровье»),
собственным свойством базы, руной в гнезде, свойством самой вещи («Броня: 358»). Паспорт складывает
их все. Что считать статом и из каких свойств игры он складывается — таблица каталога (stats); какая
строка текста какому свойству игры отвечает — слой языка каталога. Поэтому паспорт не зависит ни от
плана, ни от языка клиента.

Свойства, которые меняют саму вещь («+36 к броне» на доспехе, «% увеличение духа» на скипетре), в сумму
не идут: они уже внутри числа из блока свойств вещи — в сумму идёт оно.
"""
import re

RE_SIGN = re.compile(r'[+\-−]#')
RE_MINUS = re.compile(r'^[^#]*[-−]#')
RE_INT = re.compile(r'\d+')
RE_NOTE = re.compile(r'\([^)]*\)')      # пометка в скобках: (augmented)
RE_COLON = re.compile(r'\s*[:：]\s*')     # «Броня: 358»; в китайском и японском клиенте двоеточие широкое
RE_LIST = re.compile(r'[,，、]')           # «Уровень 36, 54 Сила»: запятая — и восточная тоже
SOURCES = {'explicit': None, 'implicit': 'implicit', 'rune': 'rune', 'enchant': 'enchant', 'unique': 'unique'}


def norm(shape):
    """Форма строки без знака перед числом: «+# к броне» и «# к броне» — одна строка."""
    return RE_SIGN.sub('#', shape or '').strip()


def line_index(cat, lang):
    """Форма строки на языке клиента -> [(ключ строки каталога, знак написания)]. У одного текста бывает
    несколько ключей (броня доспеха и броня пояса); знак −1 — написание «наоборот» («снижение …»)."""
    cache = cat.setdefault('_line_index', {})
    if lang not in cache:
        pack = (cat.get('lang') or {}).get(lang) or {}
        less = pack.get('less') or {}
        idx = {}
        for key, shapes in (pack.get('stats') or {}).items():
            minus = set(less.get(key) or ())
            for sh in shapes:
                idx.setdefault(norm(sh), []).append((key, -1 if sh in minus else 1))
        cache[lang] = idx
    return cache[lang]


def stat_index(cat):
    """Свойство игры -> [(стат героя, 'ids' или 'local')]."""
    cache = cat.get('_stat_index')
    if cache is None:
        cache = {}
        for sid, s in ((cat.get('stats') or {}).get('stats') or {}).items():
            for field in ('ids', 'local'):
                for i in s.get(field) or []:
                    cache.setdefault(i, []).append((sid, field))
        cat['_stat_index'] = cache
    return cache


def _pick(cands, allowed, by_id, have):
    """Ключ строки из нескольких с одним текстом («+# к броне» — броня самой вещи или героя).
    У опознанного аффикса — ключ его семейства. Иначе: если вещь сама несёт это свойство числом
    (have — статы, у которых на вещи есть своё свойство: «Броня: 358»), строка меняет её; потом —
    свойство, которое складывается в стат героя; потом любое."""
    if allowed:
        for key, sign in cands:
            if key in allowed:
                return key, sign

    def rank(key):
        best = 0
        for i in key.split():
            for sid, kind in by_id.get(i, ()):
                best = max(best, 3 if kind == 'local' and sid in have else 2 if kind == 'ids' else 1)
        return best
    return max(cands, key=lambda c: rank(c[0]))


def _number(x):
    return int(x) if x == int(x) else x


def _props(pack, plain):
    """Блок свойств вещи: числа («Броня: 358»), гнёзда («Гнезда: S S») и требования
    («Требуется: Уровень 36, 54 Сила»). Слова — из слоя языка каталога."""
    names, words = pack.get('props') or {}, pack.get('words') or {}
    props, req, sockets = {}, {}, 0
    for p in plain or []:
        cut = RE_COLON.split(p['text'], maxsplit=1)
        if len(cut) < 2:
            continue
        name, rest = cut
        name, rest = name.strip(), rest.strip()
        if name in names and p['values']:
            props[names[name]] = _number(p['values'][0])
        elif name == words.get('sockets'):
            sockets = len(rest.split())
        elif name == words.get('requires'):
            for chunk in RE_LIST.split(rest):
                # изменённое требование игра помечает в середине строки: «40 (augmented) Сила»
                chunk = RE_NOTE.sub(' ', chunk)
                n = RE_INT.search(chunk)
                word = RE_INT.sub('', chunk).strip()
                for field in ('level', 'str', 'dex', 'int'):
                    if n and any(word.startswith(w) for w in words.get(field) or ()):
                        req[field] = int(n.group(0))
    return props, req, sockets


def passport(cat, item):
    """Паспорт разобранной вещи (itemcopy.parse + identify); None — нет каталога или его таблицы статов.

    stats — стат героя -> сумма с вещи; parts — из чего она сложилась (стат -> [{v, src, text}], src —
    prefix / suffix / implicit / rune / enchant / unique / property / base); props — свойства вещи числом, req —
    требования, sockets — гнёзд всего, runes — из них занято, affixes — сколько префиксов и суффиксов
    на вещи, other — строки, которые ни в один стат не идут (их число).
    """
    table = ((cat or {}).get('stats') or {}).get('stats')
    if not table or not item:
        return None
    lang = item.get('lang')
    pack = (cat.get('lang') or {}).get(lang) or {}
    idx, by_id = line_index(cat, lang), stat_index(cat)
    parts, other = {}, 0
    affixes = {'prefix': 0, 'suffix': 0}
    runes = 0
    local = {}       # стат -> строки, которые меняют саму вещь: проценты и числа, отдельно — от вставок

    def put(sid, value, src, text):
        parts.setdefault(sid, []).append({'v': _number(value), 'src': src, 'text': text})

    props, req, sockets = _props(pack, item.get('plain'))
    have = {sid for sid, s in table.items() if s.get('prop') in props}

    def line(shape, text, values, src, allowed=None):
        """Одна строка свойства: её числа — в статы героя. False — строка ни в один стат не идёт."""
        cands = idx.get(norm(shape))
        if not cands:
            return False
        key, sign = _pick(cands, allowed, by_id, have)
        if RE_MINUS.match(shape):
            sign = -sign
        hit = False
        for n, stat_id in enumerate(key.split()):
            for sid, field in by_id.get(stat_id, ()):
                hit = True
                if n >= len(values):
                    continue
                if field == 'ids':
                    # scale — у строки из двух чисел («Добавляет от 3 до 9 урона») в стат идёт их среднее
                    put(sid, sign * values[n] * table[sid].get('scale', 1), src, text)
                else:
                    # Строка меняет саму вещь: она уже внутри числа из блока свойств. Запоминаем её
                    # отдельно — чтобы снять вклад вставки (bare): проценты складываются с процентами
                    # аффиксов, числа — с базой.
                    bucket = local.setdefault(sid, {'pct': 0, 'flat': 0, 'rune_pct': 0, 'rune_flat': 0})
                    bucket[('rune_' if src == 'rune' else '') + ('pct' if '#%' in shape else 'flat')] += sign * values[n]
        return hit

    for m in item.get('mods') or []:
        kind = m.get('kind')
        if kind == 'other' and item.get('rarity') == 'unique':
            kind = 'unique'           # запись надетого, сделанная до 2026-11-23: свойство уникального читалось «прочим»
        if kind == 'explicit' and m.get('gen') in affixes:
            affixes[m['gen']] += 1
        if kind == 'rune':
            runes += 1
        src = m.get('gen') if kind == 'explicit' else SOURCES.get(kind) or kind
        fam = (cat.get('mods') or {}).get(m.get('fam')) if m.get('fam') else None
        allowed = set(fam['lines']) if fam and fam.get('lines') else None
        for shape, text, values in zip(m['shapes'], m['lines'], m['values']):
            if not line(shape, text, values, src, allowed):
                other += 1
    # Простая копия (Ctrl+C): строки аффиксов идут без заголовков и уже сложены игрой — паспорту
    # нужна как раз сумма. Строки блока свойств («Броня: 358») разобраны выше, прочие строки
    # (подсказки, описания) ни с каким свойством не совпадут.
    for p in item.get('plain') or []:
        if ':' not in p['text']:
            line(p['shape'], p['text'], p['values'], 'affix')
    own = item.get('own') or {}
    for sid, s in table.items():
        if s.get('prop') in props:
            put(sid, props[s['prop']], 'property', None)
        # свойство базы, которого на вещи не написано: штраф скорости нательного доспеха и щита
        if s.get('base') and own.get(s['base']):
            put(sid, own[s['base']], 'base', None)
    stats = {sid: _number(sum(p['v'] for p in ps)) for sid, ps in parts.items()}
    return {'stats': stats, 'parts': parts, 'props': props, 'req': req, 'sockets': sockets, 'runes': runes,
            'affixes': affixes, 'other': other, 'local': local}


def bare(p):
    """Та же вещь без вставок в гнёздах (руны, сердцевины душ): паспорт без их строк, а свойство самой
    вещи («Энергетический щит: 249») — без их вклада. Собственные свойства базы остаются: они часть вещи.

    Так вещи сравнивают друг с другом: руны в новую вещь ещё только предстоит вставить, и ответ нужен
    до того, как их потратят.

    Число из блока свойств игра считает так: (база + числа) × (1 + проценты) × (1 + качество); проценты
    аффиксов и вставок складываются между собой. Вклад вставки снимается обратным счётом.
    """
    if not p:
        return p
    quality = 1 + (p.get('props') or {}).get('quality', 0) / 100.0
    parts = {}
    for sid, ps in (p.get('parts') or {}).items():
        loc = (p.get('local') or {}).get(sid) or {}
        keep = []
        for part in ps:
            if part['src'] == 'rune':
                continue
            if part['src'] == 'property' and (loc.get('rune_pct') or loc.get('rune_flat')):
                core = part['v'] / (1 + (loc['pct'] + loc['rune_pct']) / 100.0) / quality - loc['rune_flat']
                part = dict(part, v=_number(round(max(0.0, core) * (1 + loc['pct'] / 100.0) * quality)))
            keep.append(part)
        if keep:
            parts[sid] = keep
    return dict(p, parts=parts, stats={sid: _number(sum(x['v'] for x in ps)) for sid, ps in parts.items()})


def inserts(p):
    """Что вещи дают вставки в гнёздах: стат -> число (у свойства самой вещи — их вклад в него)."""
    if not p:
        return {}
    plain = bare(p)['stats']
    out = {}
    for sid, v in (p.get('stats') or {}).items():
        d = round(v - plain.get(sid, 0), 1)
        if d:
            out[sid] = _number(d)
    return out


def view(cat, item, lang='ru'):
    """Паспорт для страницы: статы в порядке каталога, с названиями на языке страницы.
    [{id, name, short, value, unit, parts}] — только те, что на вещи есть."""
    p = passport(cat, item)
    if p is None:
        return None
    packs = cat.get('lang') or {}
    names = (packs.get(lang) or {}).get('statNames') or (packs.get('ru') or {}).get('statNames') or {}
    table = cat['stats']['stats']
    order = cat['stats'].get('order') or list(table)
    rows = []
    for sid in order:
        if p['stats'].get(sid):
            full, short = names.get(sid) or (sid, sid)
            rows.append({'id': sid, 'name': full, 'short': short, 'value': p['stats'][sid],
                         'unit': table[sid].get('unit') or '', 'parts': p['parts'][sid]})
    return {'rows': rows, 'req': p['req'], 'sockets': p['sockets'], 'runes': p['runes'],
            'affixes': p['affixes'], 'other': p['other']}
