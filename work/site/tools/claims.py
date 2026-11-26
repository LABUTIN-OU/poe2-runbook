# -*- coding: utf-8 -*-
"""The site's statements about the program -> where the code says so: file:line, resolved against the project as it
is NOW (an anchor is a piece of a code line; its line number is looked up, so the table does not go stale silently:
an anchor that is no longer found is reported).

    python -X utf8 claims.py <project> [out.md]"""
import re
import sys
from pathlib import Path

project = Path(sys.argv[1])
out = Path(sys.argv[2]) if len(sys.argv) > 2 else None
_cache = {}


def lines(rel):
    if rel not in _cache:
        _cache[rel] = (project / rel).read_text(encoding='utf-8-sig', errors='replace').splitlines()
    return _cache[rel]


def at(rel, anchor, nth=1, after=None):
    """Line number of the nth line holding the anchor (after the line holding «after», if given)."""
    start = 0
    if after:
        start = next(i for i, ln in enumerate(lines(rel)) if after in ln) + 1
    hits = [i + 1 for i, ln in enumerate(lines(rel)) if i >= start and anchor in ln]
    if len(hits) < nth:
        return '%s:?? («%s» не найдено)' % (rel, anchor)
    return '%s:%d' % (rel, hits[nth - 1])


def absent(rel, word):
    """«The file has no such word» as a reference: the count is looked up, like a line number."""
    n = sum(word.lower() in ln.lower() for ln in lines(rel))
    return '%s: «%s» — %s' % (rel, word, 'нет' if not n else 'ЕСТЬ, строк: %d ??' % n)


