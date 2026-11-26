# -*- coding: utf-8 -*-
"""Behaviour checks of the site in a hidden Chrome: the pages are what the sources build; language rules on every
page; the shared header and footer; «Скачать» in every state on every page; the main page's budget, first screen,
pictures and questions; the list on the page of what the program reads; ready plans; the settings of config.js; pages
without JavaScript; the 404 page; opening from disk; links. The overlay folder of serve.py supplies
update/latest.json, plans/index.json and another assets/config.js for a case; site/ itself is never written.

    python -X utf8 site_checks.py <base url> <overlay dir> <site dir> <shots dir> <chrome profile> [debug port]"""
import json
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import quote, urljoin, urlsplit

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from cdp import Chrome  # noqa: E402

base, overlay, site, shots, profile = (sys.argv[1].rstrip('/'), Path(sys.argv[2]), Path(sys.argv[3]).resolve(), Path(sys.argv[4]),
                                       sys.argv[5])
port = int(sys.argv[6]) if len(sys.argv) > 6 else 4759
project = site.parent
host = urlsplit(base).netloc
GOOD = json.loads((site / 'update' / 'latest.example.json').read_text(encoding='utf-8'))
PLANS = json.loads((site / 'plans' / 'index.example.json').read_text(encoding='utf-8'))
PAGES = {'overview': '', 'safety': 'safety/', 'install': 'install/', 'about': 'about/'}
FOOT = {'en': ['Install', 'What Runbook reads', 'Source code', 'Licence', 'Contact'],
        'ru': ['Установка', 'Что программа читает', 'Исходный код', 'Лицензия', 'Связь']}
GGG = "This product isn't affiliated with or endorsed by Grinding Gear Games in any way."
# the languages that are on the site (their first page exists), in the program's order, by their own names
ON_SITE = []
for _file in sorted((project / 'planner' / 'lang').glob('*.json')):
    if _file.stem != 'raw' and (site / ('' if _file.stem == 'en' else _file.stem) / 'index.html').is_file():
        ON_SITE.append((_file.stem, json.loads(_file.read_text(encoding='utf-8'))['name']))
ON_SITE.sort(key=lambda x: ({'en': 0, 'ru': 1}.get(x[0], 2), x[0]))
results = []


def check(name, ok, detail=''):
    results.append((name, bool(ok)))
    print('%s  %s%s' % ('ok  ' if ok else 'FAIL', name, ('  — ' + str(detail)) if detail and not ok else ''))


def put(rel, text):
    path = overlay / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')


def clear():
    if overlay.exists():
        shutil.rmtree(overlay)
    overlay.mkdir(parents=True)


def url(page, lang, ask=False):
    """The page's address; ask=True — the English one with «?lang=en», the link that asks for English by name.
    The checks open English pages in an English browser by their plain address, as a visitor does."""
    return '/' + ('ru/' if lang == 'ru' else '') + PAGES[page] + ('?lang=en' if lang == 'en' and ask else '')


STATE = ("(function(){var g=function(i){var e=document.getElementById(i);return e?!e.hidden:null};"
         "return {url: location.pathname + location.search + location.hash, lang: document.documentElement.lang,"
         "wait: g('dl-wait'), ready: g('dl-ready'), soon: g('dl-soon'), plans: g('plans'), line: g('dl-line'), none: g('dl-none'),"
         "links: [...document.querySelectorAll('[data-dl-link]')].map(a => a.getAttribute('href')),"
         "repo: [...document.querySelectorAll('main [data-repo-row]')].map(e => !e.hidden),"
         "contact: [...document.querySelectorAll('main [data-contact-row]')].map(e => !e.hidden),"
         "saved: (function(){try{return localStorage.getItem('runbook-lang')}catch(e){return 'ERR'}})()}})()")
# the page has read update/latest.json and shown what follows from it (site.js marks that on <html>); the plans file is
# asked for before it from the same server, so its answer is in by then too
DONE = "document.readyState === 'complete' && document.documentElement.classList.contains('dl-done')"
PLAN_ROWS = ("[...document.querySelectorAll('#plans-list > .plan')].map(li => ({"
             "title: li.querySelector('.pn').textContent, meta: li.querySelector('.pm') ? li.querySelector('.pm').textContent.replace(/\\s+/g, ' ').trim() : '',"
             "summary: li.querySelector('.ps') ? li.querySelector('.ps').textContent : null,"
             "links: [...li.querySelectorAll('a')].map(a => a.getAttribute('href')), tags: li.querySelectorAll('img,script,b b,i').length}))")
WORDS = "function W(s){return s.split(/\\s+/).filter(function(w){return /[\\p{L}\\p{N}]/u.test(w)}).length}"
SIDE = "({sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth})"
# a dash that is the first thing on its line: every text node is walked, a dash is compared with the character before it
DASHES = ("(function(){var bad=[], w=document.createTreeWalker(document.querySelector('main'), NodeFilter.SHOW_TEXT), n, r=document.createRange();"
          "var box=function(node, i){r.setStart(node, i); r.setEnd(node, i + 1); var b=r.getClientRects(); return b.length ? b[0] : null};"
          "while ((n = w.nextNode())) { var t=n.nodeValue; for (var i=1; i<t.length; i++) { if (t[i] !== '\\u2014' && t[i] !== '\\u2013') continue;"
          "var d=box(n, i), j=i-1; while (j > 0 && /\\s/.test(t[j])) j--; var p=box(n, j);"
          "if (d && p && d.top > p.top + 4) bad.push(t.slice(Math.max(0, i - 24), i + 12)); } } return bad})()")


def open_tab(chrome, accept=None, dark=True, width=1280, script=True):
    tab = chrome.tab()
    tab.size(width, 800, scale=1, dark=dark)
    if accept:
        tab.call('Network.setUserAgentOverride', userAgent=tab.js('navigator.userAgent'), acceptLanguage=accept)
    if not script:
        tab.call('Emulation.setScriptExecutionDisabled', value=True)
    return tab


def load(tab, path):
    tab.go(base + path)
    tab.wait(DONE, 20)
    time.sleep(0.4)
    return tab.js(STATE)


def forget(tab):
    tab.go(base + '/ru/')
    tab.wait("document.readyState === 'complete'", 20)
    tab.js("localStorage.clear()")


def click(tab, selector):
    tab.js("document.querySelector(%s).click()" % json.dumps(selector))
    time.sleep(1.2)
    tab.wait(DONE, 20)
    return tab.js(STATE)


def desktop(tab):
    tab.size(1280, 800, scale=1, dark=True)


