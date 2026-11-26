# -*- coding: utf-8 -*-
"""Is a language's set of texts complete and shaped like the Russian one? Run after translating, before the build.

    python -X utf8 check_lang.py <project> <language code> [<language code> …]

A language's texts (all in work/site/src):
  words.<code>.json                     the shell's words and the inner pages' titles — the same keys as words.ru.json
  overview.<code>.json                  the main page: {"Russian piece of the sample": "translation"} for every piece
  safety|install|about.<code>.html      the inner pages — the Russian fragments with the text translated
What is checked: nothing is missing; the fragments keep the Russian ones' markup tag for tag (ids, classes, links,
marks); placeholders {version} {n} {link} and the «·» lines of the main page keep their shape; every {{ui Слово}} mark
names a word the program really has in that language; no Russian text is left. Writes nothing."""
import json
import re
import subprocess
import sys
from pathlib import Path

project = Path(sys.argv[1]).resolve()
SRC = project / 'work' / 'site' / 'src'
SOURCE = 'ru'
PAGES = ('safety', 'install', 'about')
TEXT_ATTRS = ('data-t-button', 'data-t-mb', 'data-t-bytes', 'data-done', 'data-on', 'alt', 'aria-label', 'title')
units = json.loads(subprocess.run([sys.executable, '-X', 'utf8', str(Path(__file__).with_name('build_site.py')), str(project), '--units'],
                                  capture_output=True, text=True, encoding='utf-8', check=True).stdout)


def skeleton(fragment):
    """The fragment's tags in order, with the values of the attributes that hold text taken out."""
    out = []
    for tag in re.findall(r'<[^>]+>', fragment):
        for attr in TEXT_ATTRS:
            tag = re.sub(r'(\s%s=")[^"]*(")' % attr, r'\1…\2', tag)
        out.append(tag)
    return out


def marks(text, ui):
    found = re.findall(r'\{\{([^{}]+)\}\}', text)
    return sorted(m.strip() for m in found if m.strip().startswith('ui ') == ui)


def holders(text):
    return sorted(re.findall(r'\{(?:version|game|date|size|n|link)\}', text))


def cyrillic(text):
    return re.findall(r'[А-Яа-яЁё]+', re.sub(r'\{\{[^{}]+\}\}', '', text))


