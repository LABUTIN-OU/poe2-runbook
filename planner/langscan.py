# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Sergei Labutin
# Additional terms under GPL-3.0 section 7: see NOTICE.md
"""Поиск текстов в коде — для проверки слоя языка (test_lang.py) и для скриптов, которые оборачивают
тексты вызовом перевода.

Слой языка устроен так (planner/i18n.py): текст программы записан в коде по-русски и обёрнут вызовом
перевода — в Python это tr('…'), на страницах T('…'); перевод лежит в planner/lang/<язык>.json под ключом —
самим русским текстом. Чтобы ни один текст не остался без перевода, проверка должна видеть каждый
строковый литерал с кириллицей: он либо обёрнут (и тогда у него есть перевод), либо назван в списке
planner/lang/raw.json — «это не текст программы» (разбор лога и текста предмета по языку клиента).

Здесь два разборщика:
  py_literals(src)  — литералы с кириллицей в модуле Python (по дереву разбора ast);
  js_pieces(src)    — куски с кириллицей в коде страницы (свой разбор JS на лексемы: строки, шаблонные
                      строки со вставками ${…}, регулярные выражения, комментарии).
Кусок страницы — это текст между знаками разметки: строка '<b>Шаг</b> опаздывает' даёт куски «Шаг»
и «опаздывает»."""
import ast
import re

CYR = re.compile('[А-Яа-яЁё]')
# вызовы перевода: Python — tr(…), plural(n, …); страницы — T(…), TK(…), TN(n, …), plural(n, …, …, …)
PY_CALLS = ('tr', 'plural')
JS_CALLS = ('T', 'TK', 'TN', 'plural')


# --- Python ---------------------------------------------------------------------------------------

def py_literals(src):
    """Строковые литералы модуля с кириллицей: [{text, line, col, end_line, end_col, call, doc, fstr}].
    call — имя вызова перевода, аргументом которого литерал стоит (tr('…') -> 'tr'), иначе None;
    doc — это докстрока (в проверку не идёт); fstr — кусок f-строки (обернуть его нельзя).
    Место — как у ast: строка с 1, столбец в байтах UTF-8."""
    tree = ast.parse(src)
    docs, calls, fparts = set(), {}, set()
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            fparts.update(id(v) for v in node.values)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef)):
            body = getattr(node, 'body', [])
            if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], 'value', None), ast.Constant) \
                    and isinstance(body[0].value.value, str):
                docs.add(id(body[0].value))
        if isinstance(node, ast.Call) and node.args:
            name = node.func.id if isinstance(node.func, ast.Name) else (
                node.func.attr if isinstance(node.func, ast.Attribute) else None)
            if name not in PY_CALLS:
                continue
            # ключ — первый аргумент; у plural(n, 'шаг|шага|шагов') — второй
            arg = node.args[1] if name == 'plural' and len(node.args) > 1 else node.args[0]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                calls[id(arg)] = name
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and CYR.search(node.value):
            out.append({'text': node.value, 'line': node.lineno, 'col': node.col_offset,
                        'end_line': node.end_lineno, 'end_col': node.end_col_offset,
                        'call': calls.get(id(node)), 'doc': id(node) in docs, 'fstr': id(node) in fparts})
    out.sort(key=lambda x: (x['line'], x['col']))
    return out


# --- JavaScript -----------------------------------------------------------------------------------

# после этих лексем косая черта начинает регулярное выражение, а не деление
_RE_BEFORE = set('( , = : [ ! & | ? { } ; + - * % < > ~ ^'.split()) | {
    'return', 'typeof', 'case', 'do', 'else', 'in', 'of', 'void', 'delete', 'throw', 'new', 'yield', 'await'}
_IDENT = re.compile(r'[A-Za-z_$][\w$]*')
_NUM = re.compile(r'\d[\w.]*')
_BS = chr(92)   # обратная косая черта


