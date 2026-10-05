#!/usr/bin/python3
"""Install the app and desktop launcher without changing Snippet Search."""
import os
from pathlib import Path
import shutil

source = Path(__file__).resolve().parent
target = Path.home() / 'Softwares/SnipPop'
if target.exists() and not (target / '.snippop-install').exists():
    raise SystemExit('Destination exists and is not a managed SnipPop installation.')
target.mkdir(parents=True, exist_ok=True)
for name in ('core.py','desktop.py','snippop.py','editor.html','launch_snippop.sh','snippop.svg','README.md','COMPATIBILITY.md','LICENSE'):
    shutil.copy2(source / name, target / name)
shutil.copytree(source / 'tests', target / 'tests', dirs_exist_ok=True, ignore=shutil.ignore_patterns('__pycache__'))
(target / '.snippop-install').write_text('SnipPop 0.1\n')
os.chmod(target / 'launch_snippop.sh', 0o755)
apps = Path.home() / '.local/share/applications'
apps.mkdir(parents=True, exist_ok=True)
(apps / 'io.snippop.App.desktop').write_text(f'''[Desktop Entry]
Type=Application
Name=SnipPop
Comment=Find and paste snippets, rich content and logins
Exec="{target / 'launch_snippop.sh'}"
Icon={target / 'snippop.svg'}
Terminal=false
Categories=Utility;Office;
StartupNotify=true
StartupWMClass=snippop.py
''')
print('Installed:', target)
print('Desktop launcher:', apps / 'io.snippop.App.desktop')
