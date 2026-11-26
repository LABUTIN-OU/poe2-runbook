# -*- coding: utf-8 -*-
"""The site's pages are built here: site/[<language>/][<page>/]index.html — four pages for every language of the
program that has its texts — and site/assets/site.css, from work/site/src.

    python -X utf8 build_site.py <project>                  write the pages
    python -X utf8 build_site.py <project> --take           first take the live sample (work/site/mock) as the version the
                                                            site stands on, naming what changed in its text; then write
    python -X utf8 build_site.py <project> --check          change nothing; say what in site/ differs from the sources
    python -X utf8 build_site.py <project> --trial <dir>    ALL the program's languages, into <dir> and not into site/:
                                                            what a language still lacks is borrowed from English.
                                                            For looking at addresses and the header's list before a
                                                            language's texts exist (serve.py lays <dir> over site/)
    python -X utf8 build_site.py <project> --units          print the pieces of the sample's text a translator of the
                                                            main page has to translate

LANGUAGES. Which languages there are, their own names and number formats is read from the program
(planner/lang/*.json), in the program's order. English stands at the site's root — the general address; every other
language in its folder (/ru/, /de/, /pt/ …). A language is on the site when it has everything: the shell's words and
page titles (src/words.<code>.json), the three inner pages (src/<page>.<code>.html), the main page, the pictures. A language
that lacks something is named in the output with what it lacks, and is not on the site at all: no address, no line in
the header's list.

THE MAIN PAGE IS THE SAMPLE. Its words are kept nowhere else. The Russian main page is the <main> of
src/sample/index.html (the version of work/site/mock/ the site stands on) with the live parts put in:
  links to the installer -> the install page (site.js sends them straight to the file once a build is published);
  the line under the first button and the release block -> templates that site.js fills from update/latest.json;
  the sample's pictures -> the site's own shots of the same things (PICS); its «#» links -> real addresses (LINKS);
  the section «Готовые планы» (src/plans.html, hidden until the catalogue has a plan) before the authors' band.
site/404.html is built as well (src/404.html): it links the first page of every language that is on the site.
A picture or a link the sample has and this file does not know stops the build: it has to be given a shot or an address.
Title, description and the link picture's description of the main page are the sample's too (<title>, the sentence
under the headline, the first picture's description).
Any other language is the same page with every piece of text replaced through its table src/overview.<code>.json
{"Russian text": "translation"}: a sentence that changed in the sample has no translation any more, and the build
names it. Until a language has its table, a fragment kept from an earlier sample (src/overview.<code>.html) stands in;
the output says so.

The stylesheet is built too: site/assets/site.css = the sample's mock.css as it is + src/extra.css.

Marks in fragments and in the shell:
  {{root}}                                   path to the site's root from the page ('' | '../' | '../../')
  {{overview}} {{safety}} {{install}} {{about}}   path to that page in the same language
  {{img file.webp}}                          src, width and height of a picture from site/assets (its real size)
  {{pic list}}                               the same for a shot of the program in the page's language (list-<code>.webp)
  {{w key}}                                  a word of the shell in the page's language (words.<code>.json)
  {{ui Слово программы}}                     how the program itself names the thing in the page's language (its lang file)
  {{program_langs}}                          the program's languages by their own names, in its order
A space before a dash is made non-breaking in every page, so that no line begins with a dash.
Every page must come out without a mark left, without inline styles or scripts (the pages' Content-Security-Policy
forbids them), and every local link and anchor in it must lead somewhere: the build stops otherwise."""
import html as htmllib
import json
import posixpath
import re
import shutil
import sys
from pathlib import Path

project = Path(sys.argv[1]).resolve()
ARGS = sys.argv[2:]
check = '--check' in ARGS
trial = Path(ARGS[ARGS.index('--trial') + 1]).resolve() if '--trial' in ARGS else None
SRC, SITE = project / 'work' / 'site' / 'src', project / 'site'
OUT = trial or SITE
SAMPLE = SRC / 'sample'
CSS_HEAD = ('/* PoE2 Runbook — сайт программы. Этот файл собран (work/site/tools/build_site.py): первая часть — стили образца\n'
            '   главной слово в слово (work/site/src/sample/mock.css), вторая — своё (work/site/src/extra.css). Правится там, не здесь.\n'
            '   Тема одна — тёмная. Ни одного файла с других сайтов. */\n')
