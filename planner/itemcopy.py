# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Sergei Labutin
# Additional terms under GPL-3.0 section 7: see NOTICE.md
"""Вещь из буфера обмена игры: разбор текста и выбор слота, в который она идёт.

Игрок наводит на вещь и жмёт Ctrl+Alt+C — игра кладёт в буфер её текст. Формат сверен с копией из
русского клиента (2026-11-15):

    Класс предмета: Нательные доспехи
    Редкость: Редкий
    Колючий спаситель
    Полные латы
    --------
    Уровень предмета: 47
    --------
    +36% к сопротивлению холоду (rune)
    --------
    { Префикс "Шипованный" (Уровень: 10) — Броня }
    +36(28-56) к броне

Секции разделены строкой дефисов. У каждого аффикса — заголовок в фигурных скобках: префикс или суффикс,
имя и «Уровень: N» — тир (1 — лучший). В строке свойства за выпавшим числом в скобках стоит
диапазон тира. Гибридный аффикс — один заголовок и две строки. Руны и собственные свойства помечены
в конце строки по-английски: (rune), (implicit).

Простая копия (Ctrl+C) заголовков не несёт, а одинаковые свойства разных аффиксов в ней сложены
(здоровье гибрида плюс здоровье чистого префикса) — тир по ней не узнать. Сравнению по статам
(herostats.py) тир и не нужен: там нужна как раз сумма, поэтому годится и такая копия.

Где вещь лежит (надета, в сумке, на земле), в тексте нет. Поэтому копия ничего не меняет сама: она
показывает вещь против своего слота, а «надеть» подтверждает игрок.

Слова клиента — строки таблицы игры ClientStrings на языке клиента (каталог, слой языка: copy): копия читается
на любом из десяти языков игры. Встроенные русские и английские — на случай, когда каталога нет.
"""
import re

from i18n import tr

SEP = '--------'
MAX_CHARS = 20000          # текст вещи — пара тысяч знаков; длиннее — в буфере не вещь
# Подписи копии на языке клиента — строки таблицы игры ClientStrings (каталог: слой языка, поле copy; сборщик —
# catalog/build.py). Язык узнаётся по первой строке копии («Item Class: …» на любом из языков игры). Пока каталог
# подписи не назвал (проверки, старый каталог), действуют встроенные русские и английские — те же строки игры.
BUILTIN = {
    'ru': {'class': 'Класс предмета', 'rarity': 'Редкость', 'ilvl': 'Уровень предмета',
           'rarities': {'Обычный': 'normal', 'Волшебный': 'magic', 'Редкий': 'rare', 'Уникальный': 'unique'},
           'unidentified': 'Неопознано', 'corrupted': 'Осквернено', 'twice': 'Дважды осквернено',
           'cannot': 'Вы не можете использовать этот предмет, его параметры не будут учтены',
           'unscalable': ' — Неизменяемое значение', 'prefix': 'Префикс "{0}"', 'suffix': 'Суффикс "{0}"',
           'implicit': 'Собственное свойство', 'enchant': 'Улучшение', 'crafted': 'Ремесленное {0}',
           'fractured': 'Расколотое {0}', 'desecrated': 'Очернённое {0}', 'tier': '(Уровень: {0})', 'rank': '(Ранг: {0})',
           'uniqueMod': 'Уникальное свойство'},
    'en': {'class': 'Item Class', 'rarity': 'Rarity', 'ilvl': 'Item Level',
           'rarities': {'Normal': 'normal', 'Magic': 'magic', 'Rare': 'rare', 'Unique': 'unique'},
           'unidentified': 'Unidentified', 'corrupted': 'Corrupted', 'twice': 'Twice Corrupted',
           'cannot': 'You cannot use this item. Its stats will be ignored',
           'unscalable': ' — Unscalable Value', 'prefix': 'Prefix Modifier "{0}"', 'suffix': 'Suffix Modifier "{0}"',
           'implicit': 'Implicit Modifier', 'enchant': 'Enhancement', 'crafted': 'Crafted {0}',
           'fractured': 'Fractured {0}', 'desecrated': 'Desecrated {0}', 'tier': '(Tier: {0})', 'rank': '(Rank: {0})',
           'uniqueMod': 'Unique Modifier'},
}
# Пометка в конце строки свойства — чем оно дано; у обычного аффикса пометки нет. Во всех клиентах — по-английски.
MARKS = {'implicit': 'implicit', 'rune': 'rune', 'added rune': 'rune', 'enchant': 'enchant',
         'crafted': 'explicit', 'fractured': 'explicit', 'desecrated': 'explicit'}
