# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Sergei Labutin
# Additional terms under GPL-3.0 section 7: see NOTICE.md
"""Проверки logtext: лог клиента на любом языке — системные строки по шаблонам игры, реплики по кодам строк."""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import core  # noqa: E402
import gamedata  # noqa: E402
import logtext  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
# Шаблоны английского и немецкого клиента — строки таблицы игры BackendErrors (выгрузка 0.5.5.10).
EN = {'LevelUp': '{0} ({1}) is now level {2}', 'PlayerSlain': '{0} has been slain.',
      'ReceivedStatBonusWithName': '{0} has received {1}.',
      'ReceivedPassivePoint1': 'You have received a Passive Skill Point.',
      'ReceivedPassivePointN': 'You have received {0} Passive Skill Points.',
      'ReceivedWeaponSpecialisationPoint1': 'You have received a Weapon Set Passive Skill Point.',
      'ReceivedWeaponSpecialisationPointN': 'You have received {0} Weapon Set Passive Skill Points.'}
DE = {'LevelUp': '{0} ({1}) hat Stufe {2} erreicht.', 'PlayerSlain': '{0} wurde getötet.',
      'ReceivedStatBonusWithName': "{0} erhält '{1}'.",
      'ReceivedPassivePointN': 'Du hast {0} passive Fertigkeitspunkte erhalten.'}


def sys_line(t, text):
    return '2026/11/22 %s 1000 abcd [INFO Client 1] : %s' % (t, text)


def feed(parser, lines):
    return [ev for line in lines for ev in parser.feed(line)]


class TemplateTest(unittest.TestCase):
    def test_english_client_is_read(self):
        p = core.LogParser((), logtext.LogText({'msg': EN}, 'en'))
        evs = feed(p, [sys_line('10:00:00', 'Varra (Sorceress) is now level 12'),
                       sys_line('10:00:01', 'Varra has received +10% to [Resistances|Cold Resistance].'),
                       sys_line('10:00:02', 'You have received 2 Passive Skill Points.'),
                       sys_line('10:00:02', 'You have received 2 Weapon Set Passive Skill Points.'),
                       sys_line('10:00:03', 'Varra has been slain.')])
        self.assertEqual([(e['type'], e.get('level') or e.get('n') or e.get('text') or e.get('name')) for e in evs], [
            ('level', 12), ('reward', '+10% to Cold Resistance'), ('points', 2), ('reward', 'очки пассивных умений: +2'),
            ('points', 2), ('death', 'Varra')])
        self.assertEqual([e['weapon'] for e in evs if e['type'] == 'points'], [False, True])

    def test_german_client_is_read(self):
        p = core.LogParser((), logtext.LogText({'msg': DE}, 'de'))
        evs = feed(p, [sys_line('10:00:00', 'Varra (Hexe) hat Stufe 7 erreicht.'),
                       sys_line('10:00:01', "Varra erhält '+30 zu Geist'."),
                       sys_line('10:00:03', 'Varra wurde getötet.')])
        self.assertEqual([(e['type'], e.get('level') or e.get('text') or e.get('name')) for e in evs],
                         [('level', 7), ('reward', '+30 zu Geist'), ('death', 'Varra')])

    def test_russian_lines_are_the_default(self):
        evs = feed(core.LogParser(), [sys_line('10:00:00', 'Герой (Чародейка) достигает 3 уровня'),
                                      sys_line('10:00:01', 'Вы получили очко пассивных умений.')])
        self.assertEqual([(e['type'], e.get('level') or e.get('n')) for e in evs], [('level', 3), ('points', 1), ('reward', None)])

    def test_every_language_of_the_catalogue(self):
        # каждый язык каталога: из его же шаблона собранная строка лога читается обратно
        cat = gamedata.load(ROOT / 'catalog' / 'data')
        msgs = gamedata.log_msgs(cat)
        if not msgs:
            self.skipTest('в каталоге нет текстов лога')
        self.assertEqual(len(msgs), 10)
        for lang, msg in msgs.items():
            fill = lambda key, *args: msg[key].format(*args)
            p = core.LogParser((), logtext.LogText({'msg': msg}, lang))
            evs = feed(p, [sys_line('10:00:00', fill('LevelUp', 'Varra', 'Cls', 21)),
                           sys_line('10:00:01', fill('ReceivedPassivePointN', 2)),
                           sys_line('10:00:02', fill('PlayerSlain', 'Varra'))])
            self.assertEqual([e['type'] for e in evs], ['level', 'points', 'reward', 'death'], lang)
            self.assertEqual((evs[0]['level'], evs[0]['name'], evs[1]['n']), (21, 'Varra', 2), lang)
            # язык узнаётся по самим строкам лога
            self.assertEqual(logtext.detect([sys_line('10:00:00', fill('LevelUp', 'Varra', 'Cls', 21))] * 3, msgs),
                             lang)

    def test_unknown_lines_name_no_language(self):
        self.assertIsNone(logtext.detect(['просто строка'], {'en': EN, 'de': DE}))
        self.assertEqual(logtext.CONFIG_LANGS['ru'], 'ru')


