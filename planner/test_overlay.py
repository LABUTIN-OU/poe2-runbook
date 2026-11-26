# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Sergei Labutin
# Additional terms under GPL-3.0 section 7: see NOTICE.md
"""Окна поверх игры (overlay.py): где встают окна и как идёт слежение — на подменах окон Windows и страниц.
Настоящих окон проверки не создают, клавиш и мыши не трогают.

    python -X utf8 -m unittest planner.test_overlay
"""
import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import overlay  # noqa: E402

GAME = (100, 50, 4034, 2040)       # клиентская область окна игры, как у игрока: 4034×2040, масштаб экрана 150%
SCALE = 1.5


class GeometryTest(unittest.TestCase):
    def test_list_stands_at_the_bottom_centre_of_the_game(self):
        """Список шага — внизу по центру окна игры, над полосой опыта; растёт вверх: низ не двигается."""
        x, y, w, h = overlay.list_box(GAME, SCALE, 200)
        self.assertEqual((w, h), (810, 300))
        self.assertEqual(x + w // 2, GAME[0] + GAME[2] // 2)                  # по центру
        self.assertEqual(y + h, GAME[1] + GAME[3] - 39)                       # 26 точек страницы над нижним краем
        taller = overlay.list_box(GAME, SCALE, 400)
        self.assertEqual((taller[1] + taller[3], taller[0]), (y + h, x))      # выше стал — низ и место те же
        # окно игры ниже списка: список не уходит за верх окна
        self.assertEqual(overlay.list_box((0, 0, 1280, 300), 1.0, 400)[1], 8)

    def test_folded_list_stands_under_the_tree_buttons_of_the_game(self):
        """Свёрнутый список (строка шага и имена дел зоны над ней) целиком стоит под кнопками дерева игры «Подтвердить»
        и отмены (они кончаются на 90,4% высоты окна) и над полосой опыта (она с 98,4%). Сколько строк имён при
        этом входит, зависит от окна игры: в окне игрока и в 2560×1440 — две, в 1920×1080 — одна. Одна строка есть
        всегда — и когда ей тесно (1920×1080 при масштабе экрана 125%)."""
        for game, scale, lines in ((GAME, SCALE, 2), ((0, 0, 2560, 1440), 1.0, 2), ((0, 0, 1920, 1080), 1.0, 1)):
            self.assertEqual(overlay.fold_lines(game, scale), lines)
            x, y, w, h = overlay.list_box(game, scale, overlay.FOLD_BASE + overlay.FOLD_LINE * lines)
            self.assertGreaterEqual(y, game[1] + game[3] * overlay.FOLD_TOP)
            self.assertLess(y + h, game[1] + game[3] * 0.984)
        self.assertEqual(overlay.fold_lines((0, 0, 1920, 1080), 1.25), 1)
        self.assertEqual(overlay.fold_lines((0, 0, 7680, 4320), 1.0), overlay.FOLD_MAX)

    def test_answer_stands_at_the_edge_of_the_game_panel_near_the_item(self):
        """Ответ на копию: курсор над панелью игры (инвентарь справа, тайник слева) — у её края, со стороны центра;
        иначе — рядом с курсором. Предмет под курсором ответ не закрывает."""
        gx, gy, gw, gh = GAME
        panel = round(gh * overlay.PANEL)
        w = 720
        # инвентарь: курсор в правой панели — ответ левее её края
        box = overlay.answer_box(GAME, SCALE, 300, (gx + gw - 300, 900))
        self.assertEqual((box[2], box[3]), (w, 450))
        self.assertEqual(box[0] + w, gx + gw - panel - 72)
        self.assertLess(box[0] + w, gx + gw - 300)
        # тайник: курсор в левой панели — ответ правее её края
        box = overlay.answer_box(GAME, SCALE, 300, (gx + 200, 900))
        self.assertEqual(box[0], gx + panel + 72)
        # курсор в середине — справа от него; не поместился бы за правый край окна игры — слева
        mid = (gx + gw // 2, 900)
        self.assertEqual(overlay.answer_box(GAME, SCALE, 300, mid)[0], mid[0] + 72)
        small = (0, 0, 1000, 900)                                             # маленькое окно игры: у края панели места нет
        self.assertEqual(overlay.answer_box(small, 1.0, 300, (700, 400))[0], 700 - 48 - 480)
        self.assertEqual(overlay.answer_box(small, 1.0, 300, (300, 400))[0], 300 + 48)
        # курсора нет — у середины окна игры
        self.assertTrue(overlay.inside(GAME, overlay.answer_box(GAME, SCALE, 300, None)[:2]))

    def test_answer_never_covers_the_list_or_leaves_the_game(self):
        """По высоте ответ — у курсора, но не поверх списка шага и не за краем окна игры; выше места — обрезается снизу."""
        gx, gy, gw, gh = GAME
        list_top = overlay.list_box(GAME, SCALE, 300)[1]
        low = overlay.answer_box(GAME, SCALE, 400, (gx + gw - 300, gy + gh - 100), list_top)
        self.assertEqual(low[1] + low[3], list_top - 15)                      # над списком, с зазором
        high = overlay.answer_box(GAME, SCALE, 400, (gx + gw - 300, gy + 5), list_top)
        self.assertEqual(high[1], gy + 12)
        near = overlay.answer_box(GAME, SCALE, 400, (gx + gw - 300, 900), list_top)
        self.assertEqual(near[1], 900 - 60)                                   # чуть выше курсора
        huge = overlay.answer_box(GAME, SCALE, 3000, (gx + gw - 300, 900), list_top)
        self.assertEqual((huge[1], huge[1] + huge[3]), (gy + 12, list_top - 15))

    def test_tree_stands_at_the_top_centre_of_the_game(self):
        """Окно дерева — сверху по центру окна игры: под ним дерево игры, список и ответ оно не задевает."""
        x, y, w, h = overlay.tree_box(GAME, SCALE, 260)
        self.assertEqual((w, h, y), (1050, 390, GAME[1] + 105))
        self.assertEqual(x + w // 2, GAME[0] + GAME[2] // 2)
        self.assertLess(y + h, overlay.list_box(GAME, SCALE, 400)[1])
        self.assertEqual(overlay.tree_box((0, 0, 1280, 300), 1.0, 600)[3], 300 - 70 - 8)   # ниже окна игры не уходит

    def test_inside(self):
        self.assertTrue(overlay.inside((10, 10, 100, 50), (10, 10)))
        self.assertFalse(overlay.inside((10, 10, 100, 50), (110, 30)))
        self.assertTrue(overlay.inside((10, 10, 100, 50), (112, 30), pad=6))
        self.assertFalse(overlay.inside(None, (1, 1)) or overlay.inside((0, 0, 5, 5), None))

    def test_page_tells_only_sane_sizes(self):
        """Страница говорит высоту содержимого и свой масштаб; мусор не принимается. Кроме box, странице ничего не видно."""
        b = overlay.Bridge()
        self.assertEqual(b._size('list'), (0, None))
        b.box('list', 254, 1.5)
        b.box('answer', 310.4)
        b.box('list', -5, 1.5)
        b.box('list', 'много', 1.5)
        b.box('other', 100, 1.5)
        b.box('answer', 120, 99)
        self.assertEqual((b._size('list'), b._size('answer')), ((254, 1.5), (120, None)))
        # список говорит, сколько строк имён он считает разрешёнными в свёрнутом виде: только 1 или 2
        self.assertIsNone(b._room('list'))
        b.box('list', 100, 1.5, None, 2)
        self.assertEqual(b._room('list'), 2)
        b.box('list', 100, 1.5, None, 1.0)
        self.assertEqual(b._room('list'), 1)
        for junk in (0, 3, True, '2', 1.5, None):
            b.box('list', 100, 1.5, None, junk)
            self.assertIsNone(b._room('list'))
        b.box('list', 254, 1.5)
        # места кнопок: только четвёрки разумных чисел
        b.box('answer', 120, 1.5, [[300, 20, 100, 30], [1, 2, 3], 'x', [5, 6, -7, 8], [True, 1, 2, 3], [10.5, 60, 40, 20]])
        self.assertEqual(b._places('answer'), ((300.0, 20.0, 100.0, 30.0), (10.5, 60.0, 40.0, 20.0)))
        self.assertEqual(b._places('list'), ())
        self.assertEqual([n for n in dir(b) if not n.startswith('_')], ['box'])


class FakeWin:
    """Вместо Windows: что впереди, где окно игры и курсор, зажата ли клавиша, что лежит поверх игры — задаёт проверка;
    что сделано с окнами — в calls."""

    def __init__(self):
        self.fg, self.rects, self.mouse, self.keys, self.dressed_set, self.calls = None, {}, (0, 0), set(), set(), []
        self.front_calls, self.fades = [], []
        self.cover = None           # чужое окно, которое лежит поверх окна игры
        self.folded = set()         # свёрнутые окна

    def foreground(self):
        return self.fg

    def exists(self, hwnd):
        return hwnd in self.rects or hwnd in (11, 12, 13, 98, 99)

    def alive(self, hwnd):
        return self.exists(hwnd) and hwnd not in self.folded

    def client(self, hwnd):
        return self.rects.get(hwnd)

    def under(self, point):
        if self.cover is not None:
            return self.cover
        return next((h for h, r in self.rects.items() if overlay.inside(r, point)), None)

    def scale(self, hwnd):
        return SCALE

    def cursor(self):
        return self.mouse

    def key_down(self, vk):
        return vk in self.keys

    def dressed(self, hwnd):
        return hwnd in self.dressed_set

    def dress(self, hwnd, size):
        self.dressed_set.add(hwnd)
        self.calls.append(('dress', hwnd, size))

    def fix_page(self, window, size, bottom):
        self.calls.append(('fix', window.native.Handle.ToInt32(), size, bottom))

    def fade(self, hwnd, alpha):
        self.fades.append((hwnd, alpha))

    def place(self, hwnd, box):
        self.calls.append(('place', hwnd, box))

    def park(self, hwnd):
        self.calls.append(('park', hwnd))

    def to_front(self, hwnd):
        self.front_calls.append(hwnd)
        self.fg = hwnd
        return True


class FakeGlass:
    def __init__(self, hwnd=99):
        self.hwnd, self.box, self.spots = hwnd, None, None

    def cover(self, box, spots=None):
        self.box, self.spots = box, spots

    def hide(self):
        self.box = self.spots = None


class FakeWindow:
    """Вместо окна pywebview: окно создано и показано; что позвали у страницы — в js."""

    def __init__(self, hwnd):
        self.js = []
        self.room = []          # отдельно — сколько строк имён свёрнутого списка сказано странице (ovRoom)
        self.events = type('E', (), {'shown': threading.Event()})()
        self.events.shown.set()
        handle = type('H', (), {'ToInt32': lambda s: hwnd})()
        self.native = type('N', (), {'Handle': handle})()

    def run_js(self, script):
        (self.room if script.startswith('window.ovRoom') else self.js).append(script)


class App:
    def __init__(self):
        self.overlay = {'can': True, 'on': True}
        self.copy_cursor = None


ARM = 'window.ovArm && ovArm(%d)'


class OverlayTest(unittest.TestCase):
    def make(self, front=True):
        self.win, self.glass, self.app, self.game_front, self.now = FakeWin(), FakeGlass(), App(), [front], [0.0]
        self.taps = FakeGlass(98)
        self.win.rects[7] = GAME
        self.win.fg = 7 if front else 5
        o = overlay.Overlay(self.app, lambda: self.game_front[0], find_game=lambda: 7, win=self.win, glass=self.glass,
                            taps=self.taps, clock=lambda: self.now[0])
        self.lst, self.ans, self.tre = FakeWindow(11), FakeWindow(12), FakeWindow(13)
        o.add('list', self.lst)
        o.add('answer', self.ans)
        o.add('tree', self.tre)
        return o

    def later(self, o, seconds=1.0):
        """Прошло время (проверка «видно ли окно игры» идёт не на каждом проходе) — и ещё один проход."""
        self.now[0] += seconds
        return o.step()

    def places(self, hwnd):
        return [c for c in self.win.calls if c[0] == 'place' and c[1] == hwnd]

    def test_windows_follow_the_game_and_the_page_height(self):
        """Окна получают свои свойства один раз; список встаёт внизу по центру окна игры, когда странице есть что
        показать. Страница внутри окна закрепляется один раз — постоянного размера, за нижний край: высота
        сменилась — окно растёт вверх, низ на месте."""
        o = self.make()
        self.assertEqual(o.step(), 0.03)
        self.assertEqual([c for c in self.win.calls if c[0] == 'dress'],
                         [('dress', 11, (810, 1350)), ('dress', 12, (720, 1650)), ('dress', 13, (1050, 1050))])
        self.assertEqual(self.places(11), [])                                 # страница ещё не сказала высоту
        o.api.box('list', 200, 1.5)
        o.step()
        box = overlay.list_box(GAME, SCALE, 200)
        self.assertEqual(self.win.calls[-2:], [('fix', 11, (810, 1350), True), ('place', 11, box)])
        self.assertEqual((o.panes['list'].box, o.panes['list'].dy), (box, 1050))
        o.step()
        self.assertEqual(len(self.places(11)), 1)                             # ничего не изменилось — окно не трогают
        o.api.box('list', 229, 1.5)                                           # строка пришла: список вырос вверх
        o.step()
        taller = self.places(11)[-1][2]
        self.assertEqual((taller[3], taller[1] + taller[3], o.panes['list'].dy), (344, box[1] + box[3], 1350 - 344))
        self.assertEqual(len([c for c in self.win.calls if c[0] == 'fix']), 1)   # страница закреплена один раз
        # игрок выключил окна кнопкой «поверх игры»
        self.app.overlay['on'] = False
        self.assertEqual(o.step(), 0.25)
        self.assertEqual((self.win.calls[-1], o.panes['list'].box), (('park', 11), None))
        self.app.overlay['on'] = True
        o.step()
        self.assertEqual(self.places(11)[-1], ('place', 11, taller))
        # показывать нечего (плана нет): окно убрано, хотя игра на месте
        o.api.box('list', 0, 1.5)
        o.step()
        self.assertEqual((self.win.calls[-1], o.panes['list'].box), (('park', 11), None))

    def test_list_is_as_clear_as_the_player_chose_and_the_answer_stays_above_it(self):
        """Прозрачность списка без клавиши — настройка игрока (0, 15, 30, 50%; без неё — 30%); с зажатой клавишей список
        плотный. Список раскрылся по клавише и встал поверх всех окон — ответ на копию остаётся над ним."""
        self.assertEqual([overlay.idle_alpha(c) for c in (None, 30, 0, 15, 50, 'x', True, 500)],
                         [178, 178, overlay.ALPHA, 217, 128, 178, 178, 178])
        o = self.make()
        o.api.box('list', 100, 1.5)
        o.step()
        self.assertIn((11, 178), self.win.fades)
        self.app.overlay['clear'] = 50
        o.step()
        self.assertEqual(self.win.fades[-1], (11, 128))
        self.win.keys = {overlay.VK_MENU}                                     # клавиша зажата — список плотный
        o.step()
        self.assertEqual(self.win.fades[-1], (11, overlay.ALPHA))
        self.win.keys = set()
        o.step()
        # ответ на копию показан; список раскрылся (страница сказала новую высоту) — ответ снова ставится поверх
        gx, gy, gw, gh = GAME
        self.app.copy_cursor = (100.0, (gx + gw - 300, 900))
        o.api.box('answer', 300, 1.5)
        o.step()
        ans = o.panes['answer'].box
        self.assertEqual(self.places(12), [('place', 12, ans)])
        o.step()
        self.assertEqual(len(self.places(12)), 1)                             # ничего не менялось — окна не трогают
        o.api.box('list', 420, 1.5)
        o.step()
        self.assertEqual(self.win.calls[-2:], [('place', 11, o.panes['list'].box), ('place', 12, ans)])
        self.assertEqual(o.panes['answer'].box, ans)                          # сам ответ с места не сдвинулся

    def test_page_is_told_how_many_name_lines_the_folded_list_may_take(self):
        """Сколько строк имён входит в свёрнутый список под кнопками дерева игры, странице говорит программа — по высоте
        окна игры. Страница отвечает, что знает; не ответила (ещё грузилась, перезагрузилась) — программа говорит ещё
        раз, но не чаще раза в секунду. Окно игры сменило размер — говорит заново."""
        room = 'window.ovRoom && ovRoom(%d)'
        o = self.make()
        o.api.box('list', 74, 1.5)
        o.step()
        self.assertEqual(self.lst.room, [room % 2])                           # окно игрока: входят две строки
        o.step()
        self.assertEqual(len(self.lst.room), 1)                               # ждём ответа страницы
        self.later(o, 1.5)
        self.assertEqual(self.lst.room, [room % 2, room % 2])                 # не ответила — ещё раз
        o.api.box('list', 100, 1.5, None, 2)                                  # страница знает: две
        self.later(o, 5)
        self.assertEqual(len(self.lst.room), 2)
        self.win.rects[7] = (0, 0, 1920, 1080)                                # окно игры стало маленьким — одна строка
        self.later(o)
        self.assertEqual(self.lst.room[-1], room % 1)
        self.assertEqual((self.ans.room, self.tre.room), ([], []))            # другим окнам это не говорят

    def test_windows_stay_while_the_game_is_seen(self):
        """Окна держатся, пока окно игры видно под ними, — активно оно или нет: игра стоит в окне рядом с программой, и
        список при ней — часть игры. Свернули игру или закрыли её в этом месте другим окном — окна убраны."""
        o = self.make()
        o.api.box('list', 200, 1.5)
        o.step()
        box = o.panes['list'].box
        self.assertIsNotNone(box)
        # игрок ушёл в окно программы рядом: игра не активна, но видна — список на месте
        self.win.fg, self.game_front[0] = 5, False
        self.assertEqual(self.later(o), 0.03)
        self.assertEqual((o.panes['list'].box, len(self.places(11))), (box, 1))
        # поверх игры в этом месте легло чужое окно (у игры на весь экран — любое другое окно) — список убран
        self.win.cover = 5
        o.step()
        self.assertEqual(o.panes['list'].box, box)                            # проверка идёт не на каждом проходе
        self.later(o)
        self.assertEqual((self.win.calls[-1], o.panes['list'].box), (('park', 11), None))
        self.win.cover = None
        self.later(o)
        self.assertEqual((self.places(11)[-1], o.panes['list'].box), (('place', 11, box), box))
        # стекло самой программы над списком игру не «закрывает»
        self.win.cover = 99
        self.later(o)
        self.assertEqual(o.panes['list'].box, box)
        self.win.cover = None
        # игру свернули
        self.win.folded = {7}
        self.assertEqual(o.step(), 0.25)
        self.assertEqual((self.win.calls[-1], o.panes['list'].box), (('park', 11), None))
        self.win.folded = set()
        self.later(o)
        self.assertEqual(o.panes['list'].box, box)

    def test_windows_are_away_while_the_hero_is_out_of_the_game(self):
        """Экран входа, выбор персонажа: окно игры видно, но героя в игре нет (по логу) — окон поверх игры нет. Герой
        вошёл в игру — окна на месте."""
        o = self.make()
        playing = [True]
        o.playing = lambda: playing[0]
        o.api.box('list', 200, 1.5)
        o.api.box('tree', 260, 1.5)
        o.step()
        box = o.panes['list'].box
        self.assertIsNotNone(box)
        playing[0] = False                                                    # вышли на экран выбора персонажа
        self.assertEqual(o.step(), 0.25)
        self.assertEqual((o.panes['list'].box, o.panes['tree'].box, self.glass.box, self.taps.box), (None, None, None, None))
        self.win.keys = {overlay.VK_MENU}                                     # клавиша там ничего не показывает
        o.step()
        self.assertEqual(o.panes['list'].box, None)
        self.win.keys = set()
        playing[0] = True                                                     # вошли героем
        o.step()
        self.assertEqual(o.panes['list'].box, box)

    def test_game_window_is_found_without_being_in_front(self):
        """Программу запустили при запущенной игре, а впереди — другое окно: окно игры находится само, список встаёт."""
        o = self.make(front=False)
        o.api.box('list', 200, 1.5)
        o.step()
        self.assertEqual((o.game, o.panes['list'].box), (7, overlay.list_box(GAME, SCALE, 200)))
        # игру закрыли — окна убраны; запустили снова (другое окно) — список при ней
        del self.win.rects[7]
        o.find_game = lambda: None
        self.assertEqual(self.later(o, 2), 0.25)
        self.assertEqual((o.game, o.panes['list'].box), (None, None))
        self.win.rects[8] = GAME
        o.find_game = lambda: 8
        self.later(o, 2)
        self.assertEqual((o.game, o.panes['list'].box), (8, overlay.list_box(GAME, SCALE, 200)))

    def test_answer_stands_where_the_cursor_was_at_the_copy(self):
        """Ответ встаёт у места, где курсор был в момент копии, и не ездит за курсором; новая копия — новое место."""
        o = self.make()
        o.api.box('list', 200, 1.5)
        o.step()
        gx, gy, gw, gh = GAME
        self.app.copy_cursor = (100.0, (gx + gw - 300, 900))
        o.api.box('answer', 300, 1.5)
        self.win.mouse = (gx + 500, 500)                                      # курсор уже ушёл
        o.step()
        want = overlay.answer_box(GAME, SCALE, 300, (gx + gw - 300, 900), overlay.list_box(GAME, SCALE, 200)[1])
        self.assertEqual((o.panes['answer'].box, o.panes['answer'].dy), (want, 0))
        self.assertEqual(self.win.calls[-2:], [('fix', 12, (720, 1650), False), ('place', 12, want)])   # страница — за верх
        self.win.mouse = (gx + 900, 700)
        o.step()
        self.assertEqual(len(self.places(12)), 1)
        # список вырос до самого ответа (с зажатым Alt он раскрывается) — ответ стоит, где стоял
        self.app.copy_cursor = (150.0, (gx + gw - 300, gy + gh - 100))        # копия внизу: ответ — прямо над списком
        o.step()
        low = o.panes['answer'].box
        self.assertEqual(low[1] + low[3], overlay.list_box(GAME, SCALE, 200)[1] - 15)
        o.api.box('list', 600, 1.5)
        o.step()
        self.assertEqual(o.panes['answer'].box, low)
        o.api.box('list', 200, 1.5)
        o.step()
        self.app.copy_cursor = (200.0, (gx + 200, 900))                       # новая копия — у тайника слева
        o.step()
        self.assertEqual(o.panes['answer'].box[0], gx + round(gh * overlay.PANEL) + 72)
        o.api.box('answer', 0, 1.5)                                           # окно сравнения закрылось
        o.step()
        self.assertEqual((self.win.calls[-1], o.panes['answer'].box), (('park', 12), None))
        # копия без места (буфер-файл в проверках): ответ встаёт у курсора, каким он был при появлении
        self.app.copy_cursor = None
        self.win.mouse = (gx + 2000, 800)
        o.api.box('answer', 300, 1.5)
        o.step()
        self.assertEqual(o.panes['answer'].box[0], gx + 2000 + 72)

    def test_key_shows_the_frame_and_the_cursor_lets_click(self):
        """Клавиша зажата — окна показывают рамку, где бы ни была мышь: видно, что они слушают. Курсор над окном —
        встаёт стекло, страница раскрыта целиком, щелчок и движение уходят ей в её точках. Клавишу отпустили — стекла
        нет, рамки нет."""
        o = self.make()
        o.api.box('list', 200, 1.5)
        o.step()
        box = o.panes['list'].box
        self.win.mouse = (box[0] + 100, box[1] + 30)
        o.step()
        self.assertEqual((self.glass.box, self.lst.js), (None, []))           # курсор над окном, клавиша не зажата
        self.win.mouse = (box[0] - 900, box[1] - 600)                         # мышь у героя, клавиша зажата — рамка
        self.win.keys = {overlay.VK_MENU}
        o.step()
        self.assertEqual((self.glass.box, self.lst.js), (None, [ARM % 1]))
        self.win.mouse = (box[0] + 100, box[1] + 30)                          # курсор пришёл на список — можно нажимать
        o.step()
        self.assertEqual((self.glass.box, self.lst.js), (box, [ARM % 1, ARM % 2]))
        o._click(150, 45)                                                     # точки стекла — экранные, от его угла
        o._move(300, 60)
        o.step()
        # в точках страницы: её верх на 1050 точек экрана выше верха окна (страница прижата к низу)
        self.assertEqual(self.lst.js[2:], ['window.ovClick && ovClick(100,730)', 'window.ovHover && ovHover(200,740)'])
        o.step()
        self.assertEqual(len(self.lst.js), 4)                                 # то же место — второй раз не шлём
        # курсор ушёл с окна, клавиша ещё зажата: стекла нет, рамка осталась
        self.win.mouse = (box[0] - 200, box[1])
        o.step()
        self.assertEqual((self.glass.box, self.lst.js[-1]), (None, ARM % 1))
        n = len(self.lst.js)
        o.step()
        self.assertEqual(len(self.lst.js), n)
        # появился ответ: клавиша зажата — рамка и у него; курсор над ответом — нажимать можно по нему
        self.app.copy_cursor = (1.0, (GAME[0] + 2000, 600))
        o.api.box('answer', 300, 1.5)
        o.step()
        ans = o.panes['answer'].box
        self.assertEqual(self.ans.js, [ARM % 1])
        self.win.mouse = (ans[0] + 30, ans[1] + 30)
        o.step()
        self.assertEqual((self.glass.box, self.ans.js, self.lst.js[-1]), (ans, [ARM % 1, ARM % 2], ARM % 1))
        o._click(30, 30)
        o.step()
        self.assertEqual(self.ans.js[-1], 'window.ovClick && ovClick(20,20)')
        self.win.keys = set()
        o.step()
        self.assertEqual((self.glass.box, self.ans.js[-1], self.lst.js[-1]), (None, ARM % 0, ARM % 0))
        o._click(30, 30)                                                      # запоздавший щелчок без клавиши не уходит
        o.step()
        self.assertEqual(self.ans.js[-1], ARM % 0)
        # окно убрали при зажатой клавише — странице сказано, что рамки больше нет
        self.win.keys = {overlay.VK_MENU}
        o.step()
        self.assertEqual(self.lst.js[-1], ARM % 1)
        self.app.overlay['on'] = False
        o.step()
        self.assertEqual((self.lst.js[-1], o.panes['list'].level), (ARM % 0, 0))

    def test_answer_buttons_take_clicks_without_the_key(self):
        """Кнопки окна ответа («Надеть», ✕, выбор слота) нажимаются и без клавиши: стекло лежит только на них, остальное
        окно мышь пропускает в игру. Места кнопок называет страница; ответа нет — стекла нет."""
        o = self.make()
        o.api.box('list', 200, 1.5)
        self.app.copy_cursor = (1.0, (GAME[0] + 2000, 600))
        o.api.box('answer', 300, 1.5, [[300, 20, 100, 30], [20, 80, 60, 20]])
        o.step()
        ans = o.panes['answer'].box
        self.assertEqual((self.taps.box, self.taps.spots), (ans, [(447, 27, 156, 51), (27, 117, 96, 36)]))
        self.assertEqual((self.glass.box, self.ans.js), (None, []))           # клавиша не зажата — большого стекла нет
        o._tap(460, 40)                                                       # щелчок по кнопке: точки стекла — экранные
        o._tap_move(470, 45)
        o.step()
        self.assertEqual(self.ans.js, ['window.ovClick && ovClick(307,27)', 'window.ovHover && ovHover(313,30)'])
        o._tap_leave()                                                        # курсор ушёл с кнопки — подсветка снята
        o.step()
        self.assertEqual(self.ans.js[-1], 'window.ovHover && ovHover(-1,-1)')
        o.api.box('answer', 300, 1.5, [[300, 20, 100, 30]])                   # кнопок стало меньше (слот выбран)
        o.step()
        self.assertEqual(self.taps.spots, [(447, 27, 156, 51)])
        o.api.box('answer', 300, 1.5)                                         # кнопок нет — стекла нет
        o.step()
        self.assertEqual(self.taps.box, None)
        o.api.box('answer', 300, 1.5, [[300, 20, 100, 30]])
        o.step()
        self.assertEqual(self.taps.box, ans)
        # стекло кнопок игру «не закрывает»: окно ответа остаётся
        self.win.cover = 98
        self.later(o)
        self.assertEqual(o.panes['answer'].box, ans)
        self.win.cover = None
        o.api.box('answer', 0, 1.5)                                           # окно сравнения закрылось
        o._tap(460, 40)
        o.step()
        self.assertEqual((self.taps.box, o.tapped, o.panes['answer'].box), (None, [], None))
        n = len(self.ans.js)
        o.step()
        self.assertEqual(len(self.ans.js), n)                                 # запоздавший щелчок никуда не ушёл

    def test_tree_window_comes_by_the_key_and_never_takes_the_mouse(self):
        """Окно дерева: клавишу его странице говорят и убранному — по ней страница решает показаться и называет высоту
        (без клавиши — ноль: само окно не появляется, их слова из игры 2026-11-26); программа ставит окно по высоте,
        которую назвала страница, и сама ничего не решает. Мышь оно не ловит никогда: под ним дерево игры."""
        o = self.make()
        o.api.box('list', 200, 1.5)
        o.step()
        self.assertEqual((self.tre.js, o.panes['tree'].box), ([], None))
        self.win.keys = {overlay.VK_MENU}
        self.win.mouse = (GAME[0] + 2000, GAME[1] + 200)                      # курсор там, где встанет окно дерева
        o.step()
        self.assertEqual((self.tre.js, o.panes['tree'].box), ([ARM % 1], None))   # страница узнала о клавише
        o.api.box('tree', 260, 1.5)                                           # …и показалась
        o.step()
        box = overlay.tree_box(GAME, SCALE, 260)
        self.assertEqual((o.panes['tree'].box, self.win.calls[-2:]), (box, [('fix', 13, (1050, 1050), False), ('place', 13, box)]))
        self.assertTrue(overlay.inside(box, self.win.mouse))
        self.assertEqual((self.glass.box, o.armed, self.tre.js), (None, None, [ARM % 1]))   # курсор над ним — стекла нет
        self.win.keys = set()
        o.step()
        self.assertEqual((self.tre.js[-1], o.panes['tree'].box), (ARM % 0, box))   # клавишу отпустили: страница решит сама
        o.api.box('tree', 0, 1.5)
        o.step()
        self.assertEqual((self.win.calls[-1], o.panes['tree'].box, len(self.tre.js)), (('park', 13), None, 2))
        # высоту назвала страница — окно стоит по ней: показаться или нет, решает страница, а не программа
        o.api.box('tree', 300, 1.5)
        o.step()
        self.assertEqual(o.panes['tree'].box, overlay.tree_box(GAME, SCALE, 300))
        self.assertEqual([f for f in self.win.fades if f[0] == 13], [(13, overlay.ALPHA)])   # дерево плотное всегда

    def test_list_is_fainter_until_the_key_is_held(self):
        """Список шага стоит поверх игры всё время — без клавиши он прозрачнее; клавиша зажата — плотный, как окно
        ответа. Ответ плотный всегда: его вызывают, чтобы прочитать."""
        o = self.make()
        o.api.box('list', 200, 1.5)
        o.api.box('answer', 300, 1.5)
        fades = lambda: [f for f in self.win.fades if f[0] != 13]      # окно дерева — в своей проверке
        o.step()
        self.assertEqual(sorted(fades()), [(11, overlay.ALPHA_IDLE), (12, overlay.ALPHA)])
        self.assertLess(overlay.ALPHA_IDLE, overlay.ALPHA)
        o.step()
        self.assertEqual(len(fades()), 2)                              # ничего не изменилось — окно не трогают
        self.win.keys = {overlay.VK_MENU}
        o.step()
        self.assertEqual(fades()[2:], [(11, overlay.ALPHA)])
        self.win.keys = set()
        o.step()
        self.assertEqual(fades()[3:], [(11, overlay.ALPHA_IDLE)])
        # свойства окна сброшены и возвращены — плотность задаётся заново
        self.win.dressed_set.discard(11)
        o.step()
        self.assertEqual(fades()[4:], [(11, overlay.ALPHA_IDLE)])

    def test_window_properties_come_back_if_lost(self):
        """WinForms сбросил свойства окна (или окно создано заново) — они возвращаются, страница закрепляется и место
        ставится снова."""
        o = self.make()
        o.api.box('list', 200, 1.5)
        o.step()
        self.assertEqual(len(self.places(11)), 1)
        self.win.dressed_set.discard(11)
        o.step()
        self.assertEqual([c for c in self.win.calls if c[0] == 'dress' and c[1] == 11][1:], [('dress', 11, (810, 1350))])
        self.assertEqual((len(self.places(11)), len([c for c in self.win.calls if c[0] == 'fix'])), (2, 2))
        # окно ещё не создано: шаг не падает
        o.add('answer', type('W', (), {'events': type('E', (), {'shown': threading.Event()})(), 'native': None})())
        o.step()
        self.assertIsNone(o.panes['answer'].hwnd)

    def test_program_and_game_switch(self):
        """«Программа ↔ игра»: впереди игра (или что угодно) — вперёд окно программы; впереди программа — назад в игру."""
        o = self.make()
        o.step()
        self.assertTrue(o.switch(3))
        self.assertEqual((self.win.front_calls, self.win.fg), ([3], 3))
        self.assertTrue(o.switch(3))
        self.assertEqual(self.win.front_calls, [3, 7])                        # игру видели впереди — в неё и возвращаемся
        o.game = None                                                         # игру впереди ещё не видели: её окно ищут
        self.win.fg = 3
        self.assertTrue(o.switch(3))
        self.assertEqual(self.win.front_calls, [3, 7, 7])
        o.find_game = lambda: None                                            # игра не запущена — ничего
        self.win.fg = 3
        self.assertFalse(o.switch(3))


if __name__ == '__main__':
    unittest.main()
