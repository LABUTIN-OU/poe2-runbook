@echo off
rem SPDX-License-Identifier: GPL-3.0-only
rem Copyright © 2026 Sergei Labutin
rem Additional terms under GPL-3.0 section 7: see NOTICE.md
rem Запускает страницу маршрута и открывает её в браузере. Закрыть: Ctrl+C или закрыть это окно.
chcp 65001 >nul
cd /d "%~dp0"
python -u planner\server.py --open
pause