ORIGIN = 'https://poe2.labutin.gg/'
GENERAL = 'en'                                        # the language of the general address (the site's root)
SOURCE = 'ru'                                         # the language the sample is written in
TAGS = {'pt': 'pt-BR'}                                # the program's Portuguese is the Brazilian one: its name and number format say so
# the sample's picture -> the site's shot of the same thing (make_shots.py takes them, pack_shots.py packs them)
PICS = {'shot-list-ru.webp': 'list', 'window-ru.png': 'window', 'late-ru.png': 'late', 'shot-answer-ru.webp': 'answer',
        'tiles-ru.png': 'tiles', 'f-time-ru.webp': 'time', 'f-plan-ru.webp': 'plan'}
PICTURES = ('list', 'window', 'late', 'answer', 'tiles', 'time', 'plan')
# a «#» link of the sample (by its text) -> where it leads on the site: (the link's attributes, what stands after it)
LINKS = {'Как добавить план в каталог': ('href="{{about}}#catalogue"', ''),
         'Как установить': ('href="{{install}}"', ''),
         'Как сверить файл перед запуском': ('href="{{install}}#verify"', ''),
         # The address is a setting (assets/config.js): site.js puts it into the link and shows it; the words stay.
         # Beside it — a link to the repository's issues, shown only when that address is set too (the repository is open).
         'Написать автору': ('href="{{about}}#contact" data-contact data-contact-keep data-contact-row hidden',
                             '<span data-issues-row hidden> · <a data-issues href="{{about}}#contact" rel="noopener noreferrer">{{w issues}}</a></span>')}

conf = json.loads((SRC / 'pages.json').read_text(encoding='utf-8'))
layout = (SRC / 'layout.html').read_text(encoding='utf-8')
PAGES = conf['pages']
# a language's words: src/words.<code>.json = {"words": the shell's words, "titles": {page: title, og_title, description}}
conf['words'] = {}
for _file in sorted(SRC.glob('words.*.json')):
    _code, _own = _file.name.split('.')[1], json.loads(_file.read_text(encoding='utf-8'))
    conf['words'][_code] = _own.get('words') or {}
    for _page in PAGES:
        if _page['id'] in (_own.get('titles') or {}):
            _page[_code] = _own['titles'][_page['id']]
notes = []
TAG = re.compile(r'(<[^>]+>)')
ALT = re.compile(r'(\salt=")([^"]+)(")')


def stop(text):
    raise SystemExit(text)


def squeeze(text):
    return ' '.join(text.split())


def units(fragment):
    """Every piece of text of a fragment, in page order: the text between tags and the pictures' descriptions."""
    out = []
    for part in TAG.split(fragment):
        if part.startswith('<'):
            out += [m.group(2) for m in ALT.finditer(part)]
        elif part.strip():
            out.append(squeeze(part))
    return out


if '--take' in ARGS:
    # the live sample (work/site/mock) becomes the version the site stands on; what changed in its text is named
    LIVE = project / 'work' / 'site' / 'mock'
    was = units((SAMPLE / 'index.html').read_text(encoding='utf-8')) if (SAMPLE / 'index.html').is_file() else []
    now = units((LIVE / 'index.html').read_text(encoding='utf-8'))
    for name in ('index.html', 'mock.css'):
        shutil.copyfile(LIVE / name, SAMPLE / name)
    if (SAMPLE / 'img').is_dir():
        shutil.rmtree(SAMPLE / 'img')
    shutil.copytree(LIVE / 'img', SAMPLE / 'img')
    print('the sample is taken from work/site/mock: %d piece(s) of text gone, %d new' % (
        len([u for u in was if u not in now]), len([u for u in now if u not in was])))
    for u in was:
        if u not in now:
            print('  - ' + u)
    for u in now:
        if u not in was:
            print('  + ' + u)


def program_languages():
    """The program's interface languages in its own order (planner/i18n.languages): English, Russian, then by code."""
    found = {}
    for path in sorted((project / 'planner' / 'lang').glob('*.json')):
        if path.stem == 'raw' or not re.fullmatch(r'[a-z]{2,3}(-[A-Za-z]{2,4})?', path.stem):
            continue
        d = json.loads(path.read_text(encoding='utf-8'))
        code = path.stem
        found[code] = {'code': code, 'name': d.get('name') or code, 'locale': d.get('locale') or code,
                       'texts': d.get('texts') or {}, 'tag': TAGS.get(code, code),
                       'dir': '' if code == GENERAL else code + '/'}
    order = {GENERAL: 0, SOURCE: 1}
    return [found[c] for c in sorted(found, key=lambda c: (order.get(c, 2), c))]


