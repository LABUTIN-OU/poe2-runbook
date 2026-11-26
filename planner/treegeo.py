# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Sergei Labutin
# Additional terms under GPL-3.0 section 7: see NOTICE.md
"""Геометрия дерева пассивных умений для страницы — из данных, которые выкладывает GGG.

Исходник: treedata/ggg/data.json — файл из https://github.com/grindinggear/poe2-skilltree-export
(рядом с ним лежит SOURCE.txt: откуда и когда скачан). Из него берётся только то, что нужно, чтобы
нарисовать карту: узлы основного дерева с координатами и связи между ними. Результат —
planner/static/tree.json, страница читает его один раз.

    nodes: [id, x, y, вид, название]   вид: 0 малый, 1 «Характеристика», 2 значимый, 3 ключевой,
                                       4 гнездо самоцвета, 5 старт класса; id — как в логе игры
    edges: [a, b] или [a, b, cx, cy]   номера узлов в списке nodes; cx, cy — центр дуги, по которой идёт связь
    starts: {id: [сила, ловкость, интеллект]}   атрибуты, с которыми начинает класс этого узла старта
    classes: [{id, base, start, ascendancies}]  классы героя, за которые можно играть: имя класса, его
                                       атрибуты [сила, ловкость, интеллект], id узла старта и вознесения
                                       ([{id, name}]: id — как в id узлов вознесения в логе игры, Sorceress3)
    anoint: {emotions: [id эмоции], nodes: {id: [skill, [номера эмоций], название?]}}   узлы, которые берут
                                       зачарованием амулета: рецепт по порядку; название — только у узла без места

Не входят: деревья восхождения (у них свои очки и своё место), «мастерства» — украшения в центре
групп, которые взять нельзя, — и узлы только для зачарования («Господство»): связей у них нет, они есть
лишь в anoint.

Второй файл — planner/static/treestats.json: что даёт каждый узел ({id: [строки]}, текст GGG,
по-английски, без разметки), вместе с узлами восхождения. Страница берёт его, когда открывают правку
дерева на карте; программа по нему считает, какой стат дерево обнуляет и сколько атрибутов оно даёт.

Те же строки на языках страниц программы — planner/static/treestats.<язык>.json (ru, de, fr, es, pt, ja, ko, th):
GGG пишет строки только по-английски, перевод — словами самой игры. Источник — описания свойств из файлов игры
в источниках каталога (catalog/sources/<версия>/dat/: passive_skill_stat_descriptions.csd.gz, stat_descriptions.csd.gz
— у каждого свойства варианты строки на всех языках клиента, catalog/dat_pack.py) и строки её интерфейса
(ClientStrings: «Grants {0} Passive Skill Points», «Grants Skill: {0}»); английская строка узнаётся по английскому
варианту, числа переносятся в вариант того же языка. Запасной путь — таблица статов Exiled Exchange 2
(<язык>-stats.ndjson против en-stats.ndjson, есть для ru). Строка, которой нет нигде, остаётся английской.
Страницы «Игра» и «Редактор» берут файл своего языка (подсказки узлов, «куда вложить очки»).

Когда выйдет новая версия игры, GGG выложит новые данные: заменить data.json и запустить заново.

Запуск: python planner/treegeo.py [data.json] [tree.json] [treestats.json] [папка источников каталога]
"""
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent / 'treedata' / 'ggg' / 'data.json'
TARGET = HERE / 'static' / 'tree.json'
STATS = HERE / 'static' / 'treestats.json'
CATALOG_SOURCES = HERE.parent / 'catalog' / 'sources'   # здесь current.txt называет папку версии игры
RE_MARK = re.compile(r'\[([^\]|]*)\|([^\]]*)\]')     # [EnergyShield|Energy Shield] -> Energy Shield
RE_MARK1 = re.compile(r'\[([^\]]*)\]')               # [Spell] -> Spell
RE_TAG = re.compile(r'<[^<>{}]*>\{([^{}]*)\}')         # <underline>{Fire Spell on Hit} -> Fire Spell on Hit

SMALL, ATTRIBUTE, NOTABLE, KEYSTONE, SOCKET, START = range(6)


