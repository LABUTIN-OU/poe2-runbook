# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Sergei Labutin
# Additional terms under GPL-3.0 section 7: see NOTICE.md
"""Слой языка: тексты программы на языке пользователя.

Как это устроено.
  * Текст программы записан в коде по-русски (SOURCE) и обёрнут вызовом tr('…'). Вызов возвращает Text —
    обычную строку с русским текстом, которая помнит свой шаблон и то, что в него подставили. Весь расчёт
    идёт как раньше, с русскими строками: сравнения, ключи словарей, записи в файлы не меняются.
  * Язык появляется только на выходе: сервер отдаёт странице состояние через render(данные, язык). Для
    русского это те же данные без единой перемены; для другого языка каждый Text собирается заново по
    шаблону из файла перевода planner/lang/<язык>.json (ключ — русский текст из кода).
  * Языком управляет запрос страницы (параметр lang): сервер о языке ничего не помнит, поэтому две вкладки
    на разных языках друг другу не мешают.
  * Новый язык — новый файл planner/lang/<код>.json; кода править не нужно (test_lang.py проверит, что
    в файле есть все ключи).

Что переводится, а что нет.
  * Текст программы — переводится (Text).
  * Название из игры — по правилу языка: по-русски «Гремящий скипетр (Rattling Sceptre)», по-английски
    «Rattling Sceptre», на другом языке игры — названием из её данных на этом языке и английским в скобках:
    «Rasselndes Zepter (Rattling Sceptre)» (Names: пара из плана показывается по своей английской части).
  * Слово, которое в файл плана записала сама программа («любой», «от 120», название слота), — переводится
    по точному совпадению (Names).
  * Текст автора плана (заметка, своё название) — показывается как записан.
  * Текст клиента игры (строки лога, текст скопированного предмета) разбирается по языку клиента и к языку
    страницы отношения не имеет: здесь его нет.

В коде:
    from i18n import tr           tr('с шага «%s»') % name       tr('Шаг {0} из {1}').format(a, b)
    i18n.plural(n, 'шаг|шага|шагов')                              i18n.join(', ', названия)
Один и тот же русский текст с разным переводом различают пометкой после «##»: tr('цель##время') по-русски
даёт «цель», а ключ перевода у него свой. (Имя tr, а не привычное _: в модулях _ — переменная «не нужно».)
"""
import json
import re
from pathlib import Path

SOURCE = 'ru'      # на этом языке тексты записаны в коде
DEFAULT = 'en'     # язык страницы, пока пользователь не выбрал свой
LANG_DIR = Path(__file__).resolve().parent / 'lang'
CYR = re.compile('[А-Яа-яЁё]')
CTX = '##'         # за этим знаком в ключе — пометка, а не текст
_SPEC = re.compile(r'%(?:\(\w+\))?[-+ #0]*\d*(?:\.\d+)?[sdirfx%]')     # подстановка вида %s, %d
_FIELD = re.compile(r'\{(\w*)\}')                                        # место вида {0}


def bare(key):
    """Ключ без пометки: «цель##время» -> «цель»."""
    return key.split(CTX, 1)[0] if CTX in key else key


class Raw(str):
    """Строка, которую не переводят: название, которое дал не план и не программа, а человек на сайте игры
    (название фильтра). Совпади оно со словом программы («Карты»), оно всё равно осталось бы как есть."""
    __slots__ = ()