def js_tokens(src, start=0, end=None, until_brace=False, templates=None):
    """Лексемы кода страницы: [(вид, начало, конец)] — вид: 'str' (строка в кавычках), 'tpl' (кусок
    шаблонной строки между её краями и вставками ${…}), 'com', 're', 'id', 'num', 'op'.
    until_brace — разбор вставки шаблонной строки: кончается на закрывающей скобке её уровня;
    тогда возвращается (лексемы, место за скобкой). templates — список, куда складываются шаблонные
    строки целиком: {'chunks': [(начало, конец)…], 'exprs': [(начало, конец)…]} — вставка exprs[i] стоит
    между кусками chunks[i] и chunks[i + 1]."""
    end = len(src) if end is None else end
    out, i, depth, prev = [], start, 0, None
    while i < end:
        c = src[i]
        if c in ' \t\r\n':
            i += 1
            continue
        if src.startswith('//', i):
            j = src.find('\n', i)
            j = end if j < 0 else j
            out.append(('com', i, j))
            i = j
            continue
        if src.startswith('/*', i):
            j = src.find('*/', i + 2)
            j = end if j < 0 else j + 2
            out.append(('com', i, j))
            i = j
            continue
        if c in '\'"':
            j = i + 1
            while j < end and src[j] != c:
                j += 2 if src[j] == _BS else 1
            out.append(('str', i, j + 1))
            i, prev = j + 1, 'str'
            continue
        if c == '`':
            i = _template(src, i, end, out, templates)
            prev = 'str'
            continue
        if c == '/' and (prev is None or prev in _RE_BEFORE):
            j, cls = i + 1, False
            while j < end and (src[j] != '/' or cls):
                if src[j] == _BS:
                    j += 1
                elif src[j] == '[':
                    cls = True
                elif src[j] == ']':
                    cls = False
                elif src[j] == '\n':
                    break
                j += 1
            j += 1
            m = _IDENT.match(src, j)
            j = m.end() if m else j
            out.append(('re', i, j))
            i, prev = j, 'str'
            continue
        m = _IDENT.match(src, i)
        if m:
            out.append(('id', i, m.end()))
            i, prev = m.end(), m.group()
            continue
        m = _NUM.match(src, i)
        if m:
            out.append(('num', i, m.end()))
            i, prev = m.end(), 'num'
            continue
        if until_brace:
            if c == '{':
                depth += 1
            elif c == '}':
                if depth == 0:
                    return out, i + 1
                depth -= 1
        out.append(('op', i, i + 1))
        # «)» и «]» кончают выражение: косая за ними — деление
        prev = 'num' if c in ')]' else c
        i += 1
    return (out, end) if until_brace else out


def _template(src, i, end, out, templates=None):
    """Шаблонная строка с места i (на открывающем `): её куски — лексемы 'tpl' (без краёв), вставки
    разбираются как код. Возвращает место за закрывающим `."""
    j = seg = i + 1
    rec = {'chunks': [], 'exprs': []}
    if templates is not None:
        templates.append(rec)
    while j < end:
        c = src[j]
        if c == _BS:
            j += 2
        elif c == '`':
            out.append(('tpl', seg, j))
            rec['chunks'].append((seg, j))
            return j + 1
        elif c == '$' and src.startswith('${', j):
            out.append(('tpl', seg, j))
            rec['chunks'].append((seg, j))
            inner, k = js_tokens(src, j + 2, end, until_brace=True, templates=templates)
            out.extend(inner)
            rec['exprs'].append((j + 2, k - 1))
            j = seg = k
        else:
            j += 1
    out.append(('tpl', seg, end))
    rec['chunks'].append((seg, end))
    return end


# текст между знаками разметки: всё, кроме < > и кавычки атрибута
_RUN = re.compile(r'[^<>"]+')


def runs(src, a, b, want=CYR):
    """Куски текста внутри отрезка [a, b) кода, в которых есть искомое (кириллица): [(начало, конец)]
    без пробелов по краям."""
    out = []
    for m in _RUN.finditer(src, a, b):
        text = m.group()
        if not want.search(text):
            continue
        lead = len(text) - len(text.lstrip())
        tail = len(text) - len(text.rstrip())
        out.append((m.start() + lead, m.end() - tail))
    return out


def _call_of(src, code, n):
    """Вызов перевода, аргументом которого стоит строка — лексема n: (имя, номер аргумента с 0) или None."""
    depth, arg = 0, 0
    for k in range(n - 1, max(-1, n - 60), -1):
        kind, a, b = code[k]
        if kind != 'op':
            continue
        t = src[a:b]
        if t in ')]}':
            depth += 1
        elif t in '([{':
            if depth == 0:
                if t == '(' and k and code[k - 1][0] == 'id' and src[code[k - 1][1]:code[k - 1][2]] in JS_CALLS:
                    return src[code[k - 1][1]:code[k - 1][2]], arg
                return None
            depth -= 1
        elif t == ',' and depth == 0:
            arg += 1
        elif t in ';?:=' and depth == 0:
            return None
    return None


