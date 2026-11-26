# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Sergei Labutin
# Additional terms under GPL-3.0 section 7: see NOTICE.md
"""Русские названия, тексты и условия узлов дерева атласа — как их пишет клиент игры.

В выгрузке таблиц игры (catalog/sources/…/Atlas.min.json) у узла есть только английское название и
английский текст; условий, при которых узел берётся или действует («Требует активации большого
зеркала», «Действует на области 70+ уровня»), и вариантов выбора у узлов с выбором там нет вовсе.
Всё это есть в открытой базе poe2db: одна и та же страница со списком узлов атласа читается на двух
языках, узлы сопоставляются по адресу своей страницы. Сами страницы на диск не кладутся — сохраняется
только выжимка, catalog/extra/atlas-ru.json:

    names   {английское название: русское}
    nodes   {английское название: {when: [условия], text: [строки текста по порядку], count: сколько
            таких узлов в дереве, ids: {id узла: [условия]}}} — у узла с выбором после его собственных
            строк идут варианты
    trees   как клиент называет сами деревья («очки умений Бездны» -> «Бездна»): раздел ведётся руками
            и при обновлении не трогается

Про условия. Если название носит один узел (так у всех значимых узлов и узлов с выбором), его условия
в списке точные. Малый узел с одним названием стоит в дереве много раз, в разных его разделах, и условия
у этих узлов разные — список же показывает условия только одного из них (поле when у такого названия
поэтому ничего не говорит об остальных). Условия по каждому узлу отдельно есть на странице самого
названия; оттуда они и берутся в поле ids. Страница перечисляет не больше пяти узлов, так что часть
малых узлов остаётся без данных — и так и записана, без догадок.

Запуск: python -I catalog/fetch_atlas_names.py [куда записать]
"""
import json
import re
import sys
import time
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

PAGE = 'https://poe2db.tw/%s/Atlas_passive_skill'
NODE_PAGE = 'https://poe2db.tw/ru/%s'      # страница одного названия: адрес — как в списке
PAUSE = 0.4                                # секунд между страницами названий: их три десятка
TARGET = Path(__file__).resolve().parent / 'extra' / 'atlas-ru.json'
# Деревья атласа по id их корневого узла — словами клиента (подсказки к счётчикам очков на экране атласа).
TREES = {
    'AtlasGenericStart': 'Атлас',
    'AtlasAbyssStart': 'Бездна',
    'AtlasBreachStart': 'Разлом',
    'AtlasDeliriumStart': 'Делириум',
    'AtlasRitualStart': 'Ритуал',
    'AtlasIncursionStart_': 'Храм',
    'AtlasExpeditionStart': 'Экспедиция',
}
# Строки-условия в карточке узла: когда узел действует и что нужно, чтобы его взять. Остальные строки
# свойств карточки — служебные («SubTree: Breach», «Количество: 8», «Мастерство: …»).
RE_WHEN = re.compile(r'^(Действует|Требует)\b')
RE_COUNT = re.compile(r'^Количество:\s*(\d+)$')


def download(url):
    """Страница из сети. Запрос несёт только общее имя программы."""
    req = urllib.request.Request(url, headers={'User-Agent': 'generic-reader/1.0', 'Accept': 'text/html'})
    with urllib.request.urlopen(req, timeout=90) as r:
        return r.read().decode('utf-8', errors='replace')


