# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Sergei Labutin
# Additional terms under GPL-3.0 section 7: see NOTICE.md
"""Каталог данных игры для плеера: загрузка с диска и вопросы к нему.

Каталог собирает catalog/build.py из открытых выгрузок игры; ключи в нём — идентификаторы самой игры
(код зоны, семейство аффикса, свойство), слова на языке игрока лежат отдельным слоем. Здесь — только
чтение готовых файлов и чистые функции над ними: какие ступени аффикса бывают на базе, как ступень
подписать, какое семейство стоит за строкой текста на вещи.
"""
import json
import re
from pathlib import Path
from i18n import tr

PARTS = ('areas', 'bases', 'mods')
# метки рода доспеха: у «чистой» базы такая одна
ARMOUR_KINDS = {'str_armour', 'dex_armour', 'int_armour', 'str_dex_armour', 'str_int_armour', 'dex_int_armour',
                'str_dex_int_armour'}


def load(root):
    """Каталог из папки (catalog/data): берётся версия, названная в current.txt. Нет папки или файлов —
    None: плеер работает и без каталога, но строки аффиксов из него тогда не развернуть."""
    root = Path(root)
    try:
        version = (root / 'current.txt').read_text(encoding='utf-8').strip()
        folder = root / version
        meta = json.loads((folder / 'meta.json').read_text(encoding='utf-8'))
        cat = {'version': meta.get('version') or version, 'lang': {}}
        for part in PARTS:
            cat[part] = json.loads((folder / (part + '.json')).read_text(encoding='utf-8'))
        # камни, правила и путевые камни добавлены в каталог позже остального: в папке постарше этих файлов нет
        for part in ('gems', 'rules', 'waystones', 'implicits', 'augments', 'stats', 'craft', 'emotions', 'uniques'):
            try:
                cat[part] = json.loads((folder / (part + '.json')).read_text(encoding='utf-8'))
            except OSError:
                cat[part] = {}
        for lang in meta.get('languages') or []:
            cat['lang'][lang] = json.loads((folder / ('lang-%s.json' % lang)).read_text(encoding='utf-8'))
        # что игра пишет в лог, по языкам клиента: большие файлы, читаются по запросу (log_pack)
        cat['dir'] = str(folder)
        cat['logs'] = list(meta.get('log') or [])
        # названия из игры на языках страниц (names-<язык>.json.gz): тоже по запросу (names_pack)
        cat['namePacks'] = list(meta.get('names') or [])
        return cat
    except (OSError, ValueError):
        return None


_LOG_PACKS = {}


def log_pack(cat, lang):
    """Тексты лога языка клиента из каталога: {npc, say, msg} (catalog/build.py, log-<язык>.json.gz) или None.
    Файл читается один раз."""
    if not cat or lang not in (cat.get('logs') or ()):
        return None
    path = Path(cat['dir']) / ('log-%s.json.gz' % lang)
    key = str(path)
    if key not in _LOG_PACKS:
        import gzip
        try:
            _LOG_PACKS[key] = json.loads(gzip.decompress(path.read_bytes()).decode('utf-8'))
        except (OSError, ValueError, EOFError):
            _LOG_PACKS[key] = None
    return _LOG_PACKS[key]


_NAME_PACKS = {}


def names_pack(cat, lang):
    """Названия из игры на языке lang по английскому названию (catalog/build.py, names-<язык>.json.gz):
    {names: {English: местное}, nodes: {id узла дерева: местное}} или None. Файл читается один раз."""
    if not cat or lang not in (cat.get('namePacks') or ()):
        return None
    path = Path(cat['dir']) / ('names-%s.json.gz' % lang)
    key = str(path)
    if key not in _NAME_PACKS:
        import gzip
        try:
            _NAME_PACKS[key] = json.loads(gzip.decompress(path.read_bytes()).decode('utf-8'))
        except (OSError, ValueError, EOFError):
            _NAME_PACKS[key] = None
    return _NAME_PACKS[key]