# Чем аффикс дан помимо обычного выпадения: сущностью (ремесленный), очернением, расколом. Сравнению это всё тот же
# аффикс (kind — explicit), а помощнику крафта нужна сама пометка: она хранится у свойства полем how. Клиент
# ставит её словом в заголовке аффикса: «{ Ремесленное Суффикс "саламандры" (Уровень: 7) — … }», «{ Очернённое
# Префикс "Баронский" (Уровень: 7) }» (сверено с копиями игрока 2026-11-20); пометка в конце строки по-английски —
# (crafted), (desecrated), (fractured) — тоже читается.
HOWS = ('crafted', 'fractured', 'desecrated')
# Основы слов, которыми копию читали до таблицы строк игры: остаются вдобавок к ней (род и падеж слова в
# заголовке бывают разные — «Очернённое», «Очернённый»).
STEMS = {'ru': {'desecrated': ('очернён', 'очернен'), 'crafted': ('ремесл',), 'fractured': ('раскол',),
                'enchant': ('улучшение',), 'implicit': ('собственное',), 'unique': ('уникальн',)},
         'en': {'desecrated': ('desecrated',), 'crafted': ('crafted',), 'fractured': ('fractured',),
                'enchant': ('enchant', 'enhancement'), 'implicit': ('implicit',), 'unique': ('unique',)}}
RE_QUOTED = re.compile(r'"([^"]*)"|「([^」]*)」|“([^”]*)”|«\s*([^»]*?)\s*»')


def _norm(text):
    """Для сравнения слов: без регистра, «ё» как «е»."""
    return (text or '').casefold().replace('ё', 'е')


def _word(template):
    """Слово шаблона без места для имени и кавычек: «Префикс "{0}"» -> «префикс», «Crafted {0}» -> «crafted»."""
    return _norm(' '.join(re.sub(r'\{0\}|["「」“”«»:：]', ' ', template or '').split()))


def _paren(template, group):
    """Шаблон «(Tier: {0})» -> regex числа в скобках: и обычные, и широкие скобки и двоеточие («(階層：7)»)."""
    m = re.match(r'^\s*[(（]\s*(.*?)\s*[:：]\s*\{0\}\s*[)）]\s*$', template or '')
    if not m:
        return None
    return re.compile(r'[(（]\s*%s\s*[:：]\s*(?P<%s>\d+)\s*[)）]' % (re.escape(m.group(1)), group), re.I)