def phone(tab):
    tab.size(390, 844, scale=2, mobile=True, dark=True)
    time.sleep(0.5)


clear()
# ---------- the pages are what the sources build ----------------------------------------------------------------------
built = subprocess.run([sys.executable, '-X', 'utf8', str(HERE / 'build_site.py'), str(project), '--check'],
                       capture_output=True, text=True, encoding='utf-8')
check('site/ holds exactly what work/site/src builds (one header and footer for all pages)', built.returncode == 0,
      (built.stdout + built.stderr)[-400:])

chrome = Chrome(profile, port)
try:
    # ---------- language ------------------------------------------------------------------------------------------------
    ru = open_tab(chrome, accept='ru-RU,ru;q=0.9,en;q=0.8')
    forget(ru)
    s = load(ru, '/')
    check('/, Russian browser, first visit -> /ru/', s['url'] == '/ru/' and s['lang'] == 'ru', s)
    s = load(ru, '/safety/')
    check('/safety/, Russian browser, first visit -> /ru/safety/ (the address without a language is the general one)',
          s['url'] == '/ru/safety/' and s['lang'] == 'ru', s)
    s = load(ru, '/?lang=en')
    check('/?lang=en, Russian browser -> stays English, the address keeps the parameter', s['lang'] == 'en' and s['url'] == '/?lang=en', s)
    s = load(ru, '/install/?lang=en')
    check('/install/?lang=en, Russian browser -> stays English', s['lang'] == 'en' and s['url'] == '/install/?lang=en', s)
    load(ru, '/about/?lang=en')
    s = click(ru, '.foot nav a')
    check('/about/?lang=en, Russian browser, nothing chosen: a link to another page keeps English (/install/?lang=en)',
          s['lang'] == 'en' and s['url'] == '/install/?lang=en' and s['saved'] is None, s)
    load(ru, '/ru/safety/#network')
    s = click(ru, 'a[data-lang=en]')
    check('«English» on /ru/safety/#network -> the same page in English, place kept, choice saved, parameter removed',
          s['lang'] == 'en' and s['url'] == '/safety/#network' and s['saved'] == 'en', s)
    s = load(ru, '/install/')
    check('/install/, Russian browser, English chosen -> stays English', s['lang'] == 'en' and s['url'] == '/install/', s)
    s = click(ru, 'a[data-lang=ru]')
    check('«Русский» on /install/ -> /ru/install/, choice saved', s['lang'] == 'ru' and s['url'] == '/ru/install/' and s['saved'] == 'ru', s)
    s = load(ru, '/about/')
    check('/about/, Russian chosen -> /ru/about/', s['lang'] == 'ru' and s['url'] == '/ru/about/', s)
    ru.call('Page.close')

    en = open_tab(chrome, accept='en-GB,en;q=0.9')
    forget(en)
    s = load(en, '/')
    check('/, English browser, first visit -> stays', s['lang'] == 'en' and s['url'] == '/', s)
    s = load(en, '/ru/about/')
    check('/ru/about/, English browser -> stays Russian (a direct link)', s['lang'] == 'ru' and s['url'] == '/ru/about/', s)
    # the browser's languages are tried in its own order: the first one the site has wins (a language the site lacks is skipped)
    de = open_tab(chrome, accept='zh-TW,zh;q=0.9,ru;q=0.5')
    s = load(de, '/safety/')
    check('/safety/, a browser whose first language the site lacks and Russian second -> /ru/safety/', s['lang'] == 'ru' and s['url'] == '/ru/safety/', s)
    de.call('Page.close')
    de = open_tab(chrome, accept='zh-TW,zh;q=0.9,en;q=0.6,ru;q=0.5')
    s = load(de, '/safety/')
    check('/safety/, the same with English before Russian -> stays English', s['lang'] == 'en' and s['url'] == '/safety/', s)
    de.call('Page.close')
    de = open_tab(chrome, accept='zh-TW,zh;q=0.9')
    s = load(de, '/')
    check('/, a browser with no language the site has -> stays English', s['lang'] == 'en' and s['url'] == '/', s)
    de.call('Page.close')

    # ---------- the shared header and footer ------------------------------------------------------------------------------
    own = (site / 'assets' / 'config.js').read_text(encoding='utf-8')
    conf = {k: (re.search(r"^\s*%s:\s*'([^']*)'" % k, own, re.M) or [None, ''])[1] for k in ('repo', 'contact', 'contactSubject')}
    SHELL = ("(function(){var p=function(a){var u=new URL(a.href); return u.origin === location.origin ? u.pathname + u.search + u.hash : a.href};"
             "return {bar: [document.querySelector('.brand').innerText.trim(), document.querySelector('.bar summary').innerText.trim(),"
             "document.querySelector('.langs-menu a').textContent.trim(), document.querySelector('.bar .btn').innerText.trim()],"
             "tabs: document.querySelectorAll('.tabs').length, menu: document.querySelector('.bar details').open,"
             "list: [...document.querySelectorAll('.langs-menu > *')].map(e => (e.tagName === 'A' ? '' : '* ') + e.textContent.trim()),"
             "brand: document.querySelector('.brand').getAttribute('href'), lang: p(document.querySelector('.langs-menu a')),"
             "foot: [...document.querySelectorAll('.foot nav a')].filter(a => !a.hidden).map(a => a.textContent),"
             "to: [...document.querySelectorAll('.foot nav a')].filter(a => !a.hidden).map(p),"
             "ggg: document.querySelector('.ggg').textContent, who: document.querySelector('.foot p').textContent,"
             "h1: document.querySelectorAll('h1').length, scheme: document.querySelector('meta[name=color-scheme]').content,"
             "bg: getComputedStyle(document.body).backgroundColor,"
             "canon: document.querySelector('link[rel=canonical]').href, og: document.querySelector('meta[property=\"og:image\"]').content,"
             "card: document.querySelector('meta[name=\"twitter:card\"]').content}})()")
    for lang in ('en', 'ru'):
        home = '/ru/' if lang == 'ru' else '/'
        other = 'en' if lang == 'ru' else 'ru'
        for page in PAGES:
            load(en, url(page, lang))
            g = en.js(SHELL)
            names = {'en': 'English', 'ru': 'Русский'}
            check('%s %s: header — name, the language with its menu closed, «Скачать», no tabs; footer — five links to the right places, the GGG line' % (lang, page),
                  g['bar'] == ['PoE2 Runbook', names[lang] + ' ▾', names[other], {'en': 'Download', 'ru': 'Скачать'}[lang]]
                  and g['menu'] is False and g['tabs'] == 0 and g['lang'] == url(page, other, ask=True) and g['foot'] == FOOT[lang]
                  # the list names every language of the site in the program's order; the current one is marked and is not a link
                  and g['list'] == [('* ' if code == lang else '') + name for code, name in ON_SITE]
                  and g['to'] == [home + 'install/', home + 'safety/', conf['repo'], home + 'about/#licence', home + 'about/#contact']
                  and g['ggg'] == GGG and g['who'] == '© 2026 Sergei Labutin' and g['h1'] == 1
                  and g['canon'] == 'https://poe2.labutin.gg' + home + PAGES[page]
                  and g['og'] == 'https://poe2.labutin.gg/assets/og-%s.png' % lang and g['card'] == 'summary_large_image', g)
            check('%s %s: the brand leads to the main page' % (lang, page),
                  en.js("new URL(document.querySelector('.brand').href).pathname") == home, g['brand'])
    for name in ('og-en.png', 'og-ru.png'):
        from PIL import Image
        with Image.open(site / 'assets' / name) as im:
            check('assets/%s is 1200 x 630' % name, im.size == (1200, 630), im.size)
    # the language menu: a click on the name opens it, Esc and a click elsewhere close it
    load(en, url('safety', 'ru'))
    en.js("document.querySelector('.bar summary').click()")
    time.sleep(0.3)
    a = en.js("(function(){var d=document.querySelector('.bar details'), m=document.querySelector('.langs-menu a').getBoundingClientRect();"
              "return {open: d.open, seen: m.width > 0 && m.height > 0, inside: m.right <= document.documentElement.clientWidth}})()")
    en.js("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true}))")
    time.sleep(0.2)
    b = en.js("document.querySelector('.bar details').open")
    en.js("document.querySelector('.bar summary').click()")
    time.sleep(0.2)
    en.js("document.querySelector('h1').click()")
    time.sleep(0.2)
    c = en.js("document.querySelector('.bar details').open")
    check('the language menu opens under the name, inside the window; Esc and a click elsewhere close it',
          a == {'open': True, 'seen': True, 'inside': True} and b is False and c is False, (a, b, c))
    # one theme: with a light system the page stays dark
    light = open_tab(chrome, accept='en-GB,en', dark=False)
    for page in ('overview', 'safety'):
        load(light, url(page, 'ru'))
        g = light.js("({bg: getComputedStyle(document.body).backgroundColor, scheme: document.querySelector('meta[name=color-scheme]').content,"
                     "ink: getComputedStyle(document.querySelector('h1')).color})")
        check('ru %s with a light system: still the dark page' % page,
              g['bg'] == 'rgb(8, 9, 11)' and g['scheme'] == 'dark' and g['ink'] == 'rgb(245, 245, 247)', g)
    light.call('Page.close')

    # ---------- «Скачать»: no build published ---------------------------------------------------------------------------------
    NONE = {'en': 'The first build is not published yet', 'ru': 'Первая сборка ещё не опубликована'}
    LINE = {'en': 'Version 0.5.5.18 · for game 0.5.5', 'ru': 'Версия 0.5.5.18 · для игры 0.5.5'}
    SYS = {'en': 'Windows 10 and 11', 'ru': 'Windows 10 и 11'}
    META = {'en': '26 November 2026 · for game 0.5.5 · Windows 10 and 11 · 39 MB', 'ru': '26 ноября 2026 · для игры 0.5.5 · Windows 10 и 11 · 39 МБ'}
    TEXT = "(function(s){return document.querySelector(s).innerText.replace(/\\s+/g, ' ').trim()})"
    for lang in ('en', 'ru'):
        for page in PAGES:
            s = load(en, url(page, lang))
            want = '#download' if page == 'install' else ({'overview': '', 'safety': '../', 'about': '../'}[page] + 'install/#download')
            ok = bool(s['links']) and set(s['links']) == {want}
            got = ''
            if page == 'overview':
                got = (en.js(TEXT + "('.hero .fine')"), en.js(TEXT + "('.release-name')"), en.js(TEXT + "('.release-meta')"))
                ok = ok and len(s['links']) == 3 and got == (NONE[lang], 'PoE2 Runbook', NONE[lang] + ' · ' + SYS[lang])
            if page == 'install':
                ok = ok and s['soon'] and not s['ready'] and not s['wait']
            check('%s %s, no latest.json: every «Скачать» leads to the install page%s' % (
                lang, page, {'overview': '; under the first button and in the release block — no build yet',
                             'install': '; the block says «soon»'}.get(page, '')), ok, (s, got))

    # ---------- «Скачать»: a build is published --------------------------------------------------------------------------------
    put('update/latest.json', json.dumps(GOOD))
    for lang in ('en', 'ru'):
        for page in PAGES:
            s = load(en, url(page, lang))
            ok = bool(s['links']) and set(s['links']) == {GOOD['installer']['url']}
            got = ''
            if page == 'overview':
                got = (en.js(TEXT + "('.hero .fine')"), en.js(TEXT + "('.release-name')"), en.js(TEXT + "('.release-meta')"),
                       en.js("document.querySelector('.release-do a').getAttribute('href')"))
                ok = ok and got == (LINE[lang], 'PoE2 Runbook 0.5.5.18', META[lang], 'install/')
            check('%s %s, latest.json: every «Скачать» is one click to the installer%s' % (
                lang, page, '; version and game under the first button; name, date, game, system and size in the release block' if page == 'overview' else ''), ok, (s, got))
        s = load(en, url('install', lang))
        got = en.js("({link: document.getElementById('dl-link').href, button: document.getElementById('dl-link').textContent,"
                    "version: document.getElementById('dl-version').textContent, game: document.getElementById('dl-game').textContent,"
                    "size: document.getElementById('dl-size').textContent, bytes: document.getElementById('dl-bytes').textContent,"
                    "date: document.getElementById('dl-date').textContent, sha: document.getElementById('dl-sha').textContent,"
                    "file: document.getElementById('dl-file').textContent, notes: document.getElementById('dl-notes-text').textContent,"
                    "cmd: document.getElementById('cmd-hash').textContent, rows: document.querySelectorAll('#download .row:not([hidden])').length})")
        print('   ', lang, json.dumps(got, ensure_ascii=False))
        check('%s install: latest.json -> the block is ready' % lang, s['ready'] and not s['soon'] and not s['wait'], s)
        check('%s install: link, version, game, size, hash, file name, command — seven rows' % lang,
              got['link'] == GOOD['installer']['url'] and got['version'] == '0.5.5.18' and got['game'] == '0.5.5'
              and got['sha'] == GOOD['installer']['sha256'] and got['file'] == 'PoE2Runbook-Setup-0.5.5.18.exe'
              and got['cmd'] == 'Get-FileHash "PoE2Runbook-Setup-0.5.5.18.exe"' and '0.5.5.18' in got['button']
              and got['size'] in ('39.0 MB', '39,0 МБ') and got['rows'] == 7, got)
        check('%s install: notes in the page language' % lang, got['notes'] == GOOD['notes'][lang], got)
        for name, size in (('1280', desktop), ('390', phone)):
            size(en)
            box = en.rect('#download')
            en.shot(shots / ('ready-install-%s-%s.png' % (lang, name)),
                    clip={'x': 0, 'y': 0, 'width': en.js('document.documentElement.clientWidth'), 'height': box['y'] + box['height'] + 24})
            m = en.js(SIDE)
            check('%s install: the ready block at %s does not scroll sideways' % (lang, name), m['sw'] <= m['cw'], m)
        desktop(en)
        load(en, url('overview', lang))
        en.shot(shots / ('ready-release-%s.png' % lang), clip=en.rect('.release-in', 40))
        en.shot(shots / ('ready-hero-%s.png' % lang))
    bad = {'wrong format': dict(GOOD, format='something-else'), 'version 2': dict(GOOD, v=2),
           'http address': dict(GOOD, installer=dict(GOOD['installer'], url='http://example.com/a.exe')),
           'javascript address': dict(GOOD, installer=dict(GOOD['installer'], url='javascript:alert(1)')),
           'short hash': dict(GOOD, installer=dict(GOOD['installer'], sha256='abc')),
           'no installer': {k: v for k, v in GOOD.items() if k != 'installer'},
           'size as text': dict(GOOD, installer=dict(GOOD['installer'], size='big'))}
    for name, data in bad.items():
        put('update/latest.json', json.dumps(data))
        s = load(en, url('install', 'en'))
        o = load(en, url('overview', 'en'))
        check('latest.json with %s -> «soon»; the main page keeps its buttons on the install page' % name,
              s['soon'] and not s['ready'] and o['none'] is True and set(o['links']) == {'install/#download'}, (s, o))
    put('update/latest.json', '<html>not json')
    s = load(en, url('install', 'en'))
    check('latest.json that is not JSON -> «soon»', s['soon'] and not s['ready'], s)
    hostile = dict(GOOD, notes={'en': '<img src=x onerror=alert(1)><b>bold</b>', 'ru': 'x'}, notice={'en': 'an announcement'})
    put('update/latest.json', json.dumps(hostile))
    s = load(en, url('install', 'en'))
    got = en.js("({text: document.getElementById('dl-notes-text').textContent, tags: document.getElementById('dl-notes-text').children.length})")
    check('notes are shown as text, never as markup; a field the page does not know is skipped',
          s['ready'] and got['tags'] == 0 and '<img' in got['text'], got)
    clear()

    # ---------- the main page: order, first screen, budget, pictures, questions --------------------------------------------------
    # What the sample itself shows — the version the site stands on (src/sample): the order of its blocks, how many
    # words (its own text, answers closed), questions and pictures. The Russian main page must show exactly that, plus
    # the section of ready plans before the authors' band; the English one — the same in its own words.
    sample = open_tab(chrome)
    sample.go((project / 'work' / 'site' / 'src' / 'sample' / 'index.html').as_uri())
    sample.wait("document.readyState === 'complete'", 20)
    SAMPLE = sample.js("(function(){%s var main=document.querySelector('main'); return {words: W(main.innerText),"
                       "order: [...main.children].map(e => e.className), questions: main.querySelectorAll('.faq details').length,"
                       "pictures: main.querySelectorAll('img').length, links: main.querySelectorAll('a').length}})()" % WORDS)
    sample.call('Page.close')
    sample_words = SAMPLE['words']
    at = SAMPLE['order'].index('authors')
    ORDER = SAMPLE['order'][:at] + ['faq plans'] + SAMPLE['order'][at:]
    print('    the sample:', json.dumps(SAMPLE, ensure_ascii=False))
    put('update/latest.json', json.dumps(dict(GOOD, version='0.5.5.22')))       # the state the sample draws: a build is published
    for lang in ('en', 'ru'):
        desktop(en)
        load(en, url('overview', lang))
        b = en.js("(function(){%s var q=function(s){return Math.round(document.querySelector(s).getBoundingClientRect().bottom)};"
                  "var main=document.querySelector('main'), faq=document.querySelector('.faq:not(.plans)');"
                  "return {order: [...main.children].map(e => e.className), h1: q('.hero h1'), lead: q('.lead'), button: q('.hero .btn'), fine: q('.hero .fine'),"
                  "list: q('.product img'), listW: document.querySelector('.product img').getBoundingClientRect().width,"
                  "words: W(main.innerText), page: W(document.body.innerText), height: document.documentElement.scrollHeight,"
                  "h1px: parseFloat(getComputedStyle(document.querySelector('h1')).fontSize),"
                  "h2: [...main.querySelectorAll('section:not([hidden]) h2')].map(e => W(e.innerText)),"
                  "h3: [...main.querySelectorAll('h3')].map(e => W(e.innerText)),"
                  "removed: main.querySelectorAll('.scene, .game, .feats, ul.no, ol.start, figcaption, .get').length,"
                  "authors: (function(a){return a ? a.getAttribute('href') : null})(document.querySelector('.authors a')),"
                  "open: faq.querySelectorAll('details[open]').length, questions: faq.querySelectorAll('details').length,"
                  "answers: [...faq.querySelectorAll('details')].map(d => d.querySelector('p').textContent.trim().length),"
                  "links: [...faq.querySelectorAll('details a')].map(a => a.getAttribute('href')),"
                  "rules: /GGG|Grinding Gear|правил|\\brules?\\b/i.test(main.textContent),"
                  "code: main.querySelectorAll('code,pre,kbd').length}})()" % WORDS)
        print('   ', lang, json.dumps(b, ensure_ascii=False))
        kept = False        # a language whose main page is still a fragment kept from an earlier sample (none now)
        check('%s main page: %s; no block of the earlier versions; the authors’ link leads to «Каталог планов»' % (
            lang, 'the sample’s blocks in the sample’s order, [ready plans] before the authors’ band' if not kept else
            'first screen first, [ready plans] right before the authors’ band, then the release and the questions'),
            (b['order'] == ORDER if not kept else b['order'][0] == 'hero' and b['order'][-4:] == ORDER[-4:])
            and b['removed'] == 0 and b['authors'] == 'about/#catalogue', b)
        check('%s main page, 1280 x 800: headline (%d px), sentence, button, its line and the whole list are on the first screen' % (lang, b['h1px']),
              b['h1'] < b['lead'] < b['button'] < b['fine'] < b['list'] <= 800 and 60 <= b['h1px'] <= 92 and abs(b['listW'] - 832) < 1, b)
        check('%s main page: %d words of the page’s own text with the answers closed (with header and footer %d); the sample shows %d%s' % (
            lang, b['words'], b['page'], sample_words, ' — the same' if lang == 'ru' else ' in Russian'),
              b['words'] == sample_words if lang == 'ru' else b['words'] > 100, b)
        check('%s main page: no code, key cap or path' % lang, b['code'] == 0, b)
        check('%s main page: %d questions%s, closed, each with an answer' % (lang, b['questions'], ' as in the sample' if not kept else ''),
              (b['questions'] == SAMPLE['questions'] if not kept else b['questions'] >= 5) and b['open'] == 0 and min(b['answers']) > 15, b)
        if not kept:
            check('%s main page: the answers’ links lead to «how to verify the file» of the install page and to the author’s address '
                  '(the one of config.js); the link to the repository’s issues is there but hidden while no address is set' % lang,
                  b['links'] == ['install/#verify', 'mailto:%s?subject=%s' % (conf['contact'], quote(conf['contactSubject'])), 'about/#contact']
                  and en.js("document.querySelector('[data-issues-row]').hidden") is True, b['links'])
        check('%s main page: GGG and its rules are not spoken of (the footer line apart) — that is the reads page’s matter' % lang, b['rules'] is False, b)
        pics = en.js("(async function(){for (const i of document.images) i.loading='eager';"
                     "await Promise.all([...document.images].map(i => i.decode().catch(() => null)));"
                     "return [...document.querySelectorAll('main img')].map(i => ({src: i.getAttribute('src').split('/').pop(), w: i.naturalWidth, h: i.naturalHeight,"
                     "aw: +i.getAttribute('width'), ah: +i.getAttribute('height'), shown: Math.round(i.getBoundingClientRect().width)}))})()")
        dense = [p for p in pics if p['src'] != 'icon.png']
        check('%s main page: %d pictures of the program%s in the page’s language, each loads, has its size written and is twice as dense as shown at 1280 %s' % (
            lang, len(dense), ' as in the sample' if not kept else '', [(p['src'], p['shown'], p['w']) for p in dense]),
              (len(dense) == SAMPLE['pictures'] if not kept else len(dense) >= 6) and all(p['src'].endswith('-%s.webp' % lang) for p in dense)
              and all(p['w'] > 0 and p['w'] == p['aw'] and p['h'] == p['ah'] and p['w'] >= 2 * p['shown'] - 2 for p in dense), pics)
        d = en.js(DASHES)
        check('%s main page at 1280: no line begins with a dash' % lang, not d, d)
        phone(en)
        m = en.js("(function(){var q=function(s){return Math.round(document.querySelector(s).getBoundingClientRect().bottom)};"
                  "var w=document.querySelector('.shot-window'), i=w.querySelector('img'), a=document.querySelector('.split-pic img');"
                  "return {h1: q('.hero h1'), lead: q('.lead'), button: q('.hero .btn'), height: document.documentElement.scrollHeight,"
                  "sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth,"
                  "box: Math.round(w.getBoundingClientRect().width), img: Math.round(i.getBoundingClientRect().width), natural: i.naturalWidth,"
                  "clip: getComputedStyle(w).overflowX, answer: Math.round(a.getBoundingClientRect().width), answerNatural: a.naturalWidth}})()")
        check('%s main page, 390 x 844: headline, sentence and button on the first screen; no sideways scroll' % lang,
              m['h1'] < m['lead'] < m['button'] <= 844 and m['sw'] <= m['cw'], m)
        check('%s main page, 390: the program’s window is cut on the right, not shrunk (%d px in a box of %d), and still twice as dense' % (
            lang, m['img'], m['box']), m['img'] > m['box'] * 1.9 and m['clip'] == 'hidden' and m['natural'] >= 2 * m['img'] - 2
              and m['answerNatural'] >= 2 * m['answer'] - 2, m)
        d = en.js(DASHES)
        check('%s main page at 390: no line begins with a dash' % lang, not d, d)
    desktop(en)
    clear()

    # ---------- what the program reads: a list read at a glance --------------------------------------------------------------------
    for lang in ('en', 'ru'):
        load(en, url('safety', lang))
        f = en.js("(function(){var rows=[...document.querySelectorAll('.facts > li')], d=[...document.querySelectorAll('main details')];"
                  "var b=document.querySelector('button[data-open-all]');"
                  "return {rows: rows.length, details: d.length, open: d.filter(x => x.open).length,"
                  "empty: rows.filter(r => !r.querySelector('.k') || !r.querySelector('.v') || !r.querySelector('.k').textContent.trim() || !r.querySelector('.v').textContent.trim()).length,"
                  "tall: [...document.querySelectorAll('.facts summary, .facts .row')].filter(e => e.getBoundingClientRect().height > 62).map(e => e.querySelector('.k').textContent),"
                  "nobody: d.filter(x => !x.querySelector('.w') || !x.querySelector('.w').textContent.trim()).length,"
                  "button: !!b && !b.hidden, word: b ? b.textContent : null, tiles: document.querySelectorAll('ul.no, .no li').length,"
                  "h1px: parseFloat(getComputedStyle(document.querySelector('h1')).fontSize), px: parseFloat(getComputedStyle(document.querySelector('.facts .v')).fontSize),"
                  "boxed: [...document.querySelectorAll('.facts > li')].filter(e => getComputedStyle(e).borderLeftWidth !== '0px' || getComputedStyle(e).backgroundColor !== 'rgba(0, 0, 0, 0)').length,"
                  "toc: [...document.querySelectorAll('.toc a')].map(a => a.getAttribute('href')),"
                  "ids: [...document.querySelectorAll('section.blk')].map(s => '#' + s.id),"
                  "files: /update\\/latest\\.json/.test(document.getElementById('network').textContent) && /plans\\/index\\.json/.test(document.getElementById('network').textContent),"
                  "ggg: document.getElementById('rules').textContent.indexOf(%s) >= 0}})()" % json.dumps(GGG))
        print('   ', lang, json.dumps(f, ensure_ascii=False))
        check('%s reads page: a headline of 44–54 px, the sentence, no tiles with crosses; contents lead to every group, GGG’s rules at the end' % lang,
              44 <= f['h1px'] <= 54 and f['tiles'] == 0 and f['toc'] == f['ids'] and f['ids'][-1] == '#rules' and f['ggg'], f)
        check('%s reads page: %d rows of 17 px with thin lines and no boxes, each «what — why» in one line at 1280; every explanation closed and not empty' % (lang, f['rows']),
              f['rows'] >= 30 and f['empty'] == 0 and not f['tall'] and f['details'] >= 25 and f['open'] == 0 and f['nobody'] == 0
              and f['px'] == 17 and f['boxed'] == 0, f)
        check('%s reads page: the update and catalogue rows are in the page’s text' % lang, f['files'], f)
        en.js("document.querySelector('button[data-open-all]').click()")
        time.sleep(0.3)
        a = en.js("({open: [...document.querySelectorAll('main details')].filter(x => x.open).length, word: document.querySelector('button[data-open-all]').textContent})")
        en.js("document.querySelector('button[data-open-all]').click()")
        time.sleep(0.3)
        z = en.js("({open: [...document.querySelectorAll('main details')].filter(x => x.open).length, word: document.querySelector('button[data-open-all]').textContent})")
        check('%s reads page: one button opens every explanation and closes them again' % lang,
              f['button'] and a['open'] == f['details'] and a['word'] != f['word'] and z['open'] == 0 and z['word'] == f['word'], (f['word'], a, z))
        load(en, url('install', lang))
        st = en.js("({steps: document.querySelectorAll('.troubles > details').length, open: document.querySelectorAll('.troubles details[open]').length,"
                   "tall: [...document.querySelectorAll('.troubles summary')].filter(e => e.getBoundingClientRect().height > 72).length,"
                   "blocks: [...document.querySelectorAll('section.blk')].map(s => s.id), langs: document.querySelectorAll('#langs .langs span[lang]').length,"
                   "h1px: parseFloat(getComputedStyle(document.querySelector('h1')).fontSize)})")
        check('%s install: four first-start troubles, each one line with the answer inside; what it needs, updating, nine languages, removal' % lang,
              st['steps'] == 4 and st['open'] == 0 and st['tall'] == 0 and st['blocks'] == ['first-start', 'needs', 'update', 'langs', 'remove']
              and st['langs'] == 9 and 44 <= st['h1px'] <= 54, st)

    # ---------- ready plans on the main page -----------------------------------------------------------------------------------------
    s = load(en, url('overview', 'en'))
    check('no plans/index.json -> no section of ready plans', s['plans'] is False, s)
    put('plans/index.json', json.dumps(PLANS))
    one = PLANS['plans'][0]
    want = {'en': ('by %s · for game %s · version %s · 26 November 2026', 'Ready-made plans', 'Edit → Catalogue'),
            'ru': ('автор: %s · для игры %s · версия %s · 26 ноября 2026 г.', 'Готовые планы', '«Редактор» → «Каталог»')}
    for lang in ('en', 'ru'):
        s = load(en, url('overview', lang))
        rows = en.js(PLAN_ROWS)
        head = en.js("({h: document.querySelector('#plans h2').textContent, fine: document.querySelector('#plans .fine').innerText.replace(/\\s+/g, ' ').trim(),"
                     "mail: [...document.querySelectorAll('#plans [data-contact]')].map(a => a.getAttribute('href')),"
                     "download: [...document.querySelectorAll('#plans a')].filter(a => /\\.plan|file/.test(a.getAttribute('href') || '')).length,"
                     "before: !!(document.getElementById('plans').compareDocumentPosition(document.getElementById('download')) & 4),"
                     "after: document.getElementById('plans').nextElementSibling.classList.contains('authors'),"
                     "lines: getComputedStyle(document.querySelector('#plans .plan')).borderTopWidth,"
                     "sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth})")
        print('   ', lang, json.dumps(rows, ensure_ascii=False), json.dumps(head, ensure_ascii=False))
        check('%s: plans/index.json -> the section stands right before the authors’ band, above the release block' % lang,
              s['plans'] is True and head['before'] and head['after'] and head['lines'] == '1px', (s, head))
        check('%s: a plan row — title, author as a link, game, version, date, one sentence' % lang,
              len(rows) == 1 and rows[0]['title'] == one['title'][lang]
              and rows[0]['meta'] == want[lang][0] % (one['author']['name'], one['game'], one['version'])
              and rows[0]['summary'] == one['summary'][lang] and rows[0]['links'] == [one['author']['url']], rows)
        check('%s: the section says where a plan is installed, offers to send one, and has no download link' % lang,
              head['h'] == want[lang][1] and want[lang][2] in head['fine'] and head['download'] == 0
              and '@' in head['fine'] and head['mail'][0].startswith('mailto:'), head)
        check('%s: the page with plans does not scroll sideways' % lang, head['sw'] <= head['cw'], head)
        if lang == 'ru':
            en.shot(shots / 'plans-ru-1280.png', clip=en.rect('#plans', 20))
            phone(en)
            en.shot(shots / 'plans-ru-390.png', clip=en.rect('#plans', 8))
            m = en.js(SIDE)
            check('ru: the section of ready plans at 390 does not scroll sideways', m['sw'] <= m['cw'], m)
            desktop(en)
    evil = '<img src=x onerror="window.__hit=1"><script>window.__hit=1</script>'
    nasty = {'format': 'poe2-runbook-plans', 'v': 1, 'updated': '2026-11-26', 'plans': [
        {'uid': 'p1', 'version': evil, 'title': {'en': evil, 'ru': evil}, 'author': {'name': evil, 'url': 'javascript:window.__hit=1'},
         'game': evil, 'summary': {'en': evil}, 'published': evil},
        {'uid': 'p2', 'version': 2, 'title': {'ru': 'Только по-русски'}, 'author': {'name': 'Someone', 'url': 'http://example.com/me'},
         'game': '0.5.5', 'summary': {'ru': 'Одно предложение.'}, 'published': '2026-11-20'},
        {'uid': 'p3', 'title': {}, 'author': 'not an object', 'summary': 7},
        'not a plan', None, {'title': {'en': ''}}]}
    put('plans/index.json', json.dumps(nasty))
    s = load(en, url('overview', 'en'))
    rows = en.js(PLAN_ROWS)
    hit = en.js("({hit: window.__hit || 0, imgs: document.querySelectorAll('#plans img, #plans script').length})")
    print('   ', json.dumps(rows, ensure_ascii=False)[:700])
    check('values of plans/index.json are shown as text only: nothing runs, no tag appears',
          hit == {'hit': 0, 'imgs': 0} and len(rows) == 3 and rows[0]['title'].startswith('<img') and rows[0]['links'] == [], (hit, rows))
    check('an author address that is not http(s) gives no link; an http one does; a missing language falls back',
          rows[0]['links'] == [] and rows[1]['links'] == ['http://example.com/me'] and rows[1]['title'] == 'Только по-русски'
          and rows[1]['meta'] == 'by Someone · for game 0.5.5 · version 2 · 20 November 2026', rows)
    check('a plan with no title is named by its uid; rows that are not plans are skipped',
          rows[2]['title'] == 'p3' and rows[2]['meta'] == '' and rows[2]['summary'] is None, rows)
    for name, data in {'another format': dict(PLANS, format='x'), 'version 2': dict(PLANS, v=2), 'no plans': dict(PLANS, plans=[]),
                       'plans not a list': dict(PLANS, plans={'a': 1})}.items():
        put('plans/index.json', json.dumps(data))
        s = load(en, url('overview', 'en'))
        check('plans/index.json with %s -> no section' % name, s['plans'] is False, s)
    put('plans/index.json', 'not json at all')
    s = load(en, url('overview', 'en'))
    check('plans/index.json that is not JSON -> no section', s['plans'] is False, s)
    clear()

    # ---------- settings ----------------------------------------------------------------------------------------------------
    # the site's own config.js, as it is: what it names is what the pages show
    mail = ('mailto:' + conf['contact'] + ('?subject=' + quote(conf['contactSubject']) if conf['contactSubject'] else '')
            if '@' in conf['contact'] else conf['contact'])
    # the one wording about official builds (the same as in NOTICE.md): the site, then where the files are kept
    BUILDS = {'en': 'Official builds are published only at poe2.labutin.gg; the files themselves are stored in the releases of %s.',
              'ru': 'Официальные сборки публикуются только на poe2.labutin.gg; сами файлы лежат в выпусках репозитория %s.'}
    ABOUT = ("({repo: [...document.querySelectorAll('main [data-repo]')].map(a => a.getAttribute('href')),"
             "builds: [...document.querySelectorAll('#official p')].map(e => e.innerText.replace(/\\s+/g, ' ').trim())[2],"
             "mail: document.getElementById('contact-link').getAttribute('href'), mailText: document.getElementById('contact-link').textContent})")
    FOOTER = ("({source: document.querySelector('.foot nav a[data-repo]').getAttribute('href'),"
              "contact: !document.querySelector('.foot nav a[data-contact-row]').hidden, links: [...document.querySelectorAll('.foot nav a')].filter(a => !a.hidden).length})")
    for lang in ('en', 'ru'):
        s = load(en, url('about', lang))
        got = en.js(ABOUT)
        print('   ', lang, json.dumps(got, ensure_ascii=False))
        check('%s about: the site\'s own settings (repo %r, contact %r) are what the page shows' % (lang, conf['repo'], conf['contact']),
              s['repo'] == [bool(conf['repo'])] * 2 and s['contact'] == [bool(conf['contact'])] * 2
              and (not conf['repo'] or got['repo'] == [conf['repo']] * 2), (s, got))
        if conf['repo']:
            check('%s about: official builds — the one wording, with the repository address in it' % lang,
                  got['builds'] == BUILDS[lang] % conf['repo'].replace('https://', ''), got['builds'])
        if conf['contact']:
            check('%s about: contact — the address as the link text, the letter opens with its subject' % lang,
                  got['mail'] == mail and got['mailText'] == conf['contact'], (got['mail'], got['mailText']))
    put('assets/config.js', "window.RUNBOOK_SITE = {repo: '', contact: ''};")
    s = load(en, url('about', 'en'))
    f = en.js(FOOTER)
    check('settings empty -> no repository link, no contact section; in the footer «Source code» leads to the licence and «Contact» is gone',
          s['repo'] == [False, False] and s['contact'] == [False, False] and f == {'source': '#licence', 'contact': False, 'links': 4}, (s, f))
    put('assets/config.js', "window.RUNBOOK_SITE = {repo: 'https://github.com/example/poe2-runbook', contact: 'hello@example.com'};")
    for lang in ('en', 'ru'):
        s = load(en, url('about', lang))
        got = en.js("({repo: document.querySelector('main [data-repo]').href, mail: document.getElementById('contact-link').href,"
                    "text: document.getElementById('contact-link').textContent})")
        f = en.js(FOOTER)
        check('%s about: settings filled -> repository link, contact without a subject; the footer follows' % lang,
              s['repo'] == [True, True] and s['contact'] == [True, True]
              and got['repo'] == 'https://github.com/example/poe2-runbook' and got['mail'] == 'mailto:hello@example.com'
              and f == {'source': 'https://github.com/example/poe2-runbook', 'contact': True, 'links': 5}, (s, got, f))
    put('assets/config.js', "window.RUNBOOK_SITE = {repo: 'javascript:alert(1)', contact: 'https://example.com/contact'};")
    s = load(en, url('about', 'en'))
    got = en.js("({href: document.getElementById('contact-link').href, text: document.getElementById('contact-link').textContent})")
    check('a repository address that is not https is refused; a contact page address is a link',
          s['repo'] == [False, False] and s['contact'] == [True, True] and got['href'] == 'https://example.com/contact', (s, got))
    clear()

    # ---------- no page scrolls sideways; no line begins with a dash; every local link answers -----------------------------------
    links = set()
    for lang in ('en', 'ru'):
        for page in PAGES:
            for name, size in (('1280', desktop), ('390', phone)):
                size(en)
                load(en, url(page, lang))
                m = en.js(SIDE)
                check('%s %s at %s does not scroll sideways' % (lang, page, name), m['sw'] <= m['cw'], m)
                if page != 'overview':
                    en.js("document.querySelectorAll('main details').forEach(function(d){d.open = true})")
                    time.sleep(0.2)
                    d = en.js(DASHES)
                    check('%s %s at %s, everything opened: no line begins with a dash' % (lang, page, name), not d, d)
            links |= set(en.js("[...document.querySelectorAll('a[href]')].map(a => a.href).filter(h => h.indexOf(location.origin) === 0)"))
    desktop(en)
    dead = []
    for link in sorted({urljoin(link, urlsplit(link).path) for link in links}):
        try:
            with urllib.request.urlopen(link, timeout=10) as r:
                r.read(1)
        except urllib.error.HTTPError as e:
            dead.append((e.code, urlsplit(link).path))
    check('every link between the pages answers (%d addresses)' % len(links), not dead and len(links) >= 10, dead)
    en.call('Page.close')

    # ---------- without JavaScript ------------------------------------------------------------------------------------------
    for lang in ('en', 'ru'):
        for page in PAGES:
            off = open_tab(chrome, accept='ru-RU,ru', script=False)
            off.go(base + url(page, lang))
            time.sleep(1.6)
            off.call('Emulation.setScriptExecutionDisabled', value=False)
            got = off.js("(function(){var v=function(e){return !!e && getComputedStyle(e).display !== 'none'}, id=function(i){return document.getElementById(i)};"
                         "var ns=document.querySelector('#download noscript');"
                         "return {url: location.pathname, lang: document.documentElement.lang, js: /\\bjs\\b/.test(document.documentElement.className),"
                         "h1: document.querySelectorAll('h1').length, foot: [...document.querySelectorAll('.foot nav a')].filter(v).map(a => a.getAttribute('href')),"
                         "links: [...document.querySelectorAll('[data-dl-link]')].map(a => a.getAttribute('href')),"
                         "wait: v(id('dl-wait')), ready: v(id('dl-ready')), soon: v(id('dl-soon')), plans: v(id('plans')),"
                         "line: !!id('dl-line') && id('dl-line').textContent.trim() !== '', none: v(id('dl-none')), contact: v(id('contact')), all: v(document.querySelector('button[data-open-all]')),"
                         "rel: [id('rel-before'), id('rel-none'), id('rel-after')].some(v), name: id('rel-name') ? id('rel-name').textContent : '',"
                         "details: document.querySelectorAll('main details').length,"
                         "text: document.querySelector('main').textContent.length, noscript: /update\\/latest\\.json/.test(ns ? ns.textContent : '')}})()")
            ok = (got['lang'] == lang and got['url'] == url(page, lang) and not got['js'] and got['h1'] == 1 and len(got['foot']) == 4
                  and all(h.endswith('#download') for h in got['links']) and got['text'] > 400
                  and not any(got[k] for k in ('wait', 'ready', 'soon', 'plans', 'line', 'none', 'contact', 'all', 'rel')))
            if page == 'install':
                ok = ok and got['noscript']
            if page == 'safety':
                ok = ok and got['details'] >= 25
            if page == 'overview':
                ok = ok and got['details'] >= 5 and got['name'] == 'PoE2 Runbook'
            check('%s %s without JavaScript: no redirect, the page reads, «Скачать» leads to the install page, no state that needs a script' % (lang, page),
                  ok, got)
            if page in ('overview', 'install') and lang == 'ru':
                off.size(1280, 800, scale=1, dark=True)
                off.call('Emulation.setScriptExecutionDisabled', value=True)
                off.go(base + url(page, lang))
                time.sleep(1.5)
                off.shot(shots / ('nojs-%s-ru.png' % page))
            off.call('Page.close')

    # ---------- 404 ---------------------------------------------------------------------------------------------------------
    t = open_tab(chrome)
    t.go(base + '/no/such/page')
    t.wait("document.readyState === 'complete'", 20)
    got = t.js("({title: document.title, links: [...document.links].map(a => a.getAttribute('href')), h: [...document.querySelectorAll('h1')].map(e => e.textContent),"
               "bg: getComputedStyle(document.body).backgroundColor})")
    status = [e['params']['response']['status'] for e in t.events if e.get('method') == 'Network.responseReceived'
              and e['params']['response']['url'].endswith('/no/such/page')]
    foreign = [e['params']['request']['url'] for e in t.events if e.get('method') == 'Network.requestWillBeSent'
               and urlsplit(e['params']['request']['url']).netloc != host]
    check('a missing address -> 404.html with status 404, the same dark page, a link to the first page of every language of the site, nothing foreign',
          status == [404] and got['links'] == ['/' if code == 'en' else '/%s/' % code for code, _ in ON_SITE] and not foreign
          and got['bg'] == 'rgb(8, 9, 11)', (status, got, foreign))
    t.shot(shots / '404.png')
    t.call('Page.close')

    # ---------- opened from disk (double click) ---------------------------------------------------------------------------------
    f = open_tab(chrome, accept='ru-RU,ru')
    f.go((site / 'index.html').as_uri())
    time.sleep(2.5)
    got = f.js("({url: location.href.split('/site/')[1], lang: document.documentElement.lang, styled: getComputedStyle(document.body).backgroundColor,"
               "none: !document.getElementById('dl-none').hidden, plans: !document.getElementById('plans').hidden,"
               "img: document.querySelector('.product img').naturalWidth,"
               "foot: [...document.querySelectorAll('.foot nav a')].map(a => a.getAttribute('href')),"
               "dl: document.querySelector('.bar .btn').getAttribute('href'), brand: document.querySelector('.brand').getAttribute('href'),"
               "en: document.querySelector('a[data-lang=en]') ? document.querySelector('a[data-lang=en]').getAttribute('href') : null})")
    check('opened as a file, Russian browser -> ru/index.html, styled, no build, no plans, picture loaded, every link points at a file',
          got['url'] == 'ru/index.html' and got['lang'] == 'ru' and got['styled'] == 'rgb(8, 9, 11)' and got['none']
          and not got['plans'] and got['img'] > 0 and got['en'] == '../index.html?lang=en' and got['brand'] == '#top'
          and got['foot'][:2] == ['install/index.html', 'safety/index.html'] and got['foot'][3] == 'about/index.html#licence'
          and got['dl'] == 'install/index.html#download', got)
    f.go((site / 'safety' / 'index.html').as_uri())
    time.sleep(2.5)
    got = f.js("({url: location.href.split('/site/')[1], lang: document.documentElement.lang, styled: getComputedStyle(document.body).backgroundColor,"
               "rows: document.querySelectorAll('.facts > li').length})")
    check('safety/index.html opened as a file, Russian browser -> ru/safety/index.html, styled',
          got['url'] == 'ru/safety/index.html' and got['lang'] == 'ru' and got['styled'] == 'rgb(8, 9, 11)' and got['rows'] >= 30, got)
    f.call('Page.close')
finally:
    chrome.stop()
    clear()
bad = [n for n, ok in results if not ok]
print('\n%d checks, %d failed%s' % (len(results), len(bad), ': ' + '; '.join(bad) if bad else ''))

sys.exit(1 if bad else 0)
