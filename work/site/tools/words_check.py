# -*- coding: utf-8 -*-
"""Words in the site's pictures of the program that are not in the page's language.

    python -X utf8 words_check.py <project> <raw dir> [<code> …]

For every picture <name>-<code>.png make_shots.py writes <name>-<code>.txt: every piece of text inside the picture's
frame (text and field values). Each piece is checked here:
  * a page not in Russian — Cyrillic;
  * a Russian, Japanese, Korean or Thai page — a Latin word, unless the game's own client of that language uses the very
    same word (the Thai client keeps many English names), or it is a name people gave or a key (ALLOW);
  * a page not in English — an English name of the game (zone, monster, boss, item base, skill, hero class) that has a
    name of its own in that language's client.
Not counted: the English name in brackets right after the local one («Колокольщик (The Crowbell)» — the program pairs
them on purpose, so that a guide in English can be found); a word the program's own translation into that language uses
(the editor's tab «Build»); the code of the page's language on the program's language button.
Names come from the catalogue of game data (catalog/data/<version>: areas, lang-<code>.json, names-<code>.json.gz).
Exit code 1 when something is found."""
import gzip
import json
import re
import sys
from pathlib import Path

project, raw = Path(sys.argv[1]).resolve(), Path(sys.argv[2])
codes = sys.argv[3:] or ['en', 'ru', 'de', 'es', 'fr', 'ja', 'ko', 'pt', 'th']
PICTURES = ('list', 'window', 'late', 'answer', 'tiles', 'time', 'plan')
# Latin words that are names people gave or keys, not words of a language: the program's name, the plan's title,
# the trial hero, keys, Windows, version tags, units
ALLOW = {'poe2', 'runbook', 'hc', 'ssf', 'dov', 'trial', 'f2', 'f3', 'f7', 'alt', 'ctrl', 'windows', 'path', 'of', 'exile',
         'trialaa1', 'trialaa2', 'trialaa3', 'h', 'x', 'ms', 'en', 'ru', 'de', 'es', 'fr', 'ja', 'ko', 'pt', 'th'}
LATIN = re.compile(r"[A-Za-z][A-Za-z0-9'’-]*")
PAIR = re.compile(r'\s*\((?:The |A |An )?[A-Z][^()А-Яа-яЁё]*\)')     # «Местное (English)»: the English half of a pair
CYR = re.compile(r'[А-Яа-яЁё][А-Яа-яЁё-]*')
data = project / 'catalog' / 'data'
cat = data / (data / 'current.txt').read_text(encoding='utf-8').strip()
areas = json.loads((cat / 'areas.json').read_text(encoding='utf-8'))


def pairs(code):
    """English name -> this language's name, for everything the client names."""
    out = {}
    pack = json.loads((cat / ('lang-%s.json' % code)).read_text(encoding='utf-8'))
    for key, local in (pack.get('areas') or {}).items():
        if key in areas and isinstance(local, str):
            out[areas[key]['name']] = local
    for field in ('bases', 'gems', 'heroClasses'):
        out.update({k: v for k, v in (pack.get(field) or {}).items() if isinstance(v, str)})
    names = cat / ('names-%s.json.gz' % code)
    if names.is_file():
        with gzip.open(names, 'rt', encoding='utf-8') as f:
            out.update({k: v for k, v in (json.load(f).get('names') or {}).items() if isinstance(v, str)})
    return out


def grams(text, n=6):
    words = re.findall(r"[^\s,.;:!?«»“”„()\[\]·→—–]+", text)
    for i in range(len(words)):
        for j in range(i + 1, min(len(words), i + n) + 1):
            yield ' '.join(words[i:j])


found = 0
def program_words(code):
    """Every word the program's own translation into this language uses (its texts and the plan layer)."""
    path = project / 'planner' / 'lang' / ('%s.json' % code)
    if code == 'ru' or not path.is_file():
        return set()
    d = json.loads(path.read_text(encoding='utf-8'))
    return {v.casefold() for part in ('texts', 'plan') for v in (d.get(part) or {}).values() if isinstance(v, str)}


for code in codes:
    local = {} if code == 'en' else pairs(code)
    own = program_words(code)
    english = {en: lo for en, lo in local.items() if en != lo and len(en) >= 4 and LATIN.fullmatch(en.split()[0] or '')}
    native = {lo.casefold() for lo in local.values()}
    rows = []
    for name in PICTURES:
        path = raw / ('%s-%s.txt' % (name, code))
        if not path.is_file():
            rows.append((name, '(no text file: the picture was taken without it)', []))
            continue
        for whole in path.read_text(encoding='utf-8').splitlines():
            stripped = PAIR.sub('', whole)                   # the pair's English half goes; a lone «(English)» stays
            piece = stripped if stripped.strip() else whole
            bad = []
            if code != 'ru':
                bad += ['cyrillic: ' + w for w in CYR.findall(piece)]
            if code in ('ru', 'ja', 'ko', 'th'):
                for w in LATIN.findall(piece):
                    if w.casefold() not in ALLOW and w.casefold() not in native and w.casefold() not in own and not any(
                            w.casefold() in g.casefold().split() and g.casefold() in native for g in grams(piece)):
                        bad.append('latin: ' + w)
            if code != 'en':
                bad += ['english name: %s (here: %s)' % (g, english[g]) for g in set(grams(piece))
                        if g in english and g.casefold() not in own]
            if bad:
                rows.append((name, whole, sorted(set(bad))))
    words = sorted({b for _, _, bs in rows for b in bs})
    found += bool(words)
    print('%s: %s' % (code, 'every word is in the page\'s language' if not rows else '%d piece(s), %d word(s) not in the page\'s language'
                      % (len([r for r in rows if r[2]]), len(words))))
    for name, piece, bad in rows:
        print('  %-7s %s%s' % (name, piece[:90], ('   <- ' + '; '.join(bad)) if bad else ''))
sys.exit(1 if found else 0)
