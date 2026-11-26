# -*- coding: utf-8 -*-
"""The main page against its sample: every block's place, size, type and words, at the widths the sample was looked
at, and both pages side by side screen after screen.

    python -X utf8 compare_mock.py <project> <base url> <overlay dir of serve.py> <out dir> <chrome profile> [debug port] [--live]

Which sample: by default the version the site was built from (work/site/src/sample/); with --live — the sample
folder as it is now (work/site/mock/), to see how far it has moved since.

Nothing about the sample's make-up is written here: both pages are walked the same way — every heading, paragraph,
picture, link, button and question that is seen, in the order of the page — and the two lists are compared item by
item. So the tool keeps working when the sample changes. The site's page is compared in the state the sample draws:
a build is published (the overlay gets an update/latest.json with the version, date and size the sample names).
Each difference is printed; nothing is changed."""
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cdp import Chrome  # noqa: E402

project, base, overlay, out, profile = Path(sys.argv[1]).resolve(), sys.argv[2].rstrip('/'), Path(sys.argv[3]), Path(sys.argv[4]), sys.argv[5]
live = '--live' in sys.argv[6:]
port = next((int(a) for a in sys.argv[6:] if a.isdigit()), 4759)
MOCK_FILE = project / 'work' / 'site' / ('mock' if live else 'src/sample') / 'index.html'
MOCK, SITE = MOCK_FILE.as_uri(), base + '/ru/'
WIDTHS = ((1280, 800), (500, 844), (390, 844))
MEASURE = """(async function () {
  for (const i of document.images) i.loading = 'eager';
  await Promise.all([...document.images].map(i => i.decode().catch(() => null)));
  const flat = s => s.replace(/\\s+/g, ' ').trim();
  const seen = e => e.getClientRects().length > 0 && getComputedStyle(e).visibility !== 'hidden' &&
    !(e.tagName !== 'SUMMARY' && e.closest('details:not([open])'));      // what a closed question or menu holds is not seen
  const what = 'header a, header summary, main h1, main h2, main h3, main p, main img, main summary, main b.pn, footer p, footer a';
  const items = [...document.querySelectorAll(what)].filter(seen).map(e => {
    const r = e.getBoundingClientRect(), s = getComputedStyle(e);
    return {tag: e.tagName.toLowerCase(), x: r.left + scrollX, y: r.top + scrollY, w: r.width, h: r.height, size: s.fontSize, weight: s.fontWeight,
      color: s.color, family: s.fontFamily.split(',')[0], text: e.tagName === 'IMG' ? '' : flat(e.innerText),
      alt: e.tagName === 'IMG' ? flat(e.getAttribute('alt') || '') : ''};
  });
  return {height: document.documentElement.scrollHeight, items: items, title: document.title,
    // an answer's words as a reader gets them once it is opened: what the page keeps hidden for another state is not among them
    answers: [...document.querySelectorAll('main details')].map(d => { const c = d.cloneNode(true); c.querySelectorAll('[hidden]').forEach(e => e.remove());
      return flat(c.querySelector('summary').textContent) + ' — ' + flat([...c.children].slice(1).map(e => e.textContent).join(' ')); })};
})()"""

# the state the sample draws: its version, date and size
mock_text = MOCK_FILE.read_text(encoding='utf-8')
good = json.loads((project / 'site' / 'update' / 'latest.example.json').read_text(encoding='utf-8'))
version = re.search(r'(\d+\.\d+\.\d+\.\d+)', mock_text)
if version:
    good['version'] = version.group(1)
(overlay / 'update').mkdir(parents=True, exist_ok=True)
(overlay / 'update' / 'latest.json').write_text(json.dumps(good), encoding='utf-8')
out.mkdir(parents=True, exist_ok=True)
chrome = Chrome(profile, port)
total = 0
try:
    from PIL import Image
    for width, height in WIDTHS:
        got = {}
        for name, url in (('mock', MOCK), ('site', SITE)):
            tab = chrome.tab()
            tab.size(width, height, scale=1, mobile=width < 600, dark=True)
            tab.go(url)
            tab.wait("document.readyState === 'complete'" + (" && document.documentElement.classList.contains('dl-done')" if name == 'site' else ''), 30)
            time.sleep(0.8)
            got[name] = tab.js(MEASURE)
            tall, n = got[name]['height'], 0
            while n * height < tall:
                tab.js('window.scrollTo(0, %d)' % (n * height))
                time.sleep(0.35)
                n += 1
                tab.shot(out / ('%s-%d-%d.png' % (name, width, n)))
            got[name]['screens'] = n
            tab.call('Page.close')
        m, s = got['mock'], got['site']
        diffs = []
        if abs(m['height'] - s['height']) > 2:
            diffs.append('page height: sample %d, site %d' % (m['height'], s['height']))
        if len(m['items']) != len(s['items']):
            diffs.append('the sample shows %d things, the site %d: %s / %s' % (
                len(m['items']), len(s['items']), [i['tag'] + ':' + (i['text'] or i['alt'])[:18] for i in m['items']],
                [i['tag'] + ':' + (i['text'] or i['alt'])[:18] for i in s['items']]))
        for a, b in zip(m['items'], s['items']):
            name = '%s «%s»' % (a['tag'], (a['text'] or a['alt'] or 'picture')[:36])
            for key, tol in (('x', 1.5), ('y', 2.0), ('w', 1.5), ('h', 2.0)):
                if abs(a[key] - b[key]) > tol:
                    diffs.append('%s: %s %.1f in the sample, %.1f on the site' % (name, key, a[key], b[key]))
            for key in ('tag', 'size', 'weight', 'color', 'family', 'text', 'alt'):
                if a[key] != b[key]:
                    diffs.append('%s: %s «%s» in the sample, «%s» on the site' % (name, key, a[key], b[key]))
        if m['answers'] != s['answers']:
            for n, (a, b) in enumerate(zip(m['answers'], s['answers']), 1):
                if a != b:
                    diffs.append('question %d: «%s» in the sample, «%s» on the site' % (n, a, b))
            if len(m['answers']) != len(s['answers']):
                diffs.append('questions: %d in the sample, %d on the site' % (len(m['answers']), len(s['answers'])))
        if width == WIDTHS[0][0] and m['title'] != s['title']:
            diffs.append('title: «%s» / «%s»' % (m['title'], s['title']))
        print('%d x %d: sample %d px, site %d px, %d screens, %d things compared — %d difference(s)' % (
            width, height, m['height'], s['height'], s['screens'], min(len(m['items']), len(s['items'])), len(diffs)))
        for d in diffs:
            print('   ', d)
        total += len(diffs)
        # both pages side by side, screen after screen: the sample on the left
        for n in range(1, max(m['screens'], s['screens']) + 1):
            pair = [out / ('%s-%d-%d.png' % (name, width, n)) for name in ('mock', 'site')]
            ims = [Image.open(p).convert('RGB') if p.is_file() else Image.new('RGB', (width, height), (40, 0, 0)) for p in pair]
            both = Image.new('RGB', (width * 2 + 12, height), (60, 60, 60))
            both.paste(ims[0], (0, 0))
            both.paste(ims[1], (width + 12, 0))
            both.save(out / ('compare-%d-%d.png' % (width, n)))
            for p in pair:
                if p.is_file():
                    p.unlink()
finally:
    chrome.stop()
    (overlay / 'update' / 'latest.json').unlink()
print('\n%d difference(s) in all with %s' % (total, MOCK_FILE.parent))
