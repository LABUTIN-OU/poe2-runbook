# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Sergei Labutin
# Additional terms under GPL-3.0 section 7: see NOTICE.md
"""Что игра пишет в лог на языке клиента — по таблицам самой игры (каталог: log-<язык>.json.gz).

Системные строки лога («… достигает N уровня», «… был повержен», «Игрок … получил …», «Вы получили очков
пассивных умений: N») — шаблоны таблицы игры BackendErrors на языке клиента, поэтому лог читается на любом
из десяти языков. Реплики NPC и боссов — строки таблицы NPCTextAudio: план ждёт реплику по КОДУ строки (код
один на всех языках), а здесь код находится по тексту из лога и имени говорящего.

Говорящий. В логе реплику подписывает имя NPC из таблицы игры. Бывает, что голос тот же, а имя другое (в одних
забегах «Дрейвен, претор Вечных», в других «Тихо, Чёрный претор»). Поэтому строка засчитывается, если совпал
говорящий, или если такой текст во всей таблице есть только у строк, которых ждёт план.

Награда. Строка «Игрок … получил +10% к сопротивлению холоду» — это текст свойства героя из описаний свойств
игры на языке клиента. План ждёт награду по КОДАМ свойств (base_cold_damage_resistance_%): здесь код находится
по тексту — числа в тексте и места для чисел в шаблонах игры сравниваются как «#». Очки пассивных умений —
отдельные системные строки лога; их код у программы свой: POINTS.
"""
import re

# Код награды «очки пассивных умений» (строки лога «Вы получили очков пассивных умений: N»): у игры это не
# свойство героя, а сообщение сервера, поэтому код — программы; свойства с таким кодом в игре нет.
POINTS = 'passive_points'
# Место для числа в шаблоне свойства игры: {0}, {0:+d}, {1:d}…; и само число в строке лога
RE_PH = re.compile(r'\{\d*(?::[^{}]*)?\}')
RE_NUM = re.compile(r'[+\-−]?\d+(?:[.,]\d+)?')
RE_SIGNED = re.compile(r'[+\-−]#')

RE_SET = re.compile(r'<<[^<>]*>>')
# Обращение по роду героя: в логе стоят оба варианта подряд — <if:MS>{Гость признан}<elif:FS>{Гостья признана}
RE_IF = re.compile(r'<if:MS>\{([^{}]*)\}<elif:FS>\{([^{}]*)\}')
RE_TAG = re.compile(r'<[^<>]*>')
RE_ARG = re.compile(r'\{(\d+)\}')

# Шаблоны русского клиента — те же строки таблицы BackendErrors. Ими лог читается, пока каталога с текстами
# лога нет (проверки, старый каталог).
RU = {
    'LevelUp': '{0} ({1}) достигает {2} уровня',
    'PlayerSlain': '{0} был повержен.',
    'ReceivedStatBonusWithName': 'Игрок {0} получил {1}.',
    'ReceivedPassivePoint1': 'Вы получили очко пассивных умений.',
    'ReceivedPassivePointN': 'Вы получили очков пассивных умений: {0}.',
    'ReceivedWeaponSpecialisationPoint1': 'Вы получили очко пассивных умений для набора оружия.',
    'ReceivedWeaponSpecialisationPointN': 'Вы получили {0} очка пассивных умений для набора оружия.',
}


# Язык клиента в настройках игры (строка language= раздела [LANGUAGE]) -> язык текстов лога в каталоге.
# Русский клиент пишет language=ru; код, которого здесь нет, язык не определяет — тогда он узнаётся по логу.
CONFIG_LANGS = {'en': 'en', 'ru': 'ru', 'de': 'de', 'fr': 'fr', 'es': 'es', 'pt': 'pt', 'pt-br': 'pt', 'pt_br': 'pt',
                'ja': 'ja', 'jp': 'ja', 'ko': 'ko', 'kr': 'ko', 'th': 'th', 'zh': 'zh-Hant', 'zh-tw': 'zh-Hant',
                'zh_tw': 'zh-Hant', 'tw': 'zh-Hant', 'zh-hant': 'zh-Hant'}


def detect(lines, msgs):
    """Язык клиента по строкам лога: чьи системные строки (уровень, награда, гибель, очки) в них встречаются
    чаще. msgs — {язык: {код: шаблон}}. Ни одной не нашлось — None."""
    best, score = None, 0
    for lang, msg in sorted((msgs or {}).items()):
        t = LogText({'msg': msg}, lang)
        rxs = [r for r in (t.level, t.slain, t.reward) if r] + [r for r, _n, _w in t.points]
        n = sum(1 for line in lines if '] : ' in line and any(r.search(line) for r in rxs))
        if n > score:
            best, score = lang, n
    return best


def skeleton(text):
    """Текст свойства без чисел: и шаблон игры («{0:+d}% к сопротивлению холоду»), и строка лога («+10% к
    сопротивлению холоду.») дают одно и то же — «#% к сопротивлению холоду». Регистр и точка в конце не важны."""
    t = RE_NUM.sub('#', RE_PH.sub('#', text or ''))
    t = RE_SIGNED.sub('#', t)
    t = ' '.join(t.split()).rstrip('.。 ')
    return t.casefold()