def kind_of(n):
    if n.get('classStartIndex') is not None:
        return START
    if n.get('isKeystone'):
        return KEYSTONE
    if n.get('isJewelSocket'):
        return SOCKET
    if n.get('isNotable'):
        return NOTABLE
    if n.get('isGenericAttribute'):
        return ATTRIBUTE
    return SMALL


def clean(name):
    """Название узла без разметки ссылок: у гнезда самоцвета GGG пишет «[Jewel] Socket»."""
    return RE_MARK1.sub(r'\1', RE_MARK.sub(r'\2', str(name or ''))).strip()


def plain(text):
    """Текст строки без разметки: ссылки [Ключ|слово] и [Слово] — словом, <underline>{…} — текстом."""
    return RE_TAG.sub(r'\1', RE_MARK1.sub(r'\1', RE_MARK.sub(r'\2', str(text or ''))))


def build(data):
    """Данные GGG -> компактная геометрия: {'nodes': [...], 'edges': [...]}."""
    raw = data['nodes']
    linked = {str(e.get(k)) for e in data.get('edges') or [] for k in ('from', 'to')}
    keep = {}
    for key, n in raw.items():
        if not isinstance(n, dict) or not n.get('id') or 'x' not in n or 'y' not in n:
            continue
        if n.get('ascendancyId') or n.get('isMastery'):
            continue
        # Узел только для зачарования (у него есть рецепт, а связей нет — «Господство»): места на дереве у него
        # нет, хотя координаты в данных стоят. На карту он не идёт — только в список зачарования (anoint).
        if n.get('recipe') and str(key) not in linked and not n.get('in') and not n.get('out'):
            continue
        keep[str(key)] = n
    order = sorted(keep, key=lambda k: (keep[k]['y'], keep[k]['x'], k))
    index = {k: i for i, k in enumerate(order)}
    # название — без разметки ссылок: у гнезда самоцвета GGG пишет «[Jewel] Socket»
    nodes = [[keep[k]['id'], int(round(keep[k]['x'])), int(round(keep[k]['y'])), kind_of(keep[k]),
              clean(keep[k].get('name'))] for k in order]
    edges, seen = [], set()
    for e in data.get('edges') or []:
        a, b = index.get(str(e.get('from'))), index.get(str(e.get('to')))
        if a is None or b is None or a == b:
            continue
        pair = (min(a, b), max(a, b))
        if pair in seen:
            continue
        seen.add(pair)
        if isinstance(e.get('orbitX'), (int, float)) and isinstance(e.get('orbitY'), (int, float)):
            edges.append([a, b, int(round(e['orbitX'])), int(round(e['orbitY']))])
        else:
            edges.append([a, b])
    # Старт класса: с какими атрибутами герой начинает. У узла старта два класса (прежний и нынешний:
    # WITCH — Witch и Sorceress), атрибуты у них одни и те же; разошлись бы — старт в файл не идёт.
    classes, starts = data.get('classes') or [], {}
    for k in order:
        idx = keep[k].get('classStartIndex')
        idx = idx if isinstance(idx, list) else [] if idx is None else [idx]
        base = {(classes[i].get('base_str'), classes[i].get('base_dex'), classes[i].get('base_int'))
                for i in idx if isinstance(i, int) and 0 <= i < len(classes)}
        if len(base) == 1 and all(isinstance(x, int) for x in next(iter(base))):
            starts[keep[k]['id']] = list(next(iter(base)))
    return {'tree': data.get('tree'), 'nodes': nodes, 'edges': edges, 'starts': starts,
            'classes': hero_classes(data, [keep[k] for k in order]), 'anoint': anoints(raw, keep)}


def anoints(raw, keep):
    """Какие узлы берут зачарованием амулета (жидкие эмоции, Liquid Emotions) и чем:
    {emotions: [id эмоций GGG — «LiquidEnvy» …], nodes: {id узла: [номер узла в данных игры, рецепт]}}; у узла
    без места на дереве третьим — его название. Номер (skill) связывает узел со строкой предмета «Активирует …»:
    слой языка каталога знает её по этому номеру. Рецепт — три эмоции по порядку (номера в emotions): порядок
    важен, те же три в другом порядке — другой узел."""
    rows = {n['id']: (key, n) for key, n in raw.items()
            if isinstance(n, dict) and n.get('id') and isinstance(n.get('recipe'), list) and n['recipe']}
    emotions = sorted({str(r) for _, n in rows.values() for r in n['recipe']})
    at = {e: i for i, e in enumerate(emotions)}
    nodes = {}
    for nid, (key, n) in rows.items():
        row = [int(key) if str(key).isdigit() else str(key), [at[str(r)] for r in n['recipe']]]
        if str(key) not in keep:
            row.append(clean(n.get('name')))
        nodes[nid] = row
    return {'emotions': emotions, 'nodes': nodes}


