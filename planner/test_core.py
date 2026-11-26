# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Sergei Labutin
# Additional terms under GPL-3.0 section 7: see NOTICE.md
"""Проверка разбора лога и расчёта состояния. Запуск: python -m unittest planner.test_core"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import core  # noqa: E402
import logtext  # noqa: E402

DAY = '2026/11/11'


def gen(t, level, code, seed=1):
    return '%s %s 1000 abcd [DEBUG Client 1] Generating level %d area "%s" with seed %d' % (DAY, t, level, code, seed)


def src(t, name):
    return '%s %s 1000 abcd [INFO Client 1] [SCENE] Set Source [%s]' % (DAY, t, name)


def ascends(events):
    """Только события вознесения: каждый клик по дереву даёт ещё и событие passive."""
    return [e for e in events if e['type'] == 'ascend']


def lvl(t, n, cls='Чародейка'):
    return '%s %s 1000 abcd [INFO Client 1] : Герой (%s) достигает %d уровня' % (DAY, t, cls, n)


def reward(t, text):
    return '%s %s 1000 abcd [INFO Client 1] : Игрок Герой получил %s.' % (DAY, t, text)


def flt(t, fid, ok='true'):
    return ('%s %s 1000 abcd [INFO Client 1] [Item Filter] Finished reloading online filter %s. '
            'Result: %s. Hash: aa. Type: Normal. Message: ' % (DAY, t, fid, ok))


def zone(t, level, code, name, seed=1):
    return [gen(t, level, code, seed), src(t, '(null)'), src(t, name)]


def ascend(t, node='AscendancySorceress3Small1'):
    return ('%s %s 1000 abcd [INFO Client 1] Successfully allocated passive skill id: %s, name: Дух'
            % (DAY, t, node))


# Повторяет начало настоящего забега: берег, город, Клирфелл, город, Клирфелл, босс, Грельвуд.
RUN_LINES = (
    zone('20:07:03', 1, 'G1_1', 'Берег реки')
    + [flt('20:07:04', 'base1')]
    + [lvl('20:09:17', 2)]
    + zone('20:09:28', 15, 'G1_town', 'Лагерь Клирфелл')
    + zone('20:10:55', 2, 'G1_2', 'Клирфелл')
    + [lvl('20:15:53', 3)]
    + zone('20:20:18', 15, 'G1_town', 'Лагерь Клирфелл')
    + ['%s 20:22:04 1000 abcd [INFO Client 1] : Указанный предмет уничтожен' % DAY]
    + zone('20:33:10', 2, 'G1_2', 'Клирфелл')
    + [reward('20:39:46', '+10% к сопротивлению [Resistances|холоду]')]
    + zone('20:40:07', 4, 'G1_4', 'Грельвуд')
)

# Продолжение того же забега: заглянули в заросли, новые копии Грельвуда, Красная Долина,
# смена фильтра, уровни, снова Грельвуд и уже всерьёз Мрачные заросли.
RUN_TAIL = (
    zone('20:40:40', 6, 'G1_6', 'Мрачные заросли', 9)
    + zone('20:40:45', 4, 'G1_4', 'Грельвуд')
    + [src('20:42:59', 'Акт 1'), src('20:45:36', 'Грельвуд')]
    + zone('20:46:19', 15, 'G1_town', 'Лагерь Клирфелл')
    + zone('20:46:32', 4, 'G1_4', 'Грельвуд', 2)
    + zone('20:49:14', 5, 'G1_5', 'Красная Долина')
    + [flt('21:01:42', 'simple1'), lvl('21:02:50', 4), lvl('21:09:17', 5)]
    + zone('21:13:41', 15, 'G1_town', 'Лагерь Клирфелл')
    + zone('21:20:14', 4, 'G1_4', 'Грельвуд', 3)
    + zone('21:20:41', 6, 'G1_6', 'Мрачные заросли', 9)
)

PLAN = {
    'title': 'тест',
    'slots': [{'id': 'weapon', 'name': 'Оружие'}, {'id': 'helmet', 'name': 'Шлем'}, {'id': 'amulet', 'name': 'Амулет'}],
    'steps': [
        {'id': 'riverbank', 'zone': 'G1_1', 'name': 'Берег реки'},
        {'id': 'clearfell', 'zone': 'G1_2', 'name': 'Клирфелл', 'notes': ['Зачистка']},
        {'id': 'grelwood', 'zone': 'G1_4', 'name': 'Грельвуд'},
        {'id': 'tangle', 'zone': 'G1_6', 'name': 'Мрачные заросли'},
    ],
    'goals': [
        {'id': 'weapon-crossbow', 'slot': 'weapon', 'title': 'Арбалет', 'key': True, 'need': 'clearfell'},
        {'id': 'weapon-sceptre', 'slot': 'weapon', 'title': 'Скипетр', 'need': 'tangle', 'closeOn': 'equip'},
        {'id': 'helmet-any', 'slot': 'helmet', 'title': 'любой', 'any': True, 'soft': True, 'need': 'clearfell'},
        {'id': 'amulet-1', 'slot': 'amulet', 'title': 'Амулет 1', 'need': 'grelwood'},
        {'id': 'amulet-2', 'slot': 'amulet', 'title': 'Амулет 2', 'need': 'tangle'},
        {'id': 'skill-bomb', 'group': 'Навыки', 'title': 'Морозная бомба', 'need': 'clearfell'},
    ],
}

# Маршрут, где Грельвуд встречается дважды, а в заросли сначала только заглядывают.
ROUTE = {
    'title': 'маршрут',
    'slots': [{'id': 'weapon', 'name': 'Оружие'}],
    'filters': {'base1': {'name': 'Базовый'}, 'simple1': {'name': 'Простой', 'note': 'только арбалеты'}},
    'steps': [
        {'id': 'riverbank', 'zone': 'G1_1', 'name': 'Берег реки'},
        {'id': 'clearfell', 'zone': 'G1_2', 'name': 'Клирфелл'},
        {'id': 'grelwood-1', 'zone': 'G1_4', 'also': ['G1_6'], 'name': 'Грельвуд'},
        {'id': 'redvale', 'zone': 'G1_5', 'name': 'Красная Долина', 'filter': 'simple1'},
        {'id': 'grelwood-2', 'zone': 'G1_4', 'name': 'Грельвуд, дерево'},
        {'id': 'tangle', 'zone': 'G1_6', 'name': 'Мрачные заросли'},
        {'id': 'cemetery', 'zone': 'G1_7', 'name': 'Кладбище Вечных'},
        {'id': 'ascension', 'zone': 'G2_13', 'name': 'Восхождение', 'far': True},
    ],
    'goals': [
        {'id': 'weapon-crossbow', 'slot': 'weapon', 'title': 'Арбалет', 'need': 'clearfell'},
        {'id': 'skill-flash', 'group': 'Навыки', 'title': 'Ослепляющая граната', 'heroLevel': 6, 'need': 'redvale'},
        {'id': 'gold', 'group': 'Ресурсы', 'title': '7000 золота', 'need': 'ascension'},
    ],
}


def say(t, who, text):
    return '%s %s 1000 abcd [INFO Client 1] %s: %s' % (DAY, t, who, text)


# Учебная таблица реплик игры (в программе — из каталога, log-<язык>.json.gz): код строки -> [текст, номера говорящих].
# «Дело сделано.» говорят двое — Асала и Уна: чужой голос с этим текстом не засчитывается.
TEXT = logtext.LogText({'npc': ['Асала', 'Скрытный', 'Яма', 'Навали', 'Сехема Асала', 'Уна'], 'msg': logtext.RU, 'say': {
    'AsalaDone': ['Дело сделано.', 0], 'AsalaDone2': ['Дело сделано.', 0], 'SehemaDone': ['Дело сделано.', 4],
    'UnaDone': ['Дело сделано.', 5],
    'HoodedPiece1': ['Теперь мы должны найти остальные. Поспеши.', 1],
    'YamaDefeat': ['<if:MS>{Ай! Хорошо, хорошо. Ты достоин.}<elif:FS>{Ай! Хорошо, хорошо. Ты достойна.}', 2],
    'NavaliDefeat': ['<if:MS>{Свершилось! Гость признан достойным!}<elif:FS>{Свершилось! Гостья признана достойной!}', 3],
    'YamaAtul': ['<i>{Атул!}', 2]},
    # тексты свойств (описания свойств игры): по ним строка награды находит код свойства
    'stat': {'base_cold_damage_resistance_%': ['{0:+d}% к сопротивлению холоду'],
             'mana_regeneration_rate_+%': ['{0}% повышение скорости регенерации маны',
                                           '{0}% понижение скорости регенерации маны'],
             'stun_threshold_+%': ['{0}% увеличение порога оглушения']}}, 'ru')


def build(lines, marks=(), plan=PLAN, moves=(), text=None):
    plan, problems = core.norm_plan(plan)
    # как в программе: парсер ищет в чате только реплики, которых ждёт план; text — тексты лога языка клиента
    parser = core.LogParser(core.heard_ids(plan), text or TEXT)
    run = core.Run()
    for line in lines:
        for ev in parser.feed(line):
            if ev['type'] == 'start':
                run = core.Run(core.run_id(ev['ts']), ev['ts'])
            else:
                run.events.append(ev)
    last = max([e['ts'] for e in run.events] or [0])
    for i, (goal, status) in enumerate(marks):
        run.marks.append({'ts': last + 5000 + i, 'goal': goal, 'status': status})
    for i, step in enumerate(moves):
        run.moves.append({'ts': last + 9000 + i, 'step': step})
    return run, core.derive(plan, run, 0), problems


def goal(view, gid):
    tiles = view['slots'] + [t for st in view.get('stash', []) for t in st.get('tiles', [])]
    for s in tiles:
        for key in ('worn', 'bag', 'next', 'later'):
            if s[key] and s[key]['id'] == gid:
                return s[key]
    for grp in view['groups']:
        for g in grp['goals']:
            if g['id'] == gid:
                return g
            for c in g.get('children', []):
                if c['id'] == gid:
                    return c
    # части слотов (аффиксы) живут только в строках носителей
    rows = view.get('holders', []) + [r for st in view.get('stash', []) for r in st.get('rows', [])]
    for r in rows:
        for lad in ([r['base']] if r['base'] else []) + r['parts']:
            for key in ('have', 'bag', 'next', 'later'):
                if lad[key] and lad[key]['id'] == gid:
                    return lad[key]
    # вещь будущего периода слота (рюкзака нет) — цель на карточке своего шага
    for c in view.get('cards', []):
        for g in c.get('goals', []):
            if g['id'] == gid:
                return g
    return None


def upto(lines, marker):
    return lines[:lines.index(marker)]


class ParserTest(unittest.TestCase):
    def test_events_of_real_run_shape(self):
        run, view, problems = build(RUN_LINES)
        self.assertEqual(problems, [])
        self.assertEqual(run.id, '20261111-200703')
        kinds = [e['type'] for e in run.events]
        self.assertEqual(kinds, ['zone', 'filter', 'level', 'zone', 'zone', 'level', 'zone', 'zone', 'reward', 'zone'])
        self.assertEqual([e['name'] for e in run.events if e['type'] == 'zone'],
                         ['Берег реки', 'Лагерь Клирфелл', 'Клирфелл', 'Лагерь Клирфелл', 'Клирфелл', 'Грельвуд'])
        rew = [e for e in run.events if e['type'] == 'reward'][0]
        self.assertEqual(rew['text'], '+10% к сопротивлению холоду')

    def test_new_start_resets_run_and_carries_filter(self):
        lines = RUN_LINES + zone('21:00:00', 1, 'G1_1', 'Берег реки')
        run, view, _ = build(lines)
        self.assertEqual(run.id, '20261111-210000')
        self.assertEqual([e['type'] for e in run.events], ['filter', 'zone'])
        self.assertEqual(view['zone']['name'], 'Берег реки')
        self.assertEqual(view['filter']['id'], 'base1')

    def test_zone_without_generating_line(self):
        lines = RUN_LINES + [src('20:45:00', 'Клирфелл')]
        run, view, _ = build(lines)
        self.assertEqual(view['zone']['code'], 'G1_2')

    def test_world_map_lines_do_not_change_zone(self):
        lines = RUN_LINES + [src('20:42:59', 'Акт 1'), src('20:45:36', 'Грельвуд')]
        run, view, _ = build(lines)
        self.assertEqual(view['zone']['name'], 'Грельвуд')
        self.assertEqual(len([e for e in run.events if e['type'] == 'zone']), 6)

    def test_lines_without_date_are_ignored(self):
        self.assertEqual(core.LogParser().feed('просто текст'), [])
        self.assertEqual(core.LogParser().feed(''), [])

    def test_character_screen_starts_a_session(self):
        # Экран выбора персонажа игра пишет как сцену без имени: это граница сессии одного героя.
        parser = core.LogParser()
        self.assertEqual([e['type'] for e in parser.feed(src('22:00:00', '(unknown)'))], ['session'])
        # Счёт вознесений снимается и возвращается — вместе с героем, к забегу которого вернулись.
        parser.feed(ascend('22:01:00', 'AscendancySorceress3Small1'))
        state = parser.ascension_state()
        parser.set_ascension_state(None)
        self.assertEqual([e['n'] for e in ascends(parser.feed(ascend('22:02:00', 'AscendancySorceress3Small2')))], [1])
        parser.set_ascension_state(state)
        self.assertEqual(ascends(parser.feed(ascend('22:03:00', 'AscendancySorceress3Small2'))), [])
        self.assertEqual([e['n'] for e in ascends(parser.feed(ascend('22:04:00', 'AscendancySorceress3Small3')))], [2])
        # сама строка экрана забегу ничего не меняет
        _, view, _ = build(RUN_LINES + [src('20:41:00', '(unknown)')])
        self.assertEqual((view['zone']['name'], view['hero']['level']), ('Грельвуд', 3))

    def test_time_stops_while_the_hero_is_out_of_the_game(self):
        # Чистое время забега — без отрезков, когда героя не было в игре: вышел к списку героев (сцена
        # без имени) или игру закрыли (перед строкой запуска герой вышел не позже предыдущей строки).
        lines = (zone('20:00:00', 1, 'G1_1', 'Берег реки')
                 + zone('20:10:00', 2, 'G1_2', 'Клирфелл')
                 + [src('20:15:00', '(unknown)')]
                 + zone('20:45:00', 15, 'G1_town', 'Лагерь Клирфелл')
                 + ['%s 21:00:00 1000 abcd [INFO Client 1] обычная строка' % DAY,
                    '%s 23:00:00 ***** LOG FILE OPENING *****' % DAY]
                 + zone('23:05:00', 4, 'G1_4', 'Грельвуд'))
        run, view, _ = build(lines)
        self.assertEqual([e['type'] for e in run.events if e['type'] != 'zone'], ['leave', 'session', 'leave'])
        # 3 ч 05 мин по часам, из них вне игры 30 мин и 2 ч 05 мин
        self.assertEqual((view['run']['active'], view['run']['paused']), (1800, False))
        # шаги: на какой минуте чистого времени пришли и сколько провели
        self.assertEqual({c['id']: (c['at'], c['took']) for c in view['cards']},
                         {'riverbank': (0, 600), 'clearfell': (600, 1200), 'grelwood': (1800, 0), 'tangle': (None, None)})
        # герой снова вышел — время стоит
        _, view, _ = build(lines + [src('23:20:00', '(unknown)')])
        self.assertEqual((view['run']['active'], view['run']['paused']), (2700, True))
        self.assertEqual(next(c['took'] for c in view['cards'] if c['id'] == 'grelwood'), 900)
        # обычное закрытие игры видно сразу, по её собственной строке — запуска ждать не нужно;
        # та же фраза в чате (после имени) выходом не считается, а запуск после закрытия второй раз не считается
        closing = '%s 23:20:00 1000 abcd [INFO Client 1] Closing game gracefully' % DAY
        _, view, _ = build(lines + [say('23:10:00', 'Прохожий', 'Closing game gracefully'), closing])
        self.assertEqual((view['run']['active'], view['run']['paused']), (2700, True))
        run, view, _ = build(lines + [closing, '%s 23:50:00 ***** LOG FILE OPENING *****' % DAY])
        self.assertEqual([e['ts'] for e in run.events if e['type'] == 'leave'][-1], core.line_ts(closing))
        self.assertEqual(len([e for e in run.events if e['type'] == 'leave']), 3)
        # новый герой: прежний забег на этом заканчивается, у нового время с нуля
        fresh, view, _ = build(lines + zone('23:30:00', 1, 'G1_1', 'Берег реки'))
        self.assertEqual((fresh.id, view['run']['active']), ('20261111-233000', 0))

    def test_time_targets_for_step_act_and_stretch(self):
        # Цель по времени: у шага — из плана, у акта и отрезка — сумма целей их шагов. Отрезок — этап
        # билда: от одной смены направления до другой. passed — сколько план отводил на уже пройденные
        # шаги: по нему страница считает запас и отставание.
        steps = [dict(s) for s in PLAN['steps']]
        steps[0].update(target='5:00')
        steps[1].update(target='10:00')
        steps[2].update(target=90)
        plan = dict(PLAN, steps=steps, timeWarn=0.5, stages=[{'id': 'start', 'name': 'До вознесения'}])
        lines = (zone('20:00:00', 1, 'G1_1', 'Берег реки') + zone('20:04:00', 2, 'G1_2', 'Клирфелл')
                 + zone('20:20:00', 4, 'G1_4', 'Грельвуд') + [lvl('20:21:00', 2)])
        _, view, problems = build(lines, plan=plan)
        self.assertEqual(problems, [])
        t = view['time']
        self.assertEqual((t['warn'], t['step']), (0.5, {'spent': 60, 'away': 0, 'target': 90, 'live': True, 'busy': None}))
        self.assertEqual({k: t['stretch'][k] for k in ('name', 'spent', 'target', 'passed', 'steps', 'done')},
                         {'name': 'До вознесения', 'spent': 1260, 'target': 990, 'passed': 900, 'steps': 4, 'done': 2})
        self.assertEqual({k: t['act'][k] for k in ('name', 'spent', 'target', 'passed')},
                         {'name': 'Акт 1', 'spent': 1260, 'target': 990, 'passed': 900})
        self.assertEqual([(a['name'], a['state'], a['done'], a['steps']) for a in view['acts']],
                         [('Акт 1', 'current', 2, 4)])
        self.assertEqual([c['target'] for c in view['cards']], [300, 600, 90, None])
        # второй этап делит маршрут на два отрезка: у каждого свои шаги и своя сумма целей
        two = dict(plan, stages=[{'id': 'start', 'name': 'До вознесения'}, {'id': 'late', 'from': 'grelwood', 'name': 'После'}])
        t = build(lines, plan=two)[1]['time']
        self.assertEqual({k: t['stretch'][k] for k in ('name', 'spent', 'target', 'passed', 'steps', 'done')},
                         {'name': 'После', 'spent': 60, 'target': 90, 'passed': 0, 'steps': 2, 'done': 0})
        # без целей и этапов в плане — время есть, целей и отрезка нет
        _, view, _ = build(lines)
        self.assertEqual((view['time']['step'], view['time']['stretch'], view['time']['act']['target']),
                         ({'spent': 60, 'away': 0, 'target': None, 'live': True, 'busy': None}, None, None))
        # кривая цель и прежнее поле отрезка на шаге — замечания к плану
        steps[3].update(target='пять минут', stretch='Потом')
        _, _, problems = build(lines, plan=dict(PLAN, steps=steps))
        self.assertEqual(problems, ['Шаг «tangle»: target — время вида 5:30 или 1:05:00',
                                    'Шаг «tangle»: поле stretch больше не читается — отрезок задаёт этап билда (stages)'])
        self.assertEqual([core.parse_clock(x) for x in ('5:30', '1:05:00', '75:00', 45, '5:75', '', None, True)],
                         [330, 3900, 4500, 45, None, None, None, None])

    def test_level_out_of_order_means_another_hero(self):
        # Уровни одного героя идут подряд: «9» после «3» — в забег попали события другого героя.
        _, view, _ = build(RUN_LINES)
        self.assertIsNone(view['stranger'])
        _, view, _ = build(RUN_LINES + [lvl('21:00:00', 9)])
        self.assertEqual((view['stranger']['level'], view['stranger']['after']), (9, 3))

    def test_only_the_awaited_line_of_the_chat_becomes_an_event(self):
        # Реплика персонажа игры выглядит в логе так же, как чат игроков, поэтому событием становится
        # только та, которую ждёт план, и в событии хранятся коды строк таблицы игры, а не строка лога.
        done = say('22:00:10', 'Сехема Асала', '<<set:F>><<set:S>><<set:FS>>Дело сделано.')
        self.assertEqual(core.LogParser().feed(done), [])
        self.assertEqual(core.LogParser(['SehemaDone']).feed(done), [])        # без таблицы реплик кода не узнать
        parser = core.LogParser(['SehemaDone'], TEXT)
        self.assertEqual([(e['type'], e['ids']) for e in parser.feed(done)], [('say', ['SehemaDone'])])
        # тот же текст есть и у других NPC: чужой голос не засчитывается
        self.assertEqual(parser.feed(say('22:00:11', 'Прохожий', 'Дело сделано.')), [])
        self.assertEqual(parser.feed(say('22:00:12', 'Сехема Асала', 'Никакой пощады!')), [])
        self.assertEqual(parser.feed(say('22:00:13', '#Прохожий', 'Сехема Асала: Дело сделано.')), [])
        # текст, который во всей игре есть только у ожидаемой строки, засчитывается и под другим именем:
        # голос тот же, а в логе бывает другое имя («Тихо, Чёрный претор» вместо Дрейвена)
        parser.watch = ['HoodedPiece1']
        line = say('22:00:14', 'Тень', '<<set:F>>Теперь мы должны найти остальные. Поспеши.')
        self.assertEqual([e['ids'] for e in parser.feed(line)], [['HoodedPiece1']])

    def test_failed_filter_load_is_not_current(self):
        run, view, _ = build(RUN_LINES + [flt('20:41:00', 'broken', 'false')])
        self.assertEqual(view['filter']['id'], 'base1')
        self.assertIn('Фильтр не загрузился: broken', [h['text'] for h in view['history']])

    def test_first_ascendancy_node_is_the_ascension(self):
        # Взятие узла дерева восхождения пишется в лог; вознесение — первый такой узел забега.
        parser = core.LogParser()
        first = parser.feed(ascend('23:30:00'))
        self.assertEqual([e['type'] for e in first], ['passive', 'ascend'])   # клик по дереву и само вознесение
        self.assertEqual(ascends(parser.feed(ascend('23:30:05', 'AscendancySorceress3Notable2'))), [])
        # снятый узел и узел обычного дерева вознесением не считаются
        self.assertEqual(ascends(parser.feed(ascend('23:31:00').replace('allocated', 'unallocated'))), [])
        self.assertEqual(ascends(parser.feed(ascend('23:31:10', 'spirit12'))), [])
        # новый персонаж — новый отсчёт
        parser.feed(gen('23:40:00', 1, 'G1_1'))
        self.assertEqual([e['type'] for e in ascends(parser.feed(ascend('23:59:00')))], ['ascend'])

    def test_third_ascendancy_node_is_the_second_ascension(self):
        # Испытание даёт два очка восхождения. Третий взятый узел — уже второе вознесение (испытание
        # Хаоса), пятый — третье. Перекачка (сняли узел, взяли другой) новым вознесением не считается.
        parser = core.LogParser()
        node = lambda t, name, did='allocated': ascend(t, 'AscendancySorceress3' + name).replace('allocated', did)
        self.assertEqual([e.get('n') for e in ascends(parser.feed(node('08:43:13', 'Notable8')))], [1])
        self.assertEqual(ascends(parser.feed(node('08:43:14', 'Notable13'))), [])
        self.assertEqual(ascends(parser.feed(node('09:00:00', 'Notable13', 'unallocated'))), [])
        self.assertEqual(ascends(parser.feed(node('09:00:01', 'Notable5'))), [])
        second = parser.feed(node('20:07:52', 'Notable9'))
        self.assertEqual([(e['type'], e['n']) for e in ascends(second)], [('ascend', 2)])
        self.assertEqual(ascends(parser.feed(node('20:07:54', 'Notable16'))), [])
        self.assertEqual([e['n'] for e in ascends(parser.feed(node('23:00:00', 'Small1')))], [3])


def tree_click(t, node, name, did='allocated'):
    return ('%s %s 1000 abcd [INFO Client 1] Successfully %s passive skill id: %s, name: %s'
            % (DAY, t, did, node, name))


def tree_points(t):
    """Награда «+2 очка» приходит двумя строками в одну секунду: обычные очки и очки набора оружия."""
    return ['%s %s 1000 abcd [INFO Client 1] : Вы получили очков пассивных умений: 2.' % (DAY, t),
            '%s %s 1000 abcd [INFO Client 1] : Вы получили 2 очка пассивных умений для набора оружия.' % (DAY, t)]


# Дерево: две версии. Какая действует, говорят этапы билда: первый — с самого начала, второй —
# с Красной Долины (как перекачка после вознесения).
TREE = dict(ROUTE, stages=[
    {'id': 'start', 'name': 'До вознесения', 'tree': 'start'},
    {'id': 'after', 'from': 'redvale', 'name': 'После вознесения', 'tree': 'minions'},
], tree={'phases': [
    {'id': 'start', 'name': 'До вознесения', 'nodes': [
        {'id': 'spells18', 'name': 'Урон чарами'},
        {'id': 'intelligence11', 'name': 'Характеристика', 'kind': 'attribute', 'attr': 'инт'},
        {'id': 'notable1', 'name': 'Необузданная мощь', 'kind': 'notable'},
        {'id': 'cold2', 'name': 'Урон от стихий'},
        {'id': 'cold3', 'name': 'Урон от стихий'}]},
    {'id': 'minions', 'name': 'После вознесения', 'nodes': [
        {'id': 'spells18', 'name': 'Урон чарами'},
        {'id': 'minion1', 'name': 'Урон приспешников'},
        {'id': 'minion2', 'name': 'Урон приспешников'}]},
]})


class TreeTest(unittest.TestCase):
    def test_log_tells_every_tree_click_and_the_points(self):
        parser = core.LogParser()
        ev = parser.feed(tree_click('20:10:00', 'jewel_slot1969', 'Гнездо для [Jewel|самоцвета]'))
        self.assertEqual(ev, [{'type': 'passive', 'ts': ev[0]['ts'], 'op': 'take', 'id': 'jewel_slot1969',
                               'name': 'Гнездо для самоцвета'}])
        ev = parser.feed(tree_click('20:10:05', 'jewel_slot1969', 'Гнездо для [Jewel|самоцвета]', 'unallocated'))
        self.assertEqual([(e['type'], e['op'], e['id']) for e in ev], [('passive', 'drop', 'jewel_slot1969')])
        # награда: две строки в одну секунду — обычные очки и очки набора оружия; награда для целей одна
        a, b = tree_points('20:11:00')
        self.assertEqual([(e['type'], e.get('n'), e.get('weapon')) for e in parser.feed(a)],
                         [('points', 2, False), ('reward', None, None)])
        self.assertEqual([(e['type'], e.get('n'), e.get('weapon')) for e in parser.feed(b)], [('points', 2, True)])

    def test_queue_and_free_points(self):
        # герой 3 уровня: два очка за уровни; дерева ещё не трогал
        _, view, problems = build(RUN_LINES, plan=TREE)
        self.assertEqual(problems, [])
        t = view['tree']
        self.assertEqual((t['phase'], t['taken'], t['total'], t['free'], t['extra']), ('До вознесения', 0, 5, 2, 0))
        self.assertEqual([(n['id'], n['kind'], n['attr']) for n in t['next']][:3],
                         [('spells18', 'small', None), ('intelligence11', 'attribute', 'инт'), ('notable1', 'notable', None)])
        # взял два узла по плану: очков не осталось, очередь сдвинулась
        lines = RUN_LINES + [tree_click('20:41:00', 'spells18', 'Урон чарами'),
                             tree_click('20:41:02', 'intelligence11', 'Характеристика')]
        t = build(lines, plan=TREE)[1]['tree']
        self.assertEqual((t['taken'], t['free'], [n['id'] for n in t['next']]), (2, 0, ['notable1', 'cold2', 'cold3']))
        # награда «+2 очка» даёт два обычных очка; очки набора оружия в счёт не идут
        t = build(lines + tree_points('20:42:00'), plan=TREE)[1]['tree']
        self.assertEqual(t['free'], 2)
        # узел, взятый за очко набора оружия (повторный клик по взятому — назначение набору), очков не ест
        extra = lines + tree_points('20:42:00') + [
            tree_click('20:43:00', 'notable1', 'Необузданная мощь'), tree_click('20:43:01', 'cold2', 'Урон от стихий'),
            tree_click('20:43:02', 'cold3', 'Урон от стихий'), tree_click('20:43:03', 'cold3', 'Урон от стихий')]
        t = build(extra, plan=TREE)[1]['tree']
        self.assertEqual((t['taken'], t['total'], t['free'], t['next']), (5, 5, 0, []))
        # узлы восхождения в дерево не входят: у них свои очки
        t = build(lines + [ascend('20:44:00')], plan=TREE)[1]['tree']
        self.assertEqual((t['taken'], t['free']), (2, 0))
        # узлы дерева атласа игра пишет той же строкой — в дерево героя они тоже не входят:
        # ни в свободные очки, ни в «лишнее»; что взято в атласе, страница знает отдельно
        atlas = lines + tree_points('20:42:00') + [
            tree_click('20:45:00', 'AtlasEssenceNotable2', 'Заточённые чудища'),
            tree_click('20:45:01', 'AtlasGenericSmall71', 'Шанс появления Сущностей'),
            tree_click('20:45:02', 'AtlasGenericSmall71', 'Шанс появления Сущностей', 'unallocated')]
        view = build(atlas, plan=TREE)[1]
        self.assertEqual((view['tree']['taken'], view['tree']['free'], view['tree']['extra'], len(view['tree']['have'])), (2, 2, 0, 2))
        a = view['atlas']
        self.assertEqual(a['have'], ['AtlasEssenceNotable2'])
        # плана атласа в билде нет: раздел всё равно отдаётся — что взято, видно и без плана; версии целиком
        # страница маршрута не получает: их правят на странице «Билд»
        self.assertEqual((a['open'], a['plan'], a['now'], a['total'], a['extra']), (True, [], None, 0, 1))
        self.assertNotIn('versions', a)
        self.assertNotIn('names', a)

    def test_page_knows_when_new_points_came(self):
        """Очки дерева приходят с новым уровнем и с наградой «+N очков» — их время (gainAt) страница берёт для окна
        «куда вложить очки». Очки набора оружия, клики по дереву и снятые узлы (очко вернулось) времени не меняют."""
        at = lambda line: core.LogParser().feed(line)[0]['ts']
        t = build(RUN_LINES, plan=TREE)[1]['tree']
        self.assertEqual((t['gainAt'], t['free']), (at(lvl('20:15:53', 3)), 2))
        lines = RUN_LINES + tree_points('20:42:00')
        t = build(lines, plan=TREE)[1]['tree']
        self.assertEqual((t['gainAt'], t['free']), (at(tree_points('20:42:00')[0]), 4))
        # взял узел, потом снял его: очко вернулось, но нового не пришло
        lines += [tree_click('20:43:00', 'spells18', 'Урон чарами'),
                  tree_click('20:43:30', 'spells18', 'Урон чарами', 'unallocated'),
                  '%s 20:44:00 1000 abcd [INFO Client 1] : Вы получили 2 очка пассивных умений для набора оружия.' % DAY]
        t = build(lines, plan=TREE)[1]['tree']
        self.assertEqual((t['gainAt'], t['free']), (at(tree_points('20:42:00')[0]), 4))
        t = build(lines + [lvl('20:50:00', 4)], plan=TREE)[1]['tree']
        self.assertEqual((t['gainAt'], t['free']), (at(lvl('20:50:00', 4)), 5))
        # герой ещё не получал очков — времени нет
        self.assertIsNone(build(RUN_LINES[:2], plan=TREE)[1]['tree']['gainAt'])

    def test_atlas_plan_is_a_tree_of_its_own(self):
        """Дерево атласа записано в билде разделом atlas — версии с порядком узлов, как у дерева героя.
        Что взято, пишет лог (id узлов начинаются с Atlas). Очков свободных не считаем: игра их не пишет."""
        nodes = [{'id': 'AtlasGenericSmall71', 'name': 'Шанс появления Сущностей'},
                 {'id': 'AtlasEssenceNotable2', 'name': 'Заточённые чудища', 'kind': 'notable'},
                 {'id': 'AtlasBreachSmall16', 'name': 'Объём крови улья'}]
        plan = dict(TREE, atlas={'phases': [
            {'id': 'a1', 'name': 'Атлас', 'nodes': nodes},
            {'id': 'a2', 'name': 'Позже', 'nodes': nodes[:1]},
            {'id': 'bad', 'name': 'Мимо', 'nodes': nodes[:1] + nodes[:1]}]},
            stages=[dict(TREE['stages'][0], atlas='a1'), dict(TREE['stages'][1], atlas='a2'),
                    {'id': 'lost', 'from': 'tangle', 'name': 'Мимо', 'atlas': 'nope'}])
        lines = RUN_LINES + [tree_click('20:41:10', 'AtlasGenericSmall71', 'Шанс появления Сущностей'),
                             tree_click('20:41:15', 'AtlasRitualSmall4', 'Увеличение дани')]
        _, view, problems = build(lines, plan=plan)
        self.assertEqual(problems, ['Атлас, версия «bad»: узел «AtlasGenericSmall71» записан дважды',
                                    'Этап «lost»: версии атласа «nope» в билде нет'])
        a = view['atlas']
        # до шага «Красная Долина» действует первая версия; в кампании атлас ещё не открыт,
        # но взятые узлы (их пишет лог) открывают его сами
        self.assertEqual((a['now'], a['phase'], a['total'], a['taken'], a['extra'], a['open']), ('a1', 'Атлас', 3, 1, 1, True))
        self.assertEqual([(n['id'], n['kind']) for n in a['plan']],
                         [('AtlasGenericSmall71', 'small'), ('AtlasEssenceNotable2', 'notable'), ('AtlasBreachSmall16', 'small')])
        self.assertEqual(a['have'], ['AtlasGenericSmall71', 'AtlasRitualSmall4'])
        # дерево героя от узлов атласа не меняется
        self.assertEqual((view['tree']['taken'], view['tree']['extra']), (0, 0))
        # без единого узла атлас открывает первая зона после кампании
        _, view, _ = build(RUN_LINES, plan=plan)
        self.assertFalse(view['atlas']['open'])
        _, view, _ = build(RUN_LINES + zone('23:00:00', 65, 'G_Endgame_Town', 'Убежище в зиккурате'), plan=plan)
        self.assertTrue(view['atlas']['open'])

    def test_maps_start_where_the_atlas_opens(self):
        """Шаг на картах — с зоной после кампании (убежище, карта) или по уровню зоны (этапы карт); с первого
        такого шага у героя есть атлас. В маршруте без карт его нет."""
        self.assertIsNone(core.endgame_from(ROUTE['steps']))
        steps = ROUTE['steps'] + [{'id': 'maps', 'zone': 'G_Endgame_Town'}, {'id': 'maps-65', 'level': 65}]
        self.assertEqual(core.endgame_from(steps), len(ROUTE['steps']))
        self.assertEqual(core.endgame_from(ROUTE['steps'] + [{'id': 'maps-65', 'level': 65}]), len(ROUTE['steps']))

    def test_atlas_late_by_stage(self):
        """Очков атласа лог не пишет — темп задаёт этап: версия атласа этапа — то, что взять к его концу. На следующем
        этапе узел из версии прошлого этапа (если та версия другая), которого план ждёт и сейчас, а он не взят,
        опаздывает. Новые узлы этапа не опаздывают; узел цели с условием — тоже (срок у цели свой); этап, который
        атлас не менял, опоздания не даёт."""
        nodes = [{'id': 'AtlasA1', 'name': 'Первый'}, {'id': 'AtlasA2', 'name': 'Второй', 'kind': 'notable'},
                 {'id': 'AtlasA3', 'name': 'Третий'}, {'id': 'AtlasB1', 'name': 'Бездна'}, {'id': 'AtlasA4', 'name': 'Снят'}]
        plan = dict(TREE, goals=ROUTE['goals'] + [{'id': 'take-third', 'title': 'Третий', 'node': 'AtlasA3'}],
                    stages=[dict(TREE['stages'][0], atlas='a1'), dict(TREE['stages'][1], atlas='a2')],
                    atlas={'phases': [{'id': 'a1', 'name': 'Первые', 'nodes': nodes[:3] + nodes[4:]},
                                      {'id': 'a2', 'name': 'Дальше', 'nodes': nodes[:4]}]})
        lines = RUN_LINES + [tree_click('20:41:10', 'AtlasA1', 'Первый')]
        # первый этап: опаздывать нечему
        _, view, problems = build(lines, plan=plan)
        self.assertEqual((problems, view['atlas']['now'], view['atlas']['late']), ([], 'a1', []))
        # второй этап (с Красной Долины): «Второй» был в версии первого этапа и не взят — опаздывает; «Третий» ждёт
        # своей цели; «Бездна» — новый узел этапа; «Снят» из плана убран — его не ждут
        later = lines + zone('20:50:00', 6, 'G1_5', 'Красная Долина')
        a = build(later, plan=plan)[1]['atlas']
        self.assertEqual((a['now'], a['late']), ('a2', ['AtlasA2']))
        self.assertEqual(build(later + [tree_click('20:51:00', 'AtlasA2', 'Второй')], plan=plan)[1]['atlas']['late'], [])
        # второй этап атлас не меняет — версия та же, её срок не прошёл
        same = dict(plan, stages=[dict(TREE['stages'][0], atlas='a2'), TREE['stages'][1]])
        a = build(later, plan=same)[1]['atlas']
        self.assertEqual((a['now'], a['late']), ('a2', []))

    def test_atlas_fold_takes_the_league_by_time_and_checks_the_paths(self):
        """Атлас общий у героев одной лиги: взятое — свои клики, клики героев той же лиги и отметки игрока.
        Клики идут по времени (герои одной лиги играют и вперемешку), снятый узел уходит. Узел берут только
        рядом со взятым или с корнем: клик не рядом со взятым — в атласе есть взятое, которого лог не знает."""
        near = {'R': {'A'}, 'A': {'R', 'B'}, 'B': {'A', 'C'}, 'C': {'B', 'D'}, 'D': {'C'}}
        geo = {'near': near, 'roots': {'R'}, 'names': {'B': 'Бэ'}}

        def click(ts, nid, run=None, op='take'):
            return dict({'type': 'passive', 'ts': ts, 'op': op, 'id': nid, 'name': nid.lower()}, **({'run': run} if run else {}))
        own = [click(30, 'C')]
        # без атласа лиги — только свои клики, и первый же не рядом со взятым
        f = core.atlas_fold(own, geo)
        self.assertEqual((list(f['taken']), f['src'], f['gaps']), (['C'], {'C': None}, [{'id': 'C', 'name': 'c', 'run': None}]))
        # без данных атласа проверки нет — как было
        self.assertEqual(core.atlas_fold(own)['gaps'], [])
        # клики героя той же лиги: до своих и после (вперемешку); отменённый сразу клик снимает узел
        league = dict(geo, clicks=[click(10, 'A', 'r1'), click(20, 'B', 'r1'), click(40, 'D', 'r1'), click(41, 'D', 'r1', 'untake')])
        f = core.atlas_fold(own, league)
        self.assertEqual((list(f['taken']), f['src'], f['gaps']), (['A', 'B', 'C'], {'A': 'r1', 'B': 'r1', 'C': None}, []))
        # отметка игрока — раньше всех кликов; узел, взятый кликом лога, — уже не отметка
        f = core.atlas_fold(own + [click(50, 'D')], dict(geo, marks=['A', 'B']))
        self.assertEqual((f['taken'], f['src'], f['gaps']),
                         ({'A': 'A', 'B': 'Бэ', 'C': 'c', 'D': 'd'}, {'A': 'hand', 'B': 'hand', 'C': None, 'D': None}, []))
        f = core.atlas_fold([click(5, 'A')], dict(geo, marks=['A']))
        self.assertEqual(f['src'], {'A': None})

    def test_atlas_taken_before_the_hero_is_taken(self):
        """Взятое до героя (клики героев того же атласа, отметки игрока) взято на странице: в счёте «взято N из M»,
        на карте (have), в цели-узле; откуда каждый узел — before; сколько взял сам герой и сколько отметил
        игрок — own и hand."""
        nodes = [{'id': 'AtlasA1', 'name': 'Первый'}, {'id': 'AtlasA2', 'name': 'Второй', 'kind': 'notable'},
                 {'id': 'AtlasA3', 'name': 'Третий'}, {'id': 'AtlasA4', 'name': 'Четвёртый'}]
        plan = dict(TREE, goals=ROUTE['goals'] + [{'id': 'take-second', 'title': 'Второй', 'node': 'AtlasA2'}],
                    stages=[dict(TREE['stages'][0], atlas='a1'), TREE['stages'][1]],
                    atlas={'phases': [{'id': 'a1', 'name': 'Атлас', 'nodes': nodes}]})
        run, view, problems = build(RUN_LINES + [tree_click('20:41:10', 'AtlasA3', 'Третий')], plan=plan)
        self.assertEqual(problems, [])
        a = view['atlas']
        self.assertEqual((a['taken'], a['own'], a['hand'], a['have'], a['before'], a['gaps']), (1, 1, 0, ['AtlasA3'], {}, []))
        self.assertNotEqual(goal(view, 'take-second')['urgency'], 'done')
        prev = [{'type': 'passive', 'ts': 1, 'op': 'take', 'id': i, 'name': n, 'run': 'r1'}
                for i, n in (('AtlasA1', 'Первый'), ('AtlasA2', 'Второй'), ('AtlasX9', 'Вне плана'))]
        view = core.derive(core.norm_plan(plan)[0], run, 0, atlas_league={'clicks': prev, 'marks': ['AtlasA4']})
        a = view['atlas']
        self.assertEqual((a['taken'], a['total'], a['own'], a['hand'], a['extra']), (4, 4, 1, 1, 1))
        self.assertEqual(a['have'], ['AtlasA4', 'AtlasA1', 'AtlasA2', 'AtlasX9', 'AtlasA3'])
        self.assertEqual(a['before'], {'AtlasA4': 'hand', 'AtlasA1': 'r1', 'AtlasA2': 'r1', 'AtlasX9': 'r1'})
        self.assertEqual(goal(view, 'take-second')['urgency'], 'done')

    def test_map_gets_the_whole_phase_and_the_default_attribute(self):
        """Карте нужен весь порядок этапа и всё взятое; атрибут узла «Характеристика» — общий для дерева,
        если у самого узла он не назван."""
        nodes = TREE['tree']['phases'][0]['nodes'][:2] + [
            {'id': 'attributes13', 'name': 'Характеристика', 'kind': 'attribute'},
            {'id': 'attributes14', 'name': 'Характеристика', 'kind': 'attribute', 'attr': 'сил'}]
        plan = dict(ROUTE, stages=[{'id': 's', 'name': 'Старт', 'tree': 'start'}],
                    tree={'attr': 'инт', 'phases': [{'id': 'start', 'name': 'Начало', 'nodes': nodes}]})
        lines = RUN_LINES + [tree_click('20:41:00', 'spells18', 'Урон чарами'), tree_click('20:41:02', 'other7', 'Чужой узел')]
        t = build(lines, plan=plan)[1]['tree']
        self.assertEqual([(n['id'], n['attr']) for n in t['plan']],
                         [('spells18', None), ('intelligence11', 'инт'), ('attributes13', 'инт'), ('attributes14', 'сил')])
        self.assertEqual((t['have'], t['extra']), (['spells18', 'other7'], 1))

    def test_next_phase_asks_to_drop_what_it_does_not_have(self):
        lines = RUN_LINES + [tree_click('20:41:00', 'spells18', 'Урон чарами'),
                             tree_click('20:41:02', 'intelligence11', 'Характеристика')]
        # дошли до шага, с которого действует второй этап: общий узел остаётся, лишний надо снять
        lines += RUN_TAIL[:9] + zone('20:49:14', 5, 'G1_5', 'Красная Долина')
        _, view, _ = build(lines, plan=TREE)
        t = view['tree']
        self.assertEqual(view['step']['id'], 'redvale')
        self.assertEqual((t['phase'], t['taken'], t['total'], t['extra'], t['free']), ('После вознесения', 1, 3, 1, 0))
        self.assertEqual([n['id'] for n in t['next']], ['minion1', 'minion2'])
        # снял лишний узел — очко освободилось, лишнего нет
        t = build(lines + [tree_click('20:50:00', 'intelligence11', 'Характеристика', 'unallocated')], plan=TREE)[1]['tree']
        self.assertEqual((t['extra'], t['free']), (0, 1))

    def test_node_of_a_goal_waits_for_the_goal(self):
        """Узел, взять который — отдельная цель со своим условием (поле node у цели), по очереди очков
        не берут: в очередь он не идёт, страница получает его отдельно — названием цели.
        Взят узел в игре — цель закрылась сама."""
        goals = ROUTE['goals'] + [{'id': 'take-power', 'title': 'Необузданная мощь (Raw Power)', 'node': 'notable1'}]
        plan = dict(TREE, goals=goals)
        lines = RUN_LINES + [tree_click('20:41:00', 'spells18', 'Урон чарами')]
        _, view, problems = build(lines, plan=plan)
        self.assertEqual(problems, [])
        t = view['tree']
        # одно очко свободно, но узел цели в очереди не стоит — ни первым, ни вообще
        self.assertEqual((t['free'], [n['id'] for n in t['next']]), (1, ['intelligence11', 'cold2', 'cold3']))
        self.assertEqual(t['held'], [{'id': 'notable1', 'name': 'Необузданная мощь (Raw Power)', 'kind': 'notable',
                                      'goal': 'take-power'}])
        self.assertEqual((t['taken'], t['total']), (1, 5))
        g = goal(view, 'take-power')
        self.assertEqual((g['urgency'], g['auto'], g['locked']), ('seek', True, False))
        # взял узел в игре: он больше не ждёт, цель отмечена логом
        _, view, _ = build(lines + [tree_click('20:42:00', 'notable1', 'Необузданная мощь')], plan=plan)
        t = view['tree']
        self.assertEqual((t['held'], t['taken'], [n['id'] for n in t['next']]), ([], 2, ['intelligence11', 'cold2', 'cold3']))
        g = goal(view, 'take-power')
        self.assertEqual((g['urgency'], g['locked']), ('done', True))
        # этап, где этого узла нет, его и не держит; у атласа — то же поле
        self.assertEqual(view['atlas']['held'], [])
        atlas = dict(plan, goals=goals + [{'id': 'take-beasts', 'title': 'Заточённые чудища', 'node': 'AtlasEssenceNotable2'}],
                     stages=[dict(TREE['stages'][0], atlas='a1'), TREE['stages'][1]],
                     atlas={'phases': [{'id': 'a1', 'name': 'Атлас', 'nodes': [
                         {'id': 'AtlasGenericSmall71', 'name': 'Шанс появления Сущностей'},
                         {'id': 'AtlasEssenceNotable2', 'name': 'Заточённые чудища', 'kind': 'notable'}]}]})
        _, view, problems = build(lines, plan=atlas)
        self.assertEqual(problems, [])
        self.assertEqual([(h['id'], h['goal']) for h in view['atlas']['held']], [('AtlasEssenceNotable2', 'take-beasts')])
        _, view, _ = build(lines + [tree_click('20:43:00', 'AtlasEssenceNotable2', 'Заточённые чудища')], plan=atlas)
        self.assertEqual((view['atlas']['held'], goal(view, 'take-beasts')['urgency']), ([], 'done'))
        # в плане: node — строка, и у узла одна цель
        bad = dict(TREE, goals=goals + [{'id': 'twin', 'title': 'Двойник', 'node': 'notable1'},
                                        {'id': 'empty', 'title': 'Пусто', 'node': ''}])
        self.assertEqual(core.norm_plan(bad)[1], ['Цели «take-power» и «twin» привязаны к одному узлу дерева',
                                                  'Цель «empty»: node — id узла дерева, как в логе игры'])

    def test_stages_are_checked(self):
        """Этапы билда: шаг начала (у первого его нет — он действует с самого начала) и то, что этап
        меняет целиком: версия дерева, база защиты, атрибуты, статы. Кривой параметр отбрасывается —
        этап остаётся; этапы стоят по порядку шагов маршрута."""
        plan, problems = core.norm_plan(dict(TREE, stages=[
            {'id': 'start', 'name': 'Старт', 'tree': 'start', 'kind': 'str_armour', 'attrs': ['str'],
             'stats': ['life', {'id': 'es', 'cap': 6000}]},
            {'id': 'late', 'from': 'redvale', 'tree': 'minions', 'kind': 'int_armour', 'attrs': []},
            {'id': 'late', 'from': 'tangle', 'kind': 'int_armour'},
            {'id': 'same', 'from': 'redvale', 'kind': 'dex_armour'},
            {'id': 'lost', 'from': 'nowhere', 'kind': 'dex_armour'},
            {'id': 'early', 'from': 'clearfell', 'tree': 'nope', 'kind': '', 'attrs': 'str', 'stats': ['life', 'life', 7]},
            {'kind': 'str_armour'}]))
        self.assertEqual(problems, ['Этап «late» записан дважды',
                                    'Этап «same»: с шага «redvale» уже начинается другой этап',
                                    'Этап «lost»: нет шага «nowhere» (from)',
                                    'Этап «early»: версии дерева «nope» в билде нет',
                                    'Этап «early»: kind — род баз из данных игры (str_armour, int_armour, …)',
                                    'Этап «early»: attrs — список атрибутов из данных игры (str, dex, int)',
                                    'Этап «early»: стат «life» записан дважды',
                                    'Этап «early»: stats — список статов (id из таблицы статов данных игры)',
                                    'Этапы билда: у записи нет id'])
        self.assertEqual(plan['stages'], [
            {'id': 'start', 'name': 'Старт', 'tree': 'start', 'kind': 'str_armour', 'attrs': ['str'],
             'stats': [{'id': 'life'}, {'id': 'es', 'cap': 6000}]},
            {'id': 'early', 'from': 'clearfell', 'stats': [{'id': 'life'}]},
            {'id': 'late', 'from': 'redvale', 'tree': 'minions', 'kind': 'int_armour', 'attrs': []}])
        # этапов нет — нет и списка; первому этапу шаг начала не нужен
        self.assertEqual(core.norm_plan(ROUTE)[0]['stages'], [])
        self.assertEqual(core.norm_plan(dict(ROUTE, stages=[{'id': 'a', 'from': 'redvale'}]))[1],
                         ['Этап «a»: первый этап действует с самого начала — шаг начала (from) ему не нужен'])
        # прежние разделы билда больше не читаются: о них сказано, а не молча пропущено
        self.assertEqual(core.norm_plan(dict(ROUTE, stats=[{'id': 'life'}], defence=[]))[1],
                         ['Раздел stats больше не читается: статы — параметр этапа билда (stages)',
                          'Раздел defence больше не читается: база защиты — параметр этапа билда (stages)'])

    def test_stage_names_only_what_it_changes(self):
        """Этап называет только то, что на нём меняется: остальное действует как на прежнем."""
        plan = core.norm_plan(dict(TREE, stages=[
            {'id': 'start', 'name': 'Старт', 'tree': 'start', 'kind': 'str_armour', 'attrs': ['str'], 'stats': ['life']},
            {'id': 'mid', 'from': 'clearfell', 'name': 'Середина', 'stats': ['es', 'life']},
            {'id': 'late', 'from': 'redvale', 'name': 'Конец', 'tree': 'minions', 'attrs': []}]))[0]
        self.assertEqual(core.buildstage.per_step(plan), [0, 1, 1, 2, 2, 2, 2, 2][:len(plan['steps'])])
        got = [core.buildstage.at(plan, pos) for pos in (None, 0, 1, 3)]
        self.assertEqual([(g['id'], g['tree'], g['kind'], g['attrs'], [s['id'] for s in g['stats']], g['own']) for g in got], [
            ('start', 'start', 'str_armour', ['str'], ['life'], ['tree', 'kind', 'attrs', 'stats']),
            ('start', 'start', 'str_armour', ['str'], ['life'], ['tree', 'kind', 'attrs', 'stats']),
            ('mid', 'start', 'str_armour', ['str'], ['es', 'life'], ['stats']),
            ('late', 'minions', 'str_armour', [], ['es', 'life'], ['tree', 'attrs'])])
        # кто назвал действующее: дерево и атрибуты — сам этап, базу — первый, статы — второй
        self.assertEqual(got[3]['by'], {'tree': 2, 'kind': 0, 'attrs': 2, 'stats': 1})
        self.assertEqual(core.buildstage.version(plan, 'tree', 3)['id'], 'minions')
        self.assertEqual(core.buildstage.users(plan, 'tree'), {'start': ['Старт'], 'minions': ['Конец']})
        self.assertIsNone(core.buildstage.at(core.norm_plan(ROUTE)[0], 0))

    def test_tree_plan_is_checked(self):
        bad = dict(ROUTE, tree={'phases': [
            {'id': 'a', 'nodes': [{'id': 'x', 'name': 'Икс'}, {'id': 'x', 'name': 'Икс'}]},
            {'id': 'b', 'from': 'nowhere', 'nodes': []}]})
        plan, problems = core.norm_plan(bad)
        self.assertEqual(problems, ['Дерево, версия «a»: узел «x» записан дважды',
                                    'Дерево, версия «b»: поле from больше не читается — с какого шага версия '
                                    'действует, говорит этап билда (stages)'])
        self.assertEqual([n['id'] for n in plan['tree']['phases'][0]['nodes']], ['x'])
        # без плана дерева страница ничего о дереве не показывает
        self.assertIsNone(build(RUN_LINES, plan=ROUTE)[1]['tree'])
        # версии есть, но ни один этап их не назвал: плана на шаге нет
        t = build(RUN_LINES, plan=dict(TREE, stages=[]))[1]['tree']
        self.assertEqual((t['now'], t['phase'], t['total'], t['next']), (None, None, 0, []))
        self.assertNotIn('versions', t)


class DeriveTest(unittest.TestCase):
    def test_current_zone_and_hero(self):
        _, view, _ = build(RUN_LINES)
        self.assertEqual(view['zone']['name'], 'Грельвуд')
        self.assertEqual(view['zone']['level'], 4)
        self.assertFalse(view['zone']['town'])
        self.assertEqual(view['hero']['level'], 3)
        self.assertEqual(view['step']['id'], 'grelwood')
        self.assertEqual(view['step']['next'], 'Мрачные заросли')
        self.assertTrue(view['onStep'])
        self.assertEqual([r['state'] for r in view['route']], ['behind', 'behind', 'current', 'ahead'])

    def test_overdue_after_leaving_step(self):
        _, view, _ = build(RUN_LINES)
        self.assertEqual(goal(view, 'weapon-crossbow')['urgency'], 'overdue')
        self.assertEqual(goal(view, 'skill-bomb')['urgency'], 'overdue')
        self.assertEqual(sorted(g['id'] for g in view['overdue']), ['skill-bomb', 'weapon-crossbow'])

    def test_soft_goal_never_turns_red(self):
        _, view, _ = build(RUN_LINES)
        self.assertEqual(goal(view, 'helmet-any')['urgency'], 'due')

    def test_due_on_current_step_and_seek_ahead(self):
        _, view, _ = build(RUN_LINES)
        self.assertEqual(goal(view, 'amulet-1')['urgency'], 'due')
        _, early, _ = build(upto(RUN_LINES, gen('20:20:18', 15, 'G1_town')))
        self.assertEqual(early['zone']['name'], 'Клирфелл')
        self.assertEqual(goal(early, 'weapon-crossbow')['urgency'], 'due')
        self.assertEqual(goal(early, 'amulet-1')['urgency'], 'seek')
        self.assertEqual(early['overdue'], [])

    def test_town_keeps_step_of_the_zone_we_came_from(self):
        _, view, _ = build(upto(RUN_LINES, gen('20:33:10', 2, 'G1_2')))
        self.assertTrue(view['zone']['town'])
        self.assertEqual(view['step']['id'], 'clearfell')
        # ни списка «в городе», ни задач (строк текста) у шага нет: всё, что на шаге делают, — его цели; задачи из
        # плана, записанного раньше, не читаются
        self.assertEqual(('notes' in view['step'], 'town' in view['step']), (False, False))
        self.assertEqual([g['id'] for g in view['step']['goals']], ['weapon-crossbow', 'skill-bomb'])

    def test_act_labels(self):
        self.assertEqual(core.act_of('G1_13_2'), 'Акт 1')
        self.assertEqual(core.act_of('G2_10_1'), 'Акт 2')
        self.assertEqual(core.act_of('P3_1'), 'Интерлюдия 3')
        self.assertEqual(core.act_of('Sanctum_1_Foyer_1'), 'Прочее')
        self.assertEqual(core.act_of(None), 'Прочее')
        _, view, _ = build(RUN_LINES)
        self.assertEqual({c['act'] for c in view['cards']}, {'Акт 1'})

    def test_cards_for_every_step(self):
        _, view, _ = build(RUN_LINES, [('weapon-crossbow', 2)])
        cards = view['cards']
        self.assertEqual([c['id'] for c in cards], ['riverbank', 'clearfell', 'grelwood', 'tangle'])
        self.assertEqual([c['state'] for c in cards], ['behind', 'behind', 'current', 'ahead'])
        self.assertNotIn('notes', cards[1])
        self.assertEqual([g['urgency'] for g in cards[1]['goals']], ['done', 'overdue'])
        self.assertEqual(view['step']['id'], cards[2]['id'])
        # что дальше, страница берёт из следующей карточки: она в том же списке, по порядку маршрута
        self.assertEqual((view['pos'], cards[view['pos'] + 1]['name']), (2, cards[3]['name']))

    def test_skills_follow_the_route_and_supports_sit_with_their_skill(self):
        steps = PLAN['steps']
        plan = dict(PLAN, goals=[
            # в плане цели записаны вперемешку, как это бывает при дописывании
            {'id': 'sup-2', 'group': 'Навыки', 'title': 'Залповый огонь', 'for': 'flash', 'need': 'tangle'},
            {'id': 'flash', 'group': 'Навыки', 'title': 'Ослепляющая граната', 'need': 'grelwood'},
            {'id': 'sup-1', 'group': 'Навыки', 'title': 'Залповый огонь', 'for': 'fire', 'need': 'grelwood'},
            {'id': 'later', 'group': 'Навыки', 'title': 'Без срока'},
            {'id': 'fire', 'group': 'Навыки', 'title': 'Взрывная граната', 'need': 'clearfell'},
            {'id': 'bomb', 'group': 'Навыки', 'title': 'Морозная бомба', 'need': 'clearfell'},
            {'id': 'lvl', 'group': 'Уровень', 'title': '7 уровень', 'reach': 7, 'need': 'tangle'},
            {'id': 'orphan', 'group': 'Уровень', 'title': 'Чужой', 'for': 'fire'},
        ])
        _, view, problems = build(upto(RUN_LINES, gen('20:20:18', 15, 'G1_town')), plan=plan)
        self.assertEqual(problems, [])
        skills = view['groups'][0]
        self.assertEqual(skills['name'], 'Навыки')
        # умения по шагам маршрута, при равном шаге — как в плане; без срока — в конце
        self.assertEqual([g['id'] for g in skills['goals']], ['fire', 'bomb', 'flash', 'later'])
        self.assertEqual([[c['id'] for c in g['children']] for g in skills['goals']], [['sup-1'], [], ['sup-2'], []])
        self.assertEqual(goal(view, 'sup-2')['fullTitle'], 'Залповый огонь → Ослепляющая граната')
        self.assertEqual(goal(view, 'fire')['fullTitle'], 'Взрывная граната')
        # камень из другой группы остаётся в своей, но называет умение
        other = view['groups'][1]
        self.assertEqual([g['id'] for g in other['goals']], ['orphan', 'lvl'][::-1])
        self.assertEqual(goal(view, 'orphan')['fullTitle'], 'Чужой → Взрывная граната')
        # среди целей шага цель подписана полностью: камень поддержки называет своё умение
        self.assertEqual([(g['id'], g['fullTitle']) for g in view['cards'][2]['goals']],
                         [('flash', 'Ослепляющая граната'), ('sup-1', 'Залповый огонь → Взрывная граната')])

    def test_goals_of_a_step_are_those_due_on_it(self):
        """Что закрыть на шаге, говорит срок самой цели: отдельных списков («проверок») у шага нет. Босс — своим
        блоком; «любая вещь в слоте» — на плитке слота, а не среди целей шага. Список проверок из файла,
        записанного раньше, не читается вовсе — даже с целью, которой нет."""
        steps = [dict(s) for s in PLAN['steps']]
        steps[1] = dict(steps[1], gates=[{'title': 'Перед боссом', 'goals': ['weapon-sceptre', 'nope']}])
        goals = PLAN['goals'] + [{'id': 'boss-x', 'kind': 'boss', 'title': 'Страж', 'need': 'clearfell'}]
        plan, problems = core.norm_plan(dict(PLAN, steps=steps, goals=goals))
        self.assertEqual(problems, [])
        _, view, _ = build(upto(RUN_LINES, gen('20:33:10', 2, 'G1_2')), plan=dict(PLAN, steps=steps, goals=goals))
        self.assertEqual(view['step']['id'], 'clearfell')
        # срок на шаге у арбалета, шлема («любой») и бомбы: шлем — не цель шага
        self.assertEqual([g['id'] for g in view['step']['goals']], ['weapon-crossbow', 'skill-bomb'])
        self.assertEqual([g['id'] for g in view['step']['bosses']], ['boss-x'])
        self.assertNotIn('gates', view['step'])
        # у каждого шага — свои: на шаге без сроков целей нет
        self.assertEqual([[g['id'] for g in c['goals']] for c in view['cards']],
                         [[], ['weapon-crossbow', 'skill-bomb'], ['amulet-1'], ['weapon-sceptre', 'amulet-2']])

    def test_marks_close_goals(self):
        _, view, _ = build(RUN_LINES, [('weapon-crossbow', 2), ('skill-bomb', 2), ('helmet-any', 2)])
        self.assertEqual(view['overdue'], [])
        weapon = view['slots'][0]
        self.assertEqual(weapon['worn']['id'], 'weapon-crossbow')
        self.assertEqual(weapon['next']['id'], 'weapon-sceptre')
        # отметка рукой: нажатие на неё же её снимает (status есть, locked нет)
        self.assertEqual((weapon['worn']['status'], weapon['worn']['locked']), (2, False))
        helmet = view['slots'][1]
        self.assertEqual(helmet['worn']['id'], 'helmet-any')
        self.assertIsNone(helmet['next'])

    def test_unmark_returns_goal(self):
        _, view, _ = build(RUN_LINES, [('weapon-crossbow', 2), ('weapon-crossbow', 0)])
        self.assertEqual(goal(view, 'weapon-crossbow')['urgency'], 'overdue')
        self.assertIsNone(view['slots'][0]['worn'])

    def test_bag_mark_of_an_old_run_means_nothing(self):
        # Рюкзака нет: отметка «в рюкзаке» (статус 1), оставшаяся от прежних забегов, вещь слота не закрывает —
        # вещь либо надета, либо нет
        _, view, _ = build(RUN_LINES, [('amulet-2', 1)])
        amulet = view['slots'][2]
        self.assertEqual((amulet['worn'], amulet['bag'], amulet['next']['id']), (None, None, 'amulet-1'))
        self.assertEqual(amulet['chain'], ['amulet-1', 'amulet-2'])
        # надетая (статус 2) — закрывает и ступени под собой
        _, view, _ = build(RUN_LINES, [('amulet-2', 2)])
        self.assertEqual((view['slots'][2]['worn']['id'], view['slots'][2]['next']), ('amulet-2', None))

    def test_close_on_equip_keeps_earlier_goal_alive(self):
        _, view, _ = build(RUN_LINES, [('weapon-sceptre', 1)])
        self.assertEqual(view['slots'][0]['next']['id'], 'weapon-crossbow')
        _, view, _ = build(RUN_LINES, [('weapon-sceptre', 2)])
        self.assertEqual(view['slots'][0]['worn']['id'], 'weapon-sceptre')
        self.assertIsNone(view['slots'][0]['next'])
        self.assertEqual(view['overdue'][0]['id'], 'skill-bomb')

    def test_stash_slot_goal_is_done_when_found(self):
        # Скипетр копят до вознесения: нашёл — цель закрыта, слот сразу показывает, что искать дальше.
        plan = dict(PLAN)
        plan['slots'] = PLAN['slots'] + [{'id': 'sceptre', 'name': 'Скипетр', 'doneOn': 'find'}]
        plan['goals'] = PLAN['goals'] + [
            {'id': 'sc-any', 'slot': 'sceptre', 'title': 'Скипетр', 'need': 'tangle'},
            {'id': 'sc-spirit', 'slot': 'sceptre', 'title': 'Скипетр: префикс духа', 'need': 'tangle'},
            {'id': 'sc-minion', 'slot': 'sceptre', 'title': 'Скипетр: суффикс приспешников', 'need': 'tangle'},
        ]
        _, view, problems = build(RUN_LINES, [('sc-any', 1)], plan=plan)
        self.assertEqual(problems, [])
        slot = view['slots'][3]
        self.assertEqual((slot['worn']['id'], slot['worn']['urgency'], slot['worn']['find']), ('sc-any', 'done', True))
        self.assertEqual(slot['next']['id'], 'sc-spirit')
        due = [g for g in view['cards'][3]['goals'] if g['id'].startswith('sc-')]
        self.assertEqual([(g['id'], g['urgency'] == 'done') for g in due],
                         [('sc-any', True), ('sc-spirit', False), ('sc-minion', False)])
        self.assertEqual(view['history'][0]['text'], 'Скипетр: Скипетр — в рюкзаке')
        # Найден лучший: промежуточная цель закрыта, искать больше нечего.
        _, view, _ = build(RUN_LINES, [('sc-any', 1), ('sc-minion', 1)], plan=plan)
        slot = view['slots'][3]
        self.assertEqual(slot['worn']['id'], 'sc-minion')
        self.assertIsNone(slot['next'])
        # В обычном слоте находка цель не закрывает: вещь ещё надо надеть (а «в рюкзаке» больше не бывает).
        _, view, _ = build(RUN_LINES, [('weapon-crossbow', 1)], plan=plan)
        self.assertEqual((view['slots'][0]['worn'], view['slots'][0]['bag'], view['slots'][0]['next']['id']),
                         (None, None, 'weapon-crossbow'))
        # Цель может переопределить слот; неизвестное значение — замечание к плану.
        plan['goals'] = plan['goals'][:-1] + [dict(plan['goals'][-1], doneOn='equip')]
        _, view, _ = build(RUN_LINES, [('sc-minion', 1)], plan=plan)
        self.assertEqual((view['slots'][3]['bag'], view['slots'][3]['worn']), (None, None))
        plan['slots'] = PLAN['slots'] + [{'id': 'sceptre', 'name': 'Скипетр', 'doneOn': 'bag'}]
        _, _, problems = build(RUN_LINES, plan=plan)
        self.assertEqual(problems, ['«sceptre»: doneOn бывает только find или equip'])

    def test_history_is_newest_first(self):
        _, view, _ = build(RUN_LINES, [('weapon-crossbow', 2)])
        self.assertEqual(view['history'][0]['text'], 'Оружие: Арбалет — надето')
        self.assertEqual(view['history'][1]['text'], 'Грельвуд · зона 4')
        texts = [h['text'] for h in view['history']]
        self.assertIn('Награда: +10% к сопротивлению холоду', texts)
        self.assertIn('Фильтр: base1', texts)

    def test_plan_problems_are_reported(self):
        plan, problems = core.norm_plan({
            'slots': [{'id': 'weapon'}],
            'steps': [{'id': 'a', 'filter': 'ghost'}],
            'goals': [{'id': 'g', 'slot': 'hat', 'need': 'zzz'}],
            'filters': {'ghost': {'name': '', 'inGame': False}},       # фильтра шага в игре нет (так говорит сервер)
        })
        self.assertEqual(len(problems), 3)
        self.assertIn('Шаг «a»: фильтра «ghost» нет в игре', problems)

    def test_empty_run_does_not_break(self):
        plan, _ = core.norm_plan(PLAN)
        view = core.derive(plan, core.Run(), 0)
        self.assertIsNone(view['zone'])
        self.assertIsNone(view['step'])
        self.assertIsNone(view['pos'])
        self.assertEqual(view['hero']['level'], 1)
        self.assertIsNone(view['filter']['id'])


class RouteTest(unittest.TestCase):
    """Порядок шагов, повторные заходы в зону, условие по уровню, фильтр."""

    def step_after(self, lines):
        _, view, _ = build(lines, plan=ROUTE)
        return view['step']['id'] if view['step'] else None

    def test_peek_into_next_zone_stays_on_step(self):
        full = RUN_LINES + RUN_TAIL
        self.assertEqual(self.step_after(upto(full, gen('20:40:45', 4, 'G1_4'))), 'grelwood-1')
        self.assertEqual(self.step_after(upto(full, gen('20:49:14', 5, 'G1_5'))), 'grelwood-1')

    def test_same_zone_twice_in_route(self):
        full = RUN_LINES + RUN_TAIL
        self.assertEqual(self.step_after(upto(full, gen('21:13:41', 15, 'G1_town'))), 'redvale')
        self.assertEqual(self.step_after(upto(full, gen('21:20:41', 6, 'G1_6', 9))), 'grelwood-2')
        _, view, _ = build(full, plan=ROUTE)
        self.assertEqual(view['step']['id'], 'tangle')
        self.assertEqual(view['step']['next'], 'Кладбище Вечных')
        self.assertEqual([r['state'] for r in view['route']],
                         ['behind', 'behind', 'behind', 'behind', 'behind', 'current', 'ahead', 'ahead'])

    def test_revisit_step_comes_only_as_the_next_step(self):
        """Шаг повторного захода (его зона уже была у шага раньше) наступает только следующим: заход в его зону с
        дальнего шага — ради прежней цели (ещё одна попытка испытания Сехем), а не прыжок мимо шагов между ними."""
        plan = {'steps': [{'id': 'trial', 'zone': 'G2_13', 'name': 'Испытание Сехем'},
                          {'id': 'a', 'zone': 'G3_1', 'name': 'А'}, {'id': 'b', 'zone': 'G3_3', 'name': 'Б'},
                          {'id': 'trial-3', 'zone': 'G2_13', 'name': 'Испытание Сехем · третье'}], 'goals': []}
        lines = (zone('20:00:00', 22, 'G2_13', 'Испытание Сехем') + zone('20:10:00', 33, 'G3_1', 'Болото')
                 + zone('20:20:00', 22, 'G2_13', 'Испытание Сехем') + zone('20:40:00', 33, 'G3_1', 'Болото'))
        _, view, _ = build(lines, plan=plan)
        self.assertEqual(view['step']['id'], 'a')          # двадцать минут в испытании с шага «А» — шаг прежний
        lines += zone('20:50:00', 34, 'G3_3', 'Джунгли') + zone('21:00:00', 22, 'G2_13', 'Испытание Сехем')
        _, view, _ = build(lines, plan=plan)
        self.assertEqual(view['step']['id'], 'trial-3')    # с шага прямо перед ним — обычный переход

    def test_far_milestone_is_not_shown_as_next_step(self):
        lines = RUN_LINES + RUN_TAIL + zone('21:39:18', 7, 'G1_7', 'Кладбище Вечных')
        _, view, _ = build(lines, plan=ROUTE)
        self.assertEqual(view['step']['id'], 'cemetery')
        self.assertIsNone(view['step']['next'])
        self.assertTrue(view['route'][7]['far'])
        self.assertEqual(goal(view, 'gold')['urgency'], 'seek')
        _, view, _ = build(lines + zone('23:00:00', 22, 'G2_13', 'Испытание Сехем'), plan=ROUTE)
        self.assertEqual(view['step']['id'], 'ascension')
        self.assertEqual(goal(view, 'gold')['urgency'], 'due')

    def test_unknown_zone_puts_whole_plan_behind(self):
        _, view, _ = build(RUN_LINES + RUN_TAIL + zone('21:40:00', 3, 'G1_3', 'Грязевая нора'), plan=ROUTE)
        self.assertTrue(view['beyond'])
        self.assertFalse(view['onStep'])
        self.assertEqual(view['step']['id'], 'tangle')
        self.assertEqual(view['route'][5]['state'], 'behind')
        self.assertEqual(goal(view, 'gold')['urgency'], 'seek')

    def test_returning_to_earlier_zone_keeps_position(self):
        _, view, _ = build(RUN_LINES + RUN_TAIL + zone('21:40:00', 2, 'G1_2', 'Клирфелл'), plan=ROUTE)
        self.assertEqual(view['step']['id'], 'tangle')
        self.assertFalse(view['beyond'])
        self.assertFalse(view['onStep'])
        self.assertEqual(view['route'][5]['state'], 'current')

    def test_hero_level_gate(self):
        full = RUN_LINES + RUN_TAIL
        _, view, _ = build(full, plan=ROUTE)
        flash = goal(view, 'skill-flash')
        self.assertEqual(flash['urgency'], 'early')
        self.assertEqual(flash['heroLevel'], 6)
        self.assertEqual(view['ready'], [])
        _, view, _ = build(full + [lvl('21:35:00', 6)], plan=ROUTE)
        self.assertEqual(goal(view, 'skill-flash')['urgency'], 'due')
        self.assertEqual([g['id'] for g in view['ready']], ['skill-flash'])
        later = full + [lvl('21:35:00', 6)] + zone('21:50:00', 7, 'G1_7', 'Кладбище Вечных')
        _, view, _ = build(later, plan=ROUTE)
        self.assertEqual(goal(view, 'skill-flash')['urgency'], 'overdue')
        self.assertEqual(view['ready'], [])
        _, view, _ = build(later, [('skill-flash', 2)], plan=ROUTE)
        self.assertEqual(goal(view, 'skill-flash')['urgency'], 'done')

    def test_filter_tracking(self):
        full = RUN_LINES + RUN_TAIL
        _, view, _ = build(upto(full, flt('21:01:42', 'simple1')), plan=ROUTE)
        self.assertEqual(view['filter']['id'], 'base1')
        self.assertEqual(view['filter']['name'], 'Базовый')
        self.assertEqual(view['filter']['expected'], 'simple1')
        self.assertIs(view['filter']['match'], False)
        _, view, _ = build(full, plan=ROUTE)
        self.assertEqual(view['filter']['name'], 'Простой')
        self.assertNotIn('note', view['filter'])          # заметок о фильтрах больше нет: название — из самой игры
        self.assertIs(view['filter']['match'], True)
        _, view, _ = build(upto(full, gen('20:49:14', 5, 'G1_5')), plan=ROUTE)
        self.assertIsNone(view['filter']['expected'])
        self.assertIsNone(view['filter']['match'])

    def test_step_shows_its_filter(self):
        full = RUN_LINES + RUN_TAIL
        # на Грельвуде фильтр ещё не назначен
        _, view, _ = build(upto(full, gen('20:49:14', 5, 'G1_5')), plan=ROUTE)
        self.assertIsNone(view['step']['filter'])
        # вошли в Красную Долину со старым фильтром: шаг просит включить новый
        _, view, _ = build(upto(full, flt('21:01:42', 'simple1')), plan=ROUTE)
        self.assertEqual(view['step']['filter'], {'id': 'simple1', 'name': 'Простой', 'none': False, 'loaded': False, 'switch': True,
                                                  'missing': False})
        # фильтр загружен; на следующих шагах он тот же, смены нет
        _, view, _ = build(full, plan=ROUTE)
        self.assertEqual(view['step']['filter'], {'id': 'simple1', 'name': 'Простой', 'none': False, 'loaded': True, 'switch': False,
                                                  'missing': False})

    def test_filter_missing_from_the_game(self):
        """Фильтр шага есть в плане, а в игре его нет (игрок плана на него не подписан): строка фильтра и карточка шага
        говорят «нет в игре», а у кода фильтра с сайта есть страница — на ней подписываются."""
        full = RUN_LINES + RUN_TAIL
        plan = dict(ROUTE, filters=dict(ROUTE['filters'], simple1=dict(ROUTE['filters']['simple1'], inGame=False)))
        _, view, problems = build(upto(full, flt('21:01:42', 'simple1')), plan=plan)
        self.assertTrue(view['filter']['expectedMissing'])
        self.assertFalse(view['filter']['expectedPage'])          # «simple1» — не код фильтра с сайта
        self.assertTrue(view['step']['filter']['missing'])
        self.assertIn('Шаг «Красная Долина»: фильтра «Простой» нет в игре', problems)
        site = 'Ab3dE6gH'
        steps = [dict(s, filter=site) if s.get('filter') == 'simple1' else s for s in ROUTE['steps']]
        plan = dict(ROUTE, steps=steps, filters=dict(ROUTE['filters'], **{site: {'name': 'Сайт', 'inGame': False}}))
        _, view, _ = build(upto(full, flt('21:01:42', 'simple1')), plan=plan)
        self.assertTrue(view['filter']['expectedMissing'] and view['filter']['expectedPage'])
        self.assertEqual(view['filter']['expectedName'], 'Сайт')
        # папку фильтров игры не видно (inGame не известен) — «нет в игре» не говорится
        _, view, _ = build(full, plan=ROUTE)
        self.assertFalse(view['filter']['expectedMissing'])

    def test_pause_stops_the_clock(self):
        """«Пауза» игрока: время героя и шага стоит, пока он не нажмёт «Продолжить» или не зайдёт в боевую зону; город
        паузу не снимает; выход из игры во время паузы не вычитается дважды; список забегов считает так же."""
        plan = core.norm_plan(ROUTE)[0]
        run = core.Run('r', 1000)
        z = lambda ts, code: {'type': 'zone', 'ts': ts, 'code': code, 'level': 2, 'name': code}   # noqa: E731
        run.events = [z(1000, 'G1_1'), z(2000, 'G1_town'), z(5000, 'G1_2')]
        self.assertEqual(core.derive(plan, run, 6000)['run']['active'], 5000)
        # пауза в городе: город её не снимает, снимает вход в боевую зону (G1_2 в 5000)
        run.hold = [{'ts': 2500, 'on': True}]
        v = core.derive(plan, run, 6000)
        self.assertEqual((v['run']['active'], v['run']['held']), (5000 - 2500, False))
        # «Продолжить» раньше — пауза короче; повторная «Пауза» ничего не меняет
        run.hold = [{'ts': 2500, 'on': True}, {'ts': 2600, 'on': True}, {'ts': 3000, 'on': False}]
        self.assertEqual(core.derive(plan, run, 6000)['run']['active'], 5000 - 500)
        # пауза не снята: часы стоят
        run.hold = [{'ts': 5500, 'on': True}]
        v = core.derive(plan, run, 6000)
        self.assertEqual((v['run']['active'], v['run']['held'], v['run']['paused']), (4500, True, True))
        self.assertEqual(core.clean_time(run.events, run.started, 6000, run.hold), 4500)
        # выход из игры во время паузы не вычитается дважды
        run.events = [z(1000, 'G1_1'), {'type': 'leave', 'ts': 2200}, z(2400, 'G1_town'), z(5000, 'G1_2')]
        run.hold = [{'ts': 2100, 'on': True}]
        self.assertEqual(core.derive(plan, run, 6000)['run']['active'], 5000 - 2900)
        self.assertEqual(core.clean_time(run.events, run.started, 6000, run.hold), 5000 - 2900)
        # без пауз — как раньше
        self.assertEqual(core.clean_time(run.events, run.started, 6000), 5000 - 200)

    def test_failed_filter_load_is_said(self):
        """Фильтр не загрузился (Result: false — в нём ошибка): строка фильтра называет его; следующая удачная загрузка
        это снимает."""
        bad = '2026/11/11 21:30:00 1 a [INFO Client 1] [Item Filter] Finished reloading online filter simple1. Result: false. Hash: 0.\n'
        _, view, _ = build(RUN_LINES + RUN_TAIL + [bad], plan=ROUTE)
        self.assertEqual(view['filter']['failed'], 'Простой')
        _, view, _ = build(RUN_LINES + RUN_TAIL + [bad, flt('21:31:00', 'simple1')], plan=ROUTE)
        self.assertIsNone(view['filter']['failed'])

    def test_start_without_filter(self):
        """Старт без фильтра: выключение видно только по настройкам игры, в логе его нет."""
        steps = [dict(s) for s in ROUTE['steps']]
        steps[0]['filter'] = 'none'
        plan, problems = core.norm_plan(dict(ROUTE, steps=steps))
        self.assertEqual(problems, [])
        early = upto(RUN_LINES + RUN_TAIL, gen('20:49:14', 5, 'G1_5'))
        parser, run = core.LogParser(), core.Run()
        for line in early:
            for ev in parser.feed(line):
                if ev['type'] == 'start':
                    run = core.Run(core.run_id(ev['ts']), ev['ts'])
                else:
                    run.events.append(ev)
        # по логу загружен base1, а в настройках фильтр выключен
        view = core.derive(plan, run, 0, None, 'None')
        self.assertTrue(view['filter']['off'])
        self.assertIsNone(view['filter']['id'])
        self.assertIs(view['filter']['match'], True)
        self.assertEqual(view['step']['filter'], {'id': 'none', 'name': 'без фильтра', 'none': True, 'loaded': True, 'switch': False,
                                                  'missing': False})
        # настройки не прочитаны: верим логу, а он говорит, что фильтр включён
        view = core.derive(plan, run, 0)
        self.assertFalse(view['filter']['off'])
        self.assertIs(view['filter']['match'], False)
        self.assertFalse(view['step']['filter']['loaded'])
        # в настройках выбран другой фильтр, чем последний в логе
        view = core.derive(plan, run, 0, None, 'simple1')
        self.assertEqual(view['filter']['name'], 'Простой')
        self.assertIsNone(view['filter']['since'])

    def test_new_filter_version_with_same_id(self):
        def ver(t, fid, h):
            return flt(t, fid).replace('Hash: aa.', 'Hash: %s.' % h)
        lines = RUN_LINES + [ver('22:05:40', 'simple1', 'e51e'), ver('22:05:42', 'base1', 'ce34'),
                             ver('22:05:43', 'simple1', 'e51e'), ver('22:06:28', 'simple1', '0443')]
        _, view, _ = build(lines, plan=ROUTE)
        self.assertEqual(view['filter']['id'], 'simple1')
        self.assertEqual(view['filter']['since'], core.line_ts('2026/11/11 22:06:28 x'))
        texts = [h['text'] for h in view['history']]
        self.assertEqual(texts[0], 'Фильтр обновлён, новая версия: Простой')
        self.assertEqual(texts.count('Фильтр: Простой'), 2)

    def test_manual_move(self):
        _, view, _ = build(RUN_LINES + RUN_TAIL, plan=ROUTE, moves=['redvale'])
        self.assertEqual(view['step']['id'], 'redvale')
        self.assertEqual(view['history'][0]['text'], 'Шаг выбран вручную: Красная Долина')
        _, view, _ = build(RUN_LINES + RUN_TAIL, plan=ROUTE, moves=['nope'])
        self.assertEqual(view['step']['id'], 'tangle')

    def test_peek_into_later_zone_then_back_to_skipped_step(self):
        """Как в настоящем забеге: на 19 секунд зашли в гробницу, потом пошли в мавзолей."""
        plan = dict(ROUTE, steps=ROUTE['steps'][:7] + [
            {'id': 'mausoleum', 'zone': 'G1_8', 'also': ['G1_7'], 'name': 'Мавзолей претора'},
            {'id': 'tomb', 'zone': 'G1_9', 'also': ['G1_7'], 'name': 'Супружеская гробница'},
        ], goals=ROUTE['goals'][:2] + [
            {'id': 'weapon-better', 'slot': 'weapon', 'title': 'Арбалет получше', 'need': 'mausoleum'}])
        base = RUN_LINES + RUN_TAIL + zone('21:39:18', 7, 'G1_7', 'Кладбище Вечных')
        peek = base + zone('21:43:44', 8, 'G1_9', 'Супружеская гробница')
        _, view, _ = build(peek, plan=plan)
        self.assertEqual(view['step']['id'], 'tomb')
        back = peek + zone('21:44:03', 7, 'G1_7', 'Кладбище Вечных') + zone('21:44:30', 9, 'G1_8', 'Мавзолей претора')
        _, view, _ = build(back, [('weapon-crossbow', 2)], plan=plan)
        self.assertEqual(view['step']['id'], 'mausoleum')
        self.assertTrue(view['onStep'])
        self.assertEqual(view['slots'][0]['next']['urgency'], 'due')
        self.assertEqual(view['overdue'], [])
        hub = back + zone('22:00:47', 7, 'G1_7', 'Кладбище Вечных')
        _, view, _ = build(hub, plan=plan)
        self.assertEqual(view['step']['id'], 'mausoleum')
        self.assertTrue(view['onStep'])
        _, view, _ = build(hub + zone('22:10:00', 8, 'G1_9', 'Супружеская гробница'), plan=plan)
        self.assertEqual(view['step']['id'], 'tomb')
        _, view, _ = build(hub + zone('22:10:00', 8, 'G1_9', 'Супружеская гробница')
                           + zone('22:20:00', 7, 'G1_7', 'Кладбище Вечных')
                           + zone('22:21:00', 9, 'G1_8', 'Мавзолей претора'), plan=plan)
        self.assertEqual(view['step']['id'], 'tomb')

    def test_touch_points_are_checked_from_the_log(self):
        steps = [dict(s) for s in ROUTE['steps']]
        steps[6]['touch'] = [{'zone': 'G1_8', 'name': 'Мавзолей претора'},
                             {'zone': 'G1_9', 'name': 'Супружеская гробница'}]
        plan = dict(ROUTE, steps=steps, rules=['Точки активирую сразу'],
                    goals=ROUTE['goals'][:1] + [dict(ROUTE['goals'][1], vendor=True)])
        base = RUN_LINES + RUN_TAIL + zone('21:39:18', 7, 'G1_7', 'Кладбище Вечных')
        _, view, _ = build(base, plan=plan)
        self.assertEqual(view['step']['id'], 'cemetery')
        self.assertEqual([t['done'] for t in view['step']['touch']], [False, False])
        # правил забега и напоминания «к торговцу» в программе больше нет: старые поля плана ни на что не влияют
        self.assertFalse({'rules', 'vendor'} & set(view))
        self.assertNotIn('vendor', goal(view, 'skill-flash'))
        peek = base + zone('21:43:44', 8, 'G1_9', 'Супружеская гробница') + zone('21:44:03', 7, 'G1_7', 'Кладбище Вечных')
        _, view, _ = build(peek, plan=plan, moves=['cemetery'])
        self.assertEqual([(t['name'], t['done']) for t in view['step']['touch']],
                         [('Мавзолей претора', False), ('Супружеская гробница', True)])
        _, view, _ = build(peek + [lvl('21:46:11', 6)], plan=plan)
        self.assertEqual((view['ready'][0]['id'], view['ready'][0]['fact']), ('skill-flash', None))

    def test_short_visit_to_touch_point_does_not_switch_step(self):
        """Кладбище: заглянули в обе гробницы ради точек, шаг остался; задержались — сменился."""
        steps = [dict(s) for s in ROUTE['steps'][:7]] + [
            {'id': 'mausoleum', 'zone': 'G1_8', 'also': ['G1_7'], 'name': 'Мавзолей претора'},
            {'id': 'tomb', 'zone': 'G1_9', 'also': ['G1_7'], 'name': 'Супружеская гробница'}]
        steps[6]['touch'] = [{'zone': 'G1_8', 'name': 'Мавзолей претора'},
                             {'zone': 'G1_9', 'name': 'Супружеская гробница'}]
        plan, _ = core.norm_plan(dict(ROUTE, steps=steps, goals=ROUTE['goals'][:2]))
        base = RUN_LINES + RUN_TAIL + zone('21:39:18', 7, 'G1_7', 'Кладбище Вечных')

        def at(lines, clock):
            parser, run = core.LogParser(), core.Run()
            for line in lines:
                for ev in parser.feed(line):
                    if ev['type'] == 'start':
                        run = core.Run(core.run_id(ev['ts']), ev['ts'])
                    else:
                        run.events.append(ev)
            return core.derive(plan, run, core.line_ts('%s %s x' % (DAY, clock)))

        # только что зашли в Мавзолей: шаг прежний, идёт отсчёт, точка уже отмечена
        peek8 = base + zone('21:44:30', 9, 'G1_8', 'Мавзолей претора')
        view = at(peek8, '21:44:40')
        self.assertEqual(view['step']['id'], 'cemetery')
        self.assertTrue(view['onStep'])
        # заход называет шаг, которым он станет: страница сразу показывает его карточку
        self.assertEqual(view['pending'], {'id': 'mausoleum', 'name': 'Мавзолей претора',
                                           'at': core.line_ts('%s 21:45:10 x' % DAY)})
        self.assertEqual([t['done'] for t in view['step']['touch']], [True, False])
        # вышли через 15 секунд, заглянули во вторую гробницу на 19 секунд, вернулись
        both = (peek8 + zone('21:44:45', 7, 'G1_7', 'Кладбище Вечных')
                + zone('21:45:00', 8, 'G1_9', 'Супружеская гробница')
                + zone('21:45:19', 7, 'G1_7', 'Кладбище Вечных'))
        view = at(both, '21:50:00')
        self.assertEqual(view['step']['id'], 'cemetery')
        self.assertIsNone(view['pending'])
        self.assertEqual([t['done'] for t in view['step']['touch']], [True, True])
        # зашли в Мавзолей всерьёз: через 40 секунд шаг сменился
        real = both + zone('21:52:00', 9, 'G1_8', 'Мавзолей претора')
        self.assertEqual(at(real, '21:52:39')['step']['id'], 'cemetery')
        self.assertEqual(at(real, '21:52:40')['step']['id'], 'mausoleum')
        self.assertIsNone(at(real, '21:52:40')['pending'])
        # обычный переход на следующий шаг (не точка, без перепрыгивания) — сразу
        nxt = real + zone('22:30:00', 7, 'G1_7', 'Кладбище Вечных') + zone('22:31:00', 8, 'G1_9', 'Супружеская гробница')
        self.assertEqual(at(nxt, '22:31:01')['step']['id'], 'tomb')

    def test_time_out_of_the_game_is_not_time_in_the_zone(self):
        """Зашли на карту шага впереди и вышли из игры раньше порога: отсчёта нет и шаг не меняется, сколько
        бы игра ни была закрыта. Вернулись на ту же карту — заход новый, порог ему с начала."""
        steps = [dict(s) for s in ROUTE['steps'][:7]] + [
            {'id': 'mausoleum', 'zone': 'G1_8', 'also': ['G1_7'], 'name': 'Мавзолей претора'},
            {'id': 'tomb', 'zone': 'G1_9', 'name': 'Супружеская гробница'},
            {'id': 'lachlann', 'zone': 'G1_7', 'name': 'Лакланн'},
            {'id': 'hunting', 'zone': 'G1_11', 'name': 'Охотничьи угодья'}]
        steps[6]['touch'] = [{'zone': 'G1_8'}]
        plan, _ = core.norm_plan(dict(ROUTE, steps=steps, goals=ROUTE['goals'][:2]))
        base = RUN_LINES + RUN_TAIL + zone('21:39:18', 7, 'G1_7', 'Кладбище Вечных')
        ts = lambda clock: core.line_ts('%s %s x' % (DAY, clock))   # noqa: E731

        def at(lines, clock):
            parser, run = core.LogParser(), core.Run()
            for line in lines:
                for ev in parser.feed(line):
                    if ev['type'] == 'start':
                        run = core.Run(core.run_id(ev['ts']), ev['ts'])
                    else:
                        run.events.append(ev)
            return core.derive(plan, run, ts(clock))

        card = lambda view, sid: next(c for c in view['cards'] if c['id'] == sid)   # noqa: E731
        closing = lambda clock: '%s %s 1000 abcd [INFO Client 1] Closing game gracefully' % (DAY, clock)   # noqa: E731
        opening = lambda clock: '%s %s ***** LOG FILE OPENING *****' % (DAY, clock)                       # noqa: E731
        # зашли в Мавзолей (точка перехода шага): идёт отсчёт
        visit = base + zone('21:44:30', 9, 'G1_8', 'Мавзолей претора')
        view = at(visit, '21:44:39')
        self.assertEqual((view['step']['id'], view['pending']['id'], view['run']['paused']), ('cemetery', 'mausoleum', False))
        # на десятой секунде игру закрыли: героя в игре нет — отсчёта нет, пересчитывать нечего
        closed = visit + [closing('21:44:40')]
        view = at(closed, '21:44:45')
        self.assertEqual((view['step']['id'], view['pending'], view['recheckAt'], view['run']['paused']),
                         ('cemetery', None, None, True))
        # игра закрыта час — шаг прежний: время вне игры временем в зоне не считается
        view = at(closed, '22:44:40')
        self.assertEqual((view['step']['id'], view['pending']), ('cemetery', None))
        self.assertIsNone(card(view, 'mausoleum').get('at'))
        # то же — выход к списку героев и вылет игры (о вылете говорит строка следующего запуска)
        self.assertEqual(at(visit + [src('21:44:40', '(unknown)')], '22:44:40')['step']['id'], 'cemetery')
        crashed = visit + ['%s 21:44:38 1000 abcd [INFO Client 1] обычная строка' % DAY, opening('22:50:00')]
        view = at(crashed, '22:50:05')
        self.assertEqual((view['step']['id'], view['pending'], view['run']['paused']), ('cemetery', None, True))
        # вернулись на ту же карту: заход новый, порог ему с начала
        back = closed + [opening('22:50:00')] + zone('22:51:00', 9, 'G1_8', 'Мавзолей претора')
        view = at(back, '22:51:10')
        self.assertEqual((view['step']['id'], view['pending']),
                         ('cemetery', {'id': 'mausoleum', 'name': 'Мавзолей претора', 'at': ts('22:51:40')}))
        self.assertEqual(at(back, '22:51:39')['step']['id'], 'cemetery')
        view = at(back, '22:51:40')
        self.assertEqual((view['step']['id'], view['pending']), ('mausoleum', None))
        # время шага — со второго входа; десять секунд первого захода остались прежнему шагу, час вне игры — ничей
        self.assertEqual((card(view, 'cemetery')['took'], card(view, 'mausoleum')['took']), (322, 40))
        # вернулись в город (вышли к списку героев вместо портала): заход за точкой шагом так и не стал
        town = visit + [src('21:44:45', '(unknown)')] + zone('21:44:50', 15, 'G1_town', 'Лагерь Клирфелл')
        self.assertEqual(at(town, '21:50:00')['step']['id'], 'cemetery')

        # «Заглянули и вернулись» считает так же. Гробница → кладбище: следующий шаг — сразу; через 8 секунд
        # игру закрыли на час, вернулись в город и пошли обратно в гробницу — на кладбище только заглянули.
        walk = (base + zone('21:46:00', 9, 'G1_8', 'Мавзолей претора') + zone('21:50:00', 8, 'G1_9', 'Супружеская гробница')
                + zone('22:00:00', 7, 'G1_7', 'Кладбище Вечных'))
        self.assertEqual(at(walk, '22:00:03')['step']['id'], 'lachlann')
        away = walk + [closing('22:00:08'), opening('23:10:00')]
        self.assertEqual(at(away, '23:10:05')['step']['id'], 'lachlann')
        home = away + zone('23:10:30', 15, 'G1_town', 'Лагерь Клирфелл')
        self.assertEqual(at(home + zone('23:11:00', 8, 'G1_9', 'Супружеская гробница'), '23:12:00')['step']['id'], 'tomb')
        # вернулись на кладбище и снова ушли раньше порога — всё ещё заглянули; задержались — перешли
        again = away + zone('23:10:30', 7, 'G1_7', 'Кладбище Вечных')
        self.assertEqual(at(again + zone('23:10:40', 8, 'G1_9', 'Супружеская гробница'), '23:12:00')['step']['id'], 'tomb')
        self.assertEqual(at(again + zone('23:11:20', 8, 'G1_9', 'Супружеская гробница'), '23:12:00')['step']['id'], 'lachlann')

    def test_step_can_be_switched_at_once_during_a_visit(self):
        """Кнопка «сменить шаг» во время захода: шаг меняется сразу, отсчёт пропадает, обязательный
        босс оставленного шага отмечается, как при обычном переходе; время шага — от входа на карту."""
        steps = [dict(s) for s in ROUTE['steps'][:7]] + [
            {'id': 'mausoleum', 'zone': 'G1_8', 'also': ['G1_7'], 'name': 'Мавзолей претора'}]
        steps[6]['touch'] = [{'zone': 'G1_8', 'name': 'Мавзолей претора'}]
        goals = ROUTE['goals'][:2] + [{'id': 'boss-guard', 'kind': 'boss', 'must': True, 'title': 'Страж',
                                       'need': 'cemetery'}]
        plan, _ = core.norm_plan(dict(ROUTE, steps=steps, goals=goals))
        lines = (RUN_LINES + RUN_TAIL + zone('21:39:18', 7, 'G1_7', 'Кладбище Вечных')
                 + zone('21:44:30', 9, 'G1_8', 'Мавзолей претора'))
        ts = lambda clock: core.line_ts('%s %s x' % (DAY, clock))   # noqa: E731

        def at(lines, clock, moves=()):
            parser, run = core.LogParser(), core.Run()
            for line in lines:
                for ev in parser.feed(line):
                    if ev['type'] == 'start':
                        run = core.Run(core.run_id(ev['ts']), ev['ts'])
                    else:
                        run.events.append(ev)
            run.moves = [{'ts': ts(c), 'step': s} for c, s in moves]
            return core.derive(plan, run, ts(clock))

        boss = lambda view: next(g for g in view['bosses'] if g['id'] == 'boss-guard')   # noqa: E731
        card = lambda view, sid: next(c for c in view['cards'] if c['id'] == sid)          # noqa: E731
        # десять секунд на новой карте: шаг прежний, босс ещё не отмечен
        view = at(lines, '21:44:40')
        self.assertEqual((view['step']['id'], view['pending']['id'], boss(view)['urgency']),
                         ('cemetery', 'mausoleum', 'due'))
        # нажали кнопку на 12-й секунде: шаг сменился, ждать больше нечего, босс закрыт переходом
        pressed = [('21:44:42', 'mausoleum')]
        view = at(lines, '21:44:45', pressed)
        self.assertEqual((view['step']['id'], view['pending']), ('mausoleum', None))
        self.assertEqual((boss(view)['urgency'], boss(view)['closedBy']), ('done', 'pass'))
        # отсчёта нет, но по истечении порога программа пересчитает время шага сама (см. ниже)
        self.assertEqual(view['recheckAt'], ts('21:45:10'))
        self.assertEqual(at(lines, '21:44:40')['recheckAt'], ts('21:45:10'))
        self.assertIsNone(at(lines, '21:46:00', pressed)['recheckAt'])
        # ушли в город раньше порога — шаг всё равно остаётся новым: кнопка важнее таймера
        gone = lines + zone('21:44:50', 15, 'G1_town', 'Лагерь Клирфелл')
        self.assertEqual(at(gone, '21:50:00', pressed)['step']['id'], 'mausoleum')
        # остались — после порога шаг считается начатым со входа на карту, а не с нажатия
        view = at(lines, '21:46:00', pressed)
        self.assertEqual(view['step']['id'], 'mausoleum')
        entered = at(lines, '21:46:00')          # тот же заход без кнопки: сменился сам по таймеру
        self.assertEqual(card(view, 'mausoleum')['at'], card(entered, 'mausoleum')['at'])
        self.assertEqual(card(view, 'mausoleum')['took'], 90)   # с 21:44:30 по 21:46:00

    def test_peek_into_the_next_step_and_back_is_not_a_switch(self):
        """Переход на следующий шаг — сразу. Но заглянули в его зону меньше чем на порог и вернулись в зону
        шага, с которого ушли, — перехода не было: шаг прежний, его обязательный босс снова не отмечен."""
        steps = [dict(s) for s in ROUTE['steps'][:7]] + [
            {'id': 'mausoleum', 'zone': 'G1_8', 'also': ['G1_7'], 'name': 'Мавзолей претора'},
            {'id': 'tomb', 'zone': 'G1_9', 'name': 'Супружеская гробница'},
            {'id': 'lachlann', 'zone': 'G1_7', 'name': 'Лакланн'},
            {'id': 'hunting', 'zone': 'G1_11', 'name': 'Охотничьи угодья'}]
        goals = ROUTE['goals'][:2] + [{'id': 'boss-asinia', 'kind': 'boss', 'must': True, 'title': 'Азиния', 'need': 'tomb'}]
        plan, _ = core.norm_plan(dict(ROUTE, steps=steps, goals=goals))
        base = (RUN_LINES + RUN_TAIL + zone('21:39:18', 7, 'G1_7', 'Кладбище Вечных')
                + zone('21:41:00', 9, 'G1_8', 'Мавзолей претора') + zone('21:50:00', 8, 'G1_9', 'Супружеская гробница'))
        ts = lambda clock: core.line_ts('%s %s x' % (DAY, clock))   # noqa: E731

        def at(lines, clock):
            parser, run = core.LogParser(), core.Run()
            for line in lines:
                for ev in parser.feed(line):
                    if ev['type'] == 'start':
                        run = core.Run(core.run_id(ev['ts']), ev['ts'])
                    else:
                        run.events.append(ev)
            return core.derive(plan, run, ts(clock))

        boss = lambda view: next(g for g in view['bosses'] if g['id'] == 'boss-asinia')['urgency']   # noqa: E731
        card = lambda view, sid: next(c for c in view['cards'] if c['id'] == sid)                   # noqa: E731
        self.assertEqual(at(base, '21:59:00')['step']['id'], 'tomb')
        # вышли на кладбище: следующий шаг — сразу, босс гробницы отмечен переходом
        out = base + zone('22:00:00', 7, 'G1_7', 'Кладбище Вечных')
        view = at(out, '22:00:03')
        self.assertEqual((view['step']['id'], view['pending'], boss(view)), ('lachlann', None, 'done'))
        # через 6 секунд вернулись в гробницу: шаг снова её, босс снова не отмечен, время шага не рвалось
        back = out + zone('22:00:06', 8, 'G1_9', 'Супружеская гробница')
        view = at(back, '22:00:10')
        self.assertEqual((view['step']['id'], boss(view)), ('tomb', 'due'))
        self.assertEqual(card(view, 'tomb')['took'], 610)        # с 21:50:00 по 22:00:10
        self.assertIsNone(card(view, 'lachlann').get('at'))
        # город и снова гробница — шаг её; вышли на кладбище всерьёз — «Лакланн»
        again = back + zone('22:00:20', 15, 'G1_town', 'Лагерь Клирфелл') + zone('22:01:00', 8, 'G1_9', 'Супружеская гробница')
        self.assertEqual(at(again, '22:06:59')['step']['id'], 'tomb')
        real = again + zone('22:07:00', 7, 'G1_7', 'Кладбище Вечных')
        self.assertEqual(at(real, '22:07:01')['step']['id'], 'lachlann')
        # пробыли на кладбище две минуты и вернулись в гробницу: переход состоялся, назад шаг не идёт
        self.assertEqual(at(real + zone('22:09:00', 8, 'G1_9', 'Супружеская гробница'), '22:10:00')['step']['id'], 'lachlann')
        # город между заходом и возвратом не в счёт: заглянули, ушли в город, вернулись в гробницу — шаг её
        town = out + zone('22:00:10', 15, 'G1_town', 'Лагерь Клирфелл')
        self.assertEqual(at(town, '22:00:30')['step']['id'], 'lachlann')
        self.assertEqual(at(town + zone('22:01:10', 8, 'G1_9', 'Супружеская гробница'), '22:02:00')['step']['id'], 'tomb')
        # два коротких захода подряд — всё ещё «заглянули»; а задержались на кладбище на порог — перешли
        twice = town + zone('22:01:10', 7, 'G1_7', 'Кладбище Вечных') + zone('22:01:20', 15, 'G1_town', 'Лагерь Клирфелл')
        self.assertEqual(at(twice + zone('22:02:00', 8, 'G1_9', 'Супружеская гробница'), '22:03:00')['step']['id'], 'tomb')
        stayed = town + zone('22:01:10', 7, 'G1_7', 'Кладбище Вечных') + zone('22:02:10', 15, 'G1_town', 'Лагерь Клирфелл')
        self.assertEqual(at(stayed + zone('22:03:00', 8, 'G1_9', 'Супружеская гробница'), '22:04:00')['step']['id'], 'lachlann')
        # заглянули и пошли дальше, а не назад: переход состоялся
        on = out + zone('22:00:06', 10, 'G1_11', 'Охотничьи угодья')
        self.assertEqual(at(on, '22:00:07')['step']['id'], 'hunting')
        # шаг сменили кнопкой — это уже не «заглянули»: возврат в прежнюю зону шаг не вернёт
        parser, run = core.LogParser(), core.Run()
        for line in back:
            for ev in parser.feed(line):
                if ev['type'] == 'start':
                    run = core.Run(core.run_id(ev['ts']), ev['ts'])
                else:
                    run.events.append(ev)
        run.moves = [{'ts': ts('22:00:04'), 'step': 'lachlann'}]
        self.assertEqual(core.derive(plan, run, ts('22:00:10'))['step']['id'], 'lachlann')

    def test_jump_over_steps_needs_time_too(self):
        """Заход в зону далеко впереди по маршруту без пометки «точка» тоже не меняет шаг сразу."""
        lines = RUN_LINES + zone('20:41:00', 7, 'G1_7', 'Кладбище Вечных') + zone('20:41:10', 4, 'G1_4', 'Грельвуд')
        _, view, _ = build(lines, plan=ROUTE)
        self.assertEqual(view['step']['id'], 'grelwood-1')
        _, view, _ = build(RUN_LINES + zone('20:41:00', 7, 'G1_7', 'Кладбище Вечных')
                           + zone('20:45:00', 15, 'G1_town', 'Лагерь Клирфелл'), plan=ROUTE)
        self.assertEqual(view['step']['id'], 'cemetery')

    def test_reward_goal_marks_itself_from_the_log(self):
        def points(t):
            return ['%s %s 1000 abcd [INFO Client 1] : Вы получили очков пассивных умений: 2.' % (DAY, t),
                    '%s %s 1000 abcd [INFO Client 1] : Вы получили 2 очка пассивных умений для набора оружия.' % (DAY, t)]
        plan = dict(ROUTE, goals=ROUTE['goals'] + [
            {'id': 'pts', 'group': 'Пассивки', 'title': 'Босс: +2 очка', 'reward': 'passive_points', 'need': 'tangle'}])
        full = RUN_LINES + RUN_TAIL
        run, view, _ = build(full, plan=plan)
        g = goal(view, 'pts')
        self.assertTrue(g['auto'])
        self.assertEqual(g['urgency'], 'due')
        # очки, полученные до шага цели, эту цель не закрывают
        early = upto(full, gen('21:13:41', 15, 'G1_town')) + points('21:10:00')
        _, view, _ = build(early + full[len(upto(full, gen('21:13:41', 15, 'G1_town'))):], plan=plan)
        self.assertEqual(goal(view, 'pts')['urgency'], 'due')
        # очки на своём шаге: две строки лога дают одно событие, цель закрыта
        run, view, _ = build(full + points('21:30:00'), plan=plan)
        self.assertEqual(len([e for e in run.events if e['type'] == 'reward']), 2)
        self.assertEqual(goal(view, 'pts')['urgency'], 'done')
        self.assertEqual(view['history'][0]['text'], 'Награда: очки пассивных умений: +2')

    def test_reward_with_a_choice_is_marked_by_the_line_of_any_option(self):
        """У награды с выбором коды свойств свои у каждого варианта: награда взята, какой бы вариант ни выбрали."""
        plan = dict(ROUTE, goals=ROUTE['goals'] + [
            {'id': 'draught', 'group': 'Награды', 'title': 'Яд: 25% увеличение порога оглушения',
             'reward': ['stun_threshold_+%', 'mana_regeneration_rate_+%'], 'need': 'tangle'}])
        full = RUN_LINES + RUN_TAIL
        _, view, _ = build(full, plan=plan)
        self.assertEqual((goal(view, 'draught')['auto'], goal(view, 'draught')['urgency']), (True, 'due'))
        _, view, _ = build(full + [reward('21:30:00', '25% повышение скорости регенерации маны')], plan=plan)
        self.assertEqual(goal(view, 'draught')['urgency'], 'done')
        # чужая награда эту цель не закрывает
        _, view, _ = build(full + [reward('21:30:00', '+10% к сопротивлению холоду')], plan=plan)
        self.assertEqual(goal(view, 'draught')['urgency'], 'due')

    def test_reward_is_recognised_in_any_client_language(self):
        # Награда в плане — код свойства игры; строку лога английского клиента он узнаёт так же, как русскую
        en = logtext.LogText({'msg': {'ReceivedStatBonusWithName': '{0} has received {1}.'},
                              'stat': {'stun_threshold_+%': ['{0}% increased Stun Threshold']}}, 'en')
        plan = dict(ROUTE, goals=ROUTE['goals'] + [
            {'id': 'draught', 'group': 'Награды', 'title': 'Яд', 'reward': 'stun_threshold_+%', 'need': 'tangle'}])
        full = RUN_LINES + RUN_TAIL
        line = '%s 21:30:00 1000 abcd [INFO Client 1] : Hero has received 25%% increased [StunThreshold|Stun Threshold].' % DAY
        _, view, _ = build(full + [line], plan=plan, text=en)
        self.assertEqual(goal(view, 'draught')['urgency'], 'done')
        self.assertIn('Награда: 25% increased Stun Threshold', [h['text'] for h in view['history']])
        # та же строка русского клиента — тот же код
        _, view, _ = build(full + [reward('21:30:00', '25% увеличение [StunThreshold|порога оглушения]')], plan=plan)
        self.assertEqual(goal(view, 'draught')['urgency'], 'done')

    def test_two_reward_goals_on_neighbour_steps(self):
        def points(t):
            return ['%s %s 1000 abcd [INFO Client 1] : Вы получили 2 очка пассивных умений для набора оружия.' % (DAY, t)]
        plan = dict(ROUTE, goals=ROUTE['goals'] + [
            {'id': 'boss', 'group': 'Пассивки', 'title': 'Босс', 'reward': 'passive_points', 'need': 'tangle'},
            {'id': 'hut', 'group': 'Пассивки', 'title': 'Хижина', 'reward': 'passive_points', 'need': 'cemetery'}])
        full = RUN_LINES + RUN_TAIL
        cem = zone('21:39:18', 7, 'G1_7', 'Кладбище Вечных')
        # первая награда на шаге босса закрывает босса, вторая на следующем шаге — хижину
        _, view, _ = build(full + points('21:30:00'), plan=plan)
        # награда привязана к карте: до своего шага она не «ищу», а «позже»
        self.assertEqual([goal(view, x)['urgency'] for x in ('boss', 'hut')], ['done', 'early'])
        self.assertEqual(goal(view, 'hut')['since'], 'с шага «Кладбище Вечных»')
        _, view, _ = build(full + points('21:30:00') + cem + points('21:45:00'), plan=plan)
        self.assertEqual([goal(view, x)['urgency'] for x in ('boss', 'hut')], ['done', 'done'])
        # босса пропустили: награда на следующем шаге относится к хижине, а не к боссу
        _, view, _ = build(full + cem + points('21:45:00'), plan=plan)
        self.assertEqual([goal(view, x)['urgency'] for x in ('boss', 'hut')], ['overdue', 'done'])
        # награду за хижину забрали позже, уже уйдя дальше: она всё равно её закрывает
        later = full + points('21:30:00') + cem + zone('21:50:00', 9, 'G1_8', 'Мавзолей претора') + points('21:55:00')
        _, view, _ = build(later, plan=plan)
        self.assertEqual([goal(view, x)['urgency'] for x in ('boss', 'hut')], ['done', 'done'])

    def test_reach_level_goal_marks_itself(self):
        plan = dict(ROUTE, goals=ROUTE['goals'] + [
            {'id': 'hero-6', 'group': 'Уровень', 'title': '6 уровень героя', 'reach': 6, 'need': 'tangle'}])
        full = RUN_LINES + RUN_TAIL
        _, view, _ = build(full, plan=plan)
        g = goal(view, 'hero-6')
        self.assertTrue(g['auto'])
        self.assertEqual(g['urgency'], 'due')
        _, view, _ = build(full + [lvl('21:35:00', 6)], plan=plan)
        self.assertEqual(goal(view, 'hero-6')['urgency'], 'done')
        _, view, _ = build(full + zone('21:39:18', 7, 'G1_7', 'Кладбище Вечных'), plan=plan)
        self.assertEqual(goal(view, 'hero-6')['urgency'], 'overdue')

    def test_new_instance_is_noted(self):
        _, view, _ = build(upto(RUN_LINES + RUN_TAIL, gen('20:49:14', 5, 'G1_5')), plan=ROUTE)
        self.assertEqual(view['history'][0]['text'], 'Грельвуд · зона 4 · новая копия')
        texts = [h['text'] for h in view['history']]
        self.assertIn('Мрачные заросли · зона 6', texts)
        self.assertEqual(texts.count('Грельвуд · зона 4'), 2)


# Вещи меняют по одной, срок у каждой цели свой: самострел и гранаты в ходу по испытание включительно
# (until), скипетр со щитом и скелеты — с шага «После вознесения» (use): до него их собирают в запас.
# Шаг «После вознесения» своей зоны не имеет — он наступает по строке лога.
KITS = {
    'title': 'смена вещей',
    'slots': [{'id': 'weapon', 'name': 'Оружие'}, {'id': 'offhand', 'name': 'Вторая рука'}],
    'steps': [
        {'id': 'riverbank', 'zone': 'G1_1', 'name': 'Берег реки'},
        {'id': 'clearfell', 'zone': 'G1_2', 'name': 'Клирфелл'},
        {'id': 'vastiri', 'zone': 'G2_1', 'name': 'Окраины Вастири'},
        {'id': 'trial', 'zone': 'G2_13', 'name': 'Испытание Сехем'},
        {'id': 'after', 'event': 'ascend', 'name': 'После вознесения',
         'notes': ['Надеть скипетр и щит']},
        {'id': 'next', 'zone': 'G2_4', 'name': 'Дальше'},
    ],
    'goals': [
        {'id': 'bow-1', 'slot': 'weapon', 'until': 'trial', 'title': 'Самострел', 'need': 'clearfell'},
        {'id': 'bow-2', 'slot': 'weapon', 'until': 'trial', 'title': 'Самострел лучше', 'need': 'vastiri'},
        {'id': 'sc-any', 'slot': 'weapon', 'use': 'after', 'title': 'Скипетр', 'need': 'trial'},
        {'id': 'sc-spirit', 'slot': 'weapon', 'use': 'after', 'title': 'Скипетр: префикс духа', 'need': 'trial'},
        {'id': 'sc-plus2', 'slot': 'weapon', 'use': 'after', 'title': 'Скипетр: суффикс +2', 'need': 'next',
         'opens': 25},
        {'id': 'shield', 'slot': 'offhand', 'use': 'after', 'title': 'Щит', 'from': 'vastiri', 'need': 'trial'},
        {'id': 'grenade', 'group': 'Навыки', 'kind': 'skill', 'until': 'trial', 'title': 'Граната', 'need': 'clearfell'},
        {'id': 'multishot', 'group': 'Навыки', 'kind': 'support', 'until': 'trial', 'title': 'Залповый огонь',
         'for': 'grenade', 'need': 'clearfell'},
        {'id': 'gem5', 'group': 'Навыки', 'kind': 'gem', 'until': 'trial', 'title': '5 уровень камня', 'for': 'grenade',
         'need': 'vastiri'},
        {'id': 'skeleton', 'group': 'Навыки', 'kind': 'skill', 'use': 'after', 'title': 'Скелеты', 'need': 'after'},
        {'id': 'gold', 'group': 'Ресурсы', 'kind': 'resource', 'title': 'Золото', 'need': 'trial'},
        {'id': 'ring', 'group': 'Ресурсы', 'title': 'Кольцо на первый акт', 'need': 'clearfell',
         'until': 'clearfell'},
    ],
}

ACT1 = zone('20:07:03', 1, 'G1_1', 'Берег реки') + [lvl('20:09:17', 2)] + zone('20:10:55', 2, 'G1_2', 'Клирфелл')
ACT2 = ACT1 + zone('22:00:00', 16, 'G2_1', 'Окраины Вастири')
TRIAL = ACT2 + zone('23:00:00', 22, 'G2_13', 'Испытание Сехем')


def tile(view, slot):
    return next(s for s in view['slots'] if s['id'] == slot)


def stash_tile(view, slot):
    return next(t for st in view['stash'] for t in st['tiles'] if t['id'] == slot)


def worn_line(view, slot='weapon'):
    """Линия слота, которая сейчас в ходу: шаг, с которого носят то, что в слоте (None — с самого начала)."""
    return next((r['line'] for r in view['holders'] if r.get('slot') == slot), None)


def group(view, name):
    return [g['id'] for grp in view['groups'] if grp['name'] == name for g in grp['goals']]


class SwapTest(unittest.TestCase):
    def test_plan_is_valid(self):
        _, view, problems = build(ACT1, plan=KITS)
        self.assertEqual(problems, [])
        self.assertEqual((worn_line(view), 'kit' in view), (None, False))
        # шаги цели должны быть в маршруте; gear — описание вещи слота. Прежние комплекты (раздел kits,
        # поле kit у шага и у цели) больше не читаются: о них сказано, а не молча пропущено
        bad = dict(KITS, goals=KITS['goals'] + [
            {'id': 'x', 'title': 'x', 'kit': 'nope', 'from': 'nowhere', 'use': 'someday', 'until': 'never', 'gear': 'Sceptre'}])
        bad['steps'] = KITS['steps'] + [{'id': 'odd', 'event': 'boss', 'kit': 'ghost', 'name': 'Странный'}]
        bad['kits'] = {'djinn': {'name': 'Скипетр и щит', 'until': 'endgame'}}
        _, _, problems = build(ACT1, plan=bad)
        self.assertEqual(problems, [
            'Раздел kits больше не читается: с какого шага и по какой предмет или камень в ходу, говорит сама цель '
            '(use, until), что это за предмет — её поле gear',
            'Поле kit у целей больше не читается (1): срок у каждой цели свой — use и until',
            'Шаг «odd»: поле kit больше не читается — срок у каждой цели свой (use, until)',
            'Шаг «odd»: событие бывает только ascend, ascend2, ascend3, ascend4',
            'Цель «x»: нет шага «nowhere»', 'Цель «x»: нет шага «someday»', 'Цель «x»: нет шага «never»',
            'Цель «x»: gear — описание базы предмета слота («Sceptre», «Shield str_armour»)'])

    def test_every_goal_says_what_it_is(self):
        # Вид цели подписан у всех одинаково: слот предмета, умение, поддержка, уровень камня, ресурс.
        _, view, _ = build(ACT1, plan=KITS)
        self.assertEqual(tile(view, 'weapon')['next']['kind'], 'оружие')
        self.assertEqual(goal(view, 'shield')['kind'], 'вторая рука')
        grenade = goal(view, 'grenade')
        self.assertEqual(grenade['kind'], 'умение')
        self.assertEqual([(c['id'], c['kind']) for c in grenade['children']],
                         [('multishot', 'камень поддержки'), ('gem5', 'уровень камня')])
        self.assertEqual(goal(view, 'gold')['kind'], 'ресурс')
        self.assertIsNone(goal(view, 'ring')['kind'])
        _, view, _ = build(RUN_LINES + [lvl('21:00:00', 9)], plan=dict(PLAN, goals=PLAN['goals'] + [
            {'id': 'hero-7', 'group': 'Уровень', 'title': '7 уровень героя', 'reach': 7, 'need': 'grelwood'},
            {'id': 'cold', 'group': 'Награды', 'title': 'Босс', 'reward': 'base_cold_damage_resistance_%', 'need': 'clearfell'}]))
        self.assertEqual((goal(view, 'hero-7')['kind'], goal(view, 'cold')['kind']), ('уровень героя', 'награда'))

    def test_what_is_worn_later_waits_for_its_step(self):
        # Рюкзака нет. В слотах — то, что план ждёт сейчас: скипетр, который носят после вознесения, туда не лезет.
        _, view, _ = build(ACT1, [('sc-any', 1)], plan=KITS)
        weapon = tile(view, 'weapon')
        self.assertEqual(weapon['chain'], ['bow-1', 'bow-2'])
        self.assertEqual((weapon['next']['id'], weapon['next']['urgency']), ('bow-1', 'due'))
        self.assertIsNone(weapon['worn'])
        self.assertFalse(tile(view, 'offhand')['hasGoals'])
        # Вещь следующего периода — «позже» до шага, с которого её носят (поле from раньше него не в счёт); отметка
        # «в рюкзаке» прежних забегов (статус 1) её не закрывает.
        later = 'с шага «После вознесения»'
        self.assertEqual([(x, goal(view, x)['urgency'], goal(view, x)['since']) for x in ('sc-any', 'sc-plus2', 'shield')],
                         [('sc-any', 'early', later), ('sc-plus2', 'early', later), ('shield', 'early', later)])
        # Запас — только умения, которые возьмут позже; умение появится на своём шаге, его шаг страница называет и так.
        self.assertEqual([(s['line'], s['from'], [r['id'] for r in s['rows']]) for s in view['stash']],
                         [('after', 'После вознесения', ['skill:skeleton'])])
        self.assertEqual((goal(view, 'skeleton')['urgency'], goal(view, 'skeleton')['since'], goal(view, 'skeleton')['needName']),
                         ('early', None, 'После вознесения'))
        self.assertEqual(view['overdue'], [])
        self.assertNotIn('wear', view)

    def test_goal_window_opens_by_step_and_by_zone_level(self):
        # С шага периода вещь ищут, когда она уже бывает: +2 — на вещи с 25 уровня, а вещь с редкого чудовища на два
        # уровня выше зоны — значит, падает с зоны 23.
        after = TRIAL + [ascend('23:30:00')]
        marks = [('sc-any', 2), ('sc-spirit', 2)]
        _, view, _ = build(after, marks, plan=KITS)
        weapon = tile(view, 'weapon')
        self.assertEqual((weapon['worn']['id'], weapon['next'], weapon['later']['id'], weapon['later']['since']),
                         ('sc-spirit', None, 'sc-plus2', 'с зоны 23'))
        # зона 25 уже была: +2 ищут, даже когда вернулись в зону пониже
        deep = after + zone('23:40:00', 25, 'G2_8', 'Глубже') + zone('23:50:00', 20, 'G2_4', 'Дальше')
        _, view, _ = build(deep, marks, plan=KITS)
        weapon = tile(view, 'weapon')
        self.assertEqual((weapon['worn']['id'], weapon['next']['id'], weapon['later']), ('sc-spirit', 'sc-plus2', None))

    def test_until_drops_goal_silently(self):
        _, view, _ = build(ACT1, plan=KITS)
        self.assertEqual(goal(view, 'ring')['urgency'], 'due')
        _, view, _ = build(ACT2, plan=KITS)
        # срок годности вышел: цели нет ни в группе, ни в просроченных
        self.assertEqual(group(view, 'Ресурсы'), ['gold'])
        self.assertEqual([g['id'] for g in view['overdue']], ['bow-1', 'grenade', 'multishot'])

    def test_second_ascension_opens_its_own_step(self):
        # Испытание Хаоса делится так же, как испытание Сехем: шаг самого испытания и шаг «после»,
        # который наступает сам — по третьему взятому узлу восхождения.
        steps = KITS['steps'] + [
            {'id': 'chaos', 'zone': 'G3_10_Airlock', 'also': ['G3_10'], 'name': 'Испытание Хаоса'},
            {'id': 'after-chaos', 'event': 'ascend2', 'name': 'После испытания Хаоса'},
            {'id': 'later', 'zone': 'G3_6_2', 'name': 'Святилище'}]
        plan = dict(KITS, steps=steps)
        node = lambda t, name: ascend(t, 'AscendancySorceress3' + name)
        first = TRIAL + [node('23:30:00', 'Notable8'), node('23:30:01', 'Notable13')]
        _, view, problems = build(first, plan=plan)
        self.assertEqual(problems, [])
        # первое вознесение открывает только свой шаг
        self.assertEqual(view['step']['id'], 'after')
        trial = (first + zone('23:35:00', 20, 'G2_4', 'Дальше') + zone('23:40:00', 38, 'G3_10_Airlock', 'Храм Хаоса')
                 + zone('23:40:20', 38, 'G3_10', 'Испытание Хаоса'))
        _, view, _ = build(trial, plan=plan)
        self.assertEqual((view['step']['id'], view['onStep'], view['cards'][view['pos'] + 1]['event']),
                         ('chaos', True, 'ascend2'))
        # взяли третий узел прямо в испытании — наступил шаг «после», и мы на нём
        done = trial + [node('23:55:00', 'Notable9'), node('23:55:02', 'Notable16')]
        _, view, _ = build(done, plan=plan)
        self.assertEqual((view['step']['id'], view['onStep'], view['beyond']), ('after-chaos', True, False))
        self.assertEqual(view['cards'][7]['event'], 'ascend2')
        self.assertIn('Восхождение получено: 2-е', [h['text'] for h in view['history']])
        # вышли в храм — шаг тот же
        _, view, _ = build(done + zone('23:56:00', 38, 'G3_10_Airlock', 'Храм Хаоса'), plan=plan)
        self.assertEqual((view['step']['id'], view['beyond']), ('after-chaos', False))

    def test_ascension_swaps_what_is_worn(self):
        marks = [('bow-1', 2), ('gold', 2), ('sc-any', 1), ('shield', 1)]
        _, view, _ = build(TRIAL, marks, plan=KITS)
        # до вознесения в оружии — то, что в ходу с самого начала; вторая рука пуста
        self.assertEqual((view['step']['id'], worn_line(view), worn_line(view, 'offhand'), view['hero']['ascended']),
                         ('trial', None, None, False))
        # вещи, которые носят после вознесения, — «позже» до своего шага: рюкзака нет, отметка «в рюкзаке» ничего не значит
        self.assertEqual([(g['id'], g['urgency']) for g in view['step']['goals']],
                         [('sc-any', 'early'), ('sc-spirit', 'early'), ('shield', 'early'), ('gold', 'done')])
        self.assertTrue(all('wear' not in c and 'move' not in c for c in view['cards']))

        _, view, _ = build(TRIAL + [ascend('23:30:00')], marks, plan=KITS)
        # после вознесения в ходу то, что носят с шага «После вознесения», — в обоих слотах
        self.assertEqual((view['step']['id'], worn_line(view), worn_line(view, 'offhand'), view['hero']['ascended']),
                         ('after', 'after', 'after', True))
        self.assertTrue(view['onStep'])
        self.assertFalse(view['beyond'])
        card = view['cards'][4]
        self.assertEqual((card['act'], card['event'], card['state']), ('Акт 2', 'ascend', 'current'))
        self.assertEqual(view['stash'], [])
        # В плитках — то, что план ждёт теперь: самострел ушёл со своим периодом; скипетр и щит не надеты — срок их
        # (шаг испытания) позади, они горят.
        weapon = tile(view, 'weapon')
        self.assertEqual((weapon['worn'], weapon['bag']), (None, None))
        self.assertEqual((weapon['next']['id'], weapon['next']['urgency']), ('sc-any', 'overdue'))
        self.assertEqual(weapon['later']['id'], 'sc-plus2')
        self.assertEqual((tile(view, 'offhand')['next']['id'], tile(view, 'offhand')['bag']), ('shield', None))
        # Самострел и гранаты сняты: их невзятые цели не горят и в текущем состоянии не показываются…
        self.assertEqual([g['id'] for g in view['overdue']], ['sc-any', 'sc-spirit', 'shield'])
        self.assertEqual(group(view, 'Навыки'), ['skeleton'])
        self.assertEqual(goal(view, 'skeleton')['urgency'], 'due')
        # …но остаются для разбора: что взяли, что нет.
        # …сгруппированные по шагу, после которого сняты. Ресурс со сроком годности («Кольцо на первый
        # акт») сюда не идёт: он не был в ходу и снят молча.
        self.assertEqual([(r['id'], r['name']) for r in view['retired']], [('trial', 'Испытание Сехем')])
        self.assertEqual([(g['id'], g['urgency']) for g in view['retired'][0]['goals']],
                         [('bow-1', 'done'), ('grenade', 'expired'), ('multishot', 'expired'),
                          ('bow-2', 'expired'), ('gem5', 'expired')])
        texts = [h['text'] for h in view['history']]
        self.assertIn('Восхождение получено', texts)
        self.assertIn('С этого шага в ходу: Скипетр, Щит', texts)
        self.assertIn('Снято: Самострел · не взято: Самострел лучше, Граната, '
                      'Залповый огонь → Граната, 5 уровень камня → Граната', texts)

        _, view, _ = build(TRIAL + [ascend('23:30:00')], marks + [('sc-any', 2)], plan=KITS)
        weapon = tile(view, 'weapon')
        self.assertEqual((weapon['worn']['id'], weapon['bag']), ('sc-any', None))
        self.assertNotIn('wear', view)

    def test_ascension_is_also_seen_by_class_change(self):
        _, view, _ = build(TRIAL + [lvl('23:40:00', 23, 'Ученица Варашты')], plan=KITS)
        self.assertEqual((view['step']['id'], worn_line(view)), ('after', 'after'))
        self.assertTrue(view['hero']['ascended'])

    def test_hero_is_what_the_log_says(self):
        """Имя, класс и вознесение героя — из лога; того, что назвал билд, в них нет."""
        # до второго уровня лог героя не называет: ни имени, ни класса
        _, view, _ = build(zone('20:07:03', 1, 'G1_1', 'Берег реки'), plan=KITS)
        self.assertEqual(view['hero'], {'level': 1, 'name': None, 'cls': None, 'asc': None, 'ascNode': None, 'ascended': False})
        _, view, _ = build(TRIAL, plan=KITS)
        self.assertEqual((view['hero']['name'], view['hero']['cls'], view['hero']['asc']), ('Герой', 'Чародейка', None))
        # вознесение взято, новый уровень ещё не пришёл: слова в логе нет — есть взятый узел вознесения
        _, view, _ = build(TRIAL + [ascend('23:30:00')], plan=KITS)
        self.assertEqual((view['hero']['cls'], view['hero']['asc'], view['hero']['ascNode'], view['hero']['ascended']),
                         ('Чародейка', None, 'AscendancySorceress3Small1', True))
        # со следующим уровнем лог зовёт героя вознесением: класс остаётся классом, имя — именем
        _, view, _ = build(TRIAL + [ascend('23:30:00'), lvl('23:40:00', 3, 'Ученица Варашты')], plan=KITS)
        self.assertEqual((view['hero']['name'], view['hero']['cls'], view['hero']['asc'], view['hero']['level']),
                         ('Герой', 'Чародейка', 'Ученица Варашты', 3))

    def test_event_step_is_left_like_any_other(self):
        done = TRIAL + [ascend('23:30:00')]
        # следующая зона плана — обычный переход
        _, view, _ = build(done + zone('23:50:00', 23, 'G2_4', 'Дальше'), plan=KITS)
        self.assertEqual((view['step']['id'], view['onStep']), ('next', True))
        # зона, которой в плане нет: шаг «после вознесения» остался позади
        _, view, _ = build(done + zone('23:50:00', 23, 'G2_99', 'Неведомая'), [('sc-any', 1)], plan=KITS)
        self.assertEqual((view['pos'], view['onStep'], view['beyond']), (4, False, True))
        self.assertEqual(goal(view, 'sc-any')['urgency'], 'overdue')
        self.assertEqual([g['id'] for g in view['overdue']], ['sc-any', 'sc-spirit', 'shield', 'skeleton', 'gold'])
        # вознесение не отметилось в логе, а игрок ушёл дальше: вещи всё равно сменились
        _, view, _ = build(TRIAL + zone('23:50:00', 23, 'G2_4', 'Дальше'), plan=KITS)
        self.assertEqual((view['step']['id'], worn_line(view)), ('next', 'after'))

    def test_skill_granted_by_an_item_comes_with_it(self):
        # Скелет-воин идёт от скипетра: цель умения нужна, чтобы при нём жили камни поддержки,
        # а отмечается она сама — когда скипетр надет (не просто найден).
        plan = dict(KITS, goals=KITS['goals'] + [
            {'id': 'warrior', 'group': 'Навыки', 'kind': 'skill', 'use': 'after', 'title': 'Скелет-воин',
             'grantedBy': 'sc-any', 'need': 'after'},
            {'id': 'gasp', 'group': 'Навыки', 'kind': 'support', 'use': 'after', 'title': 'Последний вздох',
             'for': 'warrior', 'need': 'next'}])
        lines = TRIAL + [ascend('23:30:00')]
        _, view, problems = build(lines, [('sc-any', 1)], plan=plan)
        self.assertEqual(problems, [])
        row = holder(view, 'skill:warrior')
        self.assertEqual((row['base']['next']['id'], row['base']['next']['urgency'], row['base']['next']['locked']),
                         ('warrior', 'due', False))
        _, view, _ = build(lines, [('sc-any', 2)], plan=plan)
        row = holder(view, 'skill:warrior')
        self.assertEqual((row['base']['have']['id'], row['base']['have']['urgency'], row['base']['have']['locked']),
                         ('warrior', 'done', True))
        # умение держит сама вещь (locked) — нажатием его не снять; камень поддержки стоит при умении (его шаг впереди —
        # пока «позже»)
        self.assertEqual([(p['label'], p['later']['id'], p['next']) for p in row['parts']], [('камень поддержки', 'gasp', None)])
        _, _, problems = build(lines, plan=dict(KITS, goals=KITS['goals'] + [
            {'id': 'warrior', 'group': 'Навыки', 'kind': 'skill', 'use': 'after', 'title': 'Скелет-воин',
             'grantedBy': 'nothing', 'need': 'after'}]))
        self.assertEqual(problems, ['Цель «warrior»: нет цели «nothing» (grantedBy)'])

    def test_marked_later_item_does_not_close_what_is_worn(self):
        # Вещь следующего периода, отмеченная рукой заранее, закрывает только свою лесенку: самострел сейчас ищут
        # по-прежнему, а внутри своей линии лучшее закрывает промежуточное.
        _, view, _ = build(ACT1, [('sc-spirit', 2)], plan=KITS)
        weapon = tile(view, 'weapon')
        self.assertEqual((weapon['next']['id'], weapon['next']['urgency']), ('bow-1', 'due'))
        self.assertEqual([(g['id'], g['urgency']) for g in view['cards'][3]['goals'][:2]],
                         [('sc-any', 'closed'), ('sc-spirit', 'done')])


# Камень умения стоит в своём гнезде: новое умение старое не вытесняет, поэтому снять его — отдельное действие.
# Шаг «Снять» страница называет там же, где «Надеть»: карточка шага, «Дальше», полный маршрут, плитка и план умения.
# Камень поддержки со своим шагом «Снять» (раньше, чем у умения) — так же; с шагом умения — уходит вместе с ним.
DROPS = dict(KITS, goals=KITS['goals'] + [
    {'id': 'boost', 'group': 'Навыки', 'kind': 'support', 'until': 'vastiri', 'title': 'Ускорение',
     'for': 'grenade', 'need': 'clearfell'}])
DROP_MARKS = [('grenade', 2), ('multishot', 2), ('boost', 2), ('bow-1', 2)]


def build_off(lines, off, marks=DROP_MARKS, plan=DROPS):
    """Как build, но игрок нажал «Снять» (run.off) — после всех событий."""
    run, _, _ = build(lines, marks, plan=plan)
    run.off = {gid: 1e10 + i for i, gid in enumerate(off)}
    return run, core.derive(core.norm_plan(plan)[0], run, 0)


def skill_holder(view, gid):
    return next((r for r in view['holders'] if r['id'] == 'skill:' + gid), None)


class DropTest(unittest.TestCase):
    def test_page_names_the_step_a_skill_comes_off(self):
        _, view, problems = build(ACT1, DROP_MARKS, plan=DROPS)
        self.assertEqual(problems, [])
        # что снимают — у карточки своего шага; камень поддержки с шагом умения отдельно не назван
        self.assertEqual([[d['id'] for d in c['drop']] for c in view['cards']], [[], [], ['boost'], ['grenade'], [], []])
        # карточка шага знает, что на нём снимают и что из этого умение, а что камень поддержки
        self.assertEqual([[(d['title'], d['skill']) for d in c['drop']] for c in view['cards'][2:4]],
                         [[('Ускорение → Граната', False)], [('Граната', True)]])
        row = skill_holder(view, 'grenade')
        self.assertFalse(row['drop'])
        # в плане умения шаги «Снять» — ячейками в своих дорожках, впереди
        self.assertEqual([(t['id'], t['needName'], t['urgency']) for t in row['timeline'] if t.get('drop')],
                         [('boost', 'Окраины Вастири', 'seek'), ('grenade', 'Испытание Сехем', 'seek')])

    def test_skill_comes_off_on_its_step(self):
        _, view, _ = build(TRIAL, DROP_MARKS, plan=DROPS)
        self.assertEqual(view['step']['drop'],
                         [{'id': 'grenade', 'title': 'Граната', 'kind': 'умение', 'skill': True, 'have': True,
                           'done': False}])
        row = skill_holder(view, 'grenade')
        self.assertTrue(row['drop'])
        self.assertEqual([(t['needName'], t['urgency']) for t in row['timeline'] if t.get('drop')], [('Испытание Сехем', 'due')])
        # не взятое умение снимать нечего, а надевать на шаге «Снять» уже незачем: ни плашки «снять», ни опоздания —
        # ни у умения, ни у его уровня камня (их заметка 2026-11-23)
        _, view, _ = build(TRIAL, [('bow-1', 2)], plan=DROPS)
        self.assertEqual(view['step']['drop'], [])
        self.assertFalse({'grenade', 'gem5'} & {g['id'] for g in view['overdue']})
        self.assertEqual(goal(view, 'grenade')['urgency'] if goal(view, 'grenade') else 'expired', 'expired')
        # впереди шаг «Снять» по-прежнему виден как план: умение могут успеть взять
        _, view, _ = build(ACT2, [('bow-1', 2)], plan=DROPS)
        self.assertEqual([d['id'] for d in view['cards'][view['pos'] + 1]['drop']], ['grenade'])

    def test_one_step_skill_is_still_wanted_on_its_step(self):
        """Умение на один шаг — «Надеть» и «Снять» на одном: на этом шаге его ещё требуют."""
        plan = dict(DROPS, goals=DROPS['goals'] + [
            {'id': 'flash', 'group': 'Навыки', 'kind': 'skill', 'until': 'trial', 'title': 'Вспышка', 'need': 'trial'}])
        _, view, _ = build(TRIAL, [('bow-1', 2)], plan=plan)
        self.assertEqual([d['id'] for d in view['step']['drop']], [])
        self.assertIn(goal(view, 'flash')['urgency'], ('due', 'seek'))

    def test_taken_off_leaves_the_page_at_once(self):
        _, view = build_off(TRIAL, ['grenade'])
        # умение со своими частями ушло сразу: ни плитки, ни опоздания по уровню камня
        self.assertIsNone(skill_holder(view, 'grenade'))
        self.assertEqual([g['id'] for g in view['overdue']], ['bow-2'])
        self.assertEqual(view['step']['drop'][0]['done'], True)
        texts = [h['text'] for h in view['history']]
        self.assertIn('Граната — снято', texts)
        # в конце шага журнал его не повторяет; кто не нажал «Снять», того журнал называет по имени
        _, view = build_off(TRIAL + [ascend('23:30:00')], ['grenade'])
        self.assertIn('Снято: Самострел · не взято: Самострел лучше, 5 уровень камня → Граната',
                      [h['text'] for h in view['history']])
        _, view, _ = build(TRIAL + [ascend('23:30:00')], DROP_MARKS, plan=DROPS)
        self.assertIsNone(skill_holder(view, 'grenade'))
        self.assertIn('Снято: Самострел, Граната · не взято: Самострел лучше, 5 уровень камня → Граната',
                      [h['text'] for h in view['history']])

    def test_off_counts_only_from_the_drop_step(self):
        # «Снять» на шаге, который страница приняла за текущий по ошибке: шаг раньше «Снять» умение остаётся в ходу
        _, view = build_off(ACT2, ['grenade'])
        row = skill_holder(view, 'grenade')
        self.assertIsNotNone(row)
        self.assertFalse(row['drop'])

    def test_support_comes_off_by_its_own_step(self):
        _, view, _ = build(ACT2, DROP_MARKS, plan=DROPS)
        self.assertEqual(view['step']['drop'], [{'id': 'boost', 'title': 'Ускорение → Граната', 'kind': 'камень поддержки',
                                                 'skill': False, 'have': True, 'done': False}])
        self.assertEqual(part(skill_holder(view, 'grenade'), 'boost')['drop'], 'boost')
        _, view = build_off(ACT2, ['boost'])
        row = skill_holder(view, 'grenade')
        # снятый камень гнездо не занимает; умение в ходу
        self.assertEqual([p['key'] for p in row['parts']], ['multishot', 'gem5'])
        self.assertIn('Граната: Ускорение — снято', [h['text'] for h in view['history']])
        # не снял — гнездо освобождается в конце шага; уровень камня, которого нет, на шаге «Снять» умения уже не ждут
        _, view, _ = build(TRIAL, DROP_MARKS, plan=DROPS)
        self.assertEqual([p['key'] for p in skill_holder(view, 'grenade')['parts']], ['multishot'])
        self.assertNotIn('gem5', {g['id'] for g in view['overdue']})

    def test_skill_without_drop_step_is_not_named(self):
        _, view, _ = build(TRIAL + [ascend('23:30:00')], [('skeleton', 2)], plan=DROPS)
        self.assertEqual(view['step']['drop'], [])
        self.assertFalse(skill_holder(view, 'skeleton')['drop'])
        self.assertFalse([t for t in skill_holder(view, 'skeleton')['timeline'] if t.get('drop')])


# Носители и части: в слоте лежит база и живут аффиксы, у умения — поддержка и уровень камня.
# У части есть уровни (тир аффикса, уровень камня) — лесенка целей с общим ключом part.
PARTS = {
    'title': 'части',
    'slots': [{'id': 'weapon', 'name': 'Оружие'}, {'id': 'boots', 'name': 'Сапоги'},
              {'id': 'helmet', 'name': 'Шлем'}],
    'steps': [
        {'id': 'riverbank', 'zone': 'G1_1', 'name': 'Берег реки'},
        {'id': 'clearfell', 'zone': 'G1_2', 'name': 'Клирфелл'},
        {'id': 'vastiri', 'zone': 'G2_1', 'name': 'Окраины Вастири'},
    ],
    'goals': [
        {'id': 'sceptre', 'slot': 'weapon', 'title': 'Скипетр', 'need': 'clearfell'},
        {'id': 'spirit-1', 'slot': 'weapon', 'part': 'spirit', 'label': 'префикс · дух', 'title': '20–26%',
         'need': 'clearfell'},
        {'id': 'spirit-2', 'slot': 'weapon', 'part': 'spirit', 'title': '27–32%', 'opens': 8},
        {'id': 'minion-1', 'slot': 'weapon', 'part': 'minion', 'label': 'суффикс · приспешники', 'title': '+1',
         'need': 'riverbank'},
        {'id': 'minion-2', 'slot': 'weapon', 'part': 'minion', 'title': '+2', 'opens': 25},
        {'id': 'boots-any', 'slot': 'boots', 'title': 'любые', 'any': True, 'soft': True, 'need': 'clearfell'},
        {'id': 'speed-1', 'slot': 'boots', 'part': 'speed', 'label': 'префикс · скорость', 'title': '10%'},
        {'id': 'speed-2', 'slot': 'boots', 'part': 'speed', 'title': '15%', 'opens': 16},
        {'id': 'helmet-any', 'slot': 'helmet', 'title': 'любой', 'any': True, 'soft': True, 'need': 'clearfell'},
        {'id': 'sniper', 'group': 'Навыки', 'kind': 'skill', 'title': 'Снайпер', 'need': 'clearfell'},
        {'id': 'lvl-5', 'group': 'Навыки', 'kind': 'gem', 'part': 'level', 'for': 'sniper', 'title': '5',
         'need': 'clearfell'},
        {'id': 'lvl-6', 'group': 'Навыки', 'kind': 'gem', 'part': 'level', 'for': 'sniper', 'title': '6', 'opens': 18},
        {'id': 'multi', 'group': 'Навыки', 'kind': 'support', 'for': 'sniper', 'title': 'Залповый огонь',
         'need': 'vastiri'},
        {'id': 'gold', 'group': 'Ресурсы', 'kind': 'resource', 'title': 'Золото', 'need': 'vastiri'},
    ],
}
ALL_PARTS = [(g, 2) for g in ('sceptre', 'spirit-1', 'minion-1', 'boots-any', 'speed-1', 'helmet-any',
                               'sniper', 'lvl-5', 'multi')]


def holder(view, rid):
    rows = view['holders'] + [r for st in view['stash'] for r in st['rows']]
    return next(r for r in rows if r['id'] == rid)


def part(row, key):
    return next(p for p in row['parts'] if p['key'] == key)


def ids(lad):
    """Лесенка коротко: (что есть, что в рюкзаке, что ищут, что позже)."""
    return tuple(lad[k]['id'] if lad[k] else None for k in ('have', 'bag', 'next', 'later'))


class HolderTest(unittest.TestCase):
    def test_slot_holds_base_and_affixes(self):
        _, view, problems = build(ACT1, plan=PARTS)
        self.assertEqual(problems, [])
        self.assertEqual([r['id'] for r in view['holders']],
                         ['slot:weapon:', 'slot:boots:', 'slot:helmet:', 'skill:sniper'])
        weapon = holder(view, 'slot:weapon:')
        self.assertEqual((weapon['kind'], weapon['state'], weapon['simple']), ('оружие', 'overdue', False))
        self.assertEqual(ids(weapon['base']), (None, None, 'sceptre', None))
        self.assertEqual([(p['key'], p['label']) for p in weapon['parts']],
                         [('spirit', 'префикс · дух'), ('minion', 'суффикс · приспешники')])
        # у каждой части своя лесенка: что ищут сейчас и что будет позже
        spirit, minion = part(weapon, 'spirit'), part(weapon, 'minion')
        self.assertEqual(ids(spirit), (None, None, 'spirit-1', 'spirit-2'))
        # opens — уровень предмета; с редкого чудовища вещь на два уровня выше зоны
        self.assertEqual((spirit['next']['urgency'], spirit['later']['since']), ('due', 'с зоны 6'))
        self.assertEqual((minion['next']['urgency'], minion['later']['since']), ('overdue', 'с зоны 23'))
        # ступень называет свою часть и знает, что лежит в её слоте
        self.assertEqual((spirit['next']['fullTitle'], spirit['next']['holderName'], spirit['later']['label']),
                         ('префикс · дух: 20–26%', 'Скипетр', 'префикс · дух'))
        self.assertEqual(view['step']['goals'][0]['kind'], 'оружие')

    def test_item_picture_name_reaches_the_page(self):
        """Поле icon у вещи — имя её картинки: item-… (сама вещь) или type-… (силуэт типа)."""
        plan = dict(PARTS, goals=[dict(g, icon='item-rattling-sceptre') if g['id'] == 'sceptre' else g
                                  for g in PARTS['goals']])
        _, view, problems = build(ACT1, plan=plan)
        self.assertEqual(problems, [])
        self.assertEqual(holder(view, 'slot:weapon:')['base']['next']['icon'], 'item-rattling-sceptre')
        # у цели без поля картинки нет: страница сама возьмёт силуэт по слоту
        self.assertIsNone(part(holder(view, 'slot:weapon:'), 'spirit')['next']['icon'])
        # имя уходит в адрес картинки, поэтому всё прочее — ошибка в плане, и картинки нет
        for bad in ('../secret', 'sceptre', 'item-Скипетр', 7):
            plan = dict(PARTS, goals=[dict(g, icon=bad) if g['id'] == 'sceptre' else g for g in PARTS['goals']])
            _, view, problems = build(ACT1, plan=plan)
            self.assertEqual(problems, ['Цель «sceptre»: icon — имя картинки вида item-…, type-… или art-…'])
            self.assertIsNone(holder(view, 'slot:weapon:')['base']['next']['icon'])

    def test_item_rarity_is_a_goal_parameter(self):
        """Редкость, какой предмет подбирают, — параметр предмета слота, словами игры: Normal, Magic, Rare."""
        with_rarity = lambda gid, val: dict(PARTS, goals=[dict(g, rarity=val) if g['id'] == gid else g for g in PARTS['goals']])   # noqa: E731
        for ok in core.ITEM_RARITIES:
            self.assertEqual(build(ACT1, plan=with_rarity('sceptre', ok))[2], [])
        refused = ['Цель «%s»: rarity — редкость предмета слота: Normal, Magic или Rare']
        for bad in ('Unique', 'rare', 'жёлтый', 7, ''):
            self.assertEqual(build(ACT1, plan=with_rarity('sceptre', bad))[2], [refused[0] % 'sceptre'])
        # у цели по стату и у цели не слота редкости нет
        stat = next(g['id'] for g in PARTS['goals'] if g.get('slot') and g.get('part'))
        free = next(g['id'] for g in PARTS['goals'] if not g.get('slot'))
        for gid in (stat, free):
            self.assertEqual(build(ACT1, plan=with_rarity(gid, 'Rare'))[2], [refused[0] % gid])

    def test_soft_slot_stays_calm(self):
        _, view, _ = build(ACT1, plan=PARTS)
        boots = holder(view, 'slot:boots:')
        # «надеть что угодно» жёлтым не горит, а аффикс без срока просто ищут
        self.assertEqual((boots['state'], boots['simple']), ('seek', False))
        self.assertEqual(ids(part(boots, 'speed')), (None, None, 'speed-1', 'speed-2'))
        helmet = holder(view, 'slot:helmet:')
        self.assertEqual((helmet['state'], helmet['simple'], helmet['parts']), ('seek', True, []))

    def test_skill_holds_supports_and_gem_level(self):
        _, view, _ = build(ACT1, plan=PARTS)
        sniper = holder(view, 'skill:sniper')
        self.assertEqual((sniper['kind'], sniper['state']), ('умение', 'due'))
        self.assertEqual(ids(sniper['base']), (None, None, 'sniper', None))
        level, support = part(sniper, 'level'), part(sniper, 'multi')
        self.assertEqual((level['label'], ids(level)), ('уровень камня', (None, None, 'lvl-5', 'lvl-6')))
        self.assertEqual(level['next']['fullTitle'], 'уровень камня: 5 → Снайпер')
        # камень поддержки вставляют на его шаге («Окраины Вастири»): раньше план его не ждёт — «позже»
        self.assertEqual((support['label'], support['single'], ids(support)),
                         ('камень поддержки', True, (None, None, None, 'multi')))
        self.assertEqual((support['later']['fullTitle'], support['later']['since']), ('Залповый огонь → Снайпер', None))

    def test_ladders_do_not_close_each_other(self):
        _, view, _ = build(ACT1, [('sceptre', 2), ('minion-1', 2)], plan=PARTS)
        weapon = holder(view, 'slot:weapon:')
        self.assertEqual(ids(weapon['base']), ('sceptre', None, None, None))
        self.assertEqual(ids(part(weapon, 'minion')), ('minion-1', None, None, 'minion-2'))
        # суффикс есть, а префикс всё ещё ищут
        self.assertEqual(ids(part(weapon, 'spirit')), (None, None, 'spirit-1', 'spirit-2'))
        self.assertEqual(weapon['state'], 'due')
        self.assertEqual(view['history'][0]['text'], 'Оружие: суффикс · приспешники: +1 — есть')
        # внутри лесенки ступень повыше закрывает нижнюю
        _, view, _ = build(ACT2, [('sceptre', 2), ('spirit-2', 2)], plan=PARTS)
        spirit = part(holder(view, 'slot:weapon:'), 'spirit')
        self.assertEqual(ids(spirit), ('spirit-2', None, None, None))
        self.assertEqual(goal(view, 'spirit-2')['urgency'], 'done')
        due = next(g for g in view['cards'][1]['goals'] if g['id'] == 'spirit-1')
        self.assertEqual(due['urgency'], 'closed')
        # уровень камня — такая же лесенка
        _, view, _ = build(ACT2 + zone('22:30:00', 18, 'G2_8', 'Глубже'), [('sniper', 2), ('lvl-6', 2)], plan=PARTS)
        self.assertEqual(ids(part(holder(view, 'skill:sniper'), 'level')), ('lvl-6', None, None, None))
        # в журнале часть умения называет и умение, и себя
        self.assertEqual(view['history'][0]['text'], 'Снайпер: уровень камня: 6 — есть')
        _, view, _ = build(ACT1, [('multi', 2)], plan=PARTS)
        self.assertEqual(view['history'][0]['text'], 'Снайпер: Залповый огонь — взято')

    def test_state_shows_the_gap_to_the_current_best_tier(self):
        # В состоянии забега сверяют не со следующей ступенью, а с актуальной — лучшей из доступных
        # сейчас: разрыв показывает, где просадка. Следующая ступень («хотя бы на одну выше») — в плане сверху.
        tiers = [('+10–19', 0), ('+20–29', 6), ('+30–39', 16), ('+40–59', 24)]
        goals = [{'id': 'body-any', 'slot': 'weapon', 'title': 'любой', 'any': True, 'soft': True}]
        goals += [dict({'id': 'life-%d' % n, 'slot': 'weapon', 'part': 'life', 'title': t},
                       **({'opens': o} if o else {}), **({'label': 'здоровье'} if n == 1 else {}))
                  for n, (t, o) in enumerate(tiers, 1)]
        plan = dict(PARTS, goals=goals)
        _, view, _ = build(ACT2, plan=plan)                      # дошли до зоны 16
        life = part(holder(view, 'slot:weapon:'), 'life')
        self.assertEqual((life['have'], life['top']['level'], life['gap']), (None, '+30–39', 3))
        _, view, _ = build(ACT2, [('life-1', 2)], plan=plan)
        life = part(holder(view, 'slot:weapon:'), 'life')
        self.assertEqual((life['have']['level'], life['top']['level'], life['gap'], life['next']['level']),
                         ('+10–19', '+30–39', 2, '+20–29'))
        _, view, _ = build(ACT2, [('life-1', 2), ('life-2', 2), ('life-3', 2)], plan=plan)
        life = part(holder(view, 'slot:weapon:'), 'life')
        # в ногу с зоной: разрыва нет, следующая ступень откроется позже
        self.assertEqual((life['have']['level'], life['gap'], life['next'], life['later']['level']),
                         ('+30–39', 0, None, '+40–59'))
        _, view, _ = build(ACT1, plan=plan)                      # зона 2: актуальна только первая ступень
        self.assertEqual(part(holder(view, 'slot:weapon:'), 'life')['gap'], 1)

    def test_stat_goal_marks_itself_by_the_remembered_item(self):
        """Цель по стату («на оружии уровень умений приспешников от +1 к такому-то шагу») отмечается
        сама — по вещи, которую игрок запомнил надетой в слоте: стата хватает — сделана, нет — горит.
        Пока вещь в слоте не запомнена, цель отмечают рукой, как любую другую."""
        goals = [{'id': 'any', 'slot': 'weapon', 'title': 'любое', 'any': True, 'soft': True},
                 {'id': 'minion', 'slot': 'weapon', 'part': 'minion', 'label': 'уровень умений приспешников',
                  'stat': 'minion_level', 'min': 1, 'title': 'от +1', 'need': 'riverbank'}]
        steps = [{'id': s['id'], 'zone': s['zone'], 'name': s['name']} for s in PARTS['steps']]
        plan = dict(PARTS, steps=steps, goals=goals)

        def state(gear=None, marks=()):
            run, view, problems = build(ACT2, marks, plan=plan)
            self.assertEqual(problems, [])
            if gear is not None:
                run.gear = gear
                view = core.derive(core.norm_plan(plan)[0], run, 0)
            row = holder(view, 'slot:weapon:')
            p = part(row, 'minion')
            g = p['have'] or p['next']
            return (g['urgency'], g['locked'], g['auto'], g['fullTitle'], row['state'], p['stat'])

        name = 'уровень умений приспешников: от +1'
        # вещь не запомнена: цель горит, отметить её можно рукой
        self.assertEqual(state(), ('overdue', False, True, name, 'overdue', 'minion_level'))
        self.assertEqual(state(marks=[('minion', 2)])[:2], ('done', False))
        # вещь запомнена: решает она — отметка рукой не в счёт, и снять её нажатием нельзя
        self.assertEqual(state({'weapon/': {'minion_level': 2}})[:2], ('done', True))
        self.assertEqual(state({'weapon/': {'spirit': 120}}, marks=[('minion', 2)])[:2], ('overdue', True))
        # вещь другого слота цели не касается
        self.assertEqual(state({'helmet/': {'minion_level': 2}})[:2], ('overdue', False))
        # запись без слота, без числа или с неизвестным статом — замечание к плану
        cat = {'stats': {'stats': {'minion_level': {}}}}
        bad = [dict(goals[1], id='a', slot=None), dict(goals[1], id='b', min='много'), dict(goals[1], id='c', stat='nope')]
        problems = core.norm_plan(dict(plan, goals=goals + bad), cat)[1]
        self.assertEqual(problems, ['Цель «a»: цели по стату нужны слот (slot) и имя части (part)',
                                    'Цель «b»: min — число, меньше которого стата быть не должно',
                                    'Цель «c»: стата «nope» нет в таблице статов данных игры'])

    def test_second_rung_of_a_stat_goal_is_what_the_plan_wants_now(self):
        """У цели по стату бывает ступень повыше («от +3» к картам). Вещь с +1 закрывает первую, вторая
        остаётся искомой со своим сроком; вещь с +3 закрывает обе. Строке цели на странице нужна ступень,
        которую план требует сейчас (plan): её полное название и заметка."""
        goals = [{'id': 'any', 'slot': 'weapon', 'title': 'любое', 'any': True, 'soft': True},
                 {'id': 'minion', 'slot': 'weapon', 'part': 'minion', 'label': 'уровень умений приспешников',
                  'stat': 'minion_level', 'min': 1, 'title': 'от +1', 'need': 'riverbank'},
                 {'id': 'minion-3', 'slot': 'weapon', 'part': 'minion', 'stat': 'minion_level', 'min': 3,
                  'title': 'от +3', 'note': 'с уровня предмета 55', 'need': 'vastiri'}]
        steps = [{'id': s['id'], 'zone': s['zone'], 'name': s['name']} for s in PARTS['steps']]
        plan = dict(PARTS, steps=steps, goals=goals)

        def state(gear):
            run, view, problems = build(ACT2, plan=plan)
            self.assertEqual(problems, [])
            run.gear = gear
            view = core.derive(core.norm_plan(plan)[0], run, 0)
            row = holder(view, 'slot:weapon:')
            p = part(row, 'minion')
            want = p['plan'] or {}
            return ((p['have'] or {}).get('fullTitle'), (p['next'] or {}).get('fullTitle'),
                    (p['next'] or {}).get('urgency'), row['state'],
                    (want.get('fullTitle'), want.get('urgency'), want.get('fact'), want.get('note')))

        low, high = 'уровень умений приспешников: от +1', 'уровень умений приспешников: от +3'
        how = (None, 'с уровня предмета 55')
        # на вещи +1: первая ступень есть, вторая — к этому шагу
        self.assertEqual(state({'weapon/': {'minion_level': 1}}), (low, high, 'due', 'due', (high, 'due') + how))
        # на вещи +3: обе ступени закрыты, у части искать нечего (строка слота ждёт только свою базу)
        self.assertEqual(state({'weapon/': {'minion_level': 3}}), (high, None, None, 'seek', (None,) * 4))
        # на вещи стата нет: первая ступень опаздывает, а требует план уже вторую — с той же срочностью
        self.assertEqual(state({'weapon/': {}}), (None, low, 'overdue', 'overdue', (high, 'overdue') + how))

    def test_how_late_a_holder_is(self):
        # Каждая строка носителя знает долю своей лесенки (надетая ступень из тех, что уже бывают);
        # строка, чьи ступени ещё не бывают, пуста. Опоздание цели со сроком считается в шагах.
        goals = [{'id': 'any', 'slot': 'weapon', 'title': 'любой', 'any': True, 'soft': True},
                 {'id': 'a-1', 'slot': 'weapon', 'part': 'a', 'label': 'суффикс · главное', 'title': '+1',
                  'need': 'riverbank'},
                 {'id': 'a-2', 'slot': 'weapon', 'part': 'a', 'title': '+2'},
                 {'id': 'b-1', 'slot': 'weapon', 'part': 'b', 'label': 'префикс · второе', 'title': '10'},
                 {'id': 'b-2', 'slot': 'weapon', 'part': 'b', 'title': '20'},
                 {'id': 'b-3', 'slot': 'weapon', 'part': 'b', 'title': '30', 'opens': 40},
                 {'id': 'c-1', 'slot': 'weapon', 'part': 'c', 'label': 'префикс · третье', 'title': '5', 'opens': 40}]
        steps = [{'id': s['id'], 'zone': s['zone'], 'name': s['name']} for s in PARTS['steps']]
        plan = dict(PARTS, steps=steps, goals=goals)
        _, view, problems = build(ACT2, [('b-1', 2)], plan=plan)   # третий шаг, зона 16
        self.assertEqual(problems, [])
        row = holder(view, 'slot:weapon:')
        a, b, c = (part(row, k) for k in 'abc')
        # главное: 0 из 2; второе: 1 из 2 (третья ступень ещё не бывает); третье: не бывает вовсе
        self.assertEqual([(p['haveN'], p['topN']) for p in (a, b, c)], [(0, 2), (1, 2), (0, 0)])
        # срок главной строки был на первом шаге, сейчас третий: опоздание — два шага
        self.assertEqual((a['next']['urgency'], a['next']['late'], row['late']), ('overdue', 2, 2))
        _, view, _ = build(ACT2, [('a-2', 2), ('b-2', 2)], plan=plan)
        self.assertEqual(holder(view, 'slot:weapon:')['late'], 0)

    def test_tier_can_drop_two_levels_above_the_zone(self):
        # Тир бывает с такого-то уровня ПРЕДМЕТА (opens), а вещь с редкого чудовища или босса на два
        # уровня выше зоны: в зоне 16 уже падает тир, который бывает с 18-го, — он и есть актуальный.
        tiers = [('+10–19', 0), ('+20–29', 17), ('+30–39', 18), ('+40–59', 19)]
        goals = [{'id': 'any', 'slot': 'weapon', 'title': 'любой', 'any': True, 'soft': True}]
        goals += [dict({'id': 'life-%d' % n, 'slot': 'weapon', 'part': 'life', 'title': t, 'tier': 5 - n},
                       **({'opens': o} if o else {}), **({'label': 'префикс · здоровье'} if n == 1 else {}))
                  for n, (t, o) in enumerate(tiers, 1)]
        _, view, _ = build(ACT2, plan=dict(PARTS, goals=goals))                    # дошли до зоны 16
        life = part(holder(view, 'slot:weapon:'), 'life')
        self.assertEqual((life['top']['id'], life['topN'], life['later']['id'], life['later']['since']),
                         ('life-3', 3, 'life-4', 'с зоны 17'))

    def test_goals_know_their_act(self):
        # Уровень и награды на странице сворачиваются по актам, поэтому цель знает акт шага, к которому
        # нужна. Шаг по событию своей зоны не имеет и стоит в акте предыдущего. Акт текущего шага
        # отдаётся отдельно: его список раскрыт.
        steps = [{'id': s['id'], 'zone': s['zone'], 'name': s['name']} for s in PARTS['steps']]
        steps.append({'id': 'after', 'event': 'ascend', 'name': 'После вознесения'})
        goals = [{'id': 'r1', 'group': 'Награды', 'title': 'Награда 1', 'need': 'clearfell'},
                 {'id': 'r2', 'group': 'Награды', 'title': 'Награда 2', 'need': 'after'},
                 {'id': 'r3', 'group': 'Награды', 'title': 'Без шага'}]
        _, view, problems = build(ACT2, plan=dict(PARTS, steps=steps, goals=goals))
        self.assertEqual(problems, [])
        got = {g['id']: g['act'] for grp in view['checks'] for g in grp['goals']}
        self.assertEqual(got, {'r1': 'Акт 1', 'r2': 'Акт 2', 'r3': None})
        self.assertEqual(view['act'], 'Акт 2')

    def test_skills_keep_the_order_of_the_plan(self):
        # Встроенное умение стоит наверху, даже если его берут позже камней: порядок умений — порядок
        # плана, а не шагов, к которым они нужны. До своего шага умение — в запасе (серое, «позже»): план его
        # там ещё не ждёт; с шага — среди умений, на своём месте по плану.
        steps = [{'id': s['id'], 'zone': s['zone'], 'name': s['name']} for s in PARTS['steps']]
        goals = [{'id': 'djinn', 'group': 'Навыки', 'kind': 'skill', 'title': 'Джинн', 'need': 'vastiri'},
                 {'id': 'sniper', 'group': 'Навыки', 'kind': 'skill', 'title': 'Снайпер', 'need': 'clearfell'}]
        _, view, problems = build(ACT1, plan=dict(PARTS, steps=steps, goals=goals))
        self.assertEqual(problems, [])
        self.assertEqual([r['id'] for r in view['holders'] if not r['slot']], ['skill:sniper'])
        self.assertEqual([r['id'] for st in view['stash'] for r in st['rows']], ['skill:djinn'])
        _, view, _ = build(ACT2, plan=dict(PARTS, steps=steps, goals=goals))
        self.assertEqual([r['id'] for r in view['holders'] if not r['slot']], ['skill:djinn', 'skill:sniper'])

    def test_skill_starts_on_its_own_step(self):
        # Автор называет у умения два шага: не позже какого получить (на нём умение берут и начинают использовать) и
        # после какого снять. Начало использования — не его поле: прежние use, from и hero у умения и его камней
        # поддержки не читаются. Камень поддержки ждут с его собственного шага, а снимают вместе с умением.
        steps = [{'id': s['id'], 'zone': s['zone'], 'name': s['name']} for s in PARTS['steps']]
        goals = [{'id': 'bomb', 'group': 'Навыки', 'kind': 'skill', 'title': 'Бомба', 'use': 'riverbank',
                  'from': 'riverbank', 'hero': 1, 'need': 'vastiri', 'until': 'vastiri'},
                 {'id': 'boost', 'group': 'Навыки', 'kind': 'support', 'for': 'bomb', 'title': 'Усиление',
                  'use': 'riverbank', 'from': 'riverbank', 'hero': 60, 'need': 'vastiri'},
                 {'id': 'bomb-5', 'group': 'Навыки', 'kind': 'gem', 'part': 'level', 'for': 'bomb', 'title': '5',
                  'use': 'riverbank', 'hero': 14, 'need': 'vastiri'}]
        raw = dict(PARTS, steps=steps, goals=goals)
        plan, problems = core.norm_plan(raw)
        self.assertEqual(problems, [])
        fields = lambda gid: {k: next(g for g in plan['goals'] if g['id'] == gid).get(k) for k in ('use', 'from', 'hero', 'until')}   # noqa: E731
        self.assertEqual(fields('bomb'), {'use': 'vastiri', 'from': None, 'hero': None, 'until': 'vastiri'})
        self.assertEqual(fields('boost'), {'use': 'vastiri', 'from': None, 'hero': None, 'until': 'vastiri'})
        # уровень героя у уровня камня — требование игры к камню этого уровня, его не трогают
        self.assertEqual(fields('bomb-5'), {'use': 'vastiri', 'from': None, 'hero': 14, 'until': 'vastiri'})
        self.assertEqual((goals[0]['use'], goals[1]['from']), ('riverbank', 'riverbank'))     # исходные записи не меняются
        # на «Клирфелле» умение и камень поддержки — «позже»: план их ещё не ждёт, но взять раньше можно
        _, view, _ = build(ACT1, plan=raw)
        self.assertEqual([(goal(view, x)['urgency'], goal(view, x)['since']) for x in ('bomb', 'boost')],
                         [('early', None), ('early', None)])
        _, view, _ = build(ACT1, [('bomb', 2), ('boost', 2)], plan=raw)
        self.assertEqual([goal(view, x)['urgency'] for x in ('bomb', 'boost')], ['done', 'done'])
        # на своём шаге — к концу шага
        _, view, _ = build(ACT2, plan=raw)
        self.assertEqual([goal(view, x)['urgency'] for x in ('bomb', 'boost')], ['due', 'due'])

    def test_support_gem_is_replaced_in_its_place(self):
        # Камень поддержки в одном месте со временем меняют (Область I, с такого-то шага — II), как базу
        # в слоте: до шага стоит первый, с шага нужен второй. Обе цели — одна часть умения (общий part).
        goals = PARTS['goals'] + [
            {'id': 'area-1', 'group': 'Навыки', 'kind': 'support', 'part': 'area', 'for': 'sniper',
             'title': 'Область I', 'need': 'clearfell'},
            {'id': 'area-2', 'group': 'Навыки', 'kind': 'support', 'part': 'area', 'for': 'sniper',
             'title': 'Область II', 'from': 'vastiri', 'need': 'vastiri'}]
        plan = dict(PARTS, goals=goals)
        _, view, problems = build(ACT1, [('sniper', 2), ('area-1', 2)], plan=plan)
        self.assertEqual(problems, [])
        area = part(holder(view, 'skill:sniper'), 'area')
        # до своего шага второй камень — «позже»: в месте стоит первый, менять ещё не просят
        self.assertEqual((area['label'], area['single'], ids(area)),
                         ('камень поддержки', False, ('area-1', None, None, 'area-2')))
        # план места виден заранее: какой камень дальше и к какому шагу — его можно вставить с опережением
        self.assertEqual({k: area['plan'][k] for k in ('id', 'urgency', 'act', 'needName')},
                         {'id': 'area-2', 'urgency': 'early', 'act': 'Акт 2', 'needName': 'Окраины Вастири'})
        _, view, _ = build(ACT2, [('sniper', 2), ('area-1', 2)], plan=plan)
        area = part(holder(view, 'skill:sniper'), 'area')
        self.assertEqual((ids(area), area['next']['urgency']), (('area-1', None, 'area-2', None), 'due'))
        self.assertEqual(area['next']['fullTitle'], 'камень поддержки: Область II → Снайпер')
        self.assertEqual((area['plan']['id'], area['plan']['urgency']), ('area-2', 'due'))
        # план умения целиком — действия по порядку шагов: что, чего касается и на каком шаге
        line = [(t['id'], t['where'], t['act'], t['needName'], t['urgency'])
                for t in holder(view, 'skill:sniper')['timeline']]
        self.assertEqual(line[0], ('sniper', 'умение', 'Акт 1', 'Клирфелл', 'done'))
        self.assertEqual([t for t in line if t[0].startswith('area')],
                         [('area-1', 'гнездо 2', 'Акт 1', 'Клирфелл', 'done'),
                          ('area-2', 'гнездо 2', 'Акт 2', 'Окраины Вастири', 'due')])
        # дорожки таблицы плана: база первой, дальше части по порядку (уровень, гнёзда)
        lanes = {t['id']: (t['lane'], t['isBase']) for t in holder(view, 'skill:sniper')['timeline']}
        self.assertEqual((lanes['sniper'], lanes['area-1'], lanes['area-2']), ((0, True), (3, False), (3, False)))
        # по порядку шагов, а внутри шага — как записано в плане
        self.assertEqual([t[3] for t in line], sorted([t[3] for t in line], key=['Клирфелл', 'Окраины Вастири'].index))
        # заменили — в месте второй, первый закрыт, плана дальше нет
        _, view, _ = build(ACT2, [('sniper', 2), ('area-1', 2), ('area-2', 2)], plan=plan)
        self.assertEqual(ids(part(holder(view, 'skill:sniper'), 'area')), ('area-2', None, None, None))
        self.assertIsNone(part(holder(view, 'skill:sniper'), 'area')['plan'])
        self.assertEqual([t['urgency'] for t in holder(view, 'skill:sniper')['timeline'] if t['id'].startswith('area')],
                         ['done', 'done'])
        # обычная поддержка рядом остаётся отдельной частью
        self.assertEqual([p['key'] for p in holder(view, 'skill:sniper')['parts']], ['level', 'multi', 'area'])

    def test_town_named_in_the_plan_is_a_step(self):
        # Город шагом не бывает — кроме того, который план сам назвал шагом: «Выход на карты» наступает
        # со входом в убежище. Боевой зоной оно не становится; ушли на карту, которой в плане нет, —
        # шаг позади, и его цели опаздывают.
        steps = [{'id': 'riverbank', 'zone': 'G1_1', 'name': 'Берег реки'},
                 {'id': 'clearfell', 'zone': 'G1_2', 'name': 'Клирфелл'},
                 {'id': 'maps', 'zone': 'G_Endgame_Town', 'name': 'Выход на карты'}]
        goals = [{'id': 'hero-65', 'group': 'Уровень', 'title': '65 уровень героя', 'reach': 65, 'need': 'maps'}]
        plan = dict(PLAN, steps=steps, goals=goals)
        town = ACT1 + zone('21:00:00', 15, 'G1_town', 'Лагерь Клирфелл')
        _, view, problems = build(town, plan=plan)
        self.assertEqual((problems, view['step']['id']), ([], 'clearfell'))   # обычный город шаг не двигает
        hub = town + zone('21:10:00', 65, 'G_Endgame_Town', 'Убежище в зиккурате')
        _, view, _ = build(hub, plan=plan)
        self.assertEqual((view['step']['id'], view['onStep'], view['beyond'], view['act']),
                         ('maps', True, False, 'Карты'))
        self.assertEqual(goal(view, 'hero-65')['urgency'], 'due')
        # в другой город и обратно — шаг тот же
        _, view, _ = build(hub + zone('21:12:00', 15, 'G1_town', 'Лагерь Клирфелл'), plan=plan)
        self.assertEqual((view['step']['id'], view['onStep']), ('maps', True))
        # первая карта: зоны в плане нет — шаг позади, уровень не набран — опаздываю
        _, view, _ = build(hub + zone('21:20:00', 65, 'MapAugury', 'Карта'), plan=plan)
        self.assertEqual((view['step']['id'], view['onStep'], view['beyond']), ('maps', False, True))
        self.assertEqual(goal(view, 'hero-65')['urgency'], 'overdue')
        # Этапы карт — шаги по уровню зон (у карт нет постоянных кодов): первая карта открывает
        # «Карты 1–5», первая зона 70-го уровня — следующий этап. Этап длится, пока не откроется
        # следующий: другая карта и город между картами его не меняют, карта пониже назад не возвращает.
        # запас по опыту: герой 2-го уровня — зоны 1–5 без штрафа (3 + 2 // 16); карта 65-го далеко за ним
        self.assertEqual(view['xp'], {'band': 3, 'lo': 1, 'hi': 5, 'zone': 65, 'out': True})
        staged = dict(plan, steps=steps + [{'id': 'maps-65', 'level': 65, 'name': 'Карты 1–5'},
                                             {'id': 'maps-70', 'level': 70, 'name': 'Карты 6–10'}])
        first = hub + zone('21:20:00', 66, 'MapAugury', 'Карта')
        _, view, problems = build(first, plan=staged)
        self.assertEqual((problems, view['step']['id'], view['onStep'], view['beyond'], view['act']),
                         ([], 'maps-65', True, False, 'Карты'))
        self.assertEqual(goal(view, 'hero-65')['urgency'], 'overdue')   # выход на карты позади
        same = first + zone('21:30:00', 65, 'G_Endgame_Town', 'Убежище в зиккурате') + zone('21:31:00', 68, 'MapCrypt', 'Карта')
        _, view, _ = build(same, plan=staged)
        self.assertEqual((view['step']['id'], view['onStep'], view['beyond']), ('maps-65', True, False))
        up = same + zone('21:40:00', 71, 'MapMire', 'Карта') + zone('21:50:00', 66, 'MapAugury', 'Карта', 2)
        _, view, _ = build(up, plan=staged)
        self.assertEqual((view['step']['id'], view['onStep']), ('maps-70', True))
        # зона кампании уровнем не считается: этап открывают только зоны, которых в плане нет
        _, _, problems = build(ACT1, plan=dict(staged, steps=staged['steps'] + [{'id': 'bad', 'level': 'x', 'name': 'Плохой'}]))
        self.assertEqual(problems, ['Шаг «bad»: level — целое число, и у такого шага нет ни зоны, ни события'])

    def test_area_with_a_level_of_its_own_does_not_open_a_map_stage(self):
        # Узел механики и арена босса живут на своём постоянном уровне («Увядшая ива» — всегда 79): игрок
        # бегает карты 73-го, зашёл к иве — этап «Карты 15–16» от этого не наступает. Какие зоны такие,
        # говорят данные игры (gamedata.own_level); без них правило прежнее.
        steps = [{'id': 'riverbank', 'zone': 'G1_1', 'name': 'Берег реки'},
                 {'id': 'maps', 'zone': 'G_Endgame_Town', 'name': 'Выход на карты'},
                 {'id': 'maps-65', 'level': 65, 'name': 'Карты 1–5'},
                 {'id': 'maps-70', 'level': 70, 'name': 'Карты 6–10'},
                 {'id': 'maps-79', 'level': 79, 'name': 'Карты 15–16'}]
        plan = dict(PLAN, steps=steps, goals=[])
        lines = (zone('20:00:00', 1, 'G1_1', 'Берег реки') + zone('21:10:00', 65, 'G_Endgame_Town', 'Убежище в зиккурате')
                 + zone('21:20:00', 73, 'MapSteppe', 'Карта')
                 + zone('21:40:00', 79, 'MapUberBoss_Delirium', 'Увядшая ива')
                 + zone('21:50:00', 72, 'MapMarrow', 'Карта', 2))
        run, view, problems = build(lines, plan=plan)
        self.assertEqual((problems, view['step']['id']), ([], 'maps-79'))   # без данных игры — как раньше
        norm, _ = core.norm_plan(plan)
        view = core.derive(norm, run, 0, own_level={'MapUberBoss_Delirium'})
        self.assertEqual((view['step']['id'], view['onStep'], view['beyond']), ('maps-70', True, False))
        # настоящая карта 79-го уровня этап открывает
        run, _, _ = build(lines + zone('22:00:00', 79, 'MapCrypt', 'Карта', 3), plan=plan)
        view = core.derive(norm, run, 0, own_level={'MapUberBoss_Delirium'})
        self.assertEqual(view['step']['id'], 'maps-79')
        # какие зоны такие: уровень в данных выше уровня любого города
        import gamedata
        cat = {'areas': {'G_Endgame_Town': {'level': 65, 'town': True}, 'G1_town': {'level': 15, 'town': True},
                         'MapSteppe': {'level': 65, 'town': False}, 'G1_2': {'level': 2, 'town': False},
                         'MapUberBoss_Delirium': {'level': 79, 'town': False},
                         'MapUberBoss_Monolith': {'level': 74, 'town': False}}}
        self.assertEqual(gamedata.own_level(cat), {'MapUberBoss_Delirium', 'MapUberBoss_Monolith'})
        self.assertEqual(gamedata.own_level(None), frozenset())

    def test_filter_is_checked_for_the_zone_the_hero_goes_to(self):
        # Фильтр проверяется для зоны, где герой сейчас; в городе — для последней боевой зоны: в неё возвращаются.
        # Но с шага без своей боевой зоны (шаг-город «Выход на карты», шаг по событию) возвращаться некуда: из
        # города идут на шаг впереди. Фильтр для карт (правила с AreaLevel >= 65), загруженный в убежище,
        # проверяется для этапа карт, а не для последней зоны кампании 64-го уровня.
        steps = [{'id': 'riverbank', 'zone': 'G1_1', 'name': 'Берег реки'},
                 {'id': 'estate', 'zone': 'P1_6', 'name': 'Поместье Холтен'},
                 {'id': 'maps', 'zone': 'G_Endgame_Town', 'name': 'Выход на карты'},
                 {'id': 'maps-65', 'level': 65, 'name': 'Карты 1–5'},
                 {'id': 'maps-70', 'level': 70, 'name': 'Карты 6–10'}]
        plan = dict(PLAN, steps=steps, goals=[{'id': 'sc', 'group': 'Проверка', 'title': 'Скипетр', 'need': 'maps-65'}])
        norm, problems = core.norm_plan(plan)
        self.assertEqual(problems, [])

        def look(lines, plan=plan, norm=norm, **more):
            run, _, _ = build(lines, plan=plan)
            view = core.derive(norm, run, 0, lambda level: {'sc': 'show' if level >= 65 else 'hide'}, **more)
            return view['step']['id'], view['filter']['level'], goal(view, 'sc')['ground']

        camp = zone('20:00:00', 1, 'G1_1', 'Берег реки') + zone('20:30:00', 64, 'P1_6', 'Поместье Холтен')
        self.assertEqual(look(camp), ('estate', 64, 'hide'))                        # в боевой зоне — её уровень
        # город посреди шага боевой зоны: вернутся в неё же
        self.assertEqual(look(camp + zone('20:40:00', 64, 'P1_Town', 'Караван Ардура')), ('estate', 64, 'hide'))
        # убежище, откуда ходят на карты: шаг-город, впереди этап карт с 65-го уровня
        hub = camp + zone('21:00:00', 65, 'G_Endgame_Town', 'Убежище в зиккурате')
        self.assertEqual(look(hub), ('maps', 65, 'show'))
        # с этого шага вернулись в зону кампании — проверяется она; снова убежище — снова этап карт
        back = hub + zone('21:05:00', 64, 'P1_6', 'Поместье Холтен', 2)
        self.assertEqual(look(back), ('maps', 64, 'hide'))
        self.assertEqual(look(back + zone('21:08:00', 65, 'G_Endgame_Town', 'Убежище в зиккурате')), ('maps', 65, 'show'))
        # на карте — уровень карты; в убежище между картами — уровень последней карты, а не следующего этапа
        first = hub + zone('21:10:00', 66, 'MapAugury', 'Карта')
        self.assertEqual(look(first), ('maps-65', 66, 'show'))
        self.assertEqual(look(first + zone('21:20:00', 65, 'G_Endgame_Town', 'Убежище в зиккурате')), ('maps-65', 66, 'show'))
        # готовый словарь вместо функции — как раньше; уровень проверки страница знает и тогда
        run, _, _ = build(hub, plan=plan)
        view = core.derive(norm, run, 0, {'sc': 'hide'})
        self.assertEqual((view['filter']['level'], goal(view, 'sc')['ground']), (65, 'hide'))
        self.assertIsNone(goal(core.derive(norm, run, 0), 'sc')['ground'])

        # Шаг по событию: после вознесения в городе — зона шага впереди. Её уровень называют данные игры; у зоны
        # там младший уровень, поэтому ниже последней боевой зоны проверка не опускается.
        steps = [{'id': 'riverbank', 'zone': 'G1_1', 'name': 'Берег реки'},
                 {'id': 'trial', 'zone': 'G2_13', 'name': 'Испытание Сехем'},
                 {'id': 'after', 'event': 'ascend', 'name': 'После вознесения'},
                 {'id': 'pass', 'zone': 'G2_5_1', 'name': 'Перевал'}]
        plan2 = dict(PLAN, steps=steps, goals=[{'id': 'sc', 'group': 'Проверка', 'title': 'Скипетр', 'need': 'pass'}])
        norm2, problems = core.norm_plan(plan2)
        self.assertEqual(problems, [])
        risen = (zone('20:00:00', 1, 'G1_1', 'Берег реки') + zone('20:30:00', 22, 'G2_13', 'Испытание Сехем')
                 + [ascend('20:50:00')])
        self.assertEqual(look(risen, plan2, norm2, zone_levels={'G2_5_1': 70})[:2], ('after', 22))   # ещё в испытании
        town = risen + zone('21:00:00', 32, 'G2_town', 'Караван Ардура')
        self.assertEqual(look(town, plan2, norm2, zone_levels={'G2_5_1': 70}), ('after', 70, 'show'))
        self.assertEqual(look(town, plan2, norm2, zone_levels={'G2_5_1': 21}), ('after', 22, 'hide'))
        self.assertEqual(look(town, plan2, norm2), ('after', 22, 'hide'))                   # данных игры нет

        # сама функция: шага ещё нет, боевой зоны ещё не было, впереди ничего с уровнем
        z = lambda code, level: {'code': code, 'level': level}      # noqa: E731
        self.assertEqual(core.ground_level(steps, None, None, None), 1)
        self.assertEqual(core.ground_level(steps, None, z('G1_town', 15), None), 1)
        self.assertEqual(core.ground_level(steps[:3], 2, z('G2_town', 32), z('G2_13', 22), {'G2_5_1': 70}), 22)
        import gamedata
        cat = {'areas': {'G1_town': {'level': 15, 'town': True}, 'G1_2': {'level': 2, 'town': False},
                         'G_login': {'level': 0, 'town': False}, 'X': {'town': False}}}
        self.assertEqual(gamedata.zone_levels(cat), {'G1_2': 2})
        self.assertEqual(gamedata.zone_levels(None), {})

    def test_gem_level_runs_from_the_starting_level_to_what_the_hero_can_wear(self):
        # Уровень камня — лесенка, как тир аффикса: «моё» и «актуальное». Ступени в плане не пишут: они
        # идут от стартового уровня умения (gemFrom) по таблице gemLevels — с какого уровня героя камень
        # такого уровня носят. Стартовый уровень приходит вместе с умением: «нет уровня» не бывает.
        # В плане пишут только уровни со сроком — по ним и опаздывают.
        steps = [{'id': 'riverbank', 'zone': 'G1_1', 'name': 'Берег реки'},
                 {'id': 'clearfell', 'zone': 'G1_2', 'name': 'Клирфелл'},
                 {'id': 'vastiri', 'zone': 'G2_1', 'name': 'Окраины Вастири'},
                 {'id': 'trial', 'zone': 'G2_13', 'name': 'Испытание Сехем'}]
        goals = [{'id': 'skill-mage', 'group': 'Навыки', 'kind': 'skill', 'title': 'Маг', 'need': 'clearfell',
                  'gemFrom': 3},
                 {'id': 'gem5-mage', 'group': 'Навыки', 'kind': 'gem', 'part': 'level', 'for': 'skill-mage',
                  'title': '5', 'need': 'vastiri'}]
        plan = dict(PARTS, steps=steps, goals=goals, gemLevels=[0, 3, 6, 10, 14, 18])
        hero10 = ACT1 + [lvl('20:30:00', 10)]
        vastiri = hero10 + zone('22:00:00', 16, 'G2_1', 'Окраины Вастири')
        trial = vastiri + zone('23:00:00', 22, 'G2_13', 'Испытание Сехем')

        def level(lines, *marked):
            _, view, problems = build(lines, [(g, 2) for g in marked], plan=plan)
            self.assertEqual(problems, [])
            return view, part(holder(view, 'skill:skill-mage'), 'level')

        # камня ещё нет — нет и уровня; ступени от стартового до последнего в таблице
        view, lad = level(hero10)
        self.assertEqual(lad['chain'], ['gem3-mage', 'gem4-mage', 'gem5-mage', 'gem6-mage'])
        self.assertEqual((lad['label'], lad['have']), ('уровень камня', None))
        # камень взяли: стартовый уровень есть сам; актуальный — тот, что герой уже может носить
        view, lad = level(hero10, 'skill-mage')
        self.assertEqual(ids(lad), ('gem3-mage', None, 'gem4-mage', 'gem5-mage'))
        # стартовый уровень приходит с камнем (locked): нажатием его не снять
        self.assertEqual((lad['have']['locked'], lad['top']['id'], lad['gap']), (True, 'gem4-mage', 1))
        self.assertEqual(lad['later']['since'], 'с 14 уровня')
        # подняли на один — в ногу с уровнем героя
        view, lad = level(hero10, 'skill-mage', 'gem4-mage')
        self.assertEqual((ids(lad), lad['gap'], lad['have']['status'], lad['have']['locked']),
                         (('gem4-mage', None, None, 'gem5-mage'), 0, 2, False))
        # уровень со сроком горит на своём шаге, даже когда героя для него ещё не хватает; что мешает — под ним
        view, lad = level(vastiri, 'skill-mage')
        due = view['step']['goals'][0]
        self.assertEqual((due['id'], due['urgency'], due['fact']), ('gem5-mage', 'due', 'с 14 уровня'))
        self.assertEqual((lad['top']['id'], lad['gap'], lad['next']['id']), ('gem5-mage', 2, 'gem4-mage'))
        self.assertEqual((lad['next']['urgency'], lad['next']['aim']), ('due', '5'))
        # шаг позади — в списке опозданий сам уровень со сроком, а ближайшая ступень берёт его срочность:
        # по ней плитка умения видит, что камень отстаёт от плана, на сколько шагов и чего план требует
        view, lad = level(trial, 'skill-mage')
        self.assertEqual([g['id'] for g in view['overdue']], ['gem5-mage'])
        self.assertEqual((lad['next']['id'], lad['next']['urgency'], lad['next']['late'], lad['next']['aim']),
                         ('gem4-mage', 'overdue', 1, '5'))
        row = holder(view, 'skill:skill-mage')
        self.assertEqual((row['state'], row['late']), ('overdue', 1))
        # камень поднят до уровня плана — опоздания нет, выше него сроков нет
        view, lad = level(trial, 'skill-mage', 'gem4-mage')
        self.assertEqual((lad['next']['id'], lad['next']['urgency']), ('gem5-mage', 'overdue'))
        # сразу на 5 (камень 5-го уровня поверх стартового): ступень между ними закрыта
        view, lad = level(trial, 'skill-mage', 'gem5-mage')
        self.assertEqual((lad['have']['id'], lad['gap'], view['overdue']), ('gem5-mage', 0, []))
        self.assertEqual(goal(view, 'gem4-mage')['urgency'], 'closed')
        view, lad = level(trial + [lvl('23:30:00', 18)], 'skill-mage', 'gem5-mage')
        self.assertEqual((lad['top']['id'], lad['gap'], lad['next']['id']), ('gem6-mage', 1, 'gem6-mage'))
        # без таблицы лесенку не построить; уровня ниже стартового у умения не бывает
        _, _, problems = build(ACT1, plan=dict(plan, gemLevels=[]))
        self.assertEqual(problems, ['Умение «skill-mage»: нет таблицы gemLevels'])
        low = {'id': 'gem2-mage', 'kind': 'gem', 'part': 'level', 'for': 'skill-mage', 'title': '2'}
        _, _, problems = build(ACT1, plan=dict(plan, goals=goals + [low]))
        self.assertEqual(problems, ['Цель «gem2-mage»: уровня камня 2 у умения «skill-mage» не бывает'])

    def test_skill_taken_early_lists_every_level_the_hero_can_wear(self):
        """Умение взяли раньше плана: в списке уровней камня — все уровни, какие герой уже может носить, а не только
        стартовый (их заметка 2026-11-24: в игре камень был выше стартового, а выбрать такой уровень было нельзя)."""
        steps = [{'id': 'riverbank', 'zone': 'G1_1', 'name': 'Берег реки'},
                 {'id': 'clearfell', 'zone': 'G1_2', 'name': 'Клирфелл'},
                 {'id': 'vastiri', 'zone': 'G2_1', 'name': 'Окраины Вастири'}]
        hero10 = ACT1 + [lvl('20:30:00', 10)]
        for need in ('vastiri', 'clearfell'):          # шаг умения впереди — и уже настал: список один и тот же
            goals = [{'id': 'skill-mage', 'group': 'Навыки', 'kind': 'skill', 'title': 'Маг', 'need': need, 'gemFrom': 3}]
            plan = dict(PARTS, steps=steps, goals=goals, gemLevels=[0, 3, 6, 10, 14, 18])
            for marks in ([], [('skill-mage', 2)]):
                _, view, problems = build(hero10, marks, plan=plan)
                self.assertEqual(problems, [])
                lad = part(holder(view, 'skill:skill-mage'), 'level')
                # герою 10: камень 4-го уровня он уже носит, 5-го (с 14) — ещё нет
                self.assertEqual([(r['id'], r['open']) for r in lad['rungs']],
                                 [('gem3-mage', True), ('gem4-mage', True), ('gem5-mage', False), ('gem6-mage', False)])

    def test_goal_with_a_number_says_how_much_there_is_now(self):
        """У цели, где нужное — число, сказано, сколько есть сейчас (now): уровень героя, уровень камня, стат на
        предмете, запомненном в слоте, — по разнице видно, срочно ли (их замечание 2026-11-25: нужный уровень камня
        был виден, а какой у камня сейчас — нет). Пустая строка — сейчас ничего нет; None — цель не о числе или
        программа не знает (предмет слота не запомнен)."""
        steps = [{'id': 'riverbank', 'zone': 'G1_1', 'name': 'Берег реки'},
                 {'id': 'clearfell', 'zone': 'G1_2', 'name': 'Клирфелл'},
                 {'id': 'vastiri', 'zone': 'G2_1', 'name': 'Окраины Вастири'},
                 {'id': 'trial', 'zone': 'G2_13', 'name': 'Испытание Сехем'}]
        goals = [{'id': 'any', 'slot': 'weapon', 'title': 'любое', 'any': True, 'soft': True},
                 {'id': 'spirit', 'slot': 'weapon', 'part': 'spirit', 'label': 'дух скипетра', 'stat': 'spirit',
                  'min': 120, 'title': 'от 120', 'need': 'vastiri'},
                 {'id': 'ally', 'slot': 'weapon', 'part': 'ally', 'label': 'урон союзников', 'stat': 'ally_damage',
                  'min': 75, 'title': 'от 75%', 'need': 'vastiri'},
                 {'id': 'minion', 'slot': 'weapon', 'part': 'minion', 'label': 'уровень умений приспешников',
                  'stat': 'minion_level', 'min': 3, 'title': 'от +3', 'need': 'vastiri'},
                 {'id': 'skill-mage', 'group': 'Навыки', 'kind': 'skill', 'title': 'Маг', 'need': 'clearfell',
                  'gemFrom': 3},
                 {'id': 'gem5-mage', 'group': 'Навыки', 'kind': 'gem', 'part': 'level', 'for': 'skill-mage',
                  'title': '5', 'need': 'vastiri'},
                 {'id': 'hero-16', 'group': 'Уровень', 'title': '16 уровень героя', 'reach': 16, 'need': 'vastiri'},
                 {'id': 'gold', 'group': 'Ресурсы', 'title': 'Золото', 'need': 'vastiri'}]
        plan = dict(PARTS, steps=steps, goals=goals, gemLevels=[0, 3, 6, 10, 14, 18])
        vastiri = ACT1 + [lvl('20:30:00', 10)] + zone('22:00:00', 16, 'G2_1', 'Окраины Вастири')
        trial = vastiri + zone('23:00:00', 22, 'G2_13', 'Испытание Сехем')

        def state(lines=vastiri, marks=(), gear=None):
            run, view, problems = build(lines, [(g, 2) for g in marks], plan=plan)
            self.assertEqual(problems, [])
            if gear is not None:
                run.gear = gear
                view = core.derive(core.norm_plan(plan)[0], run, 0)
            return view

        def now(view, where='step'):
            found = view['step']['goals'] if where == 'step' else view[where]
            return {g['id']: g['now'] for g in found}

        # уровень героя — из лога; камня умения ещё нет — пусто; предмет слота не запомнен — о стате программа не знает;
        # цель не о числе — None
        self.assertEqual(now(state()), {'spirit': None, 'ally': None, 'minion': None, 'gem5-mage': '', 'hero-16': '10',
                                        'gold': None})
        # умение взяли: у камня стартовый уровень; подняли — тот, до которого подняли
        self.assertEqual(now(state(marks=['skill-mage']))['gem5-mage'], '3')
        view = state(marks=['skill-mage', 'gem4-mage'])
        self.assertEqual(now(view)['gem5-mage'], '4')
        # то же число у ступени в строке умения (её копия в лесенке) и у закрытых ступеней под ней
        lad = part(holder(view, 'skill:skill-mage'), 'level')
        self.assertEqual((lad['next']['id'], lad['next']['now'], lad['have']['now']), ('gem5-mage', '4', '4'))
        self.assertEqual(goal(view, 'gem5-mage')['now'], '4')
        # стат — с предмета, запомненного в слоте, в том же виде, что и нужное: «от +3» — «+1», «от 75%» — «60%»
        got = now(state(gear={'weapon/': {'spirit': 95.0, 'ally_damage': 60, 'minion_level': 1}}))
        self.assertEqual((got['spirit'], got['ally'], got['minion']), ('95', '60%', '+1'))
        # стата на предмете нет — пусто; набранное число называется так же (цель сделана — страница его не покажет)
        got = now(state(gear={'weapon/': {'spirit': 123}}))
        self.assertEqual((got['spirit'], got['ally'], got['minion']), ('123', '', ''))
        # шаг позади: в опозданиях у цели то же «сейчас» — по нему решают, что навёрстывать первым
        late = now(state(trial, ['skill-mage'], {'weapon/': {'spirit': 95}}), 'overdue')
        self.assertEqual((late['gem5-mage'], late['hero-16'], late['spirit'], late['ally']), ('3', '10', '95', ''))

    def test_checks_are_what_does_not_live_in_a_holder(self):
        _, view, _ = build(ACT1, plan=PARTS)
        self.assertEqual([(c['name'], [g['id'] for g in c['goals']]) for c in view['checks']],
                         [('Ресурсы', ['gold'])])
        self.assertEqual([(g['id'], g['holder']) for g in view['overdue']], [('minion-1', True)])

    def test_retired_things_leave_the_rows(self):
        marks = [('bow-1', 2), ('gold', 2), ('sc-any', 1), ('shield', 1), ('grenade', 2)]
        _, view, _ = build(TRIAL + [ascend('23:30:00')], marks, plan=KITS)
        self.assertEqual([r['id'] for r in view['holders']], ['slot:weapon:', 'slot:offhand:', 'skill:skeleton'])
        weapon = holder(view, 'slot:weapon:')
        # строка оружия — то, что план ждёт сейчас: самострел ушёл со своим периодом, скипетр ищут (отметка «в рюкзаке»
        # прежних забегов ничего не значит), +2 — позже
        self.assertEqual(ids(weapon['base']), (None, None, 'sc-any', 'sc-plus2'))
        self.assertEqual((weapon['state'], holder(view, 'slot:offhand:')['state']), ('overdue', 'overdue'))
        self.assertEqual(view['stash'], [])

    def test_retired_item_takes_its_affix_rows_along(self):
        """Аффикс снятой вещи уходит вместе с ней: строка «стихийный урон» самострела
        не остаётся в слоте оружия, когда носят уже скипетр."""
        plan = dict(KITS, goals=KITS['goals'] + [
            {'id': 'bow-elem', 'slot': 'weapon', 'until': 'trial', 'part': 'elem',
             'label': 'префикс · стихийный урон (любой)', 'tier': 10, 'need': 'clearfell'},
            {'id': 'bow-elem-9', 'slot': 'weapon', 'until': 'trial', 'part': 'elem', 'tier': 9},
            {'id': 'sc-minion', 'slot': 'weapon', 'use': 'after', 'part': 'minion',
             'label': 'суффикс · приспешники', 'title': '+1', 'tier': 4},
        ])
        marks = [('bow-1', 2), ('bow-elem', 2)]
        # пока носят самострел — его аффикс в строке оружия; аффикс скипетра — цель «позже», отдельной строки запаса нет
        _, view, problems = build(ACT2, marks, plan=plan)
        self.assertEqual(problems, [])
        self.assertEqual([p['key'] for p in holder(view, 'slot:weapon:')['parts']], ['elem'])
        # (строка у слота есть всегда: во второй руке план сейчас ничего не ждёт, но надеть в неё можно)
        self.assertEqual([r['id'] for r in view['holders']], ['slot:weapon:', 'slot:offhand:', 'skill:grenade'])
        self.assertEqual((holder(view, 'slot:offhand:')['base'], holder(view, 'slot:offhand:')['state']), (None, 'idle'))
        self.assertEqual(goal(view, 'sc-minion'), None)        # срока нет — ни на какой карточке шага её нет
        # после вознесения в строке оружия — только аффиксы скипетра; самострел целиком среди снятого
        _, view, _ = build(TRIAL + [ascend('23:30:00')], marks, plan=plan)
        self.assertEqual([p['key'] for p in holder(view, 'slot:weapon:')['parts']], ['minion'])
        retired = {g['id'] for r in view['retired'] if r['id'] == 'trial' for g in r['goals']}
        self.assertTrue({'bow-1', 'bow-elem'} <= retired)
        # тир без срока, до которого так и не дошли, целью не был — в разборе его нет
        self.assertNotIn('bow-elem-9', retired)


# Боссы — цели вида boss на своём шаге: обязательный (must), с наградой (группа, иногда reward
# для автоотметки по логу) и необязательный без награды (soft).
BOSSES = dict(ROUTE, goals=ROUTE['goals'] + [
    {'id': 'boss-miller', 'kind': 'boss', 'must': True, 'title': 'Мельник', 'need': 'riverbank'},
    {'id': 'boss-beira', 'kind': 'boss', 'group': 'Награды', 'title': 'Бейра: +10% холода',
     'reward': 'base_cold_damage_resistance_%', 'need': 'clearfell'},
    {'id': 'boss-king', 'kind': 'boss', 'must': True, 'title': 'Ржавый король', 'need': 'redvale'},
    {'id': 'boss-druid', 'kind': 'boss', 'soft': True, 'title': 'Друид', 'need': 'tangle'},
    {'id': 'boss-relic', 'kind': 'boss', 'group': 'Награды', 'title': 'Страж: реликвия', 'need': 'tangle'},
    {'id': 'hut', 'group': 'Награды', 'title': 'Хижина: +2 очка', 'reward': 'passive_points', 'need': 'cemetery'},
])
NO_REWARD = [line for line in RUN_LINES if 'сопротивлению' not in line]
CEMETERY = zone('21:39:18', 7, 'G1_7', 'Кладбище Вечных')


def points(t):
    return ['%s %s 1000 abcd [INFO Client 1] : Вы получили 2 очка пассивных умений для набора оружия.' % (DAY, t)]


def boss(view, step, gid):
    card = next(c for c in view['cards'] if c['id'] == step)
    return next(b for b in card['bosses'] if b['id'] == gid)


class BossTest(unittest.TestCase):
    def test_bosses_sit_on_their_step(self):
        _, view, problems = build(RUN_LINES, plan=BOSSES)
        self.assertEqual(problems, [])
        self.assertEqual([[b['id'] for b in c['bosses']] for c in view['cards']],
                         [['boss-miller'], ['boss-beira'], [], ['boss-king'], [], ['boss-druid', 'boss-relic'], [], []])
        # босс с наградой подписан как босс, а не как награда
        self.assertEqual({b['kind'] for c in view['cards'] for b in c['bosses']}, {'босс'})
        # до своей карты босс — «позже»
        king = boss(view, 'redvale', 'boss-king')
        self.assertEqual((king['urgency'], king['since'], king['must']), ('early', 'с шага «Красная Долина»', True))
        _, _, problems = build(RUN_LINES, plan=dict(BOSSES, goals=BOSSES['goals'] + [
            {'id': 'x', 'kind': 'boss', 'title': 'x'}]))
        self.assertEqual(problems, ['Босс «x»: не указан шаг (need)'])

    def test_must_boss_closes_itself_when_the_step_is_behind(self):
        full = RUN_LINES + RUN_TAIL
        _, view, _ = build(upto(full, gen('21:13:41', 15, 'G1_town')), plan=BOSSES)
        king = boss(view, 'redvale', 'boss-king')
        self.assertEqual((view['step']['id'], king['urgency'], king['locked']), ('redvale', 'due', False))
        # шаг позади — обязательный босс убит, отмечать его не нужно
        _, view, _ = build(full, plan=BOSSES)
        king = boss(view, 'redvale', 'boss-king')
        self.assertEqual((king['urgency'], king['locked']), ('done', True))
        miller = boss(view, 'riverbank', 'boss-miller')
        self.assertEqual((miller['urgency'], miller['locked']), ('done', True))
        self.assertEqual(view['missed'], [])

    def test_reward_in_the_log_marks_the_boss(self):
        _, view, _ = build(RUN_LINES, plan=BOSSES)
        beira = boss(view, 'clearfell', 'boss-beira')
        self.assertEqual((beira['urgency'], beira['locked'], beira['auto']), ('done', True, True))

    def test_boss_death_is_heard_in_the_log(self):
        # После боя кто-то всегда говорит одно и то же: по этой реплике босс отмечается сам, не дожидаясь
        # следующей карты. Если реплику в игре поменяют, обязательного босса закроет маршрут, как раньше.
        plan = dict(BOSSES, goals=[dict(g, heard=['AsalaDone', 'AsalaDone2']) if g['id'] == 'boss-king' else g
                                   for g in BOSSES['goals']])
        before = upto(RUN_LINES + RUN_TAIL, gen('21:13:41', 15, 'G1_town'))     # на шаге «Красная Долина»
        _, view, problems = build(before, plan=plan)
        self.assertEqual(problems, [])
        king = boss(view, 'redvale', 'boss-king')
        self.assertEqual((king['urgency'], king['auto'], king['locked']), ('due', True, False))
        _, view, _ = build(before + [say('21:10:00', 'Асала', '<<set:F>><<set:S>>Дело сделано.')], plan=plan)
        king = boss(view, 'redvale', 'boss-king')
        self.assertEqual((view['step']['id'], king['urgency'], king['locked']), ('redvale', 'done', True))
        self.assertEqual(view['history'][0]['text'], 'Босс убит: Ржавый король')
        # та же реплика на чужой карте босса не закрывает
        _, view, _ = build(RUN_LINES + [say('20:41:00', 'Асала', 'Дело сделано.')], plan=plan)
        self.assertEqual(boss(view, 'redvale', 'boss-king')['urgency'], 'early')

    def test_goal_not_tied_to_a_map_is_heard_anywhere(self):
        # Части оружия собирают на любых островах, а нужны они к одному шагу: такая цель (не босс,
        # не задание карты, не награда) отмечается по реплике, где бы та ни прозвучала.
        goals = BOSSES['goals'] + [{'id': 'piece-1', 'kind': 'resource', 'group': 'Ресурсы', 'title': 'Часть оружия 1',
                                    'heard': 'HoodedPiece1', 'need': 'cemetery'}]
        plan = dict(BOSSES, goals=goals)
        lines = RUN_LINES + [say('20:41:00', 'Скрытный', '<<set:F>>Теперь мы должны найти остальные. Поспеши.')]
        _, view, problems = build(lines, plan=plan)
        self.assertEqual(problems, [])
        piece = next(g for grp in view['checks'] for g in grp['goals'] if g['id'] == 'piece-1')
        self.assertEqual((piece['urgency'], piece['closedBy']), ('done', 'phrase'))
        # без реплики цель ждёт своего шага
        _, view, _ = build(RUN_LINES, plan=plan)
        piece = next(g for grp in view['checks'] for g in grp['goals'] if g['id'] == 'piece-1')
        self.assertEqual(piece['urgency'], 'seek')
        # Ту же реплику ждёт и босс карты, где часть подбирают: она засчитывается обоим, но боссу —
        # только на своей карте, и в журнал попадает каждая засчитанная цель.
        phrase = 'HoodedPiece1'
        goals2 = [dict(g, heard=phrase) if g['id'] in ('boss-king', 'boss-beira') else g for g in goals]
        before = upto(RUN_LINES + RUN_TAIL, gen('21:13:41', 15, 'G1_town'))     # на шаге «Красная Долина»
        _, view, _ = build(before + [say('21:10:00', 'Скрытный', 'Теперь мы должны найти остальные. Поспеши.')], plan=dict(BOSSES, goals=goals2))
        got = {b['id']: b['closedBy'] for b in view['bosses'] if b['id'] in ('boss-king', 'boss-beira')}
        self.assertEqual(got, {'boss-king': 'phrase', 'boss-beira': 'reward'})
        self.assertEqual([h['text'] for h in view['history'][:2]], ['По логу: Часть оружия 1', 'Босс убит: Ржавый король'])

    def test_bosses_carry_their_properties(self):
        # Босс — сущность со свойствами: финальный босс акта, закрывает ли проход, как должен отмечаться
        # (реплика, награда, переход, рукой) и как отметился на деле. Ждали реплику, а босс закрылся
        # переходом — нестыковка: по ней план правят к следующему забегу.
        goals = [dict(g, heard='AsalaDone', final=True) if g['id'] == 'boss-king' else g
                 for g in BOSSES['goals']]
        plan = dict(BOSSES, goals=goals)
        _, view, problems = build(RUN_LINES + RUN_TAIL, [('boss-relic', 2)], plan=plan)   # Красная Долина пройдена
        self.assertEqual(problems, [])
        got = {b['id']: (b['final'], b['must'], b['expect'], b['closedBy'], b['mismatch']) for b in view['bosses']}
        self.assertEqual(got, {
            'boss-miller': (False, True, 'pass', 'pass', None),
            'boss-beira': (False, False, 'reward', 'reward', None),
            'boss-king': (True, True, 'phrase', 'pass', 'реплика не прозвучала'),
            'boss-druid': (False, False, 'hand', None, None),
            'boss-relic': (False, False, 'hand', 'hand', None)})
        # все боссы плана, по порядку маршрута
        self.assertEqual([b['id'] for b in view['bosses']],
                         ['boss-miller', 'boss-beira', 'boss-king', 'boss-druid', 'boss-relic'])
        # реплика прозвучала на своей карте — нестыковки нет
        lines = upto(RUN_LINES + RUN_TAIL, gen('21:13:41', 15, 'G1_town')) + [say('21:10:00', 'Асала', 'Дело сделано.')]
        _, view, _ = build(lines, plan=plan)
        king = next(b for b in view['bosses'] if b['id'] == 'boss-king')
        self.assertEqual((king['closedBy'], king['mismatch']), ('phrase', None))
        # награду отметили рукой, потому что строки в логе не было
        _, view, _ = build(NO_REWARD + RUN_TAIL, [('boss-beira', 2)], plan=plan)
        beira = next(b for b in view['bosses'] if b['id'] == 'boss-beira')
        self.assertEqual((beira['closedBy'], beira['mismatch']), ('hand', 'награды в логе не было'))

    def test_boss_death_can_sound_in_several_ways(self):
        # Победа звучит не всегда одинаково: то босс сдаётся сам, то о его поражении объявляет другой.
        # Поле heard берёт и список — хватит любой реплики. Обращение по роду героя в логе записано
        # обоими вариантами с разметкой («<if:MS>{…}<elif:FS>{…}») — фраза сравнивается без неё.
        plan = dict(BOSSES, goals=[dict(g, heard=['YamaDefeat', 'NavaliDefeat'])
                                   if g['id'] == 'boss-king' else g for g in BOSSES['goals']])
        before = upto(RUN_LINES + RUN_TAIL, gen('21:13:41', 15, 'G1_town'))     # на шаге «Красная Долина»
        self.assertEqual(core.heard_ids(core.norm_plan(plan)[0]), ('NavaliDefeat', 'YamaDefeat'))
        self.assertEqual(boss(build(before, plan=plan)[1], 'redvale', 'boss-king')['urgency'], 'due')
        for who, text in (('Яма', '<<set:F>><<set:S>><if:MS>{Ай! Хорошо, хорошо. Ты достоин.}<elif:FS>{Ай! Хорошо, хорошо. Ты достойна.}'),
                          ('Навали', '<<set:F>><if:MS>{Свершилось! Гость признан достойным!}<elif:FS>{Свершилось! Гостья признана достойной!}')):
            _, view, _ = build(before + [say('21:10:00', who, text)], plan=plan)
            self.assertEqual(boss(view, 'redvale', 'boss-king')['urgency'], 'done')
            self.assertEqual(view['history'][0]['text'], 'Босс убит: Ржавый король')
        # боевой выкрик с курсивом — не та реплика
        _, view, _ = build(before + [say('21:10:00', 'Яма', '<<set:F>><i>{Атул!}')], plan=plan)
        self.assertEqual(boss(view, 'redvale', 'boss-king')['urgency'], 'due')
        # прозвучали обе реплики — в журнале босс назван один раз
        both = [say('21:10:00', 'Яма', 'Ай! Хорошо, хорошо. Ты достоин.'), say('21:10:20', 'Навали', 'Свершилось! Гость признан достойным!')]
        _, view, _ = build(before + both, plan=plan)
        self.assertEqual([h['text'] for h in view['history']].count('Босс убит: Ржавый король'), 1)

    def test_skipped_boss_with_a_reward_stays_lit(self):
        lines = NO_REWARD + RUN_TAIL
        _, view, _ = build(lines, plan=BOSSES)
        beira = boss(view, 'clearfell', 'boss-beira')
        self.assertEqual((beira['urgency'], beira['place'], beira['locked']), ('overdue', True, False))
        # пропущенное называет карту, на которую возвращаться
        self.assertEqual([(g['id'], g['needName']) for g in view['missed']], [('boss-beira', 'Клирфелл')])
        # награды в логе ещё нет (книгу не прочли) — босса можно отметить рукой
        _, view, _ = build(lines, [('boss-beira', 2)], plan=BOSSES)
        beira = boss(view, 'clearfell', 'boss-beira')
        self.assertEqual((beira['urgency'], beira['locked']), ('done', False))
        self.assertEqual(view['missed'], [])
        self.assertEqual(view['history'][0]['text'], 'Босс: Бейра: +10% холода — готово')

    def test_reward_belongs_to_the_map_where_it_was_taken(self):
        plan = dict(ROUTE, goals=ROUTE['goals'] + [
            {'id': 'bell', 'kind': 'boss', 'group': 'Награды', 'title': 'Колокольщик: +2 очка',
             'reward': 'passive_points', 'need': 'clearfell'},
            {'id': 'hut', 'group': 'Награды', 'title': 'Хижина: +2 очка', 'reward': 'passive_points', 'need': 'cemetery'}])
        # обоих пропустили, с кладбища вернулись в Клирфелл и взяли очки там: это босс Клирфелла
        back = NO_REWARD + RUN_TAIL + CEMETERY + zone('21:50:00', 2, 'G1_2', 'Клирфелл', 5) + points('21:55:00')
        _, view, _ = build(back, plan=plan)
        self.assertEqual(view['step']['id'], 'cemetery')
        self.assertEqual([goal(view, x)['urgency'] for x in ('bell', 'hut')], ['done', 'due'])
        self.assertEqual(view['missed'], [])
        # босса убили раньше его шага, заглянув на его карту: награда всё равно его
        early = dict(ROUTE, goals=ROUTE['goals'] + [
            {'id': 'ahead', 'kind': 'boss', 'group': 'Награды', 'title': 'Босс зарослей: +2 очка',
             'reward': 'passive_points', 'need': 'tangle'}])
        _, view, _ = build(RUN_LINES + zone('20:40:40', 6, 'G1_6', 'Мрачные заросли', 9) + points('20:40:42'), plan=early)
        self.assertEqual((view['step']['id'], goal(view, 'ahead')['urgency']), ('grelwood-1', 'done'))

    def test_optional_boss_without_a_reward_leaves_silently(self):
        full = RUN_LINES + RUN_TAIL
        _, view, _ = build(full, plan=BOSSES)
        druid = boss(view, 'tangle', 'boss-druid')
        self.assertEqual((druid['urgency'], druid['soft'], druid['boss']), ('due', True, True))
        _, view, _ = build(full + CEMETERY, plan=BOSSES)
        self.assertEqual(boss(view, 'tangle', 'boss-druid')['urgency'], 'expired')
        # а босс с наградой (здесь без строки в логе — реликвия) остаётся гореть
        self.assertEqual([(g['id'], g['needName']) for g in view['missed']], [('boss-relic', 'Мрачные заросли')])
        self.assertEqual([g['id'] for g in view['overdue'] if g['place']], ['boss-relic'])

    def test_untouched_waypoint_of_a_passed_map_is_listed_as_skipped(self):
        # Точка перехода — тоже цель карты: ушли, не зайдя в её зону, — она горит в «Пропущено»
        # с названием карты, откуда её берут, и гаснет сама, когда лог покажет вход в эту зону.
        steps = [dict(s, touch=[{'zone': 'G1_3', 'name': 'Грязевая нора'}]) if s['id'] == 'clearfell' else s
                 for s in ROUTE['steps']]
        plan = dict(ROUTE, steps=steps)
        grelwood = zone('20:40:07', 4, 'G1_4', 'Грельвуд')
        on_map = upto(RUN_LINES, grelwood[0])
        _, view, problems = build(on_map, plan=plan)
        self.assertEqual(problems, [])
        # пока карта текущая, точка просто не отмечена
        self.assertEqual((view['step']['id'], view['step']['touch'], view['missed']),
                         ('clearfell', [{'name': 'Грязевая нора', 'done': False}], []))
        _, view, _ = build(RUN_LINES, plan=plan)
        self.assertEqual([(g['title'], g['needName'], g['locked'], g['urgency']) for g in view['missed']],
                         [('Точка: Грязевая нора', 'Клирфелл', True, 'overdue')])
        # в предупреждение «Опаздываю» точка не попадает: её место — рядом с пропущенными боссами
        self.assertEqual([g['id'] for g in view['overdue'] if g['id'].startswith('touch:')], [])
        # заглянули в зону точки перед уходом — пропущенного нет
        _, view, _ = build(on_map + zone('20:39:50', 3, 'G1_3', 'Грязевая нора') + grelwood, plan=plan)
        self.assertEqual((view['step']['id'], view['missed']), ('grelwood-1', []))

    def test_map_quest_is_tied_to_its_map_like_a_boss(self):
        # Реликвия карты: отмечают рукой, а пропущенная горит и называет карту.
        plan = dict(ROUTE, goals=ROUTE['goals'] + [
            {'id': 'relic', 'kind': 'quest', 'group': 'Награды', 'title': 'Реликвия', 'need': 'tangle'}])
        full = RUN_LINES + RUN_TAIL
        _, view, problems = build(RUN_LINES, plan=plan)
        self.assertEqual(problems, [])
        g = goal(view, 'relic')
        self.assertEqual((g['kind'], g['place'], g['urgency'], g['since']),
                         ('задание', True, 'early', 'с шага «Мрачные заросли»'))
        _, view, _ = build(full, plan=plan)
        self.assertEqual((goal(view, 'relic')['urgency'], goal(view, 'relic')['locked']), ('due', False))
        _, view, _ = build(full + CEMETERY, plan=plan)
        self.assertEqual([(g['id'], g['needName']) for g in view['missed']], [('relic', 'Мрачные заросли')])
        _, view, _ = build(full + CEMETERY, [('relic', 2)], plan=plan)
        self.assertEqual((goal(view, 'relic')['urgency'], view['missed']), ('done', []))
        self.assertEqual(view['history'][0]['text'], 'Реликвия — взято')

    def test_a_mechanic_is_a_goal_of_its_map_on_every_step_it_stands(self):
        # Механика (Бездна) — цель карты, как задание: на шаге она среди его целей, отмечают рукой; не отмеченная,
        # когда карта позади, — «пропущено» с названием карты. Одна механика стоит на нескольких шагах.
        plan = dict(ROUTE, goals=ROUTE['goals'] + [
            {'id': 'abyss-clearfell', 'kind': 'mechanic', 'group': 'Механики', 'title': 'Бездна (Abyss)', 'need': 'clearfell'},
            {'id': 'abyss-tangle', 'kind': 'mechanic', 'group': 'Механики', 'title': 'Бездна (Abyss)', 'need': 'tangle'}])
        on_map = upto(RUN_LINES, zone('20:40:07', 4, 'G1_4', 'Грельвуд')[0])
        _, view, problems = build(on_map, plan=plan)
        self.assertEqual(problems, [])
        card = next(c for c in view['cards'] if c['id'] == 'clearfell')
        g = next(x for x in card['goals'] if x['id'] == 'abyss-clearfell')
        self.assertEqual((view['step']['id'], g['kind'], g['place'], g['urgency'], g['locked'], g['boss']),
                         ('clearfell', 'механика', True, 'due', False, False))
        later = goal(view, 'abyss-tangle')
        self.assertEqual((later['urgency'], later['since']), ('early', 'с шага «Мрачные заросли»'))
        # ушли с карты, не отметив, — пропущено; отмеченная — сделана, и журнал говорит «Механика: …»
        _, view, _ = build(RUN_LINES, plan=plan)
        self.assertEqual([(g['id'], g['needName']) for g in view['missed']], [('abyss-clearfell', 'Клирфелл')])
        # в «Опаздываю» её нет: её место — рядом с пропущенными боссами
        self.assertNotIn('abyss-clearfell', [g['id'] for g in view['overdue'] if not g['place']])
        _, view, _ = build(RUN_LINES, [('abyss-clearfell', 2)], plan=plan)
        self.assertEqual((goal(view, 'abyss-clearfell')['urgency'], view['missed']), ('done', []))
        self.assertEqual(view['history'][0]['text'], 'Механика: Бездна (Abyss) — готово')
        # в общем состоянии забега механики — своей группой, по порядку маршрута
        self.assertEqual([g['id'] for c in view['checks'] if c['name'] == 'Механики' for g in c['goals']],
                         ['abyss-clearfell', 'abyss-tangle'])

    def test_a_cache_of_a_zone_is_a_goal_of_its_map(self):
        # Тайник зоны («Опасный клад») — цель карты: на шаге среди его целей, отмечают рукой; пропущенный — с картой
        plan = dict(ROUTE, goals=ROUTE['goals'] + [
            {'id': 'cache-trove', 'kind': 'cache', 'group': 'Тайники', 'title': 'Опасный клад (Embattled Trove)', 'need': 'clearfell'}])
        _, view, problems = build(RUN_LINES, plan=plan)
        self.assertEqual(problems, [])
        g = next(x for c in view['cards'] if c['id'] == 'clearfell' for x in c['goals'] if x['id'] == 'cache-trove')
        self.assertEqual((g['kind'], g['place'], g['urgency']), ('тайник', True, 'overdue'))
        self.assertEqual([(m['id'], m['needName']) for m in view['missed']], [('cache-trove', 'Клирфелл')])
        _, view, _ = build(RUN_LINES, [('cache-trove', 2)], plan=plan)
        self.assertEqual((goal(view, 'cache-trove')['urgency'], view['history'][0]['text']),
                         ('done', 'Опасный клад (Embattled Trove) — взято'))

    def test_a_camp_and_a_task_of_a_zone_are_marked_by_hand(self):
        # Лагерь («Паромщик») и задание зоны («Канальный рычаг») — цели карты: лог их не видит, отмечает игрок;
        # не отмеченные, когда карта позади, горят в «Пропущено», как всё остальное
        plan = dict(ROUTE, goals=ROUTE['goals'] + [
            {'id': 'camp-ferry', 'kind': 'camp', 'group': 'Лагеря', 'title': 'Паромщик (The Ferryman)', 'need': 'clearfell'},
            {'id': 'quest-lever', 'kind': 'quest', 'group': 'Задания', 'title': 'Канальный рычаг (Canal Lever)', 'need': 'clearfell'}])
        _, view, problems = build(RUN_LINES, plan=plan)
        self.assertEqual(problems, [])
        card = next(c for c in view['cards'] if c['id'] == 'clearfell')
        self.assertEqual([(g['id'], g['kind'], g['locked']) for g in card['goals'] if g['id'] in ('camp-ferry', 'quest-lever')],
                         [('camp-ferry', 'лагерь', False), ('quest-lever', 'задание', False)])
        self.assertEqual(sorted(m['id'] for m in view['missed'] if m['id'] in ('camp-ferry', 'quest-lever')), ['camp-ferry', 'quest-lever'])
        _, view, _ = build(RUN_LINES, [('quest-lever', 2)], plan=plan)
        self.assertEqual([m['id'] for m in view['missed'] if m['id'] in ('camp-ferry', 'quest-lever')], ['camp-ferry'])

    def test_only_bosses_with_a_reward_are_in_the_state(self):
        _, view, _ = build(RUN_LINES + RUN_TAIL, plan=BOSSES)
        self.assertEqual([g['id'] for c in view['checks'] if c['name'] == 'Награды' for g in c['goals']],
                         ['boss-beira', 'boss-relic', 'hut'])
        listed = {g['id'] for c in view['checks'] for g in c['goals']}
        self.assertFalse(listed & {'boss-miller', 'boss-king', 'boss-druid'})



class FactTest(unittest.TestCase):
    """Строка под названием цели — то, что знает программа: факты справочника игры и что мешает цели со сроком.
    Автор плана её не пишет."""
    GOALS = [
        {'id': 'relic-a', 'kind': 'quest', 'group': 'Награды', 'title': 'Реликвия А (Relic A)', 'need': 'clearfell', 'random': True},
        {'id': 'relic-b', 'kind': 'quest', 'group': 'Награды', 'title': 'Реликвия Б (Relic B)', 'need': 'grelwood-1', 'random': True,
         'monsters': ['Змеиная соплеменница (Serpent Clan)', 'Шаманка змеелюдов (Serpent Shaman)']},
        {'id': 'medal', 'kind': 'quest', 'group': 'Награды', 'title': 'Медальон (Medallion)', 'need': 'redvale',
         'spot': 'Галерея (The Galleria)', 'handout': 'G1_town',
         'needs': [{'id': 'relic-a', 'title': 'Реликвия А (Relic A)'}, {'id': 'relic-c', 'title': 'Реликвия В (Relic C)'}]},
        {'id': 'points', 'group': 'Награды', 'title': 'Очки', 'need': 'redvale', 'handout': 'G1_5'},
    ]

    def fact(self, gid, marks=(), goals=None):
        _, view, problems = build(RUN_LINES, marks, plan=dict(ROUTE, goals=ROUTE['goals'] + (goals or self.GOALS)))
        self.assertEqual(problems, [])
        return goal(view, gid)['fact']

    def test_facts_of_the_reference(self):
        self.assertEqual(self.fact('relic-a'), 'падает случайно — бить всех')
        # падает не с любых монстров зоны — страница называет, кого бить; по-английски — английскими названиями
        heart = self.fact('relic-b')
        self.assertEqual(heart, 'падает случайно — бить: Змеиная соплеменница (Serpent Clan), Шаманка змеелюдов (Serpent Shaman)')
        import i18n
        self.assertEqual(i18n.to(heart, 'en', i18n.Names('en')), 'drops at random — kill: Serpent Clan, Serpent Shaman')
        # город — словом «в городе», название — как его писал лог; записи, которой в плане нет, не видно взятой
        self.assertEqual(self.fact('medal'), 'где: Галерея (The Galleria) · награду выдают в городе: Лагерь Клирфелл · '
                                             'сначала: Реликвия А (Relic A), Реликвия В (Relic C)')
        self.assertEqual(self.fact('points'), 'награду выдают: G1_5')
        # что нужно раньше — только пока этого нет: реликвия взята — о ней не говорят
        self.assertEqual(self.fact('medal', [('relic-a', 2)]), 'где: Галерея (The Galleria) · награду выдают в городе: Лагерь Клирфелл · '
                                                               'сначала: Реликвия В (Relic C)')

    def test_records_waiting_for_each_other_do_not_loop(self):
        goals = [{'id': 'a', 'kind': 'quest', 'group': 'Награды', 'title': 'А', 'need': 'clearfell', 'needs': [{'id': 'b', 'title': 'Б'}]},
                 {'id': 'b', 'kind': 'quest', 'group': 'Награды', 'title': 'Б', 'need': 'clearfell', 'needs': [{'id': 'a', 'title': 'А'}]}]
        self.assertEqual((self.fact('a', goals=goals), self.fact('b', goals=goals)), ('сначала: Б', 'сначала: А'))

    def test_what_blocks_a_goal_whose_time_has_come(self):
        def fact(need):
            goals = [{'id': 'bow', 'slot': 'weapon', 'title': 'Лук', 'need': need, 'opens': 30}]
            _, view, problems = build(RUN_LINES, plan=dict(ROUTE, goals=goals))
            self.assertEqual(problems, [])
            return goal(view, 'bow')['fact']

        # предмет падает с зоны выше тех, что уже бывают: срок прошёл — цель горит и говорит, с какой зоны ждать
        self.assertEqual(fact('clearfell'), 'с зоны %d' % (30 - core.DROP_ABOVE))
        # срок впереди — цель просто «позже», под названием ничего
        self.assertIsNone(fact('ascension'))

    def test_what_the_game_asks_of_a_late_support_or_skill(self):
        """Гнездо по уровню героя — пока уровня нет; сферу златокузнеца и дух программа проверить не может: они
        названы, пока цель опаздывает. Дух — на уровне камня, который герой может носить сейчас, не ниже
        стартового. Срок впереди — ничего."""
        orb = "Большая сфера златокузнеца (Greater Jeweller's Orb)"

        def facts(hero, start=None):
            skill = {'id': 'skill-x', 'kind': 'skill', 'group': 'Навыки', 'title': 'Умение', 'need': 'clearfell',
                     'spirit': [90, 65, 50, 41]}
            if start:
                skill['gemFrom'] = start
            goals = [skill,
                     {'id': 'sup-hero', 'kind': 'support', 'group': 'Навыки', 'for': 'skill-x', 'title': 'Поддержка 3',
                      'need': 'clearfell', 'socket': {'n': 3, 'hero': hero}},
                     {'id': 'sup-orb', 'kind': 'support', 'group': 'Навыки', 'for': 'skill-x', 'title': 'Поддержка 4',
                      'need': 'clearfell', 'socket': {'n': 4, 'orb': orb}},
                     {'id': 'sup-later', 'kind': 'support', 'group': 'Навыки', 'for': 'skill-x', 'title': 'Поддержка 5',
                      'need': 'ascension', 'socket': {'n': 5, 'hero': 90}}]
            _, view, problems = build(RUN_LINES, plan=dict(ROUTE, goals=ROUTE['goals'] + goals, gemLevels=[0, 3, 6, 10]))
            self.assertEqual(problems, [])
            out = {}

            def walk(x):
                if isinstance(x, dict):
                    if x.get('id') in ('skill-x', 'sup-hero', 'sup-orb', 'sup-later') and 'fact' in x:
                        out.setdefault(x['id'], x['fact'])
                    for v in x.values():
                        walk(v)
                elif isinstance(x, list):
                    for v in x:
                        walk(v)
            walk(view)
            return out

        # герою 3-й уровень: камень он носит до 2-го уровня (65 духа)
        got = facts(36)
        self.assertEqual((got['sup-hero'], got['sup-orb'], got['skill-x']),
                         ('3-е гнездо — с 36 уровня', '4-е гнездо — ' + orb, 'нужно 65 духа'))
        self.assertIsNone(got.get('sup-later'))
        # уровень героя уже есть (3-й) — гнездо открыто, сказать нечего; камень начинается с 3-го уровня — 50 духа
        got = facts(2, start=3)
        self.assertEqual((got['sup-hero'], got['skill-x']), (None, 'нужно 50 духа'))


class StageRespecTest(unittest.TestCase):
    """Перекачка дерева — цель шага, с которого этап действует с другой версией дерева: её не пишет автор, она следует
    из этапов. Отмечает её лог — лишних узлов (взятых, но не из новой версии) не осталось. Шаг позади, а лишнее
    не снято — опаздывает, как любая цель."""
    TAKEN = RUN_LINES + [tree_click('20:41:00', 'spells18', 'Урон чарами'),
                         tree_click('20:41:02', 'intelligence11', 'Характеристика')]

    def respec(self, view, step='redvale'):
        card = next(c for c in view['cards'] if c['id'] == step)
        return next((g for g in card['goals'] if g['id'].startswith('respec:')), None)

    def test_respec_waits_on_the_step_of_its_stage(self):
        _, view, problems = build(self.TAKEN, plan=TREE)
        self.assertEqual(problems, [])
        g = self.respec(view)
        # первая цель шага, с которого этап «После вознесения» действует; раньше этого шага её не ждут
        self.assertEqual(next(c for c in view['cards'] if c['id'] == 'redvale')['goals'][0]['id'], g['id'])
        self.assertEqual((g['title'], g['kind'], g['urgency'], g['auto'], g['locked'], g['fact']),
                         ('Перекачать дерево', 'дерево', 'early', True, True, None))
        # на этом шаге: сколько узлов снять — по логу (общий узел остаётся, лишний один)
        lines = self.TAKEN + RUN_TAIL[:9] + zone('20:49:14', 5, 'G1_5', 'Красная Долина')
        _, view, _ = build(lines, plan=TREE)
        g = self.respec(view)
        self.assertEqual((view['step']['id'], g['urgency'], g['status'], g['fact']), ('redvale', 'due', 0, 'снять 1 узел'))
        self.assertEqual(view['step']['goals'][0]['id'], g['id'])
        # сняли лишнее — сделано, и это видно в журнале; потом герой отошёл от плана — перекачка всё равно была
        lines += [tree_click('20:50:00', 'intelligence11', 'Характеристика', 'unallocated')]
        _, view, _ = build(lines, plan=TREE)
        self.assertEqual((self.respec(view)['urgency'], self.respec(view)['fact']), ('done', None))
        self.assertIn('Дерево перекачано: этап «После вознесения»', [h['text'] for h in view['history']])
        _, view, _ = build(lines + [tree_click('20:51:00', 'other7', 'Чужой узел')], plan=TREE)
        self.assertEqual((self.respec(view)['urgency'], view['tree']['extra']), ('done', 1))

    def test_respec_not_done_is_late_after_its_step(self):
        lines = (self.TAKEN + RUN_TAIL[:9] + zone('20:49:14', 5, 'G1_5', 'Красная Долина')
                 + zone('21:20:14', 4, 'G1_4', 'Грельвуд', 3))
        _, view, _ = build(lines, plan=TREE)
        g = self.respec(view)
        self.assertEqual((view['step']['id'], g['urgency'], g['late'], g['fact']), ('grelwood-2', 'overdue', 1, 'снять 1 узел'))
        self.assertIn(g['id'], [v['id'] for v in view['overdue']])
        self.assertFalse(g['place'])          # не привязана к карте: в «Опаздываю», а не в «Пропущено»
        self.assertNotIn(g['id'], [v['id'] for v in view['missed']])

    def test_a_later_stage_takes_over_the_respec(self):
        """Следующий этап со своей перекачкой начался — прежняя, так и не сделанная, больше не нужна: не горит."""
        stages = TREE['stages'] + [{'id': 'maps', 'from': 'tangle', 'name': 'Карты', 'tree': 'last'}]
        tree = {'phases': TREE['tree']['phases'] + [{'id': 'last', 'name': 'Карты', 'nodes': [{'id': 'minion1', 'name': 'Урон приспешников'}]}]}
        plan = dict(TREE, stages=stages, tree=tree)
        lines = (self.TAKEN + RUN_TAIL[:9] + zone('20:49:14', 5, 'G1_5', 'Красная Долина')
                 + zone('21:20:14', 4, 'G1_4', 'Грельвуд', 3) + zone('21:20:41', 6, 'G1_6', 'Мрачные заросли', 9))
        _, view, _ = build(lines, plan=plan)
        old, new = self.respec(view), self.respec(view, 'tangle')
        self.assertEqual((view['step']['id'], old['urgency'], new['urgency'], new['fact']),
                         ('tangle', 'expired', 'due', 'снять 2 узла'))

    def test_no_respec_when_the_new_version_keeps_every_node(self):
        tree = {'phases': [TREE['tree']['phases'][0], dict(TREE['tree']['phases'][0], id='minions', name='Шире',
                                                            nodes=TREE['tree']['phases'][0]['nodes'] + [{'id': 'minion1', 'name': 'Урон приспешников'}])]}
        _, view, _ = build(self.TAKEN, plan=dict(TREE, tree=tree))
        self.assertIsNone(self.respec(view))
        # и этапа без своей версии дерева — тоже: он действует с деревом прежнего
        stages = [TREE['stages'][0], {'id': 'after', 'from': 'redvale', 'name': 'После'}]
        _, view, _ = build(self.TAKEN, plan=dict(TREE, stages=stages))
        self.assertIsNone(self.respec(view))


class AscensionGoalTest(unittest.TestCase):
    """Восхождение — одна запись справочника (вид ascension), её ставят на шаги, где берут очки Восхождения. Какое оно
    по счёту, говорит порядок маршрута: номер (ascend) и название считает программа. Отмечает его лог: каждая ступень
    испытания даёт два очка Восхождения, и N-е восхождение есть, когда взят первый его узел. Раньше шага его не ждут."""
    ASC = {'kind': 'ascension', 'title': 'Восхождение (Ascendancy)', 'group': 'Восхождение', 'levels': [22, 38, 60, 75],
           'zones': ['G2_13', 'G3_10']}
    PLAN = dict(ROUTE, goals=ROUTE['goals'] + [dict(ASC, id='asc-b', need='ascension'), dict(ASC, id='asc-a', need='ascension')])

    def test_the_log_marks_each_ascension(self):
        _, view, problems = build(RUN_LINES, plan=self.PLAN)
        self.assertEqual(problems, [])
        # на одном шаге — по порядку записи: первое, второе
        one, two = goal(view, 'asc-b'), goal(view, 'asc-a')
        self.assertEqual((one['title'], two['title']), ('Первое восхождение', 'Второе восхождение'))
        self.assertEqual((one['kind'], one['urgency'], one['auto'], one['locked']), ('восхождение', 'early', True, True))
        node = lambda t, name: ascend(t, 'AscendancySorceress3' + name)
        _, view, _ = build(RUN_LINES + [node('20:41:00', 'Small1')], plan=self.PLAN)
        self.assertEqual((goal(view, 'asc-b')['urgency'], goal(view, 'asc-a')['status']), ('done', 0))
        _, view, _ = build(RUN_LINES + [node('20:41:00', 'Small1'), node('20:41:01', 'Small2'), node('21:00:00', 'Notable3')],
                           plan=self.PLAN)
        self.assertEqual([goal(view, g)['urgency'] for g in ('asc-b', 'asc-a')], ['done', 'done'])
        self.assertIn('Восхождение получено: 2-е', [h['text'] for h in view['history']])

    def test_the_number_follows_the_route(self):
        """Номер — по порядку шагов, а не записей: восхождение раньше по маршруту — первое, даже записанное вторым;
        сверх четырёх — так и названо."""
        goals = [dict(self.ASC, id='late', need='ascension'), dict(self.ASC, id='early', need='redvale')]
        plan, problems = core.norm_plan(dict(ROUTE, goals=goals))
        by = {g['id']: (g['ascend'], g['title']) for g in plan['goals']}
        self.assertEqual((problems, by), ([], {'early': (1, 'Первое восхождение'), 'late': (2, 'Второе восхождение')}))
        plan, _ = core.norm_plan(dict(ROUTE, goals=[dict(self.ASC, id='a%d' % k, need='ascension') for k in range(5)]))
        self.assertEqual([(g['ascend'], g['title']) for g in plan['goals']][-1], (5, 'Восхождение сверх четырёх'))


if __name__ == '__main__':
    unittest.main()