class RewardTest(unittest.TestCase):
    def test_numbers_do_not_matter(self):
        self.assertEqual(logtext.skeleton('{0:+d}% к сопротивлению холоду'), logtext.skeleton('+10% к сопротивлению холоду.'))
        self.assertEqual(logtext.skeleton('+{0} to Spirit'), logtext.skeleton('+30 to Spirit'))
        self.assertEqual(logtext.stat_text('{0:+d}% к сопротивлению холоду'), '#% к сопротивлению холоду')
        t = logtext.LogText({'stat': {'a': ['{0}% increased Stun Threshold'], 'b': ['{0}% increased Stun Threshold']}}, 'en')
        self.assertEqual(t.reward_keys('25% increased Stun Threshold'), ['a', 'b'])     # один текст — все коды
        self.assertEqual(t.reward_keys('что-то другое'), [])

    def test_every_language_of_the_catalogue(self):
        # строка награды на любом из 10 языков: шаблон игры с числом читается обратно в тот же код
        cat = gamedata.load(ROOT / 'catalog' / 'data')
        langs = (cat or {}).get('logs') or []
        if not langs:
            self.skipTest('в каталоге нет текстов лога')
        for lang in langs:
            t = logtext.LogText(gamedata.log_pack(cat, lang), lang)
            for key in ('base_cold_damage_resistance_%', 'base_maximum_life', 'stun_threshold_+%', 'num_charm_slots'):
                line = logtext.RE_PH.sub('10', t.stat[key][0])
                self.assertIn(key, t.reward_keys(line), (lang, line))


class SpeechTest(unittest.TestCase):
    PACK = {'npc': ['Дрейвен', 'Уна', 'Асала'], 'msg': logtext.RU, 'say': {
        'DravenDeath': ['Наконец... вместе...', 0],
        'AsalaDone': ['Дело сделано.', 2], 'UnaDone': ['Дело сделано.', 1],
        'Greet': ['<if:MS>{Гость признан}<elif:FS>{Гостья признана}', 1]}}

    def test_markup_is_dropped(self):
        self.assertEqual(logtext.clean('<<set:F>><<set:S>>Дело  сделано.'), 'Дело сделано.')
        self.assertEqual(logtext.clean('<if:MS>{Гость признан}<elif:FS>{Гостья признана}'), 'Гость признан')
        self.assertEqual(logtext.clean('<if:MS>{Гость признан}<elif:FS>{Гостья признана}', 'F'), 'Гостья признана')
        self.assertEqual(logtext.clean('<i>{Атул!}'), 'Атул!')

    def test_speaker_decides_when_the_text_is_shared(self):
        t = logtext.LogText(self.PACK, 'ru')
        idx = t.watch(['AsalaDone', 'DravenDeath', 'Greet'])
        self.assertEqual(t.heard(idx, 'Асала', '<<set:F>>Дело сделано.'), ['AsalaDone'])
        self.assertEqual(t.heard(idx, 'Уна', 'Дело сделано.'), [])           # та же фраза, но не та строка
        self.assertEqual(t.heard(idx, 'Тихо', 'Наконец... вместе...'), ['DravenDeath'])   # текст только этой строки
        self.assertEqual(t.heard(idx, 'Уна', '<if:MS>{Гость признан}<elif:FS>{Гостья признана}'), ['Greet'])
        self.assertEqual(t.heard(idx, 'Уна', 'Гостья признана'), ['Greet'])
        self.assertEqual(t.heard(idx, 'Асала', 'Другое'), [])


if __name__ == '__main__':
    unittest.main()