def hero_classes(data, nodes):
    """Классы героя, за которые в игре можно играть, — те, у которых в данных GGG есть названное
    вознесение: [{id — имя класса, base — [сила, ловкость, интеллект], start — id узла старта,
    ascendancies — [{id, name}]}]. Вознесение без имени (заготовка будущего) не идёт."""
    classes = data.get('classes') or []
    start = {}
    for n in nodes:
        idx = n.get('classStartIndex')
        for i in idx if isinstance(idx, list) else [] if idx is None else [idx]:
            start.setdefault(i, n['id'])
    out = []
    for i, c in enumerate(classes):
        asc = [{'id': a['id'], 'name': a['name']} for a in c.get('ascendancies') or []
               if isinstance(a, dict) and a.get('id') and a.get('name')]
        base = [c.get('base_str'), c.get('base_dex'), c.get('base_int')]
        if c.get('name') and asc and all(isinstance(x, int) for x in base):
            out.append({'id': c['name'], 'base': base, 'start': start.get(i), 'ascendancies': asc})
    return out


def raw_stats(data):
    """Свойства каждого узла дерева героя, как их пишет GGG: {id: [свойство]} — без разметки, перенос строки внутри
    свойства сохранён (одно свойство игры бывает в две строки). Узлы восхождения входят."""
    out = {}
    for n in data['nodes'].values():
        if not isinstance(n, dict) or not n.get('id') or 'x' not in n or 'y' not in n:
            continue
        if n.get('isMastery'):
            continue
        items = [plain(s).strip() for s in n.get('stats') or []]
        items = [s for s in items if s.strip()]
        if items:
            out[n['id']] = items
    return out


def stats(data):
    """Что даёт каждый узел дерева героя: {id: [строки]} — текст GGG без разметки ссылок. Узлы восхождения
    сюда входят тоже (на карте их нет, но взятые героем узлы лог называет теми же id: по строкам видно,
    что они дают, — например атрибуты)."""
    return {nid: [p.strip() for s in items for p in s.split('\n') if p.strip()] for nid, items in raw_stats(data).items()}


RE_NUM = re.compile(r'[+-]?\d+(?:\.\d+)?')        # число строки стата: «+5», «12», «0.5», «-10»
RE_SLOT = re.compile(r'([+-]?)#')                  # место числа в шаблоне, со знаком шаблона, если он есть