class Text(str):
    """Текст программы: строка с русским текстом, которая помнит, как она собрана.
      kind 'msg'    — сам текст по ключу key;
      kind 'mod'    — key % args[0];        kind 'fmt' — key.format(*args[0], **args[1]);
      kind 'plural' — форма числа args (ключ «шаг|шага|шагов»);
      kind 'cat'    — склейка частей args (тексты программы и обычные строки);
      kind 'rmod'   — обычный шаблон args[0], в который подставлен текст программы args[1].
    Действие, которого Text не знает (срез, lower, f-строка), возвращает обычную русскую строку."""
    __slots__ = ('key', 'args', 'kind')

    def __new__(cls, value, key=None, args=None, kind='msg'):
        self = str.__new__(cls, value)
        self.key, self.args, self.kind = key, args, kind
        return self

    def __mod__(self, args):
        value = str.__mod__(self, args)
        if self.kind == 'msg':
            return Text(value, self.key, (args,), 'mod')
        return value

    def __rmod__(self, fmt):
        value = str.__mod__(fmt, str.__str__(self))
        return Text(value, None, (fmt, self), 'rmod') if isinstance(fmt, str) else value

    def format(self, *args, **kwargs):
        value = str.format(self, *args, **kwargs)
        if self.kind == 'msg':
            return Text(value, self.key, (args, kwargs), 'fmt')
        return value

    def __add__(self, other):
        if not isinstance(other, str):
            return NotImplemented
        return Text(str.__add__(self, other), None, _parts(self) + _parts(other), 'cat')

    def __radd__(self, other):
        if not isinstance(other, str):
            return NotImplemented
        return Text(str.__add__(other, self), None, _parts(other) + _parts(self), 'cat')

    def __reduce__(self):
        return (Text, (str.__str__(self), self.key, self.args, self.kind))


def _parts(x):
    return x.args if isinstance(x, Text) and x.kind == 'cat' else (x,)


def tr(key):
    """Текст программы по его русскому ключу."""
    return Text(bare(key), key, None, 'msg')


def join(sep, items):
    """sep.join(items), который не теряет тексты программы и названия: каждая часть переводится сама."""
    items = [x if isinstance(x, str) else str(x) for x in items]
    parts = []
    for n, x in enumerate(items):
        if n:
            parts.append(sep)
        parts.extend(_parts(x))
    return Text(str.__str__(sep).join(items), None, tuple(parts), 'cat')


# --- число: какая форма слова у числа n ------------------------------------------------------------
# Правило называет файл языка (поле plural); формы в ключе и в переводе идут в порядке правила.

def _slavic(n):       # 1 шаг · 2 шага · 5 шагов
    a, b = abs(n) % 100, abs(n) % 10
    return 2 if 10 < a < 20 else 0 if b == 1 else 1 if 2 <= b <= 4 else 2


def _polish(n):
    a, b = abs(n) % 100, abs(n) % 10
    return 0 if abs(n) == 1 else 1 if 2 <= b <= 4 and not 12 <= a <= 14 else 2


def _czech(n):
    return 0 if abs(n) == 1 else 1 if 2 <= abs(n) <= 4 else 2


PLURALS = {
    'slavic': (3, _slavic),                                    # русский, украинский, белорусский
    'one_other': (2, lambda n: 0 if abs(n) == 1 else 1),       # английский, немецкий, испанский…
    'french': (2, lambda n: 0 if abs(n) <= 1 else 1),          # французский, бразильский португальский
    'polish': (3, _polish),
    'czech': (3, _czech),                                      # чешский, словацкий
    'none': (1, lambda n: 0),                                  # китайский, японский, корейский…
}


def plural(n, key):
    """Форма слова для числа n: plural(3, 'шаг|шага|шагов') -> «шага». Само число в текст не входит."""
    forms = bare(key).split('|')
    return Text(forms[min(_slavic(n), len(forms) - 1)], key, n, 'plural')


# --- файлы перевода --------------------------------------------------------------------------------

_tables = {}


def table(lang):
    """Перевод языка lang: {lang, name, plural, quotes, locale, texts, plan, patterns}. Файл перечитывается, когда
    меняется (планировщик работает часами, перевод могут поправить на ходу). Нет файла — None."""
    path = LANG_DIR / ('%s.json' % lang)
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    hit = _tables.get(lang)
    if hit and hit[0] == mtime:
        return hit[1]
    try:
        data = json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return hit[1] if hit else None
    if not isinstance(data, dict):
        return hit[1] if hit else None
    data.setdefault('texts', {})
    data.setdefault('plan', {})
    data['_patterns'] = [(re.compile(p), t) for p, t in data.get('patterns') or [] if isinstance(p, str)]
    _tables[lang] = (mtime, data)
    return data