def check(code):
    bad = []
    lang_file = project / 'planner' / 'lang' / ('%s.json' % code)
    if not lang_file.is_file():
        return ['the program has no language «%s» (planner/lang)' % code]
    ui = json.loads(lang_file.read_text(encoding='utf-8')).get('texts') or {}

    def ui_ok(text, where):
        for m in marks(text, True):
            if code != SOURCE and m[3:].strip() not in ui:
                bad.append('%s: {{%s}} — the program has no such word in this language' % (where, m))

    # --- words and titles ---
    base = json.loads((SRC / ('words.%s.json' % SOURCE)).read_text(encoding='utf-8'))
    path = SRC / ('words.%s.json' % code)
    if not path.is_file():
        bad.append('no words.%s.json' % code)
    else:
        own = json.loads(path.read_text(encoding='utf-8'))
        for key, value in base['words'].items():
            got = (own.get('words') or {}).get(key)
            if not got:
                bad.append('words.%s.json: no word «%s»' % (code, key))
            elif holders(got) != holders(value):
                bad.append('words.%s.json: «%s» — placeholders %s, the Russian has %s' % (code, key, holders(got), holders(value)))
            elif code != SOURCE and cyrillic(got):
                bad.append('words.%s.json: «%s» — Russian text left: %s' % (code, key, cyrillic(got)))
            else:
                ui_ok(got, 'words.%s.json «%s»' % (code, key))
        for page in PAGES:
            for key in ('title', 'og_title', 'description'):
                got = ((own.get('titles') or {}).get(page) or {}).get(key)
                if not got:
                    bad.append('words.%s.json: no %s of «%s»' % (code, key, page))
                elif code != SOURCE and cyrillic(got):
                    bad.append('words.%s.json: %s of «%s» — Russian text left' % (code, key, page))
    # --- the main page ---
    if code != SOURCE:
        path = SRC / ('overview.%s.json' % code)
        if not path.is_file():
            bad.append('no overview.%s.json' % code)
        else:
            table = json.loads(path.read_text(encoding='utf-8'))
            for unit in units:
                got = table.get(unit)
                if not got or not got.strip():
                    bad.append('overview.%s.json: no translation of «%s»' % (code, unit))
                    continue
                if cyrillic(got):
                    bad.append('overview.%s.json: Russian text left in «%s»' % (code, got))
                ui_ok(got, 'overview.%s.json' % code)
                if ' · ' in unit and re.search(r'\d', unit):                # the two lines site.js fills: version, release
                    if len(got.split(' · ')) != len(unit.split(' · ')) or re.findall(r'\d+(?:\.\d+)+', got) != re.findall(r'\d+(?:\.\d+)+', unit):
                        bad.append('overview.%s.json: «%s» must keep the parts between « · » and the version numbers of «%s»' % (code, got, unit))
                    if 'Windows' in unit and 'Windows' not in got.split(' · ')[2]:
                        bad.append('overview.%s.json: the third part of the release line must name Windows: «%s»' % (code, got))
            extra = [k for k in table if k not in units]
            if extra:
                bad.append('overview.%s.json: %d key(s) that are not pieces of the sample (a changed sentence?): %s' % (code, len(extra), extra[:3]))
    # --- the inner pages ---
    for page in PAGES:
        src = (SRC / ('%s.%s.html' % (page, SOURCE))).read_text(encoding='utf-8')
        path = SRC / ('%s.%s.html' % (page, code))
        if not path.is_file():
            bad.append('no %s.%s.html' % (page, code))
            continue
        own = path.read_text(encoding='utf-8')
        if code == 'en':
            # the rule quoted on the reads page is English: the English page has the quote alone, the others — the quote
            # and how it reads in their language
            src, own = (re.sub(r'<blockquote>.*?</blockquote>', '<blockquote/>', t, flags=re.S) for t in (src, own))
        a, b = skeleton(src), skeleton(own)
        if a != b:
            n = next((i for i, (x, y) in enumerate(zip(a, b)) if x != y), min(len(a), len(b)))
            bad.append('%s.%s.html: the markup differs from the Russian fragment at tag %d of %d: «%s» there, «%s» here'
                       % (page, code, n + 1, len(a), a[n] if n < len(a) else '(end)', b[n] if n < len(b) else '(end)'))
        if marks(src, False) != marks(own, False):
            bad.append('%s.%s.html: marks %s, the Russian has %s' % (page, code, marks(own, False), marks(src, False)))
        for attr in ('data-t-button', 'data-t-mb', 'data-t-bytes'):
            x, y = re.search(r'%s="([^"]*)"' % attr, src), re.search(r'%s="([^"]*)"' % attr, own)
            if x and (not y or holders(x.group(1)) != holders(y.group(1))):
                bad.append('%s.%s.html: %s must keep %s' % (page, code, attr, holders(x.group(1))))
        ui_ok(own, '%s.%s.html' % (page, code))
        if code != SOURCE and cyrillic(re.sub(r'<[^>]+>', ' ', own)):
            bad.append('%s.%s.html: Russian text left: %s' % (page, code, cyrillic(re.sub(r'<[^>]+>', ' ', own))[:8]))
    return bad


failed = 0
for code in sys.argv[2:]:
    problems = check(code)
    failed += bool(problems)
    print('%s: %s' % (code, 'complete, shaped like the Russian texts' if not problems else '%d problem(s)' % len(problems)))
    for p in problems:
        print('  ' + p)
sys.exit(1 if failed else 0)
