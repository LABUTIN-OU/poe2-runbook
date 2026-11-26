# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Sergei Labutin
# Additional terms under GPL-3.0 section 7: see NOTICE.md
"""Окна поверх игры: список шага и ответ на копию предмета — прямо в игре, без перехода в окно программы.

Что это. Маленькие окна самой программы (страница «Игра» в режимах ?ov=list, ?ov=answer и ?ov=tree), которые стоят
поверх окна игры, пока оно видно:
  * список шага — внизу по центру окна игры: строка шага и над ней имена дел зоны (одна-две строки — сколько входит
    под кнопками дерева игры, fold_lines); раскрытый — пока зажат Alt (всегда или только под курсором: выбор
    игрока) и всегда, если игрок выбрал «раскрыт» (окно «Настройки» страницы), — всё, что осталось на шаге, строками
    по именам;
  * ответ на копию — у края боковой панели игры рядом с курсором: сравнение предмета или путевой камень;
  * дерево — сверху по центру: что брать за свободные очки, с куском карты дерева. Видно, только пока зажата клавиша
    (Alt); несколько секунд после распределения очков под ней видно и взятое: свериться, туда ли поставили. Само не
    появляется, мышь не ловит никогда.

Правила, на которых всё держится.
  * Фокус у игры не забирается никогда. Окна со страницей мышь не принимают вовсе (щелчок проходит сквозь них в игру)
    и не активируются. Нажать по ним можно только с зажатой клавишей (Alt) и курсором над окном: тогда поверх окна
    встаёт своё невидимое «стекло» — оно ловит щелчок и передаёт его странице (ovClick), а активным окном остаётся
    то, что было. Клавиша отпущена или курсор ушёл — стекла нет, мышь снова целиком в игре. Пока клавиша зажата, окна
    показывают рамку — где бы ни была мышь.
  * Окна видны, пока под ними видно окно игры: оно не свёрнуто и в этом месте не закрыто чужим окном (и пока их не
    выключили кнопкой «поверх игры» на странице). Активно ли окно игры — не важно.
  * С экрана программа ничего не читает и в игру отсюда ничего не посылает: где окно игры и где курсор, говорит
    Windows; что показывать — страница берёт у программы, как обычно.
  * Режим игры — окно или окно без рамки на весь экран. В монопольном полноэкранном режиме чужие окна поверх игры
    Windows не показывает — так у всех подобных программ.

Как устроено. Окно со страницей создаёт desktop.py (pywebview, WebView2) — скрытым; здесь оно получает свои свойства
(поверх всех, без активации, сквозное для мыши, без кнопки на панели задач) и место. Прозрачным окно WebView2 в
Windows быть не умеет, поэтому окно стоит ровно по содержимому: страница сообщает его высоту (Bridge.box). А чтобы
строка шага на экране не дёргалась, когда строки приходят и уходят, сама страница внутри окна — постоянного размера
и закреплена за его край (Win.fix_page): список — за нижний, ответ — за верхний. Окно меняет высоту — страница на
экране стоит на месте и под новый размер не перерисовывается, окно лишь открывает её больше или меньше. Проверено на
этом компьютере (2026-11-25): 360 замеров при быстрой смене высоты — ни одного кадра со сдвигом.
Что не подошло: область окна (SetWindowRgn) — вне её Windows рисует тёмную подложку окна (#202020), а не то, что под
окном, поэтому и скруглений у окон нет; «ключевой» цвет (прозрачность WinForms) на эту подложку не действует.
Геометрия (list_box, answer_box) — обычные функции: их проверяют тесты (test_overlay.py), как и шаг слежения — на
подменах окон.
"""
import ctypes
import sys
import threading
import time

LIST_W, LIST_TALL = 540, 900        # список шага: ширина окна и высота страницы внутри него, точки страницы
ANSWER_W, ANSWER_TALL = 480, 1100   # ответ на копию
# дерево: что брать за свободные очки (окно очков дерева со страницы). Шире 640: уже — страница ставит список узлов
# под карту, и окно выходит вдвое выше
TREE_W, TREE_TALL = 700, 700
TREE_TOP = 70           # дерево — на столько ниже верхнего края окна игры
SIZE = {'list': (LIST_W, LIST_TALL), 'answer': (ANSWER_W, ANSWER_TALL), 'tree': (TREE_W, TREE_TALL)}
# Список — на столько выше нижнего края окна игры: вплотную над полосой опыта (она — нижние ~1,5% высоты окна).
# Было 40; ниже — чтобы свёрнутый список целиком вставал под кнопками дерева игры (FOLD_TOP).
LIST_BOTTOM = 26
# Свёрнутый список не поднимается выше этой доли высоты окна игры: над ней по центру — кнопки дерева игры «Подтвердить»
# (Apply Points) и отмены (они на 83–90,4% высоты окна; окно камней умений кончается на ~88%, окно торговца — на ~85,5%; замер
# по кадрам игры 2026-11-25). Раскрытый список их закрывает, свёрнутый — нет.
FOLD_TOP = 0.904
# Высота свёрнутого списка, точки страницы: рамка, поля и строка шага (FOLD_BASE) и каждая строка имён (FOLD_LINE)
FOLD_BASE, FOLD_LINE = 48, 26
FOLD_MAX = 2            # больше строк имён свёрнутому списку не нужно
EDGE = 8                # ближе к краю окна игры окна не встают
GAP = 48                # от края панели игры (или от курсора) до ответа
# Ширина боковой панели игры (инвентарь, тайник) к высоте её окна. Число — из программ оценки предметов (Awakened PoE
# Trade, Exiled Exchange 2: 986 / 1600); на самой игре его ещё не мерили — при ошибке ответ встанет не вплотную к панели.
PANEL = 986 / 1600
ALPHA = 242             # плотность окна (из 255): чуть видно, что под ним
# Список шага стоит поверх игры всё время — пока клавиша не зажата, он прозрачнее (их слова из игры 2026-11-25:
# «можно ли его сделать ещё более прозрачным, а при нажатии alt сделать таким как сейчас»). Окно ответа остаётся
# плотным: его вызывают, чтобы прочитать, и вспоминать ради этого про Alt не должны.
ALPHA_IDLE = 178