class CopyLang:
    """Подписи копии одного языка клиента и как по ним читать строки."""

    def __init__(self, lang, labels):
        self.lang = lang
        # «Item Class: », по-французски «Classe d'objet : », по-китайски «物品種類：»
        heads = lambda w: tuple(w + sep for sep in (': ', ' : ', '：', ' ：', ':')) if w else ()
        self.cls, self.rarity, self.ilvl = (heads(labels.get(k)) for k in ('class', 'rarity', 'ilvl'))
        self.rarities = dict(labels.get('rarities') or {})
        self.unidentified = labels.get('unidentified') or None
        self.corrupted = labels.get('corrupted') or None
        self.twice = labels.get('twice') or None
        # «Вы не можете использовать этот предмет, …» — строка начинается с первой части фразы
        cannot = re.split(r'[.,，。、]', labels.get('cannot') or '', maxsplit=1)[0].strip()
        self.cannot = cannot or None
        self.unscalable = labels.get('unscalable') or None
        self.prefix, self.suffix = _word(labels.get('prefix')), _word(labels.get('suffix'))
        stems = STEMS.get(lang) or {}
        self.implicit = [w for w in (_word(labels.get('implicit')),) + stems.get('implicit', ()) if w]
        self.enchant = [w for w in (_word(labels.get('enchant')), _word(labels.get('corruptionEnchant')))
                        + stems.get('enchant', ()) if w]
        # «{ Уникальное свойство — Характеристика }»: свойство уникального предмета — не аффикс, места префикса или
        # суффикса у него нет
        self.unique = [w for w in (_word(labels.get('uniqueMod')),) + stems.get('unique', ()) if w]
        self.how = [(h, w) for h in HOWS for w in (_word(labels.get(h)),) + stems.get(h, ()) if w]
        self.tier, self.rank = _paren(labels.get('tier'), 'tier'), _paren(labels.get('rank'), 'rank')

    def is_corrupted(self, line):
        if line in (self.corrupted, self.twice):
            return True
        # «Дважды осквернено» и подобное: слово «осквернено» в короткой строке
        return bool(self.corrupted) and self.corrupted in line and len(line) <= len(self.corrupted) + 12


_LANGS = [CopyLang(k, v) for k, v in BUILTIN.items()]


def use_catalog(cat):
    """Подписи копии всех языков клиента из каталога (слой языка, поле copy). Нет их — встроенные ru и en."""
    global _LANGS
    packs = (cat or {}).get('lang') or {}
    specs = [CopyLang(lang, p['copy']) for lang, p in packs.items() if (p.get('copy') or {}).get('class')]
    _LANGS = specs or [CopyLang(k, v) for k, v in BUILTIN.items()]


def copy_lang(first):
    """Язык копии по её первой строке («Item Class: …»); не копия предмета — None."""
    return next((spec for spec in _LANGS if _after(first, spec.cls) is not None), None)


RE_HEAD = re.compile(r'^\{\s*(.*?)\s*\}$')
RE_RANGE = re.compile(r'\(\s*-?\d+(?:[.,]\d+)?\s*[-–—]\s*-?\d+(?:[.,]\d+)?\s*\)')
RE_NUM = re.compile(r'\d+(?:[.,]\d+)?')
RE_MARK = re.compile(r'\s*\(([a-z ]+)\)$')


def _after(line, prefixes):
    """Остаток строки после одного из начал («Класс предмета: »), иначе None."""
    for p in prefixes:
        if line.startswith(p):
            return line[len(p):].strip()
    return None


def is_item(text):
    """Похоже ли содержимое буфера на текст вещи. Всё остальное программа не разбирает и не хранит."""
    if not isinstance(text, str) or not text or len(text) > MAX_CHARS:
        return False
    first = text.lstrip().split('\n', 1)[0].strip()
    return copy_lang(first) is not None


def stat_line(line):
    """Строка свойства: текст без пометки, её форма (каждое число заменено на #), выпавшие числа
    и диапазоны тира. «+95(85-99) к максимуму здоровья» -> форма «+# к максимуму здоровья», число 95."""
    text = line.strip()
    mark = None
    m = RE_MARK.search(text)
    if m:
        mark = m.group(1)
        text = text[:m.start()].rstrip()
    for tail in {spec.unscalable for spec in _LANGS if spec.unscalable}:
        if text.endswith(tail):
            text = text[:-len(tail)].rstrip()
    bare = RE_RANGE.sub('', text)
    num = lambda s: float(s.replace(',', '.'))
    ranges = []
    for r in RE_RANGE.findall(text):
        lo, hi = RE_NUM.findall(r)[:2]
        ranges.append((num(lo), num(hi)))
    return {'text': text, 'mark': mark, 'shape': RE_NUM.sub('#', bare),
            'values': [num(n) for n in RE_NUM.findall(bare)], 'ranges': ranges}