def rel(here, there):
    """Path from the page folder «here» to the folder «there» (both from the site's root, '' or 'a/b/')."""
    path = posixpath.relpath('/' + there, '/' + here)
    return './' if path == '.' else path + '/'


def asset(name):
    """A file of site/assets (in a trial build — of the trial folder first)."""
    for folder in ((OUT, SITE) if trial else (SITE,)):
        if (folder / 'assets' / name).is_file():
            return folder / 'assets' / name
    return None


def picture(name):
    from PIL import Image
    path = asset(name)
    if not path:
        stop('no picture site/assets/%s (pack_shots.py makes them)' % name)
    with Image.open(path) as im:
        return im.size


def fill(text, values, where):
    def put(m):
        key = m.group(1).strip()
        if key.startswith('img '):
            name = key[4:].strip()
            return 'src="%sassets/%s" width="%d" height="%d"' % ((values['root'], name) + picture(name))
        if key.startswith('pic '):
            name = '%s-%s.webp' % (key[4:].strip(), values['pictures'])
            return 'src="%sassets/%s" width="%d" height="%d"' % ((values['root'], name) + picture(name))
        if key.startswith('w '):
            if key[2:].strip() not in values['w']:
                stop('%s: no word «%s» in words.%s.json' % (where, key[2:].strip(), values['code']))
            return values['w'][key[2:].strip()]
        if key.startswith('ui '):
            return ui(key[3:].strip(), values['language'], where)
        if key not in values:
            stop('%s: unknown mark {{%s}}' % (where, key))
        return values[key]
    return re.sub(r'\{\{([^{}]+)\}\}', put, text)


def ui(word, lang, where):
    """How the program names its own thing in a language: the program's language file knows (Russian is its source)."""
    if lang['code'] == SOURCE:
        return word
    if word not in lang['texts']:
        stop('%s: the program has no word «%s» in %s (planner/lang/%s.json)' % (where, word, lang['name'], lang['code']))
    return lang['texts'][word]


def words(lang):
    """The shell's words of a language; a {{ui …}} mark inside a word is the program's own name of a thing."""
    table = conf['words'].get(lang['code'])
    if table is None:
        return None
    return {k: re.sub(r'\{\{ui ([^{}]+)\}\}', lambda m: ui(m.group(1).strip(), lang, 'words.%s.json' % lang['code']), v) for k, v in table.items()}


# --- the main page out of the sample --------------------------------------------------------------------------------
def sample():
    page = (SAMPLE / 'index.html').read_text(encoding='utf-8')
    main = re.search(r'<main id="top">\n(.*?)\n</main>', page, re.S)
    title = re.search(r'<title>([^<]+)</title>', page)
    if not main or not title:
        stop('src/sample/index.html: no <main id="top"> or no <title>')
    return squeeze(title.group(1)), main.group(1).strip('\n')


def hooked(main):
    """The sample's <main> with addresses and the site's own pictures instead of the sample's stand-ins."""
    main, n = re.subn(r'href="https://github\.com/[^"]+\.exe"', 'href="{{install}}#download" data-dl-link', main)
    if n != 2:
        stop('the sample: %d links to the installer inside <main>, 2 expected (first screen, release block)' % n)

    def link(m):
        if m.group(1) not in LINKS:
            stop('the sample has a link «%s» that leads nowhere yet: name its address in LINKS (build_site.py)' % m.group(1))
        return '<a %s>%s</a>%s' % (LINKS[m.group(1)][0], m.group(1), LINKS[m.group(1)][1])
    main = re.sub(r'<a href="#">([^<]+)</a>', link, main)
    if 'href="#"' in main:
        stop('the sample: a link with href="#" of a shape the build does not know')
    seen = []

    def pic(m):
        if m.group(1) not in PICS:
            stop('the sample shows a picture %s the site has no shot for: name it in PICS (build_site.py)' % m.group(1))
        lazy = ' loading="lazy" decoding="async"' if seen else ''      # the first one is on the first screen
        seen.append(PICS[m.group(1)])
        return '<img {{pic %s}}%s alt="%s">' % (seen[-1], lazy, m.group(2))
    main = re.sub(r'<img src="img/([^"]+)" width="\d+" height="\d+" alt="([^"]*)">', pic, main)
    if '<img src=' in main:
        stop('the sample: a picture written in a way the build does not know')
    return main


