# -*- coding: utf-8 -*-
"""Whole-page pictures of the site (it has one theme, dark) and, for every page of every language at 1280 and 390,
what it requested, what the console said, whether it scrolls sideways, how tall it is and how many words it shows.
Pictures kept: the main page of every language at both widths; the inner pages of Russian and English at both widths
(the other languages' inner pages are measured, not kept). The Russian and English main pages are also cut into screens of 1280 x 800, the way
a visitor meets them. The languages are the ones the site's own header lists.

    python -X utf8 site_shots.py <base url> <out dir> <chrome profile dir> [debug port]"""
import json
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cdp import Chrome  # noqa: E402

base, out, profile = sys.argv[1].rstrip('/'), Path(sys.argv[2]), sys.argv[3]
port = int(sys.argv[4]) if len(sys.argv) > 4 else 4759
host = urlsplit(base).netloc
PAGES = ('overview', 'safety', 'install', 'about')
PATH = {'overview': '', 'safety': 'safety/', 'install': 'install/', 'about': 'about/'}
SIZES = ((1280, 800), (390, 844))
READY = "document.readyState === 'complete' && document.documentElement.classList.contains('dl-done')"
LOAD_ALL = """(async function () {
  for (const img of document.images) { img.loading = 'eager'; }
  await Promise.all([...document.images].map(i => i.decode().catch(() => null)));
  return document.images.length;
})()"""
MEASURE = """(function(){var words = function (s) { return s.split(/\\s+/).filter(function (w) { return /[\\p{L}\\p{N}]/u.test(w); }).length; };
  var d = document.documentElement, main = document.querySelector('main'), tpl = document.querySelector('template');
  return {sw: d.scrollWidth, cw: d.clientWidth, h: d.scrollHeight, lang: d.lang, bg: getComputedStyle(document.body).backgroundColor,
    words: words(main.innerText), page: words(document.body.innerText),
    allWords: words(main.textContent.replace(tpl ? tpl.textContent : '', '')),
    wide: [...document.querySelectorAll('body *')].filter(function (e) { return e.getBoundingClientRect().right > d.clientWidth + 0.5 && getComputedStyle(e.parentElement).overflowX === 'visible'; })
      .map(function (e) { return e.tagName + '.' + (e.className.baseVal === undefined ? e.className : e.className.baseVal); }).slice(0, 6)}})()"""

out.mkdir(parents=True, exist_ok=True)
for old in out.glob('*.png'):
    old.unlink()
chrome = Chrome(profile, port)
report = []
try:
    tab = chrome.tab()
    tab.go(base + '/?lang=en')
    tab.wait(READY, 30)
    LANGS = tab.js("[...document.querySelectorAll('.langs-menu > *')].map(e => e.getAttribute('data-lang') || 'en')")
    tab.call('Page.close')
    print('languages of the site:', ' '.join(LANGS))
    for page in PAGES:
        for lang in LANGS:
            # the English page by the link that asks for English by name: the browser here may be anyone's
            path = ('/' if lang == 'en' else '/%s/' % lang) + PATH[page] + ('?lang=en' if lang == 'en' else '')
            for width, height in SIZES:
                tab = chrome.tab()
                tab.size(width, height, scale=2 if width < 500 else 1, mobile=width < 500, dark=True)
                tab.go(base + path)
                tab.wait(READY, 30)
                tab.js(LOAD_ALL)
                time.sleep(0.4)
                tab.pump(0.6)
                name = '%s-%s-%d.png' % (page, lang, width)
                keep = page == 'overview' or lang in ('ru', 'en')
                size = tab.shot(out / name, full=True) if keep else 0
                m = tab.js(MEASURE)
                urls = [e['params']['request']['url'] for e in tab.events if e.get('method') == 'Network.requestWillBeSent']
                foreign = sorted({u for u in urls if urlsplit(u).netloc != host and not u.startswith('data:')})
                failed = [(e['params']['response']['status'], urlsplit(e['params']['response']['url']).path)
                          for e in tab.events if e.get('method') == 'Network.responseReceived'
                          and e['params']['response']['status'] >= 400]
                thrown = [e['params'] for e in tab.events if e.get('method') == 'Runtime.exceptionThrown']
                logs = [(e['params']['type'], ' '.join(str(a.get('value', a.get('description', ''))) for a in e['params']['args'])[:160])
                        for e in tab.events if e.get('method') == 'Runtime.consoleAPICalled']
                row = {'page': name, 'bytes': size, 'requests': len(urls), 'foreign': foreign, 'failed': failed,
                       'exceptions': len(thrown), 'console': logs, 'scrollsSideways': m['sw'] > m['cw'], 'wide': m['wide'],
                       'height': m['h'], 'screens': round(m['h'] / height, 1),
                       'words': m['words'], 'pageWords': m['page'], 'allWords': m['allWords'], 'lang': m['lang'], 'bg': m['bg']}
                report.append(row)
                print(json.dumps(row, ensure_ascii=False))
                if page == 'overview' and width == 1280 and lang in ('ru', 'en'):
                    # the main page as a visitor meets it: one screen of 800 after another
                    n = 0
                    while n * height < m['h']:
                        tab.js('window.scrollTo(0, %d)' % (n * height))
                        time.sleep(0.35)
                        n += 1
                        tab.shot(out / ('overview-%s-screen-%d.png' % (lang, n)))
                tab.call('Page.close')
finally:
    chrome.stop()
(out / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')
bad = [r['page'] for r in report if r['foreign'] or r['exceptions'] or r['scrollsSideways']
       or [f for f in r['failed'] if f[1] not in ('/update/latest.json', '/plans/index.json')]]
print('\n%d pages measured, %d pictures kept, %d with a problem%s' % (
    len(report), len([r for r in report if r['bytes']]), len(bad), ': ' + ', '.join(bad) if bad else ''))
sys.exit(1 if bad else 0)
