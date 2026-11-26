# -*- coding: utf-8 -*-
"""Add or remove ONE entry of .claude/launch.json — this session's own preview server; every other entry stays exactly
as it is. The file is shared by several sessions and they may pick the same names, so:
  add     refuses when an entry with that name is already there (it is somebody's — choose another name);
  remove  takes an entry away only if it is the one added here: the name AND the overlay folder in its arguments match.

    python -X utf8 launch_entry.py <launch.json> add <name> <serve.py> <site> <port> <overlay>
    python -X utf8 launch_entry.py <launch.json> remove <name> <overlay>"""
import json
import sys
from pathlib import Path

path, what, name = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
raw = path.read_bytes()
data = json.loads(raw.decode('utf-8'))
entries = data['configurations']
same = [c for c in entries if c.get('name') == name]
if what == 'add':
    serve, site, port, overlay = sys.argv[4], sys.argv[5], int(sys.argv[6]), sys.argv[7]
    if same:
        raise SystemExit('an entry named %r is already in %s (port %s) — not replaced; take another name' % (name, path, same[0].get('port')))
    entries.append({'name': name, 'runtimeExecutable': 'python',
                    'runtimeArgs': ['-X', 'utf8', '-u', serve, site, str(port), overlay], 'port': port})
elif what == 'remove':
    overlay = sys.argv[4]
    mine = [c for c in same if overlay in (c.get('runtimeArgs') or [])]
    if same and not mine:
        raise SystemExit('the entry %r in %s is not the one added here (another overlay folder) — left alone' % (name, path))
    data['configurations'] = [c for c in entries if c not in mine]
else:
    raise SystemExit('add or remove')
text = json.dumps(data, ensure_ascii=False, indent=2)
tail = b'\r\n' if raw.endswith(b'\r\n') else b'\n' if raw.endswith(b'\n') else b''
eol = b'\r\n' if b'\r\n' in raw else b'\n'
path.write_bytes(text.encode('utf-8').replace(b'\n', eol) + tail)
print('%s %s: %d entries -> %s (%d bytes)' % (what, name, len(data['configurations']), [c['name'] for c in data['configurations']],
                                              path.stat().st_size))