def js_pieces(src, start=0, end=None):
    """Куски с кириллицей в коде страницы: [{text, start, end, kind, lit, call, key}].
      kind — 'str' (в строке в кавычках) или 'tpl' (в шаблонной строке);
      lit  — (начало, конец) всего литерала: у строки вместе с кавычками, у шаблонной — её кусок;
      call — вызов перевода, чьим ключом стоит вся строка: T('…'), TK('…') — первый аргумент, TN(n, '…') —
             второй, plural(n, '…', '…', '…') — со второго по четвёртый; иначе None;
      key  — строка стоит ключом объекта ({'ключ': …}): обернуть её вызовом нельзя."""
    toks = js_tokens(src, start, end)
    code = [t for t in toks if t[0] != 'com']
    out = []
    for n, (kind, a, b) in enumerate(code):
        if kind not in ('str', 'tpl'):
            continue
        body = (a + 1, b - 1) if kind == 'str' else (a, b)
        if not CYR.search(src[body[0]:body[1]]):
            continue
        call = key = None
        if kind == 'str':
            hit = _call_of(src, code, n)
            if hit and (hit[0] in ('T', 'TK') and hit[1] == 0 or hit[0] == 'TN' and hit[1] == 1
                        or hit[0] == 'plural' and 1 <= hit[1] <= 3):
                call = hit[0]
            before = src[code[n - 1][1]:code[n - 1][2]] if n else ''
            after = src[code[n + 1][1]:code[n + 1][2]] if n + 1 < len(code) else ''
            key = after == ':' and before in ('{', ',')
        for s, e in runs(src, body[0], body[1]):
            whole = kind == 'str' and (s, e) == body
            out.append({'text': src[s:e], 'start': s, 'end': e, 'kind': kind, 'lit': (a, b),
                        'call': call if whole else None, 'key': bool(key)})
    return out


def js_keys(src, start=0, end=None):
    """Ключи перевода, которыми пользуется код страницы: тексты из T('…'), TK('…'), TN(n, '…') и формы
    числа из plural(n, 'шаг', 'шага', 'шагов') одним ключом «шаг|шага|шагов»."""
    toks = js_tokens(src, start, end)
    code = [t for t in toks if t[0] != 'com']
    keys, forms = [], {}
    for n, (kind, a, b) in enumerate(code):
        if kind != 'str':
            continue
        hit = _call_of(src, code, n)
        if not hit:
            continue
        text = unquote(src[a:b])
        if hit[0] in ('T', 'TK') and hit[1] == 0 or hit[0] == 'TN' and hit[1] == 1:
            keys.append(text)
        elif hit[0] == 'plural' and 1 <= hit[1] <= 3:
            # три формы одного вызова стоят подряд: собираем их по месту открывающей скобки
            forms.setdefault(_open_of(src, code, n), []).append(text)
    keys += ['|'.join(v) for v in forms.values()]
    return keys


def _open_of(src, code, n):
    depth = 0
    for k in range(n - 1, -1, -1):
        if code[k][0] != 'op':
            continue
        t = src[code[k][1]:code[k][2]]
        if t in ')]}':
            depth += 1
        elif t in '([{':
            if depth == 0:
                return code[k][1]
            depth -= 1
    return -1


def unquote(lit):
    """Значение строки JS в кавычках (знаки с обратной косой — как их читает JS)."""
    body, out, i = lit[1:-1], [], 0
    simple = {'n': '\n', 't': '\t', 'r': '\r', '0': '\0'}
    while i < len(body):
        c = body[i]
        if c == _BS and i + 1 < len(body):
            d = body[i + 1]
            if d == 'u' and i + 5 < len(body) + 0 and re.fullmatch('[0-9a-fA-F]{4}', body[i + 2:i + 6] or ''):
                out.append(chr(int(body[i + 2:i + 6], 16)))
                i += 6
                continue
            out.append(simple.get(d, d))
            i += 2
            continue
        out.append(c)
        i += 1
    return ''.join(out)


def script_span(html):
    """Где в файле страницы её код: (начало, конец) содержимого <script>…</script>."""
    a = html.index('<script>') + len('<script>')
    return a, html.rindex('</script>')


def markup_texts(html):
    """Тексты с кириллицей в разметке страницы до её кода (вне <style> и комментариев):
    [{text, start, end}] — содержимое узлов и значения атрибутов."""
    head = html[:html.index('<script>')]
    out = []
    spans = [(m.start(), m.end()) for m in re.finditer(r'<style\b.*?</style>|<!--.*?-->', head, re.S)]
    for a, b in runs(head, 0, len(head)):
        if any(s <= a < e for s, e in spans):
            continue
        out.append({'text': head[a:b], 'start': a, 'end': b})
    return out