def program_modules():
    """The modules that ARE the program: everything desktop.py imports, directly or through others, plus the modules
    the build names itself (hiddenimports of packaging/PoE2Runbook.spec). Tests and developer tools that live beside
    them in planner/ (hostile_pages.py, langscan.py…) are not the program and are not searched."""
    import ast
    root = project / 'planner'
    names = {p.stem for p in root.glob('*.py')}
    spec = (project / 'packaging' / 'PoE2Runbook.spec').read_text(encoding='utf-8')
    hidden = re.search(r'hiddenimports=\[(.*?)\]', spec, re.S)
    seen, todo = set(), ['desktop'] + re.findall(r"'(\w+)'", hidden.group(1) if hidden else '')
    while todo:
        m = todo.pop()
        if m in seen or m not in names:
            continue
        seen.add(m)
        for node in ast.walk(ast.parse((root / (m + '.py')).read_text(encoding='utf-8-sig'))):
            if isinstance(node, ast.Import):
                todo += [a.name.split('.')[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                todo.append(node.module.split('.')[0])
    return sorted(seen)


MODULES = program_modules()


def count(pattern):
    """How many code lines of the program hold the pattern, per file — for «the program has no such call»."""
    rx, found = re.compile(pattern), {}
    for name in MODULES:
        p = project / 'planner' / (name + '.py')
        n = sum(1 for ln in p.read_text(encoding='utf-8-sig', errors='replace').splitlines()
                if rx.search(ln) and not ln.lstrip().startswith('#'))
        if n:
            found[p.name] = n
    return found


S, C, G, O, D, A, K, I = ('planner/server.py', 'planner/clip.py', 'planner/gamepaths.py', 'planner/overlay.py',
                          'planner/desktop.py', 'planner/appsettings.py', 'planner/core.py', 'packaging/PoE2Runbook.iss')
U, PC, SG = 'planner/update.py', 'planner/plancat.py', 'planner/signed.py'
P, AD, H, RV = 'planner/static/index.html', 'planner/static/admin.html', 'planner/herostats.py', 'planner/review.py'
ROWS = [
    ('## Главная (по образцу от 17:14): первый экран, разделы, авторам, блок выпуска, «Вопросы»', None),
    ('«Сотни часов проб и ошибок за вас уже потратил автор плана»: у плана из каталога есть автор — его имя идёт из подписанного каталога',
     [at(PC, 'Имя автора плана берётся ТОЛЬКО из подписанного каталога'), at(S, 'def plancat_get(self, uid):')]),
    ('«Runbook ведёт вас по нему: куда идти, кого убить и что взять в каждой зоне»: на шаге — точки, боссы, умения, камни поддержки, задания, тайники',
     [at(K, "KIND_NAMES = {'skill': tr('умение'), 'support': tr('камень поддержки'), 'gem': tr('уровень камня'), 'resource': tr('ресурс'),"),
      at(K, "'boss': tr('босс'), 'quest': tr('задание'), 'mechanic': tr('механика'), 'cache': tr('тайник'),"),
      at(K, "'kind': tr('точка'), 'urgency': 'overdue', 'status': 0, 'place': True, 'auto': True, 'locked': True,")]),
    ('Картинка первого экрана — список шага, окно программы внизу по центру окна игры (страница «Игра» в режиме ?ov=list)',
     [at(O, 'def list_box(game, scale, height):'), at(P, 'const OV = (m =>'), at(D, "for part in ('list', 'answer', 'tree'):")]),
    ('«Вошли в зону — Runbook уже показывает, что в ней делать»: шаг определяется по зоне из лога. ОГОВОРКА: обычный переход на карту '
     'следующего шага меняет шаг сразу; зона, которая на текущем шаге — точка для активации, и вход через несколько шагов меняют шаг '
     'только после порога времени (короткий заход шаг не меняет)',
     [at(K, "return [{'type': 'zone', 'ts': p['ts']"), at(K, 'def derive(plan, run, now'), at(K, '# Короткий заход шаг не меняет.')]),
    ('«Уровень, награды и узлы дерева отмечает сам»: цель «умеет отмечаться сама по логу» — уровень героя, награда, узел дерева '
     '(а ещё восхождение, реплика NPC, стат надетого предмета, путевая точка)',
     [at(K, "'auto': bool(reach or asc or respec is not None or reward or g.get('heard') or g.get('stat') or g.get('node')),"),
      at(K, "return [{'type': 'level', 'ts': ts, 'name': m.group('name')"), at(K, "return [{'type': 'reward', 'ts': ts, 'text': said"),
      at(K, 'RE_PASSIVE = re.compile('), at(K, "or (g.get('node') is not None and (g['node'] in tree_taken or g['node'] in atlas_taken)))")]),
    ('Картинка «Окно PoE2 Runbook: зона, время против плана, маршрут и то, что осталось сделать на шаге» — страница «Игра»',
     [at(P, "g = kind === 'act' ? t.act : t.stretch;"), at(K, 'def derive(plan, run, now')]),
    ('«Автор плана знает, к какому шагу что должно быть взято и надето»: у цели плана есть шаг-срок',
     [at(K, "urg = 'overdue' if deadline >= 0 and past(deadline) else 'due'")]),
    ('«Опоздали — строка краснеет…»',
     [at(K, "late = max(1, p_now - late_from) if urg == 'overdue' and late_from is not None and late_from >= 0 else 0"),
      at(P, "T('Опаздываю')")]),
    ('«…и остаётся, пока не сделаете»: опоздавшие цели собираются со всех шагов, в свёрнутом списке — красным числом',
     [at(K, "overdue = [v for v in all_views + [gview(g) for g in respec_goals] if v['urgency'] == 'overdue']"),
      at(P, 'долги — красным числом')]),
    ('«F2 над предметом — и видно, лучше он надетого или хуже»: одна копия текста предмета на нажатие, ответ «ЛУЧШЕ» / «ХУЖЕ» / «ТАК ЖЕ»',
     [at(S, 'def hotkey_item('), at(C, 'def send_copy(self, mod=VK_MENU):'), at(S, 'def take_copy('),
      at(P, "const VERDICT = {better: T('ЛУЧШЕ'), worse: T('ХУЖЕ'), same: T('ТАК ЖЕ')")]),
    ('«По статам, которые выбрал автор плана»: сравнение идёт по статам плана (его этапам)',
     [at(H, 'def compare(cat, plan, slot, key, item, worn, extra'), at(S, 'def _stats_view(')]),
    ('«У каждого шага и акта — время из плана»: целевое время шага записано в плане, у акта и этапа — сумма',
     [at(K, "targets = [parse_clock(s.get('target')) for s in steps]"), at(K, 'def group_time(member):'),
      at(K, "'target': sum(targets[i] or 0 for i in idx) or None,")]),
    ('«Видно, где вы идёте с запасом и где отстаёте» — слова плиток времени «запас» / «отстаю»',
     [at(P, "(T('запас') + ' ')")]),
    ('Картинка «Три плитки времени: до восхождения, акт и текущая зона — прошло, цель и запас» — плитки этапа, акта и шага страницы «Игра»',
     [at(P, "g = kind === 'act' ? t.act : t.stretch;"), at(P, "label = stepName || T('Шаг'); spent = stepSpent; target = t.step.target;")]),
    ('«После игры «Разбор» показывает, куда ушло время: по шагам, в зоне, в городе и в стороне от маршрута» — столбцы «Разбора»',
     [at(RV, 'def split(plan, run, pos_log, now=None):'), at(S, 'def review_view('), at(P, "th(T('В зоне'), 'rv-nw', 'z');"),
      at(P, "th(T('Город'), 'rv-nw', 't');"), at(P, "th(T('Вне маршрута'), '', 'o');")]),
    ('«Сравните с прошлым героем — и увидите, где стали быстрее»: время в «Разборе» сравнивается с целями плана или с другим героем',
     [at(P, 'С чем сравнивать — с целями плана или с другим героем'), at(P, "T('Где отстал от {0}', tag(D.base))")]),
    ('Строка под разделом: «Где отстал от цели · Где дольше в городе · Где уходил с маршрута» — дословно порядки строк «Разбора». '
     'ОГОВОРКА: четвёртый — «Сколько попыток ушло на карту» — пересказ: в программе этот порядок называется «Где больше попыток» '
     '(до 26.11, 18:34 — «Карты заново»; число попыток на шаге и время в прерванных попытках там названы)',
     [at(P, "T('Где отстал от цели')"), at(P, "T('Где дольше в городе')"), at(P, "T('Где уходил с маршрута')"),
      at(P, "['again', T('Где больше попыток'), steps.filter(s => s.q > 0).length]];"), at(P, 's.q — сколько попыток на шаге')]),
    ('Картинка ««Разбор»: время каждого шага первого акта рядом с целью и график отставания» — таблица «Разбора»: полоса шага с меткой цели, '
     'в строке акта — ход отставания', [at(S, 'def review_view('), at(P, "th(T('В зоне'), 'rv-nw', 'z');")]),
    ('«Соберите свой план. Кампания уже размечена: каждая зона, босс и награда»: «Новый план» берёт маршрут из шаблона кампании, '
     'который идёт с программой; боссы и награды — из справочника игры',
     [at('planner/planlib.py', "TEMPLATE = 'campaign.json'"), at(S, 'self.template_path = self.know_path.with_name(planlib.TEMPLATE)'),
      at(S, "if base == 'template':"), at('planner/landmarks.py', 'def load(path):')]),
    ('«…добавьте билд и сроки»; картинка «Редактор плана: шаги первого акта с целями и временем» — вкладки редактора',
     [at(AD, "const TABS = [['build', T('Билд')], ['tree', T('Дерево')], ['route', T('Маршрут')]"), at(S, 'def new_plan(self, req):')]),
    ('Авторам: «Соберите билд в план: маршрут, этапы, время на каждый шаг» — вкладки «Маршрут» и «Этапы», целевое время шага',
     [at(AD, "const TABS = [['build', T('Билд')], ['tree', T('Дерево')], ['route', T('Маршрут')]"),
      at(K, "targets = [parse_clock(s.get('target')) for s in steps]")]),
    ('Авторам: «В каталоге он будет стоять под вашим именем и со ссылкой на вас»: имя и адрес страницы автора программа берёт '
     'только из подписанного каталога',
     [at(PC, 'Имя автора плана берётся ТОЛЬКО из подписанного каталога'), at(PC, "author['url'] = who['url']"), at(S, 'def open_author(self, uid):')]),
    ('Авторам: «Игроки пройдут игру вашим путём»: план из каталога ставится из программы', [at(S, 'def plancat_get(self, uid):'), at(PC, 'def read_index(')]),
    ('Вопрос о гайде: «Runbook идёт вместе с вами: знает, в какой вы зоне, и показывает, что делать сейчас»',
     [at(S, 'def poll_log('), at(K, "return [{'type': 'zone', 'ts': p['ts']"), at(K, 'def derive(plan, run, now')]),
    ('Вопрос о плане под класс: «Планы появляются в каталоге, когда ими делятся авторы» — каталог одобренных планов',
     [at(PC, 'def read_index('), at(S, 'def plancat_view(self, lang):')]),
    ('…«А пока можно собрать свой: кампания уже размечена, остаётся добавить билд»',
     [at(S, 'def new_plan(self, req):'), at('planner/planlib.py', "TEMPLATE = 'campaign.json'")]),
    ('Вопрос о патче: «После патча нужна новая сборка Runbook»: каждая сборка сделана под одну версию игры',
     [at('planner/appversion.py', "GAME = '0.5.5'"), at('planner/appversion.py', 'def program(')]),
    ('…«Пока её нет, программа предупредит, что игра новее»: версию игры читает из лога и сравнивает со своей',
     [at('planner/appversion.py', 'def newer(game, catalog_version):'), at(S, "'newer': appversion.newer(self.game_tag, made)}")]),
    ('…«Когда выйдет — обновится одной кнопкой» — «Обновить», когда новая сборка опубликована',
     [at(U, 'def install(self):'), at(S, "elif req.get('go') is True:")]),
    ('Вопрос «Список не появляется поверх игры»: «…когда игра идёт в полноэкранном режиме: она закрывает собой окна Runbook. '
     'Выберите… оконный полноэкранный режим»',
     [at(O, 'Режим игры — окно или окно без рамки на весь экран'), at(O, 'В монопольном полноэк')]),
    ('…«проверьте в «Настройках» Runbook, что окна поверх игры включены» — строка «Окна поверх игры» окна «Настройки»',
     [at(P, "rows += line(T('Окна поверх игры')"), at(S, "OVERLAY_CHOICES = {'on': ('overlay', (True, False), True)")]),
    ('Вопрос об установщике: «Установщик пока не подписан» — в сборке установщика подписи нет (слова «Подробнее» и «Выполнить в любом случае» — '
     'окна Windows, кодом программы не доказываются)', [absent(I, 'SignTool')]),
    ('Вопрос о запросах: «Написать автору» — адрес берётся из настройки сайта («Это первая версия… принимаются любые запросы» — '
     'обещание автора, не факт кода)', [at('site/assets/config.js', "contact: '")]),
    ('Блок выпуска: «Windows 10 и 11» — установщик для 64-разрядной Windows', [at(I, 'ArchitecturesAllowed=x64compatible')]),

    ('## Читает: файлы игры', None),
    ('Лог игры — `logs\\Client.txt` в папке игры (у клиента Kakao — `KakaoClient.txt`)',
     [at(G, "LOGS = ('Client.txt', 'KakaoClient.txt')"), at(G, 'def log_in(')]),
    ('Лог открывается только на чтение; дочитываются новые байты с места, где остановились',
     [at(S, 'def poll_log('), at(S, "with open(self.log_path, 'rb') as f:", after='def poll_log(')]),
    ('При запуске лог читается целиком', [at(S, 'app.poll_log(initial=True)')]),
    ('Новые строки — дважды в секунду', [at(S, 'def loop(self):'), at(S, 'time.sleep(0.5)', after='def loop(self):'),
                                        at(S, 'def tick(self):')]),
    ('Из лога берётся: запуск и закрытие игры', [at(K, "LOG_OPENING = 'LOG FILE OPENING'"), at(K, 'RE_CLOSING = re.compile')]),
    ('…зона, в которую вошли (код, уровень, название)', [at(K, 'RE_GEN = re.compile'), at(K, 'RE_SRC = re.compile'),
                                                        at(K, "return [{'type': 'zone', 'ts': p['ts']")]),
    ('…уровень героя — с именем и классом героя', [at(K, "return [{'type': 'level', 'ts': ts, 'name': m.group('name')")]),
    ('…награды за задания, очки пассивных умений', [at(K, "return [{'type': 'reward', 'ts': ts, 'text': said"),
                                                   at(K, "out = [{'type': 'points', 'ts': ts")]),
    ('…гибель героя', [at(K, "return [{'type': 'death', 'ts': ts")]),
    ('…какой фильтр предметов загрузила игра', [at(K, 'RE_FILTER = re.compile'), at(K, "return [{'type': 'filter', 'ts': ts, 'id': m.group(1)")]),
    ('…нажатия в дереве пассивных умений', [at(K, 'RE_PASSIVE = re.compile'), at(K, "out = [{'type': 'passive', 'ts': ts")]),
    ('…версия игры', [at('planner/appversion.py', 'RE_GAME_TAG = re.compile'), at(S, 'tag = appversion.game_tag(line)')]),
    ('Из чата замечаются только реплики, которых ждёт план; хранятся коды строк, а не текст; остальное не сохраняется',
     [at(K, 'RE_SAY = re.compile'), at(K, 'if self._index:'), at(K, "return [{'type': 'say', 'ts': ts, 'ids': ids}]"),
      at(K, 'return []', after="return [{'type': 'say', 'ts': ts, 'ids': ids}]")]),
    ('Настройки игры — `poe2_production_Config.ini` в «Документах» (иначе самый свежий `poe2_*Config.ini`)',
     [at(G, "CONFIG = 'poe2_production_Config.ini'"), at(G, 'def game_docs('), at(G, 'def config_in(')]),
    ('Из настроек берётся: выбранный фильтр, язык клиента, привязки клавиш; файл читается заново, когда меняется',
     [at(S, 'def load_config('), at(S, 'if mtime == self._config_mtime:'), at(S, "if line.startswith('item_filter='):"),
      at(S, "elif line.startswith('language='):"), at(S, 'keys = clip.pick_keys(clip.game_keys(text), clip.ALL_KEYS)'),
      at(C, 'def game_keys('), at(D, 'def message_lang(')]),
    ('Фильтры предметов из аккаунта — папка `OnlineFilters` в «Документах»', [at(S, "args.filters or docs / 'OnlineFilters'")]),
    ('Читаются название фильтра (шапка файла) и его правила — предупредить, что фильтр скрывает цель плана',
     [at(S, 'def filter_header('), at(S, 'def _filters_stamp('), at(S, 'def _filter_blocks('),
      at(S, 'self._fcache = filtereval.parse(path)'), at(S, 'def filter_check(')]),
    ('Копия каждой загруженной версии фильтра остаётся в папке программы', [at(S, 'def archive_filter('),
                                                                           at(S, 'dst.write_bytes(src.read_bytes())')]),
    ('Где стоит игра: файлы Steam `libraryfolders.vdf`, `appmanifest_2694490.acf`',
     [at(G, 'def steam_libraries('), at(G, "(steam / 'steamapps' / 'libraryfolders.vdf').read_text"), at(G, 'def steam_dirs(')]),
    ('…и реестр Windows — только чтение: папка Steam, записи установленных программ',
     [at(G, 'class Registry:'), at(G, 'STEAM_KEYS = ('), at(G, 'UNINSTALL = ('), at(G, 'def installed_dirs('), at(G, 'def find(')]),
    ('Игра не нашлась — папку указывает игрок (окно выбора папки)', [at(S, 'def choose_game('), at(S, "if path == '/api/game':"),
                                                                    at(D, 'def pick_folder():')]),

    ('## Спрашивает у Windows', None),
    ('Какое окно активно и какой программе оно принадлежит (её папка); память игры не читается',
     [at(C, 'def game_in_front('), at(C, 'def _front_exe_dir('), at(C, 'PROCESS_QUERY_LIMITED_INFORMATION = 0x1000'),
      at(G, 'def game(self):'), at(G, 'handle = self.kernel32.OpenProcess(0x1000')]),
    ('Где окно игры, где курсор, зажат ли Alt — пока окна поверх игры включены, окно игры есть и герой в игре',
     [at(O, 'def client(self, hwnd):'), at(O, 'def cursor(self):'), at(O, 'def key_down(self, vk):'),
      at(O, 'held = bool(cursor) and win.key_down(self.key)'), at(O, "on = bool(self.app.overlay.get('on')) and bool(game) and win.alive(game)"),
      at(O, 'return 0.03')]),
    ('С экрана ничего не читается', [at(O, 'С экрана программа ничего не читает')]),

    ('## Буфер обмена', None),
    ('Следит только за счётчиком изменений буфера (число), раз в 0,2 с; содержимое при этом не читается',
     [at(C, 'def seq(self):'), at(C, 'return self.user32.GetClipboardSequenceNumber()'), at(C, 'def run(self, pause=0.2):')]),
    ('Содержимое читается один раз на смену счётчика и только при активном окне игры; иначе буфер не открывается',
     [at(C, 'def poll(self):', after='class Watcher:'), at(C, 'def text(self):'), at(C, 'if not self.game_in_front():')]),
    ('То, что лежало в буфере до запуска программы, не читается', [at(C, 'self.last = source.seq()')]),
    ('Только текст, не больше 200 000 байт', [at(C, 'CF_UNICODETEXT = 13'), at(C, 'MAX_BYTES = 200_000'),
                                             at(C, 'if not size or size > MAX_BYTES:')]),
    ('Текст, который не начинается со строки игры «Класс предмета», отбрасывается: не хранится и не пишется',
     [at(C, 'if not itemcopy.is_item(text):'), at('planner/itemcopy.py', 'def is_item(')]),
    ('Текст предмета — только в памяти; сравнение уходит со страницы через 60 секунд',
     [at(S, 'COPY_SECONDS = 60'), at(S, 'def take_copy('), at(S, 'def expire_copy(')]),
    ('По «Надеть» предмет записывается в файл героя как надетый',
     [at(S, "self.run.worn[keep] = {'at': time.time(), 'item': self.copied}"), at(S, "'worn': run.worn,")]),
    ('F2: программа запоминает буфер (до 32 МБ), копирует, читает один раз и возвращает прежнее; запомненное не разбирает',
     [at(C, 'class Copier:'), at(C, 'def grab(self):'), at(C, 'def snapshot(self):'), at(C, 'SNAP_BYTES = 32 * 1024 * 1024'),
      at(C, 'def restore(self, snap):')]),

    ('## Клавиши, которые слушает', None),
    ('F2 «Сравнить / Надеть», F3 «Закрыть», F7 «Программа ↔ игра»; запасные — F6, F9, F10, F11; F4 не берётся никогда',
     [at(C, 'KEY_ORDER = (2, 3, 7, 6, 9, 10, 11)'), at(C, "KEY_IDS = {'wear': 0x5E01, 'close': 0x5E02, 'app': 0x5E04}"),
      at(C, 'def pick_keys('), at(C, '# F4 программа не берёт никогда')]),
    ('Клавиши, занятые игрой, не берутся (по её файлу настроек)', [at(C, 'def game_keys('),
                                                                  at(S, 'keys = clip.pick_keys(clip.game_keys(text), clip.ALL_KEYS)')]),
    ('Клавиши регистрируются в Windows (RegisterHotKey) только пока активно окно игры и снимаются, когда активно другое',
     [at(C, 'class WinKeys:'), at(C, 'def step(self):'), at(C, 'if self.user32.RegisterHotKey(None, kid, MOD_NOREPEAT, vk):'),
      at(C, 'self.user32.UnregisterHotKey(None, kid)       # игра ушла назад')]),
    ('F7 слушается и в окне самой программы', [at(S, "fronts['app'] = lambda:")]),
    ('F2 работает и с зажатым Alt', [at(C, "ALT_TOO = ('wear',)"), at(C, 'MOD_NOREPEAT | MOD_ALT, vk)')]),
    ('F2: новый предмет — сравнить, тот же предмет ещё раз — «Надеть»', [at(S, 'def on_wear():'), at(S, 'def hotkey_item('),
                                                                        at(S, 'SAME_GUARD = 0.3')]),
    ('F3 убирает верхнее окно программы', [at(S, 'def hotkey_close(')]),
    ('F7 выводит окно программы вперёд и возвращает в игру', [at(O, 'def switch(self, main):'), at(O, 'def to_front(self, hwnd):')]),

    ('## Что посылает игре', None),
    ('Ctrl + Alt + C — одно нажатие на каждое F2 (SendInput), клавиши держатся 15 мс',
     [at(C, 'def send_copy(self, mod=VK_MENU):'), at(C, 'return user32.SendInput(len(pairs), arr, ctypes.sizeof(INPUT)) == len(pairs)'),
      at(C, 'time.sleep(0.015)'), at(C, 'src.send_copy(self.mod())')]),
    ('Только пока активно окно игры', [at(C, 'if not src.game_in_front():')]),
    ('Вместо Alt — клавиша «подробное описание предмета» из настроек игры, если она другая',
     [at(S, "self.copy_mod = clip.game_key(text, 'show_advanced_item_descriptions') or clip.VK_MENU"), at(C, 'def game_key(')]),
    ('«Надеть» и отметки меняют только записи программы', [at(S, 'def wear(self, req):'), at(S, 'def mark(self, goal_id, status):')]),

    ('## Окна поверх игры', None),
    ('Три окна: список шага, ответ на копию, дерево', [at(D, "for part in ('list', 'answer', 'tree'):")]),
    ('Не активируются и пропускают мышь в игру', [at(O, 'DRESS = WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_LAYERED | WS_EX_NOACTIVATE'),
                                                at(O, 'def dress(self, hwnd, size):')]),
    ('Нажать по ним можно при зажатом Alt и курсоре над окном («стекло»), у ответа — и по кнопкам без Alt',
     [at(O, 'class Glass:'), at(O, '# MA_NOACTIVATE'), at(O, 'over = next((p for p in (ans, lst)'), at(O, 'def _taps(self, pane):')]),
    ('Им нужна игра в окне или в окне без рамки на весь экран', [at(O, 'Режим игры — окно или окно без рамки на весь экран')]),
    ('Выключаются настройкой', [at(S, 'OVERLAY_CHOICES = {'), at(S, 'def set_overlay_opt(')]),

    ('## Что пишет на диск', None),
    ('Папка данных — `%APPDATA%\\PoE2 Runbook`', [at(D, "APP = 'PoE2 Runbook'"), at(D, 'def data_dir('),
                                                 at(D, "args = ['--port', str(port), '--plans', str(data / 'plans'), '--runs', str(data / 'runs'),")]),
    ('`plans\\` — планы игрока и планы из каталога; план из комплекта кладётся при первом запуске',
     [at(D, 'def seed_plans('), at(S, "pid = planlib.add(self.plans_dir, data, '', uid=uid, extra={'catalog': record})")]),
    ('`runs\\` — файл на героя (события лога, отметки, надетое) и малые списки',
     [at(S, 'def save_run('), at(S, 'def _run_path('), at(S, "return self.runs_dir / 'plans.json'"),
      at(S, "return self.runs_dir / 'switches.json'"), at(S, "return self.runs_dir / 'gone.json'"), at(S, "return self.runs_dir / 'atlas.json'")]),
    ('`filters\\` — копии версий фильтра', [at(D, "'--archive', str(data / 'filters')"), at(S, 'def archive_filter(')]),
    ('`backup\\` — прежние версии плана перед правкой; убранные планы',
     [at(S, 'def book_backup('), at('planner/buildplan.py', 'def write_text('), at('planner/planlib.py', 'shutil.move(str(path.parent), str(dest))')]),
    ('`export\\` — файлы планов для обмена', [at(S, 'def save_plan_file(')]),
    ('`settings.json` — папка игры, окно, выбор в «Настройках»',
     [at(A, 'def update('), at(D, 'def remember_window():'), at(S, 'appsettings.update(self.settings_path, gameDir=str(self.game_dir))'),
      at(S, 'appsettings.update(self.settings_path, **{key: value})')]),
    ('`program.log` и пять прежних', [at(D, 'LOGS_KEPT = 5'), at(D, 'def open_log(')]),
    ('`webview\\` — хранилище движка окна', [at(D, "storage_path=str(data / 'webview')")]),
    ('`update\\` — установщик новой версии после «Обновить»; после установки убирается',
     [at(D, "upd = update.Updater(version, data / 'update'"), at(U, 'final, part = self.folder / name'), at(U, 'def tidy(self):')]),
    ('Папка программы `%LOCALAPPDATA%\\Programs\\PoE2 Runbook` — пишет только установщик, без прав администратора',
     [at(I, 'DefaultDirName={autopf}\\PoE2 Runbook'), at(I, 'PrivilegesRequired=lowest')]),
    ('«Скачать файл плана» — в папку «Загрузки»', [at(D, "webview.settings['ALLOW_DOWNLOADS'] = True")]),
    ('Удаление программы оставляет папку данных', [at(I, 'ни обновление, ни удаление программы их не трогают')]),

    ('## Сеть', None),
    ('Проверка обновлений — при запуске и раз в 6 часов; сайт не ответил или игра новее программы, а новой сборки нет — через полчаса',
     [at(U, 'EVERY = 6 * 3600'), at(U, 'SOON = 30 * 60'), at(U, 'def run(self):'),
      at(U, 'soon = not reached or (self.on and self.offer is None and self.urgent())'),
      at(D, "urgent=lambda: appversion.newer(app.game_tag, made)")]),
    ('…скачиваются четыре файла с этого сайта: `update/latest.json`, `plans/index.json` и подпись (`.sig`) к каждому',
     [at(U, "URL = 'https://poe2.labutin.gg/update/latest.json'"), at(U, "SIG_URL = URL + '.sig'"),
      at(U, 'data = self.fetch(URL, MAX_MANIFEST, CHECK_TIMEOUT)'), at(U, 'sig = self.fetch(SIG_URL, MAX_SIG, CHECK_TIMEOUT)'),
      at(PC, "INDEX_URL = 'https://poe2.labutin.gg/plans/index.json'"), at(PC, "SIG_URL = INDEX_URL + '.sig'"),
      at(PC, 'data = self.fetch(INDEX_URL, MAX_INDEX, update.CHECK_TIMEOUT)'),
      at(PC, 'sig = self.fetch(SIG_URL, MAX_SIG, update.CHECK_TIMEOUT)')]),
    ('…каталог спрашивается каждой проверкой обновлений, пока «Проверять обновления» включено',
     [at(U, 'for extra in (self.also if self.on else ()):'), at(D, 'upd.also.append(app.plancat_check)'), at(S, 'def plancat_check(')]),
    ('Каталог запрашивается ещё и при открытии списка планов в «Редакторе» — не чаще раза в минуту и только пока «Проверять обновления» включено',
     [at('planner/static/index.html', 'if (refresh) catPost({refresh: true});'), at(S, 'def plancat_refresh(self, ask=False):'),
      at(S, 'if not ask and not self.net_allowed():'), at(S, 'def net_allowed(self):'), at(PC, 'FRESH = 60'),
      at(PC, 'def check(self, fresh=None):')]),
    ('Настройка выключена — программа сама к сайту не обращается: каталог запрашивается только по кнопке «Спросить каталог»',
     [at(U, 'reached = self.check() if self.on else True'), at(U, 'for extra in (self.also if self.on else ()):'),
      at(S, "if req.get('refresh') is True or req.get('ask') is True:"), at(S, "app.plancat_refresh(ask=req.get('ask') is True)"),
      at('planner/static/index.html', "if (what === 'ask') { if (!CAT.busy) catPost({ask: true}); return; }")]),
    ('…в каждом запросе — версия программы (`User-Agent: PoE2Runbook/<версия>`) и больше ничего: cookies выключены',
     [at(U, "self.agent = 'PoE2Runbook/%s' % version"),
      at(S, "self.plancat = plancat.Catalog(signed.embedded_key(), 'PoE2Runbook/%s' % ("),
      at(PC, 'self.fetch = fetch or (lambda url, limit, timeout: update.get(url, self.agent, limit, timeout))'),
      at(U, 'no_cookies = w.DWORD(0x1)'), at(U, 'if not h.WinHttpSendRequest(r, None, 0, None, 0, 0, 0):')]),
    ('…выключается в «Настройках»: «Проверять обновления»',
     [at(U, "SETTING = 'updates'"), at(U, 'def set_on(self, on):'), at(U, 'reached = self.check() if self.on else True'),
      at(S, "elif 'on' in req:")]),
    ('…есть только у собранной программы (окно), не у сервера из исходников', [at(D, "if getattr(sys, 'frozen', False) and not own.selftest:"),
                                                                             at(D, 'def start_updates(app):')]),
    ('Подписи обоих файлов программа проверяет сама — ключом, вписанным в неё, — до того, как читает файл',
     [at(U, 'def read_manifest('), at(U, 'signed.check(data, sig, point, MAX_MANIFEST)'), at(PC, 'def read_index('),
      at(PC, 'signed.check(data, sig, point, MAX_INDEX)'), at(SG, 'def check(data, sig, point, limit):'),
      at(SG, 'if not verify(data, raw, point):'), at(SG, 'def verify(data, signature, point):'), at(SG, 'def embedded_key():'),
      at('planner/updatekey.py', 'PUBLIC_KEY = ')]),
    ('Принимается только версия новее своей', [at(U, "raise Refused('older', info['version'])"),
                                              at(U, 'self.offer = info if rel > 0 else None')]),
    ('Пока не нажато «Обновить» или «Поставить», ничего не качается и не ставится',
     [at(U, 'def install(self):'), at(S, "elif req.get('go') is True:"), at(S, 'ok = upd.install()'),
      at(S, "elif isinstance(req.get('get'), str):"), at(S, "res = app.plancat_get(req['get'])")]),
    ('«Поставить» / «Обновить» в каталоге: файл плана — по адресу из подписанного каталога (только https), сверяются размер, '
     'SHA-256 и метка плана; план кладётся в библиотеку',
     [at(S, 'def plancat_get(self, uid):'), at(PC, 'def load(self, entry):'),
      at(PC, "data = self.fetch(entry['url'], entry['size'], update.LOAD_TIMEOUT)"), at(PC, 'def read_plan(data, entry):'),
      at(PC, "if hashlib.sha256(data).hexdigest() != entry['sha256']:"),
      at(PC, "url, size, sha = update._https(f.get('url')), f.get('size'), f.get('sha256')"),
      at(S, "pid = planlib.add(self.plans_dir, data, '', uid=uid, extra={'catalog': record})")]),
    ('По «Обновить»: установщик — по адресу из подписанного файла (только https)', [at(U, 'def _https(url):'),
                                                                                  at(U, "url = _https(inst.get('url'))"),
                                                                                  at(U, "got = self.fetch(offer['url'], offer['size'], LOAD_TIMEOUT")]),
    ('…сверяются размер и SHA-256 с подписанным файлом', [at(U, 'def _load(self, offer, part):'),
                                                         at(U, "if got != offer['size'] or part.stat().st_size != offer['size']:"),
                                                         at(U, "if digest.hexdigest() != offer['sha256']:")]),
    ('…установщик запускается, программа закрывается; установщик ставит новую версию и открывает её',
     [at(U, 'def start_installer('), at(U, "SWITCHES = ('/VERYSILENT'"), at(U, 'self.quit()'), at(D, 'def quit_for_update():')]),
    ('Страницы окна отдаёт свой сервер на 127.0.0.1; запрос с чужим Host / Origin получает отказ',
     [at(S, "httpd = ThreadingHTTPServer(('127.0.0.1', args.port)"), at(S, 'def _local_only(self):')]),
    ('Окно — Microsoft Edge WebView2', [at(D, "webview.start(boot, gui='edgechromium'"), at(D, 'def webview2():')]),
    ('Браузер по нажатию: официальный сайт из окна «О программе»', [at(S, 'def open_site('), at('planner/about.py', "SITE = 'https://poe2.labutin.gg'"),
                                                                   at('planner/static/index.html', "body: JSON.stringify({page: 'site'})")]),
    ('…страница автора плана из каталога (адрес — только из подписанного каталога, только http(s))',
     [at(S, 'def open_author(self, uid):'), at(PC, 'def web_url(url):'),
      at(S, "app.open_author(req.get('uid')) if req.get('page') == 'author' else False")]),
    ('…страница фильтра на pathofexile2.com', [at(S, 'def open_filter('), at(K, "FILTER_PAGE = 'https://pathofexile2.com/item-filter/%s'"),
                                              at(S, "if path == '/api/open':")]),
    ('…страница загрузки WebView2 у Microsoft, если движка нет', [at(D, 'WEBVIEW2_PAGE = '), at(D, 'webbrowser.open(WEBVIEW2_PAGE)')]),

    ('## Первый запуск, что нужно, обновление, удаление, каталог планов, лицензия', None),
    ('Удаление — запись «PoE2 Runbook» среди приложений Windows', [at(I, 'UninstallDisplayName=PoE2 Runbook')]),
    ('«Установщик пока не подписан»: в сборке установщика подписи нет', [absent(I, 'SignTool')]),
    ('«Нет прав администратора — они не нужны. Установщик ставит программу только для вас»: Windows 64-bit, установка для текущего пользователя',
     [at(I, 'ArchitecturesAllowed=x64compatible'), at(I, 'PrivilegesRequired=lowest')]),
    ('Нет WebView2 — программа говорит об этом и предлагает страницу Microsoft', [at(D, "if sys.platform == 'win32' and not webview2():")]),
    ('«Программа ищет игру сама: Steam или клиент с сайта игры, на любом диске»: запущенная игра, запомненная папка, Steam, записи '
     'установщиков, папки по умолчанию', [at(G, 'def find(')]),
    ('«Если не нашла, она скажет об этом и даст указать папку игры»', [at(S, 'def choose_game(self, path):'), at(S, 'def set_game(self, game_dir, log):')]),
    ('«О новой версии программа скажет сама и поставит её по кнопке «Обновить»»', [at(U, 'def install(self):'), at(S, "elif req.get('go') is True:")]),
    ('«Новая версия ставится поверх прежней: ваши планы и герои остаются» — они лежат не в папке программы, а в папке данных',
     [at(I, 'PrivilegesRequired=lowest'), at(D, 'APPDATA')]),
    ('«Каталог — это планы, которые игроки ставят прямо из программы: «Редактор» → «Каталог»»',
     [at(AD, "${T('Каталог')}</h3>"), at(S, 'def plancat_get(self, uid):')]),
    ('«Каждый план стоит там под именем автора и со ссылкой на него»; «Имя автора программа берёт только из каталога, не из файла плана»',
     [at(PC, 'Имя автора плана берётся ТОЛЬКО из подписанного каталога'), at(PC, "author['url'] = who['url']")]),
    ('«Сохраните его файлом: «Редактор» → «Скачать файл плана»»', [at(AD, "${T('Скачать файл плана')}</a>"), at(S, 'def save_plan_file(self, pid):')]),
    ('«Автор программы посмотрит план и добавит его в каталог»: план в каталог добавляет инструмент выпуска — проверка файла плана и подпись каталога',
     [at('release/plans.py', 'def check_plan(bundle, root):'), at('release/plans.py', 'def add(path, author, author_url=None'),
      at('release/plans.py', 'def write_index(doc, site, key, planner):')]),
    ('«После этого план появится в программе у всех игроков»: каталог программа спрашивает при запуске и раз в 6 часов', [at(PC, 'def read_index(')]),
    ('Сборка сделана под одну версию игры', [at('planner/appversion.py', "GAME = '0.5.5'"), at('planner/appversion.py', 'def program(')]),
    ('Языки программы — файлы `planner/lang/*.json` (девять; `raw.json` — не язык)', [at('planner/i18n.py', 'def languages():')]),
    ('Лог читается на языке клиента', [at('planner/logtext.py', 'CONFIG_LANGS = {'), at(S, 'def set_client_lang(')]),
    ('Условия лицензии — слова из `NOTICE.md`', [at('NOTICE.md', '## In plain words'), at('NOTICE.md', '## По-русски, коротко')]),
    ('`LICENSE` и `NOTICE.md` лежат в программе и открываются в окне «О программе»',
     [at('packaging/build.py', "LEGAL = ['LICENSE', 'NOTICE.md']"), at('planner/about.py', "LEGAL = ('LICENSE', 'NOTICE.md', 'THIRD-PARTY.md')"),
      at('planner/static/index.html', 'function abtFile(name)')]),
    ('Строка GGG', [at('NOTICE.md', "This product isn't affiliated with or endorsed by Grinding Gear Games in any way.")]),
]

md = ['| Утверждение на странице | Где это в коде |', '|---|---|']
missing = 0
for text, refs in ROWS:
    if refs is None:
        md.append('| **%s** | |' % text[3:])
        continue
    missing += sum('??' in r for r in refs)
    md.append('| %s | %s |' % (text, ', '.join('`%s`' % r for r in refs)))

SEARCH = [
    ('Перехватчик клавиатуры (`SetWindowsHook`, `GetKeyboardState`, `RegisterRawInputDevices`)', r'SetWindowsHook|GetKeyboardState|RegisterRawInputDevices'),
    ('Опрос клавиш `GetAsyncKeyState` (overlay.py — Alt; clip.py — Ctrl и Alt в момент своей копии)', r'GetAsyncKeyState\('),
    ('Посылка клавиш `SendInput` (clip.py — своя копия)', r'\.SendInput\('),
    ('Другие способы послать ввод (`keybd_event`, `mouse_event`, `PostMessage`, `SendMessage`)', r'keybd_event|mouse_event|PostMessage|SendMessage'),
    ('Память чужого процесса (`ReadProcessMemory`, `WriteProcessMemory`)', r'ReadProcessMemory|WriteProcessMemory'),
    ('`OpenProcess` (только право 0x1000 — узнать файл программы окна)', r'\.OpenProcess\('),
    ('Снимок экрана (`BitBlt`, `PrintWindow`, `GetDC`, `ImageGrab`, `CopyFromScreen`)', r'BitBlt|PrintWindow|GetDC\b|ImageGrab|CopyFromScreen'),
    ('Запросы в сеть через WinHTTP самой Windows (update.py — одно место на всё: файл обновления, каталог планов, установщик, '
     'файл плана)', r'WinHttpSendRequest\('),
    ('Запросы в сеть средствами Python (`urllib.request`, `http.client`, `requests`, `urlopen`, `ftplib`, `smtplib`): '
     'desktop.py — проверка сборки у своего же сервера на 127.0.0.1, только с ключом `--selftest`',
     r'urllib\.request|http\.client|\brequests\.|urlopen\(|ftplib|smtplib'),
    ('`socket` (desktop.py — поиск свободного порта на 127.0.0.1)', r'socket\.socket\('),
    ('Запуск браузера (`webbrowser.open`, `self.opener(`)', r'webbrowser\.open|self\.opener\('),
    ('Запуск других программ (`subprocess.Popen`, `os.system`, `os.startfile`, `ShellExecute`): update.py — установщик новой версии',
     r'subprocess\.Popen|os\.system|os\.startfile|ShellExecute'),
]
md += ['', '| Поиск по модулям программы (%d: всё, что тянет за собой `desktop.py`, и названное в сборке; тесты и инструменты '
       'разработчика рядом с ними — не программа) | Найдено строк кода |' % len(MODULES), '|---|---|']
for name, pattern in SEARCH:
    found = count(pattern)
    md.append('| %s | %s |' % (name, ', '.join('%s — %d' % kv for kv in found.items()) or 'нет'))
pages = {p.name: sum(1 for ln in p.read_text(encoding='utf-8', errors='replace').splitlines()
                     if re.search(r"""(?:src|href)=["']https?://|fetch\(\s*['"`]https?://|@import|url\(\s*['"]?https?://""", ln))
         for p in sorted((project / 'planner' / 'static').glob('*.html'))}
md.append('| Страницы программы: внешние файлы и запросы (`src=`/`href=` на другой сайт в разметке, `fetch` на другой сайт) | %s |'
          % ', '.join('%s — %d' % kv for kv in pages.items()))
text = '\n'.join(md) + '\n'
if out:
    out.write_text(text, encoding='utf-8')
print(text)
print('anchors not found: %d' % missing, file=sys.stderr)
