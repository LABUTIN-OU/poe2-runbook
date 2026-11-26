# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Sergei Labutin
# Additional terms under GPL-3.0 section 7: see NOTICE.md
"""Настройки программы на этом компьютере: файл settings.json в папке данных игрока.

Что в нём: gameDir — папка игры, которую программа нашла или которую указал игрок; window — размер и место окна
программы. Файл маленький, пишется целиком: сначала во временный файл, потом подменой — оборванная запись не
портит прежний.
"""
import json
import os
import threading
from pathlib import Path

_lock = threading.Lock()


def load(path):
    """Настройки из файла; нет файла или он не читается — пустые."""
    if not path:
        return {}
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def update(path, **values):
    """Записывает значения в файл настроек, остальное в нём оставляет как было. Без пути — ничего не делает."""
    if not path:
        return
    path = Path(path)
    with _lock:
        data = load(path)
        data.update(values)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + '.tmp')
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')
        os.replace(tmp, path)
