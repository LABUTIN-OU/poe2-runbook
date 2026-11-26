# -*- coding: utf-8 -*-
"""The site in ALL the program's languages — checks of what the languages share: addresses, the list in the header,
the choice by the browser's language, hreflang, number and date formats, the pictures of the program in each language,
the header on a phone, and that every page of every language is in its own words. They run on a trial build
(build_site.py --trial): a language that has no texts yet shows the English ones there — such a language is named,
and the check of its words fails until the texts are written.

    python -X utf8 lang_checks.py <project> <trial dir> <shots dir> <chrome profile> [port] [debug port]

The trial dir is written anew (pages, stylesheet, an update/latest.json of the example); a server of its own lays it
over site/ for the time of the run. site/ itself is never written."""
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from cdp import Chrome  # noqa: E402

project, trial, shots, profile = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve(), Path(sys.argv[3]).resolve(), sys.argv[4]
port = int(sys.argv[5]) if len(sys.argv) > 5 else 4753
debug = int(sys.argv[6]) if len(sys.argv) > 6 else 4757
site = project / 'site'
base = 'http://127.0.0.1:%d' % port
ORIGIN = 'https://poe2.labutin.gg/'
TAGS = {'pt': 'pt-BR'}
# 26 November 2026 as each language writes a date (the program's own number format of the language)
DATES = {'en': '26 November 2026', 'ru': '26 ноября 2026', 'de': '26. November 2026', 'es': '26 de noviembre de 2026',
         'fr': '26 novembre 2026', 'ja': '2026年11月26日', 'ko': '2026년 11월 26일', 'pt': '26 de novembro de 2026',
         'th': '26 พฤศจิกายน 2569'}
results = []


def check(name, ok, detail=''):
    results.append((name, bool(ok)))
    print('%s  %s%s' % ('ok  ' if ok else 'FAIL', name, ('  — ' + str(detail)) if detail and not ok else ''))


# the program's languages, in its order — read the same way the build reads them
langs = []
for path in sorted((project / 'planner' / 'lang').glob('*.json')):
    if path.stem == 'raw':
        continue
    d = json.loads(path.read_text(encoding='utf-8'))
    langs.append({'code': path.stem, 'name': d['name'], 'locale': d['locale'], 'tag': TAGS.get(path.stem, path.stem),
                  'dir': '' if path.stem == 'en' else path.stem + '/'})
langs.sort(key=lambda x: ({'en': 0, 'ru': 1}.get(x['code'], 2), x['code']))
NAMES = [x['name'] for x in langs]

if trial.exists():
    shutil.rmtree(trial)
built = subprocess.run([sys.executable, '-X', 'utf8', str(HERE / 'build_site.py'), str(project), '--trial', str(trial)],
                       capture_output=True, text=True, encoding='utf-8')
pages = sorted(str(p.relative_to(trial)).replace('\\', '/') for p in trial.rglob('index.html'))
check('the trial build: four pages for each of the program’s %d languages (%s)' % (len(langs), ' '.join(x['code'] for x in langs)),
      built.returncode == 0 and len(pages) == 4 * len(langs), (built.stdout + built.stderr)[-600:])
example = json.loads((site / 'update' / 'latest.example.json').read_text(encoding='utf-8'))
(trial / 'update').mkdir(exist_ok=True)
(trial / 'update' / 'latest.json').write_text(json.dumps(dict(example, version='0.5.5.22', published='2026-11-26')), encoding='utf-8')