def _mod_head(inner, spec=None):
    """Заголовок аффикса без скобок: «Префикс "Массивный" (Уровень: 7) — Здоровье» — по шаблонам языка клиента
    (таблица строк игры): префикс или суффикс, имя в кавычках, ступень (тир) и ранг в скобках, метки после тире."""
    spec = spec or _LANGS[0]
    parts = [p.strip() for p in inner.split('—')]
    head = parts[0]
    tier = rank = None
    for rx, what in ((spec.tier, 'tier'), (spec.rank, 'rank')):
        m = rx.search(head) if rx else None
        if m:
            if what == 'tier':
                tier = int(m.group('tier'))
            else:
                rank = int(m.group('rank'))
            head = head[:m.start()] + head[m.end():]
    q = RE_QUOTED.search(head)
    name = next((g for g in q.groups() if g is not None), None) if q else None
    kind_text = _norm(' '.join(re.sub(r'[:：]', ' ', RE_QUOTED.sub(' ', head)).split()))
    gen = 'prefix' if spec.prefix and spec.prefix in kind_text else \
        'suffix' if spec.suffix and spec.suffix in kind_text else None
    if any(w in kind_text for w in spec.implicit):
        kind = 'implicit'
    elif any(w in kind_text for w in spec.enchant):
        kind = 'enchant'
    elif not gen and any(w in kind_text for w in spec.unique):
        kind = 'unique'
    else:
        kind = 'explicit' if gen else 'other'
    mod = {'kind': kind, 'gen': gen, 'name': name or None, 'tier': tier,
           'tags': [t.strip() for t in parts[1].split(',') if t.strip()] if len(parts) > 1 else [],
           'lines': [], 'shapes': [], 'values': [], 'ranges': []}
    how = next((h for h, w in spec.how if w in kind_text), None)
    if how:
        mod['how'] = how          # у обычного аффикса поля нет: записи надетых предметов остаются как были
    return mod


def _add_line(mod, line):
    s = stat_line(line)
    mod['lines'].append(s['text'])
    mod['shapes'].append(s['shape'])
    mod['values'].append(s['values'])
    mod['ranges'].append(s['ranges'])
    return s