def languages():
    """Языки, у которых есть файл перевода: [{code, name}] — язык по умолчанию первым, за ним язык кода,
    дальше по алфавиту."""
    found = []
    for path in sorted(LANG_DIR.glob('*.json')):
        code = path.stem
        if code == 'raw' or not re.fullmatch(r'[a-z]{2,3}(-[A-Za-z]{2,4})?', code):
            continue
        tab = table(code)
        if tab:
            found.append({'code': code, 'name': tab.get('name') or code})
    order = {DEFAULT: 0, SOURCE: 1}
    return sorted(found, key=lambda x: (order.get(x['code'], 2), x['code']))


def pick(code):
    """Язык запроса: названный, если его файл есть; иначе язык по умолчанию."""
    if code == SOURCE:
        return SOURCE
    if isinstance(code, str) and re.fullmatch(r'[a-z]{2,3}(-[A-Za-z]{2,4})?', code) and table(code):
        return code
    return DEFAULT if table(DEFAULT) else SOURCE


def _words(lang):
    """Тексты кода и слова из файлов плана языка lang одним словарём; чего в его файле нет (текст добавили в код,
    а перевод на этот язык ещё не сделан), — по-английски: язык по умолчанию понятнее русского."""
    tab = table(lang) or {}
    own = dict(tab.get('plan') or {}, **(tab.get('texts') or {}))
    if lang in (SOURCE, DEFAULT):
        return own
    base = table(DEFAULT) or {}
    out = dict(base.get('plan') or {})
    out.update(base.get('texts') or {})
    out.update(own)
    return out


def page(lang):
    """Что нужно странице, чтобы говорить на языке lang: его тексты и список языков для переключателя."""
    tab = table(lang) or {}
    return {'lang': lang, 'source': SOURCE, 'default': DEFAULT, 'name': tab.get('name') or lang,
            'plural': tab.get('plural') or 'slavic', 'quotes': tab.get('quotes') or '',
            'locale': tab.get('locale') or lang,
            # тексты кода и слова из файлов плана — одним словарём: странице они нужны вместе
            'texts': {} if lang == SOURCE else _words(lang),
            'patterns': [] if lang == SOURCE else tab.get('patterns') or [], 'langs': languages()}


# --- текст на языке --------------------------------------------------------------------------------

def to(x, lang, names=None):
    """Текст программы x на языке lang. Обычная строка — название из плана: показывается по правилу языка
    (names — Names этого языка), без names остаётся как есть."""
    if lang == SOURCE or not isinstance(x, str):
        return x
    if isinstance(x, Raw):
        return str.__str__(x)
    if not isinstance(x, Text):
        return names.of(x) if names is not None else x
    tab = table(lang) or {}
    texts = tab.get('texts') or {}
    kind = x.kind
    if kind == 'cat':
        return ''.join(to(p, lang, names) for p in x.args)
    if kind == 'rmod':
        return x.args[0] % to(x.args[1], lang, names)
    tmpl = texts.get(x.key)
    if tmpl is None and lang != DEFAULT:
        # на этот язык текст ещё не переведён — по-английски, по правилу числа английского
        tab = table(DEFAULT) or {}
        tmpl = (tab.get('texts') or {}).get(x.key)
    if tmpl is None:
        return str.__str__(x)                     # перевода нет: текст как в коде
    if kind == 'msg':
        return tmpl
    if kind == 'plural':
        forms = tmpl.split('|')
        rule = PLURALS.get(tab.get('plural') or '', PLURALS['one_other'])[1]
        return forms[min(rule(x.args), len(forms) - 1)]
    try:
        if kind == 'mod':
            args = x.args[0]
            if isinstance(args, tuple):
                args = tuple(to(a, lang, names) for a in args)
            elif isinstance(args, dict):
                args = {k: to(v, lang, names) for k, v in args.items()}
            else:
                args = to(args, lang, names)
            return tmpl % args
        if kind == 'fmt':
            return tmpl.format(*[to(a, lang, names) for a in x.args[0]],
                               **{k: to(v, lang, names) for k, v in x.args[1].items()})
    except (TypeError, ValueError, KeyError, IndexError):
        pass
    return str.__str__(x)                         # перевод не подошёл к подстановке: текст как в коде