def stat_text(template):
    """Шаблон свойства игры для показа человеку: места для чисел — «#», перенос строки в шаблоне — «·»."""
    return ' '.join(RE_PH.sub('#', (template or '').replace('\\n', ' · ')).split())


def clean(text, gender='M'):
    """Текст реплики без разметки игры — так его видно в чате. Обращение по роду: один вариант (gender M / F)."""
    text = RE_SET.sub('', text or '')
    text = RE_IF.sub(lambda m: m.group(1) if gender == 'M' else m.group(2), text)
    text = RE_TAG.sub('', text).replace('{', '').replace('}', '')
    return ' '.join(text.split())


def template(text, groups):
    """Шаблон игры («{0} ({1}) достигает {2} уровня») -> regex строки лога (системное сообщение идёт после «] : »).

    groups: {номер аргумента: (имя группы, её шаблон)}. Точка в конце необязательна: в логе её бывает и нет."""
    text = text.strip()
    while text and text[-1] in '.。':
        text = text[:-1]
    out, pos, seen = [], 0, set()
    for m in RE_ARG.finditer(text):
        out.append(re.escape(text[pos:m.start()]))
        name, pat = groups.get(int(m.group(1)), ('a%s' % m.group(1), '.+?'))
        out.append('(?P<%s>%s)' % (name, pat) if name not in seen else '(?P=%s)' % name)
        seen.add(name)
        pos = m.end()
    out.append(re.escape(text[pos:]))
    return re.compile(r'\] : ' + ''.join(out) + r'[.。]?\s*$')


class LogText:
    """Тексты лога одного языка клиента: системные строки (шаблоны) и реплики (код строки -> текст, говорящие)."""

    def __init__(self, pack=None, lang='ru'):
        pack = pack or {'msg': RU}
        self.lang = lang
        msg = dict(pack.get('msg') or {})
        self.npc = pack.get('npc') or []
        self.say = pack.get('say') or {}
        # тексты свойств: коды свойств -> шаблоны на этом языке (описания свойств игры)
        self.stat = pack.get('stat') or {}
        self._skel = None
        mk = lambda key, groups: template(msg[key], groups) if msg.get(key) else None
        self.level = mk('LevelUp', {0: ('name', '.+?'), 1: ('cls', '.+?'), 2: ('level', r'\d+')})
        self.slain = mk('PlayerSlain', {0: ('name', r'\S+')})
        self.reward = mk('ReceivedStatBonusWithName', {0: ('name', r'\S+'), 1: ('text', '.+?')})
        # очки умений: сначала «N очков», потом «одно очко»; у набора оружия свои строки
        self.points = [(rx, n1, weapon) for key, n1, weapon in (
            ('ReceivedPassivePointN', None, False), ('ReceivedPassivePoint1', 1, False),
            ('ReceivedWeaponSpecialisationPointN', None, True), ('ReceivedWeaponSpecialisationPoint1', 1, True))
            for rx in [mk(key, {0: ('n', r'\d+')})] if rx]
        self._texts = None

    def reward_keys(self, text):
        """Коды свойств, которые дала строка награды лога (текст без разметки игры); не узнана — пусто.
        Один текст бывает у нескольких свойств — тогда все."""
        if self._skel is None:
            index = {}
            for key, temps in self.stat.items():
                for t in temps:
                    index.setdefault(skeleton(t), set()).add(key)
            self._skel = index
        return sorted(self._skel.get(skeleton(text), ()))

    def speakers(self, lid):
        """Имена тех, кто говорит строку lid, на этом языке."""
        row = self.say.get(lid) or []
        return {self.npc[r] for r in row[1:] if isinstance(r, int) and 0 <= r < len(self.npc) and self.npc[r]}

    def text_owners(self):
        """Текст без разметки -> коды всех строк таблицы с этим текстом (считается один раз)."""
        if self._texts is None:
            owners = {}
            for lid, row in self.say.items():
                for g in ('M', 'F'):
                    owners.setdefault(clean(row[0], g), set()).add(lid)
            self._texts = owners
        return self._texts

    def watch(self, ids):
        """Указатель для реплик, которых ждёт план: текст -> [(код, говорящие)] и для каждого текста — все его коды."""
        index = {}
        for lid in ids:
            row = self.say.get(lid)
            if not row:
                continue
            names = self.speakers(lid)
            for g in ('M', 'F'):
                t = clean(row[0], g)
                if (lid, names) not in [(x, y) for x, y in index.get(t, [])]:
                    index.setdefault(t, []).append((lid, names))
        owners = self.text_owners() if index else {}
        return {t: (cands, owners.get(t, set())) for t, cands in index.items()}

    @staticmethod
    def heard(index, speaker, raw):
        """Коды строк плана, которые звучат в строке лога «говорящий: текст» (пусто — не та реплика)."""
        hit = index.get(clean(raw))
        if not hit:
            return []
        cands, owners = hit
        mine = sorted({lid for lid, names in cands if speaker in names})
        if mine:
            return mine
        ids = {lid for lid, _ in cands}
        # другой говорящий: засчитываем, только если этот текст в игре есть лишь у ожидаемых строк
        return sorted(ids) if owners and owners <= ids else []