def idle_alpha(clear):
    """Плотность списка шага, пока клавиша не зажата. clear — на сколько процентов он прозрачен: настройка игрока
    (0, 15, 30, 50; окно «Настройки»), без неё — 30 (ALPHA_IDLE). Плотнее, чем с зажатой клавишей, список не бывает."""
    if isinstance(clear, bool) or not isinstance(clear, (int, float)) or not 0 <= clear <= 90:
        return ALPHA_IDLE
    return min(ALPHA, round(255 * (100 - clear) / 100))
TAP_PAD = 3             # запас вокруг кнопки ответа, точки экрана: попасть легче
VK_MENU = 0x12          # Alt: с ним по окнам можно нажимать
MIN_GAME = (640, 400)   # окно игры меньше — поверх него ничего не ставим
PAD = 6                 # запас вокруг окна, в котором зажатая клавиша ещё «над окном»
COVER_EVERY = 0.25      # как часто проверять, не закрыто ли окно игры под окном поверх неё, секунды


def list_box(game, scale, height):
    """Место списка шага: (x, y, ширина, высота) в точках экрана. game — клиентская область окна игры
    (x, y, ширина, высота), scale — сколько точек экрана в точке страницы (1.5 при 150%), height — высота содержимого,
    точки страницы."""
    gx, gy, gw, gh = game
    w, h = round(LIST_W * scale), round(height * scale)
    x = gx + (gw - w) // 2
    y = gy + gh - round(LIST_BOTTOM * scale) - h
    return (x, max(gy + round(EDGE * scale), y), w, h)