# Поля состояния, значения которых не показывают как названия: ключи и коды (их сравнивает код страницы)
# и тексты автора (заметки) — они идут как записаны.
KEEP = frozenset(('id', 'code', 'attr', 'path', 'key', 'icon', 'slot', 'row', 'node', 'hash', 'stat', 'part',
                  'note', 'notes', 'error'))


def render(obj, lang, names=None, plain=False):
    """Данные для страницы на языке lang: каждый Text — на этом языке. plain — показывать по правилу языка
    и обычные строки (названия из плана): так отдаётся состояние страницы забега, где всё только читают;
    редактору плана записи плана отдаются как есть (он их правит и присылает обратно).
    Для языка кода данные возвращаются без перемен."""
    if lang == SOURCE:
        return obj

    def walk(x, key=None):
        if isinstance(x, Text):
            return to(x, lang, names)
        if isinstance(x, Raw):
            return str.__str__(x)
        if isinstance(x, str):
            return names.of(x) if plain and names is not None and key not in KEEP else x
        if isinstance(x, dict):
            return {k: walk(v, k) for k, v in x.items()}
        if isinstance(x, (list, tuple)):
            return [walk(v, key) for v in x]
        return x

    return walk(obj)


# --- названия из плана и из игры --------------------------------------------------------------------

# «Русское (English)»: в скобках латиница без кириллицы. Перед парой — начало строки или один из разделителей.
_PAIR = re.compile(r' \(([^()]*)\)')
_LATIN = re.compile('[A-Za-z]')
_EDGE = re.compile(r': | → | · | — |(?<=\)), |; ')
_SPLIT = re.compile(r'(: | → | · | — )')
_DIGITS = re.compile(r'\d+')
_TAIL = re.compile(r'(.+?) \(([^()]+)\)')              # «Оружие (скипетры)»: слово и уточнение в скобках
_QUOTED = re.compile('([«“])([^«»“”]+)([»”])')         # название в кавычках внутри текста


class _Shape:
    """Шаблон вида «с шага «%s»» как выражение для узнавания готового текста."""
    __slots__ = ('rx', 'kinds')

    def __init__(self, rx, kinds):
        self.rx, self.kinds = rx, kinds

    def fullmatch(self, s):
        return self.rx.fullmatch(s)


def _reverse(key):
    """Выражение, которое узнаёт текст, собранный по ключу с подстановками %s и %d; None — подстановки
    сложнее (точность, имена): такой ключ узнаётся только по своему Text."""
    out, kinds, pos = [], [], 0
    text = bare(key)
    for m in _SPEC.finditer(text):
        out.append(re.escape(text[pos:m.start()]))
        spec = m.group()
        if spec == '%%':
            out.append('%')
        elif spec == '%d':
            out.append(r'(-?\d+)')
            kinds.append('d')
        elif spec == '%s':
            out.append('(.+?)')
            kinds.append('s')
        else:
            return None
        pos = m.end()
    out.append(re.escape(text[pos:]))
    return _Shape(re.compile(''.join(out), re.S), tuple(kinds)) if kinds else None


def _head(key):
    """Первые два знака ключа, если он начинается с текста, а не с подстановки: по ним шаблоны разложены
    по полкам, чтобы не примерять каждый к каждой строке."""
    text = bare(key)
    return '' if text[:1] == '%' or text[1:2] == '%' else text[:2]