server = subprocess.Popen([sys.executable, '-X', 'utf8', '-u', str(HERE / 'serve.py'), str(site), str(port), str(trial)],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
DONE = "document.readyState === 'complete' && document.documentElement.classList.contains('dl-done')"
STATE = ("({url: location.pathname + location.search + location.hash, lang: document.documentElement.lang,"
         "saved: (function(){try{return localStorage.getItem('runbook-lang')}catch(e){return 'ERR'}})()})")
chrome = None
try:
    time.sleep(1.0)
    chrome = Chrome(profile, debug)
    shots.mkdir(parents=True, exist_ok=True)

    def open_tab(accept):
        tab = chrome.tab()
        tab.size(1280, 800, scale=1, dark=True)
        tab.call('Network.setUserAgentOverride', userAgent=tab.js('navigator.userAgent'), acceptLanguage=accept)
        return tab

    def load(tab, path):
        tab.go(base + path)
        tab.wait(DONE, 20)
        time.sleep(0.3)
        return tab.js(STATE)

    def forget(tab):
        tab.go(base + '/ru/')
        tab.wait("document.readyState === 'complete'", 20)
        tab.js('localStorage.clear()')

    # ---------- every language: its address, its header, its pictures -------------------------------------------------
    en = open_tab('en-GB,en;q=0.9')
    forget(en)
    SHELL = ("(function(){var p=function(a){var u=new URL(a.href); return u.pathname + u.search};"
             "var alt={}; document.querySelectorAll('link[rel=alternate]').forEach(l => alt[l.hreflang] = l.href);"
             "return {lang: document.documentElement.lang, locale: document.documentElement.getAttribute('data-locale'),"
             "name: document.querySelector('.bar summary').innerText.trim(),"
             "list: [...document.querySelectorAll('.langs-menu > *')].map(e => (e.tagName === 'A' ? '' : '* ') + e.textContent.trim()),"
             "to: [...document.querySelectorAll('.langs-menu a')].map(a => [a.getAttribute('data-lang'), a.lang, p(a)]),"
             "alt: alt, canon: document.querySelector('link[rel=canonical]').href,"
             "ogl: document.querySelector('meta[property=\"og:locale\"]').content,"
             "oga: [...document.querySelectorAll('meta[property=\"og:locale:alternate\"]')].length,"
             "foot: [...document.querySelectorAll('.foot nav a')].filter(a => !a.hidden && new URL(a.href).origin === location.origin).map(p),"
             "rel: (document.querySelector('.release-meta') || {innerText: ''}).innerText.trim()}})()")
    PICS = ("(async function(){for (const i of document.images) i.loading='eager';"
            "await Promise.all([...document.images].map(i => i.decode().catch(() => null)));"
            "return [...document.querySelectorAll('main img')].map(i => ({src: i.getAttribute('src').split('/').pop(), w: i.naturalWidth,"
            "shown: Math.round(i.getBoundingClientRect().width)}))})()")
    WORDS = ("(function(){var m=document.querySelector('main').cloneNode(true);"
             "m.querySelectorAll('.langs, template, code, pre, [lang=en]').forEach(e => e.remove()); return m.textContent.replace(/\\s+/g, ' ').trim()})()")
    english = {}
    for x in langs:
        code, home = x['code'], '/' + x['dir']
        for page in ('', 'safety/', 'install/', 'about/'):
            s = load(en, home + page)
            g = en.js(SHELL)
            text = en.js(WORDS)
            if code == 'en':
                english[page] = text
            else:
                left = sorted(set(re.findall('[А-Яа-яЁё]{3,}', text))) if code != 'ru' else []
                check('%s /%s%s: the page is in its own words — not the English text, no Russian word left' % (code, x['dir'], page),
                      text != english[page] and len(text) > 200 and not left, left[:8] or 'the same text as the English page')
            short = x['name'].split(' (')[0]
            ok = (s['url'] == home + page and g['lang'] == x['tag'] and g['locale'] == x['locale'] and g['name'] == short + ' ▾'
                  and g['list'] == [('* ' if n == x['name'] else '') + n for n in NAMES]
                  and g['to'] == [[o['code'], o['tag'], '/' + o['dir'] + page + ('?lang=en' if o['code'] == 'en' else '')] for o in langs if o is not x]
                  and g['alt'] == dict({o['tag']: ORIGIN + o['dir'] + page for o in langs}, **{'x-default': ORIGIN + page})
                  and g['canon'] == ORIGIN + x['dir'] + page and g['ogl'] == x['locale'].replace('-', '_') and g['oga'] == len(langs) - 1
                  and all(u.startswith(home) for u in g['foot']))
            check('%s /%s%s: opens as it is (a direct link), its language and number format, the header names it, the list holds all %d '
                  'in the program’s order with this one marked, every link leads to the same page; hreflang for all; links stay in the language'
                  % (code, x['dir'], page, len(langs)), ok, g)
            if page == '':
                check('%s: the release line starts with the date as the language writes it — «%s»' % (code, g['rel'][:40]),
                      g['rel'].startswith(DATES[code] + ' · '), g['rel'])
                pics = en.js(PICS)
                check('%s main page: %d pictures of the program, all in this language and twice as dense as shown' % (code, len(pics)),
                      len(pics) == 7 and all(p['src'].endswith('-%s.webp' % code) and p['w'] >= 2 * p['shown'] - 2 for p in pics), pics)
                en.js("document.querySelector('.bar summary').click()")
                time.sleep(0.3)
                en.shot(shots / ('%s-1280.png' % code))
                en.js("document.querySelector('.bar summary').click()")
                # phones: 390 (the sample's width) and 360 (the narrowest common Android)
                for width in (390, 360):
                    en.size(width, 844, scale=2, mobile=True, dark=True)
                    time.sleep(0.5)
                    en.js("document.querySelector('.bar summary').click()")
                    time.sleep(0.3)
                    m = en.js("(function(){var r=function(s){var b=document.querySelector(s).getBoundingClientRect(); return [Math.round(b.left), Math.round(b.right), Math.round(b.bottom)]};"
                              "return {sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth, brand: r('.brand'), lang: r('.bar summary'),"
                              "button: r('.bar .btn'), menu: r('.langs-menu'), h: innerHeight, tight: document.querySelector('.bar').classList.contains('tight'),"
                              "label: document.querySelector('.bar summary').innerText.trim()}})()")
                    if width == 390:
                        en.shot(shots / ('%s-390.png' % code))
                    check('%s main page at %d: no sideways scroll; name, language (%s) and button stand in one row with air between them; the opened list is inside the window'
                          % (code, width, 'its code: the name does not fit' if m['tight'] else 'by its name'),
                          m['sw'] <= m['cw'] and m['lang'][0] - m['brand'][1] >= 12 and m['button'][0] - m['lang'][1] >= 12 and m['button'][1] <= m['cw']
                          and m['menu'][0] >= 0 and m['menu'][1] <= m['cw'] and m['menu'][2] <= m['h'], m)
                    en.js("document.querySelector('.bar summary').click()")
                en.size(1280, 800, scale=1, dark=True)
    en.call('Page.close')

    # ---------- the general address goes to the browser's language --------------------------------------------------------
    cases = [(x['locale'] + ',' + x['code'] + ';q=0.9,en;q=0.5', x) for x in langs]
    for accept, x in cases:
        tab = open_tab(accept)
        forget(tab)
        s = load(tab, '/')
        t = load(tab, '/install/')
        check('a browser in %s (%s): / -> /%s, /install/ -> /%sinstall/' % (x['name'], accept.split(',')[0], x['dir'], x['dir']),
              s['url'] == '/' + x['dir'] and s['lang'] == x['tag'] and t['url'] == '/' + x['dir'] + 'install/' and s['saved'] is None, (s, t))
        tab.call('Page.close')
    for accept, want, why in (('pt-PT,pt;q=0.9', '/pt/', 'Portuguese of Portugal -> the Portuguese the site has'),
                              ('de-AT,de;q=0.9,en;q=0.8', '/de/', 'a regional German -> German'),
                              ('uk-UA,uk;q=0.9,ko;q=0.8,en;q=0.7', '/ko/', 'the first language is not on the site -> the next one that is'),
                              ('zh-TW,zh;q=0.9', '/', 'no language of the site -> stays at the general address'),
                              ('uk,en;q=0.9,ru;q=0.8', '/', 'English stands before Russian in the browser’s list -> stays')):
        tab = open_tab(accept)
        forget(tab)
        s = load(tab, '/')
        check('a browser with «%s»: %s (%s)' % (accept, want, why), s['url'] == want, s)
        tab.call('Page.close')

    # ---------- the choice in the list is remembered ------------------------------------------------------------------------
    tab = open_tab('ru-RU,ru;q=0.9,en;q=0.8')
    forget(tab)
    load(tab, '/ru/safety/#network')
    tab.js("document.querySelector('.bar summary').click()")
    tab.js("document.querySelector('.langs-menu a[data-lang=ja]').click()")
    time.sleep(1.2)
    tab.wait(DONE, 20)
    s = tab.js(STATE)
    check('«日本語» chosen on /ru/safety/#network -> the same page and place in Japanese, the choice saved', s['url'] == '/ja/safety/#network' and s['saved'] == 'ja', s)
    s = load(tab, '/about/')
    check('then the general address /about/ in a Russian browser -> /ja/about/ (the choice beats the browser)', s['url'] == '/ja/about/', s)
    tab.js("document.querySelector('.langs-menu a[data-lang=en]').click()")
    time.sleep(1.2)
    tab.wait(DONE, 20)
    s = tab.js(STATE)
    t = load(tab, '/install/')
    check('«English» chosen there -> /about/ without the parameter, and the general addresses stay English', s['url'] == '/about/' and s['saved'] == 'en' and t['url'] == '/install/', (s, t))
    tab.call('Page.close')
finally:
    if chrome is not None:
        chrome.stop()
    server.terminate()
    try:
        server.wait(10)
    except subprocess.TimeoutExpired:
        server.kill()

bad = [name for name, ok in results if not ok]
print('\n%d checks, %d failed' % (len(results), len(bad)))
sys.exit(1 if bad else 0)