def fold_lines(game, scale):
    """Сколько строк имён входит в свёрнутый список так, чтобы он целиком стоял под кнопками дерева игры (FOLD_TOP):
    одна или две — по высоте окна игры и масштабу страницы. Одна строка есть всегда, даже когда и ей тесно (маленькое
    окно игры при крупном масштабе экрана)."""
    room = game[3] * (1 - FOLD_TOP) / scale - LIST_BOTTOM
    return max(1, min(FOLD_MAX, int((room - FOLD_BASE) // FOLD_LINE)))


def answer_box(game, scale, height, cursor, list_top=None):
    """Место ответа на копию. Курсор над боковой панелью игры — ответ встаёт у её края со стороны центра экрана; иначе —
    рядом с курсором (справа, а не поместился — слева). По высоте — у курсора, но не поверх списка шага (list_top — его
    верх) и не за краем окна игры; не помещается по высоте — нижняя часть обрезается."""
    gx, gy, gw, gh = game
    w, h = round(ANSWER_W * scale), round(height * scale)
    gap, edge, panel = round(GAP * scale), round(EDGE * scale), round(gh * PANEL)
    cx, cy = cursor if cursor else (gx + gw // 2, gy + gh // 2)
    if cx >= gx + gw - panel and gw - panel - gap - w >= edge:
        x = gx + gw - panel - gap - w                 # курсор над правой панелью (инвентарь)
    elif cx <= gx + panel and panel + gap + w <= gw - edge:
        x = gx + panel + gap                          # над левой (тайник, торговец)
    elif cx + gap + w <= gx + gw - edge:
        x = cx + gap
    else:
        x = cx - gap - w
    x = max(gx + edge, min(x, gx + gw - edge - w))
    top = gy + edge
    bottom = (list_top if list_top is not None else gy + gh) - round(10 * scale)
    h = max(1, min(h, bottom - top))
    y = max(top, min(cy - round(40 * scale), bottom - h))
    return (x, y, w, h)


def tree_box(game, scale, height):
    """Место окна дерева: сверху по центру окна игры; ниже нижнего края окна игры не уходит."""
    gx, gy, gw, gh = game
    w, top = round(TREE_W * scale), round(TREE_TOP * scale)
    h = max(1, min(round(height * scale), gh - top - round(EDGE * scale)))
    return (gx + (gw - w) // 2, gy + top, w, h)


def inside(box, point, pad=0):
    """Точка экрана point внутри прямоугольника box (x, y, ширина, высота) с запасом pad."""
    if not box or not point:
        return False
    x, y, w, h = box
    return x - pad <= point[0] < x + w + pad and y - pad <= point[1] < y + h + pad


class Bridge:
    """То, что страница зовёт у программы (window.pywebview.api) — одно: box. pywebview отдаёт странице все методы
    объекта без подчёркивания в имени, поэтому здесь нет ничего, кроме него."""

    def __init__(self):
        self._boxes, self._spots, self._rooms = {}, {}, {}

    def box(self, part, height, ratio=None, spots=None, room=None):
        """Страница окна part говорит высоту своего содержимого (0 — показывать нечего), сколько точек экрана в её
        точке (devicePixelRatio) и где на ней кнопки (spots: [[x, y, ширина, высота], …] в точках страницы) — по ним
        нажимают и без клавиши. Список говорит ещё, сколько строк имён он считает разрешёнными в свёрнутом виде
        (room): программа сверяет со своим счётом."""
        if part in SIZE and isinstance(height, (int, float)) and 0 <= height < 10000:
            ok = isinstance(ratio, (int, float)) and 0.5 <= ratio <= 5
            self._boxes[part] = (int(height), float(ratio) if ok else None)
            self._spots[part] = self._rects(spots)
            ok = isinstance(room, (int, float)) and not isinstance(room, bool) and room in range(1, FOLD_MAX + 1)
            self._rooms[part] = int(room) if ok else None

    @staticmethod
    def _rects(spots):
        out = []
        for r in (spots if isinstance(spots, (list, tuple)) else ())[:24]:
            if (isinstance(r, (list, tuple)) and len(r) == 4
                    and all(isinstance(n, (int, float)) and not isinstance(n, bool) and 0 <= n < 10000 for n in r)):
                out.append(tuple(float(n) for n in r))
        return tuple(out)

    def _size(self, part):
        return self._boxes.get(part, (0, None))

    def _places(self, part):
        return self._spots.get(part, ())

    def _room(self, part):
        return self._rooms.get(part)


# --- Windows -------------------------------------------------------------------------------------------------------

GWL_EXSTYLE = -20
WS_EX_TOPMOST, WS_EX_TRANSPARENT, WS_EX_TOOLWINDOW, WS_EX_LAYERED, WS_EX_NOACTIVATE = 0x8, 0x20, 0x80, 0x80000, 0x8000000
WS_EX_APPWINDOW = 0x40000       # «окно — на панель задач»: WinForms ставит его каждому окну; окну поверх игры оно не нужно
DRESS = WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_LAYERED | WS_EX_NOACTIVATE
SWP_NOSIZE, SWP_NOMOVE, SWP_NOZORDER, SWP_NOACTIVATE, SWP_SHOWWINDOW = 0x1, 0x2, 0x4, 0x10, 0x40
HWND_TOPMOST = -1
PARK = (-32000, -32000)     # «убранное» окно стоит за краем экрана: скрытое по-настоящему перестаёт считать страницу


class Win:
    """Системные вызовы Windows, которые нужны окнам поверх игры."""

    def __init__(self):
        if sys.platform != 'win32':
            raise OSError('windows only')
        from ctypes import wintypes as w
        self.w = w
        u = self.u = ctypes.WinDLL('user32', use_last_error=True)
        k = self.k = ctypes.WinDLL('kernel32', use_last_error=True)
        u.GetForegroundWindow.restype = w.HWND
        u.WindowFromPoint.argtypes, u.WindowFromPoint.restype = [w.POINT], w.HWND
        u.GetAncestor.argtypes, u.GetAncestor.restype = [w.HWND, w.UINT], w.HWND
        u.IsWindow.argtypes, u.IsWindow.restype = [w.HWND], w.BOOL
        u.IsIconic.argtypes, u.IsIconic.restype = [w.HWND], w.BOOL
        u.IsWindowVisible.argtypes, u.IsWindowVisible.restype = [w.HWND], w.BOOL
        u.GetClientRect.argtypes = [w.HWND, ctypes.POINTER(w.RECT)]
        u.ClientToScreen.argtypes = [w.HWND, ctypes.POINTER(w.POINT)]
        u.GetCursorPos.argtypes = [ctypes.POINTER(w.POINT)]
        u.GetAsyncKeyState.argtypes, u.GetAsyncKeyState.restype = [ctypes.c_int], ctypes.c_short
        u.SetWindowPos.argtypes = [w.HWND, w.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, w.UINT]
        u.ShowWindow.argtypes = [w.HWND, ctypes.c_int]
        u.SetForegroundWindow.argtypes, u.SetForegroundWindow.restype = [w.HWND], w.BOOL
        u.BringWindowToTop.argtypes = [w.HWND]
        u.GetWindowThreadProcessId.argtypes = [w.HWND, ctypes.POINTER(w.DWORD)]
        u.GetWindowThreadProcessId.restype = w.DWORD
        u.AttachThreadInput.argtypes = [w.DWORD, w.DWORD, w.BOOL]
        u.SetLayeredWindowAttributes.argtypes = [w.HWND, w.DWORD, ctypes.c_ubyte, w.DWORD]
        u.MonitorFromWindow.argtypes, u.MonitorFromWindow.restype = [w.HWND, w.DWORD], w.HANDLE
        u.GetDpiForWindow.argtypes, u.GetDpiForWindow.restype = [w.HWND], w.UINT
        get, put = getattr(u, 'GetWindowLongPtrW', u.GetWindowLongW), getattr(u, 'SetWindowLongPtrW', u.SetWindowLongW)
        get.argtypes, get.restype = [w.HWND, ctypes.c_int], ctypes.c_ssize_t
        put.argtypes, put.restype = [w.HWND, ctypes.c_int, ctypes.c_ssize_t], ctypes.c_ssize_t
        self._get, self._put = get, put
        k.GetCurrentThreadId.restype = w.DWORD
        try:
            s = self.shcore = ctypes.WinDLL('shcore', use_last_error=True)
            s.GetDpiForMonitor.argtypes = [w.HANDLE, ctypes.c_int, ctypes.POINTER(w.UINT), ctypes.POINTER(w.UINT)]
        except OSError:
            self.shcore = None

    def foreground(self):
        return self.u.GetForegroundWindow()

    def exists(self, hwnd):
        return bool(hwnd) and bool(self.u.IsWindow(hwnd))

    def alive(self, hwnd):
        """Окно есть и не свёрнуто."""
        return self.exists(hwnd) and not self.u.IsIconic(hwnd)

    def client(self, hwnd):
        """Клиентская область окна на экране: (x, y, ширина, высота); None — окна нет."""
        r, p = self.w.RECT(), self.w.POINT(0, 0)
        if not self.u.GetClientRect(hwnd, ctypes.byref(r)) or not self.u.ClientToScreen(hwnd, ctypes.byref(p)):
            return None
        return (p.x, p.y, r.right - r.left, r.bottom - r.top)

    def scale(self, hwnd):
        """Масштаб монитора, на котором стоит окно (1.5 при 150%). Нужен, пока страница не сказала свой."""
        dpi = 0
        if self.shcore is not None:
            x, y = self.w.UINT(0), self.w.UINT(0)
            mon = self.u.MonitorFromWindow(hwnd, 2)                    # MONITOR_DEFAULTTONEAREST
            if mon and self.shcore.GetDpiForMonitor(mon, 0, ctypes.byref(x), ctypes.byref(y)) == 0:
                dpi = x.value
        return (dpi or self.u.GetDpiForWindow(hwnd) or 96) / 96

    def under(self, point):
        """Окно верхнего уровня, которое получило бы щелчок в этой точке экрана. Сквозные для мыши окна (наши окна со
        страницей, чужие прозрачные окна поверх игры) Windows при этом пропускает — как и сам щелчок."""
        hwnd = self.u.WindowFromPoint(self.w.POINT(int(point[0]), int(point[1])))
        return self.u.GetAncestor(hwnd, 2) if hwnd else None           # GA_ROOT

    def cursor(self):
        p = self.w.POINT()
        return (p.x, p.y) if self.u.GetCursorPos(ctypes.byref(p)) else None

    def key_down(self, vk):
        return bool(self.u.GetAsyncKeyState(vk) & 0x8000)

    def dressed(self, hwnd):
        """Свойства окна со страницей на месте и окно показано (WinForms при смене своих свойств их сбрасывает)."""
        ex = self._get(hwnd, GWL_EXSTYLE)
        return ex & DRESS == DRESS and not ex & WS_EX_APPWINDOW and bool(self.u.IsWindowVisible(hwnd))

    def dress(self, hwnd, size):
        """Свойства окна со страницей: поверх всех, не активируется, сквозное для мыши, без кнопки на панели задач.
        Окно получает размер страницы и встаёт за край экрана — показанным, но без активации. Стиль меняется у
        скрытого окна: так панель задач не оставляет его кнопку."""
        self.u.ShowWindow(hwnd, 0)
        self._put(hwnd, GWL_EXSTYLE, (self._get(hwnd, GWL_EXSTYLE) | DRESS | WS_EX_TOPMOST) & ~WS_EX_APPWINDOW)
        self.u.SetLayeredWindowAttributes(hwnd, 0, ALPHA, 2)           # LWA_ALPHA
        self.u.SetWindowPos(hwnd, HWND_TOPMOST, PARK[0], PARK[1], size[0], size[1], SWP_NOACTIVATE)
        self.u.ShowWindow(hwnd, 4)                                      # SW_SHOWNOACTIVATE

    def fix_page(self, window, size, bottom):
        """Страница внутри окна pywebview — постоянного размера size (точки экрана) и закреплена за нижний край окна
        (bottom) или за верхний. Тогда окно меняет высоту, а страница на экране не двигается и под новый размер не
        перерисовывается. Свойства элемента WinForms меняются в потоке окна."""
        from System import Func, Type                      # pythonnet: его уже загрузил pywebview
        from System.Drawing import Point, Size
        import System.Windows.Forms as WinForms
        form = window.native
        page = form.browser.webview                        # элемент WebView2 внутри окна

        def fix():
            page.Dock = getattr(WinForms.DockStyle, 'None')
            page.Anchor = (WinForms.AnchorStyles.Bottom if bottom else WinForms.AnchorStyles.Top) | WinForms.AnchorStyles.Left
            page.Size = Size(size[0], size[1])
            page.Location = Point(0, form.ClientSize.Height - size[1] if bottom else 0)
        form.Invoke(Func[Type](fix))

    def fade(self, hwnd, alpha):
        """Плотность окна со страницей: 255 — непрозрачное."""
        self.u.SetLayeredWindowAttributes(hwnd, 0, alpha, 2)           # LWA_ALPHA

    def place(self, hwnd, box):
        """Поставить окно в box (x, y, ширина, высота) — поверх всех, без активации."""
        self.u.SetWindowPos(hwnd, HWND_TOPMOST, box[0], box[1], box[2], box[3], SWP_NOACTIVATE | SWP_SHOWWINDOW)

    def park(self, hwnd):
        self.u.SetWindowPos(hwnd, None, PARK[0], PARK[1], 0, 0, SWP_NOSIZE | SWP_NOACTIVATE | SWP_NOZORDER)

    def to_front(self, hwnd):
        """Окно — вперёд (и из свёрнутого). Зовётся по своей клавише игрока: Windows в ответ на неё это разрешает; не
        разрешила — тот же вызов с подключением к очереди ввода активного окна."""
        u = self.u
        if not self.exists(hwnd):
            return False
        if u.IsIconic(hwnd):
            u.ShowWindow(hwnd, 9)                                       # SW_RESTORE
        if u.SetForegroundWindow(hwnd) and u.GetForegroundWindow() == hwnd:
            return True
        fg = u.GetForegroundWindow()
        mine, other = self.k.GetCurrentThreadId(), u.GetWindowThreadProcessId(fg, None) if fg else 0
        if other and other != mine and u.AttachThreadInput(mine, other, True):
            try:
                u.BringWindowToTop(hwnd)
                u.SetForegroundWindow(hwnd)
            finally:
                u.AttachThreadInput(mine, other, False)
        return u.GetForegroundWindow() == hwnd


class Glass:
    """Невидимое окно программы поверх окна со страницей: ловит щелчок и движение мыши. Само не активируется
    (WM_MOUSEACTIVATE -> «не активировать») — активным остаётся то окно, что было. Живёт в своём потоке со своей
    очередью сообщений; on_click(x, y) и on_move(x, y) зовутся в этом потоке — точки внутри стекла, экранные;
    on_leave() — курсор ушёл со стекла.

    Стёкол два. Одно закрывает окно целиком, пока зажата клавиша и курсор над окном. Другое лежит только на кнопках
    окна ответа (cover с местами spots): по ним нажимают и без клавиши, а всё остальное окно мышь пропускает в игру."""

    COUNT = [0]

    def __init__(self, on_click, on_move, on_leave=None):
        from ctypes import wintypes as w
        Glass.COUNT[0] += 1
        self.name = 'PoE2RunbookGlass%d' % Glass.COUNT[0]      # у класса окна одна функция окна — у каждого стекла свой
        self.w, self.on_click, self.on_move, self.on_leave = w, on_click, on_move, on_leave
        self.hwnd, self.shown, self._tracked = None, None, False
        self.u = ctypes.WinDLL('user32', use_last_error=True)
        self.k = ctypes.WinDLL('kernel32', use_last_error=True)
        g = self.g = ctypes.WinDLL('gdi32', use_last_error=True)
        g.CreateRectRgn.argtypes, g.CreateRectRgn.restype = [ctypes.c_int] * 4, w.HRGN
        g.CombineRgn.argtypes = [w.HRGN, w.HRGN, w.HRGN, ctypes.c_int]
        g.DeleteObject.argtypes = [w.HANDLE]
        self.u.SetWindowRgn.argtypes = [w.HWND, w.HRGN, w.BOOL]
        self._ready = threading.Event()
        threading.Thread(target=self._run, daemon=True).start()
        self._ready.wait(5)

    def _run(self):
        w, u, k = self.w, self.u, self.k
        lresult = ctypes.c_ssize_t
        proc_type = ctypes.WINFUNCTYPE(lresult, w.HWND, w.UINT, w.WPARAM, w.LPARAM)

        class WNDCLASS(ctypes.Structure):
            _fields_ = [('style', w.UINT), ('lpfnWndProc', proc_type), ('cbClsExtra', ctypes.c_int),
                        ('cbWndExtra', ctypes.c_int), ('hInstance', w.HINSTANCE), ('hIcon', w.HANDLE),
                        ('hCursor', w.HANDLE), ('hbrBackground', w.HANDLE), ('lpszMenuName', w.LPCWSTR),
                        ('lpszClassName', w.LPCWSTR)]

        class TRACKMOUSEEVENT(ctypes.Structure):
            _fields_ = [('cbSize', w.DWORD), ('dwFlags', w.DWORD), ('hwndTrack', w.HWND), ('dwHoverTime', w.DWORD)]

        u.DefWindowProcW.argtypes, u.DefWindowProcW.restype = [w.HWND, w.UINT, w.WPARAM, w.LPARAM], lresult
        u.RegisterClassW.argtypes, u.RegisterClassW.restype = [ctypes.POINTER(WNDCLASS)], w.ATOM
        u.CreateWindowExW.argtypes = [w.DWORD, w.LPCWSTR, w.LPCWSTR, w.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                      ctypes.c_int, w.HWND, w.HANDLE, w.HINSTANCE, w.LPVOID]
        u.CreateWindowExW.restype = w.HWND
        u.GetMessageW.argtypes = [ctypes.POINTER(w.MSG), w.HWND, w.UINT, w.UINT]
        u.TranslateMessage.argtypes = u.DispatchMessageW.argtypes = [ctypes.POINTER(w.MSG)]
        u.LoadCursorW.argtypes, u.LoadCursorW.restype = [w.HINSTANCE, w.LPCWSTR], w.HANDLE
        u.SetLayeredWindowAttributes.argtypes = [w.HWND, w.DWORD, ctypes.c_ubyte, w.DWORD]
        u.SetWindowPos.argtypes = [w.HWND, w.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, w.UINT]
        u.ShowWindow.argtypes = [w.HWND, ctypes.c_int]
        u.TrackMouseEvent.argtypes = [ctypes.POINTER(TRACKMOUSEEVENT)]
        k.GetModuleHandleW.argtypes, k.GetModuleHandleW.restype = [w.LPCWSTR], w.HMODULE

        def xy(lp):
            return ctypes.c_short(lp & 0xffff).value, ctypes.c_short((lp >> 16) & 0xffff).value

        def proc(hwnd, msg, wp, lp):
            try:
                if msg == 0x0021:                       # WM_MOUSEACTIVATE
                    return 3                            # MA_NOACTIVATE: щелчок окно не активирует
                if msg == 0x0201:                       # WM_LBUTTONDOWN
                    self.on_click(*xy(lp))
                    return 0
                if msg == 0x0200:                       # WM_MOUSEMOVE
                    if not self._tracked:               # попросить Windows сказать, когда курсор уйдёт со стекла
                        self._tracked = True
                        u.TrackMouseEvent(ctypes.byref(TRACKMOUSEEVENT(ctypes.sizeof(TRACKMOUSEEVENT), 2, hwnd, 0)))
                    self.on_move(*xy(lp))
                    return 0
                if msg == 0x02A3:                       # WM_MOUSELEAVE
                    self._tracked = False
                    if self.on_leave is not None:
                        self.on_leave()
                    return 0
            except Exception as e:                      # ошибка обработчика не должна ронять очередь сообщений
                print('overlay glass: %r' % (e,), flush=True)
            return u.DefWindowProcW(hwnd, msg, wp, lp)

        self._proc = proc_type(proc)                    # держим ссылку: иначе функцию соберёт сборщик мусора
        inst = k.GetModuleHandleW(None)
        hand = u.LoadCursorW(None, ctypes.cast(32649, w.LPCWSTR))      # курсор-рука: видно, что сейчас нажмётся
        cls = WNDCLASS(0, self._proc, 0, 0, inst, None, hand, None, None, self.name)
        u.RegisterClassW(ctypes.byref(cls))
        self.hwnd = u.CreateWindowExW(WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE | WS_EX_TOPMOST, self.name, '',
                                      0x80000000, 0, 0, 10, 10, None, None, inst, None)       # WS_POPUP
        u.SetLayeredWindowAttributes(self.hwnd, 0, 1, 2)   # почти невидимо; совсем прозрачное окно мышь не ловит
        self._ready.set()
        msg = w.MSG()
        while u.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            u.TranslateMessage(ctypes.byref(msg))
            u.DispatchMessageW(ctypes.byref(msg))

    def cover(self, box, spots=None):
        """Встать поверх прямоугольника box (без активации). spots — места внутри него (x, y, ширина, высота): мышь
        ловится только в них, остальное стекло для неё не существует; None — ловится во всём прямоугольнике."""
        key = (box, tuple(spots) if spots is not None else None)
        if not self.hwnd or key == self.shown:
            return
        self.shown = key
        rgn = None
        if spots is not None:
            rgn = self.g.CreateRectRgn(0, 0, 0, 0)
            for x, y, w, h in spots:
                part = self.g.CreateRectRgn(x, y, x + w, y + h)
                self.g.CombineRgn(rgn, rgn, part, 2)                    # RGN_OR
                self.g.DeleteObject(part)
        if not self.u.SetWindowRgn(self.hwnd, rgn, False) and rgn:
            self.g.DeleteObject(rgn)                                    # область не взята — она осталась нашей
        self.u.SetWindowPos(self.hwnd, HWND_TOPMOST, box[0], box[1], box[2], box[3], SWP_NOACTIVATE | SWP_SHOWWINDOW)

    def hide(self):
        if self.hwnd and self.shown is not None:
            self.shown = None
            self.u.ShowWindow(self.hwnd, 0)


class Pane:
    """Одно окно со страницей: его окно pywebview и место на экране."""

    def __init__(self, part, window):
        self.part, self.window = part, window
        self.hwnd = None
        self.box = None         # где окно стоит на экране; None — убрано за край экрана
        self.fixed = None       # размер страницы внутри окна, когда он закреплён (точки экрана)
        self.dy = 0             # на сколько верх страницы выше верха окна (у списка: страница прижата к низу)
        self.scale = 1.0        # сколько точек экрана в точке страницы
        self.level = 0          # что знает страница о клавише: 0 — не зажата, 1 — зажата, 2 — зажата и курсор над окном
                                # (окну дерева клавишу говорят и убранному: оно само решает, показаться ли)
        self.alpha = None       # плотность, которая задана окну сейчас
        self.room = None        # сколько строк имён свёрнутого списка странице сказано в последний раз, и когда
        self.room_at = 0.0
        self.seen = None        # (место, когда проверяли, видно ли там окно игры)


class Overlay:
    """Окна поверх игры: следит за окном игры, ставит и убирает окна, включает нажатия по зажатой клавише.

    Окна стоят, пока окно игры ВИДНО под ними: оно не свёрнуто и в этом месте не закрыто чужим окном. Активно ли оно —
    не важно (их слова после первого запуска 2026-11-25: «плашка пропадает когда игровое окно не в фокусе, это
    специально так сделано или это просто баг?»): игра стоит в окне рядом с программой, и список при ней — часть игры.
    Игрок ушёл в окно, которое игру закрывает (так выходит у игры на весь экран), — окна убираются.

    И ещё окна убраны, пока герой вне игры — экран входа, выбор персонажа (playing: тот же признак из лога игры, по
    которому программа останавливает время и пишет «вне игры»): там показывать нечего, а список вставал поверх кнопки
    «Войти» (их снимок 2026-11-25: «окно появилось, когда я вне игры… можем ли мы его использовать чтобы скрывать»).

    Клавиша (Alt): зажата — страницы всех окон показывают рамку, где бы ни была мышь («alt срабатывает только когда
    мышка находится над нашей плашкой» — без отклика казалось, что клавиша не работает); курсор над окном — встаёт
    стекло, окно раскрыто целиком, по нему можно нажимать. Раскрывается список только под курсором: иначе он рос бы
    поверх ответа каждый раз, когда игрок держит Alt, читая тиры предмета.

    Кнопки окна ответа («Надеть», ✕, выбор слота) нажимаются и без клавиши: второе стекло (taps) лежит только на них,
    остальное окно мышь пропускает в игру. Их слова из игры 2026-11-25: «хочется нажать без alt чтобы надеть или
    закрыть… alt очень удобно для нижней панели, но для попапов хочется принять решение и нажать без того чтобы
    вспоминать про alt… особенно в кейсе где выбор слота (оружие и кольца), которые с клавиатуры не выбрать». Ответ
    вызывают сами (F2), поэтому его кнопки — как кнопки игры: видна — нажимается.

    app — server.App: включены ли окна (app.overlay) и где был курсор при копии (app.copy_cursor); front() — впереди
    ли окно игры (как у буфера обмена и клавиш: clip.WinClipboard.game_in_front) — так узнаётся само окно игры;
    find_game() — окно запущенной игры, пока его впереди ещё не видели; playing() — герой сейчас в игре (по логу;
    не задано — считается, что в игре). Окна pywebview добавляет add(); страницы
    говорят свою высоту в api (Bridge — его отдают окнам при создании). Создавать после запуска окон pywebview: до
    него программа ещё не объявила Windows, что сама учитывает масштаб экрана, и стекло встало бы не туда.
    win, glass, taps, clock — подмены для проверок."""

    def __init__(self, app, front, find_game=None, api=None, win=None, glass=None, taps=None, key=VK_MENU,
                 clock=time.monotonic, playing=None):
        self.app, self.front, self.find_game, self.key, self.clock = app, front, find_game, key, clock
        self.playing = playing
        self.win = win or Win()
        self.api = api or Bridge()
        self.panes = {}
        self.game = None            # окно игры: то, что видели впереди последним (или нашли запущенным)
        self.sought = None          # когда последний раз искали запущенную игру
        self.armed = None           # окно под курсором при зажатой клавише: по нему сейчас можно нажимать
        self.clicks, self.hover, self._hover_sent = [], None, None
        self.cursor_at = None       # копия, для которой уже выбрано место ответа
        self.anchor = None          # курсор в момент копии: ответ стоит у него
        self.floor = None           # сколько места внизу окна игры занимал тогда список: ответ встал над ним
        self.glass = glass or Glass(self._click, self._move)
        # стекло на кнопках ответа: нажатия без клавиши
        self.tapped, self.tap_hover, self._tap_sent, self.tap_left = [], None, None, False
        self.taps = taps or Glass(self._tap, self._tap_move, self._tap_leave)
        self.stop = False

    def add(self, part, window):
        self.panes[part] = Pane(part, window)

    def _click(self, x, y):
        self.clicks.append((x, y))

    def _move(self, x, y):
        self.hover = (x, y)

    def _tap(self, x, y):
        self.tapped.append((x, y))

    def _tap_move(self, x, y):
        self.tap_hover, self.tap_left = (x, y), False

    def _tap_leave(self):
        self.tap_hover, self.tap_left = None, True

    def _js(self, pane, script):
        """Позвать функцию страницы. Страница ещё грузится или окно закрывают — следующий проход повторит."""
        try:
            pane.window.run_js(script)
        except Exception as e:
            print('overlay js: %r' % (e,), flush=True)

    def _ready(self, pane):
        """Окно pywebview создано — дать ему свойства окна поверх игры (и вернуть их, если WinForms их сбросил)."""
        win = self.win
        if pane.hwnd and not win.exists(pane.hwnd):
            pane.hwnd = pane.box = pane.fixed = None
        if pane.hwnd is None:
            try:
                if not pane.window.events.shown.is_set():
                    return
                pane.hwnd = pane.window.native.Handle.ToInt32()
            except Exception:
                return
            pane.box = pane.fixed = pane.alpha = None
        if not win.dressed(pane.hwnd):
            w, tall = SIZE[pane.part]
            scale = win.scale(pane.hwnd)
            win.dress(pane.hwnd, (round(w * scale), round(tall * scale)))
            pane.box = pane.fixed = pane.alpha = None

    def _clear(self, pane, box):
        """В этом месте игрок видит окно игры: под окном поверх игры — она, а не чужое окно. Проверяется не чаще раза
        в COVER_EVERY секунд: вопрос «чьё окно в этой точке» Windows задаёт самим окнам."""
        now = self.clock()
        if pane.seen is None or pane.seen[0] != box or now - pane.seen[1] >= COVER_EVERY:
            x, y, w, h = box
            edge = min(8, w // 4)
            points = ((x + w // 2, y + h // 2), (x + edge, y + h // 2), (x + w - 1 - edge, y + h // 2))
            ours = (self.game, self.glass.hwnd, self.taps.hwnd)
            pane.seen = (box, now, all(self.win.under(point) in ours for point in points))
        return pane.seen[2]

    def _show(self, pane, box, scale, bottom):
        """Поставить окно в box. Страница внутри — постоянного размера: у списка прижата к низу окна (bottom), у ответа
        — к верху; закрепляется один раз (и заново, если сменился масштаб)."""
        size = (box[2], max(box[3], round(SIZE[pane.part][1] * scale)))
        if size != pane.fixed:
            self.win.fix_page(pane.window, size, bottom)
            pane.fixed = size
        if box != pane.box:
            self.win.place(pane.hwnd, box)
            pane.box = box
        pane.scale, pane.dy = scale, (size[1] - box[3] if bottom else 0)

    def _hide(self, pane):
        if pane.box is not None and pane.hwnd:
            self.win.park(pane.hwnd)
        pane.box = None
        if pane.level and pane.part != 'tree':
            pane.level = 0
            self._js(pane, 'window.ovArm && ovArm(0)')
        if pane.part == 'answer':
            self._untap()

    def _untap(self):
        """Стекла на кнопках ответа нет: ответа нет или на нём нет кнопок."""
        self.taps.hide()
        del self.tapped[:]
        self.tap_hover, self._tap_sent, self.tap_left = None, None, False

    def _taps(self, pane):
        """Кнопки окна ответа ловят мышь и без клавиши: стекло встаёт только на них (места называет страница);
        щелчок и движение уходят странице в её точках, курсор ушёл с кнопок — странице сказано."""
        scale, dy, w, h = pane.scale, pane.dy, pane.box[2], pane.box[3]
        spots = []
        for x, y, sw, sh in self.api._places(pane.part):
            x0, y0 = max(0, round(x * scale) - TAP_PAD), max(0, round(y * scale) - dy - TAP_PAD)
            x1, y1 = min(w, round((x + sw) * scale) + TAP_PAD), min(h, round((y + sh) * scale) - dy + TAP_PAD)
            if x1 - x0 >= 4 and y1 - y0 >= 4:
                spots.append((x0, y0, x1 - x0, y1 - y0))
        if not spots:
            self._untap()
            return
        self.taps.cover(pane.box, spots)
        while self.tapped:
            x, y = self.tapped.pop(0)
            self._js(pane, 'window.ovClick && ovClick(%d,%d)' % (round(x / scale), round((y + dy) / scale)))
        if self.tap_left:
            self.tap_left, self._tap_sent = False, None
            self._js(pane, 'window.ovHover && ovHover(-1,-1)')
        elif self.tap_hover is not None and self.tap_hover != self._tap_sent:
            x, y = self._tap_sent = self.tap_hover
            self._js(pane, 'window.ovHover && ovHover(%d,%d)' % (round(x / scale), round((y + dy) / scale)))

    def _unhand(self):
        """Стекло убрано: мышь снова целиком у игры."""
        self.armed = None
        self.glass.hide()
        del self.clicks[:]
        self.hover = self._hover_sent = None

    def hide_all(self):
        self._unhand()
        for pane in self.panes.values():
            self._hide(pane)

    def _game(self, fg):
        """Окно игры: то, что видели впереди; закрылось или ещё не видели — запущенная игра (ищем не чаще раза в секунду)."""
        win = self.win
        ours = bool(fg) and fg in [p.hwnd for p in self.panes.values()] + [self.glass.hwnd, self.taps.hwnd]
        if not ours and self.front():
            self.game = fg
        if not win.exists(self.game):
            self.game = None
            now = self.clock()
            if self.find_game is not None and (self.sought is None or now - self.sought >= 1.0):
                self.sought = now
                self.game = self.find_game() or None
        return self.game

    def step(self):
        """Один проход. Возвращает, сколько ждать до следующего (секунды)."""
        win = self.win
        for pane in self.panes.values():
            self._ready(pane)
        game = self._game(win.foreground())
        on = bool(self.app.overlay.get('on')) and bool(game) and win.alive(game)
        on = on and (self.playing is None or bool(self.playing()))      # герой вне игры — окон нет
        game = win.client(game) if on else None
        if not game or game[2] < MIN_GAME[0] or game[3] < MIN_GAME[1]:
            self.hide_all()
            return 0.25
        monitor, cursor = win.scale(self.game), win.cursor()
        lst, ans, tre = self.panes.get('list'), self.panes.get('answer'), self.panes.get('tree')
        # список шага
        list_top, list_moved = None, False
        if lst is not None and lst.hwnd:
            height, ratio = self.api._size('list')
            scale = ratio or monitor
            # сколько строк имён входит в свёрнутый список в этом окне игры, странице говорит программа; страница
            # отвечает, что знает (box). Не совпало — сказать ещё раз, но не чаще раза в секунду: страница могла
            # ещё грузиться или перезагрузиться (смена языка)
            room, now = fold_lines(game, scale), self.clock()
            if self.api._room('list') != room and (lst.room != room or now - lst.room_at >= 1.0):
                lst.room, lst.room_at = room, now
                self._js(lst, 'window.ovRoom && ovRoom(%d)' % room)
            box = list_box(game, scale, min(height, LIST_TALL)) if height > 0 else None
            if box and self._clear(lst, box):
                list_moved = box != lst.box
                self._show(lst, box, scale, bottom=True)
                list_top = box[1]
            else:
                self._hide(lst)
        # ответ на копию: место — по курсору в момент копии и по списку, каким он тогда был, — один раз на копию.
        # Потом ответ не ездит: ни за курсором, ни за списком, когда тот растёт или убывает.
        if ans is not None and ans.hwnd:
            height, ratio = self.api._size('answer')
            box = None
            if height > 0:
                got, fresh = getattr(self.app, 'copy_cursor', None), ans.box is None
                if got and got != self.cursor_at:
                    self.cursor_at, self.anchor, fresh = got, got[1], True
                if self.anchor is None:
                    self.anchor = cursor
                if fresh:
                    self.floor = game[1] + game[3] - list_top if list_top is not None else None
                scale = ratio or monitor
                top = game[1] + game[3] - self.floor if self.floor is not None else None
                box = answer_box(game, scale, min(height, ANSWER_TALL), self.anchor, top)
            else:
                self.anchor = None
            if box and self._clear(ans, box):
                same = box == ans.box
                self._show(ans, box, scale, bottom=False)
                if list_moved and same:
                    # список сменил размер (раскрылся по клавише) и встал поверх всех окон — ответ на копию остаётся
                    # над ним: его читают, а список в этом месте лишь заслонён
                    win.place(ans.hwnd, box)
                self._taps(ans)
            else:
                self._hide(ans)
        # дерево: показаться или нет, решает его страница (только пока зажата клавиша) и говорит высоту; мышь это
        # окно не ловит никогда — под ним дерево игры, по которому нажимают
        if tre is not None and tre.hwnd:
            height, ratio = self.api._size('tree')
            scale = ratio or monitor
            box = tree_box(game, scale, min(height, TREE_TALL)) if height > 0 else None
            if box and self._clear(tre, box):
                self._show(tre, box, scale, bottom=False)
            else:
                self._hide(tre)
        # Клавиша зажата — все окна показывают рамку: видно, что они слушают мышь. Курсор над окном — оно раскрыто, по
        # нему можно нажимать: стекло ловит мышь. Клавишу отпустили — мышь снова целиком у игры.
        held = bool(cursor) and win.key_down(self.key)
        over = None
        if held:
            over = next((p for p in (ans, lst) if p is not None and p.box and inside(p.box, cursor, round(PAD * p.scale))), None)
        for pane in (ans, lst, tre):
            if pane is None or not pane.hwnd:
                continue
            if pane.part == 'tree':
                level = 1 if held else 0           # клавишу окну дерева говорят всегда: по ней оно появляется
            elif not pane.box:
                continue
            else:
                level = 0 if not held else 2 if pane is over else 1
            if level != pane.level:
                pane.level = level
                self._js(pane, 'window.ovArm && ovArm(%d)' % level)
            # список прозрачнее, пока клавиша не зажата (на сколько — настройка игрока); ответ и дерево плотные всегда
            alpha = idle_alpha(self.app.overlay.get('clear')) if pane.part == 'list' and not level else ALPHA
            if alpha != pane.alpha:
                pane.alpha = alpha
                win.fade(pane.hwnd, alpha)
        if over is not self.armed:
            self._unhand()
            self.armed = over
        pane = self.armed
        if pane is not None and pane.box:
            self.glass.cover(pane.box)
            dy, scale = pane.dy, pane.scale        # точки стекла — от угла окна; страница начинается выше на dy
            while self.clicks:
                x, y = self.clicks.pop(0)
                self._js(pane, 'window.ovClick && ovClick(%d,%d)' % (round(x / scale), round((y + dy) / scale)))
            if self.hover is not None and self.hover != self._hover_sent:
                x, y = self._hover_sent = self.hover
                self._js(pane, 'window.ovHover && ovHover(%d,%d)' % (round(x / scale), round((y + dy) / scale)))
        return 0.03

    def switch(self, main):
        """«Программа ↔ игра» (своя клавиша): впереди окно программы main — назад в игру; иначе — окно программы вперёд."""
        win = self.win
        if win.foreground() != main:
            return win.to_front(main)
        game = self.game if win.exists(self.game) else None
        if game is None and self.find_game is not None:
            game = self.find_game()
        return bool(game) and win.to_front(game)

    def run(self):
        while not self.stop:
            try:
                pause = self.step()
            except Exception as e:  # слежение не должно умирать из-за одной ошибки
                print('overlay: %r' % (e,), flush=True)
                pause = 0.5
            time.sleep(pause)