def parse(text):
    """Разбирает текст вещи. Возвращает словарь или None, если это не вещь.

    mods — свойства по порядку: kind (explicit — аффикс, implicit, rune, enchant, unique — свойство уникального
    предмета), gen (prefix / suffix),
    name, tier, tags и строки (lines — как в игре, shapes — с # вместо чисел). advanced — в копии были
    заголовки аффиксов, то есть тиры известны. loose — сколько строк осталось неразобранными; сами эти
    строки — в plain (sec — номер секции, text, shape, values, mark): в простой копии (Ctrl+C) это
    строки аффиксов без заголовков, их читает разбор путевого камня (waystone.py).
    """
    if not is_item(text):
        return None
    sections = [[]]
    for raw in text.replace('\r\n', '\n').replace('\r', '\n').split('\n'):
        line = raw.strip()
        if line == SEP:
            sections.append([])
        elif line:
            sections[-1].append(line)
    sections = [s for s in sections if s]
    head = sections[0]
    spec = copy_lang(head[0])
    item = {'cls': _after(head[0], spec.cls), 'rarity': None, 'name': None, 'base': None, 'ilvl': None,
            'identified': True, 'corrupted': False, 'advanced': False, 'mods': [], 'loose': 0, 'plain': [],
            # язык клиента виден по первой строке: по нему берётся слой языка в каталоге данных игры
            'lang': spec.lang}
    names = head[1:]
    if names and _after(names[0], spec.rarity) is not None:
        item['rarity'] = spec.rarities.get(_after(names[0], spec.rarity))
        names = names[1:]
    body = sections[1:]
    if names and spec.cannot and names[0].startswith(spec.cannot):
        # игра сама сказала, что герой вещью пользоваться не может (требования или не тот класс оружия)
        item['unusable'] = True
        names, body = (body[0] if body else []), body[1:]
    if names:
        # у редкой и уникальной вещи две строки — имя и база; у обычной и волшебной одна: в ней и база
        item['name'] = names[0]
        item['base'] = names[1] if len(names) > 1 else names[0]
    def loose(no, s):
        item['loose'] += 1
        item['plain'].append({'sec': no, 'text': s['text'], 'shape': s['shape'], 'values': s['values'],
                              'mark': s['mark']})

    for no, sec in enumerate(body):
        if any(RE_HEAD.match(ln) for ln in sec):
            item['advanced'] = True
            cur = None
            for ln in sec:
                h = RE_HEAD.match(ln)
                if h:
                    cur = _mod_head(h.group(1), spec)
                    item['mods'].append(cur)
                elif cur is not None:
                    s = _add_line(cur, ln)
                    # пометка в строке сильнее заголовка: руна остаётся руной, что бы ни стояло выше
                    if MARKS.get(s['mark']) and MARKS[s['mark']] != 'explicit':
                        cur['kind'] = MARKS[s['mark']]
                    elif s['mark'] in HOWS:
                        cur['how'] = s['mark']
                else:
                    loose(no, stat_line(ln))
            continue
        level = _after(sec[0], spec.ilvl)
        if level is not None:
            digits = RE_NUM.search(level)
            item['ilvl'] = int(float(digits.group(0).replace(',', '.'))) if digits else None
            continue
        if spec.unidentified and sec[0].startswith(spec.unidentified):
            item['identified'] = False
            continue
        if spec.is_corrupted(sec[0]):
            item['corrupted'] = True
            continue
        for ln in sec:
            s = stat_line(ln)
            kind = MARKS.get(s['mark'])
            if kind and kind != 'explicit':
                # руна или собственное свойство: своя строка без заголовка, в аффиксы не идёт
                mod = {'kind': kind, 'gen': None, 'name': None, 'tier': None, 'tags': [],
                       'lines': [], 'shapes': [], 'values': [], 'ranges': []}
                _add_line(mod, ln)
                item['mods'].append(mod)
            else:
                loose(no, s)
    return item


# --- вещь в каталоге данных игры ------------------------------------------------------------------
# Вещь узнаётся по идентификаторам игры, а не по словам: её база ищется в каталоге по названию на языке
# клиента (слой языка), от базы известны класс и метки; за каждой строкой аффикса находится его
# семейство в игре. План ссылается на те же семейства, поэтому сравнение не зависит от языка.

def find_base(cat, lang, name):
    """База в каталоге по строке названия вещи. У волшебной вещи база стоит внутри имени
    («Усиленные Грубые поножи тритона»), поэтому ищем самое длинное название базы, входящее в строку."""
    names = ((cat.get('lang') or {}).get(lang) or {}).get('bases') or {}
    text = (name or '').lower()
    best = None
    for en, local in names.items():
        low = local.lower()
        if low and low in text and (best is None or len(low) > len(best[1])):
            best = (en, low)
    if best is None:
        return None
    return next((b for b in cat['bases'].values() if b['name'] == best[0]), None)


def family_of(cat, lang, mod, tags):
    """Семейство аффикса по его строкам на вещи: то же место (префикс / суффикс), столько же строк,
    каждая строка — одно из написаний своей строки семейства, и на базе с такими метками оно бывает
    (так различаются «к броне» на доспехе и на поясе). None — такого семейства в каталоге нет."""
    import gamedata
    texts = ((cat.get('lang') or {}).get(lang) or {}).get('stats') or {}
    shapes = [s.replace('+#', '#') for s in mod['shapes']]
    for key, fam in cat['mods'].items():
        lines = fam.get('lines')
        if not lines or len(lines) != len(shapes) or (mod.get('gen') and fam['gen'] != mod['gen']):
            continue
        for order in (lines, lines[::-1]):
            if all(sh in texts.get(k, ()) for sh, k in zip(shapes, order)) and gamedata.tiers(fam, tags):
                return key
    return None