def log_msgs(cat):
    """Системные строки лога всех языков клиента: {язык: {код: шаблон}} — по ним язык узнаётся по самому логу."""
    if not cat or not cat.get('logs'):
        return {}
    try:
        return json.loads((Path(cat['dir']) / 'log-msg.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def own_level(cat):
    """Коды зон с собственным постоянным уровнем: в данных игры он выше уровня любого города.

    У обычной карты в данных стоит базовый уровень (как у города, откуда ходят на карты), а настоящий
    задаёт путевой камень. Узлы механик и арены боссов живут иначе: «Увядшая ива» всегда 79-го уровня,
    «Горящий монолит» — 74-го. Такой уровень игрок не выбирал, поэтому этап карт эти зоны не открывают."""
    areas = (cat or {}).get('areas') or {}
    towns = [a.get('level') or 0 for a in areas.values() if a.get('town')]
    base = max(towns) if towns else 0
    return frozenset(code for code, a in areas.items() if not a.get('town') and (a.get('level') or 0) > base)


def zone_levels(cat):
    """Код боевой зоны -> её уровень в данных игры. Это младший уровень зоны: у зон, чей уровень растёт с порядком
    прохождения (ветки второго акта, острова четвёртого, интерлюдии), настоящий бывает выше. Города не в счёт:
    их уровень в данных выше окрестных зон."""
    areas = (cat or {}).get('areas') or {}
    return {code: a['level'] for code, a in areas.items()
            if isinstance(a, dict) and not a.get('town') and isinstance(a.get('level'), int) and a['level'] > 0}


def fits(mod, tags):
    """Бывает ли аффикс на базе с такими метками: решает первая метка из списка аффикса, что есть у базы."""
    have = set(tags)
    for tag, weight in mod['on']:
        if tag in have:
            return weight > 0
    return False


def tiers(fam, tags):
    """Ступени семейства на базе с такими метками, от слабой к сильной; tier — как в игре: 1 — лучший."""
    mine = [m for m in fam['mods'] if fits(m, tags)]
    n = len(mine)
    return [dict(m, tier=n - i) for i, m in enumerate(mine)]


def gear_tags(cat, spec):
    """Метки базы по её описанию в плане: «Helmet int_armour» — класс и, если важно, род (шлем на
    энергощит). Берутся с первой подходящей «чистой» базы каталога; None — такой базы нет."""
    words = (spec or '').rsplit(' ', 1) if isinstance(spec, str) else []
    if not words:
        return None
    cls, tag = (words[0], words[1]) if len(words) == 2 and words[1].islower() and '_' in words[1] else (spec, None)
    for b in cat['bases'].values():
        if b['class'] == cls and (tag is None or tag in b['tags']) and len(ARMOUR_KINDS & set(b['tags'])) <= 1:
            return b['tags']
    return None


def spec_parts(spec):
    """Описание базы из плана -> (класс, род или None): «Helmet int_armour» -> ('Helmet', 'int_armour')."""
    words = (spec or '').rsplit(' ', 1) if isinstance(spec, str) else []
    if len(words) == 2 and words[1].islower() and '_' in words[1]:
        return words[0], words[1]
    return (spec if isinstance(spec, str) and spec else None), None


def tag_sets(cat, spec):
    """Все наборы меток, какие бывают у баз по описанию из плана. Род назван («Helmet int_armour») —
    набор один; не назван («Gloves») — по набору на каждый род: перчатки бывают на броню, уклонение,
    энергощит и смешанные, и что из этого наденет герой, план не говорит."""
    cls, kind = spec_parts(spec)
    seen = {}
    for b in cat['bases'].values():
        if b['class'] == cls and (kind is None or kind in b['tags']):
            seen.setdefault(tuple(sorted(set(b['tags']) & ARMOUR_KINDS)), b['tags'])
    return list(seen.values())


# Вставки в гнёзда (руны, ядра душ): на вещи какой категории вставка что даёт. Категории — слова игры
# из её данных (augments.json); к какой вещи какая относится, там не сказано, поэтому таблица своя:
# «Armour» — всё с меткой armour (шлем, доспех, перчатки, сапоги, щит, баклер, фокус), «Martial Weapon» —
# всё с меткой weapon (у скипетра, жезла и посоха её нет). Скипетр в «Caster Weapon» записан
# предположительно: в данных такая категория есть у четырёх редких рун, проверить было не на чем.
CASTER = ('Wand', 'Staff')
AUGMENT_ON = {
    'All': lambda cls, tags: 'armour' in tags or 'weapon' in tags or cls in CASTER or cls == 'Sceptre',
    'Armour': lambda cls, tags: 'armour' in tags,
    'Martial Weapon': lambda cls, tags: 'weapon' in tags,
    'Wand or Staff': lambda cls, tags: cls in CASTER,
    'Caster Weapon': lambda cls, tags: cls in CASTER or cls == 'Sceptre',
    'Martial Or Caster Weapon': lambda cls, tags: 'weapon' in tags or cls in CASTER or cls == 'Sceptre',
    'Martial Weapon Wand or Staff': lambda cls, tags: 'weapon' in tags or cls in CASTER,
    'Quarterstaff': lambda cls, tags: cls == 'Warstaff',
    'Shield or Buckler': lambda cls, tags: cls in ('Shield', 'Buckler'),
    'One Hand Mace or Quarterstaff': lambda cls, tags: cls in ('One Hand Mace', 'Warstaff'),
    'Crossbow Bow or Spear': lambda cls, tags: cls in ('Crossbow', 'Bow', 'Spear'),
    'Maces or Talisman': lambda cls, tags: cls in ('One Hand Mace', 'Two Hand Mace', 'Talisman'),
    'Quarterstaff or Spear': lambda cls, tags: cls in ('Warstaff', 'Spear'),
}


# категории «на целый род вещей»: такая вставка — обычная руна; остальные привязаны к одному классу вещи
AUGMENT_BROAD = ('All', 'Armour', 'Martial Weapon', 'Wand or Staff', 'Caster Weapon', 'Martial Or Caster Weapon',
                 'Martial Weapon Wand or Staff')


def augment_fits(category, cls, tags):
    """Относится ли вещь (класс и метки базы) к категории вставки. Категория, которой нет в таблице, —
    имя класса вещи («Helmet», «Sceptre»)."""
    rule = AUGMENT_ON.get(category)
    return rule(cls, tags or ()) if rule else category == cls


def base_icon(cat, item):
    """Имя файла картинки базы вещи (art-…) или None. База берётся по английскому имени, которое вещь
    получила при опознании (itemcopy.identify): оно лежит и в вещах, запомненных раньше."""
    name = (item or {}).get('base_en')
    if not cat or not name:
        return None
    index = cat.get('_icon_by_base')
    if index is None:
        index = cat['_icon_by_base'] = {b['name']: b['icon'] for b in cat['bases'].values() if b.get('icon')}
    return index.get(name)


def _fold(name):
    """Имя для поиска: без регистра, «ё» как «е», пробелы как один."""
    return ' '.join((name or '').casefold().replace('ё', 'е').split())


def find_unique(cat, lang, name, base_en=None):
    """Уникальный предмет каталога по имени из копии на языке клиента: (английское имя, запись) или None.

    Имя ищется в слое языка (имена уникальных на этом языке), потом среди английских: английский и тайский клиенты
    пишут имена уникальных по-английски. Одно имя у двух уникальных на этом языке (по-немецки «Atziris
    Verachtung») — выбирает база предмета (base_en); не выбрала — None: картинка чужого предмета хуже картинки базы."""
    uniques = (cat or {}).get('uniques') or {}
    if not uniques or not name:
        return None
    index = cat.setdefault('_unique_names', {})
    if lang not in index:
        names = {_fold(en): [en] for en in uniques}
        layer = (((cat.get('lang') or {}).get(lang) or {}).get('uniques') or {})
        for local, en in layer.items():
            names[_fold(local)] = [en] if isinstance(en, str) else list(en)
        index[lang] = names
    found = [en for en in index[lang].get(_fold(name)) or () if en in uniques]
    if len(found) > 1:
        found = [en for en in found if base_en and base_en in (uniques[en].get('bases') or ())]
    return (found[0], uniques[found[0]]) if len(found) == 1 else None


def item_icon(cat, item, have=None):
    """Картинка предмета: у уникального — его собственный рисунок (uniq-…), у прочих и у уникального, которого
    в каталоге нет, — рисунок базы (art-…). have — имена картинок, что лежат в папке: из них первая подходящая
    (нет своего рисунка уникального — рисунок базы). None — картинки нет."""
    if not cat or not item:
        return None
    names = []
    if item.get('rarity') == 'unique':
        u = find_unique(cat, item.get('lang'), item.get('name'), item.get('base_en'))
        if u and u[1].get('icon'):
            names.append(u[1]['icon'])
    base = base_icon(cat, item)
    if base:
        names.append(base)
    return next((n for n in names if have is None or n in have), None)


def num(x):
    return '%g' % x


# --- свои статы билда -----------------------------------------------------------------------------------
# Таблица статов каталога (catalog/extra/stats.json) — готовый набор: каждый стат в ней собран руками из
# нескольких свойств игры («Сопротивление огню» — огонь, все стихии и два гибрида). Это не все свойства
# игры: билду на чарах хаоса нужны «уровень камней чар» и «урон хаосом», которых в наборе нет. Поэтому
# билд может завести свой стат (раздел statDefs файла билда): название и строки свойств игры, которые
# в него складываются, — любые из тех, что бывают на вещах аффиксом. Дальше свой стат живёт как готовый:
# его ставят в статы этапа и в цели по стату, паспорт вещи его считает, сравнение вещей его учитывает.

RE_STAT_ID = re.compile(r'[a-z][a-z0-9_]{0,39}')
MAX_STAT_DEFS = 60       # своих статов у билда
MAX_STAT_LINES = 12      # строк свойств в одном стате
MAX_STAT_NAME = 60       # длина названия


def affix_lines(cat):
    """Строки свойств, которые бывают на вещах аффиксом: {ключ строки: (свойства игры)}. Ключ — как
    в семействах аффиксов каталога: одно свойство или два через пробел («Добавляет от # до # урона» —
    нижнее и верхнее число). Строки, меняющие саму вещь (их уже ведёт готовый стат: «+# к броне» на
    доспехе — внутри числа «Броня: 358»), сюда не идут: в сумму героя они складываться не должны."""
    cache = cat.get('_affix_lines')
    if cache is None:
        local = {i for s in ((cat.get('stats') or {}).get('stats') or {}).values() if not s.get('own')
                 for i in s.get('local') or []}
        cache = {}
        for fam in (cat.get('mods') or {}).values():
            for key in fam.get('lines') or []:
                ids = tuple(key.split())
                if 1 <= len(ids) <= 2 and not local & set(ids):
                    cache[key] = ids
        cat['_affix_lines'] = cache
    return cache


def line_text(cat, key, lang='ru'):
    """Текст строки свойства на языке lang («#% увеличение урона хаосом»); нет — по-английски; нет
    и такого — сам ключ."""
    for code in (lang, 'en'):
        shapes = (((cat.get('lang') or {}).get(code) or {}).get('stats') or {}).get(key)
        if shapes:
            return shapes[0]
    return key


def is_percent(cat, key):
    """Процентная ли строка свойства («#% увеличение урона хаосом») — по её тексту на любом языке каталога."""
    for pack in (cat.get('lang') or {}).values():
        shapes = (pack.get('stats') or {}).get(key)
        if shapes:
            return '#%' in shapes[0]
    return False


def stat_defs(cat, raw):
    """Проверяет свои статы билда (раздел statDefs). Запись — {id, name, lines, short?}: id — латинские
    буквы, цифры и подчёркивание (не как у готового стата); name — название; lines — ключи строк свойств
    игры (affix_lines), которые складываются в стат; short — короткое название для плитки. У строк одного
    стата поровну чисел: строку «от # до #» с обычной не сложить. Возвращает (записи для файла, замечания);
    запись с замечанием в список не идёт."""
    if raw is None:
        return [], []
    if not isinstance(raw, list) or len(raw) > MAX_STAT_DEFS:
        return [], [tr('свои статы: нужен список не длиннее %d') % MAX_STAT_DEFS]
    table = {sid for sid, s in ((cat or {}).get('stats') or {}).get('stats', {}).items() if not s.get('own')}
    known = affix_lines(cat) if cat else {}
    out, problems, ids = [], [], set()
    for d in raw:
        if not (isinstance(d, dict) and isinstance(d.get('id'), str) and RE_STAT_ID.fullmatch(d['id'])):
            problems.append(tr('свой стат: id — латинские буквы, цифры, подчёркивание'))
            continue
        sid = d['id']
        name = d.get('name').strip() if isinstance(d.get('name'), str) else ''
        where = tr('свой стат «%s»') % (name or sid)
        if sid in ids or sid in table:
            problems.append(tr('%s: id «%s» уже занят%s') % (where, sid, tr(' готовым статом') if sid in table else ''))
            continue
        if not name or len(name) > MAX_STAT_NAME:
            problems.append(tr('%s: нужно название не длиннее %d знаков') % (where, MAX_STAT_NAME))
            continue
        lines = d.get('lines')
        if not (isinstance(lines, list) and lines and len(lines) <= MAX_STAT_LINES
                and all(isinstance(x, str) for x in lines) and len(set(lines)) == len(lines)):
            problems.append(tr('%s: строки свойств — список без повторов, от одной до %d') % (where, MAX_STAT_LINES))
            continue
        lost = [x for x in lines if x not in known]
        if lost:
            problems.append(tr('%s: строки свойства «%s» среди аффиксов предметов в данных игры нет') % (where, lost[0]))
            continue
        if len({len(known[x]) for x in lines}) > 1:
            problems.append(tr('%s: строку «от # до #» нельзя сложить в один стат со строкой из одного числа') % where)
            continue
        rec = {'id': sid, 'name': name}
        short = d.get('short')
        if short is not None:
            if not isinstance(short, str) or len(short.strip()) > MAX_STAT_NAME:
                problems.append(tr('%s: короткое название — текст не длиннее %d знаков') % (where, MAX_STAT_NAME))
                continue
            if short.strip():
                rec['short'] = short.strip()
        rec['lines'] = list(lines)
        ids.add(sid)
        out.append(rec)
    return out, problems


_ENGLISH = re.compile(r'^[^()]*\(([^()]*)\)\s*$')


def english(title):
    """Английское имя из названия вида «Русское (English)» — так в плане названы умения и предметы. По нему
    вещь плана узнаётся в данных игры. Название другого вида («любой», «Ростовой щит (Tower Shield): жёлтый»)
    возвращается как есть: это не название из игры."""
    m = _ENGLISH.match(title or '')
    return (m.group(1) if m else (title or '')).strip()


_TITLE_EN = re.compile(r'^[^()]*\(([^()]*)\)')


def title_names(title):
    """Название цели-предмета «Русское (English): приписка» -> (местное строчными, английское); у названия не из
    игры английского нет. Так же название читает узнавание скопированного предмета (slotwear._names)."""
    t = title if isinstance(title, str) else ''
    m = _TITLE_EN.match(t)
    return t.split(' (', 1)[0].split(':', 1)[0].strip().lower(), (m.group(1).strip() if m else '')


def slot_classes(slot):
    """Классы предметов, которые слот носит за забег: по его периодам (wear); у слота старого вида — его список."""
    out = []
    for per in (slot or {}).get('wear') or []:
        for c in (per.get('classes') if isinstance(per, dict) else None) or []:
            if isinstance(c, str) and c not in out:
                out.append(c)
    return out or [c for c in (slot or {}).get('classes') or [] if isinstance(c, str)]


def named_bases(cat, title, classes=None):
    """Базы из данных игры, которые называет цель-предмет: (точно ли, записи баз).
      Точно — английская часть названия и есть название базы («Гремящий скипетр (Rattling Sceptre)»): её записи.
      Не точно — название входит в названия нескольких баз («Ростовой щит» — в «Баррикадный ростовой щит»): план
        называет так любую из них, и так же по названию узнаётся скопированный предмет (slotwear.fits). Записи —
        те из них, что падают сами: вариант с меткой runeforged делают из базы, а не находят; есть только такие —
        тогда они.
      Пусто — игра такого названия не знает («любой», «жёлтый щит»).
    classes — классы предметов слота цели: базы других классов не в счёт (не названы — любые). Базы наград
    (метка demigods) не в счёт никогда."""
    if not cat:
        return False, []
    key = (title if isinstance(title, str) else '', tuple(classes or ()))
    cache = cat.setdefault('_named', {})
    if key not in cache:
        local, en = title_names(title)
        pool = [b for b in (cat.get('bases') or {}).values()
                if b.get('name') and 'demigods' not in (b.get('tags') or ()) and (not classes or b.get('class') in classes)]
        exact = [b for b in pool if en and b['name'] == en]
        if exact:
            cache[key] = (True, exact)
        elif len(local) < 3:
            cache[key] = (False, [])
        else:
            packs = [pk.get('bases') or {} for pk in (cat.get('lang') or {}).values() if isinstance(pk, dict)]
            family = [b for b in pool if any(local in (names.get(b['name']) or '').lower() for names in packs)]
            cache[key] = (False, [b for b in family if 'runeforged' not in (b.get('tags') or ())] or family)
    return cache[key]


_TWIN_SKIP = ('name', 'art', 'icon')


def twins(cat, en):
    """Базы, одинаковые с базой en (английское название) по данным игры: класс, уровень, требования, защита, метки,
    неотъемлемые свойства — всё, кроме названия и рисунка («Тиара волшебника (Magus Tiara)» и «Тиара небес (Skycrown
    Tiara)»: ур. 65, энергощит 90, интеллект 91). Для плана это одна база: названная одной, она узнаётся и в другой.
    В счёт — только базы, которые знает клиент игры (есть в слое языка: без названия в клиенте — заготовка, её не
    найти), без наград (demigods) и сделанных из базы (runeforged). Пусто — таких нет или слоя языка в каталоге нет."""
    if not cat or not en:
        return []
    table = cat.get('_twins')
    if table is None:
        packs = [pk.get('bases') or {} for pk in (cat.get('lang') or {}).values() if isinstance(pk, dict)]
        groups = {}
        for b in (cat.get('bases') or {}).values():
            if (not b.get('name') or {'demigods', 'runeforged'} & set(b.get('tags') or ())
                    or not any(b['name'] in p for p in packs)):
                continue
            sig = json.dumps({k: v for k, v in b.items() if k not in _TWIN_SKIP}, sort_keys=True, ensure_ascii=False)
            groups.setdefault(sig, set()).add(b['name'])
        table = {n: sorted(names - {n}) for names in groups.values() if len(names) > 1 for n in names}
        cat['_twins'] = table
    return list(table.get(en) or ())


def base_at(bases, level=None):
    """Какая из баз падает в зоне такого уровня: старшая из тех, чей уровень не выше (её там и подберут); уровень
    не назван — младшая. None — ни одна там ещё не падает."""
    rows = sorted(bases, key=lambda b: (b.get('level') or 1, b.get('name') or ''))
    if level is None:
        return rows[0] if rows else None
    ok = [b for b in rows if (b.get('level') or 1) <= level]
    return ok[-1] if ok else None


def ground_base(cat, goal, classes, level):
    """Какая база цели-предмета может лежать на земле в зоне такого уровня — по названию цели: (знает ли игра
    название, запись базы или None). Точное название — эта база, если здесь она уже падает; общее — старшая из
    падающих здесь (base_at). Игра названия не знает (и у цели по стату, и у «любого») — (False, None)."""
    if not isinstance(goal, dict) or not goal.get('slot') or goal.get('part') or goal.get('any'):
        return False, None
    _, recs = named_bases(cat, goal.get('title'), classes)
    if not recs:
        return False, None
    return True, base_at(recs, level)


def filter_class(cat, cls):
    """Как класс предмета называет таблица классов игры — так его пишут фильтры предметов (условие Class):
    «Shield» -> «Shields». None — таблицы в каталоге нет (он собран до неё) или класса в ней нет."""
    names = (((cat or {}).get('lang') or {}).get('en') or {}).get('classNames') or {}
    return names.get(cls) if isinstance(cls, str) else None


def base_defences(base):
    """Защита самой базы для условий фильтра (BaseArmour, BaseEvasion, BaseEnergyShield): у базы доспеха, чьи
    числа есть в данных игры, — они (чего у базы нет — ноль); иначе пусто — фильтру о них сказать нечего."""
    props = base.get('props') or {}
    if 'armour' not in (base.get('tags') or ()) or not props:
        return {}
    return {'BaseArmour': props.get('armour') or 0, 'BaseEvasion': props.get('evasion') or 0,
            'BaseEnergyShield': props.get('energy_shield') or 0}


def _step_reach(cat, steps):
    """Шаг -> старший уровень боевой зоны, какой герой видел к этому шагу (по зонам шагов маршрута; города
    не в счёт: их уровень в данных игры выше окрестных зон)."""
    areas, top, out = (cat or {}).get('areas') or {}, None, {}
    for s in steps or []:
        if not isinstance(s, dict):
            continue
        a = areas.get(s['zone']) if isinstance(s.get('zone'), str) else None
        if isinstance(a, dict) and not a.get('town') and a.get('level'):
            top = max(top or 0, a['level'])
        if s.get('id'):
            out[s['id']] = top
    return out


def fact_index(cat):
    """Справка игры о вещах, которые план называет по имени, — по английскому имени:
    gems — камень умения -> {level: с какого уровня камня умение делают (0 — камня не делают: умение предмета
           или восхождения), keys: ключи камней с таким именем};
    bases — база предмета -> записи каталога (class, level — с какого уровня зоны падает, grants — ключи умений,
           которые база даёт сама)."""
    idx = cat.get('_facts')
    if idx is None:
        gems, bases = {}, {}
        for key, g in (cat.get('gems') or {}).items():
            if g.get('type') == 'support' or not g.get('name'):
                continue
            rec = gems.setdefault(g['name'], {'level': 0, 'keys': set()})
            rec['level'] = max(rec['level'], g.get('level') or 0)
            rec['keys'].add(key.rsplit('/', 1)[-1])
            if g.get('spirit'):
                rec['spirit'] = list(g['spirit'])
            if g.get('ascendancy'):
                rec['ascendancy'] = True
        # «Kelari, the Tainted Sands» план зовёт коротко — «Келари (Kelari)»: имя до запятой ведёт к тому же
        # камню, если такое имя одно и само не имя другого камня
        short = {}
        for name in list(gems):
            head = name.split(', ', 1)[0]
            if head != name:
                short.setdefault(head, []).append(name)
        for head, full in short.items():
            if len(full) == 1 and head not in gems:
                gems[head] = gems[full[0]]
        for b in (cat.get('bases') or {}).values():
            if b.get('name'):
                bases.setdefault(b['name'], []).append(b)
        idx = cat['_facts'] = {'gems': gems, 'bases': bases}
    return idx


def with_facts(cat, raw):
    """План, в который подставлено то, что о названных в нём вещах знает игра. Автор этого не пишет и изменить
    не может — это справка игры, а не решение билда:
      - умение, названное как камень умения из данных игры: gemFrom — уровень камня, с которого его делают;
      - умение, которое даёт сама база предмета, когда предмет с такой базой есть в плане: grantedBy — эта цель
        (она закроется сама, когда предмет наденут);
      - предмет, названный как база из данных игры: opens — уровень зоны, с которого база падает (1 — не пишется);
      - предмет, название которого игра знает (named_bases): icon — рисунок базы; у общего названия («Ростовой
        щит») — той из баз, что падает к шагу цели (base_at);
      - предмет, названный как база из данных игры: twins — английские названия баз, одинаковых с ней по данным
        (twins): копию такой базы план узнаёт как названную (itemcopy, slotwear);
      - таблица gemLevels (уровень героя для уровня камня) — правило gemHero каталога, если в плане её нет;
      - умение, чей камень резервирует дух: spirit — резерв по уровням камня, [на 1-м, на 2-м, …] (у умения
        предмета и восхождения — нет);
      - камень поддержки с 3-го гнезда своего умения: socket — {n: номер гнезда, hero: с какого уровня героя оно
        открыто (умение восхождения) или orb: какая сфера златокузнеца его делает (камень умения)}. Номер гнезда —
        по порядку камней поддержки умения в плане; замена (та же часть part) стоит в том же гнезде.
    Чего игра не знает (название не из данных), остаётся как записано в плане. Исходный план не меняется."""
    if not cat or not isinstance(raw, dict) or not isinstance(raw.get('goals'), list):
        return raw
    idx = fact_index(cat)
    goals = [dict(g) if isinstance(g, dict) else g for g in raw['goals']]
    slots = {s.get('id'): s for s in raw.get('slots') or [] if isinstance(s, dict)}
    reach = _step_reach(cat, raw.get('steps'))
    items = []        # предметы плана, чьё название — база из игры: (цель, записи базы)
    for g in goals:
        if not isinstance(g, dict) or not g.get('slot') or g.get('part'):
            continue
        classes = slot_classes(slots.get(g['slot']))
        if not g.get('any'):
            exact, named = named_bases(cat, g.get('title'), classes)
            pick = named[0] if exact else base_at(named, reach.get(g.get('need') or g.get('use'))) or base_at(named)
            if pick and pick.get('icon'):
                g['icon'] = pick['icon']
            same = twins(cat, named[0]['name']) if exact else []
            if same:
                g['twins'] = same
            else:
                g.pop('twins', None)
        recs = idx['bases'].get(english(g.get('title'))) or []
        recs = [b for b in recs if b.get('class') in classes] or recs
        if not recs:
            continue
        items.append((g, recs))
        level = max(b.get('level') or 0 for b in recs)
        if level > 1:
            g['opens'] = level
        else:
            g.pop('opens', None)
    skills = {}       # умение плана -> его камень в данных игры (кроме умений, которые даёт предмет)
    for g in goals:
        if not isinstance(g, dict) or g.get('kind') != 'skill':
            continue
        gem = idx['gems'].get(english(g.get('title')))
        if not gem:
            continue
        if gem['level'] >= 1:
            g['gemFrom'] = gem['level']
        giver = next((it for it, recs in items if any(gem['keys'] & set(b.get('grants') or ()) for b in recs)), None)
        if giver is not None and giver.get('id'):
            g['grantedBy'] = giver['id']
        if giver is not None:
            continue            # умение предмета: его уровень и гнёзда даёт сам предмет
        skills[g.get('id')] = gem
        if gem.get('spirit') and not gem.get('ascendancy'):
            g['spirit'] = list(gem['spirit'])
    rule = (cat.get('rules') or {}).get('gemSockets') or {}
    names = ((cat.get('lang') or {}).get('ru') or {}).get('bases') or {}
    order = {}        # умение -> части его камней поддержки по порядку: номер гнезда — место части в списке
    for g in goals:
        if not isinstance(g, dict) or g.get('kind') != 'support' or g.get('for') not in skills:
            continue
        parts = order.setdefault(g['for'], [])
        part = g.get('part') or '#' + str(g.get('id'))
        if part not in parts:
            parts.append(part)
        n = parts.index(part) + 1
        if skills[g['for']].get('ascendancy'):
            hero = (rule.get('level') or {}).get(str(n))
            if isinstance(hero, int):
                g['socket'] = {'n': n, 'hero': hero}
        else:
            orb = (rule.get('orbs') or {}).get(str(n))
            if orb:
                g['socket'] = {'n': n, 'orb': '%s (%s)' % (names[orb], orb) if names.get(orb) else orb}
    out = dict(raw, goals=goals)
    table = (cat.get('rules') or {}).get('gemHero')
    if table and not out.get('gemLevels'):
        out['gemLevels'] = list(table)
    return out


def with_stats(cat, raw):
    """Каталог, в таблицу статов которого добавлены свои статы билда (raw — раздел statDefs плана), и
    замечания к ним: (каталог, замечания). Своих статов нет — возвращается тот же каталог. Свой стат
    в таблице: ids — свойства игры из его строк; scale 0.5 — у строк «от # до #» (в стат идёт среднее);
    unit «%» — если все его строки процентные; own — пометка «стат билда, а не каталога». Название встаёт
    в слой каждого языка (statNames). Исходный каталог не меняется."""
    if not cat or not cat.get('stats'):
        return cat, []
    defs, problems = stat_defs(cat, raw)
    if not defs:
        return cat, problems
    known = affix_lines(cat)
    table = dict(cat['stats'].get('stats') or {})
    order = list(cat['stats'].get('order') or table)
    lang = {code: dict(pack, statNames=dict(pack.get('statNames') or {})) for code, pack in (cat.get('lang') or {}).items()}
    for d in defs:
        rec = {'ids': list(dict.fromkeys(i for key in d['lines'] for i in known[key])), 'own': True}
        if all(len(known[key]) == 2 for key in d['lines']):
            rec['scale'] = 0.5
        if all(is_percent(cat, key) for key in d['lines']):
            rec['unit'] = '%'
        table[d['id']] = rec
        order.append(d['id'])
        for pack in lang.values():
            pack['statNames'][d['id']] = [d['name'], d.get('short') or d['name']]
    # то, что посчитано по таблице статов, в новом каталоге считается заново; остальное общее
    out = {k: v for k, v in cat.items() if k not in ('_stat_index', '_carriers', '_kinds', '_own_units', '_kind_stats')}
    out['stats'] = dict(cat['stats'], stats=table, order=order)
    out['lang'] = lang
    return out, problems