def own(unit):
    """A piece with no word of the sample's language in it (a name, a version) reads the same in every language."""
    return not re.search('[А-Яа-яЁё]', unit)


def translated(fragment, table):
    def word(unit):
        return unit if own(unit) and unit not in table else table[unit]
    out = []
    for part in TAG.split(fragment):
        if part.startswith('<'):
            out.append(ALT.sub(lambda m: m.group(1) + word(m.group(2)) + m.group(3), part))
        elif part.strip():
            body = part.strip()
            out.append(part[:part.index(body[0])] + word(squeeze(part)) + part[len(part.rstrip()):])
        else:
            out.append(part)
    return ''.join(out)


def live(main, w):
    """The two places that name the current build become templates: site.js fills them from update/latest.json.
    Without a published build (and without JavaScript) the page says only what is true in every state."""
    def one(pattern, what):
        found = re.findall(pattern, main)
        if len(found) != 1:
            stop('the sample: %s — %d found, 1 expected' % (what, len(found)))
        return re.search(pattern, main)

    def numbered(text, pattern, mark, what):
        out, n = re.subn(pattern, mark, text, count=1)
        if not n:
            stop('the sample: no %s in «%s»' % (what, text))
        return out
    fine = one(r'<p class="fine">([^<]+)</p>', 'the line under the first button')
    line = numbered(numbered(fine.group(1), r'\d+\.\d+\.\d+\.\d+', '{version}', 'program version'), r'\d+(\.\d+){1,2}', '{game}', 'game version')
    main = main.replace(fine.group(0), '<p class="fine" id="get" data-t-line="%s"><span id="dl-line">&nbsp;</span>'
                        '<span id="dl-none" hidden>%s</span></p>' % (line, w['none']))
    name = one(r'<p class="release-name">([^<]+)</p>', 'the release block: name')
    meta = one(r'<p class="release-meta">([^<]+)</p>', 'the release block: facts')
    head = one(r'<section class="release" id="download">', 'the release block')
    name_t = numbered(name.group(1), r'\d+(\.\d+){2,3}', '{version}', 'program version')
    parts = meta.group(1).split(' · ')
    if len(parts) != 4 or 'Windows' not in parts[2]:
        stop('the sample: the release line is no longer «date · game · Windows · size»: «%s»' % meta.group(1))
    game_t = numbered(parts[1], r'\d+(\.\d+){1,3}', '{game}', 'game version')
    size_t = numbered(parts[3], r'\d+([.,]\d+)?', '{n}', 'size')
    main = main.replace(head.group(0), '<section class="release" id="download" data-t-name="%s" data-t-before="{date} · %s · " '
                        'data-t-after=" · {size}" data-t-mb="%s">' % (name_t, game_t, size_t))
    main = main.replace(name.group(0), '<p class="release-name" id="rel-name">%s</p>' % squeeze(name_t.replace('{version}', '')))
    return main.replace(meta.group(0), '<p class="release-meta"><span id="rel-before" hidden></span><span id="rel-none" hidden>%s · </span>'
                        '%s<span id="rel-after" hidden></span></p>' % (w['none'], parts[2]))


def with_plans(main):
    """«Готовые планы» stand before the band for authors: first what there is to take, then how to add one's own."""
    block = (SRC / 'plans.html').read_text(encoding='utf-8').rstrip('\n')
    for anchor in ('  <section class="authors"', '  <section class="release"'):
        if main.count(anchor) == 1:
            return main.replace(anchor, block + '\n\n' + anchor)
    stop('the sample: neither the authors band nor the release block — nowhere to put «Готовые планы»')


SAMPLE_TITLE, SAMPLE_MAIN = sample()
SAMPLE_HOOKED = hooked(SAMPLE_MAIN)
if '--units' in ARGS:
    # what a translator of the main page gets: every piece of the sample's text that needs a translation, in page order
    print(json.dumps([SAMPLE_TITLE] + [u for u in units(SAMPLE_HOOKED) if not own(u)], ensure_ascii=False, indent=1))
    raise SystemExit(0)