def identify(cat, item):
    """Дополняет разобранную вещь сведениями из каталога: cls_id и tags — класс и метки её базы,
    у каждого аффикса fam — его семейство. Без каталога (или без слоя языка клиента) вещь остаётся
    как есть: слот ей найдётся по слову «Класс предмета», а сравнить её по статам будет нечем."""
    if not cat or not item or item.get('lang') not in (cat.get('lang') or {}):
        return item
    import gamedata
    base = find_base(cat, item['lang'], item.get('base'))
    if base:
        item['cls_id'], item['tags'] = base['class'], base['tags']
        item['base_en'] = base['name']
        # свойства базы, которых на самой вещи не написано (штраф скорости доспеха и щита)
        item['own'] = {k: base[k] for k in ('speed',) if base.get(k)}
    else:
        # Названия базы в каталоге нет (новая база, иное написание): класс берём из строки «Класс
        # предмета» по словам слоя языка, метки — с любой базы этого класса. Слот найдётся, а род доспеха
        # может не совпасть — тогда часть строк просто не сопоставится.
        cls = ((cat['lang'][item['lang']].get('classes') or {}).get(item.get('cls')))
        item['cls_id'] = cls
        item['tags'] = gamedata.gear_tags(cat, cls) if cls else None
    for m in item.get('mods') or []:
        m['fam'] = (family_of(cat, item['lang'], m, item['tags'])
                    if item['tags'] and m.get('kind') == 'explicit' else None)
    return item


# --- вещь и слот ------------------------------------------------------------------------------------

def _ru_name(title):
    """«Прочный самострел (Sturdy Crossbow)» -> «прочный самострел»: имя базы, как его пишет игра."""
    return (title or '').split(' (', 1)[0].split(':', 1)[0].strip().lower()


def _sign(n):
    return (n > 0) - (n < 0)


def _classes(owner):
    """Классы предметов слота (поле classes плана); кривое поле — как пустое."""
    cl = (owner or {}).get('classes')
    return [c for c in cl if isinstance(c, str)] if isinstance(cl, list) else []


def same_item(a, b):
    """Один и тот же предмет: совпал текст из игры — имя, база, редкость, уровень предмета и все строки свойств. Как
    программа разобрала текст (вид свойства, пометки, числа после записи в файл), не в счёт: запись в памяти надетого
    могла быть сделана прежней версией разбора (свойство уникального до 2026-11-23 читалось «прочим»)."""
    def text(x):
        return [x.get('name'), x.get('base'), x.get('rarity'), x.get('ilvl'), bool(x.get('corrupted')),
                x.get('identified', True), [list(m.get('lines') or ()) for m in x.get('mods') or [] if isinstance(m, dict)],
                [p.get('text') for p in x.get('plain') or [] if isinstance(p, dict)]]
    return isinstance(a, dict) and isinstance(b, dict) and text(a) == text(b)


def slot_rows(view):
    """Строки слотов из состояния забега: в каждом слоте — то, что в нём носят сейчас (рюкзака нет)."""
    return [r for r in view.get('holders') or [] if r.get('slot')]