class Cards(HTMLParser):
    """Карточки узлов со страницы: у каждой — адрес страницы узла, название, вид, строки свойств
    (условия и служебное) и строки текста. Карточка — блок <div class="col">; строки текста — блоки
    implicitMod и explicitMod, пункты списка и переносы внутри них — отдельные строки."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.cards = []
        self.cur = None      # карточка, внутри которой идёт разбор
        self.depth = 0       # вложенность <div> внутри карточки
        self.cap = None      # блок, текст которого собирается: {'to', 'until', 'parts'}
        self.name = None     # собираемое название (текст ссылки на страницу узла)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        words = (a.get('class') or '').split()
        if tag == 'div' and words == ['col']:
            self.cur = {'href': None, 'name': '', 'kind': None, 'props': [], 'text': []}
            self.cards.append(self.cur)
            self.depth, self.cap, self.name = 1, None, None
            return
        if self.cur is None:
            return
        if tag == 'div':
            self.depth += 1
        if self.cap is not None:
            if tag == 'li':
                self.cap['parts'].append('')
            elif tag == 'br':
                self.cap['parts'][-1] += '\n'
            return
        if tag == 'div':
            for w in words:
                if w.startswith('passive-icon-type__atlas_'):
                    self.cur['kind'] = w.rsplit('_', 1)[1]
            to = 'props' if 'property' in words else 'text' if ('implicitMod' in words or 'explicitMod' in words) else None
            if to:
                self.cap = {'to': to, 'until': self.depth, 'parts': ['']}
        elif tag == 'a' and 'PassiveSkills' in words:
            self.cur['href'] = a.get('href')
            self.name = ''

    def handle_endtag(self, tag):
        if self.cur is None:
            return
        if tag == 'a' and self.name is not None:
            self.cur['name'] = ' '.join(self.name.split())
            self.name = None
        if tag != 'div':
            return
        self.depth -= 1
        if self.cap is not None and self.depth < self.cap['until']:
            for part in self.cap['parts']:
                for line in part.split('\n'):
                    line = ' '.join(line.split())
                    if line:
                        self.cur[self.cap['to']].append(line)
            self.cap = None
        if self.depth <= 0:
            self.cur = None

    def handle_data(self, data):
        if self.cap is not None:
            self.cap['parts'][-1] += data
        elif self.name is not None:
            self.name += data


def cards(page):
    """Карточки узлов со страницы по порядку (только те, у которых есть название и адрес)."""
    parser = Cards()
    parser.feed(page)
    parser.close()
    return [c for c in parser.cards if c['href'] and c['name']]


class Variants(HTMLParser):
    """Страница одного названия: под ним может стоять несколько узлов дерева (малый узел повторяется
    в разных разделах), и у каждого свои условия. Узлы идут блоками: строки свойств, затем таблица
    со строкой «ID». Собирает [(id узла, [строки свойств блока])]."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.found = []
        self.props = []      # строки свойств текущего блока
        self.depth = None    # вложенность <div> внутри собираемой строки свойств
        self.text = ''
        self.cell = None     # текст собираемой ячейки таблицы
        self.want_id = False

    def handle_starttag(self, tag, attrs):
        if self.depth is not None:
            if tag == 'div':
                self.depth += 1
            return
        if tag == 'div' and 'property' in (dict(attrs).get('class') or '').split():
            self.depth, self.text = 1, ''
        elif tag in ('td', 'th'):
            self.cell = ''

    def handle_endtag(self, tag):
        if self.depth is not None:
            if tag == 'div':
                self.depth -= 1
                if self.depth == 0:
                    line = ' '.join(self.text.split())
                    if line:
                        self.props.append(line)
                    self.depth = None
            return
        if tag in ('td', 'th') and self.cell is not None:
            cell = ' '.join(self.cell.split())
            if self.want_id and cell:
                self.found.append((cell, self.props))
                self.props, self.want_id = [], False
            elif cell == 'ID':
                self.want_id = True
            self.cell = None

    def handle_data(self, data):
        if self.depth is not None:
            self.text += data
        elif self.cell is not None:
            self.cell += data


def variants(page):
    """Узлы со страницы одного названия: {id: [условия]} — только те, что страница перечисляет."""
    parser = Variants()
    parser.feed(page)
    parser.close()
    return {i: [p for p in props if RE_WHEN.match(p)] for i, props in parser.found}


def pair(en_page, ru_page):
    """Две языковые версии одной страницы -> (названия {английское: русское}, узлы {английское название:
    {when, text, count}}, адреса страниц названий {английское название: адрес}). Узлы сопоставляются
    по адресу своей страницы."""
    en, ru = cards(en_page), cards(ru_page)
    if not en or len(en) != len(ru) or [c['href'] for c in en] != [c['href'] for c in ru]:
        raise ValueError('страницы разошлись: узлов %d и %d' % (len(en), len(ru)))
    names, nodes, hrefs, clash = {}, {}, {}, []
    for e, r in zip(en, ru):
        if e['name'] in names:
            clash.append(e['name'])
        names[e['name']] = r['name']
        hrefs[e['name']] = e['href']
        count = next((int(m.group(1)) for m in map(RE_COUNT.match, r['props']) if m), 1)
        nodes[e['name']] = {'when': [p for p in r['props'] if RE_WHEN.match(p)], 'text': r['text'], 'count': count}
    if clash:
        raise ValueError('одно английское имя у нескольких узлов: %s' % ', '.join(clash[:5]))
    return names, nodes, hrefs


def main(argv):
    target = Path(argv[1]) if len(argv) > 1 else TARGET
    names, nodes, hrefs = pair(download(PAGE % 'us'), download(PAGE % 'ru'))
    # Название, под которым в дереве несколько узлов: условия каждого — со страницы самого названия.
    many = [name for name, node in nodes.items() if node['count'] > 1]
    for name in many:
        if not re.fullmatch(r'[\w%.\-~]+', hrefs[name]):
            raise ValueError('странный адрес страницы узла: %r' % hrefs[name][:60])
        nodes[name]['ids'] = variants(download(NODE_PAGE % hrefs[name]))
        time.sleep(PAUSE)
    old = {}
    if target.is_file():
        old = json.loads(target.read_text(encoding='utf-8'))
    data = {'source': PAGE % 'ru', 'fetched': time.strftime('%Y-%m-%d %H:%M'),
            'trees': old.get('trees') or TREES, 'names': dict(sorted(names.items())),
            'nodes': dict(sorted(nodes.items()))}
    target.write_text(json.dumps(data, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print('названий: %d (без перевода %d) | строк текста: %d | условия: точные у %d названий, по узлам у %d из %d узлов '
          'с повторяющимся названием | записано: %s, %d байт' % (
              len(names), sum(1 for a, b in names.items() if a == b), sum(len(n['text']) for n in nodes.values()),
              sum(1 for n in nodes.values() if n['count'] == 1), sum(len(nodes[n].get('ids') or {}) for n in many),
              sum(nodes[n]['count'] for n in many), target, target.stat().st_size))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