def missing_words(code):
    """Pieces of the sample's text a language's table has no translation for (None — the language has no table)."""
    path = SRC / ('overview.%s.json' % code)
    if not path.is_file():
        return None
    table = json.loads(path.read_text(encoding='utf-8'))
    return [u for u in [SAMPLE_TITLE] + units(SAMPLE_HOOKED) if u not in table and not own(u)]


def main_page(lang, w):
    """The main page of a language: (body with marks, title, description, the link picture's description, note)."""
    code = lang['code']
    if code == SOURCE or missing_words(code) == []:
        main, title = SAMPLE_HOOKED, SAMPLE_TITLE
        if code != SOURCE:
            table = json.loads((SRC / ('overview.%s.json' % code)).read_text(encoding='utf-8'))
            main, title = translated(main, table), table.get(title, title)
        main = with_plans(live(main, w))
        lead = re.search(r'<p class="lead">(.*?)</p>', main, re.S)
        first = re.search(r'<div class="product"><img [^>]*alt="([^"]*)"', main)
        if not lead or not first:
            stop('the sample: no sentence under the headline or no first picture')
        return main, title, squeeze(re.sub(r'<[^>]+>', ' ', lead.group(1))), first.group(1), None
    kept = SRC / ('overview.%s.html' % code)
    if not kept.is_file():
        return None
    p = PAGES[0].get(code)
    if not p or 'og_alt' not in p:
        stop('pages.json: the kept main page of %s needs its title, description and og_alt' % code)
    lack = missing_words(code)
    note = ('%s: the main page is a fragment kept from an earlier sample (src/overview.%s.html) — %s'
            % (code, code, 'no word table yet' if lack is None else '%d piece(s) of the sample have no translation' % len(lack)))
    return kept.read_text(encoding='utf-8').rstrip('\n'), p['title'], p['description'], p['og_alt'], note


def lacks(lang):
    """What a language still has to get before it can be on the site: {what kind: [the things]}."""
    code, miss = lang['code'], {}
    if code not in conf['words']:
        miss.setdefault('words', []).append('words.%s.json' % code)
    for page in PAGES[1:]:
        if code not in page:
            miss.setdefault('words', []).append('titles of «%s» in words.%s.json' % (page['id'], code))
        if not (SRC / ('%s.%s.html' % (page['id'], code))).is_file():
            miss.setdefault('words', []).append('%s.%s.html' % (page['id'], code))
    if code != SOURCE and missing_words(code) != [] and not (SRC / ('overview.%s.html' % code)).is_file():
        miss.setdefault('words', []).append('the main page: overview.%s.json' % code)
    for name in ['%s-%s.webp' % (n, code) for n in PICTURES] + ['og-%s.png' % code]:
        if not (SITE / 'assets' / name).is_file():
            miss.setdefault('pictures', []).append(name)
    return miss


def said(miss):
    """The same in a line: texts are named one by one, pictures — in site/assets — by their number unless they are few."""
    parts = list(miss.get('words', []))
    pics = miss.get('pictures', [])
    if pics:
        parts.append('%d picture(s) in site/assets' % len(pics) if len(pics) > 2 else ', '.join(pics))
    return '; '.join(parts)


# --- pages ----------------------------------------------------------------------------------------------------------
def esc(text):
    return htmllib.escape(text, quote=True)


