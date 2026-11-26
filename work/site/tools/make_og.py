# -*- coding: utf-8 -*-
"""The picture a link to the site shows in a chat or a feed (og:image), 1200 x 630, one per language: the main
page's headline and the step list on the page's dark background. It is drawn by a browser from the site's own
picture, with the site's own colours and type, and saved as PNG.

    python -X utf8 make_og.py <project> <work dir> [debug port]

One picture for every language that has its list picture (site/assets/list-<code>.webp) and its headline. The headline
comes from the sources, so the picture can be made before the language's pages are built: the Russian one is the
sample's <h1> (work/site/src/sample/index.html), any other — its translation in work/site/src/overview.<code>.json.
A headline too long for the picture is set smaller until it fits."""
import html
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cdp import Chrome  # noqa: E402

project, work = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
port = int(sys.argv[3]) if len(sys.argv) > 3 else 4759
SITE, SRC = project / 'site', project / 'work' / 'site' / 'src'
TAGS = {'pt': 'pt-BR'}
m = re.search(r'<h1>(.*?)</h1>', (SRC / 'sample' / 'index.html').read_text(encoding='utf-8'), re.S)
HEAD = ' '.join(html.unescape(re.sub(r'<[^>]+>', '', m.group(1))).split())           # the sample's headline, Russian
TITLES = {}
for picture in sorted((SITE / 'assets').glob('list-*.webp')):
    code = picture.stem.split('-', 1)[1]
    table = SRC / ('overview.%s.json' % code)
    if code == 'ru':
        TITLES[code] = HEAD
    elif table.is_file() and json.loads(table.read_text(encoding='utf-8')).get(HEAD):
        TITLES[code] = json.loads(table.read_text(encoding='utf-8'))[HEAD]
    else:
        print('og-%s.png  not made: no headline yet (work/site/src/overview.%s.json)' % (code, code))

DOC = """<!doctype html><html lang="{lang}"><head><meta charset="utf-8"><style>
*{{box-sizing:border-box}}
html,body{{margin:0;width:1200px;height:630px;overflow:hidden;background:#08090b;color:#f5f5f7;
  font:17px/1.47 "Segoe UI Variable Text","Segoe UI",system-ui,sans-serif;-webkit-font-smoothing:antialiased}}
body{{position:relative}}
body::before{{content:"";position:absolute;left:50%;bottom:-150px;width:1180px;height:520px;transform:translateX(-50%);
  background:radial-gradient(closest-side,rgba(92,150,255,.34),rgba(92,150,255,.1) 55%,transparent 78%)}}
.b{{position:absolute;left:56px;top:40px;display:flex;align-items:center;gap:12px;font-size:24px;font-weight:600;letter-spacing:-.01em}}
.b img{{width:40px;height:40px}}
h1{{position:absolute;left:0;right:0;top:128px;margin:0;text-align:center;white-space:nowrap;
  font-family:"Segoe UI Variable Display","Segoe UI",system-ui,sans-serif;font-size:{size}px;font-weight:600;line-height:1.04;letter-spacing:-.03em}}
.l{{position:absolute;left:150px;top:286px;width:900px;border-radius:10px;box-shadow:0 0 0 1px rgba(127,178,255,.6),0 30px 90px rgba(0,0,0,.85)}}
</style></head><body>
<div class="b"><img src="{icon}" alt="">PoE2 Runbook</div>
<h1><span>{title}</span></h1>
<img class="l" src="{list}" alt="">
</body></html>
"""

chrome = Chrome(str(work / 'chrome-profile'), port)
try:
    tab = chrome.tab()
    for lang, title in TITLES.items():
        for size in (84, 74, 66, 58, 52, 46, 40):
            doc = DOC.format(lang=TAGS.get(lang, lang), title=html.escape(title), size=size,
                             icon=(SITE / 'assets' / 'icon.png').as_uri(),
                             list=(SITE / 'assets' / ('list-%s.webp' % lang)).as_uri())
            src = work / ('og-%s.html' % lang)
            src.write_text(doc, encoding='utf-8')
            tab.size(1200, 630, scale=1, dark=True)
            tab.go(src.as_uri())
            tab.wait("document.readyState === 'complete' && [...document.images].every(i => i.complete && i.naturalWidth > 0)", 30)
            time.sleep(0.6)
            if tab.js("document.querySelector('h1 span').getBoundingClientRect().width <= 1080"):
                break
        else:
            raise SystemExit('og-%s.png: the headline «%s» does not fit even at 40 px' % (lang, title))
        out = SITE / 'assets' / ('og-%s.png' % lang)
        n = tab.shot(out, clip={'x': 0, 'y': 0, 'width': 1200, 'height': 630})
        print('og-%s.png  %d bytes  «%s» at %d px' % (lang, n, title, size))
finally:
    chrome.stop()