def game_name(local, english, lang):
    """Название из игры на языке lang: «Местное (English)», а по-английски и там, где местного названия нет
    или оно то же, — только «English»."""
    if lang == 'en' or not local or local == english:
        return english
    return '%s (%s)' % (local, english)


class Names:
    """Как показать на языке lang название, записанное в плане по-русски.
      * слово программы, попавшее в план («любой», «Оружие», «уровень камня»), — по точному совпадению
        с ключом перевода;
      * название из игры, записанное парой «Русское (English)», — по-английски своей английской частью, на
        другом языке игры — «Местное (English)», если данные игры знают его на этом языке (иначе английским);
      * русское название из данных игры без пары (класс героя из лога, база надетого предмета, зона) —
        так же без пары: названием на языке страницы из каталога, а нет его — английским;
      * составная строка («уровень камня: 3 → Инфекция (Contagion)») — по частям.
    Чего в данных нет, остаётся как записано. cat — каталог данных игры, zones — {код зоны: её название
    в логе игры}, pack — названия из игры на языке lang по английскому названию (gamedata.names_pack)."""

    def __init__(self, lang, cat=None, zones=None, pack=None):
        self.lang = lang
        tab = table(lang) or {}
        # слова программы: тексты кода и слова из файлов плана (раздел plan файла языка)
        self.texts = _words(lang)
        self.patterns = tab.get('_patterns') or []
        self.exact = {}
        self.cache = {}
        packs = (cat or {}).get('lang') or {}
        src, own = packs.get(SOURCE) or {}, packs.get(lang) or {}
        # Название из игры на этом языке по английскому названию: слой языка каталога (базы, камни, классы героя)
        # и таблицы игры (pack: монстры, NPC, задания, предметы, зоны…). По-английски его нет: там название — само.
        self.local = {}
        if lang != 'en':
            for part in ('bases', 'gems', 'heroClasses'):
                for en, loc in (own.get(part) or {}).items():
                    if isinstance(loc, str) and loc and loc != en:
                        self.local.setdefault(en, loc)
            for en, loc in ((pack or {}).get('names') or {}).items():
                self.local.setdefault(en, loc)
        for part in ('bases', 'gems', 'heroClasses'):
            for en, ru in (src.get(part) or {}).items():
                if isinstance(ru, str) and ru != en:
                    self.exact.setdefault(ru, self.local.get(en) or en)
        # Классы предметов: слово клиента («Сапоги») и название из таблицы классов игры («Обувь») -> по-английски
        # класс игры, на другом языке — слово клиента этого языка («Stiefel»).
        words = {}
        for word, cid in (own.get('classes') or {}).items():
            words.setdefault(cid, word)
        for cid, word in (own.get('classNames') or {}).items():
            words.setdefault(cid, word)
        cls = (lambda cid: cid) if lang == 'en' else (lambda cid: words.get(cid) or cid)
        for word, cid in (src.get('classes') or {}).items():
            self.exact.setdefault(word, cls(cid))
        for cid, word in (src.get('classNames') or {}).items():
            self.exact.setdefault(word, cls(cid))
        for sid, pair in (src.get('statNames') or {}).items():
            there = (own.get('statNames') or {}).get(sid)
            for n, word in enumerate(pair if isinstance(pair, list) else ()):
                if there and n < len(there) and isinstance(word, str):
                    self.exact.setdefault(word, there[n])
        # зоны: название из лога игры (или из слоя языка каталога) -> название зоны в данных игры
        areas = (cat or {}).get('areas') or {}
        known = dict(src.get('areas') or {})
        known.update(zones or {})
        there = own.get('areas') or {}
        for code, word in known.items():
            en = (areas.get(code) or {}).get('name') if isinstance(areas.get(code), dict) else None
            if isinstance(word, str) and en and word != en:
                self.exact.setdefault(word, (there.get(code) if lang != 'en' else None) or en)
        # Текст программы, который дошёл сюда уже обычной строкой (его вставили в другой текст, склеили
        # через join, прочли из файла забега): узнаётся по своему шаблону — «зона 12» по ключу «зона %d».
        self.shapes = {}
        for key, text in self.texts.items():
            if '%' not in key or len(CYR.findall(key)) < 3:
                continue
            rx = _reverse(key)
            if rx is not None:
                self.shapes.setdefault(_head(key), []).append((rx, text))

    def _lookup(self, en):
        """Название из игры на языке страницы по английскому; составное («Spectre: Powered Zealot») — по частям,
        если игра знает каждую. Нет на этом языке (или оно то же) — None."""
        if not self.local:
            return None
        hit = self.local.get(en)
        if hit is None and ': ' in en:
            parts = [self.local.get(p) for p in en.split(': ')]
            hit = ': '.join(parts) if all(parts) else None
        return hit if hit and hit != en else None

    def game(self, en):
        """Название из игры, записанное в плане парой, на языке страницы: по-английски — английское, на другом
        языке — «Местное (English)», если игра называет его иначе, а нет — английское."""
        loc = self._lookup(en)
        return '%s (%s)' % (loc, en) if loc else en

    def game_names(self, data):
        """Названия из игры, записанные парами «Русское (English)» где-нибудь в data: {English: на языке страницы}
        — для страницы, которая показывает пары сама (редактор плана). Только те, что игра называет иначе."""
        found = {}

        def walk(x):
            if isinstance(x, str):
                if '(' in x:
                    for m in _PAIR.finditer(x):
                        en = m.group(1)
                        if en not in found and _LATIN.search(en) and not CYR.search(en):
                            found[en] = self._lookup(en)
            elif isinstance(x, dict):
                for v in x.values():
                    walk(v)
            elif isinstance(x, (list, tuple)):
                for v in x:
                    walk(v)

        if self.local:
            walk(data)
        return {en: loc for en, loc in found.items() if loc}

    def of(self, s):
        hit = self.cache.get(s)
        if hit is None:
            if len(self.cache) > 50000:      # программа работает часами: память показанных строк не копится
                self.cache.clear()
            hit = self.cache[s] = self._show(s) if CYR.search(s) else s
        return hit

    def _word(self, s):
        """Точное совпадение: слово программы или название из данных игры; заодно с другой буквой в начале
        («оружие» по ключу «Оружие»)."""
        for table_ in (self.texts, self.exact):
            if s in table_:
                return table_[s]
        if len(s) > 1 and s[0].isalpha():
            other = s[0].swapcase() + s[1:]
            for table_ in (self.texts, self.exact):
                hit = table_.get(other)
                if hit:
                    return (hit[0].lower() if s[0].islower() else hit[0].upper()) + hit[1:]
        hit = self._shaped(s)
        if hit is None and len(s) > 1 and s[0].islower() and s[0].isalpha():
            # «кольцо 1» — название слота «Кольцо 1» со строчной буквы
            hit = self._shaped(s[0].upper() + s[1:])
            hit = hit and hit[0].lower() + hit[1:]
        return hit

    def _shaped(self, s):
        """Текст по образцу: образцы файла языка («от 120» -> «from 120») и шаблоны ключей («зона 12» по
        ключу «зона %d»)."""
        for rx, tmpl in self.patterns:
            m = rx.fullmatch(s)
            if m:
                try:
                    return tmpl.format(*[self.of(g) if g else '' for g in m.groups()])
                except (IndexError, KeyError, ValueError):
                    continue
        for rx, tmpl in (self.shapes.get(s[:2]) or []) + (self.shapes.get('') or []):
            m = rx.fullmatch(s)
            if m:
                try:
                    return tmpl % tuple(int(g) if kind == 'd' else self.of(g) for g, kind in zip(m.groups(), rx.kinds))
                except (TypeError, ValueError):
                    continue
        return None

    def _pairs(self, s):
        """Пары «Русское (English)» внутри строки -> «English» (на другом языке игры — «Местное (English)»: game)."""
        out, end = [], len(s)
        for m in reversed(list(_PAIR.finditer(s))):
            en = m.group(1)
            if not _LATIN.search(en) or CYR.search(en):
                continue
            # начало русской части — за ближайшим разделителем; разделитель, который есть и в английской
            # части («Призрак: Заряженный подвижник (Spectre: Powered Zealot)»), — часть самого названия
            edges = [(e.group(), e.end()) for e in _EDGE.finditer(s, 0, m.start())]
            inside = [e.group() for e in _EDGE.finditer(en)]
            while edges and edges[-1][0] in inside:
                inside.remove(edges.pop()[0])
            start = edges[-1][1] if edges else 0
            ru = s[start:m.start()]
            if not CYR.search(ru) or ru != ru.strip():
                continue
            # число в русской части, которого нет в английской, — это не перевод, а уточнение автора
            if any(d not in _DIGITS.findall(en) for d in _DIGITS.findall(ru)):
                continue
            out.append(s[m.end():end])
            out.append(self.game(en))
            end = start
        out.append(s[:end])
        return ''.join(reversed(out))

    def _part(self, s, whole=False):
        """Часть составной строки на языке страницы: слово программы или название; «Оружие (скипетры)» —
        слово и уточнение в скобках порознь; перечень через запятую — по словам. None — перевести нечем.
        whole — это вся строка целиком: точное совпадение для неё уже проверено."""
        hit = None if whole else self._word(s)
        if hit is None:
            m = _TAIL.fullmatch(s)
            if m and CYR.search(m.group(2)):
                head, inner = self._part(m.group(1)), self._part(m.group(2))
                if head is not None or inner is not None:
                    hit = '%s (%s)' % (m.group(1) if head is None else head, m.group(2) if inner is None else inner)
        if hit is None and ', ' in s:
            # перечень через запятую («Оружие, Шлем»): каждое слово само
            items = s.split(', ')
            found = [self._word(x.strip()) if CYR.search(x) else None for x in items]
            if any(f is not None for f in found):
                hit = ', '.join(x if f is None else f for f, x in zip(found, items))
        return hit

    def _quoted(self, m):
        """Название в кавычках внутри текста: «к шагу «Клирфелл»»."""
        inner = m.group(2)
        hit = self._word(inner) if CYR.search(inner) else None
        return m.group(1) + (self._pairs(inner) if hit is None else hit) + m.group(3)

    def _show(self, s):
        text, lead, tail = s.strip(), s[:len(s) - len(s.lstrip())], s[len(s.rstrip()):]
        hit = self._word(text)
        if hit is not None:
            return lead + hit + tail
        parts = _SPLIT.split(self._pairs(text))
        for n in range(0, len(parts), 2):
            if CYR.search(parts[n]):
                hit = self._part(parts[n].strip(), whole=len(parts) == 1)
                if hit is not None:
                    parts[n] = parts[n].replace(parts[n].strip(), hit, 1)
        text = ''.join(parts)
        if CYR.search(text):
            text = _QUOTED.sub(self._quoted, text)
        return lead + text + tail


# --- консоль ---------------------------------------------------------------------------------------

CONSOLE = [SOURCE]     # язык сообщений в окне программы (server.py --lang)


def say(*parts, **kwargs):
    """print() для окна программы: тексты программы — на языке окна."""
    kwargs.setdefault('flush', True)
    print(*[to(p, CONSOLE[0]) if isinstance(p, Text) else p for p in parts], **kwargs)


# --- проверка перевода (для test_lang.py) -----------------------------------------------------------



def shape(text):
    """Что в текст подставляется: (подстановки вида %s по порядку, места вида {0} набором). У перевода
    должно быть то же самое — иначе подстановка упадёт или перепутает значения."""
    specs = [m[-1] for m in _SPEC.findall(text) if m != '%%']
    return specs, sorted(set(_FIELD.findall(text)))