def build(langs, donor):
    """Pages of the given languages. «donor» (a trial build only): the language whose texts stand in for missing ones."""
    out = {}
    for lang in langs:
        code = lang['code']
        w = words(lang) or words(donor)
        text = lang if conf['words'].get(code) else donor                    # whose fragments and titles this language shows
        pictures = code if all(asset('%s-%s.webp' % (n, code)) for n in PICTURES) else (donor or lang)['code']
        og = code if asset('og-%s.png' % code) else (donor or lang)['code']
        main = main_page(text, words(text))
        if main is None:
            stop('%s: no main page (no word table, no kept fragment)' % code)
        if main[4] and main[4] not in notes:
            notes.append(main[4])
        for page in PAGES:
            here = lang['dir'] + page['dir']
            v = {'lang': lang['tag'], 'code': code, 'language': lang, 'locale': lang['locale'], 'page': page['id'],
                 'root': '../' * here.count('/'), 'w': w, 'pictures': pictures, 'canonical': ORIGIN + here,
                 'og_image': ORIGIN + 'assets/og-%s.png' % og, 'og_locale': lang['locale'].replace('-', '_'),
                 'og_alternates': '\n'.join('<meta property="og:locale:alternate" content="%s">' % o['locale'].replace('-', '_')
                                            for o in langs if o is not lang),
                 'hreflangs': '\n'.join(['<link rel="alternate" hreflang="%s" href="%s">' % (o['tag'], ORIGIN + o['dir'] + page['dir'])
                                         for o in langs] +
                                        ['<link rel="alternate" hreflang="x-default" href="%s">' % (ORIGIN + page['dir'])]),
                 # the header: the current language by its name (the region in brackets is kept for the list), the list — all
                 # of them in the program's order; a link to the general address carries «?lang=en»: English asked for by name
                 'lang_name': esc(re.sub(r'\s*\(.*\)$', '', lang['name'])),
                 'lang_code': code.upper(),                    # stands in for the name where the header is too narrow for it (site.js)
                 'lang_menu': ''.join(
                     '<span class="here" lang="%s" aria-current="true">%s</span>' % (o['tag'], esc(o['name'])) if o is lang else
                     '<a href="%s%s" lang="%s" hreflang="%s" data-lang="%s">%s</a>'
                     % (rel(here, o['dir'] + page['dir']), '?lang=en' if o['code'] == GENERAL else '', o['tag'], o['tag'], o['code'], esc(o['name']))
                     for o in langs),
                 # the page of the general address tells lang.js where its twins are: a first visit goes to the browser's language
                 'html_attrs': ' data-locale="%s"' % lang['locale'] + (
                     ' data-root="%s" data-page="%s" data-langs="%s"' % ('../' * here.count('/'), page['dir'],
                                                                         ' '.join(o['code'] for o in langs if o is not lang))
                     if code == GENERAL and len(langs) > 1 else ''),
                 'ggg_lang': ' lang="en"' if lang['tag'] != 'en' else ''}
            for q in PAGES:
                v[q['id']] = rel(here, lang['dir'] + q['dir'])
            v['brand_href'] = '#top' if page['id'] == 'overview' else v['overview']
            # the program's languages by their own names — the list of the install page
            v['program_langs'] = ', '.join('<span lang="%s">%s</span>' % (o['tag'], esc(o['name'])) for o in everyone)
            v['dl_href'] = ('' if page['id'] == 'install' else v['install']) + '#download'
            v['plans_offer'] = w.get('plans_offer', '').replace(
                '{link}', '<a data-contact href="%s#contact" rel="noopener noreferrer"></a>' % v['about'])
            if page['id'] == 'overview':
                body, title, description = main[:3]
                og_title, name = title, 'the main page (%s)' % text['code']
            else:
                p = page[text['code']]
                title, og_title, description = p['title'], p['og_title'], p['description']
                name = '%s.%s.html' % (page['id'], text['code'])
                body = (SRC / name).read_text(encoding='utf-8').rstrip('\n')
            # the link picture is one for all pages of a language: the main page's headline and its first picture
            v.update(title=esc(title), og_title=esc(og_title), description=esc(description), og_description=esc(description),
                     og_alt=esc(main[3]))
            body = fill(body, v, name)
            # no line begins with a dash: in the page's own text the space before a dash does not break
            body = body.replace(' — ', '&nbsp;— ').replace(' – ', '&nbsp;– ')
            # the first page lays its own sections out; the others are one column of text
            v['body'] = body if page['id'] == 'overview' else '<div class="wrap page">\n%s\n</div>' % body
            page_html = fill(layout, v, 'layout.html')
            # a link to a place on this very page is just «#place»: nothing is loaded again
            out[here + 'index.html'] = page_html.replace('href="./#', 'href="#').replace('\r\n', '\n')
    return out