def compare(plan, view, item):
    """Куда идёт вещь из буфера: по строке на каждый слот-кандидат (у кольца их два). Чистая функция.

    В строке — слот, его линия (шаг, с которого в слоте носят то, что сейчас) и что план говорит о базе вещи (base):
    что лежит в слоте сейчас (now), какая база у вещи (new), знак разницы (delta), цель, которую отметит «надеть» (to),
    и названы ли базы в плане по именам (named: самострелы — да, «любой шлем» — нет). held — база слота отмечена
    надетой. Чем вещь лучше надетой, здесь не решается: это считает herostats.compare по статам билда, и программа
    добавляет ответ к строке (server._stats_view).

    Вещь идёт в слот, если её класс носят в нём в любом из периодов: надеть её можно всегда, даже раньше периода по
    плану (щит во вторую руку до вознесения) — статы героя считаются по тому, что надето на деле. Рюкзака нет.
    """
    if not item:
        return None
    out = {'at': item.get('at'), 'name': item.get('name'), 'base': item.get('base'), 'cls': item.get('cls'),
           'rarity': item.get('rarity'), 'ilvl': item.get('ilvl'), 'rows': [], 'pick': None, 'note': None}
    # Вещь опознана по каталогу (identify): класс — идентификатор игры. Без каталога — слово клиента.
    by_id = 'tags' in item
    if by_id and not item.get('tags'):
        out['note'] = tr('база «%s» не найдена в данных игры') % item.get('base')
        return out
    # класс вещи: идентификатор игры (из каталога) и слово клиента — план может называть любой из них
    names = {item.get('cls_id'), item.get('cls')} - {None} if by_id else {item.get('cls')}
    slots = [s for s in plan.get('slots') or [] if names & set(_classes(s))]
    if not slots:
        out['note'] = tr('класс «%s» не из плана') % item.get('cls')
        return out
    if not item.get('identified', True):
        out['note'] = tr('предмет не опознан')
    goal_by_id = {g['id']: g for g in plan.get('goals') or []}
    slot_ids = [s['id'] for s in slots]
    slot_name = {s['id']: s.get('name') or s['id'] for s in slots}
    for r in slot_rows(view):
        if r['slot'] not in slot_ids:
            continue
        line = r.get('line')
        base, held = None, None
        lad = r.get('base')
        if lad and lad.get('chain'):
            chain = lad['chain']
            held = lad.get('have') or lad.get('bag')
            now_i = chain.index(held['id']) if held and held['id'] in chain else -1
            base_text = (item.get('base') or '').lower()

            def by_name(gid):
                # ступень называет базу предмета: её именем или базой, одинаковой с ним по данным игры (twins)
                g = goal_by_id.get(gid) or {}
                ru = _ru_name(g.get('title'))
                return bool(not g.get('any') and ru and (ru in base_text or (item.get('base_en') or '') in (g.get('twins') or ())))
            named = [i for i, gid in enumerate(chain) if by_name(gid)]
            anys = [i for i, gid in enumerate(chain) if (goal_by_id.get(gid) or {}).get('any')]
            new_i = named[-1] if named else (anys[-1] if anys else None)
            base = {'chain': chain, 'now': held['title'] if held else None,
                    'new': goal_by_id[chain[new_i]].get('title') if new_i is not None else item.get('base'),
                    'to': chain[new_i] if new_i is not None else None,
                    'delta': _sign(new_i - now_i) if new_i is not None and now_i >= 0 else 0,
                    # базы в плане названы (самострелы по именам), а не «любая вещь»: тогда о базе есть
                    # что сказать — она лучше, хуже или её в плане нет вовсе (to пусто)
                    'named': any(not (goal_by_id.get(gid) or {}).get('any') for gid in chain),
                    # план называет в этой строке именно базу предмета (а не «любое»)
                    'byName': bool(named)}
        out['rows'].append({'row': r['id'], 'slot': r['slot'], 'slotName': slot_name[r['slot']], 'line': line,
                            'base': base, 'held': held is not None})
    if not out['rows']:
        out['note'] = tr('в плане сейчас нет слота под «%s»') % item.get('cls')
        return out
    out['pick'] = out['rows'][0]['row']
    return out


def wear_marks(cmp_view, row_id):
    """Отметки плана, которые ставит «надеть» для строки слота: список (цель, статус) по порядку.

    В плане у слота остались только базы: вещь встаёт на свою базу в лесенке слота, отметки баз
    повыше снимаются. База не из плана ничего не отмечает (пустой список). Цели по стату и цели будущих
    периодов отмечаются сами — по запомненной вещи. None — такой строки нет.
    """
    row = next((x for x in (cmp_view or {}).get('rows') or [] if x['row'] == row_id), None)
    if row is None:
        return None
    puts = []
    b = row.get('base')
    if b and b.get('to'):
        i = b['chain'].index(b['to'])
        puts += [(gid, 0) for gid in b['chain'][i + 1:]]
        puts.append((b['to'], 2))
    return puts
