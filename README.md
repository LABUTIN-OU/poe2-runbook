# PoE2 Runbook

PoE2 Runbook is a Windows program for playing Path of Exile 2 by a plan. A plan is the route of the campaign step by
step and the goals of a build on each step: skills and supports, gem levels, items and their affixes, bosses,
rewards, hero level. While you play, the program follows the game's own log: it sees the zone you are in, your level,
deaths, passive points and rewards, ticks off what is done and shows in red what is late. It compares an item you copy
in the game with the plan, shows the current step in a small window over the game and keeps the time of every step
for a review after the run. Plans are made and edited in the program itself. The interface speaks nine languages.

**Official site and downloads: <https://poe2.labutin.gg>**

© 2026 Sergei Labutin · [Русская версия](README.ru.md)

Designed and directed by the author; most of the code was written with an AI coding assistant (Claude by Anthropic).

## Official builds — only from the site and the releases

Official builds of PoE2 Runbook are published only at <https://poe2.labutin.gg>; the installer files themselves are
stored in the [releases of this repository](https://github.com/LABUTIN-OU/poe2-runbook/releases). A file from anywhere else is not an official build, even
if it carries the same name and icon. Versions that others build from this source must carry a name and an icon of their own (see
`NOTICE.md`). If you meet a build passed off as the official one, please report it in the
[issues of this repository](https://github.com/LABUTIN-OU/poe2-runbook/issues).

A version number such as `0.5.5.17` reads as "made for the game 0.5.5, build 17": a new version of the game comes with
a new version of the program, older ones are not updated.

## What the program reads

The game's log file (`Client.txt`), the game's settings file and item filter files, and the text of an item you copy
in the game with Ctrl+Alt+C — the clipboard is read only while the game window is in front, once per copy. On its
"Compare" key the program presses the game's own copy keys once, as you would. It does not read the game's memory or
the screen. Plans, runs and settings stay on your computer.

## Run from source

You need Windows 10 or 11 and [Python 3.12](https://www.python.org/downloads/) — the version official builds use.

1. Get the source: `git clone https://github.com/LABUTIN-OU/poe2-runbook.git`, or download it as a ZIP (Code → Download ZIP) and unpack it.
2. Optional: download the pictures of items and gems (see [Pictures](#pictures)).
3. Start the program in one of two ways.
   - **In its own window**, like the installed program:

         python -m pip install pywebview
         python planner/desktop.py

     The window needs the Microsoft Edge WebView2 Runtime (part of Windows 11; the program says so if it is
     missing). Plans, runs and settings go to `%APPDATA%\PoE2 Runbook` — the same folder the installed program uses.
   - **As a page in your browser**, with Python alone: double-click `start.cmd`, or run

         python -u planner/server.py --open

     In this mode the program keeps its data inside the source folder — `runs/`, `filters/`, `backup/`, `export/`
     (all four are in `.gitignore`) — and plan edits change the files in `plans/`.

The program finds the game by itself: Steam, the client from the game's site, or the running game. If it does not,
start the game. The window can also be told the game folder; the browser mode takes `--log <path to Client.txt>`.

## Pictures

Pictures of item bases, gems and unique items are art of Grinding Gear Games and are not in the repository. Download
them once:

    python -I catalog/fetch_icons.py

About 1,900 files, 15 MB, from the CDN of poe2db.tw into `planner/static/icons/`; files already there are kept,
`--dry` only says what is missing. Without the pictures the program works and their places stay empty.

## Tests

    python -X utf8 -m unittest discover -s planner
    python -X utf8 -m unittest discover -s catalog

A few tests need the raw game tables (`catalog/sources`, not in the repository) and are skipped without them.

## Build the installer

You need Python 3.12 and [Inno Setup 6](https://jrsoftware.org/isinfo.php). Download the pictures first (see
[Pictures](#pictures)): the installer takes what lies in `planner/static/icons`.

    python -m venv packaging\.venv
    packaging\.venv\Scripts\python -m pip install pyinstaller pywebview
    packaging\.venv\Scripts\python packaging\build.py

The program folder appears in `packaging\dist\PoE2Runbook`, the installer in `dist\`
(`PoE2Runbook-Setup-<version>.exe`). Before the installer is made, the built program starts once, hidden, on a test
log. Official builds use PyInstaller 6.22.3 and pywebview 6.2.1. A build of your own is not an official build: before
you share it, read `NOTICE.md` (another name and another icon).

## Game data in the repository

The built game data the program and its tests need are here: the catalogue `catalog/data/<version>`, the passive and
Atlas trees `planner/static/*.json` and the tree export `treedata/ggg`. They belong to Grinding Gear Games; each of
these folders has a README saying so. The raw game tables (`catalog/sources`) are not here: `catalog/dat_pack.py` and
`catalog/build.py` describe how to get them and how to rebuild the catalogue after a patch of the game.

## Licence

PoE2 Runbook is free software: you can redistribute it and/or modify it under the terms of the GNU General Public
License, version 3, as published by the Free Software Foundation, supplemented by the additional terms in `NOTICE.md`.
The text of the licence is in the file `LICENSE`. This program is distributed in the hope that it will be useful, but
WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

You may use the program for any purpose, study it, change it and share your own version. If you share a version of
your own, you must publish its source under the same licence; keep "Based on PoE2 Runbook by Sergei Labutin —
https://poe2.labutin.gg" in its "About" window and in its description; say that it is a modified version, and when
it was modified; give it another name and another icon.

## Path of Exile 2

This product isn't affiliated with or endorsed by Grinding Gear Games in any way.

Path of Exile 2 game data and images that come with the program belong to Grinding Gear Games. The licence above does
not cover them.

## Contributing and security

Contributions are welcome under the short contributor agreement in [CONTRIBUTING.md](CONTRIBUTING.md). A bug: open an
[issue](https://github.com/LABUTIN-OU/poe2-runbook/issues/new/choose) with the bug report form. A vulnerability:
[report it privately](https://github.com/LABUTIN-OU/poe2-runbook/security/advisories/new), see [SECURITY.md](SECURITY.md).
Contact: <games@labutin.gg>.