def lint(pages, langs):
    """What the pages' own rules forbid, and links that lead nowhere."""
    bad = []
    ids = {path: set(re.findall(r'\sid="([^"]+)"', page)) for path, page in pages.items()}
    for path, page in pages.items():
        if '{{' in page or '}}' in page:
            bad.append('%s: a mark is left' % path)
        if re.search(r'<[^>]+\sstyle=', page) or re.search(r'<style\b', page):
            bad.append('%s: an inline style (the Content-Security-Policy would drop it)' % path)
        if re.search(r'<script(?![^>]*\ssrc=)', page) or re.search(r'<[^>]+\son[a-z]+=', page):
            bad.append('%s: an inline script or handler' % path)
        folder = posixpath.dirname(path)
        for attr, url in re.findall(r'\s(href|src)="([^"]*)"', page):
            if re.match(r'(https?:|mailto:)', url):
                continue
            if url.startswith('/'):
                bad.append('%s: %s="%s" starts at the root — only relative paths' % (path, attr, url))
                continue
            target, _, frag = url.partition('#')
            target = target.split('?')[0]
            full = posixpath.normpath(posixpath.join(folder, target)) if target else path
            if target.endswith('/') or target in ('', '.'):
                full = (full + '/index.html').lstrip('./') if target else path
                full = full.replace('//', '/')
                if full == 'index.html/index.html':
                    full = 'index.html'
            if full in pages:
                if frag and frag not in ids[full]:
                    bad.append('%s: %s="%s" — no id «%s» on %s' % (path, attr, url, frag, full))
            elif not (SITE / full).is_file() and not (OUT / full).is_file():
                # update/latest.json and plans/index.json appear with the first release: a link to them may wait
                if full not in ('update/latest.json', 'plans/index.json'):
                    bad.append('%s: %s="%s" — no such file in site/' % (path, attr, url))
    return bad


def lost_page(langs):
    """404.html — the page the hosting gives for any missing address, at any depth: its paths start at the root, its
    styles are inside (it has a policy of its own), and it names every language's first page by the language's name."""
    links = ''.join('<a href="/%s" lang="%s" hreflang="%s">%s</a>' % (x['dir'], x['tag'], x['tag'], esc(x['name'])) for x in langs)
    page = (SRC / '404.html').read_text(encoding='utf-8')
    if page.count('{{langs}}') != 1:
        stop('src/404.html: the mark {{langs}} must stand in it once')
    return page.replace('{{langs}}', links).replace('\r\n', '\n')


everyone = program_languages()
general = next((x for x in everyone if x['code'] == GENERAL), None)
if not general or lacks(general):
    stop('the general address is %s, and it lacks: %s' % (GENERAL, said(lacks(general)) if general else 'its language file'))
if trial:
    trial.mkdir(parents=True, exist_ok=True)
    (trial / 'assets').mkdir(exist_ok=True)
    langs = everyone
    for lang in langs:
        miss = lacks(lang)
        if said(miss):
            notes.append('%s (%s): borrowed from %s — %s' % (lang['code'], lang['name'], GENERAL, said(miss)))
else:
    langs = [x for x in everyone if not lacks(x)]
    notes += ['%s (%s) is not on the site yet — it lacks: %s' % (x['code'], x['name'], said(lacks(x)))
              for x in everyone if lacks(x)]
pages = build(langs, general if trial else None)
styles = (CSS_HEAD + (SAMPLE / 'mock.css').read_text(encoding='utf-8').rstrip('\n') + '\n'
          + (SRC / 'extra.css').read_text(encoding='utf-8')).replace('\r\n', '\n')
problems = lint(pages, langs)
if problems:
    print('\n'.join(problems))
    stop('%d problem(s): nothing written' % len(problems))
changed = []
pages = dict(pages)
pages['assets/site.css'] = styles
pages['404.html'] = lost_page(langs)
for path, page in pages.items():
    file = OUT / path
    if not file.is_file() or file.read_bytes() != page.encode('utf-8'):
        changed.append(path)
        if not check:
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(page.encode('utf-8'))
for path, page in sorted(pages.items()):
    print('%-26s %6d bytes%s' % (path, len(page.encode('utf-8')), '  <- differs' if path in changed and check else
                                 ('  written' if path in changed else '')))
print('languages: %s' % ', '.join('%s /%s' % (x['code'], x['dir']) for x in langs))
for note in notes:
    print('  ' + note)
if check and changed:
    stop('site/ differs from work/site/src (and the sample) in %d file(s): run build_site.py' % len(changed))
print('%d pages, 404.html and the stylesheet%s: %s' % (len(pages) - 2, ' -> %s' % trial if trial else '',
                                             'the same as the sources' if not changed else ('%d written' % len(changed))))