def stat_rows(path):
    """Таблица статов Exiled Exchange 2 (<язык>-stats.ndjson): по записи на строку —
    {ref: английский шаблон с #, matchers: [{string, negate?, value?}]}. ref у записей одинаков во всех языках."""
    rows = []
    with open(path, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def translator(en_rows, xx_rows):
    """Перевод строки «что даёт узел» с английского текста GGG на язык таблицы xx_rows: функция строка ->
    перевод или None. Шаблон ищется среди английских форм (числа — #), без учёта регистра; знак «+» перед числом
    у таблицы не пишется — пробуется и без него. Запись другого языка — по тому же ref; форма берётся та же:
    «уменьшение» (negate) — своей формой, форма для одного числа (value) — своей, если она есть. Числа идут
    в перевод по порядку, со своими знаками («+5 к силе»)."""
    other = {}
    for e in xx_rows:
        if isinstance(e, dict) and e.get('ref'):
            other.setdefault(e['ref'], e.get('matchers') or [])
    index = {}
    for e in en_rows:
        if not isinstance(e, dict) or not e.get('ref'):
            continue
        for m in e.get('matchers') or []:
            s = str(m.get('string') or '').strip()
            if s:
                index.setdefault(s.lower(), []).append((e['ref'], bool(m.get('negate')), m.get('value')))

    def pick(matchers, negate, value):
        same = [m for m in matchers if bool(m.get('negate')) == negate and str(m.get('string') or '').strip()]
        exact = [m for m in same if value is not None and m.get('value') == value]
        plain = [m for m in same if m.get('value') is None]
        return (exact or plain or [None])[0]

    def fill(text, nums):
        it = iter(nums)
        # у числа свой знак («+5»): знак шаблона перед ним не повторяется; двойной пробел таблицы — одним
        text = RE_SLOT.sub(lambda m: (lambda n: n if n[:1] in '+-' else m.group(1) + n)(next(it)), text)
        return ' '.join(text.split())

    def tr(line):
        nums = RE_NUM.findall(line)
        shape = RE_NUM.sub('#', line).strip()
        for cand in dict.fromkeys((shape, shape.replace('+#', '#'))):
            for ref, negate, value in index.get(cand.lower(), ()):
                m = pick(other.get(ref) or [], negate, value)
                if m is None:
                    continue
                text = str(m['string']).strip()
                if text.count('#') != len(nums):
                    continue
                return fill(text, nums)
        return None
    return tr


def lang_stats(what, en_rows, xx_rows):
    """Строки узлов (what — результат stats) на языке таблицы xx_rows: {id: [строки]}; строка без перевода
    остаётся английской. Второе значение — (сколько строк переведено, сколько всего)."""
    tr = translator(en_rows, xx_rows)
    out, done, total = {}, 0, 0
    for nid, lines in what.items():
        got = []
        for line in lines:
            total += 1
            t = tr(line)
            done += t is not None
            got.append(t if t is not None else line)
        out[nid] = got
    return out, (done, total)


# --- строки узлов словами игры на любом её языке: описания свойств (файлы игры) -----------------------------------

# Файлы описаний в источниках каталога (dat/): первым — описания пассивных умений (ключевые узлы, вознесение), за ним
# общие. Языки — коды каталога; упрощённого китайского клиента, который читает программа, нет.
DESC_FILES = ('passive_skill_stat_descriptions.csd.gz', 'stat_descriptions.csd.gz')
DESC_LANGS = {'Russian': 'ru', 'German': 'de', 'French': 'fr', 'Spanish': 'es', 'Portuguese': 'pt', 'Japanese': 'ja',
              'Korean': 'ko', 'Thai': 'th', 'Traditional Chinese': 'zh-Hant'}
PAGE_LANGS = ('ru', 'de', 'fr', 'es', 'pt', 'ja', 'ko', 'th')     # языки страниц программы, кроме английского
# Строки интерфейса игры, которыми клиент сам пишет часть строк узла (их нет в описаниях свойств)
UI_ROWS = ('PassiveNodeGrantsPassivePoint', 'PassiveNodeGrantsPassivePoints', 'PassiveNodeGrantsSpecialisationPoint',
           'PassiveNodeGrantsSpecialisationPoints')
GRANTED = 'ItemDisplayGrantedSkillNoScaling'        # «Grants Skill: <underline>{{{0}}}» — узел даёт умение
RE_PLACE = re.compile(r'\{(\d*)(?::([^}]*))?\}')
RE_SLOTS = re.compile(r'[+-]?\{(\d*)(?::([^}]*))?\}|[+-]?\d+(?:\.\d+)?')
# обработчик описания -> как из числа на экране получить значение свойства (по нему выбирается форма строки языка)
UNDO = {'negate': -1, 'double': 0.5, 'negate_and_double': -0.5, 'divide_by_one_hundred': 100, 'divide_by_ten': 10,
        'milliseconds_to_seconds': 1000, 'per_minute_to_per_second': 60, 'times_twenty': 0.05, 'divide_by_two': 2,
        'divide_by_three': 3, 'divide_by_five': 5, 'divide_by_fifteen': 15, 'divide_by_fifty': 50,
        'deciseconds_to_seconds': 10}


def parse_descriptions(text):
    """Описания свойств игры (файл .csd, текст): [{ids: [коды], lang: {язык: [(условия, шаблон, обработчики)]}}].
    Условия — по одному на свойство («1|#», «#», «!0»); обработчики — [(имя, номер свойства с 1 или None)];
    шаблон — без разметки, «\\n» в нём — перенос строки."""
    out, cur, lang = [], None, None
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith('description') and i + 1 < len(lines):
            head = lines[i + 1].split()
            n = int(head[0]) if head and head[0].isdigit() else 0
            cur, lang = {'ids': head[1:1 + n], 'lang': {}}, 'en'
            out.append(cur)
            i += 2
            continue
        if cur is not None and line.startswith('lang '):
            lang = DESC_LANGS.get(line[5:].strip().strip('"'))
            i += 1
            continue
        if cur is not None and line.isdigit():
            count = int(line)
            rows = []
            for v in lines[i + 1:i + 1 + count]:
                a, b = v.find('"'), v.rfind('"')
                if not 0 <= a < b:
                    continue
                words = v[b + 1:].split()
                handlers = [(w, int(words[k + 1]) if k + 1 < len(words) and words[k + 1].isdigit() else None)
                            for k, w in enumerate(words) if not w.isdigit()]
                rows.append((v[:a].split(), plain(v[a + 1:b]).replace('\\n', '\n'), handlers))
            if lang:
                cur['lang'][lang] = rows
            i += 1 + count
            continue
        i += 1
    return out


def read_descriptions(base):
    """Описания свойств из папки версии источников каталога (dat/*.csd.gz) по порядку DESC_FILES; нет — []."""
    import gzip
    out = []
    for name in DESC_FILES:
        path = Path(base) / 'dat' / name
        if path.is_file():
            out += parse_descriptions(gzip.decompress(path.read_bytes()).decode('utf-16'))
    return out


def ui_descriptions(base):
    """Строки интерфейса игры для строк узлов — в виде описаний с одним вариантом (UI_ROWS), и шаблон «узел даёт
    умение» по языкам ({язык: шаблон}). Нет таблицы ClientStrings — ([], {})."""
    import gzip
    path = Path(base) / 'dat' / 'ClientStrings.json.gz'
    if not path.is_file():
        return [], {}
    tab = json.loads(gzip.decompress(path.read_bytes()).decode('utf-8'))
    ids, texts = tab['columns']['Id'], tab['columns']['Text']
    at = {rid: k for k, rid in enumerate(ids)}
    langs = texts if isinstance(texts, dict) else {'en': texts}
    descs = []
    for rid in UI_ROWS:
        if rid in at:
            descs.append({'ids': [rid], 'lang': {lang: [([], plain(vals[at[rid]]), [])] for lang, vals in langs.items()
                                                 if isinstance(vals[at[rid]], str) and vals[at[rid]].strip()}})
    granted = {lang: vals[at[GRANTED]] for lang, vals in langs.items() if GRANTED in at and isinstance(vals[at[GRANTED]], str)}
    return descs, granted


def _slots(template):
    """Места чисел шаблона по порядку: [(номер свойства или None — число в самом тексте, формат)] и скелет: шаблон,
    где каждое число — «#» (знак перед местом входит в место), в одну строку, строчными."""
    marks, out, last, auto = [], [], 0, 0
    for m in RE_SLOTS.finditer(template):
        if m.group(0).lstrip('+-').startswith('{'):
            idx = int(m.group(1)) if m.group(1) else auto
            if not m.group(1):
                auto = idx + 1
            marks.append((idx, m.group(2) or ''))
        else:
            marks.append((None, ''))
        out += [template[last:m.start()], '#']
        last = m.end()
    out.append(template[last:])
    return marks, ' '.join(''.join(out).split()).lower()


def _cond_ok(cond, value):
    if value is None or cond in ('#', ''):
        return True
    try:
        if cond.startswith('!'):
            return value != float(cond[1:])
        if '|' in cond:
            lo, hi = cond.split('|', 1)
            return (lo == '#' or value >= float(lo)) and (hi == '#' or value <= float(hi))
        return value == float(cond)
    except ValueError:
        return True


def desc_translator(descs, lang, granted=None, names=None, source='en'):
    """Перевод свойства узла (текст GGG без разметки, может быть в две строки) на язык lang словами игры: функция
    свойство -> [строки] или None. Вариант описания на языке строки (source, обычно английский) узнаётся по скелету
    (числа — «#»), числа идут в вариант языка lang по номерам свойств; форма языка — та же по счёту, а если у языка
    свои формы (единственное и множественное число) — по условиям на значения. «Узел даёт умение» — шаблоном игры,
    имя умения — словами игры на этом языке, если они известны (names: английское -> местное)."""
    index = {}
    for d in descs:
        for k, (_, tmpl, _) in enumerate(d['lang'].get(source) or ()):
            marks, skel = _slots(tmpl)
            index.setdefault(skel, []).append((d, k, marks))
    grant_en = granted.get(source) if granted else None
    grant_xx = granted.get(lang) if granted else None
    head = grant_en.split('<', 1)[0] if grant_en and '<' in grant_en else None

    def pick(d, k, shown):
        en_rows, rows = d['lang'][source], d['lang'].get(lang)
        if not rows and source != 'en':
            # у описания нет строки на этом языке — игра пишет её по-английски (имена: «Amanamu»)
            rows = d['lang'].get('en')
        if not rows:
            return None
        if len(rows) == len(en_rows) and all(r[0] == e[0] for r, e in zip(rows, en_rows)):
            return rows[k]
        conds, _, handlers = en_rows[k]
        raw = {}
        for i in range(len(d['ids'])):
            if i in shown:
                v = float(shown[i])
                for name, n in handlers:
                    base = re.sub(r'_\d?dp(_if_required)?$', '', name)
                    if n == i + 1 and base in UNDO:
                        v *= UNDO[base]
                raw[i] = v
            else:
                try:
                    raw[i] = float(conds[i]) if i < len(conds) else None
                except ValueError:
                    raw[i] = None
        return next((r for r in rows if all(_cond_ok(c, raw.get(i)) for i, c in enumerate(r[0]))),
                    rows[k] if k < len(rows) else None)

    def fill(row, en_handlers, shown):
        neg_en = {n for name, n in en_handlers if name.startswith('negate')}
        neg_xx = {n for name, n in row[2] if name.startswith('negate')}
        auto = [0]

        def one(m):
            idx = int(m.group(1)) if m.group(1) else auto[0]
            if not m.group(1):
                auto[0] = idx + 1
            num = shown.get(idx)
            if num is None:
                return m.group(0)
            if ((idx + 1) in neg_en) != ((idx + 1) in neg_xx):
                num = num[1:] if num.startswith('-') else '-' + num.lstrip('+')
            sign = '-' if num.startswith('-') else '+' if '+' in (m.group(2) or '') else ''
            return sign + num.lstrip('+-')
        return RE_PLACE.sub(one, row[1])

    def tr(item):
        text = ' '.join(item.split())
        if head and grant_xx and text.startswith(head) and len(text) > len(head):
            name = text[len(head):].strip()
            local = (names or {}).get(name) or name
            # «{{» и «}}» шаблона — сами скобки разметки, {0} — имя умения
            body = re.sub(r'\{\{|\}\}|\{0\}', lambda m: {'{{': '{', '}}': '}'}.get(m.group(0), local), grant_xx)
            return [' '.join(plain(body).split())]
        skel = ' '.join(RE_NUM.sub('#', text).split()).lower()
        nums = RE_NUM.findall(text)
        for d, k, marks in index.get(skel, ()):
            if len(marks) != len(nums):
                continue
            shown, ok = {}, True
            for (idx, _), num in zip(marks, nums):
                if idx is not None:
                    ok = ok and shown.setdefault(idx, num) == num
            if not ok:
                continue
            row = pick(d, k, shown)
            if row is None:
                continue
            out = [' '.join(x.split()) for x in fill(row, d['lang'][source][k][2], shown).split('\n')]
            if any(RE_PLACE.search(x) for x in out):
                continue
            return [x for x in out if x]
        return None
    return tr


def page_stats(raw, tr_desc, tr_line=None):
    """Строки узлов на языке: {id: [строки]} по свойствам raw (raw_stats). Свойство переводится целиком (описанием
    игры), а нет — по строкам: описанием, потом таблицей tr_line; чего нет нигде, остаётся английским. Второе
    значение — (сколько английских строк переведено, сколько всего)."""
    out, done, total = {}, 0, 0
    for nid, items in raw.items():
        got = []
        for item in items:
            parts = [x.strip() for x in item.split('\n') if x.strip()]
            total += len(parts)
            whole = tr_desc(item) if tr_desc else None
            if whole:
                got += whole
                done += len(parts)
                continue
            for part in parts:
                t = tr_desc(part) if tr_desc else None
                t = t or ([tr_line(part)] if tr_line and tr_line(part) else None)
                done += t is not None
                got += t or [part]
        out[nid] = got
    return out, (done, total)


def skill_names(catalog_data, lang):
    """Названия умений и предметов из игры на языке lang по английскому (каталог: камни, базы, names-<язык>) — для
    строки «узел даёт умение». Нет каталога — {}."""
    import gzip
    try:
        ver = (Path(catalog_data) / 'current.txt').read_text(encoding='utf-8').strip()
        base = Path(catalog_data) / ver
        layer = json.loads((base / ('lang-%s.json' % lang)).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    out = {}
    pack = base / ('names-%s.json.gz' % lang)
    if pack.is_file():
        out.update((json.loads(gzip.decompress(pack.read_bytes()).decode('utf-8')).get('names') or {}))
    for part in ('bases', 'gems'):
        out.update(layer.get(part) or {})
    return out


def catalog_langs(sources):
    """Языки, для которых в папке версии каталога лежит таблица статов: {язык: путь}; английская — отдельно
    (None, если её нет). Папку версии называет current.txt."""
    try:
        ver = (sources / 'current.txt').read_text(encoding='utf-8').strip()
    except OSError:
        return None, {}
    base = sources / ver
    en = base / 'en-stats.ndjson'
    found = {p.name[:-len('-stats.ndjson')]: p for p in sorted(base.glob('*-stats.ndjson'))}
    found.pop('en', None)
    return (en if en.is_file() else None), found


def main(argv):
    src = Path(argv[1]) if len(argv) > 1 else SOURCE
    dst = Path(argv[2]) if len(argv) > 2 else TARGET
    dst_stats = Path(argv[3]) if len(argv) > 3 else STATS
    sources = Path(argv[4]) if len(argv) > 4 else CATALOG_SOURCES
    with open(src, encoding='utf-8') as f:
        data = json.load(f)
    geo = build(data)
    with open(dst, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(geo, f, ensure_ascii=False, separators=(',', ':'))
    what = stats(data)
    with open(dst_stats, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(what, f, ensure_ascii=False, separators=(',', ':'))
    print('строки статов: у %d узлов, записано: %s, %d байт' % (len(what), dst_stats, dst_stats.stat().st_size))
    # на языках страниц: описания свойств игры, запасной путь — таблица Exiled Exchange 2 (если она есть у языка)
    en, langs = catalog_langs(sources)
    try:
        base = sources / (sources / 'current.txt').read_text(encoding='utf-8').strip()
    except OSError:
        base = None
    descs = read_descriptions(base) if base else []
    ui, granted = ui_descriptions(base) if base else ([], {})
    raw = raw_stats(data)
    for code in sorted(set(PAGE_LANGS) | set(langs)):
        tr_line = translator(stat_rows(en), stat_rows(langs[code])) if en is not None and code in langs else None
        tr_desc = desc_translator(ui + descs, code, granted, skill_names(sources.parent / 'data', code)) if descs else None
        if tr_desc is None and tr_line is None:
            continue
        out, (done, total) = page_stats(raw, tr_desc, tr_line)
        target = dst_stats.with_name('treestats.%s.json' % code)
        with open(target, 'w', encoding='utf-8', newline='\n') as f:
            json.dump(out, f, ensure_ascii=False, separators=(',', ':'))
        print('строки статов, %s: переведено %d из %d, записано: %s, %d байт'
              % (code, done, total, target, target.stat().st_size))
    kinds = [0] * 6
    for n in geo['nodes']:
        kinds[n[3]] += 1
    print('узлов: %d (малых %d, «Характеристика» %d, значимых %d, ключевых %d, гнёзд %d, стартов %d), связей: %d (дуг %d)'
          % (len(geo['nodes']), *kinds, len(geo['edges']), sum(1 for e in geo['edges'] if len(e) == 4)))
    print('зачарование: эмоций %d, узлов с рецептом %d, из них без места на дереве %d'
          % (len(geo['anoint']['emotions']), len(geo['anoint']['nodes']),
             sum(1 for r in geo['anoint']['nodes'].values() if len(r) > 2)))
    print('записано: %s, %d байт' % (dst, dst.stat().st_size))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
